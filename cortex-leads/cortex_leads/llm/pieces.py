"""Read a text too long for one answer, a piece at a time (WP32). A piece the model cannot answer is cut in half and each
half asked on its own; what each piece yielded is kept in `saved` (keyed by the piece's text), so a second try after a
failure at piece 5 of 6 starts at piece 5."""
import hashlib
import re
from collections.abc import Callable
from typing import Any

from cortex_leads.core.context import RunContext
from cortex_leads.db import models as m
from cortex_leads.llm.ask import AskFailed, ask_json
from cortex_leads.llm.gateway import LLMGateway

MIN_PIECE = 1_500  # below this a failing piece is not cut again: the trouble is not its length


def split_text(text: str, size: int) -> list[str]:
    """Pieces of about `size` characters, cut after a sentence end so that no sentence is split."""
    out, cur = [], ""
    for sentence in re.split(r"(?<=[.!?…])\s+", text):
        if cur and len(cur) + len(sentence) > size:
            out.append(cur)
            cur = ""
        cur += sentence + " "
    return [*out, cur] if cur.strip() else out


def halve(piece: str) -> list[str]:
    """Two pieces cut at the sentence end nearest the middle; one piece if there is no sentence end to cut at."""
    sentences = re.split(r"(?<=[.!?…])\s+", piece)
    if len(sentences) < 2:
        return [piece]
    best, run_len, cut = len(piece), 0, 1
    for i, sentence in enumerate(sentences[:-1], 1):
        run_len += len(sentence) + 1
        if abs(run_len - len(piece) / 2) < best:
            best, cut = abs(run_len - len(piece) / 2), i
    return [" ".join(sentences[:cut]), " ".join(sentences[cut:])]


def key_of(piece: str) -> str:
    return hashlib.sha1(piece.encode(), usedforsecurity=False).hexdigest()[:16]


async def read_in_pieces(gateway: LLMGateway, ctx: RunContext, run: m.TriggerRun, text: str, *, system: str,
                         chunk_chars: int, prompt: Callable[[int, int, str], str], shape: dict[str, Any],
                         note: str | None, timeout_s: float, tries: int, saved: dict[str, list[str]]) -> list[str]:
    """The `notes` of every piece, in order. `prompt(i, n, piece)` words the request for piece i of n. `saved` is read first and
    filled as pieces succeed, also when a later one fails (the caller keeps it)."""
    async def one(piece: str, i: int, n: int) -> list[str]:
        key = key_of(piece)
        if key in saved:
            return saved[key]
        try:
            got = await ask_json(gateway, ctx, run, system, prompt(i, n, piece), shape=shape, note=note,
                                 timeout_s=timeout_s, tries=tries)
        except AskFailed:
            if len(piece) < 2 * MIN_PIECE:
                raise
            halves = halve(piece)
            if len(halves) < 2:
                raise
            notes = [n_ for h in halves for n_ in await one(h, i, n)]
            saved[key] = notes
            return notes
        notes = [x for x in got.get("notes", []) if isinstance(x, str)]
        saved[key] = notes
        return notes

    pieces = split_text(text, chunk_chars)
    return [n_ for i, p in enumerate(pieces, 1) for n_ in await one(p, i, len(pieces))]
