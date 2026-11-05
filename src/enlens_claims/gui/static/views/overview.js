// 0.9: the Overview: the start page of a project. Exploring the documents comes first (Search, Profile, Concepts,
// Themes, one document), checking hypotheses second. Each feature says in one line what it does, whether it uses the
// AI, and what is already made in this project.
import { App, api, h, icon, P, pageHead, plural, claudeStatus } from "../lib.js";
import { FEATURES, SECTIONS, aiTag } from "../features.js";
import { overviewSections } from "../registry.js";
import { quickLookButton } from "./quicklook.js";

export async function renderOverview(view) {
  const project = App.project;
  let o = {};
  try { o = await api("GET", `/api/projects/${P(project)}/overview`); } catch (_) { o = {}; }
  const nDocs = o.documents || 0;

  view.appendChild(pageHead(project, {
    eyebrow: "Project overview",
    sub: nDocs ? `${plural(nDocs, "document", "documents")} · ${plural(o.passages || 0, "passage", "passages")}. Explore what the documents say, then check your hypotheses against them.`
      : "Add documents first: everything below works on them.",
    actions: [quickLookButton({ class: "btn btn-sm" }), h("a", { class: "btn btn-sm", href: "#/sources" }, icon("upload", { size: 14 }), "Add documents")],
  }));

  view.appendChild(aiLine(o));

  if (!nDocs) {
    view.appendChild(h("div", { class: "notice notice-info ov-empty-docs" }, icon("info"),
      h("div", {}, h("p", {}, h("strong", {}, "This project has no documents yet. "), "Add PDFs, Word files, text or saved web pages; they stay on this computer."),
        h("a", { class: "btn btn-primary btn-sm", href: "#/sources", style: { marginTop: "6px" } }, icon("upload", { size: 14 }), "Add documents"))));
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
    history: o.hypotheses ? [true, `${plural(o.hypotheses, "result", "results")}`] : [false, "None yet"],
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
}

function card(key, [made, text], href, opts = {}) {
  const f = FEATURES[key];
  return h("a", { class: "ov-card", href, title: !opts.compact && f.use ? f.use : null },
    h("div", { class: "ov-card-head" }, h("span", { class: "ov-card-icon" }, icon(f.icon, { size: opts.compact ? 15 : 18 })), h("h3", {}, opts.title || f.title)),
    h("p", {}, opts.what || f.what),
    // 0.13.3: what it is for is the card's tooltip, so a card says one thing (it was a second, grey paragraph)
    h("div", { class: "ov-card-foot" }, aiTag(f.ai), text ? h("span", { class: `ov-state ${made ? "ov-made" : ""}` }, made ? icon("circle-check", { size: 13 }) : null, text) : null));
}

// Which AI answers, in one line, with what to do when it is not ready.
function aiLine(o) {
  const s = App.settings();
  const p = App.privacy();
  const box = h("div", { class: "ov-ai" }, icon(p.icon, { size: 18 }),
    h("div", { class: "grow" }, h("strong", {}, s.backend === "claude_code" ? "AI: Claude Code, on your Claude plan" : `AI: ${p.label}`),
      h("div", { class: "muted small" }, s.backend === "claude_code" ? "Only the passages inside its tasks are sent to Anthropic." : p.plain)),
    h("a", { class: "btn btn-sm btn-ghost", href: "#/settings/model" }, "Change"));
  if (s.backend === "claude_code") {
    claudeStatus().then((st) => {  // 0.13.4: the answer the sidebar asked for too
      if (st.ready) {
        box.querySelector(".grow .muted").append(o.waiting ? ` ${plural(o.waiting, "task waits", "tasks wait")} for it now.` : " Ready.");
        return;
      }
      box.insertBefore(h("a", { class: "btn btn-sm btn-primary", href: "#/settings/model" }, icon("zap", { size: 13 }), st.found ? "Finish the set-up" : "Set up Claude Code"), box.lastChild);
    }).catch(() => {});
  }
  return box;
}
