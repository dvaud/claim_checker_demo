// Documents: a big add area first, the document table, smart search in plain words, a document viewer, and the
// rarely needed things (folder path, exclude patterns, remove everything) folded away.
import { featureEyebrow, viewTabs } from "../features.js";
import { tesseractHelp, App, api, h, icon, replace, clear, toast, showError, failedLoad, fmt, pageHead, watchJob, P, batchId, confirmDialog, field, emptyState, TERMINAL, KIND_TEXT,
  dialog, certainty, breakSegments, session, download, plural, shortTitle, cap, runningJob, TOKEN, drawInSteps } from "../lib.js";
import { simpleProgress, jobCard } from "./progress.js";
import { blockNode, blockUnit, originalLink, forgetOriginals } from "./result.js";
import { LEVEL, accessChoice, accessSelect, accessBadge, accessAskCard, accessBanner, docAccessDialog, levels as accessLevels } from "./ai-access.js";
import { aiLabelCard, startKeywordPass, keywordLabel, SOURCE_WORDS, RELEVANCE_WORDS, DIRECTION_WORDS } from "./profile.js";
import { colourPicker, editNote, removeNote, useAsEvidence, noteCard } from "./notes.js";
import { askWhy } from "./versions.js";

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
  const addBtn = h("button", { class: "btn btn-primary btn-lg", type: "button", disabled: true }, icon("upload", { size: 15 }), "Add to the project");
  const excludeInput = h("input", { class: "input input-sm", type: "text", placeholder: "e.g. draft*  *_old.pdf", id: "exclude" });
  const drawFiles = () => {
    fileList.hidden = !files.length;
    replace(fileList, files.map((f, i) => h("li", {}, icon("file-text", { size: 13 }), h("span", { class: "grow", style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, f.name), h("span", { class: "fs" }, fmt.bytes(f.size)),
      h("button", { class: "icon-btn", type: "button", "aria-label": `Remove ${f.name} from the list`, style: { width: "24px", height: "24px" }, onClick: () => { files.splice(i, 1); drawFiles(); } }, icon("x", { size: 12 })))));
    addBtn.disabled = !files.length || needLevel() || adding;
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
    h("p", { class: "drop-title" }, h("strong", {}, "Drop your documents here"), " or ", h("label", { for: "src-files", class: "btn", tabindex: "0", onKeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } } }, "choose files"), fileInput),
    h("p", { class: "muted small" }, "PDF, Word (.docx), text, Markdown and saved web pages (HTML), or a zip folder of them. ",
      ocrState().available === false ? ["Scanned PDFs cannot be read on this computer yet: they need Tesseract (", h("a", { href: "#/settings/ocr" }, "how to get it"), ")."] : ocrState().available && (App.settings().ocr || "auto") === "off" ? "Reading scanned PDFs is switched off in Settings." : ocrState().available ? "Scanned PDFs are read with text recognition (OCR), which is slow and can make mistakes." : ""),
    fileList);
  for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); });
  for (const ev of ["dragleave", "drop"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); });
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
  const pathInput = h("input", { class: "input", type: "text", placeholder: "e.g. C:\\Users\\me\\Documents\\Literature  or  /Users/me/Documents/Literature", id: "src-path" });
  const pathBtn = h("button", { class: "btn", type: "button" }, icon("folder-open", { size: 14 }), "Add this folder");
  const progressBox = h("div", { class: "section", hidden: true, "aria-live": "polite" });

  const addCard = h("section", { class: "card", "aria-label": "Add documents" },
    drop,
    h("div", { class: "add-access" }, accessPick, acc.chosen ? null : h("p", { class: "muted small", style: { margin: "6px 0 0" } }, "Choose once for this project; it becomes the default, and you can change single documents in the list below.")),
    h("div", { class: "btn-row", style: { marginTop: "12px" } }, addBtn),
    h("details", { class: "fold", style: { marginTop: "12px" } }, h("summary", {}, "More ways to add"),
      h("div", { class: "card card-plain", style: { marginTop: "8px" } },
        h("div", { class: "field" }, h("label", { class: "field-label", for: "src-path" }, "Add a whole folder on this computer"), h("div", { class: "row", style: { flexWrap: "nowrap" } }, pathInput, pathBtn),
          h("div", { class: "field-help" }, "Type or paste the full path of a folder (or of a zip file). The files are read where they are, nothing is copied.")),
        field("Leave out files whose name matches", excludeInput, { help: "Patterns separated by spaces; * stands for anything. Applies to everything you add." }),
        h("p", { class: "small", style: { margin: "0 0 10px" } }, icon("library", { size: 13 }), " From Zotero: on the ", h("a", { href: "#/bibliography" }, "Bibliography"), " page, bring in a collection; the PDFs Zotero keeps are added in one go, and each document is linked to its work."),
        h("p", { class: "muted small", style: { margin: 0 } }, "For technical users: a zip may contain a manifest.csv (columns file, reference, doi) naming the work each file is; an ai_access column (cloud, local or none) and an ai_note column set each file's AI setting."))));
  view.appendChild(addCard);
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
    const holder = h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, label || "Adding documents"), h("button", { class: "btn btn-sm btn-outline-danger", type: "button", onClick: () => api("POST", `/api/jobs/${P(jobId)}/cancel`).catch(showError) }, icon("stop", { size: 13 }), "Stop")), h("div", { class: "pb" }));
    replace(progressBox, holder);
    const w = watchJob(jobId, (job) => {
      replace(holder.querySelector(".pb"), simpleProgress(job, (p) => p.phase === "embedding" ? `Setting up search by meaning for the new documents · ${p.done || 0} of ${p.total || "?"} excerpts` : p.phase === "glossary" ? "Updating the glossary of terms (Concepts)…" : p.phase === "codes" ? "Finding the codebook's codes by keywords (Profile)…" : p.file ? `Reading ${p.file} (${(p.done || 0) + 1} of ${p.total})` : p.total ? `${p.done} of ${p.total} files` : "Reading the files…"));
      if (TERMINAL.has(job.state)) { const b = holder.querySelector(".btn-outline-danger"); if (b) b.hidden = true; }
    });
    watchers.push(w);
    w.promise.then(async (job) => {
      const hd = holder.querySelector(".card-head h2"); if (hd) hd.textContent = job.state === "done" ? "Documents added" : job.state === "cancelled" ? "Stopped" : "Could not add the documents";
      if (job.state === "done") ingestSummary(holder, job.result || {});
      else if (job.state === "error") replace(holder.querySelector(".pb"), h("div", { class: "notice notice-error" }, icon("alert-circle"), h("div", {}, h("p", {}, "The documents could not be added."), h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, job.error || "")), job.error_kind === "backend" ? h("a", { href: "#/settings" }, "Check the AI model in Settings") : null)));
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
    bits.push(h("div", { class: `notice ${added ? "notice-ok" : "notice-warn"}` }, icon(added ? "circle-check" : "alert-triangle"),
      h("div", {}, h("p", {}, added ? `${added} ${added === 1 ? "document" : "documents"} added.` : "No new document was added.", st.duplicates ? ` ${st.duplicates} ${st.duplicates === 1 ? "was" : "were"} already in the project.` : ""),
        added ? h("a", { class: "btn btn-primary btn-sm", href: "#/hypotheses", style: { marginTop: "8px" } }, icon("flask", { size: 13 }), "Check a hypothesis") : null)));
    const noText = new Set(st.scanned_no_text || []);
    if (st.ocr && st.ocr.length) bits.push(h("div", { class: "notice notice-info" }, icon("eye"), h("p", {}, `Scanned pages were read with text recognition (OCR) in ${st.ocr.length === 1 ? "1 document" : `${st.ocr.length} documents`}: ${st.ocr.join(", ")}. The recognised text can contain mistakes; the quotes are checked against it.`)));
    const notAdded = [...noText].filter((f) => (st.empty_files || []).includes(f));
    if (noText.size) bits.push(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("div", {}, h("p", {}, h("strong", {}, "Scanned: no text. "), `${noText.size === 1 ? "This document has" : "These documents have"} scanned pages that stayed without text: ${[...noText].join(", ")}. `,
      notAdded.length ? `${notAdded.length === 1 ? `${notAdded[0]} was not added, because none of its pages has text. ` : `${notAdded.length} of them were not added, because none of their pages has text. `}` : "",
      ocrState().available === false ? (ocrState().install ? "" : "Tesseract (text recognition) is needed to read them.") : (App.settings().ocr || "auto") === "off" ? ["Reading scanned PDFs is switched off: turn it on in ", h("a", { href: "#/settings/ocr" }, "Settings → Documents"), " and add the document again."] : "Text recognition could not read these pages."),
      ocrState().available === false ? tesseractHelp(ocrState()) : null)));
    const emptyOther = (st.empty_files || []).filter((f) => !noText.has(f));
    if (emptyOther.length) bits.push(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("p", {}, `${emptyOther.length} ${emptyOther.length === 1 ? "file has" : "files have"} no readable text: ${emptyOther.join(", ")}`)));
    if (st.mostly_unreadable && st.mostly_unreadable.length) bits.push(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("p", {}, "The text of these could mostly not be read: " + st.mostly_unreadable.join(", ") + ". Try another copy (for example from the publisher), or run OCR.")));
    if (st.failed && st.failed.length) bits.push(h("div", { class: "notice notice-error" }, icon("alert-circle"), h("div", {}, h("p", {}, "These could not be read:"), h("ul", { class: "errors-list" }, st.failed.map((f) => h("li", {}, f))))));
    if (st.excluded && st.excluded.length) bits.push(h("p", { class: "muted small" }, `Left out: ${st.excluded.join(", ")}`));
    if (st.not_in_manifest && st.not_in_manifest.length) bits.push(h("p", { class: "muted small" }, `Not named in the manifest: ${st.not_in_manifest.slice(0, 10).join(", ")}${st.not_in_manifest.length > 10 ? "…" : ""}`));
    if (st.glossary_error || st.codes_error) bits.push(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("div", {}, h("p", {}, "The documents were added, but " + (st.glossary_error ? "the glossary of terms" : "the codes found by keywords") + " could not be updated. Update them from the Concepts or Profile page."), h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, st.glossary_error || st.codes_error)))));
    if (st.semantic_index_error) bits.push(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("div", {}, h("p", {}, "The documents were added, but search by meaning could not be set up for them, so they are searched by their words only."), h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, st.semantic_index_error)))));
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
    const holder = h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Copying the files into the project")), h("div", { class: "pb" }));
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
  const indexCard = h("section", { class: "card", "aria-label": "Search by meaning" });
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
    const head = h("div", { class: "index-card" }, h("span", { class: "icon-big" }, icon("sparkles", { size: 26 })), body);
    if (!s.model) {
      body.append(h("h2", {}, "Search by meaning is off"), h("p", { class: "muted", style: { margin: "4px 0 0" } }, "Documents are searched by their words only. With search by meaning, excerpts are found even when they use other words than your hypothesis. It can be turned on under Settings → Documents."));
      indexCard.appendChild(head); return;
    }
    if (indexJob) {
      const p = indexJob.progress || {};
      body.append(h("h2", {}, "Setting up search by meaning…"), h("p", { class: "muted", style: { margin: "4px 0 0" } }, p.total ? `${fmt.num(p.done || 0)} of ${fmt.num(p.total)} excerpts are covered. Until it is set up, the rest are found by their words only.` : "Getting ready…"));
      head.appendChild(h("button", { class: "btn btn-primary", type: "button", disabled: true }, icon("sparkles", { size: 14 }), "Setting up…"));
      indexCard.append(head, h("div", { style: { marginTop: "10px" } }, simpleProgress(indexJob, indexLabel)));
      return;
    }
    if (!s.passages) {
      body.append(h("h2", {}, "Search by meaning is on"), h("p", { class: "muted", style: { margin: "4px 0 0" } }, "Finds excerpts even when they use other words than your hypothesis. It is set up automatically for every document you add."));
      indexCard.appendChild(head); return;
    }
    const complete = s.complete || (s.passages > 0 && s.embedded >= s.passages);
    body.append(h("h2", {}, complete ? "Search by meaning is on" : s.embedded ? "Search by meaning is set up for part of the documents" : "Search by meaning is not set up yet"),
      h("p", { class: "muted", style: { margin: "4px 0 0" } }, complete ? "Finds excerpts even when they use other words than your hypothesis." : `${fmt.num(s.embedded || 0)} of ${fmt.num(s.passages || 0)} excerpts are covered. Until it is set up, the rest are found by their words only.`));
    const btn = complete ? null : h("button", { class: "btn btn-primary", type: "button" }, icon("sparkles", { size: 14 }), "Set up search by meaning");
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
  const nr = { running: false, done: null, older: [] };
  let pa = {};                // the project's AI-access info, as last drawn
  let countsEl = null, shieldNote = null, tbody = null;
  const rows = new Map();     // doc_id -> its row
  async function reloadDocs() {
    let r;
    try { r = await api("GET", `/api/projects/${P(project)}/documents`); } catch (e) { failedLoad(docsBox, e); return; }
    drawDocs(r);
  }
  const countsNode = () => {
    const docs = (pa.counts && Object.values(pa.counts).reduce((a, b) => a + b, 0)) || 0;
    return docs ? h("span", { class: "muted small access-counts" }, accessLevels().filter((lv) => (pa.counts || {})[lv]).map((lv) => [accessBadge(lv), ` ${pa.counts[lv]} `])) : h("span", { class: "muted small access-counts" });
  };
  const shieldNode = () => h("p", { class: "muted small", hidden: !(pa.counts && (pa.counts.local || pa.counts.none)) }, icon("shield", { size: 12 }), " Documents marked Only a local AI or No AI are never sent to Claude, in any feature.");
  // the whole list: after adding or removing documents (a change of one document's AI setting patches its row)
  function drawDocs(r) {
    drawIndex(r.search);
    const docs = r.documents || [];
    pa = r.ai_access || {};
    clear(docsBox); rows.clear();
    for (const id of [...picked]) if (!docs.some((d) => d.doc_id === id)) picked.delete(id);
    if (pa.ask) docsBox.appendChild(accessAskCard(project, pa, reloadDocs));
    else if (pa.banner && docs.length) { const b = accessBanner(project, () => b.remove()); docsBox.appendChild(b); }
    countsEl = countsNode();
    docsBox.appendChild(h("div", { class: "section-title" }, h("h2", {}, `In this project (${docs.length})`), docs.length ? countsEl : null));
    if (!docs.length) { docsBox.appendChild(emptyState("book-open", "No documents yet", "Add the reports, papers and web pages you want to check hypotheses against. PDFs keep their page numbers.")); return; }
    newReader = r.new_reader || newReader;
    const warned = docs.filter((d) => d.check || (d.reading_quality === "poor" && !d.reading_checked)).length;
    if (warned) docsBox.appendChild(h("p", { class: "muted small" }, icon("alert-triangle", { size: 12 }), ` ${warned} ${warned === 1 ? "document needs" : "documents need"} a look: see the note next to ${warned === 1 ? "it" : "them"}.`));
    shieldNote = shieldNode();
    docsBox.appendChild(shieldNote);
    nr.older = docs.filter((d) => (d.reader || 1) < newReader);
    docsBox.appendChild(nrBox);
    drawNr();
    // 0.11: the AI setting of each document (a dropdown), several at once, and how much Claude has read
    const bulkSel = h("select", { class: "select select-sm", "aria-label": "Who may read the selected documents with AI" }, accessLevels().map((lv) => h("option", { value: lv }, LEVEL[lv].title)));
    const bulkCount = h("span", { class: "small" });
    const bulk = h("div", { class: "bulk-bar", hidden: true, role: "region", "aria-label": "Change the selected documents" }, bulkCount, bulkSel,
      h("button", { class: "btn btn-sm btn-primary", type: "button", onClick: () => setAccess([...picked], bulkSel.value) }, icon("check", { size: 13 }), "Apply"),
      h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { picked.clear(); for (const c of docsBox.querySelectorAll(".doc-pick")) c.checked = false; drawBulk(); } }, "Clear"));
    const drawBulk = () => { bulk.hidden = !picked.size; bulkCount.textContent = `${picked.size} selected: who may read them with AI?`; drawNr(); };
    const pickAll = h("input", { type: "checkbox", class: "doc-pick-all", "aria-label": "Select every document" });
    // 0.16: every document of the list, drawn yet or not (the rows are drawn as the list scrolls into view)
    pickAll.addEventListener("change", () => { for (const d of docs) { if (pickAll.checked) picked.add(d.doc_id); else picked.delete(d.doc_id); } for (const c of docsBox.querySelectorAll(".doc-pick")) c.checked = pickAll.checked; drawBulk(); });
    const sentCell = (d) => {
      const pct = Math.round((d.sent || 0) * 1000) / 10;
      const label = d.ai_access !== "cloud" && !pct ? "never" : pct ? `${pct < 1 ? "<1" : Math.round(pct)}%` : "0%";
      return h("button", { class: "link-btn small", type: "button", title: "What Claude has read of this document", onClick: () => docAccessDialog(project, d, pa.default, (res) => patchDocs(res, [d.doc_id])) }, label, d.budget_reached ? h("span", { class: "muted" }, " (cap reached)") : null);
    };
    const rowFor = (d) => {
      const c = h("input", { type: "checkbox", class: "doc-pick", value: d.doc_id, "aria-label": `Select ${d.title || d.file}`, checked: picked.has(d.doc_id) });
      c.addEventListener("change", () => { if (c.checked) picked.add(d.doc_id); else picked.delete(d.doc_id); drawBulk(); });
      const row = h("tr", {},
        h("td", { class: "pick-col" }, c),
        h("td", {}, h("div", { class: "doc-title", title: d.title || d.file }, h("a", { href: `#/doc/${encodeURIComponent(d.doc_id)}` }, d.title || d.file)),
          h("div", { class: "doc-file" }, d.file),
          d.bib && d.bib.cite ? h("div", { class: "doc-cite it", title: `In the bibliography: ${d.bib.title}` }, icon("library", { size: 11 }), d.bib.cite) : null,
          // 0.14.3: Open and Remove sit under the title, where they are always in view (the table was wider than the page
          // and its last column, with them, was out of sight)
          h("div", { class: "doc-actions" },
            h("a", { class: "link-btn small", href: `#/doc/${encodeURIComponent(d.doc_id)}`, "aria-label": `Open ${d.title || d.file}` }, icon("eye", { size: 12 }), "Open"),
            h("button", { class: "link-btn small doc-remove", type: "button", "aria-label": `Remove ${d.title || d.file}`, onClick: () => removeDoc(d) }, icon("trash", { size: 12 }), "Remove"))),
        h("td", { "data-label": "Type" }, KIND_TEXT[d.kind] || d.kind || ""),
        h("td", { "data-label": "Pages", class: "num" }, d.pages ? String(d.pages) : "—"),
        h("td", { "data-label": "Added", class: "small muted nowrap" }, fmt.dateShort(d.added_at || "") || d.added || ""),
        h("td", { "data-label": "AI", class: "access-cell" }, accessSelect(d, pa.default, (lv) => setAccess([d.doc_id], lv || pa.default)),
          d.note ? h("button", { class: "link-btn small access-why", type: "button", title: `Why: ${d.note}`, onClick: () => docAccessDialog(project, d, pa.default, (res) => patchDocs(res, [d.doc_id])) }, d.note) : null),
        h("td", { "data-label": "Sent to Claude", class: "num" }, sentCell(d)),
        h("td", { "data-label": "Note", class: "check-cell" },
          d.clash ? h("span", { class: "it tag-clash", title: `The same file as another document here, read into other text on ${d.clash.name === "you" ? "your" : `${d.clash.name}’s`} computer (another ENLENS version, or text recognition on one computer and not the other). Quotes are places in the text, so this reading came in as a document of its own, with the results made from it.` }, icon("copy", { size: 12 }), `sync clash · ${d.clash.name === "you" ? "your" : `${d.clash.name}’s`} reading`) : null,
          d.check ? h("span", { class: "warn-chip" }, icon("alert-triangle", { size: 12 }), d.check) : null,
          d.scanned ? h("span", { class: "it scanned-note" + (/no text/i.test(d.scanned) ? " warn-chip" : " muted small") }, icon(/no text/i.test(d.scanned) ? "alert-triangle" : "eye", { size: 12 }), d.scanned) : null,
          readingNote(d),
          !d.check && !d.scanned && !readingNote(d) ? h("span", { class: "it muted small" }, icon("check", { size: 12 }), "readable") : null),
        );
      rows.set(d.doc_id, row);
      return row;
    };
    // a change of the AI setting, note or cap: the answer carries the list again; only the rows changed are
    // redrawn (the ticks and the scroll position stay), with the counts above the table
    function patchDocs(res, ids) {
      pa = res.ai_access || pa;
      for (const d of res.documents || []) { const at = docs.findIndex((x) => x.doc_id === d.doc_id); if (at >= 0) docs[at] = d; }   // 0.14.3: the list the loosening check reads
      for (const d of res.documents || []) { const old = rows.get(d.doc_id); if (old && ids.includes(d.doc_id)) old.replaceWith(rowFor(d)); }
      const c = countsNode(); countsEl.replaceWith(c); countsEl = c;
      const sh = shieldNode(); shieldNote.replaceWith(sh); shieldNote = sh;
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
    async function setAccess(ids, level, note) {
      if (!(await confirmLoosen(ids, level))) { await reloadDocs(); return; }
      const body = { doc_ids: ids, ai_access: level === pa.default ? null : level };
      if (note !== undefined) body.note = note;
      try {
        const res = await api("PUT", `/api/projects/${P(project)}/documents/ai-access`, body);
        toast(ids.length === 1 ? `${LEVEL[level].title}.` : `${ids.length} documents: ${LEVEL[level].many.toLowerCase()}.`, "ok", { ttl: 2500 });
        patchDocs(res, ids);
      } catch (e) { showError(e); await reloadDocs(); }
    }
    docsBox.appendChild(bulk);
    drawBulk();
    tbody = h("tbody");
    // 0.16 (H5): the rows are drawn as the list scrolls into view (hundreds of documents drew thousands of controls
    // before the page showed); ticking, the counts and the AI settings work on every document all the same
    drawInSteps(tbody, docs, rowFor, { first: 60, step: 120, more: (left, onClick) => h("tr", { class: "draw-more-row" },
      h("td", { colspan: "8" }, h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick }, icon("chevron-down", { size: 13 }), `Show more documents (${left} more)`))) });
    docsBox.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "table table-responsive docs-table" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col", class: "pick-col" }, pickAll), h("th", { scope: "col" }, "Title"), h("th", { scope: "col" }, "Type"), h("th", { scope: "col", class: "num" }, "Pages"), h("th", { scope: "col" }, "Added"), h("th", { scope: "col", id: "ai-column" }, "AI"), h("th", { scope: "col", class: "num", title: "The share of each document's text Claude has read" }, "Sent to Claude"), h("th", { scope: "col" }, "Note"))),
      tbody)));
  }

  // 0.15.7: the documents an earlier reader read, offered to the new one; the job's progress; what it did
  function drawNr() {
    if (nr.running) return;  // the job's card is in the box
    // while the note of the last move is shown, the documents it left as they were are listed there, not offered again
    const kept = new Set(((nr.done && nr.done.kept) || []).map((k) => k.doc_id));
    const older = nr.older.filter((d) => !kept.has(d.doc_id));
    const sel = older.filter((d) => picked.has(d.doc_id));
    const parts = [];
    if (nr.done) parts.push(nrSummary(nr.done));
    if (older.length) {
      const n = older.length;
      parts.push(h("div", { class: "notice notice-info" }, icon("layers"), h("div", { class: "grow" },
        h("p", {}, h("strong", {}, `${fmt.num(n)} ${n === 1 ? "document was" : "documents were"} read by an earlier reader of ENLENS.`),
          ` ${n === 1 ? "It keeps" : "They keep"} that reading, so your quotes and judgements stay where they are. The new reader reads two columns in the right order, sets running heads, page numbers and the like aside, keeps tables as tables and repairs words broken over lines.`),
        h("div", { class: "btn-row", style: { marginTop: "8px" } },
          h("button", { class: "btn btn-sm btn-primary", type: "button", onClick: () => startNr(sel.length ? sel : older, !!sel.length) }, icon("layers", { size: 13 }),
            sel.length ? `Read the ${sel.length === 1 ? "selected one" : `${fmt.num(sel.length)} selected`} with the new reader` : n === 1 ? "Read it with the new reader" : `Read all ${fmt.num(n)} with the new reader`),
          sel.length ? null : h("span", { class: "muted small" }, "or tick some in the list to read only those")))));
    }
    nrBox.hidden = !parts.length;
    replace(nrBox, parts);
  }
  async function startNr(list, chosen) {
    const n = list.length;
    const ok = await confirmDialog({
      title: n === 1 ? "Read this document with the new reader?" : `Read ${fmt.num(n)} documents with the new reader?`,
      message: h("div", {},
        h("p", {}, `${n === 1 ? "It is" : "Each is"} read again from ${n === 1 ? "its" : "their"} original file, and your results (quotes, judgements, codes, themes) move with ${n === 1 ? "it" : "each"} to the same words.`),
        h("p", {}, "A document where any result would not find its place is left as it is. The list afterwards says which, and you can look at each one on its own page before you move it."),
        h("p", { class: "muted small" }, "You can go on working meanwhile, or stop it: documents already moved stay moved.")),
      confirmText: n === 1 ? "Read it" : "Read them" });
    if (!ok) return;
    let job;
    try { job = (await api("POST", `/api/projects/${P(project)}/new-reader`, chosen ? { doc_ids: list.map((d) => d.doc_id) } : {})).job; }
    catch (e) { showError(e); return; }
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
  function nrSummary(res) {
    const moved = res.moved || [], kept = res.kept || [];
    const results = moved.reduce((a, m) => a + (m.results || 0), 0);
    const aside = moved.reduce((a, m) => a + (m.left_out || 0), 0);
    const ok = moved.length && !kept.length;
    return h("div", { class: `notice ${ok ? "notice-ok" : "notice-warn"}`, role: "status" }, icon(ok ? "circle-check" : "alert-triangle"), h("div", { class: "grow" },
      h("p", {}, h("strong", {}, `${res.stopped ? "Stopped. " : ""}${moved.length ? `Read with the new reader: ${plural(moved.length, "document")}` : "No document was moved"}`),
        moved.length ? `, ${plural(results, "result")} moved with ${moved.length === 1 ? "it" : "them"}.` : "."),
      aside ? h("p", { class: "small" }, `${plural(aside, "result")} now ${aside === 1 ? "sits" : "sit"} in text the new reader leaves out of searches (a running head, say): see each document’s Reading.`) : null,
      kept.length ? [h("p", { class: "small", style: { margin: "6px 0 2px" } }, h("strong", {}, `Left as ${kept.length === 1 ? "it was" : "they were"}: ${fmt.num(kept.length)}`)),
        h("ul", { class: "nr-kept small" }, kept.slice(0, 20).map((k) => h("li", {}, h("a", { href: `#/doc/${encodeURIComponent(k.doc_id)}?tab=reading&preview=1` }, k.title || "a document"), h("span", { class: "muted" }, ` · ${k.reason}`)))),
        kept.length > 20 ? h("p", { class: "muted small" }, `and ${fmt.num(kept.length - 20)} more.`) : null] : null),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Close this note", onClick: () => { nr.done = null; drawNr(); } }, icon("x", { size: 14 })));
  }

  async function removeDoc(d) {
    // 0.16 (F4): the reason goes into the research log
    const ok = await askWhy({ title: "Remove this document?", confirmText: "Remove", placeholder: "For example: a duplicate, the wrong version, outside the scope",
      message: h("div", {}, h("p", {}, h("strong", {}, d.title || d.file)), h("p", {}, "It is no longer searched. Results you already have keep their quotes, marked as coming from a removed document. Your notes on it are kept in Notes.")) });
    if (!ok) return;
    try { await api("DELETE", `/api/projects/${P(project)}/documents/${P(d.doc_id)}${ok.why ? `?why=${encodeURIComponent(ok.why)}` : ""}`); toast("Document removed.", "ok"); await reloadDocs(); await App.refresh(); }
    catch (e) { showError(e); }
  }

  // ----------------------------------------------------------------- start over
  view.appendChild(h("details", { class: "fold section" }, h("summary", {}, "Start over or remove the project"),
    h("section", { class: "card danger-zone card-plain", "aria-label": "Start over", style: { marginTop: "8px" } },
      h("div", { class: "row", style: { justifyContent: "space-between" } },
        h("div", { class: "grow" }, h("strong", {}, "Remove all documents and results"), h("div", { class: "muted small" }, "Empties this project. Your settings and other projects stay.")),
        h("button", { class: "btn btn-outline-danger", type: "button", onClick: async () => {
          const ok = await confirmDialog({ title: "Remove every document and every result?", message: `This empties the project “${project}”. It cannot be undone.`, confirmText: "Remove everything", typeToConfirm: "remove" });
          if (!ok) return;
          try { await api("DELETE", `/api/projects/${P(project)}/documents`, { confirm: true }); toast("All documents and results removed.", "ok"); await reloadDocs(); await App.refresh(); } catch (e) { showError(e); }
        } }, icon("trash", { size: 14 }), "Remove everything")),
      h("hr"),
      h("div", { class: "row", style: { justifyContent: "space-between" } },
        h("div", { class: "grow" }, h("strong", {}, "Remove this project"), h("div", { class: "muted small" }, info.linked ? "The folder is unlinked and left untouched." : "The project is moved to a trash folder; nothing is deleted outright.")),
        h("a", { class: "btn btn-ghost", href: "#/projects" }, "Manage projects")))));

  await reloadDocs();
  // an ingest or index job already running for this project (started earlier, or in another tab)
  try {
    const jobs = (await api("GET", "/api/jobs")).jobs || [];
    const running = jobs.find((j) => j.project === project && (j.kind === "ingest") && !TERMINAL.has(j.state));
    if (running) followIngest(running.id, "Adding documents");
    const moving = jobs.find((j) => j.project === project && j.kind === "new_reader" && !TERMINAL.has(j.state));  // 0.15.7
    if (moving) followNr(moving.id);
    const indexing = jobs.find((j) => j.project === project && j.kind === "index" && !TERMINAL.has(j.state));
    if (indexing) {
      indexJob = indexing; drawIndex(lastSearch);   // the card says it runs, with the button off
      followIndex(indexing.id).catch(showError);
    }
  } catch (_) { /* ignore */ }
  return () => watchers.forEach((w) => w.stop());
}

// 0.15: how a document was read, in the list: one that read badly or has something to check (0.15.7: until the
// person marks the reading as checked), or one read by an earlier reader (0.15.7: also 0.15.0's; its link opens the
// preview of the move)
let newReader = 3;  // ingest.READER, as the list of documents says it
function readingNote(d) {
  const href = `#/doc/${encodeURIComponent(d.doc_id)}?tab=reading`;
  if ((d.reading_quality === "poor" || d.reading_quality === "fair") && !d.reading_checked) {
    return h("a", { class: d.reading_quality === "poor" ? "warn-chip it" : "it muted small", href, title: `${(d.reading_warnings || []).join(" ")} Open it to see where to look, then mark the reading as checked.`.trim() },
      icon(d.reading_quality === "poor" ? "alert-triangle" : "info", { size: 12 }), d.reading_quality === "poor" ? "read badly" : "something to check in its reading");
  }
  if ((d.reader || 1) < newReader) return h("a", { class: "it muted small", href: `${href}&preview=1`, title: "Read by an earlier reader of ENLENS. Open it to see what the new reader would change, or read several at once with the button above the list." },
    icon("layers", { size: 12 }), (d.reader || 1) < 2 ? "read before 0.15" : "read by an earlier reader");
  return null;
}

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
// 0.15: what each kind of block is called in the reading view (reader.KIND_TEXT), in the plural for counts
const KIND_PLURAL = { title: ["title", "titles"], heading: ["heading", "headings"], abstract: ["abstract paragraph", "abstract paragraphs"], body: ["paragraph", "paragraphs"],
  caption: ["caption", "captions"], table: ["table", "tables"], footnote: ["footnote", "footnotes"], front: ["part of the front matter (authors, publishing details)", "parts of the front matter (authors, publishing details)"],
  back: ["end note (acknowledgements, funding, licence)", "end notes (acknowledgements, funding, licence)"], references: ["part of the reference list", "parts of the reference list"],
  figure: ["piece of text inside a figure", "pieces of text inside figures"], furniture: ["running head or page number", "running heads and page numbers"],
  // 0.15.1 (reader 3)
  contents: ["line of the table of contents", "lines of the table of contents"], index: ["part of the index", "parts of the index"] };
// 0.15 (A0): how many results a move to the new reader places (reread.move's counts, per kind of result)
const movedCount = (r) => Object.values((r && r.counts) || {}).reduce((a, c) => a + (c.moved || 0), 0);
let keepPlace = null;               // 0.15: where the reader was before a block was restored or left out
const kindCount = (k, n) => `${fmt.num(n)} ${(KIND_PLURAL[k] || [k, k])[n === 1 ? 0 : 1]}`;
const WORD = /[\p{L}\p{N}_'’-]/u;
// a job this page started earlier (kept for this tab), if it is still running
async function stillRunning(key) {
  const j = session(key);
  if (!j || !j.id) return null;
  try { const job = await api("GET", `/api/jobs/${P(j.id)}`); if (!TERMINAL.has(job.state)) return j; } catch (_) { /* gone */ }
  session(key, null);
  return null;
}
const norm = (s) => String(s || "").replace(/\s+/g, " ").trim().toLowerCase();

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
    if (e.status === 404) { view.appendChild(emptyState("search-x", "No such document", "It was removed from the project.", h("a", { class: "btn", href: "#/sources" }, "Back to documents"))); return; }
    throw e;
  }
  const blocks = d.blocks || [];
  const totalBlocks = d.total_blocks ?? blocks.length;
  const reading = blocks.some((b) => b.kind);  // 0.15: read by the new reader: blocks that know what they are
  const hit = span ? blocks.findIndex((b) => span.start >= b.start && span.start < b.end) : -1;
  // the quote's text, for opening the original at it (the whole excerpt is too long for that)
  const quoteText = hit >= 0 && !span.whole ? (blocks[hit].text || "").slice(Math.max(0, span.start - blocks[hit].start), Math.max(0, span.end - blocks[hit].start)).trim() || null : null;
  const back = from ? h("a", { href: `#/h/${encodeURIComponent(from)}${query.card ? `?card=${encodeURIComponent(query.card)}` : ""}`, class: "btn btn-sm" }, icon("arrow-left", { size: 13 }), "Back to the result") : null;
  const watchers = [];
  const cleanups = [];
  let tab = DOC_TABS.some(([k]) => k === query.tab) ? query.tab : null;
  let framework = query.framework || App.settings().profile_framework || "sdg";

  // 0.13.3: the original and the highlighted copy are two quiet links on one line, as on the result page
  const copyBtn = h("button", { class: "link-btn it", type: "button", title: "A copy of the document with its quotes and labels highlighted", onClick: () => highlightedCopy() }, icon("highlighter", { size: 13 }), "Download a highlighted copy");
  view.appendChild(h("header", { class: "page-head" }, h("div", { class: "page-head-main" },
    h("p", { class: "eyebrow" }, from ? [back, " "] : null, h("a", { href: "#/sources", class: "it" }, icon("book-open", { size: 12 }), "All documents")),
    h("h1", { id: "page-title", tabindex: "-1", class: "serif", style: { fontWeight: 500 } }, d.title || d.file),
    h("div", { class: "result-meta", style: { marginTop: "6px" } }, h("span", {}, d.file), h("span", { class: "sep" }, "·"), h("span", {}, KIND_TEXT[d.kind] || d.kind || ""), d.n_pages ? [h("span", { class: "sep" }, "·"), h("span", {}, `${d.n_pages} pages`)] : null,
      reading ? (d.paragraphs ? [h("span", { class: "sep" }, "·"), h("span", {}, plural(d.paragraphs, "paragraph"))] : null)
        : d.n_pages && blockUnit(blocks[0]) === "pages" && totalBlocks === d.n_pages ? null : [h("span", { class: "sep" }, "·"), h("span", {}, `${totalBlocks} ${blockUnit(blocks[0])}`)], d.doi ? [h("span", { class: "sep" }, "·"), h("a", { href: `https://doi.org/${d.doi}`, target: "_blank", rel: "noopener noreferrer", title: "Opens the publisher's page in your browser" }, `doi ${d.doi}`)] : null,
      d.scanned ? [h("span", { class: "sep" }, "·"), h("span", { class: "it" }, icon("eye", { size: 12 }), d.scanned)] : null),
    d.bib ? h("p", { class: "dv-bib" }, icon("library", { size: 13 }), h("span", {}, "In your ", h("a", { href: "#/bibliography" }, "bibliography"), ": ", h("strong", {}, d.bib.cite || d.bib.title)),
      d.bib.title && d.bib.title !== d.title ? [h("span", { class: "sep" }, "·"), h("span", { class: "serif" }, d.bib.title)] : null,
      d.bib.doi && d.bib.doi !== d.doi ? [h("span", { class: "sep" }, "·"), h("a", { href: `https://doi.org/${d.bib.doi}`, target: "_blank", rel: "noopener noreferrer" }, `doi ${d.bib.doi}`)] : null,
      d.bib.link ? [h("span", { class: "sep" }, "·"), h("a", { href: d.bib.link }, "Open in Zotero")] : null) : null,
    // 0.13.3: the heading is the work's title; the one read from the file stays visible, on a line of its own
    d.file_title ? h("p", { class: "muted small dv-file-title", style: { margin: "4px 0 0" } }, "Title in the file: ", h("span", { class: "serif" }, d.file_title)) : null,
    h("div", { class: "row dv-head-row", style: { marginTop: "8px", gap: "8px 14px" } },
      originalLink(project, docId, hit >= 0 ? blocks[hit].page : null, d.kind, { info: d.original || undefined, quote: quoteText, text: d.kind === "pdf" ? (hit >= 0 && blocks[hit].page ? `Open the original PDF at page ${blocks[hit].page}` : "Open the original PDF") : quoteText ? "Open the original at the quote" : "Open the original" }),
      copyBtn),
    span ? h("p", { class: "muted small", style: { marginTop: "6px" } }, hit >= 0 ? (span.whole ? `The excerpt from the result is highlighted, in ${blocks[hit].label.toLowerCase()}.` : `The quote from the result is highlighted, in ${blocks[hit].label.toLowerCase()}.`) : "The quote could not be placed in this text.") : null)));

  // ----------------------------------------------------------------- the text, with layers of highlights
  const nodeAt = new WeakMap();        // text node -> document offset of its first character
  const rows = new Map();              // block n -> {row, b, sig}
  const loaded = [];                   // the blocks shown, in order
  const list = h("div", { class: "card doc-view dv-text" });
  const moreBox = h("div", { class: "dv-more" });
  const selBar = h("div", { class: "dv-selbar", role: "toolbar", "aria-label": "With the selected text", hidden: true });
  let focus = null;                    // the place jumped to last: {start, end, cls, extra: [decorations]}
  let docNotes = [];                   // 0.16 (F2): the notes and highlights on this document's words

  // 0.15 (A4): a document read by the new reader comes block by block, each knowing what it is. Headings, captions and
  // tables look like what they are, a page mark stands where a page begins, and what was left out of the text
  // (running heads, page numbers, front and back matter, footnotes, tables...) is folded under "Left out of the text",
  // each with Restore; every block that counts has Leave out.
  let fold = null, lastPage = null;
  // the label column: where the block is cited, a mark when a person changed it, and (on hover) its actions
  function labelParts(b) {
    return [b.label ? h("b", {}, b.label) : null,
      b.bound ? h("span", { class: "dv-mine" }, b.bound === "start" ? "the text starts here (you said)" : "the text ends here (you said)") : null,
      b.changed ? h("span", { class: "dv-mine" }, b.included ? "restored by you" : "left out by you") : null,
      b.kind === "table" && b.included === false && !b.changed ? h("span", { class: "dv-mine dv-muted" }, "left out") : null,
      reading ? blockActions(b) : null];
  }
  function addBlocks(bs) {
    for (const b of bs) {
      const body = h("div", { class: "dv-body" });
      const kindCls = b.kind ? ` dv-k-${b.kind}${b.included === false ? " dv-out" : ""}${b.changed ? " dv-changed" : ""}${b.joined ? " dv-joined" : ""}` : "";
      const label = h("div", { class: "pp" }, labelParts(b));
      const row = h("div", { class: "passage-row" + kindCls + (hit >= 0 && b.n === blocks[hit].n ? " hit" : "") }, label, body);
      row.id = `block-${b.n}`;
      rows.set(b.n, { row, body, label, b, sig: null });
      place(b, row, keptOpen);
      loaded.push(b);
    }
  }
  // where a block's row goes: after a page mark where a page begins; folded under "Left out of the text" when it is
  // left out (a table stays in the text, greyed), the fold open when what is left out is shown or `openNs` (blocks by
  // n) holds one of its blocks
  function place(b, row, openNs) {
    if (reading && b.page != null && b.page !== lastPage) {
      lastPage = b.page;
      fold = null;
      list.insertBefore(h("div", { class: "dv-page-mark", id: `page-${b.page}` }, h("span", {}, `Page ${b.page}`)), selBar);
    }
    if (reading && b.included === false && b.kind !== "table") {
      if (!fold) {
        fold = { el: h("details", { class: "dv-fold" }), kinds: new Map() };
        fold.sum = h("summary", {});
        fold.el.appendChild(fold.sum);
        if (showLeftOut) fold.el.open = true;
        list.insertBefore(fold.el, selBar);
      }
      if (openNs.has(b.n)) fold.el.open = true;
      fold.kinds.set(b.kind, (fold.kinds.get(b.kind) || 0) + 1);
      replace(fold.sum, icon("chevron-right", { size: 13 }), h("span", {}, "Left out of the text: ", [...fold.kinds].map(([k, n]) => kindCount(k, n)).join(", ")));
      fold.el.appendChild(row);
    } else {
      fold = null;
      list.insertBefore(row, selBar);
    }
  }
  let showLeftOut = !!session(`leftout:${docId}`);
  function blockActions(b) {
    const wrap = h("div", { class: "dv-act" });
    const where = b.label || `${b.kind_text || "text"}${b.page ? `, page ${b.page}` : ""}`;
    const btn = b.included === false
      ? h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": `Restore: ${where}`, title: "Count this in searches, codes, themes and checks again", onClick: (e) => setIncluded(b, true, e.currentTarget) }, icon("refresh", { size: 12 }), "Restore")
      : h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": `Leave out: ${where}`, title: b.kind === "heading" || b.kind === "title" ? "Leave this heading and the text under it out of searches, codes, themes and checks" : "Leave this out of searches, codes, themes and checks (a heading above it goes with it)", onClick: (e) => setIncluded(b, false, e.currentTarget) }, icon("minus", { size: 12 }), "Leave out");
    wrap.appendChild(btn);
    // 0.15.1: the same for every block that looks like this one (running heads, page numbers, a repeated label)
    if (b.alike > 0) wrap.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": `${b.included === false ? "Restore" : "Leave out"} all ${b.alike + 1} blocks like this: ${where}`,
      title: b.included === false ? `Restore this and the ${plural(b.alike, "other block")} that look the same (their numbers aside)` : `Leave out this and the ${plural(b.alike, "other block")} that look the same (their numbers aside), such as a running head on every page`,
      onClick: (e) => setIncluded(b, b.included === false, e.currentTarget, true) }, icon("copy", { size: 12 }), `All like this (${fmt.num(b.alike + 1)})`));
    // 0.15.1: where the document's own text starts and ends (a book's title pages before, its notes and index after)
    if (b.bound) wrap.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": `Undo: the text ${b.bound === "start" ? "starts" : "ends"} here`, title: "What was left out by this mark counts again, unless it was left out for another reason", onClick: (e) => setBound(b.bound, null, e.currentTarget) }, icon("x", { size: 12 }), b.bound === "start" ? "Undo start" : "Undo end"));
    else if (b.included !== false && b.share != null) {
      if (b.share <= 0.34) wrap.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": `The text starts here: ${where}`, title: "Leave out everything before this (title pages, publishing details, contents). Anything you restore there still counts.", onClick: (e) => setBound("start", b.n, e.currentTarget) }, icon("chevron-down", { size: 12 }), "Text starts here"));
      if (b.share >= 0.66) wrap.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": `The text ends here: ${where}`, title: "Leave out everything after this (notes, bibliography, index, about the author). Anything you restore there still counts.", onClick: (e) => setBound("end", b.n, e.currentTarget) }, icon("chevron-up", { size: 12 }), "Text ends here"));
    }
    if (b.table) wrap.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": `Download table ${b.table.n} for Excel`, title: "The table's rows and cells, for Excel", onClick: () => download(`${docBase}/tables/${b.table.n}.xlsx`).catch(showError) }, icon("download", { size: 12 }), "Excel"));
    return wrap;
  }
  // 0.16: Restore, Leave out and where the text starts or ends change the reading where it is. Before, the whole
  // document was drawn again: the page flashed and it was hard to tell what had happened. Now what leaves the text
  // greys and folds away into the line "Left out of the text", what comes back joins the text again, and the rest of
  // the page stays where it was.
  let turn = Promise.resolve();   // one change at a time, in the order clicked: a click during another waits for it
  const inTurn = (job) => { turn = turn.catch(() => {}).then(job); return turn; };
  function setIncluded(b, included, btn, alike = false) {
    btn.disabled = true;
    return inTurn(() => changeIncluded(b, included, btn, alike));
  }
  async function changeIncluded(b, included, btn, alike) {
    const hadFocus = list.contains(document.activeElement);
    const r0 = rows.get(b.n);
    const greyNow = !included && r0 && r0.row.parentElement === list && b.kind !== "table";
    if (greyNow) r0.row.classList.add("dv-leaving");  // at once: the answer from the app follows
    let r;
    try { r = await api("PUT", `${docBase}/blocks/${b.n}`, alike ? { included, alike: true } : { included }); }
    catch (e) { btn.disabled = false; if (greyNow) r0.row.classList.remove("dv-leaving"); showError(e); return; }
    const folded = await showChange(r, b, hadFocus);
    // where it went, when it folded away out of sight
    const away = (them) => (!included && folded ? ` ${them ? "They are" : "It is"} folded under “Left out of the text”, where Restore brings ${them ? "them" : "it"} back.` : "");
    if (alike) {
      toast(`${included ? "Restored" : "Left out"}: ${plural(r.alike || 1, "block")} like this${(r.together || 0) > (r.alike || 0) ? `, with ${plural(r.together - r.alike, "block")} read together with them` : ""}. Searches, codes, themes and checks ${included ? "read them again" : "will not read them"}.${away(true)}`, "ok");
      return;
    }
    // what went with it (its passage), and blocks elsewhere with the same words (the choice is kept by the words)
    const group = new Set(r.group || (r.blocks || []).map((x) => x.n));
    const others = (r.blocks || []).filter((x) => x.n !== b.n && group.has(x.n));
    const same = (r.blocks || []).filter((x) => !group.has(x.n) && (x.included !== false) === included).length;
    const elsewhere = same ? ` So ${same === 1 ? "is" : "are"} ${plural(same, "block")} elsewhere with the same words.` : "";
    const heads = others.filter((x) => x.kind === "heading" || x.kind === "title").map((x) => `“${x.text.length > 60 ? x.text.slice(0, 57) + "…" : x.text}”`);
    const rest = others.length - heads.length;
    const withWhat = [heads.length ? `${heads.length > 1 ? "its headings" : "its heading"} ${heads.join(" and ")}` : null,
      rest ? `${plural(rest, "paragraph")} next to it (they are read as one passage)` : null].filter(Boolean).join(" and ");
    toast(included ? `Restored${withWhat ? `, together with ${withWhat}` : ""}. Searches, codes, themes and checks read ${others.length ? "them" : "it"} again.${elsewhere}`
      : `Left out${withWhat ? `, together with ${withWhat}` : ""}. Searches, codes, themes and checks will not read ${others.length ? "them" : "it"}.${away(others.length > 0)}${elsewhere}`, "ok");
  }
  // 0.15.1: where the text starts or ends (block null: no longer)
  function setBound(side, n, btn) {
    btn.disabled = true;
    return inTurn(() => changeBound(side, n, btn));
  }
  async function changeBound(side, n, btn) {
    const hadFocus = list.contains(document.activeElement);
    const at = rows.get(Number(btn.closest(".passage-row").id.slice(6)));   // the block whose button was pressed
    let r;
    try { r = await api("PUT", `${docBase}/bounds`, { side, block: n }); }
    catch (e) { btn.disabled = false; showError(e); return; }
    await showChange(r, at ? at.b : null, hadFocus);
    const what = side === "start" ? "before it" : "after it";
    toast(n == null ? `Undone: ${r.restored ? `${plural(r.restored, "block")} ${what.replace("it", "that mark")} count${r.restored === 1 ? "s" : ""} again` : "nothing else changed"}.`
      : `The text ${side === "start" ? "starts" : "ends"} here: ${r.left_out ? `${plural(r.left_out, "block")} ${what} left out, folded under “Left out of the text”` : "nothing more to leave out"}. Searches, codes, themes and checks read only the text.`, "ok");
  }
  const calm = () => !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const pause = (ms) => new Promise((ok) => setTimeout(ok, calm() ? 0 : ms));
  // whether a row is shown (not in a closed fold), and where it is seen: the row itself or the line of its fold
  const isShown = (row) => { const f = row.closest("details.dv-fold"); return !f || f.open; };
  const shownBox = (row) => (!row.isConnected ? null : isShown(row) ? row : row.closest("details.dv-fold").querySelector(":scope > summary"));
  const onScreen = (el) => { const q = el && el.getBoundingClientRect(); return !!q && q.height > 0 && q.bottom > 0 && q.top < window.innerHeight; };
  // the height of a fold's line "Left out of the text" with its margins: what a row that folds away shrinks to
  function foldLineHeight() {
    const probe = h("details", { class: "dv-fold", style: { visibility: "hidden" } }, h("summary", {}, icon("chevron-right", { size: 13 }), h("span", {}, "Left out of the text")));
    list.insertBefore(probe, selBar);
    const cs = getComputedStyle(probe);
    const px = probe.getBoundingClientRect().height + (parseFloat(cs.marginTop) || 0) + (parseFloat(cs.marginBottom) || 0);
    probe.remove();
    return px;
  }
  // Show what the app changed (`res.blocks`: the blocks as they are now, `res.doc`: the reading's figures) in place.
  // `clicked`: the block whose button was pressed. Returns whether a block that was on the screen folded away.
  async function showChange(res, clicked, hadFocus) {
    const now = new Map((res.blocks || []).map((x) => [x.n, x]));
    const folds = (b) => b.included === false && b.kind !== "table";   // a left-out table stays in the text
    // which fold each left-out block will be in (named by its first block), laid out as place() will lay them out,
    // and which of those will be open: shown, or holding a block whose fold is open now
    const key = new Map();
    let k = null, page;
    for (const b of loaded) {
      if (b.page != null && b.page !== page) { page = b.page; k = null; }
      if (folds(now.get(b.n) || b)) { if (k == null) k = b.n; key.set(b.n, k); } else k = null;
    }
    const openNow = () => {
      const ns = new Set();
      for (const f of list.querySelectorAll("details.dv-fold[open]")) for (const x of f.querySelectorAll(":scope > .passage-row")) ns.add(Number(x.id.slice(6)));
      return ns;
    };
    const openNs = openNow();
    const openKeys = new Set([...key].filter(([n]) => openNs.has(n)).map(([, f]) => f));
    const foldedBefore = new Set();   // folds that hold a block folded already (their line is there now)
    for (const [n, f] of key) if (folds(rows.get(n).b)) foldedBefore.add(f);
    const going = [], coming = [];
    for (const [n, x] of now) {
      const r = rows.get(n);
      if (!r) continue;   // not drawn yet: it comes as it now is with the rest of the document
      if (!folds(r.b) && folds(x)) going.push(r);
      else if (folds(r.b) && !folds(x)) coming.push(r);
    }
    // 1. what leaves the text and is on the screen greys
    const seen = going.filter((r) => onScreen(r.row));
    for (const r of seen) r.row.classList.add("dv-leaving");
    if (seen.length) await pause(200);
    // 2. and folds away, into the line "Left out of the text" that takes its place (unless that fold is shown open):
    // a fold's first block shrinks to the line, the others to nothing; a block joining a fold already there, to nothing
    const folding = seen.filter((r) => !showLeftOut && !openKeys.has(key.get(r.b.n)));
    if (folding.length) {
      const line = foldLineHeight();
      for (const r of folding) r.row.style.height = `${r.row.getBoundingClientRect().height}px`;
      void list.offsetHeight;   // the heights above are where the shrinking starts
      for (const r of folding) {
        const f = key.get(r.b.n);
        r.row.classList.add("dv-folding");
        r.row.style.height = `${f === r.b.n && !foldedBefore.has(f) ? line : 0}px`;
      }
      await pause(280);
    }
    // 3. the rows as they are now, laid out again; the row just above the first change on the screen (or, when that
    // row is not on the screen, the first unchanged row that is) stays where it is, so a change above the screen
    // moves nothing
    const changed = (n) => now.has(n);
    const rowOf = (b) => rows.get(b.n).row;
    let anchor = null;
    const firstSeen = loaded.findIndex((b) => changed(b.n) && onScreen(shownBox(rowOf(b))));
    for (let i = firstSeen - 1; i >= 0 && !anchor; i--) if (!changed(loaded[i].n) && isShown(rowOf(loaded[i]))) anchor = rowOf(loaded[i]);
    if (anchor && anchor.getBoundingClientRect().bottom < 0) anchor = null;   // far above: changes in between would move the screen
    if (!anchor) { const b = loaded.find((x) => !changed(x.n) && isShown(rowOf(x)) && onScreen(rowOf(x))); if (b) anchor = rowOf(b); }
    const top0 = anchor ? anchor.getBoundingClientRect().top : 0;
    for (const [n, x] of now) {
      const r = rows.get(n);
      if (!r) continue;
      Object.assign(r.b, x);
      r.row.classList.toggle("dv-out", r.b.included === false);
      r.row.classList.toggle("dv-changed", !!r.b.changed);
      replace(r.label, labelParts(r.b));
    }
    const openThen = openNow();   // as they are now: a fold opened or closed during the animation stays so
    for (const el of [...list.children]) if (el !== selBar) el.remove();
    fold = null; lastPage = null;
    for (const b of loaded) place(b, rows.get(b.n).row, openThen);
    for (const el of list.querySelectorAll(".dv-leaving, .dv-folding")) { el.classList.remove("dv-leaving", "dv-folding"); el.style.height = ""; }
    if (anchor) {
      const dy = anchor.getBoundingClientRect().top - top0;
      if (Math.abs(dy) >= 1) window.scrollBy(0, dy);
    }
    // 4. a short glow where it went: the fold's line, or the row itself when it is in view
    const glow = new Set();
    for (const r of [...seen, ...coming]) { const el = shownBox(r.row); if (el && onScreen(el)) glow.add(el); }
    for (const el of glow) { el.classList.remove("dv-glow"); void el.offsetWidth; el.classList.add("dv-glow"); setTimeout(() => el.classList.remove("dv-glow"), 1700); }
    // the keyboard stays where the change happened: on the block's first action, or the line of the fold it went into
    if (hadFocus && clicked && rows.get(clicked.n) && !list.contains(document.activeElement)) {
      const el = shownBox(rows.get(clicked.n).row);
      const to = el && (el.tagName === "SUMMARY" ? el : el.querySelector(".dv-act button"));
      if (to) to.focus({ preventScroll: true });
    }
    // the reading's figures, the page beside the text, and the panels that depend on what counts
    Object.assign(d, res.doc || {});
    for (const p of Object.values(panels)) if (p.live) Promise.resolve(p.live()).then(paint, () => {});
    const mine = clicked && rows.get(clicked.n);
    return !!mine && !isShown(mine.row);
  }
  // 0.15: after a move to the new reader, the folds holding what changed stay open
  const keptOpen = new Set(keepPlace && keepPlace.doc === docId ? keepPlace.open || [] : []);
  list.appendChild(selBar);
  addBlocks(blocks);

  function drawMore() {
    clear(moreBox);
    if (loaded.length >= totalBlocks) return;
    moreBox.appendChild(h("button", { class: "btn btn-sm", type: "button", onClick: (e) => { e.currentTarget.disabled = true; loadMore().then(() => paint()); } }, icon("chevron-down", { size: 13 }),
      reading ? `Show the rest of the document (${fmt.num(totalBlocks - loaded.length)} more parts)` : `Show the rest of the document (${fmt.num(totalBlocks - loaded.length)} more ${blockUnit(blocks[0])})`));
  }
  async function loadMore() {
    if (loaded.length >= totalBlocks) return false;
    let r;
    try { r = await api("GET", `${docBase}?view=blocks&offset=${loaded.length}&limit=500`); } catch (e) { showError(e); return false; }
    const bs = r.blocks || [];
    if (!bs.length) return false;
    addBlocks(bs);
    drawMore();
    return true;
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
    return b.text.slice(s - b.start, e - b.start);
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
  function paint() {
    const all = decorations();
    for (const b of loaded) {
      const r = rows.get(b.n);
      const mine = all.filter((x) => x.start < b.end && x.end > b.start);
      const sig = mine.map((x) => `${x.start}-${x.end}-${x.cls}-${x.term || ""}-${x.note || ""}`).join("|");
      if (r.sig === sig) continue;
      r.sig = sig;
      replace(r.body, blockText(b, mine));
    }
  }
  // A block's text cut at its headings (as blockNode does), each piece under the decorations that cover it.
  function blockText(b, decos) {
    const text = b.text || "";
    if (b.table && !decos.length) {
      const rowsT = b.table.rows || [];
      return h("div", { class: "dv-table-wrap" }, h("table", { class: "dv-table" },
        rowsT.length ? h("thead", {}, h("tr", {}, rowsT[0].map((c) => h("th", { scope: "col" }, c)))) : null,
        h("tbody", {}, rowsT.slice(1).map((r) => h("tr", {}, r.map((c) => h("td", {}, c)))))));
    }
    const breaks = (b.headings || []).map((x) => ({ at: x.at, end: x.end, kind: "heading" }));
    const segs = breakSegments(text, breaks);
    const fill = (el, s0, s1) => {
      const cuts = new Set([s0, s1]);
      for (const x of decos) { const a = x.start - b.start, z = x.end - b.start; if (a > s0 && a < s1) cuts.add(a); if (z > s0 && z < s1) cuts.add(z); }
      const pts = [...cuts].sort((p, q) => p - q);
      for (let i = 0; i < pts.length - 1; i++) {
        const a = pts[i], z = pts[i + 1];
        const on = decos.filter((x) => x.start - b.start < z && x.end - b.start > a);
        const t = document.createTextNode(text.slice(a, z));
        nodeAt.set(t, b.start + a);
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
    const fold = r.row.closest("details");
    if (fold) fold.open = true;  // 0.15: a place in text that was left out
    const target = r.row.querySelector(".dv-focus, .dv-focus-soft") || r.row;
    target.scrollIntoView({ block: "center", behavior: opts.instant ? "auto" : "smooth" });
    r.row.classList.remove("ev-flash"); void r.row.offsetWidth; r.row.classList.add("ev-flash");
    setTimeout(() => r.row.classList.remove("ev-flash"), 1700);
  }

  // where a click or a selection is, as a document offset
  function docOffset(node, offset, isEnd) {
    if (node.nodeType === Node.TEXT_NODE) { const o = nodeAt.get(node); return o === undefined ? null : o + offset; }
    const walker = document.createTreeWalker(list, NodeFilter.SHOW_TEXT);
    const ref = node.childNodes[offset] || null;
    let t = null;
    if (isEnd) {
      if (ref) { walker.currentNode = ref; t = walker.previousNode(); }
      else { let last = node; while (last.lastChild) last = last.lastChild; t = last.nodeType === Node.TEXT_NODE ? last : (walker.currentNode = last, walker.previousNode()); }
      return t && nodeAt.has(t) ? nodeAt.get(t) + t.length : null;
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
    let i = off - b.start;
    if (!WORD.test(t[i] || "")) { if (i > 0 && WORD.test(t[i - 1])) i--; else return null; }
    let s = i, e = i + 1;
    while (s > 0 && WORD.test(t[s - 1])) s--;
    while (e < t.length && WORD.test(t[e])) e++;
    while (s < e && /['’-]/.test(t[s])) s++;
    while (e > s && /['’-]/.test(t[e - 1])) e--;
    return e > s ? { start: b.start + s, end: b.start + e, text: t.slice(s, e) } : null;
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
      const act = (ic, label, fn) => h("button", { class: "btn btn-sm btn-ghost", type: "button", onMousedown: (e) => e.preventDefault(), onClick: () => { const x = selNow; selBar.hidden = true; fn(x); } }, icon(ic, { size: 13 }), label);
      replace(selBar,
        // 0.16 (F2): keep the words, plainly or with a note of yours
        act("highlighter", "Highlight", (x) => addNote(x, "", "yellow")),
        act("note", "Note", (x) => noteDialog(x)),
        act("text-search", "Search in this document", (x) => { openTab("search"); panels.search.searchFor(x.text.split(" ").length > 1 ? `"${x.text}"` : x.text); }),
        x0(s) ? act("link", "Every mention of this", (x) => { openTab("refs"); panels.refs.lookup(x); }) : null,
        act("tag", "Label it with a code", (x) => { openTab("codes"); panels.codes.labelSelection(x); }));
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
    const ta = h("textarea", { class: "input", rows: 4, maxlength: 10000, placeholder: "What these words mean for your work…" });
    const body = h("div", {}, h("blockquote", { class: "note-quote" }, x.text),
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Your note"), ta),
      h("div", { class: "field" }, h("span", { class: "field-label" }, "Colour"), colourPicker(colour, (c) => { colour = c; })));
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { const b = ta.closest("dialog").querySelector(".btn-primary"); if (b) b.click(); } });
    const r = await dialog({ title: "Add a note", body, actions: [{ text: "Cancel", value: null }, { text: "Keep the note", value: true, primary: true }], onOpen: () => ta.focus() });
    if (r) await addNote(x, ta.value.trim(), colour);
  }
  function showNoteBar(n, rect) {
    selNow = null;
    const act = (ic, label, fn, cls) => h("button", { class: "btn btn-sm btn-ghost" + (cls ? " " + cls : ""), type: "button", onClick: () => { selBar.hidden = true; fn(); } }, icon(ic, { size: 13 }), label);
    replace(selBar,
      h("div", { class: "dv-notebar-text" }, n.text ? n.text : h("span", { class: "muted" }, n.mine ? "A highlight (no note)" : `A highlight by ${n.who}`), n.mine ? null : h("span", { class: "muted small" }, ` · ${n.who}`)),
      h("div", { class: "dv-notebar-actions" },
        n.mine ? act("note", n.text ? "Edit" : "Add a note", async () => { const got = await editNote(n); if (got) { Object.assign(n, got); paint(); if (panels.notes) panels.notes.refresh(); } }) : null,
        act("flask", "Use as evidence", () => useAsEvidence(n)),
        n.mine ? act("trash", "Remove", async () => { if (await removeNote(n)) { docNotes = docNotes.filter((x) => x.note_id !== n.note_id); paint(); if (panels.notes) panels.notes.refresh(); } }, "danger-link") : null));
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
  const tabsRow = h("div", { class: "btn-row dv-tabs", role: "group", "aria-label": "Show next to the text" });
  const panelBox = h("div", { class: "dv-panel-box" });
  const intro = h("p", { class: "muted small dv-intro" }, "Show next to the text: which codes of a codebook it addresses, its key terms, what “it” and “they” refer to, search inside it, how it was read", d.page_images ? ", or the page of the original beside the text." : ".");
  const side = h("aside", { class: "dv-side", "aria-label": "About this document" }, tabsRow, panelBox);
  const layout = h("div", { class: "dv-layout" }, side, h("div", { class: "dv-main" }, list, moreBox));
  view.appendChild(layout);

  const panels = {};
  const makers = { codes: codesPanel, terms: termsPanel, refs: refsPanel, search: searchPanel, notes: notesPanel, reading: readingPanel, page: pagePanel };
  function drawTabs() {
    replace(tabsRow, DOC_TABS.filter(([k]) => k !== "page" || d.page_images).map(([k, label, ic]) => h("button", { class: "btn btn-sm seg-btn" + (tab === k ? " seg-on" : ""), type: "button", "aria-pressed": tab === k ? "true" : "false", dataset: { tab: k },
      onClick: () => { openTab(tab === k ? null : k); const b = tabsRow.querySelector(`[data-tab="${k}"]`); if (b) b.focus(); } }, icon(ic, { size: 13 }), label)));
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

  // ---- 0.15: how the document was read (A5), and moving it to the new reader (A0)
  function readingPanel() {
    const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-read-h" });
    const rep = d.reading || {};
    const older = (d.reader || 1) < (d.new_reader || 1);
    const before15 = (d.reader || 1) < 2;  // 0.15.1: a document of 0.15.0's reader has a reading report too
    const qual = { good: ["circle-check", "Read well."], fair: ["alert-triangle", "Read, with something to check."], poor: ["alert-circle", "Read badly: check it before you rely on it."] }[rep.quality];
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
      showLeftOut = on; session(`leftout:${docId}`, showLeftOut || null);
      for (const f of list.querySelectorAll("details.dv-fold")) f.open = showLeftOut;
    };
    let outBox = null;
    const outPart = h("div", { class: "dv-outkinds" });
    function live() {
      replace(passFig, h("span", { class: "muted" }, "Passages that count:"), " ", `${fmt.num(d.passages_read || 0)} of ${fmt.num(d.passages_all || 0)}`);
      const kinds = outKinds();
      outPart.hidden = !kinds.length;
      outBox = kinds.length ? h("input", { type: "checkbox", checked: showLeftOut, onChange: (e) => setLeftOut(e.currentTarget.checked) }) : null;
      replace(outPart, kinds.length ? [h("p", { class: "small", style: { margin: "8px 0 4px" } }, h("strong", {}, "Left out of the text: "), kinds.map(([k, n]) => kindCount(k, n)).join(", "), "."),
        h("p", { class: "muted small", style: { margin: "0 0 6px" } }, "They stay in the document and in a search of all its text, but searches, codes, themes and checks do not read them. Restore any that should count; leave out any that should not."),
        h("label", { class: "dv-check" }, outBox, h("span", {}, "Show what was left out in the text"))] : []);
    }
    // 0.15.7: a warning's way to what it is about: the pages of the original, or what the reader set aside
    const showOut = () => {
      if (outBox) outBox.checked = true;
      setLeftOut(true);
      const f = list.querySelector("details.dv-fold");
      if (f) f.scrollIntoView({ block: "center", behavior: "smooth" });
    };
    const placeBtn = (place) => place === "page" && d.page_images ? h("button", { class: "link-btn small", type: "button", onClick: () => openTab("page") }, icon("file-text", { size: 12 }), "Look at the pages")
      : place === "left_out" && outKinds().length ? h("button", { class: "link-btn small", type: "button", onClick: showOut }, icon("eye", { size: 12 }), "Show what was left out") : null;
    el.append(...[h("h2", { id: "dv-read-h", class: "dv-panel-title", tabindex: "-1" }, "How this document was read"),
      older ? h("div", { class: "notice notice-info" }, icon("info"), h("div", {},
        h("p", {}, before15 ? `Read by the reader of ENLENS before 0.15. ENLENS ${App.state.version || ""} has a new reader: it reads two columns in the right order, sets running heads, page numbers, author details, acknowledgements and the like aside, keeps tables as tables and repairs words broken over lines.`
          : `Read by the reader of ENLENS 0.15.0. The reader of ENLENS ${App.state.version || ""} also sets running heads, page numbers, contents pages and indexes aside in text files and books, finds their headings and paragraphs, and puts apart words that ran together.`),
        h("p", { class: "small" }, "Documents already in a project keep their reading, so every quote and judgement in them stays where it is, until you move one over."))) : null,
      !before15 && qual ? h("p", { class: `dv-quality dv-q-${rep.quality}` }, icon(qual[0], { size: 14 }), qual[1]) : null,
      (rep.warnings || []).length ? h("ul", { class: "dv-warn" }, rep.warnings.map((w, i) => h("li", {}, w, " ", placeBtn((rep.places || [])[i])))) : null,
      !before15 && (rep.quality === "fair" || rep.quality === "poor") ? checkedBox(rep) : null,
      figs.length ? h("ul", { class: "dv-figs" }, figs) : null,
      outPart,
      older ? rereadBox() : null].filter(Boolean));  // append(null) would write "null"
    live();
    return { el, live };
  }

  // 0.15.7: the person looked at what the reading report names and marks the reading as checked (or takes it
  // back): the note in the list of documents goes away; a new reading of the document asks again
  function checkedBox(rep) {
    const box = h("div", { class: "dv-checked" });
    function draw() {
      const c = rep.checked;
      replace(box, c ? h("p", { class: "small", style: { margin: "4px 0 8px" } }, icon("circle-check", { size: 13 }),
        ` Checked by ${c.name || "you"}${c.at ? ` on ${fmt.dateShort(c.at)}` : ""}: the list of documents no longer asks for a look. `,
        h("button", { class: "link-btn small", type: "button", onClick: (e) => mark(false, e.currentTarget) }, "Undo"))
        : [h("p", { class: "muted small", style: { margin: "4px 0 6px" } }, "Look at what each point names. If the text is good enough for your work, mark the reading as checked: the note in the list of documents goes away. A new reading of this document asks again."),
          h("button", { class: "btn btn-sm", type: "button", onClick: (e) => mark(true, e.currentTarget) }, icon("check", { size: 13 }), "Checked: it reads well enough")]);
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
  function rereadBox() {
    const box = h("div", { class: "dv-reread" });
    function drawStart(focusIt) {
      const start = h("button", { class: "btn btn-sm btn-primary", type: "button", onClick: (e) => preview(e.currentTarget) }, icon("layers", { size: 13 }), "Read with the new reader");
      replace(box, h("p", { class: "small", style: { margin: "10px 0 6px" } }, "See first what would change: how many of your results find their place in the new reading, and which do not. Nothing changes until you confirm."), start);
      if (focusIt) start.focus();
      return start;
    }
    async function preview(start) {
      start.disabled = true;
      replace(box, h("p", { class: "muted small", role: "status" }, icon("loader", { size: 13 }), " Reading the original file again (nothing changes yet)…"));
      let r;
      try { r = await api("GET", `${docBase}/reread`); }
      catch (e) { replace(box, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, e.message))); return; }
      if (r.ok === false) { replace(box, h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("p", {}, r.reason || "This document cannot be read again now."))); return; }
      const lost = r.not_placed || [];
      const moved = movedCount(r);
      const aside = Array.isArray(r.left_out) ? r.left_out : [];  // placed, in text the new reader leaves out
      const go = h("button", { class: "btn btn-sm btn-primary", type: "button", onClick: () => move(go) }, icon("check", { size: 13 }), "Move it to the new reader");
      const summary = h("p", { class: "small", tabindex: "-1" }, moved || lost.length ? [h("strong", {}, plural(moved, "result")), moved === 1 ? " finds its place" : " find their place", " in the new reading", lost.length ? [", ", h("strong", {}, `${fmt.num(lost.length)} ${lost.length === 1 ? "does" : "do"} not`)] : "", "."]
        : "Nothing in your results points into this document yet: it is simply read again.");
      replace(box, h("div", { class: "dv-reread-preview" }, summary,
        (r.warnings || []).length ? h("ul", { class: "dv-warn", style: { marginTop: "6px" } }, r.warnings.map((w) => h("li", {}, w))) : null,
        lost.length ? h("ul", { class: "dv-lost" }, lost.slice(0, 12).map((x) => h("li", { class: "small" }, h("span", { class: "muted" }, `${cap(x.kind_text || x.what || "a result")}${x.page ? `, page ${x.page}` : ""}: `),
          x.quote ? `“${x.quote}”` : (x.what || ""), x.why ? h("span", { class: "muted" }, ` ${x.why}`) : null))) : null,
        lost.length > 12 ? h("p", { class: "muted small" }, `and ${fmt.num(lost.length - 12)} more.`) : null,
        aside.length ? h("ul", { class: "dv-lost" }, aside.slice(0, 12).map((x) => h("li", { class: "small" }, h("span", { class: "muted" }, `${cap(x.kind_text || "a result")}${x.page ? `, page ${x.page}` : ""}: `),
          x.quote ? `“${x.quote}”` : (x.what || ""), x.note ? h("span", { class: "muted" }, ` ${x.note}`) : null))) : null,
        r.reading && r.reading.quality ? h("p", { class: "muted small" }, `The new reading: ${plural(r.reading.body_passages, "passage")} that count${(r.reading.warnings || []).length ? `; ${r.reading.warnings.join(" ")}` : ", nothing to warn about."}`) : null,
        h("div", { class: "btn-row", style: { marginTop: "8px" } }, go, h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => drawStart(true) }, "Not now"))));
      summary.focus();
    }
    async function move(btn) {
      btn.disabled = true;
      let job;
      try { job = (await api("POST", `${docBase}/reread`)).job; }
      catch (e) { btn.disabled = false; showError(e); return; }
      // the move is one step; then, as after adding a document, its search by meaning, key terms and keyword codes
      replace(box, h("p", { class: "muted small", role: "status" }, icon("loader", { size: 13 }), " Moving it to the new reader, then updating its key terms and codes…"));
      const w = watchJob(job.id);
      watchers.push(w);
      let done;
      try { done = await w.promise; } catch (e) { showError(e); return; }
      if (done.state !== "done") { replace(box, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, done.error || "The document could not be moved; nothing was changed."))); return; }
      const r = (done.result || {}).report || {};
      toast(`Read with the new reader: ${plural(movedCount(r), "result")} moved${(r.not_placed || []).length ? `, ${fmt.num(r.not_placed.length)} without a place` : ""}.`, "ok");
      keepPlace = { doc: docId, y: 0, tab: "reading", focus: "dv-read-h" };
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    }
    const first = drawStart(false);
    if (query.preview === "1") setTimeout(() => preview(first), 0);  // 0.15.7: from the list of documents
    return box;
  }

  // ---- 0.15 (A4): the page of the original PDF beside the text, the blocks the reader found drawn on it
  function pagePanel() {
    const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-page-h" });
    const SCALE = 1.5;
    let page = null;
    const img = h("img", { class: "dv-page-img", alt: "" });
    const boxes = h("div", { class: "dv-page-boxes", "aria-hidden": "true" });
    const frame = h("div", { class: "dv-page-frame" }, img, boxes);
    const nav = h("div", { class: "btn-row dv-page-nav" });
    const note = h("p", { class: "muted small", style: { margin: "6px 0 0" } }, reading ? "Outlined: what the reader found. Solid: read by searches, codes, themes and checks; dashed: left out. Click one to go to it in the text."
      : "Outlines of what the reader found come with the new reader: see Reading.");
    el.append(h("h2", { id: "dv-page-h", class: "dv-panel-title" }, "The page"), nav, frame, note);
    function draw() {
      const last = d.n_pages || 1;
      replace(nav, h("button", { class: "btn btn-sm", type: "button", disabled: page <= 1, "aria-label": "Previous page", onClick: () => go(page - 1, true) }, icon("chevron-left", { size: 13 })),
        h("span", { class: "small" }, `Page ${page} of ${last}`),
        h("button", { class: "btn btn-sm", type: "button", disabled: page >= last, "aria-label": "Next page", onClick: () => go(page + 1, true) }, icon("chevron-right", { size: 13 })),
        h("a", { class: "btn btn-sm btn-ghost", href: `${docBase}/file?token=${encodeURIComponent(TOKEN)}#page=${page}`, target: "_blank", rel: "noopener" }, icon("external-link", { size: 12 }), "Open the PDF at this page"));
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
      if (tab !== "page" || !following) return;
      const vis = entries.filter((e) => e.isIntersecting).map((e) => rows.get(Number(e.target.id.slice(6)))).filter(Boolean);
      const first = vis.map((r) => r.b).filter((b) => b.page).sort((a, z) => a.start - z.start)[0];
      if (first) go(first.page, false);
    }, { rootMargin: "0px 0px -60% 0px" });
    for (const r of rows.values()) seen.observe(r.row);
    cleanups.push(() => seen.disconnect());
    go((hit >= 0 && blocks[hit].page) || (loaded[0] && loaded[0].page) || 1, false);
    return { el, live: drawBoxes };   // 0.16: Restore and Leave out change the outlines (solid or dashed)
  }

  // ---- Codes (F2)
  function codesPanel() {
    const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-codes-h" });
    const head = h("div");
    const jobBox = h("div", { hidden: true });
    const aiBox = h("div");
    const addBox = h("div");
    const listBox = h("div", { "aria-live": "polite", "aria-busy": "false" });
    el.append(h("h2", { id: "dv-codes-h", class: "dv-panel-title" }, "Codes"), head, jobBox, addBox, listBox, aiBox);
    let prof = null, fws = null, codeItems = null, ai = null, aiFw = null;
    const open = new Set(query.code ? [query.code] : []);
    const all = new Set();      // codes whose every passage is shown
    let marks = [];             // the passages of the open codes, marked in the text
    const passages = new Map(); // passage_id -> Promise of {start, text}

    async function load() {
      listBox.setAttribute("aria-busy", "true");
      try { prof = await api("GET", `${docBase}/profile?framework=${encodeURIComponent(framework)}`); }
      catch (e) { listBox.setAttribute("aria-busy", "false"); replace(listBox, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, e.message))); return; }
      listBox.setAttribute("aria-busy", "false");
      // a goal from the profile grid (?code=7): open its targets
      for (const c of [...open]) if (!prof.codes.some((x) => x.code === c)) { open.delete(c); for (const x of prof.codes) if (x.group === c) open.add(x.code); }
      draw();
      refreshMarks();
    }

    function draw() {
      const fwName = prof.framework_title || framework;
      const label = prof.code_label || "code";
      const sel = h("select", { class: "select input-sm", id: "dv-fw" }, (fws || [{ name: framework, title: fwName }]).map((f) => h("option", { value: f.name, selected: f.name === framework }, f.title || f.name)));
      sel.addEventListener("change", async () => { framework = sel.value; open.clear(); keepUrl(); await load(); const again = document.getElementById("dv-fw"); if (again) again.focus(); });
      replace(head, h("div", { class: "dv-fw" }, h("label", { class: "field-label", for: "dv-fw" }, "Codebook"), sel));
      clear(listBox);
      const p1 = prof.pass1 || {};
      if (!p1.done) {
        clear(aiBox); ai = null;
        if (jobBox.hidden) listBox.appendChild(emptyState("tag", "No codes found yet", `The app first finds the ${label}s of “${fwName}” in every passage of the project by their keywords. It takes seconds and runs on this computer.`,
          h("button", { class: "btn btn-primary btn-sm", type: "button", onClick: (e) => startKeywordPass(project, framework, jobBox, watchers, (job) => { if (job.state === "done") jobBox.hidden = true; load(); }, e.currentTarget) }, icon("tag", { size: 13 }), "Find the codes by keywords")));
        return;
      }
      if (p1.stale && jobBox.hidden) listBox.appendChild(h("div", { class: "notice notice-warn", style: { marginBottom: "10px" } }, icon("alert-triangle"),
        h("div", {}, h("p", {}, "Documents were added or removed since the codes were found, so this profile may be out of date."),
          h("button", { class: "btn btn-sm", type: "button", style: { marginTop: "6px" }, onClick: (e) => startKeywordPass(project, framework, jobBox, watchers, (job) => { if (job.state === "done") jobBox.hidden = true; load(); }, e.currentTarget) }, icon("refresh", { size: 13 }), "Find them again"))));
      const codes = prof.codes || [];
      const labelled = new Set(codes.flatMap((c) => c.items.map((it) => it.passage_id))).size;
      const provisional = codes.some((c) => c.items.some((it) => it.provisional));
      listBox.appendChild(h("p", { class: "dv-sum" }, codes.length
        ? [h("strong", {}, `${plural(codes.length, label)}`), ` in ${plural(labelled, "passage")} of ${fmt.num(prof.passages)} (${Math.round((labelled / Math.max(1, prof.passages)) * 100)}%).`]
        : `No ${label} counts in this document yet.`));
      listBox.appendChild(h("p", { class: "muted small", style: { margin: "0 0 10px" } },
        prof.read_by_model ? `The AI has read ${plural(prof.read_by_model, "passage")} of this document. ` : "The AI has not read this document yet. ",
        provisional ? [h("span", { class: "chip chip-weak" }, "provisional"), " codes were found by keywords", p1.meaning_model ? " or meaning" : "", " and wait for the AI or you."] : ""));
      if (codes.length) {
        listBox.appendChild(h("ol", { class: "dv-codes" }, codes.map(codeNode)));
        listBox.appendChild(h("p", { class: "muted small" }, "Ranked by the number of passages. The strip shows where in the document each code occurs. Open a code to see its passages and why each was labelled."));
      }
      if (aiFw !== framework) {
        aiFw = framework;
        const key = `label-job:${project}:${docId}`;
        ai = aiLabelCard({ project, framework, docIds: [docId], watchers, compact: true, onStart: (id) => session(key, { id }), onEnd: () => load() });
        replace(aiBox, ai.el);
        stillRunning(key).then((j) => { if (j && ai) ai.follow(j.id); });
      }
    }

    function pagesText(pages, n) {
      const out = [];
      for (let i = 0; i < pages.length; i++) {
        let j = i;
        while (j + 1 < pages.length && pages[j + 1] === pages[j] + 1) j++;
        out.push(j > i ? `${pages[i]}–${pages[j]}` : String(pages[i]));
        i = j;
      }
      return `${pages.length === 1 ? "page" : "pages"} ${out.join(", ")}${n ? ` of ${n}` : ""}`;
    }

    function codeNode(c) {
      const isOpen = open.has(c.code);
      const n = prof.n_pages;
      const share = c.share < 0.01 ? "under 1%" : `${Math.round(c.share * 100)}%`;
      const allProv = c.items.every((it) => it.provisional);
      const ticks = n && c.pages.length ? c.pages.map((pg) => ((pg - 0.5) / n) * 100) : c.positions;
      const whereText = n && c.pages.length ? pagesText(c.pages, n) : `at ${c.positions.map((x) => `${x}%`).join(", ")} of the text`;
      const strip = h("div", { class: "dv-strip", role: "img", "aria-label": `Where: ${whereText}`, title: `Where: ${whereText}. Click to go there.`,
        onClick: (e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const x = ((e.clientX - r.left) / Math.max(1, r.width)) * 100;
          const pos = (it) => (n && it.page ? ((it.page - 0.5) / n) * 100 : it.position_pct || 0);
          const best = [...c.items].sort((a, b) => Math.abs(pos(a) - x) - Math.abs(pos(b) - x))[0];
          if (best) jumpItem(best);
        } }, ticks.map((t) => h("span", { class: "dv-tick", style: { left: `${Math.max(0, Math.min(100, t))}%` } })));
      const headBtn = h("button", { class: "dv-code-head", type: "button", "aria-expanded": isOpen ? "true" : "false", dataset: { code: c.code },
        onClick: () => { if (open.has(c.code)) open.delete(c.code); else open.add(c.code); draw(); refreshMarks(); const b = listBox.querySelector(`.dv-code-head[data-code="${CSS.escape(c.code)}"]`); if (b) b.focus(); } },
        h("span", { class: "dv-code-id" }, c.code),
        h("span", { class: "dv-code-main" }, h("span", { class: "dv-code-desc" }, c.description || c.code),
          h("span", { class: "dv-code-n" }, `${plural(c.passages, "passage")} · ${share} of the document`, c.main ? ` · main topic in ${c.main}` : "", allProv ? " · " : "", allProv ? h("span", { class: "chip chip-weak" }, "provisional") : null)),
        icon(isOpen ? "chevron-up" : "chevron-down", { size: 14 }));
      const li = h("li", { class: "dv-code" + (isOpen ? " dv-open" : "") }, headBtn, strip);
      if (isOpen) {
        const items = all.has(c.code) ? c.items : c.items.slice(0, 12);
        li.appendChild(h("ul", { class: "dv-items" }, items.map((it) => itemNode(c, it))));
        if (c.items.length > items.length) li.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { all.add(c.code); draw(); } }, icon("chevron-down", { size: 13 }), `Show all ${c.items.length} passages`));
      }
      return li;
    }

    function itemNode(c, it) {
      const chips = [h("span", { class: "chip" + (it.source === "person" ? " chip-yours" : "") }, SOURCE_WORDS[it.source] || it.source)];
      if (it.provisional) chips.push(h("span", { class: "chip chip-weak", title: "Found without the AI. It counts until the AI has read this passage (or you decide)." }, "provisional"));
      if (it.source === "model" || it.source === "person" || it.decision === "change") {
        if (it.relevance) chips.push(h("span", { class: "chip" }, RELEVANCE_WORDS[it.relevance] || it.relevance));
        if (prof.directional && it.direction && it.direction !== "not_stated") chips.push(h("span", { class: "chip" }, DIRECTION_WORDS[it.direction] || it.direction));
      }
      if (it.source === "model" && it.confidence !== null && it.confidence !== undefined) { const ce = certainty(it.confidence); chips.push(h("span", { class: `cert cert-${ce.word}`, title: ce.long }, `AI certainty: ${ce.word} (${Math.round(it.confidence * 100)}%)`)); }
      if (it.decision === "accept") chips.push(h("span", { class: "chip chip-yours" }, icon("check", { size: 12 }), "you agree"));
      else if (it.decision === "change") chips.push(h("span", { class: "chip chip-yours" }, icon("note", { size: 12 }), "changed by you"));
      const why = [];
      if (it.quote) why.push(h("p", { class: "dv-quote serif" }, h("mark", { class: "dv-code-mark" }, it.quote)));
      if (it.source === "model" && it.reason) why.push(h("p", { class: "dv-why" }, h("span", { class: "muted" }, "The AI's reason: "), it.reason));
      else if (it.source === "person") why.push(h("p", { class: "dv-why" }, h("span", { class: "muted" }, "Your note: "), it.reason || "added by you"));
      else {
        const bits = [];
        if ((it.matched || []).length) bits.push(h("span", {}, h("span", { class: "muted" }, "Matched words: "), it.matched.map((w, i) => [i ? ", " : "", h("b", {}, w)])));
        else if (it.reason && !it.similarity) bits.push(h("span", {}, it.reason));
        if (it.similarity !== null && it.similarity !== undefined) bits.push(h("span", {}, h("span", { class: "muted" }, bits.length ? " · close in meaning" : "Close in meaning to the code's text"), ` (similarity ${Number(it.similarity).toFixed(2)})`));
        why.push(h("p", { class: "dv-why found-words" }, it.source === "both" ? h("strong", {}, "Keywords and meaning agree. ") : null, bits));
      }
      if (it.note && it.source !== "person") why.push(h("div", { class: "user-note" }, icon("note", { size: 13 }), h("span", {}, h("span", { class: "muted" }, "Your note: "), it.note)));
      const where = h("button", { class: "link-btn dv-loc", type: "button", title: "Show it in the text", onClick: () => jumpItem(it) }, icon("eye", { size: 12 }), cap(it.location || (it.page ? `page ${it.page}` : "show in the text")));
      return h("li", { class: "dv-item" + (it.provisional ? " dv-prov" : "") + (it.decision ? " ev-yours" : ""), dataset: { lid: it.label_id } },
        h("div", { class: "dv-item-top" }, where, h("span", { class: "chips" }, chips)), why, decideRow(c, it));
    }

    // agree / change relevance or direction / reject, every decision with Undo
    function decideRow(c, it) {
      const put = async (body, msg) => {
        try {
          await api("PUT", `${base}/labels/${P(it.label_id)}`, body);
          toast(msg, "ok", { small: true, ttl: 8000, group: "label", button: { text: "Undo", onClick: async () => {
            try { await api("PUT", `${base}/labels/${P(it.label_id)}`, it.decision ? { decision: it.decision === "change" ? "change" : it.decision, relevance: it.decision === "change" ? it.relevance : undefined, direction: it.decision === "change" ? it.direction : undefined } : { decision: "clear" }); toast("Undone.", "ok", { small: true, ttl: 2500, group: "label" }); await load(); } catch (e) { showError(e); }
          } } });
          await load();
          const again = listBox.querySelector(`[data-lid="${CSS.escape(it.label_id)}"] button`) || listBox.querySelector(`.dv-code-head[data-code="${CSS.escape(c.code)}"]`);
          if (again) again.focus({ preventScroll: true });
        } catch (e) { showError(e); }
      };
      const row = h("div", { class: "judge-row dv-decide" });
      if (it.source === "person") {
        row.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => put({ decision: "reject" }, "Your label was removed.") }, icon("trash", { size: 13 }), "Remove my label"));
        return row;
      }
      const agreed = it.decision === "accept";
      row.appendChild(h("button", { class: "btn btn-sm" + (agreed ? " btn-primary" : ""), type: "button", "aria-pressed": agreed ? "true" : "false",
        onClick: () => (agreed ? put({ decision: "clear" }, "Your decision was cleared.") : put({ decision: "accept" }, it.provisional ? "Saved: you agree. The label now counts as yours." : "Saved: you agree with this label.")) },
        icon("check", { size: 13 }), agreed ? "You agree" : "Agree"));
      row.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => put({ decision: "reject" }, `Rejected: ${c.code} no longer counts for this passage.`) }, icon("x", { size: 13 }), "Reject"));
      // change: relevance and direction (where the codebook has one)
      const name = `dv-rel-${it.label_id}`;
      const radios = (nm, choices, current) => h("div", { class: "judge-opts", role: "radiogroup" }, choices.map(([v, t]) => {
        const input = h("input", { type: "radio", name: nm, value: v });
        input.checked = current === v;
        return h("label", { class: "judge-opt" }, input, h("span", {}, t));
      }));
      const rel = radios(name, [["main", "main topic"], ["mentioned", "mentioned"]], it.relevance || "main");
      rel.setAttribute("aria-label", "How much the passage is about this code");
      const dir = prof.directional ? radios(`${name}-d`, [["helps", "helps"], ["hinders", "hinders"], ["mixed", "mixed"], ["not_stated", "not stated"]], it.direction || "not_stated") : null;
      if (dir) dir.setAttribute("aria-label", "Direction");
      const note = h("input", { class: "input input-sm", type: "text", placeholder: "Optional note", value: it.decision === "change" ? (it.note || "") : "", "aria-label": "Your note on this label" });
      const save = h("button", { class: "btn btn-sm", type: "button", onClick: () => {
        const r = rel.querySelector("input:checked"), dd = dir && dir.querySelector("input:checked");
        put({ decision: "change", relevance: r ? r.value : undefined, direction: dd ? dd.value : undefined, note: note.value.trim() || undefined }, "Saved: your change to this label.");
      } }, "Save the change");
      const instead = h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "Reject this code here and choose the right one",
        onClick: async () => { await put({ decision: "reject" }, "This code is rejected here: choose the right one."); addForm({ passage_id: it.passage_id, where: it.location }); } },
        icon("plus", { size: 13 }), "Wrong code? Choose another instead");
      row.appendChild(h("details", { class: "fold judge-diff" }, h("summary", {}, it.decision === "change" ? "Your change · edit" : "Change how it applies"),
        h("div", { class: "judge-body" }, h("div", { class: "small muted" }, "How much is it about this code?"), rel,
          dir ? [h("div", { class: "small muted", style: { marginTop: "6px" } }, "Does the passage say it helps or hinders the aim?"), dir] : null,
          h("div", { class: "row", style: { marginTop: "8px", gap: "6px" } }, note, save),
          h("div", { style: { marginTop: "8px" } }, instead))));
      row.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => addForm({ passage_id: it.passage_id, where: it.location }) }, icon("plus", { size: 13 }), "Another code here"));
      return row;
    }

    async function passageOf(pid) {
      if (!passages.has(pid)) passages.set(pid, api("GET", `${base}/passages/${P(pid)}?around=0`).then((r) => (r.passages || []).find((x) => x.passage_id === pid) || null).catch(() => null));
      return passages.get(pid);
    }
    function wordMarks(text, startAt, words) {
      const out = [];
      for (const w of words || []) {
        const rx = new RegExp(`(?<![\\p{L}\\p{N}])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\p{L}\\p{N}])`, "giu");
        let mm;
        while ((mm = rx.exec(text))) out.push({ start: startAt + mm.index, end: startAt + mm.index + mm[0].length, cls: "dv-code-mark", mark: true });
      }
      return out;
    }
    async function jumpItem(it) {
      if (Number.isInteger(it.start) && Number.isInteger(it.end)) return jumpTo({ start: it.start, end: it.end });
      const p = await passageOf(it.passage_id);
      if (!p || !Number.isInteger(p.start)) { toast("This passage could not be placed in the text.", "warn"); return; }
      jumpTo({ start: p.start, end: p.start + (p.text || "").length }, { soft: true, extra: wordMarks(p.text || "", p.start, it.matched) });
    }

    // the passages of the open codes, marked in the text: quotes where the AI or you gave one, else the matched words
    let markSeq = 0;
    async function refreshMarks() {
      const my = ++markSeq;
      const out = [];
      for (const c of (prof && prof.codes) || []) {
        if (!open.has(c.code)) continue;
        const want = new Map();
        for (const it of c.items) {
          if (Number.isInteger(it.start) && Number.isInteger(it.end)) out.push({ start: it.start, end: it.end, cls: "dv-code-mark", mark: true });
          else if ((it.matched || []).length) want.set(it.passage_id, new Set(it.matched.map((w) => w.toLowerCase())));
        }
        if (!want.size) continue;
        const words = [...new Set([...want.values()].flatMap((s) => [...s]))].slice(0, 60);
        try {
          const r = await api("GET", `${base}/search?${new URLSearchParams({ q: words.join(" "), docs: docId, code: `${framework}:${c.code}`, limit: "1000", width: "20" })}`);
          for (const l of r.lines || []) { const w = want.get(l.passage_id); if (w && w.has(norm(l.node))) out.push({ start: l.start, end: l.end, cls: "dv-code-mark", mark: true }); }
        } catch (_) { /* the marks are a help, not essential */ }
      }
      if (my !== markSeq) return;
      marks = out;
      if (tab === "codes") paint();
    }

    // a label of one's own: for a passage (from a labelled passage) or for selected text
    let codeList = null;
    async function codesOf() {
      if (!codeList) codeList = api("GET", `${base}/frameworks/${P(framework)}`).then((r) => ((r.framework && r.framework.items) || [])).catch(() => []);
      return codeList;
    }
    async function addForm({ passage_id, quote, where }) {
      const label = (prof && prof.code_label) || "code";
      const items = await codesOf();
      const dl = h("datalist", { id: "dv-code-list" }, items.map((x) => h("option", { value: x.code }, `${x.code} · ${shortTitle(x.description, 90)}`)));
      const code = h("input", { class: "input input-sm", type: "text", list: "dv-code-list", autocomplete: "off", id: "dv-add-code", placeholder: items[0] ? `e.g. ${items[0].code}` : "" });
      const desc = h("p", { class: "muted small", style: { margin: "4px 0 0" } });
      code.addEventListener("input", () => { const x = items.find((y) => y.code === code.value.trim()); desc.textContent = x ? x.description : ""; });
      const rel = h("select", { class: "select input-sm", "aria-label": "How much it is about the code" }, h("option", { value: "main" }, "main topic"), h("option", { value: "mentioned" }, "mentioned"));
      const dir = prof && prof.directional ? h("select", { class: "select input-sm", "aria-label": "Direction" }, ["not_stated", "helps", "hinders", "mixed"].map((v) => h("option", { value: v }, DIRECTION_WORDS[v]))) : null;
      const note = h("input", { class: "input input-sm", type: "text", placeholder: "Why (optional)", "aria-label": "Why this code (optional)" });
      const msg = h("p", { class: "field-error", role: "alert", hidden: true });
      const save = h("button", { class: "btn btn-sm btn-primary", type: "button" }, icon("plus", { size: 13 }), "Add my label");
      save.addEventListener("click", async () => {
        msg.hidden = true;
        if (!code.value.trim()) { code.focus(); return; }
        save.disabled = true;
        try {
          await api("POST", `${base}/labels`, { framework, passage_id, code: code.value.trim(), quote: quote || undefined, relevance: rel.value, direction: dir ? dir.value : "not_stated", note: note.value.trim() || undefined });
          clear(addBox);
          toast("Your label was added. It always counts.", "ok", { small: true });
          await load();
        } catch (e) { msg.textContent = e.message; msg.hidden = false; save.disabled = false; }
      });
      replace(addBox, h("div", { class: "card card-plain dv-add" },
        h("h3", {}, `Add ${/^[aeiouAEIOU]|^SDG/.test(label) ? "an" : "a"} ${label} of your own`),
        h("p", { class: "muted small", style: { margin: "2px 0 8px" } }, quote ? ["For the selected text: ", h("q", { class: "serif" }, shortTitle(quote, 160))] : `For the passage ${where ? `in ${where}` : ""}.`),
        h("label", { class: "field-label", for: "dv-add-code" }, cap(label)), code, dl, desc,
        h("div", { class: "row", style: { marginTop: "8px", gap: "6px" } }, rel, dir, note),
        msg,
        h("div", { class: "btn-row", style: { marginTop: "8px" } }, save, h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => clear(addBox) }, "Cancel"))));
      addBox.scrollIntoView({ block: "nearest" });
      code.focus();
    }
    // selected text -> its passage (found as a phrase in this document) -> the form
    async function labelSelection(s) {
      if (!prof) await load();
      let r;
      try { r = await api("GET", `${base}/search?${new URLSearchParams({ q: `"${s.text}"`, docs: docId, mode: "phrase", limit: "200", width: "20" })}`); }
      catch (e) { showError(e); return; }
      const line = (r.lines || []).filter((l) => Math.abs(l.start - s.start) <= 30).sort((a, b) => Math.abs(a.start - s.start) - Math.abs(b.start - s.start))[0];
      if (!line) { toast("The selection could not be matched to one passage: select words within one paragraph, not across a heading or page break.", "warn"); return; }
      addForm({ passage_id: line.passage_id, quote: s.text, where: line.location });
    }

    api("GET", `${base}/frameworks`).then((r) => { fws = r.frameworks || []; if (prof) draw(); }).catch(() => {});
    load();
    return {
      el, labelSelection,
      live: load,   // 0.16: what counts changed (Restore, Leave out): the codes read again, in place
      decos: () => marks,
      show() { runningJob(project, ["keywords"]).then((j) => { if (j) watchers.push(jobCard(jobBox, j.id, "Finding the codes by keywords and meaning", keywordLabel, () => { jobBox.hidden = true; load(); }, { small: true, plain: true })); }); },
      framework: () => framework,
      frameworkTitle: () => (prof && prof.framework_title) || ((fws || []).find((f) => f.name === framework) || {}).title || framework,
    };
  }

  // ---- Key terms (F6)
  function termsPanel() {
    const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-terms-h" });
    const jobBox = h("div", { hidden: true });
    const body = h("div", { "aria-busy": "true" }, h("p", { class: "muted small" }, "Loading…"));
    el.append(h("h2", { id: "dv-terms-h", class: "dv-panel-title" }, "Key terms"), jobBox, body);
    let data = null, n = 15, pinned = null;
    const cursor = {};
    async function load() {
      try { data = await api("GET", `${docBase}/terms?n=${n}`); } catch (e) { replace(body, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, e.message))); return; }
      body.setAttribute("aria-busy", "false");
      draw();
      if (tab === "terms") paint();
    }
    function build(btn) {
      if (btn) btn.disabled = true;
      api("POST", `${base}/terms/build`, {}).then((r) => watchers.push(jobCard(jobBox, r.job.id, "Building the glossary", (p) => (p.total ? `Reading the documents: ${fmt.num(p.done || 0)} of ${fmt.num(p.total)}` : "Reading the documents…"), (job) => { if (job.state === "done") jobBox.hidden = true; load(); }, { small: true, plain: true })))
        .catch((e) => { showError(e); if (btn) btn.disabled = false; });
    }
    const hover = (tid, on) => { for (const x of list.querySelectorAll(`[data-terms~="${CSS.escape(tid)}"]`)) x.classList.toggle("kt-on", on); };
    function draw() {
      clear(body);
      const st = data.status || {};
      if (!st.built) {
        body.appendChild(emptyState("network", "No glossary yet", "Key terms come from the glossary of the project's terms. It is made on this computer in seconds to a minute; nothing is sent anywhere.",
          jobBox.hidden ? h("button", { class: "btn btn-primary btn-sm", type: "button", onClick: (e) => build(e.currentTarget) }, icon("network", { size: 13 }), "Make the glossary") : null));
        return;
      }
      if (st.stale && jobBox.hidden) body.appendChild(h("div", { class: "notice notice-warn", style: { marginBottom: "10px" } }, icon("alert-triangle"),
        h("div", {}, h("p", {}, "Documents were added or removed since the glossary was made, so the key terms may be out of date."),
          h("button", { class: "btn btn-sm", type: "button", style: { marginTop: "6px" }, onClick: (e) => build(e.currentTarget) }, icon("refresh", { size: 13 }), "Update the glossary"))));
      const terms = data.terms || [];
      if (!terms.length) { body.appendChild(emptyState("network", "No key terms", "No term of the glossary occurs in this document.")); return; }
      body.appendChild(h("p", { class: "muted small", style: { margin: "0 0 8px" } }, "The terms that set this document apart from the others in the project. Point at a term to underline it in the text; click it to keep it marked and go from one place to the next."));
      const max = Math.max(...terms.map((t) => t.score || 0), 1);
      const spans = data.spans || [];
      body.appendChild(h("ol", { class: "dv-terms" }, terms.map((t) => {
        const places = spans.filter((s) => s.term_id === t.term_id);
        const isPin = pinned === t.term_id;
        const pinBtn = h("button", { class: "dv-term-btn serif", type: "button", "aria-pressed": isPin ? "true" : "false", title: isPin ? "Click again for the next place" : "Mark it in the text and go to its first place",
          onClick: () => {
            if (pinned !== t.term_id) { pinned = t.term_id; cursor[t.term_id] = -1; }
            const i = cursor[t.term_id] = (cursor[t.term_id] + 1) % Math.max(1, places.length);
            draw();
            if (places[i]) jumpTo(places[i]);
            const again = body.querySelector(`[data-tid="${CSS.escape(t.term_id)}"] .dv-term-btn`); if (again) again.focus({ preventScroll: true });
          } }, t.label);
        const li = h("li", { class: "dv-term" + (isPin ? " dv-pinned" : ""), dataset: { tid: t.term_id },
          onMouseenter: () => hover(t.term_id, true), onMouseleave: () => hover(t.term_id, false), onFocusin: () => hover(t.term_id, true), onFocusout: () => hover(t.term_id, false) },
          h("div", { class: "dv-term-main" }, pinBtn,
            h("span", { class: "muted small" }, isPin && places.length ? `place ${cursor[t.term_id] + 1} of ${places.length}` : plural(t.mentions, "mention"))),
          h("span", { class: "dv-term-bar", "aria-hidden": "true" }, h("span", { style: { width: `${Math.max(4, Math.round(((t.score || 0) / max) * 100))}%` } })),
          h("span", { class: "dv-term-links" },
            h("a", { href: `#/search?q=${encodeURIComponent(t.label)}&mode=phrase`, class: "btn btn-sm btn-ghost", title: `Search the whole project for “${t.label}”` }, icon("text-search", { size: 13 }), h("span", { class: "visually-hidden" }, `Search the project for ${t.label}`)),
            h("a", { href: `#/concepts?name=${encodeURIComponent(t.label)}`, class: "btn btn-sm btn-ghost", title: `The concept “${t.label}” across the documents` }, icon("network", { size: 13 }), h("span", { class: "visually-hidden" }, `Open the concept ${t.label}`))));
        return li;
      })));
      const btns = [];
      if (pinned) btns.push(h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { pinned = null; draw(); paint(); } }, icon("x", { size: 13 }), "Stop marking"));
      if (terms.length >= n && n < 50) btns.push(h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { n = 40; load(); } }, icon("chevron-down", { size: 13 }), "Show more key terms"));
      if (btns.length) body.appendChild(h("div", { class: "btn-row", style: { marginTop: "8px" } }, btns));
      body.appendChild(h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("p", { class: "muted small" }, `Ranked by TF-IDF against the ${fmt.num(st.terms || 0)} terms of the project's glossary (made ${fmt.date(st.built_at)}); a term inside a longer key term with as many mentions is left out.`)));
    }
    load();
    return {
      el,
      live: load,   // 0.16: what counts changed (Restore, Leave out): the key terms read again, in place
      decos: () => (data ? (data.spans || []).map((s) => ({ start: s.start, end: s.end, cls: pinned === s.term_id ? "kt kt-pin" : "kt", term: s.term_id, mark: pinned === s.term_id })) : []),
    };
  }

  // ---- References (F5)
  function refsPanel() {
    const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-refs-h" });
    const jobBox = h("div", { hidden: true });
    const selBox = h("div", { "aria-live": "polite" });
    const body = h("div", {}, h("p", { class: "muted small" }, "Loading…"));
    el.append(h("h2", { id: "dv-refs-h", class: "dv-panel-title" }, "References"), selBox, jobBox, body);
    let data = null, selected = null, after = null, showAll = false, running = false;
    async function load() {
      try { data = await api("GET", `${docBase}/references`); } catch (e) { replace(body, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, e.message))); return; }
      if (selected !== null && !(data.chains || []).some((c) => c.chain_id === selected)) selected = null;
      draw();
      if (tab === "refs") paint();
    }
    function start(name, btn) {
      if (btn) btn.disabled = true;
      api("POST", `${docBase}/references`, name ? { name } : {}).then((r) => { session(`refs-job:${project}:${docId}`, { id: r.job.id, name: name || null }); follow(r.job.id, name); }).catch((e) => { showError(e); if (btn) btn.disabled = false; });
    }
    function follow(jobId, name) {
      running = true;
      draw();
      watchers.push(jobCard(jobBox, jobId, name ? `Following the references to “${name}”` : "Following the references", (p) => (p.total ? `The AI has read ${fmt.num(Math.max(0, (p.done || 0) - 1))} of ${fmt.num(p.total)} stretches` : "The AI is getting ready…"), (job) => {
        running = false;
        if (job.state === "done") { jobBox.hidden = true; const r = job.result || {}; toast(name && !r.windows ? `“${name}” does not occur in this document, written this way. Try another spelling, or select the name in the text.`
          : !r.read && r.already_read ? `The AI had already read ${plural(r.already_read, "stretch", "stretches")} for this. ${plural(r.chains || 0, "name")} with references.`
          : `The AI read ${plural(r.read || 0, "stretch", "stretches")}${r.failed ? `; ${r.failed} could not be read` : ""}. ${r.chains ? `${plural(r.chains, "name")} with references.` : "It found no references to follow."}`, r.failed || (name && !r.windows) ? "warn" : "ok", { ttl: 9000 }); }
        load();
      }, { small: true, plain: true, stoppedText: "Stopped. What the AI read so far is kept; start again to go on where it stopped." }));
    }
    function draw() {
      clear(body);
      const st = data.status || {};
      const chains = data.chains || [];
      const where = App.privacy();
      body.appendChild(h("p", { class: "small", style: { margin: "0 0 6px" } }, "The AI reads the document three passages at a time and links “it”, “they” or “the study” to the name they stand for. Every mention it reports is checked against the text. It is a reading aid: the AI misses some references."));
      const left = Math.max(0, (st.windows_total || 0) - (st.windows_read || 0));
      body.appendChild(h("p", { class: "muted small", style: { margin: "0 0 8px" } },
        st.windows_read ? `The AI has read ${fmt.num(st.windows_read)} of ${plural(st.windows_total || 0, "stretch", "stretches")} of this document` : `Not followed yet: ${plural(st.windows_total || 0, "stretch", "stretches")} of three passages to read`,
        st.windows_failed ? `; ${fmt.num(st.windows_failed)} could not be read` : "", ".",
        where.where === "cloud" ? ` ${where.sent || "The passages are sent to the Claude API (cloud)."}` : ""));
      if (!running) {
        const name = h("input", { class: "input input-sm", type: "text", placeholder: "a name used in the document", "aria-label": "Only for one name" });
        const nameBtn = h("button", { class: "btn btn-sm", type: "button", onClick: (e) => { const v = name.value.trim(); if (!v) { name.focus(); return; } start(v, e.currentTarget); } }, "Follow this name");
        name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); nameBtn.click(); } });
        body.appendChild(h("div", { class: "btn-row" },
          left ? h("button", { class: "btn btn-sm" + (chains.length ? "" : " btn-primary"), type: "button", onClick: (e) => start(null, e.currentTarget) }, icon("link", { size: 13 }),
            st.windows_read ? `Go on where it stopped (${plural(left, "stretch", "stretches")} left)` : "Follow the references in this document") : h("span", { class: "it small" }, icon("circle-check", { size: 13 }), " The AI has read the whole document.")));
        body.appendChild(h("details", { class: "fold" }, h("summary", {}, "Only for one name"), h("p", { class: "muted small", style: { margin: "4px 0 6px" } }, "Faster: the AI reads only the passages where the name occurs."), h("div", { class: "row dv-name-row" }, name, nameBtn)));
      }
      if (!chains.length) {
        if (st.windows_read) body.appendChild(h("p", { class: "muted small" }, left ? "No references found yet in the stretches read." : "The AI found no references to follow in this document."));
        return;
      }
      body.appendChild(h("p", { class: "muted small", style: { margin: "10px 0 6px" } }, "Select a name in the text to see every later mention of the same thing, or pick a name here."));
      const shown = showAll ? chains : chains.slice(0, 25);
      body.appendChild(h("ul", { class: "dv-chains" }, shown.map((ch) => {
        const on = selected === ch.chain_id;
        const li = h("li", { class: "dv-chain" + (on ? " dv-open" : "") },
          h("button", { class: "dv-chain-btn", type: "button", "aria-pressed": on ? "true" : "false", dataset: { chain: String(ch.chain_id) },
            onClick: () => { selected = on ? null : ch.chain_id; after = null; draw(); paint(); if (!on && ch.mentions[0]) jumpTo(ch.mentions[0]); const b = body.querySelector(`[data-chain="${ch.chain_id}"]`); if (b) b.focus({ preventScroll: true }); } },
            h("span", { class: "serif dv-chain-name" }, ch.name),
            h("span", { class: "muted small" }, `${plural(ch.size, "mention")}${ch.unnamed ? ` · ${ch.unnamed} without the name` : ""}`)));
        if (on) {
          const ms = after !== null ? ch.mentions.filter((x) => x.start >= after) : ch.mentions;
          li.appendChild(h("p", { class: "muted small", style: { margin: "6px 0 2px" } }, after !== null ? `${plural(ms.length, "later mention")} (of ${ch.size}):` : "Its mentions, in order:"));
          li.appendChild(h("ol", { class: "dv-mentions" }, ms.slice(0, 80).map((x) => h("li", {},
            h("button", { class: "link-btn", type: "button", onClick: () => jumpTo(x) }, x.is_named ? h("strong", {}, x.text) : x.text),
            h("span", { class: "muted small" }, ` · ${x.location || ""}`)))));
        }
        return li;
      })));
      if (chains.length > shown.length) body.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { showAll = true; draw(); } }, icon("chevron-down", { size: 13 }), `Show all ${chains.length} names`));
    }
    // a selection in the text: its chain (by offsets, or by the same words), else offer to follow that name
    async function lookup(s) {
      if (!data) await load();
      let ch = null;
      try { ch = (await api("GET", `${docBase}/references?start=${s.start}&end=${s.end}`)).chain; } catch (_) { /* try by text */ }
      if (!ch) ch = (data.chains || []).find((c) => norm(c.name) === norm(s.text) || c.mentions.some((x) => norm(x.text) === norm(s.text))) || null;
      clear(selBox);
      if (ch) {
        selected = ch.chain_id; after = s.end; showAll = showAll || !(data.chains || []).slice(0, 25).some((c) => c.chain_id === ch.chain_id);
        draw(); paint();
        const later = ch.mentions.filter((x) => x.start >= s.end);
        if (later[0]) jumpTo(later[0]);
        replace(selBox, h("p", { class: "dv-selnote" }, icon("link", { size: 13 }), ` “${shortTitle(s.text, 60)}” is part of `, h("strong", {}, ch.name), later.length ? `: ${plural(later.length, "later mention")}, marked in the text.` : ": no later mention."));
        return;
      }
      const btn = h("button", { class: "btn btn-sm", type: "button", disabled: running, onClick: (e) => { clear(selBox); start(s.text, e.currentTarget); } }, icon("link", { size: 13 }), `Follow the references to “${shortTitle(s.text, 40)}”`);
      replace(selBox, h("div", { class: "notice notice-info dv-selnote" }, icon("info"), h("div", {}, h("p", {}, `No reference found yet for “${shortTitle(s.text, 60)}”.`), h("div", { class: "btn-row", style: { marginTop: "6px" } }, btn))));
    }
    load();
    return {
      el, lookup,
      show() { stillRunning(`refs-job:${project}:${docId}`).then((j) => { if (j && !running) follow(j.id, j.name); }); },
      decos: () => {
        const ch = data && selected !== null ? (data.chains || []).find((c) => c.chain_id === selected) : null;
        return ch ? ch.mentions.map((x) => ({ start: x.start, end: x.end, cls: x.is_named ? "dv-ref dv-ref-named" : "dv-ref", mark: true })) : [];
      },
    };
  }

  // ---- Search in this document (F1)
  function searchPanel() {
    const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-search-h" });
    const input = h("input", { class: "input", type: "search", id: "dv-q", placeholder: "Words to find in this document", value: query.find || "", autocomplete: "off" });
    const mode = h("select", { class: "select input-sm", "aria-label": "How to match the words" }, [["any", "any of the words"], ["all", "all the words, in one passage"], ["phrase", "the exact phrase"]].map(([v, t]) => h("option", { value: v }, t)));
    const form = h("form", { class: "dv-search", role: "search", onSubmit: (e) => { e.preventDefault(); run(); } },
      h("label", { class: "visually-hidden", for: "dv-q" }, "Search in this document"),
      h("div", { class: "row dv-search-row" }, input, h("button", { class: "btn btn-sm btn-primary", type: "submit" }, icon("search", { size: 13 }), "Search")), mode);
    const results = h("div", { "aria-live": "polite" });
    el.append(h("h2", { id: "dv-search-h", class: "dv-panel-title" }, "Search in this document"), form,
      h("p", { class: "muted small", style: { margin: "6px 0 8px" } }, "Or click a word in the text to add it; Shift-click a later word to make a phrase."), results);
    let res = null, cur = -1, lastPick = null, seq = 0;
    mode.addEventListener("change", () => { if (input.value.trim()) run(); });
    async function run(more) {
      const q = input.value.trim();
      keepUrl();
      if (!q) { res = null; cur = -1; clear(results); if (tab === "search") paint(); return; }
      const my = ++seq;
      const off = more && res ? res.lines.length : 0;
      let r;
      try { r = await api("GET", `${base}/search?${new URLSearchParams({ q, docs: docId, mode: mode.value, limit: "200", offset: String(off), width: "45" })}`); }
      catch (e) { if (my === seq) replace(results, h("p", { class: "field-error" }, e.message)); return; }
      if (my !== seq) return;
      if (more && res) { res.lines = res.lines.concat(r.lines || []); } else { res = r; cur = -1; }
      draw();
      paint();
    }
    function go(i) {
      if (!res || !res.lines[i]) return;
      cur = i;
      draw();
      jumpTo(res.lines[i]);
    }
    function draw() {
      clear(results);
      if (!res) return;
      const lines = res.lines || [];
      if (!res.total) { results.appendChild(h("p", { class: "muted" }, `No hit for “${res.query}” in this document.`, " ", h("a", { href: `#/search?q=${encodeURIComponent(res.query)}` }, "Search the whole project"))); return; }
      results.appendChild(h("div", { class: "row dv-hitnav" },
        h("strong", {}, `${plural(res.total, "hit")} in ${plural(res.passages, "passage")}`),
        h("span", { class: "grow" }),
        h("button", { class: "btn btn-sm", type: "button", disabled: !lines.length, "aria-label": "Previous hit", onClick: () => go(cur <= 0 ? lines.length - 1 : cur - 1) }, icon("chevron-left", { size: 13 })),
        h("span", { class: "small muted" }, cur >= 0 ? `${cur + 1} of ${fmt.num(lines.length)}` : ""),
        h("button", { class: "btn btn-sm", type: "button", disabled: !lines.length, "aria-label": "Next hit", onClick: () => go(cur >= lines.length - 1 ? 0 : cur + 1) }, icon("chevron-right", { size: 13 }))));
      results.appendChild(h("div", { class: "kwic-wrap dv-kwic" }, h("table", { class: "kwic" },
        h("caption", { class: "visually-hidden" }, `Hits for ${res.query} in this document`),
        h("tbody", {}, lines.map((l, i) => h("tr", { class: i === cur ? "dv-cur" : "" },
          h("td", { class: "kw-left" }, h("span", {}, l.left)),
          h("td", { class: "kw-node" }, h("button", { class: "dv-node", type: "button", title: `Go to ${l.location || "it"}`, onClick: () => go(i) }, h("mark", {}, l.node))),
          h("td", { class: "kw-right" }, l.right),
          h("td", { class: "kw-where" }, l.location || "")))))));
      if (lines.length < res.total) results.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", style: { marginTop: "6px" }, onClick: () => run(true) }, icon("chevron-down", { size: 13 }), `Show more hits (${fmt.num(res.total - lines.length)} more)`));
      results.appendChild(h("p", { class: "small", style: { marginTop: "8px" } }, h("a", { href: `#/search?q=${encodeURIComponent(res.query)}${mode.value !== "any" ? `&mode=${mode.value}` : ""}` }, icon("text-search", { size: 12 }), " Search the whole project for it")));
    }
    function addWord(w, shift) {
      let v = input.value;
      if (shift && lastPick) {
        const s = Math.min(lastPick.start, w.start), e = Math.max(lastPick.end, w.end);
        const phrase = docSlice(s, e);
        if (phrase !== null && e - s <= 200) {
          const add = `"${phrase.replace(/\s+/g, " ").replace(/"/g, "").trim()}"`;
          v = v.trimEnd().endsWith(lastPick.inBox) ? v.trimEnd().slice(0, v.trimEnd().length - lastPick.inBox.length) + add : `${v.trim()} ${add}`;
          lastPick = { start: s, end: e, inBox: add };
          input.value = v.trim();
          run();
          return;
        }
      }
      if (!v.toLowerCase().split(/\s+/).includes(w.text.toLowerCase())) v = `${v.trim()} ${w.text}`;
      lastPick = { start: w.start, end: w.end, inBox: w.text };
      input.value = v.trim();
      run();
    }
    if (input.value.trim()) run();
    return {
      el, addWord,
      query: () => input.value.trim(),
      searchFor(text) { input.value = text; lastPick = null; run(); },
      show(fromUser) { if (fromUser) setTimeout(() => input.focus({ preventScroll: true }), 0); },
      decos: () => (res ? res.lines.map((l, i) => ({ start: l.start, end: l.end, cls: i === cur ? "dv-hit dv-hit-cur" : "dv-hit", mark: true })) : []),
    };
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
  const kept = keepPlace && keepPlace.doc === docId ? keepPlace : null;
  keepPlace = null;
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
