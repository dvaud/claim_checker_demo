// Documents: a big add area first, the document table, smart search in plain words, a document viewer, and the
// rarely needed things (folder path, exclude patterns, remove everything) folded away.
import { featureEyebrow } from "../features.js";
import { App, api, h, icon, replace, clear, toast, showError, fmt, pageHead, watchJob, P, batchId, confirmDialog, field, emptyState, TERMINAL, KIND_TEXT } from "../lib.js";
import { simpleProgress } from "./progress.js";
import { plainSection, blockNode, blockUnit, originalLink, forgetOriginals } from "./result.js";
import { dialog, certainty, breakSegments, session } from "../lib.js";
import { aiLabelCard, jobCard, runningJob, startKeywordPass, keywordLabel, plural, shortTitle, SOURCE_WORDS, RELEVANCE_WORDS, DIRECTION_WORDS } from "./profile.js";

const ACCEPT = ".pdf,.docx,.html,.htm,.txt,.md,.zip";
const OK_EXT = ["pdf", "docx", "html", "htm", "txt", "md", "zip"];
const ocrState = () => (App.state && App.state.ocr) || {};

export async function renderSources(view) {
  const project = App.project;
  let info;
  try { info = await api("GET", `/api/projects/${P(project)}`); } catch (e) { showError(e); info = { search: null, passages: 0 }; }
  view.appendChild(pageHead("Documents", { eyebrow: featureEyebrow("sources"), sub: `The reports, papers and web pages of project “${project}” that you explore and check hypotheses against. Open one to read it with its codes, key terms and references.` }));

  const watchers = [];

  // ----------------------------------------------------------------- add documents
  const files = [];
  const fileInput = h("input", { type: "file", multiple: true, accept: ACCEPT, class: "visually-hidden", id: "src-files" });
  const fileList = h("ul", { class: "file-list", hidden: true });
  const addBtn = h("button", { class: "btn btn-primary btn-lg", type: "button", disabled: true }, icon("upload", { size: 15 }), "Add to the project");
  const excludeInput = h("input", { class: "input input-sm", type: "text", placeholder: "e.g. draft*  *_old.pdf", id: "exclude" });
  const drawFiles = () => {
    fileList.hidden = !files.length;
    replace(fileList, files.map((f, i) => h("li", {}, icon("file-text", { size: 13 }), h("span", { class: "grow", style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, f.name), h("span", { class: "fs" }, fmt.bytes(f.size)),
      h("button", { class: "icon-btn", type: "button", "aria-label": `Remove ${f.name} from the list`, style: { width: "24px", height: "24px" }, onClick: () => { files.splice(i, 1); drawFiles(); } }, icon("x", { size: 12 })))));
    addBtn.disabled = !files.length;
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
      ocrState().available === false ? "Scanned PDFs cannot be read on this computer yet: ask IT to install Tesseract (text recognition)." : ocrState().available && (App.settings().ocr || "auto") === "off" ? "Reading scanned PDFs is switched off in Settings." : ocrState().available ? "Scanned PDFs are read with text recognition (OCR), which is slow and can make mistakes." : ""),
    fileList);
  for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); });
  for (const ev of ["dragleave", "drop"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); });
  drop.addEventListener("drop", (e) => { if (e.dataTransfer && e.dataTransfer.files) takeFiles(e.dataTransfer.files); });
  // a click anywhere on the area (not on a chosen file's row or its remove button) opens the file chooser
  drop.addEventListener("click", (e) => { if (e.target.closest("label, button, input, .file-list")) return; fileInput.click(); });

  const pathInput = h("input", { class: "input", type: "text", placeholder: "e.g. C:\\Users\\me\\Documents\\Literature  or  /Users/me/Documents/Literature", id: "src-path" });
  const pathBtn = h("button", { class: "btn", type: "button" }, icon("folder-open", { size: 14 }), "Add this folder");
  const progressBox = h("div", { class: "section", hidden: true, "aria-live": "polite" });

  const addCard = h("section", { class: "card", "aria-label": "Add documents" },
    drop,
    h("div", { class: "btn-row", style: { marginTop: "12px" } }, addBtn),
    h("details", { class: "fold", style: { marginTop: "12px" } }, h("summary", {}, "More ways to add"),
      h("div", { class: "card card-plain", style: { marginTop: "8px" } },
        h("div", { class: "field" }, h("label", { class: "field-label", for: "src-path" }, "Add a whole folder on this computer"), h("div", { class: "row", style: { flexWrap: "nowrap" } }, pathInput, pathBtn),
          h("div", { class: "field-help" }, "Type or paste the full path of a folder (or of a zip file). The files are read where they are, nothing is copied.")),
        field("Leave out files whose name matches", excludeInput, { help: "Patterns separated by spaces; * stands for anything. Applies to everything you add." }),
        h("p", { class: "muted small", style: { margin: 0 } }, "For technical users: a zip may contain a manifest.csv (columns file, reference, doi) naming the work each file is."))));
  view.appendChild(addCard);
  view.appendChild(progressBox);

  async function runIngest(body, label) {
    try {
      const r = await api("POST", `/api/projects/${P(project)}/ingest`, body);
      followIngest(r.job.id, label);
    } catch (e) { showError(e); addBtn.disabled = !files.length; pathBtn.disabled = false; }
  }

  function followIngest(jobId, label) {
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
      files.length = 0; drawFiles(); pathBtn.disabled = false;
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
        added ? h("a", { class: "btn btn-primary btn-sm", href: "#/check", style: { marginTop: "8px" } }, icon("flask", { size: 13 }), "Check a hypothesis") : null)));
    const noText = new Set(st.scanned_no_text || []);
    if (st.ocr && st.ocr.length) bits.push(h("div", { class: "notice notice-info" }, icon("eye"), h("p", {}, `Scanned pages were read with text recognition (OCR) in ${st.ocr.length === 1 ? "1 document" : `${st.ocr.length} documents`}: ${st.ocr.join(", ")}. The recognised text can contain mistakes; the quotes are checked against it.`)));
    const notAdded = [...noText].filter((f) => (st.empty_files || []).includes(f));
    if (noText.size) bits.push(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("div", {}, h("p", {}, h("strong", {}, "Scanned: no text. "), `${noText.size === 1 ? "This document has" : "These documents have"} scanned pages that stayed without text: ${[...noText].join(", ")}. `,
      notAdded.length ? `${notAdded.length === 1 ? `${notAdded[0]} was not added, because none of its pages has text. ` : `${notAdded.length} of them were not added, because none of their pages has text. `}` : "",
      ocrState().available === false ? "Ask IT to install Tesseract to read it." : (App.settings().ocr || "auto") === "off" ? ["Reading scanned PDFs is switched off: turn it on in ", h("a", { href: "#/settings/basics" }, "Settings"), " and add the document again."] : "Text recognition could not read these pages."))));
    const emptyOther = (st.empty_files || []).filter((f) => !noText.has(f));
    if (emptyOther.length) bits.push(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("p", {}, `${emptyOther.length} ${emptyOther.length === 1 ? "file has" : "files have"} no readable text: ${emptyOther.join(", ")}`)));
    if (st.mostly_unreadable && st.mostly_unreadable.length) bits.push(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("p", {}, "The text of these could mostly not be read: " + st.mostly_unreadable.join(", ") + ". Try another copy (for example from the publisher), or run OCR.")));
    if (st.failed && st.failed.length) bits.push(h("div", { class: "notice notice-error" }, icon("alert-circle"), h("div", {}, h("p", {}, "These could not be read:"), h("ul", { class: "errors-list" }, st.failed.map((f) => h("li", {}, f))))));
    if (st.excluded && st.excluded.length) bits.push(h("p", { class: "muted small" }, `Left out: ${st.excluded.join(", ")}`));
    if (st.not_in_manifest && st.not_in_manifest.length) bits.push(h("p", { class: "muted small" }, `Not named in the manifest: ${st.not_in_manifest.slice(0, 10).join(", ")}${st.not_in_manifest.length > 10 ? "…" : ""}`));
    if (st.glossary_error || st.codes_error) bits.push(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("div", {}, h("p", {}, "The documents were added, but " + (st.glossary_error ? "the glossary of terms" : "the codes found by keywords") + " could not be updated. Update them from the Concepts or Profile page."), h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, st.glossary_error || st.codes_error)))));
    if (st.semantic_index_error) bits.push(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("div", {}, h("p", {}, "The documents were added, but search by meaning could not be set up for them, so they are searched by their words only."), h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, st.semantic_index_error)))));
    const newDocsLine = h("div", { "aria-live": "polite" });
    if (added) bits.push(newDocsLine);
    replace(holder.querySelector(".pb"), h("div", { class: "stack" }, bits));
    // results checked before these documents were added can read them now
    if (added) api("GET", `/api/projects/${P(project)}/hypotheses`).then((r) => {
      const n = (r.hypotheses || []).filter((x) => x.docs_added_since > 0).length;
      if (!n) return;
      replace(newDocsLine, h("p", { class: "it" }, icon("history", { size: 14 }), h("span", {}, `${n} ${n === 1 ? "result was checked before these documents were added and can read them now" : "results were checked before these documents were added and can read them now"}: `, h("a", { href: "#/history" }, "go to Results"), " and press “Read the new documents”. Your reviews are kept.")));
    }).catch(() => {});
  }

  addBtn.addEventListener("click", async () => {
    if (!files.length) return;
    addBtn.disabled = true;
    const batch = batchId();
    progressBox.hidden = false;
    const holder = h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Copying the files into the project")), h("div", { class: "pb" }));
    replace(progressBox, holder);
    let n = 0;
    try {
      for (const f of files) {
        replace(holder.querySelector(".pb"), simpleProgress({ state: "running", seconds: 0, progress: { done: n, total: files.length, file: f.name } }, () => `Copying ${f.name} (${n + 1} of ${files.length})`));
        await api("POST", `/api/projects/${P(project)}/uploads?batch=${batch}&name=${encodeURIComponent(f.name)}`, f);
        n++;
      }
    } catch (e) { showError(e); addBtn.disabled = false; progressBox.hidden = true; return; }
    const body = { batch };
    if (excludeInput.value.trim()) body.exclude = excludeInput.value.trim();
    await runIngest(body, `Reading ${files.length === 1 ? "the document" : `the ${files.length} documents`}`);
  });
  pathBtn.addEventListener("click", async () => {
    const p = pathInput.value.trim();
    if (!p) { pathInput.focus(); return; }
    pathBtn.disabled = true;
    const body = { path: p };
    if (excludeInput.value.trim()) body.exclude = excludeInput.value.trim();
    await runIngest(body, `Reading the folder`);
  });
  pathInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); pathBtn.click(); } });

  // ----------------------------------------------------------------- smart search
  const indexCard = h("section", { class: "card", "aria-label": "Search by meaning" });
  view.appendChild(indexCard);
  function drawIndex(search) {
    clear(indexCard);
    const s = search || {};
    const body = h("div", { class: "grow" });
    const head = h("div", { class: "index-card" }, h("span", { class: "icon-big" }, icon("sparkles", { size: 26 })), body);
    if (!s.model) {
      body.append(h("h2", {}, "Search by meaning is off"), h("p", { class: "muted", style: { margin: "4px 0 0" } }, "Documents are searched by their words only. With search by meaning, excerpts are found even when they use other words than your hypothesis. It can be turned on under Settings → Documents."));
      indexCard.appendChild(head); return;
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
        const r = await api("POST", `/api/projects/${P(project)}/index`);
        const pb = h("div", { style: { marginTop: "10px" } });
        indexCard.appendChild(pb);
        const w = watchJob(r.job.id, (job) => replace(pb, simpleProgress(job, (p) => p.total ? `Preparing ${p.done} of ${p.total} excerpts` : "Starting…")));
        watchers.push(w);
        const job = await w.promise;
        await reloadDocs();
        if (job.state === "error") showError({ message: job.error, kind: job.error_kind }); else if (job.state === "done") toast("Search by meaning is ready.", "ok");
      } catch (e) { showError(e); btn.disabled = false; }
    });
    if (btn) head.appendChild(btn);
    indexCard.appendChild(head);
  }

  // ----------------------------------------------------------------- documents
  const docsBox = h("section", { class: "section", "aria-label": "Documents in this project" });
  view.appendChild(docsBox);
  async function reloadDocs() {
    let r;
    try { r = await api("GET", `/api/projects/${P(project)}/documents`); } catch (e) { showError(e); return; }
    drawIndex(r.search);
    const docs = r.documents || [];
    clear(docsBox);
    docsBox.appendChild(h("div", { class: "section-title" }, h("h2", {}, `In this project (${docs.length})`)));
    if (!docs.length) { docsBox.appendChild(emptyState("book-open", "No documents yet", "Add the reports, papers and web pages you want to check hypotheses against. PDFs keep their page numbers.")); return; }
    const warned = docs.filter((d) => d.check).length;
    if (warned) docsBox.appendChild(h("p", { class: "muted small" }, icon("alert-triangle", { size: 12 }), ` ${warned} ${warned === 1 ? "document needs" : "documents need"} a look: see the note next to ${warned === 1 ? "it" : "them"}.`));
    docsBox.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "table table-responsive docs-table" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Title"), h("th", { scope: "col" }, "Type"), h("th", { scope: "col", class: "num" }, "Pages"), h("th", { scope: "col" }, "Added"), h("th", { scope: "col" }, "Note"), h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, "Actions")))),
      h("tbody", {}, docs.map((d) => h("tr", {},
        h("td", {}, h("div", { class: "doc-title", title: d.title || d.file }, h("a", { href: `#/doc/${encodeURIComponent(d.doc_id)}` }, d.title || d.file)), h("div", { class: "doc-file" }, d.file)),
        h("td", { "data-label": "Type" }, KIND_TEXT[d.kind] || d.kind || ""),
        h("td", { "data-label": "Pages", class: "num" }, d.pages ? String(d.pages) : "—"),
        h("td", { "data-label": "Added", class: "small muted nowrap" }, fmt.dateShort(d.added_at || "") || d.added || ""),
        h("td", { "data-label": "Note", class: "check-cell" },
          d.check ? h("span", { class: "warn-chip" }, icon("alert-triangle", { size: 12 }), d.check) : null,
          d.scanned ? h("span", { class: "it scanned-note" + (/no text/i.test(d.scanned) ? " warn-chip" : " muted small") }, icon(/no text/i.test(d.scanned) ? "alert-triangle" : "eye", { size: 12 }), d.scanned) : null,
          !d.check && !d.scanned ? h("span", { class: "it muted small" }, icon("check", { size: 12 }), "readable") : null),
        h("td", { class: "actions" },
          h("a", { class: "btn btn-sm btn-ghost", href: `#/doc/${encodeURIComponent(d.doc_id)}`, "aria-label": `Open ${d.title || d.file}` }, icon("eye", { size: 13 }), "Open"),
          h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": `Remove ${d.title || d.file}`, onClick: () => removeDoc(d) }, icon("trash", { size: 13 }), "Remove"))))))));
  }

  async function removeDoc(d) {
    const ok = await confirmDialog({ title: "Remove this document?", message: h("div", {}, h("p", {}, h("strong", {}, d.title || d.file)), h("p", {}, "It is no longer searched. Results you already have keep their quotes, marked as coming from a removed document.")), confirmText: "Remove" });
    if (!ok) return;
    try { await api("DELETE", `/api/projects/${P(project)}/documents/${P(d.doc_id)}`); toast("Document removed.", "ok"); await reloadDocs(); await App.refresh(); }
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
    const indexing = jobs.find((j) => j.project === project && j.kind === "index" && !TERMINAL.has(j.state));
    if (indexing) {
      const pb = h("div", { style: { marginTop: "10px" } });
      indexCard.appendChild(pb);
      const w = watchJob(indexing.id, (job) => replace(pb, simpleProgress(job, (p) => p.total ? `Preparing ${p.done} of ${p.total} excerpts` : "Starting…")));
      watchers.push(w);
      w.promise.then(() => reloadDocs()).catch(showError);
    }
  } catch (_) { /* ignore */ }
  return () => watchers.forEach((w) => w.stop());
}

// ---------------------------------------------------------------------------------------------
// document viewer: the document by paragraph or page (the units the locations cite), with the quote highlighted.
// 0.7: panels beside the text on wide screens (above it on phones): Codes (F2), Key terms (F6), References (F5) and
// Search in this document (F1); a highlighted copy to download (F7). `?tab=codes|terms|refs|search` opens a panel.
// ---------------------------------------------------------------------------------------------
const DOC_TABS = [["codes", "Codes", "tag"], ["terms", "Key terms", "network"], ["refs", "References", "link"], ["search", "Search", "text-search"]];
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
  const hit = span ? blocks.findIndex((b) => span.start >= b.start && span.start < b.end) : -1;
  // the quote's text, for opening the original at it (the whole excerpt is too long for that)
  const quoteText = hit >= 0 && !span.whole ? (blocks[hit].text || "").slice(Math.max(0, span.start - blocks[hit].start), Math.max(0, span.end - blocks[hit].start)).trim() || null : null;
  const back = from ? h("a", { href: `#/h/${encodeURIComponent(from)}${query.card ? `?card=${encodeURIComponent(query.card)}` : ""}`, class: "btn btn-sm" }, icon("arrow-left", { size: 13 }), "Back to the result") : null;
  const watchers = [];
  const cleanups = [];
  let tab = DOC_TABS.some(([k]) => k === query.tab) ? query.tab : null;
  let framework = query.framework || App.settings().profile_framework || "sdg";

  const copyBtn = h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => highlightedCopy() }, icon("highlighter", { size: 13 }), "Download a highlighted copy");
  view.appendChild(h("header", { class: "page-head" }, h("div", { class: "page-head-main" },
    h("p", { class: "eyebrow" }, from ? [back, " "] : null, h("a", { href: "#/sources", class: "it" }, icon("book-open", { size: 12 }), "All documents")),
    h("h1", { id: "page-title", tabindex: "-1", class: "serif", style: { fontWeight: 500 } }, d.title || d.file),
    h("div", { class: "result-meta", style: { marginTop: "6px" } }, h("span", {}, d.file), h("span", { class: "sep" }, "·"), h("span", {}, KIND_TEXT[d.kind] || d.kind || ""), d.n_pages ? [h("span", { class: "sep" }, "·"), h("span", {}, `${d.n_pages} pages`)] : null,
      d.n_pages && blockUnit(blocks[0]) === "pages" && totalBlocks === d.n_pages ? null : [h("span", { class: "sep" }, "·"), h("span", {}, `${totalBlocks} ${blockUnit(blocks[0])}`)], d.doi ? [h("span", { class: "sep" }, "·"), h("span", {}, `doi ${d.doi}`)] : null,
      d.scanned ? [h("span", { class: "sep" }, "·"), h("span", { class: "it" }, icon("eye", { size: 12 }), d.scanned)] : null),
    h("div", { class: "row dv-head-row", style: { marginTop: "8px", gap: "8px 14px" } },
      originalLink(project, docId, hit >= 0 ? blocks[hit].page : null, d.kind, { info: d.original || undefined, quote: quoteText, text: d.kind === "pdf" ? (hit >= 0 && blocks[hit].page ? `Open the original PDF at page ${blocks[hit].page}` : "Open the original PDF") : quoteText ? "Open the original at the quote" : "Open the original" }),
      h("span", { class: "muted small" }, d.original && d.original.available ? (d.kind === "pdf" && quoteText ? "Opens in a new tab at that page; the quote is highlighted below." : "Opens in a new tab, as the file was when it was added.") : ""),
      copyBtn),
    span ? h("p", { class: "muted small", style: { marginTop: "6px" } }, hit >= 0 ? (span.whole ? `The excerpt from the result is highlighted, in ${blocks[hit].label.toLowerCase()}.` : `The quote from the result is highlighted, in ${blocks[hit].label.toLowerCase()}.`) : "The quote could not be placed in this text.") : h("p", { class: "muted small", style: { marginTop: "6px" } }, "The text as the app reads it."))));

  // ----------------------------------------------------------------- the text, with layers of highlights
  const nodeAt = new WeakMap();        // text node -> document offset of its first character
  const rows = new Map();              // block n -> {row, b, sig}
  const loaded = [];                   // the blocks shown, in order
  const list = h("div", { class: "card doc-view dv-text" });
  const moreBox = h("div", { class: "dv-more" });
  const selBar = h("div", { class: "dv-selbar", role: "toolbar", "aria-label": "With the selected text", hidden: true });
  let focus = null;                    // the place jumped to last: {start, end, cls, extra: [decorations]}

  function addBlocks(bs) {
    for (const b of bs) {
      const body = h("div", { class: "dv-body" });
      const row = h("div", { class: "passage-row" + (hit >= 0 && b.n === blocks[hit].n ? " hit" : "") }, h("div", { class: "pp" }, h("b", {}, b.label)), body);
      row.id = `block-${b.n}`;
      list.insertBefore(row, selBar);
      rows.set(b.n, { row, body, b, sig: null });
      loaded.push(b);
    }
  }
  list.appendChild(selBar);
  addBlocks(blocks);

  function drawMore() {
    clear(moreBox);
    if (loaded.length >= totalBlocks) return;
    moreBox.appendChild(h("button", { class: "btn btn-sm", type: "button", onClick: (e) => { e.currentTarget.disabled = true; loadMore().then(() => paint()); } }, icon("chevron-down", { size: 13 }),
      `Show the rest of the document (${fmt.num(totalBlocks - loaded.length)} more ${blockUnit(blocks[0])})`));
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
      const sig = mine.map((x) => `${x.start}-${x.end}-${x.cls}-${x.term || ""}`).join("|");
      if (r.sig === sig) continue;
      r.sig = sig;
      replace(r.body, blockText(b, mine));
    }
  }
  // A block's text cut at its headings (as blockNode does), each piece under the decorations that cover it.
  function blockText(b, decos) {
    const text = b.text || "";
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
        const piece = h(on.some((x) => x.mark) ? "mark" : "span", { class: [...new Set(on.map((x) => x.cls))].join(" "), dataset: terms.length ? { terms: terms.join(" ") } : null });
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
    if (tab !== "search" || e.target.closest(".dv-selbar, button, a")) return;
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
  list.addEventListener("mouseup", () => setTimeout(showSelBar, 0));
  list.addEventListener("touchend", () => setTimeout(showSelBar, 250));
  list.addEventListener("keyup", (e) => { if (e.shiftKey) setTimeout(showSelBar, 0); });
  const onSelChange = () => { const sel = window.getSelection(); if (!selBar.hidden && (!sel || sel.isCollapsed) && !selBar.contains(document.activeElement)) selBar.hidden = true; };
  document.addEventListener("selectionchange", onSelChange);
  cleanups.push(() => document.removeEventListener("selectionchange", onSelChange));
  selBar.addEventListener("keydown", (e) => { if (e.key === "Escape") selBar.hidden = true; });

  // ----------------------------------------------------------------- the panels
  const tabsRow = h("div", { class: "btn-row dv-tabs", role: "group", "aria-label": "Show next to the text" });
  const panelBox = h("div", { class: "dv-panel-box" });
  const intro = h("p", { class: "muted small dv-intro" }, "Show next to the text: which codes of a codebook it addresses, its key terms, what “it” and “they” refer to, or search inside it.");
  const side = h("aside", { class: "dv-side", "aria-label": "About this document" }, tabsRow, panelBox);
  const layout = h("div", { class: "dv-layout" }, side, h("div", { class: "dv-main" }, list, moreBox));
  view.appendChild(layout);

  const panels = {};
  const makers = { codes: codesPanel, terms: termsPanel, refs: refsPanel, search: searchPanel };
  function drawTabs() {
    replace(tabsRow, DOC_TABS.map(([k, label, ic]) => h("button", { class: "btn btn-sm seg-btn" + (tab === k ? " seg-on" : ""), type: "button", "aria-pressed": tab === k ? "true" : "false", dataset: { tab: k },
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
    for (const [k, v] of Object.entries(query)) if (!["tab", "code", "find", "framework"].includes(k)) s.set(k, v);
    if (tab) s.set("tab", tab);
    if (framework !== (App.settings().profile_framework || "sdg")) s.set("framework", framework);
    if (tab === "search" && panels.search && panels.search.query()) s.set("find", panels.search.query());
    const qs = s.toString();
    history.replaceState(null, "", `#/doc/${encodeURIComponent(docId)}${qs ? "?" + qs : ""}`);
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
          const res = await api("GET", `${docBase}/annotated.pdf?layers=${layers.join(",")}&framework=${encodeURIComponent(fwNow)}`, undefined, { raw: true });
          const blob = await res.blob();
          const cd = res.headers.get("Content-Disposition") || "";
          const mm = /filename="?([^";]+)"?/.exec(cd);
          const url = URL.createObjectURL(blob);
          const a = h("a", { href: url, download: (mm && mm[1]) || `${d.title || docId} - highlighted.${isPdf ? "pdf" : "html"}` });
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(() => URL.revokeObjectURL(url), 2000);
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
  if (tab) { const k = tab; tab = null; openTab(k, false); } else { replace(panelBox, intro); paint(); }
  drawMore();
  if (span && span.end > (loaded[loaded.length - 1] || { end: 0 }).end) await ensureLoaded(span.end).then(paint);
  if (hit >= 0 || span) setTimeout(() => { const b = span ? blockAt(span.start) : null; const row = b ? document.getElementById(`block-${b.n}`) : null; const el = (row && row.querySelector("mark.quote")) || row; if (el) el.scrollIntoView({ block: "center" }); }, 60);
  return () => { watchers.forEach((w) => w.stop()); cleanups.forEach((f) => f()); };
}

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
