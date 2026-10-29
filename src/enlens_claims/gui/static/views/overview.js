// 0.9: the Overview: the start page of a project. Exploring the documents comes first (Search, Profile, Concepts,
// Themes, one document), checking hypotheses second. Each feature says in one line what it does, whether it uses the
// AI, and what is already made in this project.
import { App, api, h, icon, P, pageHead } from "../lib.js";
import { FEATURES, aiTag } from "../features.js";
import { quickLookButton } from "./quicklook.js";

const plural = (n, one, many) => `${Number(n).toLocaleString()} ${n === 1 ? one : many}`;

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

  // Explore: the main part
  const pf = o.profile || {}, cs = o.concepts || {}, th = o.themes || {};
  const state = {
    search: [false, "Ready: type a word"],
    profile: pf.labels ? [true, `${plural(pf.documents || 0, "document", "documents")} profiled`] : [false, "Not made yet · takes seconds"],
    concepts: cs.terms ? [true, `${plural(cs.terms, "term", "terms")}${cs.concepts ? `, ${plural(cs.concepts, "concept", "concepts")}` : ""}`] : [false, "Not made yet · takes seconds"],
    themes: th.themes ? [true, `${plural(th.themes, "theme", "themes")} found`] : [false, "Not made yet · takes seconds"],
  };
  view.appendChild(h("div", { class: "ov-section-head" }, h("h2", {}, "Explore the documents"), h("p", {}, "Start here: no hypothesis needed.")));
  const grid = h("div", { class: "ov-grid" });
  for (const key of ["search", "profile", "concepts", "themes"]) {
    const href = key === "themes" && th.latest ? `#/themes/${encodeURIComponent(th.latest)}` : FEATURES[key].href;
    grid.appendChild(card(key, state[key], href));
  }
  grid.appendChild(card("sources", [!!o.references, o.references ? `References followed in ${plural(o.references, "document", "documents")}` : `${plural(nDocs, "document", "documents")}`], "#/sources",
    { title: "Read one document", what: "Open a document from the list to see its codes, key terms, what “it” and “they” refer to, and a highlighted copy." }));
  view.appendChild(grid);

  // Check: second
  view.appendChild(h("div", { class: "ov-section-head" }, h("h2", {}, "Check hypotheses"), h("p", {}, "When you have a statement to test against the documents.")));
  const small = h("div", { class: "ov-grid ov-grid-small" });
  small.appendChild(card("check", [false, ""], FEATURES.check.href, { compact: true }));
  small.appendChild(card("batch", [false, ""], FEATURES.batch.href, { compact: true }));
  small.appendChild(card("history", o.hypotheses ? [true, `${plural(o.hypotheses, "result", "results")}`] : [false, "None yet"], FEATURES.history.href, { compact: true }));
  view.appendChild(small);
}

function card(key, [made, text], href, opts = {}) {
  const f = FEATURES[key];
  return h("a", { class: "ov-card", href },
    h("div", { class: "ov-card-head" }, h("span", { class: "ov-card-icon" }, icon(f.icon, { size: opts.compact ? 15 : 18 })), h("h3", {}, opts.title || f.title)),
    h("p", {}, opts.what || f.what),
    !opts.compact && f.use ? h("p", { class: "ov-use" }, f.use) : null,
    h("div", { class: "ov-card-foot" }, aiTag(f.ai), text ? h("span", { class: `ov-state ${made ? "ov-made" : ""}` }, made ? icon("circle-check", { size: 13 }) : null, text) : null));
}

// Which AI answers, in one line, with what to do when it is not ready.
function aiLine(o) {
  const s = App.settings();
  const p = App.privacy();
  const box = h("div", { class: "ov-ai" }, icon(p.icon, { size: 18 }),
    h("div", { class: "grow" }, h("strong", {}, s.backend === "claude_code" ? "AI: Claude Code, on your Claude plan" : `AI: ${p.label}`),
      h("div", { class: "muted small" }, s.backend === "claude_code" ? "The AI buttons prepare the work here; Claude Code answers it. Only the passages inside the tasks are sent to Anthropic." : p.plain)),
    h("a", { class: "btn btn-sm btn-ghost", href: "#/settings/model" }, "Change"));
  if (s.backend === "claude_code") {
    api("GET", "/api/claude-setup").then((r) => {
      const st = r.status || {};
      if (st.ready) {
        box.querySelector(".grow .muted").append(o.waiting ? ` ${plural(o.waiting, "task waits", "tasks wait")} for it now.` : " Ready.");
        return;
      }
      box.insertBefore(h("a", { class: "btn btn-sm btn-primary", href: "#/settings/model" }, icon("zap", { size: 13 }), st.found ? "Finish the set-up" : "Set up Claude Code"), box.lastChild);
    }).catch(() => {});
  }
  return box;
}
