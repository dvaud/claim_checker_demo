// A document's page, the Reading and Page panels: how the document was read, moving it to the new reader (doc-page.js
// builds the panels and hands each the page's `ctx`), and the page of the original PDF beside the text.
import { App, api, h, icon, replace, clear, toast, showError, fmt, watchJob, session, plural, cap, TOKEN, button,
  link, notice } from "../lib.js";
import { keep, newReaderFor, READER_4_NEWS, READER_5_NEWS, kindCount } from "./doc-shared.js";

// 0.15 (A0): how many results a move to the new reader places (reread.move's counts, per kind of result)
const movedCount = (r) => Object.values((r && r.counts) || {}).reduce((a, c) => a + (c.moved || 0), 0);

// ---- 0.15: how the document was read (A5), and moving it to the new reader (A0)
export function readingPanel(ctx) {
  const { d, docId, list, openTab } = ctx;
  const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-read-h" });
  const rep = d.reading || {};
  const older = newReaderFor(d, d.new_reader || 1);
  const before15 = (d.reader || 1) < 2;  // 0.15.1: a document of 0.15.0's reader has a reading report too
  const qual = { good: "Read well.", fair: "Read, with something to check.", poor: "Read badly: check it before you rely on it." }[rep.quality];
  const figs = [];
  const fig = (label, value, title) => { if (value) figs.push(h("li", { title: title || null }, h("span", { class: "muted" }, label), " ", value)); };
  const passFig = h("li", { title: "The passages that searches, codes, themes and checks read" });
  if (!before15) {
    fig("Pages:", rep.pages ? `${fmt.num(rep.pages)}${rep.multi_column_pages ? `, ${fmt.num(rep.multi_column_pages)} in columns (read column by column)` : ""}` : "");
    const rp = rep.repairs || {};
    const fixes = [rp.hyphens_joined && plural(rp.hyphens_joined, "word") + " cut at a line end joined", rp.hyphens_kept && plural(rp.hyphens_kept, "hyphen") + " kept (long-term, well-known)",
      rp.words_split && plural(rp.words_split, "word") + " that ran together split", rp.ligatures && plural(rp.ligatures, "ligature") + " (ﬁ, ﬂ) put right",
      rp.accents && plural(rp.accents, "accent") + " put on its letter", rp.spaces && plural(rp.spaces, "odd space") + " made plain",
      rp.doubled && plural(rp.doubled, "line") + " printed twice read once"].filter(Boolean);
    fig("Repaired:", fixes.join("; "));
    fig("Tables:", rep.tables ? `${fmt.num(rep.tables)}, kept as rows and cells (each can be downloaded for Excel from the text)` : "");
    // live: Restore and Leave out change it (0.16: drawn again in place, by live())
    if (d.passages_read != null) figs.push(passFig);
    if (rep.engine === "pypdf") fig("Read from:", "the text layer only (with the pdfminer extra, columns and tables are found too)");
  }
  const outKinds = () => Object.entries(d.left_out || {});
  const setLeftOut = (on) => {
    ctx.showLeftOut = on; session(`leftout:${docId}`, ctx.showLeftOut || null);
    for (const f of list.querySelectorAll("details.dv-fold")) f.open = ctx.showLeftOut;
  };
  let outBox = null;
  const outPart = h("div", { class: "dv-outkinds" });
  function live() {
    replace(passFig, h("span", { class: "muted" }, "Passages that count:"), " ", `${fmt.num(d.passages_read || 0)} of ${fmt.num(d.passages_all || 0)}`);
    const kinds = outKinds();
    outPart.hidden = !kinds.length;
    outBox = kinds.length ? h("input", { type: "checkbox", checked: ctx.showLeftOut, onChange: (e) => setLeftOut(e.currentTarget.checked) }) : null;
    replace(outPart, kinds.length ? [h("p", { class: "small dv-left-out" }, h("strong", {}, "Left out of the text: "), kinds.map(([k, n]) => kindCount(k, n)).join(", "), "."),
      h("p", { class: "muted small dv-left-out-note" }, "They stay in the document and in a search of all its text, but searches, codes, themes and checks do not read them. Restore any that should count; leave out any that should not."),
      h("label", { class: "dv-check" }, outBox, h("span", {}, "Show what was left out in the text"))] : []);
  }
  // 0.15.7: a warning's way to what it is about: the pages of the original, or what the reader set aside
  const showOut = () => {
    if (outBox) outBox.checked = true;
    setLeftOut(true);
    const f = list.querySelector("details.dv-fold");
    if (f) f.scrollIntoView({ block: "center", behavior: "smooth" });
  };
  const placeBtn = (place) => place === "page" && d.page_images ? link({ kind: "jump", onClick: () => openTab("page") }, icon("file-text", { size: 12 }), "Look at the pages")
    : place === "left_out" && outKinds().length ? button({ kind: "quiet", sm: true, onClick: showOut }, icon("eye", { size: 12 }), "Show what was left out") : null;
  el.append(...[h("h2", { id: "dv-read-h", class: "dv-panel-title", tabindex: "-1" }, "How this document was read"),
    older ? notice({ kind: "info" }, h("div", {},
      h("p", {}, before15 ? `Read by the reader of ENLENS before 0.15. ENLENS ${App.state.version || ""} has a new reader: it reads two columns in the right order, sets running heads, page numbers, author details, acknowledgements and the like aside, keeps tables as tables and repairs words broken over lines.`
        : d.reader === 2 ? `Read by the reader of ENLENS 0.15.0. The reader of ENLENS ${App.state.version || ""} also sets running heads, page numbers, contents pages and indexes aside in text files and books, finds their headings and paragraphs, and puts apart words that ran together.`
        : d.reader === 3 ? `Read by the reader of ENLENS 0.15.1 to 0.17.1. ${READER_4_NEWS}`
        : `Read by the reader of ENLENS 0.17.2 to 0.18.0. ${READER_5_NEWS}`),
      h("p", { class: "small" }, "Documents already in a project keep their reading, so every quote and judgement in them stays where it is, until you move one over."))) : null,
    // a reading to check needs you: an attention notice; a good one is a quiet line with the tick (DESIGN 3.3, 4.12)
    !before15 && qual ? (rep.quality === "good" ? h("p", { class: "dv-quality small" }, icon("check", { size: 14 }), ` ${qual}`)
      : notice({ kind: "attention", class: "dv-quality" }, h("p", {}, qual))) : null,
    (rep.warnings || []).length ? h("ul", { class: "dv-warn" }, rep.warnings.map((w, i) => h("li", {}, w, " ", placeBtn((rep.places || [])[i])))) : null,
    !before15 && (rep.quality === "fair" || rep.quality === "poor") ? checkedBox(ctx, rep) : null,
    figs.length ? h("ul", { class: "dv-figs" }, figs) : null,
    outPart,
    older ? rereadBox(ctx) : null].filter(Boolean));  // append(null) would write "null"
  live();
  return { el, live };
}

// 0.15.7: the person looked at what the reading report names and marks the reading as checked (or takes it
// back): the note in the list of documents goes away; a new reading of the document asks again
function checkedBox(ctx, rep) {
  const { docBase } = ctx;
  const box = h("div", { class: "dv-checked" });
  function draw() {
    const c = rep.checked;
    replace(box, c ? h("p", { class: "small dv-read-ok" }, icon("check", { size: 13 }),
      ` Checked by ${c.name || "you"}${c.at ? ` on ${fmt.dateShort(c.at)}` : ""}: the list of documents no longer asks for a look. `,
      button({ kind: "quiet", sm: true, onClick: (e) => mark(false, e.currentTarget) }, "Undo"))
      : [h("p", { class: "muted small dv-read-check" }, "Look at what each point names. If the text is good enough for your work, mark the reading as checked: the note in the list of documents goes away. A new reading of this document asks again."),
        button({ sm: true, onClick: (e) => mark(true, e.currentTarget) }, icon("check", { size: 13 }), "Checked: it reads well enough")]);
  }
  async function mark(on, btn) {
    btn.disabled = true;
    try {
      rep.checked = (await api("PUT", `${docBase}/reading-checked`, { checked: on })).checked;
      draw();
      const f = box.querySelector("button");
      if (f) f.focus();
      toast(on ? "Marked as checked." : "No longer marked as checked.", "ok", { ttl: 2500 });
    } catch (e) { btn.disabled = false; showError(e); }
  }
  draw();
  return box;
}

// 0.15 (A0): move a document read by an earlier reader to the new one, its results with it, after a preview
function rereadBox(ctx) {
  const { docBase, watchers, docId, query } = ctx;
  const box = h("div", { class: "dv-reread" });
  function drawStart(focusIt) {
    const start = button({ kind: "main", sm: true, onClick: (e) => preview(e.currentTarget) }, icon("layers", { size: 13 }), "Read with the new reader");
    replace(box, h("p", { class: "small dv-start-note" }, "See first what would change: how many of your results find their place in the new reading, and which do not. Nothing changes until you confirm."), start);
    if (focusIt) start.focus();
    return start;
  }
  async function preview(start) {
    start.disabled = true;
    replace(box, h("p", { class: "muted small", role: "status" }, icon("loader", { size: 13 }), " Reading the original file again (nothing changes yet)…"));
    let r;
    try { r = await api("GET", `${docBase}/reread`); }
    catch (e) { replace(box, notice({ kind: "error" }, h("p", {}, e.message))); return; }
    if (r.ok === false) { replace(box, notice({ kind: "attention", live: "status" }, h("p", {}, r.reason || "This document cannot be read again now."))); return; }
    const lost = r.not_placed || [];
    const moved = movedCount(r);
    const aside = Array.isArray(r.left_out) ? r.left_out : [];  // placed, in text the new reader leaves out
    const go = button({ kind: "main", sm: true, onClick: () => move(go) }, icon("check", { size: 13 }), "Move it to the new reader");
    const summary = h("p", { class: "small", tabindex: "-1" }, moved || lost.length ? [h("strong", {}, plural(moved, "result")), moved === 1 ? " finds its place" : " find their place", " in the new reading", lost.length ? [", ", h("strong", {}, `${fmt.num(lost.length)} ${lost.length === 1 ? "does" : "do"} not`)] : "", "."]
      : "Nothing in your results points into this document yet: it is simply read again.");
    replace(box, h("div", { class: "dv-reread-preview" }, summary,
      (r.warnings || []).length ? h("ul", { class: "dv-warn dv-preview-warn" }, r.warnings.map((w) => h("li", {}, w))) : null,
      lost.length ? h("ul", { class: "dv-lost" }, lost.slice(0, 12).map((x) => h("li", { class: "small" }, h("span", { class: "muted" }, `${cap(x.kind_text || x.what || "a result")}${x.page ? `, page ${x.page}` : ""}: `),
        x.quote ? `“${x.quote}”` : (x.what || ""), x.why ? h("span", { class: "muted" }, ` ${x.why}`) : null))) : null,
      lost.length > 12 ? h("p", { class: "muted small" }, `and ${fmt.num(lost.length - 12)} more.`) : null,
      aside.length ? h("ul", { class: "dv-lost" }, aside.slice(0, 12).map((x) => h("li", { class: "small" }, h("span", { class: "muted" }, `${cap(x.kind_text || "a result")}${x.page ? `, page ${x.page}` : ""}: `),
        x.quote ? `“${x.quote}”` : (x.what || ""), x.note ? h("span", { class: "muted" }, ` ${x.note}`) : null))) : null,
      r.reading && r.reading.quality ? h("p", { class: "muted small" }, `The new reading: ${plural(r.reading.body_passages, "passage")} that count${(r.reading.warnings || []).length ? `; ${r.reading.warnings.join(" ")}` : ", nothing to warn about."}`) : null,
      h("div", { class: "btn-row dv-start-actions" }, go, button({ kind: "quiet", sm: true, onClick: () => drawStart(true) }, "Not now"))));
    summary.focus();
  }
  async function move(btn) {
    btn.disabled = true;
    let job;
    try { job = (await api("POST", `${docBase}/reread`)).job; }
    catch (e) { btn.disabled = false; showError(e); return; }
    // the move is one step; then, as after adding a document, its search by meaning, key terms and keyword codes
    const moving = h("p", { class: "muted small", role: "status" }, icon("loader", { size: 13 }), " Moving it to the new reader, then updating its key terms and codes…");
    replace(box, moving);
    // 0.18 queued jobs: while another job of the project runs, the move waits its turn and says so
    let queued = false;
    const w = watchJob(job.id, (j) => {
      if (!!j.waiting_for === queued) return;   // redrawn only when it starts or stops waiting (the spinner goes on)
      queued = !!j.waiting_for;
      replace(moving, icon(queued ? "clock" : "loader", { size: 13 }), queued ? ` ${j.waiting_for.message}.` : " Moving it to the new reader, then updating its key terms and codes…");
    });
    watchers.push(w);
    let done;
    try { done = await w.promise; } catch (e) { showError(e); return; }
    if (done.state !== "done") { replace(box, notice({ kind: "error" }, h("p", {}, done.error || "The document could not be moved; nothing was changed."))); return; }
    const r = (done.result || {}).report || {};
    toast(`Read with the new reader: ${plural(movedCount(r), "result")} moved${(r.not_placed || []).length ? `, ${fmt.num(r.not_placed.length)} without a place` : ""}.`, "ok");
    keep.place = { doc: docId, y: 0, tab: "reading", focus: "dv-read-h" };
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  }
  const first = drawStart(false);
  if (query.preview === "1") setTimeout(() => preview(first), 0);  // 0.15.7: from the list of documents
  return box;
}

// ---- 0.15 (A4): the page of the original PDF beside the text, the blocks the reader found drawn on it
export function pagePanel(ctx) {
  const { reading, d, docBase, loaded, rows, jumpTo, totalBlocks, loadMore, paint, rowWatchers, cleanups, hit, blocks } = ctx;
  const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-page-h" });
  const SCALE = 1.5;
  let page = null;
  const img = h("img", { class: "dv-page-img", alt: "" });
  const boxes = h("div", { class: "dv-page-boxes", "aria-hidden": "true" });
  const frame = h("div", { class: "dv-page-frame" }, img, boxes);
  const nav = h("div", { class: "btn-row dv-page-nav" });
  const note = h("p", { class: "muted small dv-pagenav-note" }, reading ? "Outlined: what the reader found. Solid: read by searches, codes, themes and checks; dashed: left out. Click one to go to it in the text."
    : "Outlines of what the reader found come with the new reader: see Reading.");
  el.append(h("h2", { id: "dv-page-h", class: "dv-panel-title" }, "The page"), nav, frame, note);
  function draw() {
    const last = d.n_pages || 1;
    replace(nav, button({ sm: true, disabled: page <= 1, "aria-label": "Previous page", onClick: () => go(page - 1, true) }, icon("chevron-left", { size: 13 })),
      h("span", { class: "small" }, `Page ${page} of ${last}`),
      button({ sm: true, disabled: page >= last, "aria-label": "Next page", onClick: () => go(page + 1, true) }, icon("chevron-right", { size: 13 })),
      link({ kind: "external", href: `${docBase}/file?token=${encodeURIComponent(TOKEN)}#page=${page}` }, "Open the PDF at this page"));
  }
  function drawBoxes() {
    clear(boxes);
    const w = img.naturalWidth, hh = img.naturalHeight;
    if (!w || !hh) return;
    for (const b of loaded) {
      if (b.page !== page || !b.box) continue;
      const [x0, y0, x1, y1] = b.box;
      boxes.appendChild(h("button", { class: `dv-pbox dv-pbox-${b.included === false ? "out" : "in"}`, type: "button", tabindex: "-1", title: `${cap(b.kind_text || b.kind || "")}${b.included === false ? " (left out)" : ""}`,
        style: { left: `${(x0 * SCALE / w) * 100}%`, top: `${(y0 * SCALE / hh) * 100}%`, width: `${((x1 - x0) * SCALE / w) * 100}%`, height: `${Math.max(0.6, ((y1 - y0) * SCALE / hh) * 100)}%` },
        onClick: () => { const r = rows.get(b.n); if (r && r.row.closest("details")) r.row.closest("details").open = true; jumpTo({ start: b.start, end: b.end }); } }));
    }
  }
  img.addEventListener("load", drawBoxes);
  img.addEventListener("error", () => replace(frame, h("p", { class: "muted small" }, "The page could not be drawn.")));
  let following = true;  // off while a scroll this panel started is under way (the rows passing by are not "here")
  async function go(p, scroll) {
    p = Math.max(1, Math.min(d.n_pages || 1, p));
    if (p === page) return;
    page = p;
    if (scroll) { following = false; setTimeout(() => { following = true; }, 1200); }
    draw();
    img.alt = `Page ${page} of the original PDF`;
    img.src = `${docBase}/pages/${page}.png?scale=${SCALE}&token=${encodeURIComponent(TOKEN)}`;
    if (scroll && reading) {
      while (loaded.length < totalBlocks && (loaded[loaded.length - 1].page || 0) < page) { if (!(await loadMore())) break; }
      paint();
      const mark = document.getElementById(`page-${page}`);
      if (mark) mark.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }
  // follow the text: the page of the paragraph at the top of the view
  const seen = new IntersectionObserver((entries) => {
    if (ctx.tab !== "page" || !following) return;
    const vis = entries.filter((e) => e.isIntersecting).map((e) => rows.get(Number(e.target.id.slice(6)))).filter(Boolean);
    const first = vis.map((r) => r.b).filter((b) => b.page).sort((a, z) => a.start - z.start)[0];
    if (first) go(first.page, false);
  }, { rootMargin: "0px 0px -60% 0px" });
  // the rows there now, and (through rowWatchers) every row "Show the rest" or a jump adds later
  for (const r of rows.values()) seen.observe(r.row);
  rowWatchers.add(seen);
  cleanups.push(() => { rowWatchers.delete(seen); seen.disconnect(); });
  go((hit >= 0 && blocks[hit].page) || (loaded[0] && loaded[0].page) || 1, false);
  // 0.16: Restore and Leave out change the outlines (solid or dashed); 0.18.1: a figure's "Open the page"
  return { el, live: drawBoxes, goTo: (p) => go(p, false) };
}

