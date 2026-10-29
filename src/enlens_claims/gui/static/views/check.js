// Check a hypothesis: the hypothesis box and the button are the page; the codebook tag is optional and quiet;
// everything else sits under "More options". The live progress of the running check is shown below.
import { featureEyebrow } from "../features.js";
import { App, api, h, icon, replace, clear, append, toast, showError, field, pageHead, navigate, watchJob, P, debounce, session } from "../lib.js";
import { checkOptions, pickCode } from "./options.js";
import { ProgressPanel } from "./progress.js";

export async function renderCheck(view, params, query) {
  const project = App.project;
  let info, docsRes;
  try {
    [info, docsRes] = await Promise.all([api("GET", `/api/projects/${P(project)}`), api("GET", `/api/projects/${P(project)}/documents`)]);
  } catch (e) { showError(e); info = { frameworks: [], search: null, passages: 0 }; docsRes = { documents: [] }; }
  const docs = docsRes.documents || [];
  const frameworks = info.frameworks || [];
  const draft = session("draft") || {};
  if (query.text) { draft.text = String(query.text).slice(0, 2000); session("draft", { ...draft }); }  // "Check a hypothesis about this…"
  const nDocs = docs.length;

  view.appendChild(pageHead("Check a hypothesis", { eyebrow: featureEyebrow("check"), sub: `The app looks through the ${nDocs} ${nDocs === 1 ? "document" : "documents"} of project “${project}”, the AI reads the excerpts that match, and every quote is verified against the document.` }));
  if (query.text) view.appendChild(h("p", { class: "muted small", style: { margin: "-6px 0 12px" } }, icon("info", { size: 12 }), " The words you chose are filled in below: turn them into the claim you want to check."));

  if (!App.modelConfigured()) {
    view.appendChild(h("div", { class: "notice notice-warn", style: { marginBottom: "16px" } }, icon("alert-triangle"),
      h("div", {}, h("p", {}, "No AI model is set up yet, so checks cannot run."), h("a", { href: "#/settings/model" }, "Set up the AI model"))));
  }
  if (!info.passages) {
    view.appendChild(h("div", { class: "notice notice-info", style: { marginBottom: "16px" } }, icon("info"),
      h("div", {}, h("p", {}, h("strong", {}, "Add documents first."), " A hypothesis is checked against the reports and papers in this project, and there are none yet."), h("a", { class: "btn btn-primary btn-sm", href: "#/sources", style: { marginTop: "6px" } }, icon("upload", { size: 13 }), "Add documents"))));
  }

  // --- the form
  const ta = h("textarea", { class: "textarea textarea-hyp", rows: 3, placeholder: "For example: Longer school days improve children's reading skills.", "aria-describedby": "hyp-hint", maxlength: 2000, id: "hyp" });
  ta.value = draft.text || "";
  const counter = h("span", { class: "muted" });
  const hint = h("div", { class: "hint-row", id: "hyp-hint" }, h("span", {}, "One sentence that could be true or false. ", h("span", { class: "faint" }, h("kbd", {}, "Ctrl"), "+", h("kbd", {}, "Enter"), " checks it.")), counter);

  // codebook tag (optional, quiet)
  const fwSelect = h("select", { class: "select input-sm", "aria-label": "Codebook" }, h("option", { value: "" }, "No codebook"), frameworks.map((f) => h("option", { value: f.name, selected: f.name === (draft.framework ?? "sdg") }, f.title || f.name)));
  let code = draft.code || "", codeDesc = draft.codeDesc || "";
  const codeBtn = h("button", { type: "button", class: "btn btn-sm code-btn", "aria-haspopup": "dialog" });
  const codeClear = h("button", { type: "button", class: "icon-btn", "aria-label": "Remove the code", hidden: !code, onClick: () => setCode("", "") }, icon("x", { size: 14 }));
  const suggestBox = h("div", { class: "suggest", "aria-live": "polite" });
  let suggestions = [];
  const fwLabel = () => (frameworks.find((f) => f.name === fwSelect.value) || {}).label || "code";
  const setCode = (c, d) => {
    code = c || ""; codeDesc = d || "";
    const fwName = fwSelect.value;
    replace(codeBtn, icon("search", { size: 13 }), h("span", { class: "code-txt" }, code ? [h("strong", {}, code), codeDesc ? ` · ${codeDesc}` : ""] : (fwName ? `Choose a ${fwLabel()}…` : "Choose a codebook first")));
    codeBtn.disabled = !fwName;
    codeClear.hidden = !code;
    session("draft", { text: ta.value, framework: fwSelect.value, code, codeDesc });
  };
  const fetchSuggestions = debounce(async () => {
    const text = ta.value.trim();
    const fwName = fwSelect.value;
    if (!fwName || text.length < 10) { suggestions = []; replace(suggestBox); return; }
    try {
      const r = await api("GET", `/api/projects/${P(project)}/suggest?text=${encodeURIComponent(text)}&framework=${P(fwName)}&n=5`);
      suggestions = r.codes || [];
    } catch (_) { suggestions = []; }
    replace(suggestBox, suggestions.length ? [icon("star", { size: 12 }), h("span", {}, "Suggested:"),
      suggestions.map((c) => h("button", { type: "button", class: "chip chip-btn", "aria-pressed": c.code === code ? "true" : "false", title: c.description, onClick: () => setCode(c.code, c.description) }, c.code))] : []);
  }, 350);
  codeBtn.addEventListener("click", async () => {
    const r = await pickCode({ project, framework: fwSelect.value, suggested: suggestions, current: code });
    if (r === undefined) return;
    if (r === null) setCode("", ""); else setCode(r.code, r.description);
    fetchSuggestions();
  });
  fwSelect.addEventListener("change", () => { setCode("", ""); fetchSuggestions(); });
  setCode(code, codeDesc);
  const tagRow = frameworks.length ? h("details", { class: "fold tag-row", open: !!code }, h("summary", {}, "Tag with a code from a codebook (optional)"),
    h("div", { class: "tag-body" }, h("p", { class: "muted small", style: { margin: "4px 0 8px" } }, "Like coding in NVivo or Atlas.ti: the hypothesis is filed under a code, and the AI reads the code's description alongside it."),
      h("div", { class: "row" }, fwSelect, codeBtn, codeClear), suggestBox)) : null;

  const options = checkOptions({ docs, search: info.search });
  const runBtn = h("button", { type: "submit", class: "btn btn-primary btn-lg" }, icon("flask", { size: 16 }), "Check this hypothesis");
  const lookBtn = h("button", { type: "button", class: "btn btn-lg", title: "See how the AI would split the hypothesis and which extra words it would search for, and change them, before the check runs" }, icon("eye", { size: 16 }), "Look before checking");
  let prepared = null;        // {text, parts: [{text, role}], terms: [[...]], split, editedParts, editedTerms} from "Look before checking"
  let prepareWatcher = null;
  const prepBox = h("section", { class: "section prep-box", "aria-label": "Parts and search words", hidden: true });
  const updateCounter = () => {
    const n = ta.value.trim().length;
    counter.textContent = n && n < 10 ? "A little longer, please" : "";
    runBtn.disabled = n < 10;
    lookBtn.disabled = n < 10;
    if (prepared && prepared.text !== ta.value.trim()) discardPrepared("The hypothesis changed, so the parts and words below no longer apply: look again, or check it as it is now.");
  };
  // a hypothesis with several claims in one sentence: offer to check each part separately, right here
  const splitQ = h("p", {}, "This hypothesis may have more than one part. Check each part separately?");
  const splitHint = h("div", { class: "notice notice-info split-hint", hidden: true }, icon("split", { size: 14 }),
    h("div", {}, splitQ, h("div", { class: "split-hint-ctl" })));
  const updateSplitHint = () => {
    const t = " " + ta.value.toLowerCase() + " ";
    const multi = ta.value.trim().length >= 10 && (/\s(and|but)\s/.test(t) || t.includes(";"));
    splitHint.hidden = !multi;
  };
  ta.addEventListener("input", () => { updateCounter(); updateSplitHint(); session("draft", { text: ta.value, framework: fwSelect.value, code, codeDesc }); fetchSuggestions(); });
  updateCounter();

  const decomposeSwitch = options.querySelector(".options-grid .switch-field");
  const hintSwitch = decomposeSwitch ? decomposeSwitch.cloneNode(true) : null;
  if (hintSwitch) {
    const a = decomposeSwitch.querySelector("input"), b = hintSwitch.querySelector("input");
    b.id = a.id + "-hint"; hintSwitch.querySelector("label").setAttribute("for", b.id);
    b.addEventListener("change", () => { a.checked = b.checked; a.dispatchEvent(new Event("change", { bubbles: true })); });
    a.addEventListener("change", () => { b.checked = a.checked; });
    splitHint.querySelector(".split-hint-ctl").appendChild(hintSwitch);
    // the question itself toggles the switch too (people click the words)
    splitQ.classList.add("split-q"); splitQ.setAttribute("role", "presentation");
    splitQ.addEventListener("click", () => { b.checked = !b.checked; b.dispatchEvent(new Event("change", { bubbles: true })); });
  }
  const form = h("form", { class: "hyp-form card" },
    h("div", { class: "field" }, h("label", { class: "field-label", for: "hyp" }, "Your hypothesis"), ta, hint, splitHint),
    h("div", { class: "btn-row", style: { margin: "4px 0 14px" } }, runBtn, lookBtn, h("span", { class: "muted small" }, "Takes a moment to a few minutes, depending on the AI model. “Look before checking” shows the parts and search words first, so you can change them.")),
    prepBox,
    tagRow,
    options);
  view.appendChild(form);
  updateSplitHint();
  if (suggestions.length === 0 && ta.value) fetchSuggestions();

  // --- "Look before checking": the parts and the AI's extra search words, editable, then "Check" sends them along
  function discardPrepared(why) {
    prepared = null;
    if (prepareWatcher) { prepareWatcher.stop(); prepareWatcher = null; }
    if (why) { replace(prepBox, h("div", { class: "notice notice-info" }, icon("info"), h("p", {}, why))); prepBox.hidden = false; }
    else { clear(prepBox); prepBox.hidden = true; }
    replace(runBtn, icon("flask", { size: 16 }), "Check this hypothesis");
  }
  // the split / other-wordings options changed after a look: the preview is out of date
  options.addEventListener("change", () => {
    if (!prepared) return;
    const o = options.values();
    if (o.decompose === prepared.decompose && o.expand === prepared.expand) return;
    const changed = o.decompose !== prepared.decompose ? (o.decompose ? "“Check each part separately” is now on" : "“Check each part separately” is now off") : (o.expand ? "“Also search for other words” is now on" : "“Also search for other words” is now off");
    const again = h("button", { class: "btn btn-sm btn-primary", type: "button", onClick: () => lookBtn.click() }, icon("eye", { size: 13 }), "Look again");
    prepared = null;
    replace(prepBox, h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("div", {}, h("p", {}, `${changed}, so the parts and words you looked at no longer apply. Look again to see the new ones, or check it as usual with the new options.`), h("div", { style: { marginTop: "8px" } }, again))));
    prepBox.hidden = false;
    replace(runBtn, icon("flask", { size: 16 }), "Check this hypothesis");
  });
  lookBtn.addEventListener("click", async () => {
    const text = ta.value.trim();
    if (text.length < 10) { ta.focus(); return; }
    const o = options.values();
    const body = { text, decompose: o.decompose, expand: o.expand };
    if (fwSelect.value && code) { body.framework = fwSelect.value; body.code = code; }
    lookBtn.disabled = true; runBtn.disabled = true;
    const panel = new ProgressPanel({ title: "Looking at your hypothesis", steps: ["terms"] });
    replace(prepBox, h("div", { class: "section-title" }, h("h2", {}, "Looking before checking"), h("span", { class: "muted" }, o.decompose ? "how the AI splits it, and which words it would add to the search" : o.expand ? "which words the AI would add to the search" : "the sentence as it will be checked")), panel.el);
    prepBox.hidden = false;
    try {
      const r = await api("POST", `/api/projects/${P(project)}/prepare`, body);
      prepareWatcher = watchJob(r.job.id, (job) => panel.update(job));
      const job = await prepareWatcher.promise;
      prepareWatcher = null;
      if (job.state === "done" && job.result) {
        prepared = { text, parts: (job.result.parts || []).map((p) => (typeof p === "string" ? { text: p, role: null } : { text: p.text, role: p.role || null })), terms: (job.result.terms || []).map((t) => [...(t || [])]), split: !!job.result.split, editedParts: false, editedTerms: false, expand: o.expand, decompose: o.decompose };
        if (!prepared.parts.length) prepared.parts = [{ text, role: null }];
        while (prepared.terms.length < prepared.parts.length) prepared.terms.push([]);
        drawPrepared();
      } else if (job.state === "cancelled") discardPrepared();
      else if (job.state === "error") { discardPrepared(); showError({ message: job.error, kind: job.error_kind }); }
    } catch (e) { discardPrepared(); showError(e); }
    updateCounter();
  });

  function drawPrepared() {
    const pr = prepared;
    const many = pr.parts.length > 1;
    const box = h("div", { class: "card card-plain prep-card" });
    const lead = h("p", { class: "muted small", style: { margin: "0 0 10px" } }, many
      ? `The AI would check this hypothesis as ${pr.parts.length} parts that must all hold. Change a part, remove one, or add one; each part is checked exactly as written here.`
      : (pr.split ? "The AI would check this hypothesis as one part." : "The hypothesis is checked as one sentence, as written here.") + (pr.expand ? " Below it are the extra words the AI would search for, besides the words of the hypothesis itself: remove any that do not fit, or add words your documents use." : ""));
    const list = h("ol", { class: "prep-parts" });
    const partRow = (i) => {
      const part = pr.parts[i];
      const input = h("textarea", { class: "textarea prep-part-input serif", rows: 1, "aria-label": many ? `Part ${i + 1}` : "The sentence to check", maxlength: 500 });
      input.value = part.text;
      const grow = () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight + 2}px`; };
      input.addEventListener("input", () => { part.text = input.value.replace(/\s*\n\s*/g, " "); pr.editedParts = true; grow(); });
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });   // one sentence per part; Enter must not start the check
      requestAnimationFrame(grow);
      const remove = h("button", { class: "icon-btn", type: "button", "aria-label": `Remove part ${i + 1}`, hidden: pr.parts.length < 2, onClick: () => { pr.parts.splice(i, 1); pr.terms.splice(i, 1); pr.editedParts = true; pr.editedTerms = true; drawPrepared(); } }, icon("x", { size: 14 }));
      const chips = h("div", { class: "chips term-chips", role: "group", "aria-label": `Extra search words for ${many ? `part ${i + 1}` : "the hypothesis"}` });
      const drawChips = () => {
        replace(chips, pr.terms[i].map((t, j) => h("span", { class: "chip chip-term" }, h("span", {}, t),
          h("button", { class: "chip-x", type: "button", "aria-label": `Remove the word ${t}`, onClick: () => { pr.terms[i].splice(j, 1); pr.editedTerms = true; drawChips(); } }, icon("x", { size: 11 })))),
        pr.terms[i].length ? null : h("span", { class: "muted small" }, "No extra words: only the words of the sentence itself are searched for."));
      };
      drawChips();
      const add = h("input", { class: "input input-sm prep-add", type: "text", placeholder: "add a word…", "aria-label": `Add a search word for ${many ? `part ${i + 1}` : "the hypothesis"}`, maxlength: 60 });
      const addBtn = h("button", { class: "btn btn-sm", type: "button", onClick: () => { const w = add.value.trim(); if (!w) { add.focus(); return; } if (!pr.terms[i].some((x) => x.toLowerCase() === w.toLowerCase())) pr.terms[i].push(w); pr.editedTerms = true; add.value = ""; drawChips(); add.focus(); } }, icon("plus", { size: 12 }), "Add");
      add.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addBtn.click(); } });
      return h("li", { class: "prep-part" },
        h("div", { class: "prep-part-row" }, input, remove),
        pr.expand ? h("div", { class: "prep-terms" }, h("span", { class: "muted small prep-terms-label" }, "Also search for:"), chips, h("div", { class: "prep-add-row" }, add, addBtn)) : null);
    };
    pr.parts.forEach((_, i) => list.appendChild(partRow(i)));
    const addPart = h("button", { class: "btn btn-sm", type: "button", disabled: pr.parts.length >= 6, onClick: () => { pr.parts.push({ text: "", role: null }); pr.terms.push([]); pr.editedParts = true; drawPrepared(); const inputs = prepBox.querySelectorAll(".prep-part-input"); const last = inputs[inputs.length - 1]; if (last) last.focus(); } }, icon("plus", { size: 13 }), "Add a part");
    const cancel = h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => discardPrepared() }, "Forget this and check as usual");
    append(box, [lead, list, h("div", { class: "btn-row", style: { marginTop: "8px" } }, addPart, cancel, h("span", { class: "muted small" }, "Then press “Check” above: it checks exactly these parts and words. Nothing is saved until then."))]);
    replace(prepBox, h("div", { class: "section-title" }, h("h2", {}, many ? `Checked as ${pr.parts.length} parts` : "Checked as one sentence"), h("span", { class: "muted" }, "change anything before the check runs")), box);
    prepBox.hidden = false;
    replace(runBtn, icon("flask", { size: 16 }), many ? `Check these ${pr.parts.length} parts` : "Check it like this");
  }

  // --- progress area
  const progressBox = h("section", { class: "section", "aria-label": "Progress", hidden: true });
  view.appendChild(progressBox);
  let watcher = null;
  let panel = null;

  const follow = (jobId, text) => {
    if (watcher) watcher.stop();
    panel = new ProgressPanel({ title: "Checking your hypothesis" });
    replace(progressBox, h("div", { class: "section-title" }, h("h2", {}, "Checking"), text ? h("span", { class: "muted serif" }, text) : null), panel.el);
    progressBox.hidden = false;
    const det = options.querySelector("details"); if (det) det.open = false;
    setTimeout(() => progressBox.scrollIntoView({ block: "start", behavior: "smooth" }), 50);
    session("activeCheck", jobId);
    runBtn.disabled = true; lookBtn.disabled = true;
    watcher = watchJob(jobId, (job) => panel.update(job));
    watcher.promise.then((job) => {
      session("activeCheck", null);
      updateCounter();
      if (job.state === "done" && job.result && job.result.hyp_id) {
        App.lastRun = { hyp_id: job.result.hyp_id, seconds: job.seconds, summary: ProgressPanel.summary(job.progress), model: (job.progress && job.progress.model) || null };
        session("draft", null);
        navigate(`#/h/${encodeURIComponent(job.result.hyp_id)}`);
      } else if (job.state === "cancelled") {
        toast("The check was stopped. Nothing was saved.", "info");
      } else if (job.state === "error") {
        showError({ message: job.error, kind: job.error_kind });
      }
    }).catch((e) => { session("activeCheck", null); updateCounter(); showError(e); });
  };

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = ta.value.trim();
    if (text.length < 10) { ta.focus(); return; }
    const o = options.values();
    const body = { text, decompose: o.decompose, expand: o.expand, k: o.k, per_doc: o.per_doc, semantic: o.semantic };
    if (o.doc_ids) body.doc_ids = o.doc_ids;
    if (fwSelect.value && code) { body.framework = fwSelect.value; body.code = code; }
    if (prepared && prepared.text === text) {
      const parts = prepared.parts.map((p) => ({ text: p.text.trim(), role: p.role }));
      const short = parts.findIndex((p) => p.text.length < 10);
      if (short >= 0) { toast(`Part ${short + 1} is too short: write a sentence that could be true or false, or remove it.`, "warn"); const inputs = prepBox.querySelectorAll(".prep-part-input"); if (inputs[short]) inputs[short].focus(); return; }
      body.parts = parts.map((p) => (p.role ? p : p.text));
      if (prepared.expand) body.terms = prepared.terms.map((t) => t.map((w) => w.trim()).filter(Boolean));
      body.edited = { parts: !!prepared.editedParts, terms: !!prepared.editedTerms };
      body.decompose = parts.length > 1;
    }
    runBtn.disabled = true;
    try {
      const r = await api("POST", `/api/projects/${P(project)}/checks`, body);
      const summary = prepared && prepared.text === text ? (prepared.parts.length > 1 ? `${prepared.parts.length} parts, as you set them` : "as you set it") : "";
      discardPrepared();
      follow(r.job.id, text + (summary ? ` (${summary})` : ""));
    } catch (err) {
      runBtn.disabled = false;
      showError(err);
    }
  });
  form.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); if (!runBtn.disabled) form.requestSubmit(); } });

  // a check started earlier (page reload, navigation) is still running: show it
  const active = query.job || session("activeCheck");
  if (active) {
    try {
      const job = await api("GET", `/api/jobs/${P(active)}`);
      if (job.kind === "check" && (job.state === "queued" || job.state === "running")) follow(job.id, job.title);
      else if (job.kind === "check" && job.state === "done" && query.job && job.result) navigate(`#/h/${encodeURIComponent(job.result.hyp_id)}`);
      else session("activeCheck", null);
    } catch (_) { session("activeCheck", null); }
  }

  view.appendChild(h("details", { class: "fold section", style: { marginTop: "20px" } }, h("summary", {}, "What happens when you check"),
    h("div", { class: "card card-plain", style: { marginTop: "8px" } },
      h("ol", { class: "plain-steps" },
        h("li", {}, h("strong", {}, "Search. "), "The app finds the excerpts of your documents that match the hypothesis (and, with search by meaning, excerpts that use other words for the same thing)."),
        h("li", {}, h("strong", {}, "Read. "), "The AI reads them and says for each one whether it supports, partly supports or contradicts the hypothesis, quoting the exact words."),
        h("li", {}, h("strong", {}, "Verify. "), "Every quote is checked against the document, word for word. An answer whose quote cannot be found in the document is rejected and the AI is asked again."),
        h("li", {}, h("strong", {}, "Answer. "), "You get an answer such as “supported”, “contradicted” or “mixed evidence”, with the quotes, so you can judge for yourself. “No evidence found” means just that: the documents may still say it in other words.")))));

  return () => { if (watcher) watcher.stop(); };
}
