// Quick look (F8): drop one document and read it at once (search, key terms, codes), in a temporary project that is
// moved to the trash after a week unless it is kept.
import { App, api, h, icon, replace, toast, showError, dialog, confirmDialog, watchJob, P, navigate, fmt } from "../lib.js";
import { simpleProgress } from "./progress.js";

const OK = /\.(pdf|html?|txt|md)$/i;

// The banner shown on every page of a temporary project.
export function quickLookBanner(box) {
  if (!box) return;
  const p = ((App.state && App.state.projects) || []).find((x) => x.name === App.project);
  const t = p && p.temporary;
  if (!t) { replace(box); return; }
  const until = new Date((t.expires_at || 0) * 1000);
  const keep = h("button", { class: "btn btn-sm btn-primary", type: "button" }, icon("pin", { size: 13 }), "Keep as a project");
  keep.addEventListener("click", async () => {
    keep.disabled = true;
    try { await api("POST", `/api/projects/${P(p.name)}/keep`, {}); await App.refresh(); toast(`“${p.name}” is kept as a project.`, "ok"); replace(box); }
    catch (e) { showError(e); keep.disabled = false; }
  });
  const discard = h("button", { class: "btn btn-sm btn-ghost", type: "button" }, icon("trash", { size: 13 }), "Discard now");
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
  replace(box, h("div", { class: "ql-banner", role: "status" }, icon("eye", { size: 16 }),
    h("span", { class: "grow" }, h("strong", {}, "A quick look"), ` at ${t.file || "one document"}, in a temporary project of its own. It is moved to the trash on ${fmt.dateShort(until.toISOString())} unless you keep it.`),
    keep, discard));
}

// "Quick look at one document": choose a file, it is read into a temporary project and opened.
export function quickLookButton(opts = {}) {
  const input = h("input", { type: "file", accept: ".pdf,.docx,.html,.htm,.txt,.md", class: "visually-hidden" });
  const btn = h("button", { class: opts.class || "btn", type: "button", title: "Read one document at once: search it, see its key terms and the codes it addresses, without setting up a project" },
    icon("eye", { size: 15 }), opts.text || "Quick look at one document");
  btn.addEventListener("click", () => input.click());
  input.addEventListener("change", () => { const f = input.files && input.files[0]; input.value = ""; if (f) startQuickLook(f); });
  return h("span", {}, btn, input);
}

export async function startQuickLook(file) {
  if (!OK.test(file.name)) { toast("A quick look reads one PDF, web page (HTML), text or Markdown file.", "warn"); return; }
  const pb = h("div", {}, h("p", { class: "muted" }, `Copying ${file.name} (${fmt.bytes(file.size)})…`));
  let watcher = null, jobId = null;
  const done = dialog({
    title: "Quick look", body: h("div", { class: "stack" }, h("p", {}, "The document is read into a temporary project of its own. You can search it, see its key terms and the codes it addresses at once."), pb),
    actions: [{ text: "Stop", value: null, onClick: async () => { if (jobId) await api("POST", `/api/jobs/${P(jobId)}/cancel`).catch(() => {}); } }],
  });
  try {
    const r = await api("POST", `/api/quicklook?name=${encodeURIComponent(file.name)}`, file);
    jobId = r.job.id;
    await App.refresh();
    watcher = watchJob(jobId, (job) => replace(pb, simpleProgress(job, (p) => p.phase === "glossary" ? "Finding the document's key terms…" : p.phase === "codes" ? "Finding the codes it addresses…" : p.phase === "embedding" ? "Setting up search by meaning…" : "Reading the document…")));
    const job = await watcher.promise;
    const dlg = document.querySelector("#dialogs dialog");
    if (dlg) { dlg.close(); dlg.remove(); }
    if (job.state === "done") {
      const added = (job.result && job.result.documents_added) || [];
      if (!added.length) { toast("The document could not be read: it has no text (a scan without text recognition?).", "warn", { ttl: 9000 }); navigate("#/sources"); return; }
      navigate(`#/doc/${encodeURIComponent(added[0].doc_id)}?tab=terms`);
    } else if (job.state === "error") showError({ message: job.error, kind: job.error_kind });
  } catch (e) {
    const dlg = document.querySelector("#dialogs dialog");
    if (dlg) { dlg.close(); dlg.remove(); }
    showError(e);
  }
  return done;
}
