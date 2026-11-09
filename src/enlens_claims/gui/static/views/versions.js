// 0.16 (roadmap F5): earlier versions of a set of themes, a check (your judgements) or a codebook. *History* lists
// them; *Compare with now* says in words what changed since; *Restore* puts one back (the state it replaces is kept
// as a version too, so a restore can be undone the same way). Also the question "why?" the research log keeps beside
// a removal (F4).
import { App, api, h, icon, dialog, toast, showError, fmt, P, plural } from "../lib.js";

const base = () => `/api/projects/${P(App.project)}/history`;

// A button that opens the history of `kind`/`key`. `onRestored()` is called after a restore (redraw the page).
export function historyButton(kind, key, opts = {}) {
  return h("button", { class: "btn btn-ghost btn-sm", type: "button", title: "Earlier versions: compare them with now, or restore one",
    onClick: () => showHistory({ kind, key, onRestored: opts.onRestored }) }, icon("history", { size: 14 }), opts.text || "History");
}

export async function showHistory({ kind, key, onRestored }) {
  let data;
  try { data = await api("GET", `${base()}/${kind}/${P(key)}`); } catch (e) { showError(e); return; }
  const list = h("div", { class: "versions" });
  if (!data.versions.length) {
    list.appendChild(h("p", { class: "muted" }, "No earlier version yet. A version is kept each time you change it."));
  }
  for (const v of data.versions) {
    list.appendChild(h("div", { class: "version-row" },
      h("div", { class: "version-main" },
        h("div", { class: "version-when" }, fmt.date(v.at), v.mine ? null : h("span", { class: "muted" }, ` · ${v.who}`)),
        h("div", { class: "version-label" }, v.label ? `Before ${v.label}` : "An earlier version")),
      h("div", { class: "version-actions" },
        h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: async (e) => {
          const dlg = e.target.closest("dialog");
          const done = await compareVersion({ kind, key, versionId: v.version_id, onRestored });
          if (done && dlg) { dlg.close(); dlg.remove(); }
        } }, icon("eye", { size: 13 }), "Compare with now"))));
  }
  await dialog({
    title: `History of ${data.title}`, wide: true,
    body: h("div", {}, h("p", { class: "muted" }, "The state before each change, newest first. Restoring one keeps the present state as a version too, so nothing is lost."), list),
  });
}

// The changes from a version to now, with Restore. Returns true when it was restored.
export async function compareVersion({ kind, key, versionId, onRestored }) {
  let data;
  try { data = await api("GET", `${base()}/${kind}/${P(key)}/${P(versionId)}`); } catch (e) { showError(e); return false; }
  const body = h("div", {},
    h("p", {}, `The version of ${fmt.date(data.version.at)}${data.version.who && data.version.who !== "you" ? `, by ${data.version.who}` : ""}, compared with now.`),
    data.same ? h("p", { class: "muted" }, "It is the same as now: nothing to restore.") : changesTable(data.changes));
  const r = await dialog({
    title: `Compare: ${data.title}`, wide: true, body,
    actions: [{ text: "Close", value: null }].concat(data.same ? [] : [{ text: "Restore this version", value: "restore", primary: true }]),
  });
  if (r !== "restore") return false;
  try {
    const res = await api("POST", `${base()}/${kind}/${P(key)}/${P(versionId)}/restore`, {});
    toast(res.restored ? `Restored (${plural((res.changes || []).length, "change")}). The research log says so; the state before is kept as a version.` : "Nothing to restore: it is the same as now.", "ok");
    if (onRestored) onRestored();
    return true;
  } catch (e) { showError(e); return false; }
}

function changesTable(changes) {
  const tb = h("tbody");
  for (const c of changes) {
    tb.appendChild(h("tr", {}, h("th", { scope: "row" }, c.what),
      h("td", { class: "ch-before" }, c.before || h("span", { class: "muted" }, "(empty)")),
      h("td", { class: "ch-after" }, c.after || h("span", { class: "muted" }, "(empty)"))));
  }
  return h("div", { class: "table-wrap" }, h("table", { class: "table changes-table" },
    h("thead", {}, h("tr", {}, h("th", {}, "What"), h("th", {}, "Then"), h("th", {}, "Now"))), tb));
}

// "Why?" before a removal: an optional reason, kept in the research log beside the entry. Returns null (cancelled)
// or { why } (possibly empty).
export async function askWhy({ title, message, confirmText = "Remove", danger = true, placeholder }) {
  const ta = h("textarea", { class: "input", rows: 3, maxlength: 2000, placeholder: placeholder || "For example: off-topic, a duplicate, outside the scope of the study" });
  const body = h("div", {}, typeof message === "string" ? h("p", {}, message) : message,
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Why? (optional, kept in the research log)"), ta));
  const r = await dialog({ title, body, danger, actions: [{ text: "Cancel", value: false }, { text: confirmText, value: true, primary: true }],
    onOpen: () => ta.focus() });
  return r ? { why: ta.value.trim() } : null;
}

