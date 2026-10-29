// Batch: several hypotheses at once, from pasted lines, CSV text or a file read in the browser.
import { featureEyebrow } from "../features.js";
import { App, api, h, icon, replace, clear, toast, showError, fmt, pageHead, watchJob, P, session, emptyState, statusBadge, debounce } from "../lib.js";
import { checkOptions } from "./options.js";
import { ProgressPanel } from "./progress.js";

export async function renderBatch(view, params, query) {
  const project = App.project;
  let info, docsRes;
  try { [info, docsRes] = await Promise.all([api("GET", `/api/projects/${P(project)}`), api("GET", `/api/projects/${P(project)}/documents`)]); }
  catch (e) { showError(e); info = { search: null }; docsRes = { documents: [] }; }

  view.appendChild(pageHead("Check several hypotheses", { eyebrow: featureEyebrow("batch"), sub: "Paste a list, or load a spreadsheet. They are checked one after the other, and each one gets its own result under Results." }));

  const ta = h("textarea", { class: "textarea", rows: 8, id: "batch-text", placeholder: "One hypothesis per line, for example:\n\nWorking from home reduces commuting emissions.\nHybrid work increases loneliness among young employees.", spellcheck: "false" });
  ta.value = session("batchDraft") || "";
  const fileInput = h("input", { type: "file", accept: ".csv,.txt,.md,text/csv,text/plain", class: "visually-hidden", id: "batch-file" });
  fileInput.addEventListener("change", async () => {
    const f = fileInput.files && fileInput.files[0];
    if (!f) return;
    try { ta.value = await f.text(); session("batchDraft", ta.value); preview(); toast(`Loaded ${f.name}.`, "ok", { ttl: 2500 }); }
    catch (e) { showError(e); }
    fileInput.value = "";
  });
  const previewBtn = h("button", { class: "btn", type: "button", onClick: () => preview() }, icon("eye", { size: 14 }), "Show the list");
  const runBtn = h("button", { class: "btn btn-primary", type: "button", disabled: true }, icon("play", { size: 14 }), "Check them all");
  const previewBox = h("div", { class: "section", hidden: true });
  const reason = h("span", { class: "muted small", id: "batch-reason", role: "status" }, "Paste or load at least one hypothesis to start.");
  const options = checkOptions({ docs: docsRes.documents || [], search: info.search, compact: true });
  let items = [];

  const form = h("div", { class: "card" },
    h("div", { class: "field" }, h("label", { class: "field-label", for: "batch-text" }, "Your hypotheses"), ta,
      h("div", { class: "hint-row" }, h("span", {}, "Up to 500. A spreadsheet saved as CSV works too: it needs a column called “hypothesis” and may have a column “code” for a codebook tag."),
        h("label", { class: "btn btn-sm", for: "batch-file", tabindex: "0", onKeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } } }, icon("upload", { size: 13 }), "Load a spreadsheet (CSV) or text file", fileInput))),
    options,
    h("div", { class: "btn-row", style: { marginTop: "14px" } }, previewBtn, runBtn, reason));
  view.appendChild(form);
  view.appendChild(previewBox);
  const autoPreview = debounce(() => { if (ta.value.trim()) preview(true); }, 500);
  ta.addEventListener("input", () => {
    session("batchDraft", ta.value); runBtn.disabled = true;
    if (ta.value.trim()) reason.textContent = "Reading your list…";
    else { reason.textContent = "Paste or load at least one hypothesis to start."; items = []; clear(previewBox); previewBox.hidden = true; replace(runBtn, icon("play", { size: 14 }), "Check them all"); }
    autoPreview();
  });

  async function preview(quiet) {
    const text = ta.value;
    if (!text.trim()) { if (!quiet) toast("Paste or load some hypotheses first.", "warn"); return; }
    previewBtn.disabled = true;
    try {
      const r = await api("POST", `/api/projects/${P(project)}/batches/preview`, { text });
      if (text !== ta.value) { previewBtn.disabled = false; return; }   // typed on meanwhile
      items = r.items || [];
      clear(previewBox);
      previewBox.hidden = quiet ? previewBox.hidden : false;
      if (!items.length) { previewBox.hidden = false; previewBox.appendChild(emptyState("search-x", "No hypotheses found", "Write one per line, or load a CSV with a column called “hypothesis”.")); runBtn.disabled = true; reason.textContent = "No hypothesis found in the text yet."; previewBtn.disabled = false; return; }
      reason.textContent = `${items.length} ${items.length === 1 ? "hypothesis" : "hypotheses"} found.`;
      previewBox.appendChild(h("div", { class: "section-title" }, h("h2", {}, `${r.count} ${r.count === 1 ? "hypothesis" : "hypotheses"} ready`), h("span", { class: "muted" }, "have a look before checking them")));
      previewBox.appendChild(h("div", { class: "table-wrap batch-preview" }, h("table", { class: "table" },
        h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "#"), h("th", { scope: "col" }, "Hypothesis"), h("th", { scope: "col" }, "Codebook"), h("th", { scope: "col" }, "Code"))),
        h("tbody", {}, items.map((it, i) => h("tr", {}, h("td", { class: "num muted" }, String(i + 1)), h("td", { class: "serif" }, it.text), h("td", { class: "muted" }, it.framework || ""), h("td", { class: "mono" }, it.code || "")))))));
      runBtn.disabled = false;
      replace(runBtn, icon("play", { size: 14 }), `Check ${items.length === 1 ? "this hypothesis" : `all ${items.length}`}`);
    } catch (e) { if (!quiet) showError(e); }
    previewBtn.disabled = false;
  }

  // --- running
  const progressBox = h("section", { class: "section", hidden: true, "aria-label": "Progress of the checks" });
  view.appendChild(progressBox);
  let watcher = null;

  function follow(jobId) {
    if (watcher) watcher.stop();
    const panel = new ProgressPanel({ title: "Checking the hypotheses" });
    replace(progressBox, h("div", { class: "section-title" }, h("h2", {}, "Checking"), h("span", { class: "muted" }, "you can leave this page; the checks continue")), panel.el);
    progressBox.hidden = false;
    setTimeout(() => progressBox.scrollIntoView({ block: "start", behavior: "smooth" }), 50);
    session("activeBatch", jobId);
    runBtn.disabled = true;
    watcher = watchJob(jobId, (job) => panel.update(job));
    watcher.promise.then((job) => {
      session("activeBatch", null);
      runBtn.disabled = false;
      const st = progressBox.querySelector(".section-title"); if (st) replace(st, h("h2", {}, job.state === "done" ? "Finished" : "Stopped"));
      summary(job);
    }).catch((e) => { session("activeBatch", null); runBtn.disabled = false; showError(e); });
  }

  async function summary(job) {
    const r = job.result || {};
    const errors = r.errors || [];
    const checked = r.checked || [];
    let rows = [];
    if (r.batch_id) { try { rows = (await api("GET", `/api/projects/${P(project)}/hypotheses?batch=${encodeURIComponent(r.batch_id)}`)).hypotheses || []; } catch (_) { rows = []; } }
    const card = h("div", { class: "card", style: { marginTop: "14px" } },
      h("div", { class: "card-head" }, h("h2", {}, job.state === "done" ? "All done" : job.state === "cancelled" ? "Stopped" : "Something went wrong"),
        r.batch_id ? h("a", { class: "btn btn-primary btn-sm", href: `#/history?batch=${encodeURIComponent(r.batch_id)}` }, icon("history", { size: 14 }), "See the results") : null),
      h("div", { class: "kv-grid" },
        h("div", { class: "kv" }, h("dt", {}, "Checked"), h("dd", {}, `${checked.length} of ${r.total ?? items.length}`)),
        errors.length ? h("div", { class: "kv" }, h("dt", {}, "Could not be checked"), h("dd", {}, String(errors.length))) : null,
        h("div", { class: "kv" }, h("dt", {}, "Time"), h("dd", {}, fmt.secs(job.seconds)))),
      rows.length ? h("ul", { class: "batch-answers" }, rows.map((x) => h("li", {}, h("a", { href: `#/h/${encodeURIComponent(x.hyp_id)}`, class: "serif" }, x.text || x.claim), " ", statusBadge(x.status, { short: true })))) : null,
      r.stopped ? h("div", { class: "notice notice-warn", style: { marginTop: "10px" } }, icon("alert-triangle"), h("p", {}, r.stopped)) : null,
      job.state === "error" ? h("div", { class: "notice notice-error", style: { marginTop: "10px" } }, icon("alert-circle"), h("div", {}, h("p", {}, job.error_kind === "backend" ? "The AI model stopped answering." : "The checks could not continue."), h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, job.error || "")), job.error_kind === "backend" ? h("a", { href: "#/settings" }, "Check the AI model in Settings") : null)) : null,
      errors.length ? h("details", { class: "fold", open: true, style: { marginTop: "10px" } }, h("summary", {}, `Hypotheses that could not be checked (${errors.length})`),
        h("ul", { class: "batch-errors" }, errors.map((e) => h("li", {}, h("span", { class: "muted" }, `#${(e.index ?? 0) + 1} `), h("span", { class: "serif" }, e.text), " — ", h("span", { class: "bad", style: { color: "var(--bad)" } }, e.error))))) : null);
    progressBox.appendChild(card);
    if (job.state === "done") toast(`All done: ${checked.length} checked${errors.length ? `, ${errors.length} could not be checked` : ""}.`, errors.length ? "warn" : "ok");
  }

  runBtn.addEventListener("click", async () => {
    if (!items.length) return;
    const o = options.values();
    const body = { items, decompose: o.decompose, expand: o.expand, k: o.k, per_doc: o.per_doc, semantic: o.semantic };
    if (o.doc_ids) body.doc_ids = o.doc_ids;
    runBtn.disabled = true;
    try {
      const r = await api("POST", `/api/projects/${P(project)}/batches`, body);
      session("batchDraft", null);
      follow(r.job.id);
    } catch (e) { runBtn.disabled = false; showError(e); }
  });

  const active = query.job || session("activeBatch");
  if (active) {
    try {
      const job = await api("GET", `/api/jobs/${P(active)}`);
      if (job.kind === "batch" && (job.state === "queued" || job.state === "running")) follow(job.id);
      else if (job.kind === "batch" && query.job) { progressBox.hidden = false; summary(job); }
      else session("activeBatch", null);
    } catch (_) { session("activeBatch", null); }
  }
  if (ta.value.trim()) preview(true);
  return () => { if (watcher) watcher.stop(); };
}
