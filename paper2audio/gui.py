"""Desktop front end (Tkinter, ships with Python on macOS and Windows)."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from . import audio
from .extract import extract
from .pipeline import Options, build_script, convert, safe_filename, transcript

APP_NAME = "Paper to Audio"
PREFS_PATH = os.path.join(os.path.expanduser("~"), ".paper2audio.json")
SAMPLE_TEXT = ("Here is how this voice sounds reading a paper. We recovered a well-supported "
               "species tree that was robust to different strategies for analyzing whole-genome data.")


def open_path(path: str) -> None:
    """Open a file or folder with the operating system's default app."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def load_prefs() -> dict:
    try:
        with open(PREFS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_prefs(prefs: dict) -> None:
    try:
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
    except Exception:
        pass


class App(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=16)
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.last_output: str | None = None
        self.voices = list(audio.FEATURED_VOICES)
        prefs = load_prefs()

        self.pdfs: list[str] = []
        self.out_dir = tk.StringVar(value=prefs.get("out_dir", ""))
        self.voice_label = tk.StringVar()
        self.rate = tk.IntVar(value=prefs.get("rate", 0))
        self.split = tk.BooleanVar(value=prefs.get("split", False))
        self.captions = tk.BooleanVar(value=prefs.get("captions", False))
        self.back_matter = tk.BooleanVar(value=prefs.get("back_matter", False))
        self.citations = tk.BooleanVar(value=prefs.get("citations", False))
        self.transcript = tk.BooleanVar(value=prefs.get("transcript", False))
        self.status = tk.StringVar(value="Add a PDF to get started.")
        self.progress = tk.DoubleVar(value=0)

        voice = prefs.get("voice", audio.DEFAULT_VOICE)
        if voice not in dict(self.voices):
            self.voices.append((voice, voice))
        self.voice_label.set(dict(self.voices)[voice])

        self._build()
        self.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)

    # --- layout --------------------------------------------------------------

    def _build(self):
        self.columnconfigure(0, weight=1)

        heading_font = tkfont.nametofont("TkDefaultFont").copy()
        heading_font.configure(size=18, weight="bold")
        title = ttk.Label(self, text=APP_NAME, font=heading_font)
        title.grid(row=0, column=0, sticky="w")
        ttk.Label(self, text="Turn academic papers into MP3s for iTunes, Apple Music, Spotify or any player.",
                  foreground="gray").grid(row=1, column=0, sticky="w", pady=(0, 12))

        # Papers
        files = ttk.LabelFrame(self, text="Papers", padding=10)
        files.grid(row=2, column=0, sticky="nsew")
        files.columnconfigure(0, weight=1)
        files.rowconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.file_list = tk.Listbox(files, height=5, activestyle="none", selectmode="extended")
        self.file_list.grid(row=0, column=0, rowspan=3, sticky="nsew")
        sb = ttk.Scrollbar(files, orient="vertical", command=self.file_list.yview)
        sb.grid(row=0, column=1, rowspan=3, sticky="ns")
        self.file_list.configure(yscrollcommand=sb.set)
        ttk.Button(files, text="Add PDFs…", command=self._add_files).grid(row=0, column=2, sticky="ew", padx=(8, 0))
        ttk.Button(files, text="Remove", command=self._remove_files).grid(row=1, column=2, sticky="ew", padx=(8, 0), pady=4)
        ttk.Button(files, text="Preview text", command=self._preview_text).grid(row=2, column=2, sticky="new", padx=(8, 0))

        # Output
        out = ttk.LabelFrame(self, text="Save to", padding=10)
        out.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        out.columnconfigure(0, weight=1)
        self.out_entry = ttk.Entry(out, textvariable=self.out_dir, width=10)
        self.out_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(out, text="Choose…", command=self._choose_dir).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(out, text="Leave blank to save next to each PDF.", foreground="gray").grid(row=1, column=0, sticky="w")
        fmt = ttk.Frame(out)
        fmt.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Radiobutton(fmt, text="One MP3 with chapter markers", variable=self.split, value=False).pack(side="left")
        ttk.Radiobutton(fmt, text="One track per section (album)", variable=self.split, value=True).pack(side="left", padx=(16, 0))

        # Voice
        v = ttk.LabelFrame(self, text="Voice", padding=10)
        v.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        v.columnconfigure(1, weight=1)
        ttk.Label(v, text="Narrator").grid(row=0, column=0, sticky="w")
        self.voice_box = ttk.Combobox(v, textvariable=self.voice_label, state="readonly",
                                      values=[label for _, label in self.voices])
        self.voice_box.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(v, text="▶ Listen", command=self._preview_voice).grid(row=0, column=2)
        ttk.Button(v, text="More voices…", command=self._more_voices).grid(row=0, column=3, padx=(6, 0))
        ttk.Label(v, text="Speed").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.rate_label = ttk.Label(v, width=6)
        scale = ttk.Scale(v, from_=-30, to=60, variable=self.rate, command=self._on_rate)
        scale.grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
        self.rate_label.grid(row=1, column=2, sticky="w", pady=(8, 0))
        self._on_rate()

        # Content
        c = ttk.LabelFrame(self, text="What to read", padding=10)
        c.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        ttk.Checkbutton(c, text="Figure and table captions", variable=self.captions).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(c, text="In-text citations, e.g. “(Smith et al. 2020)”", variable=self.citations).grid(row=0, column=1, sticky="w", padx=(16, 0))
        ttk.Checkbutton(c, text="Acknowledgements, funding and references", variable=self.back_matter).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(c, text="Also save a text transcript", variable=self.transcript).grid(row=1, column=1, sticky="w", padx=(16, 0))

        # Progress + actions
        bottom = ttk.Frame(self)
        bottom.grid(row=6, column=0, sticky="ew", pady=(14, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Progressbar(bottom, variable=self.progress, maximum=1.0).grid(row=0, column=0, columnspan=4, sticky="ew")
        ttk.Label(bottom, textvariable=self.status, wraplength=520).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.open_btn = ttk.Button(bottom, text="Show files", command=self._open_output, state="disabled")
        self.open_btn.grid(row=1, column=1, padx=(8, 0), pady=(6, 0))
        self.cancel_btn = ttk.Button(bottom, text="Cancel", command=self.cancel.set, state="disabled")
        self.cancel_btn.grid(row=1, column=2, padx=(8, 0), pady=(6, 0))
        self.go_btn = ttk.Button(bottom, text="Create audio", command=self._start)
        self.go_btn.grid(row=1, column=3, padx=(8, 0), pady=(6, 0))
        ttk.Label(self, text="Speech is generated with Microsoft's online neural voices; an internet connection is required.",
                  foreground="gray").grid(row=7, column=0, sticky="w", pady=(10, 0))

    # --- helpers -------------------------------------------------------------

    def _voice_id(self) -> str:
        label = self.voice_label.get()
        return next((vid for vid, lab in self.voices if lab == label), audio.DEFAULT_VOICE)

    def _conversion_options(self) -> Options:
        return Options(voice=self._voice_id(), rate=int(self.rate.get()), split_tracks=self.split.get(),
                       include_captions=self.captions.get(), include_back_matter=self.back_matter.get(),
                       keep_citations=self.citations.get(), save_transcript=self.transcript.get())

    def _save(self):
        save_prefs({"out_dir": self.out_dir.get(), "voice": self._voice_id(), "rate": int(self.rate.get()),
                    "split": self.split.get(), "captions": self.captions.get(),
                    "back_matter": self.back_matter.get(), "citations": self.citations.get(),
                    "transcript": self.transcript.get()})

    def _on_rate(self, *_):
        r = int(round(self.rate.get() / 5) * 5)
        self.rate.set(r)
        self.rate_label.configure(text=f"{1 + r / 100:.2f}×")

    def _busy(self, busy: bool):
        self.go_btn.configure(state="disabled" if busy else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")

    def _run_bg(self, fn, on_done, on_error=None):
        """Run fn() off the UI thread; deliver its result back on the UI thread."""
        def work():
            try:
                self.events.put(("call", on_done, fn()))
            except Exception as e:
                self.events.put(("call", on_error or self._show_error, e))
        threading.Thread(target=work, daemon=True).start()

    def _show_error(self, e: Exception):
        messagebox.showerror(APP_NAME, str(e) or e.__class__.__name__)

    def _poll(self):
        try:
            while True:
                kind, *rest = self.events.get_nowait()
                if kind == "progress":
                    frac, msg = rest
                    self.progress.set(frac)
                    self.status.set(msg)
                elif kind == "call":
                    cb, arg = rest
                    cb(arg)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # --- actions -------------------------------------------------------------

    def _add_files(self):
        paths = filedialog.askopenfilenames(title="Choose papers", filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        self.add_paths(paths)

    def add_paths(self, paths):
        for p in paths:
            if p not in self.pdfs:
                self.pdfs.append(p)
                self.file_list.insert("end", os.path.basename(p))
        if self.pdfs:
            self.status.set(f"{len(self.pdfs)} paper(s) ready.")

    def _remove_files(self):
        for i in reversed(self.file_list.curselection()):
            self.file_list.delete(i)
            del self.pdfs[i]

    def _choose_dir(self):
        d = filedialog.askdirectory(title="Save audio to")
        if d:
            self.out_dir.set(d)

    def _selected_or_first(self) -> str | None:
        sel = self.file_list.curselection()
        if sel:
            return self.pdfs[sel[0]]
        return self.pdfs[0] if self.pdfs else None

    def _preview_text(self):
        pdf = self._selected_or_first()
        if not pdf:
            messagebox.showinfo(APP_NAME, "Add a PDF first.")
            return
        opts = self._conversion_options()
        self.status.set("Extracting text…")

        def build():
            paper = extract(pdf, opts.include_captions, opts.include_back_matter)
            return paper.title, transcript(build_script(paper, opts))

        def show(result):
            title, text = result
            self.status.set("This is exactly what will be read aloud.")
            win = tk.Toplevel(self.root)
            win.title(f"Preview – {title[:60]}")
            win.geometry("760x620")
            txt = tk.Text(win, wrap="word", padx=12, pady=12)
            sb = ttk.Scrollbar(win, command=txt.yview)
            txt.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            txt.pack(fill="both", expand=True)
            txt.insert("1.0", text)
            txt.configure(state="disabled")

        self._run_bg(build, show)

    def _preview_voice(self):
        voice, rate = self._voice_id(), int(self.rate.get())
        self.status.set("Fetching voice sample…")

        def make():
            clip = audio.synthesize([audio.Segment(SAMPLE_TEXT)], voice, rate)[0]
            path = os.path.join(tempfile.gettempdir(), f"paper2audio-sample-{voice}.mp3")
            with open(path, "wb") as f:
                f.write(clip)
            return path

        def play(path):
            self.status.set("Playing sample in your default audio player.")
            open_path(path)

        self._run_bg(make, play)

    def _more_voices(self):
        self.status.set("Loading voice list…")

        def loaded(voices):
            current = self._voice_id()
            featured = {vid for vid, _ in audio.FEATURED_VOICES}
            self.voices = list(audio.FEATURED_VOICES) + [v for v in voices if v[0] not in featured]
            self.voice_box.configure(values=[lab for _, lab in self.voices])
            self.voice_label.set(dict(self.voices).get(current, self.voices[0][1]))
            self.status.set(f"{len(self.voices)} English voices available.")
            self.voice_box.focus_set()

        self._run_bg(lambda: audio.list_voices("en"), loaded)

    def _start(self):
        if not self.pdfs:
            messagebox.showinfo(APP_NAME, "Add at least one PDF first.")
            return
        out_dir = self.out_dir.get().strip()
        if out_dir and not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir)
            except OSError as e:
                messagebox.showerror(APP_NAME, f"Can't use that folder:\n{e}")
                return
        self._save()
        opts = self._conversion_options()
        jobs = list(self.pdfs)
        self.cancel.clear()
        self._busy(True)
        self.open_btn.configure(state="disabled")

        def work():
            written, failures = [], []
            for n, pdf in enumerate(jobs, 1):
                if self.cancel.is_set():
                    break
                folder = out_dir or os.path.dirname(os.path.abspath(pdf))
                stem = safe_filename(os.path.splitext(os.path.basename(pdf))[0])
                target = os.path.join(folder, stem if opts.split_tracks else stem + ".mp3")
                prefix = f"[{n}/{len(jobs)}] " if len(jobs) > 1 else ""

                def progress(frac, msg, n=n, prefix=prefix):
                    self.events.put(("progress", ((n - 1) + frac) / len(jobs), prefix + msg))
                try:
                    written += convert(pdf, target, opts, progress=progress, cancel=self.cancel)
                except audio.Cancelled:
                    break
                except Exception as e:
                    failures.append((os.path.basename(pdf), e))
            return written, failures

        self._run_bg(work, self._finished, on_error=self._finished)

    def _finished(self, result):
        self._busy(False)
        if isinstance(result, Exception):
            self.status.set("Failed.")
            self._show_error(result)
            return
        written, failures = result
        if self.cancel.is_set():
            self.status.set("Cancelled.")
            self.progress.set(0)
        else:
            self.progress.set(1.0 if written else 0)
        if written:
            self.last_output = written[0]
            self.open_btn.configure(state="normal")
            mp3s = [w for w in written if w.endswith(".mp3")]
            if not self.cancel.is_set():
                self.status.set(f"Done – saved {len(mp3s)} MP3 file(s). Add them to your music app to listen.")
        if failures:
            msg = "\n\n".join(f"{name}:\n{err}" for name, err in failures)
            self.status.set(f"{len(failures)} paper(s) failed.")
            messagebox.showerror(APP_NAME, f"Some papers could not be converted:\n\n{msg}")

    def _open_output(self):
        if not self.last_output:
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", self.last_output])          # reveal in Finder
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.last_output)])
        else:
            open_path(os.path.dirname(self.last_output))

    def _on_close(self):
        if self.worker_running() and not messagebox.askyesno(APP_NAME, "A conversion is running. Quit anyway?"):
            return
        self.cancel.set()
        self._save()
        self.root.destroy()

    def worker_running(self) -> bool:
        return str(self.go_btn.cget("state")) == "disabled"


def main():
    root = tk.Tk()
    root.title(APP_NAME)
    root.minsize(640, 600)
    style = ttk.Style(root)
    if sys.platform == "win32" and "vista" in style.theme_names():
        style.theme_use("vista")
    elif sys.platform.startswith("linux") and "clam" in style.theme_names():
        style.theme_use("clam")
    app = App(root)
    app.add_paths([os.path.abspath(p) for p in sys.argv[1:] if p.lower().endswith(".pdf")])
    root.mainloop()


if __name__ == "__main__":
    main()
