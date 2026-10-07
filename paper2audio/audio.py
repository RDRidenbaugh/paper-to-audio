"""Text-to-speech synthesis and MP3 assembly/tagging."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

import edge_tts
from mutagen.id3 import (
    APIC, CHAP, COMM, CTOC, CTOCFlags, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TRCK,
)

DEFAULT_VOICE = "en-US-AndrewNeural"

# A short, curated list shown first in the GUI; the full catalogue is fetched on demand.
FEATURED_VOICES = [
    ("en-US-AndrewNeural", "Andrew (US, male)"),
    ("en-US-AvaNeural", "Ava (US, female)"),
    ("en-US-BrianNeural", "Brian (US, male)"),
    ("en-US-EmmaNeural", "Emma (US, female)"),
    ("en-US-AriaNeural", "Aria (US, female)"),
    ("en-US-ChristopherNeural", "Christopher (US, male)"),
    ("en-GB-RyanNeural", "Ryan (UK, male)"),
    ("en-GB-SoniaNeural", "Sonia (UK, female)"),
    ("en-AU-NatashaNeural", "Natasha (Australia, female)"),
    ("en-CA-LiamNeural", "Liam (Canada, male)"),
    ("en-IE-EmilyNeural", "Emily (Ireland, female)"),
    ("en-IN-PrabhatNeural", "Prabhat (India, male)"),
]


class Cancelled(Exception):
    pass


@dataclass
class Segment:
    """One piece of narration. `chapter` starts a new chapter/track when set."""
    text: str
    chapter: str | None = None
    pause_after: float = 0.0


# --- MP3 frame helpers -------------------------------------------------------

_BITRATES = {
    1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],   # MPEG-1 L3
    2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],      # MPEG-2/2.5 L3
}
_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def _frame_info(header: bytes) -> tuple[int, float]:
    """(frame length in bytes, frame duration in seconds) for an MPEG layer III header."""
    version = (header[1] >> 3) & 0b11
    br_idx = header[2] >> 4
    sr_idx = (header[2] >> 2) & 0b11
    padding = (header[2] >> 1) & 1
    sr = _RATES[version][sr_idx]
    bitrate = _BITRATES[1 if version == 3 else 2][br_idx] * 1000
    samples = 1152 if version == 3 else 576
    length = (samples // 8) * bitrate // sr + padding
    return length, samples / sr


def _find_sync(data: bytes) -> int:
    i = 0
    if data[:3] == b"ID3":
        size = data[6] << 21 | data[7] << 14 | data[8] << 7 | data[9]
        i = 10 + size
    while i < len(data) - 1:
        if data[i] == 0xFF and data[i + 1] & 0xE0 == 0xE0:
            return i
        i += 1
    return -1


def mp3_duration(data: bytes) -> float:
    i = _find_sync(data)
    total = 0.0
    while 0 <= i < len(data) - 4:
        if data[i] != 0xFF or data[i + 1] & 0xE0 != 0xE0:
            break
        length, dur = _frame_info(data[i:i + 4])
        if length <= 0:
            break
        total += dur
        i += length
    return total


def silence(like: bytes, seconds: float) -> bytes:
    """Silent MP3 frames in the same format as `like` (all-zero side info decodes to silence)."""
    i = _find_sync(like)
    if i < 0 or seconds <= 0:
        return b""
    header = bytearray(like[i:i + 4])
    header[1] |= 0x01          # no CRC
    header[2] &= 0b11111101    # no padding
    length, dur = _frame_info(bytes(header))
    frame = bytes(header) + bytes(length - 4)
    return frame * max(1, round(seconds / dur))


# --- Synthesis ---------------------------------------------------------------

async def _stream(text: str, voice: str, rate: str) -> bytes:
    out = bytearray()
    async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
        if chunk["type"] == "audio":
            out += chunk["data"]
    return bytes(out)


async def _synthesize_one(text: str, voice: str, rate: str, attempts: int = 4) -> bytes:
    # A healthy request takes about a second per 1,500 characters, but the
    # service occasionally stalls a connection for 30 s or more. Give up on a
    # stalled request early and retry instead of holding up the whole paper.
    timeout = max(10.0, len(text) / 100)
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            out = await asyncio.wait_for(_stream(text, voice, rate), timeout)
            if out:
                return out
            raise RuntimeError("The speech service returned no audio.")
        except Exception as e:  # network hiccups, throttling, stalls
            last = e
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Speech synthesis failed after {attempts} attempts: {last}") from last


def synthesize(segments: list[Segment], voice: str, rate_pct: int, progress=None,
               cancel: threading.Event | None = None, concurrency: int = 8) -> list[bytes]:
    """Synthesize all segments (in parallel, order preserved). Blocking."""
    rate = f"{rate_pct:+d}%"

    async def run():
        sem = asyncio.Semaphore(concurrency)
        done = 0
        total_chars = sum(len(s.text) for s in segments) or 1
        results: list[bytes | None] = [None] * len(segments)

        async def work(i: int, seg: Segment):
            nonlocal done
            async with sem:
                if cancel and cancel.is_set():
                    raise Cancelled()
                results[i] = await _synthesize_one(seg.text, voice, rate)
                done += len(seg.text)
                if progress:
                    progress(done / total_chars, f"Generating speech… {int(100 * done / total_chars)}%")

        tasks = [asyncio.create_task(work(i, s)) for i, s in enumerate(segments)]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return results

    return asyncio.run(run())


async def _list_voices() -> list[dict]:
    return await edge_tts.list_voices()


def list_voices(language_prefix: str = "en") -> list[tuple[str, str]]:
    voices = asyncio.run(_list_voices())
    out = []
    for v in sorted(voices, key=lambda v: (v["Locale"], v["ShortName"])):
        if v["Locale"].lower().startswith(language_prefix.lower()):
            name = v["ShortName"].split("-")[-1].replace("Neural", "")
            out.append((v["ShortName"], f"{name} ({v['Locale']}, {v['Gender'].lower()})"))
    return out


# --- Tagging -----------------------------------------------------------------

@dataclass
class Tags:
    title: str
    artist: str
    album: str
    year: str = ""
    comment: str = ""
    cover_jpeg: bytes | None = None
    track: tuple[int, int] | None = None


def write_tags(path: str, tags: Tags, chapters: list[tuple[str, float, float]] | None = None) -> None:
    id3 = ID3()
    id3.add(TIT2(encoding=3, text=tags.title))
    id3.add(TPE1(encoding=3, text=tags.artist))
    id3.add(TPE2(encoding=3, text=tags.artist))
    id3.add(TALB(encoding=3, text=tags.album))
    id3.add(TCON(encoding=3, text="Audiobook"))
    if tags.year:
        id3.add(TDRC(encoding=3, text=tags.year))
    if tags.comment:
        id3.add(COMM(encoding=3, lang="eng", desc="", text=tags.comment))
    if tags.track:
        id3.add(TRCK(encoding=3, text=f"{tags.track[0]}/{tags.track[1]}"))
    if tags.cover_jpeg:
        id3.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=tags.cover_jpeg))
    if chapters:
        ids = [f"ch{i}" for i in range(len(chapters))]
        id3.add(CTOC(element_id="toc", flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
                     child_element_ids=ids, sub_frames=[TIT2(encoding=3, text="Contents")]))
        for cid, (name, start, end) in zip(ids, chapters):
            id3.add(CHAP(element_id=cid, start_time=int(start * 1000), end_time=int(end * 1000),
                         sub_frames=[TIT2(encoding=3, text=name)]))
    id3.save(path, v2_version=3)


def cover_from_pdf(pdf_path: str) -> bytes | None:
    """First page of the paper as square-ish cover art."""
    try:
        import pymupdf
        doc = pymupdf.open(pdf_path)
        page = doc[0]
        r = page.rect
        clip = pymupdf.Rect(r.x0, r.y0, r.x1, r.y0 + r.width)  # top square of the page
        pix = page.get_pixmap(clip=clip, dpi=110)
        return pix.tobytes("jpeg", jpg_quality=85)
    except Exception:
        return None
