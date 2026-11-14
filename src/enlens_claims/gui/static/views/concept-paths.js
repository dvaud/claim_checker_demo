// 0.18.1 (roadmap D3 and D4): two cards on a concept's page. *Paths to another concept*: the shortest chains from this
// concept to another, through links you accepted and concepts mentioned together more often than by chance, each step
// with the passages that join its two concepts (a list, not a drawn map). *Over time and across groups*: the concept's
// wordings and neighbours by publication year (from the bibliography) or in two sets of documents you pick (not
// stored). Theory documents are left out of both. Routes: gui/api_corpus.py; rules: conceptpaths.py.
import { api, h, P, replace, showError, button, link, card, input, fold, plural, shortTitle, tag, debounce } from "../lib.js";

const REL_WORDS = { same: "the same as", broader: "broader than", narrower: "part of", related: "related to",
  effect: "leads to", effect_of: "an effect of", replaces: "used instead of", replaced_by: "replaced by" };
const docHref = (b) => `#/doc/${encodeURIComponent(b.doc_id)}?q=${b.start}-${b.start + 1}`;

function passageItem(b) {
  return h("li", {}, h("span", { class: "serif" }, "“", shortTitle(b.text || b.quote || "", 260), "” "),
    b.doc_id ? link({ href: docHref(b), class: "small" }, `${b.title || "a document"}${b.location ? `, ${b.location}` : b.page ? `, p. ${b.page}` : ""}`) : null);
}

function stepItem(st) {
  const how = st.kind === "link"
    ? tag({ icon: "link" }, `a link: ${REL_WORDS[st.relation] || st.relation}`)
    : tag({}, st.pmi !== null && st.pmi !== undefined ? `mentioned together, ${st.pmi} PMI` : "mentioned together");
  const ev = (st.bridges || []).length ? st.bridges : (st.sentences || []);
  return h("li", { class: "cp-step" },
    h("div", {}, h("span", { class: "serif" }, st.from.label), " → ", h("span", { class: "serif" }, st.to.label), " ", how),
    ev.length ? fold({ sm: true, class: "cp-bridges" }, (st.bridges || []).length ? `${plural(st.bridges.length, "passage")} that join them` : "Why the link",
      h("ul", { class: "ct-quotes" }, ev.map(passageItem))) : null);
}

// a term the person types, as a term id of the glossary (null when none matches)
async function termOf(base, text) {
  try { return (await api("GET", `${base}/concepts?name=${encodeURIComponent(text)}`)).term_id; }
  catch (e) { if (e.status === 404) return null; throw e; }
}

export function pathsCard(project, termId, label) {
  const base = `/api/projects/${P(project)}`;
  const out = h("div", { class: "cp-paths" });
  const other = input({ sm: true, list: "cp-term-list", autocomplete: "off", placeholder: "another concept…", "aria-label": "The other concept" });
  const dl = h("datalist", { id: "cp-term-list" });
  other.addEventListener("input", debounce(async () => {
    const t = other.value.trim();
    if (t.length < 2) return;
    try { replace(dl, ((await api("GET", `${base}/terms?q=${encodeURIComponent(t)}&limit=10`)).items || []).map((e) => h("option", { value: e.label }))); } catch (_) { /* suggestions only */ }
  }, 250));
  const go = button({ sm: true, icon: "network" }, "Find the paths");
  go.addEventListener("click", async () => {
    const t = other.value.trim();
    if (!t) { other.focus(); return; }
    go.disabled = true;
    try {
      const to = await termOf(base, t);
      if (!to) { replace(out, h("p", { class: "field-error", role: "alert" }, `No concept of the glossary matches “${t}”.`)); return; }
      const r = await api("GET", `${base}/concept-paths?from=${encodeURIComponent(termId)}&to=${encodeURIComponent(to)}`);
      if (!r.paths.length) { replace(out, h("p", { class: "muted" }, `The documents give no path from “${r.from.label}” to “${r.to.label}”: no chain of links or concepts mentioned together joins them.`)); return; }
      replace(out, r.paths.map((p, i) => h("div", { class: "cp-path" },
        h("h3", {}, i === 0 ? "The shortest path" : `Another path`, h("span", { class: "muted small" }, ` · ${plural(p.steps.length, "step")}`)),
        h("ol", { class: "cp-steps" }, p.steps.map(stepItem)))));
    } catch (e) { showError(e); } finally { go.disabled = false; }
  });
  other.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go.click(); } });
  return card({ class: "section", title: "Paths to another concept", titleId: "cp-h" },
    h("p", { class: "muted small" }, "How the documents get from this concept to another: through links you accepted, and concepts mentioned together more often than by chance. Each step shows the passages that join its two concepts. Theory documents are left out."),
    h("div", { class: "row ct-add-form" }, h("span", { class: "serif" }, shortTitle(label, 40)), other, dl, go), out);
}

function profileRows(groups, nameOf) {
  return h("div", { class: "table-wrap" }, h("table", { class: "table table-responsive cp-time" },
    h("thead", {}, h("tr", {}, h("th", {}, "Group"), h("th", { class: "num" }, "Documents"), h("th", { class: "num" }, "Mentions"), h("th", {}, "Wordings"), h("th", {}, "Mentioned with it"))),
    h("tbody", {}, groups.map((g) => h("tr", {},
      h("td", { "data-label": "Group" }, nameOf(g)),
      h("td", { "data-label": "Documents", class: "num" }, `${g.documents} of ${g.documents_in_group}`),
      h("td", { "data-label": "Mentions", class: "num" }, String(g.mentions)),
      h("td", { "data-label": "Wordings", class: "small" }, g.wordings.slice(0, 4).map((w) => `${w.label} (${w.mentions})`).join(", ") || "—"),
      h("td", { "data-label": "Mentioned with it", class: "small" }, g.neighbours.slice(0, 5).map((n) => n.label).join(", ") || "—"))))));
}

export function timeCard(project, termId) {
  const base = `/api/projects/${P(project)}`;
  const out = h("div", { class: "cp-time-out" });
  const byYear = button({ sm: true, icon: "clock" }, "By year");
  byYear.addEventListener("click", async () => {
    byYear.disabled = true;
    try {
      const r = await api("GET", `${base}/concept-time/${P(termId)}`);
      const groups = [...r.years.map((y) => ({ ...y, name: y.year })), ...(r.no_year ? [{ ...r.no_year, name: "No year" }] : [])];
      replace(out, r.with_year ? null : h("p", { class: "muted small" }, "No document has a year yet: link them to works in the bibliography first (Bibliography, in the sidebar)."),
        profileRows(groups, (g) => g.name));
    } catch (e) { showError(e); } finally { byYear.disabled = false; }
  });
  const pickBox = h("div", { class: "cp-groups" });
  const groupsFold = fold({ class: "cp-groups-fold" }, "Compare two sets of documents", pickBox);
  groupsFold.addEventListener("toggle", async () => {
    if (!groupsFold.open || pickBox.childElementCount) return;
    let docs;
    try { docs = (await api("GET", `${base}/documents`)).documents || []; } catch (e) { showError(e); return; }
    const names = [input({ sm: true, value: "Set A", "aria-label": "Name of the first set" }), input({ sm: true, value: "Set B", "aria-label": "Name of the second set" })];
    const ticks = docs.map((d) => [d, h("input", { type: "checkbox", "aria-label": `${d.title || d.file} in the first set` }), h("input", { type: "checkbox", "aria-label": `${d.title || d.file} in the second set` })]);
    const run = button({ sm: true }, "Compare");
    run.addEventListener("click", async () => {
      // two sets of the same name stay two sets (review 17): the second gets a number
      const a = names[0].value.trim() || "Set A";
      let b = names[1].value.trim() || "Set B";
      if (b === a) b = `${b} (2)`;
      const groups = { [a]: ticks.filter((x) => x[1].checked).map((x) => x[0].doc_id), [b]: ticks.filter((x) => x[2].checked).map((x) => x[0].doc_id) };
      run.disabled = true;
      try {
        const r = await api("POST", `${base}/concept-groups/${P(termId)}`, { groups });
        replace(out, profileRows(r.groups, (g) => [g.name, g.theory_left_out ? h("span", { class: "muted small" }, ` (${plural(g.theory_left_out, "theory or working document")} left out)`) : null]));
      } catch (e) { showError(e); } finally { run.disabled = false; }
    });
    replace(pickBox, h("div", { class: "table-wrap" }, h("table", { class: "table cp-pick" },
      h("thead", {}, h("tr", {}, h("th", {}, "Document"), h("th", {}, names[0]), h("th", {}, names[1]))),
      h("tbody", {}, ticks.map(([d, a, b]) => h("tr", {}, h("td", { class: "serif" }, d.title || d.file), h("td", {}, a), h("td", {}, b)))))),
    h("div", { class: "btn-row" }, run));
  });
  return card({ class: "section", title: "Over time and across groups", titleId: "cp-t-h" },
    h("p", { class: "muted small" }, "How the concept is worded, and what it is mentioned with, by publication year or in two sets of documents you pick (policy against academic, one country against another). Theory documents are left out."),
    h("div", { class: "btn-row" }, byYear), groupsFold, out);
}
