// 0.18.1 (roadmap K2 part 1): a document's role. A theory document is the lens the research is read through, not
// evidence: still read, searched, opened and noted, but left out of themes, codebook labels, the excerpts a check reads
// and key terms. Set by the researcher, never guessed. The Documents list shows the small Theory tag and offers the
// mark in each row's menu; the document's page says what the mark means, offers to change it, and lists what was made
// with the document in (marking changes no result by itself). Routes: gui/api_corpus.py; rules: docrole.py.
// 0.18.6: the Non-scientific mark, beside the role (a document of either role can carry it): read and judged as any
// other, but no judgement of its excerpts counts in an answer. Unlike the role it changes answers at once, so the
// dialog says how many checks read it, and the reply lists the answers it changed.
import { api, h, P, toast, showError, tag, button, link, notice, plural, confirmDialog } from "../lib.js";

const ROLES_API = (p) => `/api/projects/${P(p)}/document-roles`;
const ROLE_API = (p, d) => `/api/projects/${P(p)}/documents/${P(d)}/role`;
const NONSCI_API = (p, d) => `/api/projects/${P(p)}/documents/${P(d)}/nonscientific`;
export const NONSCI_MEANS = "It reports no method or data of its own (a news article, a press release, a company brochure, a blog)";

export const LEFT_OUT = "themes, codebook labels, the excerpts a check reads and key terms";

// {doc id: "theory"} for the Documents list ({} when it cannot be read: the list still draws)
export async function documentRoles(project) {
  return (await documentMarks(project)).roles;
}

// 0.18.6: {roles: {doc id: "theory"}, nonscientific: Set of doc ids}, for the Documents list
export async function documentMarks(project) {
  try {
    const r = await api("GET", ROLES_API(project));
    return { roles: r.roles || {}, nonscientific: new Set(r.nonscientific || []) };
  } catch (_) { return { roles: {}, nonscientific: new Set() }; }
}

// 0.18.6: the small grey Non-scientific tag (a fact about the document, never pressed)
export function nonsciTag() {
  return tag({ icon: "newspaper", class: "doc-nonsci-tag", title: `Non-scientific: ${NONSCI_MEANS.charAt(0).toLowerCase()}${NONSCI_MEANS.slice(1)}. Its excerpts are read and judged, but never counted in an answer.` }, "Non-scientific");
}

// 0.18.6: ask, then mark (on true) or count again (false); `done(answer)` after a change
export async function setNonscientific(project, docId, title, on, done) {
  let checks = 0;
  try { checks = ((await api("GET", ROLE_API(project, docId))).impact?.checks || []).length; } catch (_) { /* unknown */ }
  const ok = await confirmDialog({ title: on ? "Mark as non-scientific?" : "Count as scientific again?", danger: false,
    confirmText: on ? "Mark as non-scientific" : "Count it again",
    message: h("div", {},
      h("p", {}, on
        ? `${NONSCI_MEANS}. “${title}” stays in themes, codebook labels, the excerpts a check reads and key terms, and its excerpts are still judged, but no judgement of them counts in an answer: on their own they make a hypothesis neither supported, nor mixed, nor contradicted.`
        : `The judgements of “${title}” then count in answers again, as any other document’s.`),
      h("p", {}, checks ? `Answers change at once: ${plural(checks, "check")} read ${checks === 1 ? "an excerpt" : "excerpts"} of it. You will see which answers changed.` : "No check has read it yet, so no answer changes now."),
      on ? h("p", { class: "muted small" }, "Do not mark documents that are your material: when you study what newspapers or companies say, they are your evidence. In a project you share, the owner decides: your mark is a proposal until it is accepted.")
        : h("p", { class: "muted small" }, "In a project you share, the owner decides: your change is a proposal until it is accepted.")) });
  if (!ok) return null;
  try {
    const r = await api("PUT", NONSCI_API(project, docId), { nonscientific: on });
    const n = (r.answers || []).length;
    toast(`${on ? "Marked as non-scientific." : "Counted as scientific again."}${n ? ` ${plural(n, "answer")} changed: the document’s page lists ${n === 1 ? "it" : "them"}.` : ""}`, "ok", { small: !n });
    if (done) done(r);
    return r;
  } catch (e) { showError(e); return null; }
}

// 0.18.6: the row menu's item in the Documents list
export function nonsciMenuItem(project, d, on, done) {
  const title = d.title || d.file || "this document";
  return on
    ? { text: "Count as scientific…", icon: "flask", onClick: () => setNonscientific(project, d.doc_id, title, false, done) }
    : { text: "Mark as non-scientific…", icon: "newspaper", onClick: () => setNonscientific(project, d.doc_id, title, true, done) };
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

// 0.18.6: the checks that read a Non-scientific document, each with its answer now and, where it differs, counting
// the non-scientific documents
function answersList(answers) {
  return answers.map((a) => h("li", {}, link({ kind: "title", serif: true, href: `#/h/${encodeURIComponent(a.hyp_id)}` }, a.text),
    ` · ${a.status_text || a.status}`, a.all !== a.status ? h("span", { class: "muted" }, ` (counting the non-scientific documents: ${a.all_text})`) : null));
}

// the document page's box: what its role is, the button to change it, and what was made with it in; 0.18.6: whether
// it is marked Non-scientific, the button to change that, and the answers of the checks that read it
export async function roleBox(project, docId, title) {
  const box = h("div", { class: "doc-role-box" });
  async function draw() {
    let r;
    try { r = await api("GET", ROLE_API(project, docId)); } catch (_) { box.replaceChildren(); return; }
    const theory = r.role === "theory";
    const ns = !!r.nonscientific;
    const imp = impactList(r.impact || {});
    const change = button({ kind: "quiet", sm: true, icon: theory ? "book-open" : "book-marked", onClick: () => setRole(project, docId, title, theory ? null : "theory", draw) },
      theory ? "Mark as evidence" : "Mark as theory");
    const changeNs = button({ kind: "quiet", sm: true, icon: ns ? "flask" : "newspaper", onClick: () => setNonscientific(project, docId, title, !ns, draw) },
      ns ? "Count as scientific" : "Mark as non-scientific");
    const parts = [];
    if (theory) parts.push(notice({ kind: "info", class: "doc-role-note" },
      h("p", {}, roleTag("theory"), ` The lens the research is read through, not evidence. It is still read, searched and noted; it is left out of ${LEFT_OUT}.`),
      imp.length ? [h("p", {}, "Made with it in, before it was marked (they stay as they are until you make them again):"), h("ul", { class: "doc-role-impact" }, imp)] : null,
      h("div", { class: "btn-row" }, change)));
    if (ns) {
      const ans = answersList(r.answers || []);
      parts.push(notice({ kind: "info", class: "doc-nonsci-note" },
        h("p", {}, nonsciTag(), ` ${NONSCI_MEANS}. Its excerpts are read and judged, but no judgement of them counts in an answer.`),
        ans.length ? [h("p", {}, "Checks that read it:"), h("ul", { class: "doc-role-impact" }, ans)] : null,
        h("div", { class: "btn-row" }, changeNs)));
    }
    const quiet = [theory ? null : change, ns ? null : changeNs].filter(Boolean);
    if (quiet.length) parts.push(h("div", { class: "row doc-role-row" }, quiet));
    box.replaceChildren(...parts);
  }
  await draw();
  return box;
}
