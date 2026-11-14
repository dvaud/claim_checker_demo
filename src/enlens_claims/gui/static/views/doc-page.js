// A document's page: the text with layers of highlights (Restore and Leave out in place, selections, notes), and the panels
// beside it: Reading and Page (doc-reading.js), Codes (doc-codes.js), Key terms, References and Search (doc-lookup.js).
import { App, api, h, icon, replace, clear, toast, showError, fmt, pageHead, P, emptyState, KIND_TEXT, dialog,
  breakSegments, breaksToIndex, textPositions, wordSpan, cpLength, safeHref, session, download, plural, TOKEN,
  button, downloadButton, link, card, textarea, fold, choice, navigate } from "../lib.js";
import { blockUnit, originalLink } from "./result.js";
import { colourPicker, editNote, removeNote, useAsEvidence, noteCard } from "./notes.js";
import { roleBox } from "./doc-role.js";   // 0.18.1 K2: theory documents
import { keep, kindCount } from "./doc-shared.js";
import { leaveOut } from "./doc-leave-out.js";
import { readingPanel, pagePanel } from "./doc-reading.js";
import { codesPanel } from "./doc-codes.js";
import { termsPanel, refsPanel, searchPanel } from "./doc-lookup.js";

// ---------------------------------------------------------------------------------------------
// document viewer: the document by paragraph or page (the units the locations cite), with the quote highlighted.
// 0.7: panels beside the text on wide screens (above it on phones): Codes (F2), Key terms (F6), References (F5) and
// Search in this document (F1); a highlighted copy to download (F7). `?tab=codes|terms|refs|search` opens a panel.
// ---------------------------------------------------------------------------------------------
const DOC_TABS = [["codes", "Codes", "tag"], ["terms", "Key terms", "network"], ["refs", "References", "link"], ["search", "Search", "text-search"],
  // 0.16 (F2): your notes and highlights on the document's words
  ["notes", "Notes", "highlighter"],
  // 0.15: how the document was read (A5), and the page of the original beside the text (A4)
  ["reading", "Reading", "layers"], ["page", "Page", "file-text"]];

export async function renderDocument(view, [docId], query) {
  const project = App.project;
  const base = `/api/projects/${P(project)}`;
  const docBase = `${base}/documents/${P(docId)}`;
  const from = query.from || "";
  let span = null;
  const m = /^(\d+)-(\d+)$/.exec(query.q || "");
  if (m) span = { start: Number(m[1]), end: Number(m[2]), whole: query.whole === "1" };
  let d;
  try { d = await api("GET", `${docBase}?view=blocks&offset=0&limit=500`); }
  catch (e) {
    if (e.status === 404) { view.appendChild(emptyState("search-x", "No such document", "It was removed from the project.", link({ kind: "back", href: "#/sources" }, "Back to documents"))); return; }
    throw e;
  }
  const blocks = d.blocks || [];
  const totalBlocks = d.total_blocks ?? blocks.length;
  const reading = blocks.some((b) => b.kind);  // 0.15: read by the new reader: blocks that know what they are
  const hit = span ? blocks.findIndex((b) => span.start >= b.start && span.start < b.end) : -1;
  // the quote's text, for opening the original at it (the whole excerpt is too long for that)
  // (span and the block’s start are the app’s offsets: turned into indices of the block’s own text to cut it)
  const hitPos = hit >= 0 ? textPositions(blocks[hit].text || "") : null;
  const quoteText = hit >= 0 && !span.whole ? (blocks[hit].text || "").slice(hitPos.index(Math.max(0, span.start - blocks[hit].start)), hitPos.index(Math.max(0, span.end - blocks[hit].start))).trim() || null : null;
  const back = from ? { href: `#/h/${encodeURIComponent(from)}${query.card ? `?card=${encodeURIComponent(query.card)}` : ""}`, text: "Back to the result" } : null;
  const watchers = [];
  const cleanups = [];
  let tab = DOC_TABS.some(([k]) => k === query.tab) ? query.tab : null;
  let framework = query.framework || App.settings().profile_framework || "sdg";

  // 0.13.3: the original and the highlighted copy are two quiet links on one line, as on the result page
  const copyBtn = downloadButton({ title: "A copy of the document with its quotes and labels highlighted", onClick: () => highlightedCopy() }, "Download a highlighted copy");
  view.appendChild(pageHead(d.title || d.file, { display: true, back: [back, { href: "#/sources", text: "All documents" }],
    facts: [d.file, KIND_TEXT[d.kind] || d.kind || "", d.n_pages ? `${d.n_pages} pages` : null,
      reading ? (d.paragraphs ? plural(d.paragraphs, "paragraph") : null)
        : d.n_pages && blockUnit(blocks[0]) === "pages" && totalBlocks === d.n_pages ? null : `${totalBlocks} ${blockUnit(blocks[0])}`,
      d.doi ? h("a", { href: `https://doi.org/${d.doi}`, target: "_blank", rel: "noopener noreferrer", title: "Opens the publisher's page in your browser" }, `doi ${d.doi}`) : null,
      d.scanned ? h("span", { class: "it" }, icon("eye", { size: 12 }), d.scanned) : null],
    meta: [
      d.bib ? h("p", { class: "dv-bib" }, icon("library", { size: 13 }), h("span", {}, "In your ", h("a", { href: "#/bibliography" }, "bibliography"), ": ", h("strong", {}, d.bib.cite || d.bib.title)),
        d.bib.title && d.bib.title !== d.title ? [h("span", { class: "sep" }, "·"), h("span", { class: "serif" }, d.bib.title)] : null,
        d.bib.doi && d.bib.doi !== d.doi ? [h("span", { class: "sep" }, "·"), h("a", { href: `https://doi.org/${d.bib.doi}`, target: "_blank", rel: "noopener noreferrer" }, `doi ${d.bib.doi}`)] : null,
        safeHref(d.bib.link, ["http", "https", "zotero"]) ? [h("span", { class: "sep" }, "·"), h("a", { href: safeHref(d.bib.link, ["http", "https", "zotero"]) }, "Open in Zotero")] : null) : null,
      // 0.13.3: the heading is the title of the work; the one read from the file stays visible, on a line of its own
      d.file_title ? h("p", { class: "muted small dv-file-title" }, "Title in the file: ", h("span", { class: "serif" }, d.file_title)) : null,
      h("div", { class: "row dv-head-row" },
        originalLink(project, docId, hit >= 0 ? blocks[hit].page : null, d.kind, { info: d.original || undefined, quote: quoteText, text: d.kind === "pdf" ? (hit >= 0 && blocks[hit].page ? `Open the original PDF at page ${blocks[hit].page}` : "Open the original PDF") : quoteText ? "Open the original at the quote" : "Open the original" }),
        copyBtn),
      span ? h("p", { class: "muted small dv-span-note" }, hit >= 0 ? (span.whole ? `The excerpt from the result is highlighted, in ${blocks[hit].label.toLowerCase()}.` : `The quote from the result is highlighted, in ${blocks[hit].label.toLowerCase()}.`) : "The quote could not be placed in this text.") : null] }));
  let docRole = null;   // 0.18.8 (N3): a working document's selection offers Check against the corpus
  view.appendChild(await roleBox(project, docId, d.title || d.file || "this document", (r) => { docRole = r; }));   // 0.18.1 K2: theory or evidence

  // ----------------------------------------------------------------- the text, with layers of highlights
  const nodeAt = new WeakMap();        // text node -> document offset of its first character
  const rows = new Map();              // block n -> {row, b, sig}
  const loaded = [];                   // the blocks shown, in order
  const list = card({ as: "div", class: "doc-view dv-text" });
  const moreBox = h("div", { class: "dv-more" });
  const selBar = h("div", { class: "dv-selbar", role: "toolbar", "aria-label": "With the selected text", hidden: true });
  let focus = null;                    // the place jumped to last: {start, end, cls, extra: [decorations]}
  let docNotes = [];                   // 0.16 (F2): the notes and highlights on this document's words

  // 0.15 (A4): a document read by the new reader comes block by block, each knowing what it is. Headings, captions and
  // tables look like what they are, a page mark stands where a page begins, and what was left out of the text
  // (running heads, page numbers, front and back matter, footnotes, tables...) is folded under "Left out of the text",
  // each with Restore; every block that counts has Leave out.
  let leftFold = null, lastPage = null;
  // 0.18.1 (reader 5): a figure with its place on a PDF page whose pictures can be drawn shows its picture in the text,
  // where it stands, with its caption and the way to its page; it is never read (its words stay out of the passages),
  // so it is not folded under "Left out of the text". Without a box (a Word file's or web page's picture: its
  // alternative text only), without page pictures, or when its picture cannot be drawn, it is folded as before.
  const figureFailed = new Set();      // figures whose picture could not be drawn: folded, as before
  const figureEls = new Map();         // n -> its <figure>, kept so a repaint does not load the picture again
  // (reader 5 only: an earlier reader's "figure" is the words inside a figure, folded with its Restore, review 9)
  const shownFigure = (b) => reading && (d.reader || 1) >= 5 && b.kind === "figure" && !!b.box && !!d.page_images && !figureFailed.has(b.n);
  // a figure's caption: the caption block just after it, else just before it
  function captionOf(b) {
    const i = loaded.indexOf(b);
    if (i < 0) return null;
    for (const j of [i + 1, i - 1]) if (loaded[j] && loaded[j].kind === "caption") return loaded[j];
    return null;
  }
  function figureBody(b, decos) {
    const cap = captionOf(b);
    let el = figureEls.get(b.n);
    if (!el) {
      const img = h("img", { class: "dv-figure-img", loading: "lazy", decoding: "async",
        src: `${docBase}/figures/${b.n}.png?scale=1.5&token=${encodeURIComponent(TOKEN)}`,
        alt: cap ? cap.text : `Figure on page ${b.page}` });
      img.addEventListener("error", () => figureGone(b));
      el = { fig: h("figure", { class: "dv-figure" }), img, capEl: h("figcaption", { class: "small muted dv-figure-cap" }),
        words: h("div", { class: "dv-figure-words" }) };
      el.fig.append(img, el.capEl,
        h("div", { class: "dv-figure-act" }, link({ kind: "jump", onClick: () => openPageAt(b.page) }, icon("file-text", { size: 12 }), "Open the page")),
        el.words);
      figureEls.set(b.n, el);
    }
    if (cap) el.img.alt = cap.text;
    el.capEl.textContent = cap ? cap.text : "";
    el.capEl.hidden = !cap;
    // the words inside the figure, when it has any: out of the passages, behind a small fold
    replace(el.words, (b.text || "").trim() ? fold({ sm: true }, "Words in the figure", blockText({ ...b, kind: "figure-words" }, decos)) : null);
    return el.fig;
  }
  // its picture could not be drawn (the original is gone, or the page cannot be read): folded as before, silently
  function figureGone(b) {
    if (figureFailed.has(b.n)) return;
    figureFailed.add(b.n);
    figureEls.delete(b.n);
    const r = rows.get(b.n);
    if (!r) return;
    r.row.classList.add("dv-out");
    r.row.classList.remove("dv-figure-row");
    const f = h("details", { class: "dv-fold" }, h("summary", {}, icon("chevron-right", { size: 13 }), h("span", {}, "Left out of the text: ", kindCount("figure", 1))));
    r.row.replaceWith(f);
    f.appendChild(r.row);
    r.sig = null;
    replace(r.body, blockText(b, []));
  }
  function openPageAt(page) {
    openTab("page");
    if (panels.page && panels.page.goTo) panels.page.goTo(page);
  }
  // the label column: where the block is cited, a mark when a person changed it, and (on hover) its actions
  function labelParts(b) {
    return [b.label ? h("b", {}, b.label) : null,
      b.bound ? h("span", { class: "dv-mine" }, b.bound === "start" ? "the text starts here (you said)" : "the text ends here (you said)") : null,
      b.changed ? h("span", { class: "dv-mine" }, b.included ? "restored by you" : "left out by you") : null,
      b.kind === "table" && b.included === false && !b.changed ? h("span", { class: "dv-mine dv-muted" }, "left out") : null,
      reading ? blockActions(b) : null];
  }
  const rowWatchers = new Set();       // observers that follow every row (the Page panel’s), the rows added later too
  function addBlocks(bs) {
    for (const b of bs) {
      if (rows.has(b.n)) continue;     // drawn already: a block is on the page once, so blockAt’s search holds
      const body = h("div", { class: "dv-body" });
      const kindCls = b.kind ? ` dv-k-${b.kind}${b.included === false && !shownFigure(b) ? " dv-out" : ""}${shownFigure(b) ? " dv-figure-row" : ""}${b.changed ? " dv-changed" : ""}${b.joined ? " dv-joined" : ""}` : "";
      const label = h("div", { class: "pp" }, labelParts(b));
      const row = h("div", { class: "passage-row" + kindCls, "data-found": hit >= 0 && b.n === blocks[hit].n ? "true" : null }, label, body);
      row.id = `block-${b.n}`;
      rows.set(b.n, { row, body, label, b, sig: null });
      place(b, row, keptOpen);
      loaded.push(b);
      for (const w of rowWatchers) w.observe(row);
    }
  }
  // where a block's row goes: after a page mark where a page begins; folded under "Left out of the text" when it is
  // left out (a table stays in the text, greyed), the fold open when what is left out is shown or `openNs` (blocks by
  // n) holds one of its blocks
  function place(b, row, openNs) {
    if (reading && b.page != null && b.page !== lastPage) {
      lastPage = b.page;
      leftFold = null;
      list.insertBefore(h("div", { class: "dv-page-mark", id: `page-${b.page}` }, h("span", {}, `Page ${b.page}`)), selBar);
    }
    if (reading && b.included === false && b.kind !== "table" && !shownFigure(b)) {
      if (!leftFold) {
        leftFold = { el: h("details", { class: "dv-fold" }), kinds: new Map() };
        leftFold.sum = h("summary", {});
        leftFold.el.appendChild(leftFold.sum);
        if (showLeftOut) leftFold.el.open = true;
        list.insertBefore(leftFold.el, selBar);
      }
      if (openNs.has(b.n)) leftFold.el.open = true;
      leftFold.kinds.set(b.kind, (leftFold.kinds.get(b.kind) || 0) + 1);
      replace(leftFold.sum, icon("chevron-right", { size: 13 }), h("span", {}, "Left out of the text: ", [...leftFold.kinds].map(([k, n]) => kindCount(k, n)).join(", ")));
      leftFold.el.appendChild(row);
    } else {
      leftFold = null;
      list.insertBefore(row, selBar);
    }
  }
  let showLeftOut = !!session(`leftout:${docId}`);
  const panels = {};
  // what the parts of the page in other files (leaving out in place: doc-leave-out.js; the panels: doc-reading.js, doc-codes.js,
  // doc-lookup.js) take from it: its values by name, and the three that they also change (the codebook, the choice to show
  // what is left out) or read as they are now (the open tab)
  const ctx = {
    project, base, docBase, docId, query, d, reading, blocks, totalBlocks, hit, loaded, rows, rowWatchers, list, selBar, watchers, cleanups, panels,
    jumpTo, paint, loadMore, openTab, keepUrl, docSlice, shownFigure, labelParts, place,
    resetFold() { leftFold = null; lastPage = null; },
    get tab() { return tab; },
    get framework() { return framework; }, set framework(v) { framework = v; },
    get showLeftOut() { return showLeftOut; }, set showLeftOut(v) { showLeftOut = v; },
  };
  // Restore, Leave out and where the text starts or ends, in place (doc-leave-out.js)
  const { blockActions } = leaveOut(ctx);
  // 0.15: after a move to the new reader, the folds holding what changed stay open
  const keptOpen = new Set(keep.place && keep.place.doc === docId ? keep.place.open || [] : []);
  list.appendChild(selBar);
  addBlocks(blocks);

  function drawMore() {
    clear(moreBox);
    if (loaded.length >= totalBlocks) return;
    moreBox.appendChild(button({ sm: true, onClick: (e) => { e.currentTarget.disabled = true; loadMore().then(() => paint()); } }, icon("chevron-down", { size: 13 }),
      reading ? `Show the rest of the document (${fmt.num(totalBlocks - loaded.length)} more parts)` : `Show the rest of the document (${fmt.num(totalBlocks - loaded.length)} more ${blockUnit(blocks[0])})`));
  }
  // one load at a time: a second call while one is under way (a jump, the Page panel, "Show the rest") waits for it
  // instead of asking for the same 500 blocks again
  let loading = null;
  function loadMore() {
    if (!loading) loading = loadNext().finally(() => { loading = null; });
    return loading;
  }
  async function loadNext() {
    if (loaded.length >= totalBlocks) return false;
    let r;
    try { r = await api("GET", `${docBase}?view=blocks&offset=${loaded.length}&limit=500`); } catch (e) { showError(e); return false; }
    const bs = r.blocks || [];
    const before = loaded.length;
    addBlocks(bs);
    drawMore();
    return loaded.length > before;
  }
  // make sure the text up to a document offset is on the page
  async function ensureLoaded(off) {
    while (loaded.length < totalBlocks && loaded[loaded.length - 1].end < off) { if (!(await loadMore())) break; }
  }
  function blockAt(off) {
    let lo = 0, hi = loaded.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1, b = loaded[mid];
      if (off < b.start) hi = mid - 1; else if (off >= b.end) lo = mid + 1; else return b;
    }
    return null;
  }
  // the text between two document offsets, when both are in one block
  function docSlice(s, e) {
    const b = blockAt(s);
    if (!b || e > b.end) return null;
    const pos = textPositions(b.text);
    return b.text.slice(pos.index(s - b.start), pos.index(e - b.start));
  }

  // Every decoration: {start, end, cls, mark (a highlight, drawn as <mark>), term (a key term's id)} in document offsets
  function decorations() {
    const out = [];
    if (span) out.push({ start: span.start, end: span.end, cls: "quote", mark: true });
    // 0.16: your highlights and notes, always shown (a note with words of yours is underlined too)
    for (const n of docNotes) if (!n.lost) out.push({ start: n.start, end: n.end, cls: `hl hl-${n.colour || "yellow"}${n.text ? " hl-noted" : ""}`, mark: true, note: n.note_id });
    const p = tab && panels[tab];
    if (p && p.decos) for (const x of p.decos()) out.push(x);
    if (focus) { out.push({ start: focus.start, end: focus.end, cls: focus.cls || "dv-focus", mark: !focus.soft }); for (const x of focus.extra || []) out.push(x); }
    return out;
  }
  // one sweep of the decorations, sorted by where they start, along the blocks in their order: each block takes the
  // ones that overlap it from those started before its end (a search with thousands of hits and a document of
  // thousands of blocks no longer filter every decoration for every block on every jump)
  function paint() {
    const all = decorations().sort((x, y) => x.start - y.start);
    let next = 0, open = [];
    for (const b of loaded) {
      while (next < all.length && all[next].start < b.end) open.push(all[next++]);
      open = open.filter((x) => x.end > b.start);   // ended before this block: no later block has it either
      const r = rows.get(b.n);
      const mine = open.filter((x) => x.start < b.end);
      const fig = shownFigure(b);
      const sig = mine.map((x) => `${x.start}-${x.end}-${x.cls}-${x.term || ""}-${x.note || ""}`).join("|")
        + (fig ? `|fig:${(captionOf(b) || {}).n ?? ""}` : "");   // its caption may come with the next blocks loaded
      if (r.sig === sig) continue;
      r.sig = sig;
      replace(r.body, fig ? figureBody(b, mine) : blockText(b, mine));
    }
  }
  // A block’s text cut at its headings (as blockNode does), each piece under the decorations that cover it. The
  // decorations and headings are the app’s offsets: cut here at the indices of the block’s own text, and each piece
  // remembers the app’s offset of its first character (nodeAt).
  // a cell that holds only a figure (a number, a share, an amount): it stays on one line, right-aligned
  const FIGURE = /^[\s\d.,%€$£+\-–−()]+$/;
  function blockText(b, decos) {
    const text = b.text || "";
    const pos = textPositions(text);
    if (b.table && !decos.length) {
      const rowsT = b.table.rows || [];
      return h("div", { class: "dv-table-wrap" }, h("table", { class: "dv-table" },
        rowsT.length ? h("thead", {}, h("tr", {}, rowsT[0].map((c) => h("th", { scope: "col" }, c)))) : null,
        h("tbody", {}, rowsT.slice(1).map((r) => h("tr", {}, r.map((c) => h("td", { class: FIGURE.test(c || "") ? "num" : null }, c)))))));
    }
    const breaks = breaksToIndex(text, (b.headings || []).map((x) => ({ at: x.at, end: x.end, kind: "heading" })));
    const segs = breakSegments(text, breaks);
    const spans = decos.map((x) => ({ x, a: pos.index(x.start - b.start), z: pos.index(x.end - b.start) }));
    const fill = (el, s0, s1) => {
      const cuts = new Set([s0, s1]);
      for (const { a, z } of spans) { if (a > s0 && a < s1) cuts.add(a); if (z > s0 && z < s1) cuts.add(z); }
      const pts = [...cuts].sort((p, q) => p - q);
      for (let i = 0; i < pts.length - 1; i++) {
        const a = pts[i], z = pts[i + 1];
        const on = spans.filter((s) => s.a < z && s.z > a).map((s) => s.x);
        const t = document.createTextNode(text.slice(a, z));
        nodeAt.set(t, b.start + pos.point(a));
        if (!on.length) { el.appendChild(t); continue; }
        const terms = on.filter((x) => x.term).map((x) => x.term);
        const noteIds = on.filter((x) => x.note).map((x) => x.note);   // 0.16: a click on a highlight opens its note
        const ds = {};
        if (terms.length) ds.terms = terms.join(" ");
        if (noteIds.length) ds.notes = noteIds.join(" ");
        const piece = h(on.some((x) => x.mark) ? "mark" : "span", { class: [...new Set(on.map((x) => x.cls))].join(" "), dataset: Object.keys(ds).length ? ds : null });
        piece.appendChild(t);
        el.appendChild(piece);
      }
      return el;
    };
    if (!segs) return fill(h("p", {}), 0, text.length);
    return h("div", { class: "passage-broken" }, segs.map((sg) => fill(h("p", { class: sg.heading ? "passage-heading" : "passage-para" }), sg.start, sg.end)));
  }

  // Go to a place in the text and mark it: {start, end}; opts.soft marks a whole passage lightly, opts.extra adds marks.
  async function jumpTo(where, opts = {}) {
    if (!where || !Number.isInteger(where.start)) return;
    await ensureLoaded(where.end);
    focus = { start: where.start, end: Math.max(where.end, where.start + 1), cls: opts.soft ? "dv-focus-soft" : "dv-focus", soft: !!opts.soft, extra: opts.extra || [] };
    paint();
    const b = blockAt(where.start);
    if (!b) { toast("This place is not in the text shown.", "warn"); return; }
    const r = rows.get(b.n);
    const leftFold = r.row.closest("details");
    if (leftFold) leftFold.open = true;  // 0.15: a place in text that was left out
    const target = r.row.querySelector(".dv-focus, .dv-focus-soft") || r.row;
    target.scrollIntoView({ block: "center", behavior: opts.instant ? "auto" : "smooth" });
    r.row.classList.remove("ev-flash"); void r.row.offsetWidth; r.row.classList.add("ev-flash");
    setTimeout(() => r.row.classList.remove("ev-flash"), 1700);
  }

  // where a click or a selection is, as a document offset (the app’s count: a node’s offset is an index of its text)
  function docOffset(node, offset, isEnd) {
    if (node.nodeType === Node.TEXT_NODE) { const o = nodeAt.get(node); return o === undefined ? null : o + textPositions(node.data).point(offset); }
    const walker = document.createTreeWalker(list, NodeFilter.SHOW_TEXT);
    const ref = node.childNodes[offset] || null;
    let t = null;
    if (isEnd) {
      if (ref) { walker.currentNode = ref; t = walker.previousNode(); }
      else { let last = node; while (last.lastChild) last = last.lastChild; t = last.nodeType === Node.TEXT_NODE ? last : (walker.currentNode = last, walker.previousNode()); }
      return t && nodeAt.has(t) ? nodeAt.get(t) + cpLength(t.data) : null;
    }
    if (ref && ref.nodeType === Node.TEXT_NODE) t = ref;
    else if (ref) { walker.currentNode = ref; t = walker.nextNode(); }
    else { let last = node; while (last.lastChild) last = last.lastChild; walker.currentNode = last; t = walker.nextNode(); }
    return t && nodeAt.has(t) ? nodeAt.get(t) : null;
  }
  function caretAt(x, y) {
    if (document.caretPositionFromPoint) { const p = document.caretPositionFromPoint(x, y); return p ? { node: p.offsetNode, offset: p.offset } : null; }
    if (document.caretRangeFromPoint) { const r = document.caretRangeFromPoint(x, y); return r ? { node: r.startContainer, offset: r.startOffset } : null; }
    return null;
  }
  function wordAt(off) {
    const b = blockAt(off);
    if (!b) return null;
    const t = b.text;
    const pos = textPositions(t);
    const span = wordSpan(t, pos.index(off - b.start));   // lib.js: a letter outside the BMP is one letter
    if (!span) return null;
    const [s, e] = span;
    return { start: b.start + pos.point(s), end: b.start + pos.point(e), text: t.slice(s, e) };
  }

  // a click on a word (with Search in this document open) adds it to the search; Shift-click makes a phrase
  list.addEventListener("mousedown", (e) => { if (tab === "search" && e.shiftKey && !e.target.closest(".dv-selbar")) e.preventDefault(); });
  list.addEventListener("click", (e) => {
    if (tab !== "search" || e.target.closest(".dv-selbar, button, a, [data-notes]")) return;
    const sel = window.getSelection();
    if (sel && !sel.isCollapsed) return;
    const pos = caretAt(e.clientX, e.clientY);
    if (!pos) return;
    const off = docOffset(pos.node, pos.offset, false);
    if (off === null) return;
    const w = wordAt(off);
    if (w) panels.search.addWord(w, e.shiftKey);
  });

  // a selection in the text: search for it, see every mention of it (references), or label it with a code
  function readSelection() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    const r = sel.getRangeAt(0);
    if (!list.contains(r.commonAncestorContainer) || selBar.contains(r.commonAncestorContainer)) return null;
    let a = docOffset(r.startContainer, r.startOffset, false), z = docOffset(r.endContainer, r.endOffset, true);
    if (a === null || z === null || z <= a) return null;
    const raw = docSlice(a, z);
    if (raw === null) return { tooLong: true, rect: r.getBoundingClientRect() };
    const text = raw.replace(/\s+/g, " ").trim();
    if (!text) return null;
    a += raw.length - raw.trimStart().length;
    z -= raw.length - raw.trimEnd().length;
    return { start: a, end: z, text, rect: r.getBoundingClientRect() };
  }
  let selNow = null;
  function showSelBar() {
    const s = readSelection();
    if (!s) { selBar.hidden = true; selNow = null; return; }
    if (s.tooLong) { selNow = null; replace(selBar, h("span", { class: "muted small" }, "Select words within one paragraph or page.")); }
    else {
      selNow = s;
      const act = (ic, label, fn) => button({ kind: "quiet", sm: true, onMousedown: (e) => e.preventDefault(), onClick: () => { const x = selNow; selBar.hidden = true; fn(x); } }, icon(ic, { size: 13 }), label);
      replace(selBar,
        // 0.16 (F2): keep the words, plainly or with a note of yours
        act("highlighter", "Highlight", (x) => addNote(x, "", "yellow")),
        act("note", "Note", (x) => noteDialog(x)),
        act("text-search", "Search in this document", (x) => { openTab("search"); panels.search.searchFor(x.text.split(" ").length > 1 ? `"${x.text}"` : x.text); }),
        x0(s) ? act("link", "Every mention of this", (x) => { openTab("refs"); panels.refs.lookup(x); }) : null,
        act("tag", "Label it with a code", (x) => { openTab("codes"); panels.codes.labelSelection(x); }),
        // 0.18.8 (N3): a sentence of your own draft, checked against the corpus (the draft itself is never a source)
        docRole === "working" && s.text.length <= 1000 ? act("list-checks", "Check against the corpus", (x) => navigate(`#/hypotheses?text=${encodeURIComponent(x.text)}`)) : null);
    }
    const lr = list.getBoundingClientRect();
    const rect = (s.rect) || lr;
    selBar.hidden = false;
    const w = selBar.offsetWidth || 300;
    selBar.style.top = `${Math.round(rect.bottom - lr.top + 6)}px`;
    selBar.style.left = `${Math.round(Math.max(8, Math.min(rect.left - lr.left, lr.width - w - 8)))}px`;
  }
  const x0 = (s) => s.text.length <= 120;

  // ---- 0.16 (F2): notes and highlights on the words of the document
  async function loadNotes() {
    try { docNotes = (await api("GET", `${docBase}/notes`)).notes || []; } catch (e) { docNotes = []; return; }
    paint();
    if (panels.notes) panels.notes.refresh();
  }
  async function addNote(x, text, colour) {
    try {
      const r = await api("POST", `${base}/notes`, { doc_id: docId, start: x.start, end: x.end, quote: x.text, text, colour });
      const sel = window.getSelection();
      if (sel) sel.removeAllRanges();
      docNotes.push(r.note);
      paint();
      if (panels.notes) panels.notes.refresh();
      toast(text ? "Note kept. It is in Notes, and can be evidence in a check." : "Highlighted. Click it to add a note, use it as evidence or remove it.", "ok", { small: true, group: "note" });
    } catch (e) { showError(e); }
  }
  async function noteDialog(x) {
    let colour = "yellow";
    const ta = textarea({ rows: 4, maxlength: 10000, placeholder: "What these words mean for your work…" });
    const body = h("div", {}, h("blockquote", { class: "note-quote" }, x.text),
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Your note"), ta),
      h("div", { class: "field" }, h("span", { class: "field-label" }, "Colour"), colourPicker(colour, (c) => { colour = c; })));
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { const b = ta.closest("dialog").querySelector(".btn-primary"); if (b) b.click(); } });
    const r = await dialog({ title: "Add a note", body, actions: [{ text: "Cancel", value: null }, { text: "Keep the note", value: true, primary: true }], onOpen: () => ta.focus() });
    if (r) await addNote(x, ta.value.trim(), colour);
  }
  function showNoteBar(n, rect) {
    selNow = null;
    const act = (ic, label, fn, danger) => button({ kind: danger ? "danger" : "quiet", sm: true, onClick: () => { selBar.hidden = true; fn(); } }, icon(ic, { size: 13 }), label);
    replace(selBar,
      h("div", { class: "dv-notebar-text" }, n.text ? n.text : h("span", { class: "muted" }, n.mine ? "A highlight (no note)" : `A highlight by ${n.who}`), n.mine ? null : h("span", { class: "muted small" }, ` · ${n.who}`)),
      h("div", { class: "dv-notebar-actions" },
        n.mine ? act("note", n.text ? "Edit" : "Add a note", async () => { const got = await editNote(n); if (got) { Object.assign(n, got); paint(); if (panels.notes) panels.notes.refresh(); } }) : null,
        act("flask", "Use as evidence", () => useAsEvidence(n)),
        n.mine ? act("trash", "Remove", async () => { if (await removeNote(n)) { docNotes = docNotes.filter((x) => x.note_id !== n.note_id); paint(); if (panels.notes) panels.notes.refresh(); } }, true) : null));
    const lr = list.getBoundingClientRect();
    selBar.hidden = false;
    const w = selBar.offsetWidth || 300;
    selBar.style.top = `${Math.round(rect.bottom - lr.top + 6)}px`;
    selBar.style.left = `${Math.round(Math.max(8, Math.min(rect.left - lr.left, lr.width - w - 8)))}px`;
    const first = selBar.querySelector("button");
    if (first) first.focus({ preventScroll: true });
  }
  list.addEventListener("click", (e) => {
    const m = e.target.closest("[data-notes]");
    if (!m || e.target.closest(".dv-selbar, button, a")) return;
    const sel = window.getSelection();
    if (sel && !sel.isCollapsed) return;
    const n = docNotes.find((x) => x.note_id === m.dataset.notes.split(" ")[0]);
    if (n) showNoteBar(n, m.getBoundingClientRect());
  });
  function notesPanel() {
    const listEl = h("ul", { class: "notes-cards notes-cards-doc" });
    const head = h("p", { class: "muted small" });
    const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-notes-h" },
      h("h2", { id: "dv-notes-h", class: "dv-panel-title" }, "Your notes"), head, listEl,
      h("p", { class: "small" }, h("a", { href: "#/notes" }, "All notes of the project"), " · notes stay on this computer and go with the project when you share it."));
    function refresh() {
      replace(head, docNotes.length ? `${plural(docNotes.length, "note")} on this document. Click one to find it in the text.` : "None yet. Select words in the text, then choose Highlight or Note.");
      clear(listEl);
      for (const n of docNotes) listEl.appendChild(noteCard(n, loadNotes, { inDocument: true, onJump: (x) => jumpTo({ start: x.start, end: x.end }) }));
    }
    refresh();
    return { el, refresh };
  }
  // 0.16: a click on a highlight (no words selected) opens its note's bar: the selection's bar must not close it
  const onHighlight = (e) => { const sel = window.getSelection(); return !!(e.target.closest && e.target.closest("[data-notes]") && (!sel || sel.isCollapsed)); };
  list.addEventListener("mouseup", (e) => { if (!onHighlight(e)) setTimeout(showSelBar, 0); });
  list.addEventListener("touchend", (e) => { if (!onHighlight(e)) setTimeout(showSelBar, 250); });
  list.addEventListener("keyup", (e) => { if (e.shiftKey) setTimeout(showSelBar, 0); });
  const onSelChange = () => { const sel = window.getSelection(); if (!selBar.hidden && (!sel || sel.isCollapsed) && !selBar.contains(document.activeElement)) selBar.hidden = true; };
  document.addEventListener("selectionchange", onSelChange);
  cleanups.push(() => document.removeEventListener("selectionchange", onSelChange));
  selBar.addEventListener("keydown", (e) => { if (e.key === "Escape") selBar.hidden = true; });

  // ----------------------------------------------------------------- the panels
  const tabsRow = h("div", { class: "dv-tabs" });
  const panelBox = h("div", { class: "dv-panel-box" });
  const intro = h("p", { class: "muted small dv-intro" }, "Show next to the text: which codes of a codebook it addresses, its key terms, what “it” and “they” refer to, search inside it, how it was read", d.page_images ? ", or the page of the original beside the text." : ".");
  const side = card({ sm: true, as: "aside", class: "dv-side", "aria-label": "About this document" }, tabsRow, panelBox);
  const layout = h("div", { class: "dv-layout" }, side, h("div", { class: "dv-main" }, list, moreBox));
  view.appendChild(layout);

  const makers = { codes: () => codesPanel(ctx), terms: () => termsPanel(ctx), refs: () => refsPanel(ctx), search: () => searchPanel(ctx), notes: notesPanel, reading: () => readingPanel(ctx), page: () => pagePanel(ctx) };
  function drawTabs() {
    // which panel shows beside the text: a choice (docs/DESIGN.md 4.6); picking the chosen one again closes it
    replace(tabsRow, choice({ filter: true, label: "Show next to the text", value: tab,
      options: DOC_TABS.filter(([k]) => k !== "page" || d.page_images).map(([k, label, ic]) => [k, [icon(ic, { size: 13 }), label]]),
      onPick: (k) => { openTab(tab === k ? null : k); const b = tabsRow.querySelector(`[data-value="${k}"]`); if (b) b.focus(); } }));
  }
  function openTab(k, fromUser = true) {
    if (k === tab && (!k || panels[k])) return;
    tab = k;
    focus = null;
    drawTabs();
    if (!k) { replace(panelBox, intro); keepUrl(); paint(); return; }
    if (!panels[k]) panels[k] = makers[k]();
    replace(panelBox, panels[k].el);
    if (panels[k].show) panels[k].show(fromUser);
    keepUrl();
    paint();
  }
  function keepUrl() {
    const s = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (!["tab", "code", "find", "framework", "preview"].includes(k)) s.set(k, v);
    if (tab) s.set("tab", tab);
    if (framework !== (App.settings().profile_framework || "sdg")) s.set("framework", framework);
    if (tab === "search" && panels.search && panels.search.query()) s.set("find", panels.search.query());
    const qs = s.toString();
    history.replaceState(null, "", `#/doc/${encodeURIComponent(docId)}${qs ? "?" + qs : ""}`);
  }

  // ---- a highlighted copy to keep (F7)
  async function highlightedCopy() {
    const isPdf = d.kind === "pdf" && d.original && d.original.available;
    const fwNow = panels.codes ? panels.codes.framework() : framework;
    const fwTitle = panels.codes ? panels.codes.frameworkTitle() : fwNow === "sdg" ? "the SDG targets" : fwNow;
    const box = (id, label, help, checked, disabled) => h("label", { class: "dv-layer", for: id }, h("input", { type: "checkbox", id, checked, disabled }), h("span", {}, h("strong", {}, label), h("span", { class: "muted small" }, help)));
    const body = h("div", {},
      h("p", {}, isPdf ? "A copy of the original PDF with highlights and a note on each, readable in any PDF reader."
        : d.kind === "pdf" ? "The original PDF is no longer available, so you get a copy of the text the app read, as a web page (HTML) with coloured highlights."
        : "A copy of the text as a web page (HTML) with coloured highlights and notes, to open in any browser."),
      h("fieldset", { class: "dv-layers" }, h("legend", { class: "field-label" }, "What to highlight"),
        box("dv-l-j", "The AI's and your judgements", "From every result that read this document: green supports, amber partly supports, red contradicts. Always included.", true, true),
        box("dv-l-l", "Codebook labels", `The quotes the AI or you gave for a code of ${fwTitle.startsWith("the ") ? fwTitle : `“${fwTitle}”`} (blue). Codes found by keywords alone have no quote and are left out.`, tab === "codes", false),
        box("dv-l-r", "References", "The mentions the AI linked to a name (grey).", tab === "refs", false)));
    await dialog({
      title: "Download a highlighted copy",
      body,
      actions: [{ text: "Cancel", value: null }, { text: isPdf ? "Download the PDF" : "Download the HTML copy", primary: true, value: true, onClick: async (dlg) => {
        const layers = ["judgements"];
        if (dlg.querySelector("#dv-l-l").checked) layers.push("labels");
        if (dlg.querySelector("#dv-l-r").checked) layers.push("references");
        const btn = dlg.querySelector(".dialog-actions .btn-primary");
        btn.disabled = true;
        try {
          const res = await download(`${docBase}/annotated.pdf?layers=${layers.join(",")}&framework=${encodeURIComponent(fwNow)}`, undefined, `${d.title || docId} - highlighted.${isPdf ? "pdf" : "html"}`);
          const [placed, marks] = (res.headers.get("X-Enlens-Placed") || "").split("/").map(Number);
          if (!marks) toast("Downloaded. There was nothing to highlight yet with what you chose.", "info");
          else if (placed < marks) toast(`Downloaded: ${placed} of ${plural(marks, "highlight")} placed. The others are listed ${isPdf ? "in a note on the first page" : "at the top"}.`, "warn");
          else toast(`Downloaded with ${plural(marks, "highlight")}.`, "ok");
          return true;
        } catch (e) { showError(e); btn.disabled = false; return false; }
      } }],
    });
  }

  drawTabs();
  // 0.15: back where the reader was after Restore, Leave out or a move to the new reader
  const kept = keep.place && keep.place.doc === docId ? keep.place : null;
  keep.place = null;
  if (kept && kept.tab && DOC_TABS.some(([k]) => k === kept.tab)) tab = kept.tab;
  if (tab) { const k = tab; tab = null; openTab(k, false); } else { replace(panelBox, intro); paint(); }
  drawMore();
  await loadNotes();  // 0.16
  if (query.at && /^\d+$/.test(query.at)) {  // from the Notes page: the note at this place
    const at = Number(query.at);
    const n = docNotes.find((x) => !x.lost && x.start <= at && x.end > at);
    if (n) setTimeout(() => jumpTo({ start: n.start, end: n.end }), 60);
  }
  if (kept && kept.y) setTimeout(() => window.scrollTo(0, kept.y), 40);
  if (kept && kept.focus) setTimeout(() => { const f = document.getElementById(kept.focus); if (f) f.focus(); }, 60);
  if (span && span.end > (loaded[loaded.length - 1] || { end: 0 }).end) await ensureLoaded(span.end).then(paint);
  if (hit >= 0 || span) setTimeout(() => { const b = span ? blockAt(span.start) : null; const row = b ? document.getElementById(`block-${b.n}`) : null; if (row && row.closest("details")) row.closest("details").open = true; const el = (row && row.querySelector("mark.quote")) || row; if (el) el.scrollIntoView({ block: "center" }); }, 60);
  return () => { watchers.forEach((w) => w.stop()); cleanups.forEach((f) => f()); };
}
