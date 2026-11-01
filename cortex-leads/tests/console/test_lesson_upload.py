"""WP37: a recording is sent by the browser straight to the teacher's Drive folder (Cortex only opens the upload); the watcher is the one pipeline that summarises it."""
import asyncio
import json
import shutil
import struct
import subprocess
import wave
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from support import h, sign_in

from cortex_leads.config import get_settings
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.lessons import job, uploads
from cortex_leads.llm.gateway import LLMGateway
from cortex_leads.llm.providers import FakeProvider
from cortex_leads.llm.types import LLMResult
from cortex_leads.skills.loader import sync_dir
from cortex_leads.skills.profile import SANDBOXES_DIR
from cortex_leads.skills.registry import promote

TRANSCRIPT = "Hôm nay chúng ta học thì hiện tại hoàn thành. " * 8
RECAP = {"summary": "Lớp học thì hiện tại hoàn thành và làm bài luyện tập.", "topics": ["Thì hiện tại hoàn thành"],
         "homework": [{"task": "Bài 3 trang 45", "due": None}], "class_notes": ""}


def wav_bytes(tmp_path, seconds: float = 1.0) -> bytes:
    path = tmp_path / "in.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<h", 100) * int(8000 * seconds))
    return path.read_bytes()


ORIGIN = "https://cortex.example"


@pytest.fixture(autouse=True)
def public_address(monkeypatch):
    monkeypatch.setenv("CL_PUBLIC_BASE_URL", ORIGIN + "/app")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def as_(app_client, world, api_key_factory, role="staff"):
    _, key = await api_key_factory(world.t, role, "nv1" if role == "staff" else None)
    app_client.cookies.clear()
    return await sign_in(app_client, key)


@pytest.fixture
async def lab(world, seed):
    sb = await seed(m.Sandbox(tenant_id=world.t.id, name="lesson_recap", purpose="lesson_recap", profile_ref="lesson_recapper@1", domain_pack={},
                                budget={"runs_per_day": 100, "tokens_per_day": 100000}))
    async with tenant_session(world.t.id) as s:
        for row in await sync_dir(s, world.t.id, sb.id, SANDBOXES_DIR / "lesson_recap" / "skills"):
            await promote(s, sb.id, row.name, row.version, "shadow")
            await promote(s, sb.id, row.name, row.version, "live")
    return sb


async def ask(app_client, csrf, name="Lớp A1 - buổi 6.wav", size=1000, language="en", headers=None, **extra):
    return await app_client.post("/api/v1/lessons/upload/session", json={"name": name, "size": size, "language": language, **extra}, headers={**h(csrf), **(headers or {})})


class Bearer:
    async def headers(self):
        return {"Authorization": "Bearer t"}


def uploader_for(fc):
    from cortex_leads.connectors.drive_store import DriveUploader
    return lambda secret: DriveUploader(httpx.AsyncClient(transport=fc.transport()), Bearer(), base="https://x/drive/v3", upload_base="https://x/upload/drive/v3")


@pytest.fixture
async def account(world, seed):
    from cryptography.fernet import Fernet
    secret = json.dumps({"client_id": "c", "client_secret": "s", "refresh_token": "r"}).encode()
    return await seed(m.GoogleAccount(tenant_id=world.t.id, label="Cô Lan", scopes=["drive.file"], connected_by="staff:owner",
                                      secret_enc=Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(secret)))


@pytest.fixture
async def drive(world, lab, seed, account):
    """A class: a folder Cortex made in the teacher's Drive, read as the account."""
    return await seed(m.Class(tenant_id=world.t.id, recap_sandbox_id=lab.id, source_kind="drive", source_ref="watched1", name="Lớp A1", owned=True, drive_account_id=account.id, recap_mode="auto"))


@pytest.fixture
def fc(monkeypatch):
    from dev.local.fake_classroom import FakeClassroom
    fake = FakeClassroom()
    fake.folders["watched1"] = {"id": "watched1", "name": "Lớp A1", "trashed": False}  # the class's folder, made earlier
    monkeypatch.setattr("cortex_leads.console.lessons.open_uploader", uploader_for(fake))
    return fake


async def test_the_ticket_opens_an_upload_into_the_watched_folder_and_nothing_passes_through_cortex(app_client, world, api_key_factory, lab, drive, fc):
    csrf = await as_(app_client, world, api_key_factory)
    r = await ask(app_client, csrf, size=123456)
    assert r.status_code == 201
    (session,) = fc._sessions.values()
    body = r.json()
    assert body["name"] == "Lớp A1 - buổi 6.wav" and body["upload_url"].startswith("http://fake.drive/upload/session/") and body["chunk_bytes"] == 8 * 1024 * 1024
    assert session["meta"]["parents"] == ["watched1"] and session["meta"]["properties"] == {"cortex_language": "en"}  # fixed here, not by the browser
    assert session["total"] == 123456 and session["origin"] == ORIGIN  # Google is told the one page that will send the bytes, from settings
    assert not fc.uploaded and list(fc.folders) == ["watched1"]  # no byte has been sent and no new folder was made
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(select(m.Lesson))).first() is None  # the watcher alone makes lessons: one pipeline
    trail = str((await app_client.get("/api/v1/audit")).json()["items"])
    assert "Bắt đầu tải lên bản ghi" in trail and body["upload_url"] not in trail  # the ticket itself is never written down


@pytest.mark.parametrize("name,size,status,code", [("ghi.exe", 10, 415, "BAD_TYPE"), ("ghi.txt", 10, 415, "BAD_TYPE"), ("ghi.wav", 0, 422, "EMPTY")])
async def test_what_cannot_be_a_recording_gets_no_ticket(app_client, world, api_key_factory, lab, drive, fc, name, size, status, code):
    r = await ask(app_client, await as_(app_client, world, api_key_factory), name=name, size=size)
    assert r.status_code == status and r.json()["detail"]["code"] == code and not fc._sessions


async def test_a_size_over_the_limit_or_an_unknown_language_gets_no_ticket(app_client, world, api_key_factory, lab, drive, fc, monkeypatch):
    monkeypatch.setattr(uploads, "max_bytes", lambda: 1000)
    csrf = await as_(app_client, world, api_key_factory)
    r = await ask(app_client, csrf, size=1001)
    assert r.status_code == 413 and r.json()["detail"]["code"] == "TOO_LARGE"
    assert (await ask(app_client, csrf, size=10, language="klingon")).status_code == 422 and not fc._sessions


async def test_a_page_that_is_not_the_console_gets_no_ticket_and_an_unset_address_uses_the_one_asked(app_client, world, api_key_factory, lab, drive, fc, monkeypatch):
    csrf = await as_(app_client, world, api_key_factory)
    r = await ask(app_client, csrf, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "BAD_ORIGIN"
    assert (await ask(app_client, csrf, headers={"Origin": ORIGIN})).status_code == 201
    monkeypatch.setenv("CL_PUBLIC_BASE_URL", "")  # unset (and a developer's own .env must not fill it in)
    get_settings.cache_clear()
    assert (await ask(app_client, csrf)).status_code == 201  # running locally: the address the console was opened at
    assert [x["origin"] for x in fc._sessions.values()][-1] == "http://test"


async def test_it_needs_a_running_sandbox_with_its_skill_and_a_connected_drive(app_client, world, api_key_factory, lab, fc):
    csrf = await as_(app_client, world, api_key_factory)
    r = await ask(app_client, csrf)  # no drive connected yet
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NO_CLASS"
    assert (await app_client.get("/api/v1/lessons")).json()["can_upload"] is False
    async with tenant_session(world.t.id) as s:
        for v in (await s.execute(select(m.SkillVersion))).scalars():
            v.status = "retired"
    assert (await ask(app_client, csrf)).json()["detail"]["code"] == "NO_SKILL"


async def test_without_a_lesson_sandbox_there_is_no_upload(app_client, world, api_key_factory):
    r = await ask(app_client, await as_(app_client, world, api_key_factory))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NO_SANDBOX"
    assert (await app_client.get("/api/v1/lessons")).json()["can_upload"] is False


async def test_a_class_that_is_not_this_sandboxes_or_is_switched_off_gets_no_ticket(app_client, world, api_key_factory, lab, drive, fc):
    from uuid import uuid4
    csrf = await as_(app_client, world, api_key_factory)
    r = await ask(app_client, csrf, class_id=str(uuid4()))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "BAD_CLASS"
    async with tenant_session(world.t.id) as s:
        (await s.get(m.Class, drive.id)).active = False
    assert (await ask(app_client, csrf, class_id=str(drive.id))).status_code == 409 and not fc._sessions


@pytest.mark.parametrize("refusal,status,code", [("storage", 507, "DRIVE_STORAGE_FULL"), ("scope", 502, "DRIVE_PERMISSION_DENIED"), ("auth", 502, "DRIVE_UNAUTHENTICATED")])
async def test_when_drive_refuses_the_ticket_says_why(app_client, world, api_key_factory, lab, drive, fc, refusal, status, code):
    fc.drive_refuses = refusal
    r = await ask(app_client, await as_(app_client, world, api_key_factory))
    assert r.status_code == status and r.json()["detail"]["code"] == code and r.json()["detail"]["message"]


async def test_one_person_and_one_business_can_only_start_so_many_a_day(app_client, world, api_key_factory, lab, drive, fc, monkeypatch):
    monkeypatch.setenv("CL_UPLOAD_PER_USER_DAY", "2")
    get_settings.cache_clear()
    csrf = await as_(app_client, world, api_key_factory)
    assert [(await ask(app_client, csrf)).status_code for _ in range(3)] == [201, 201, 429]
    assert len(fc._sessions) == 2  # the refused one never reached Google
    monkeypatch.setenv("CL_UPLOAD_PER_USER_DAY", "50")
    monkeypatch.setenv("CL_UPLOAD_PER_TENANT_DAY", "2")
    get_settings.cache_clear()
    r = await ask(app_client, csrf)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "TOO_MANY"


async def test_a_class_folder_deleted_in_drive_is_made_again_and_stays_the_class(app_client, world, api_key_factory, lab, drive, fc):
    csrf = await as_(app_client, world, api_key_factory)
    fc.folders["watched1"]["trashed"] = True  # the teacher threw the folder away
    for _ in range(2):
        assert (await ask(app_client, csrf)).status_code == 201
    assert len(fc.folders) == 2 and len(fc._sessions) == 2  # made again once, then found again
    async with tenant_session(world.t.id) as s:
        row = await s.get(m.Class, drive.id)
        assert row.source_ref != "watched1" and row.source_ref in fc.folders and row.name == "Lớp A1"


# --- the one pipeline: whatever lands in the watched folder is found, summarised and played from there -----------------
class Speech:
    def __init__(self):
        self.languages = []

    async def transcribe(self, audio, language=None):
        self.languages.append(language)
        return TRANSCRIPT


@pytest.fixture
async def watched(world, lab, seed, account):
    return await seed(m.Class(tenant_id=world.t.id, recap_sandbox_id=lab.id, source_kind="drive", source_ref="watched1", drive_account_id=account.id, name="watched1", listed=False, recap_mode="auto"))


class Listing:
    def __init__(self, files, data=b""):
        self.files, self.data = files, data

    async def list_files(self, now):
        return self.files

    async def fetch(self, f):
        yield self.data


def test_the_language_told_to_the_speech_model():
    get_settings.cache_clear()
    assert job.spoken_language("en") == "en" and job.spoken_language("vi") == "vi"
    assert job.spoken_language("auto") is None  # let the model recognise it
    assert job.spoken_language(None) == "vi"  # lessons from a folder: the settings' default


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_the_watcher_finds_an_uploaded_file_takes_its_language_and_summarises_it_once(app_client, world, api_key_factory, lab, watched, tmp_path):
    from cortex_leads.connectors.lesson_sources import RemoteFile
    from cortex_leads.skills.registry import live_skills_for
    later = datetime(2030, 1, 1, tzinfo=UTC)
    files = [RemoteFile("up1", "Lớp A1.wav", later, {"cortex_language": "en"}), RemoteFile("up2", "tay.wav", later, {"cortex_language": "klingon"}), RemoteFile("up3", "thả.wav", later)]
    source, speech = Listing(files, wav_bytes(tmp_path, 2)), Speech()
    now = datetime(2030, 2, 1, tzinfo=UTC)
    async with tenant_session(world.t.id) as s:
        sandbox = await s.get(m.Sandbox, lab.id)
        assert await job.discover(s, sandbox, watched, source, now) == 3
        assert await job.discover(s, sandbox, watched, source, now) == 0  # the same files again: nothing new
        skill = (await live_skills_for(s, lab.id, job.EVENT))[0]
        langs = {r.name: r.language for r in (await s.execute(select(m.Lesson))).scalars()}
    assert langs == {"Lớp A1.wav": "en", "tay.wav": None, "thả.wav": None}  # a made-up language is ignored, not trusted
    async with tenant_session(world.t.id) as s:
        jobs = await job.claim(s, sandbox, now)
    gateway = LLMGateway(FakeProvider([LLMResult(content=json.dumps(RECAP, ensure_ascii=False), tokens_in=10, tokens_out=10, model="f")] * 3))
    first = next(j for j in jobs if j.name == "Lớp A1.wav")
    assert await job.process(world.t.id, lab.id, first, source, speech, gateway, now, skill)
    assert speech.languages == ["en"]


async def test_a_recording_in_the_drive_plays_with_ranges_through_cortex_and_only_for_its_business(app_client, world, api_key_factory, lab, watched, fc, monkeypatch, seed, tenant_factory, tmp_path):
    data = wav_bytes(tmp_path, 2)
    fc.files["fileA"] = {"mimeType": "audio/wav", "bytes": data}
    lesson = await seed(m.Lesson(tenant_id=world.t.id, sandbox_id=lab.id, class_id=watched.id, file_id="fileA", name="Lớp A1.wav", status="done"))
    monkeypatch.setattr("cortex_leads.console.lessons.open_uploader", uploader_for(fc))
    pass  # the account fixture holds a real encrypted sign-in
    await as_(app_client, world, api_key_factory)
    url = f"/api/v1/lessons/{lesson.id}/media"
    full = await app_client.get(url)
    assert full.status_code == 200 and full.content == data and full.headers["content-type"] == "audio/wav" and "no-store" in full.headers["cache-control"]
    part = await app_client.get(url, headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == data[100:200] and part.headers["content-range"] == f"bytes 100-199/{len(data)}"
    assert (await app_client.get(url, headers={"Range": "bytes=999999999-"})).status_code == 416
    assert "authorization" not in {k.lower() for k in full.headers}  # no credential reaches the browser
    item = next(i for i in (await app_client.get("/api/v1/lessons")).json()["items"] if i["id"] == str(lesson.id))
    assert item["storage"] == "drive" and item["has_media"] is True and item["media_type"] == "audio"
    other = await tenant_factory("Khác")
    await as_(app_client, type("W", (), {"t": other})(), api_key_factory)
    assert (await app_client.get(url)).status_code == 404
    app_client.cookies.clear()
    assert (await app_client.get(url)).status_code in (401, 403)


async def test_a_file_gone_from_the_drive_is_said_so(app_client, world, api_key_factory, lab, watched, fc, monkeypatch, seed):
    lesson = await seed(m.Lesson(tenant_id=world.t.id, sandbox_id=lab.id, class_id=watched.id, file_id="nope", name="x.wav", status="done"))
    monkeypatch.setattr("cortex_leads.console.lessons.open_uploader", uploader_for(fc))
    pass  # the account fixture holds a real encrypted sign-in
    await as_(app_client, world, api_key_factory)
    r = await app_client.get(f"/api/v1/lessons/{lesson.id}/media")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "NOT_FOUND"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
@pytest.mark.parametrize("body,code", [(b"this is plain text pretending to be sound", "NOT_MEDIA")])
async def test_the_watcher_refuses_what_the_browser_sent_but_is_not_a_recording(app_client, world, api_key_factory, lab, watched, body, code):
    from cortex_leads.connectors.lesson_sources import RemoteFile
    from cortex_leads.skills.registry import live_skills_for
    now = datetime(2030, 2, 1, tzinfo=UTC)
    source = Listing([RemoteFile("bad", "fake.wav", datetime(2030, 1, 1, tzinfo=UTC))], body)
    async with tenant_session(world.t.id) as s:
        sandbox = await s.get(m.Sandbox, lab.id)
        await job.discover(s, sandbox, watched, source, now)
        skill = (await live_skills_for(s, lab.id, job.EVENT))[0]
    async with tenant_session(world.t.id) as s:
        (lesson,) = await job.claim(s, sandbox, now)
    speech = Speech()
    assert not await job.process(world.t.id, lab.id, lesson, source, speech, LLMGateway(FakeProvider([])), now, skill) and not speech.languages
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(select(m.Lesson.error))).scalar_one() == code  # said in words on the page, no transcription was paid for


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_the_watcher_refuses_a_video_without_sound(app_client, world, api_key_factory, lab, watched, tmp_path):
    from cortex_leads.connectors.lesson_sources import RemoteFile
    from cortex_leads.skills.registry import live_skills_for
    mp4 = tmp_path / "mute.mp4"
    await asyncio.to_thread(subprocess.run, ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1", "-c:v", "libx264", str(mp4)], check=True)
    now = datetime(2030, 2, 1, tzinfo=UTC)
    source = Listing([RemoteFile("mute", "cam.mp4", datetime(2030, 1, 1, tzinfo=UTC))], mp4.read_bytes())
    async with tenant_session(world.t.id) as s:
        sandbox = await s.get(m.Sandbox, lab.id)
        await job.discover(s, sandbox, watched, source, now)
        skill = (await live_skills_for(s, lab.id, job.EVENT))[0]
    async with tenant_session(world.t.id) as s:
        (lesson,) = await job.claim(s, sandbox, now)
    assert not await job.process(world.t.id, lab.id, lesson, source, Speech(), LLMGateway(FakeProvider([])), now, skill)
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(select(m.Lesson.error))).scalar_one() == "NO_AUDIO"


async def test_deleting_a_recording_bins_the_drive_file_and_drops_the_lesson(app_client, world, api_key_factory, lab, drive, fc):
    fc.uploaded["file9"] = {"name": "buổi 6.wav", "parents": ["watched1"], "bytes": bytearray(b"x"), "mime": "audio/wav"}
    async with tenant_session(world.t.id) as s:
        lesson = m.Lesson(tenant_id=world.t.id, sandbox_id=lab.id, class_id=drive.id, file_id="file9", name="buổi 6.wav", status="done")
        s.add(lesson)
        await s.flush()
        lid = lesson.id
    csrf = await as_(app_client, world, api_key_factory)
    r = await app_client.delete(f"/api/v1/lessons/{lid}", headers=h(csrf))
    assert r.status_code == 200 and "file9" in fc.trashed
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(select(m.Lesson))).first() is None


async def test_a_recording_in_a_read_only_folder_is_not_deleted_from_here(app_client, world, api_key_factory, lab, drive, fc):
    async with tenant_session(world.t.id) as s:
        (await s.get(m.Class, drive.id)).owned = False
        lesson = m.Lesson(tenant_id=world.t.id, sandbox_id=lab.id, class_id=drive.id, file_id="file9", name="meet.mp4", status="done")
        s.add(lesson)
        await s.flush()
        lid = lesson.id
    r = await app_client.delete(f"/api/v1/lessons/{lid}", headers=h(await as_(app_client, world, api_key_factory)))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "READ_ONLY" and not fc.trashed


async def test_a_console_opened_as_localhost_is_the_same_page_as_127_0_0_1_and_nothing_else_is(app_client, world, api_key_factory, lab, drive, fc, monkeypatch):
    monkeypatch.setenv("CL_PUBLIC_BASE_URL", "http://127.0.0.1:8200")
    get_settings.cache_clear()
    csrf = await as_(app_client, world, api_key_factory)
    assert (await ask(app_client, csrf, headers={"Origin": "http://localhost:8200"})).status_code == 201
    assert list(fc._sessions.values())[-1]["origin"] == "http://localhost:8200"  # Google lets exactly the spelling the browser used
    for evil in ("http://localhost:9999", "https://localhost:8200", "http://evil.example:8200"):
        r = await ask(app_client, csrf, headers={"Origin": evil})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "BAD_ORIGIN", evil
