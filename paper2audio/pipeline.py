"""PDF -> narration script -> MP3(s). Shared by the GUI and the command line."""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass

from . import audio, speech
from .extract import Paper, extract


@dataclass
class Options:
    voice: str = audio.DEFAULT_VOICE
    rate: int = 0                     # percent, -50..+100
    split_tracks: bool = False        # one MP3 per section instead of one file with chapters
    include_captions: bool = False
    include_back_matter: bool = False
    keep_citations: bool = False
    keep_figure_refs: bool = False
    read_intro: bool = True
    save_transcript: bool = False


def _byline(authors: list[str]) -> str:
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) <= 3:
        return ", ".join(authors[:-1]) + " and " + authors[-1]
    return f"{authors[0]} and colleagues"


def build_script(paper: Paper, opts: Options) -> list[audio.Segment]:
    segs: list[audio.Segment] = []
    prep = lambda t: speech.prepare(t, opts.keep_citations, opts.keep_figure_refs)

    if opts.read_intro:
        intro = paper.title.rstrip(".") + "."
        if paper.authors:
            intro += f" By {_byline(paper.authors)}."
        pub = ", ".join(x for x in (paper.journal, paper.year) if x)
        if pub:
            intro += f" Published in {pub}."
        segs.append(audio.Segment(prep(intro), chapter="Title and authors", pause_after=1.2))

    for sec in paper.sections:
        heading = sec.title
        if sec.opens_parent and sec.parent:
            heading = f"{sec.parent}. {sec.title}"
        segs.append(audio.Segment(prep(heading.rstrip(".") + "."), chapter=sec.full_title, pause_after=0.7))
        body = [prep(p) for p in sec.paragraphs]
        if opts.include_captions:
            body += [prep(c) for c in sec.captions]
        # Group paragraphs into service-sized chunks, keeping paragraph breaks as short pauses.
        for para in body:
            for piece in speech.chunk(para):
                segs.append(audio.Segment(piece, pause_after=0.0))
            if segs:
                segs[-1].pause_after = 0.45
        segs[-1].pause_after = 1.2

    segs.append(audio.Segment("End of paper.", chapter=None, pause_after=0.5))
    return [s for s in segs if s.text.strip()]


def transcript(segs: list[audio.Segment]) -> str:
    out = []
    for s in segs:
        if s.chapter:
            out.append(f"\n## {s.chapter}\n")
            if s.chapter != "Title and authors":
                continue  # the spoken heading just repeats the chapter name
        out.append(s.text)
    return "\n\n".join(out).strip() + "\n"


def safe_filename(name: str, limit: int = 120) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:limit].rstrip(" .") or "paper")


def convert(pdf_path: str, out_path: str, opts: Options, progress=None,
            cancel: threading.Event | None = None) -> list[str]:
    """Convert a PDF to audio. Returns the list of files written.

    `out_path` is the MP3 file for single-file mode, or the folder for split-track mode.
    `progress(fraction, message)` is called with an overall 0..1 fraction.
    """
    def report(frac, msg):
        if progress:
            progress(frac, msg)

    def check():
        if cancel and cancel.is_set():
            raise audio.Cancelled()

    report(0.0, "Reading PDF…")
    paper = extract(pdf_path, include_captions=opts.include_captions,
                    include_back_matter=opts.include_back_matter,
                    progress=lambda f, m: report(0.08 * f, m))
    check()
    segs = build_script(paper, opts)
    if len(segs) < 3:
        raise ValueError("Couldn't find readable text in this PDF.")
    report(0.1, f"Found {sum(1 for s in segs if s.chapter)} sections. Generating speech…")

    clips = audio.synthesize(segs, opts.voice, opts.rate,
                             progress=lambda f, m: report(0.1 + 0.85 * f, m), cancel=cancel)
    check()
    report(0.96, "Assembling audio file…")

    cover = audio.cover_from_pdf(pdf_path)
    artist = _byline(paper.authors) or "Unknown author"
    comment = ", ".join(x for x in (paper.journal, paper.year) if x)
    gap = lambda s, like: audio.silence(like, s)

    # Group clips into chapters.
    chapters: list[tuple[str, list[bytes]]] = []
    for seg, clip in zip(segs, clips):
        if seg.chapter or not chapters:
            chapters.append((seg.chapter or "Ending", []))
        chapters[-1][1].append(clip + gap(seg.pause_after, clip))
    # Fold the closing "End of paper." into the last real chapter.
    if len(chapters) > 1 and chapters[-1][0] == "Ending":
        chapters[-2][1].extend(chapters.pop()[1])

    written: list[str] = []
    if opts.split_tracks:
        os.makedirs(out_path, exist_ok=True)
        n = len(chapters)
        width = max(2, len(str(n)))
        for i, (name, parts) in enumerate(chapters, 1):
            fn = os.path.join(out_path, f"{i:0{width}d} {safe_filename(name, 80)}.mp3")
            with open(fn, "wb") as f:
                f.write(b"".join(parts))
            audio.write_tags(fn, audio.Tags(title=name, artist=artist, album=paper.title, year=paper.year,
                                            comment=comment, cover_jpeg=cover, track=(i, n)))
            written.append(fn)
        base = os.path.join(out_path, safe_filename(paper.title))
    else:
        data = bytearray()
        marks: list[tuple[str, float, float]] = []
        t = 0.0
        for name, parts in chapters:
            blob = b"".join(parts)
            dur = audio.mp3_duration(blob)
            marks.append((name, t, t + dur))
            t += dur
            data += blob
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        audio.write_tags(out_path, audio.Tags(title=paper.title, artist=artist, album=paper.title,
                                              year=paper.year, comment=comment, cover_jpeg=cover),
                         chapters=marks)
        written.append(out_path)
        base = os.path.splitext(out_path)[0]

    if opts.save_transcript:
        with open(base + " - transcript.txt", "w", encoding="utf-8") as f:
            f.write(transcript(segs))
        written.append(base + " - transcript.txt")

    report(1.0, "Done")
    return written
