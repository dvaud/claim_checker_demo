// 0.18.1 (roadmap K2 part 1): a document's role. A theory document is the lens the research is read through, not
// evidence: still read, searched, opened and noted, but left out of themes, codebook labels, the excerpts a check reads
// and key terms. Set by the researcher, never guessed. The Documents list shows the small Theory tag and offers the
// mark in each row's menu; the document's page says what the mark means, offers to change it, and lists what was made
// with the document in (marking changes no result by itself). Routes: gui/api_corpus.py; rules: docrole.py.
import { api, h, P, toast, showError, tag, button, link, notice, plural, confirmDialog } from "../lib.js";

const ROLES_API = (p) => `/api/projects/${P(p)}/document-roles`;
const ROLE_API = (p, d) => `/api/projects/${P(p)}/documents/${P(d)}/role`;

export const LEFT_OUT = "themes, codebook labels, the excerpts a check reads and key terms";

// {doc id: "theory"} for the Documents list ({} when it cannot be read: the list still draws)
export async function documentRoles(project) {
  try { return (await api("GET", ROLES_API(project))).roles || {}; } catch (_) { return {}; }
}

// the small grey Theory tag beside a document's title (DESIGN 4.10: a fact about the item, never pressed)
export function roleTag(role) {
  if (role !== "theory") return null;
  return tag({ icon: "book-marked", class: "doc-role-tag", title: `Theory: the lens the research is read through. Left out of ${LEFT_OUT}.` }, "Theory");
}

// ask, then mark (role "theory") or unmark (null); `done(answer)` after a change
export async function setRole(project, docId, title, role, done) {
  const marking = role === "theory";
  const ok = await confirmDialog({ title: marking ? "Mark as theory?" : "Mark as evidence again?", danger: false,
    confirmText: marking ? "Mark as theory" : "Mark as evidence",
    message: h("div", {},
      h("p", {}, marking
        ? `“${title}” is then the lens the research is read through, not evidence about your field. It is still read, searched, opened and noted, but left out of ${LEFT_OUT}.`
        : `“${title}” then counts as evidence again: in ${LEFT_OUT}.`),
      h("p", {}, "Results made before stay as they are: its page lists them, so you can make them again."),
      h("p", { class: "muted small" }, "A study that uses a theory is still evidence. In a project you share, the owner decides: your mark is a proposal until it is accepted.")) });
  if (!ok) return null;
  try {
    const r = await api("PUT", ROLE_API(project, docId), { role });
    toast(marking ? "Marked as theory." : "Marked as evidence.", "ok", { small: true });
    if (done) done(r);
    return r;
  } catch (e) { showError(e); return null; }
}

// the row menu's item in the Documents list
export function roleMenuItem(project, d, role, done) {
  const title = d.title || d.file || "this document";
  return role === "theory"
    ? { text: "Mark as evidence…", icon: "book-open", onClick: () => setRole(project, d.doc_id, title, null, done) }
    : { text: "Mark as theory…", icon: "book-marked", onClick: () => setRole(project, d.doc_id, title, "theory", done) };
}

// what was made with the document in: theme runs, codebook labels, checks (each a link)
function impactList(imp) {
  const items = [];
  if ((imp.themes || []).length) items.push(h("li", {}, `${plural(imp.themes.length, "set")} of themes (${plural(imp.themes.reduce((a, t) => a + (t.passages || 0), 0), "passage")} of it in them). `, link({ href: "#/themes" }, "Make the themes again")));
  for (const l of imp.labels || []) items.push(h("li", {}, `Labels of the codebook ${l.name} on ${plural(l.passages, "passage")}. `, link({ href: `#/profile?framework=${encodeURIComponent(l.framework)}` }, "Label again")));
  for (const c of (imp.checks || []).slice(0, 8)) items.push(h("li", {}, link({ kind: "title", serif: true, href: `#/h/${encodeURIComponent(c.hyp_id)}` }, c.text), ` · ${plural(c.excerpts, "excerpt")} from it. Re-run it from its page.`));
  if ((imp.checks || []).length > 8) items.push(h("li", { class: "muted" }, `and ${plural(imp.checks.length - 8, "more check")}`));
  return items;
}

// the document page's box: what its role is, the button to change it, and what was made with it in
export async function roleBox(project, docId, title) {
  const box = h("div", { class: "doc-role-box" });
  async function draw() {
    let r;
    try { r = await api("GET", ROLE_API(project, docId)); } catch (_) { box.replaceChildren(); return; }
    const theory = r.role === "theory";
    const imp = impactList(r.impact || {});
    const change = button({ kind: "quiet", sm: true, icon: theory ? "book-open" : "book-marked", onClick: () => setRole(project, docId, title, theory ? null : "theory", draw) },
      theory ? "Mark as evidence" : "Mark as theory");
    if (!theory) { box.replaceChildren(h("div", { class: "row doc-role-row" }, change)); return; }
    box.replaceChildren(notice({ kind: "info", class: "doc-role-note" },
      h("p", {}, roleTag("theory"), ` The lens the research is read through, not evidence. It is still read, searched and noted; it is left out of ${LEFT_OUT}.`),
      imp.length ? [h("p", {}, "Made with it in, before it was marked (they stay as they are until you make them again):"), h("ul", { class: "doc-role-impact" }, imp)] : null,
      h("div", { class: "btn-row" }, change)));
  }
  await draw();
  return box;
}
