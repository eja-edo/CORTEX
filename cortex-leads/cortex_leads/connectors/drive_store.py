"""Putting a recording into a teacher's own Google Drive (WP36). The scope is `drive.file`: Cortex can touch only the files and the folder it
created itself, never the rest of that Drive. The file belongs to the teacher; Cortex keeps its own copy only until the words are out of
it. Uploads are resumable and sent in chunks, so a recording of hundreds of megabytes never has to fit in one request or in memory."""
import json
import re
from pathlib import Path
from typing import Any

import httpx

from cortex_leads.config import get_settings
from cortex_leads.connectors.google_auth import RefreshToken, TokenSource
from cortex_leads.core.errors import CortexError

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_MIME = "application/vnd.google-apps.folder"
FOLDER_NAME = "Cortex – bản ghi buổi học"
CHUNK = 8 * 1024 * 1024  # a multiple of 256 KiB, as Google requires for every chunk but the last
ERRORS = {400: "INVALID_ARGUMENT", 401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND", 429: "RATE_LIMITED"}


class DriveError(CortexError):
    """`.code`: UNAUTHENTICATED (the stored sign-in expired or was revoked) | PERMISSION_DENIED (the `drive.file` permission was never given) |
    STORAGE_FULL (the teacher's Drive has no room) | RATE_LIMITED | NOT_FOUND | UPSTREAM"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _refused(r: httpx.Response) -> DriveError:
    try:
        reason = (r.json().get("error", {}).get("errors") or [{}])[0].get("reason", "")
    except ValueError:
        reason = ""
    return DriveError("STORAGE_FULL" if reason == "storageQuotaExceeded" else ERRORS.get(r.status_code, "UPSTREAM"))


class DriveStream:
    """An answer from Drive that is still arriving: its headers now, its bytes as they come. Closing it matters: it holds a connection."""

    def __init__(self, status: int, headers: dict[str, str], media_type: str, response: httpx.Response) -> None:
        self.status, self.headers, self.media_type, self._r = status, headers, media_type, response

    async def chunks(self):
        try:
            if self._r.is_stream_consumed:  # an answer already in memory (a test double): hand it over whole
                yield self._r.content
            else:
                async for chunk in self._r.aiter_raw():
                    yield chunk
        finally:
            await self._r.aclose()

    async def close(self) -> None:
        await self._r.aclose()


RANGE = re.compile(r"^bytes=\d*-\d*$")  # one range, as a player sends it; anything stranger is ignored, not passed on


class DriveUploader:
    def __init__(self, http: httpx.AsyncClient, auth: TokenSource, *, base: str, upload_base: str) -> None:
        self._http, self._auth, self._base, self._up = http, auth, base.rstrip("/"), upload_base.rstrip("/")

    async def _send(self, method: str, url: str, **kw: Any) -> httpx.Response:
        try:
            headers = {**await self._auth.headers(), **kw.pop("headers", {})}
        except httpx.HTTPStatusError:
            raise DriveError("UNAUTHENTICATED") from None
        except httpx.HTTPError:
            raise DriveError("UPSTREAM") from None
        try:
            return await self._http.request(method, url, headers=headers, timeout=120, **kw)
        except httpx.HTTPError:
            raise DriveError("UPSTREAM") from None

    async def ensure_folder(self, folder_id: str | None, name: str = FOLDER_NAME) -> str:
        """The id of Cortex's folder in this Drive: the one we made before if it is still there, else a new one called `name`."""
        if folder_id:
            r = await self._send("GET", f"{self._base}/files/{folder_id}", params={"fields": "id,trashed"})
            if r.status_code == 200 and not r.json().get("trashed"):
                return folder_id
            if r.status_code not in (200, 404):
                raise _refused(r)
        r = await self._send("POST", f"{self._base}/files", params={"fields": "id"}, json={"name": name, "mimeType": FOLDER_MIME})
        if r.status_code >= 300:
            raise _refused(r)
        return r.json()["id"]

    async def open_stream(self, file_id: str, range_header: str | None) -> DriveStream:
        """The file's bytes for a player: type and size first, then the body (or the requested range of it) streamed through without being kept."""
        meta = await self._send("GET", f"{self._base}/files/{file_id}", params={"fields": "mimeType,size"})
        if meta.status_code >= 300:
            raise _refused(meta)
        try:
            headers = {**await self._auth.headers(), **({"Range": range_header} if range_header and RANGE.match(range_header) else {})}
        except httpx.HTTPError:
            raise DriveError("UNAUTHENTICATED") from None
        request = self._http.build_request("GET", f"{self._base}/files/{file_id}", params={"alt": "media"}, headers=headers)
        try:
            r = await self._http.send(request, stream=True)
        except httpx.HTTPError:
            raise DriveError("UPSTREAM") from None
        if r.status_code >= 300:
            await r.aclose()
            if r.status_code == 416:
                raise DriveError("BAD_RANGE")
            raise _refused(r)
        kept = {k: r.headers[k] for k in ("content-length", "content-range", "accept-ranges") if k in r.headers}
        return DriveStream(r.status_code, {"accept-ranges": "bytes", **kept}, meta.json().get("mimeType", "application/octet-stream"), r)

    async def trash_file(self, file_id: str) -> None:
        """Moves the file to the Drive's bin (the teacher can still restore it there). A file that is already gone counts as done."""
        r = await self._send("PATCH", f"{self._base}/files/{file_id}", params={"fields": "id"}, json={"trashed": True})
        if r.status_code >= 300 and r.status_code != 404:
            raise _refused(r)

    async def check_write(self, folder_id: str) -> None:
        """Proves this sign-in may put files in `folder_id` (a folder the teacher already had, which the narrow `drive.file` permission may or may
        not allow) by making a tiny text file there and removing it again. Raises DriveError (NOT_FOUND / PERMISSION_DENIED …) otherwise."""
        r = await self._send("POST", f"{self._base}/files", params={"fields": "id"},
                             json={"name": "cortex-test.txt", "mimeType": "text/plain", "parents": [folder_id]})
        if r.status_code >= 300:
            raise _refused(r)
        await self._send("DELETE", f"{self._base}/files/{r.json()['id']}")

    async def start_session(self, name: str, mime: str, size: int, folder_id: str, properties: dict[str, str] | None = None,
                            origin: str | None = None) -> str:
        """Opens a resumable upload of one new file and returns its session URL. Whoever holds the URL can write THAT file (name, folder and
        properties are fixed here, not by the holder) until it is finished or a week passes, so it goes only to the signed-in person who asked.
        `origin` is the page that will send the bytes: Google allows cross-site requests from exactly that origin (not from a request header)."""
        start = await self._send("POST", f"{self._up}/files", params={"uploadType": "resumable", "fields": "id,webViewLink"},
                                 headers={"X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(size),
                                          "Content-Type": "application/json; charset=UTF-8", **({"Origin": origin} if origin else {})},
                                 content=json.dumps({"name": name, "parents": [folder_id], "mimeType": mime, **({"properties": properties} if properties else {})}).encode())
        if start.status_code >= 300 or not start.headers.get("location"):
            raise _refused(start)
        return start.headers["location"]

    async def upload(self, path: Path, name: str, mime: str, folder_id: str, properties: dict[str, str] | None = None) -> dict[str, str]:
        """{id, webViewLink} of the new file in `folder_id`, sent from this server. `properties` are custom properties on the file."""
        size = path.stat().st_size
        session = await self.start_session(name, mime, size, folder_id, properties)
        sent = 0
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(CHUNK)
                if not chunk:
                    break
                end = sent + len(chunk) - 1
                r = await self._send("PUT", session, content=chunk, headers={"Content-Range": f"bytes {sent}-{end}/{size}"})
                sent = end + 1
                if r.status_code in (200, 201):
                    return {"id": r.json()["id"], "webViewLink": r.json().get("webViewLink", "")}
                if r.status_code != 308:  # 308: Google has the chunk and wants the next
                    raise _refused(r)
        raise DriveError("UPSTREAM")


def open_uploader(secret: bytes, *, http: httpx.AsyncClient | None = None) -> DriveUploader:
    """The uploader for a stored target: `secret` is the decrypted {client_id, client_secret, refresh_token}. The HTTP client is made here."""
    data = json.loads(secret)
    http = http or httpx.AsyncClient()
    s = get_settings()
    return DriveUploader(http, RefreshToken(data["client_id"], data["client_secret"], data["refresh_token"], http),
                         base=s.DRIVE_API_BASE, upload_base=s.DRIVE_UPLOAD_BASE)
