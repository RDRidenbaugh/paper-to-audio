"""Pull the readable body of an academic paper out of a PDF.

Journal PDFs are hostile to naive text extraction: two-column layouts,
running headers, page numbers, rotated watermarks, figure labels, tables,
captions and a long reference list. This module keeps only the prose a
listener wants, grouped into sections so the audio can have chapters.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

# Sections that are almost never worth listening to. Matched against the
# lower-cased heading with leading numbering removed.
BACK_MATTER = (
    "references", "bibliography", "literature cited", "works cited",
    "acknowledgements", "acknowledgments", "acknowledgement", "acknowledgment",
    "funding", "conflict of interest", "conflicts of interest",
    "competing interests", "declaration of competing interest",
    "data availability", "data availability statement", "data accessibility",
    "supplementary material", "supplementary materials",
    "supplementary information", "supporting information",
    "author contributions", "author contribution", "credit authorship contribution statement",
    "ethics statement", "appendix",
)
# Image payloads are huge in figure-heavy papers and we never use them.
TEXT_FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES

# Once one of these is reached, everything after it is dropped.
END_OF_BODY = ("references", "bibliography", "literature cited", "works cited")

CAPTION_RE = re.compile(r"^(fig\.?|figure|table|supplementary (fig|table))\s*S?\d+", re.I)
ABSTRACT_RE = re.compile(r"^\s*abstract\b", re.I)
# Keyword lists: a "Keywords: ..." / "Key words" / "Index Terms" line, or a bracketed
# "[term; term; term.]" list closing the abstract (Systematic Biology style).
KEYWORDS_RE = re.compile(r"^\s*(key\s*-?\s*words?|index terms)\b", re.I)
KEYWORDS_TAIL_RE = re.compile(
    r"\s*(?:\[[^\[\]]+;[^\[\]]+\]|(?:key\s*-?\s*words?|index terms)\s*[:.—–-].*)\s*$", re.I | re.S)
PARAGRAPH_END = re.compile(r"[.?!][”\"’')\]]*$")


@dataclass
class Section:
    title: str
    level: int = 1
    paragraphs: list[str] = field(default_factory=list)
    captions: list[str] = field(default_factory=list)
    parent: str = ""            # enclosing top-level section, e.g. "Results"
    opens_parent: bool = False  # first subsection after an otherwise empty parent heading

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)

    @property
    def full_title(self) -> str:
        return f"{self.parent}: {self.title}" if self.parent else self.title


@dataclass
class Paper:
    title: str
    authors: list[str]
    journal: str
    year: str
    sections: list[Section]


@dataclass
class _Block:
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    size: float          # dominant font size
    font: str            # dominant font name
    bold: bool
    italic: bool


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _heading_key(s: str) -> str:
    s = _norm(s).lower()
    s = re.sub(r"^(\d+(\.\d+)*|[ivxlc]+)[.)]?\s+", "", s)  # "2.1 Methods", "IV. Results"
    return s.strip(" .:")


def _block_from_dict(b: dict, page_no: int, doc_words: Counter) -> _Block | None:
    lines_out: list[str] = []
    chars = Counter()
    fonts = Counter()
    bold = italic = 0
    total = 0
    for line in b["lines"]:
        dx, dy = line["dir"]
        if abs(dy) > 0.1:            # rotated text: watermarks, axis labels
            return None
        pieces = []
        body_sizes = [s["size"] for s in line["spans"] if s["text"].strip()]
        line_size = max(body_sizes) if body_sizes else 0
        full = [s for s in line["spans"] if s["text"].strip() and s["size"] >= 0.9 * line_size]
        baseline = max((s["origin"][1] for s in full), default=0)
        for s in line["spans"]:
            t = s["text"]
            if not t:
                continue
            # Superscripts (citation numbers, affiliation markers, footnotes)
            small = s["flags"] & 1 or s["size"] < 0.75 * line_size
            # Superscripts (raised) are citation/footnote markers; subscripts (F2, H2O) are content.
            if small and s["origin"][1] < baseline - 0.5 and re.fullmatch(r"[\s\d,*†‡§¶–\-]+", t):
                continue
            pieces.append(t)
            n = len(t.strip())
            chars[round(s["size"], 1)] += n
            fonts[s["font"]] += n
            total += n
            if s["flags"] & 16 or "bold" in s["font"].lower():
                bold += n
            if s["flags"] & 2 or "italic" in s["font"].lower() or "oblique" in s["font"].lower():
                italic += n
        lines_out.append("".join(pieces))
    if total == 0:
        return None
    text = _join_lines(lines_out, doc_words)
    if not text.strip():
        return None
    return _Block(
        page=page_no,
        bbox=tuple(b["bbox"]),
        text=text,
        size=chars.most_common(1)[0][0],
        font=fonts.most_common(1)[0][0],
        bold=bold > 0.8 * total,
        italic=italic > 0.8 * total,
    )


def _join_lines(lines: list[str], doc_words: Counter) -> str:
    """Join wrapped lines, undoing typesetter hyphenation."""
    out = ""
    for raw in lines:
        line = raw.replace(" ", " ").replace(" ", " ").rstrip()
        if not line:
            continue
        if not out:
            out = line.lstrip()
            continue
        if out.endswith("­"):                      # soft hyphen: always a word break
            out = out[:-1] + line.lstrip()
        elif out.endswith("-") and not out.endswith(" -"):
            # Hard hyphen at line end: "gene-\ntree" keeps it, "concor-\ndance" drops it.
            head = re.search(r"(\w+)-$", out)
            tail = re.match(r"\s*(\w+)", line)
            if head and tail and tail.group(1)[0].islower():
                joined = (head.group(1) + tail.group(1)).lower()
                hyph = f"{head.group(1)}-{tail.group(1)}".lower()
                if doc_words[joined] > doc_words[hyph]:
                    out = out[:-1] + line.lstrip()
                    continue
            out += line.lstrip()
        else:
            out += " " + line.lstrip()
    out = re.sub(r"­\s*", "", out)
    return re.sub(r"[ \t]+", " ", out).strip()


def _reading_order(blocks: list[_Block], page_width: float) -> list[_Block]:
    """Order blocks for single- or multi-column pages.

    Full-width blocks act as horizontal separators; between separators the
    left column is read top-to-bottom before the right column.
    """
    mid = page_width / 2
    full = lambda b: (b.bbox[2] - b.bbox[0]) > 0.6 * page_width or (b.bbox[0] < mid - 20 and b.bbox[2] > mid + 20)
    blocks = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
    ordered: list[_Block] = []
    band: list[_Block] = []

    def flush():
        left = [b for b in band if (b.bbox[0] + b.bbox[2]) / 2 < mid]
        right = [b for b in band if (b.bbox[0] + b.bbox[2]) / 2 >= mid]
        ordered.extend(sorted(left, key=lambda b: b.bbox[1]))
        ordered.extend(sorted(right, key=lambda b: b.bbox[1]))
        band.clear()

    for b in blocks:
        if full(b):
            flush()
            ordered.append(b)
        else:
            band.append(b)
    flush()
    return ordered


def _repeated_margin_text(doc: pymupdf.Document) -> set[str]:
    """Text that recurs in page margins (running heads, journal footers)."""
    seen = Counter()
    for page in doc:
        h = page.rect.height
        for b in page.get_text("blocks"):
            if b[1] < 0.1 * h or b[3] > 0.9 * h:
                seen[_margin_key(b[4])] += 1
    threshold = max(2, doc.page_count // 3)
    return {k for k, n in seen.items() if n >= threshold and k}


def _margin_key(text: str) -> str:
    # Strip digits so "SYSTEMATIC BIOLOGY 842" and "... 844" collapse together.
    return re.sub(r"[\d\s]+", " ", text).strip().lower()


def _is_heading(b: _Block, body_size: float, toc_titles: set[str]) -> bool:
    words = b.text.split()
    if not words or len(words) > 18:
        return False
    key = _heading_key(b.text)
    if toc_titles:
        return key in toc_titles
    if b.text.rstrip().endswith((".", ",", ";")) and not re.match(r"^\d+(\.\d+)*\.?\s", b.text):
        return False
    if key in BACK_MATTER or key in ("introduction", "abstract", "background", "methods",
                                       "materials and methods", "results", "discussion",
                                       "conclusion", "conclusions", "results and discussion"):
        return True
    return b.size > body_size + 0.5 or b.bold


def _toc_titles(doc: pymupdf.Document) -> tuple[set[str], dict[str, int]]:
    titles, levels = set(), {}
    for level, title, _page in doc.get_toc():
        if level == 1:          # usually the paper title itself
            continue
        # Run-in paragraph heads ("Genome assembly.—Following ...") show up as long
        # TOC entries; they are read inline instead of becoming chapters.
        if len(title.split()) > 18 or "—" in title:
            continue
        k = _heading_key(title)
        titles.add(k)
        levels[k] = level - 1
    return titles, levels


def extract(path: str, include_captions: bool = False, include_back_matter: bool = False,
            progress=None) -> Paper:
    doc = pymupdf.open(path)
    if doc.needs_pass:
        raise ValueError("This PDF is password-protected.")

    # Word frequencies for hyphenation repair.
    doc_words = Counter(w.lower() for page in doc for w in re.findall(r"[\w-]+", page.get_text()))
    margin_text = _repeated_margin_text(doc)
    toc_titles, toc_levels = _toc_titles(doc)

    blocks: list[_Block] = []
    for i, page in enumerate(doc):
        if progress:
            progress(i / doc.page_count, f"Reading page {i + 1} of {doc.page_count}")
        raw = [_block_from_dict(b, i, doc_words) for b in page.get_text("dict", flags=TEXT_FLAGS)["blocks"] if b["type"] == 0]
        raw = [b for b in raw if b]
        h = page.rect.height
        kept = []
        for b in raw:
            in_margin = b.bbox[1] < 0.1 * h or b.bbox[3] > 0.9 * h
            if in_margin and (_margin_key(b.text) in margin_text or re.fullmatch(r"[\d\s]+", b.text)):
                continue
            kept.append(b)
        blocks.extend(_reading_order(kept, page.rect.width))

    if not blocks:
        raise ValueError("No text found. This PDF may be a scanned image; run OCR on it first.")

    # The body font size is the one carrying the most characters.
    size_chars = Counter()
    font_chars = Counter()
    for b in blocks:
        size_chars[b.size] += len(b.text)
        font_chars[b.font.split("-")[0]] += len(b.text)
    body_size = size_chars.most_common(1)[0][0]
    body_family = font_chars.most_common(1)[0][0]

    meta = doc.metadata or {}
    title = _norm(meta.get("title") or "")
    if not title or len(title) < 8 or title.lower().endswith((".pdf", ".doc", ".docx")):
        first = [b for b in blocks if b.page == 0]
        biggest = max(first, key=lambda b: b.size) if first else None
        title = biggest.text if biggest else "Untitled paper"
        # Titles often wrap into two blocks of the same size.
        if biggest:
            same = [b.text for b in first if b.size == biggest.size]
            title = _norm(" ".join(same))
    front, byline = _front_matter(blocks, title)
    authors = byline or [a.strip() for a in re.split(r",| and |;", meta.get("author") or "") if a.strip()]
    journal, year = _journal_and_year(meta, blocks)

    sections: list[Section] = [Section("Introduction", 1)]
    abstract: Section | None = None
    title_key = _heading_key(title)
    skipping = False
    ended = False

    for idx, b in enumerate(blocks):
        if ended:
            break
        if idx in front:
            continue
        family = b.font.split("-")[0]
        text = b.text

        # Headings that wrap over two lines are often split into two blocks.
        prev = sections[-1]
        if toc_titles and not prev.paragraphs and not prev.captions and len(sections) > 1:
            joined = _heading_key(prev.title + " " + text)
            if joined in toc_titles or any(t.startswith(joined) for t in toc_titles):
                prev.title = _norm(prev.title + " " + text)
                prev.level = toc_levels.get(joined, prev.level)
                continue

        if _is_heading(b, body_size, toc_titles) and _heading_key(text) != title_key:
            key = _heading_key(text)
            if key in END_OF_BODY and not include_back_matter:
                ended = True
                continue
            skipping = key in BACK_MATTER and not include_back_matter
            sections.append(Section(_norm(text), toc_levels.get(key, 1 if (b.size > body_size or not b.italic) else 2)))
            continue

        # First line of a two-line heading only matches the TOC once joined.
        if toc_titles and len(text.split()) <= 14 and not text.rstrip().endswith("."):
            key = _heading_key(text)
            if any(t.startswith(key + " ") for t in toc_titles):
                skipping = False
                sections.append(Section(_norm(text), 1))
                continue

        if ABSTRACT_RE.match(text) and abstract is None:
            body = re.sub(r"^\s*abstract\s*[.:—–-]*\s*", "", text, flags=re.I)
            body = KEYWORDS_TAIL_RE.sub("", body)
            abstract = Section("Abstract", 1, [body])
            continue

        if KEYWORDS_RE.match(text):
            continue

        if CAPTION_RE.match(text):
            if include_captions and not skipping:
                sections[-1].captions.append(text)
            continue

        if skipping:
            continue
        # Body prose only: same font family, close to body size, and actual sentences.
        if family != body_family or abs(b.size - body_size) > 0.6:
            continue
        if len(text.split()) < 4 and not sections[-1].paragraphs:
            continue
        if b.page == 0 and not any(s.paragraphs for s in sections) and _looks_like_front_matter(text):
            continue

        sec = sections[-1]
        # A paragraph split across a column or page break continues mid-sentence.
        prev_para = sec.paragraphs[-1] if sec.paragraphs else ""
        unfinished = prev_para and (not PARAGRAPH_END.search(prev_para.rstrip())
                                    or prev_para.count("(") > prev_para.count(")")
                                    or text[:1].islower())
        if unfinished:
            sec.paragraphs[-1] = _join_continuation(sec.paragraphs[-1], text, doc_words)
        else:
            sec.paragraphs.append(text)

    if abstract:
        sections.insert(0, abstract)
    sections = _nest(sections)
    if progress:
        progress(1.0, "Text extracted")
    return Paper(title=title, authors=authors, journal=journal, year=year, sections=sections)


def _nest(sections: list[Section]) -> list[Section]:
    """Attach subsections to their parent and drop heading-only sections."""
    out: list[Section] = []
    top, pending = "", False
    for s in sections:
        if s.level <= 1:
            top = s.title
            pending = not (s.paragraphs or s.captions)
            if not pending:
                out.append(s)
            continue
        if not (s.paragraphs or s.captions):
            continue
        s.parent = top
        s.opens_parent = pending
        pending = False
        out.append(s)
    return out


def _split_names(text: str) -> list[str]:
    text = re.sub(r"[*†‡§¶\d]+", "", text)
    parts = re.split(r",\s*(?:and\s+)?|\s+and\s+|;", text)
    return [_norm(p) for p in parts if _norm(p)]


def _is_byline(text: str) -> bool:
    if _looks_like_front_matter(text) or len(text.split()) > 80:
        return False
    names = _split_names(text)
    if len(names) < 1 or not all(1 <= len(n.split()) <= 5 for n in names):
        return False
    words = [w for n in names for w in n.split()]
    caps = sum(1 for w in words if w[:1].isupper())
    ends_ok = not text.rstrip().endswith((".", "?", "!")) or bool(re.search(r"\b[A-Z]\.$", text.strip()))
    return caps >= 0.8 * len(words) and ends_ok


def _front_matter(blocks: list[_Block], title: str) -> tuple[set[int], list[str]]:
    """Indices of first-page blocks before the abstract/body, plus the author byline."""
    first = [i for i, b in enumerate(blocks) if b.page == 0]
    if not first:
        return set(), []
    cutoff = None
    for i in first:
        if ABSTRACT_RE.match(blocks[i].text):
            cutoff = i
            break
    if cutoff is None:
        cutoff = next((i for i in first if len(blocks[i].text.split()) >= 40), first[-1] + 1)
    front = {i for i in first if i < cutoff}
    authors: list[str] = []
    for i in sorted(front):
        t = _norm(blocks[i].text)
        if t.lower() in title.lower() or blocks[i].size > max(b.size for b in blocks) - 0.1:
            continue
        if _is_byline(t):
            authors = _split_names(blocks[i].text)
            break
    return front, authors


def _join_continuation(prev: str, nxt: str, doc_words: Counter) -> str:
    return _join_lines([prev, nxt], doc_words)


def _looks_like_front_matter(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ("@", "university", "department", "received", "accepted",
                                 "correspondence", "doi", "editor", "copyright", "©", "licence", "license"))


def _journal_and_year(meta: dict, blocks: list[_Block]) -> tuple[str, str]:
    subject = meta.get("subject") or ""
    journal, year = "", ""
    m = re.search(r"\b(19|20)\d{2}\b", subject)
    if m:
        year = m.group(0)
    for part in re.split(r"[\r\n]+", subject):
        if "," in part and not part.lower().startswith(("doi", "abstract", "associate")):
            journal = part.split(",")[0].strip()
            break
    if not year:
        for b in blocks[:15]:
            m = re.search(r"\b(19|20)\d{2}\b", b.text)
            if m:
                year = m.group(0)
                break
    if not year:
        m = re.search(r"(19|20)\d{2}", meta.get("creationDate") or "")
        year = m.group(0) if m else ""
    return journal, year
