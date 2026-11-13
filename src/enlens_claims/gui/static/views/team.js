// 0.18 (roadmap L4, with L1, L3 and L5): working together, in two places.
// - The Team tab of the right-hand panel, beside the research log: the day-to-day. What waits for your word (owner.js),
//   the sync state with Sync now and Pause, what needs your attention, what came in, what you shared (with Unshare),
//   documents a colleague's work names that are not on this computer, and one quiet line to the Team page. Without a
//   team yet, one line and the way to the Team page.
// - The Team page (#/team, `renderTeam`): the team itself. Where the storage space or shared folder is, the people
//   (roles, since when, Remove…), the invites, the owner's settings, the documents-stay-here switch, how often rounds
//   run, the downloads as a file and Stop using it here; without a team, the set-up (a storage space, an invite link
//   or a shared folder).
// Both are one panel (`teamPanel`) drawing a list of sections from the same data (`ctx`): TEAM_SECTIONS for the tab,
// TEAM_PAGE_SECTIONS for the page. Built on GET/PUT/DELETE …/shared-folder (gui/api_folder.py) and GET …/sharing
// (gui/api_sharing.py); the poller's state is read through team-state.js. Built of 0.17.0's components
// (docs/DESIGN.md 5.5): buttons, fields, switches, folds, help marks, notices (noticeList), work states for the sync
// state, list rows for people, rounds and items, cards for the page's sections, and the AI line's folder for what the
// folder holds; placed in views.css (the block "Working together").
//
// A later stage adds a section to the tab with `addTeamSection` (L2: "Waiting for your word", before "state").
import { App, api, h, clear, replace, toast, showError, P, plural, field, switchControl, confirmDialog, watchJob,
  TERMINAL, store, shortTitle, helpMark, navigate, button, link, input, select, fold, tag, noticeList, notice, workState, dialog,
  listRow, listGroup, absentDocument, aiWhere, personMark, setBusy, card, pageHead } from "../lib.js";
import { itemHref, shareButton, KIND_WORDS, KIND_MANY, zipButton, ZIP_WORDS, SHARING_HELP } from "./share.js";
import { pollerState, syncLine, myShared, personLine, cleanPath, whenText, whenPhrase, newsLines, whoseWork, folderAsSeen, POLLER_API, EVERY_CHOICES } from "./team-state.js";
import { OWNER_SECTION, ownerMarks, ownerPerson } from "./owner.js";   // 0.18 L2
import { MINE_SECTION, REMOVED_SECTION, ROLES_SECTION, peopleRows, personSub, peopleNote } from "./owner.js";   // roles
import { SPACE_SETUP_SECTION, SPACE_SECTION, joinDialog, removeMember, memberSub, SERVICE_NAME } from "./team-space.js";   // 0.18.0rc2 (L6): a storage space

const EVERY = 20000;          // how often the open tab reads the folder's state again (it is cheap)
const SOON = 4000;            // … and while the poller is about to start a round ("due": it looks every 5 s)
const SHOWN_PER_KIND = 5;     // "What you shared": rows per kind before "Show all"
const KEEP_OUT_LABEL = "Keep documents marked Only a local AI or No AI out of the shared folder";
const KEEP_OUT_HELP = "Their text, their files and the passages an AI read from them stay on this computer; colleagues add those files themselves. What you share still carries the words you quoted from them, your notes on them and their titles. Once anyone in the team turns it on, it holds for everyone.";
const mac = () => /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent || "");
const win = () => /Win/i.test(navigator.platform || navigator.userAgent || "");

// ---- the Team tab's sections, in order. Each is {key, render(ctx) -> Element | null}.
export const TEAM_SECTIONS = [
  { key: "setup", render: tabSetupSection },      // no team yet: one line, the way to the Team page
  { key: "stop", render: stopSection },           // roles: a folder problem that stops this copy, first of all
  { key: "state", render: stateSection },         // the sync state, Sync now, Pause, the team in one line
  { key: "problems", render: problemsSection },
  { key: "came-in", render: cameInSection },
  { key: "shared", render: sharedSection },
  { key: "not-here", render: notHereSection },
];

export function addTeamSection(section, { before } = {}) {
  const at = before ? TEAM_SECTIONS.findIndex((s) => s.key === before) : -1;
  if (at < 0) TEAM_SECTIONS.push(section); else TEAM_SECTIONS.splice(at, 0, section);
}
// 0.18 L2: a section may also read its own answer with the tab's refresh (`load(project)`, kept in ctx.data[key]) and
// add to the tab's number (`count(ctx)`)
// roles (DESIGN-roles §5, mock-up B): "Waiting for your word" is the tab's first section, before the sync state (and
// only there when something waits); a Member's own proposals after it; the removals of the last 30 days after what
// came in
addTeamSection(OWNER_SECTION, { before: "state" });
addTeamSection(MINE_SECTION, { before: "state" });
addTeamSection(REMOVED_SECTION, { before: "shared" });

// ---- the Team page's sections, in order: the team itself
export const TEAM_PAGE_SECTIONS = [
  SPACE_SETUP_SECTION,                            // no team yet: a storage space (recommended), or an invite link
  { key: "setup", render: setupSection },         // … or a folder the team already shares
  { key: "folder", render: folderSection },       // a shared folder: where it is
  SPACE_SECTION,                                  // a storage space: where it is, invites, move, technical details
  { key: "people", render: peopleSection },       // the people: roles, since when, Remove…
  ROLES_SECTION,                                  // the owner (Become the owner, Accept documents … at once)
  { key: "keep-out", render: keepOutSection },
  { key: "often", render: oftenSection },         // how often rounds run, for every project
  { key: "downloads", render: downloadsSection },
  { key: "leave", render: leaveSection },
];
const sectionCount = (ctx, list = TEAM_SECTIONS) => list.reduce((n, s) => { try { return n + (s.count ? Number(s.count(ctx)) || 0 : 0); } catch (_) { return n; } }, 0);

function section(key, title, ...children) {
  const id = `team-h-${key}`;
  return h("section", { class: `team-section team-sec-${key}`, "aria-labelledby": id, dataset: { key } },
    h("h3", { class: "team-h", id }, title), ...children);
}

// ---------------------------------------------------------------------------------------------
// the panel
// ---------------------------------------------------------------------------------------------
// Makes the Team panel. `onCount(n)`: how many things came in that were not seen yet (for the tab's label).
// `sections`: what it draws (the tab's, or TEAM_PAGE_SECTIONS); `page`: drawn on the Team page, each section a card.
export function teamPanel({ onCount, sections = TEAM_SECTIONS, page = false } = {}) {
  // a live region of its own, kept across redraws: it says when the folder goes offline, is paused or a round fails
  const live = h("p", { class: "visually-hidden", role: "status", "aria-live": "polite" });
  const body = h("div");
  const root = h("div", { class: page ? "team team-page" : "team", "aria-busy": "true" }, live, body);
  const ctx = { project: null, status: null, sharing: null, history: null, poller: null, poll: null, open: new Set(),
    setup: freshSetup(), refresh, startRound, markSeen, focusHeading, page, data: {} };   // 0.18 L2: data
  let shown = false, timer = null, token = 0, watching = null, drawn = null, said = null;
  let reading = Promise.resolve();   // the refresh show() started: focusSection waits for it
  const gone = new Set();   // rounds that could not be followed (no such job any more): not followed again

  const seenKey = () => `team-seen:${ctx.project}`;
  const seenAt = () => { const v = Number(store(seenKey())); return Number.isFinite(v) && v > 0 ? v : null; };

  // `force`: draw even when nothing changed (after an action of the person's)
  async function refresh({ force = false } = {}) {
    const mine = ++token;
    const project = App.project;
    if (!project) { replace(body, h("p", { class: "muted team-empty" }, "Open a project first.")); return; }
    if (project !== ctx.project) {   // another project: nothing of the last one is kept, its round is not followed
      Object.assign(ctx, { project, status: null, sharing: null, history: null, poller: null, poll: null, setup: freshSetup(), data: {} });   // 0.18 L2: data
      ctx.open.clear();
      if (watching) { watching.w.stop(); watching = null; }
      gone.clear();
      drawn = null; said = null;
    }
    // a read that fails keeps what was there; 404 means the thing is not there (the poller, until it is merged)
    const keep = (prev) => (e) => (e && e.status === 404 ? null : prev);
    let status, sharing, together, poller, extra;   // 0.18 L2: extra, the sections' own answers
    const loads = sections.filter((s) => s.load);
    try {
      [status, sharing, together, poller, extra] = await Promise.all([
        api("GET", `/api/projects/${P(project)}/shared-folder`),
        api("GET", `/api/projects/${P(project)}/sharing`).catch(keep(ctx.sharing)),
        // the work brought in that the project keeps (what came in before, team-state.js)
        api("GET", `/api/projects/${P(project)}/together`).catch(() => ({ history: ctx.history })),
        // the poller's state (L3); null until it is there (team-state.js: the stand-in)
        api("GET", POLLER_API.state(P(project))).catch(keep(ctx.poller)),
        Promise.all(loads.map((s) => s.load(project).catch(keep(ctx.data[s.key])))),   // 0.18 L2
      ]);
    } catch (e) {
      if (mine !== token || project !== App.project) return;
      if (!ctx.status) {
        replace(body, h("p", { class: "muted team-empty" }, "The team’s state could not be read."),
          button({ kind: "quiet", sm: true, id: "team-try-again", onClick: () => refresh({ force: true }) }, "Try again"));
        root.setAttribute("aria-busy", "false");
      }
      return;
    }
    if (mine !== token || project !== App.project) return;
    ctx.status = status;
    ctx.sharing = sharing;
    ctx.history = together ? together.history : null;
    ctx.poller = poller;
    ctx.poll = pollerState(status, seenAt(), ctx.history, poller);
    loads.forEach((s, i) => { ctx.data[s.key] = extra[i]; });   // 0.18 L2
    if (onCount) onCount((status.folder ? ctx.poll.unseen : 0) + sectionCount(ctx, sections));   // 0.18 L2: + sectionCount
    // drawn again only when something changed: a redraw under a hand moves the focus and a screen reader's place
    const sig = JSON.stringify([status, sharing, ctx.history, poller, seenAt(), ctx.data]);   // 0.18 L2: ctx.data
    if (force || sig !== drawn) { drawn = sig; draw(); } else updateLine();
    follow(status.job || ctx.poll.round);
  }

  function draw() {
    // keep the place: the control with focus is found again by its id; one that went (an item unshared) leaves the
    // focus on its section's heading
    const fa = document.activeElement;
    const had = fa && body.contains(fa) ? { id: fa.id, section: (fa.closest(".team-section") || {}).dataset } : null;
    const scroller = root.parentElement;   // the drawer's section that scrolls (docs/DESIGN.md 4.19)
    const y = scroller ? scroller.scrollTop : 0;
    clear(body);
    for (const s of sections) {
      let el = null;
      try { el = s.render(ctx); } catch (e) { console.error(`Team ${page ? "page" : "tab"}, ${s.key}:`, e); }
      if (el) body.appendChild(page ? pageCard(el) : el);
    }
    root.setAttribute("aria-busy", "false");
    if (scroller) scroller.scrollTop = y;
    if (had) {
      const again = had.id && document.getElementById(had.id);
      if (again && body.contains(again)) again.focus({ preventScroll: true });
      else if (had.section && had.section.key) focusHeading(had.section.key);
    }
    say();
  }

  // the state line again (its times move on) without drawing the rest
  function updateLine() {
    const line = body.querySelector(".team-state-line");
    if (line) {
      const s = syncLine(ctx.status, ctx.poll);
      line.dataset.kind = s.kind;
      replace(line, stateLine(ctx));
    }
    say();
  }

  // say it (the live region) when the folder goes offline or comes back, is paused or resumed, or a round fails
  function say() {
    if (!ctx.status || !ctx.status.folder) { said = null; return; }
    const s = syncLine(ctx.status, ctx.poll);
    const loud = (k) => ["offline", "paused", "failed"].includes(k);
    if (s.kind === "running" && loud(said)) return;   /* 0.18 real poller: back from offline, say how the round went, not that it runs */
    const words = [s.text, s.sub].filter(Boolean).map((t) => (/[.…:!?]$/.test(t) ? t : `${t}.`)).join(" ");
    if (said && said !== s.kind && (loud(s.kind) || loud(said))) live.textContent = words;
    said = s.kind;
  }

  function focusHeading(key) {
    const h3 = body.querySelector(`#team-h-${key}`);
    if (h3) { h3.setAttribute("tabindex", "-1"); h3.focus({ preventScroll: false }); }
  }

  // a round running (started here, by the poller, or in another window): its progress in the state line
  function watch(job, after) {
    if (watching) watching.w.stop();
    const project = ctx.project;
    const w = watchJob(job.id, (j) => {
      if (!ctx.status || ctx.project !== project || (j.project && j.project !== project)) return;
      ctx.status.job = TERMINAL.has(j.state) ? null : j;
      if (!TERMINAL.has(j.state)) updateLine();
    }, 1000);
    watching = { id: job.id, w };
    w.promise.then((j) => { if (watching && watching.w === w) watching = null; if (after && j.project === App.project) after(j); if (ctx.project === project) refresh(); })
      .catch(() => { if (watching && watching.w === w) watching = null; gone.add(job.id); if (ctx.project === project) refresh(); });
  }
  function follow(job) {
    if (!job || !job.id || TERMINAL.has(job.state) || gone.has(job.id) || (watching && watching.id === job.id)) return;
    if (job.project && job.project !== ctx.project) return;
    watch(job, null);
  }

  async function startRound(btn) {
    if (btn) btn.setAttribute("aria-disabled", "true");   /* 0.18 real poller: not `disabled`, so the focus stays on it */
    try {
      const r = await api("POST", `/api/projects/${P(ctx.project)}/shared-folder/sync`, {});
      ctx.status.job = r.job;
      updateLine();
      if (!watching || watching.id !== r.job.id) watch(r.job, roundToast);
    } catch (e) { showError(e); if (btn) btn.removeAttribute("aria-disabled"); }
  }

  async function markSeen() {
    try {
      if (ctx.poll.live) ctx.poller = await api("POST", POLLER_API.seen(P(ctx.project)), ctx.poll.newest_id !== null ? { through: ctx.poll.newest_id } : {});
      else store(seenKey(), String(Date.now()));
    } catch (e) { showError(e); return; }
    ctx.poll = pollerState(ctx.status, seenAt(), ctx.history, ctx.poller);
    if (onCount) onCount(ctx.poll.unseen + sectionCount(ctx, sections));   // 0.18 L2: + sectionCount
    drawn = null;
    draw();
    focusHeading("came-in");
  }

  function arm() {
    clearTimeout(timer);
    if (!shown) return;
    timer = setTimeout(async () => {
      // never redraw under a hand: not while something in the panel is being typed in or chosen
      const fa = document.activeElement;
      if (fa && body.contains(fa) && fa.matches("input[type=text], textarea, select")) { arm(); return; }
      await refresh();
      arm();
    }, ctx.poll && ctx.poll.due ? SOON : EVERY);   /* 0.18 real poller: a round about to start is looked at again soon */
  }

  // the poller says something came in (app.js fires it when its count grows): read again while the tab is shown
  const news = (e) => {
    if (!e.detail || e.detail.project !== App.project) return;
    if (shown) refresh();
    else if (onCount && e.detail.came_in) onCount((e.detail.came_in.count || 0) + (ctx.project === App.project ? sectionCount(ctx, sections) : 0));   // 0.18 L2
  };
  window.addEventListener("enlens-sync-news", news);

  return {
    el: root,
    show() { shown = true; reading = refresh(); arm(); },
    hide() { shown = false; clearTimeout(timer); },
    refresh,
    // a section's heading, once the current refresh has drawn: focused and brought into view (the sharing line's
    // See what you shared opens the tab at "shared")
    async focusSection(key) {
      try { await reading; } catch (_) { /* what was drawn before stays */ }
      focusHeading(key);
      const head = body.querySelector(`#team-h-${key}`);
      if (head) head.scrollIntoView({ block: "nearest" });
    },
    // the page's panel is made again on each visit: it stops listening when the page goes
    destroy() { shown = false; clearTimeout(timer); window.removeEventListener("enlens-sync-news", news); if (watching) { watching.w.stop(); watching = null; } },
  };
}

// On the Team page each section is a card (docs/DESIGN.md 4.11) under the page's title: its heading one level up
function pageCard(sec) {
  const h3 = sec.querySelector(":scope > .team-h");
  if (h3) {
    const h2 = h("h2", { class: "team-h", id: h3.id, tabindex: h3.getAttribute("tabindex") });
    h2.append(...h3.childNodes);
    h3.replaceWith(h2);
  }
  return card({ as: "div", class: "team-card" }, sec);
}

// The Team page (#/team): the team itself (app.js loads this file when the page is first opened)
export function renderTeam(view) {
  view.appendChild(pageHead("Team", {
    sub: ["The people you work with on this project and how your copies keep in step. The day-to-day is in the ",
      link({ kind: "jump", id: "team-open-tab", onclick: () => window.dispatchEvent(new CustomEvent("enlens-drawer", { detail: { tab: "team" } })) }, "Team tab"), "."] }));
  const panel = teamPanel({ sections: TEAM_PAGE_SECTIONS, page: true });
  view.appendChild(panel.el);
  panel.show();
  const off = App.onChange(() => panel.refresh());   // another project chosen in the sidebar
  return () => { panel.destroy(); if (typeof off === "function") off(); };
}

// keepOut null: not touched here, so the form shows the project's own switch and leaves it as it is (it stays on
// after Stop using this folder, and a project moved to this computer brings it)
// 0.18.0rc2 (L7): the cloud folders this computer has, read once and kept for the page's life (they rarely change)
let cloudAnswer = null;
let cloudKnown = [];
const cloudAnswerNow = () => cloudKnown;
function cloudFolders() {
  if (!cloudAnswer) cloudAnswer = api("GET", "/api/cloud-folders").catch(() => ({ folders: [], picker: false }))
    .then((a) => { cloudKnown = a.folders || []; return a; });
  return cloudAnswer;
}
function freshSetup() { return { path: "", name: "", keepOut: null, error: "" }; }

function roundToast(j) {
  if (!j) return;
  if (j.state === "error") { toast(`The round did not work: ${j.error || "unknown reason"}`, "error"); return; }
  if (j.state !== "done" || !j.result) return;
  const res = j.result;
  const came = (res.read || []).filter((r) => r.report && newsLines(r.report.lines).length);
  const sent = res.wrote && res.wrote.seq ? (res.wrote.items || []).length : 0;
  const bits = [];
  if (came.length) bits.push(whoseWork(came.map((r) => r.name)));
  if (sent) bits.push(`${plural(sent, "item")} of yours sent.`);
  const problem = (res.problems || [])[0];
  if (problem) toast(`${bits.join(" ")} ${problem.message}`.trim(), "warn", { ttl: 9000 });
  else toast(bits.join(" ") || "Up to date: nothing new to send or bring in.", "ok", { small: !bits.length });
}

// a fold (docs/DESIGN.md 4.22) whose summary keeps an id across redraws (so the focus finds it again)
function teamFold(id, open, summary, ...body) {
  const f = fold({ open, class: `team-fold ${id}` }, summary, ...body);
  f.querySelector("summary").id = id;
  return f;
}

// a switch whose control keeps one id across redraws (so the focus finds it again). `mark`: its longer explanation
// behind a help mark beside it (docs/DESIGN.md 4.18), not a help line under it
function teamSwitch(id, label, checked, help, mark = null) {
  const sw = switchControl(label, checked, { help });
  sw.input.id = id;
  const lab = sw.querySelector("label");
  if (lab) lab.htmlFor = id;
  if (mark) {
    const row = h("div", { class: "team-switch" }, sw, helpMark(mark.label, mark.text));
    row.input = sw.input;
    return row;
  }
  return sw;
}

// ---------------------------------------------------------------------------------------------
// the tab without a team yet: one line, the way to the Team page, and an invite link
// ---------------------------------------------------------------------------------------------
function tabSetupSection(ctx) {
  const st = ctx.status;
  if (st.folder || st.space) return null;
  return section("setup", "Work together",
    h("p", { class: "muted team-text" }, "Not shared with a team yet. ", link({ href: "#/team", id: "team-set-up" }, "Set up a team")),
    h("div", { class: "btn-row" }, button({ sm: true, icon: "link", id: "team-join", onClick: () => joinDialog(ctx) }, "Join with an invite link…")));
}

// ---------------------------------------------------------------------------------------------
// no shared folder yet: the set-up step
// ---------------------------------------------------------------------------------------------
function setupSection(ctx) {
  const st = ctx.status;
  if (st.folder) return null;
  const typed = ctx.setup;   // what was typed and chosen here stays across redraws until the folder is chosen
  const example = win() ? "C:\\Users\\Anna\\OneDrive\\Our project" : "/Users/anna/Dropbox/Our project";
  const path = input({ mono: true, id: "team-folder-path", autocomplete: "off", spellcheck: "false", placeholder: example, value: typed.path });
  path.addEventListener("input", () => { typed.path = path.value; });
  const copyTip = mac() ? "In the Finder, select the folder and press ⌥⌘C to copy its path." : win() ? "In File Explorer, hold Shift, right-click the folder and choose Copy as path." : "";
  const pathField = field("The shared folder", path, { help: `Its whole path on this computer. ${copyTip}`.trim() });
  const err = h("p", { class: "field-error team-error", role: "alert", id: "team-folder-error" }, typed.error);
  path.setAttribute("aria-describedby", `${path.getAttribute("aria-describedby") || ""} team-folder-error`.trim());
  if (typed.error) path.setAttribute("aria-invalid", "true");
  const sw = teamSwitch("team-setup-keep-out", KEEP_OUT_LABEL, typed.keepOut ?? !!(st.keep_out || {}).mine, null, { label: "About documents that stay here", text: KEEP_OUT_HELP });
  sw.input.addEventListener("change", () => { typed.keepOut = sw.input.checked; });
  const me = st.me || {};
  const name = input({ id: "team-your-name", maxlength: 60, autocomplete: "name", placeholder: "e.g. Anna de Vries", value: typed.name });
  name.addEventListener("input", () => { typed.name = name.value; });
  const nameField = me.name ? null : field("Your name", name, { help: "Colleagues see your work under this name." });
  const go = button({ kind: "main", sm: true, icon: "folder", id: "team-use-folder" }, "Use this folder");
  // the error is said where the field is now (the panel may have been drawn again meanwhile)
  const showErr = (text) => {
    typed.error = text;
    const e = document.getElementById("team-folder-error"), f = document.getElementById("team-folder-path");
    if (e) e.textContent = text;
    if (f) { f.setAttribute("aria-invalid", text ? "true" : "false"); if (text) f.focus(); }
  };
  const choose = async () => {
    showErr("");
    const p = cleanPath(typed.path);
    if (!p) { showErr("Type or paste the path of the folder your team shares."); return; }
    const b = document.getElementById("team-use-folder") || go;
    b.disabled = true;
    let named = false;
    try {
      if (!me.name && typed.name.trim()) { await api("PUT", "/api/settings", { your_name: typed.name.trim() }); named = true; }
      await api("PUT", `/api/projects/${P(ctx.project)}/shared-folder`, typed.keepOut === null ? { path: p } : { path: p, keep_out: typed.keepOut });
      ctx.setup = freshSetup();
      toast("This project now works through the shared folder. The first round starts now.", "ok");
      await ctx.refresh({ force: true });
      ctx.focusHeading("folder");
      ctx.startRound();
    } catch (e) {
      const again = document.getElementById("team-use-folder");
      if (again) again.disabled = false;
      if (e.status === 400) showErr(e.message); else showError(e);
    } finally {
      if (named) App.refresh().catch(() => {});   // the name, for the other pages (after the folder: no read beside it)
    }
  };
  go.addEventListener("click", choose);
  // 0.18.0rc2 (L7): the cloud folders by name, the system's folder window, and a colleague's folder already found
  const fillPath = (p) => {
    typed.path = p;
    const f = document.getElementById("team-folder-path") || path;
    f.value = p;
    showErr("");
    f.focus();
  };
  const offers = h("div", { class: "team-offers", id: "team-offers" });
  const drawOffers = (into) => replace(into, offerBlock(typed.offers, project, fillPath, showErr, typed));
  const project = ctx.project;
  if (!typed.offers) {
    typed.offers = { loaded: false, folders: [], picker: false, found: [], team: "" };
    Promise.all([cloudFolders(), api("GET", `/api/projects/${P(project)}/shared-folder/find`).catch(() => ({ found: [], team: "" }))])
      .then(([cloud, find]) => {
        Object.assign(typed.offers, { loaded: true, folders: cloud.folders || [], picker: !!cloud.picker, found: find.found || [], team: find.team || "" });
        const el = document.getElementById("team-offers");
        if (el && ctx.setup === typed) drawOffers(el);
      });
  }
  drawOffers(offers);
  path.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); choose(); } });
  return section("setup", "Or a folder your team already shares",
    h("p", { class: "muted team-lead" }, "OneDrive, Dropbox, Google Drive or a network drive.",
      helpMark("About working through a shared folder", FOLDER_HELP)),
    nameField, offers, pathField, err, sw,
    h("div", { class: "btn-row" }, go),
    // where text goes, at the foot (docs/DESIGN.md 4.4 and 5.5: the AI line's folder)
    aiWhere([h("strong", {}, "The folder will hold the documents’ text and files, and only what you share of your own work. "),
      "Your project’s database stays on this computer."], "folder"));
}

const FOLDER_HELP = "Each of you keeps your own copy of this project. ENLENS puts what you share in the folder and brings in what your colleagues share. Nothing of yours goes to the team until you press Share on it: a check, a set of themes, a codebook, a note, an entry of your own or a link between terms.";

// 0.18.0rc2 (L7): above the path field. A colleague's shared folder, when it is already among this computer's cloud
// folders ("Use it"); the cloud folders by name (one click fills the path); the system's folder window; and, when the
// team's folder is nowhere yet, what to do at each service. The pasted path stays as the fallback.
const WHERE = "Your colleague’s shared folder is here:";
function offerBlock(o, project, fillPath, showErr, typed) {
  const rows = [];
  for (const dir of o.found) {
    const seen = folderAsSeen(dir, o.folders);
    rows.push(h("p", { class: "team-text team-found" }, `${WHERE} `, h("strong", { title: dir }, seen.text), " · ",
      link({ kind: "jump", "data-found": dir, onclick: () => fillPath(dir) }, "Use it")));
  }
  if (o.folders.length) {
    rows.push(h("div", { class: "team-cloud" }, listGroup("Cloud folders on this computer", ...o.folders.map((c) =>
      listRow({ title: c.name, sub: c.path, actions: [button({ sm: true, "aria-label": `Use ${c.name}`, onclick: () => fillPath(c.path) }, "Use")] })))));
  }
  if (o.picker) {
    const pick = button({ sm: true, icon: "folder", id: "team-choose-folder" }, "Choose folder…");
    pick.addEventListener("click", async () => {
      showErr("");
      setBusy(pick, true);
      try {
        const r = await api("POST", "/api/choose-folder", { prompt: "Choose the folder your team shares", start: cleanPath(typed.path) || undefined });
        if (r.path) fillPath(r.path);
      } catch (e) {
        if (e.status === 409) showErr(e.message); else showError(e);
      } finally { setBusy(pick, false); }
    });
    rows.push(h("div", { class: "btn-row team-pick" }, pick));
  }
  if (o.loaded && !o.found.length) {   // how a colleague's folder comes to this computer, folded beside the field
    rows.push(fold({ sm: true, class: "team-where", id: "team-where" }, "Your colleague’s folder is not here yet?",
      h("p", { class: "muted small" }, "Ask the colleague who set it up to share the folder with you, then make it available on this computer. ",
        h("strong", {}, "OneDrive: "), "on OneDrive’s website, choose ", h("em", {}, "Add shortcut to My files"), " on the shared folder, and ",
        h("em", {}, "Always keep on this device"), " so its files are not fetched only when opened. ",
        h("strong", {}, "Google Drive and Dropbox: "), "accept the share and keep the folder available offline. ",
        "It then appears here.")));
  }
  return h("div", {}, ...rows);
}

// ---------------------------------------------------------------------------------------------
// with a shared folder
// ---------------------------------------------------------------------------------------------
// the sync state is a work state (docs/DESIGN.md 4.21, 5.5): running, waiting its turn, not running (offline,
// paused), did not work, done; its second line in quiet words
const WORK_STATE = { running: "running", busy: "waiting", never: "waiting", offline: "stopped", paused: "paused", failed: "failed", ok: "done" };
// one line: the state; its second line is said only when it needs you (offline, failed, waiting its turn, a round's
// progress), otherwise it is the line's tooltip ("Up to date; next round in about 2 min.")
const SAY_SUB = new Set(["running", "busy", "offline", "failed", "never"]);
function stateLine(ctx) {
  const s = syncLine(ctx.status, ctx.poll);
  const ws = workState(WORK_STATE[s.kind] || "waiting", s.text);
  if (s.sub && !SAY_SUB.has(s.kind)) { ws.title = s.sub; return [ws, h("span", { class: "visually-hidden" }, ` ${s.sub}`)]; }
  return [ws, s.sub ? h("span", { class: "muted small team-state-sub" }, s.sub) : null];
}

// the team in one line, for the tab: "Backblaze · 3 people", "OneDrive › Our project · 2 people"
function teamSummary(st) {
  const sp = st.space;
  const n = sp ? (sp.members || []).filter((m) => !m.removed).length : (st.people || []).length + 1;
  const where = sp ? SERVICE_NAME[sp.service] || "A storage space" : folderAsSeen(st.folder, cloudAnswerNow()).text;
  return `${where} · ${plural(Math.max(n, 1), "person", "people")}`;
}

// the poller's settings: pause this project (the tab), every project and the interval (the page). `undo()`: puts the
// control back as it was when the app refuses
function putter(ctx) {
  return async (path, body, el, undo) => {
    const id = el && el.id;   /* 0.18 real poller: the focus goes back to the control once the tab is drawn again */
    if (el) el.disabled = true;
    try { await api("PUT", path, body); await ctx.refresh({ force: true }); const again = id && document.getElementById(id); if (again) again.focus(); }
    catch (e) { showError(e); if (undo) undo(); if (el) { el.disabled = false; el.focus(); } }
  };
}

function stateSection(ctx) {
  const st = ctx.status, p = ctx.poll;
  if (!st.folder) return null;
  // off only while a round really runs (a round the poller expects to start, "due", may never come)
  const going = (j) => !!j && !TERMINAL.has(j.state);
  const running = going(st.job) || going(p.round);
  // 0.18 real poller: off with aria-disabled (still focusable), so the focus stays on it through a round and its redraws
  const sync = button({ sm: true, icon: "refresh", "aria-disabled": running ? "true" : null, id: "team-sync-now",
    title: "Send what changed and bring in what your colleagues shared, now" }, "Sync now");
  sync.addEventListener("click", () => { if (sync.getAttribute("aria-disabled") !== "true") ctx.startRound(sync); });
  // the poller's rounds (L3): pause this project here; every project and how often on the Team page
  const put = putter(ctx);
  let pause = null;
  if (p.live && p.auto) {
    const resumeAll = p.paused_all && !p.paused_here;
    pause = button({ kind: "quiet", sm: true, icon: p.paused ? "play" : "pause", id: "team-pause",
      title: p.paused ? "Let rounds run by themselves again" : "No round runs by itself until you resume (Sync now still works)" },
      p.paused ? (resumeAll ? "Resume every project" : "Resume") : "Pause");
    pause.addEventListener("click", () => (resumeAll ? put(POLLER_API.app, { paused: false }, pause) : put(POLLER_API.state(P(ctx.project)), { paused: !p.paused_here }, pause)));
  }
  const wrote = st.last_round && st.last_round.result && st.last_round.result.wrote;
  const waiting = (wrote && wrote.waiting) || [];
  const s = syncLine(st, p);
  return section("state", "Sync",
    // not a live region: its times move on every few seconds (the panel's own region says what matters)
    h("div", { class: "team-state-line", "data-kind": s.kind }, stateLine(ctx)),
    waiting.length ? h("p", { class: "muted small team-waiting" }, `${plural(waiting.length, "shared item")} still being worked on go${waiting.length === 1 ? "es" : ""} with the next round once ${waiting.length === 1 ? "it is" : "they are"} done: `,
      waiting.slice(0, 3).map((x) => `“${shortTitle(x.title || x.key, 40)}”`).join(", "), waiting.length > 3 ? "…" : "", ".") : null,
    // 3-polish: a round may take documents out of the folder (the switch came into force for them)
    wrote && wrote.taken_out ? h("p", { class: "muted small team-waiting" }, `The last round took ${plural(wrote.taken_out, "document")} out of the shared folder: they are kept on this computer now.`) : null,
    h("div", { class: "btn-row team-actions" }, sync, pause),
    // the team itself is managed on its page
    h("p", { class: "muted small team-summary" }, h("span", { title: st.space ? st.space.where : st.folder }, teamSummary(st)), " · ",
      link({ href: "#/team", id: "team-manage" }, "Manage the team")));
}

// The Team page: how often rounds run and pausing them, for every project
function oftenSection(ctx) {
  const st = ctx.status, p = ctx.poll;
  if (!st.folder || !(p.live && p.auto)) return null;
  const put = putter(ctx);
  const minutes = p.every ? Math.round(p.every / 60) : 2;
  const sel = select({ id: "team-every" },
    [...new Set([...EVERY_CHOICES, minutes])].sort((a, b) => a - b).map((m) => h("option", { value: String(m), selected: m === minutes }, m === 1 ? "every minute" : `every ${m} minutes`)));
  sel.addEventListener("change", () => put(POLLER_API.app, { every_minutes: Number(sel.value) }, sel, () => { sel.value = String(minutes); }));
  const all = teamSwitch("team-pause-all", "Pause rounds for every project", p.paused_all, null,
    { label: "About pausing", text: "For all your projects with a team. Each project can also be paused on its own, with Pause in its Team tab. Sync now still works." });
  all.input.addEventListener("change", () => put(POLLER_API.app, { paused: all.input.checked }, all.input, () => {
    all.input.checked = p.paused_all;
    all.input.setAttribute("aria-checked", p.paused_all ? "true" : "false");
  }));
  return section("often", "How often ENLENS looks",
    field("Look for new work", sel, { help: "For all your projects. A round also runs about 20 seconds after you change something." }), all);
}

// The Team page, a shared folder: where it is (a storage space has its own section, team-space.js)
function folderSection(ctx) {
  const st = ctx.status;
  if (!st.folder || st.space) return null;
  const seen = folderAsSeen(st.folder, cloudAnswerNow());
  return section("folder", "The shared folder",
    h("p", { class: "team-text" }, seen.text),
    h("p", { class: "team-folder mono", title: st.folder }, st.folder));
}

// Another computer writes under this person's name: the page offers Use both computers too (the tab says it first)
function secondComputer(ctx) {
  if (!ctx.status.other_computer) return null;
  return h("div", { class: "btn-row" }, button({ sm: true, id: "team-page-both-computers", onClick: () => bothComputersDialog(ctx) }, "Use both computers…"));
}

// roles: the problems that stop this copy from writing (another computer under this name, the folder out of reach)
// come first in the tab; the others stay under the shared folder
const STOPS = new Set(["other_computer", "unreachable"]);
const SECOND_COMPUTER = (since) => `Another computer is writing into this folder under your name${since ? ` (since ${since})` : ""}. Nothing was written from here, so nothing is lost.`;
function folderProblems(ctx) {
  const st = ctx.status;
  const list = (st.problems || []).filter((x) => !(x.kind === "unreachable" && ctx.poll.offline && !x.person));
  // the second-computer guard (DESIGN-roles §4.11): folder.status() says it as `other_computer` too
  if (st.other_computer && !list.some((x) => x.kind === "other_computer")) list.unshift({ kind: "other_computer", person: null, message: "" });
  return list;
}
const problemItem = (ctx, x) => {
  const severe = new Set(["damaged", "other_project", "failed"]);
  if (x.kind === "other_computer") {
    const since = ctx.status.other_computer && ctx.status.other_computer.since ? new Date(ctx.status.other_computer.since).toLocaleDateString("en-GB", { day: "numeric", month: "long" }) : "";
    return { kind: "attention", text: SECOND_COMPUTER(since),
      action: h("div", { class: "btn-row" }, button({ sm: true, id: "team-both-computers", onClick: () => bothComputersDialog(ctx) }, "Use both computers…")) };
  }
  return { kind: severe.has(x.kind) ? "error" : "attention", person: x.person && x.person.name ? personMark([x.person.name]) : null, text: x.message };
};

function stopSection(ctx) {
  const st = ctx.status;
  if (!st.folder) return null;
  const list = folderProblems(ctx).filter((x) => STOPS.has(x.kind) && !x.person);
  if (!list.length) return null;
  return section("stop", "Needs your attention", noticeList(list.map((x) => problemItem(ctx, x))));
}

function problemsSection(ctx) {
  const st = ctx.status;
  const list = folderProblems(ctx).filter((x) => !(STOPS.has(x.kind) && !x.person));
  if (!st.folder || !list.length) return null;
  return section("problems", list.length === 1 ? "Needs your attention" : `Needs your attention (${list.length})`,
    noticeList(list.map((x) => problemItem(ctx, x))));
}

// "Use both computers": this computer becomes a second person in the projects (DESIGN-roles §5.6)
async function bothComputersDialog(ctx) {
  const me = (ctx.status && ctx.status.me) || {};
  const name = input({ id: "team-dlg-name", maxlength: 60, autocomplete: "off", value: me.name ? `${me.name} (2)` : "" });
  const err = h("p", { class: "field-error", role: "alert" });
  const ok = await dialog({ title: "Use both computers?", body: h("div", {},
    h("p", {}, "This computer becomes a second person in your projects. What you did on this computer so far stays here, shown as your other computer’s."),
    field("Your name on this computer", name, { help: "Colleagues see this name beside what you do here." }), err),
  actions: [{ text: "Cancel", value: null }, { text: "Use both computers", value: true, primary: true, id: "team-dlg-ok",
    async onClick() {
      err.textContent = "";
      if (!name.value.trim()) { err.textContent = "Give this computer a name."; name.focus(); return false; }
      try { await api("POST", "/api/second-computer", { name: name.value.trim() }); } catch (e) { err.textContent = e.message; return false; }
      return true;
    } }],
  onOpen: () => { name.focus(); name.select(); } });
  if (!ok) return;
  toast("This computer is a second person in your projects now. The owner can mark both as you.", "ok", { ttl: 9000 });
  await App.refresh().catch(() => {});
  await ctx.refresh({ force: true });
  ctx.focusHeading("state");
}

function cameInSection(ctx) {
  const st = ctx.status, p = ctx.poll;
  if (!st.folder) return null;
  const items = p.came_in || [];
  const fresh = items.filter((c) => !c.seen), older = items.filter((c) => c.seen);
  // a round: who (a person mark), what came in, when (docs/DESIGN.md 4.20, list rows)
  const row = (c) => {
    const r = listRow({ person: personMark([c.from]), title: c.lines.join(" "), time: c.at ? whenText(c.at) : null });
    const t = r.querySelector("time");
    if (t) t.dateTime = new Date(c.at).toISOString();
    return r;
  };
  const body = [];
  if (!items.length) {
    body.push(h("p", { class: "muted team-text", title: "What your colleagues share shows here when a round brings it in." }, "Nothing yet."));
  } else {
    if (fresh.length) {
      body.push(listGroup(null, ...fresh.map(row)),
        h("div", { class: "btn-row" }, button({ kind: "quiet", sm: true, icon: "check", id: "team-mark-seen", onClick: () => ctx.markSeen() }, "Mark as seen")));
    }
    if (older.length) {
      const d = teamFold("team-older", !fresh.length || ctx.open.has("older"),
        fresh.length ? `Seen before (${older.length})` : "Seen already", listGroup(null, ...older.map(row)));
      // (a fold drawn open fires "toggle" too: only a fold beside new things is remembered, 0.18 real poller)
      d.addEventListener("toggle", () => { if (!fresh.length) return; if (d.open) ctx.open.add("older"); else ctx.open.delete("older"); });
      body.push(d);
    }
  }
  const title = fresh.length ? `What came in (${p.unseen || fresh.length} new)` : "What came in";
  return section("came-in", title, ...body);
}

// The Team page: the people. Each a list row (docs/DESIGN.md 5.5): the person mark (and its role), the name, a quiet
// second line (since when, who keeps the storage space's keys; an attention tag when it needs you), and one control at
// the row's end: the owner's More menu (roles, and Remove from the team… for the copy that keeps the space's keys), or
// Remove… alone
function peopleSection(ctx) {
  const st = ctx.status;
  if (!st.folder) return null;
  const me = st.me || {};
  const people = st.people || [];
  const sp = st.space;   // 0.18.0rc2 (L6): the storage space's members are the same people
  const members = sp ? (sp.members || []).filter((m) => !m.removed) : [];
  const memberOf = (id) => (id ? members.find((m) => m.person === id && !m.me) || null : null);
  const removal = (m) => (sp && sp.keeper && m && !m.me ? { text: "Remove from the team…", icon: "x", onClick: () => removeMember(ctx, m) } : null);
  const control = (person, m) => {   // one control per row
    const r = removal(m);
    const more = ownerMarks(ctx, person, r ? [r] : []);
    if (more || !r) return [more].filter(Boolean);
    return [button({ kind: "quiet", sm: true, id: `space-remove-${m.part}`, onClick: r.onClick }, "Remove…")];
  };
  const withMember = (line, m) => {
    const bits = memberSub(m);
    if (!bits) return line;
    if (!line || !line.text) return { text: bits, warn: false };
    return line.warn ? line : { text: [line.text, " · ", bits], warn: false };
  };
  const mineM = members.find((m) => m.me);
  const mine = listRow({ person: ownerPerson(ctx, me, "you"), title: me.name ? `${me.name} (you)` : "You",   // 0.18 L2: ownerPerson, ownerMarks
    sub: [me.last_written_at ? `you last sent work ${whenPhrase(me.last_written_at)}` : "you have not sent work yet",
      mineM && memberSub(mineM) ? ` · ${memberSub(mineM)}` : null,
      me.name ? null : [" · ", link({ href: "#/projects" }, "add your name")]], actions: [ownerMarks(ctx, me)].filter(Boolean) });
  // roles: rows of one person stand together; the second line says who else they are, or that a Co-owner's ENLENS
  // is too old to act as one
  const rows = peopleRows(ctx, people).map((x) => {
    const m = memberOf(x.id);
    const line = withMember(personSub(ctx, x, personLine(x, st.problems || [])), m);
    return listRow({ person: ownerPerson(ctx, x, x.name), title: x.name || "a colleague", sub: line.text, warn: line.warn,   // 0.18 L2: ownerPerson, ownerMarks
      actions: control(x, m) });   // ownerMarks(ctx, x) with Remove from the team…
  });
  // in the storage space, not yet among the people (joined, nothing sent yet)
  const known = new Set(people.map((x) => x.id));
  const joined = members.filter((m) => !m.me && !known.has(m.person)).map((m) => listRow({ person: personMark([m.name]), title: m.name,
    sub: ["nothing sent yet", memberSub(m)].filter(Boolean).join(" · "), actions: control({ id: m.person, name: m.name }, m) }));
  const removed = sp ? (sp.members || []).filter((m) => m.removed) : [];
  const gone = removed.length ? h("p", { class: "muted small team-text" }, `Removed: ${removed.map((m) => m.name).join(", ")}. What they shared before stays in the project.`) : null;
  const both = st.other_computer ? h("div", { class: "btn-row" }, button({ sm: true, id: "team-page-both-computers", onClick: () => bothComputersDialog(ctx) }, "Use both computers…")) : null;
  /* 0.18 real poller: offline, the folder says nothing of who is in it (not "no colleague yet") */
  if (!people.length && st.reachable === false) {
    return section("people", "People", h("div", { class: "team-people" }, listGroup(null, mine, ...joined)),
      h("p", { class: "muted team-text" }, st.space ? "Your colleagues show here again once the storage space can be reached." : "Your colleagues show here again once the shared folder can be reached."), gone, both);
  }
  const join = people.length || st.space ? null : h("div", { class: "team-join" },   // (a storage space: its section invites)
    h("p", { class: "muted team-text" }, "No colleague has used this folder for this project yet. A colleague joins in three steps:"),
    h("ol", { class: "team-steps" },
      h("li", {}, "Send them what you shared (below), as a file."),
      h("li", {}, "They open it with Import a project, under Projects."),
      h("li", {}, "In their copy, the Team page offers the shared folder, ", h("strong", { class: "team-join-folder", title: st.folder }, folderAsSeen(st.folder, cloudAnswerNow()).text),
        ", as soon as it is among their cloud folders: they confirm it there.")));
  if (join && !cloudAnswerNow().length) cloudFolders().then((c) => {   // the cloud folder's name, when it arrives
    const el = document.querySelector(".team-join-folder");
    if (el && (c.folders || []).length) el.textContent = folderAsSeen(st.folder, c.folders).text;
  });
  const count = 1 + people.length + joined.length;
  return section("people", count > 1 ? `People (${count})` : "People",
    peopleNote(ctx), h("div", { class: "team-people" }, listGroup(null, mine, ...rows, ...joined)), gone, both, join);
}

function sharedSection(ctx) {
  const listing = ctx.sharing;
  if (!listing) return null;
  const mine = myShared(listing);
  const body = [];
  if (!mine.total) {
    body.push(h("p", { class: "muted team-text", title: "Share an item from its own page: a check, a set of themes, a codebook, a note, an entry of your own or a link between terms." }, "Nothing yet."));
  } else {
    for (const kind of Object.keys(KIND_MANY)) {
      const items = mine.byKind[kind];
      if (!items || !items.length) continue;
      const all = ctx.open.has(`kind:${kind}`);
      const shown = all ? items : items.slice(0, SHOWN_PER_KIND);
      const rows = shown.map((it) => listRow({ title: shortTitle(it.title || it.key, 90), href: itemHref(it),
        actions: [shareButton(it, () => ctx.refresh({ force: true }), { link: true, idPrefix: "team" })].filter(Boolean) }));
      const more = items.length > shown.length ? button({ kind: "quiet", sm: true, class: "team-more", id: `team-more-${kind}`,
        onClick: () => {   // the focus goes on to the first row that was not shown
          ctx.open.add(`kind:${kind}`);
          ctx.refresh({ force: true }).then(() => { const next = document.querySelector(`#team-kind-${kind} li:nth-child(${SHOWN_PER_KIND + 1}) a, #team-kind-${kind} li:nth-child(${SHOWN_PER_KIND + 1}) button`); if (next) next.focus(); });
        } }, `Show all ${items.length}`) : null;
      body.push(h("div", { class: "team-kind", id: `team-kind-${kind}` }, listGroup([KIND_MANY[kind], " ", tag({ kind: "count" }, String(items.length))], ...rows), more));
    }
  }
  if (mine.withdrawn) body.push(h("p", { class: "muted small team-text" }, `${plural(mine.withdrawn, "item")} you took back: colleagues keep what they had, marked as withdrawn.`));
  return section("shared", mine.total ? `What you shared (${mine.total})` : "What you shared",
    ...body, h("p", { class: "small team-help" }, helpMark("About sharing", SHARING_HELP), " Private until you share it."));
}

const NOT_HERE_HELP = "Your colleagues’ work names these documents, but they keep them out of the shared folder (marked Only a local AI or No AI). Add the same file under Documents: ENLENS recognises it by its content, keeps the stricter AI setting of the two, and puts their work on it at the next round.";
function notHereSection(ctx) {
  const list = ctx.status.not_here || [];
  if (!list.length) return null;
  return section("not-here", `Documents not on this computer (${list.length})`,
    h("p", { class: "muted small team-lead" }, "Kept out of the shared folder by a colleague.", helpMark("About documents not on this computer", NOT_HERE_HELP)),
    listGroup(null, ...list.map((d) => {
      // its title, "not on this computer" and Add its file (docs/DESIGN.md 5.5), which goes to the Documents page
      const doc = absentDocument(d.title || d.doc_id, { onAdd: () => navigate("#/sources") });
      const add = doc.querySelector("button");
      add.id = `team-add-${d.doc_id}`;
      add.setAttribute("aria-label", `Add the file of “${shortTitle(d.title || d.doc_id, 60)}” under Documents`);
      return listRow({ title: doc, sub: `kept out by ${d.from || "a colleague"}` });
    })));
}

function keepOutSection(ctx) {
  const st = ctx.status;
  if (!st.folder) return null;
  const ko = st.keep_out || {};
  const sw = teamSwitch("team-keep-out", KEEP_OUT_LABEL, !!ko.mine, null, { label: "About documents that stay here", text: KEEP_OUT_HELP });
  sw.input.addEventListener("change", async () => {
    const want = sw.input.checked;
    sw.input.disabled = true;
    try {
      const after = await api("PUT", `/api/projects/${P(ctx.project)}/shared-folder/keep-out`, { keep_out: want });
      const still = ((after.keep_out || {}).colleagues || []).length;
      toast(want ? "Documents marked Only a local AI or No AI stay out of the shared folder from the next round."
        : still ? "Your switch is off, but a colleague keeps it on, so it still holds for the whole team." : "Documents marked Only a local AI or No AI go into the shared folder from the next round, as the others do.", "ok", { small: true, ttl: 7000 });
      await ctx.refresh({ force: true });
      const again = document.getElementById("team-keep-out");   /* 0.18 real poller: the focus back on the switch */
      if (again) again.focus();
    } catch (e) {
      showError(e);
      sw.input.checked = !want;
      sw.input.setAttribute("aria-checked", sw.input.checked ? "true" : "false");
      sw.input.disabled = false;
    }
  });
  const them = ko.colleagues || [];
  /* 0.18 stage 5: while the folder cannot be read, the colleagues are those who had it on when it last could be */
  const because = ko.last_known
    ? `It is on for the whole team because ${them.join(" and ")} had it on when the shared folder could last be reached: while anyone keeps it on, it holds in every copy.`
    : `It is on for the whole team because ${them.join(" and ")} ${them.length === 1 ? "has" : "have"} it on: while anyone keeps it on, it holds in every copy.`;
  return section("keep-out", "Documents that stay on this computer", sw,
    !ko.mine && them.length ? notice({ kind: "info", role: "note" }, h("p", {}, because)) : null);
}

function downloadsSection(ctx) {
  const project = ctx.project;
  return section("downloads", ctx.status.folder ? "As a file" : "Or as a file",
    h("p", { class: "muted team-text" }, ctx.status.folder ? "For a colleague outside the team, or to move the project." : "By e-mail or a USB stick, without a storage space or folder."),
    h("ul", { class: "team-downloads" },
      h("li", {}, zipButton(project, "shared", { id: "team-zip-shared" }), h("span", { class: "muted small" }, ZIP_WORDS.shared.what)),
      h("li", {}, zipButton(project, "all", { id: "team-zip-all" }), h("span", { class: "muted small" }, ZIP_WORDS.all.what))));
}

function leaveSection(ctx) {
  const st = ctx.status;
  if (!st.folder) return null;
  // a quiet button: it asks first, and nothing is removed (docs/DESIGN.md 4.1: danger is for what removes)
  const sp = st.space;   // 0.18.0rc2 (L6): leaving a storage space on this computer is the same button
  const b = button({ kind: "quiet", sm: true, icon: "x", id: "team-leave" }, sp ? "Stop using the storage space here" : "Stop using this folder");
  b.addEventListener("click", async () => {
    const ok = await confirmDialog({ title: sp ? "Stop using the storage space here?" : "Stop using the shared folder?", confirmText: "Stop using it", danger: false,
      message: h("div", {}, h("p", {}, sp ? "This project stops sending your shared work to the team’s storage space and bringing in your colleagues’ from it, and this computer forgets its keys to it." : `This project stops sending your shared work to ${st.folder} and bringing in your colleagues’ from it.`),
        h("p", {}, sp ? (sp.keeper ? "Nothing in the storage space is removed, and what came in stays here. You keep its keys: hand the project to a colleague first, or your team cannot invite anyone any more." : "Nothing in the storage space is removed, and what came in stays here. To come back, ask the owner for a new invite.") : "Nothing in the folder is removed, and what came in stays here. You can choose the folder again later.")) });
    if (!ok) return;
    try {
      await api("DELETE", `/api/projects/${P(ctx.project)}/shared-folder`, {});
      toast(sp ? "This project no longer uses the storage space." : "This project no longer uses the shared folder.", "ok");
      await ctx.refresh({ force: true });
      ctx.focusHeading("space-setup");
    } catch (e) { showError(e); }
  });
  return section("leave", sp ? "Leave the storage space" : "Leave the shared folder", h("div", { class: "btn-row" }, b));
}
