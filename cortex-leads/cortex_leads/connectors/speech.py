"""Speech -> text. `api` sends the audio to a Whisper endpoint (it leaves this machine: only for recordings you
may share, DESIGN §6); `local` runs faster-whisper here and sends nothing anywhere."""
import asyncio
from pathlib import Path
from typing import Protocol

import httpx

from cortex_leads.config import Settings
from cortex_leads.core.errors import CortexError


class Transcriber(Protocol):
    async def transcribe(self, audio: Path, language: str | None = None) -> str: ...  # None: let the model recognise the language


class WhisperApi:
    def __init__(self, base_url: str, api_key: str, model: str, client: httpx.AsyncClient) -> None:
        self.url, self.key, self.model, self._http = base_url.rstrip("/") + "/audio/transcriptions", api_key, model, client

    async def transcribe(self, audio: Path, language: str | None = None) -> str:
        r = await self._http.post(self.url, headers={"Authorization": f"Bearer {self.key}"}, timeout=300,
                                  data={"model": self.model, "response_format": "json", **({"language": language} if language else {})},
                                  files={"file": (audio.name, audio.read_bytes(), "audio/ogg")})
        r.raise_for_status()
        return r.json()["text"].strip()


class LocalWhisper:
    def __init__(self, model_size: str) -> None:
        self.size, self._model = model_size, None

    def _run(self, audio: Path, language: str | None) -> str:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise CortexError("CL_TRANSCRIBER=local needs `pip install faster-whisper`") from e
            self._model = WhisperModel(self.size, compute_type="int8")
        segments, _ = self._model.transcribe(str(audio), language=language)  # a language forced onto speech in another one comes out as nonsense
        return " ".join(s.text.strip() for s in segments)

    async def transcribe(self, audio: Path, language: str | None = None) -> str:
        return await asyncio.to_thread(self._run, audio, language)


def make_transcriber(s: Settings, client: httpx.AsyncClient) -> Transcriber:
    if s.TRANSCRIBER == "api":
        if not s.WHISPER_API_KEY:
            raise CortexError("CL_TRANSCRIBER=api needs CL_WHISPER_API_KEY")
        return WhisperApi(s.WHISPER_BASE_URL, s.WHISPER_API_KEY, s.WHISPER_MODEL, client)
    if s.TRANSCRIBER == "local":
        return LocalWhisper(s.WHISPER_LOCAL_MODEL)
    raise CortexError(f"CL_TRANSCRIBER must be 'local' or 'api', got {s.TRANSCRIBER!r}")


def open_transcriber() -> Transcriber:
    """The transcriber the settings name; the HTTP client for the API kind is made here so no other package imports a network library."""
    from cortex_leads.config import get_settings

    return make_transcriber(get_settings(), httpx.AsyncClient())
