// 0.9: the Overview: the start page of a project. Exploring the documents comes first (Search, Profile, Concepts,
// Themes, one document), checking hypotheses second. Each feature says in one line what it does, whether it uses the
// AI, and what is already made in this project.
import { App, api, h, icon, P, pageHead, plural, link, notice } from "../lib.js";
import { FEATURES, SECTIONS, aiTag, viewTabs } from "../features.js";
import { finderBox } from "../finder.js";
import { overviewSections } from "../registry.js";
import { quickLookButton } from "./quicklook.js";

export async function renderOverview(view) {
  const project = App.project;
  // 0.14.3: a failed request is an error on the page (the router draws it), never "this project has no documents"
  const o = await api("GET", `/api/projects/${P(project)}/overview`);
  const nDocs = o.documents || 0;

  view.appendChild(pageHead(project, {
    eyebrow: "Project overview",
    // 0.17.0 (design guide): the page head holds one action (Quick look); the way to add documents is a link in the
    // line under the title, where a place belongs
    sub: nDocs ? [`${plural(nDocs, "document", "documents")} · ${plural(o.passages || 0, "passage", "passages")}. Explore what the documents say, then check your hypotheses against them. `,
      link({ href: "#/sources" }, "Add more on the Documents page"), "."]
      : "Add documents first: everything below works on them.",
    actions: quickLookButton({ sm: true }),
  }));
  view.appendChild(viewTabs("overview", "overview"));   // 0.17.0: Overview | Research log
  // 0.17.0: "What do you want to do?": the feature finder (finder.js, no AI), so a newcomer finds a feature by its words
  view.appendChild(h("div", { class: "ov-finder" }, finderBox()));

  if (!nDocs) {
    view.appendChild(notice({ kind: "info", class: "ov-empty-docs" },
      h("p", {}, h("strong", {}, "This project has no documents yet. "), "Add PDFs, Word files, text or saved web pages; they stay on this computer."),
      h("p", {}, link({ kind: "next", href: "#/sources" }, "Add documents on the Documents page"))));
  }

  // 0.13.6: the sections and their cards come from FEATURES and SECTIONS (registry.js), so an add-on's section or
  // feature shows here without an edit. Explore comes first (the main part), checking hypotheses second.
  const pf = o.profile || {}, cs = o.concepts || {}, th = o.themes || {};
  const STATE = {
    search: [false, "Ready: type a word"],
    profile: pf.labels ? [true, `${plural(pf.documents || 0, "document", "documents")} profiled`] : [false, "Not made yet · takes seconds"],
    concepts: cs.terms ? [true, `${plural(cs.terms, "term", "terms")}${cs.concepts ? `, ${plural(cs.concepts, "concept", "concepts")}` : ""}`] : [false, "Not made yet · takes seconds"],
    themes: th.themes ? [true, `${plural(th.themes, "theme", "themes")} found`] : [false, "Not made yet · takes seconds"],
    sources: [!!o.references, o.references ? `References followed in ${plural(o.references, "document", "documents")}` : `${plural(nDocs, "document", "documents")}`],
    check: o.hypotheses ? [true, `${plural(o.hypotheses, "answer", "answers")} so far`] : [false, "None yet · one hypothesis or a list"],
    // 0.16
    codebooks: o.codebooks ? [true, `${plural(o.codebooks, "codebook", "codebooks")} of your own`] : [false, "None yet · start from the themes"],
    annotations: o.notes ? [true, plural(o.notes, "note", "notes")] : [false, "None yet · select words in a document"],
    researchlog: o.log ? [true, plural(o.log, "entry", "entries")] : [false, "Kept by itself as you work"],
  };
  const HREF = { themes: th.latest ? `#/themes/${encodeURIComponent(th.latest)}` : null };
  for (const sec of overviewSections(FEATURES, SECTIONS)) {
    view.appendChild(h("div", { class: "ov-section-head" }, h("h2", {}, sec.title), sec.sub ? h("p", {}, sec.sub) : null));
    const grid = h("div", { class: sec.compact ? "ov-grid ov-grid-small" : "ov-grid" });
    for (const key of sec.features) {
      const f = FEATURES[key];
      let st = STATE[key] || [false, ""];
      if (typeof f.state === "function") { try { st = f.state(o) || st; } catch (e) { console.error(e); } }
      grid.appendChild(card(key, st, HREF[key] || f.href, { compact: sec.compact, ...(f.overview || {}) }));
    }
    view.appendChild(grid);
  }
  // 0.15 (J4.2): a project opened in a newer version says which results came from an older one
  const older = madeWith(o.made_with);
  if (older) view.appendChild(older);
}

const MADE = { checks: ["check", "checks"], theme_runs: ["theme run", "theme runs"], labels: ["codebook label", "codebook labels"],
  answers: ["AI answer", "AI answers"] };

// Results an earlier ENLENS made, in one quiet line under the cards; nothing when every result is from this version
function madeWith(m) {
  if (!m || !m.older) return null;
  // a check records the version that started it; answers, labels and theme runs the one that made them
  const parts = (m.results || []).filter((r) => r.older && MADE[r.what])
    .map((r) => `${plural(r.n, ...MADE[r.what])} ${r.what === "checks" ? "started" : "made"} ${r.app_version ? `with ENLENS ${r.label}` : r.label}`);
  const docs = (m.documents || []).filter((d) => d.older).reduce((a, d) => a + d.n, 0);
  if (docs) parts.push(`${plural(docs, "document", "documents")} ${docs === 1 ? "was" : "were"} read by an earlier reader`);
  if (!parts.length) return null;
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0];
  const results = parts.length > (docs ? 1 : 0);
  return h("p", { class: "ov-made-with" }, icon("info", { size: 14 }),
    h("span", {}, `Made with an earlier version of ENLENS (you have ${m.version}): ${list}. `,
      results ? "Results stay as they were made; each Excel download names the version behind every answer." : null,
      // 0.15 (A0): how to move a document to the new reader, with its results
      docs ? [results ? " " : "", `To read ${docs === 1 ? "it" : "one"} with the new reader, open it in `, h("a", { href: "#/sources" }, "Documents"), " and choose ", h("em", {}, "Reading"), "."] : null));
}

// the card shows the short state ("Not made yet"); what follows " · " ("takes seconds") is in the tooltip and aria-label
function card(key, [made, text], href, opts = {}) {
  const f = FEATURES[key];
  return h("a", { class: "ov-card", href, title: !opts.compact && f.use ? f.use : null },
    h("div", { class: "ov-card-head" }, h("span", { class: "ov-card-icon" }, icon(f.icon, { size: 18 })), h("h3", {}, opts.title || f.title)),
    h("p", {}, opts.what || f.what),
    // 0.13.3: what it is for is the card's tooltip, so a card says one thing (it was a second, grey paragraph)
    h("div", { class: "ov-card-foot" }, aiTag(f.ai), text ? h("span", { class: `ov-state ${made ? "ov-made" : ""}`, title: text, "aria-label": text }, made ? icon("check", { size: 13 }) : null, h("span", { class: "ov-state-text" }, text.split(" · ")[0])) : null));
}
