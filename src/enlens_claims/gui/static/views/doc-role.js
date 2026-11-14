// 0.18.1 (roadmap K2 part 1): a document's role. A theory document is the lens the research is read through, not
// evidence: still read, searched, opened and noted, but left out of themes, codebook labels, the excerpts a check reads
// and key terms. Set by the researcher, never guessed. The Documents list shows the small Theory tag and offers the
// mark in each row's menu; the document's page says what the mark means, offers to change it, and lists what was made
// with the document in (marking changes no result by itself). Routes: gui/api_corpus.py; rules: docrole.py.
// 0.18.6: the Non-scientific mark, beside the role (a document of either role can carry it): read and judged as any
// other, but no judgement of its excerpts counts in an answer. Unlike the role it changes answers at once, so the
// dialog says how many checks read it, and the reply lists the answers it changed.
// 0.18.8 (roadmap N3): a third role, the working document: the researcher's own draft or notes, kept in the project,
// read, searched, noted and labelled with codebooks, and checked against the corpus a sentence at a time (select it in
// the text, then Check against the corpus), but never a source. Its codes are its own: never in the corpus's counts.
// 0.18.8 (roadmap K3): a quiet suggestion from the bibliography's item type (a newspaper article, a blog post, a web
// page): one line with Mark and No, never a mark by itself and never a pop-up. No is kept as a decision (the research
// log), so it does not come back here or in a colleague's copy.
import { api, h, P, toast, showError, tag, button, link, notice, plural, confirmDialog, icon } from "../lib.js";

const ROLES_API = (p) => `/api/projects/${P(p)}/document-roles`;
const ROLE_API = (p, d) => `/api/projects/${P(p)}/documents/${P(d)}/role`;
const NONSCI_API = (p, d) => `/api/projects/${P(p)}/documents/${P(d)}/nonscientific`;
const SUGGEST_API = (p, d) => `/api/projects/${P(p)}/documents/${P(d)}/nonscientific-suggestion`;
export const NONSCI_MEANS = "It reports no method or data of its own (a news article, a press release, a company brochure, a blog)";

export const LEFT_OUT = "themes, codebook labels, the excerpts a check reads and key terms";
// N3: what a working document is left out of (it is labelled with codebooks, but its codes are counted apart)
export const WORKING_LEFT_OUT = "themes, the excerpts a check reads, key terms and the corpus’s code counts";
export const WORKING_MEANS = "Your own draft or notes: kept here, read, labelled with codes and checked against the corpus, but never a source";

// each role's words: its tag, its menu item, its dialog and its line in the Documents list's panel
const ROLE = {
  theory: { tag: "Theory", icon: "book-marked", title: `Theory: the lens the research is read through. Left out of ${LEFT_OUT}.`,
    menu: "Mark as theory…", button: "Mark as theory", ask: "Mark as theory?", toast: "Marked as theory.",
    line: "Theory: the lens the research is read through, not evidence",
    means: (t) => `“${t}” is then the lens the research is read through, not evidence about your field. It is still read, searched, opened and noted, but left out of ${LEFT_OUT}.`,
    small: "A study that uses a theory is still evidence." },
  working: { tag: "Working document", icon: "notebook", title: `Working document: ${WORKING_MEANS.charAt(0).toLowerCase()}${WORKING_MEANS.slice(1)}. Left out of ${WORKING_LEFT_OUT}.`,
    menu: "Mark as my working document…", button: "Mark as my working document", ask: "Mark as your working document?", toast: "Marked as your working document.",
    line: "Working document: your own draft or notes, never a source",
    means: (t) => `“${t}” is then your own draft or notes, never a source. It is still read, searched, opened, noted and labelled with codebooks, and you can check any of its sentences against the corpus (select it in the text), but it is left out of ${WORKING_LEFT_OUT}.`,
    small: "A colleague’s or another author’s draft you study is evidence, not your working document." },
  evidence: { menu: "Mark as evidence…", button: "Mark as evidence", ask: "Mark as evidence again?", toast: "Marked as evidence.", line: "Evidence",
    means: (t) => `“${t}” then counts as evidence again: in themes, codebook labels, the excerpts a check reads and key terms.` },
};

// {doc id: "theory" | "working"} for the Documents list ({} when it cannot be read: the list still draws)
export async function documentRoles(project) {
  return (await documentMarks(project)).roles;
}

// 0.18.6: {roles: {doc id: "theory" | "working"}, nonscientific: Set of doc ids}, for the Documents list; 0.18.8 (K3):
// suggested: {doc id: "a newspaper article"}, the documents the bibliography suggests marking ({} when it cannot be
// read: the list still draws)
export async function documentMarks(project) {
  const sug = api("GET", `/api/projects/${P(project)}/nonscientific-suggestions`).then((r) => r.suggested || {}, () => ({}));
  try {
    const r = await api("GET", ROLES_API(project));
    return { roles: r.roles || {}, nonscientific: new Set(r.nonscientific || []), suggested: await sug };
  } catch (_) { return { roles: {}, nonscientific: new Set(), suggested: await sug }; }
}

// 0.18.8 (K3): the suggestion's line: "Your bibliography lists this as a newspaper article. Mark it as
// non-scientific?" with Mark (the usual dialog) and No (remembered); `done()` after either
export function suggestLine(project, docId, title, words, done) {
  const no = async () => {
    try { await api("POST", SUGGEST_API(project, docId), { answer: "no" }); toast("Kept as scientific. It will not be suggested again.", "ok", { small: true }); if (done) done(); }
    catch (e) { showError(e); }
  };
  return h("p", { class: "doc-nonsci-suggest small" }, icon("library", { size: 13 }), ` Your bibliography lists this as ${words}. Mark it as non-scientific? `,
    button({ kind: "quiet", sm: true, onClick: () => setNonscientific(project, docId, title, true, () => done && done()) }, "Mark"),
    button({ kind: "quiet", sm: true, title: "Keep counting it as scientific; the research log keeps your answer", onClick: no }, "No"));
}

// 0.18.8 (K3): after a No, for whoever said it (the Owner and Co-owners for anyone's): one quiet line to take it
// back, kept in the research log as a decision that replaces the No
export function suggestAgainLine(project, docId, by, done) {
  const who = by.length ? by.join(" and ") : "Someone";
  const again = async () => {
    try { await api("POST", SUGGEST_API(project, docId), { answer: "again" }); toast("Suggested as non-scientific again.", "ok", { small: true }); if (done) done(); }
    catch (e) { showError(e); }
  };
  return h("p", { class: "doc-nonsci-suggest small muted" }, icon("library", { size: 13 }),
    ` ${who.charAt(0).toUpperCase()}${who.slice(1)} said No to the bibliography's suggestion to mark it as non-scientific. `,
    button({ kind: "quiet", sm: true, title: "Take the No back: the suggestion shows again; the research log keeps it", onClick: again }, "Suggest again"));
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

// the small grey Theory or Working document tag beside a document's title (DESIGN 4.10: a fact about the item, never
// pressed)
export function roleTag(role) {
  const r = ROLE[role];
  if (!r || !r.tag) return null;
  return tag({ icon: r.icon, class: `doc-role-tag doc-role-${role}`, title: r.title }, r.tag);
}

// the words of a document's role in the Documents list's panel
export const roleLine = (role) => (ROLE[role] || ROLE.evidence).line;

// ask, then mark (role "theory" or, N3, "working") or unmark (null); `done(answer)` after a change
export async function setRole(project, docId, title, role, done) {
  const w = ROLE[role || "evidence"];
  const ok = await confirmDialog({ title: w.ask, danger: false, confirmText: w.button,
    message: h("div", {},
      h("p", {}, w.means(title)),
      h("p", {}, "Results made before stay as they are: its page lists them, so you can make them again."),
      h("p", { class: "muted small" }, `${w.small ? `${w.small} ` : ""}In a project you share, the owner decides: your mark is a proposal until it is accepted.`)) });
  if (!ok) return null;
  try {
    const r = await api("PUT", ROLE_API(project, docId), { role });
    toast(w.toast, "ok", { small: true });
    if (done) done(r);
    return r;
  } catch (e) { showError(e); return null; }
}

// the row menu's items in the Documents list: every role the document does not have (N3: three roles)
export function roleMenuItems(project, d, role, done) {
  const title = d.title || d.file || "this document";
  return [["evidence", null, "book-open"], ["theory", "theory", "book-marked"], ["working", "working", "notebook"]]
    .filter(([, r]) => r !== (role || null))
    .map(([k, r, ic]) => ({ text: ROLE[k].menu, button: ROLE[k].button, icon: ic, onClick: () => setRole(project, d.doc_id, title, r, done) }));
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
// the non-scientific documents; 0.18.8 (K3): a check set to count them says so
function answersList(answers) {
  return answers.map((a) => h("li", {}, link({ kind: "title", serif: true, href: `#/h/${encodeURIComponent(a.hyp_id)}` }, a.text),
    ` · ${a.status_text || a.status}`,
    a.count_nonscientific ? h("span", { class: "muted" }, " · counted in this check (set on the hypothesis)")
      : a.all !== a.status ? h("span", { class: "muted" }, ` (counting the non-scientific documents: ${a.all_text})`) : null));
}

// the document page's box: what its role is, the button to change it, and what was made with it in; 0.18.6: whether
// it is marked Non-scientific, the button to change that, and the answers of the checks that read it. 0.18.8 (N3):
// `onRole(role)` after each drawing, so the page knows a working document (its selection offers a check).
export async function roleBox(project, docId, title, onRole) {
  const box = h("div", { class: "doc-role-box" });
  async function draw() {
    let r;
    try { r = await api("GET", ROLE_API(project, docId)); } catch (_) { box.replaceChildren(); return; }
    if (onRole) onRole(r.role || null);
    const theory = r.role === "theory";
    const working = r.role === "working";
    const ns = !!r.nonscientific;
    let sug = null, saidNo = null;   // 0.18.8 (K3)
    if (!ns) { try { const g = await api("GET", SUGGEST_API(project, docId)); sug = g.suggestion; saidNo = g.answered_no; } catch (_) { sug = null; } }
    const imp = impactList(r.impact || {});
    const items = roleMenuItems(project, { doc_id: docId, title }, r.role, draw);
    const changes = items.map((it) => button({ kind: "quiet", sm: true, icon: it.icon, onClick: it.onClick }, it.button));
    const change = changes;
    const changeNs = button({ kind: "quiet", sm: true, icon: ns ? "flask" : "newspaper", onClick: () => setNonscientific(project, docId, title, !ns, draw) },
      ns ? "Count as scientific" : "Mark as non-scientific");
    const parts = [];
    if (theory) parts.push(notice({ kind: "info", class: "doc-role-note" },
      h("p", {}, roleTag("theory"), ` The lens the research is read through, not evidence. It is still read, searched and noted; it is left out of ${LEFT_OUT}.`),
      imp.length ? [h("p", {}, "Made with it in, before it was marked (they stay as they are until you make them again):"), h("ul", { class: "doc-role-impact" }, imp)] : null,
      h("div", { class: "btn-row" }, change)));
    if (working) parts.push(notice({ kind: "info", class: "doc-role-note doc-working-note" },
      h("p", {}, roleTag("working"), ` ${WORKING_MEANS}. It is left out of ${WORKING_LEFT_OUT}.`),
      h("p", {}, icon("list-checks", { size: 13 }), " To check one of its claims, select the sentence in the text and choose ", h("strong", {}, "Check against the corpus"), "."),
      imp.length ? [h("p", {}, "Made with it in, before it was marked (they stay as they are until you make them again):"), h("ul", { class: "doc-role-impact" }, imp)] : null,
      h("div", { class: "btn-row" }, change)));
    if (ns) {
      const ans = answersList(r.answers || []);
      parts.push(notice({ kind: "info", class: "doc-nonsci-note" },
        h("p", {}, nonsciTag(), ` ${NONSCI_MEANS}. Its excerpts are read and judged, but their judgements count in no answer, except in checks set to count non-scientific documents.`),
        ans.length ? [h("p", {}, "Checks that read it:"), h("ul", { class: "doc-role-impact" }, ans)] : null,
        h("div", { class: "btn-row" }, changeNs)));
    }
    const quiet = [...(theory || working ? [] : change), ns ? null : changeNs].filter(Boolean);
    if (quiet.length) parts.push(h("div", { class: "row doc-role-row" }, quiet));
    if (sug) parts.push(suggestLine(project, docId, title, sug.words, draw));
    else if (saidNo && saidNo.may_suggest_again) parts.push(suggestAgainLine(project, docId, saidNo.by || [], draw));
    box.replaceChildren(...parts);
  }
  await draw();
  return box;
}
