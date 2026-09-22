#!/usr/bin/env python3
"""
Build assets/data/bibliography.json from one or more BibLaTeX (.bib) files.

Usage:
    python3 scripts/build_bibliography.py

Reads the .bib files listed in SOURCES below (relative to the repo root),
parses them with bibtexparser 2.x, and writes a single JSON array to
assets/data/bibliography.json for the client-side search page to load.

Fields that hold personal working notes or local file-system paths
(Zotero's file/owner/creationdate/modificationdate/annotation/source
fields, etc.) are deliberately dropped -- they are not bibliographic
data and were never meant to be public. See README.md for the full
list and the reasoning.
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import bibtexparser
from indic_transliteration import sanscript

ROOT = Path(__file__).resolve().parent.parent

# Each source .bib file, and the "collection" tag its entries get in the
# output (so the site can filter/label by which file an entry came from).
SOURCES = [
    ("biblio4-utf8.bib", "main", "Main bibliography"),
    ("mbh-vols.bib", "mahabhasya-volumes", "Patañjali's Mahābhāṣya (Joshi & Roodbergen volumes)"),
    ("incremental_SS_Translation.bib", "incremental-translation", "Specific bib for the Suśruta Project translation book"),
]

# Glossary databases (bib2gls/glossaries-extra format: @Entry with Name +
# Description). Handled separately from the bibliography -- see glossary.py.
GLOSSARIES = [
    ("plants.bib", "plants", "Flora (plants.bib)", "Plant"),
    ("animals.bib", "animals", "Fauna (animals.bib)", "Animal"),
    ("minerals.bib", "minerals", "Minerals (minerals.bib)", "Mineral"),
]

# Fields that are personal working notes, local file paths, or otherwise
# not meant for public display. Dropped from both the JSON record and the
# cleaned BibTeX text shown in the "Copy BibTeX" box.
PRIVATE_FIELDS = {
    "file", "owner", "creationdate", "modificationdate",
    "annotation", "annote", "source", "refid", "size",
}

# Fields that are just bookkeeping duplicates of the entry key or are too
# noisy to be worth carrying into the structured JSON (they are still
# stripped from the copyable BibTeX via PRIVATE_FIELDS if listed there;
# these are additionally left out of the structured record).
SKIP_IN_RECORD = PRIVATE_FIELDS | {"citationkey"}

LATEX_MACRO_STRIP = re.compile(
    r"\\(emph|textit|textbf|textsc|mkbibemph|mkbibbold|dev|foreignlanguage|textsuperscript|textsubscript)\{([^{}]*)\}"
)
LATEX_SIMPLE_ESCAPES = {
    r"\&": "&", r"\%": "%", r"\_": "_", r"\$": "$", r"\#": "#",
    r"\{": "{", r"\}": "}", r"\textasciitilde": "~",
    r"\ldots": "\u2026", r"\dots": "\u2026",
    r"\textendash": "\u2013", r"\textemdash": "\u2014",
    r"\textquotedblleft": "\u201c", r"\textquotedblright": "\u201d",
    r"\textquoteleft": "\u2018", r"\textquoteright": "\u2019",
    r"\textquotesingle": "'", r"\slash": "/", r"\ae": "\u00e6",
    "\\ ": " ", r"\,": " ",
}
# Old-style TeX accent commands (predating this file's mostly-UTF-8 text) --
# converted to a base letter + Unicode combining mark, then NFC-normalized
# to a single precomposed character (e.g. \'e -> e + COMBINING ACUTE -> é).
TEX_ACCENT_COMBINING = {
    "'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308",
    "~": "\u0303", "=": "\u0304", ".": "\u0307",
}
TEX_ACCENT_SYMBOL_RE = re.compile(r"\\(['`^\"~=.])\{?([A-Za-z])\}?")
TEX_ACCENT_LETTER_RE = re.compile(r"\\(c|d)\{([A-Za-z])\}")  # cedilla, dot-below
TEX_BARE_MACRO_RE = re.compile(r"\\(cjk|textrussian)\b")  # macros used without {} in this file


def convert_tex_accents(s):
    # Dotless i/j (\i, \j) appear inside accent commands like {\=\i} for ī;
    # normalize them to plain letters first so the accent regex below can match.
    s = re.sub(r"\\([ij])(?![a-zA-Z])", r"\1", s)
    s = TEX_ACCENT_SYMBOL_RE.sub(lambda m: m.group(2) + TEX_ACCENT_COMBINING[m.group(1)], s)
    s = TEX_ACCENT_LETTER_RE.sub(
        lambda m: m.group(2) + ("\u0327" if m.group(1) == "c" else "\u0323"), s
    )
    return unicodedata.normalize("NFC", s)


def ensure_period(s):
    """Append a period unless the string already ends with sentence
    punctuation (handles abbreviations like 'R. I.' reasonably)."""
    s = s.rstrip()
    if not s:
        return s
    return s if s[-1] in ".?!" else s + "."


def join_loc_pub(location, publisher):
    """'Location: Publisher.' with graceful fallback when either is empty."""
    if location and publisher:
        return f"{location}: {publisher}."
    if location or publisher:
        return ensure_period(location or publisher)
    return ""


DEV_RE = re.compile(r"\\dev\s*\{")


def find_dev(s):
    """Yield (start, end, inner) for each \\dev{...} in s, braces balanced."""
    for m in DEV_RE.finditer(s):
        depth, j = 1, m.end()
        while j < len(s) and depth:
            if s[j] == "\\":
                j += 2
                continue
            depth += {"{": 1, "}": -1}.get(s[j], 0)
            j += 1
        yield m.start(), j, s[m.end():j - 1]


def to_devanagari(iast):
    """Transliterate IAST to Devanagari, as the \\dev{} macro does when
    typeset. Text already in Devanagari is left alone."""
    if not re.search(r"[A-Za-zĀ-ſḀ-ỿ]", iast):
        return iast
    return sanscript.transliterate(iast.lower().replace("--", "–"),
                                   sanscript.IAST, sanscript.DEVANAGARI)


def convert_dev(s):
    """Replace every \\dev{...} with its Devanagari rendering."""
    out, pos = [], 0
    for a, b, inner in find_dev(s):
        out.append(s[pos:a])
        out.append(to_devanagari(clean_latex(inner)))
        pos = b
    out.append(s[pos:])
    return "".join(out)


def dev_originals(raw):
    """The romanized text of all \\dev{...} in an entry, kept for searching
    so that IAST queries still find titles displayed in Devanagari."""
    return " ".join(clean_latex(inner) for _, _, inner in find_dev(raw))


def clean_latex(text):
    """Light-touch cleanup of LaTeX markup for plain-text display.
    Not a full LaTeX parser -- handles the patterns actually present
    in this bibliography (protective braces, \\emph, accent commands,
    common escapes)."""
    if not text:
        return text
    s = text
    s = convert_tex_accents(s)
    if "\\dev" in s:
        s = convert_dev(s)
    s = TEX_BARE_MACRO_RE.sub("", s)
    s = s.replace("``", "\u201c").replace("''", "\u201d")
    # Repeatedly unwrap \emph{...} etc., innermost first, keeping the text.
    prev = None
    while prev != s:
        prev = s
        s = LATEX_MACRO_STRIP.sub(r"\2", s)
    for macro, repl in LATEX_SIMPLE_ESCAPES.items():
        s = s.replace(macro, repl)
    # A bare "~" left after the substitutions above is TeX's protected
    # (non-breaking) space convention (e.g. "Simon~Erik"), not an accent.
    s = s.replace("~", " ")
    # Strip bare braces used only to protect capitalization, e.g. "{V}edic".
    s = re.sub(r"\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Drop a dangling comma/colon/semicolon left at the very end of a field,
    # or a stray leading period/comma (seen on a handful of publisher/title/
    # subtitle values in the source data, e.g. a subtitle field that was
    # split off with its separating period still attached).
    s = re.sub(r"[,:;]+$", "", s).strip()
    s = re.sub(r"^[.,;]+\s*", "", s).strip()
    return s


def split_names(raw):
    """Split a BibLaTeX 'author'/'editor' string ('X and Y and Z') into
    a list of {family, given, display} dicts. Handles both 'Given Family'
    and 'Family, Given' forms."""
    if not raw:
        return []
    raw = clean_latex(raw)
    parts = [p.strip() for p in re.split(r"\s+\band\b\s+", raw) if p.strip()]
    people = []
    particles = {"van", "von", "de", "der", "den", "du", "la", "le", "del", "da", "di", "af"}
    for p in parts:
        if p.lower() in ("others", "et al."):
            people.append({"family": "", "given": "", "display": "et al."})
            continue
        if "," in p:
            family, given = [x.strip() for x in p.split(",", 1)]
        else:
            tokens = p.split()
            if len(tokens) == 1:
                family, given = tokens[0], ""
            else:
                # Pull trailing particle(s) + last token into the surname.
                i = len(tokens) - 1
                while i > 0 and tokens[i - 1].lower() in particles:
                    i -= 1
                family = " ".join(tokens[i:])
                given = " ".join(tokens[:i])
        display = f"{given} {family}".strip() if given else family
        people.append({"family": family, "given": given, "display": display})
    return people


def format_author_list(people, max_display=3):
    """'et al.'-truncated display string, e.g. for citations."""
    if not people:
        return ""
    names = [p["display"] for p in people]
    if len(names) > max_display:
        return f"{names[0]} et al."
    if len(names) == 1:
        return names[0]
    if names[-1] == "et al.":
        return ", ".join(names[:-1]) + ", et al." if len(names) > 2 else names[0] + ", et al."
    return ", ".join(names[:-1]) + " and " + names[-1]


def extract_year(date_val, year_val):
    """Return (year_sort:int|None, year_display:str) from date/year fields.
    BibLaTeX 'date' can be '2022', '2022-05', '2020/2021', '1968/1986', etc."""
    raw = date_val or year_val or ""
    raw = raw.strip()
    if not raw:
        return None, ""
    if "/" in raw:
        start, end = raw.split("/", 1)
        y1 = re.match(r"\d{4}", start.strip())
        y2 = re.match(r"\d{4}", end.strip())
        display = f"{y1.group(0) if y1 else start}\u2013{y2.group(0) if y2 else end}"
        sort_year = int(y1.group(0)) if y1 else None
        return sort_year, display
    m = re.match(r"\d{4}", raw)
    if m:
        return int(m.group(0)), raw
    return None, raw


def get(fd, *names):
    for n in names:
        if n in fd:
            return clean_latex(fd[n].value)
    return ""


def get_raw(fd, *names):
    for n in names:
        if n in fd:
            return fd[n].value
    return ""


TYPE_LABELS = {
    "book": "Book", "article": "Article", "incollection": "Chapter",
    "online": "Online resource", "mvbook": "Multi-volume book",
    "unpublished": "Unpublished", "inbook": "Book section",
    "phdthesis": "PhD thesis", "review": "Review", "misc": "Misc",
    "www": "Website", "techreport": "Technical report",
    "inproceedings": "Conference paper", "collection": "Edited collection",
    "electronic": "Electronic resource", "manuscript": "Manuscript",
    "proceedings": "Proceedings", "comment": "Comment",
    "audio": "Audio", "mastersthesis": "Master's thesis", "thesis": "Thesis",
    "report": "Report", "conference": "Conference paper",
    "inreference": "Reference entry", "mvcollection": "Multi-volume collection",
    "software": "Software", "mvreference": "Multi-volume reference",
    "phd": "PhD thesis", "bookinbook": "Book section", "booklet": "Booklet",
    "": "Volume",  # bare "@{key,...}" sub-entries (e.g. one volume of a
                    # multivolume work referenced via `related`/`relatedtype`)
}


def render_citation(rec):
    """Simple, generic author-date bibliography-style plain-text rendering.
    Not a full CSL engine -- covers the common shapes in this file."""
    a = rec["author_display"] or (rec["editor_display"] + ", ed." if rec["editor_display"] else "")
    y = rec["year_display"] or "n.d."
    title = rec["title"]
    if rec["subtitle"]:
        title = f"{title}: {rec['subtitle']}" if title else rec["subtitle"]
    quoted_title = (f'"{title}"' if title and title[-1] in "?!" else f'"{title}."') if title else ""
    plain_title = ensure_period(title) if title else ""
    t = rec["type"]
    bits = [f"{a}." if a else "", f"{y}."]

    if t in ("article", "review"):
        bits.append(quoted_title)
        tail = rec["container"]
        if rec["volume"]:
            tail += f" {rec['volume']}"
        if rec["number"]:
            tail += f"({rec['number']})"
        if rec["pages"]:
            tail += f": {rec['pages']}"
        bits.append(ensure_period(tail) if tail else "")
    elif t in ("incollection", "inbook", "bookinbook", "inreference"):
        bits.append(quoted_title)
        in_bits = []
        if rec["container"]:
            in_bits.append(f"In {rec['container']}")
        if rec["editor_display"]:
            in_bits.append(f"ed. {rec['editor_display']}")
        if rec["pages"]:
            in_bits.append(rec["pages"])
        loc = ", ".join(in_bits)
        pub = join_loc_pub(rec["location"], rec["publisher"])
        bits.append(f"{loc}. {pub}".strip() if pub else ensure_period(loc))
    elif t in ("inproceedings", "conference"):
        bits.append(quoted_title)
        bits.append(f"In {rec['container']}." if rec["container"] else "")
    elif t in ("phdthesis", "mastersthesis", "phd", "thesis"):
        label = "PhD diss." if t in ("phdthesis", "phd") else "Master's thesis"
        institution = rec["publisher"] or rec["location"]
        tail = ensure_period(f"{label}, {institution}") if institution else label
        bits.append((plain_title + " " + tail).strip())
    elif t in ("online", "www", "electronic", "software"):
        bits.append(plain_title)
        if rec["url"]:
            bits.append(rec["url"])
    else:  # book, mvbook, collection, misc, manuscript, report, etc.
        bits.append(plain_title)
        tail_bits = []
        if rec["edition"]:
            ed = rec["edition"]
            tail_bits.append(ensure_period(ed) if "ed" in ed.lower() else f"{ed} ed.")
        if rec["volume"] and t in ("mvbook", "mvcollection", "mvreference"):
            tail_bits.append(f"{rec['volume']} vols.")
        loc_pub = join_loc_pub(rec["location"], rec["publisher"])
        if loc_pub:
            tail_bits.append(loc_pub)
        bits.append(" ".join(tail_bits))

    result = re.sub(r"\s+", " ", " ".join(b for b in bits if b)).strip()
    result = re.sub(r"\s+([.,:;])", r"\1", result)
    result = re.sub(r"(?<!\.)\.\.(?!\.)", ".", result)  # collapse accidental ".." but leave "..." ellipses
    return result


def clean_bibtex(raw_entry_text):
    """Strip private fields out of the original entry text for the
    public 'Copy BibTeX' box, keeping everything else verbatim."""
    lines = raw_entry_text.split("\n")
    out = []
    for line in lines:
        m = re.match(r"\s*([A-Za-z]+)\s*=", line)
        if m and m.group(1).lower() in PRIVATE_FIELDS:
            continue
        out.append(line)
    return "\n".join(out).strip() + "\n"


def load_bib(path):
    lib = bibtexparser.parse_file(str(path))
    return {e.key: e for e in lib.entries if e.entry_type.lower() != "comment"}, lib.entries


def build():
    all_records = []
    stats = []
    entries_by_key_global = {}

    # First pass: load everything so crossref lookups can span files.
    loaded = []
    for filename, tag, label in SOURCES:
        path = ROOT / filename
        if not path.exists():
            print(f"  (skipping {filename}: not found at {path})", file=sys.stderr)
            continue
        by_key, entries = load_bib(path)
        entries_by_key_global.update(by_key)
        loaded.append((tag, label, entries))

    for tag, label, entries in loaded:
        count = 0
        for e in entries:
            fd = e.fields_dict
            crossref_key = get(fd, "crossref")
            parent_fd = entries_by_key_global[crossref_key].fields_dict if crossref_key in entries_by_key_global else {}

            author_people = split_names(get_raw(fd, "author"))
            editor_people = split_names(get_raw(fd, "editor"))
            translator_people = split_names(get_raw(fd, "translator"))

            container = get(fd, "journaltitle", "journal", "booktitle") or get(parent_fd, "journaltitle", "journal", "booktitle", "title")
            year_sort, year_display = extract_year(get_raw(fd, "date"), get_raw(fd, "year"))
            keywords_raw = get(fd, "keywords")
            keywords = [k.strip() for k in re.split(r"[;,]", keywords_raw) if k.strip()] if keywords_raw else []
            language = get(fd, "langid", "language")

            rec = {
                "id": e.key,
                "collection": tag,
                "type": e.entry_type.lower(),
                "type_label": TYPE_LABELS.get(e.entry_type.lower(), e.entry_type.title()),
                "author_people": author_people,
                "author_display": format_author_list(author_people, max_display=99),
                "author_short": format_author_list(author_people, max_display=3),
                "author_sort": (author_people[0]["family"] if author_people else
                                (editor_people[0]["family"] if editor_people else "zzz")).lower(),
                "editor_display": format_author_list(editor_people, max_display=99),
                "translator_display": format_author_list(translator_people, max_display=99),
                "year": year_sort,
                "year_display": year_display,
                "title": get(fd, "title"),
                "subtitle": get(fd, "subtitle"),
                "container": container,
                "volume": get(fd, "volume"),
                "number": get(fd, "number"),
                "pages": get(fd, "pages"),
                "series": get(fd, "series"),
                "edition": get(fd, "edition"),
                "publisher": get(fd, "publisher"),
                "location": get(fd, "location", "address"),
                "isbn": get(fd, "isbn"),
                "issn": get(fd, "issn"),
                "doi": get(fd, "doi"),
                "url": get(fd, "url"),
                # ARK identifiers (eprinttype = {ark}, eprint = {ark:/13960/...})
                # resolve through the n2t.net resolver.
                "ark_url": ("https://n2t.net/" + get_raw(fd, "eprint").strip())
                           if get_raw(fd, "eprint").strip().startswith("ark:/") else "",
                "language": language,
                "keywords": keywords,
                "note": get(fd, "note"),
                "contents": get(fd, "contents", "Contents"),
                "comment": get(fd, "comment"),
            }
            rec["citation"] = render_citation(rec)
            rec["bibtex"] = clean_bibtex(e.raw)
            rec["search_extra"] = " ".join(dev_originals(f.value) for f in e.fields if f.key.lower() not in PRIVATE_FIELDS).strip()
            # author_people (full structured list) was only needed to
            # compute author_display/author_short/author_sort above; the
            # site's search/display code works from those, so drop the
            # structured list here to keep the shipped JSON smaller.
            # Short label used when glossary descriptions cite this work:
            # the BibLaTeX shorthand if there is one (e.g. "GVDB"), else
            # "Family Year", as biblatex's author-year styles would print it.
            shorthand = get(fd, "shorthand", "Shorthand")
            if shorthand:
                rec["cite_label"] = shorthand
            else:
                people = author_people or editor_people
                fam = people[0]["family"] if people else rec["title"][:30]
                if len(people) == 2:
                    fam += " and " + people[1]["family"]
                elif len(people) > 2:
                    fam += " et al."
                rec["cite_label"] = f"{fam} {year_display}".strip()
            del rec["author_people"]
            all_records.append(rec)
            count += 1
        stats.append((label, count))

    return all_records, stats


def main():
    records, stats = build()
    from glossary import build_glossaries
    for r in records:
        r["collection_label"] = next((lbl for f, t, lbl in SOURCES if t == r["collection"]), r["collection"])
    gl_records, gl_stats = build_glossaries(ROOT, GLOSSARIES, records)
    records += gl_records
    stats += gl_stats
    out_path = ROOT / "assets" / "data" / "bibliography.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(records)} entries to {out_path}")
    for label, count in stats:
        print(f"  - {label}: {count}")


if __name__ == "__main__":
    main()
