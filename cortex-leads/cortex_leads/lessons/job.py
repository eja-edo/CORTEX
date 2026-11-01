"""The lesson_recap sandbox's loop (WP31): find new recordings, turn each into a recap, tell the team.
Three short database turns around the slow part (download + speech to text), so no transaction stays open for
minutes. A crash mid-way leaves a `working` row that is released after CLAIM_TTL and tried again."""
import json
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.config import get_settings
from cortex_leads.connectors.drive_store import DriveError
from cortex_leads.connectors.google_accounts import secret_of_account
from cortex_leads.connectors.google_auth import RefreshToken
from cortex_leads.connectors.lesson_sources import (
    DriveFolder,
    LocalFolder,
    RemoteFile,
    Source,
    new_client,
)
from cortex_leads.connectors.speech import Transcriber, make_transcriber
from cortex_leads.core.errors import CortexError
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import list_active_tenants, system_session, tenant_session
from cortex_leads.lessons.recap import RecapFailed, make_recap
from cortex_leads.llm.gateway import LLMGateway
from cortex_leads.media.audio import split_audio
from cortex_leads.notify import service as notify
from cortex_leads.sandbox.policy import check_budget
from cortex_leads.skills.registry import LoadedSkill, live_skills_for
from cortex_leads.work import queue

Client = Any  # an httpx.AsyncClient; the network library stays in connectors/ (A9 guard)
log = logging.getLogger(__name__)
PER_PASS = 2  # recordings processed per pass and sandbox: a long lesson is minutes of work
MAX_ATTEMPTS = queue.MAX_ATTEMPTS
CLAIM_TTL = queue.CLAIM_TTL
PURPOSE = "lesson_recap"
EVENT = "lesson.recorded"


def open_source(src: m.Class, client: Client) -> Source:
    if src.source_kind == "local":
        return LocalFolder(src.source_ref)
    data = json.loads(secret_of_account(src.drive_account, DriveError("UNAUTHENTICATED")))
    return DriveFolder(src.source_ref, RefreshToken(data["client_id"], data["client_secret"], data["refresh_token"], client), client)


async def discover(session: AsyncSession, sandbox: m.Sandbox, src: m.Class, source: Source,
                   now: datetime) -> int:
    """Queue files that appeared after the source was connected. Idempotent on (sandbox, file)."""
    n = 0
    for f in await source.list_files(now):
        if f.modified < src.created_at:
            continue
        language = f.tags.get("cortex_language")  # a recording uploaded in the console carries the language its uploader chose
        got = await session.execute(insert(m.Lesson).values(
            id=uuid7(), tenant_id=sandbox.tenant_id, sandbox_id=sandbox.id, class_id=src.id, file_id=f.id,
            name=f.name, language=language if language in ("vi", "en", "auto") else None, created_at=now).on_conflict_do_nothing().returning(m.Lesson.id))
        n += got.scalar() is not None
    return n


@dataclass(frozen=True)
class Job:
    id: object
    class_id: object
    file_id: str
    name: str
    transcript: str | None  # kept from an earlier try: speech to text is the slow, costly part
    notes: dict | None  # likewise what each piece of it yielded
    language: str | None  # what the person who uploaded it said it is in: vi, en, auto; None = the settings' default
    token: datetime  # when this worker took the job: only the holder of the latest may write its result


async def claim(session: AsyncSession, sandbox: m.Sandbox, now: datetime, active_classes: list | None = None) -> list[Job]:
    """`active_classes`: only lessons of these classes are taken, so a class that is switched off keeps its queued files waiting instead of failing them."""
    where = [m.Lesson.sandbox_id == sandbox.id] + ([m.Lesson.class_id.in_(active_classes)] if active_classes is not None else [])
    rows = await queue.claim(session, m.Lesson, where, now, limit=PER_PASS, ttl=CLAIM_TTL)
    return [Job(r.id, r.class_id, r.file_id, r.name, r.transcript, r.notes, r.language, now) for r in rows]


def spoken_language(chosen: str | None) -> str | None:
    """What to tell the speech model: the uploader's choice ("auto" = let it recognise), else the settings' default (Vietnamese)."""
    return None if chosen == "auto" else (chosen or get_settings().WHISPER_LANGUAGE or None)


class NotRecording(Exception):
    """The file in the folder is not sound or video we can read; `.code` is what the page says."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def to_text(source: Source, f: RemoteFile, transcriber: Transcriber, language: str | None = None) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "recording"
        with raw.open("wb") as out:
            async for chunk in source.fetch(f):
                out.write(chunk)
        parts_dir = Path(tmp) / "parts"
        parts_dir.mkdir()
        try:  # the bytes may have come straight from a browser to the Drive, so this is the first place anything has looked at them
            parts = await split_audio(raw, parts_dir)
        except CortexError as e:
            raise NotRecording("NO_AUDIO" if ("no sound track" in str(e) or "does not contain any stream" in str(e)) else "NOT_MEDIA") from None
        return "\n".join([await transcriber.transcribe(p, language=spoken_language(language)) for p in parts])


def release(row: m.Lesson, by: str, now: datetime) -> None:
    """Lets a finished recap go out: the team's Mezon channel (the `notify` worker) and the Classroom course (`lessons.post`) both wait for this."""
    row.released_at, row.released_by = now, by


async def _fail(tenant_id, job: Job, code: str, now: datetime) -> None:
    async with tenant_session(tenant_id) as s:
        if (row := await queue.mine(s, m.Lesson, job.id, job.token)) is not None:
            queue.fail(row, code, now, max_attempts=MAX_ATTEMPTS)


async def process(tenant_id, sandbox_id, lesson: Job, source: Source, transcriber: Transcriber,
                  gateway: LLMGateway, now: datetime, skill: LoadedSkill) -> bool:
    f = RemoteFile(lesson.file_id, lesson.name, now)
    try:
        text = lesson.transcript or await to_text(source, f, transcriber, lesson.language)
    except NotRecording as e:
        await _fail(tenant_id, lesson, e.code, now)
        return False
    except Exception as e:  # a bad file or a down endpoint costs this lesson a try, not the pass
        log.exception("lesson %s: could not transcribe", lesson.id)
        await _fail(tenant_id, lesson, f"TRANSCRIBE_{type(e).__name__}"[:80], now)
        return False
    if len(text.split()) < 30:
        await _fail(tenant_id, lesson, "TOO_SHORT", now)
        return False
    saved = dict(lesson.notes or {})
    async with tenant_session(tenant_id) as s:
        sandbox = await s.get(m.Sandbox, sandbox_id)
        row = await queue.mine(s, m.Lesson, lesson.id, lesson.token)
        if row is None:
            log.warning("lesson %s was taken over by another worker: result dropped", lesson.id)
            return False
        row.transcript = text
        if await check_budget(s, sandbox, "tokens", now) or await check_budget(s, sandbox, "runs", now):
            queue.release(row)  # over budget: wait, don't burn a try
            return False
        try:
            async with s.begin_nested():
                row.recap = await make_recap(s, sandbox, skill, row.name, text, gateway, now, saved)
        except RecapFailed as e:
            row.notes = saved or None  # the pieces already read survive the failure; the next try starts after them
            queue.fail(row, e.code, now, max_attempts=MAX_ATTEMPTS)
            return False
        row.status, row.error, row.finished_at = "done", None, now
        row.notes = saved or None
        cls = await s.get(m.Class, row.class_id)
        if cls is not None and cls.recap_mode == "auto":  # review: the recap waits for a person (console: release_lesson)
            release(row, "auto", now)
            await notify.enqueue(s, tenant_id, "lesson", row.id, now)
    return True


async def lessons_once(now: datetime, gateway: LLMGateway, *, transcriber: Transcriber | None = None,
                       client: Client | None = None) -> int:
    """Returns how many recaps were made."""
    own = client is None
    client = client or new_client()
    made = 0
    try:
        transcriber = transcriber or make_transcriber(get_settings(), client)
        async with system_session() as sys_s:
            tenants = await list_active_tenants(sys_s)
        for tid in tenants:
            try:
                made += await _tenant_pass(tid, now, gateway, transcriber, client)
            except Exception:
                log.exception("lesson pass failed for a tenant")
    finally:
        if own:
            await client.aclose()
    return made


async def _tenant_pass(tid, now: datetime, gateway: LLMGateway, transcriber: Transcriber,
                       client: Client) -> int:
    made = 0
    async with tenant_session(tid) as s:
        sandboxes = list((await s.execute(select(m.Sandbox).where(
            m.Sandbox.status == "active", m.Sandbox.purpose == PURPOSE))).scalars())
        sources = list((await s.execute(select(m.Class).where(
            m.Class.active.is_(True), m.Class.recap_sandbox_id.is_not(None), m.Class.source_kind.in_(("local", "drive"))))).scalars())  # `upload` sources are from before WP37: nothing to watch there
        sources = [x for x in sources if x.source_kind == "local" or (x.drive_account is not None and x.drive_account.status == "active")]  # a class whose Google account was deleted or cut off waits to be linked again
    for sb in sandboxes:
        async with tenant_session(tid) as s:
            skills = await live_skills_for(s, sb.id, EVENT)
        if not skills:  # no live skill = nobody told the agent what to do: do nothing, like any sandbox without skills
            log.warning("sandbox %s has no live skill for %s: nothing to do", sb.id, EVENT)
            continue
        opened: dict[object, Source] = {}
        for src in (x for x in sources if x.recap_sandbox_id == sb.id):
            try:
                opened[src.id] = open_source(src, client)
                async with tenant_session(tid) as s:
                    await discover(s, sb, src, opened[src.id], now)
            except Exception:
                log.exception("lesson source %s: could not list", src.id)
        async with tenant_session(tid) as s:
            jobs = await claim(s, sb, now, [x.id for x in sources])
        for lesson in jobs:
            source = opened.get(lesson.class_id)
            if source is None:
                await _fail(tid, lesson, "SOURCE_UNAVAILABLE", now)
                continue
            made += await process(tid, sb.id, lesson, source, transcriber, gateway, now, skills[0])
    return made
