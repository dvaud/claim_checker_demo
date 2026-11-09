// 0.16 (roadmap K1): your own codebook. The list of codebooks, a new one (fresh, from the themes found, a copy, or a
// CSV file), and the editor: codes with a definition, when to use them and when not, the words they are matched by
// and example quotes from the documents, in groups; drag (or Move up / down) to reorder, rename, merge, split and
// remove codes. *Try it* counts what the keyword pass would pick, without AI. Saving keeps the codebook as it was
// (History) and writes the changes in the research log; labels follow renames and merges, and wait under *Removed
// codes* when a code is removed. An edit changes no result by itself.
import { featureEyebrow } from "../features.js";
import { App, api, h, icon, replace, clear, toast, showError, failedLoad, fmt, pageHead, P, plural, confirmDialog, download,
  dialog, field, switchControl, watchJob, emptyState, shortTitle, session } from "../lib.js";
import { forgetFrameworks } from "./options.js";
import { showHistory, askWhy } from "./versions.js";

const WHERE = { project: ["This project", "folder"], home: ["All projects", "layers"], bundled: ["Ships with ENLENS", "library"] };
const drafts = new Map();   // unsaved edits, kept while you look at another page: `${project}:${name}` -> {st, merges}

function whereBadge(where) {
  const [t, ic] = WHERE[where] || [where, "circle"];
  return h("span", { class: `badge cb-where cb-where-${where}` }, icon(ic, { size: 12 }), t);
}

// A CSV file as text: UTF-8, else the Windows code page of a spreadsheet saved in Europe (f.text() read every file as
// UTF-8 and garbled the others: ő and ű mark the Central European page).
async function readCsv(f) {
  const bytes = new Uint8Array(await f.arrayBuffer());
  try { return new TextDecoder("utf-8", { fatal: true }).decode(bytes).replace(/^\uFEFF/, ""); }
  catch (_) { return new TextDecoder(bytes.some((b) => b === 0xF5 || b === 0xD5) ? "windows-1250" : "windows-1252").decode(bytes); }
}

// ---------------------------------------------------------------------------------------------
// the list
// ---------------------------------------------------------------------------------------------
export async function renderCodebooks(view) {
  const project = App.project;
  const base = `/api/projects/${P(project)}/codebooks`;
  const newBtn = h("button", { class: "btn btn-primary", type: "button", onClick: () => newCodebook() }, icon("plus", { size: 14 }), "New codebook");
  view.appendChild(pageHead("Codebooks", {
    eyebrow: featureEyebrow("codebooks"),
    sub: "The codes Profile and the Codes panel look for, and that a hypothesis can be tagged with. A codebook stays a CSV file, so it still opens in a spreadsheet.",
    actions: newBtn,
  }));
  const box = h("div", { class: "cb-list" });
  view.appendChild(box);
  let data;
  try { data = await api("GET", base); } catch (e) { failedLoad(box, e); return; }
  for (const b of data.problems || []) {
    box.appendChild(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("p", {}, `The codebook file ${b.file} (${b.source === "home" ? "for all projects" : "in this project"}) cannot be used: ${b.error}`)));
  }
  const own = data.codebooks.filter((c) => c.where !== "bundled");
  const ships = data.codebooks.filter((c) => c.where === "bundled");
  const card = (c) => h("li", { class: "cb-card" },
    h("a", { class: "cb-card-main", href: `#/codebooks/${encodeURIComponent(c.name)}` },
      h("span", { class: "cb-card-title" }, c.title || c.name),
      h("span", { class: "cb-card-sub" }, `${plural(c.codes, "code")}${c.groups ? ` in ${plural(c.groups, "group")}` : ""} · each is called “${c.label}”`),
      h("span", { class: "cb-card-use" }, whereBadge(c.where),
        c.labels ? h("span", { class: "muted" }, plural(c.labels, "label")) : null,
        c.checks ? h("span", { class: "muted" }, plural(c.checks, "check")) : null,
        c.profile_default ? h("span", { class: "badge badge-accent" }, icon("tag", { size: 11 }), "Profile uses it") : null)),
    h("span", { class: "cb-card-go", "aria-hidden": "true" }, icon("chevron-right", { size: 16 })));
  if (!own.length) {
    box.appendChild(h("div", { class: "card cb-start" }, h("h2", { class: "card-title" }, "Make a codebook of your own"),
      h("p", {}, "Start fresh, from the themes already found in the documents, as a copy of the SDG targets, or from a spreadsheet. Each code gets a definition, when to use it and when not, the words it is matched by and examples from the documents."),
      h("div", { class: "btn-row" }, h("button", { class: "btn btn-primary", type: "button", onClick: () => newCodebook("themes") }, icon("shapes", { size: 14 }), "Start from the themes"),
        h("button", { class: "btn", type: "button", onClick: () => newCodebook("fresh") }, icon("plus", { size: 14 }), "Start fresh"))));
  } else {
    box.append(h("h2", { class: "cb-h2" }, "Your codebooks"), h("ul", { class: "cb-cards" }, own.map(card)));
  }
  box.append(h("h2", { class: "cb-h2" }, "Ship with ENLENS"), h("ul", { class: "cb-cards" }, ships.map(card)),
    h("p", { class: "muted small" }, "To change one of these, open it and make a copy."));
}

// "New codebook": its name, where it is kept, and how it starts. `start`: preselected way to start.
export async function newCodebook(start = "fresh", opts = {}) {
  const project = App.project;
  const base = `/api/projects/${P(project)}/codebooks`;
  const title = h("input", { class: "input", type: "text", maxlength: 200, placeholder: "e.g. Remote work and wellbeing", value: opts.title || "" });
  const name = h("input", { class: "input", type: "text", maxlength: 40, placeholder: "e.g. remote_work" });
  let nameTouched = false;
  name.addEventListener("input", () => { nameTouched = true; });
  title.addEventListener("input", () => { if (!nameTouched) name.value = title.value.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40); });
  const whereSel = h("div", { class: "seg-pick", role: "radiogroup", "aria-label": "Kept" });
  let where = "project";
  for (const [w, t] of [["project", "With this project"], ["home", "With all my projects"]]) {
    const b = h("button", { type: "button", role: "radio", class: "seg-choice", "aria-checked": w === where ? "true" : "false", onClick: () => {
      where = w; for (const x of whereSel.children) x.setAttribute("aria-checked", x === b ? "true" : "false");
    } }, t);
    whereSel.appendChild(b);
  }
  const startSel = h("div", { class: "cb-start-pick", role: "radiogroup", "aria-label": "Start" });
  const STARTS = [["fresh", "Start fresh", "An empty codebook: add codes and groups yourself.", "plus"],
    ["themes", "From the themes", "The themes found in the documents become draft codes: their names, descriptions, key terms and best passages. Tick the ones to keep.", "shapes"],
    ["copy", "A copy of a codebook", "The SDG targets or one of yours, to change.", "copy"],
    ["csv", "From a CSV file", "Columns code and description (and group, group_name, when_to_use, when_not_to_use, keywords, examples).", "upload"]];
  let fws = [];
  try { fws = (await api("GET", base)).codebooks; } catch (_) { /* the copy choice lists none */ }
  const copySel = h("select", { class: "input", "aria-label": "Codebook to copy" }, fws.map((f) => h("option", { value: f.name, selected: f.name === opts.of }, `${f.title || f.name} (${f.codes} codes)`)));
  const file = h("input", { type: "file", accept: ".csv,text/csv", class: "input", "aria-label": "CSV file" });
  const extra = h("div", { class: "cb-start-extra" });
  const drawExtra = () => { replace(extra, start === "copy" ? field("Copy of", copySel) : start === "csv" ? field("CSV file", file) : null); };
  for (const [k, t, sub, ic] of STARTS) {
    const b = h("button", { type: "button", role: "radio", class: "cb-start-opt", "aria-checked": k === start ? "true" : "false", onClick: () => {
      start = k; for (const x of startSel.children) x.setAttribute("aria-checked", x === b ? "true" : "false"); drawExtra();
      const go = b.closest("dialog") && b.closest("dialog").querySelector(".dialog-actions .btn-primary");
      if (go) go.textContent = start === "themes" ? "Next" : "Create";   // themes: a second step to tick them
    } }, icon(ic, { size: 16 }), h("span", {}, h("strong", {}, t), h("span", { class: "muted small" }, sub)));
    startSel.appendChild(b);
  }
  drawExtra();
  const err = h("div", { class: "field-error", role: "alert" });
  const r = await dialog({
    title: "New codebook", wide: true,
    body: h("div", { class: "stack" }, h("div", { class: "fields-2" }, field("Title", title), field("Short name", name, { help: "letters, digits, - and _ (the file's name)" })),
      h("div", { class: "field" }, h("span", { class: "field-label" }, "Kept"), whereSel, h("div", { class: "field-help" }, "All my projects: every project can use it, and a change shows in each. A project can still take its own copy later.")),
      h("div", { class: "field" }, h("span", { class: "field-label" }, "Start"), startSel, extra), err),
    actions: [{ text: "Cancel", value: null }, { text: start === "themes" ? "Next" : "Create", value: true, primary: true, onClick: async () => {
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
    body.source = { csv: await readCsv(f) };
  }
  if (start === "themes") {
    const picked = await pickThemes(where === "home");
    if (!picked) return;
    body.source = { codes: picked };
  }
  try {
    const res = await api("POST", base, body);
    forgetFrameworks();
    toast("Codebook made. The research log says so.", "ok");
    location.hash = `#/codebooks/${encodeURIComponent(res.codebook.name)}`;
  } catch (e) { showError(e); }
}

// The themes found (this project's, and with `all` every project's) to start from: tick the ones to keep.
async function pickThemes(all) {
  const base = `/api/projects/${P(App.project)}/codebooks/sources`;
  let runs;
  try { runs = (await api("GET", `${base}${all ? "?all=1" : ""}`)).runs; } catch (e) { showError(e); return null; }
  if (!runs.length) {
    await dialog({ title: "No themes yet", body: h("div", {}, h("p", {}, "Find the themes of the documents first (Themes, in the sidebar): they take seconds and need no AI."),
      h("a", { class: "btn btn-sm", href: "#/themes" }, icon("shapes", { size: 14 }), "Go to Themes")) });
    return null;
  }
  const boxes = [];
  const list = h("div", { class: "cb-theme-pick" });
  runs.forEach((run, i) => {
    const fs = h("fieldset", { class: "cb-run" }, h("legend", {}, `${run.here ? "Themes" : `Themes of ${run.project}`} found on ${fmt.dateShort(run.created_at)}`,
      h("span", { class: "muted small" }, ` · ${plural(run.themes.length, "theme")}`)));
    for (const t of run.themes) {
      const cb = h("input", { type: "checkbox", checked: i === 0 });
      boxes.push([cb, t]);
      fs.appendChild(h("label", { class: "cb-theme" }, cb, h("span", {}, h("strong", {}, t.name), h("span", { class: "muted small" }, ` · ${plural(t.size, "passage")}`),
        h("span", { class: "cb-theme-desc" }, t.code.described ? t.code.description : `Key terms: ${t.code.keywords.join(", ") || "none"}`))));
    }
    list.appendChild(fs);
  });
  const r = await dialog({ title: "Start from the themes", wide: true,
    body: h("div", {}, h("p", {}, "Each theme you tick becomes a draft code: its name, its description (where the AI named it), its key terms as the words it is matched by, and its best passages as examples. Removed themes are left out. You edit them next."), list),
    actions: [{ text: "Cancel", value: null }, { text: "Make the codebook", value: true, primary: true }] });
  if (!r) return null;
  const picked = boxes.filter(([cb]) => cb.checked).map(([, t]) => t.code);
  if (!picked.length) { toast("Tick at least one theme.", "info"); return null; }
  // two themes with the same name become two codes: the second gets a number
  const seen = new Map();
  for (const c of picked) {
    const k = c.code.toLowerCase();
    const n = (seen.get(k) || 0) + 1;
    seen.set(k, n);
    if (n > 1) c.code = `${c.code.slice(0, 36)} (${n})`;
  }
  return picked;
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
    if (e.status === 404) { view.appendChild(emptyState("search-x", "No such codebook", "It was removed, or it belongs to another project.", h("a", { class: "btn", href: "#/codebooks" }, "All codebooks"))); return; }
    throw e;
  }
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
  const notices = h("div");
  const body = h("div", { class: "cb-editor" });
  const saveBar = h("div", { class: "cb-savebar", hidden: true, role: "region", "aria-label": "Unsaved changes" });
  view.append(head, notices, body, saveBar);

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
      moreItems.push(["trash", "Remove the codebook", removeCodebook]);
    }
    const more = moreItems.length ? h("details", { class: "menu cb-more" }, h("summary", { class: "btn btn-ghost btn-sm", "aria-label": "More" }, icon("more-horizontal", { size: 15 })),
      h("div", { class: "menu-list", role: "menu" }, moreItems.map(([ic, t, fn]) => h("button", { class: "menu-item", type: "button", role: "menuitem", onClick: (e) => { e.target.closest("details").open = false; fn(); } }, icon(ic, { size: 14 }), t)))) : null;
    replace(head, pageHead(cb.title || cb.name, {
      eyebrow: h("span", {}, h("a", { href: "#/codebooks", class: "it" }, icon("book-marked", { size: 12 }), "All codebooks")),
      sub: h("span", { class: "cb-meta" }, whereBadge(cb.where), `${plural(st.codes.length, "code")} · each is called “${st.label}”`,
        cb.used.labels ? ` · ${plural(cb.used.labels, "label")} in this project` : "", cb.used.checks ? ` · ${plural(cb.used.checks, "check")}` : "",
        cb.shadows_home ? h("span", { class: "muted" }, " · this project's own copy of a codebook kept with all projects") : null),
      actions: h("div", { class: "btn-row" },
        ro ? h("button", { class: "btn btn-primary btn-sm", type: "button", onClick: () => newCodebook("copy", { of: cb.name, title: `${cb.title} (copy)` }) }, icon("copy", { size: 14 }), "Make a copy to change it") : null,
        h("button", { class: "btn btn-sm", type: "button", title: "Without AI: how many passages and documents the keyword pass would pick for each code", onClick: tryIt }, icon("zap", { size: 14 }), "Try it"),
        ro ? null : h("button", { class: "btn btn-ghost btn-sm", type: "button", title: "Earlier versions: compare them with now, or restore one",
          onClick: () => { if (dirty) { toast("Save or discard your changes first: a restore would replace them.", "info"); return; } showHistory({ kind: "codebook", key: cb.name, onRestored: reload }); } },
          icon("history", { size: 14 }), "History"),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onClick: () => download(`${base}.csv`).catch(showError) }, icon("download", { size: 14 }), "CSV"),
        more),
    }));
  }

  // ---- notices: removed codes whose labels wait, codes labelled with an earlier wording
  function drawNotices() {
    clear(notices);
    if (saved && dirty) notices.appendChild(h("div", { class: "notice notice-info" }, icon("info"), h("p", {}, "Your unsaved changes from before are kept below: save them or discard them.")));
    if (setAside) notices.appendChild(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("p", {}, "The codebook changed since your unsaved changes (it was restored, or changed elsewhere), so they were discarded rather than saved over it. It is shown as it is now.")));
    const stale = Object.entries(cb.stale || {});
    if (stale.length) {
      notices.appendChild(h("div", { class: "notice notice-warn cb-stale" }, icon("alert-triangle"), h("div", {},
        h("p", {}, h("strong", {}, "The AI labelled with an earlier wording. "), "These codes changed after the AI used them. Their labels stay as they are until you ask for these passages to be labelled again (only those passages)."),
        h("ul", {}, stale.map(([code, s]) => h("li", {}, h("strong", {}, code), ` · ${plural(s.passages, "passage")} labelled before ${fmt.date(s.since)} `,
          h("button", { class: "btn btn-sm", type: "button", onClick: () => relabel(code) }, icon("refresh", { size: 13 }), "Label them again")))))));
    }
    if ((cb.removed || []).length) {
      notices.appendChild(h("details", { class: "card cb-removed" }, h("summary", {}, icon("inbox", { size: 15 }), h("strong", {}, `Removed codes (${cb.removed.length})`), h("span", { class: "muted small" }, " · their labels wait here, not deleted")),
        h("ul", {}, cb.removed.map((r) => h("li", {}, h("strong", {}, r.code), ` · ${plural(r.labels, "label")}`, r.description ? h("span", { class: "muted" }, ` · ${shortTitle(r.description, 90)}`) : null,
          r.definition && r.definition.merged_into ? h("span", { class: "muted small" }, ` · merged into ${r.definition.merged_into}; these passages had both`) : null,
          !ro && r.uid ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => bringBack(r) }, icon("undo", { size: 13 }), "Bring it back") : null)))));
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
    drawNotices();
    clear(body);
    if (!ro) {
      body.appendChild(h("details", { class: "card cb-settings" }, h("summary", {}, icon("sliders", { size: 14 }), "Codebook settings"),
        h("div", { class: "fields-2" },
          field("Title", input(st.title, (v) => { st.title = v; }, { maxlength: 200 })),
          field("What one code is called", input(st.label, (v) => { st.label = v || "code"; }, { maxlength: 40 }), { help: "e.g. code, theme, category" })),
        (() => { const sw = switchControl("Its codes are aims a text can help or hinder", st.directional, { help: "Like the SDG targets: the AI's labels then also say whether a passage helps, hinders or does not say." });
          sw.input.addEventListener("change", () => { st.directional = sw.input.checked; touch(); }); return sw; })()));
    }
    if (!st.codes.length) {
      body.appendChild(h("div", { class: "empty" }, icon("book-marked", { size: 28 }), h("h3", {}, "No codes yet"), h("p", {}, "Add a first code: a short name and a sentence that says what it is about.")));
    }
    for (const g of groupsInOrder()) {
      const codes = st.codes.filter((c) => c.group === g.group);
      if (!codes.length && ro) continue;
      const sec = h("section", { class: "cb-group", dataset: { group: g.group } });
      const gName = ro ? h("h2", { class: "cb-group-name" }, g.group_name || g.group || "Codes without a group")
        : input(g.group_name, (v) => { const x = st.groups.find((y) => y.group === g.group); if (x) x.group_name = v; else st.groups.push({ group: g.group, group_name: v }); },
          { class: "input cb-group-input", placeholder: g.group ? `Group ${g.group}` : "Codes without a group", "aria-label": "Group name" });
      if (g.group && gName.tagName === "INPUT") gName.title = `Short name in the CSV file: ${g.group}`;
      sec.appendChild(h("div", { class: "cb-group-head" }, gName,
        h("span", { class: "muted small" }, plural(codes.length, "code")),
        ro ? null : h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => addCode(g.group) }, icon("plus", { size: 13 }), "Add a code")));
      const ul = h("ul", { class: "cb-codes" });
      for (const c of codes) ul.appendChild(codeCard(c));
      if (!ro) dropZone(sec, g.group);
      sec.appendChild(ul);
      body.appendChild(sec);
    }
    if (!ro) body.appendChild(h("div", { class: "btn-row cb-foot" },
      h("button", { class: "btn btn-sm", type: "button", onClick: addGroup }, icon("plus", { size: 13 }), "Add a group"),
      !st.codes.length ? h("button", { class: "btn btn-sm btn-primary", type: "button", onClick: () => addCode("") }, icon("plus", { size: 13 }), "Add a code") : null));
    drawSaveBar();
  }

  function input(value, onChange, attrs = {}) {
    const el = h("input", { class: "input", type: "text", value: value || "", ...attrs });
    el.addEventListener("input", () => { onChange(el.value); touch(); });
    return el;
  }
  function area(value, onChange, attrs = {}) {
    const el = h("textarea", { class: "input", rows: 2, ...attrs }, value || "");
    el.addEventListener("input", () => { onChange(el.value); touch(); });
    return el;
  }

  function codeCard(c) {
    const t = tried && tried.codes[c.code];
    const open = openCode === c.uid || (!c.uid && openCode === c.code);
    const stale = (cb.stale || {})[c.code];
    const li = h("li", { class: "cb-code" + (open ? " cb-open" : ""), dataset: { uid: c.uid || "", code: c.code } });
    const count = t ? h("span", { class: "badge" + (t.note ? " badge-warn" : ""), title: t.note || "" }, `${plural(t.passages, "passage")} · ${plural(t.documents, "doc")}`) : null;
    const summary = h("button", { class: "cb-code-sum", type: "button", "aria-expanded": open ? "true" : "false", onClick: () => {
      openCode = open ? null : (c.uid || c.code); session(`cb-open:${key}`, openCode); draw();
      if (!open) setTimeout(() => { const x = body.querySelector(`.cb-open input`); if (x) x.focus(); }, 0);
    } },
      h("span", { class: "cb-code-name" }, c.code || h("em", { class: "muted" }, "new code")),
      h("span", { class: "cb-code-desc" }, c.description ? shortTitle(c.description, 140) : h("em", { class: "muted" }, "no definition yet")),
      h("span", { class: "cb-code-badges" }, stale ? h("span", { class: "badge badge-warn", title: "Labelled by the AI with an earlier wording" }, "earlier wording") : null,
        (c.examples || []).length ? h("span", { class: "badge" }, icon("quote", { size: 11 }), (c.examples || []).length) : null, count),
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
    sec.addEventListener("dragover", (e) => { e.preventDefault(); sec.classList.add("cb-drop-group"); });
    sec.addEventListener("dragleave", (e) => { if (!sec.contains(e.relatedTarget)) sec.classList.remove("cb-drop-group"); });
    sec.addEventListener("drop", (e) => { e.preventDefault(); sec.classList.remove("cb-drop-group"); moveCode(e.dataTransfer.getData("text/plain"), null, group); });
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
    return h("div", { class: "cb-tried" }, h("p", { class: "small" }, h("strong", {}, "Try it: "), `${plural(t.passages, "passage")} in ${plural(t.documents, "document")}`, t.note ? h("span", { class: "warn-text" }, ` · ${t.note}`) : null),
      t.examples.length ? h("ul", { class: "cb-tried-list" }, t.examples.map((x) => h("li", {}, h("a", { href: `#/doc/${encodeURIComponent(x.doc_id)}` }, shortTitle(x.title || x.doc_id, 60)), x.page ? h("span", { class: "muted" }, ` p. ${x.page}`) : null, ": ", h("span", { class: "serif" }, `“${x.text}”`)))) : null);
  }

  function detail(c, t) {
    const groups = groupsInOrder();
    const groupSel = h("select", { class: "input", "aria-label": "Group" },
      groups.map((g) => h("option", { value: g.group, selected: g.group === c.group }, g.group_name || g.group || "No group")));
    groupSel.addEventListener("change", () => moveCode(c.uid || c.code, null, groupSel.value));
    const kw = input((c.keywords || []).join(", "), (v) => { c.keywords = v.split(/[,;]/).map((x) => x.trim()).filter(Boolean); }, { placeholder: "e.g. commute, commuting, travel to work" });
    const exList = h("ul", { class: "cb-examples" });
    const drawExamples = () => {
      clear(exList);
      (c.examples || []).forEach((e, i) => exList.appendChild(h("li", {}, h("span", { class: "serif" }, `“${e.quote}”`),
        h("span", { class: "muted small" }, e.title ? ` · ${shortTitle(e.title, 50)}${e.page ? `, p. ${e.page}` : ""}` : " · not found in this project's documents"),
        h("button", { class: "link-btn danger-link", type: "button", onClick: () => { c.examples.splice(i, 1); touch(); drawExamples(); } }, "Remove"))));
    };
    drawExamples();
    const exInput = h("textarea", { class: "input", rows: 2, placeholder: "Paste words of a document, exactly as they are there" });
    const exBtn = h("button", { class: "btn btn-sm", type: "button", onClick: async () => {
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
    const mergeSel = h("select", { class: "input cb-merge", "aria-label": `Merge ${c.code} into another code` }, h("option", { value: "" }, "Merge into…"), others.map((x) => h("option", { value: x.uid }, x.code)));
    mergeSel.addEventListener("change", () => mergeInto(c, find(mergeSel.value)));
    return h("div", { class: "cb-detail" },
      h("div", { class: "fields-2" },
        field("Name", input(c.code, (v) => { c.code = v; }, { maxlength: 40 }), { help: "Short: it is how labels and checks name the code." }),
        field("Group", groupSel)),
      field("Definition", area(c.description, (v) => { c.description = v; }, { rows: 3, maxlength: 4000 }), { help: "What the code is about, in a sentence or two. The AI reads it when it labels." }),
      h("div", { class: "fields-2" },
        field("When to use it", area(c.include, (v) => { c.include = v; }, { maxlength: 2000 })),
        field("When not to use it", area(c.exclude, (v) => { c.exclude = v; }, { maxlength: 2000 }))),
      field("Words it is matched by", kw, { help: "Besides its definition, for the keyword pass. Separate them with commas." }),
      h("div", { class: "field" }, h("span", { class: "field-label" }, "Examples from the documents"), exList, exInput, h("div", { class: "btn-row" }, exBtn,
        h("span", { class: "muted small" }, "Each example is checked: it must be words of a document of this project."))),
      triedExamples(t),
      h("div", { class: "btn-row cb-code-actions" },
        h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => step(c, -1), "aria-label": `Move ${c.code} up` }, icon("arrow-up", { size: 13 }), "Up"),
        h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => step(c, 1), "aria-label": `Move ${c.code} down` }, icon("chevron-down", { size: 13 }), "Down"),
        h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => splitCode(c), title: "A second code made from this one; its labels stay with this one" }, icon("split", { size: 13 }), "Split"),
        others.length ? mergeSel : null,
        h("button", { class: "btn btn-sm btn-ghost danger-link", type: "button", onClick: () => removeCode(c) }, icon("trash", { size: 13 }), "Remove")));
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
  const whyInput = h("input", { class: "input cb-why", type: "text", maxlength: 2000, placeholder: "Why? (optional, for the research log)", "aria-label": "Why" });
  const saveBtn = h("button", { class: "btn btn-primary btn-sm", type: "button", onClick: () => save(saveBtn, whyInput.value.trim()) }, icon("check", { size: 14 }), "Save");
  replace(saveBar, h("span", { class: "cb-unsaved" }, icon("alert-circle", { size: 14 }), "Unsaved changes"), whyInput,
    h("button", { class: "btn btn-ghost btn-sm", type: "button", onClick: discard }, "Discard"), saveBtn);
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
  async function tryIt() {
    toast("Trying the codebook on every passage (no AI)…", "info", { small: true, group: "cb-try" });
    try {
      const r = await api("POST", `${base}/try`, { codebook: st });
      const job = await watchJob(r.job.id).promise;
      if (job.state !== "done") { if (job.error) toast(job.error, "error"); return; }
      tried = job.result;
      const none = Object.entries(tried.codes).filter(([, x]) => !x.passages).map(([k]) => k);
      const many = Object.entries(tried.codes).filter(([, x]) => x.note && x.passages).map(([k]) => k);
      toast(`Tried on ${plural(tried.passages, "passage")}.${none.length ? ` ${plural(none.length, "code")} match nothing.` : ""}${many.length ? ` ${plural(many.length, "code")} match a large part of the documents.` : ""} Open a code to see what it picks.`, none.length || many.length ? "warn" : "ok", { group: "cb-try" });
      draw();
    } catch (e) { showError(e); }
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
  return () => window.removeEventListener("beforeunload", onUnload);
}
