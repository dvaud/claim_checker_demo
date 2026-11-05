// 0.13: the Bibliography: a Zotero library or collection (read from the Zotero app on this computer), or a file
// exported from a reference manager, next to the project's documents. Four lists: works linked to their document,
// probable pairs to confirm, works still to find (with Zotero's files to add in one go), documents not in the
// bibliography.
import { featureEyebrow } from "../features.js";
import { App, api, h, icon, replace, clear, toast, showError, fmt, pageHead, watchJob, P, confirmDialog, emptyState, TERMINAL,
  dialog, session, download, plural, spinner } from "../lib.js";
import { simpleProgress, jobError } from "./progress.js";
import { accessChoice } from "./ai-access.js";

const TABS = [
  ["confirm", "Please confirm", "help"],
  ["to_find", "To find", "search"],
  ["linked", "Linked", "link"],
  ["not_in", "Not in the bibliography", "file-text"],
];
const HOW = { file: "Same file", doi: "Same DOI", title: "You confirmed it", person: "You linked it" };
const PAGE_ROWS = 150;

export async function renderBibliography(view) {
  const project = App.project;
  const base = `/api/projects/${P(project)}`;
  view.appendChild(pageHead("Bibliography", {
    eyebrow: featureEyebrow("bibliography"),
    sub: "Your Zotero library next to this project’s documents: which works you have and which you still need to find.",
  }));
  const watchers = [];
  const top = h("div", { class: "bib-top" });
  const jobBox = h("div", { class: "section", hidden: true, "aria-live": "polite" });
  const body = h("div", { class: "bib-body" });
  view.append(top, jobBox, body);
  let data = null;
  let tab = session(`bib-tab:${project}`) || null;
  let picking = false;   // the source card is open over an existing bibliography ("Use another collection or file")

  async function load() {
    try { data = await api("GET", `${base}/bibliography`); } catch (e) { showError(e); return; }
    draw();
  }

  function draw() {
    clear(top); clear(body);
    const bib = data && data.bibliography;
    if (!bib) { top.appendChild(sourceCard(false)); return; }
    top.appendChild(summaryCard(bib, data.counts));
    if (picking) top.appendChild(sourceCard(true));
    drawLists();
  }

  // ----------------------------------------------------------------- where the bibliography comes from
  function sourceLine(bib) {
    if (bib.kind === "zotero") {
      const where = [bib.library_name || "My Library", bib.collection_name].filter(Boolean).join(" › ");
      return [h("strong", {}, "From Zotero: "), where, bib.collection && bib.subcollections ? h("span", { class: "muted" }, " (with its subcollections)") : null];
    }
    return [h("strong", {}, "From the file "), bib.name, bib.format_text ? h("span", { class: "muted" }, ` (${bib.format_text})`) : null];
  }

  function summaryCard(bib, c) {
    const update = bib.kind === "zotero"
      ? h("button", { class: "btn btn-primary btn-sm", type: "button", onClick: () => start({ update: true }, "Updating from Zotero") }, icon("refresh", { size: 13 }), "Update from Zotero")
      : null;
    const change = h("button", { class: "btn btn-sm", type: "button", "aria-expanded": picking ? "true" : "false", onClick: () => { picking = !picking; draw(); if (picking) top.lastChild.scrollIntoView({ block: "nearest" }); } },
      icon(picking ? "x" : "folder-open", { size: 13 }), picking ? "Close" : bib.kind === "zotero" ? "Use another collection or file" : "Use a newer file or Zotero");
    return h("section", { class: "card bib-summary", "aria-label": "Your bibliography" },
      h("div", { class: "bib-source" }, h("span", { class: "bib-source-icon" }, icon("library", { size: 20 })),
        h("div", { class: "grow" }, h("p", { class: "bib-source-line" }, sourceLine(bib)),
          h("p", { class: "muted small" }, `${plural(c.works, "work", "works")} · brought in on ${fmt.dateShort(bib.pulled_at)}`)),
        h("div", { class: "btn-row" }, update, change)),
      h("div", { class: "bib-tiles", role: "tablist", "aria-label": "Lists" }, TABS.map(([k, label, ic]) => {
        const n = c[k] || 0;
        const on = k === currentTab();
        return h("button", { class: `bib-tile bib-tile-${k}` + (on ? " on" : ""), type: "button", role: "tab", "aria-selected": on ? "true" : "false", "aria-controls": "bib-list",
          onClick: () => { tab = k; session(`bib-tab:${project}`, k); draw(); } },
          h("span", { class: "bib-tile-n" }, fmt.num(n)), h("span", { class: "bib-tile-label" }, icon(ic, { size: 13 }), label));
      })));
  }

  function currentTab() {
    const c = (data && data.counts) || {};
    if (tab && TABS.some(([k]) => k === tab)) return tab;
    return c.confirm ? "confirm" : c.to_find ? "to_find" : "linked";
  }

  function sourceCard(replacing) {
    const card = h("section", { class: "card bib-pick", "aria-label": "Bring in a bibliography" },
      h("div", { class: "card-head" }, h("h2", {}, replacing ? "Use another collection or file" : "Bring in your bibliography")),
      h("p", { class: "muted", style: { margin: "0 0 12px" } }, replacing
        ? "It replaces the bibliography above. Your confirmations are kept for every work that is in the new one too."
        : "Pick a Zotero collection, or your whole library. ENLENS links each work to the document you already have, lists the works you still need to find, and the documents Zotero does not have."));
    const zbox = h("div", { class: "bib-zotero", "aria-live": "polite" }, h("p", { class: "it muted" }, spinner("Looking for Zotero"), "Looking for Zotero on this computer…"));
    const fileFold = h("details", { class: "fold bib-file" }, h("summary", {}, "Use an exported file instead"), fileForm());
    card.append(zbox, fileFold, h("p", { class: "muted small bib-privacy" }, icon("shield", { size: 12 }), " Read on this computer: nothing goes over the internet, and your Zotero is not changed."));
    zoteroForm(zbox, fileFold);
    return card;
  }

  async function zoteroForm(box, fileFold) {
    let st;
    try { st = await api("GET", "/api/zotero"); } catch (e) { replace(box, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, e.message))); return; }
    const again = () => h("button", { class: "btn btn-sm", type: "button", onClick: () => { replace(box, h("p", { class: "it muted" }, spinner("Looking for Zotero"), "Looking again…")); zoteroForm(box, fileFold); } }, icon("refresh", { size: 13 }), "Look again");
    if (st.state !== "ready") {
      fileFold.open = true;
      const text = {
        not_running: [h("strong", {}, "Zotero is not open on this computer. "), "Open the Zotero app (version 7 or later), then look again. Or use a file exported from Zotero (below)."],
        api_off: [h("strong", {}, "Zotero is open, but does not let ENLENS read it yet. "), "In Zotero, open ", h("em", {}, "Settings → Advanced"), " and tick ", h("em", {}, "Allow other applications on this computer to communicate with Zotero"), ". Then look again."],
        too_old: [h("strong", {}, "This Zotero cannot be read directly. "), "Zotero 7 or later can: update Zotero, or use a file exported from it (below)."],
        failed: [h("strong", {}, "Zotero answered, but not as expected. "), "Try again, or use a file exported from it (below)."],
      }[st.state] || [st.detail || "Zotero could not be read."];
      replace(box, h("div", { class: `notice ${st.state === "api_off" ? "notice-warn" : "notice-info"}` }, icon(st.state === "api_off" ? "key" : "info"),
        h("div", {}, h("p", {}, text), st.state === "failed" && st.detail ? h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, st.detail)) : null,
          h("div", { style: { marginTop: "8px" } }, again()))));
      return;
    }
    const libs = st.libraries || [{ id: "user", name: "My Library" }];
    const curLib = data && data.bibliography && data.bibliography.kind === "zotero" ? data.bibliography.library : null;
    const libSel = h("select", { class: "select", id: "bib-library" }, libs.map((l) => h("option", { value: l.id, selected: l.id === curLib }, l.name)));
    const colSel = h("select", { class: "select", id: "bib-collection" }, h("option", { value: "" }, "Loading the collections…"));
    const subs = h("input", { type: "checkbox", id: "bib-subs", checked: true });
    const subsRow = h("label", { class: "bib-subs", for: "bib-subs", hidden: true }, subs, h("span", {}, "Include its subcollections"));
    const go = h("button", { class: "btn btn-primary", type: "button", disabled: true }, icon("download", { size: 14 }), "Bring in the bibliography");
    let cols = [];
    const drawSubs = () => {
      const k = colSel.value;
      subsRow.hidden = !k || !cols.some((c) => c.parent === k);
    };
    async function loadCols() {
      go.disabled = true;
      replace(colSel, h("option", { value: "" }, "Loading the collections…"));
      try { cols = (await api("GET", `/api/zotero/collections?library=${encodeURIComponent(libSel.value)}`)).collections || []; }
      catch (e) { showError(e); cols = []; }
      replace(colSel, h("option", { value: "" }, "The whole library"), cols.map((c) => h("option", { value: c.key }, `${" ".repeat(c.depth)}${c.name}${c.items ? ` (${c.items})` : ""}`)));
      // the collection in use when it is replaced; else the one chosen last time on this page
      const cur = data && data.bibliography && data.bibliography.kind === "zotero" && data.bibliography.library === libSel.value ? data.bibliography.collection : null;
      const keep = cur || session(`bib-col:${project}`);
      if (keep && cols.some((c) => c.key === keep)) colSel.value = keep;
      go.disabled = false;
      drawSubs();
    }
    libSel.addEventListener("change", loadCols);
    colSel.addEventListener("change", () => { session(`bib-col:${project}`, colSel.value); drawSubs(); });
    go.addEventListener("click", () => {
      go.disabled = true;
      const opt = colSel.selectedOptions[0];
      start({ zotero: { library: libSel.value, collection: colSel.value || null, subcollections: subs.checked } },
        colSel.value ? `Reading “${(opt && opt.textContent || "").trim().replace(/\s*\(\d+\)$/, "")}” from Zotero` : "Reading your Zotero library");
    });
    replace(box, h("div", { class: "bib-form" },
      h("p", { class: "it bib-found" }, icon("circle-check", { size: 14 }), "Zotero is open on this computer."),
      h("div", { class: "bib-fields" },
        libs.length > 1 ? h("div", { class: "field" }, h("label", { class: "field-label", for: "bib-library" }, "Library"), libSel) : null,
        h("div", { class: "field grow" }, h("label", { class: "field-label", for: "bib-collection" }, "Collection"), colSel)),
      subsRow,
      h("div", { class: "btn-row", style: { marginTop: "12px" } }, go)));
    loadCols();
  }

  function fileForm() {
    const input = h("input", { type: "file", accept: ".bib,.bibtex,.biblatex,.ris,.json,.csv,.txt", class: "visually-hidden", id: "bib-file" });
    input.addEventListener("change", async () => {
      const f = input.files && input.files[0];
      input.value = "";
      if (!f) return;
      if (f.size > 18 * 1024 * 1024) { toast("This file is too large (over 18 MB). Export one collection at a time.", "warn"); return; }
      let text;
      try { text = await f.text(); } catch (e) { showError(e); return; }
      start({ file: { name: f.name, text } }, `Reading ${f.name}`);
    });
    return h("div", { class: "card card-plain", style: { marginTop: "8px" } },
      h("p", { style: { marginTop: 0 } }, "In Zotero, right-click a collection, choose ", h("em", {}, "Export Collection…"), " and pick ", h("strong", {}, "BibTeX"), ", ", h("strong", {}, "RIS"), ", ", h("strong", {}, "CSL JSON"), " or ", h("strong", {}, "CSV"), ". Mendeley, EndNote and other reference managers export BibTeX or RIS too."),
      h("p", { class: "muted small" }, "With CSV and BibTeX, the files Zotero keeps for each work come along, so they can be added in one go."),
      h("label", { for: "bib-file", class: "btn", tabindex: "0", onKeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } } }, icon("upload", { size: 14 }), "Choose the exported file"), input);
  }

  async function start(bodyIn, label) {
    let r;
    try { r = await api("POST", `${base}/bibliography`, bodyIn); } catch (e) { showError(e); draw(); return; }
    follow(r.job.id, label);
  }

  function follow(jobId, label) {
    jobBox.hidden = false;
    const head = h("h2", {}, label || "Bringing in the bibliography");
    const stop = h("button", { class: "btn btn-sm btn-outline-danger", type: "button", onClick: () => api("POST", `/api/jobs/${P(jobId)}/cancel`).catch(showError) }, icon("stop", { size: 13 }), "Stop");
    const pb = h("div", {});
    replace(jobBox, h("div", { class: "card" }, h("div", { class: "card-head" }, head, stop), pb));
    const w = watchJob(jobId, (job) => {
      replace(pb, simpleProgress(job, (p) => p.phase === "files" ? `Finding the files Zotero keeps: ${p.done} of ${p.total}`
        : p.phase === "attachments" ? `Reading the attachments: ${p.done} of ${p.total} works`
          : p.phase === "checksums" ? `Comparing the files with your documents: ${p.done} of ${p.total}`
            : p.phase === "matching" ? "Matching the works with your documents…"
              : p.done ? `${fmt.num(p.done)} works read` : "Reading…"));
      if (TERMINAL.has(job.state)) stop.hidden = true;
    });
    watchers.push(w);
    w.promise.then(async (job) => {
      if (job.state === "done") {
        jobBox.hidden = true;
        picking = false;
        const c = job.result || {};
        toast(`${plural(c.works || 0, "work", "works")} in the bibliography: ${c.linked || 0} linked to a document${c.confirm ? `, ${c.confirm} to confirm` : ""}.`, "ok", { ttl: 6000 });
        tab = null;
        await load();
        App.refresh().catch(() => {});
      } else if (job.state === "error") { head.textContent = "It did not work"; replace(pb, jobError(job)); draw(); }
      else { head.textContent = "Stopped"; replace(pb, h("p", { class: "muted", style: { margin: 0 } }, "Stopped. The bibliography was not changed.")); draw(); }
    }).catch(showError);
  }

  // ----------------------------------------------------------------- the four lists
  function drawLists() {
    const k = currentTab();
    const box = h("section", { class: "bib-list", id: "bib-list", role: "tabpanel", "aria-label": TABS.find((t) => t[0] === k)[1] });
    body.appendChild(box);
    ({ confirm: drawConfirm, to_find: drawToFind, linked: drawLinked, not_in: drawNotIn })[k](box);
    body.appendChild(h("details", { class: "fold section bib-remove" }, h("summary", {}, "Remove the bibliography"),
      h("div", { class: "card card-plain danger-zone", style: { marginTop: "8px" } },
        h("div", { class: "row", style: { justifyContent: "space-between" } },
          h("p", { class: "grow", style: { margin: 0 } }, "Takes the works and their links out of this project. Your documents and Zotero stay as they are."),
          h("button", { class: "btn btn-outline-danger btn-sm", type: "button", onClick: async () => {
            if (!(await confirmDialog({ title: "Remove the bibliography?", message: "The works and your confirmations are taken out of this project. Your documents and your Zotero library are not touched.", confirmText: "Remove" }))) return;
            try { data = await api("DELETE", `${base}/bibliography`, {}); toast("The bibliography was removed.", "ok"); draw(); } catch (e) { showError(e); }
          } }, icon("trash", { size: 13 }), "Remove")))));
  }

  const workCell = (w, opts = {}) => h("div", { class: "bib-work" },
    h("div", { class: "bib-title" }, w.title),
    h("div", { class: "bib-meta" }, [w.cite || null, w.type || null, w.container || null].filter(Boolean).map((x, i) => [i ? h("span", { class: "sep" }, "·") : null, h("span", {}, x)]),
      opts.links === false ? null : findLinks(w)));
  const findLinks = (w) => [
    w.doi ? [h("span", { class: "sep" }, "·"), h("a", { href: `https://doi.org/${w.doi}`, target: "_blank", rel: "noopener noreferrer", class: "it", title: `Open doi.org/${w.doi} in your browser` }, "DOI", icon("external-link", { size: 11 }))] : null,
    w.url && !w.doi ? [h("span", { class: "sep" }, "·"), h("a", { href: w.url, target: "_blank", rel: "noopener noreferrer", class: "it", title: w.url }, "Web page", icon("external-link", { size: 11 }))] : null,
    w.link ? [h("span", { class: "sep" }, "·"), h("a", { href: w.link, class: "it", title: "Shows this work in Zotero" }, "Open in Zotero")] : null];
  // 0.13.3: a linked document is called by its work's title; the title read from the file is under its file name
  const docCell = (d) => h("div", { class: "bib-doc" }, h("a", { href: `#/doc/${encodeURIComponent(d.doc_id)}`, class: "bib-doc-title" }, d.title || d.file), h("div", { class: "doc-file" }, d.file),
    d.file_title ? h("div", { class: "muted small bib-own-title" }, "Title in the file: ", d.file_title) : null);

  async function decide(item_key, doc_id, decision, msg, undo) {
    try {
      data = await api("PUT", `${base}/bibliography/links`, { item_key, doc_id, decision });
      draw();
      toast(msg, "ok", { ttl: 5000, group: "bib", button: undo ? { text: "Undo", onClick: () => decide(item_key, doc_id, undo, "Undone.") } : undefined });
    } catch (e) { showError(e); }
  }

  function drawConfirm(box) {
    const rows = data.confirm || [];
    if (!rows.length) { box.appendChild(emptyState("circle-check", "Nothing to confirm", "When a work’s title, and an author or the year, are found on the first pages of a document, the pair waits here for you.")); return; }
    box.appendChild(h("div", { class: "bib-list-head" },
      h("p", { class: "grow" }, `ENLENS found ${rows.length === 1 ? "this work’s title" : "these works’ titles"} on the first pages of a document. Is it the same work?`),
      rows.length > 1 ? h("button", { class: "btn btn-sm", type: "button", onClick: async () => {
        if (!(await confirmDialog({ title: `Confirm all ${rows.length} pairs?`, message: "Each work is linked to the document shown next to it. You can unlink any of them later, under Linked.", confirmText: "Confirm all", danger: false }))) return;
        try { data = await api("POST", `${base}/bibliography/confirm-all`, {}); toast(`${plural(data.confirmed || 0, "pair", "pairs")} confirmed.`, "ok"); tab = "linked"; draw(); } catch (e) { showError(e); }
      } }, icon("check", { size: 13 }), `Confirm all ${rows.length}`) : null));
    for (const r of rows) {
      const ev = r.evidence || {};
      const ex = ev.excerpt ? h("blockquote", { class: "bib-excerpt" },
        ev.end > ev.start ? [ev.excerpt.slice(0, ev.start), h("mark", {}, ev.excerpt.slice(ev.start, ev.end)), ev.excerpt.slice(ev.end)] : ev.excerpt) : null;
      const found = [
        ev.title === "whole" ? "the whole title" : ev.title === "main" ? "the title without its subtitle" : "nearly all the words of the title",
        ev.author ? `the author ${titleCase(ev.author)}` : null,
        ev.year ? `the year ${ev.year}` : null].filter(Boolean);
      box.appendChild(h("article", { class: "card bib-pair" },
        h("div", { class: "bib-pair-cols" },
          h("div", {}, h("p", { class: "bib-label" }, icon("library", { size: 12 }), "In your bibliography"), workCell(r.work)),
          h("div", {}, h("p", { class: "bib-label" }, icon("file-text", { size: 12 }), "Document in this project"), docCell(r.doc))),
        h("p", { class: "bib-why small" }, `Found ${ev.page ? `on page ${ev.page}` : "at the start"}: ${found.join(", ")}.`),
        ex,
        h("div", { class: "btn-row" },
          h("button", { class: "btn btn-primary btn-sm", type: "button", onClick: () => decide(r.work.key, r.doc.doc_id, "same", "Linked.", "clear") }, icon("check", { size: 13 }), "Same work"),
          h("button", { class: "btn btn-ghost btn-sm", type: "button", onClick: () => decide(r.work.key, r.doc.doc_id, "different", "Not proposed again.", "clear") }, icon("x", { size: 13 }), "Not the same"))));
    }
  }

  function filterBox(placeholder, onInput) {
    const inp = h("input", { class: "input input-sm bib-filter", type: "search", placeholder, "aria-label": placeholder });
    inp.addEventListener("input", () => onInput(inp.value.trim().toLowerCase()));
    return inp;
  }

  function drawToFind(box) {
    const rows = data.to_find || [];
    const c = data.counts || {};
    if (!rows.length) { box.appendChild(emptyState("circle-check", "Every work has its document", "All the works of the bibliography are linked to a document of this project, or wait for you to confirm one.")); return; }
    if (c.files) box.appendChild(filesCard(c.files));
    const tbody = h("tbody", {});
    const more = h("div", { class: "bib-more" });
    let shown = PAGE_ROWS, filter = "";
    const list = () => rows.filter((w) => !filter || `${w.title} ${w.authors} ${w.year || ""} ${w.container || ""}`.toLowerCase().includes(filter));
    const drawRows = () => {
      const all = list();
      replace(tbody, all.slice(0, shown).map((w) => h("tr", {},
        h("td", {}, workCell(w)),
        h("td", { "data-label": "Year", class: "num nowrap" }, w.year || "—"),
        h("td", { "data-label": fileHead(), class: "small" + (w.file ? "" : " bib-nofile") }, w.file ? h("span", { class: "it bib-has-file", title: w.file }, icon("file-text", { size: 12 }), "Has a file") : h("span", { class: "muted" }, "—")),
        h("td", { class: "actions" }, h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "The document is in the project already: say which one", onClick: () => linkDialog(w) }, icon("link", { size: 13 }), "Link a document")))));
      replace(more, all.length > shown ? h("button", { class: "btn btn-sm", type: "button", onClick: () => { shown = all.length; drawRows(); } }, `Show all ${fmt.num(all.length)}`) : null,
        filter ? h("span", { class: "muted small" }, `${plural(all.length, "work", "works")} match`) : null);
    };
    box.appendChild(h("div", { class: "bib-list-head" },
      h("p", { class: "grow" }, `${plural(rows.length, "work has", "works have")} no document in this project yet.`),
      filterBox("Filter by title, author or year", (v) => { filter = v; shown = PAGE_ROWS; drawRows(); }),
      h("button", { class: "btn btn-sm", type: "button", title: "The list as a spreadsheet: title, authors, year, DOI, web address and Zotero link", onClick: () => download(`${base}/bibliography/to-find.xlsx`).catch(showError) }, icon("download", { size: 13 }), "Download the list")));
    box.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "table table-responsive bib-table" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Work"), h("th", { scope: "col", class: "num" }, "Year"), h("th", { scope: "col" }, fileHead()), h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, "Actions")))),
      tbody)));
    box.appendChild(more);
    drawRows();
  }

  // where the files of the works are: Zotero's own, or the paths an exported file names on this computer
  const fromZotero = () => !!(data && data.bibliography && data.bibliography.kind === "zotero");
  const fileHead = () => (fromZotero() ? "File in Zotero" : "File on this computer");

  // Zotero's files for works without a document: added where they are, after the person says who may read them
  function filesCard(n) {
    const acc = data.ai_access || {};
    let level = acc.chosen ? acc.default : null;
    const btn = h("button", { class: "btn btn-primary btn-sm", type: "button", disabled: !level }, icon("upload", { size: 13 }), `Add ${n === 1 ? "this file" : `these ${n} files`} to the project`);
    const pick = accessChoice({ value: level, name: "bib-access", onChange: (v) => { level = v; btn.disabled = false; } });
    const pb = h("div", { "aria-live": "polite" });
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      let r;
      try { r = await api("POST", `${base}/bibliography/files`, { ai_access: level }); } catch (e) { showError(e); btn.disabled = false; return; }
      const w = watchJob(r.job.id, (job) => replace(pb, simpleProgress(job, (p) => p.phase === "embedding" ? "Setting up search by meaning for them…" : p.phase === "glossary" ? "Updating the glossary of terms…" : p.phase === "codes" ? "Finding the codebook’s codes by keywords…" : p.file ? `Reading ${p.file} (${(p.done || 0) + 1} of ${p.total})` : "Reading the files…")));
      watchers.push(w);
      const job = await w.promise;
      if (job.state === "done") {
        const st = job.result || {};
        const b = st.bibliography || {};
        toast(`${plural(st.added || 0, "document", "documents")} added${b.linked ? `, ${b.linked} linked to ${b.linked === 1 ? "its work" : "their works"}` : ""}.`, "ok", { ttl: 6000 });
        await load();
        App.refresh().catch(() => {});
      } else if (job.state === "error") { replace(pb, jobError(job)); btn.disabled = false; }
      else { replace(pb, h("p", { class: "muted small" }, "Stopped. The files read so far were added.")); await load(); }
    });
    return h("section", { class: "card bib-files", "aria-label": "Files Zotero has" },
      h("div", { class: "bib-files-head" }, h("span", { class: "bib-source-icon" }, icon("file-text", { size: 18 })),
        h("div", { class: "grow" }, h("h3", {}, fromZotero() ? `Zotero has a file for ${n === 1 ? "1 of these works" : `${n} of these works`}`
          : `Your exported file names a file on this computer for ${n === 1 ? "1 of these works" : `${n} of these works`}`),
          h("p", { class: "muted small", style: { margin: "2px 0 0" } }, n === 1 ? `Add it: it is read where ${fromZotero() ? "Zotero keeps it" : "it is"}, nothing is copied, and it is linked to its work.`
            : `Add them in one go: they are read where ${fromZotero() ? "Zotero keeps them" : "they are"}, nothing is copied, and each is linked to its work.`))),
      acc.chosen ? h("p", { class: "small", style: { margin: "10px 0" } }, "Who may read them with AI: ", h("strong", {}, ({ cloud: "Claude may read them", local: "only a local AI", none: "no AI" })[acc.default] || acc.default), h("span", { class: "muted" }, " (this project’s choice). "),
        h("button", { class: "link-btn small", type: "button", onClick: (e) => { e.currentTarget.parentNode.replaceWith(pick); } }, "Change for these")) : pick,
      h("div", { class: "btn-row", style: { marginTop: "10px" } }, btn), pb);
  }

  function drawLinked(box) {
    const rows = data.linked || [];
    if (!rows.length) { box.appendChild(emptyState("link", "Nothing linked yet", "A work is linked to its document when they are the same file or have the same DOI, or when you confirm a pair.")); return; }
    const tbody = h("tbody", {});
    let filter = "";
    const drawRows = () => replace(tbody, rows.filter((r) => !filter || `${r.work.title} ${r.work.authors} ${r.doc.title} ${r.doc.file} ${r.doc.file_title || ""}`.toLowerCase().includes(filter)).map((r) => h("tr", {},
      h("td", {}, workCell(r.work)),
      h("td", { "data-label": "Document" }, docCell(r.doc)),
      h("td", { "data-label": "How", class: "small nowrap" }, r.status === "confirmed" ? (r.method === "person" ? HOW.person : HOW.title) : HOW[r.method] || r.method),
      h("td", { class: "actions" }, h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": `Unlink ${r.work.title} from ${r.doc.title || r.doc.file}`, onClick: () => decide(r.work.key, r.doc.doc_id, "different", "Unlinked.", "same") }, icon("x", { size: 13 }), "Unlink")))));
    box.appendChild(h("div", { class: "bib-list-head" },
      h("p", { class: "grow" }, `${plural(rows.length, "work is", "works are")} linked to ${rows.length === 1 ? "its document" : "their documents"}. Each document shows its reference in the list of documents.`),
      rows.length > 8 ? filterBox("Filter", (v) => { filter = v; drawRows(); }) : null));
    box.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "table table-responsive bib-table" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Work"), h("th", { scope: "col" }, "Document"), h("th", { scope: "col" }, "How"), h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, "Actions")))),
      tbody)));
    drawRows();
  }

  function drawNotIn(box) {
    const rows = data.not_in || [];
    if (!rows.length) { box.appendChild(emptyState("circle-check", "Every document is in the bibliography", "Each document of this project is linked to a work, or waits for you to confirm one.")); return; }
    box.appendChild(h("div", { class: "bib-list-head" }, h("p", { class: "grow" },
      `${plural(rows.length, "document has", "documents have")} no work in the bibliography. If you cite ${rows.length === 1 ? "it" : "them"}, add ${rows.length === 1 ? "it" : "them"} to Zotero${data.bibliography.kind === "zotero" ? " and press Update from Zotero" : ""}; or link ${rows.length === 1 ? "it" : "one"} to a work by hand.`)));
    box.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "table table-responsive bib-table" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Document"), h("th", { scope: "col" }, "Added"), h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, "Actions")))),
      h("tbody", {}, rows.map((d) => h("tr", {},
        h("td", {}, docCell(d)),
        h("td", { "data-label": "Added", class: "small muted nowrap" }, fmt.dateShort(d.added_at || "")),
        h("td", { class: "actions" }, h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => linkDialog(null, d) }, icon("link", { size: 13 }), "Link to a work"))))))));
  }

  // Link a work and a document by hand: pick the other side from a list that can be filtered
  async function linkDialog(work, doc) {
    const options = work ? (data.not_in || []).map((d) => ({ id: d.doc_id, title: d.title || d.file, sub: d.file }))
      : (data.to_find || []).map((w) => ({ id: w.key, title: w.title, sub: [w.cite, w.type].filter(Boolean).join(" · ") }));
    if (!options.length) { toast(work ? "Every document is linked to a work already: unlink one under Linked first." : "Every work has a document already.", "info"); return; }
    let chosen = null;
    const listBox = h("div", { class: "bib-pick-list", role: "radiogroup", "aria-label": work ? "Documents" : "Works" });
    const drawOpts = (f) => replace(listBox, options.filter((o) => !f || `${o.title} ${o.sub}`.toLowerCase().includes(f)).slice(0, 200).map((o) => {
      const r = h("input", { type: "radio", name: "bib-pick", value: o.id, checked: chosen === o.id });
      r.addEventListener("change", () => { chosen = o.id; });
      return h("label", { class: "bib-pick-opt" }, r, h("span", {}, h("span", { class: "bib-pick-title" }, o.title), o.sub ? h("span", { class: "muted small" }, o.sub) : null));
    }));
    const filt = h("input", { class: "input input-sm", type: "search", placeholder: "Filter", "aria-label": "Filter" });
    filt.addEventListener("input", () => drawOpts(filt.value.trim().toLowerCase()));
    drawOpts("");
    const ok = await dialog({
      title: work ? "Which document is this work?" : "Which work is this document?",
      wide: true,
      body: h("div", { class: "stack" }, h("p", { style: { margin: 0 } }, h("strong", {}, work ? work.title : doc.title || doc.file)), filt, listBox),
      actions: [{ text: "Cancel", value: false }, { text: "Link", primary: true, value: true, onClick: () => { if (!chosen) { toast("Choose one first.", "warn", { ttl: 2500 }); return false; } return true; } }],
      onOpen: () => filt.focus(),
    });
    if (!ok || !chosen) return;
    await decide(work ? work.key : chosen, work ? chosen : doc.doc_id, "same", "Linked.", "clear");
  }

  // a bibliography job already running for this project (started earlier, or in another tab)
  try {
    const jobs = (await api("GET", "/api/jobs")).jobs || [];
    const running = jobs.find((j) => j.project === project && j.kind === "bibliography" && !TERMINAL.has(j.state));
    if (running) follow(running.id, running.title);
  } catch (_) { /* ignore */ }
  await load();
  return () => watchers.forEach((w) => w.stop());
}

const titleCase = (s) => String(s || "").replace(/\b\p{L}/gu, (c) => c.toUpperCase());
