// 0.9: one description of every feature, used by the sidebar, the Overview page and the page heads, so each feature
// says the same thing wherever it is shown: what it does, which part of the app it belongs to, and whether it needs
// the AI.
import { h, icon } from "./lib.js";

// 0.13.6: `sub` and `compact`: the section's line and card size on the Overview (registry.js builds it from these)
export const SECTIONS = {
  explore: { title: "Explore the documents", short: "Explore", sub: "Start here: no hypothesis needed." },
  check: { title: "Check hypotheses", short: "Check", sub: "When you have a statement to test against the documents.", compact: true },
  project: { title: "Your project", short: "Project" },
  // 0.16: what you note and decide, kept as you work (notes and highlights, the research log)
  record: { title: "Your notes and decisions", short: "Notes", sub: "Kept as you work, with the date and who made them.", compact: true },
};

// ai: "none" (never uses the AI), "optional" (works without it; the AI can add to it), "uses" (the AI does the work).
// 0.13.6: `overview` (where its Overview card goes, or false), and an add-on's `state(o)` and `nav` (registry.js).
export const FEATURES = {
  sources: {
    section: "project", title: "Documents", icon: "book-open", href: "#/sources", ai: "optional",
    what: "Add your reports, papers and web pages, say who may read each with AI, and open one to read it with its codes, key terms and references, and see how it was read.",
    overview: { section: "explore", order: 99, title: "Read one document", what: "Open a document from the list to see its codes, key terms, what “it” and “they” refer to, how it was read beside its pages, and a highlighted copy." },
  },
  together: {
    section: "project", title: "Work together", icon: "users", href: "#/projects", ai: "none",
    what: "Each of you keeps a copy of the project on your own computer and Claude plan. Send your work as one file and bring in a colleague’s: what is new comes in, each person’s judgements are kept under their name, and nothing you decided is replaced.",
    overview: false,
  },
  bibliography: {
    section: "project", title: "Bibliography", icon: "library", href: "#/bibliography", ai: "none",
    what: "Your Zotero library or a collection of it, matched with the documents: which works you have, which you still need to find, and which documents Zotero does not have.",
    overview: false,
  },
  codebooks: {
    section: "project", title: "Codebooks", icon: "book-marked", href: "#/codebooks", ai: "none",
    what: "Make and change your own codebooks: codes with a definition, when to use them and when not, the words they are matched by and examples from the documents. Start fresh or from the themes found.",
    use: "To code the documents with your own categories, and see before any AI labels what each code would pick.",
    overview: false,   // 0.17.0: a view of Codes, named on its card
  },
  search: {
    section: "explore", title: "Search", icon: "text-search", href: "#/search", ai: "none",
    what: "Every place a word or phrase occurs in the documents, one line per place, with the words around it.",
    use: "To see how the documents talk about something, or to find a passage you remember.",
  },
  profile: {
    section: "explore", title: "Codes by document", icon: "tag", href: "#/profile", ai: "optional",
    overview: { title: "Codes", what: "Which codes each document addresses (the SDG targets or your own codebook), how much and where. Make your own codebooks beside it." },
    what: "Which codes each document addresses (the SDG targets or your own codebook), how much, and where.",
    use: "To compare documents by topic and find the passages behind each code.",
  },
  concepts: {
    section: "explore", title: "Concepts", icon: "network", href: "#/concepts", ai: "optional",
    what: "A glossary of the terms the documents use, grouped into concepts you can follow from one document to the next.",
    use: "To see which words mean the same thing (abbreviations, other wordings) and where each concept appears.",
  },
  themes: {
    section: "explore", title: "Themes", icon: "shapes", href: "#/themes", ai: "optional",
    what: "What the documents are about, grouped into themes, by document and by code.",
    use: "For an overview of a set of documents before you form hypotheses.",
  },
  check: {
    section: "check", title: "Hypotheses", icon: "flask", href: "#/hypotheses", ai: "uses",
    what: "Check one statement or a list against the documents: whether they support or contradict each, with the exact quotes for you to judge. Every answer stays here, with the evidence map.",
  },
  batch: {
    section: "check", title: "Check several", icon: "list-checks", href: "#/hypotheses", ai: "uses",
    what: "A list of hypotheses (pasted or from a spreadsheet), checked one after the other: write them in the Hypotheses box, one per line.",
    overview: false,   // 0.17.0: a mode of Hypotheses
  },
  history: {
    section: "check", title: "Answers", icon: "history", href: "#/hypotheses", ai: "optional",
    what: "Every hypothesis checked in this project: the answers, your reviews, the evidence map and Excel downloads.",
    overview: false,   // 0.17.0: the answers are on the Hypotheses page
  },
  // 0.16 (F2, F4)
  annotations: {
    section: "project", title: "Notes", icon: "highlighter", href: "#/notes", ai: "none",
    what: "Your highlights and notes on exact words of the documents, in one searchable list. A note can be evidence in a check.",
    overview: false,   // 0.17.0: a view of Documents
  },
  researchlog: {
    section: "project", title: "Research log", icon: "notebook", href: "#/log", ai: "none",
    what: "A dated record of what was decided: documents added, checks made and dropped, themes removed, codebook changes. Add your own entries, say why, and go back to an earlier version.",
    overview: false,   // 0.17.0: a view of the Overview, and the drawer beside every page
  },
};

// The one AI mark (0.17.0): the chip icon says whether something uses the AI, everywhere in the same words (the
// sidebar's groups, a page's top line, beside an action). The cloud icon is kept for where text goes (which AI reads
// it): the AI line at the foot of the sidebar and "Claude, on your plan, reads…" beside a check.
const AI_TEXT = {
  none: ["No AI", "Never uses the AI: it runs on this computer."],
  optional: ["AI on request", "Works without the AI; the AI adds to it only when you ask."],
  uses: ["Uses the AI", "The AI does this work: it reads the passages it needs."],
};

export function aiTag(ai) {
  const [text, plain] = AI_TEXT[ai] || AI_TEXT.none;
  return h("span", { class: `ai-tag ai-${ai}`, title: plain }, icon("cpu", { size: 12 }), text);
}

// 0.17.0: the places of the sidebar, in its order, and the views each place has (tabs on its pages). A view is
// [key, label, href, icon]; its key is the FEATURES key of the page when there is one. `section` is the sidebar group
// (null: the project's own, above the groups). `match` lists the routes (as their FEATURES/nav keys) that light it.
export const PLACES = {
  overview: { title: "Overview", icon: "grid", href: "#/overview", section: null,
    what: "Your project: what is made so far, where to go next, and the research log.",
    views: [["overview", "Overview", "#/overview", "grid"], ["researchlog", "Research log", "#/log", "notebook"]] },
  documents: { title: "Documents", icon: "book-open", href: "#/sources", section: null,
    what: "Your reports, papers and web pages: add them, read one, your notes on them, and your Zotero library.",
    views: [["sources", "Documents", "#/sources", "book-open"], ["annotations", "Notes", "#/notes", "highlighter"], ["bibliography", "Bibliography", "#/bibliography", "library"]] },
  search: { title: "Search", icon: "text-search", href: "#/search", section: "explore",
    what: "Every place a word or phrase occurs in the documents, one line per place.", views: [] },
  codes: { title: "Codes", icon: "tag", href: "#/profile", section: "explore",
    what: "Which codes each document addresses (the SDG targets or your own), and your codebooks.",
    views: [["profile", "By document", "#/profile", "tag"], ["codebooks", "Codebooks", "#/codebooks", "book-marked"]] },
  concepts: { title: "Concepts", icon: "network", href: "#/concepts", section: "explore",
    what: "A glossary of the terms the documents use, grouped into concepts.", views: [] },
  themes: { title: "Themes", icon: "shapes", href: "#/themes", section: "explore",
    what: "What the documents are about, grouped into themes.", views: [] },
  hypotheses: { title: "Hypotheses", icon: "flask", href: "#/hypotheses", section: "check",
    what: "Check one hypothesis or a list against the documents, and every answer with its quotes.",
    views: [["answers", "Answers", "#/hypotheses", "history"], ["map", "Evidence map", "#/map", "layers"]] },
};

// The tabs of a place's views, under its page title: the same component on every place (and in Settings).
export function viewTabs(place, current) {
  const p = PLACES[place];
  if (!p || !p.views.length) return null;
  return h("nav", { class: "settings-tabs view-tabs", "aria-label": `${p.title}: views` },
    p.views.map(([key, label, href, ic]) => h("a", { href, "aria-current": key === current ? "page" : null }, icon(ic, { size: 14 }), label)));
}

// The line above a page title: which part of the app the page belongs to, and whether it needs the AI.
// 0.17.0: the part's short name, the same word as the sidebar's group ("Explore", "Check", "Project").
export function featureEyebrow(key) {
  const f = FEATURES[key];
  if (!f) return null;
  const sec = SECTIONS[f.section] || {};
  return h("span", { class: "feature-eyebrow" }, h("span", { class: "fe-section" }, sec.short || sec.title || ""), aiTag(f.ai));
}
