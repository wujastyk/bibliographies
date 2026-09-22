"""
Glossary databases (plants.bib, animals.bib, minerals.bib) -> JSON records.

These files use the bib2gls / glossaries-extra convention:

    @Entry{kāṇḍekṣu,
      Description = {Saccharum spontaneum L., \\cite[90]{gvdb}},
      Name        = {wild sugar cane},
    }

The entry key is the Sanskrit term, Name is the English name, and
Description is free LaTeX. The Description is rendered here to a small,
safe subset of HTML: citations become links to the corresponding entry in
the bibliography index (when that entry exists), \\gls/\\egls cross-
references become links to the other glossary entry, and \\emph becomes
italics. Everything else is escaped text.
"""
import html
import re
import unicodedata

import bibtexparser

from build_bibliography import clean_bibtex, clean_latex, convert_tex_accents, dev_originals, to_devanagari, PRIVATE_FIELDS

# Macros from Dominik's own LaTeX setup that appear in the descriptions.
TEXT_MACROS = {
    "SS": "<i>Suśrutasaṃhitā</i>",
    "CS": "<i>Carakasaṃhitā</i>",
    "rightarrow": "→", "leftarrow": "←",
    "S": "§", "P": "¶", "ldots": "…", "slash": "/",
}
# Macros whose single argument is simply printed (formatting only).
PASS_THROUGH = {"textnormal", "textbengali", "textgreek", "textbf", "textsc"}
ITALIC = {"emph", "textit"}
DROP = {"ref", "pageref", "label", "index"}
GLS = {"gls", "egls", "glspl", "Gls", "Glspl", "glsname"}
CITE = {"cite", "citep", "citet", "parencite", "textcite", "autocite", "footcite"}
VOLCITE = {"volcite", "pvolcite", "tvolcite", "avolcite"}


class Renderer:
    def __init__(self, bib_by_id, gloss_ids):
        self.bib = bib_by_id          # bibliography id -> record
        self.gloss = gloss_ids        # glossary key -> record id

    # -- argument parsing ------------------------------------------------
    @staticmethod
    def _group(s, i, open_ch, close_ch):
        """If s[i] == open_ch, return (content, index after close)."""
        if i >= len(s) or s[i] != open_ch:
            return None, i
        depth, j = 0, i
        while j < len(s):
            c = s[j]
            if c == "\\":
                j += 2
                continue
            if c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return s[i + 1:j], j + 1
            j += 1
        return s[i + 1:], len(s)

    def _skip_ws(self, s, i):
        while i < len(s) and s[i] in " \t\n":
            i += 1
        return i

    def _opts(self, s, i):
        """Read any number of [..] optional args."""
        out = []
        while True:
            k = self._skip_ws(s, i)
            val, j = self._group(s, k, "[", "]")
            if val is None:
                return out, i
            out.append(val)
            i = j

    def _arg(self, s, i):
        k = self._skip_ws(s, i)
        val, j = self._group(s, k, "{", "}")
        if val is None:
            return "", i
        return val, j

    # -- output helpers ----------------------------------------------------
    def cite_link(self, key, pre="", post="", vol=""):
        key = key.strip()
        rec = self.bib.get(key)
        label = html.escape(rec["cite_label"] if rec else key)
        loc = ""
        if vol and post:
            loc = f" {html.escape(vol)}: {self.render(post)}"
        elif vol:
            loc = f" vol. {html.escape(vol)}"
        elif post:
            loc = f": {self.render(post)}"
        pre_html = self.render(pre) + " " if pre else ""
        inner = f"{label}{loc}"
        if rec:
            title = html.escape(rec.get("citation", ""), quote=True)
            inner = f'<a class="cite" href="#entry-{html.escape(key, quote=True)}" title="{title}">{inner}</a>'
        return pre_html + inner

    def gls_link(self, key):
        key = key.strip()
        target = self.gloss.get(key)
        text = f"<i>{html.escape(key)}</i>"
        if target:
            return f'<a class="gls" href="#entry-{html.escape(target, quote=True)}">{text}</a>'
        return text

    # -- main render -------------------------------------------------------
    def render(self, s):
        out = []
        i = 0
        n = len(s)
        while i < n:
            c = s[i]
            if c == "\\":
                m = re.match(r"\\([A-Za-z]+)\*?|\\(.)", s[i:])
                name = m.group(1) or m.group(2)
                i += m.end()
                if m.group(2) is not None:          # \& \% \, \  etc.
                    out.append({",": "\u2009", " ": " ", "\\": " "}.get(name, html.escape(name)))
                    continue
                if name in TEXT_MACROS:
                    out.append(TEXT_MACROS[name])
                elif name in ITALIC:
                    a, i = self._arg(s, i)
                    out.append(f"<i>{self.render(a)}</i>")
                elif name == "dev":
                    a, i = self._arg(s, i)
                    out.append('<span class="deva" lang="sa">' + html.escape(to_devanagari(clean_latex(a))) + '</span>')
                elif name in PASS_THROUGH:
                    a, i = self._arg(s, i)
                    out.append(self.render(a))
                elif name in DROP:
                    _, i = self._arg(s, i)
                elif name in GLS:
                    a, i = self._arg(s, i)
                    out.append(self.gls_link(a))
                elif name in CITE:
                    opts, i = self._opts(s, i)
                    keys, i = self._arg(s, i)
                    pre, post = ("", opts[0]) if len(opts) == 1 else (opts + ["", ""])[:2]
                    out.append("; ".join(self.cite_link(k, pre, post) for k in keys.split(",")))
                elif name == "cites":           # \cites[p]{a}[p]{b}...
                    parts = []
                    while True:
                        opts, j = self._opts(s, i)
                        k = self._skip_ws(s, j)
                        if k >= n or s[k] != "{":
                            break
                        key, i = self._arg(s, j)
                        post = opts[-1] if opts else ""
                        parts.append(self.cite_link(key, "", post))
                    out.append("; ".join(parts))
                elif name in VOLCITE:
                    _, i = self._opts(s, i)
                    vol, i = self._arg(s, i)
                    opts, i = self._opts(s, i)
                    key, i = self._arg(s, i)
                    out.append(self.cite_link(key, "", opts[-1] if opts else "", vol))
                elif name == "citeauthor":
                    key, i = self._arg(s, i)
                    rec = self.bib.get(key.strip())
                    out.append(html.escape((rec["author_display"] or rec["cite_label"]) if rec else key))
                elif name in ("gvdb", "gvdbt"):     # \gvdb{page}
                    page, i = self._arg(s, i)
                    out.append(self.cite_link("gvdb", "", page))
                elif name in ("Su", "Ca", "Dalhana"):   # \Su{ref}{page}
                    ref, i = self._arg(s, i)
                    page, i = self._arg(s, i)
                    ed = "cara-trikamji3" if name == "Ca" else "vulgate"
                    lead = "Ḍalhaṇa on " if name == "Dalhana" else ""
                    out.append(f"{lead}{self.render(ref)} ({self.cite_link(ed, '', page)})")
                elif name == "href":
                    url, i = self._arg(s, i)
                    text, i = self._arg(s, i)
                    out.append(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">{self.render(text)}</a>')
                elif name == "url":
                    url, i = self._arg(s, i)
                    out.append(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">{html.escape(url)}</a>')
                else:
                    # Unknown macro: print its argument if it has one.
                    if i < n and s[i] == "{":
                        a, i = self._arg(s, i)
                        out.append(self.render(a))
            elif c in "{}":
                i += 1
            elif c == "`" and not s.startswith("``", i):
                out.append("‘"); i += 1
            elif c == "~":
                out.append("\u00a0")
                i += 1
            elif s.startswith("``", i):
                out.append("“"); i += 2
            elif s.startswith("''", i):
                out.append("”"); i += 2
            elif s.startswith("---", i):
                out.append("—"); i += 3
            elif s.startswith("--", i):
                out.append("–"); i += 2
            elif c == "$":
                i += 1                               # drop math-mode delimiters
            else:
                out.append(html.escape(c))
                i += 1
        return re.sub(r"\s+", " ", "".join(out)).strip()


def tex_accents(s):
    """convert_tex_accents plus breve (\\u) and caron (\\v), used here."""
    marks = {"u": "\u0306", "v": "\u030c"}
    s = re.sub(r"\\([uv])(?:\{([A-Za-z])\}| ([A-Za-z]))",
               lambda m: (m.group(2) or m.group(3)) + marks[m.group(1)], s)
    return convert_tex_accents(s)


def strip_tags(h):
    return html.unescape(re.sub(r"<[^>]+>", "", h))


def build_glossaries(root, sources, bib_records):
    bib_by_id = {r["id"]: r for r in bib_records}
    loaded = []
    gloss_ids = {}
    for filename, tag, label, type_label in sources:
        path = root / filename
        if not path.exists():
            continue
        lib = bibtexparser.parse_file(str(path))
        entries = [e for e in lib.entries if e.entry_type.lower() == "entry"]
        for e in entries:
            key = unicodedata.normalize("NFC", e.key)
            gloss_ids.setdefault(key, f"{tag}-{key}")
        loaded.append((tag, label, type_label, entries))

    r = Renderer(bib_by_id, gloss_ids)
    records, stats = [], []
    for tag, label, type_label, entries in loaded:
        for e in entries:
            fd = e.fields_dict
            key = unicodedata.normalize("NFC", e.key)
            raw_desc = tex_accents(fd["Description"].value) if "Description" in fd else ""
            english = strip_tags(r.render(tex_accents(fd["Name"].value))) if "Name" in fd else ""
            desc_html = r.render(raw_desc)
            desc_text = strip_tags(desc_html)
            kw = fd["keywords"].value if "keywords" in fd else ""
            show_en = english if english and english != key else ""
            rec = {
                "id": gloss_ids[key],
                "collection": tag,
                "collection_label": label,
                "type": "glossary",
                "type_label": type_label,
                "sanskrit": key,
                "english": show_en,
                "description_html": desc_html,
                "description_text": desc_text,
                "keywords": [k.strip() for k in re.split(r"[;,]", kw) if k.strip()],
                "author_sort": key.lower(),
                "title": (show_en or key).lower(),
                "year": None, "year_display": "",
                "citation": f"{key}" + (f" ({show_en})" if show_en else "") + (f": {desc_text}" if desc_text else ""),
                "bibtex": clean_bibtex(e.raw),
                "search_extra": " ".join(dev_originals(f.value) for f in e.fields if f.key.lower() not in PRIVATE_FIELDS).strip(),
            }
            records.append(rec)
        stats.append((label, len(entries)))
    return records, stats
