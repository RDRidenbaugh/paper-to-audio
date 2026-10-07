"""Command-line entry point: python -m paper2audio.cli paper.pdf [-o out.mp3]"""

from __future__ import annotations

import argparse
import os
import sys

from . import audio
from .extract import extract
from .pipeline import Options, build_script, convert, safe_filename, transcript


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert an academic paper PDF into an MP3 you can listen to.")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--output", help="output .mp3 (or folder with --split)")
    ap.add_argument("--voice", default=audio.DEFAULT_VOICE)
    ap.add_argument("--rate", type=int, default=0, help="speed change in percent, e.g. 15 or -10")
    ap.add_argument("--split", action="store_true", help="one track per section")
    ap.add_argument("--captions", action="store_true", help="read figure and table captions")
    ap.add_argument("--back-matter", action="store_true", help="read acknowledgements, funding, references")
    ap.add_argument("--citations", action="store_true", help="keep in-text citations")
    ap.add_argument("--transcript", action="store_true", help="also save the narration text")
    ap.add_argument("--preview", action="store_true", help="print the narration script and exit")
    ap.add_argument("--list-voices", action="store_true")
    a = ap.parse_args(argv)

    if a.list_voices:
        for short, label in audio.list_voices():
            print(f"{short:40} {label}")
        return

    opts = Options(voice=a.voice, rate=a.rate, split_tracks=a.split, include_captions=a.captions,
                   include_back_matter=a.back_matter, keep_citations=a.citations,
                   save_transcript=a.transcript)
    if a.preview:
        paper = extract(a.pdf, opts.include_captions, opts.include_back_matter)
        print(transcript(build_script(paper, opts)))
        return

    out = a.output
    if not out:
        stem = safe_filename(os.path.splitext(os.path.basename(a.pdf))[0])
        out = os.path.join(os.path.dirname(os.path.abspath(a.pdf)), stem if a.split else stem + ".mp3")

    def progress(frac, msg):
        sys.stderr.write(f"\r[{int(frac * 100):3d}%] {msg:<60}")
        sys.stderr.flush()

    files = convert(a.pdf, out, opts, progress=progress)
    sys.stderr.write("\n")
    for f in files:
        print(f)


if __name__ == "__main__":
    main()
