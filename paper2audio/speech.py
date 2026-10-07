"""Rewrite extracted paper text so it sounds natural when read aloud."""

from __future__ import annotations

import re

# One author-year citation: "Linnen and Farrell 2008a", "Hey and Nielsen 2004",
# "Zhang et al. 2018a, 2018b", "Betancur-R. et al. 2013", "Maynard Smith and Haigh 1974".
_NAME = r"(?:(?:de|van|von|der|den|la|le|du|da|di)\s+)*[A-Z][\w'’\-.]*(?:\s+[A-Z][\w'’\-.]*)?"
_YEAR = r"(?:19|20)\d{2}[a-z]?|in press|forthcoming|unpubl(?:ished)?(?: data)?|submitted|n\.d\."
_AUTHORS = rf"{_NAME}(?:\s*(?:,|and|&)\s*{_NAME})*(?:\s+et\s+al\.?)?"
_CITE = rf"(?:{_AUTHORS}),?\s+(?:{_YEAR})(?:\s*,\s*(?:{_YEAR}))*"
# Case-sensitive on purpose: a citation must start with a capitalised author name.
_CITE_STRICT = re.compile(
    rf"^\s*(?:(?:e\.g\.|i\.e\.|[Ss]ee(?: also)?|cf\.|reviewed in|but see|as in)\s*,?\s*)?{_CITE}\s*$")
_YEAR_ONLY = re.compile(rf"^\s*(?:{_YEAR})(?:\s*[,;]\s*(?:{_YEAR}))*\s*$")
_NUMERIC = re.compile(r"\[\s*\d+(?:\s*[-–,]\s*\d+)*\s*\]")
_FIG_REF = re.compile(
    r"^\s*(?:see\s+)?(?:(?:supplementary|suppl\.?)\s+)?(?:fig(?:ure)?s?\.?|tables?|eqs?\.?|equations?|appendix|sections?)"
    r"\s*S?\d+[a-z]?(?:[\s,–\-and]+S?\d*[a-z]?)*\s*$", re.I)

ABBREVIATIONS = [
    (r"\be\.g\.,?", "for example,"),
    (r"\bi\.e\.,?", "that is,"),
    (r"\bcf\.", "compare"),
    (r"\bet al\.", "and colleagues"),
    (r"\bvs\.", "versus"),
    (r"\bv\.?\s?(?=\d)", "version "),
    (r"\bapprox\.", "approximately"),
    (r"\bresp\.", "respectively"),
    (r"\bFigs?\.\s*", "Figure "),
    (r"\bEqs?\.\s*", "Equation "),
    (r"\bSect?\.\s*", "Section "),
    (r"\bca\.\s*(?=\d)", "about "),
    (r"\bno\.\s*(?=\d)", "number "),
    (r"\bspp\.", "species"),
    (r"\bsp\.(?=\s)", "species"),
]

UNITS = {
    "kb": "kilobases", "Kb": "kilobases", "Mb": "megabases", "MB": "megabases",
    "Gb": "gigabases", "bp": "base pairs", "µL": "microliters", "μL": "microliters",
    "mL": "milliliters", "µm": "micrometers", "μm": "micrometers", "nm": "nanometers",
    "mm": "millimeters", "cm": "centimeters", "km": "kilometers", "mg": "milligrams",
    "kg": "kilograms", "°C": "degrees Celsius", "ng": "nanograms", "µg": "micrograms",
    "μg": "micrograms", "Myr": "million years", "Ma": "million years ago", "kya": "thousand years ago",
}

SYMBOLS = [
    ("≤", " less than or equal to "), ("≥", " greater than or equal to "),
    ("≈", " approximately "), ("±", " plus or minus "), ("×", " times "),
    ("→", " to "), ("<", " less than "), (">", " greater than "),
    ("~", " approximately "), ("∼", " approximately "),
    ("α", "alpha"), ("β", "beta"), ("γ", "gamma"), ("δ", "delta"), ("Δ", "delta"),
    ("θ", "theta"), ("λ", "lambda"), ("μ", "mu"), ("π", "pi"), ("σ", "sigma"),
    ("τ", "tau"), ("χ", "chi"), ("ω", "omega"), ("ρ", "rho"), ("ε", "epsilon"),
    ("²", " squared"), ("³", " cubed"),
]


def _strip_parenthetical(text: str, keep_figure_refs: bool) -> str:
    """Remove citations (and optionally figure refs) from (...) groups, keeping other asides."""
    # Walk manually so nested parentheses like "(i.e., incomplete lineage sorting (ILS))" survive.
    result: list[str] = []
    stack: list[int] = []
    spans: list[tuple[int, int]] = []
    for i, c in enumerate(text):
        if c == "(":
            stack.append(i)
        elif c == ")" and stack:
            spans.append((stack.pop(), i))
    # Innermost first; replacements are tracked by marking characters for deletion/rewrite.
    replace: dict[int, tuple[int, str]] = {}
    for a, b in sorted(spans, key=lambda s: s[1] - s[0]):
        if any(a < x < b for x in replace):  # contains an already-rewritten group; leave outer alone
            continue
        inner = text[a + 1:b]
        new = _clean_group(inner, keep_figure_refs)
        if new != inner:
            replace[a] = (b, "" if not new else f"({new})")
    pos = 0
    for a in sorted(replace):
        if a < pos:
            continue
        b, rep = replace[a]
        result.append(text[pos:a])
        result.append(rep)
        pos = b + 1
    result.append(text[pos:])
    return "".join(result)


def _clean_group(inner: str, keep_figure_refs: bool) -> str:
    parts = [p.strip() for p in inner.split(";")]
    kept = []
    for p in parts:
        if not p:
            continue
        if _CITE_STRICT.match(p) or _YEAR_ONLY.match(p):
            continue
        if not keep_figure_refs and _FIG_REF.match(p):
            continue
        # "e.g., SNaQ, ABBA-BABA tests, or HyDe" stays; a trailing ", Smith 2010" goes.
        p2 = re.sub(rf",\s*{_CITE}\s*$", "", p)
        kept.append(p2 if not _CITE_STRICT.match(p2) else "")
    kept = [k for k in kept if k and k.lower() not in ("e.g.", "e.g.,", "see", "see also", "cf.")]
    return "; ".join(kept)


def _expand_units(text: str) -> str:
    for unit, word in UNITS.items():
        u = re.escape(unit)
        # "50-kb windows" -> "50-kilobase windows" (adjectival, singular)
        text = re.sub(rf"(\d)\s*-\s*{u}\b", lambda m: f"{m.group(1)}-{word.rstrip('s')}", text)
        text = re.sub(rf"(\d)\s*{u}(?![\w])", lambda m: f"{m.group(1)} {word}", text)
    return text


def _protect(m: re.Match) -> str:
    # Non-breaking hyphens survive the "1-5 -> 1 to 5" range rule below.
    return m.group(0).replace("-", "\u2011")


def _numbers(text: str) -> str:
    text = re.sub(r"\bversion \S+", _protect, text)                     # v2.1-0
    text = re.sub(r"\b(19|20)\d{2}-\d{2}(-\d{2})?\b", _protect, text)  # ISO dates
    text = re.sub(r"\b[A-Z]{2,}\d*-\d+", _protect, text)                 # accession-like IDs
    text = re.sub(r"(\d),(\d{3})\b", r"\1\2", text)                    # 14,732 -> 14732
    text = re.sub(r"(\d)\s*[–-]\s*(\d)", r"\1 to \2", text)            # 1990–2000 -> 1990 to 2000
    text = re.sub(r"(\d)\s*%", r"\1 percent", text)
    text = re.sub(r"\bP\s*([<=>])\s*", lambda m: "P " + {"<": "less than ", "=": "equals ", ">": "greater than "}[m.group(1)], text)
    text = re.sub(r"\bp\s*([<=>])\s*", lambda m: "p " + {"<": "less than ", "=": "equals ", ">": "greater than "}[m.group(1)], text)
    text = re.sub(r"(\d)\s*=\s*(\d)", r"\1 equals \2", text)
    text = re.sub(r"\b([A-Za-z])\s*=\s*", r"\1 equals ", text)
    return text


def prepare(text: str, keep_citations: bool = False, keep_figure_refs: bool = False) -> str:
    t = text
    # Links and addresses: name them instead of spelling them out; keep trailing punctuation.
    end = r"(?=[.,;:)\]]*(?:\s|$))"
    t = re.sub(rf"(?:https?://|www\.|doi:\s*)\S+?{end}|\b10\.\d{{4,}}/\S+?{end}", "a link", t)
    t = re.sub(rf"[\w.+-]+@[\w-]+\.[\w.-]+?{end}", "an email address", t)
    t = t.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    if not keep_citations:
        t = _NUMERIC.sub("", t)
        t = _strip_parenthetical(t, keep_figure_refs)
        # Narrative citations "Linnen and Farrell (2008a)" lose the bare year.
        t = re.sub(r"\s*\(\s*\)", "", t)
    elif not keep_figure_refs:
        t = _strip_parenthetical_figs(t)
    for pat, rep in ABBREVIATIONS:
        t = re.sub(pat, rep, t)
    t = _expand_units(t)
    t = _numbers(t)
    for sym, word in SYMBOLS:
        t = t.replace(sym, word)
    t = t.replace("—", ", ").replace("–", "-")
    # Tidy whitespace and punctuation left behind by removals.
    t = re.sub(r"\s+([,.;:)])", r"\1", t)
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r",\s*,", ",", t)
    t = re.sub(r"([.;:]),", r"\1", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def _strip_parenthetical_figs(text: str) -> str:
    return re.sub(r"\(([^()]*)\)", lambda m: "" if _FIG_REF.match(m.group(1)) else m.group(0), text)


def chunk(text: str, limit: int = 3000) -> list[str]:
    """Split text at sentence boundaries into pieces the TTS service accepts comfortably."""
    if len(text) <= limit:
        return [text] if text.strip() else []
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])", text)
    pieces, cur = [], ""
    for s in sentences:
        while len(s) > limit:                      # pathological run-on
            cut = s.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(s[:cut])
            s = s[cut:].lstrip()
        if len(cur) + len(s) + 1 > limit and cur:
            pieces.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}" if cur else s
    if cur:
        pieces.append(cur)
    return pieces
