---
---
(function () {
  "use strict";

  // Jekyll processes this file as a Liquid template (see the empty front
  // matter above) purely so this next line can inject the build time --
  // used below to cache-bust the bibliography.json fetch. Every push
  // regenerates that JSON, but browsers that already have a copy won't
  // know to re-fetch it unless the URL itself changes.
  var BUILD_VERSION = "{{ site.time | date: '%s' }}";

  var PAGE_SIZE = 40;

  var state = {
    all: [],           // every record, as loaded
    filtered: [],       // after search + filters, before paging
    page: 1,
    query: "",
    mode: "plain",
    collection: "",
    type: "",
    lang: "",
    yearFrom: null,
    yearTo: null,
    sort: "author",
  };

  var els = {};

  function $(sel, ctx) { return (ctx || document).querySelector(sel); }
  function $all(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ---- loading ----------------------------------------------------

  function init() {
    els.app = $("#app");
    els.q = $("#q");
    els.results = $("#results");
    els.count = $("#results-count");
    els.blurb = $("#entry-count-blurb");
    els.pager = $("#pager");
    els.fCollection = $("#f-collection");
    els.fType = $("#f-type");
    els.fLang = $("#f-lang");
    els.fYearFrom = $("#f-year-from");
    els.fYearTo = $("#f-year-to");
    els.fSort = $("#f-sort");
    els.reset = $("#f-reset");
    els.template = $("#entry-template");

    fetch(resolveDataUrl(), { cache: "force-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(onDataLoaded)
      .catch(function (err) {
        els.count.textContent = "";
        $("#loading-msg").textContent =
          "Could not load the bibliography data (" + err.message + "). " +
          "Try reloading, or check assets/data/bibliography.json exists.";
      });

    bindControls();
  }

  function resolveDataUrl() {
    // index.html is served from the site root (respecting baseurl),
    // so a relative path from the page works whether the site is
    // hosted at the domain root or under /bibliographies/. The "?v="
    // suffix is the build-time cache-buster described above.
    var script = document.currentScript || $all("script[src*='app.js']").pop();
    var base = script
      ? script.src.replace(/assets\/js\/app\.js.*$/, "assets/data/bibliography.json")
      : "assets/data/bibliography.json";
    return base + "?v=" + encodeURIComponent(BUILD_VERSION);
  }

  function onDataLoaded(records) {
    records.forEach(function (r) {
      r._s = buildSearchString(r);
      r._f = fold(r._s);
    });
    state.all = records;
    els.app.dataset.loading = "false";
    els.blurb.textContent = "Currently " + records.length.toLocaleString() + " entries.";
    populateFacets(records);
    readStateFromForm();
    runSearch();
    scrollToHashEntry();
  }

  function buildSearchString(r) {
    return [
      r.author_display, r.editor_display, r.translator_display, r.title,
      r.subtitle, r.container, r.year_display, r.publisher, r.location,
      (r.keywords || []).join(" "), r.series, r.note, r.id, r.language,
      r.sanskrit, r.english, r.description_text,
    ].join(" ").toLowerCase();
  }

  // Diacritic-insensitive form used by plain search: "kanda" finds "kāṇḍa".
  function fold(s) {
    return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  // ---- facets -------------------------------------------------------

  function populateFacets(records) {
    var byCollection = {}, byType = {}, byLang = {};
    records.forEach(function (r) {
      collectionLabels[r.collection] = r.collection_label || r.collection;
      byCollection[r.collection] = (byCollection[r.collection] || 0) + 1;
      byType[r.type_label] = (byType[r.type_label] || 0) + 1;
      if (r.language) byLang[normalizeLang(r.language)] = (byLang[normalizeLang(r.language)] || 0) + 1;
    });

    fillSelect(els.fCollection, Object.keys(byCollection).sort(), byCollection, collectionLabel);
    fillSelect(els.fType, Object.keys(byType).sort(), byType, function (t) { return t; });
    fillSelect(els.fLang, Object.keys(byLang).sort(), byLang, function (l) { return l; });
  }

  var collectionLabels = {};
  function collectionLabel(tag) { return collectionLabels[tag] || tag; }

  function normalizeLang(l) {
    var known = { en: "English", eng: "English", "en-gb": "English", "en-in": "English",
      german: "German", ger: "German", french: "French", sanskrit: "Sanskrit" };
    var key = String(l).toLowerCase();
    return known[key] || (l.charAt(0).toUpperCase() + l.slice(1));
  }

  function fillSelect(select, keys, counts, labelFn) {
    keys.forEach(function (k) {
      var opt = document.createElement("option");
      opt.value = k;
      opt.textContent = labelFn(k) + " (" + counts[k] + ")";
      select.appendChild(opt);
    });
  }

  // ---- controls -------------------------------------------------------

  var debounceTimer = null;
  function bindControls() {
    els.q.addEventListener("input", function () {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () { readStateFromForm(); runSearch(); }, 120);
    });
    $all("input[name='mode']").forEach(function (r) {
      r.addEventListener("change", function () { readStateFromForm(); runSearch(); });
    });
    [els.fCollection, els.fType, els.fLang, els.fSort].forEach(function (el) {
      el.addEventListener("change", function () { readStateFromForm(); runSearch(); });
    });
    [els.fYearFrom, els.fYearTo].forEach(function (el) {
      el.addEventListener("input", function () {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () { readStateFromForm(); runSearch(); }, 200);
      });
    });
    els.reset.addEventListener("click", function () {
      $("#controls").reset();
      readStateFromForm();
      runSearch();
      els.q.focus();
    });
    window.addEventListener("hashchange", scrollToHashEntry);
  }

  function readStateFromForm() {
    state.query = els.q.value.trim();
    state.mode = ($all("input[name='mode']").filter(function (r) { return r.checked; })[0] || {}).value || "plain";
    state.collection = els.fCollection.value;
    state.type = els.fType.value;
    state.lang = els.fLang.value;
    state.yearFrom = els.fYearFrom.value ? parseInt(els.fYearFrom.value, 10) : null;
    state.yearTo = els.fYearTo.value ? parseInt(els.fYearTo.value, 10) : null;
    state.sort = els.fSort.value;
    state.page = 1;
  }

  // ---- search / filter / sort -------------------------------------------

  function matchesQuery(r, query, mode) {
    if (!query) return true;
    if (mode === "regex") {
      try {
        var re = new RegExp(query, "i");
        return re.test(r._s);
      } catch (e) {
        return true; // invalid regex-in-progress: don't hide everything
      }
    }
    var terms = fold(query).split(/\s+/).filter(Boolean);
    return terms.every(function (t) { return r._f.indexOf(t) !== -1; });
  }

  function runSearch() {
    var q = state.query, mode = state.mode;
    var out = state.all.filter(function (r) {
      if (state.collection && r.collection !== state.collection) return false;
      if (state.type && r.type_label !== state.type) return false;
      if (state.lang && normalizeLang(r.language || "") !== state.lang) return false;
      if (state.yearFrom != null && (r.year == null || r.year < state.yearFrom)) return false;
      if (state.yearTo != null && (r.year == null || r.year > state.yearTo)) return false;
      return matchesQuery(r, q, mode);
    });
    sortRecords(out, state.sort);
    state.filtered = out;
    renderPage();
  }

  function sortRecords(list, sort) {
    list.sort(function (a, b) {
      switch (sort) {
        case "year-desc": return (b.year || -Infinity) - (a.year || -Infinity) || cmp(a.author_sort, b.author_sort);
        case "year-asc": return (a.year || Infinity) - (b.year || Infinity) || cmp(a.author_sort, b.author_sort);
        case "title": return cmp(a.title, b.title);
        case "author":
        default: return cmp(a.author_sort, b.author_sort) || (a.year || 0) - (b.year || 0);
      }
    });
  }
  function cmp(a, b) { a = a || ""; b = b || ""; return a < b ? -1 : a > b ? 1 : 0; }

  // ---- rendering -------------------------------------------------------

  function renderPage() {
    var total = state.filtered.length;
    var pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (state.page > pages) state.page = pages;
    var start = (state.page - 1) * PAGE_SIZE;
    var slice = state.filtered.slice(start, start + PAGE_SIZE);

    els.count.textContent = total === 0
      ? "No matching entries."
      : total.toLocaleString() + " matching entr" + (total === 1 ? "y" : "ies") +
        (pages > 1 ? " · page " + state.page + " of " + pages : "");

    els.results.innerHTML = "";
    var frag = document.createDocumentFragment();
    slice.forEach(function (r) { frag.appendChild(renderEntry(r)); });
    els.results.appendChild(frag);
    renderPager(pages);
  }

  function highlight(text, query, mode) {
    if (!query || mode === "regex") return escapeHtml(text);
    var terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    var escaped = escapeHtml(text);
    terms.forEach(function (t) {
      var re = new RegExp("(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
      escaped = escaped.replace(re, "<mark>$1</mark>");
    });
    return escaped;
  }

  function renderEntry(r) {
    var node = els.template.content.firstElementChild.cloneNode(true);
    node.id = "entry-" + r.id;
    node.dataset.id = r.id;

    node.querySelector(".entry__type").textContent = r.type_label;
    var toggle = node.querySelector(".entry__toggle");

    if (r.type === "glossary") {
      // Glossary rows show English name, Sanskrit name and description in
      // full. The description contains links (citations, cross-references),
      // which can't live inside the toggle <button>, so the row becomes a
      // plain block and a small "details" button opens the BibTeX panel.
      var row = node.querySelector(".entry__row");
      var body = document.createElement("div");
      body.className = "entry__gloss";
      var head = r.english
        ? '<span class="gl-en">' + highlight(r.english, state.query, state.mode) + '</span> ' +
          '<span class="gl-skt">' + highlight(r.sanskrit, state.query, state.mode) + '</span>'
        : '<span class="gl-skt">' + highlight(r.sanskrit, state.query, state.mode) + '</span>';
      body.innerHTML = '<span class="entry__type"></span><span class="gl-text">' + head +
        (r.description_html ? '<span class="gl-sep"> — </span><span class="gl-desc">' + r.description_html + '</span>' : '') +
        '</span>';
      body.querySelector(".entry__type").textContent = r.type_label;
      toggle.className = "entry__more";
      toggle.innerHTML = "";
      toggle.textContent = "details";
      toggle.setAttribute("aria-label", "Show BibTeX and permalink for " + r.sanskrit);
      row.insertBefore(body, toggle);
      toggle.addEventListener("click", function () { toggleDetail(node, r); });
      return node;
    }

    node.querySelector(".entry__citation").innerHTML = highlight(r.citation, state.query, state.mode);
    toggle.addEventListener("click", function () { toggleDetail(node, r); });

    return node;
  }

  function toggleDetail(node, r) {
    var detail = node.querySelector(".entry__detail");
    var toggle = node.querySelector(".entry__toggle, .entry__more");
    var open = detail.hidden;
    detail.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (open && !detail.dataset.populated) {
      populateDetail(detail, node, r);
      detail.dataset.populated = "1";
    }
  }

  var FIELD_LABELS = [
    ["editor_display", "Editor"], ["translator_display", "Translator"],
    ["container", "In"], ["series", "Series"], ["volume", "Volume"],
    ["number", "Number"], ["pages", "Pages"], ["edition", "Edition"],
    ["publisher", "Publisher"], ["location", "Location"],
    ["isbn", "ISBN"], ["issn", "ISSN"], ["doi", "DOI"],
    ["language", "Language"], ["note", "Note"], ["comment", "Comment"],
    ["contents", "Contents"],
  ];

  function populateDetail(detail, node, r) {
    var dl = detail.querySelector(".entry__fields");
    FIELD_LABELS.forEach(function (pair) {
      var key = pair[0], label = pair[1];
      var val = r[key];
      if (!val) return;
      var dt = document.createElement("dt");
      dt.textContent = label;
      var dd = document.createElement("dd");
      if (key === "contents") dd.className = "is-contents";
      if (key === "doi") {
        var a = document.createElement("a");
        a.href = "https://doi.org/" + encodeURIComponent(val);
        a.textContent = val;
        a.target = "_blank"; a.rel = "noopener";
        dd.appendChild(a);
      } else {
        dd.textContent = val;
      }
      dl.appendChild(dt); dl.appendChild(dd);
    });

    var kwWrap = detail.querySelector(".entry__keywords");
    (r.keywords || []).forEach(function (kw) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = kw;
      b.addEventListener("click", function () {
        els.q.value = kw;
        readStateFromForm();
        runSearch();
        els.q.focus();
      });
      kwWrap.appendChild(b);
    });

    var linkEl = detail.querySelector(".entry__link");
    if (r.url) { linkEl.href = r.url; linkEl.hidden = false; }
    else if (r.doi) { linkEl.href = "https://doi.org/" + encodeURIComponent(r.doi); linkEl.hidden = false; }

    var permaEl = detail.querySelector(".entry__permalink");
    permaEl.href = location.pathname + "#entry-" + r.id;
    permaEl.hidden = false;
    permaEl.addEventListener("click", function (e) {
      e.preventDefault();
      history.replaceState(null, "", "#entry-" + r.id);
      copyToClipboard(location.href);
      flashButton(permaEl, "Link copied");
    });

    var bibtexPre = detail.querySelector(".entry__bibtex");
    bibtexPre.textContent = r.bibtex;

    node.querySelector(".btn-copy-citation").addEventListener("click", function (e) {
      copyToClipboard(r.citation);
      flashButton(e.currentTarget, "Copied");
    });
    node.querySelector(".btn-copy-bibtex").addEventListener("click", function (e) {
      bibtexPre.hidden = !bibtexPre.hidden;
      if (!bibtexPre.hidden) copyToClipboard(r.bibtex);
      flashButton(e.currentTarget, bibtexPre.hidden ? "Copy BibTeX" : "Copied ✓ (shown below)");
    });
  }

  function flashButton(btn, msg) {
    var original = btn.dataset.originalText || btn.textContent;
    btn.dataset.originalText = original;
    btn.textContent = msg;
    clearTimeout(btn._flashTimer);
    btn._flashTimer = setTimeout(function () { btn.textContent = btn.dataset.originalText; }, 1600);
  }

  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(function () { fallbackCopy(text); });
    } else {
      fallbackCopy(text);
    }
  }
  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (e) { /* ignore */ }
    document.body.removeChild(ta);
  }

  // ---- pager -------------------------------------------------------

  function renderPager(pages) {
    els.pager.innerHTML = "";
    if (pages <= 1) return;
    var frag = document.createDocumentFragment();

    function makeBtn(label, page, opts) {
      opts = opts || {};
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      if (opts.current) b.setAttribute("aria-current", "true");
      if (opts.disabled) b.disabled = true;
      b.addEventListener("click", function () {
        state.page = page;
        renderPage();
        window.scrollTo({ top: els.results.offsetTop - 80, behavior: "smooth" });
      });
      frag.appendChild(b);
    }

    makeBtn("‹ Prev", Math.max(1, state.page - 1), { disabled: state.page === 1 });
    var windowSize = 5;
    var startP = Math.max(1, state.page - Math.floor(windowSize / 2));
    var endP = Math.min(pages, startP + windowSize - 1);
    startP = Math.max(1, endP - windowSize + 1);
    if (startP > 1) makeBtn("1", 1);
    if (startP > 2) { var dots = document.createElement("span"); dots.textContent = "…"; dots.style.padding = "0 .2rem"; frag.appendChild(dots); }
    for (var p = startP; p <= endP; p++) makeBtn(String(p), p, { current: p === state.page });
    if (endP < pages - 1) { var dots2 = document.createElement("span"); dots2.textContent = "…"; dots2.style.padding = "0 .2rem"; frag.appendChild(dots2); }
    if (endP < pages) makeBtn(String(pages), pages);
    makeBtn("Next ›", Math.min(pages, state.page + 1), { disabled: state.page === pages });

    els.pager.appendChild(frag);
  }

  // ---- deep-linking to a single entry -------------------------------------------------------

  function scrollToHashEntry() {
    var hash = location.hash.replace(/^#/, "");
    if (!hash) return;
    var id = hash.replace(/^entry-/, "");
    var idx = state.filtered.findIndex(function (r) { return r.id === id; });
    if (idx === -1) {
      // Not in the current filtered set (e.g. filters hide it) -- clear
      // filters/search so a shared link always resolves.
      var rec = state.all.filter(function (r) { return r.id === id; })[0];
      if (!rec) return;
      $("#controls").reset();
      readStateFromForm();
      state.query = ""; els.q.value = "";
      state.filtered = state.all.slice();
      sortRecords(state.filtered, state.sort);
      idx = state.filtered.findIndex(function (r) { return r.id === id; });
    }
    if (idx === -1) return;
    state.page = Math.floor(idx / PAGE_SIZE) + 1;
    renderPage();
    var raf = window.requestAnimationFrame || function (cb) { setTimeout(cb, 0); };
    raf(function () {
      var node = document.getElementById("entry-" + id);
      if (node) {
        node.classList.add("is-highlighted");
        if (typeof node.scrollIntoView === "function") node.scrollIntoView({ block: "center" });
        var r = state.filtered[idx];
        if (r.type !== "glossary") toggleDetail(node, r);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
