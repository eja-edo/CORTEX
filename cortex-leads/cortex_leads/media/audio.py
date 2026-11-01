"""Recording or spoken answer -> small audio pieces a speech model accepts (the API takes 25 MB per file). Needs `ffmpeg`."""
import asyncio
from pathlib import Path

from cortex_leads.core.errors import CortexError

CHUNK_S = 600  # 10 minutes of mono 16 kHz opus at 24 kbit/s is about 1.8 MB


async def split_audio(src: Path, out_dir: Path, chunk_s: int = CHUNK_S) -> list[Path]:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "libopus", "-b:a", "24k", "-f", "segment", "-segment_time", str(chunk_s),
        str(out_dir / "part%03d.ogg"), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise CortexError(f"ffmpeg failed: {err.decode(errors='replace')[-300:]}")
    parts = sorted(out_dir.glob("part*.ogg"))
    if not parts:
        raise CortexError("ffmpeg produced no audio (no sound track?)")
    return parts


async def probe(path: Path) -> dict[str, float | bool]:
    """{has_audio, has_video, seconds} of a media file, or CortexError if it is not one. Run on a file somebody just uploaded: the pipeline
    would only find out minutes later, in the middle of a transcription."""
    import json

    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        raise CortexError("not a media file")
    info = json.loads(out or b"{}")
    kinds = {st.get("codec_type") for st in info.get("streams", [])}
    try:
        seconds = float(info.get("format", {}).get("duration", 0) or 0)
    except ValueError:
        seconds = 0.0
    return {"has_audio": "audio" in kinds, "has_video": "video" in kinds, "seconds": seconds}
