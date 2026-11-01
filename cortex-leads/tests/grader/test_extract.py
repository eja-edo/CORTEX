"""WP34: a student may hand in a PDF, a Word file, a recording or a video; each is read by what it is, or refused with a reason."""
import asyncio
import shutil
import struct
import subprocess
import wave
import zipfile

import httpx
import pytest

from cortex_leads.connectors.classroom import ClassroomClient
from cortex_leads.grader import extract as ex
from cortex_leads.grader.extract import ExtractError, extract, extracted_from_row
from dev.local.fake_classroom import demo, minimal_pdf

ENGLISH = "I have two brothers. She has a cat. We have a dog."


class Speech:
    def __init__(self, text: str = ENGLISH) -> None:
        self.text, self.heard, self.languages = text, 0, []

    async def transcribe(self, audio, language=None):
        self.heard += 1
        self.languages.append(language)
        return self.text


class Bearer:
    async def headers(self):
        return {"Authorization": "Bearer t"}


def setup(file=None, **kw):
    fc = demo()
    w = fc.add_work("X", ours=True)
    fc.add_submission(w, "u1", file=file, **kw)
    client = ClassroomClient(httpx.AsyncClient(transport=fc.transport()), Bearer(), base="https://x/v1", drive_base="https://x/drive/v3")
    return fc, w, client


async def read(file=None, speech=None, language=None, **kw):
    _, w, client = setup(file, **kw)
    (sub,) = await client.submissions("c1", w)
    return await extract(client, sub, lambda: speech or Speech(), language)


pdf = minimal_pdf


def docx(path, paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{p}</w:t></w:r></w:p>" for p in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<?xml version='1.0'?><w:document xmlns:w='x'><w:body>{body}</w:body></w:document>")
    return path.read_bytes()


def wav(path, seconds: float, rate: int = 8000) -> bytes:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(rate * seconds))
    return path.read_bytes()


async def test_a_pdf_with_text_is_read_and_the_teacher_is_told_it_was_a_pdf(tmp_path):
    r = await read(("application/pdf", pdf("She has finished her homework"), "Bài - Nguyễn An.pdf"))
    assert "She has finished her homework" in r.text and r.kinds == ["pdf"] and r.notes == [ex.NOTES["pdf"]]
    assert "Nguyễn" not in r.text  # the file name, which holds a name, is not passed on


async def test_a_scanned_pdf_has_no_text_to_read_and_is_refused_for_that_reason():
    with pytest.raises(ExtractError) as e:
        await read(("application/pdf", pdf(None), "scan.pdf"))
    assert e.value.code == "NO_TEXT_LAYER"


async def test_a_broken_pdf_and_a_file_that_is_not_what_it_says_are_unreadable_not_a_crash():
    for blob in (b"%PDF-1.4 not really", b"\x00\x01\x02", b""):
        with pytest.raises(ExtractError) as e:
            await read(("application/pdf", blob, "x.pdf"))
        assert e.value.code == "FILE_UNREADABLE"


async def test_a_word_file_gives_its_paragraphs_with_entities_decoded(tmp_path):
    blob = docx(tmp_path / "a.docx", ["I have lived in Hanoi.", "She &amp; he have finished."])
    r = await read((ex.DOCX, blob, "bai.docx"))
    assert r.text == "I have lived in Hanoi.\nShe & he have finished." and r.kinds == ["docx"] and r.notes == []


async def test_an_empty_or_broken_word_file_is_named_as_such(tmp_path):
    with pytest.raises(ExtractError) as e:
        await read((ex.DOCX, docx(tmp_path / "e.docx", [""]), "e.docx"))
    assert e.value.code == "EMPTY_SUBMISSION"
    with pytest.raises(ExtractError) as e:
        await read((ex.DOCX, b"not a zip", "b.docx"))
    assert e.value.code == "FILE_UNREADABLE"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_a_spoken_answer_is_written_out_with_a_header_and_a_warning_that_the_machine_may_be_wrong(tmp_path):
    speech = Speech()
    r = await read(("audio/wav", wav(tmp_path / "a.wav", 3), "noi.wav"), speech=speech)
    assert r.text.startswith(ex.SPOKEN_HEADER) and ENGLISH in r.text and r.kinds == ["audio"] and r.notes == [ex.NOTES["audio"]] and speech.heard == 1


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_a_video_gives_its_sound_only_and_says_the_picture_was_not_read(tmp_path):
    mp4 = tmp_path / "v.mp4"
    await asyncio.to_thread(subprocess.run, ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2", "-f", "lavfi", "-i", "sine=f=440:d=2",
                    "-shortest", "-c:v", "libx264", "-c:a", "aac", str(mp4)], check=True)
    r = await read(("video/mp4", mp4.read_bytes(), "clip.mp4"))
    assert r.kinds == ["video"] and ENGLISH in r.text and "hình ảnh không được đọc" in r.notes[0]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_more_than_fifteen_minutes_of_speech_is_refused_before_the_model_hears_any(tmp_path):
    speech = Speech()
    with pytest.raises(ExtractError) as e:
        await read(("audio/wav", wav(tmp_path / "long.wav", 16 * 60, rate=4000), "dai.wav"), speech=speech)
    assert e.value.code == "TOO_LONG" and speech.heard == 0


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_a_recording_with_no_words_in_it_is_no_speech(tmp_path):
    with pytest.raises(ExtractError) as e:
        await read(("audio/wav", wav(tmp_path / "s.wav", 2), "im.wav"), speech=Speech(""))
    assert e.value.code == "NO_SPEECH"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_a_file_that_is_not_audio_though_it_says_so_is_unreadable(tmp_path):
    with pytest.raises(ExtractError) as e:
        await read(("audio/mpeg", b"this is text, not sound", "x.mp3"))
    assert e.value.code == "FILE_UNREADABLE"


async def test_pictures_slides_links_and_the_like_are_refused_not_graded_on_a_part():
    for file in (("image/png", b"x", "a.png"), ("application/vnd.google-apps.presentation", b"x", "s"), ("application/zip", b"x", "z.zip")):
        with pytest.raises(ExtractError) as e:
            await read(file, answer="phần chữ")  # the short answer alone is not the whole work
        assert e.value.code == "UNSUPPORTED_ATTACHMENT"


async def test_a_file_without_a_type_is_read_by_the_end_of_its_name():
    r = await read(("application/octet-stream", pdf("I have eaten breakfast already"), "bai.PDF"))
    assert r.kinds == ["pdf"]


async def test_a_short_answer_and_a_file_are_read_together(tmp_path):
    r = await read((ex.DOCX, docx(tmp_path / "m.docx", ["Phần hai của bài."]), "m.docx"), answer="Phần một của bài.")
    assert r.text == "Phần một của bài.\n\nPhần hai của bài." and r.kinds == ["text", "docx"]


async def test_a_file_over_the_limit_is_refused_before_it_is_downloaded(monkeypatch):
    monkeypatch.setattr(ex, "MAX_FILE_BYTES", 100)
    fc, w, client = setup(("application/pdf", pdf("x" * 300), "big.pdf"))
    (sub,) = await client.submissions("c1", w)
    calls = len(fc.calls)
    with pytest.raises(ExtractError) as e:
        await extract(client, sub, lambda: Speech())
    assert e.value.code == "TOO_LARGE" and not any("alt=media" in c[1] for c in fc.calls[calls:])


async def test_a_very_long_text_is_cut_and_the_teacher_is_told(monkeypatch):
    monkeypatch.setattr(ex, "MAX_TEXT", 50)
    r = await read(answer="Một câu khá dài. " * 20)
    assert len(r.text) == 50 and any("chỉ đọc 50 ký tự đầu" in n for n in r.notes)
    assert any("chỉ đọc" in n for n in extracted_from_row(r.text, "text").notes)  # a retry keeps the note


def test_a_retry_rebuilds_what_was_read_with_its_notes():
    r = extracted_from_row("text", "audio,text")
    assert r.kinds == ["audio", "text"] and r.notes == [ex.NOTES["audio"]]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_the_language_of_the_assignment_is_the_one_the_speech_model_is_told(tmp_path):
    """A language forced onto speech in another one comes out as nonsense (English speech written out in Vietnamese was graded 2/10)."""
    for given in ("en", "vi", None):
        speech = Speech()
        await read(("audio/wav", wav(tmp_path / "a.wav", 2), "n.wav"), speech=speech, language=given)
        assert speech.languages == [given]


async def test_the_api_names_a_language_only_when_it_was_given():
    from cortex_leads.connectors.speech import WhisperApi
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.content.decode(errors="replace"))
        return httpx.Response(200, json={"text": " hi "})

    api = WhisperApi("https://w.example/v1", "k", "whisper-1", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    f = __import__("pathlib").Path(__import__("tempfile").mkdtemp()) / "a.ogg"
    f.write_bytes(b"x")
    assert await api.transcribe(f, language="en") == "hi" and 'name="language"' in seen[0] and "en" in seen[0]
    await api.transcribe(f)
    assert 'name="language"' not in seen[1]


# --- photos (they go to the model as they are, so a deployment must turn them on) ---------------------
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc000000301010018dd8db00000000049454e44ae426082")


async def test_a_photo_is_refused_unless_the_deployment_allows_photos():
    _, w, client = setup(("image/png", PNG, "bai_viet_tay.png"))
    (sub,) = await client.submissions("c1", w)
    with pytest.raises(ExtractError) as e:
        await extract(client, sub, lambda: Speech(), None)
    assert e.value.code == "UNSUPPORTED_ATTACHMENT"


async def test_a_photo_is_kept_as_bytes_for_the_model_with_a_note_for_the_teacher():
    _, w, client = setup(("image/png", PNG, "bai_viet_tay.png"))
    (sub,) = await client.submissions("c1", w)
    r = await extract(client, sub, lambda: Speech(), None, allow_images=True)
    assert r.images == [("image/png", PNG)] and r.kinds == ["image"] and r.text == ""
    assert any("ảnh chụp" in n and "đối chiếu" in n for n in r.notes)


async def test_a_photo_that_is_too_big_is_refused(monkeypatch):
    monkeypatch.setattr(ex, "MAX_IMAGE_BYTES", 10)
    _, w, client = setup(("image/png", PNG, "to.png"))
    (sub,) = await client.submissions("c1", w)
    with pytest.raises(ExtractError) as e:
        await extract(client, sub, lambda: Speech(), None, allow_images=True)
    assert e.value.code == "TOO_LARGE"
