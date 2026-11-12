// Quick look (F8): drop one document and read it at once (search, key terms, codes), in a temporary project that is
// moved to the trash after a week unless it is kept.
import { App, api, h, icon, replace, toast, showError, dialog, confirmDialog, watchJob, P, navigate, fmt, button, notice } from "../lib.js";
import { simpleProgress } from "./progress.js";

const OK = /\.(pdf|docx|html?|txt|md)$/i;   // 0.14.3: Word too (the app reads it, and the file chooser offers it)

// The banner shown on every page of a temporary project.
export function quickLookBanner(box) {
  if (!box) return;
  const p = ((App.state && App.state.projects) || []).find((x) => x.name === App.project);
  const t = p && p.temporary;
  if (!t) { replace(box); return; }
  const until = new Date((t.expires_at || 0) * 1000);
  const keep = button({ kind: "main", sm: true }, icon("pin", { size: 13 }), "Keep as a project");
  keep.addEventListener("click", async () => {
    keep.disabled = true;
    try { await api("POST", `/api/projects/${P(p.name)}/keep`, {}); await App.refresh(); toast(`“${p.name}” is kept as a project.`, "ok"); replace(box); }
    catch (e) { showError(e); keep.disabled = false; }
  });
  const discard = button({ kind: "quiet", sm: true }, icon("trash", { size: 13 }), "Discard now");
  discard.addEventListener("click", async () => {
    const ok = await confirmDialog({ title: "Discard this quick look?", message: `“${p.name}” is moved to the trash folder inside the data folder now, instead of on ${fmt.dateShort(until.toISOString())}.`, confirmText: "Discard" });
    if (!ok) return;
    discard.disabled = true;
    try {
      await api("DELETE", `/api/projects/${P(p.name)}`, { confirm: p.name });
      const back = t.from && ((App.state && App.state.projects) || []).some((x) => x.name === t.from) ? t.from : null;
      if (back) await api("PUT", "/api/settings", { project: back });
      await App.refresh();
      replace(box);
      toast("The quick look was discarded.", "ok");
      navigate("#/");
    } catch (e) { showError(e); discard.disabled = false; }
  });
  replace(box, notice({ kind: "info", icon: "eye", class: "ql-banner", role: "status" },
    h("p", {}, h("strong", {}, "A quick look"), ` at ${t.file || "one document"}, in a temporary project of its own. It is moved to the trash on ${fmt.dateShort(until.toISOString())} unless you keep it.`),
    h("div", { class: "btn-row" }, keep, discard)));
}

// "Quick look at one document": choose a file, it is read into a temporary project and opened.
export function quickLookButton(opts = {}) {
  const input = h("input", { type: "file", accept: ".pdf,.docx,.html,.htm,.txt,.md", class: "visually-hidden" });
  const btn = button({ sm: !!opts.sm, title: "Read one document at once: search it, see its key terms and the codes it addresses, without setting up a project" },
    icon("eye", { size: 15 }), opts.text || "Quick look at one document");
  btn.addEventListener("click", () => input.click());
  input.addEventListener("change", () => { const f = input.files && input.files[0]; input.value = ""; if (f) startQuickLook(f); });
  return h("span", {}, btn, input);
}

export async function startQuickLook(file) {
  if (!OK.test(file.name)) { toast("A quick look reads one PDF, Word (.docx), web page (HTML), text or Markdown file.", "warn"); return; }
  const pb = h("div", {}, h("p", { class: "muted" }, `Copying ${file.name} (${fmt.bytes(file.size)})…`));
  const upload = new AbortController();
  let watcher = null, jobId = null, stopped = false, finished = false, own = null;
  // Stop, Escape and a click outside all end the work: the upload is cut off and the job, once it exists, is stopped
  const stopWork = async () => {
    stopped = true;
    upload.abort();
    if (jobId) await api("POST", `/api/jobs/${P(jobId)}/cancel`).catch(() => {});
  };
  const done = dialog({
    title: "Quick look", body: h("div", { class: "stack" }, h("p", {}, "The document is read into a temporary project of its own. You can search it, see its key terms and the codes it addresses at once."), pb),
    actions: [{ text: "Stop", value: null }],
    onOpen: (dlg) => { own = dlg; },
  });
  done.then(() => { if (!finished) stopWork(); });
  // Closes this dialog and no other: by the time the job ends, a Find or a confirmation may be open on top of the page.
  // The dialog helper closes on its own "cancel" event, so that is how it is asked to.
  const closeOwn = () => {
    finished = true;
    if (own && own.isConnected) own.dispatchEvent(new Event("cancel", { cancelable: true }));
  };
  try {
    const r = await api("POST", `/api/quicklook?name=${encodeURIComponent(file.name)}`, file, { signal: upload.signal });
    jobId = r.job.id;
    if (stopped) { await stopWork(); return done; }   // Stop came as the copy ended: the job is stopped as soon as it is known
    await App.refresh();
    watcher = watchJob(jobId, (job) => { if (!stopped) replace(pb, simpleProgress(job, (p) => p.phase === "glossary" ? "Finding the document's key terms…" : p.phase === "codes" ? "Finding the codes it addresses…" : p.phase === "embedding" ? "Setting up search by meaning…" : "Reading the document…")); });
    const job = await watcher.promise;
    closeOwn();
    if (stopped) return done;
    if (job.state === "done") {
      const added = (job.result && job.result.documents_added) || [];
      if (!added.length) { toast("The document could not be read: it has no text (a scan without text recognition?).", "warn", { ttl: 9000 }); navigate("#/sources"); return; }
      navigate(`#/doc/${encodeURIComponent(added[0].doc_id)}?tab=terms`);
    } else if (job.state === "error") showError({ message: job.error, kind: job.error_kind });
  } catch (e) {
    closeOwn();
    if (!stopped && e.name !== "AbortError") showError(e);
  }
  return done;
}
