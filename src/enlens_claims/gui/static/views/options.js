// The options of a check (shared by the Check and Batch pages) and the framework code picker.
import { App, api, h, icon, replace, switchControl, rangeControl, field, dialog, P, debounce, store } from "../lib.js";

export function checkOptions({ docs = [], search = null, compact = false } = {}) {
  const s = App.settings();
  const decompose = switchControl("Check each part separately", s.decompose, { help: "For a hypothesis with several claims in one sentence. It is split into 2–5 parts that must all hold, and each part is checked on its own." });
  const expand = switchControl("Also search for other words (synonyms)", s.expand, { help: "The AI thinks of other words your documents might use for the same thing. Finds more, takes a little longer." });
  const k = rangeControl("How many excerpts the AI reads", { min: 4, max: 12, step: 1, value: Math.min(12, Math.max(4, s.k || 8)), help: "More excerpts find more evidence but take longer." });
  const perDoc = rangeControl("At most this many from one document", { min: 1, max: 4, step: 1, value: Math.min(4, Math.max(1, s.per_doc || 2)), help: "So that one long report does not crowd out the others." });
  const hasIndex = search && search.model && search.embedded > 0;
  const semantic = switchControl("Search by meaning: finds excerpts even when they use other words than your hypothesis", !!hasIndex, {
    help: !search || !search.model ? "Search by meaning is off: documents are searched by their words only. It can be turned on under Settings → Documents." :
      !search.embedded ? "Search by meaning is not set up for this project yet (see Documents)." :
      search.complete ? "Ready for all documents of this project." : `Set up for part of the documents only (finish it under Documents).`,
  });
  if (!hasIndex) semantic.input.disabled = true;

  // only these documents
  const pick = h("div", { class: "doc-pick", role: "group", "aria-label": "Only these documents" });
  const filter = h("input", { class: "input input-sm", type: "search", placeholder: "Find a document…", "aria-label": "Find a document" });
  const boxes = [];
  const drawDocs = (q) => {
    replace(pick);
    const ql = (q || "").toLowerCase();
    let n = 0;
    for (const d of docs) {
      if (ql && !(`${d.title} ${d.file}`.toLowerCase().includes(ql))) continue;
      n++;
      let cb = boxes.find((b) => b.value === d.doc_id);
      if (!cb) { cb = h("input", { type: "checkbox", value: d.doc_id }); boxes.push(cb); }
      pick.appendChild(h("label", {}, cb, h("span", {}, d.title || d.file, d.check ? h("span", { class: "muted" }, ` · ${d.check}`) : null)));
    }
    if (!n) pick.appendChild(h("div", { class: "muted small", style: { padding: "6px" } }, docs.length ? "No document matches." : "No documents in this project yet."));
  };
  drawDocs("");
  filter.addEventListener("input", debounce(() => drawDocs(filter.value), 120));
  const docsField = h("div", { class: "field", style: { gridColumn: "1 / -1" } },
    h("div", { class: "row", style: { justifyContent: "space-between" } }, h("span", { class: "field-label" }, "Search only in these documents"), h("span", { class: "muted small" }, "nothing ticked = all documents")),
    docs.length > 6 ? filter : null, pick);

  const summary = h("summary", {}, h("span", { class: "opt-summary" }, h("strong", {}, "More options"), h("span", { class: "muted", id: "opt-sum" })));
  const details = h("details", { class: "fold" }, summary,
    h("div", { class: "options-grid" }, decompose, expand, semantic, k, perDoc, docsField));
  const el = h("div", { class: "options" }, details);

  const values = () => {
    const chosen = boxes.filter((b) => b.checked).map((b) => b.value);
    return {
      decompose: decompose.input.checked, expand: expand.input.checked,
      k: k.input.valueAsNumber, per_doc: perDoc.input.valueAsNumber,
      semantic: semantic.input.checked,
      doc_ids: chosen.length ? chosen : undefined,
    };
  };
  const refreshSummary = () => {
    const v = values();
    const bits = [];
    if (v.decompose) bits.push("each part separately");
    if (v.doc_ids) bits.push(`${v.doc_ids.length} chosen ${v.doc_ids.length === 1 ? "document" : "documents"}`);
    if (v.k !== 8) bits.push(`${v.k} excerpts`);
    if (!v.expand) bits.push("no synonyms");
    summary.querySelector("#opt-sum").textContent = bits.length ? " · " + bits.join(" · ") : "";
  };
  el.addEventListener("input", refreshSummary);
  el.addEventListener("change", refreshSummary);
  refreshSummary();
  el.values = values;
  return el;
}

// ---------------------------------------------------------------------------------------------
// framework code picker
// ---------------------------------------------------------------------------------------------
const fwCache = new Map();

export async function loadFramework(project, name) {
  const key = `${project}/${name}`;
  if (!fwCache.has(key)) fwCache.set(key, api("GET", `/api/projects/${P(project)}/frameworks/${P(name)}`).then((r) => r.framework));
  return fwCache.get(key);
}
export function forgetFrameworks() { fwCache.clear(); }

export function starredCodes(fw) {
  try { return new Set(JSON.parse(store(`stars.${fw}`) || "[]")); } catch (_) { return new Set(); }
}
export function toggleStar(fw, code) {
  const set = starredCodes(fw);
  if (set.has(code)) set.delete(code); else set.add(code);
  store(`stars.${fw}`, JSON.stringify([...set]));
  return set;
}

// Opens the picker; resolves to {code, description} or null (cleared) or undefined (cancelled).
export function pickCode({ project, framework, suggested = [], current = "" }) {
  return new Promise(async (resolve) => {
    let fw;
    try { fw = await loadFramework(project, framework); } catch (e) { resolve(undefined); throw e; }
    const items = fw.items || [];
    const byCode = new Map(items.map((i) => [i.code, i]));
    const stars = starredCodes(framework);
    const input = h("input", { class: "input", type: "search", placeholder: `Search ${items.length} codes by number or words…`, "aria-label": "Search codes", autocomplete: "off" });
    const list = h("div", { class: "picker-list", role: "listbox", "aria-label": fw.label || "Codes" });
    let picked;
    let dlgRef = null;
    const choose = (code) => { picked = code ? { code, description: (byCode.get(code) || {}).description || "" } : null; dlgRef.querySelector("#dlg-done").click(); };
    const draw = () => {
      replace(list);
      const q = input.value.trim().toLowerCase();
      const words = q.split(/\s+/).filter(Boolean);
      const match = (i) => !words.length || words.every((w) => i.code.toLowerCase().startsWith(w) || (i.description || "").toLowerCase().includes(w) || (i.group_name || "").toLowerCase().includes(w));
      const row = (i, star, sugg) => {
        const b = h("button", { type: "button", class: "picker-item", role: "option", "aria-selected": i.code === current ? "true" : "false", onClick: () => choose(i.code) },
          h("span", { class: "pi-code" }, sugg ? icon("star", { size: 12 }) : null, i.code),
          h("span", { class: "pi-desc" }, i.description || ""));
        b.title = star ? "Starred" : "";
        return b;
      };
      const top = [];
      const suggSet = new Set(suggested.map((s) => s.code));
      if (!q && (suggested.length || stars.size)) {
        if (suggested.length) { top.push(h("div", { class: "picker-group" }, "Suggested from your wording")); suggested.forEach((s) => byCode.has(s.code) && top.push(row(byCode.get(s.code), false, true))); }
        const starred = [...stars].filter((c) => byCode.has(c) && !suggSet.has(c));
        if (starred.length) { top.push(h("div", { class: "picker-group" }, "Starred")); starred.forEach((c) => top.push(row(byCode.get(c), true, false))); }
      }
      top.forEach((n) => list.appendChild(n));
      let group = null, n = 0;
      for (const i of items) {
        if (!match(i)) continue;
        n++;
        const g = i.group_name ? `${i.group ? i.group + " · " : ""}${i.group_name}` : (i.group || "");
        if (g !== group) { group = g; if (g) list.appendChild(h("div", { class: "picker-group" }, g)); }
        list.appendChild(row(i, stars.has(i.code), suggSet.has(i.code)));
        if (n > 400) { list.appendChild(h("div", { class: "muted small", style: { padding: "8px 10px" } }, "More codes: narrow the search.")); break; }
      }
      if (!n) list.appendChild(h("div", { class: "muted small", style: { padding: "8px 10px" } }, "No code matches."));
    };
    input.addEventListener("input", debounce(draw, 80));
    const keyNav = (e) => {
      const opts = [...list.querySelectorAll(".picker-item")];
      const i = opts.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); (opts[i + 1] || opts[0] || input).focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); if (i <= 0) input.focus(); else opts[i - 1].focus(); }
      else if (e.key === "Enter" && e.target === input) { e.preventDefault(); if (opts[0]) opts[0].click(); }
    };
    input.addEventListener("keydown", keyNav);
    list.addEventListener("keydown", keyNav);
    draw();
    const body = h("div", {}, h("p", { class: "muted small" }, fw.title || framework, " · ", h("span", {}, "the AI reads the code's description together with your hypothesis")), input, list);
    await dialog({
      title: `Choose a ${fw.label || "code"}`,
      body, wide: true,
      actions: [{ text: "No code", value: "clear", onClick: () => { picked = null; } }, { text: "Done", value: "done", id: "dlg-done", primary: true }],
      onOpen(dlg) { dlgRef = dlg; input.focus(); },
    });
    resolve(picked);
  });
}
