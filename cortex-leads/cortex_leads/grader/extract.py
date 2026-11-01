"""What a student handed in, as text the grader can read (WP34). The submission is a short answer and/or files in Drive, and each file is
read by what it is:
- a Google Doc or a plain-text file: its text;
- a PDF: the text layer. A scanned PDF has none and is refused (NO_TEXT_LAYER): reading pictures of handwriting is a different, error-prone
  job and a wrong reading would be graded as if the student had written it;
- a Word file (.docx): its paragraphs;
- audio or video: only the sound is taken (ffmpeg drops the picture), cut in pieces and written out by the same speech model the lesson
  recap uses. A spoken answer of up to 15 minutes; longer is refused (TOO_LONG).
Anything else (pictures, slides, sheets) is UNSUPPORTED_ATTACHMENT, never graded on the part that could be read. Each reading that can
be wrong in a way the student did not cause says so in `notes`, and the teacher sees it next to the suggested grade.
File names are never passed on: they often hold the student's name."""
import asyncio
import html
import re
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from cortex_leads.connectors.classroom import ClassroomClient, ClassroomError, Submission
from cortex_leads.connectors.speech import Transcriber
from cortex_leads.core.errors import CortexError
from cortex_leads.media.audio import split_audio

MAX_TEXT = 60_000          # characters read of one submission
MAX_FILE_BYTES = 25 * 1024 * 1024   # a PDF or Word file
MAX_MEDIA_BYTES = 150 * 1024 * 1024  # a recording
SPEECH_CHUNK_S = 300
MAX_SPEECH_PARTS = 3       # 15 minutes
MIN_SPOKEN_WORDS = 3
MAX_PDF_PAGES = 40
MAX_IMAGES = 6
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
MAX_XML_BYTES = 10 * 1024 * 1024
MIN_PDF_CHARS = 20

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUFFIX_KIND = {".pdf": "pdf", ".docx": "docx", ".txt": "text", ".md": "text", ".mp3": "audio", ".m4a": "audio", ".wav": "audio",
               ".ogg": "audio", ".aac": "audio", ".mp4": "video", ".mov": "video", ".webm": "video", ".mkv": "video"}
NOTES = {
    "audio": "Bài nộp là âm thanh được máy chép lại thành chữ. Lỗi nhận dạng có thể bị tính nhầm thành lỗi của học sinh (nhất là chính tả và "
             "phát âm); hãy nghe lại bản ghi trước khi duyệt.",
    "video": "Bài nộp là video; chỉ lấy tiếng, máy chép lại thành chữ. Lỗi nhận dạng có thể bị tính nhầm thành lỗi của học sinh; "
             "hãy xem lại video trước khi duyệt, vì hình ảnh không được đọc.",
    "pdf": "Bài nộp là PDF; chữ lấy từ lớp chữ của tệp, hình vẽ và bảng có thể bị mất.",
    "image": "Bài nộp là ảnh chụp; chữ (nhất là chữ viết tay) do máy đọc từ ảnh nên có thể sai theo cách học sinh không gây ra. "
             "Hãy mở ảnh gốc trên Classroom và đối chiếu trước khi duyệt.",
}
SPOKEN_HEADER = "[Bản chép lời từ bản ghi âm, do máy nhận dạng nên có thể sai]"


class ExtractError(CortexError):
    """`.code`: UNSUPPORTED_ATTACHMENT | EMPTY_SUBMISSION | NO_TEXT_LAYER | TOO_LONG | NO_SPEECH | FILE_UNREADABLE | TOO_LARGE"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Extracted:
    text: str
    kinds: list[str] = field(default_factory=list)  # text | pdf | docx | audio | video | image, in the order met
    notes: list[str] = field(default_factory=list)  # what the teacher should know about how this was read
    images: list[tuple[str, bytes]] = field(default_factory=list)  # (mime type, bytes) of photos, shown to the model as they are


def kind_of(mime: str, title: str) -> str | None:
    if mime == "application/vnd.google-apps.document" or mime.startswith("text/"):
        return "text"
    if mime in IMAGE_MIMES:
        return "image"
    if mime == "application/pdf":
        return "pdf"
    if mime == DOCX:
        return "docx"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if mime in ("", "application/octet-stream"):
        return SUFFIX_KIND.get(Path(title.lower()).suffix)
    return None


def pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ExtractError("FILE_UNREADABLE")
        text = "\n".join((p.extract_text() or "") for p in reader.pages[:MAX_PDF_PAGES])
    except (PyPdfError, ValueError, KeyError, OSError):
        raise ExtractError("FILE_UNREADABLE") from None
    if len(text.strip()) < MIN_PDF_CHARS:
        raise ExtractError("NO_TEXT_LAYER")
    return text


def docx_text(path: Path) -> str:
    """The paragraphs of a Word file, read with a regular expression rather than an XML parser: the file is the student's, and a hostile one
    must not get a chance to expand entities."""
    try:
        with zipfile.ZipFile(path) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_XML_BYTES:
                raise ExtractError("FILE_UNREADABLE")
            xml = z.read(info).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError):
        raise ExtractError("FILE_UNREADABLE") from None
    paragraphs = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.DOTALL):
        parts = re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>|<w:tab/>|<w:br/>", p, flags=re.DOTALL)
        paragraphs.append(html.unescape("".join(parts)))
    text = "\n".join(paragraphs).strip()
    if not text:
        raise ExtractError("EMPTY_SUBMISSION")
    return text


async def speech_text(path: Path, transcriber: Transcriber, language: str | None) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        parts_dir = Path(tmp)
        try:
            parts = await split_audio(path, parts_dir, chunk_s=SPEECH_CHUNK_S)
        except CortexError:
            raise ExtractError("FILE_UNREADABLE") from None
        if len(parts) > MAX_SPEECH_PARTS:
            raise ExtractError("TOO_LONG")
        text = " ".join([await transcriber.transcribe(p, language=language) for p in parts]).strip()
    if len(text.split()) < MIN_SPOKEN_WORDS:
        raise ExtractError("NO_SPEECH")
    return f"{SPOKEN_HEADER}\n{text}"


async def extract(client: ClassroomClient, sub: Submission, transcriber: Callable[[], Transcriber], language: str | None = None, *,
                  allow_images: bool = False) -> Extracted:
    """Raises ExtractError (or ClassroomError for what Google answered). `transcriber` is only called if a recording is met, and
    `language` is the one the assignment says is spoken (None: detect). Photos are taken only with `allow_images` (they reach the model
    unmasked); without it a photo is UNSUPPORTED_ATTACHMENT, as before."""
    out = Extracted("")
    parts: list[str] = [sub.answer] if sub.answer and sub.answer.strip() else []
    if parts:
        out.kinds.append("text")
    for a in sub.attachments:
        if a.kind != "drive":
            raise ExtractError("UNSUPPORTED_ATTACHMENT")
        meta = await client.drive_meta(a.id)
        kind = kind_of(meta["mimeType"], a.title)
        if kind is None or (kind == "image" and not allow_images):
            raise ExtractError("UNSUPPORTED_ATTACHMENT")
        if kind == "image":
            if len(out.images) >= MAX_IMAGES or meta["size"] > MAX_IMAGE_BYTES:
                raise ExtractError("TOO_LARGE")
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "student-image"
                try:
                    await client.download(a.id, path, MAX_IMAGE_BYTES)
                except ClassroomError as e:
                    raise ExtractError(e.code if e.code == "TOO_LARGE" else "FILE_UNREADABLE") from None
                out.images.append((meta["mimeType"], path.read_bytes()))
        elif kind == "text":
            if meta["mimeType"].startswith("text/") and meta["size"] > MAX_FILE_BYTES:
                raise ExtractError("TOO_LARGE")
            parts.append(await client.drive_text(a.id, meta["mimeType"] or "text/plain"))
        else:
            limit = MAX_MEDIA_BYTES if kind in ("audio", "video") else MAX_FILE_BYTES
            if meta["size"] > limit:
                raise ExtractError("TOO_LARGE")
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "student-file"
                try:
                    await client.download(a.id, path, limit)
                except ClassroomError as e:
                    raise ExtractError(e.code if e.code == "TOO_LARGE" else "FILE_UNREADABLE") from None
                if kind == "pdf":
                    parts.append(await asyncio.to_thread(pdf_text, path))
                elif kind == "docx":
                    parts.append(await asyncio.to_thread(docx_text, path))
                else:
                    parts.append(await speech_text(path, transcriber(), language))
        if kind not in out.kinds:
            out.kinds.append(kind)
        if kind in NOTES and NOTES[kind] not in out.notes:
            out.notes.append(NOTES[kind])
    text = "\n\n".join(p.strip() for p in parts if p and p.strip())
    if not text and not out.images:
        raise ExtractError("EMPTY_SUBMISSION")
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT]
        out.notes.append(f"Bài rất dài, chỉ đọc {MAX_TEXT:,} ký tự đầu.".replace(",", "."))
    out.text = text
    return out


def extracted_from_row(content: str, content_kind: str | None) -> Extracted:
    """What an earlier try read, with the notes that went with it, so a retry needs neither Classroom nor the speech model again."""
    kinds = [k for k in (content_kind or "").split(",") if k]
    notes = [NOTES[k] for k in kinds if k in NOTES]
    if len(content) >= MAX_TEXT:
        notes.append(f"Bài rất dài, chỉ đọc {MAX_TEXT:,} ký tự đầu.".replace(",", "."))
    return Extracted(content, kinds, notes)
