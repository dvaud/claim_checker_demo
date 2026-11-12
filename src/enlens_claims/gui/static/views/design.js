// 0.17.0: the live reference of the design guide (docs/DESIGN.md), at #/design. Every element is drawn here by the
// same helper the pages use, so this page cannot show a look the app does not have: change a component in
// components.css or its helper in lib.js, and this page changes with it. It loads site.css like every page, so an
// installation sees its own look. It is not in the sidebar or in Find: the guide and the developer docs point to it.
//
// One section per section of the guide, with the guide's number and title, in the guide's order (a test holds it):
// a reviewer with the guide open at 4.12 finds 4.12 here. The navigation's pieces (5.1 to 5.3) have no helper: they
// are drawn with their own classes, in each state; the live ones are beside the page. No sample leads away from the
// page: its links point at this page.
import {
  h, icon, toast, dialog, confirmDialog, popNote, helpMark, field, switchControl, rangeControl, spinner, emptyState,
  statusBadge, gradeBadge, codeChip, pageHead, downloadLinks, heatCell, strongerMark,
  button, downloadButton, fileButton, iconButton, link, tag, notice, card, fold, choice, optionCards, input, select,
  textarea, searchField, menu, workState, aiWhere, drawer, drawerButton, personMark, reviewedMark, severityTag, compare,
  shareState, absentDocument, listRow, listGroup, noticeList, tabs, judgementIcon, readsLine, stopButton, proposalCard, decisionCard, inset,
  passageNode, foundWords
} from "../lib.js";
import { aiTag, withAI, viewTabs, featureEyebrow } from "../features.js";

const HERE = "#/design";   // where a sample's link goes: nowhere else

// the colour tokens, by what they may mean (docs/DESIGN.md, section 3.1)
const COLOURS = [
  ["Ground and text", ["--bg", "--bg-2", "--surface", "--surface-2", "--surface-3", "--border", "--border-strong", "--text", "--text-2", "--muted"]],
  ["The accent: doing, going, chosen", ["--accent", "--accent-strong", "--accent-soft", "--accent-text", "--focus"]],
  ["Judgements of the evidence", ["--ok", "--ok-soft", "--partly", "--partly-soft", "--bad", "--bad-soft", "--mixed", "--mixed-soft", "--none", "--none-soft"]],
  ["Needs you, went wrong", ["--attention", "--attention-soft", "--danger", "--danger-soft"]],
  ["The documents' own words", ["--mark", "--mark-line", "--hl-yellow", "--hl-green", "--hl-blue", "--hl-pink"]],
];

// A section of the guide: its number and title as the guide writes them, what the element means in a line, its samples.
const section = (num, title, means, ...body) => {
  const id = `dz-${num.replace(".", "-")}`;
  return h("section", { class: "dz-section", id, "aria-labelledby": `${id}-h` },
    h("h2", { id: `${id}-h` }, `${num} ${title}`), h("p", { class: "dz-means" }, means), ...body);
};
const sample = (label, ...el) => h("div", { class: "dz-sample" }, h("p", { class: "dz-label" }, label), h("div", { class: "dz-show" }, ...el));
// a sample of a token: a small piece that takes the token's value, and the token's name
const tokenSample = (cls, property, token) => {
  const piece = h("span", { class: cls });
  piece.style.setProperty(property, `var(${token})`);
  return h("span", { class: "dz-swatch" }, piece, h("code", {}, token));
};
// a piece of the sidebar, on the sidebar's ground and at its width
const side = (...el) => h("div", { class: "dz-side" }, ...el);
const navEntry = (ic, name, current) => h("a", { href: HERE, "aria-current": current ? "page" : null },
  h("span", { class: "nav-icon" }, icon(ic, { size: 18 })), h("span", {}, name));

// the Display style as a page head draws it (pageHead({ display: true })), without the page's own title id
const displayTitle = (text) => {
  const t = pageHead(text, { display: true }).querySelector("h1");
  t.removeAttribute("id");
  t.removeAttribute("tabindex");
  t.setAttribute("role", "presentation");
  return t;
};

export async function renderDesign(page) {
  const noop = () => {};

  // ---- 3 The identity
  const swatches = COLOURS.map(([name, tokens]) => sample(name, h("div", { class: "dz-swatches" },
    tokens.map((t) => tokenSample("dz-chip", "background-color", t)))));
  // each style with its tokens (docs/DESIGN.md 3.2); real headings for their look, not headings of this page
  const typeScale = [
    sample("Display · serif, --fs-display, --fw-regular", displayTitle("Remote work lowers commuting emissions.")),
    sample("Title · --fs-title, --fw-strong", h("h1", { role: "presentation" }, "Page title")),
    sample("Section · --fs-section, --fw-strong", h("h2", { role: "presentation" }, "Section title")),
    sample("Body · --fs-body", h("p", {}, "Interface text, in the interface face.")),
    sample("Document text · serif, --fs-doc", h("p", { class: "serif" }, "The documents' own words, in the serif.")),
    sample("Small · --fs-small", h("p", { class: "small muted" }, "Help, facts, meta lines.")),
    sample("Group label · --fs-label, --fw-strong", h("span", { class: "nav-group" }, "Group label")),
    sample("Lead · --fs-lead: the box a hypothesis is written in (4.8); Fine · --fs-xs: times, a table's header row (4.20)"),
  ];

  // ---- 4.1 to 4.5
  const busy = button({ kind: "main", busy: true, icon: "loader" }, "Checking");
  const toggle = button({ kind: "quiet", sm: true, toggle: true }, "In context");
  toggle.addEventListener("click", () => toggle.setAttribute("aria-expanded", toggle.getAttribute("aria-expanded") === "true" ? "false" : "true"));
  const fileInput = h("input", { type: "file" });
  // the view tabs of a place, as a sample: a click shows the other tab as current and stays here
  const tabsDemo = viewTabs("hypotheses", "answers");
  tabsDemo.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a) return;
    e.preventDefault();
    for (const x of tabsDemo.querySelectorAll("a")) x.removeAttribute("aria-current");
    a.setAttribute("aria-current", "page");
  });

  // Settings' tabs, as a sample: a click shows the other tab as current and stays here
  const settingsTabs = tabs({ label: "A sample of Settings' tabs", current: "model", items: [["model", "AI", HERE, "cloud"], ["basics", "Checking", HERE, "flask"], ["advanced", "Technical", HERE, "sliders"]] });
  settingsTabs.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a) return;
    e.preventDefault();
    for (const x of settingsTabs.querySelectorAll("a")) x.removeAttribute("aria-current");
    a.setAttribute("aria-current", "page");
  });

  // Tabs without an address, as a sample: their panel says which is chosen; the arrow keys, Home and End move here too
  const tabPanel = h("p", { class: "muted small" });
  const PANEL_WORDS = { log: "The research log's entries would be here.", team: "What came in from your colleagues would be here." };
  const noAddressTabs = tabs({ label: "A sample of tabs without an address", current: "log", panel: tabPanel,
    onTab: (key) => { tabPanel.textContent = PANEL_WORDS[key]; },
    items: [{ key: "log", label: "Research log", icon: "notebook" }, { key: "team", label: "Team", icon: "users" }] });
  tabPanel.textContent = PANEL_WORDS.log;

  // ---- 4.14: page heads as samples (the one title a page has is this page's own, so these give up its id and its
  // place among the headings)
  const sampleHead = (title, opts) => {
    const head = pageHead(title, opts);
    const t = head.querySelector("h1");
    t.removeAttribute("id");
    t.removeAttribute("tabindex");
    t.setAttribute("role", "presentation");
    return h("div", { class: "dz-frame" }, head);
  };

  // ---- 4.19: the drawer, and a drawer with two tabs
  const logEntry = (ic, meta, text, actions) => h("li", { class: "log-entry" }, h("span", { class: "log-icon" }, icon(ic, { size: 14 })),
    h("div", { class: "log-body" }, h("div", { class: "log-meta" }, meta), h("div", { class: "log-text" }, text),
      actions ? h("div", { class: "log-actions" }, actions) : null));
  const drawerDemo = drawer({ id: "dz-drawer", title: "Research log", icon: "notebook",
    control: choice({ label: "Show entries of", filter: true, sm: true, value: "page", options: [["page", "This page"], ["all", "All"]] }),
    sections: [h("div", { class: "log-new" }, textarea({ rows: 2, "aria-label": "A new entry", placeholder: "A decision and why…" }),
      h("div", { class: "log-new-foot" }, h("p", { class: "muted small" }, "Kept with: this hypothesis"), button({ kind: "main", sm: true }, "Add to the log"))),
    h("ol", { class: "log-entries" }, h("li", { class: "log-entry log-own" }, h("span", { class: "log-icon" }, icon("note", { size: 14 })),
      h("div", { class: "log-body" }, h("div", { class: "log-meta" }, h("time", { class: "log-time" }, "Today 17:26")),
        h("div", { class: "log-text log-own-text" }, "Kept the 2019 survey out: its sample is too small."))))],
    foot: [link({ href: HERE }, "The whole research log"), h("span", { class: "muted" }, " on the Overview")] });
  const tabBodies = {
    log: () => [h("p", {}, "The first tab's sections: the research log.")],
    team: () => [h("p", {}, "The second tab's sections, drawn when its tab is chosen.")],
  };
  const tabbedDrawer = drawer({ id: "dz-drawer-tabs", title: "Beside the page",
    tabs: [{ key: "log", label: "Research log", icon: "notebook" }, { key: "team", label: "Team", icon: "users" }], current: "log",
    onTab: (key) => tabbedDrawer.setSections(tabBodies[key]()),
    sections: tabBodies.log() });
  for (const d of [drawerDemo, tabbedDrawer]) { d.hidden = false; d.classList.add("dz-drawer"); }

  // ---- 4.20 and 5.4: a table of answers
  const answersTable = () => h("div", { class: "table-wrap" }, h("table", { class: "table table-responsive" },
    h("thead", {}, h("tr", {}, h("th", {}, "Hypothesis"), h("th", {}, "Answer"), h("th", { class: "num" }, "Excerpts"), h("th", { class: "actions" }, ""))),
    h("tbody", {},
      h("tr", {}, h("td", { "data-label": "Hypothesis" }, link({ kind: "title", serif: true, href: HERE }, "Hybrid work improves wellbeing.")),
        h("td", { "data-label": "Answer" }, workState("running", "Checking", 41)), h("td", { class: "num", "data-label": "Excerpts" }, "—"),
        h("td", { class: "actions" }, stopButton())),
      h("tr", {}, h("td", { "data-label": "Hypothesis" }, link({ kind: "title", serif: true, href: HERE }, "Working from home reduces commuting emissions.")),
        h("td", { "data-label": "Answer" }, statusBadge("contested", { short: true })), h("td", { class: "num", "data-label": "Excerpts" }, "3"),
        h("td", { class: "actions" }, button({ kind: "quiet", sm: true }, "Say why"))))));

  // ---- 4.24: concordance lines
  const kwLine = (title, left, node, right) => h("tr", {},
    h("td", { class: "kw-where kw-where-title" }, link({ kind: "title", serif: true, href: HERE, class: "kw-title" }, title)),
    h("td", { class: "kw-left" }, h("span", {}, left)),
    h("td", { class: "kw-node" }, h("mark", {}, node)),
    h("td", { class: "kw-right" }, right),
    h("td", { class: "kw-act" }, button({ kind: "quiet", sm: true, icon: "flask" }, "Check")));

  // ---- 4.26: an excerpt card
  const excerpt = (grade, reviewed) => h("article", { class: `ev ev-${grade}`, "data-reviewed": reviewed ? "1" : null },
    h("div", { class: "ev-top" }, gradeBadge(grade), h("span", {}, "Certainty: medium")),
    h("p", { class: "ev-src" }, h("span", { class: "title" }, "Commuting less, emitting less?"), h("span", { class: "page" }, " · paragraph 5 of 9")),
    h("p", { class: "passage" }, "Home energy rises in winter. ", h("mark", { class: "quote" }, "The climate benefit of home working is real but small."), " It does not replace investment."),
    h("div", { class: "judge-row" }, button({ sm: true }, "Agree"), button({ kind: "quiet", sm: true }, "Not about this"),
      button({ kind: "quiet", sm: true, toggle: true }, "In context"), button({ kind: "quiet", sm: true, toggle: true }, "Details")));

  // ---- 5.2: the status area in each state, the last row
  const aiCard = (cls, ic, name, words) => h("div", { class: "status-area" }, h("div", { class: "privacy-wrap" },
    h("a", { class: `privacy ${cls}`, href: HERE }, icon(ic, { size: 16 }), h("div", {}, h("strong", {}, name), h("span", { class: "privacy-sub" }, words)))));
  const workBox = (kind, lead, words, time, sub, who, act) => h("div", { class: "status-area" }, h("div", { class: `work-box work-${kind}` },
    h("a", { class: "work-main", href: HERE }, h("span", { class: "work-line" }, lead, h("strong", { class: "work-text" }, words),
      time ? h("span", { class: "work-time" }, time) : null),
    h("span", { class: "work-sub" }, h("span", { class: "work-sub-text" }, sub), who || null)), act || null));
  const lastRow = (action) => h("div", { class: "sidebar-app" }, h("div", { class: "sidebar-app-row" },
    h("nav", { class: "nav nav-foot", "aria-label": "A sample of the last row" }, navEntry("sliders", "Settings")), action,
    iconButton({ icon: "monitor", label: "Theme: follows this computer", size: 17, class: "theme-btn" })));

  // ---- 5.3: the Find button (pressed, it opens the real finder)
  const liveFind = document.getElementById("find-btn");
  const findButton = h("button", { class: "find-btn", type: "button", "aria-haspopup": "dialog", onClick: () => liveFind && liveFind.click() },
    h("span", { class: "nav-icon" }, icon("search", { size: 18 })), h("span", { class: "find-text" }, "Find a feature or page"),
    h("kbd", { class: "find-key" }, (document.getElementById("find-key") || {}).textContent || "Ctrl K"));

  const sections = [
    section("3.1", "Colour", "Every colour is a token, set for light and dark; each has its meaning.", ...swatches),
    section("3.2", "Type", "Two faces, two weights, one scale: the serif is for the research's own words.", ...typeScale),
    section("3.3", "Space, corners, shadows, icons", "The steps every element is built from.",
      sample("Space: 4, 8, 12, 16, 24, 32 px", ...[1, 2, 3, 4, 5, 6].map((n) => tokenSample("dz-space", "width", `--space-${n}`))),
      sample("Corners: code and keys, tags, every control, cards, dialogs, pills",
        ...["--radius-xs", "--radius-sm", "--radius-ctl", "--radius", "--radius-lg", "--radius-pill"].map((t) => tokenSample("dz-corner", "border-radius", t))),
      sample("Shadows: what hangs from a trigger, what lies over everything (nothing in the page's flow has one)",
        tokenSample("dz-shadow", "box-shadow", "--shadow"), tokenSample("dz-shadow", "box-shadow", "--shadow-lg")),
      sample("Icons: 12 px with small text, 16 on buttons, 18 in the sidebar, 20 in the large badge, 28 in an empty state",
        ...[12, 16, 18, 20, 28].map((size) => icon("flask", { size }))),
      sample("Icons with one meaning each: the AI mark's chip; where text goes; needs you; went wrong; done; reviewed by you",
        aiTag("uses"), h("span", { class: "it" }, icon("cloud", { size: 14 }), "Claude"), h("span", { class: "it" }, icon("house", { size: 14 }), "this computer"),
        h("span", { class: "it" }, icon("alert-triangle", { size: 14 }), "needs you"), h("span", { class: "it" }, icon("alert-circle", { size: 14 }), "went wrong"),
        h("span", { class: "it" }, icon("check", { size: 14 }), "done"), personMark(["you"])),
      sample("The circle family: a judgement's own icons, only in a badge or a grade said in a dense place",
        ...["supports", "partially_supports", "refutes", "none"].map((g) => judgementIcon(g, 16)),
        ...["contested", "uncertain"].map((s) => judgementIcon(s, 16)))),

    section("4.1", "Buttons", "Pressing it does something. Every button has an edge at rest.",
      sample("Kinds: main, standard, quiet, danger (the confirming red one is in 4.16)",
        button({ kind: "main" }, "Check 3"), button({}, "Look before checking"), button({ kind: "quiet" }, "Say why"), button({ kind: "danger" }, icon("trash", { size: 15 }), "Remove")),
      sample("Small, the same kinds", button({ kind: "main", sm: true }, "Add to the log"), button({ sm: true }, "Agree"),
        button({ kind: "quiet", sm: true }, "Not about this"), button({ kind: "danger", sm: true }, "Delete this result")),
      sample("Stepping through a page's own content (a result's excerpts still to judge): the page's main button, an arrow after its words; then a small standard one",
        button({ kind: "main" }, "Next to review", icon("arrow-right", { size: 14 })), button({ sm: true }, "Review the 3 excerpts judged not about it")),
      sample("States: disabled, busy, a toggle, opens beside",
        button({ disabled: true }, "Check 0"), busy, toggle, button({ sm: true, opens: true, "aria-expanded": "true" }, icon("notebook", { size: 15 }), "Research log")),
      sample("A download, a file chooser (both actions)", downloadLinks([{ text: "Excel (.xlsx)", onClick: noop }, { text: "CSV", onClick: noop }]),
        downloadButton({ onClick: noop }, "Download a highlighted copy"), fileButton({ icon: "upload" }, fileInput, "Load a spreadsheet"))),

    section("4.2", "Icon buttons", "An action shown by its icon alone; its name is its tooltip.",
      sample("32 px, and 24 px in dense rows and for the help mark", iconButton({ icon: "x", label: "Close" }), iconButton({ icon: "copy", label: "Copy" }),
        iconButton({ icon: "x", label: "Remove the word", sm: true }), helpMark("What is strictness?", "How sure the AI must be for an excerpt to count."))),

    section("4.3", "Links", "Takes you somewhere. Teal words; the name of an item is its link.",
      sample("A link in a sentence", h("p", {}, "Change it in ", link({ href: HERE }, "Settings › AI"), ".")),
      sample("A title link: the research's own words in serif, other names not",
        h("p", {}, link({ kind: "title", serif: true, href: HERE }, "Hybrid work improves wellbeing.")),
        h("p", {}, link({ kind: "title", href: HERE }, "SDG targets (copy)"))),
      sample("A back link, above a page title", link({ kind: "back", href: HERE }, "All hypotheses")),
      sample("The next step, done on another page", link({ kind: "next", href: HERE }, "Add documents on the Documents page")),
      sample("Outside the app", link({ kind: "external", href: "https://github.com/dvaud/claim_checker_demo" }, "Report a problem (on GitHub)")),
      sample("A move on this page", h("p", {}, "The quote is in paragraph 5. ", link({ kind: "jump", onClick: noop }, "Show it")))),

    section("4.4", "The AI mark and the AI line", "Does this use the AI (the chip), and where text goes (the cloud or the house).",
      sample("The AI mark: three values", aiTag("uses"), aiTag("optional"), aiTag("none")),
      sample("A page's eyebrow", featureEyebrow("check")),
      sample("A button that sends text to an AI, with its mark (withAI())", ...withAI(button({ sm: true }, "Read more excerpts"))),
      sample("A row of such buttons: one mark, after the last", ...withAI(button({ sm: true }, "Ask a stronger model"), button({ sm: true }, "Get a second opinion"))),
      sample("The AI line of the AI chosen in Settings (readsLine())", readsLine("the excerpts again")),
      sample("The AI line, once per card", aiWhere("Claude, on your plan, reads the excerpts it needs."),
        aiWhere("A model on this computer reads the excerpts; nothing leaves it.", "local"),
        aiWhere("No AI model is set up yet: set one up in Settings › AI.", "attention"))),

    section("4.5", "View tabs", "Other views of this place, each with its address; the current one teal on the tabs' line.",
      sample("A place's views (viewTabs())", h("div", { class: "dz-block" }, tabsDemo)),
      sample("Settings' tabs (tabs())", h("div", { class: "dz-block" }, settingsTabs)),
      sample("Tabs without an address (a drawer's): buttons with the same look; Left and Right, Home and End move between them",
        h("div", { class: "dz-block" }, noAddressTabs, tabPanel))),

    section("4.6", "Choices", "One of a few values, shown in place; or a filter of a list.",
      sample("One of a few values", choice({ label: "Show", value: "cards", options: [["cards", "Cards"], ["table", "Table"]] })),
      sample("A filter, with the rows each would show",
        choice({ label: "Filter", filter: true, value: "all", options: [["all", "All", 3], ["supported", "Supported", 1], ["mixed", "Mixed evidence", 2]] })),
      sample("Small, for a tight place", choice({ label: "Show entries of", filter: true, sm: true, value: "page", options: [["page", "This page"], ["all", "All"]] }))),

    section("4.7", "Option cards", "A choice whose options each need a sentence.",
      optionCards({ label: "Who may read new documents", value: "cloud", options: [
        { value: "cloud", icon: "cloud", title: "Claude may read them", text: "The excerpts a check needs go to Claude." },
        { value: "local", icon: "house", title: "Only a local AI", text: "A model on this computer reads them." },
        { value: "none", icon: "eye-off", title: "No AI", text: "You judge them yourself." }] }),
      sample("With real radio inputs (a form's question), a tag and a foot line",
        optionCards({ name: "dz-route", label: "Which AI reads the documents", value: "claude_code", options: [
          { value: "claude_code", icon: "cloud", title: "Claude Code", tag: "Recommended", text: "Claude reads the excerpts on your own Claude plan.", foot: [icon("cloud", { size: 12 }), "Only the passages inside the tasks go to Anthropic"] },
          { value: "local", icon: "house", title: "A model on this computer", text: "Free and fully private; judges less well than Claude.", foot: [icon("house", { size: 12 }), "Nothing leaves this computer"] }] }))),

    section("4.8", "Form fields", "Type or pick here: the label above, help under it.",
      h("div", { class: "fields-2" },
        field("A line of text", input({ placeholder: "A name" }), { help: "Help under the field." }),
        field("A choice from a list", select({}, h("option", {}, "SDG targets"), h("option", {}, "My codebook"))),
        field("Disabled", input({ value: "Set by whoever installed ENLENS", disabled: true }), { help: "Says why it cannot be changed." }),
        field("Code or command", input({ mono: true, value: "/enlens-run" }))),
      field("A hypothesis", textarea({ hyp: true, rows: 2, placeholder: "A hypothesis, or several: one per line" })),
      sample("A search field", searchField({ placeholder: "Find a hypothesis…", "aria-label": "Find a hypothesis" })),
      sample("Small fields in a row of controls",
        h("label", { class: "dz-inline" }, "Find", select({ sm: true }, h("option", {}, "any of the words"), h("option", {}, "all of the words"))),
        h("label", { class: "dz-inline" }, "within", input({ sm: true, type: "number", min: 1, max: 50, value: 5 }), "words")),
      switchControl("Try new versions early", true, { help: "A switch applies at once." }),
      rangeControl("Strictness", { min: 0, max: 1, step: .05, value: .6, format: (v) => `${Math.round(v * 100)}%`, ends: ["Count more", "Count fewer"] })),

    section("4.9", "Judgement badges", "What the evidence says: the only pills in the app.",
      sample("Answers", ...["supported", "partially_supported", "contested", "contradicted", "uncertain", "unsupported", "no_passages"].map((s) => statusBadge(s, { short: true }))),
      sample("Grades of one excerpt", gradeBadge("supports"), gradeBadge("partially_supports"), gradeBadge("refutes"), gradeBadge(null)),
      sample("Not counted: the AI was less sure than your strictness", gradeBadge("supports", true)),
      sample("A grade said in a dense place (a table of excerpts, the answers' counts): its icon and words, grey",
        h("span", { class: "it" }, judgementIcon("supports"), "Supports, 85% sure"), h("span", { class: "it" }, judgementIcon("refutes"), "1 contradict")),
      sample("The large answer of a result page", statusBadge("contradicted", { size: "lg", text: "Contradicted by your documents" }))),

    section("4.10", "Tags and counts", "A fact about an item; never pressed.",
      sample("A fact, a code, a count", tag({ icon: "house" }, "Only a local AI"),
        codeChip("SDG", "13.2", "Integrate climate change measures into national policies"), tag({ kind: "count" }, "12 passages")),
      sample("A fact that needs you", tag({ kind: "attention" }, "very short: is this the whole text?")),
      sample("A tag that explains itself", strongerMark("partially_supported", { changed: 2 })),
      sample("Person marks in a row that names the person: you, with a role, several (Anna de Vries is AV), one word (Cleo is C)",
        personMark(["you"]), personMark(["Anna de Vries"], { role: "Owner" }), personMark(["you", "Anna de Vries", "Ben Okafor"]), personMark(["Cleo"])),
      sample("A person mark that stands alone shows the name: short, full, with what they did",
        personMark(["Anna de Vries"], { name: "short" }), personMark(["Anna de Vries"], { name: "full" }),
        personMark(["Anna de Vries"], { name: "short", prefix: "Changed by" })),
      sample("Reviewed, and partly reviewed (in words: no dashed edge)", reviewedMark(["you"]), reviewedMark(["you"], true)),
      sample("A count beside a name says what it counts", link({ kind: "title", serif: true, href: HERE }, icon("file-text", { size: 12 }), " Policy brief"), tag({ kind: "count" }, "4 passages")),
      sample("A severity: low, medium, high (never a judgement's colour)", severityTag("low"), severityTag("medium"), severityTag("high"))),

    section("4.11", "Cards", "One thing, or one task, held together.",
      sample("A card: its head a title, at most a help mark and one action",
        card({ title: "A card", help: helpMark("About cards", "One thing, or one task, held together."), action: button({ kind: "quiet", sm: true }, "One action") },
          h("p", {}, "Its head (card({ title, help, action })): a title and at most a help mark and one action. A card holds at most one box, never a card."))),
      sample("A card with AI actions: one AI mark for its row, its AI line last",
        card({ title: "A card with AI actions", titleId: "dz-ai-card-h" },
          h("div", { class: "btn-row" }, withAI(button({ sm: true }, "Ask a stronger model"), button({ sm: true }, "Get a second opinion"))),
          aiWhere("A card that holds AI actions ends with its AI line."))),
      sample("The one box a card may hold (inset()): one of a list in a card, and one not in force yet (tentative)", card({ as: "div" },
        h("ul", { class: "stack dz-list" }, inset({ as: "li" }, link({ kind: "title", serif: true, href: HERE }, "Commuting"), h("span", { class: "muted small" }, " · the same thing, said by 4 documents")),
          inset({ as: "li", tentative: true }, link({ kind: "title", serif: true, href: HERE }, "Office energy"), h("span", { class: "muted small" }, " · proposed by the AI, not accepted"))))),
      sample("The small card, one of many in a list", card({ sm: true, as: "div" }, h("p", {}, "A note: its words, where it is, what can be done with it."))),
      sample("A card that folds", card({ as: "details" }, h("summary", {}, icon("sliders", { size: 14 }), "Codebook settings"), h("p", {}, "The card's body, shown when it is open.")))),

    section("4.12", "Notices", "Something to know before going on; it stays while it is true.",
      notice({ kind: "info" }, h("p", {}, "A fact to keep in mind before going on.")),
      notice({ kind: "done" }, h("p", {}, "Ollama is installed and running.")),
      notice({ kind: "attention" }, h("p", {}, "3 documents need a look."), h("p", {}, button({ sm: true }, "Look at them"))),
      notice({ kind: "error", live: false }, h("p", {}, "The documents could not be read.")),
      notice({ kind: "info" }, h("p", {}, h("strong", {}, "Add documents first. "), "Search works on the documents of this project."),
        h("p", {}, link({ kind: "next", href: HERE }, "Add documents on the Documents page")))),

    section("4.13", "Empty states", "Nothing here yet, and the one step that fills it.",
      emptyState("flask", "No answers yet", "Check a hypothesis and its answer appears here, with its quotes. The work is done on another page: a next-step link.",
        link({ kind: "next", href: HERE }, "Check a hypothesis")),
      emptyState("tag", "No codes yet", "Which codes each document addresses. The work is done here: one main button.",
        button({ kind: "main" }, "Find the codes by keywords"))),

    section("4.14", "Page heads", "Where you are and what the page is for.",
      sample("A place: the section and its AI mark, the title, one line; at the right only actions",
        sampleHead("Hypotheses", { eyebrow: featureEyebrow("check"), sub: "Check one hypothesis or a list against the 3 documents, and judge each answer by its quotes.",
          actions: downloadLinks([{ text: "Excel (.xlsx)", onClick: noop }, { text: "CSV", onClick: noop }]) })),
      sample("One thing: a back link, its name in the Display serif, its facts; a way to another page in the line under the title",
        sampleHead("Remote work and commuting", { back: { href: HERE, text: "All themes" }, display: true,
          sub: link({ kind: "next", href: HERE }, "Check a hypothesis about this theme"),
          facts: ["Theme 3", "42 passages from 5 documents", "Named by the AI"],
          actions: [button({ sm: true }, "Rename…"), button({ kind: "danger", sm: true }, "Remove…")] }))),

    section("4.15", "Toasts", "Something just happened: saved, copied, could not be done.",
      sample("Show one", button({ kind: "quiet", onClick: () => toast("Saved.", "ok") }, "A toast"),
        button({ kind: "quiet", onClick: () => toast("The file could not be read.", "error", { detail: "ValueError: …" }) }, "An error toast"))),

    section("4.16", "Dialogs", "Decide this now, before anything else.",
      sample("Open one", button({ onClick: () => dialog({ title: "A dialog", body: h("p", {}, "Decide this now."), actions: [{ text: "Cancel", value: false }, { text: "Keep it", value: true, primary: true }] }) }, "A dialog"),
        button({ kind: "danger", onClick: () => confirmDialog({ title: "Remove the codebook?", message: "Its codes go; your documents stay.", confirmText: "Remove" }) }, "A dialog that confirms"))),

    section("4.17", "Menus", "More actions for one thing, under its button.",
      sample("A menu: a dangerous row last, after a line",
        menu({ items: [{ text: "History", icon: "history", onClick: noop }, { text: "Download as CSV", icon: "download", onClick: noop }, "sep", { text: "Remove the codebook", icon: "trash", danger: true, onClick: noop }] }))),

    section("4.18", "Help notes and defined terms", "More about this; this word has a definition.",
      sample("A help mark", h("span", {}, "Strictness"), helpMark("What is strictness?", "How sure the AI must be for an excerpt to count.")),
      sample("A defined term", h("p", {}, "The answer follows your ",
        popNote(h("button", { class: "defined", type: "button" }, "strictness"), "How sure the AI must be for an excerpt to count."), "."))),

    section("4.19", "The drawer", "Your own working space beside any page.",
      sample("Its button, in the same spot on every page", drawerButton({ label: "Research log", icon: "notebook", onClick: noop })),
      sample("The drawer: a head with one control, sections, a foot", drawerDemo),
      sample("With two tabs: the head shows them in the view tabs' look", tabbedDrawer)),

    section("4.20", "Tables, lists and dense places", "Rows divided by lines; the name of each row is its link, its actions at the row's end.",
      answersTable(),
      sample("A list of entries", h("ol", { class: "log-entries" },
        logEntry("flask", h("time", { class: "log-time" }, "Today 17:26"), link({ kind: "title", href: HERE }, "Checked the hypothesis “Hybrid work improves wellbeing”."), button({ kind: "quiet", sm: true }, "Say why")),
        logEntry("book-open", h("time", { class: "log-time" }, "Today 16:02"), "Added 3 documents."))),
      sample("Rows grouped by person or day: who, the item's title link, a quiet second line, when, one or two actions",
        listGroup("Anna de Vries", listRow({ person: personMark(["Anna de Vries"]), title: "Remote work lowers commuting emissions.", href: HERE, time: "17:26",
          actions: [button({ kind: "quiet", sm: true }, "Accept"), button({ kind: "quiet", sm: true }, "Decline")] }),
        listRow({ person: personMark(["Ben Okafor"], { role: "Co-owner" }), title: "Ben Okafor", sub: "ENLENS 0.17.0" }),
        listRow({ person: personMark(["Cleo Ma"]), title: "Cleo Ma", sub: "Cleo's copy needs ENLENS 0.17.1 or newer", warn: true })))),

    section("4.21", "Progress and work states", "Work under way, waiting or not running: words and an icon, never a pill.",
      sample("Running, waiting its turn, not running, paused by you, settled, needs you, done, did not work", workState("running", "Checking", 41), workState("waiting", "Waiting its turn"),
        workState("stopped", "Not running"), workState("paused", "Paused"), workState("ended", "Taken back"), workState("attention", "The shared folder cannot be reached"), workState("done", "Done"), workState("failed", "Did not work")),
      sample("A state of work where an answer would be", statusBadge("not_checked")),
      sample("Queued, with its one action", workState("waiting", "Queued: starts when Read the documents has finished"), button({ kind: "quiet", sm: true }, "Cancel")),
      sample("Loading a part of a page", spinner("Loading the works"), h("span", { class: "muted" }, " Loading the works…")),
      sample("A bar", h("div", { class: "dz-bar" },
        h("div", { class: "progress-bar", role: "progressbar", "aria-label": "A sample bar", "aria-valuenow": "40", "aria-valuemin": "0", "aria-valuemax": "100" }, h("span", { style: { width: "40%" } }))))),

    section("4.22", "Folds", "More here, folded away.",
      fold({}, "More options", h("p", { class: "muted" }, "Optional reading or settings, folded away.")),
      fold({ sm: true }, "Technical details", h("p", { class: "small muted" }, "The small kind, in dense places."))),

    section("4.23", "Quotes and highlights", "Marks in the documents' own words, each with one look.",
      sample("The quote the AI found: passageNode()",
        passageNode("Commuting fell by a fifth. Remote work lowers commuting emissions, especially for car commuters.", 27, 65, "p", "serif")),
      sample("Your highlights, one with a note",
        h("p", { class: "serif" }, h("mark", { class: "hl hl-yellow" }, "Yellow"), " ", h("mark", { class: "hl hl-green" }, "green"), " ",
          h("mark", { class: "hl hl-blue hl-noted" }, "blue, with a note"), " ", h("mark", { class: "hl hl-pink" }, "pink"), ".")),
      sample("Words found by a search or a code; places that name the same thing",
        h("p", { class: "serif" }, "Most ", h("mark", { class: "dv-hit" }, "workers"), " kept two office days. ",
          h("mark", { class: "dv-ref dv-ref-named" }, "The municipality"), " says ", h("mark", { class: "dv-ref" }, "it"), " will review the rule.")),
      sample("Words found by matching outside the reading view (the words that name a work): foundWords()",
        h("p", { class: "serif" }, "As shown in ", foundWords("Working from home and wellbeing"), " (2024), most panel members…"))),

    section("4.24", "Concordance lines", "Every place some words occur, one line each, the words centred.",
      h("div", { class: "kwic-wrap" }, h("table", { class: "kwic" },
        h("caption", { class: "visually-hidden" }, "Concordance: the words found, with the words before and after"),
        h("tbody", {},
          kwLine("Commuting less, emitting less? A survey of 4,000 workers", "…in the summary. Remote", "work", ["reduces commuting ", h("mark", { class: "kw-also" }, "emissions"), " by a fifth…"]),
          kwLine("Policy brief: hybrid working at the Municipality", "…two office days. Hybrid", "work", "is the rule since 2023 for most teams…"))))),

    section("4.25", "The heat grid", "How much each document addresses each code, theme or hypothesis.",
      h("div", { class: "map-wrap" }, h("table", { class: "map-table" }, h("tbody", {}, h("tr", {},
        h("th", { class: "map-hyp" }, link({ kind: "title", serif: true, href: HERE }, "A document")),
        ...[0, 1, 3, 8, 20].map((n) => heatCell(n, 20, `Code ${n}`, "pf", n ? noop : null))))))),

    section("4.26", "Excerpt cards", "One excerpt the AI read for a hypothesis.",
      sample("The quote takes its grade's tint and line; Agree first, the toggles last",
        h("div", { class: "ev-list" }, ...["supports", "partially_supports", "refutes"].map((g) => excerpt(g)))),
      sample("A reviewed card sits back", h("div", { class: "ev-list" }, excerpt("supports", true)))),

    section("4.27", "Comparisons", "Two versions of one thing, side by side, to choose between.",
      compare({ left: { title: personMark(["you"]), meta: h("span", {}, "Today 10:02"), body: h("p", { class: "serif" }, "Supports: the survey covers 4,000 workers.") },
        right: { title: personMark(["Anna de Vries"]), meta: h("span", {}, "Yesterday 16:40"), body: h("p", { class: "serif" }, "Not about this hypothesis.") },
        actions: [button({ sm: true }, "Keep mine"), button({ sm: true }, "Keep theirs"), button({ kind: "quiet", sm: true }, "Keep both")] })),

    section("5.1", "The sidebar", "The places of the app. The live sidebar is beside this page; these are its pieces.",
      sample("The project switch", side(h("div", { class: "project-switch" }, menu({ label: "Project: Demo", listClass: "ps-menu",
        trigger: [icon("folder", { size: 16 }), h("span", { class: "ps-name" }, h("span", { class: "ps-label" }, "Project"),
          h("span", { class: "ps-name-text" }, "Demo")), icon("chevron-down", { size: 14 })],
        items: [{ text: "Demo", icon: "folder", current: true, meta: "3 documents · 3 answers" }, "sep",
          { text: "New project…", icon: "plus" }, { text: "Manage projects", icon: "sliders", href: HERE }] })))),
      sample("Entries: a place, the current place; a group label with its AI mark",
        side(h("nav", { class: "nav", "aria-label": "A sample of the places" }, navEntry("grid", "Overview"), navEntry("book-open", "Documents", true),
          h("span", { class: "nav-group", role: "presentation" }, "Explore", aiTag("optional")), navEntry("text-search", "Search"))))),

    section("5.2", "The status area and the last row", "One fixed size: the AI line's card, or the work box in exactly that space.",
      sample("The AI line", side(aiCard("privacy-cloud", "cloud", "Claude, on your plan", "Only the passages of AI tasks leave this computer"))),
      sample("No AI can run yet: the attention look", side(aiCard("privacy-setup", "alert-triangle", "No AI model set up yet", "Exploring works; checking needs one"))),
      sample("Work running", side(workBox("running", h("span", { class: "running-dot", "aria-hidden": "true" }), "Check", "41 s", "and 1 more running",
        h("span", { class: "work-who" }, icon("cloud", { size: 12 }), "Claude")))),
      sample("Work not running: one action", side(workBox("stalled", icon("pause", { size: 14 }), "Not running", null, "2 tasks waiting", null,
        button({ kind: "main", sm: true, class: "work-act" }, icon("play", { size: 12 }), "Start")))),
      sample("The last row: Settings, Quit, the theme", side(lastRow(button({ kind: "quiet", sm: true }, icon("power", { size: 13 }), h("span", {}, "Quit"))))),
      sample("An update waits: it takes Quit's place", side(lastRow(button({ kind: "main", sm: true }, icon("arrow-up", { size: 13 }), h("span", {}, "Update")))))),

    section("5.3", "Find", "Find a page, a view or a setting by its words, never with the AI.",
      sample("The Find button looks like the field it opens (press it: the finder opens)", side(findButton))),

    section("5.4", "The Hypotheses composer and answers", "One box, one main action with its AI mark, one AI line; then the answers.",
      card({ as: "div", class: "hyp-form hyp-compose" },
        h("div", { class: "field" }, h("label", { class: "field-label", for: "dz-hyp" }, "Your hypothesis"),
          textarea({ hyp: true, rows: 2, id: "dz-hyp", placeholder: "A hypothesis, or several: one per line" }),
          h("div", { class: "hint-row" }, h("span", { class: "hyp-hint-main" }, "One sentence that could be true or false; for several, one per line."),
            h("span", { class: "hyp-hint-side" }, fileButton({ kind: "quiet", icon: "upload" }, h("input", { type: "file" }), "Load a spreadsheet (CSV) or text file")))),
        h("div", { class: "btn-row hyp-actions" }, withAI(button({ kind: "main", icon: "flask" }, "Check 3"), button({ icon: "eye" }, "Look before checking"))),
        readsLine("the excerpts it needs", { class: "hyp-reads" })),
      answersTable()),

    section("5.5", "The pieces of working together", "Built from the elements above; none has a look of its own.",
      sample("Sharing: a fact and its action", shareState("private"), button({ sm: true }, "Share"),
        shareState("shared"), button({ kind: "quiet", sm: true }, "Unshare"), shareState("withdrawn")),
      sample("Who, where nothing else names them: a shared item's maker, a changed-by line (the name beside the mark)",
        shareState("shared"), personMark(["Anna de Vries"], { name: "short", prefix: "By" }), personMark(["Ben Okafor"], { name: "short", prefix: "Changed by" })),
      sample("A document not on this computer", absentDocument("Commuting less, emitting less?", { onAdd: noop })),
      sample("Sync states", workState("done", "Synced 3 minutes ago"), workState("running", "Syncing"), workState("stopped", "Offline"),
        workState("attention", "The shared folder cannot be reached"), workState("attention", "Anna's copy needs a newer ENLENS")),
      sample("A set-up step", card({ title: "Choose the shared folder" }, h("div", { class: "stack" },
        h("div", { class: "row" }, h("div", { class: "grow" }, field("Folder", input({ mono: true, value: "/Users/you/Shared/Project" }))), button({ sm: true }, "Browse…")),
        notice({ kind: "done" }, h("p", {}, "The folder can be read and written.")),
        switchControl("Keep documents marked Only a local AI or No AI out of the shared folder", true, { help: "Colleagues then see your judgements and notes on them, but not their text. Turn it off only if every colleague may read every document. It changes nothing on this computer." }),
        h("div", { class: "btn-row" }, button({ kind: "main" }, "Share this project")),
        aiWhere("Your judgements, notes and the log go into this folder; your documents' text stays on this computer.", "folder")))),
      sample("Rows in the drawer, grouped by person or by day", h("div", { class: "dz-block" },
        listGroup("Today", listRow({ person: personMark(["Anna de Vries"]), title: "Remote work lowers the quality of public services.", serif: true, href: HERE, time: "10:02",
          actions: [button({ kind: "quiet", sm: true }, "Say why")] }),
        listRow({ person: personMark(["Ben Okafor"]), title: "Ben Okafor", sub: "ENLENS 0.16.1: needs a newer ENLENS to read your changes", warn: true, time: "09:40" })))),
      sample("News since last time: the tab's count, What came in, Seen before", h("div", { class: "dz-block" },
        tabs({ label: "The drawer's tabs", items: [{ key: "log", label: "Research log", icon: "notebook" }, { key: "team", label: "Team", icon: "users", count: "3 new" }], current: "team", onTab: noop }),
        listGroup({ text: "What came in", action: button({ kind: "quiet", sm: true, icon: "check" }, "Mark as seen") },
          listRow({ person: personMark(["Anna de Vries"]), title: "Anna judged 3 excerpts of “Hybrid work improves wellbeing”", href: HERE, time: "10:02" }),
          listRow({ person: personMark(["Ben Okafor"]), title: "Ben added a note to “Rush hour is back in Rivermouth”", href: HERE, time: "09:15" })),
        fold({ sm: true }, "Seen before: 12 changes", listGroup("Yesterday",
          listRow({ person: personMark(["Anna de Vries"]), title: "Anna renamed the theme “Commuting”", href: HERE, time: "16:40" }))))),
      sample("Background work you steer: Sync now, queued with Cancel, Pause, how often; a setting on because of a colleague",
        h("div", { class: "stack" },
          h("div", { class: "btn-row" }, button({ sm: true, icon: "refresh" }, "Sync now"), workState("waiting", "Queued: starts when Read the documents has finished"),
            button({ kind: "quiet", sm: true }, "Cancel")),
          h("div", { class: "btn-row" }, button({ kind: "quiet", sm: true, icon: "pause" }, "Pause this project"), button({ kind: "quiet", sm: true, icon: "pause" }, "Pause all projects"),
            workState("paused", "Paused: nothing is synced until you go on")),
          field("Sync", select({}, ["Every 5 minutes", "Every 15 minutes", "Every hour", "Only when I press Sync now"].map((t) => h("option", {}, t)))),
          switchControl("Keep documents marked Only a local AI or No AI out of the shared folder", true, { disabled: true,
            help: [personMark(["Ben Okafor"]), " On because of Ben: Ben's copy keeps these documents out, so the shared folder does for everyone. Ask Ben to turn it off."] }))),
      sample("Roles on a person row: the Owner's More menu on another person's row; a Co-owner on an old ENLENS; the owner has gone; no owner yet", h("div", { class: "dz-block team-people" },
        listGroup("People in this project",
          listRow({ person: personMark(["Sam Ortiz"], { role: "Owner" }), title: "Sam Ortiz (you)", sub: "you last sent work 2 minutes ago" }),
          listRow({ person: personMark(["Sam Ortiz (laptop)"], { role: "Co-owner" }), title: "Sam Ortiz (laptop)", sub: "Also you: the same person · last sent work yesterday",
            actions: [menu({ label: "More for Sam Ortiz (laptop)", items: [{ text: "Make a Member again…", icon: "user" }, { text: "Same person as…", icon: "users" }, "sep", { text: "Make owner…", icon: "shield" }] })] }),
          listRow({ person: personMark(["Anna de Vries"], { role: "Co-owner" }), title: "Anna de Vries", sub: "needs a newer ENLENS to act as Co-owner", warn: true,
            actions: [menu({ label: "More for Anna de Vries", items: [{ text: "Make a Member again…", icon: "user" }, { text: "Same person as…", icon: "users" }, "sep", { text: "Make owner…", icon: "shield" }] })] }),
          listRow({ person: personMark(["Ben Okafor"]), title: "Ben Okafor", sub: "last sent work 3 days ago",
            actions: [menu({ label: "More for Ben Okafor", items: [{ text: "Make a Co-owner…", icon: "users" }, { text: "Same person as…", icon: "users" }, "sep", { text: "Make owner…", icon: "shield" }] })] })),
        listGroup("People in another project, whose owner has gone",
          listRow({ person: personMark(["Cleo Ma"], { role: "Owner" }), title: "Cleo Ma", sub: "Has not synced for 40 days: the owner has gone", warn: true,
            actions: [button({ sm: true }, "Take over…")] }),
          listRow({ person: personMark(["Sam Ortiz"]), title: "Sam Ortiz (you)", sub: "you last sent work today" })),
        h("div", { class: "btn-row" }, button({ sm: true }, "Become the owner"), h("span", { class: "muted small" }, "in a project that has no owner yet")))),
      sample("Waiting for your word: a question that is not a proposal is a decision card (decisionCard()); a proposal answered both ways keeps its card, with an error notice and two even buttons",
        h("div", { class: "dz-block" }, h("ul", { class: "owner-cards" },
          proposalCard({ what: "Remove “Jobs in the coal regions” from the project", severity: "high", person: personMark(["Carol Smit"], { name: "short", prefix: "Proposed by" }), time: "11 Nov",
            reason: "It is a blog post, not a source.", even: true, onAccept: noop, onDecline: noop,
            detail: notice({ kind: "error", live: false, class: "owner-line owner-both" },
              h("p", {}, h("strong", {}, "Answered both ways."), " Ben accepted it and Anna (laptop) declined it, neither knowing the other’s answer."),
              h("p", {}, "Neither answer counts: ", h("em", {}, "the document stays in the project"), ". Decide it again.")) }),
          decisionCard({ what: "Ben took the project over", flag: "A take-over", person: personMark(["Ben Okafor"], { name: "short" }), time: "08:55",
            said: "Nothing was heard of the owner for 14 days.", body: h("p", { class: "owner-line" }, "You follow Anna. If you follow Ben, Ben decides about the documents from now on."),
            actions: [button({ sm: true }, "Follow Ben"), button({ kind: "quiet", sm: true }, "Not now")] }),
          decisionCard({ what: "Ben lets more AI read 2 documents", flag: "More AI", person: personMark(["Ben Okafor"], { name: "short", role: "Co-owner" }), time: "10:12",
            body: [h("p", { class: "owner-line" }, "Here they stay as they are until you say."),
              h("ul", { class: "owner-ticks" }, ["Interview with a plant manager", "Grid operator annual report 2024"].map((t, i) => h("li", {},
                h("label", { class: "owner-check" }, h("input", { type: "checkbox", checked: i === 0 }), h("span", { class: "owner-check-text" }, h("span", { class: "serif" }, t),
                  h("span", { class: "owner-levels" }, h("span", { class: "muted small" }, "Here:"), tag({ icon: i ? "eye-off" : "house" }, i ? "No AI" : "Only a local AI"),
                    h("span", { class: "muted small" }, "Ben’s:"), tag({ icon: i ? "house" : "cloud" }, i ? "Only a local AI" : "Claude may read it")))))))],
            actions: [button({ sm: true }, "Allow here for 1 document"), button({ kind: "quiet", sm: true }, "Keep 1 stricter here")],
            ai: aiWhere("Once allowed, Claude may read the excerpts of those Ben lets Claude read, and only the AI on this computer the others.", "cloud") })),
        listGroup("Settled at the same time (1)",
          listRow({ person: personMark(["you", "Ben Okafor"]), title: "Works council minutes, May", href: HERE, serif: true,
            sub: "You and Ben changed who may read it with AI at the same time. The stricter holds: No AI.", actions: [button({ kind: "quiet", sm: true }, "Leave it so")] })))),
      sample("Problems with the shared folder, one notice each", noticeList([
        { kind: "attention", text: "The shared folder cannot be reached: is the drive connected, or are you offline?" },
        { kind: "info", person: personMark(["Anna de Vries"]), text: "Anna's changes are still arriving: try again in a few minutes." },
        { kind: "error", text: "The last round of syncing did not finish.", action: button({ sm: true }, "Try again") },
        { kind: "attention", person: personMark(["Ben Okafor"]), text: "Ben's copy needs a newer ENLENS." }])),
      sample("Proposals in full: grouped as waiting, decided and taken back; the owner's side and the proposer's",
        h("div", { class: "dz-block" },
          switchControl("Accept added documents at once", false, { help: "Documents a collaborator adds join the project without a proposal. Other changes still wait for you." }),
          listGroup("Waiting",
            proposalCard({ what: "Merge “Loneliness” into “Isolation”", person: personMark(["Anna de Vries"], { name: "short" }), time: "Today 10:02", severity: "medium",
              reason: "They are coded on the same passages in every interview.", onAccept: noop, onDecline: noop }),
            proposalCard({ what: "Rename the theme “Commuting”", person: personMark(["you"], { name: "short" }), time: "Today 09:30", severity: "low", side: "proposer",
              reason: "Two of its passages are about business travel.", onTakeBack: noop })),
          listGroup("Decided",
            proposalCard({ what: "Remove the code “Other”", person: personMark(["you"], { name: "short" }), time: "Yesterday", severity: "high", side: "proposer", state: "declined",
              declined: "the codebook is shared with another study" })),
          listGroup("Taken back",
            proposalCard({ what: "Add the document “Annual report 2024”", person: personMark(["Ben Okafor"], { name: "short" }), time: "Monday", severity: "low", state: "taken-back" })))),
      sample("A medium change with a longer reason: the severity stays at the head's right, the reason wraps under who and when",
        h("div", { class: "dz-block" }, listGroup("Waiting",
          proposalCard({ what: "Split the code “Wellbeing” in two", person: personMark(["Ben Okafor"], { name: "short" }), time: "Today 11:40", severity: "medium",
            reason: "Half of its passages are about sleep and exercise, the other half about stress at work.", onAccept: noop, onDecline: noop })))),
      sample("An item's proposal state in a list, and a move that waits for its person", h("div", { class: "dz-block" },
        listGroup("Documents",
          listRow({ title: "Commuting less, emitting less?", serif: true, href: HERE, sub: [workState("waiting", "Proposed: waiting for the owner"), " · ", link({ kind: "jump", onClick: noop }, "See the proposal")] }),
          listRow({ title: "Annual report 2024", serif: true, href: HERE, sub: [workState("ended", "Declined by the owner"), " · ", link({ kind: "jump", onClick: noop }, "See why")] }),
          listRow({ title: "Rush hour is back in Rivermouth", serif: true, href: HERE, sub: "2 results would not find their place", warn: true, actions: [button({ sm: true }, "Move it anyway…")] })),
        noticeList([{ kind: "attention", person: personMark(["Anna de Vries"]), text: "Moving “Rush hour is back in Rivermouth” waits for Anna: 2 of Anna's results would not find their place.",
          action: h("div", { class: "btn-row" }, button({ sm: true }, "Move it anyway…")) }]))),
      sample("Two versions of one item", h("p", { class: "muted small" }, "A comparison: section 4.27.")),
      sample("A report, a warning before an action, a refusal",
        notice({ kind: "done" }, h("p", {}, "12 changes came in from Anna."), fold({ sm: true }, "What came in", h("p", { class: "small" }, "3 judgements, 2 notes, 7 log entries."))),
        notice({ kind: "attention" }, h("p", {}, "Unsharing takes your work out of the shared folder for everyone.")),
        notice({ kind: "error", live: false }, h("p", {}, "Only the owner can remove a shared codebook."))),
      sample("Two downloads for two audiences", downloadLinks([{ text: "For your colleagues (.zip)", onClick: noop }, { text: "To move to another computer (.zip)", onClick: noop }]))),
  ];

  page.append(
    pageHead("Design reference", {
      eyebrow: "For whoever changes or reviews the interface",
      sub: "Every element of the interface, drawn by the helpers the pages use, one section per section of docs/DESIGN.md and in its order. Look at it in the light and the dark theme.",
    }),
    // the sections by the guide's numbers: moves on this page
    h("nav", { class: "dz-toc", "aria-label": "The sections of the design guide" },
      sections.map((s) => link({ kind: "jump", onClick: () => s.scrollIntoView() }, s.querySelector("h2").textContent))),
    ...sections);
}
