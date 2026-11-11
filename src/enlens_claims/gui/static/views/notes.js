// 0.16 (roadmap F2): notes and highlights on exact words of the documents. This page lists them all, searchable; the
// document page is where they are made (select words in its text) and shown in place. A note can be evidence in a
// check: the passage holding its words becomes an excerpt you judged, with the note's words as your sentence.
import { featureEyebrow, viewTabs } from "../features.js";
import { App, api, h, icon, clear, toast, showError, failedLoad, fmt, pageHead, P, plural, confirmDialog, download,
  downloadLinks, debounce, dialog, shortTitle, GRADE_TEXT, button, link, choice, input, select, textarea, card, optionCards, emptyState } from "../lib.js";

export const COLOUR_NAME = { yellow: "Yellow", green: "Green", blue: "Blue", pink: "Pink" };
const COLOURS = ["yellow", "green", "blue", "pink"];

export function colourDot(c) {
  return h("span", { class: `hl-dot hl-${c || "yellow"}`, "aria-hidden": "true" });
}

// The colour choice: four swatches as radio buttons
export function colourPicker(current, onPick) {
  const box = h("div", { class: "hl-picker", role: "radiogroup", "aria-label": "Colour" });
  for (const c of COLOURS) {
    const b = h("button", { class: `hl-swatch hl-${c}`, type: "button", role: "radio", "aria-checked": c === current ? "true" : "false",
      title: COLOUR_NAME[c], "aria-label": COLOUR_NAME[c], onClick: () => {
        for (const x of box.querySelectorAll(".hl-swatch")) x.setAttribute("aria-checked", x === b ? "true" : "false");
        onPick(c);
      } });
    box.appendChild(b);
  }
  return box;
}

// Edit a note's words and colour. Returns the saved note, or null.
export async function editNote(note) {
  let colour = note.colour || "yellow";
  const ta = textarea({ rows: 5, maxlength: 10000, placeholder: "Your note (leave empty for a highlight)" });
  ta.value = note.text || "";
  const body = h("div", {}, h("blockquote", { class: "note-quote" }, note.quote),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Note"), ta),
    h("div", { class: "field" }, h("span", { class: "field-label" }, "Colour"), colourPicker(colour, (c) => { colour = c; })));
  const r = await dialog({ title: "Your note", body, actions: [{ text: "Cancel", value: null }, { text: "Save", value: true, primary: true }],
    onOpen: () => ta.focus() });
  if (!r) return null;
  try {
    const res = await api("PUT", `/api/projects/${P(App.project)}/notes/${P(note.note_id)}`, { text: ta.value, colour });
    return res.note;
  } catch (e) { showError(e); return null; }
}

export async function removeNote(note) {
  if (!(await confirmDialog({ title: "Remove this note?", message: note.text ? `“${shortTitle(note.text, 120)}” and its highlight are removed.` : "The highlight is removed.", confirmText: "Remove" }))) return false;
  try { await api("DELETE", `/api/projects/${P(App.project)}/notes/${P(note.note_id)}`); return true; } catch (e) { showError(e); return false; }
}

// Use a note as evidence in a check: choose the check and its part, and your judgement.
export async function useAsEvidence(note) {
  const base = `/api/projects/${P(App.project)}`;
  let list;
  try { list = (await api("GET", `${base}/hypotheses`)).hypotheses || []; } catch (e) { showError(e); return null; }
  if (!list.length) {
    await dialog({ title: "Use as evidence", body: h("p", {}, "There is no check in this project yet. Check a hypothesis first, then add this note to it as evidence.") });
    return null;
  }
  const sel = select({ "aria-label": "Check" }, h("option", { value: "" }, "Choose a check…"),
    list.map((x) => h("option", { value: x.hyp_id }, shortTitle(x.text, 110))));
  const partBox = h("div", { class: "field", hidden: true });
  const partSel = select({ "aria-label": "Part of the hypothesis" });
  partBox.append(h("label", { class: "field-label" }, "Part of the hypothesis"), partSel);
  let verdict = "supports";
  const verdicts = choice({ label: "Your judgement", value: verdict, onPick: (v) => { verdict = v; },
    options: [["supports", GRADE_TEXT.supports], ["partially_supports", GRADE_TEXT.partially_supports], ["refutes", GRADE_TEXT.refutes], ["not_relevant", "Not about it"]] });
  const comment = textarea({ rows: 2, maxlength: 2000, placeholder: "Optional: a comment with your judgement" });
  let parts = [];
  sel.addEventListener("change", async () => {
    clear(partSel);
    partBox.hidden = true;
    parts = [];
    if (!sel.value) return;
    try {
      const r = await api("GET", `${base}/hypotheses/${P(sel.value)}`);
      parts = r.parts || [];
    } catch (e) { showError(e); return; }
    if (parts.length > 1) {
      for (const p of parts) partSel.appendChild(h("option", { value: p.claim_id }, shortTitle(p.claim, 110)));
      partBox.hidden = false;
    }
  });
  const body = h("div", { class: "evidence-dlg" },
    h("blockquote", { class: "note-quote" }, note.quote),
    h("p", { class: "muted" }, "The passage that holds these words becomes an excerpt of the check, judged by you, with these words as the sentence you point to. Your judgement counts as every judgement of yours does."),
    h("div", { class: "field" }, h("label", { class: "field-label" }, "Check"), sel), partBox,
    h("div", { class: "field" }, h("span", { class: "field-label" }, "Your judgement"), verdicts),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Comment"), comment));
  const r = await dialog({ title: "Use this note as evidence", wide: true, body,
    actions: [{ text: "Cancel", value: null }, { text: "Add as evidence", value: true, primary: true, onClick: () => {
      if (!sel.value) { sel.focus(); toast("Choose a check first.", "info"); return false; }
      return true;
    } }] });
  if (!r) return null;
  const claimId = parts.length > 1 ? partSel.value : (parts[0] && parts[0].claim_id);
  if (!claimId) { toast("This check has no part to add evidence to yet.", "info"); return null; }
  try {
    const res = await api("POST", `${base}/notes/${P(note.note_id)}/evidence`, { claim_id: claimId, verdict, comment: comment.value.trim() || null });
    toast(res.new ? "Added to the check as an excerpt you judged." : "The check had this passage already: your judgement of it is set, with the note's words.", "ok",
      { action: { text: "Open the check", href: `#/h/${encodeURIComponent(res.hyp_id)}` } });
    return res;
  } catch (e) { showError(e); return null; }
}

export async function renderNotes(view, _params, query) {
  const project = App.project;
  const base = `/api/projects/${P(project)}/notes`;
  view.appendChild(pageHead("Documents", {
    eyebrow: featureEyebrow("annotations"),
    sub: "Your highlights and notes on the documents' own words. To add one, open a document and select words in its text.",
  }));
  view.appendChild(viewTabs("documents", "annotations"));   // 0.17.0: Notes is a view of Documents
  let q = (query && query.q) || "", doc = (query && query.doc) || "", colour = "";
  const search = input({ type: "search", value: q, placeholder: "Search your notes and the words they mark", "aria-label": "Search notes" });
  search.addEventListener("input", debounce(() => { q = search.value.trim(); load(); }, 250));
  const docSel = select({ class: "notes-doc", "aria-label": "Document" });
  docSel.addEventListener("change", () => { doc = docSel.value; load(); });
  const colourChips = choice({ filter: true, label: "Colour", value: colour, onPick: (c) => { colour = c; load(); },
    options: ["", ...COLOURS].map((c) => [c, [c ? colourDot(c) : null, c ? COLOUR_NAME[c] : "All colours"]]) });
  const dl = downloadLinks([
    { text: "Markdown (.md)", onClick: () => download(`${base}.md`).catch(showError) },
    { text: "Excel (.xlsx)", onClick: () => download(`${base}.xlsx`).catch(showError) },
  ]);
  const listBox = h("div", { class: "notes-list", "aria-live": "polite" });
  view.append(h("div", { class: "notes-tools" }, search, docSel, colourChips, dl), listBox);

  async function load() {
    let data;
    const qs = new URLSearchParams({ limit: "2000" });
    if (q) qs.set("q", q);
    if (doc) qs.set("doc", doc);
    if (colour) qs.set("colour", colour);
    try { data = await api("GET", `${base}?${qs}`); } catch (e) { failedLoad(listBox, e); return; }
    clear(docSel);
    docSel.appendChild(h("option", { value: "" }, "All documents"));
    for (const d of data.documents) docSel.appendChild(h("option", { value: d.doc_id, selected: d.doc_id === doc }, `${shortTitle(d.title || d.doc_id, 60)} (${d.notes})${d.present ? "" : " · removed"}`));
    draw(data);
  }

  function draw(data) {
    clear(listBox);
    if (!data.notes.length) {
      listBox.appendChild(emptyState("highlighter", q || doc || colour ? "No note matches" : "No notes yet",
        q || doc || colour ? "Try other words or show every note." : "Open a document, select a few words in its text and choose Highlight or Note.",
        q || doc || colour ? null : link({ kind: "next", href: "#/sources" }, "Open a document on the Documents page")));
      return;
    }
    listBox.appendChild(h("p", { class: "muted notes-count" }, data.total > data.notes.length ? `${fmt.num(data.notes.length)} of ${fmt.num(data.total)} notes` : plural(data.total, "note", "notes")));
    const byDoc = new Map();
    for (const n of data.notes) {
      if (!byDoc.has(n.doc_id)) byDoc.set(n.doc_id, []);
      byDoc.get(n.doc_id).push(n);
    }
    for (const [did, ns] of byDoc) {
      ns.sort((a, b) => a.start - b.start);
      const first = ns[0];
      listBox.appendChild(h("h2", { class: "notes-doc-title" }, first.present ? link({ kind: "title", serif: true, href: `#/doc/${encodeURIComponent(did)}?tab=notes` }, first.title || did) : h("span", {}, first.title || did, h("span", { class: "muted" }, " · removed from the project"))));
      const ul = h("ul", { class: "notes-cards" });
      for (const n of ns) ul.appendChild(noteCard(n, load));
      listBox.appendChild(ul);
    }
  }

  await load();
}

// One note as a card: its words, the note, where it is, and what can be done with it. `onChange()` after a change.
export function noteCard(n, onChange, opts = {}) {
  // a note: a small card in a list of many (docs/DESIGN.md 4.11)
  const li = card({ as: "li", sm: true, class: "note-card" + (n.lost ? " note-lost" : "") });
  const where = [n.page !== null && n.page !== undefined ? `p. ${n.page}` : null, n.mine ? null : n.who, fmt.dateShort(n.edited_at || n.created_at)].filter(Boolean).join(" · ");
  const actions = h("div", { class: "note-actions" });
  if (n.present && !n.lost && !opts.inDocument) {
    actions.appendChild(link({ href: `#/doc/${encodeURIComponent(n.doc_id)}?at=${n.start}&tab=notes` }, icon("book-open", { size: 12 }), "In the document"));
  } else if (opts.inDocument && opts.onJump && !n.lost) {
    actions.appendChild(link({ kind: "jump", onClick: () => opts.onJump(n) }, icon("arrow-right", { size: 12 }), "Show in the text"));
  }
  if (n.present && !n.lost) actions.appendChild(button({ kind: "quiet", sm: true, onClick: () => useAsEvidence(n).then((r) => { if (r && onChange) onChange(); }) }, icon("flask", { size: 12 }), "Use as evidence"));
  if (n.mine) {
    actions.appendChild(button({ kind: "quiet", sm: true, onClick: async () => { if (await editNote(n) && onChange) onChange(); } }, "Edit"));
    actions.appendChild(button({ kind: "danger", sm: true, onClick: async () => { if (await removeNote(n) && onChange) onChange(); } }, "Remove"));
  }
  li.append(...[h("blockquote", { class: `note-quote hl-${n.colour || "yellow"}` }, n.quote),
    n.text ? h("p", { class: "note-text" }, n.text) : null,
    n.lost ? h("p", { class: "note-warn" }, icon("alert-triangle", { size: 13 }), "These words are not in the document's text now (it was read again). The note is kept.") : null,
    h("div", { class: "note-foot" }, h("span", { class: "muted" }, where), actions)].filter(Boolean));   // append(null) writes "null"
  return li;
}

// From a check's part: choose one of the project's notes (searchable) and your judgement, and add it as evidence.
// Returns the server's answer, or null.
export async function addNoteToPart(claimId, partText) {
  const base = `/api/projects/${P(App.project)}`;
  let all;
  try { all = (await api("GET", `${base}/notes?limit=500`)).notes.filter((n) => n.present && !n.lost); } catch (e) { showError(e); return null; }
  if (!all.length) {
    await dialog({ title: "Add one of your notes", body: h("div", {}, h("p", {}, "You have no notes yet. Open a document, select the words that bear on the hypothesis and choose Note or Highlight; then add it here."),
      link({ kind: "next", href: "#/sources" }, "Open a document on the Documents page")) });
    return null;
  }
  let chosen = null, verdict = "supports";
  const search = input({ type: "search", placeholder: "Search your notes", "aria-label": "Search your notes" });
  const list = h("div", { class: "note-pick" });
  // which note: option cards (docs/DESIGN.md 4.7), each headed by its document and page, then its words in serif
  const draw = () => {
    clear(list);
    const q = search.value.trim().toLowerCase();
    const shown = all.filter((n) => !q || `${n.quote} ${n.text || ""} ${n.title || ""}`.toLowerCase().includes(q)).slice(0, 80);
    if (!shown.length) { list.appendChild(h("p", { class: "muted small" }, "No note matches.")); return; }
    list.appendChild(optionCards({ label: "Your notes", value: shown.indexOf(chosen), onPick: (i) => { chosen = shown[i]; },
      options: shown.map((n, i) => ({ value: i, icon: "note",
        title: `${shortTitle(n.title || n.doc_id, 60)}${n.page !== null && n.page !== undefined ? `, p. ${n.page}` : ""}`,
        text: [h("span", { class: "serif" }, `“${shortTitle(n.quote, 160)}”`), n.text ? [" ", shortTitle(n.text, 120)] : null] })) }));
  };
  search.addEventListener("input", draw);
  draw();
  const verdicts = choice({ label: "Your judgement", value: verdict, onPick: (v) => { verdict = v; },
    options: [["supports", GRADE_TEXT.supports], ["partially_supports", GRADE_TEXT.partially_supports], ["refutes", GRADE_TEXT.refutes], ["not_relevant", "Not about it"]] });
  const r = await dialog({ title: "Add one of your notes as evidence", wide: true,
    body: h("div", { class: "evidence-dlg" }, partText ? h("p", { class: "serif" }, partText) : null,
      h("p", { class: "muted small" }, "The passage that holds the note's words becomes an excerpt of this check, judged by you, with the note's words as your sentence."),
      search, list, h("div", { class: "field" }, h("span", { class: "field-label" }, "Your judgement"), verdicts)),
    actions: [{ text: "Cancel", value: null }, { text: "Add as evidence", value: true, primary: true, onClick: () => {
      if (!chosen) { toast("Choose a note first.", "info"); return false; }
      return true;
    } }], onOpen: () => search.focus() });
  if (!r || !chosen) return null;
  try { return await api("POST", `${base}/notes/${P(chosen.note_id)}/evidence`, { claim_id: claimId, verdict }); }
  catch (e) { showError(e); return null; }
}
