---
layout: default
title: About
permalink: /about/
---

# About this site

This is a searchable index generated from the BibLaTeX files in the
[wujastyk/bibliographies](https://github.com/wujastyk/bibliographies)
repository — Dominik Wujastyk's personal working bibliography for
research in Sanskrit studies, Āyurveda, and the history of medicine and
science in South Asia.

## How it's built

- The bibliography itself lives in `biblio4-utf8.bib` (and a small
  supplementary file, `mbh-vols.bib`, for the Joshi & Roodbergen volumes
  of Patañjali's *Mahābhāṣya*), edited directly with a reference manager
  (Zotero/Better BibTeX) or a text editor.
- A Python script (`scripts/build_bibliography.py`) converts those files
  into a single JSON index (`assets/data/bibliography.json`).
- A plain JavaScript front end (`assets/js/app.js`) loads that JSON and
  does all searching, filtering, and sorting in the browser — there is no
  server or database involved, so the whole site is a handful of static
  files that GitHub Pages can host directly.
- A GitHub Actions workflow re-runs the build automatically on every push
  to `main`, so the site always reflects the current state of the `.bib`
  files.

## Glossaries of plants, animals and minerals

The index also includes three glossary databases from the repository —
`plants.bib`, `animals.bib` and `minerals.bib` — which record Sanskrit
names of flora, fauna and minerals for use with LaTeX's
`glossaries-extra` package. Each is shown as English name, Sanskrit name
and description. Citations inside a description link to the cited work
in the bibliography (where it is present there), and cross-references
link to the other glossary entry. Use the *Collection* or *Type* filter
to see only these.

## Searching

Plain search ignores diacritics, so `kanda` finds *kāṇḍa* and `susruta`
finds *Suśruta*. Regex mode matches the text exactly as written.

## What's left out

A few fields present in the source `.bib` files are deliberately
left out of both the search index and the "Copy BibTeX" text shown here:
Zotero's `file` and `owner` fields (local file-system paths), the
`creationdate`/`modificationdate` bookkeeping fields, and the
`annotation`/`annote`/`source` fields, which in this file are mostly
personal working notes (e.g. "own copy", library call numbers, or
informal comments) rather than citation data.

## Citing an entry

Every entry has a stable link — click "Permalink" under an entry (or
just copy the page URL after opening it) to get a link of the form
`.../#entry-<citekey>` that will jump straight to that reference. The
"Copy citation" and "Copy BibTeX" buttons give a plain-text reference
and a cleaned BibLaTeX record respectively, for pasting elsewhere.

The rendered citations use a simple generic author–date style for quick
reference; they are not a substitute for a proper citation-style engine
(Chicago, MLA, etc.) and haven't been checked entry-by-entry for
correctness — always verify against the original publication.
