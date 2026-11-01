"""Where recordings come from (WP31). One question per source: which files are there, and give me one.
A file is only listed once it is complete, so a recording that is still being uploaded is never read half-way."""
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from cortex_leads.connectors.google_auth import TokenSource
from cortex_leads.core.errors import CortexError

MEDIA_SUFFIXES = {".mp4", ".m4a", ".mp3", ".wav", ".mkv", ".webm", ".mov", ".ogg"}
LOCAL_SETTLE_S = 60  # a local file untouched for this long is finished
DRIVE_API = "https://www.googleapis.com/drive/v3"


@dataclass(frozen=True)
class RemoteFile:
    id: str
    name: str
    modified: datetime
    tags: dict = field(default_factory=dict)  # Drive custom properties: a file Cortex itself uploaded says so, and is not "discovered" again


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


class Source(Protocol):
    async def list_files(self, now: datetime) -> list[RemoteFile]: ...

    def fetch(self, f: RemoteFile) -> AsyncIterator[bytes]: ...


class LocalFolder:
    """A folder on the worker's disk. Meant for trying the sandbox out, not for a business."""

    def __init__(self, path: str) -> None:
        self.root = Path(path)

    async def list_files(self, now: datetime) -> list[RemoteFile]:
        out = []
        for p in sorted(self.root.iterdir()) if self.root.is_dir() else []:
            st = p.stat()
            mtime = datetime.fromtimestamp(st.st_mtime, tz=now.tzinfo)
            if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES and now - mtime >= timedelta(seconds=LOCAL_SETTLE_S):
                out.append(RemoteFile(p.name, p.name, mtime))
        return out

    async def fetch(self, f: RemoteFile) -> AsyncIterator[bytes]:
        path = (self.root / f.id).resolve()
        if path.parent != self.root.resolve():  # an id is a file name, never a path
            raise CortexError("lesson file outside the source folder")
        with path.open("rb") as fh:
            while chunk := fh.read(1 << 20):
                yield chunk


class DriveFolder:
    """A Drive folder, read with a person's Google sign-in (`auth`). `md5Checksum` only exists once an upload has finished, so asking for it is the "is this file complete" test."""

    def __init__(self, folder_id: str, auth: TokenSource, client: httpx.AsyncClient) -> None:
        self.folder_id, self._http = folder_id, client
        self._auth = auth.headers

    async def list_files(self, now: datetime) -> list[RemoteFile]:
        q = f"'{self.folder_id}' in parents and trashed = false and (mimeType contains 'video/' or mimeType contains 'audio/')"
        r = await self._http.get(f"{DRIVE_API}/files", headers=await self._auth(), params={
            "q": q, "orderBy": "createdTime desc", "pageSize": 100,
            "fields": "files(id,name,createdTime,md5Checksum,properties)"})
        r.raise_for_status()
        return [RemoteFile(f["id"], f["name"], datetime.fromisoformat(f["createdTime"]), f.get("properties") or {})
                for f in r.json().get("files", []) if f.get("md5Checksum")]

    async def fetch(self, f: RemoteFile) -> AsyncIterator[bytes]:
        async with self._http.stream("GET", f"{DRIVE_API}/files/{f.id}", headers=await self._auth(),
                                     params={"alt": "media"}) as r:
            r.raise_for_status()
            async for chunk in r.aiter_bytes(1 << 20):
                yield chunk
