// Entry point: boots the shell, routes the hash, keeps the sidebar (project, jobs, privacy, theme) current.
import { App, api, h, icon, replace, clear, toast, showError, store, navigate, parseQuery, onJobsChanged, fmt, TERMINAL, confirmDialog, P, copyLine, watchJob, startClaude } from "./lib.js";
import { FEATURES, aiTag } from "./features.js";
import { renderCheck } from "./views/check.js";
import { renderResult } from "./views/result.js";
import { renderHistory } from "./views/history.js";
import { renderBatch } from "./views/batch.js";
import { renderSources, renderDocument } from "./views/sources.js";
import { renderSettings } from "./views/settings.js";
import { renderSetup } from "./views/setup.js";
import { renderProjects, newProjectDialog } from "./views/projects.js";
import { renderMap } from "./views/map.js";
import { renderSearch } from "./views/search.js";
import { renderProfile } from "./views/profile.js";
import { renderConcepts, renderConcept } from "./views/concepts.js";
import { renderThemes, renderThemeRun, renderTheme } from "./views/themes.js";
import { quickLookBanner } from "./views/quicklook.js";
import { renderOverview } from "./views/overview.js";

const ROUTES = [
  [/^\/?$/, "overview", renderOverview],
  [/^\/overview$/, "overview", renderOverview],
  [/^\/check$/, "check", renderCheck],
  [/^\/h\/([^/]+)$/, "history", renderResult],
  [/^\/history$/, "history", renderHistory],
  [/^\/map$/, "history", renderMap],
  [/^\/batch$/, "batch", renderBatch],
  [/^\/sources$/, "sources", renderSources],
  [/^\/doc\/([^/]+)$/, "sources", renderDocument],
  [/^\/settings(?:\/([^/]+))?$/, "settings", renderSettings],
  [/^\/setup$/, "", renderSetup],
  [/^\/projects$/, "", renderProjects],
  // 0.7: explore the documents
  [/^\/search$/, "search", renderSearch],
  [/^\/profile$/, "profile", renderProfile],
  [/^\/concepts$/, "concepts", renderConcepts],
  [/^\/concepts\/([^/]+)$/, "concepts", renderConcept],
  [/^\/themes$/, "themes", renderThemes],
  [/^\/themes\/([^/]+)$/, "themes", renderThemeRun],
  [/^\/themes\/([^/]+)\/([^/]+)$/, "themes", renderTheme],
];

let cleanup = null;
let lastHash = null;
let renderSeq = 0;

async function route() {
  const hash = location.hash.replace(/^#/, "") || "/overview";
  const [pathPart, qs] = hash.split("?");
  const query = parseQuery(qs);
  const view = document.getElementById("view");
  if (!App.state) {
    try { await App.refresh(); } catch (e) { replace(view, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, e.message))); return; }
  }
  // First run: no project yet -> the setup pages.
  const noProject = !App.state.projects.length;
  if (noProject && !/^\/(setup|settings|projects)/.test(pathPart)) { navigate("#/setup"); return; }
  if (!noProject && !App.project && !/^\/(setup|settings|projects)/.test(pathPart)) {
    // projects exist but none is current: pick the first
    try { await api("PUT", "/api/settings", { project: App.state.projects[0].name }); await App.refresh(); } catch (e) { showError(e); }
  }
  let match = null, nav = "", render = null;
  for (const [rx, n, r] of ROUTES) {
    const m = rx.exec(pathPart);
    if (m) { match = m; nav = n; render = r; break; }
  }
  if (cleanup) { try { cleanup(); } catch (e) { console.error(e); } cleanup = null; }
  setNav(nav);
  closeDrawer();
  for (const d of document.querySelectorAll("#project-switch details[open], #jobs-indicator details[open], #queue-indicator details[open]")) d.open = false;
  document.title = `${{ overview: "Overview", check: "Check a hypothesis", history: "Results", batch: "Check several", sources: "Documents", settings: "Settings", search: "Search", profile: "Profile", concepts: "Concepts", themes: "Themes" }[nav] || "ENLENS"} · ENLENS`;
  quickLookBanner(document.getElementById("quicklook-banner"));
  // Each page renders into its own container: a render still in flight when the hash changes again writes into a
  // detached element and cannot disturb the new page.
  const seq = ++renderSeq;
  const page = h("div", { class: "page" });
  replace(view, page);
  view.setAttribute("aria-busy", "true");
  if (!render) {
    replace(page, h("div", { class: "empty" }, icon("search-x", { size: 28 }), h("h3", {}, "No such page"), h("p", {}, "The address does not match a page of the app."), h("a", { class: "btn", href: "#/overview" }, "Go to the overview")));
    view.setAttribute("aria-busy", "false");
    return;
  }
  const params = match.slice(1).map((x) => (x === undefined ? undefined : decodeURIComponent(x)));
  try {
    const r = await render(page, params, query);
    if (seq !== renderSeq) { if (typeof r === "function") r(); return; }
    if (typeof r === "function") cleanup = r;
  } catch (e) {
    if (seq !== renderSeq) return;
    console.error(e);
    replace(page, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("div", {}, h("p", {}, e.message || String(e)),
      e.kind === "backend" ? h("a", { href: "#/settings" }, "Open Settings") : null)));
  }
  view.setAttribute("aria-busy", "false");
  // Focus the page title on navigation (not on the first load).
  if (lastHash !== null && lastHash !== hash) {
    const t = document.getElementById("page-title");
    if (t) t.focus({ preventScroll: false });
    window.scrollTo(0, 0);
  }
  lastHash = hash;
}

function setNav(name) {
  // 0.10.1: Settings sits at the foot of the sidebar, with Theme and Quit, outside the list of features
  for (const a of document.querySelectorAll("#nav a, #nav-foot a")) {
    if (a.dataset.route === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
}

// ---------------------------------------------------------------------------------------------
// sidebar
// ---------------------------------------------------------------------------------------------
function renderProjectSwitch() {
  const box = document.getElementById("project-switch");
  const projects = App.state.projects || [];
  const current = projects.find((p) => p.name === App.project);
  const top = document.getElementById("topbar-project");
  top.textContent = current ? current.name : ""; top.title = current ? current.name : "";
  const details = h("details");
  const summary = h("summary", { "aria-label": "Project: " + (current ? current.name : "none"), title: current ? current.name : "" },
    icon("folder", { size: 16 }),
    h("span", { class: "ps-name" }, h("span", { class: "ps-label" }, "Project"), h("span", { class: "ps-name-text" }, current ? current.name : "No project")),
    icon("chevron-down", { size: 14 }));
  const menu = h("div", { class: "ps-menu", role: "menu" });
  for (const p of projects) {
    const item = h("button", { class: "ps-item", type: "button", role: "menuitem", "aria-current": p.name === App.project ? "true" : null,
      onClick: () => switchProject(p.name) },
      icon(p.linked ? "link" : "folder", { size: 14 }),
      h("span", { class: "ps-text" }, p.name),
      h("span", { class: "ps-meta" }, `${p.documents} doc${p.documents === 1 ? "" : "s"} · ${p.hypotheses} result${p.hypotheses === 1 ? "" : "s"}`));
    if (!p.ok) item.title = "This project could not be opened.";
    menu.appendChild(item);
  }
  if (projects.length) menu.appendChild(h("div", { class: "ps-sep" }));
  menu.appendChild(h("button", { class: "ps-item", type: "button", role: "menuitem", onClick: () => { details.open = false; newProjectDialog(); } }, icon("plus", { size: 14 }), h("span", { class: "ps-text" }, "New project…")));
  menu.appendChild(h("a", { class: "ps-item", href: "#/projects", role: "menuitem" }, icon("sliders", { size: 14 }), h("span", { class: "ps-text" }, "Manage projects")));
  details.append(summary, menu);
  replace(box, details);
  details.addEventListener("keydown", (e) => { if (e.key === "Escape") { details.open = false; summary.focus(); } });
}

// One document-level listener closes any open sidebar popover on an outside click.
document.addEventListener("click", (e) => {
  for (const d of document.querySelectorAll("#project-switch details[open], #jobs-indicator details[open], #queue-indicator details[open]")) {
    if (!d.contains(e.target)) d.open = false;
  }
});

export async function switchProject(name) {
  if (name === App.project) return;
  try {
    await api("PUT", "/api/settings", { project: name });
    await App.refresh();
    toast(`Project: ${name}`, "ok", { ttl: 2000 });
    if (/^#\/(h|doc|themes|concepts)\//.test(location.hash)) navigate("#/overview"); else route();
  } catch (e) { showError(e); }
}

function renderPrivacy() {
  const box = document.getElementById("privacy-indicator");
  const p = App.privacy();
  const a = h("a", { class: `privacy privacy-${p.where}${App.settings().backend === "claude_code" ? " privacy-plan" : ""}`, href: "#/settings", title: `${p.plain} AI model: ${p.detail}. Change it in Settings.` },
    icon(p.icon, { size: 16 }),
    h("div", {}, h("strong", {}, p.label), h("span", {}, p.short || p.plain)));
  replace(box, a);
}

let jobsTimer = null;
let jobsBusy = false, jobsAgain = false;
async function renderJobs() {
  if (jobsBusy) { jobsAgain = true; return; }
  jobsBusy = true;
  try { await drawJobs(); } finally { jobsBusy = false; }
  if (jobsAgain) { jobsAgain = false; renderJobs(); }
}
async function drawJobs() {
  const box = document.getElementById("jobs-indicator");
  let jobs = [];
  try { jobs = (await api("GET", "/api/jobs")).jobs || []; } catch (_) { return; }
  const active = jobs.filter((j) => !TERMINAL.has(j.state));
  const recent = jobs.filter((j) => TERMINAL.has(j.state)).slice(0, 5);
  box.hidden = !active.length && !recent.length;  // 0.9: nothing to show yet: no empty box in the sidebar
  const details = h("details", { class: "jobs " + (active.length ? "jobs-active" : "jobs-idle") });
  const summary = h("summary", {}, active.length ? h("span", { class: "running-dot", "aria-hidden": "true" }) : icon("clock", { size: 14 }),
    h("span", { class: "grow" }, active.length ? `${active.length} ${active.length === 1 ? "task" : "tasks"} running` : "Nothing running"), icon("chevron-up", { size: 14 }));
  const menu = h("div", { class: "ps-menu" });
  const linkFor = (j) => ({ check: "#/check", prepare: "#/check", batch: "#/batch", more: "#/history", reread: "#/history", "read-new": "#/history", "second-opinion": "#/history", ingest: "#/sources", index: "#/sources", benchmark: "#/settings/test",
    keywords: "#/profile", label: "#/profile", "label-compare": "#/profile", terms: "#/concepts", link: "#/concepts", wordings: "#/concepts", themes: "#/themes", "theme-names": "#/themes", resolve: "#/sources", quicklook: "#/sources", "claude-install": "#/settings/model" }[j.kind] || "#/check");
  const kindIcon = { check: "flask", prepare: "eye", batch: "list-checks", more: "search", reread: "refresh", "read-new": "book-open", "second-opinion": "cpu", ingest: "upload", index: "sparkles", benchmark: "cpu",
    keywords: "tag", label: "tag", "label-compare": "scale", terms: "network", link: "network", wordings: "network", themes: "shapes", "theme-names": "shapes", resolve: "link", quicklook: "eye", "claude-install": "download" };
  const kindText = { check: "Check", prepare: "Look before checking", batch: "Several hypotheses", more: "More evidence", reread: "Reading an excerpt again", "read-new": "Reading the new documents", "second-opinion": "Second AI model", ingest: "Adding documents", index: "Search by meaning set-up", benchmark: "Model test",
    keywords: "Codes by keywords", label: "The AI labels passages", "label-compare": "Comparing labels", terms: "Building the glossary", link: "The AI relates concepts", wordings: "Other wordings", themes: "Finding themes", "theme-names": "Naming themes", resolve: "Following references", quicklook: "Quick look", "claude-install": "Installing Claude Code" };
  const withJob = new Set(["check", "batch", "more", "read-new", "second-opinion"]);
  const row = (j) => h("a", { class: "job-row", href: linkFor(j) + (withJob.has(j.kind) ? `?job=${encodeURIComponent(j.id)}` : ""), title: ["check", "prepare", "batch"].includes(j.kind) ? (j.title || "") : null },
    icon(kindIcon[j.kind] || "circle", { size: 14 }),
    h("span", { class: "job-title" }, j.kind === "check" ? (j.title || "Check") : j.kind === "prepare" ? `${kindText.prepare}${j.title ? ` (${j.title})` : ""}` : j.kind === "read-new" ? (j.title || kindText["read-new"]) : j.kind === "second-opinion" ? `${kindText["second-opinion"]}${/ on (\d+ hypothes\w+)$/.test(j.title || "") ? ` (${/ on (\d+ hypothes\w+)$/.exec(j.title)[1]})` : ""}` : `${kindText[j.kind] || j.kind}${j.kind === "batch" && j.title ? ` (${j.title})` : ""}`),
    h("span", { class: "job-state" }, j.state === "running" ? `running · ${fmt.secs(j.seconds)}` : j.state === "queued" ? "waiting its turn" : j.state === "done" ? "done" : j.state === "error" ? "did not work" : "stopped"));
  if (!active.length && !recent.length) menu.appendChild(h("div", { class: "muted small", style: { padding: "6px 8px" } }, "Work that takes a while (checks, adding documents) shows up here, so you can move around the app and come back to it."));
  active.forEach((j) => menu.appendChild(row(j)));
  if (active.length && recent.length) menu.appendChild(h("div", { class: "ps-sep" }));
  if (recent.length) menu.appendChild(h("div", { class: "muted small", style: { padding: "2px 8px" } }, "Recent"));
  recent.forEach((j) => menu.appendChild(row(j)));
  details.append(summary, menu);
  const old = box.querySelector("details");
  if (old && old.open) details.open = true;
  replace(box, details);
  clearTimeout(jobsTimer);
  if (active.length) jobsTimer = setTimeout(renderJobs, 2000);
}

// ---------------------------------------------------------------------------------------------
// 0.8: the queue panel: what waits for Claude Code in the current project
// ---------------------------------------------------------------------------------------------
let queueTimer = null;
let queueBusy = false;
async function renderQueue() {
  if (queueBusy) return;
  queueBusy = true;
  try { await drawQueue(); } finally { queueBusy = false; }
}
async function drawQueue() {
  const box = document.getElementById("queue-indicator");
  clearTimeout(queueTimer);
  const s = App.settings();
  const summary = (App.state && App.state.queue) || {};
  if (!App.project || (s.backend !== "claude_code" && !summary.waiting)) { box.hidden = true; replace(box); return; }
  let q;
  try { q = await api("GET", `/api/projects/${P(App.project)}/queue`); } catch (_) { return; }
  if (!q.waiting && !q.being_answered && !(q.runner && q.runner.running)) {
    box.hidden = true; replace(box);
    if (s.backend === "claude_code") queueTimer = setTimeout(renderQueue, 15000);
    return;
  }
  box.hidden = false;
  const old = box.querySelector("details");
  const details = h("details", { class: "jobs queue-panel " + (q.waiting ? "jobs-active" : "jobs-idle") });
  if (old && old.open) details.open = true;
  const head = q.runner && q.runner.running ? `Claude Code is working: ${(q.waiting + q.being_answered).toLocaleString()} to go`
    : q.waiting ? (q.paused ? `Paused: ${q.waiting.toLocaleString()} waiting` : `${(q.waiting + q.being_answered).toLocaleString()} waiting for Claude Code`)
    : q.being_answered ? `Claude Code is answering ${q.being_answered}` : "Queue for Claude Code: empty";
  details.appendChild(h("summary", {}, icon(q.paused ? "pause" : "inbox", { size: 14 }), h("span", { class: "grow" }, head), icon("chevron-up", { size: 14 })));
  const menu = h("div", { class: "ps-menu queue-menu" });
  menu.appendChild(h("div", { class: "muted small qp-privacy" }, icon("cloud", { size: 12 }), " ", q.privacy));
  if (q.paused && q.paused_text) menu.appendChild(h("p", { class: "small qp-paused" }, q.paused_text));
  const act = async (kind, action) => {
    try { await api("POST", `/api/projects/${P(App.project)}/queue/order`, { kind, action }); renderQueue(); } catch (e) { showError(e); }
  };
  const remove = async (k) => {
    const ok = await confirmDialog({ title: `Take the ${k.title.toLowerCase()} out of the queue?`, message: `The ${k.waiting.toLocaleString()} tasks no session has taken yet are removed${["check", "expand", "decompose"].includes(k.kind) ? ", and the checks still waiting are removed whole (as a stopped check)" : ""}. Answers already stored stay.`, confirmText: "Remove" });
    if (!ok) return;
    try { const r = await api("POST", `/api/projects/${P(App.project)}/queue/withdraw`, { kind: k.kind }); toast(`${r.withdrawn} tasks taken out of the queue.`, "ok"); App.refresh().catch(() => {}); renderQueue(); } catch (e) { showError(e); }
  };
  const kinds = q.kinds.filter((k) => k.waiting || k.being_answered);
  if (!kinds.length) menu.appendChild(h("p", { class: "muted small", style: { padding: "4px 8px" } }, "Nothing waits. Press an AI button (a check, Label with the AI, Name the themes…): its work waits here for Claude Code."));
  for (const k of kinds) {
    menu.appendChild(h("div", { class: "qp-row" + (k.held ? " qp-held" : "") },
      h("div", { class: "qp-title" }, h("strong", {}, k.title), k.held ? h("span", { class: "chip" }, "held") : null),
      h("div", { class: "muted small" }, `${k.waiting.toLocaleString()} waiting${k.being_answered ? ` · ${k.being_answered} being answered` : ""}${k.done ? ` · ${k.done.toLocaleString()} done` : ""}${k.stronger_model ? ` · ${k.stronger_model} for a stronger model` : ""}`),
      h("div", { class: "muted small" }, [k.helper ? `${k.helper} on ${k.model}` : k.model ? `on ${k.model}` : "", k.estimate ? ` · ${k.estimate}` : ""].join("")),
      h("div", { class: "qp-actions" },
        q.order[0] !== k.kind ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => act(k.kind, "first") }, icon("arrow-up", { size: 12 }), "Do first") : null,
        h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => act(k.kind, k.held ? "go" : "hold") }, icon(k.held ? "play" : "pause", { size: 12 }), k.held ? "Go on" : "Hold"),
        h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => remove(k) }, icon("trash", { size: 12 }), "Remove"))));
  }
  if (kinds.length) {
    menu.appendChild(h("div", { style: { padding: "6px 8px 0" } }, startClaude(App.project, { command: q.command })));
    if (s.backend !== "claude_code") {
      menu.appendChild(h("div", { style: { padding: "6px 8px" } }, h("button", { class: "btn btn-sm", type: "button", onClick: async () => {
        try { const r = await api("POST", `/api/projects/${P(App.project)}/queue/run`, {}); toast("The AI model of Settings answers the queue now.", "ok"); watchJob(r.job.id, () => {}).promise.then(() => renderQueue()); } catch (e) { showError(e); }
      } }, icon("play", { size: 13 }), "Answer them here instead"), h("div", { class: "muted small" }, `with ${App.state.backend_label}`)));
    }
  }
  details.appendChild(menu);
  replace(box, details);
  if (q.waiting || q.being_answered || s.backend === "claude_code") queueTimer = setTimeout(renderQueue, q.waiting || q.being_answered ? 5000 : 15000);
}

function themeInit() {
  const btn = document.getElementById("theme-btn");
  const apply = (mode) => {
    if (mode === "light" || mode === "dark") document.documentElement.setAttribute("data-theme", mode);
    else document.documentElement.removeAttribute("data-theme");
    const names = { system: ["monitor", "Theme: system"], light: ["sun", "Theme: light"], dark: ["moon", "Theme: dark"] };
    const [ic, label] = names[mode] || names.system;
    replace(btn, icon(ic, { size: 15 }), h("span", {}, label));
    btn.setAttribute("aria-label", label + ". Change theme");
  };
  let mode = store("theme") || "system";
  apply(mode);
  btn.addEventListener("click", () => {
    mode = mode === "system" ? "light" : mode === "light" ? "dark" : "system";
    store("theme", mode === "system" ? null : mode);
    apply(mode);
  });
}

// "Quit ENLENS": stops the app (started from the ENLENS icon, there is no terminal to close)
function quitInit() {
  const btn = document.getElementById("quit-btn");
  if (!btn || !App.state || !App.state.can_quit) return;
  replace(btn, icon("power", { size: 15 }), h("span", {}, "Quit ENLENS"));
  btn.hidden = false;
  btn.addEventListener("click", async () => {
    const running = (App.state.jobs || []).length || (await api("GET", "/api/jobs").then((r) => r.jobs.filter((j) => !TERMINAL.has(j.state)).length).catch(() => 0));
    const ok = await confirmDialog({
      title: "Quit ENLENS?",
      message: running
        ? "Something is still running (a check, or documents being added). Quitting stops it; a check that is stopped leaves nothing behind. Your projects and results are kept."
        : "ENLENS stops on this computer. Your projects and results are kept.",
      confirmText: "Quit ENLENS", danger: !!running,
    });
    if (!ok) return;
    try { await api("POST", "/api/quit", {}); } catch (e) { showError(e); return; }
    const again = App.state.launcher
      ? "To open it again, double-click the ENLENS icon (on your Desktop, or in Applications)."
      : "To open it again, start it the way you started it before (for example with enlens-gui).";
    document.title = "ENLENS has stopped";
    replace(document.body, h("main", { class: "stopped-page", id: "main" },
      h("img", { src: "/static/logo.svg", alt: "", width: 48, height: 48 }),
      h("h1", {}, "ENLENS has stopped"),
      h("p", {}, "You can close this tab. Your projects and results are kept."),
      h("p", { class: "muted" }, again)));
  });
}

function closeDrawer() {
  const sb = document.getElementById("sidebar");
  const sc = document.getElementById("scrim");
  const mb = document.getElementById("menu-btn");
  sb.classList.remove("open");
  sc.hidden = true;
  mb.setAttribute("aria-expanded", "false");
}

function drawerInit() {
  const sb = document.getElementById("sidebar");
  const sc = document.getElementById("scrim");
  const mb = document.getElementById("menu-btn");
  replace(mb, icon("menu", { size: 20 }));
  mb.addEventListener("click", () => {
    const open = !sb.classList.contains("open");
    sb.classList.toggle("open", open);
    sc.hidden = !open;
    mb.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) { const first = sb.querySelector("summary, a, button"); if (first) first.focus(); }
  });
  sc.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && sb.classList.contains("open")) { closeDrawer(); mb.focus(); } });
}

// 0.9: each feature in the sidebar shows whether it uses the AI: a filled "AI" mark (the AI does the work), a dashed
// one (works without it; the AI can add to it), none (never uses the AI). A legend under the list says so in words.
const AI_BADGE = {
  uses: ["AI", "Uses the AI"],
  optional: ["AI", "Works without the AI; the AI can add to it"],
  none: ["", "No AI needed"],
};
function navIcons() {
  for (const span of document.querySelectorAll(".nav-icon[data-icon]")) replace(span, icon(span.dataset.icon, { size: 18 }));
  for (const a of document.querySelectorAll("#nav a[data-route]")) {
    const f = FEATURES[a.dataset.route];
    if (!f) continue;
    const [text, plain] = AI_BADGE[f.ai] || AI_BADGE.none;
    a.title = `${f.what} ${plain}.`;
    if (text) a.appendChild(h("span", { class: `nav-ai nav-ai-${f.ai}`, title: plain }, h("span", { "aria-hidden": "true" }, "AI"), h("span", { class: "visually-hidden" }, ` (${plain})`)));
    else a.appendChild(h("span", { class: "visually-hidden" }, ` (${plain})`));
  }
  const nav = document.getElementById("nav");
  if (nav && !nav.querySelector(".nav-legend")) {
    nav.insertBefore(h("div", { class: "nav-legend", "aria-hidden": "true" },
      h("span", {}, h("span", { class: "nav-ai nav-ai-uses" }, "AI"), " needs AI"),
      h("span", {}, h("span", { class: "nav-ai nav-ai-optional" }, "AI"), " optional"),
      h("span", {}, "no mark: no AI")), null);
  }
}

async function boot() {
  themeInit();
  drawerInit();
  navIcons();
  App.onChange(() => { renderProjectSwitch(); renderPrivacy(); renderQueue(); });
  onJobsChanged(() => { renderJobs(); renderQueue(); });
  window.addEventListener("hashchange", route);
  try {
    await App.refresh();
  } catch (e) {
    replace(document.getElementById("view"), h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, e.message)));
    return;
  }
  renderJobs();
  quitInit();
  route();
  // keep the sidebar fresh when the window regains focus
  window.addEventListener("focus", () => { renderJobs(); renderQueue(); });
}

boot();
