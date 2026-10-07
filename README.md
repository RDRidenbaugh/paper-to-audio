# Paper to Audio

Turn academic papers (PDF) into MP3 files you can listen to in Apple Music/iTunes, Spotify (local files), VLC, or any podcast/audiobook player. It runs on macOS and Windows.

It doesn't just read the PDF top to bottom. It handles the things that make journal PDFs unpleasant to listen to:

- **Two-column layouts** are read in the correct order.
- **Running headers, page numbers, watermarks** ("Downloaded from…"), affiliations and figure/table text are dropped.
- **In-text citations** such as `(Linnen and Farrell 2008a; Zhang et al. 2018)` and `[12–16]` are removed so sentences flow. Non-citation asides like `(for example, SNaQ or HyDe)` are kept.
- **References, acknowledgements, funding, data availability** etc. are skipped.
- **Abbreviations and symbols** are spoken naturally: *e.g.* → "for example", *v4.3.3* → "version 4.3.3", *50-kb* → "50-kilobase", *~* → "approximately", *P < 0.05* → "P less than 0.05".
- **Hyphenation** from line breaks is repaired (*concor-dance* → *concordance*, but *gene-tree* stays).
- **Sections become chapters.** You get either one MP3 with chapter markers or one track per section, tagged as an album with the paper's title, authors, year and the first page as cover art.

`example_output/` contains the result for the included paper (Herrig et al. 2024): 72 minutes, 15 chapters, plus the transcript of exactly what is spoken.

## Running it

### Option A – double-click launcher (easiest)

1. Install **Python 3.10 or newer** from [python.org/downloads](https://www.python.org/downloads/).
   - Windows: tick **"Add python.exe to PATH"** in the installer.
   - macOS: the python.org installer includes the GUI toolkit (Tkinter). If you use Homebrew Python instead, also run `brew install python-tk`.
2. Copy this folder to the computer and double-click:
   - **macOS:** `Start Paper to Audio.command`. The first time, macOS may block it: right-click it, choose **Open**, then **Open** again.
   - **Windows:** `Start Paper to Audio.bat`
3. The first launch takes about a minute while it installs its components into a private `.venv` folder. Later launches start straight away.

### Option B – build a standalone app

This produces an app you can give to people who don't have Python. Run it on each OS you want to support, because PyInstaller can't cross-compile:

```
python build_app.py
```

- macOS: `dist/Paper to Audio.app` (drag it to Applications)
- Windows: `dist/Paper to Audio.exe`

Unsigned apps trigger a warning the first time they open. On macOS, right-click and choose Open. On Windows, click "More info" and then "Run anyway".

### Option C – command line

```
pip install -r requirements.txt
python -m paper2audio.cli paper.pdf                 # -> paper.mp3 next to the PDF
python -m paper2audio.cli paper.pdf --split         # one track per section
python -m paper2audio.cli paper.pdf --preview       # print what would be read, no audio
python -m paper2audio.cli --list-voices
```

Options: `--voice en-GB-SoniaNeural`, `--rate 15` (15% faster), `--captions`, `--citations`, `--back-matter`, `--transcript`.

## Using the app

1. **Add PDFs…** You can queue several papers.
2. **Preview text** (optional) shows exactly what will be read aloud, so you can check a paper extracted cleanly before spending time on audio.
3. Choose a **voice** (press **Listen** to hear a sample; **More voices…** loads every English voice), a **speed**, and what to include.
4. **Create audio.** A typical 20-page paper takes 3–7 minutes and produces about an hour of audio.
5. **Show files** opens the output folder.

Your settings are remembered between sessions.

### Getting it into your music app

- **Apple Music / iTunes (Mac or Windows):** drag the MP3 (or the folder of tracks) into the window, or use File → Add to Library. To make it remember your position and skip it in shuffle: right-click → Get Info → Options → set *media kind* to **Audiobook**. To get it onto an iPhone, sync with Finder/iTunes.
- **Spotify:** Settings → *Your Library* → turn on **Show Local Files** and add the output folder. Files show up under *Local Files*. To play on your phone, add them to a playlist and download that playlist on the phone while it's on the same Wi-Fi as the computer.
- **Chapters:** the single-file mode embeds standard ID3 chapter markers, which podcast and audiobook apps (Overcast, Pocket Casts, BookPlayer, VLC, foobar2000) show. Apple Music and Spotify don't show MP3 chapters. If you want to jump between sections in those apps, use **One track per section**.

## Notes and limitations

- **Internet required.** Speech uses Microsoft Edge's free online neural voices (through the `edge-tts` package). These voices sound much better than the built-in offline ones. The paper's text is sent to that service for synthesis, so don't use this for anything confidential.
- **Scanned PDFs** (images of pages without a text layer) can't be read. Run OCR on them first, for example with Adobe Acrobat or `ocrmypdf`.
- **Equations and tables** are skipped or read literally. Results that only exist in a table won't be narrated, so turn on *Figure and table captions* if you want the captions.
- Extraction is heuristic. It's tuned on standard journal layouts and works best on publisher PDFs with embedded section bookmarks (most have them). If a paper comes out oddly, *Preview text* will show where.

## Project layout

```
paper_to_audio.py              GUI entry point (also what build_app.py packages)
paper2audio/extract.py         PDF -> ordered sections of body text
paper2audio/speech.py          text cleanup for listening (citations, units, symbols…)
paper2audio/audio.py           speech synthesis, MP3 joining, ID3 tags and chapters
paper2audio/pipeline.py        ties it together; shared by GUI and CLI
paper2audio/gui.py             Tkinter desktop app
paper2audio/cli.py             command-line interface
Start Paper to Audio.command   macOS launcher
Start Paper to Audio.bat       Windows launcher
build_app.py                   builds a standalone .app / .exe with PyInstaller
```
