// Entry point: boots the shell, routes the hash, keeps the sidebar (project, jobs, privacy, theme) current.
import { App, api, h, icon, Connection, replace, clear, toast, showError, store, navigate, parseQuery, onJobsChanged, fmt, TERMINAL, confirmDialog, P, watchJob, startClaude, claudeStatus, claudeSeenNow, rememberClaude, claudeAccount, brand, appName, Updates, checkUpdate, onUpdateSeen, UPDATE_EVERY } from "./lib.js";
import { FEATURES, SECTIONS } from "./features.js";
import { PAGE_ROUTES, applyExtensions, jobRow } from "./registry.js";
import localExtensions from "./extensions.js";
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
import { renderBibliography } from "./views/bibliography.js";
import { renderLog } from "./views/log.js";
import { renderNotes } from "./views/notes.js";
import { renderCodebooks, renderCodebook } from "./views/codebooks.js";

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
  [/^\/bibliography$/, "bibliography", renderBibliography],   // 0.13
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
  // 0.16: your own codebooks, notes and the research log
  [/^\/codebooks$/, "codebooks", renderCodebooks],
  [/^\/codebooks\/([^/]+)$/, "codebooks", renderCodebook],
  [/^\/notes$/, "annotations", renderNotes],
  [/^\/log$/, "researchlog", renderLog],
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
  for (const [rx, n, r] of [...ROUTES, ...PAGE_ROUTES]) {  // 0.13.6: an add-on's pages come after the core ones
    const m = rx.exec(pathPart);
    if (m) { match = m; nav = n; render = r; break; }
  }
  if (cleanup) { try { cleanup(); } catch (e) { console.error(e); } cleanup = null; }
  setNav(nav);
  closeDrawer();
  for (const d of document.querySelectorAll("#project-switch details[open], #jobs-indicator details[open], #queue-indicator details[open]")) d.open = false;
  const pageName = { overview: "Overview", check: "Check a hypothesis", history: "Results", batch: "Check several", sources: "Documents", settings: "Settings", search: "Search", profile: "Profile", concepts: "Concepts", themes: "Themes", codebooks: "Codebooks", annotations: "Notes", researchlog: "Research log" }[nav]
    || { "/setup": "Set up", "/projects": "Projects" }[pathPart] || (FEATURES[nav] && FEATURES[nav].title) || "";
  document.title = pageName ? `${pageName} · ${appName()}` : appName();
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
    if (/^#\/(h|doc|themes|concepts|codebooks)\//.test(location.hash)) navigate("#/overview"); else route();
  } catch (e) { showError(e); }
}

// 0.13.4: hovering the line (or reaching it with the keyboard) opens a small card with what the tooltip said and, on
// Claude Code, the account it is signed in to. Escape closes it; it stays open while the pointer is on it.
function renderPrivacy() {
  const box = document.getElementById("privacy-indicator");
  const p = App.privacy();
  const plan = App.settings().backend === "claude_code";
  const card = h("div", { class: "privacy-card", id: "privacy-card", role: "tooltip" });
  const a = h("a", { class: `privacy privacy-${p.where}${plan ? " privacy-plan" : ""}`, href: "#/settings", "aria-describedby": "privacy-card" },
    icon(p.icon, { size: 16 }),
    h("div", {}, h("strong", {}, p.label), h("span", {}, p.short || p.plain)));
  const wrap = h("div", { class: "privacy-wrap" }, a, card);
  const fill = () => replace(card,
    plan ? accountPart(claudeSeenNow()) : null,
    h("p", {}, p.plain),
    plan ? null : h("p", { class: "privacy-card-muted" }, `AI model: ${p.detail}`),
    h("p", { class: "privacy-card-muted" }, "Change it in Settings."));
  fill();
  if (plan) {
    const ask = () => claudeStatus().then(() => { if (card.isConnected) fill(); }).catch(() => {
      if (!claudeSeenNow()) { rememberClaude({ unknown: true }); fill(); }
    });
    ask();  // the card is ready before the first hover; a hover a minute later asks again
    wrap.addEventListener("mouseenter", ask);
    a.addEventListener("focus", ask);
  }
  const quiet = (on) => wrap.classList.toggle("privacy-quiet", on);
  a.addEventListener("keydown", (e) => { if (e.key === "Escape") quiet(true); });
  wrap.addEventListener("mouseleave", () => quiet(false));
  a.addEventListener("blur", () => quiet(false));
  replace(box, wrap);
}

// Which account Claude Code uses, for the card: what it says, or what is still to set up.
function accountPart(st) {
  const acc = claudeAccount(st);
  if (acc) {
    return h("div", { class: "privacy-account" },
      h("span", { class: "privacy-card-muted" }, "Signed in to Claude Code as"),
      h("strong", {}, acc.email || "an account it does not name"),
      acc.plan ? h("span", { class: "privacy-card-muted" }, acc.plan + (acc.org ? ` · ${acc.org}` : "")) : null);
  }
  const say = !st ? "Asking Claude Code which account it uses…"
    : st.unknown ? "Could not ask Claude Code which account it uses."
    : !st.found ? "Claude Code is not on this computer yet: Settings → AI sets it up."
    : st.signed_in === false ? "Claude Code is not signed in yet: Settings → AI signs you in."
    : "Claude Code does not say which account it is signed in to.";
  return h("div", { class: "privacy-account" }, h("span", {}, say));
}

// The jobs and queue panels open in place at the foot of the sidebar, which stays in the window (app.css): an open
// panel is always in view. (0.14.3 scrolled the sidebar to show it, when the foot could be below the window.)

// A wheel or touchpad turn over the sidebar never scrolls the page behind it: it scrolls the part of the sidebar under
// the pointer that can still move that way (the list of features, an open panel, the project menu), or nothing.
// (A box with nothing left to scroll hands the turn on to the page, and CSS alone cannot stop that everywhere.)
function sidebarScrollInit() {
  const sb = document.getElementById("sidebar");
  if (!sb) return;
  const canMove = (el, dy) => {
    if (el.scrollHeight <= el.clientHeight + 1) return false;
    const oy = getComputedStyle(el).overflowY;
    if (oy !== "auto" && oy !== "scroll") return false;
    return dy < 0 ? el.scrollTop > 0 : el.scrollTop + el.clientHeight < el.scrollHeight - 1;
  };
  sb.addEventListener("wheel", (e) => {
    if (e.ctrlKey || !e.deltaY) return;  // a pinch zooms the page; a sideways turn is left alone
    for (let el = e.target; el && el !== sb.parentElement; el = el.parentElement) {
      if (el.nodeType === 1 && canMove(el, e.deltaY)) return;
    }
    e.preventDefault();
  }, { passive: false });
}

let jobsTimer = null;
let jobsBusy = false, jobsAgain = false;
let jobsKey = "";  // 0.15.6: what the panel drawn last shows, all but the seconds
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
  const stateText = (j) => j.on_hold ? "not running"
    : j.state === "running" ? `running · ${fmt.secs(j.seconds)}` : j.state === "queued" ? "waiting its turn"
    : j.state === "done" ? "done" : j.state === "error" ? "did not work" : "stopped";
  // 0.15.6: while work runs the panel is drawn again every 2 s. When only the seconds changed, the rows stay and only
  // their times change: a new row under the pointer closed its tooltip (the whole name) as soon as it opened.
  const key = JSON.stringify([App.project, [...active, ...recent].map((j) => [j.id, j.kind, j.title, j.scope, j.project, j.state, !!j.on_hold])]);
  const old = box.querySelector("details");
  if (old && key === jobsKey) {
    old.querySelectorAll(".job-row[data-job]").forEach((r) => {
      const j = active.find((a) => a.id === r.dataset.job);
      const s = r.querySelector(".job-state");
      if (j && s && s.textContent !== stateText(j)) s.textContent = stateText(j);
    });
    clearTimeout(jobsTimer);
    if (active.length) jobsTimer = setTimeout(renderJobs, 2000);
    return;
  }
  // 0.12: work that waits for Claude Code with nothing answering it is not running: it says so, in its own colour,
  // with a still pause mark instead of the pulsing dot
  const hold = active.filter((j) => j.on_hold);
  const going = active.filter((j) => !j.on_hold);
  const tasks = (n) => `${n} ${n === 1 ? "task" : "tasks"}`;
  const details = h("details", { class: "jobs " + (going.length ? "jobs-active" : hold.length ? "jobs-hold" : "jobs-idle") });
  let head;
  if (going.length && hold.length) head = h("span", { class: "grow" }, `${going.length} running`, h("span", { class: "jobs-hold-part" }, ` · ${hold.length} not running`));
  else if (hold.length) head = h("span", { class: "grow jobs-hold-text" }, h("strong", {}, `${tasks(hold.length)} not running`), h("span", { class: "jobs-hold-sub" }, "Waiting for Claude Code to start"));
  else head = h("span", { class: "grow" }, active.length ? `${tasks(active.length)} running` : "Nothing running");
  const summary = h("summary", { title: hold.length ? "Nothing answers this work yet: start Claude Code (in the queue just below, or here) and it runs." : null },
    going.length ? h("span", { class: "running-dot", "aria-hidden": "true" }) : hold.length ? icon("pause", { size: 14 }) : icon("clock", { size: 14 }),
    head, icon("chevron-up", { size: 14 }));
  const menu = h("div", { class: "ps-menu" });
  // 0.13.6: each kind's link, icon and name are in registry.js (JOB_KINDS), where an add-on adds its own
  const row = (j) => {
    const v = jobRow(j);
    return h("a", { class: "job-row", href: v.href, title: v.tooltip, dataset: { job: j.id } }, icon(v.icon, { size: 14 }), h("span", { class: "job-title" }, v.text),
      h("span", { class: "job-state" + (j.on_hold ? " job-hold" : "") }, stateText(j)));
  };
  if (!active.length && !recent.length) menu.appendChild(h("div", { class: "muted small", style: { padding: "6px 8px" } }, "Work that takes a while (checks, adding documents) shows up here, so you can move around the app and come back to it."));
  if (hold.some((j) => j.project === App.project)) {
    menu.appendChild(h("div", { class: "jobs-hold-start" },
      h("p", { class: "small" }, icon("pause", { size: 12 }), " ", h("strong", {}, "Not running."), " This work waits in the queue until Claude Code answers it."),
      startClaude(App.project)));
  }
  active.forEach((j) => menu.appendChild(row(j)));
  if (active.length && recent.length) menu.appendChild(h("div", { class: "ps-sep" }));
  if (recent.length) menu.appendChild(h("div", { class: "muted small", style: { padding: "2px 8px" } }, "Recent"));
  recent.forEach((j) => menu.appendChild(row(j)));
  details.append(summary, menu);
  if (old && old.open) details.open = true;
  replace(box, details);
  jobsKey = key;
  clearTimeout(jobsTimer);
  if (active.length) jobsTimer = setTimeout(renderJobs, 2000);
}

// ---------------------------------------------------------------------------------------------
// 0.8: the queue panel: what waits for Claude Code in the current project
// ---------------------------------------------------------------------------------------------
let queueTimer = null;
let queueBusy = false;
let queueDefers = 0;  // 0.13.10: redraws put off while a list of the helpers' fold is open
let queueSoon = null;
// A job's end reaches this twice (App.refresh and jobsChanged): the calls of one moment are drawn once.
function renderQueue() {
  clearTimeout(queueSoon);
  queueSoon = setTimeout(drawQueueOnce, 50);
}
async function drawQueueOnce() {
  if (queueBusy) return;
  queueBusy = true;
  try { await drawQueue(); } finally { queueBusy = false; }
}
async function drawQueue() {
  const box = document.getElementById("queue-indicator");
  clearTimeout(queueTimer);
  // 0.13.10: not while the person has a list of "Choose the helpers for this run" open in the panel (it would close),
  // for this project, and for half a minute at most
  const el = document.activeElement;
  const sc = box.contains(el) && el.matches(".sc-helpers select") ? el.closest(".start-claude") : null;
  if (sc && sc.dataset.project === App.project && queueDefers < 6) { queueDefers += 1; queueTimer = setTimeout(renderQueue, 5000); return; }
  queueDefers = 0;
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
  const qSummary = h("summary", {}, icon(q.paused ? "pause" : "inbox", { size: 14 }), h("span", { class: "grow" }, head), icon("chevron-up", { size: 14 }));
  details.appendChild(qSummary);
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

// 0.14.2: the theme is a small icon beside Settings (it was a row of its own). The icon shows the theme in use;
// a click goes on to the next one, and the tooltip says which.
function themeInit() {
  const btn = document.getElementById("theme-btn");
  const apply = (mode) => {
    if (mode === "light" || mode === "dark") document.documentElement.setAttribute("data-theme", mode);
    else document.documentElement.removeAttribute("data-theme");
    const names = { system: ["monitor", "Theme: follows this computer", "Click for light."], light: ["sun", "Theme: light", "Click for dark."], dark: ["moon", "Theme: dark", "Click to follow this computer."] };
    const [ic, label, next] = names[mode] || names.system;
    replace(btn, icon(ic, { size: 17 }), h("span", { class: "visually-hidden" }, label));
    btn.title = `${label}. ${next}`;
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
  replace(btn, icon("power", { size: 15 }), h("span", {}, `Quit ${appName()}`));
  btn.hidden = false;
  btn.addEventListener("click", () => quitApp());
}

// 0.13.1, "Update ENLENS": installs the newest version (the latest GitHub release, or the branch a git copy follows)
// and restarts into it; the page reloads by itself once the new version answers.
// 0.13.6: the button shows only when there is something to install. The page looks when it opens and every two
// minutes (checkUpdate in lib.js); a new version also pops up once, in the corner. Without one, Settings → Technical
// has Check for updates. A failed look (offline, a git copy edited by hand) stays quiet here: Settings says why.
function updateInit() {
  const btn = document.getElementById("update-btn");
  Updates.install = () => updateApp(btn);
  if (!btn || !App.state || !App.state.can_restart) return;
  btn.addEventListener("click", () => updateApp(btn));
  onUpdateSeen((info) => showUpdate(btn, info));
  const look = () => checkUpdate().catch(() => {});
  look();
  setInterval(look, UPDATE_EVERY);
  // a computer that slept, or a tab left in the background, looks again when it is back in front
  document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - Updates.at > UPDATE_EVERY) look(); });
}

// what a look found: the button (with the version), and the pop-up once per version
function showUpdate(btn, info) {
  if (btn.disabled) return;  // updating now: the button says so
  if (!info || !info.available) { btn.hidden = true; return; }
  const to = info.latest ? `Update to ${info.latest}` : `Update ${appName()}`;
  const rc = info.candidate ? "release candidate " : "";
  replace(btn, icon("arrow-up", { size: 15 }), h("span", {}, to));
  btn.classList.add("update-ready");
  btn.title = info.on_disk ? `${appName()} ${info.latest} is installed: restart to use it`
    : info.latest ? `${appName()} ${rc}${info.latest} is ready (you have ${info.version})`
    : `${info.changes} new change${info.changes === 1 ? "" : "s"} for this copy of ${appName()}`;
  btn.hidden = false;
  if (!info.on_disk) updatePopup(info);  // a version already on disk has the banner above the page
}

// the pop-up: in the corner until it is answered. "Later" keeps it away for this version; the button stays.
function updatePopup(info) {
  const box = document.getElementById("toasts");
  const key = info.latest || `changes-${info.changes}`;
  if (!box || box.querySelector(".update-popup") || store("update-later") === key) return;
  if (document.querySelector(".release-note-problem")) return;  // 0.15.4: the note says what to do; the button stays
  const later = () => { store("update-later", key); t.remove(); };
  const t = h("div", { class: "toast toast-info update-popup", role: "status" }, icon("arrow-up"),
    h("div", { class: "toast-body" },
      h("div", {}, h("strong", {}, info.latest ? `${appName()} ${info.candidate ? "release candidate " : ""}${info.latest} is available.` : `An update for ${appName()} is available.`),
        ` You have ${info.version}. Updating restarts ${appName()}; your projects and results are kept.`,
        // 0.15: what a candidate is, said where it is offered
        info.candidate ? ` A release candidate is a try-out of the next version: use it on a project you do not share with colleagues.` : null),
      h("div", { class: "update-popup-actions" },
        h("button", { class: "btn btn-sm btn-primary", type: "button", onClick: () => { t.remove(); Updates.install(); } }, "Update and restart"),
        h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: later }, "Later"))),
    h("button", { class: "icon-btn", type: "button", "aria-label": "Later", onClick: later }, icon("x")));
  box.appendChild(t);
}

async function runningJobs() {
  return (App.state.jobs || []).length || (await api("GET", "/api/jobs").then((r) => r.jobs.filter((j) => !TERMINAL.has(j.state)).length).catch(() => 0));
}

const RUNNING_NOTE = "Something is still running (a check, or documents being added). Restarting stops it; a check that is stopped leaves nothing behind. ";

async function updateApp(btn) {
  if (btn.disabled) return;
  const label = btn.lastChild && btn.lastChild.textContent;
  btn.disabled = true;
  if (btn.lastChild) btn.lastChild.textContent = "Looking for updates…";
  let info;
  try { info = await checkUpdate(); } catch (e) { showError(e); return done(); }
  if (!info.available) { toast(`${appName()} ${info.version} is the newest version.`, "ok"); done(); btn.hidden = true; return; }
  const running = await runningJobs();
  const what = info.on_disk ? `${appName()} ${info.latest} is installed already; ${appName()} restarts to use it.`
    : info.latest ? `${appName()} ${info.candidate ? "release candidate " : ""}${info.latest} is ready (you have ${info.version}). ${appName()} downloads it, installs it and restarts.`
    : `${info.changes} new change${info.changes === 1 ? " is" : "s are"} waiting (you have ${info.version}). ${appName()} fetches ${info.changes === 1 ? "it" : "them"} and restarts.`;
  const ok = await confirmDialog({
    title: info.on_disk ? `Restart ${appName()}?` : `Update ${appName()}?`,
    message: `${what} ${running ? RUNNING_NOTE : ""}Your projects and results are kept.`,
    confirmText: info.on_disk ? "Restart" : "Update and restart", danger: !!running,
  });
  if (!ok) return done();
  if (btn.lastChild) btn.lastChild.textContent = info.on_disk ? "Restarting…" : "Updating…";
  let r;
  try { r = await api("POST", "/api/update", {}); } catch (e) { showError(e); return done(); }
  if (!r.restarting) { toast(`${appName()} ${r.version} is the newest version.`, "ok"); done(); btn.hidden = true; return; }
  waitForRestart(r.version, r.handover);

  function done() { btn.disabled = false; if (btn.lastChild && label) btn.lastChild.textContent = label; }
}

// the restart: a page that says so, then the new version once it answers (a new copy hands out a new token)
async function restartApp(version) {
  const running = await runningJobs();
  const ok = await confirmDialog({
    title: `Restart ${appName()}?`,
    message: `${appName()} ${version} starts in place of ${App.state.version}. ${running ? RUNNING_NOTE : ""}Your projects and results are kept.`,
    confirmText: "Restart", danger: !!running,
  });
  if (!ok) return;
  try { await api("POST", "/api/restart", {}); } catch (e) { showError(e); return; }
  waitForRestart(version);
}

// `handover` (0.15.4, Windows): the app quits and the new version is installed before it starts again, which takes
// longer than a restart
function waitForRestart(version, handover = false) {
  const meta = (name) => (document.querySelector(`meta[name="${name}"]`) || {}).content || "";
  const oldToken = meta("enlens-token");
  const status = h("p", { class: "muted" }, handover
    ? `${appName()} closes while Windows installs the new version, then opens again by itself. This page follows in a minute or two.`
    : "This page opens the new version by itself in a moment.");
  document.title = `${appName()} is ${handover ? "updating" : "restarting"}`;
  replace(document.body, h("main", { class: "stopped-page", id: "main" },
    h("img", { src: brand().logo, alt: "", width: 48, height: 48 }),
    h("h1", {}, `${handover ? "Installing" : "Starting"} ${appName()} ${version || ""}…`),
    h("p", {}, "Your projects and results are kept."),
    status));
  const t0 = Date.now();
  let wentDown = false;
  const poll = async () => {
    try {
      const res = await fetch("/", { cache: "no-store" });
      const page = res.ok ? await res.text() : "";
      const token = (page.match(/name="enlens-token" content="([^"]*)"/) || [])[1];
      if (page.includes('name="enlens-version"') && (wentDown || (token !== undefined && token !== oldToken))) {
        location.reload();
        return;
      }
    } catch (_) { wentDown = true; }
    if (Date.now() - t0 > (handover ? 300000 : 90000)) {
      replace(status, App.state.launcher
        ? `${appName()} did not come back. Open it again from its icon (on your Desktop, or in Applications).`
        : `${appName()} did not come back. Start it again the way you started it before (for example with enlens-gui).`);
      return;
    }
    setTimeout(poll, 800);
  };
  setTimeout(poll, 1200);
}

// `reason`: 0.10.2, why the person is asked to quit (a newer version is installed), shown in the dialog
async function quitApp(reason = "") {
  {
    const running = await runningJobs();
    const ok = await confirmDialog({
      title: `Quit ${appName()}?`,
      message: reason + (running
        ? "Something is still running (a check, or documents being added). Quitting stops it; a check that is stopped leaves nothing behind. Your projects and results are kept."
        : `${appName()} stops on this computer. Your projects and results are kept.`),
      confirmText: `Quit ${appName()}`, danger: !!running,
    });
    if (!ok) return;
    try { await api("POST", "/api/quit", {}); } catch (e) { showError(e); return; }
    const again = App.state.launcher
      ? `To open it again, double-click the ${appName()} icon (on your Desktop, or in Applications).`
      : "To open it again, start it the way you started it before (for example with enlens-gui).";
    document.title = `${appName()} has stopped`;
    replace(document.body, h("main", { class: "stopped-page", id: "main" },
      h("img", { src: brand().logo, alt: "", width: 48, height: 48 }),
      h("h1", {}, `${appName()} has stopped`),
      h("p", {}, "You can close this tab. Your projects and results are kept."),
      h("p", { class: "muted" }, again)));
  }
}

// 0.10.2: ENLENS was updated while this copy kept running (the page files are new, the program is not): say so on
// every page, with the way to start the new version. The ENLENS icon also does this by itself when nothing runs.
function renderUpdateBanner() {
  const box = document.getElementById("update-banner");
  if (!box) return;
  const st = App.state || {};
  const now = st.installed_version;
  if (!now || !st.version || now === st.version) { clear(box); return; }
  // 0.13.1: a restart, where this copy can restart itself; quitting otherwise
  const how = st.can_restart ? "Restart it to use the new version."
    : st.can_quit ? `Choose Quit ${appName()}, then open ${appName()} again${st.launcher ? " from its icon" : ""}.`
    : "Stop it and start it again.";
  replace(box, h("div", { class: "notice notice-info update-banner", role: "status" }, icon("refresh"),
    h("div", {}, h("p", {}, h("strong", {}, `${appName()} ${now} is installed, but ${st.version} is still running.`), ` ${how}`)),
    st.can_restart ? h("button", { class: "btn btn-sm", type: "button", onclick: () => restartApp(now) }, icon("refresh", { size: 13 }), "Restart now")
    : st.can_quit ? h("button", { class: "btn btn-sm", type: "button", onclick: () => quitApp(`${appName()} ${now} starts when you open it again. `) }, icon("power", { size: 13 }), `Quit ${appName()}`) : null));
}

function closeDrawer() {
  const sb = document.getElementById("sidebar");
  const sc = document.getElementById("scrim");
  const mb = document.getElementById("menu-btn");
  sb.classList.remove("open");
  const main = document.getElementById("main"); if (main) main.inert = false;
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
    // 0.14.3: while the phone menu is open the page behind it cannot be reached (Tab stayed on it)
    const main = document.getElementById("main"); if (main) main.inert = open;
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
// 0.13.6: an add-on's feature with `nav` gets a sidebar entry, after the last entry of its section (or under a new
// group heading for a section of its own). Each entry is decorated once.
function addonNav() {
  const nav = document.getElementById("nav");
  if (!nav) return;
  for (const [key, f] of Object.entries(FEATURES)) {
    if (!f.nav || nav.querySelector(`a[data-route="${CSS.escape(key)}"]`)) continue;
    const a = h("a", { href: f.href, "data-route": key }, h("span", { class: "nav-icon", "data-icon": f.icon || "circle" }), h("span", {}, f.title));
    const same = [...nav.querySelectorAll("a[data-route]")].filter((x) => (FEATURES[x.dataset.route] || {}).section === f.section);
    if (same.length) same[same.length - 1].after(a);
    else {
      const legend = nav.querySelector(".nav-legend");
      nav.insertBefore(h("span", { class: "nav-group", role: "presentation" }, (SECTIONS[f.section] || {}).title || ""), legend);
      nav.insertBefore(a, legend);
    }
  }
  navIcons();
}

function navIcons() {
  for (const span of document.querySelectorAll(".nav-icon[data-icon]")) { replace(span, icon(span.dataset.icon, { size: 18 })); span.removeAttribute("data-icon"); }
  for (const a of document.querySelectorAll("#nav a[data-route]")) {
    const f = FEATURES[a.dataset.route];
    if (!f || a.dataset.marked) continue;
    a.dataset.marked = "1";
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

// 0.13.6: the page modules of add-ons: the fork's static/extensions.js (empty in ENLENS), then each add-on package's
// (GET /api/state "addon_pages"). One that fails is left out; the page still works.
async function loadExtensions() {
  const into = { FEATURES, SECTIONS };
  try { applyExtensions(localExtensions, into); } catch (e) { console.error(e); }
  for (const url of App.state.addon_pages || []) {
    try { applyExtensions((await import(url)).default, into); } catch (e) { console.error(`The add-on page ${url} could not be loaded`, e); }
  }
  addonNav();
}

// 0.13.5: the app's name, words and logo come from brand.json (and add-ons): index.html keeps ENLENS's as a
// fallback for the moment before the state arrives, and is never edited to rename the app.
function applyBrand() {
  const b = brand();
  for (const a of document.querySelectorAll("a.brand")) a.setAttribute("aria-label", `${b.name} home`);
  for (const img of document.querySelectorAll("a.brand img")) img.setAttribute("src", b.logo);
  const big = document.querySelector(".sidebar .brand-text");
  if (big) { big.querySelector("strong").textContent = b.name; big.querySelector("small").textContent = b.tagline || ""; }
  const small = document.querySelector(".brand-small span");
  if (small) small.textContent = b.name;
  const fav = document.querySelector('link[rel="icon"]');
  if (fav) fav.setAttribute("href", b.logo);
  let meta = document.querySelector('meta[name="description"]');
  if (!meta) { meta = document.createElement("meta"); meta.name = "description"; document.head.appendChild(meta); }
  meta.content = b.description || "";
}

// 0.14.3: "Skip to content" moves focus to the page; its address (#main) is not a page of the app
function skipLinkInit() {
  const link = document.querySelector(".skip-link");
  if (!link) return;
  link.addEventListener("click", (e) => {
    e.preventDefault();
    const t = document.getElementById("main");
    if (t) t.focus();
  });
}

// 0.14.3: one banner across the app while it cannot be reached (it was stopped, or the computer slept), so no page
// has to say it by itself. It clears when the app answers again.
function connectionInit() {
  const box = document.getElementById("stopped-banner");
  const draw = () => {
    if (!Connection.down) { clear(box); return; }
    replace(box, h("div", { class: "notice notice-error stopped-banner", role: "alert" }, icon("alert-circle"),
      h("div", {}, h("p", {}, h("strong", {}, `${appName()} has stopped answering.`), " Start it again the way you started it before, then reload this page. Nothing you see below is up to date."),
        h("button", { class: "btn btn-sm", type: "button", onClick: () => location.reload() }, icon("refresh", { size: 13 }), "Reload this page"))));
  };
  window.addEventListener("enlens-connection", draw);
  // a quiet look every few seconds while it is down, so the banner goes by itself when the app is back
  setInterval(() => { if (Connection.down) api("GET", "/api/state").catch(() => {}); }, 5000);
}

// 0.15.1: a small note of what is new, once, on the first start after an update (the app marks it seen when it serves it)
// 0.15.4: or, also once, why an update on Windows did not finish (`kind: "problem"`)
async function whatsNewInit() {
  let note = null;
  try { note = (await api("GET", "/api/whats-new")).note; } catch (e) { return; }
  if (!note || !Array.isArray(note.points) || !note.points.length) return;
  const problem = note.kind === "problem";
  const onKey = (ev) => { if (ev.key === "Escape") close(); };
  const close = () => { document.removeEventListener("keydown", onKey); card.remove(); };
  const card = h("div", { class: problem ? "release-note release-note-problem" : "release-note", role: "status",
    "aria-live": "polite", "aria-label": problem ? "The update did not finish" : "What is new" },
    h("div", { class: "release-note-head" },
      problem ? icon("alert-triangle", { size: 15 }) : null,
      h("p", { class: "release-note-title" }, problem ? note.title : `${note.version}: ${note.title}`),
      h("button", { class: "icon-btn release-note-close", type: "button", "aria-label": "Close", onClick: close }, icon("x", { size: 14 }))),
    note.subtitle ? h("p", { class: "release-note-sub" }, note.subtitle) : null,
    h("ul", { class: "release-note-list" }, ...note.points.map((t) => h("li", {}, t))));
  document.addEventListener("keydown", onKey);
  if (problem) document.querySelectorAll(".update-popup").forEach((el) => el.remove());  // the same corner
  document.body.appendChild(card);
}

async function boot() {
  skipLinkInit();
  connectionInit();
  themeInit();
  drawerInit();
  sidebarScrollInit();
  navIcons();
  App.onChange(() => { renderProjectSwitch(); renderPrivacy(); renderQueue(); renderUpdateBanner(); });
  onJobsChanged(() => { renderJobs(); renderQueue(); });
  window.addEventListener("hashchange", route);
  try {
    await App.refresh();
  } catch (e) {
    replace(document.getElementById("view"), h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, e.message)));
    return;
  }
  applyBrand();
  await loadExtensions();
  renderJobs();
  updateInit();
  quitInit();
  route();
  whatsNewInit();
  // keep the sidebar fresh when the window regains focus
  window.addEventListener("focus", () => { renderJobs(); renderQueue(); });
}

boot();
