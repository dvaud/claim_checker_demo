// 0.16 (roadmap K1): your own codebook. The list of codebooks, a new one (fresh, from the themes found, a copy, or a
// CSV file), and the editor: codes with a definition, when to use them and when not, the words they are matched by
// and example quotes from the documents, in groups; drag (or Move up / down) to reorder, rename, merge, split and
// remove codes. *Try it* counts what the keyword pass would pick, without AI. Saving keeps the codebook as it was
// (History) and writes the changes in the research log; labels follow renames and merges, and wait under *Removed
// codes* when a code is removed. An edit changes no result by itself. K1's optional AI part: *Draft from the examples*
// offers a definition, when to use it and when not, from the passages that hold a code's examples only; taken, the
// words are marked *AI draft* until you rewrite them.
import { featureEyebrow, viewTabs, withAI } from "../features.js";
import { App, api, h, icon, replace, clear, toast, showError, failedLoad, fmt, pageHead, P, plural, confirmDialog, download,
  dialog, field, switchControl, watchJob, emptyState, shortTitle, session, button, iconButton, downloadButton, link, menu, notice, card, tag, input, select, textarea, choice, optionCards, readsLine, aiWhere, inset, workState, personMark, compare, readTextFile, setBusy } from "../lib.js";
import { forgetFrameworks } from "./options.js";
import { showHistory, askWhy } from "./versions.js";
import { shareBar } from "./share.js";   // 0.18 (L1)
import { decisionCard } from "../lib.js";   // roles (H8)
import { OWNER_API, codebookOfferText } from "./owner-state.js";   // roles (H8)

const WHERE = { project: ["This project", "folder"], home: ["All projects", "layers"], bundled: ["Ships with ENLENS", "library"] };
const drafts = new Map();   // unsaved edits, kept while you look at another page: `${project}:${name}` -> {st, merges}
// K1 (the optional AI part): the fields a draft from the examples fills, and those still the AI's words
const FIELDS_OF_DRAFT = ["description", "include", "exclude"];
const DRAFT_LABEL = { description: "the definition", include: "when to use it", exclude: "when not to use it" };
const flat = (v) => String(v || "").split(/\s+/).filter(Boolean).join(" ");
function draftFields(c) {
  const d = c && c.ai_draft;
  return d ? FIELDS_OF_DRAFT.filter((f) => flat(d[f]) && flat(d[f]) === flat(c[f])) : [];
}
const capital = (t) => t.charAt(0).toUpperCase() + t.slice(1);
function listWords(xs) { return xs.length < 2 ? (xs[0] || "") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`; }

function whereBadge(where) {
  const [t, ic] = WHERE[where] || [where, "circle"];
  return tag({ class: `cb-where cb-where-${where}`, icon: ic }, t);
}

// ---------------------------------------------------------------------------------------------
// the list
// ---------------------------------------------------------------------------------------------
export async function renderCodebooks(view) {
  const project = App.project;
  const base = `/api/projects/${P(project)}/codebooks`;
  const newBtn = button({ kind: "main", onClick: () => newCodebook() }, icon("plus", { size: 14 }), "New codebook");
  view.appendChild(pageHead("Codes", {
    eyebrow: featureEyebrow("codebooks"),
    sub: "Your codebooks: the codes looked for in the documents (By document, and a document’s Codes panel), and that a hypothesis can be tagged with. A codebook stays a CSV file, so it still opens in a spreadsheet.",
    actions: newBtn,
  }));
  view.appendChild(viewTabs("codes", "codebooks"));   // 0.17.0: Codebooks is a view of Codes
  const box = h("div", { class: "cb-list" });
  view.appendChild(box);
  let data;
  try { data = await api("GET", base); } catch (e) { failedLoad(box, e); return; }
  for (const b of data.problems || []) {
    box.appendChild(notice({ kind: "attention" }, h("p", {}, `The codebook file ${b.file} (${b.source === "home" ? "for all projects" : "in this project"}) cannot be used: ${b.error}`)));
  }
  const own = data.codebooks.filter((c) => c.where !== "bundled");
  const ships = data.codebooks.filter((c) => c.where === "bundled");
  // 0.17.0 (design guide): the title is the link (a title link, not serif); the rest of the card opens it too
  const cardItem = (c) => h("li", { class: "cb-card", onClick: (e) => { if (!e.target.closest("a")) location.hash = `#/codebooks/${encodeURIComponent(c.name)}`; } },
    h("div", { class: "cb-card-main" },
      link({ kind: "title", class: "cb-card-title", href: `#/codebooks/${encodeURIComponent(c.name)}` }, c.title || c.name),
      h("span", { class: "cb-card-sub" }, `${plural(c.codes, "code")}${c.groups ? ` in ${plural(c.groups, "group")}` : ""} · each is called “${c.label}”`),
      h("span", { class: "cb-card-use" }, whereBadge(c.where),
        c.labels ? h("span", { class: "muted" }, plural(c.labels, "label")) : null,
        c.checks ? h("span", { class: "muted" }, plural(c.checks, "check")) : null,
        c.profile_default ? tag({}, icon("tag", { size: 11 }), "Profile uses it") : null)),
    h("span", { class: "cb-card-go", "aria-hidden": "true" }, icon("chevron-right", { size: 16 })));
  if (!own.length) {
    box.appendChild(card({ as: "div", class: "cb-start", title: "Make a codebook of your own" },
      h("p", {}, "Start fresh, from the themes already found in the documents, as a copy of the SDG targets, or from a spreadsheet. Each code gets a definition, when to use it and when not, the words it is matched by and examples from the documents."),
      h("div", { class: "btn-row" }, button({ kind: "main", onClick: () => newCodebook("themes") }, icon("shapes", { size: 14 }), "Start from the themes"),
        button({ onClick: () => newCodebook("fresh") }, icon("plus", { size: 14 }), "Start fresh"))));
  } else {
    box.append(h("h2", { class: "cb-h2" }, "Your codebooks"), h("ul", { class: "cb-cards" }, own.map(cardItem)));
  }
  box.append(h("h2", { class: "cb-h2" }, "Ship with ENLENS"), h("ul", { class: "cb-cards" }, ships.map(cardItem)),
    h("p", { class: "muted small" }, "To change one of these, open it and make a copy."));
}

// "New codebook": its name, where it is kept, and how it starts. `start`: preselected way to start.
export async function newCodebook(start = "fresh", opts = {}) {
  const project = App.project;
  const base = `/api/projects/${P(project)}/codebooks`;
  const title = input({ maxlength: 200, placeholder: "e.g. Remote work and wellbeing", value: opts.title || "" });
  const name = input({ maxlength: 40, placeholder: "e.g. remote_work" });
  let nameTouched = false;
  name.addEventListener("input", () => { nameTouched = true; });
  title.addEventListener("input", () => { if (!nameTouched) name.value = title.value.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40); });
  let where = "project";
  const whereSel = choice({ label: "Kept", value: where, options: [["project", "With this project"], ["home", "With all my projects"]], onPick: (w) => { where = w; } });
  const STARTS = [["fresh", "Start fresh", "An empty codebook: add codes and groups yourself.", "plus"],
    ["themes", "From the themes", "The themes found in the documents become draft codes: short names made of their names, their descriptions, key terms and best passages. Tick the ones to keep.", "shapes"],
    ["theory", "From a theory document", "The concepts of a theory you read the documents through (terms it defines, its headings, words it uses often) become draft codes, each with its definition quoted from the theory and its page. Examples come only from the evidence, when you tick them. Without AI; the AI can draft more when you ask.", "book-marked"],
    ["copy", "A copy of a codebook", "The SDG targets or one of yours, to change.", "copy"],
    ["csv", "From a CSV file", "Columns code and description (and group, group_name, when_to_use, when_not_to_use, keywords, examples).", "upload"]];
  let fws = [];
  try { fws = (await api("GET", base)).codebooks; } catch (_) { /* the copy choice lists none */ }
  const copySel = select({ "aria-label": "Codebook to copy" }, fws.map((f) => h("option", { value: f.name, selected: f.name === opts.of }, `${f.title || f.name} (${f.codes} codes)`)));
  const file = input({ type: "file", accept: ".csv,text/csv", "aria-label": "CSV file" });
  const extra = h("div", { class: "cb-start-extra" });
  const drawExtra = () => { replace(extra, start === "copy" ? field("Copy of", copySel) : start === "csv" ? field("CSV file", file) : null); };
  // how to start: option cards (docs/DESIGN.md 4.7), one under the other
  const startSel = optionCards({ label: "Start", class: "cb-start-pick", value: start, options: STARTS.map(([k, t, sub, ic]) => ({ value: k, title: t, text: sub, icon: ic })),
    onPick: (k) => {
      start = k; drawExtra();
      const go = startSel.closest("dialog") && startSel.closest("dialog").querySelector(".dialog-actions .btn-primary");
      if (go) go.textContent = start === "themes" || start === "theory" ? "Next" : "Create";   // themes, theory: a second step to tick them
    } });
  drawExtra();
  const err = h("div", { class: "field-error", role: "alert" });
  const r = await dialog({
    title: "New codebook", wide: true,
    body: h("div", { class: "stack" }, h("div", { class: "fields-2" }, field("Title", title), field("Short name", name, { help: "letters, digits, - and _ (the file's name)" })),
      h("div", { class: "field" }, h("span", { class: "field-label" }, "Kept"), whereSel, h("div", { class: "field-help" }, "All my projects: every project can use it, and a change shows in each. A project can still take its own copy later.")),
      h("div", { class: "field" }, h("span", { class: "field-label" }, "Start"), startSel, extra), err),
    actions: [{ text: "Cancel", value: null }, { text: start === "themes" || start === "theory" ? "Next" : "Create", value: true, primary: true, onClick: async () => {
      err.textContent = "";
      if (!title.value.trim()) { err.textContent = "Give the codebook a title."; title.focus(); return false; }
      return true;
    } }],
    onOpen: () => title.focus(),
  });
  if (!r) return;
  const body = { name: name.value.trim() || title.value.trim(), title: title.value.trim(), where, start, source: {} };
  if (start === "copy") body.source = { of: copySel.value };
  if (start === "csv") {
    const f = file.files && file.files[0];
    if (!f) { toast("Choose a CSV file.", "info"); return; }
    body.source = { csv: await readTextFile(f) };
  }
  if (start === "themes") {
    const picked = await pickThemes(where === "home");
    if (!picked) return;
    body.source = { codes: picked };
  }
  if (start === "theory") {   // 0.18.1 (K2 part 2)
    const picked = await pickTheory();
    if (!picked) return;
    body.source = picked;
  }
  try {
    const res = await api("POST", base, body);
    forgetFrameworks();
    toast("Codebook made. The research log says so.", "ok");
    location.hash = `#/codebooks/${encodeURIComponent(res.codebook.name)}`;
  } catch (e) { showError(e); }
}

// The themes found (this project's, and with `all` every project's) to start from: tick the ones to keep. 0.16.1:
// each code name is words of the theme's name, as short as the documents allow (codenames.py); − and + make it less
// or more specific before you edit it.
async function pickThemes(all) {
  const base = `/api/projects/${P(App.project)}/codebooks/sources`;
  let runs;
  try { runs = (await api("GET", `${base}${all ? "?all=1" : ""}`)).runs; } catch (e) { showError(e); return null; }
  if (!runs.length) {
    await dialog({ title: "No themes yet", body: h("div", {}, h("p", {}, "Find the themes of the documents first (Themes, in the sidebar): they take seconds and need no AI."),
      link({ kind: "next", href: "#/themes" }, "Go to Themes")) });
    return null;
  }
  const boxes = [];
  const list = h("div", { class: "cb-theme-pick" });
  runs.forEach((run, i) => {
    const fs = h("fieldset", { class: "cb-run" }, h("legend", {}, `${run.here ? "Themes" : `Themes of ${run.project}`} found on ${fmt.dateShort(run.created_at)}`,
      h("span", { class: "muted small" }, ` · ${plural(run.themes.length, "theme")}`)));
    for (const t of run.themes) {
      const cb = h("input", { type: "checkbox", checked: i === 0 });
      const names = t.names && t.names.length ? t.names : [t.code.code];
      let at = Math.min(Math.max(t.pick || 0, 0), names.length - 1);
      const strong = h("strong", { class: "cb-theme-code" });
      const less = iconButton({ icon: "minus", size: 12, sm: true, class: "cb-step", label: `${t.name}: less specific name` });
      const more = iconButton({ icon: "plus", size: 12, sm: true, class: "cb-step", label: `${t.name}: more specific name` });
      const from = h("span", { class: "muted small" });
      const show = () => {
        t.code.code = names[at];
        strong.textContent = names[at];
        less.disabled = at === 0;
        more.disabled = at === names.length - 1;
        less.title = at ? `Less specific: ${names[at - 1]}` : "No shorter name";
        more.title = at < names.length - 1 ? `More specific: ${names[at + 1]}` : "No longer name";
        from.textContent = names[at] === t.name ? "" : ` · from “${t.name}”`;
      };
      const move = (d) => { at = Math.min(Math.max(at + d, 0), names.length - 1); show(); };
      // a button inside the label must not tick or untick the theme
      less.addEventListener("click", (e) => { e.preventDefault(); move(-1); });
      more.addEventListener("click", (e) => { e.preventDefault(); move(1); });
      less.setAttribute("aria-label", `${t.name}: less specific name`);
      more.setAttribute("aria-label", `${t.name}: more specific name`);
      show();
      boxes.push([cb, t, move]);
      const unsure = t.sure === false ? tag({ kind: "attention", title: "The documents could not show whether this name is specific enough: its words are rare in them, or in another language. Check it." }, "check it") : null;
      fs.appendChild(h("label", { class: "cb-theme" }, cb, h("span", {},
        h("span", { class: "cb-theme-name" }, strong, h("span", { class: "cb-steps" }, less, more), unsure,
          h("span", { class: "muted small" }, ` · ${plural(t.size, "passage")}`), from),
        h("span", { class: "cb-theme-desc" }, t.code.described ? t.code.description : `Key terms: ${t.code.keywords.join(", ") || "none"}`))));
    }
    list.appendChild(fs);
  });
  const everyTicked = (d) => { for (const [cb, , move] of boxes) if (cb.checked) move(d); };
  const r = await dialog({ title: "Start from the themes", wide: true,
    body: h("div", {}, h("p", {}, "Each theme you tick becomes a draft code: a short name made of words of its name, its description (where the AI named it), its key terms as the words it is matched by, and its best passages as examples. Removed themes are left out. You edit them next."),
      h("p", { class: "muted small cb-step-help" }, "Each name is as short as the documents allow: a shorter one is used too often outside its theme. ",
        icon("minus", { size: 12 }), " and ", icon("plus", { size: 12 }), " make a name less or more specific. Every ticked theme: ",
        button({ sm: true, onClick: () => everyTicked(-1) }, icon("minus", { size: 12 }), "Shorter"),
        " ", button({ sm: true, onClick: () => everyTicked(1) }, icon("plus", { size: 12 }), "Longer")),
      list),
    actions: [{ text: "Cancel", value: null }, { text: "Make the codebook", value: true, primary: true }] });
  if (!r) return null;
  const picked = boxes.filter(([cb]) => cb.checked).map(([, t]) => t.code);
  if (!picked.length) { toast("Tick at least one theme.", "info"); return null; }
  // two themes with the same name become two codes: the second gets a number (the name cut before a word to fit)
  const seen = new Map();
  for (const c of picked) {
    const k = c.code.toLowerCase();
    const n = (seen.get(k) || 0) + 1;
    seen.set(k, n);
    if (n > 1) c.code = `${cutAtWord(c.code, 40 - ` (${n})`.length)} (${n})`;
  }
  return picked;
}

// 0.18.1 (K2 part 2): a theory document's concepts to start from (theorycodes.py, no AI). First the document (theory
// documents first), then its candidate concepts: each with its definition quoted from the theory and its page, and
// examples from the evidence documents offered unticked: an example is kept only when you tick it. 0.18.4: *Draft with
// AI* beside them, where the document's AI setting allows: the AI's concepts join the list unticked, marked AI draft,
// each definition quoted from the theory (checked); their examples still come only from the evidence.
async function pickTheory() {
  const base = `/api/projects/${P(App.project)}/codebook-theory`;
  let docs;
  try { docs = (await api("GET", base)).documents; } catch (e) { showError(e); return null; }
  if (!docs.length) { toast("Add the theory document to the project first.", "info"); return null; }
  const theory = docs.filter((d) => d.theory);
  const docSel = select({ "aria-label": "Theory document" }, docs.map((d) => h("option", { value: d.doc_id }, `${d.title}${d.theory ? " (theory)" : ""}`)));
  const first = await dialog({ title: "Start from a theory document", body: h("div", { class: "stack" },
    h("p", {}, theory.length ? "Which theory should the codes come from?" : "No document is marked as theory yet (Documents: a row’s menu, Mark as theory). You can still start from any document."),
    field("Document", docSel)),
    actions: [{ text: "Cancel", value: null }, { text: "Next", value: true, primary: true }] });
  if (!first) return null;
  let r;
  try { r = await api("GET", `${base}/${P(docSel.value)}`); } catch (e) { showError(e); return null; }
  let offer = null;
  try { offer = await api("GET", `${base}/${P(r.doc_id)}/ai`); } catch (_) { offer = null; }   // without it: no AI part
  if (!r.concepts.length && !(offer && offer.offered)) { toast("No concepts were found in this document: start fresh instead.", "info"); return null; }
  const HOW = { defined: "defined in the text", heading: "a heading", frequent: "used often" };
  const rows = [];
  const names = new Set();
  const norm = (t) => { const s = String(t || "").toLowerCase().replace(/^[\s.,:;'"’()]+|[\s.,:;'"’()]+$/g, ""); return s.length > 4 && s.endsWith("s") && !s.endsWith("ss") ? s.slice(0, -1) : s; };
  const list = h("div", { class: "cb-theme-pick cb-theory-pick" });
  const addRow = (c) => {
    const k = norm(c.term);
    if (names.has(k)) return false;
    names.add(k);
    const cb = h("input", { type: "checkbox", checked: c.how === "defined" && !c.ai });
    const exBoxes = (c.suggested || []).map((e) => [h("input", { type: "checkbox", "aria-label": `Keep this example for ${c.term}` }), e]);
    rows.push([cb, c, exBoxes]);
    list.appendChild(h("div", { class: "cb-theme cb-theory" },
      h("label", { class: "cb-theory-head" }, cb, h("span", {},
        h("strong", { class: "cb-theme-code" }, c.code.code),
        c.ai ? [" ", tag({ title: "The AI drafted this concept: its definition is quoted from the theory and was checked against it. Read it before you tick it." }, "AI draft")]
          : h("span", { class: "muted small" }, ` · ${HOW[c.how] || c.how}`),
        h("span", { class: "cb-theme-desc" }, c.definition ? c.code.description : "No definition found in the text: add one in the editor."),
        c.ai && c.reason ? h("span", { class: "muted small cb-theory-why" }, `Why the AI offers it: ${c.reason}`) : null)),
      exBoxes.length ? h("div", { class: "cb-theory-examples" }, h("span", { class: "muted small" }, "Examples from the evidence (tick to keep):"),
        exBoxes.map(([x, e]) => h("label", { class: "cb-theory-example small" }, x, h("span", {}, `“${e.quote}” `, h("span", { class: "muted" }, `${e.title}${e.page ? `, p. ${e.page}` : ""}`))))) : null));
    return true;
  };
  r.concepts.forEach(addRow);
  const empty = r.concepts.length ? null : h("p", { class: "muted" }, "No concepts were found in the document’s headings or definitions. The AI can draft them.");
  // the AI part: a button with its AI mark, and the AI line under it; or one line on why it is not offered
  let aiPart = null;
  if (offer && offer.offered) {
    const draftBtn = button({ onClick: () => draftWithAI(draftBtn) }, "Draft with AI");
    aiPart = h("div", { class: "cb-theory-ai" }, h("div", { class: "btn-row" }, withAI(draftBtn)),
      offer.reader === "local"   // the AI line under the action, as everywhere (DESIGN.md 4.4)
        ? aiWhere("The AI on this computer reads the passages of this document where its concepts are defined or used most: the text never leaves it.", "local")
        : readsLine("the passages of this document where its concepts are defined or used most"));
  } else if (offer && offer.why) {
    aiPart = h("p", { class: "muted small cb-theory-ai" }, offer.why);
  }
  let drafting = false;
  let draftJob = null;   // the running draft's job: stopped if the dialog closes before it ends
  async function draftWithAI(btn) {
    if (drafting) return;
    drafting = true;
    let drafted = false;
    setBusy(btn, true);
    try {
      const res = await api("POST", `${base}/${P(r.doc_id)}/ai`);
      draftJob = res.job.id;
      const job = await watchJob(res.job.id).promise;
      if (!list.isConnected) return;   // the dialog was closed meanwhile
      if (job.state !== "done") { if (job.error) toast(job.error, "error"); return; }
      const got = job.result || {};
      if (got.stopped) return;   // stopped by the person: nothing was drafted
      if (got.withdrawn) { toast(got.why || "The request was taken back before the AI answered. Try again.", "warn"); return; }
      if (!got.ok) { toast("The AI’s definitions could not be found in the document, so nothing was added. Try again, or tick the concepts found without AI.", "warn"); return; }
      const added = (got.concepts || []).filter(addRow).length;
      if (empty) empty.remove();
      toast(added ? `The AI drafted ${plural(added, "concept")}, added at the end of the list, unticked. Read each before you tick it.`
        : "The AI found no concepts beyond those already listed.", added ? "ok" : "info");
      drafted = true;   // asked once is enough: asking again only gives the kept answer back
    } catch (e) { showError(e); }
    finally {
      drafting = false; draftJob = null;
      if (btn.isConnected) { setBusy(btn, false); if (drafted) { btn.disabled = true; btn.textContent = "Drafted with AI"; } }
    }
  }
  const ok = await dialog({ title: `Concepts of “${r.title}”`, wide: true,
    body: h("div", {}, h("p", {}, "Each concept you tick becomes a draft code with its definition quoted from the theory. Terms the text defines are ticked; headings and words it uses often are offered too. You edit them next."), aiPart, empty, list),
    actions: [{ text: "Cancel", value: null }, { text: "Make the codebook", value: true, primary: true }] });
  if (draftJob) api("POST", `/api/jobs/${P(draftJob)}/cancel`).catch(() => {});   // closed while the AI drafts: stop it
  if (!ok) return null;
  const codes = rows.filter(([cb]) => cb.checked).map(([, c, ex]) => ({ ...c.code, examples: ex.filter(([x]) => x.checked).map(([, e]) => e) }));
  if (!codes.length) { toast("Tick at least one concept.", "info"); return null; }
  return { codes, doc_id: r.doc_id };
}

// `text` in at most `n` characters, cut before a word (only a single word longer than `n` is cut inside)
function cutAtWord(text, n) {
  if (text.length <= n) return text;
  const head = text.slice(0, n + 1);
  if (!/\s/.test(head)) return text.slice(0, n);
  const cut = head.replace(/\s+\S*$/, "").replace(/[\s,;:&-]+$/, "");
  return cut || text.slice(0, n);
}

// ---------------------------------------------------------------------------------------------
// the editor
// ---------------------------------------------------------------------------------------------
export async function renderCodebook(view, [name]) {
  const project = App.project;
  const base = `/api/projects/${P(project)}/codebooks/${P(name)}`;
  const key = `${project}:${name}`;
  let cb;
  try { cb = (await api("GET", base)).codebook; }
  catch (e) {
    if (e.status === 404) { view.appendChild(emptyState("search-x", "No such codebook", "It was removed, or it belongs to another project.", link({ kind: "back", href: "#/codebooks" }, "All codebooks"))); return; }
    throw e;
  }
  let trying = false, tryWatch = null;   // the job of Try it, while it runs
  const defineOffers = new Map();   // K1: whether the AI may draft from these examples, by the examples' quotes
  const pendingDraft = new Map();   // K1: a draft not taken or put aside yet, by code
  const definingNow = new Set();    // K1: the codes whose draft is being made
  let st, merges, dirty = false, tried = null, openCode = session(`cb-open:${key}`) || null;
  // what the codebook was when unsaved edits began: a draft made on another state (restored meanwhile, or changed in
  // another window) is set aside rather than saved over it
  const stateKey = (c) => JSON.stringify({ title: c.title, label: c.label, directional: c.directional, groups: c.groups, codes: c.codes });
  let saved = drafts.get(key);
  let setAside = false;
  if (saved && saved.base !== stateKey(cb)) { drafts.delete(key); saved = null; setAside = true; }
  const fresh = () => { st = JSON.parse(JSON.stringify(cb)); merges = []; dirty = false; };
  if (saved) { st = saved.st; merges = saved.merges; dirty = true; } else fresh();
  const head = h("div");
  const sharing = cb.where === "bundled" ? null : shareBar("codebook", cb.name);   // 0.18 (L1): made once, put back on every draw
  const clashBox = h("div", { class: "cb-clashes" });   // 0.18: codes you and a colleague both changed
  const offerBox = h("div", { class: "cb-offer" });     // roles (H8): a colleague's renames and merges, offered
  const notices = h("div");
  const body = h("div", { class: "cb-editor" });
  const saveBar = h("div", { class: "cb-savebar", hidden: true, role: "region", "aria-label": "Unsaved changes" });
  view.append(head, offerBox, clashBox, notices, body, saveBar);
  drawOffer();

  // ---- roles (DESIGN-roles §4.9, §5.7; the review's rule (a)): renames and merges of this codebook by someone who did
  // not make it wait before they move this person's labels. A question with two answers is a card, never a notice:
  // Follow (main) moves the labels as they did, Keep mine (quiet) leaves them.
  async function drawOffer() {
    let offer = null;
    try { offer = (await api("GET", OWNER_API.codebookOffer(P(project), P(name)))).offer; } catch (_) { offer = null; }
    clear(offerBox);
    if (!offer) return;
    const by = offer.from && typeof offer.from === "object" ? offer.from.name : offer.from;
    const answer = async (follow, btn) => {
      btn.disabled = true;
      try {
        await api("POST", OWNER_API.codebookFollow(P(project), P(name)), { follow });
        toast(follow ? "Your labels follow their renames and merges now." : "Your labels stay as they are.", "ok", { ttl: 6000 });
        if (follow) await reload(); else drawOffer();
      } catch (e) { showError(e); btn.disabled = false; drawOffer(); }
    };
    offerBox.appendChild(h("ul", { class: "owner-cards" }, decisionCard({ id: "cb-offer-card", what: "Renames and merges to follow?",
      person: by ? personMark([by], { name: "short" }) : null, body: h("p", { class: "owner-line" }, codebookOfferText(offer)),
      actions: [button({ kind: "main", sm: true, id: "cb-offer-follow", onClick: (e) => answer(true, e.currentTarget) }, "Follow"),
        button({ kind: "quiet", sm: true, id: "cb-offer-keep", onClick: (e) => answer(false, e.currentTarget) }, "Keep mine")] })));
  }

  function touch() {
    dirty = true;
    drafts.set(key, { st, merges, base: stateKey(cb) });
    drawSaveBar();
  }
  const ro = !cb.editable;

  // ---- the head
  function drawHead() {
    const moreItems = [];
    if (!ro) {
      if (cb.where === "project" && !cb.in_home) moreItems.push(["layers", "Keep it with all my projects", () => move("home")]);
      if (cb.where === "home") moreItems.push(["folder", "Keep it with this project only", () => move("project")], ["copy", "This project's own copy (change it here only)", copyHere]);
      moreItems.push(["trash", "Remove the codebook", removeCodebook, true]);
    }
    const more = moreItems.length ? menu({ class: "cb-more", items: moreItems.map(([ic, t, fn, danger]) => ({ icon: ic, text: t, onClick: () => fn(), danger: !!danger })) }) : null;
    replace(head, pageHead(cb.title || cb.name, {
      back: { href: "#/codebooks", text: "All codebooks" },
      sub: h("span", { class: "cb-meta" }, whereBadge(cb.where), `${plural(st.codes.length, "code")} · each is called “${st.label}”`,
        cb.used.labels ? ` · ${plural(cb.used.labels, "label")} in this project` : "", cb.used.checks ? ` · ${plural(cb.used.checks, "check")}` : "",
        cb.shadows_home ? h("span", { class: "muted" }, " · this project's own copy of a codebook kept with all projects") : null),
      actions: h("div", { class: "btn-row" },
        ro ? button({ kind: "main", sm: true, onClick: () => newCodebook("copy", { of: cb.name, title: `${cb.title} (copy)` }) }, icon("copy", { size: 14 }), "Make a copy to change it") : null,
        button({ sm: true, title: "Without AI: how many passages and documents the keyword pass would pick for each code", disabled: trying, onClick: (e) => tryIt(e.currentTarget) }, icon("zap", { size: 14 }), "Try it"),
        ro ? null : button({ kind: "quiet", sm: true, title: "Earlier versions: compare them with now, or restore one",
          onClick: () => { if (dirty) { toast("Save or discard your changes first: a restore would replace them.", "info"); return; } showHistory({ kind: "codebook", key: cb.name, onRestored: reload }); } },
          icon("history", { size: 14 }), "History"),
        downloadButton({ onClick: () => download(`${base}.csv`).catch(showError) }, "CSV"),
        // 0.18.7 (G5): the codebook for NVivo, ATLAS.ti and MAXQDA
        downloadButton({ title: "A REFI-QDA codebook, for NVivo, ATLAS.ti and MAXQDA: each code with its definition", onClick: () => download(`${base}.qdc`).catch(showError) }, "Download as .qdc"),
        more),
    }), sharing);
  }

  // ---- 0.18: codes you and a colleague both changed since you last exchanged the codebook (sync/codebook_merge.py).
  // Yours is in the codebook; theirs waits beside it until you keep one of the two (POST …/clashes/<uid>).
  const CLASH_FIELDS = [["code", "Name"], ["description", "Definition"], ["group", "Group"], ["include", "When to use it"],
    ["exclude", "When not to use it"], ["keywords", "Words it is matched by"], ["examples", "Examples"]];
  function clashValue(c, k) {
    if (!c) return "";
    if (k === "group") return c.group_name || (st.groups.find((g) => g.group === c.group) || {}).group_name || c.group || "";
    if (k === "keywords") return (c.keywords || []).join(", ");
    if (k === "examples") return (c.examples || []).map((e) => (typeof e === "string" ? e : e && e.quote) || "").filter(Boolean).map((q) => `“${q}”`).join(" ");
    return c[k] || "";
  }
  // one side of the comparison (compare(), docs/DESIGN.md 4.27): who, and the code's fields, what differs said in words
  function clashSide(title, who, c, other, removed, meta) {
    return { title: h("h4", { class: "cb-clash-side-h" }, who ? personMark([who]) : personMark(["you"]), " ", title), meta: meta || null,
      body: removed ? h("p", { class: "cb-removed-here" }, "You removed this code.")
        : h("dl", {}, CLASH_FIELDS.map(([k, label]) => {
          const v = clashValue(c, k), differs = !!other && v !== clashValue(other, k);
          return v || differs ? h("div", { class: "cb-field" + (differs ? " cb-differs" : "") },
            h("dt", {}, label, differs ? h("span", { class: "cb-differs-word" }, " · differs") : null),
            h("dd", {}, v || h("span", { class: "muted" }, "none"))) : null;
        })) };
  }
  function drawClashes() {
    clear(clashBox);
    const list = cb.clashes || [];
    if (!list.length) return;
    const names = [...new Set(list.map((x) => x.name || "a colleague"))];
    clashBox.appendChild(notice({ kind: "attention", icon: "copy", role: "note" },
      h("p", {}, h("strong", {}, list.length === 1 ? "A code you and a colleague both changed. " : `${list.length} codes you and a colleague both changed. `),
        `Since you last exchanged this codebook, you and ${names.join(" and ")} changed the same ${list.length === 1 ? "code" : "codes"}. Yours is in the codebook; theirs waits here. Keep one of the two${list.length === 1 ? "" : " for each"}; the codebook as it was before is kept in History.`)));
    for (const x of list) {
      const mine = st.codes.find((c) => c.uid === x.uid) || cb.codes.find((c) => c.uid === x.uid) || null;
      const name = (mine && mine.code) || x.code || (x.theirs && x.theirs.code) || "a code";
      const who = x.name || "a colleague";
      const keep = (which, btn) => settle(x, which, btn, name, who);
      const mineBtn = button({ sm: true, icon: "check", "aria-label": x.removed_here ? `Keep mine: “${name}” stays removed` : `Keep mine: your version of “${name}”` }, "Keep mine");
      const theirsBtn = button({ sm: true, icon: "users", "aria-label": `Keep theirs: ${who}’s version of “${name}”` }, "Keep theirs");
      mineBtn.addEventListener("click", () => keep("mine", mineBtn));
      theirsBtn.addEventListener("click", () => keep("theirs", theirsBtn));
      // a card per code, the two versions side by side (yours and theirs), Keep mine / Keep theirs under both
      clashBox.appendChild(card({ class: "cb-clash", "aria-label": `Both changed: ${name}`, title: name, level: "h3" },
        compare({ label: `Your version and ${who}’s of “${name}”`,
          left: clashSide("Yours", null, mine, x.theirs, !!x.removed_here),
          right: clashSide(`${who}’s`, who, x.theirs, x.removed_here ? null : mine, false,
            [personMark([who], { name: "short", prefix: "Changed by" }), x.at ? ` ${fmt.dateShort(x.at)}` : null]),   // a changed-by line: the name shown
          actions: ro ? null : [mineBtn, theirsBtn] })));
    }
  }
  async function settle(x, which, btn, name, who) {
    if (dirty) { toast("Save or discard your changes first: keeping a version changes the codebook.", "info"); return; }
    btn.disabled = true;
    try {
      const r = await api("POST", `${base}/clashes/${P(x.uid)}`, { keep: which });
      cb = r.codebook;
      fresh();
      forgetFrameworks();
      toast(which === "mine" ? `Kept your version of “${name}”; ${who}’s is set aside.` : `Kept ${who}’s version of “${name}”; yours is in History.`, "ok");
      draw();
      const next = clashBox.querySelector(".cb-clash button") || head.querySelector("h1");
      if (next) next.focus();
    } catch (e) { showError(e); btn.disabled = false; }
  }

  // ---- notices: removed codes whose labels wait, codes labelled with an earlier wording
  function drawNotices() {
    clear(notices);
    if (saved && dirty) notices.appendChild(notice({ kind: "info" }, h("p", {}, "Your unsaved changes from before are kept below: save them or discard them.")));
    if (setAside) notices.appendChild(notice({ kind: "attention" }, h("p", {}, "The codebook changed since your unsaved changes (it was restored, or changed elsewhere), so they were discarded rather than saved over it. It is shown as it is now.")));
    const stale = Object.entries(cb.stale || {});
    if (stale.length) {
      notices.appendChild(notice({ kind: "attention", class: "cb-stale" }, h("div", {},
        h("p", {}, h("strong", {}, "The AI labelled with an earlier wording. "), "These codes changed after the AI used them. Their labels stay as they are until you ask for these passages to be labelled again (only those passages)."),
        h("ul", {}, stale.map(([code, s]) => h("li", {}, h("strong", {}, code), ` · ${plural(s.passages, "passage")} labelled before ${fmt.date(s.since)} `,
          withAI(button({ sm: true, onClick: () => relabel(code) }, icon("refresh", { size: 13 }), "Label them again"))))),
        readsLine("the passages of these codes again"))));
    }
    if ((cb.removed || []).length) {
      notices.appendChild(card({ as: "details", class: "cb-removed" }, h("summary", {}, icon("inbox", { size: 15 }), plural(cb.removed.length, "removed code"), h("span", { class: "muted small" }, " · their labels wait here, not deleted")),
        h("ul", {}, cb.removed.map((r) => h("li", {}, h("strong", {}, r.code), ` · ${plural(r.labels, "label")}`, r.description ? h("span", { class: "muted" }, ` · ${shortTitle(r.description, 90)}`) : null,
          r.definition && r.definition.merged_into ? h("span", { class: "muted small" }, ` · merged into ${r.definition.merged_into}; these passages had both`) : null,
          !ro && r.uid ? button({ kind: "quiet", sm: true, onClick: () => bringBack(r) }, icon("undo", { size: 13 }), "Bring it back") : null)))));
    }
  }

  // ---- the codes, in their groups
  function groupsInOrder() {
    const gs = st.groups.slice();
    for (const c of st.codes) if (!gs.some((g) => g.group === c.group)) gs.push({ group: c.group, group_name: "" });
    return gs;
  }
  function draw() {
    drawHead();
    drawClashes();
    drawNotices();
    clear(body);
    if (!ro) {
      body.appendChild(card({ as: "details", class: "cb-settings" }, h("summary", {}, icon("sliders", { size: 14 }), "Codebook settings"),
        h("div", { class: "fields-2" },
          field("Title", textField(st.title, (v) => { st.title = v; }, { maxlength: 200 })),
          field("What one code is called", textField(st.label, (v) => { st.label = v || "code"; }, { maxlength: 40 }), { help: "e.g. code, theme, category" })),
        (() => { const sw = switchControl("Its codes are aims a text can help or hinder", st.directional, { help: "Like the SDG targets: the AI's labels then also say whether a passage helps, hinders or does not say." });
          sw.input.addEventListener("change", () => { st.directional = sw.input.checked; touch(); }); return sw; })()));
    }
    if (!st.codes.length) {
      body.appendChild(emptyState("book-marked", "No codes yet", "Add a first code: a short name and a sentence that says what it is about."));
    }
    for (const g of groupsInOrder()) {
      const codes = st.codes.filter((c) => c.group === g.group);
      if (!codes.length && ro) continue;
      // a group is a card; its codes are rows divided by lines (two levels of boxes at most, DESIGN 4.11)
      const sec = card({ as: "section", class: "cb-group", dataset: { group: g.group } });
      const gName = ro ? h("h2", { class: "cb-group-name" }, g.group_name || g.group || "Codes without a group")
        : textField(g.group_name, (v) => { const x = st.groups.find((y) => y.group === g.group); if (x) x.group_name = v; else st.groups.push({ group: g.group, group_name: v }); },
          { class: "cb-group-input", placeholder: g.group ? `Group ${g.group}` : "Codes without a group", "aria-label": "Group name" });
      if (g.group && gName.tagName === "INPUT") gName.title = `Short name in the CSV file: ${g.group}`;
      sec.appendChild(h("div", { class: "cb-group-head" }, gName,
        h("span", { class: "muted small" }, plural(codes.length, "code")),
        ro ? null : button({ kind: "quiet", sm: true, onClick: () => addCode(g.group) }, icon("plus", { size: 13 }), "Add a code")));
      const ul = h("ul", { class: "cb-codes" });
      for (const c of codes) ul.appendChild(codeCard(c));
      if (!ro) dropZone(sec, g.group);
      sec.appendChild(ul);
      body.appendChild(sec);
    }
    if (!ro) body.appendChild(h("div", { class: "btn-row cb-foot" },
      button({ sm: true, onClick: addGroup }, icon("plus", { size: 13 }), "Add a group"),
      !st.codes.length ? button({ kind: "main", sm: true, onClick: () => addCode("") }, icon("plus", { size: 13 }), "Add a code") : null));
    drawSaveBar();
  }

  function textField(value, onChange, attrs = {}) {
    const el = input({ value: value || "", ...attrs });
    el.addEventListener("input", () => { onChange(el.value); touch(); });
    return el;
  }
  function area(value, onChange, attrs = {}) {
    const el = textarea({ rows: 2, ...attrs });
    el.value = value || "";
    el.addEventListener("input", () => { onChange(el.value); touch(); });
    return el;
  }

  function codeCard(c) {
    const t = tried && tried.codes[c.code];
    const open = openCode === c.uid || (!c.uid && openCode === c.code);
    const stale = (cb.stale || {})[c.code];
    const li = h("li", { class: "cb-code" + (open ? " cb-open" : ""), dataset: { uid: c.uid || "", code: c.code } });
    const count = t ? (t.note ? tag({ kind: "attention", title: t.note }, `${plural(t.passages, "passage")} · ${plural(t.documents, "doc")}`) : tag({}, `${plural(t.passages, "passage")} · ${plural(t.documents, "doc")}`)) : null;
    const summary = h("button", { class: "cb-code-sum", type: "button", "aria-expanded": open ? "true" : "false", onClick: () => {
      openCode = open ? null : (c.uid || c.code); session(`cb-open:${key}`, openCode); draw();
      if (!open) setTimeout(() => { const x = body.querySelector(`.cb-open input`); if (x) x.focus(); }, 0);
    } },
      h("span", { class: "cb-code-name" }, c.code || h("em", { class: "muted" }, "new code")),
      h("span", { class: "cb-code-desc" }, c.description ? shortTitle(c.description, 140) : h("em", { class: "muted" }, "no definition yet")),
      h("span", { class: "cb-code-badges" }, stale ? tag({ kind: "attention", title: "Labelled by the AI with an earlier wording" }, "earlier wording") : null,
        draftFields(c).length ? tag({ icon: "sparkles", title: "Words the AI drafted and you have not rewritten yet" }, "AI draft") : null,
        (c.examples || []).length ? tag({ icon: "quote", title: "Examples" }, plural((c.examples || []).length, "example")) : null, count),
      icon(open ? "chevron-up" : "chevron-down", { size: 15 }));
    const grip = ro ? null : h("span", { class: "cb-grip", title: "Drag to move", "aria-hidden": "true" }, icon("grip", { size: 15 }));
    li.append(h("div", { class: "cb-code-row" }, grip, summary));
    if (!ro) {
      li.draggable = false;
      grip.addEventListener("mousedown", () => { li.draggable = true; });
      li.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", c.uid || c.code); e.dataTransfer.effectAllowed = "move"; li.classList.add("cb-dragging"); });
      li.addEventListener("dragend", () => { li.draggable = false; li.classList.remove("cb-dragging"); });
      li.addEventListener("dragover", (e) => { e.preventDefault(); li.classList.add("cb-drop-before"); });
      li.addEventListener("dragleave", () => li.classList.remove("cb-drop-before"));
      li.addEventListener("drop", (e) => { e.preventDefault(); e.stopPropagation(); li.classList.remove("cb-drop-before"); moveCode(e.dataTransfer.getData("text/plain"), c, c.group); });
    }
    if (open) li.appendChild(ro ? readOnlyDetail(c, t) : detail(c, t));
    return li;
  }
  function dropZone(sec, group) {
    sec.addEventListener("dragover", (e) => { e.preventDefault(); sec.dataset.drop = "true"; });
    sec.addEventListener("dragleave", (e) => { if (!sec.contains(e.relatedTarget)) delete sec.dataset.drop; });
    sec.addEventListener("drop", (e) => { e.preventDefault(); delete sec.dataset.drop; moveCode(e.dataTransfer.getData("text/plain"), null, group); });
  }
  const find = (id) => st.codes.find((x) => (x.uid || x.code) === id);
  function moveCode(id, before, group) {
    const c = find(id);
    if (!c || c === before) return;
    st.codes.splice(st.codes.indexOf(c), 1);
    c.group = group;
    if (before) st.codes.splice(st.codes.indexOf(before), 0, c);
    else { const last = st.codes.map((x) => x.group).lastIndexOf(group); st.codes.splice(last + 1, 0, c); }
    touch(); draw();
  }
  function step(c, dir) {
    const same = st.codes.filter((x) => x.group === c.group);
    const i = same.indexOf(c), j = i + dir;
    if (j < 0 || j >= same.length) return;
    const a = st.codes.indexOf(c), b = st.codes.indexOf(same[j]);
    [st.codes[a], st.codes[b]] = [st.codes[b], st.codes[a]];
    touch(); draw();
  }

  function readOnlyDetail(c, t) {
    return h("div", { class: "cb-detail" },
      h("p", {}, c.description),
      c.include ? h("p", {}, h("strong", {}, "When to use it: "), c.include) : null,
      c.exclude ? h("p", {}, h("strong", {}, "When not: "), c.exclude) : null,
      triedExamples(t));
  }
  function triedExamples(t) {
    if (!t) return null;
    return inset({ class: "cb-tried" }, h("p", { class: "small" }, h("strong", {}, "Try it: "), `${plural(t.passages, "passage")} in ${plural(t.documents, "document")}`, t.note ? [" ", tag({ kind: "attention" }, t.note)] : null),
      t.examples.length ? h("ul", { class: "cb-tried-list" }, t.examples.map((x) => h("li", {}, link({ kind: "title", serif: true, href: `#/doc/${encodeURIComponent(x.doc_id)}` }, shortTitle(x.title || x.doc_id, 60)), x.page ? h("span", { class: "muted" }, ` p. ${x.page}`) : null, ": ", h("span", { class: "serif" }, `“${x.text}”`)))) : null);
  }

  function detail(c, t) {
    const groups = groupsInOrder();
    const groupSel = select({ "aria-label": "Group" },
      groups.map((g) => h("option", { value: g.group, selected: g.group === c.group }, g.group_name || g.group || "No group")));
    groupSel.addEventListener("change", () => moveCode(c.uid || c.code, null, groupSel.value));
    const kw = textField((c.keywords || []).join(", "), (v) => { c.keywords = v.split(/[,;]/).map((x) => x.trim()).filter(Boolean); }, { placeholder: "e.g. commute, commuting, travel to work" });
    // K1: the words still the AI's draft, said under the three fields until you rewrite them
    const mark = h("div", { class: "cb-draft-mark", "aria-live": "polite" });
    const drawMark = () => {
      const f = draftFields(c);
      replace(mark, f.length ? h("p", { class: "small" }, tag({ icon: "sparkles" }, "AI draft"), " ",
        `${capital(listWords(f.map((k) => DRAFT_LABEL[k])))} ${f.length === 1 ? "is" : "are"} still the AI’s words${c.ai_draft.model ? ` (${c.ai_draft.model})` : ""}, drafted from the examples. Rewrite ${f.length === 1 ? "it" : "them"} in your own words; the mark goes when you do.`) : null);
    };
    drawMark();
    const exList = h("ul", { class: "cb-examples" });
    const drawExamples = () => {
      clear(exList);
      (c.examples || []).forEach((e, i) => exList.appendChild(h("li", {}, h("span", { class: "serif" }, `“${e.quote}”`),
        h("span", { class: "muted small" }, e.title ? ` · ${shortTitle(e.title, 50)}${e.page ? `, p. ${e.page}` : ""}` : " · not found in this project's documents"),
        button({ kind: "danger", sm: true, onClick: () => { c.examples.splice(i, 1); touch(); drawExamples(); } }, "Remove"))));
    };
    drawExamples();
    const exInput = textarea({ rows: 2, placeholder: "Paste words of a document, exactly as they are there" });
    const exBtn = button({ sm: true, onClick: async () => {
      const q = exInput.value.trim();
      if (!q) { exInput.focus(); return; }
      exBtn.disabled = true;
      try {
        const r = await api("POST", `/api/projects/${P(project)}/codebooks/example`, { quote: q });
        c.examples = (c.examples || []).concat([r.example]);
        exInput.value = "";
        touch(); drawExamples();
      } catch (e) { showError(e); } finally { exBtn.disabled = false; }
    } }, icon("quote", { size: 13 }), "Add the example");
    const others = st.codes.filter((x) => x !== c && x.uid);  // a code saved already (a new one has no labels to take)
    const mergeSel = select({ sm: true, class: "cb-merge", "aria-label": `Merge ${c.code} into another code` }, h("option", { value: "" }, "Merge into…"), others.map((x) => h("option", { value: x.uid }, x.code)));
    mergeSel.addEventListener("change", () => mergeInto(c, find(mergeSel.value)));
    return h("div", { class: "cb-detail" },
      h("div", { class: "fields-2" },
        field("Name", textField(c.code, (v) => { c.code = v; }, { maxlength: 40 }), { help: "Short: it is how labels and checks name the code." }),
        field("Group", groupSel)),
      field("Definition", area(c.description, (v) => { c.description = v; drawMark(); }, { rows: 3, maxlength: 4000 }), { help: "What the code is about, in a sentence or two. The AI reads it when it labels." }),
      h("div", { class: "fields-2" },
        field("When to use it", area(c.include, (v) => { c.include = v; drawMark(); }, { maxlength: 2000 })),
        field("When not to use it", area(c.exclude, (v) => { c.exclude = v; drawMark(); }, { maxlength: 2000 }))),
      mark,
      field("Words it is matched by", kw, { help: "Besides its definition, for the keyword pass. Separate them with commas." }),
      h("div", { class: "field" }, h("span", { class: "field-label" }, "Examples from the documents"), exList, exInput, h("div", { class: "btn-row" }, exBtn,
        h("span", { class: "muted small" }, "Each example is checked: it must be words of a document of this project."))),
      defineBox(c),
      triedExamples(t),
      h("div", { class: "btn-row cb-code-actions" },
        button({ kind: "quiet", sm: true, onClick: () => step(c, -1), "aria-label": `Move ${c.code} up` }, icon("arrow-up", { size: 13 }), "Up"),
        button({ kind: "quiet", sm: true, onClick: () => step(c, 1), "aria-label": `Move ${c.code} down` }, icon("chevron-down", { size: 13 }), "Down"),
        button({ kind: "quiet", sm: true, onClick: () => splitCode(c), title: "A second code made from this one; its labels stay with this one" }, icon("split", { size: 13 }), "Split"),
        others.length ? mergeSel : null,
        button({ kind: "danger", sm: true, onClick: () => removeCode(c) }, icon("trash", { size: 13 }), "Remove")));
  }

  // ---- K1 (the optional AI part): a code's definition drafted from its examples (codedefine.py) -----------------
  // Asked only for an open code with two examples or more; the answer waits beside the fields (`pending`) until you
  // take it or put it aside, and survives a redraw. Taken words are marked as the AI's (`c.ai_draft`), which the save
  // keeps while the fields still hold them word for word.
  function defineKey(c) { return c.uid || `new:${c.code}`; }
  function exampleQuotes(c) { return (c.examples || []).map((e) => (typeof e === "string" ? e : e && e.quote) || "").filter(Boolean); }
  function defineBox(c) {
    const box = h("div", { class: "cb-define" });
    const quotes = exampleQuotes(c);
    const k = defineKey(c);
    const pend = pendingDraft.get(k);
    if (pend) { box.appendChild(draftPanel(c, pend)); return box; }
    if (quotes.length < 2) {
      box.appendChild(h("p", { class: "muted small" }, "With two examples or more, the AI can draft a definition, when to use the code and when not, from the passages that hold them."));
      return box;
    }
    const sig = JSON.stringify(quotes);
    const known = defineOffers.get(sig);
    const fill = (offer) => {
      if (!offer) { clear(box); return; }
      if (!offer.offered) { replace(box, h("p", { class: "muted small" }, offer.why)); return; }
      const btn = button({ onClick: () => askDraft(c, btn) }, icon("sparkles", { size: 14 }), "Draft from the examples");
      if (definingNow.has(k)) setBusy(btn, true);
      const what = `the ${offer.passages} passages that hold this code’s examples, and its name`;
      replace(box, h("div", { class: "btn-row" }, withAI(btn)),
        offer.reader === "local" ? aiWhere(`The AI on this computer reads ${what}: the text never leaves it.`, "local") : readsLine(what),
        offer.left_line ? h("p", { class: "muted small" }, offer.left_line) : null,
        h("p", { class: "muted small" }, "A draft to rewrite: it is shown here first, and nothing changes until you take it."));
    };
    if (known) fill(known);
    else api("POST", `${base}/define/offer`, { examples: quotes }).then((o) => { defineOffers.set(sig, o); fill(o); }).catch(() => fill(null));
    return box;
  }
  async function askDraft(c, btn) {
    const k = defineKey(c);
    if (definingNow.has(k)) return;
    definingNow.add(k);
    setBusy(btn, true);
    try {
      const group = (groupsInOrder().find((g) => g.group === c.group) || {}).group_name || "";
      const res = await api("POST", `${base}/define`, { code: c.code, group, examples: exampleQuotes(c) });
      const job = await watchJob(res.job.id).promise;
      if (job.state !== "done") { if (job.error) toast(job.error, "error"); return; }
      const got = job.result || {};
      if (got.stopped) return;
      if (got.withdrawn) { toast(got.why || "The request was taken back before the AI answered. Try again.", "warn"); return; }
      if (!got.ok || !got.draft) { toast("The AI’s quotes could not be found in the example passages, so nothing was drafted. Try again, or write the definition yourself.", "warn"); return; }
      pendingDraft.set(k, { ...got.draft, at: new Date().toISOString(), reused: got.reused });
      if (body.isConnected) draw();
    } catch (e) { showError(e); }
    finally { definingNow.delete(k); if (btn.isConnected) setBusy(btn, false); }
  }
  function takeDraft(c, d, fields) {
    const took = {};
    for (const f of fields) if (d[f]) { c[f] = d[f]; took[f] = d[f]; }
    if (!Object.keys(took).length) return;
    const keep = {};   // the AI's words of earlier drafts the fields still hold
    for (const f of draftFields(c)) if (!(f in took)) keep[f] = c.ai_draft[f];
    c.ai_draft = { model: d.model || "", at: d.at, ...keep, ...took };
    touch();
  }
  function draftPanel(c, d) {
    const k = defineKey(c);
    const done = () => { pendingDraft.delete(k); draw(); };
    const row = (f, label) => d[f] ? h("div", { class: "cb-draft-row" },
      h("div", { class: "cb-draft-text" }, h("span", { class: "field-label" }, label), h("p", {}, d[f]),
        d.quotes && d.quotes[f] ? h("p", { class: "muted small" }, "Shown by ", h("span", { class: "serif" }, `“${d.quotes[f].quote}”`),
          d.quotes[f].title ? ` · ${shortTitle(d.quotes[f].title, 50)}${d.quotes[f].page ? `, p. ${d.quotes[f].page}` : ""}` : "") : null),
      button({ sm: true, onClick: () => { takeDraft(c, d, [f]); delete d[f]; if (!FIELDS_OF_DRAFT.some((x) => d[x])) done(); else draw(); } },
        (c[f] || "").trim() ? "Use instead" : "Use")) : null;
    return inset({ class: "cb-draft", tentative: true },
      h("p", { class: "small" }, tag({ icon: "sparkles" }, "AI draft"), " ",
        `Drafted${d.model ? ` by ${d.model}` : ""} from the passages that hold this code’s examples${d.reused ? " (the answer kept from the same request before)" : ""}. Read it, take what fits, and rewrite it in your own words.`),
      d.note ? h("p", { class: "small" }, h("strong", {}, "The AI notes: "), d.note) : null,
      row("description", "Definition"), row("include", "When to use it"), row("exclude", "When not to use it"),
      h("div", { class: "btn-row" },
        button({ kind: "main", sm: true, onClick: () => { takeDraft(c, d, FIELDS_OF_DRAFT); done(); } }, "Use all of it"),
        button({ kind: "quiet", sm: true, onClick: done }, "Put it aside")));
  }

  function freeName(n) {
    const taken = new Set(st.codes.map((x) => x.code.toLowerCase()));
    let name = n, i = 2;
    while (taken.has(name.toLowerCase())) name = `${n.slice(0, 36)} (${i++})`;
    return name;
  }
  function addCode(group) {
    const c = { uid: "", code: freeName("New code"), description: "", group, include: "", exclude: "", keywords: [], examples: [] };
    st.codes.push(c);
    openCode = c.code;
    touch(); draw();
    setTimeout(() => { const x = body.querySelector(".cb-open input"); if (x) { x.focus(); x.select(); } }, 0);
  }
  function addGroup() {
    let n = st.groups.length + 1, k = `g${n}`;
    while (st.groups.some((g) => g.group === k) || st.codes.some((c) => c.group === k)) k = `g${++n}`;
    st.groups.push({ group: k, group_name: "" });
    touch(); draw();
    setTimeout(() => { const x = body.querySelector(`.cb-group[data-group="${k}"] .cb-group-input`); if (x) x.focus(); }, 0);
  }
  function splitCode(c) {
    const copy = { uid: "", split_from: c.uid || null, code: freeName(`${c.code.slice(0, 34)} (2)`), description: c.description, group: c.group,
      include: c.include, exclude: c.exclude, keywords: (c.keywords || []).slice(), examples: [] };
    st.codes.splice(st.codes.indexOf(c) + 1, 0, copy);
    openCode = copy.code;
    touch(); draw();
    toast("A second code made from it. Change its name and definition; the first keeps its labels.", "info", { small: true });
  }
  async function mergeInto(c, into) {
    if (!into) return;
    if (!(await confirmDialog({ title: `Merge “${c.code}” into “${into.code}”?`, message: `“${c.code}” goes, and its labels go to “${into.code}” when you save. Restoring the codebook from before (History) gives them back.`, confirmText: "Merge", danger: false }))) { draw(); return; }
    if (c.uid) merges.push({ from: c.uid, into: into.uid });
    st.codes.splice(st.codes.indexOf(c), 1);
    touch(); draw();
  }
  async function removeCode(c) {
    const n = (cb.used.by_code || {})[c.code] || 0;
    if (n && !(await confirmDialog({ title: `Remove “${c.code}”?`, message: `Its ${plural(n, "label")} in this project are not deleted: they wait under Removed codes, and come back with the code.`, confirmText: "Remove" }))) return;
    st.codes.splice(st.codes.indexOf(c), 1);
    touch(); draw();
  }
  function bringBack(r) {
    const d = r.definition || {};
    st.codes.push({ uid: r.uid, code: d.code || r.code, description: d.description || r.description || r.code, group: d.group || "",
      include: d.include || "", exclude: d.exclude || "", keywords: d.keywords || [], examples: (d.examples || []).map((q) => ({ quote: q })) });
    touch(); draw();
    toast(`“${r.code}” is back in the codebook. Save to keep it; its labels count again.`, "info");
  }

  // ---- saving
  // the bar is made once, so what is typed in "Why?" stays while other fields change
  const whyInput = input({ class: "cb-why", maxlength: 2000, placeholder: "Why? (optional, for the research log)", "aria-label": "Why" });
  const saveBtn = button({ kind: "main", sm: true, onClick: () => save(saveBtn, whyInput.value.trim()) }, icon("check", { size: 14 }), "Save");
  replace(saveBar, workState("attention", "Unsaved changes"), whyInput,
    button({ kind: "quiet", sm: true, onClick: discard }, "Discard"), saveBtn);
  function drawSaveBar() {
    saveBar.hidden = !dirty || ro;
  }
  async function save(btn, why) {
    if (btn) btn.disabled = true;
    try {
      const r = await api("PUT", base, { codebook: st, merges, why: why || null });
      drafts.delete(key);
      cb = r.codebook;
      fresh();
      whyInput.value = "";
      setAside = false;
      forgetFrameworks();
      toast(r.changes.length ? `Saved: ${r.changes.slice(0, 3).join("; ")}${r.changes.length > 3 ? ` and ${r.changes.length - 3} more` : ""}. The earlier version is in History.` : "Nothing had changed.", "ok");
      draw();
    } catch (e) { showError(e); }
    if (btn) btn.disabled = false;
  }
  async function discard() {
    if (!(await confirmDialog({ title: "Discard your changes?", message: "The codebook stays as it was saved.", confirmText: "Discard" }))) return;
    drafts.delete(key);
    fresh();
    draw();
  }
  async function reload() {
    try { cb = (await api("GET", base)).codebook; } catch (e) { showError(e); return; }
    drafts.delete(key);
    fresh();
    forgetFrameworks();
    draw();
  }

  // ---- whole-codebook actions
  // One pass at a time: the button waits while its job runs (also on a page drawn again meanwhile), and the job is
  // watched only while this page is shown
  async function tryIt(btn) {
    if (trying) return;
    trying = true;
    if (btn) setBusy(btn, true);
    toast("Trying the codebook on every passage (no AI)…", "info", { small: true, group: "cb-try" });
    try {
      const r = await api("POST", `${base}/try`, { codebook: st });
      tryWatch = watchJob(r.job.id);
      const job = await tryWatch.promise;
      trying = false;
      if (job.state !== "done") { if (job.error) toast(job.error, "error"); return; }
      tried = job.result;
      const none = Object.entries(tried.codes).filter(([, x]) => !x.passages).map(([k]) => k);
      const many = Object.entries(tried.codes).filter(([, x]) => x.note && x.passages).map(([k]) => k);
      toast(`Tried on ${plural(tried.passages, "passage")}.${none.length ? ` ${plural(none.length, "code")} match nothing.` : ""}${many.length ? ` ${plural(many.length, "code")} match a large part of the documents.` : ""} Open a code to see what it picks.`, none.length || many.length ? "warn" : "ok", { group: "cb-try" });
      draw();
    } catch (e) { showError(e); }
    finally { trying = false; tryWatch = null; if (btn) setBusy(btn, false); }
  }
  async function relabel(code) {
    try {
      const r = await api("POST", `${base}/relabel`, { code });
      toast(`The AI labels ${plural(r.passages, "passage")} of “${code}” again, with its new wording.`, "ok", { action: { text: "Follow it on Profile", href: `#/profile?framework=${encodeURIComponent(name)}` } });
    } catch (e) { showError(e); }
  }
  async function move(to) {
    if (dirty) { toast("Save or discard your changes first.", "info"); return; }
    try { cb = (await api("POST", `${base}/move`, { to })).codebook; fresh(); forgetFrameworks(); draw(); toast(to === "home" ? "Kept with all your projects now." : "Kept with this project only now.", "ok"); }
    catch (e) { showError(e); }
  }
  async function copyHere() {
    if (dirty) { toast("Save or discard your changes first.", "info"); return; }
    try { cb = (await api("POST", `${base}/copy-here`, {})).codebook; fresh(); forgetFrameworks(); draw(); toast("This project has its own copy now: changes here stay here.", "ok"); }
    catch (e) { showError(e); }
  }
  async function removeCodebook() {
    const r = await askWhy({ title: `Remove the codebook “${cb.title}”?`, confirmText: "Remove",
      message: `${cb.where === "home" ? "It is removed for all your projects. " : ""}Labels made with it stay: they are results. History keeps the codebook, so the research log can bring it back.` });
    if (!r) return;
    try { await api("DELETE", `${base}${r.why ? `?why=${encodeURIComponent(r.why)}` : ""}`); drafts.delete(key); forgetFrameworks(); toast("Codebook removed.", "ok"); location.hash = "#/codebooks"; }
    catch (e) { showError(e); }
  }

  const onUnload = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
  window.addEventListener("beforeunload", onUnload);
  draw();
  return () => { window.removeEventListener("beforeunload", onUnload); if (tryWatch) tryWatch.stop(); };
}
