// Documents: a big add area first, the document table, smart search in plain words, and the rarely needed things (folder
// path, exclude patterns, remove everything) folded away. A document's own page (doc-page.js) is exported from here too.
import { featureEyebrow, viewTabs } from "../features.js";
import { tesseractHelp, App, api, h, icon, replace, clear, toast, showError, failedLoad, fmt, pageHead, watchJob, P,
  navigate, batchId, confirmDialog, field, emptyState, TERMINAL, KIND_TEXT, dialog, plural, lazyList, button,
  iconButton, fileButton, link, notice, card, tag, input, fold, choice, stopButton, store, searchField } from "../lib.js";
import { simpleProgress, jobCard } from "./progress.js";
import { forgetOriginals } from "./result.js";
import { LEVEL, accessChoice, accessAskCard, accessBanner, docAccessDialog, levels as accessLevels } from "./ai-access.js";
import { askWhy } from "./versions.js";
import { proposalChip, proposedToast, removalNote } from "./owner.js";   // 0.18 L2
import { docChip } from "./owner-state.js";   // 0.18.5: the owner's word as an icon on a closed line
import { documentRoles, roleTag, roleMenuItem } from "./doc-role.js";   // 0.18.1 K2: theory documents
import { reader, newReaderFor, readingNote, READER_4_NEWS, READER_5_NEWS } from "./doc-shared.js";

const ACCEPT = ".pdf,.docx,.html,.htm,.txt,.md,.zip";
const OK_EXT = ["pdf", "docx", "html", "htm", "txt", "md", "zip"];
const ocrState = () => (App.state && App.state.ocr) || {};

export async function renderSources(view) {
  const project = App.project;
  let info;
  try { info = await api("GET", `/api/projects/${P(project)}`); } catch (e) { showError(e); info = { search: null, passages: 0 }; }
  view.appendChild(pageHead("Documents", { eyebrow: featureEyebrow("sources"), sub: "The reports, papers and web pages you explore and check hypotheses against. Open one to read it." }));
  view.appendChild(viewTabs("documents", "sources"));   // 0.17.0: Documents | Notes | Bibliography

  const watchers = [];

  // ----------------------------------------------------------------- add documents
  const files = [];
  let sent = [];            // 0.14.3: the files of the run that is going; files picked meanwhile wait in `files` for the next
  let adding = false;       // 0.14.3: copying or reading is going: "Add" stays off, and picks are kept, not sent
  const fileInput = h("input", { type: "file", multiple: true, accept: ACCEPT, class: "visually-hidden", id: "src-files" });
  const fileList = h("ul", { class: "file-list", hidden: true });
  const addBtn = button({ kind: "main", disabled: true }, icon("upload", { size: 15 }), "Add to the project");
  const addWhy = h("span", { class: "muted small" });   // why the button is off, beside it (DESIGN 4.1)
  const excludeInput = input({ placeholder: "e.g. draft*  *_old.pdf", id: "exclude" });
  const drawFiles = () => {
    fileList.hidden = !files.length;
    replace(fileList, files.map((f, i) => h("li", {}, icon("file-text", { size: 13 }), h("span", { class: "grow docs-file-name" }, f.name), h("span", { class: "fs" }, fmt.bytes(f.size)),
      iconButton({ icon: "x", size: 12, label: `Remove ${f.name} from the list`, title: null, sm: true, onClick: () => { files.splice(i, 1); drawFiles(); } }))));
    addBtn.disabled = !files.length || needLevel() || adding;
    addWhy.textContent = adding ? "" : !files.length ? "Choose or drop files first." : needLevel() ? "Choose who may read them with AI first." : "";
    addBtn.title = addWhy.textContent;
    replace(addBtn, icon("upload", { size: 15 }), files.length ? `Add ${files.length === 1 ? "this document" : `these ${files.length} documents`} to the project` : "Add to the project");
  };
  const takeFiles = (list) => {
    const refused = [];
    for (const f of list) {
      const ext = (f.name.split(".").pop() || "").toLowerCase();
      if (!OK_EXT.includes(ext)) { refused.push(f.name); continue; }
      if (!files.some((x) => x.name === f.name && x.size === f.size)) files.push(f);
    }
    if (refused.length) {
      const docx = refused.some((n) => /\.(doc|rtf|odt|pptx?|xlsx?)$/i.test(n));
      toast(`${refused.length === 1 ? "This file cannot be read" : `${refused.length} files cannot be read`}: ${refused.slice(0, 3).join(", ")}${refused.length > 3 ? "…" : ""}. ${docx ? "Older Word (.doc) and other Office files are not supported yet: save them as .docx or PDF first." : "Only PDF, Word (.docx), text, Markdown, web pages (HTML) and zip files are."}`, "warn", { ttl: 9000 });
    }
    drawFiles();
  };
  fileInput.addEventListener("change", () => { takeFiles(fileInput.files || []); fileInput.value = ""; });
  const drop = h("div", { class: "dropzone", role: "group", "aria-label": "Add documents", title: "Click to choose files, or drop them here" },
    icon("upload", { size: 28 }),
    h("p", { class: "drop-title" }, h("strong", {}, "Drop your documents here")), h("p", { class: "drop-choose" }, fileButton({ kind: "standard", sm: false, for: "src-files", tabindex: "0", onKeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } } }, fileInput, "Choose files")),
    h("p", { class: "muted small" }, "PDF, Word (.docx), text, Markdown and saved web pages (HTML), or a zip folder of them. ",
      ocrState().available === false ? ["Scanned PDFs cannot be read on this computer yet: they need Tesseract (", h("a", { href: "#/settings/ocr" }, "how to get it"), ")."] : ocrState().available && (App.settings().ocr || "auto") === "off" ? "Reading scanned PDFs is switched off in Settings." : ocrState().available ? "Scanned PDFs are read with text recognition (OCR), which is slow and can make mistakes." : ""),
    fileList);
  for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.dataset.over = "true"; });
  for (const ev of ["dragleave", "drop"]) drop.addEventListener(ev, (e) => { e.preventDefault(); delete drop.dataset.over; });
  drop.addEventListener("drop", (e) => { if (e.dataTransfer && e.dataTransfer.files) takeFiles(e.dataTransfer.files); });
  // a click anywhere on the area (not on a chosen file's row or its remove button) opens the file chooser
  drop.addEventListener("click", (e) => { if (e.target.closest("a, label, button, input, .file-list")) return; fileInput.click(); });

  // 0.11: "Who may read these documents with AI?" One answer for everything added now; the project's default
  // preselected, nothing the first time (guessing wrong either way costs the person something).
  const acc = info.ai_access || {};
  let chosenLevel = acc.chosen ? acc.default : null;
  const needLevel = () => !chosenLevel;
  let ingesting = false;   // an ingest is being followed: the folder button stays off until it ends
  const accessPick = accessChoice({ value: chosenLevel, name: "add-access", onChange: (v) => { chosenLevel = v; drawFiles(); if (!ingesting) pathBtn.disabled = false; } });
  drawFiles();   // the add button's state and its reason, before any file is chosen
  const pathInput = input({ placeholder: "e.g. C:\\Users\\me\\Documents\\Literature  or  /Users/me/Documents/Literature", id: "src-path" });
  const pathBtn = button({}, icon("folder-open", { size: 14 }), "Add this folder");
  const progressBox = h("div", { class: "section", hidden: true, "aria-live": "polite" });

  const addCard = card({ "aria-label": "Add documents" },
    drop,
    h("div", { class: "add-access" }, accessPick, acc.chosen ? null : h("p", { class: "muted small docs-access-note" }, "Choose once for this project; it becomes the default, and you can change single documents in the list below.")),
    h("div", { class: "btn-row docs-add-actions" }, addBtn, addWhy),
    fold({ class: "docs-more-fold" }, "More ways to add",
      card({ as: "div", class: "docs-more-card" },
        h("div", { class: "field" }, h("label", { class: "field-label", for: "src-path" }, "Add a whole folder on this computer"), h("div", { class: "row docs-folder-row" }, pathInput, pathBtn),
          h("div", { class: "field-help" }, "Type or paste the full path of a folder (or of a zip file). The files are read where they are, nothing is copied.")),
        field("Leave out files whose name matches", excludeInput, { help: "Patterns separated by spaces; * stands for anything. Applies to everything you add." }),
        h("p", { class: "small docs-zotero-note" }, icon("library", { size: 13 }), " From Zotero: on the ", h("a", { href: "#/bibliography" }, "Bibliography"), " page, bring in a collection; the PDFs Zotero keeps are added in one go, and each document is linked to its work."),
        h("p", { class: "muted small docs-manifest-note" }, "For technical users: a zip may contain a manifest.csv (columns file, reference, doi) naming the work each file is; an ai_access column (cloud, local or none) and an ai_note column set each file's AI setting."))));
  // 0.18.5: once the project has documents, adding more is one line that opens (the list was half a screen down)
  const addFold = fold({ class: "docs-add-fold", open: true }, h("span", { class: "it" }, icon("upload", { size: 15 }), "Add documents"), addCard);
  let addFoldSet = false;
  view.appendChild(addFold);
  view.appendChild(progressBox);

  async function runIngest(body, label) {
    try {
      const r = await api("POST", `/api/projects/${P(project)}/ingest`, body);
      followIngest(r.job.id, label);
    } catch (e) { showError(e); adding = false; sent = []; drawFiles(); pathBtn.disabled = false; }
  }

  function followIngest(jobId, label) {
    ingesting = true;
    progressBox.hidden = false;
    const stop = stopButton({ onClick: () => api("POST", `/api/jobs/${P(jobId)}/cancel`).catch(showError) });
    const head = h("span", {}, label || "Adding documents");
    const holder = card({ as: "div", title: head, action: stop }, h("div", { class: "pb" }));
    replace(progressBox, holder);
    const w = watchJob(jobId, (job) => {
      replace(holder.querySelector(".pb"), simpleProgress(job, (p) => p.phase === "embedding" ? `Setting up search by meaning for the new documents · ${p.done || 0} of ${p.total || "?"} excerpts` : p.phase === "glossary" ? "Updating the glossary of terms (Concepts)…" : p.phase === "codes" ? "Finding the codebook's codes by keywords (Profile)…" : p.file ? `Reading ${p.file} (${(p.done || 0) + 1} of ${p.total})` : p.total ? `${p.done} of ${p.total} files` : "Reading the files…"));
      if (TERMINAL.has(job.state)) stop.hidden = true;
    });
    watchers.push(w);
    w.promise.then(async (job) => {
      head.textContent = job.state === "done" ? "Documents added" : job.state === "cancelled" ? "Stopped" : "Could not add the documents";
      if (job.state === "done") ingestSummary(holder, job.result || {});
      else if (job.state === "error") replace(holder.querySelector(".pb"), notice({ kind: "error" }, h("div", {}, h("p", {}, "The documents could not be added."), fold({}, "Technical details", h("div", { class: "mono small" }, job.error || "")), job.error_kind === "backend" ? h("a", { href: "#/settings" }, "Check the AI model in Settings") : null)));
      else replace(holder.querySelector(".pb"), h("p", { class: "muted" }, "Stopped. The files read so far were kept."));
      ingesting = false;
      // only the files that were sent leave the list; what was picked during the run stays for the next one
      for (const f of sent) { const i = files.indexOf(f); if (i >= 0) files.splice(i, 1); }
      const waiting = files.length;
      sent = []; adding = false; drawFiles(); pathBtn.disabled = false;
      if (waiting) toast(`${waiting === 1 ? "1 file you picked" : `${waiting} files you picked`} while the documents were being added ${waiting === 1 ? "is" : "are"} still in the list: press Add to add ${waiting === 1 ? "it" : "them"}.`, "info", { ttl: 7000 });
      forgetOriginals();
      await reloadDocs();
      await App.refresh();
    }).catch(showError);
  }

  function ingestSummary(holder, st) {
    const bits = [];
    const added = st.added || 0;
    bits.push(notice({ kind: added ? "done" : "attention" },
      h("div", {}, h("p", {}, added ? `${added} ${added === 1 ? "document" : "documents"} added.` : "No new document was added.", st.duplicates ? ` ${st.duplicates} ${st.duplicates === 1 ? "was" : "were"} already in the project.` : ""),
        added ? link({ kind: "next", href: "#/hypotheses", class: "docs-check-link" }, "Check a hypothesis") : null)));
    const noText = new Set(st.scanned_no_text || []);
    if (st.ocr && st.ocr.length) bits.push(notice({ kind: "info", icon: "eye" }, h("p", {}, `Scanned pages were read with text recognition (OCR) in ${st.ocr.length === 1 ? "1 document" : `${st.ocr.length} documents`}: ${st.ocr.join(", ")}. The recognised text can contain mistakes; the quotes are checked against it.`)));
    const notAdded = [...noText].filter((f) => (st.empty_files || []).includes(f));
    if (noText.size) bits.push(notice({ kind: "attention" }, h("div", {}, h("p", {}, h("strong", {}, "Scanned: no text. "), `${noText.size === 1 ? "This document has" : "These documents have"} scanned pages that stayed without text: ${[...noText].join(", ")}. `,
      notAdded.length ? `${notAdded.length === 1 ? `${notAdded[0]} was not added, because none of its pages has text. ` : `${notAdded.length} of them were not added, because none of their pages has text. `}` : "",
      ocrState().available === false ? (ocrState().install ? "" : "Tesseract (text recognition) is needed to read them.") : (App.settings().ocr || "auto") === "off" ? ["Reading scanned PDFs is switched off: turn it on in ", h("a", { href: "#/settings/ocr" }, "Settings → Documents"), " and add the document again."] : "Text recognition could not read these pages."),
      ocrState().available === false ? tesseractHelp(ocrState()) : null)));
    const emptyOther = (st.empty_files || []).filter((f) => !noText.has(f));
    if (emptyOther.length) bits.push(notice({ kind: "attention" }, h("p", {}, `${emptyOther.length} ${emptyOther.length === 1 ? "file has" : "files have"} no readable text: ${emptyOther.join(", ")}`)));
    if (st.mostly_unreadable && st.mostly_unreadable.length) bits.push(notice({ kind: "attention" }, h("p", {}, "The text of these could mostly not be read: " + st.mostly_unreadable.join(", ") + ". Try another copy (for example from the publisher), or run OCR.")));
    if (st.failed && st.failed.length) bits.push(notice({ kind: "error", live: false }, h("div", {}, h("p", {}, "These could not be read:"), h("ul", { class: "errors-list" }, st.failed.map((f) => h("li", {}, f))))));
    if (st.excluded && st.excluded.length) bits.push(h("p", { class: "muted small" }, `Left out: ${st.excluded.join(", ")}`));
    if (st.not_in_manifest && st.not_in_manifest.length) bits.push(h("p", { class: "muted small" }, `Not named in the manifest: ${st.not_in_manifest.slice(0, 10).join(", ")}${st.not_in_manifest.length > 10 ? "…" : ""}`));
    if (st.glossary_error || st.codes_error) bits.push(notice({ kind: "attention" }, h("div", {}, h("p", {}, "The documents were added, but " + (st.glossary_error ? "the glossary of terms" : "the codes found by keywords") + " could not be updated. Update them from the Concepts or Profile page."), fold({}, "Technical details", h("div", { class: "mono small" }, st.glossary_error || st.codes_error)))));
    if (st.semantic_index_error) bits.push(notice({ kind: "attention" }, h("div", {}, h("p", {}, "The documents were added, but search by meaning could not be set up for them, so they are searched by their words only."), fold({}, "Technical details", h("div", { class: "mono small" }, st.semantic_index_error)))));
    // 0.13: the works of the bibliography the new documents are
    const bib = st.bibliography;
    if (bib && (bib.linked || bib.confirm)) bits.push(h("p", { class: "it" }, icon("library", { size: 14 }), h("span", {},
      [bib.linked ? `${bib.linked} ${bib.linked === 1 ? "was linked to its work" : "were linked to their works"} in the bibliography` : null,
        bib.confirm ? `${bib.confirm} ${bib.confirm === 1 ? "waits" : "wait"} for you to confirm ${bib.confirm === 1 ? "its work" : "their works"}` : null].filter(Boolean).join("; ") + ": ",
      h("a", { href: "#/bibliography" }, "see Bibliography"), ".")));
    const newDocsLine = h("div", { "aria-live": "polite" });
    if (added) bits.push(newDocsLine);
    replace(holder.querySelector(".pb"), h("div", { class: "stack" }, bits));
    // results checked before these documents were added can read them now
    if (added) api("GET", `/api/projects/${P(project)}/hypotheses`).then((r) => {
      const n = (r.hypotheses || []).filter((x) => x.docs_added_since > 0).length;
      if (!n) return;
      replace(newDocsLine, h("p", { class: "it" }, icon("history", { size: 14 }), h("span", {}, `${n} ${n === 1 ? "result was checked before these documents were added and can read them now" : "results were checked before these documents were added and can read them now"}: `, h("a", { href: "#/hypotheses" }, "go to Hypotheses"), " and press “Read the new documents”. Your reviews are kept.")));
    }).catch(() => {});
  }

  addBtn.addEventListener("click", async () => {
    if (!files.length || adding) return;
    adding = true; sent = files.slice();
    addBtn.disabled = true;
    const batch = batchId();
    progressBox.hidden = false;
    const holder = card({ as: "div", title: "Copying the files into the project" }, h("div", { class: "pb" }));
    replace(progressBox, holder);
    let n = 0;
    try {
      for (const f of sent) {
        replace(holder.querySelector(".pb"), simpleProgress({ state: "running", seconds: 0, progress: { done: n, total: sent.length, file: f.name } }, () => `Copying ${f.name} (${n + 1} of ${sent.length})`));
        await api("POST", `/api/projects/${P(project)}/uploads?batch=${batch}&name=${encodeURIComponent(f.name)}`, f);
        n++;
      }
    } catch (e) { showError(e); adding = false; sent = []; drawFiles(); progressBox.hidden = true; return; }
    const body = { batch, ai_access: chosenLevel };
    if (excludeInput.value.trim()) body.exclude = excludeInput.value.trim();
    await runIngest(body, `Reading ${sent.length === 1 ? "the document" : `the ${sent.length} documents`}`);
  });
  pathBtn.addEventListener("click", async () => {
    const p = pathInput.value.trim();
    if (!p) { pathInput.focus(); return; }
    if (needLevel()) { toast("Say first who may read these documents with AI.", "warn"); accessPick.scrollIntoView({ block: "center" }); return; }
    pathBtn.disabled = true;
    const body = { path: p, ai_access: chosenLevel };
    if (excludeInput.value.trim()) body.exclude = excludeInput.value.trim();
    await runIngest(body, `Reading the folder`);
  });
  pathInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); pathBtn.click(); } });

  // ----------------------------------------------------------------- smart search
  const indexCard = card({ "aria-label": "Search by meaning" });
  view.appendChild(indexCard);
  // 0.17: the index job of this project while it is queued or running (started here, or found after a reload): the card
  // shows it in place of the button, with the counts of the job's own progress, until it ends and the counts are read again
  let indexJob = null, lastSearch = null;
  const indexLabel = (p) => (p.total ? `Preparing ${fmt.num(p.done || 0)} of ${fmt.num(p.total)} excerpts` : "Starting…");
  function followIndex(jobId) {
    const w = watchJob(jobId, (job) => { if (TERMINAL.has(job.state)) return; indexJob = job; drawIndex(lastSearch); });
    watchers.push(w);
    return w.promise.then(async (job) => { indexJob = null; await reloadDocs(); return job; },
      (e) => { indexJob = null; drawIndex(lastSearch); throw e; });
  }
  function drawIndex(search) {
    clear(indexCard);
    lastSearch = search;
    const s = search || {};
    const body = h("div", { class: "grow" });
    const head = h("div", { class: "index-card" }, h("span", { class: "icon-big" }, icon("network", { size: 26 })), body);
    if (!s.model) {
      body.append(h("h2", {}, "Search by meaning is off"), h("p", { class: "muted docs-index-sub" }, "Documents are searched by their words only. With search by meaning, excerpts are found even when they use other words than your hypothesis. It can be turned on under Settings → Documents."));
      indexCard.appendChild(head); return;
    }
    if (indexJob) {
      const p = indexJob.progress || {};
      body.append(h("h2", {}, "Setting up search by meaning…"), h("p", { class: "muted docs-index-sub" }, p.total ? `${fmt.num(p.done || 0)} of ${fmt.num(p.total)} excerpts are covered. Until it is set up, the rest are found by their words only.` : "Getting ready…"));
      head.appendChild(button({ kind: "main", disabled: true }, icon("network", { size: 14 }), "Setting up…"));
      indexCard.append(head, h("div", { class: "docs-index-progress" }, simpleProgress(indexJob, indexLabel)));
      return;
    }
    if (!s.passages) {
      body.append(h("h2", {}, "Search by meaning is on"), h("p", { class: "muted docs-index-sub" }, "Finds excerpts even when they use other words than your hypothesis. It is set up automatically for every document you add."));
      indexCard.appendChild(head); return;
    }
    const complete = s.complete || (s.passages > 0 && s.embedded >= s.passages);
    body.append(h("h2", {}, complete ? "Search by meaning is on" : s.embedded ? "Search by meaning is set up for part of the documents" : "Search by meaning is not set up yet"),
      h("p", { class: "muted docs-index-sub" }, complete ? "Finds excerpts even when they use other words than your hypothesis." : `${fmt.num(s.embedded || 0)} of ${fmt.num(s.passages || 0)} excerpts are covered. Until it is set up, the rest are found by their words only.`));
    const btn = complete ? null : button({ kind: "main" }, icon("network", { size: 14 }), "Set up search by meaning");
    if (!complete) btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const r = await api("POST", `/api/projects/${P(project)}/index`);   // a job already running comes back as it is
        indexJob = r.job; drawIndex(lastSearch);
        const job = await followIndex(r.job.id);
        if (job.state === "error") showError({ message: job.error, kind: job.error_kind }); else if (job.state === "done") toast("Search by meaning is ready.", "ok");
      } catch (e) { showError(e); btn.disabled = false; }
    });
    if (btn) head.appendChild(btn);
    indexCard.appendChild(head);
  }

  // ----------------------------------------------------------------- documents
  const docsBox = h("section", { class: "section", "aria-label": "Documents in this project" });
  view.appendChild(docsBox);
  const picked = new Set();   // the documents ticked for a change of several at once (kept across re-draws)
  // 0.15.7: documents read by an earlier reader, moved to the new one from here (several at once): the box keeps
  // its job's progress, or what the last move did, across re-draws of the list
  const nrBox = h("div", { class: "nr-box", role: "region", "aria-label": "Documents read by an earlier reader" });
  const nr = { running: false, done: null, plan: null, older: [] };
  let pa = {};                // the project's AI-access info, as last drawn
  let groupsBox = null;
  let grouping = store(`docs-group:${project}`) || "ai";   // 0.18.5: how the list is grouped, kept per project
  let filterText = "";
  let shownIds = new Set();    // 0.18.5: the documents the list shows now (the filter and the folded groups hide others)
  let lastTick = null;         // 0.18.5: the tick a shift-click runs from
  let sorting = store(`docs-sort:${project}`) || "title";   // 0.18.5: by title, or the newest first
  const rows = new Map();     // doc_id -> its row
  const opened = new Set();   // 0.18.2: the documents whose panel is open (kept across re-draws)
  let roles = {};             // 0.18.1 (K2): doc_id -> "theory"
  // 0.18.5: what needs a look, for the grouping and the notice above the list: a fact that needs you (a check, a sync
  // clash, a scan with no text, a reading done badly), a reading to look over, or nothing
  const lookOf = (d) => {
    const unchecked = !d.reading_checked && (d.reading_quality === "poor" || d.reading_quality === "fair");
    if (d.check || d.clash || (d.scanned && /no text/i.test(d.scanned)) || (unchecked && d.reading_quality === "poor")) return "attention";
    return unchecked ? "reading" : "clear";
  };
  const GROUPINGS = {
    ai: { label: "AI setting", always: true, of: (d) => d.ai_access, groups: [
      { key: "cloud", name: "Claude may read them", short: "Claude", icon: "cloud", sub: "Claude may read them when Claude is the AI you use; when you use a local model, it reads them instead." },
      { key: "local", name: "Only a local AI", short: "Local AI", icon: "house", sub: "Read only by a model on this computer, or by you. Never sent to Claude." },
      { key: "none", name: "No AI", icon: "eye-off", sub: "Only you judge their excerpts. Search, the keyword codes, concepts and themes still work." }] },
    role: { label: "Role", always: true, of: (d) => (roles[d.doc_id] === "theory" ? "theory" : "evidence"), groups: [
      { key: "evidence", name: "Evidence", icon: "file-text", sub: "What hypotheses are checked against, and what themes, codes and key terms are made from." },
      { key: "theory", name: "Theory", icon: "book-marked", sub: "The lens the research is read through: left out of themes, codebook labels, the excerpts a check reads and key terms." }] },
    look: { label: "Problems", always: false, of: lookOf, groups: [
      { key: "attention", name: "Needs a look", icon: "eye", sub: "Something about the file or its reading needs you: point at the mark on each, or open it, to see what." },
      { key: "reading", name: "Something to check in its reading", short: "To check", icon: "layers", sub: "Read with a few doubts: open the reading to see where, then mark it as checked." },
      { key: "clear", name: "Nothing to look at", short: "Fine", icon: "check", sub: "Read well: nothing about them needs you." }] },
    none: { label: "None", always: true, of: () => "all", groups: [{ key: "all", name: "All documents", icon: null, sub: null }] },
  };
  async function reloadDocs() {
    let r;
    try { [r, roles] = await Promise.all([api("GET", `/api/projects/${P(project)}/documents`), documentRoles(project)]); } catch (e) { failedLoad(docsBox, e); return; }
    drawDocs(r);
  }
  // the whole list: after adding or removing documents (a change of one document's AI setting patches its row)
  function drawDocs(r) {
    drawIndex(r.search);
    const docs = r.documents || [];
    pa = r.ai_access || {};
    clear(docsBox); rows.clear();
    for (const id of [...picked]) if (!docs.some((d) => d.doc_id === id)) picked.delete(id);
    if (pa.ask) docsBox.appendChild(accessAskCard(project, pa, reloadDocs));
    else if (pa.banner && docs.length) { const b = accessBanner(project, () => b.remove()); docsBox.appendChild(b); }
    const countHead = h("h2", {}, `${docs.length} ${docs.length === 1 ? "document" : "documents"} in this project`);
    docsBox.appendChild(h("div", { class: "section-title" }, countHead));
    if (!docs.length) { addFold.open = true; docsBox.appendChild(emptyState("book-open", "No documents yet", "Add the reports, papers and web pages you want to check hypotheses against. PDFs keep their page numbers.")); return; }
    if (!addFoldSet) { addFold.open = !docs.length; addFoldSet = true; }
    reader.latest = r.new_reader || reader.latest;
    // a sentence that needs you is a one-line notice; the tag beside each document says what (docs/DESIGN.md 4.10, 4.12).
    // 0.18.5: Show them, at the sentence's end, groups the list by what needs a look (not shown when it already is)
    let warnedNote = h("div");
    const drawWarned = () => {
      const warned = docs.filter((d) => lookOf(d) === "attention").length;
      const n = !warned || grouping === "look" ? h("div", { hidden: true }) : notice({ kind: "attention", class: "docs-warned" },
        h("p", {}, `${warned} ${warned === 1 ? "document needs" : "documents need"} a look. `,
          grouping === "look" ? null : link({ kind: "jump", onClick: () => { setGrouping("look"); groupsBox.scrollIntoView({ block: "start" }); } }, "Show them")));
      warnedNote.replaceWith(n); warnedNote = n;
    };
    docsBox.appendChild(warnedNote);
    drawWarned();
    nr.older = docs.filter((d) => newReaderFor(d, reader.latest));
    docsBox.appendChild(nrBox);
    drawNr();
    // 0.11: who may read each document with AI, several at once. 0.18.2: one button per setting, in a bar that stays
    // in view while rows are ticked (a select and Apply were two steps, and scrolled away over a long list)
    const bulkCount = h("span", { class: "small", "aria-live": "polite" });
    // 0.18.5: the bar sits under the list; this line above it reaches it at once (from the keyboard too)
    const toBar = link({ kind: "jump", class: "docs-to-bar", hidden: true, onClick: () => { const b = bulk.querySelector("button"); if (b) { b.scrollIntoView({ block: "nearest" }); b.focus(); } } });
    const bulk = h("div", { class: "bulk-bar bulk-stick", hidden: true, role: "region", "aria-label": "Change the selected documents" }, bulkCount,
      h("span", { class: "bulk-move" }, accessLevels().map((lv) => button({ sm: true, "data-level": lv, onClick: () => setAccess([...picked], lv, undefined, { fromBar: true }) }, icon(LEVEL[lv].icon, { size: 13 }), LEVEL[lv].many))),
      button({ kind: "quiet", sm: true, onClick: () => clearPicked() }, "Clear"));
    const drawBulk = () => {
      bulk.hidden = !picked.size;
      // ticks the filter or a folded group hides still count: the bar says how many, so a change never surprises
      const unseen = [...picked].filter((id) => !shownIds.has(id)).length;
      bulkCount.textContent = `${picked.size} selected${unseen ? ` (${unseen} not shown)` : ""}. Who may read ${picked.size === 1 ? "it" : "them"} with AI?`;
      toBar.hidden = !picked.size;
      toBar.textContent = `Change the ${plural(picked.size, "document")} selected`;
      // a setting every ticked document has already is no change: its button says so by being off
      const levels = new Set(docs.filter((d) => picked.has(d.doc_id)).map((d) => d.ai_access));
      for (const b of bulk.querySelectorAll("[data-level]")) b.disabled = levels.size === 1 && levels.has(b.dataset.level);
      for (const f of groupsBox ? groupsBox.querySelectorAll(".doc-group") : []) if (f.paintPick) f.paintPick();
      drawNr();
    };
    const clearPicked = () => { picked.clear(); for (const c of docsBox.querySelectorAll(".doc-tick")) c.checked = false; drawBulk(); };
    // how much of it Claude has read, in words that say what the share counts (DESIGN 4.1: a number is never a button)
    const sentWords = (d) => {
      const pct = Math.round((d.sent || 0) * 1000) / 10;
      if (!pct) return d.ai_access === "cloud" ? "nothing yet" : "nothing: it is not for Claude";
      return `${pct < 1 ? "less than 1" : Math.round(pct)}% of its text${d.budget_reached ? " (its cap is reached)" : ""}`;
    };
    // what needs a look in how it was read: a tag says what, with its way on after it (DESIGN 4.10)
    const readingMarks = (d) => [
      d.clash ? tag({ kind: "attention", title: `The same file as another document here, read into other text on ${d.clash.name === "you" ? "your" : `${d.clash.name}’s`} computer (another ENLENS version, or text recognition on one computer and not the other). Quotes are places in the text, so this reading came in as a document of its own, with the results made from it.` }, `sync clash · ${d.clash.name === "you" ? "your" : `${d.clash.name}’s`} reading`) : null,
      d.check ? tag({ kind: "attention" }, d.check) : null,
      d.scanned ? (/no text/i.test(d.scanned) ? tag({ kind: "attention", class: "it scanned-note" }, d.scanned) : h("span", { class: "it scanned-note muted small" }, icon("eye", { size: 12 }), d.scanned)) : null,
      readingNote(d)].filter(Boolean);
    const docHref = (d) => `#/doc/${encodeURIComponent(d.doc_id)}`;
    const sameTitle = new Set();   // titles two documents share (lower case)
    { const seenT = new Set(); for (const d of docs) { const t = (d.title || "").trim().toLowerCase(); if (t && seenT.has(t)) sameTitle.add(t); seenT.add(t); } }
    // 0.18.5: the same on a closed line, as icons: each named in its tooltip and to a screen reader, and said in words in
    // the panel the line opens. What needs you keeps the needs-you look (an amber tag with its icon, no words).
    const iconMark = (ic, label, cls) => h("span", { class: `doc-icon-mark${cls ? ` ${cls}` : ""}`, role: "img", "aria-label": label, title: label }, icon(ic, { size: 14 }));
    const needsYou = (label) => tag({ kind: "attention", class: "doc-icon-tag", role: "img", "aria-label": label, title: label });
    const rowMarks = (d) => {
      const unchecked = !d.reading_checked && (d.reading_quality === "poor" || d.reading_quality === "fair");
      const chip = docChip(d.proposal);
      return [
        d.clash ? needsYou("Sync clash: the same file, read into other text on another computer") : null,
        d.check ? needsYou(d.check) : null,
        d.scanned && /no text/i.test(d.scanned) ? needsYou(d.scanned) : null,
        unchecked && d.reading_quality === "poor" ? needsYou("Read badly: look at its reading") : null,
        unchecked && d.reading_quality === "fair" ? iconMark("info", "Something to check in its reading") : null,
        !unchecked && newReaderFor(d, reader.latest) ? iconMark("layers", "Read by an earlier reader of ENLENS") : null,
        chip ? iconMark(chip.kind === "declined" ? "minus" : "clock", `${chip.label}${chip.text ? `: ${chip.text}` : ""}`) : null,
      ].filter(Boolean);
    };
    // 0.18.2: everything about one document, each fact under its name, in a panel under its row (DESIGN 4.20)
    const detailFor = (d) => {
      const name = d.title || d.file;
      const about = () => docAccessDialog(project, d, pa.default, (res) => patchDocs(res, [d.doc_id]));
      const access = choice({ sm: true, class: "doc-access", label: `Who may read ${name} with AI`, value: d.ai_access,
        options: accessLevels().map((lv) => [lv, [icon(LEVEL[lv].icon, { size: 13 }), LEVEL[lv].title]]), onPick: (lv) => setAccess([d.doc_id], lv) });
      const marks = readingMarks(d);
      const role = roleMenuItem(project, d, roles[d.doc_id], async () => { try { roles = await documentRoles(project); } catch (_) { /* as it was */ } drawGroups([d.doc_id], ".doc-role-btn"); });
      const facts = [KIND_TEXT[d.kind] || d.kind || "", d.pages ? plural(d.pages, "page") : null, (fmt.dateShort(d.added_at || "") || d.added) ? `added ${fmt.dateShort(d.added_at || "") || d.added}` : null].filter(Boolean).join(" · ");
      return h("div", { class: "doc-detail", id: `doc-detail-${d.doc_id}` },
        h("dl", { class: "doc-detail-grid" },
          h("dt", {}, "File"), h("dd", {}, h("span", { class: "doc-file" }, ...String(d.file || "").split(/(?<=[_-])/).flatMap((seg) => [seg, h("wbr")])), h("span", { class: "muted small" }, facts)),   // a file name may break after _ or -, never before its extension
          h("dt", {}, "Who may read it with AI"), h("dd", {}, access, button({ kind: "quiet", sm: true, class: "doc-why", title: d.note ? `Why: ${d.note}` : null, onClick: about }, d.note ? `Why: ${d.note}` : "Add a note on why")),
          h("dt", {}, "Sent to Claude"), h("dd", {}, h("span", {}, sentWords(d)), d.sent ? button({ kind: "quiet", sm: true, title: "What Claude has read of this document, and who may read it", onClick: about }, "See what it read") : null),
          h("dt", {}, "Reading"), h("dd", {}, marks.length ? marks : h("span", { class: "it" }, icon("check", { size: 13 }), "readable"),
            readingNote(d) ? null : link({ href: `${docHref(d)}?tab=reading`, class: "small" }, "How it was read")),
          d.proposal && docChip(d.proposal) ? [h("dt", {}, "The owner"), h("dd", {},
            proposalChip(d.proposal),   // 0.18 L2: waits for the owner, or in your copy only
          )] : null,
          h("dt", {}, "Role"), h("dd", {}, roles[d.doc_id] === "theory" ? "Theory: the lens the research is read through, not evidence" : "Evidence",
            button({ kind: "quiet", sm: true, class: "doc-role-btn", onClick: role.onClick }, role.text)),
          d.bib && d.bib.cite ? [h("dt", {}, "In the bibliography"), h("dd", {}, h("span", { class: "it", title: d.bib.title || null }, icon("library", { size: 13 }), d.bib.cite),
            link({ href: "#/bibliography", class: "small" }, "Open the Bibliography"))] : null),
        h("div", { class: "doc-detail-foot" }, link({ kind: "next", href: docHref(d) }, "Open the document"),
          button({ kind: "quiet", sm: true, onClick: () => removeDoc(d, () => {
            // 0.18.5: gone from the list where it stood; the page stays where it was
            const at = docs.findIndex((x) => x.doc_id === d.doc_id);
            if (at >= 0) docs.splice(at, 1);
            picked.delete(d.doc_id); opened.delete(d.doc_id);
            countHead.textContent = `${docs.length} ${docs.length === 1 ? "document" : "documents"} in this project`;
            drawWarned(); drawGroups([]); drawBulk();
          }) }, icon("trash", { size: 13 }), "Remove…")));
    };
    // 0.18.2: a document is one line: its tick, its title, what is true of it now (its role, a wait for the owner) and
    // what needs a look; the arrow (or a click on the row) opens the panel under it. No column hides anything, at any
    // width, and nothing at rest is a control but the tick, the title and the arrow. 0.18.5: who may read it is the
    // group it stands in, so the row no longer says it; a long title ends in "…" and shows whole when the row is open.
    const rowFor = (d) => {
      const name = d.title || d.file;
      const c = h("input", { type: "checkbox", class: "doc-tick", value: d.doc_id, "aria-label": `Select ${name}`, checked: picked.has(d.doc_id) });
      c.addEventListener("click", (e) => {
        // 0.18.5: shift-click ticks (or unticks) every document between the last one ticked and this one, in its group
        const ticks = [...(c.closest(".doc-list")?.querySelectorAll(".doc-tick") || [])];
        const from = ticks.indexOf(lastTick), to = ticks.indexOf(c);
        if (e.shiftKey && from >= 0 && to >= 0) for (const t of ticks.slice(Math.min(from, to), Math.max(from, to) + 1)) t.checked = c.checked;
        for (const t of e.shiftKey && from >= 0 && to >= 0 ? ticks : [c]) { if (t.checked) picked.add(t.value); else picked.delete(t.value); }
        lastTick = c;
        drawBulk();
      });
      const item = h("li", { class: "doc-item" });
      let detail = null;
      const toggle = iconButton({ icon: "chevron-down", sm: true, class: "doc-toggle", label: `Details of ${name}`, title: "Details", "aria-controls": `doc-detail-${d.doc_id}` });
      const show = (open) => {
        if (open) opened.add(d.doc_id); else opened.delete(d.doc_id);
        if (open && !detail) { detail = detailFor(d); item.append(detail); }
        if (detail) detail.hidden = !open;
        if (open) item.dataset.open = "true"; else delete item.dataset.open;
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      };
      toggle.addEventListener("click", () => show(!opened.has(d.doc_id)));
      const lv = LEVEL[d.ai_access] || LEVEL.cloud;
      item.append(h("div", { class: "doc-row", onClick: (e) => { if (!e.target.closest("a, button, input, label, select, summary")) show(!opened.has(d.doc_id)); } },
        h("span", { class: "doc-lead" }, c,
          // 0.18.5: who may read it, as its icon in a gutter of its own (the group says it when the list is grouped by it)
          // and only for the documents kept from Claude, so those stand out; Claude's place stays empty, titles in line
          grouping === "ai" ? null : d.ai_access === "cloud" ? h("span", { class: "doc-ai", "aria-hidden": "true" })
            : h("span", { class: "doc-ai", "data-level": d.ai_access, role: "img", "aria-label": lv.title, title: lv.title }, icon(lv.icon, { size: 14 }))),
        h("div", { class: "doc-main" },
          h("div", { class: "doc-title", title: d.title && d.file ? `${d.title} · ${d.file}` : name }, link({ kind: "title", serif: true, href: docHref(d) }, name)),
          h("div", { class: "doc-marks" },
            // 0.18.5: the file name when another document has the same title (the one fact that tells them apart)
            sameTitle.has((d.title || "").trim().toLowerCase()) ? h("span", { class: "doc-fact", title: d.file || null }, d.file) : null,
            grouping === "role" || roles[d.doc_id] !== "theory" ? null : iconMark("book-marked", "Theory: the lens the research is read through, not evidence"),   // 0.18.1 K2
            ...rowMarks(d))),
        h("div", { class: "doc-end" }, toggle)));
      show(opened.has(d.doc_id));
      rows.set(d.doc_id, item);
      return item;
    };
    // a change of the AI setting, note or cap: the answer carries the list again; only the rows changed are
    // redrawn (the ticks and the scroll position stay). 0.18.5: a document whose setting changed moves to the group of
    // its new setting, still open, and comes into view there.
    function patchDocs(res, ids) {
      proposedToast(res, project, ids);   // 0.18 L2: a looser setting held for the owner's word says so
      pa = res.ai_access || pa;
      let moved = false;
      for (const d of res.documents || []) {
        const at = docs.findIndex((x) => x.doc_id === d.doc_id);
        if (at >= 0) { if (docs[at].ai_access !== d.ai_access) moved = true; docs[at] = d; }   // 0.14.3: the list the loosening check reads
      }
      if (moved) { drawGroups(ids); return; }
      for (const d of res.documents || []) { const old = rows.get(d.doc_id); if (old && ids.includes(d.doc_id)) old.replaceWith(rowFor(d)); }
    }
    // 0.18.5: Undo of a change of several: each document back to what it had (one call per setting it had)
    async function undoAccess(before) {
      const by = new Map();
      for (const [id, lv] of before) { if (!by.has(lv)) by.set(lv, []); by.get(lv).push(id); }
      for (const [lv, ids] of by) await setAccess(ids, lv, undefined, { undoing: true });
      toast("Put back as it was.", "ok", { ttl: 2500 });
    }
    // 0.14.3: loosening a setting (No AI or Only a local AI -> Claude may read it) is asked about first, naming the
    // document's own note: what Claude then reads cannot be taken back. Tightening stays instant.
    const OPENNESS = { none: 0, local: 1, cloud: 2 };
    async function confirmLoosen(ids, level) {
      const wider = docs.filter((d) => ids.includes(d.doc_id) && (OPENNESS[d.ai_access] ?? 2) < (OPENNESS[level] ?? 2));
      if (!wider.length) return true;
      const toClaude = level === "cloud";
      return confirmDialog({
        title: toClaude ? "Let Claude read this?" : "Let a local AI read this?",
        message: h("div", {},
          h("p", {}, toClaude ? `${wider.length === 1 ? "This document is" : `These ${wider.length} documents are`} marked ${wider.map((d) => LEVEL[d.ai_access].short).filter((x, i, a) => a.indexOf(x) === i).join(" or ")}. If you change that, the next check sends excerpts of ${wider.length === 1 ? "it" : "them"} to Claude, and that cannot be taken back.`
            : `${wider.length === 1 ? "This document is" : `These ${wider.length} documents are`} marked No AI. A local model on this computer may then read ${wider.length === 1 ? "it" : "them"}; nothing is sent to Claude.`),
          ...wider.slice(0, 4).map((d) => h("p", {}, h("strong", {}, d.title || d.file), d.note ? ` (your note: “${d.note}”)` : "")),
          wider.length > 4 ? h("p", { class: "muted small" }, `and ${wider.length - 4} more`) : null),
        confirmText: toClaude ? "Let Claude read it" : "Let a local AI read it", danger: true });
    }
    async function setAccess(ids, level, note, { fromBar = false, undoing = false } = {}) {
      // cancelled: those rows show their own setting again; the list stays where it is (it went back to the top)
      if (!(await confirmLoosen(ids, level))) {
        patchDocs({ documents: docs.filter((d) => ids.includes(d.doc_id)) }, ids);
        if (ids.length === 1) { const sel = rows.get(ids[0])?.querySelector('.doc-access [aria-checked="true"]'); if (sel) sel.focus(); }
        return;
      }
      const body = { doc_ids: ids, ai_access: level === pa.default ? null : level };
      if (note !== undefined) body.note = note;
      try {
        const res = await api("PUT", `/api/projects/${P(project)}/documents/ai-access`, body);
        const before = new Map(docs.filter((d) => ids.includes(d.doc_id)).map((d) => [d.doc_id, d.ai_access]));
        // 0.18 L2: unless proposed. 0.18.5: the settings' own words; a change of several can be taken back at once
        const words = ids.length === 1 ? `${LEVEL[level].title}.` : `${ids.length} documents: ${LEVEL[level].many}.`;
        const undo = ids.length > 1 ? { ttl: 9000, button: { text: "Undo", onClick: () => undoAccess(before) } } : { ttl: 2500 };
        if (!undoing) { if (!(res.proposed || []).length) toast(words, "ok", undo); }   // 0.18 L2: unless proposed
        if (fromBar) { picked.clear(); for (const c of docsBox.querySelectorAll(".doc-tick")) c.checked = false; }   // 0.18.5: done with them
        patchDocs(res, ids);
        drawBulk();
      } catch (e) { showError(e); await reloadDocs(); }
    }
    // 0.18.5: the list grouped by a choice (who may read them with AI, their role, what needs a look, or not at all),
    // each group under what it means and with a way to tick it all; a box above it keeps the documents whose title or
    // file name holds every word typed. A change that moves a document to another group keeps the page where it was:
    // every group draws again as far as it was drawn, and the moved rows glow where they land.
    const view = () => GROUPINGS[grouping] || GROUPINGS.ai;
    const filterBox = searchField({ placeholder: "Filter by title or file name", "aria-label": "Filter the documents by title or file name", value: filterText });
    let filterTimer = null;
    filterBox.input.addEventListener("input", () => { clearTimeout(filterTimer); filterTimer = setTimeout(() => { filterText = filterBox.input.value; drawGroups(); }, 150); });
    const groupChoice = choice({ sm: true, label: "Group the documents by", value: grouping,
      options: Object.entries(GROUPINGS).map(([k, g]) => [k, g.label]), onPick: (k) => setGrouping(k) });
    const setGrouping = (k) => {
      grouping = k; store(`docs-group:${project}`, k);
      groupChoice.set(k);   // its value and which option Tab reaches
      drawWarned(); drawGroups();
    };
    const sortChoice = choice({ sm: true, label: "Sort the documents by", value: sorting,
      options: [["title", "Title"], ["new", "Newest"]], onPick: (k) => { sorting = k; store(`docs-sort:${project}`, k); drawGroups(); } });
    const jumps = h("nav", { class: "docs-jumps small", "aria-label": "The groups" });
    docsBox.appendChild(h("div", { class: "docs-tools" }, filterBox,
      h("div", { class: "docs-group-by" }, h("span", { class: "muted small" }, "Group by"), groupChoice),
      h("div", { class: "docs-group-by" }, h("span", { class: "muted small" }, "Sort"), sortChoice)));
    docsBox.appendChild(h("div", { class: "docs-jump-row" }, jumps, toBar));
    const lazies = new Map();   // group key -> its lazy list, as last drawn
    // folded groups, per project and grouping ("ai:local"), kept between visits
    const FOLD_KEY = `docs-folded:${project}`;
    const folded = new Set((store(FOLD_KEY) || "").split(",").filter(Boolean));
    function drawGroups(movedIds = null, focusSel = null) {
      const y = window.scrollY;
      const reach = new Map([...lazies].map(([k, l]) => [k, l.shown()]));   // how far each group was drawn
      lazies.clear(); rows.clear();
      const words = filterText.toLowerCase().split(/\s+/).filter(Boolean);
      const hit = (d) => !words.length || words.every((w) => `${d.title || ""} ${d.file || ""}`.toLowerCase().includes(w));
      const v = view();
      // 0.18.5: sorted as chosen: by title (as the server lists them) or the newest first
      const seen = docs.filter(hit);
      if (sorting === "new") seen.sort((a, b) => String(b.added_at || "").localeCompare(String(a.added_at || "")));
      // a moved document is never left in a folded group: its group opens
      for (const id of movedIds || []) { const d = docs.find((x) => x.doc_id === id); if (d && folded.delete(`${grouping}:${v.of(d)}`)) store(FOLD_KEY, [...folded].join(",")); }
      shownIds = new Set(seen.filter((d) => !folded.has(`${grouping}:${v.of(d)}`)).map((d) => d.doc_id));
      const parts = v.groups.map((g) => {
        const mine = seen.filter((d) => v.of(d) === g.key);
        const all = docs.filter((d) => v.of(d) === g.key).length;
        if (!mine.length && !v.always) return null;
        const list = h("ul", { class: "doc-list" });   // the section around it carries the group's name
        const lazy = lazyList({ items: mine, render: rowFor, list, pageSize: 120, firstSize: Math.max(60, reach.get(g.key) || 0), noun: ["document", "documents"] });
        for (const id of movedIds || []) lazy.reveal((d) => d.doc_id === id);   // a moved row is drawn, wherever it lands
        lazies.set(g.key, lazy);
        const pick = button({ kind: "quiet", sm: true, class: "doc-group-pick", hidden: !mine.length, "aria-label": `Select every document in “${g.name}”`, onClick: () => {
          const every = mine.every((d) => picked.has(d.doc_id));
          for (const d of mine) { if (every) picked.delete(d.doc_id); else picked.add(d.doc_id); }
          for (const c of list.querySelectorAll(".doc-tick")) c.checked = !every;
          drawBulk();
        } });
        const fkey = `${grouping}:${g.key}`;
        const body = h("div", { class: "doc-group-body", id: `doc-group-${g.key}`, hidden: folded.has(fkey) },
          g.sub ? h("p", { class: "doc-group-sub" }, g.sub,
            grouping === "ai" && g.key === "cloud" && mine.some((d) => d.sent) ? ` Claude has read parts of ${mine.filter((d) => d.sent).length} of them.` : null) : null,
          mine.length ? [h("div", { class: "table-wrap" }, list), lazy.footer]
            : h("p", { class: "muted small doc-group-none" }, words.length && all ? "No title or file name here holds those words." : "None."));
        const fold = h("button", { class: "doc-group-fold", type: "button", "aria-expanded": folded.has(fkey) ? "false" : "true", "aria-controls": body.id,
          onClick: () => {
            const shut = !folded.has(fkey);
            if (shut) folded.add(fkey); else folded.delete(fkey);
            store(FOLD_KEY, [...folded].join(","));
            body.hidden = shut; fold.setAttribute("aria-expanded", shut ? "false" : "true");
            shownIds = new Set(docs.filter(hit).filter((d) => !folded.has(`${grouping}:${v.of(d)}`)).map((d) => d.doc_id));
            drawBulk();
          } },
          icon("chevron-down", { size: 14, class: "doc-group-chev" }), g.icon ? icon(g.icon, { size: 16 }) : null, g.name,
          mine.length ? tag({ kind: "count" }, words.length && mine.length !== all ? `${mine.length} of ${plural(all, "document")}` : plural(mine.length, "document")) : null);   // an empty group says None. under its head
        const box = h("section", { class: "doc-group", "data-group": g.key, "aria-label": g.name },
          h("div", { class: "doc-group-head" }, h("h3", {}, fold), pick), body);
        // its button says what it will do: tick them all, or take the ticks off again
        box.paintPick = () => {
          const every = mine.length && mine.every((d) => picked.has(d.doc_id));
          pick.textContent = every ? (mine.length === 1 ? "Clear it" : `Clear these ${mine.length}`) : (mine.length === 1 ? "Select it" : `Select these ${mine.length}`);
          pick.setAttribute("aria-label", `${every ? "Take the ticks off" : "Tick"} every document in “${g.name}”`);
        };
        box.paintPick();
        return box;
      }).filter(Boolean);
      // 0.18.5: the groups' counts above the list, each a jump to its group (a long first group no longer hides the rest)
      jumps.replaceChildren(...v.groups.filter((g) => v.always || seen.some((d) => v.of(d) === g.key)).flatMap((g, i) => {
        const n = seen.filter((d) => v.of(d) === g.key).length;
        return [i ? h("span", { class: "muted", "aria-hidden": "true" }, " · ") : null, link({ kind: "jump", onClick: () => {
          const sec = groupsBox.querySelector(`.doc-group[data-group="${g.key}"]`);
          if (!sec) return;
          const f = sec.querySelector(".doc-group-fold");
          if (f && f.getAttribute("aria-expanded") === "false") f.click();
          sec.scrollIntoView({ block: "start" });
          if (f) f.focus({ preventScroll: true });
        } }, `${g.short || g.name} ${n}`)].filter(Boolean);
      }));
      if (!seen.length) parts.push(h("p", { class: "muted doc-group-none" }, `No document's title or file name holds “${filterText.trim()}”.`));
      groupsBox.replaceChildren(...parts);   // (replaceChildren writes a null as the word "null")
      if (movedIds) {
        window.scrollTo({ top: y });
        const moved = movedIds.map((id) => rows.get(id)).filter(Boolean);
        for (const it of moved) { it.classList.remove("doc-glow"); void it.offsetWidth; it.classList.add("doc-glow"); }
        if (moved.length === 1) moved[0].scrollIntoView({ block: "nearest" });
        // the focus stays with what was used: the control just used in the moved document's panel, else the setting
        // chosen there, else its arrow (after the bar's change: the first document moved, as the bar goes away)
        if (moved.length) {
          const f = (focusSel && moved[0].querySelector(focusSel)) || moved[0].querySelector('.doc-access [aria-checked="true"]') || moved[0].querySelector(".doc-toggle");
          if (f) f.focus({ preventScroll: moved.length > 1 });
        }
      }
    }
    groupsBox = h("div", { class: "doc-groups" });
    docsBox.append(groupsBox, bulk);
    drawGroups();
    drawBulk();
  }

  // 0.15.7: the documents an earlier reader read, offered to the new one; the job's progress; what it did
  // 0.18 (M7): moving many documents. First a dry run (nothing changes): how many move cleanly and how many results
  // would lose their place. Then the person chooses: move the clean ones; review the results without a place, all in
  // one list, and Move anyway (they are kept as records that point nowhere, as in a move from the document's own
  // page); or Review next, one document's Reading preview after the other. The note after a move is one line and a
  // compact table.
  const REVIEW_KEY = `enlens-nr-review:${project}`;
  const reviewLeft = () => {
    try { const ids = JSON.parse(sessionStorage.getItem(REVIEW_KEY) || "[]"); return ids.filter((id) => nr.older.some((d) => d.doc_id === id)); } catch (_) { return []; }
  };
  const setReviewLeft = (ids) => { try { sessionStorage.setItem(REVIEW_KEY, JSON.stringify(ids)); } catch (_) { /* the walk still works from the plan */ } };
  const readingHref = (id) => `#/doc/${encodeURIComponent(id)}?tab=reading&preview=1`;
  function reviewNext(ids) {
    if (ids) setReviewLeft(ids);
    const left = reviewLeft();
    if (!left.length) { toast("No document is left to review.", "info"); return; }
    setReviewLeft(left.slice(1));
    navigate(readingHref(left[0]));
  }
  // one line per document: its title as a link to its Reading, what it is, and Review
  function nrTable(rows) {
    const shown = rows.slice(0, 20);
    return [h("table", { class: "nr-table small" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Document"), h("th", { scope: "col", class: "num" }, "Results without a place"), h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, "Review")))),
      h("tbody", {}, shown.map((r) => h("tr", {},
        h("td", {}, h("a", { href: readingHref(r.doc_id) }, r.title || "a document"), r.note ? h("span", { class: "muted" }, ` · ${r.note}`) : null,
          r.reason ? h("div", { class: "muted" }, r.reason) : null),
        h("td", { class: "num" }, r.count === null ? "–" : fmt.num(r.count)),
        h("td", {}, link({ href: readingHref(r.doc_id) }, "Review")))))),
      rows.length > shown.length ? h("p", { class: "muted small" }, `and ${fmt.num(rows.length - shown.length)} more.`) : null];
  }
  function drawNr() {
    if (nr.running) return;  // the job's card is in the box
    // while the note of the last move is shown, the documents it left as they were are listed there, not offered again
    const kept = new Set(((nr.done && nr.done.kept) || []).map((k) => k.doc_id));
    const older = nr.older.filter((d) => !kept.has(d.doc_id));
    const sel = older.filter((d) => picked.has(d.doc_id));
    const parts = [];
    if (nr.done) parts.push(nrSummary(nr.done));
    if (nr.plan) parts.push(nrPlan(nr.plan));
    else if (older.length) {
      const n = older.length;
      const left = reviewLeft();
      parts.push(notice({ kind: "info", icon: "layers" }, h("div", { class: "grow" },
        h("p", {}, h("strong", {}, `${fmt.num(n)} ${n === 1 ? "document was" : "documents were"} read by an earlier reader of ENLENS.`),
          ` ${n === 1 ? "It keeps" : "They keep"} that reading, so your quotes and judgements stay where they are. `,
          older.some((d) => (d.reader || 1) < 3) ? "The new reader reads two columns in the right order, sets running heads, page numbers and the like aside, keeps tables as tables and repairs words broken over lines."
            : older.some((d) => d.reader === 3) ? READER_4_NEWS : READER_5_NEWS),
        h("div", { class: "btn-row docs-nr-actions" },
          button({ kind: "main", sm: true, onClick: () => startNr(sel.length ? sel : older, !!sel.length) }, icon("layers", { size: 13 }),
            sel.length ? `Read the ${sel.length === 1 ? "selected one" : `${fmt.num(sel.length)} selected`} with the new reader` : n === 1 ? "Read it with the new reader" : `Read all ${fmt.num(n)} with the new reader`),
          left.length ? button({ kind: "quiet", sm: true, onClick: () => reviewNext() }, `Review next (${fmt.num(left.length)} left)`) : null,
          sel.length ? null : h("span", { class: "muted small" }, n === 1 ? "It is checked first; nothing changes until you say so." : "or tick some in the list to read only those. They are checked first; nothing changes until you say so.")))));
    }
    nrBox.hidden = !parts.length;
    replace(nrBox, parts);
  }
  // the dry run: nothing is stored; the answer is drawn by drawNr()
  async function startNr(list, chosen) {
    let job;
    try { job = (await api("POST", `/api/projects/${P(project)}/new-reader/preview`, chosen ? { doc_ids: list.map((d) => d.doc_id) } : {})).job; }
    catch (e) { showError(e); return; }
    followNrCheck(job.id);
  }
  function followNrCheck(jobId) {
    nr.running = true;
    nr.done = null; nr.plan = null;
    const w = jobCard(nrBox, jobId, "Checking where your results would go",
      (p) => (p.total ? `${fmt.num(p.done)} of ${fmt.num(p.total)}${p.file ? ` · ${p.file}` : ""}` : "Starting…"),
      async (j) => {
        nr.running = false;
        if (j.state === "done" && !(j.result || {}).stopped) nr.plan = j.result || null;
        drawNr();
      }, { small: true, plain: true, stoppedText: "Stopped. Nothing was changed." });
    watchers.push(w);
  }
  function nrPlan(plan) {
    const sum = plan.summary || {}, docs = plan.documents || [];
    const clean = docs.filter((d) => d.ok && !d.no_place), losing = docs.filter((d) => d.ok && d.no_place), cannot = docs.filter((d) => !d.ok);
    const rows = [...losing.map((d) => ({ doc_id: d.doc_id, title: d.title, count: d.no_place })),
      ...cannot.map((d) => ({ doc_id: d.doc_id, title: d.title, count: null, reason: d.reason }))];
    const movable = clean.length + losing.length;
    return notice({ kind: losing.length || cannot.length ? "attention" : "info", role: "status", icon: "layers" }, h("div", { class: "grow" },
      h("p", {}, h("strong", {}, `${fmt.num(clean.length)} of ${fmt.num(docs.length)} ${docs.length === 1 ? "document moves" : "documents move"} cleanly`),
        `: every result in ${clean.length === 1 ? "it" : "them"} finds its place in the new reading.`,
        losing.length ? ` ${plural(sum.results_without_place || 0, "result")} in ${plural(losing.length, "other document")} would lose ${(sum.results_without_place || 0) === 1 ? "its" : "their"} place.` : "",
        cannot.length ? ` ${plural(cannot.length, "document")} cannot be read again now.` : ""),
      rows.length ? [h("p", { class: "small muted" }, "Review shows what each would lose, on its own page. Nothing has been changed yet."), ...nrTable(rows)] : null,
      h("div", { class: "btn-row docs-nr-actions" },
        clean.length ? button({ kind: "main", sm: true, onClick: () => moveNr(clean.map((d) => d.doc_id), false, `Move the ${plural(clean.length, "document")} that ${clean.length === 1 ? "moves" : "move"} cleanly?`) },
          icon("layers", { size: 13 }), clean.length === docs.length ? (clean.length === 1 ? "Move it" : `Move all ${fmt.num(clean.length)}`) : `Move the ${fmt.num(clean.length)} that ${clean.length === 1 ? "moves" : "move"} cleanly`) : null,
        losing.length ? button({ kind: clean.length ? "quiet" : "main", sm: true, onClick: () => reviewAll(plan) }, `Review the ${plural(sum.results_without_place || 0, "result")} without a place`) : null,
        losing.length ? button({ kind: "quiet", sm: true, onClick: () => reviewNext(losing.map((d) => d.doc_id)) }, "Review next") : null,
        button({ kind: "quiet", sm: true, onClick: () => { nr.plan = null; drawNr(); } }, "Not now"),
        movable === 0 ? h("span", { class: "muted small" }, "None can be moved now.") : null)));
  }
  // one list of every result that would lose its place, by document, then Move anyway
  async function reviewAll(plan) {
    const losing = (plan.documents || []).filter((d) => d.ok && d.no_place);
    const total = losing.reduce((a, d) => a + d.no_place, 0);
    const body = h("div", { class: "nr-review" },
      h("p", {}, `${plural(total, "result")} in ${plural(losing.length, "document")} would find no place in the new reading. Move anyway keeps each as a record: its quote and judgement stay, but it no longer points at words in the text, and the page shows it as it shows an excerpt of a removed document. The move is written in the research log.`),
      losing.map((d) => h("section", { class: "nr-review-doc" },
        h("h3", {}, h("a", { href: readingHref(d.doc_id) }, d.title || "a document"), h("span", { class: "muted small" }, ` · ${plural(d.no_place, "result")}`)),
        h("ul", { class: "nr-review-list" }, d.not_placed.slice(0, 100).map((x) => h("li", {},
          x.quote ? h("blockquote", { class: "serif" }, x.quote) : null,
          h("div", { class: "muted small" }, [x.kind_text, x.what, x.where || (x.page ? `page ${x.page}` : null)].filter(Boolean).join(" · ")),
          x.why ? h("div", { class: "small" }, x.why) : null,
          x.left_out_kind ? h("div", { class: "muted small" }, `Its words are now in ${x.left_out_kind}.`) : null))),
        d.not_placed.length > 100 ? h("p", { class: "muted small" }, `and ${fmt.num(d.not_placed.length - 100)} more: see the document’s Reading.`) : null)));
    const go = await dialog({ title: "Results that would lose their place", body, wide: true,
      actions: [{ text: "Close", value: false }, { text: `Move anyway (${plural(losing.length, "document")})`, value: true, primary: true }] });
    if (go) await moveNr(losing.map((d) => d.doc_id), true);
  }
  async function moveNr(ids, anyway, ask) {
    if (ask) {
      const ok = await confirmDialog({ title: ask, danger: false, confirmText: "Move",
        message: "Each is read again from its original file, and your results (quotes, judgements, codes, themes) move with it to the same words. You can go on working meanwhile, or stop it: documents already moved stay moved." });
      if (!ok) return;
    }
    let job;
    try { job = (await api("POST", `/api/projects/${P(project)}/new-reader`, anyway ? { doc_ids: ids, keep_unplaced: true } : { doc_ids: ids })).job; }
    catch (e) { showError(e); return; }
    nr.plan = null;
    followNr(job.id);
  }
  function followNr(jobId) {
    nr.running = true;
    nr.done = null;
    const w = jobCard(nrBox, jobId, "Reading with the new reader",
      (p) => p.phase === "reading" ? (p.total ? `${fmt.num(p.done)} of ${fmt.num(p.total)}${p.file ? ` · ${p.file}` : ""}` : "Starting…")
        : p.phase === "embedding" ? "Updating search by meaning…" : "Updating key terms and codes…",
      async (job) => {
        nr.running = false;
        if (job.state === "done") nr.done = job.result || {};
        if (job.state === "done" || job.state === "cancelled") await reloadDocs();
      }, { small: true, plain: true, stoppedText: "Stopped. The documents already moved stay moved." });
    watchers.push(w);
  }
  // the note after a move: one line, then a compact table of the documents with results that have no place
  function nrSummary(res) {
    const moved = res.moved || [], kept = res.kept || [];
    const results = moved.reduce((a, m) => a + (m.results || 0), 0);
    const aside = moved.reduce((a, m) => a + (m.left_out || 0), 0);
    const noPlace = moved.reduce((a, m) => a + (m.no_place || 0), 0);
    const ok = moved.length && !kept.length;
    const rows = [...moved.filter((m) => m.no_place).map((m) => ({ doc_id: m.doc_id, title: m.title, count: m.no_place, note: "moved, kept as records" })),
      ...kept.map((k) => ({ doc_id: k.doc_id, title: k.title, count: k.cannot ? null : (k.not_placed ?? null), note: "left as it was", reason: k.cannot ? k.reason : null }))];
    return notice({ kind: ok ? "done" : "attention", role: "status" }, h("div", { class: "grow" },
      h("p", {}, h("strong", {}, `${res.stopped ? "Stopped. " : ""}${moved.length ? `Read with the new reader: ${plural(moved.length, "document")}` : "No document was moved"}`),
        moved.length ? `, ${plural(results, "result")} moved with ${moved.length === 1 ? "it" : "them"}${noPlace ? `, ${fmt.num(noPlace)} of them kept as ${noPlace === 1 ? "a record" : "records"} that point at no words` : ""}.` : ".",
        kept.length ? ` Left as ${kept.length === 1 ? "it was" : "they were"}: ${fmt.num(kept.length)}.` : ""),
      aside ? h("p", { class: "small" }, `${plural(aside, "result")} now ${aside === 1 ? "sits" : "sit"} in text the new reader leaves out of searches (a running head, say): see each document’s Reading.`) : null,
      rows.length ? [h("p", { class: "small muted" }, "Review shows each one’s results without a place. A document left as it was can be moved from its own page after that."), ...nrTable(rows)] : null),
      iconButton({ icon: "x", size: 14, label: "Close this note", title: null, onClick: () => { nr.done = null; drawNr(); } }));
  }

  async function removeDoc(d, gone) {
    // 0.16 (F4): the reason goes into the research log
    const proposal = await removalNote(project, d);   // 0.18 L2: in a collaborator's copy, a proposal to the owner
    const ok = await askWhy({ title: "Remove this document?", confirmText: "Remove", placeholder: "For example: a duplicate, the wrong version, outside the scope",
      message: h("div", {}, h("p", {}, h("strong", {}, d.title || d.file)), h("p", {}, "It is no longer searched. Results you already have keep their quotes, marked as coming from a removed document. Your notes on it are kept in Notes."), proposal) });
    if (!ok) return;
    try { await api("DELETE", `/api/projects/${P(project)}/documents/${P(d.doc_id)}${ok.why ? `?why=${encodeURIComponent(ok.why)}` : ""}`); toast(proposal ? "Removed from your copy. For the project it waits for the owner (Team tab)." : "Document removed.", "ok"); if (gone) gone(); else await reloadDocs(); await App.refresh(); }   // 0.18 L2: proposal
    catch (e) { showError(e); }
  }

  // ----------------------------------------------------------------- start over
  view.appendChild(fold({ class: "section" }, "Start over or remove the project",
    card({ class: "danger-zone docs-start-over", "aria-label": "Start over" },
      h("div", { class: "row docs-start-over-row" },
        h("div", { class: "grow" }, h("strong", {}, "Remove all documents and results"), h("div", { class: "muted small" }, "Empties this project. Your settings and other projects stay.")),
        button({ kind: "danger", onClick: async () => {
          const ok = await confirmDialog({ title: "Remove every document and every result?", message: `This empties the project “${project}”. It cannot be undone.`, confirmText: "Remove everything", typeToConfirm: "remove" });
          if (!ok) return;
          try { await api("DELETE", `/api/projects/${P(project)}/documents`, { confirm: true }); toast("All documents and results removed.", "ok"); await reloadDocs(); await App.refresh(); } catch (e) { showError(e); }
        } }, icon("trash", { size: 14 }), "Remove everything")),
      h("hr"),
      h("div", { class: "row docs-delete-row" },
        h("div", { class: "grow" }, h("strong", {}, "Remove this project"), h("div", { class: "muted small" }, info.linked ? "The folder is unlinked and left untouched." : "The project is moved to a trash folder; nothing is deleted outright.")),
        link({ kind: "next", href: "#/projects" }, "Manage projects")))));

  await reloadDocs();
  // an ingest or index job already running for this project (started earlier, or in another tab)
  try {
    const jobs = (await api("GET", "/api/jobs")).jobs || [];
    const running = jobs.find((j) => j.project === project && (j.kind === "ingest") && !TERMINAL.has(j.state));
    if (running) followIngest(running.id, "Adding documents");
    const moving = jobs.find((j) => j.project === project && j.kind === "new_reader" && !TERMINAL.has(j.state));  // 0.15.7
    if (moving) followNr(moving.id);
    const checking = jobs.find((j) => j.project === project && j.kind === "new_reader_preview" && !TERMINAL.has(j.state));  // 0.18 (M7)
    if (checking && !moving) followNrCheck(checking.id);
    const indexing = jobs.find((j) => j.project === project && j.kind === "index" && !TERMINAL.has(j.state));
    if (indexing) {
      indexJob = indexing; drawIndex(lastSearch);   // the card says it runs, with the button off
      followIndex(indexing.id).catch(showError);
    }
  } catch (_) { /* ignore */ }
  return () => watchers.forEach((w) => w.stop());
}

export { renderDocument } from "./doc-page.js";
