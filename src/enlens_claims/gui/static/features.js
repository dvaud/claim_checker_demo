// 0.9: one description of every feature, used by the sidebar, the Overview page and the page heads, so each feature
// says the same thing wherever it is shown: what it does, which part of the app it belongs to, and whether it needs
// the AI.
import { h, icon } from "./lib.js";

export const SECTIONS = {
  explore: { title: "Explore the documents", short: "Explore" },
  check: { title: "Check hypotheses", short: "Check" },
  project: { title: "Your project", short: "Project" },
};

// ai: "none" (never uses the AI), "optional" (works without it; the AI can add to it), "uses" (the AI does the work)
export const FEATURES = {
  sources: {
    section: "project", title: "Documents", icon: "book-open", href: "#/sources", ai: "none",
    what: "Add your reports, papers and web pages, say who may read each with AI, and open one to read it with its codes, key terms and references.",
  },
  search: {
    section: "explore", title: "Search", icon: "text-search", href: "#/search", ai: "none",
    what: "Every place a word or phrase occurs in the documents, one line per place, with the words around it.",
    use: "To see how the documents talk about something, or to find a passage you remember.",
  },
  profile: {
    section: "explore", title: "Profile", icon: "tag", href: "#/profile", ai: "optional",
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
    section: "check", title: "Check a hypothesis", icon: "flask", href: "#/check", ai: "uses",
    what: "Whether the documents support or contradict one statement, with the exact quotes for you to judge.",
  },
  batch: {
    section: "check", title: "Check several", icon: "list-checks", href: "#/batch", ai: "uses",
    what: "A list of hypotheses (pasted or from a spreadsheet), checked one after the other.",
  },
  history: {
    section: "check", title: "Results", icon: "history", href: "#/history", ai: "none",
    what: "Every hypothesis checked in this project: the answers, your reviews, the evidence map and Excel downloads.",
  },
};

const AI_TEXT = {
  none: ["circle-check", "No AI needed"],
  optional: ["sparkles", "Works without AI; the AI can add to it"],
  uses: ["cpu", "Uses the AI"],
};

export function aiTag(ai) {
  const [ic, text] = AI_TEXT[ai] || AI_TEXT.none;
  return h("span", { class: `ai-tag ai-${ai}` }, icon(ic, { size: 12 }), text);
}

// The line above a page title: which part of the app the page belongs to, and whether it needs the AI.
export function featureEyebrow(key) {
  const f = FEATURES[key];
  if (!f) return null;
  return h("span", { class: "feature-eyebrow" }, h("span", { class: "fe-section" }, SECTIONS[f.section].title), aiTag(f.ai));
}
