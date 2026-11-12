// 0.16 (roadmap F4): the research log. A dated record of what was decided in the project, written by the app as it
// happens (documents added and removed, checks made and dropped, themes removed, codebook changes...), with room for
// a person's own entries and their reasons. An entry about a change can be compared with now and restored (F5).
import { featureEyebrow, viewTabs } from "../features.js";
import { App, api, h, icon, clear, toast, showError, failedLoad, fmt, pageHead, P, confirmDialog, download, downloadLinks,
  debounce, session, dialog, button, card, input, textarea, choice, link, personMark, emptyState } from "../lib.js";
import { compareVersion } from "./versions.js";
import { shareInline, sharingOf } from "./share.js";   // 0.18 (L1)

const GROUP_ICON = { entries: "note", documents: "book-open", checks: "flask", themes: "shapes", codebooks: "book-marked",
  history: "undo", together: "users", other: "circle" };
const GONE = new Set(["document-removed", "check-removed", "themes-removed", "codebook-removed"]);
const VERSION_KIND = { themes: "themes", check: "check", codebook: "codebook" };
const PAGE = 200;

export function subjectHref(e) {
  if (!e.subject_id || GONE.has(e.kind)) return null;
  const id = encodeURIComponent(e.subject_id);
  return { document: `#/doc/${id}`, check: `#/h/${id}`, themes: `#/themes/${id}`, codebook: `#/codebooks/${id}` }[e.subject_kind] || null;
}

// One entry's words and what it is about, the same on the page and in the drawer (docs/DESIGN.md 4.20): the item's
// name is its title link, with no separate "Open". In an entry ENLENS wrote, the item's quoted name is the link
// ("Checked the hypothesis “Working from home…”"); where the words do not quote it, the item is named after "About:",
// as under your own entries, which stay your words (in serif).
const SUBJECT_WORD = { document: "the document", check: "the hypothesis", themes: "the themes", codebook: "the codebook" };
function quotedName(e) {
  const m = /“([^”]+)”/.exec(e.text || "");
  const name = (e.title || "").replace(/[.…]+$/, "").trim();
  return m && name && (name.startsWith(m[1].replace(/…$/, "")) || m[1].startsWith(name)) ? m : null;
}
export function entryText(e, href) {
  if (e.kind === "entry") return h("div", { class: "log-text log-own-text" }, e.text);
  const m = href ? quotedName(e) : null;
  if (!m) return h("div", { class: "log-text" }, e.text);
  const t = e.text;
  return h("div", { class: "log-text" }, t.slice(0, m.index), "“", link({ kind: "title", href }, m[1]), "”", t.slice(m.index + m[0].length));
}
export function entrySubject(e, href) {
  if (!href || (e.kind !== "entry" && quotedName(e))) return null;
  return h("span", { class: "log-subject" }, "About: ", link({ kind: "title", href }, e.title || SUBJECT_WORD[e.subject_kind] || "its item"));
}
// a colleague's entry: a person mark that stands alone (nothing else in the entry names them), so with the name
export function entryWho(e) {
  return e.mine ? null : personMark([e.who], { name: "short" });
}

export async function renderLog(view) {
  const project = App.project;
  const base = `/api/projects/${P(project)}/log`;
  const dl = downloadLinks([
    { text: "Markdown (.md)", title: "The whole log, oldest first, a heading per day: for an appendix or an audit", onClick: () => download(`${base}.md`).catch(showError) },
    { text: "Excel (.xlsx)", onClick: () => download(`${base}.xlsx`).catch(showError) },
  ]);
  view.appendChild(pageHead(project, {
    eyebrow: featureEyebrow("researchlog"),
    sub: "The research log: a dated record of what was decided in this project. ENLENS writes down what happens; add your own entries, and say why next to any of yours.",
  }));
  view.appendChild(viewTabs("overview", "researchlog"));   // 0.17.0: the research log is a view of the Overview
  let group = session(`log-group:${project}`) || "";
  let q = "";
  let shown = PAGE;
  let shares = new Map();   // 0.18 (L1): the sharing state of entries people wrote, by entry id

  // ---- a new entry
  const ta = textarea({ rows: 3, maxlength: 10000, "aria-label": "A new entry",
    placeholder: "A decision, a reason, a field note… (dated and kept with the project)" });
  const addBtn = button({ kind: "main", sm: true, onClick: add }, icon("plus", { size: 14 }), "Add to the log");
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) add(); });
  view.appendChild(card({ class: "log-new", title: "New entry" }, ta,
    h("div", { class: "log-new-foot" }, h("span", { class: "muted" }, "Ctrl/⌘ + Enter adds it."), addBtn)));

  async function add() {
    const text = ta.value.trim();
    if (!text) { ta.focus(); return; }
    addBtn.disabled = true;
    try { await api("POST", base, { text }); ta.value = ""; toast("Added to the research log.", "ok"); await load(); }
    catch (e) { showError(e); } finally { addBtn.disabled = false; }
  }

  // ---- filters and the list
  const chips = h("div", { class: "log-chips" });
  const search = input({ class: "log-search", type: "search", placeholder: "Search the log", "aria-label": "Search the log" });
  search.addEventListener("input", debounce(() => { q = search.value.trim(); shown = PAGE; load(); }, 250));
  const listBox = h("div", { class: "log-list", "aria-live": "polite" });
  view.append(h("div", { class: "log-tools" }, chips, h("div", { class: "log-tools-right" }, search, dl)), listBox);

  async function load() {
    let data;
    try {
      const qs = new URLSearchParams({ limit: String(shown) });
      if (group) qs.set("group", group);
      if (q) qs.set("q", q);
      [data, shares] = await Promise.all([api("GET", `${base}?${qs}`), sharingOf("log")]);
    } catch (e) { failedLoad(listBox, e); return; }
    drawChips(data);
    drawList(data);
  }

  function drawChips(data) {
    clear(chips);
    const total = Object.values(data.groups || {}).reduce((a, b) => a + b, 0);
    const items = [["", "All", total]].concat(Object.entries(data.group_names).filter(([g]) => (data.groups || {})[g]).map(([g, t]) => [g, t, data.groups[g]]));
    // a filter of the list: a choice (docs/DESIGN.md, Choices), so the kind that is on shows as chosen; each kind with
    // its icon and the entries it would show
    chips.appendChild(choice({ label: "Show", filter: true, value: group,
      options: items.map(([g, text, n]) => [g, [g ? icon(GROUP_ICON[g] || "circle", { size: 13 }) : null, text], fmt.num(n)]),
      onPick: (g) => { group = g; session(`log-group:${project}`, g); shown = PAGE; load(); } }));
  }

  function drawList(data) {
    clear(listBox);
    if (!data.entries.length) {
      listBox.appendChild(emptyState("notebook", q || group ? "No entry matches" : "Nothing in the log yet",
        q || group ? "Try other words, or show all entries." : "Entries appear as you work: add documents, check a hypothesis, find themes, or write the first entry above."));
      return;
    }
    let day = null, ul = null;
    for (const e of data.entries) {
      const d = fmt.dateShort(e.at);
      if (d !== day) {
        day = d;
        listBox.appendChild(h("h2", { class: "list-head log-day" }, new Date(e.at).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })));
        ul = h("ol", { class: "log-entries" });
        listBox.appendChild(ul);
      }
      ul.appendChild(entryRow(e));
    }
    if (data.total > data.entries.length) {
      listBox.appendChild(h("div", { class: "more-row" }, button({ kind: "quiet", sm: true,
        onClick: () => { shown += PAGE; load(); } }, `Show more (${fmt.num(data.total - data.entries.length)} older)`)));
    }
  }

  function entryRow(e) {
    const li = h("li", { class: `log-entry log-${e.group}` + (e.kind === "entry" ? " log-own" : "") });
    const href = subjectHref(e);
    const time = h("time", { class: "log-time", datetime: e.at, title: fmt.date(e.at) }, new Date(e.at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }));
    const text = entryText(e, href);
    const who = entryWho(e), about = entrySubject(e, href);
    // 0.18 (L1): an entry you wrote has its sharing state, and Share / Unshare
    const share = e.kind === "entry" && shares.get(e.entry_id) ? shareInline(shares.get(e.entry_id), () => load(), { owner: false }) : null;
    const meta = who || share || about || e.edited_at ? h("div", { class: "log-meta" }, who, share, about,
      e.edited_at ? h("span", { class: "muted" }, `edited ${fmt.dateShort(e.edited_at)}`) : null) : null;
    const why = e.why ? h("p", { class: "log-why" }, h("strong", {}, "Why: "), e.why) : null;
    const actions = h("div", { class: "log-actions" });
    if (e.can_why && e.kind !== "entry") actions.appendChild(button({ kind: "quiet", sm: true, onClick: () => editWhy(e) }, e.why ? "Change why" : "Say why"));
    if (e.can_edit) {
      actions.appendChild(button({ kind: "quiet", sm: true, onClick: () => editEntry(e) }, "Edit"));
      actions.appendChild(button({ kind: "danger", sm: true, onClick: () => removeEntry(e) }, "Remove"));
    }
    if (e.has_version && VERSION_KIND[e.subject_kind]) {
      actions.appendChild(button({ kind: "quiet", sm: true, title: "What changed since just before this, and Restore",
        onClick: () => compareVersion({ kind: VERSION_KIND[e.subject_kind], key: e.subject_id, versionId: e.version_id, onRestored: load }) },
        icon("history", { size: 12 }), "Compare with before"));
    }
    li.append(h("span", { class: "log-icon", "aria-hidden": "true" }, icon(GROUP_ICON[e.group] || "circle", { size: 15 })),
      h("div", { class: "log-body" }, h("div", { class: "log-line" }, time, text), why, meta, actions.childNodes.length ? actions : null));
    return li;
  }

  async function editWhy(e) {
    const ta2 = textarea({ rows: 3, maxlength: 2000 });
    ta2.value = e.why || "";
    const r = await textDialog(`Why? ${e.text.length > 80 ? e.text.slice(0, 79) + "…" : e.text}`, ta2, "Save");
    if (r === null) return;
    try { await api("PUT", `${base}/${P(e.entry_id)}`, { why: ta2.value }); await load(); } catch (err) { showError(err); }
  }

  async function editEntry(e) {
    const ta2 = textarea({ rows: 5, maxlength: 10000 });
    ta2.value = e.text;
    const r = await textDialog("Edit your entry", ta2, "Save");
    if (r === null) return;
    try { await api("PUT", `${base}/${P(e.entry_id)}`, { text: ta2.value }); await load(); } catch (err) { showError(err); }
  }

  async function removeEntry(e) {
    if (!(await confirmDialog({ title: "Remove your entry?", message: "It is removed from the log here and, once your work is sent, from your colleagues' copies.", confirmText: "Remove" }))) return;
    try { await api("DELETE", `${base}/${P(e.entry_id)}`); await load(); } catch (err) { showError(err); }
  }

  await load();
}

async function textDialog(title, control, ok) {
  const r = await dialog({ title, body: h("div", {}, control), actions: [{ text: "Cancel", value: null }, { text: ok, value: true, primary: true }],
    onOpen: () => control.focus() });
  return r ? true : null;
}

