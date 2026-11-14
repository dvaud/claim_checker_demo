// Hypotheses (0.17.0): one place to check hypotheses and read the answers. It replaces three pages (Check a
// hypothesis, Check several, Results): "Check several has no reason to be different from Check hypotheses".
//
// One box takes one hypothesis or many. Its mode follows the text: one line is one hypothesis (the split hint, "Look
// before checking", a codebook tag); two lines or more, or a CSV with a "hypothesis" column, are a list checked one
// after the other. The progress of the check the page follows is under the box, then every answer (history.js), with
// the checks still running or waiting their turn at the top. The evidence map is the place's other view (map.js).
import { featureEyebrow, withAI, viewTabs } from "../features.js";
import { App, api, h, icon, readsLine, replace, clear, append, toast, showError, fmt, pageHead, navigate, watchJob, P, debounce, session, emptyState, statusBadge, download, downloadLinks, button, iconButton, link, notice, tag, card, fold, fileButton, select, textarea, input as fieldInput, choice, latest, norm, readTextFile } from "../lib.js";
import { checkOptions, pickCode } from "./options.js";
import { ProgressPanel } from "./progress.js";
import { answersList } from "./history.js";
import { nearNotices, dropLines, saysSomething } from "./near.js";

const MIN_CHARS = 10;     // the shortest hypothesis a check accepts (claimcheck._clean)
const MAX_CHARS = 2000;   // and the longest
const MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");

// 0.18.8 (N3): who reads words taken from a document, by its AI setting (docrole.origin_floor keeps them to it)
export const WHO_READS = {
  cloud: "The AI you chose reads these words, as it reads any hypothesis.",
  local: "It is marked Only a local AI, so only a local model on this computer reads these words and the excerpts they are checked against; without one, you judge the excerpts yourself.",
  none: "It is marked No AI, so no model reads these words: ENLENS finds the excerpts with the words as written, and you judge them yourself.",
};
const LOST_DOC = "The document these words came from is no longer in this project, so nothing was started. Start again to check them as any hypothesis you type; the check will not be listed on a document's page.";

// One non-empty line is one hypothesis; two or more are a list (a CSV has its header and at least one row).
export function composerMode(text) {
  return String(text || "").split(/\r?\n/).filter((l) => l.trim()).length >= 2 ? "list" : "single";
}

export async function renderHypotheses(view, params, query) {
  const project = App.project;
  let info, docsRes;
  try {
    [info, docsRes] = await Promise.all([api("GET", `/api/projects/${P(project)}`), api("GET", `/api/projects/${P(project)}/documents`)]);
  } catch (e) { showError(e); info = { frameworks: [], search: null, passages: 0 }; docsRes = { documents: [] }; }
  const docs = docsRes.documents || [];
  const frameworks = info.frameworks || [];
  const threshold = App.settings().threshold ?? 0.6;
  const nDocs = docs.length;

  // one draft for both modes (0.17.0): a list written on the old Check several page comes along once
  const draft = session("draft") || {};
  const oldList = session("batchDraft");
  if (oldList && !draft.text) draft.text = String(oldList);
  if (oldList !== null) session("batchDraft", null);
  if (query.text) draft.text = String(query.text).slice(0, MAX_CHARS);   // "Check a hypothesis about this…"
  // 0.18.8 (N3): words from a document's text (a working document's Check against the corpus): the check remembers
  // the document, so the document's page lists it. Kept while the box holds text, forgotten once it is checked.
  // Opened without the document's words (later, from the sidebar), the box is no longer tied to the document.
  if (query.text && query.from) draft.fromDoc = String(query.from); else delete draft.fromDoc;
  let fromDoc = draft.fromDoc || null;
  session("draft", Object.keys(draft).length ? { ...draft } : null);

  // ---- the head: the place, its views, the downloads of every answer
  const downloads = downloadLinks([
    { text: "Excel (.xlsx)", title: "Three sheets: a summary, every excerpt read, and the evidence map", onClick: () => download(`/api/projects/${P(project)}/export.xlsx?threshold=${threshold}`).catch(showError) },
    { text: "CSV", note: "(for programmers)", title: "Technical CSV: ids, raw judgement words, UTC times", onClick: () => download(`/api/projects/${P(project)}/export.csv?threshold=${threshold}`).catch(showError) },
    // 0.18.7 (G5): the whole project for another program of qualitative analysis
    { text: "NVivo, ATLAS.ti, MAXQDA (.qdpx)", title: "A REFI-QDA project: the documents, the codes, the labels and judgements that count, and your notes as memos", onClick: () => download(`/api/projects/${P(project)}/export.qdpx?threshold=${threshold}`).catch(showError) },
  ], { label: "Download all:" });
  view.appendChild(pageHead("Hypotheses", { eyebrow: featureEyebrow("check"), sub: `Check one hypothesis or a list against the ${nDocs ? `${nDocs} ${nDocs === 1 ? "document" : "documents"}` : "documents"}, and judge each answer by its quotes.`, actions: downloads }));
  const tabs = viewTabs("hypotheses", "answers");
  if (tabs) view.appendChild(tabs);
  const mapTab = tabs ? tabs.querySelector('a[href="#/map"]') : null;
  const setMapTab = (batch) => { if (mapTab) mapTab.setAttribute("href", batch ? `#/map?batch=${encodeURIComponent(batch)}` : "#/map"); };

  if (query.text) view.appendChild(h("p", { class: "muted small hyp-chosen-note" }, icon("info", { size: 12 }), " The words you chose are filled in below: turn them into the claim you want to check."));
  // 0.18.8 (N3): while the box holds one hypothesis from a document, where the check will be listed and who reads it
  const fromNote = h("p", { class: "muted small hyp-chosen-note hyp-from-note", "aria-live": "polite", hidden: true });
  view.appendChild(fromNote);
  function drawFromNote(lost) {
    const d = fromDoc && composerMode(ta.value) === "single" ? docs.find((x) => x.doc_id === fromDoc) : null;
    fromNote.hidden = !d && !lost;
    if (lost) replace(fromNote, icon("info", { size: 12 }), ` ${LOST_DOC}`);
    else if (d) replace(fromNote, icon(d.ai_access === "cloud" ? "info" : "shield", { size: 12 }), ` The check will be listed on the page of ${d.title || d.file}. ${WHO_READS[d.ai_access] || WHO_READS.none}`);
    else clear(fromNote);
  }
  // the words are no longer tied to the document: a list, a hypothesis checked, an emptied box, or the document gone
  function untie(lost) {
    if (!fromDoc) return;
    fromDoc = null;
    saveDraft();
    drawFromNote(lost);
  }
  const lostDoc = (err) => err && err.status === 400 && /from_doc/.test(err.message || "");
  if (!App.modelConfigured()) {
    view.appendChild(notice({ kind: "attention", class: "hyp-setup-notice" },
      h("p", {}, "No AI model is set up yet, so checks cannot run."), link({ kind: "next", href: "#/settings/model" }, "Set up the AI model")));
  }
  if (!info.passages) {
    view.appendChild(notice({ kind: "info", class: "hyp-setup-notice" },
      h("p", {}, h("strong", {}, "Add documents first."), " A hypothesis is checked against the reports and papers in this project, and there are none yet."), h("p", {}, link({ kind: "next", href: "#/sources" }, "Add documents on the Documents page"))));
  }

  // ---- the box: one hypothesis or many
  const ta = textarea({ hyp: true, rows: 3, placeholder: "A hypothesis, or several: one per line", "aria-describedby": "hyp-hint", id: "hyp", spellcheck: "true" });
  ta.value = draft.text || "";
  const label = h("label", { class: "field-label", for: "hyp" }, "Your hypothesis");
  const kbd = h("span", { class: "faint hyp-kbd" }, h("kbd", {}, MAC ? "⌘" : "Ctrl"), "+", h("kbd", {}, "Enter"), " checks.");
  const singleHint = h("span", { class: "hyp-hint-single" }, "One sentence that could be true or false; for several, one per line. ", kbd);
  const listLine = h("span", { class: "hyp-list-line", role: "status", hidden: true });
  const counter = h("span", { class: "hyp-counter", role: "status" });
  const fileInput = h("input", { type: "file", accept: ".csv,.txt,.md,text/csv,text/plain", class: "visually-hidden", id: "hyp-file" });
  const fileBtn = fileButton({ kind: "quiet", icon: "upload", class: "hyp-file", for: "hyp-file", tabindex: "0", title: "A list, one hypothesis per line, or a spreadsheet saved as CSV with a column called “hypothesis” (and, if you like, a column “code” for a codebook tag)",
    onKeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } } }, fileInput, "Load a spreadsheet (CSV) or text file");
  const hint = h("div", { class: "hint-row", id: "hyp-hint" }, h("span", { class: "hyp-hint-main" }, singleHint, listLine), h("span", { class: "hyp-hint-side" }, counter, fileBtn));
  // the list as it will be checked, folded away: the count above says enough most of the time
  const listBody = h("div", { class: "hyp-list-body" });
  const listFold = fold({ class: "hyp-list-fold", hidden: true }, "Show the list", listBody);
  // 0.18 (roadmap N1): lines that say nearly the same, and hypotheses checked before that do (views/near.js)
  const nearBox = h("div", { class: "hyp-near", "aria-live": "polite" });

  // codebook tag (one hypothesis only: a list carries its codes in a CSV column)
  const fwSelect = select({ sm: true, "aria-label": "Codebook" }, h("option", { value: "" }, "No codebook"), frameworks.map((f) => h("option", { value: f.name, selected: f.name === (draft.framework ?? "sdg") }, f.title || f.name)));
  let code = draft.code || "", codeDesc = draft.codeDesc || "";
  const codeBtn = button({ sm: true, class: "code-btn", "aria-haspopup": "dialog" });
  const codeClear = iconButton({ icon: "x", size: 14, label: "Remove the code", hidden: !code, onClick: () => setCode("", "") });
  const suggestBox = h("div", { class: "suggest", "aria-live": "polite" });
  let suggestions = [];
  const fwLabel = () => (frameworks.find((f) => f.name === fwSelect.value) || {}).label || "code";
  const saveDraft = () => {
    if (!ta.value.trim() && fromDoc) { fromDoc = null; drawFromNote(); }   // an emptied box is a new hypothesis, not the document's words
    session("draft", ta.value || code ? { text: ta.value, framework: fwSelect.value, code, codeDesc, ...(fromDoc ? { fromDoc } : {}) } : null);
  };
  const setCode = (c, d) => {
    code = c || ""; codeDesc = d || "";
    const fwName = fwSelect.value;
    replace(codeBtn, icon("search", { size: 13 }), h("span", { class: "code-txt" }, code ? [h("strong", {}, code), codeDesc ? ` · ${codeDesc}` : ""] : (fwName ? `Choose a ${fwLabel()}…` : "Choose a codebook first")));
    codeBtn.disabled = !fwName;
    codeClear.hidden = !code;
    saveDraft();
  };
  const freshSuggestions = latest();   // only the newest request of suggestions is drawn
  const fetchSuggestions = debounce(async () => {
    const mine = freshSuggestions();
    const text = ta.value.trim();
    const fwName = fwSelect.value;
    if (mode !== "single" || !fwName || text.length < MIN_CHARS) { suggestions = []; replace(suggestBox); return; }
    try {
      const r = await api("GET", `/api/projects/${P(project)}/suggest?text=${encodeURIComponent(text)}&framework=${P(fwName)}&n=5`);
      suggestions = r.codes || [];
    } catch (_) { suggestions = []; }
    if (!mine()) return;
    // the suggested codes: a choice; the code chosen shows as chosen
    replace(suggestBox, suggestions.length ? [h("span", { id: "hyp-suggest-l" }, "Suggested:"),
      choice({ filter: true, sm: true, "aria-labelledby": "hyp-suggest-l", value: code || null,
        options: suggestions.map((c) => [c.code, c.code, null, c.description]),
        onPick: (v) => { const c = suggestions.find((x) => x.code === v); if (c) setCode(c.code, c.description); } })] : []);
  }, 350);
  codeBtn.addEventListener("click", async () => {
    const r = await pickCode({ project, framework: fwSelect.value, suggested: suggestions, current: code });
    if (r === undefined) return;
    if (r === null) setCode("", ""); else setCode(r.code, r.description);
    fetchSuggestions();
  });
  fwSelect.addEventListener("change", () => { setCode("", ""); fetchSuggestions(); });
  setCode(code, codeDesc);
  const tagRow = frameworks.length ? fold({ class: "tag-row", open: !!code }, "Tag with a code from a codebook (optional)",
    h("div", { class: "tag-body" }, h("p", { class: "muted small hyp-code-note" }, "Like coding in NVivo or Atlas.ti: the hypothesis is filed under a code, and the AI reads the code's description alongside it."),
      h("div", { class: "row" }, fwSelect, codeBtn, codeClear), suggestBox)) : null;

  const options = checkOptions({ docs, search: info.search });
  const runBtn = button({ kind: "main", type: "submit" });
  const lookBtn = button({ title: "See how the AI would split the hypothesis and which extra words it would search for, and change them, before the check runs" }, icon("eye", { size: 16 }), "Look before checking");
  // one AI mark for the row (the 0.17 rule): Check always reads with the AI; "Look before checking" is part of the same
  // check and says in its tooltip when it needs the AI
  const lookWrap = lookBtn;
  const drawLookTag = () => {
    const o = options.values();
    lookBtn.title = `See how the AI would split the hypothesis and which extra words it would search for, and change them, before the check runs. ${o.decompose || o.expand ? "Uses the AI." : "Needs no AI while both options below are off."}`;
  };
  const prepBox = h("section", { class: "section prep-box", "aria-label": "Parts and search words", hidden: true });

  // a hypothesis with several claims in one sentence: offer to check each part separately, right here
  const splitQ = h("p", {}, "This hypothesis may have more than one part. Check each part separately?");
  const splitHint = notice({ kind: "info", icon: "split", class: "split-hint", hidden: true },
    splitQ, h("div", { class: "split-hint-ctl" }));
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

  const form = card({ as: "form", class: "hyp-form hyp-compose" },
    h("div", { class: "field" }, label, ta, hint, listFold, nearBox, splitHint),
    h("div", { class: "btn-row hyp-actions" }, withAI(runBtn, lookWrap)),
    readsLine("the excerpts it needs", { class: "hyp-reads" }),
    prepBox,
    tagRow,
    options);
  view.appendChild(form);

  // ---- the state of the box
  let mode = composerMode(ta.value);
  let list = { text: null, items: [], ready: 0, short: 0, error: null };   // the list as the server read it last
  let previewing = null;      // the preview asked for, while it is on its way
  let busy = false;           // a check is being started
  let startedText = null;     // the text of the check the page follows, while it runs: Check would start it twice
  let prepared = null;        // {text, parts: [{text, role}], terms: [[...]], split, editedParts, editedTerms} from "Look before checking"
  let prepareWatcher = null;
  let looking = false;
  let near = { text: null, res: null };   // what the server found close, for the text it was asked about

  const singleLength = () => ta.value.trim().split(/\s+/).join(" ").length;
  function drawButtons() {
    const text = ta.value.trim();
    const same = startedText !== null && text === startedText;
    if (mode === "single") {
      const n = singleLength();
      const ok = n >= MIN_CHARS && n <= MAX_CHARS;
      counter.textContent = same ? "This one is being checked now (below)." : n && n < MIN_CHARS ? "A little longer, please" : n > MAX_CHARS ? `Under ${fmt.num(MAX_CHARS)} characters, please, or one hypothesis per line` : "";
      runBtn.disabled = !ok || busy || same;
      lookBtn.disabled = !ok || looking;
      const many = prepared && prepared.parts.length > 1;
      const before = near.text === ta.value && saysSomething(near.res);   // checked before: the offer is under the box
      replace(runBtn, icon("flask", { size: 16 }), !prepared ? (before ? "Check anyway" : "Check") : many ? `Check these ${prepared.parts.length} parts` : "Check it like this");
    } else {
      const fresh = list.text === ta.value;
      counter.textContent = same ? "This list is being checked now (below)." : "";
      runBtn.disabled = busy || same || (fresh && (!list.ready || !!list.error));
      replace(runBtn, icon("flask", { size: 16 }), list.ready && !list.error ? `Check ${list.ready}` : "Check");
    }
  }

  function applyMode() {
    const many = mode === "list";
    form.classList.toggle("is-list", many);
    label.textContent = many ? "Your hypotheses" : "Your hypothesis";
    singleHint.hidden = many;
    listLine.hidden = !many;
    listFold.hidden = !many || !list.items.length;
    lookWrap.hidden = many;
    if (tagRow) tagRow.hidden = many;
    if (many) {
      splitHint.hidden = true;
      if (prepared || !prepBox.hidden) discardPrepared();
      suggestions = []; replace(suggestBox);
      if (list.text === null) replace(listLine, icon("list-checks", { size: 13 }), " Reading your list…");
      untie();   // a list is checked by /batches, which keeps no document
    } else updateSplitHint();
    drawFromNote();
  }

  const updateSplitHint = () => {
    const t = " " + ta.value.toLowerCase() + " ";
    const multi = mode === "single" && ta.value.trim().length >= MIN_CHARS && (/\s(and|but)\s/.test(t) || t.includes(";"));
    splitHint.hidden = !multi;
  };
  const grow = () => { ta.style.height = "auto"; ta.style.height = `${ta.scrollHeight + 2}px`; };

  // ---- a list: the server reads it as the check will (one per line, or a CSV), and says what it found
  async function preview() {
    const text = ta.value;
    if (composerMode(text) !== "list") return;
    const ask = api("POST", `/api/projects/${P(project)}/batches/preview`, { text });
    previewing = ask;
    let r = null, err = null;
    try { r = await ask; } catch (e) { err = e; }
    if (previewing === ask) previewing = null;
    if (text !== ta.value) return;   // typed on meanwhile: the next preview counts
    if (err) list = { text, items: [], ready: 0, short: 0, error: err.message || String(err) };
    else {
      const items = r.items || [];
      // 0.14.3: a line the check would refuse (under 10 characters) is marked and left out of the count
      const ready = items.filter((it) => it.text.length >= MIN_CHARS).length;
      list = { text, items, ready, short: items.length - ready, error: null };
    }
    drawList();
    drawButtons();
    await lookNear();
  }
  const previewSoon = debounce(preview, 400);

  // ---- near-duplicates (0.18, roadmap N1): asked a moment after the typing stops (a list: once it is read), and
  // drawn under the box. Offers only: Check never waits for them, except once when it was pressed before they came.
  const freshNear = latest();
  async function lookNear() {
    const text = ta.value;
    const many = composerMode(text) === "list";
    const lines = many ? (list.text === text && !list.error ? list.items.map((it) => it.text) : null) : [text.trim()];
    const mine = freshNear();
    if (!lines || !lines.length || (!many && singleLength() < MIN_CHARS)) { near = { text, res: null }; replace(nearBox); drawButtons(); return near; }
    let res = null;
    try { res = await api("POST", `/api/projects/${P(project)}/hypotheses/similar`, { lines }); } catch (_) { res = null; }
    if (!mine() || text !== ta.value) return null;
    near = { text, res, lines };
    replace(nearBox, nearNotices(res, { lines, list: many, onKeep: keepLine }));
    drawButtons();
    return near;
  }
  const lookNearSoon = debounce(lookNear, 500);
  // "Check as one": keep line `keep` of the group, drop the others from the box (a toast can put them back)
  function keepLine(keep, group) {
    const was = ta.value;
    const now = list.text === was ? dropLines(was, list.items, group.filter((i) => i !== keep)) : null;
    if (now === null) { toast("Those lines could not be told apart in the box: remove the ones you don't want there.", "warn"); return; }
    const put = (t) => { ta.value = t; onText(); previewSoon.cancel(); preview(); };
    put(now);
    toast(`Kept line ${keep + 1}; ${group.length === 2 ? "the other was" : "the others were"} taken out.`, "ok", { button: { text: "Undo", onClick: () => put(was) } });
  }
  // before a check starts: an offer that was not on screen when Check was pressed is shown first, and Check goes on
  // when pressed again ("Check anyway")
  async function nearFirst(seen) {
    if (seen) return true;
    lookNearSoon.cancel();
    const n = near.text === ta.value ? near : await lookNear();
    return !(n && saysSomething(n.res));
  }

  function drawList() {
    const { items, ready, short, error } = list;
    if (error) replace(listLine, tag({ kind: "attention" }, error));
    else if (!items.length) replace(listLine, icon("list-checks", { size: 13 }), " No hypothesis found yet: write one per line, or load a CSV with a column called “hypothesis”.");
    else replace(listLine, icon("list-checks", { size: 13 }), ` ${ready} ${ready === 1 ? "hypothesis" : "hypotheses"}, checked one after the other`,
      short ? [" · ", tag({ kind: "attention" }, `${short} ${short === 1 ? "line is" : "lines are"} too short and will be skipped`)] : null);
    listFold.hidden = mode !== "list" || !items.length;
    const tooShort = (it) => it.text.length < MIN_CHARS;
    const coded = items.some((it) => it.code);
    replace(listBody,
      h("div", { class: "table-wrap batch-preview" }, h("table", { class: "table" },
        h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "#"), h("th", { scope: "col" }, "Hypothesis"), coded ? [h("th", { scope: "col" }, "Codebook"), h("th", { scope: "col" }, "Code")] : null)),
        h("tbody", {}, items.map((it, i) => h("tr", { class: tooShort(it) ? "batch-short" : null }, h("td", { class: "num muted" }, String(i + 1)),
          h("td", { class: "serif" }, it.text, tooShort(it) ? h("div", {}, tag({ kind: "attention", class: "small" }, `Too short: write it as a sentence (at least ${MIN_CHARS} characters). It will be skipped.`)) : null),
          coded ? [h("td", { class: "muted" }, it.framework || ""), h("td", { class: "mono" }, it.code || "")] : null))))),
      h("p", { class: "muted small hyp-csv-note" }, "Up to 500. A spreadsheet saved as CSV needs a column called “hypothesis” and may have a column “code” for a codebook tag."));
  }

  function onText() {
    grow();
    const now = composerMode(ta.value);
    if (now !== mode) { mode = now; applyMode(); }
    if (near.text !== ta.value) { replace(nearBox); freshNear(); }   // about other text: gone until asked again
    if (mode === "single") {
      updateSplitHint();
      fetchSuggestions();
      lookNearSoon();
      if (prepared && prepared.text !== ta.value.trim()) discardPrepared("The hypothesis changed, so the parts and words below no longer apply: look again, or check it as it is now.");
    } else previewSoon();
    saveDraft();
    drawButtons();
  }
  ta.addEventListener("input", onText);
  requestAnimationFrame(grow);
  fileInput.addEventListener("change", async () => {
    const f = fileInput.files && fileInput.files[0];
    if (!f) return;
    try { ta.value = await readTextFile(f); onText(); if (mode === "list") { previewSoon.cancel(); preview(); } toast(`Loaded ${f.name}.`, "ok", { ttl: 2500 }); }
    catch (e) { showError(e); }
    fileInput.value = "";
  });

  // ---- "Look before checking": the parts and the AI's extra search words, editable, then "Check" sends them along
  function discardPrepared(why) {
    prepared = null;
    if (prepareWatcher) { prepareWatcher.stop(); prepareWatcher = null; looking = false; }
    if (why) { replace(prepBox, notice({ kind: "info", live: "status" }, h("p", {}, why))); prepBox.hidden = false; }
    else { clear(prepBox); prepBox.hidden = true; }
    drawButtons();
  }
  // the split / other-wordings options changed: the AI mark of "Look before checking" follows them, and a look taken
  // before is out of date
  options.addEventListener("change", () => {
    drawLookTag();
    if (!prepared) return;
    const o = options.values();
    if (o.decompose === prepared.decompose && o.expand === prepared.expand) return;
    const changed = o.decompose !== prepared.decompose ? (o.decompose ? "“Check each part separately” is now on" : "“Check each part separately” is now off") : (o.expand ? "“Also search for other words” is now on" : "“Also search for other words” is now off");
    const again = button({ kind: "main", sm: true, onClick: () => lookBtn.click() }, icon("eye", { size: 13 }), "Look again");
    prepared = null;
    replace(prepBox, notice({ kind: "attention", live: "status" }, h("p", {}, `${changed}, so the parts and words you looked at no longer apply. Look again to see the new ones, or check it as usual with the new options.`), h("div", { class: "hyp-prepared-again" }, again)));
    prepBox.hidden = false;
    drawButtons();
  });
  drawLookTag();
  lookBtn.addEventListener("click", async () => {
    const text = ta.value.trim();
    if (mode !== "single" || text.length < MIN_CHARS) { ta.focus(); return; }
    const o = options.values();
    const body = { text, decompose: o.decompose, expand: o.expand };
    if (fwSelect.value && code) { body.framework = fwSelect.value; body.code = code; }
    if (fromDoc) body.from_doc = fromDoc;   // 0.18.8 (N3): its AI setting decides who proposes parts and words
    looking = true; drawButtons();
    const panel = new ProgressPanel({ title: "Looking at your hypothesis", steps: ["terms"] });
    replace(prepBox, h("div", { class: "section-title" }, h("h2", {}, "Looking before checking"), h("span", { class: "muted" }, o.decompose ? "how the AI splits it, and which words it would add to the search" : o.expand ? "which words the AI would add to the search" : "the sentence as it will be checked")), panel.el);
    prepBox.hidden = false;
    try {
      const r = await api("POST", `/api/projects/${P(project)}/prepare`, body);
      prepareWatcher = watchJob(r.job.id, (job) => panel.update(job));
      const job = await prepareWatcher.promise;
      prepareWatcher = null;
      looking = false;
      if (job.state === "done" && job.result) {
        prepared = { text, parts: (job.result.parts || []).map((p) => (typeof p === "string" ? { text: p, role: null } : { text: p.text, role: p.role || null })), terms: (job.result.terms || []).map((t) => [...(t || [])]), split: !!job.result.split, editedParts: false, editedTerms: false, expand: o.expand, decompose: o.decompose };
        if (!prepared.parts.length) prepared.parts = [{ text, role: null }];
        while (prepared.terms.length < prepared.parts.length) prepared.terms.push([]);
        drawPrepared();
      } else if (job.state === "cancelled") discardPrepared();
      else if (job.state === "error") { discardPrepared(); showError({ message: job.error, kind: job.error_kind }); }
    } catch (e) { looking = false; discardPrepared(); if (lostDoc(e)) untie(true); else showError(e); }
    drawButtons();
  });

  function drawPrepared() {
    const pr = prepared;
    const many = pr.parts.length > 1;
    const box = card({ as: "div", class: "prep-card" });
    const lead = h("p", { class: "muted small hyp-prepared-lead" }, many
      ? `The AI would check this hypothesis as ${pr.parts.length} parts that must all hold. Change a part, remove one, or add one; each part is checked exactly as written here.`
      : (pr.split ? "The AI would check this hypothesis as one part." : "The hypothesis is checked as one sentence, as written here.") + (pr.expand ? " Below it are the extra words the AI would search for, besides the words of the hypothesis itself: remove any that do not fit, or add words your documents use." : ""));
    const listEl = h("ol", { class: "prep-parts" });
    const partRow = (i) => {
      const part = pr.parts[i];
      const input = textarea({ class: "prep-part-input serif", rows: 1, "aria-label": many ? `Part ${i + 1}` : "The sentence to check", maxlength: 500 });
      input.value = part.text;
      const growPart = () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight + 2}px`; };
      input.addEventListener("input", () => { part.text = input.value.replace(/\s*\n\s*/g, " "); pr.editedParts = true; growPart(); });
      input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !(e.ctrlKey || e.metaKey)) e.preventDefault(); });   // one sentence per part; Enter must not start the check
      requestAnimationFrame(growPart);
      const remove = iconButton({ icon: "x", size: 14, label: `Remove part ${i + 1}`, hidden: pr.parts.length < 2, onClick: () => { pr.parts.splice(i, 1); pr.terms.splice(i, 1); pr.editedParts = true; pr.editedTerms = true; drawPrepared(); } });
      const chips = h("div", { class: "chips term-chips", role: "group", "aria-label": `Extra search words for ${many ? `part ${i + 1}` : "the hypothesis"}` });
      const drawChips = () => {
        replace(chips, pr.terms[i].map((t, j) => tag({ class: "chip-term" }, h("span", {}, t),
          iconButton({ icon: "x", sm: true, size: 11, class: "chip-x", label: `Remove the word ${t}`, onClick: () => { pr.terms[i].splice(j, 1); pr.editedTerms = true; drawChips(); } }))),
        pr.terms[i].length ? null : h("span", { class: "muted small" }, "No extra words: only the words of the sentence itself are searched for."));
      };
      drawChips();
      const add = fieldInput({ sm: true, class: "prep-add", placeholder: "add a word…", "aria-label": `Add a search word for ${many ? `part ${i + 1}` : "the hypothesis"}`, maxlength: 60 });
      const addBtn = button({ sm: true, onClick: () => { const w = add.value.trim(); if (!w) { add.focus(); return; } if (!pr.terms[i].some((x) => x.toLowerCase() === w.toLowerCase())) pr.terms[i].push(w); pr.editedTerms = true; add.value = ""; drawChips(); add.focus(); } }, icon("plus", { size: 12 }), "Add");
      add.addEventListener("keydown", (e) => { if (e.key === "Enter" && !(e.ctrlKey || e.metaKey)) { e.preventDefault(); addBtn.click(); } });
      return h("li", { class: "prep-part" },
        h("div", { class: "prep-part-row" }, input, remove),
        pr.expand ? h("div", { class: "prep-terms" }, h("span", { class: "muted small prep-terms-label" }, "Also search for:"), chips, h("div", { class: "prep-add-row" }, add, addBtn)) : null);
    };
    pr.parts.forEach((_, i) => listEl.appendChild(partRow(i)));
    const addPart = button({ sm: true, disabled: pr.parts.length >= 6, onClick: () => { pr.parts.push({ text: "", role: null }); pr.terms.push([]); pr.editedParts = true; drawPrepared(); const inputs = prepBox.querySelectorAll(".prep-part-input"); const last = inputs[inputs.length - 1]; if (last) last.focus(); } }, icon("plus", { size: 13 }), "Add a part");
    const cancel = button({ kind: "quiet", sm: true, onClick: () => discardPrepared() }, "Forget this and check as usual");
    append(box, [lead, listEl, h("div", { class: "btn-row hyp-part-actions" }, addPart, cancel, h("span", { class: "muted small" }, "Then press “Check” above: it checks exactly these parts and words. Nothing is saved until then."))]);
    replace(prepBox, h("div", { class: "section-title" }, h("h2", {}, many ? `Checked as ${pr.parts.length} parts` : "Checked as one sentence"), h("span", { class: "muted" }, "change anything before the check runs")), box);
    prepBox.hidden = false;
    drawButtons();
  }

  // ---- progress: the check or the list the page follows; the answers below
  const progressBox = h("section", { class: "section hyp-progress", "aria-label": "Progress", hidden: true });
  view.appendChild(progressBox);
  const answersBox = h("section", { class: "section hyp-answers", "aria-labelledby": "answers-title" });
  view.appendChild(answersBox);
  let following = null;       // {id, kind, text}
  let watcher = null;
  let answers = null;

  function stopFollowing() {
    if (watcher) { watcher.stop(); watcher = null; }
    following = null;
  }
  const showProgress = (title, sub, panel) => {
    replace(progressBox, h("div", { class: "section-title" }, h("h2", {}, title), sub ? h("span", { class: "muted serif" }, sub) : null), panel.el);
    progressBox.hidden = false;
    const det = options.querySelector("details"); if (det) det.open = false;
    setTimeout(() => progressBox.scrollIntoView({ block: "start", behavior: "smooth" }), 50);
  };
  // the draft is forgotten once what it held is checked (not when another hypothesis was written meanwhile). A job's
  // title is the first 120 characters of its hypothesis.
  const forgetDraft = (text) => {
    const d = norm((session("draft") || {}).text), t = norm(text);
    if (d && t && (d === t || (t.length >= 100 && d.startsWith(t)))) session("draft", null);
  };
  const ended = (id) => {
    if (!following || following.id !== id) return false;
    following = null; watcher = null; startedText = null;
    drawButtons();
    if (answers) answers.refresh();
    return true;
  };

  // `text`: the hypothesis; `how`: how it is checked, when the person set its parts and words
  function followCheck(jobId, text, how) {
    stopFollowing();
    following = { id: jobId, kind: "check", text };
    const panel = new ProgressPanel({ title: "Checking your hypothesis" });
    showProgress("Checking", text + (how ? ` (${how})` : ""), panel);
    session("activeCheck", jobId); session("activeBatch", null);
    const w = watchJob(jobId, (job) => panel.update(job));
    watcher = w;
    w.promise.then((job) => {
      session("activeCheck", null);
      if (!ended(jobId)) return;
      if (job.state === "done" && job.result && job.result.hyp_id) {
        App.lastRun = { hyp_id: job.result.hyp_id, seconds: job.seconds, summary: ProgressPanel.summary(job.progress), model: (job.progress && job.progress.model) || null };
        forgetDraft(text);
        navigate(`#/h/${encodeURIComponent(job.result.hyp_id)}`);
      } else if (job.state === "cancelled") {
        toast("The check was stopped. Nothing was saved.", "info");
      } else if (job.state === "error") {
        showError({ message: job.error, kind: job.error_kind });
      }
    }).catch((e) => { session("activeCheck", null); ended(jobId); showError(e); });
  }

  function followBatch(jobId, text) {
    stopFollowing();
    following = { id: jobId, kind: "batch", text };
    const panel = new ProgressPanel({ title: "Checking the hypotheses" });
    showProgress("Checking", "you can leave this page; the checks continue", panel);
    session("activeBatch", jobId); session("activeCheck", null);
    let index = null;
    const w = watchJob(jobId, (job) => {
      panel.update(job);
      // each hypothesis checked joins the answers below as it is done
      const i = job.progress && job.progress.batch ? job.progress.batch.index : null;
      if (i !== index) { index = i; if (answers && i !== null) answers.refresh(); }
    });
    watcher = w;
    w.promise.then((job) => {
      session("activeBatch", null);
      if (!ended(jobId)) return;
      if (text) forgetDraft(text);
      const st = progressBox.querySelector(".section-title"); if (st) replace(st, h("h2", {}, job.state === "done" ? "Finished" : "Stopped"));
      summary(job);
    }).catch((e) => { session("activeBatch", null); ended(jobId); showError(e); });
  }

  // what a list came to: how many were checked, the answers, what could not be checked
  async function summary(job) {
    const r = job.result || {};
    const errors = r.errors || [];
    const checked = r.checked || [];
    let rows = [];
    if (r.batch_id) { try { rows = (await api("GET", `/api/projects/${P(project)}/hypotheses?batch=${encodeURIComponent(r.batch_id)}`)).hypotheses || []; } catch (_) { rows = []; } }
    const show = r.batch_id ? button({ kind: "main", sm: true, onClick: async () => { if (answers) await answers.showBatch(r.batch_id); answersBox.scrollIntoView({ block: "start", behavior: "smooth" }); } }, icon("history", { size: 14 }), "Show only these answers") : null;
    const sumCard = card({ as: "div", class: "hyp-summary-card", title: job.state === "done" ? "All done" : job.state === "cancelled" ? "Stopped" : "Something went wrong", action: show },
      h("div", { class: "kv-grid" },
        h("div", { class: "kv" }, h("dt", {}, "Checked"), h("dd", {}, `${checked.length} of ${r.total ?? "?"}`)),
        errors.length ? h("div", { class: "kv" }, h("dt", {}, "Could not be checked"), h("dd", {}, String(errors.length))) : null,
        h("div", { class: "kv" }, h("dt", {}, "Time"), h("dd", {}, fmt.secs(job.seconds)))),
      rows.length ? h("ul", { class: "batch-answers" }, rows.map((x) => h("li", {}, link({ kind: "title", serif: true, href: `#/h/${encodeURIComponent(x.hyp_id)}` }, x.text || x.claim), " ", statusBadge(x.status, { short: true })))) : null,
      r.stopped ? notice({ kind: "attention", live: "status", class: "hyp-summary-notice" }, h("p", {}, r.stopped)) : null,
      job.state === "error" ? notice({ kind: "error", class: "hyp-summary-notice" }, h("p", {}, job.error_kind === "backend" ? "The AI model stopped answering." : "The checks could not continue."), fold({}, "Technical details", h("div", { class: "mono small" }, job.error || "")), job.error_kind === "backend" ? link({ href: "#/settings" }, "Check the AI model in Settings") : null) : null,
      errors.length ? fold({ open: true, class: "hyp-errors-fold" }, `Hypotheses that could not be checked (${errors.length})`,
        h("ul", { class: "batch-errors" }, errors.map((e) => h("li", {}, h("span", { class: "muted" }, `#${e.index ?? "?"} `), h("span", { class: "serif" }, e.text), " — ", e.error)))) : null);
    progressBox.appendChild(sumCard);
    progressBox.hidden = false;
    if (job.state === "done") toast(`All done: ${checked.length} checked${errors.length ? `, ${errors.length} could not be checked` : ""}.`, errors.length ? "warn" : "ok");
  }

  // ---- checking: one hypothesis, or the list
  async function checkOne(seen) {
    const text = ta.value.trim();
    const n = singleLength();
    if (n < MIN_CHARS || n > MAX_CHARS) { ta.focus(); return; }
    busy = true; drawButtons();
    const go = await nearFirst(seen);
    busy = false; drawButtons();
    if (!go || text !== ta.value.trim()) return;
    const o = options.values();
    const body = { text, decompose: o.decompose, expand: o.expand, k: o.k, per_doc: o.per_doc, semantic: o.semantic };
    if (o.doc_ids) body.doc_ids = o.doc_ids;
    if (fwSelect.value && code) { body.framework = fwSelect.value; body.code = code; }
    if (fromDoc) body.from_doc = fromDoc;   // 0.18.8 (N3): listed on the document's page, read as its AI setting allows
    if (prepared && prepared.text === text) {
      const parts = prepared.parts.map((p) => ({ text: p.text.trim(), role: p.role }));
      const short = parts.findIndex((p) => p.text.length < MIN_CHARS);
      if (short >= 0) { toast(`Part ${short + 1} is too short: write a sentence that could be true or false, or remove it.`, "warn"); const inputs = prepBox.querySelectorAll(".prep-part-input"); if (inputs[short]) inputs[short].focus(); return; }
      body.parts = parts.map((p) => (p.role ? p : p.text));
      if (prepared.expand) body.terms = prepared.terms.map((t) => t.map((w) => w.trim()).filter(Boolean));
      body.edited = { parts: !!prepared.editedParts, terms: !!prepared.editedTerms };
      body.decompose = parts.length > 1;
    }
    busy = true; drawButtons();
    try {
      const r = await api("POST", `/api/projects/${P(project)}/checks`, body);
      const how = prepared && prepared.text === text ? (prepared.parts.length > 1 ? `${prepared.parts.length} parts, as you set them` : "as you set it") : "";
      busy = false;
      startedText = text;
      untie();   // the next hypothesis written here is not the document's
      discardPrepared();
      followCheck(r.job.id, text, how);
    } catch (err) { busy = false; if (lostDoc(err)) untie(true); else showError(err); }
    drawButtons();
  }

  async function checkList(seen) {
    if (list.text !== ta.value) {   // checked before the count came: count first (a preview on its way may be for older text)
      previewSoon.cancel();
      if (previewing) { try { await previewing; } catch (_) { /* counted again below */ } }
      if (list.text !== ta.value) await preview();
    }
    if (list.text !== ta.value || list.error) return;
    const todo = list.items.filter((it) => it.text.length >= MIN_CHARS);
    if (!todo.length) { toast("No hypothesis in the list is long enough to check: write each as a sentence.", "warn"); return; }
    if (!(await nearFirst(seen))) return;
    const o = options.values();
    const body = { items: todo, decompose: o.decompose, expand: o.expand, k: o.k, per_doc: o.per_doc, semantic: o.semantic };
    if (o.doc_ids) body.doc_ids = o.doc_ids;
    busy = true; drawButtons();
    try {
      const r = await api("POST", `/api/projects/${P(project)}/batches`, body);
      busy = false;
      startedText = ta.value.trim();
      followBatch(r.job.id, startedText);
    } catch (e) { busy = false; showError(e); }
    drawButtons();
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (runBtn.disabled) return;
    // what was found close is on screen already when Check is pressed: it checks anyway (near.js)
    const seen = near.text === ta.value;
    if (composerMode(ta.value) === "list") checkList(seen); else checkOne(seen);
  });
  form.addEventListener("keydown", (e) => {
    // Ctrl/⌘+Enter checks, in either mode; Enter alone makes a new line
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); if (!runBtn.disabled) form.requestSubmit(); return; }
    // Enter in a small field (a search word, the document filter) must not start a check
    if (e.key === "Enter" && e.target.tagName === "INPUT") e.preventDefault();
  });

  applyMode();
  drawButtons();
  if (mode === "list") preview(); else if (ta.value) { fetchSuggestions(); lookNearSoon(); }

  // ---- the answers, with the checks still running at the top
  answers = await answersList(answersBox, query, { following: () => (following ? following.id : null), onBatch: setMapTab, write: () => { ta.focus(); ta.scrollIntoView({ block: "center", behavior: "smooth" }); } });

  // a check or a list started earlier (page reload, navigation, a row above, the sidebar) and still running: follow it
  const asked = [query.job, session("activeCheck"), session("activeBatch")].filter(Boolean);
  for (const id of [...new Set(asked)]) {
    let job;
    try { job = await api("GET", `/api/jobs/${P(id)}`); } catch (_) { job = null; }
    if (!job || (job.kind !== "check" && job.kind !== "batch")) {
      if (id === session("activeCheck")) session("activeCheck", null);
      if (id === session("activeBatch")) session("activeBatch", null);
      continue;
    }
    const live = job.state === "queued" || job.state === "running";
    if (live) {
      if (job.kind === "check") followCheck(job.id, job.title); else followBatch(job.id, null);
      answers.refresh();
      break;
    }
    if (job.kind === "check") session("activeCheck", null); else session("activeBatch", null);
    if (id !== query.job) continue;
    if (job.kind === "check" && job.state === "done" && job.result && job.result.hyp_id) { navigate(`#/h/${encodeURIComponent(job.result.hyp_id)}`); break; }
    // a check that was stopped or went wrong, or a list that has ended: how it ended, as it was shown while it ran
    const panel = new ProgressPanel({ title: job.kind === "batch" ? "Checking the hypotheses" : "Checking your hypothesis" });
    replace(progressBox, h("div", { class: "section-title" }, h("h2", {}, job.state === "done" ? "Finished" : job.state === "cancelled" ? "Stopped" : "Did not work"), job.kind === "check" ? h("span", { class: "muted serif" }, job.title) : null), panel.el);
    progressBox.hidden = false;
    panel.update(job);
    if (job.kind === "batch") summary(job);
    break;
  }

  view.appendChild(fold({ class: "section hyp-how-fold" }, "What happens when you check",
    card({ as: "div", class: "hyp-how-card" },
      h("ol", { class: "plain-steps" },
        h("li", {}, h("strong", {}, "Search. "), "The app finds the excerpts of your documents that match the hypothesis (and, with search by meaning, excerpts that use other words for the same thing)."),
        h("li", {}, h("strong", {}, "Read. "), "The AI reads them and says for each one whether it supports, partly supports or contradicts the hypothesis, quoting the exact words."),
        h("li", {}, h("strong", {}, "Verify. "), "Every quote is checked against the document, word for word. An answer whose quote cannot be found in the document is rejected and the AI is asked again."),
        h("li", {}, h("strong", {}, "Answer. "), "You get an answer such as “supported”, “contradicted” or “mixed evidence”, with the quotes, so you can judge for yourself. “No evidence found” means just that: the documents may still say it in other words."),
        h("li", {}, h("strong", {}, "A list. "), "Several hypotheses, one per line or from a spreadsheet, are checked one after the other, each with its own answer. You can leave the page meanwhile.")))));

  return () => { stopFollowing(); if (prepareWatcher) prepareWatcher.stop(); previewSoon.cancel(); lookNearSoon.cancel(); if (answers) answers.stop(); };
}
