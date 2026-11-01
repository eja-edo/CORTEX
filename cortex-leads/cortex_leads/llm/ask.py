"""Ask the model for one JSON object and get back something checked (WP32). The single place that knows a model drops a
bracket in long JSON, answers with the wrong keys, or goes quiet: it asks again (naming what was wrong), counts every token
into the run, and says why it gave up as a short code, never as the model's own text."""
import base64
from typing import Any

from pydantic import BaseModel, ValidationError

from cortex_leads.core.context import RunContext
from cortex_leads.db import models as m
from cortex_leads.llm.gateway import LLMGateway
from cortex_leads.llm.shape import parse_json_object, response_shape
from cortex_leads.llm.types import LLMError, ShapeError

BAD_SHAPE, LLM_ERROR = "BAD_SHAPE", "LLM_ERROR"


def _content(pictures: list[dict[str, Any]], text: str) -> str | list[dict[str, Any]]:
    return [*pictures, {"type": "text", "text": text}] if pictures else text


class AskFailed(Exception):
    """`code`: LLM_ERROR (no usable answer from the gateway) or BAD_SHAPE (answers, but never the shape asked for)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def ask_json[T: BaseModel](gateway: LLMGateway, ctx: RunContext, run: m.TriggerRun, system: str, user: str, *,
                   shape: dict[str, Any], timeout_s: float, tries: int = 2, note: str | None = None,
                   model: type[T] | None = None, images: list[tuple[str, bytes]] | None = None) -> dict[str, Any] | T:
    """`user` is the request; the closing line that draws `shape` is added here (the last line of a prompt decides the JSON).
    With `model` the answer must also validate against it, and a failure there is asked again like broken JSON is.
    `images`: (mime type, bytes) shown to the model before the text, so the closing line is still the last thing it reads."""
    hint = ""
    pictures = [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(raw).decode()}"}} for mime, raw in images or []]
    for attempt in range(tries):
        res = None
        try:
            res = await gateway.complete(
                ctx, [{"role": "system", "content": system},
                      {"role": "user", "content": _content(pictures, user + hint + "\n\n" + response_shape(shape, note))}], timeout_s=timeout_s)
        except LLMError:
            if attempt == tries - 1:
                run.status = "error"
                raise AskFailed(LLM_ERROR) from None
            continue
        run.tokens_in += res.tokens_in
        run.tokens_out += res.tokens_out
        run.model = res.model
        try:
            data = parse_json_object(res.content)
            return model(**data) if model else data
        except (ShapeError, ValidationError, TypeError) as e:
            hint = f"\n\nLần trước câu trả lời không đúng hình dạng ({type(e).__name__}). Chỉ trả đúng một JSON object."
    run.status, run.blocked_codes = "blocked", [BAD_SHAPE]
    raise AskFailed(BAD_SHAPE)
