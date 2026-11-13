// 0.17.0: the research log beside any page. A button fixed at the top right of the window opens a panel on the right:
// write an entry while looking at anything, and see the entries kept with the page you are on (or all of them).
// The whole log, with search, export and the rest, stays on its own page (#/log).
import { App, api, h, icon, clear, session, fmt, toast, showError, P, button, link, textarea, choice, tag, drawer, drawerButton, setDrawerOpen, teamLine } from "../lib.js";
import { subjectHref, entryText, entrySubject, entryWho } from "./log.js";
import { whenText } from "./team-state.js";

const PAGE = 30;
const GROUP_ICON = { entries: "note", documents: "book-open", checks: "flask", themes: "shapes", codebooks: "book-marked",
  history: "undo", together: "users", other: "circle" };
const NOTHING_HERE = "Nothing is kept with this page; showing all";

// Which part of the log belongs to the page at this hash. {subject_kind, subject_id} for one item, {group} for a place
// (a list of things), null for a page that has none (Overview, Search, Concepts, Settings...). `label` finishes
// "Kept with: ...". `place` pages write their entries with no subject.
export function pageContext(hash) {
  const path = String(hash || "").replace(/^#/, "").split("?")[0].replace(/\/+$/, "");
  const parts = path.split("/").filter(Boolean).map((s) => { try { return decodeURIComponent(s); } catch (_) { return s; } });
  const [a, id] = parts;
  if (a === "h" && id) return { subject_kind: "check", subject_id: id, label: "this hypothesis" };
  if (a === "doc" && id) return { subject_kind: "document", subject_id: id, label: "this document" };
  if (a === "themes" && id) return { subject_kind: "themes", subject_id: id, label: "these themes" };
  if (a === "codebooks" && id) return { subject_kind: "codebook", subject_id: id, label: id };
  const place = { sources: "documents", notes: "documents", bibliography: "documents", hypotheses: "checks", check: "checks",
    batch: "checks", history: "checks", map: "checks", themes: "themes", profile: "codebooks", codebooks: "codebooks" }[a];
  if (place && parts.length === 1) return { group: place, label: "the project" };
  return null;
}

// What the team line says (lib.js teamLine().set()), from the poller's answer (GET …/sync-poller) and what is new on the
// Team tab: the first that holds of a round running, offline, the last round not working, paused, what is new, when
// the last round was, no round yet.
export function teamWords(s, count = 0, now = new Date()) {
  const r = s && s.round;
  if (!s) return { kind: "ok", words: "no round yet" };
  if ((r && (r.state === "running" || r.state === "queued")) || s.state === "due") return { kind: "running", words: "syncing now…" };
  if (s.state === "offline" || s.offline) return { kind: "attention", words: "offline" };
  if (s.last_round && s.last_round.state === "error") return { kind: "attention", words: "round did not work" };
  if (s.paused || s.paused_all) return { kind: "ok", words: "paused" };
  if (count > 0) return { kind: "ok", count: `${count} new` };
  if (s.last_round) return { kind: "ok", words: syncedWords(s.last_round.finished_at, now) };
  return { kind: "ok", words: "no round yet" };
}
// "synced 15:44" (today), "synced yesterday", "synced 12 Nov" (from whenText's "Today 15:44", "Yesterday …", "12 Nov …")
function syncedWords(t, now) {
  const w = whenText(t, now);
  if (!w) return "synced";
  if (w.startsWith("Today ")) return `synced ${w.slice(6)}`;
  if (w.startsWith("Yesterday ")) return "synced yesterday";
  return `synced ${w.slice(0, w.lastIndexOf(" "))}`;
}

export function initLogDrawer() {
  if (document.getElementById("logdrawer")) return;
  const shell = document.getElementById("shell");
  if (!shell) return;
  const body = document.body;
  let open = false;
  let mode = session("logdrawer-mode") === "all" ? "all" : "page";
  let shown = PAGE;
  let token = 0;               // the newest refresh wins
  const docTitles = new Map(); // "project, document" -> its title, each asked for once when a document page is the context

  // ---- the two doors (docs/DESIGN.md 4.19 and 5.1): the button opens the Research log tab (the drawer component's
  // button), the team line under the project's name opens the Team tab; each is soft teal while its own tab shows.
  // Under 861 px the button carries the Team tab's count ("3 new") while news waits, and then opens that tab.
  const phone = () => window.matchMedia("(max-width: 860px)").matches;
  let teamCount = 0;            // what is new on the Team tab
  let sync = null;              // the poller's last answer for this project (app.js, "enlens-sync-state")
  const phoneCount = () => phone() && teamCount > 0;
  const btn = drawerButton({ id: "logdrawer-btn", controls: "logdrawer", label: "Research log", icon: "notebook",
    title: "The research log, beside this page", onClick: () => press(phoneCount() ? "team" : "log", btn) });
  const btnCount = tag({ kind: "count", class: "tab-count" }, "");
  const placeCount = () => {
    if (phoneCount()) { btnCount.textContent = `${teamCount} new`; if (btnCount.parentNode !== btn) btn.appendChild(btnCount); }
    else btnCount.remove();
  };
  const placeBtn = () => {
    const bar = document.getElementById("topbar");
    if (phone() && bar) { if (btn.parentNode !== bar) bar.appendChild(btn); }
    else if (btn.parentNode !== body) {
      const skip = document.querySelector(".skip-link");
      if (skip) skip.after(btn); else body.prepend(btn);
    }
    placeCount();
    markDoors();
  };
  const teamBtn = teamLine({ id: "team-line", controls: "logdrawer", onClick: () => press("team", teamBtn) });
  teamBtn.hidden = true;        // until the poller says this project has a team
  // the project switch's second row (app.js renderProjectSwitch keeps it across redraws)
  const placeTeamLine = () => {
    const box = document.getElementById("project-switch");
    if (box && box.lastElementChild !== teamBtn) box.appendChild(teamBtn);
  };
  const drawTeam = () => { if (sync) teamBtn.set(teamWords(sync, teamCount)); };
  // pressing a door: closed, it opens on its tab; open on its tab, it closes; open on the other tab, that tab shows
  function press(which, door) {
    if (!open) { tab = which; openIt(true); }
    else if (tab === which) close(true, door);
    else { tabRow.choose(which); tabOf(which).focus(); }
  }
  // each door is expanded while its own tab shows; under 861 px the top bar's button whenever the drawer is open
  function markDoors() {
    btn.setAttribute("aria-expanded", open && (tab === "log" || phone()) ? "true" : "false");
    teamBtn.setAttribute("aria-expanded", open && tab === "team" ? "true" : "false");
  }

  // ---- the drawer: its frame is the drawer component; its parts are the Research log page's own (the write box and
  // the list of entries, .log-new and .log-entries), so an entry looks the same on the page and here
  const which = choice({ label: "Show entries of", filter: true, sm: true, value: mode, options: [["page", "This page"], ["all", "All"]],
    onPick: (v) => { mode = v; session("logdrawer-mode", mode); shown = PAGE; refresh(); } });
  const pageBtn = which.querySelector('[data-value="page"]');
  const ta = textarea({ class: "logdrawer-text", rows: 3, maxlength: 10000, "aria-label": "A new research-log entry", placeholder: "A decision and why…" });
  const keptWith = h("p", { class: "muted small logdrawer-kept" });
  const addBtn = button({ kind: "main", sm: true, onClick: add }, "Add to the log");
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); add(); } });
  const note = h("p", { class: "muted small", hidden: true });
  const list = h("div", { class: "logdrawer-list", "aria-live": "polite" });
  /* 0.18 Team tab: the drawer's two tabs, Research log and Team (views/team.js, loaded when first shown), in the drawer
     component's head (docs/DESIGN.md 4.19). The log's sections are the "log" tab's, unchanged; the Team panel is the
     "team" tab's one section. The drawer's body is the tabs' panel: drawer({ tabs }) makes them with tabs({ onTab, panel }). */
  let tab = session("logdrawer-tab") === "team" ? "team" : "log";
  let team = null;             // the Team panel (team.js), made the first time the tab is shown
  // each tab keeps a heading for a screen reader's list of headings (the tabs show the names)
  // This page | All filters the log's entries only, so it is the log tab's own (above its entries), not the drawer
  // head's: with two tabs, the head holds the tabs and the close button
  const logSections = [h("div", { class: "log-new" }, h("h2", { class: "visually-hidden" }, "Research log"), ta, h("div", { class: "log-new-foot" }, keptWith, addBtn)),
    h("div", { class: "log-show" }, which, note), list];
  const teamPanelBox = h("div", { class: "logdrawer-team" }, h("h2", { class: "visually-hidden" }, "Team"));
  const aside = drawer({ id: "logdrawer", title: "Research log and team", current: tab, onTab: showTab,
    tabs: [{ key: "log", label: "Research log", icon: "notebook" }, { key: "team", label: "Team", icon: "users" }],
    onClose: () => close(true), closeLabel: "Close the panel", sections: logSections,
    foot: [link({ href: "#/log" }, "The whole research log"), h("span", { class: "muted" }, " on the Overview")] });
  const closeBtn = aside.closeButton;
  // the drawer's tabs are tabs({ onTab, panel }) (lib.js, docs/DESIGN.md 4.5): ids, aria-controls, the panel (the
  // drawer's body), only the chosen tab in the Tab order, and the arrow keys, Home and End come with them
  const tabRow = aside.tabs;
  const tabOf = (key) => tabRow.querySelector(`[data-key="${key}"]`);
  const foot = aside.querySelector(".drawer-foot");       // its one link, to the whole research log: the log tab's
  // what came in and was not seen yet (team.js, or the poller's news before the tab was first shown), in words on the
  // Team tab: "3 new" (a drawer tab's count, docs/DESIGN.md 4.5 and 5.5)
  let countFor = App.project;   // the project the count is of
  // the same count on the team line and, under 861 px, in the button
  const setTeamCount = (n) => { teamCount = n || 0; tabRow.setCount("team", n ? `${n} new` : null); placeCount(); drawTeam(); };
  window.addEventListener("enlens-sync-news", (e) => { if (!team && e.detail && e.detail.project === App.project) setTeamCount((e.detail.came_in || {}).count || 0); });
  // the poller's state after each of app.js's looks (null when it could not look): the team line shows in a project
  // with a team, and says its state
  window.addEventListener("enlens-sync-state", (e) => {
    const s = e.detail;
    if (!s || s.project !== App.project) return;
    sync = s;
    teamBtn.hidden = !s.folder;
    placeTeamLine();
    // before the Team tab was first shown, what came in is the poller's count (the tab's own, once it is made)
    if (!team && s.folder) setTeamCount((s.came_in || {}).count || 0); else drawTeam();
  });
  // draws the tab chosen (tabs() calls it when a tab is pressed or chosen by its keys; code chooses with tabRow.choose)
  function showTab(value) {
    tab = value === "team" ? "team" : "log";
    session("logdrawer-tab", tab);
    markDoors();
    foot.hidden = tab !== "log";
    aside.setSections(tab === "team" ? [teamPanelBox] : logSections);
    if (tab === "team") {
      if (!team) {
        import("./team.js").then((m) => {
          team = m.teamPanel({ onCount: setTeamCount });
          teamPanelBox.appendChild(team.el);
          if (open && tab === "team") { team.show(); focusWanted(); }
        }).catch((e) => { teamPanelBox.textContent = `The Team tab could not be loaded (${e.message}).`; });
      } else if (open) { team.show(); focusWanted(); }
    } else {
      if (team) team.hide();
      if (open) refresh();
    }
  }
  // another page opens the drawer on a tab: window.dispatchEvent(new CustomEvent("enlens-drawer", {detail: {tab: "team"}}));
  // detail.section: a section of the Team tab to bring into view once it has drawn ("shared": What you shared)
  let wantSection = null;
  const focusWanted = () => {
    if (!wantSection || !team || !open || tab !== "team") return;
    const key = wantSection;
    wantSection = null;
    team.focusSection(key);
  };
  window.addEventListener("enlens-drawer", (e) => {
    tab = (e.detail && e.detail.tab) === "team" ? "team" : "log";
    wantSection = (tab === "team" && e.detail && e.detail.section) || null;
    if (open) tabRow.choose(tab); else openIt(false);
    tabOf(tab).focus();
  });
  /* end 0.18 Team tab */
  shell.appendChild(aside);
  placeBtn();
  placeTeamLine();
  window.matchMedia("(max-width: 860px)").addEventListener("change", placeBtn);

  const overlay = () => window.matchMedia("(max-width: 999px)").matches;

  function openIt(byUser) {
    open = true;
    session("logdrawer-open", true);
    aside.hidden = false;
    setDrawerOpen(true, null);
    markDoors();
    tabRow.choose(tab);   // 0.18 Team tab: reads the tab shown (the log's refresh, or the team's)
    if (byUser) (window.matchMedia("(max-width: 860px)").matches ? closeBtn : tab === "team" ? tabOf("team") : ta).focus();
  }
  function close(returnFocus, door) {
    const hadFocus = aside.contains(document.activeElement);
    open = false;
    session("logdrawer-open", false);
    if (team) team.hide();   // 0.18 Team tab
    aside.hidden = true;
    setDrawerOpen(false, null);
    markDoors();
    if (returnFocus || hadFocus) (door && !door.hidden && door.isConnected ? door : btn).focus();
  }

  // ---- what this page is
  const context = () => pageContext(location.hash);
  async function titleOf(ctx) {
    if (!ctx || ctx.subject_kind !== "document") return ctx && ctx.label;
    const project = App.project;
    const key = `${project}\n${ctx.subject_id}`;
    if (!docTitles.has(key)) {
      try {   // the one document, not the whole list of them
        const r = await api("GET", `/api/projects/${P(project)}/documents/${P(ctx.subject_id)}?limit=1`);
        docTitles.set(key, r.title || null);
      } catch (_) { /* the words "this document" do */ }
    }
    return docTitles.get(key) || ctx.label;
  }

  // ---- reading
  async function refresh() {
    if (!open || !App.project || tab !== "log") return;   // 0.18 Team tab: the log reads itself only when it is shown
    const mine = ++token;
    const project = App.project;
    const ctx = context();
    const name = await titleOf(ctx);
    if (mine !== token) return;
    keptWith.textContent = `Kept with: ${ctx ? name : "the project"}`;
    const base = `/api/projects/${P(project)}/log`;
    const query = (filter) => {
      const qs = new URLSearchParams({ limit: String(shown) });
      if (filter) for (const [k, v] of Object.entries(filter)) if (v && ["group", "subject_kind", "subject_id"].includes(k)) qs.set(k, v);
      return `${base}?${qs}`;
    };
    let data, fellBack = false;
    try {
      if (mode === "page" && ctx) {
        data = await api("GET", query(ctx));
        if (mine !== token) return;
        if (!data.entries.length) { fellBack = true; data = await api("GET", query(null)); }
      } else {
        fellBack = mode === "page";
        data = await api("GET", query(null));
      }
    } catch (e) {
      if (mine !== token) return;
      clear(list);
      list.appendChild(h("p", { class: "muted small" }, "The log could not be read. ", button({ kind: "quiet", sm: true, onClick: refresh }, "Try again")));
      return;
    }
    if (mine !== token) return;
    const showingAll = mode === "all" || fellBack;
    which.set(showingAll ? "all" : "page");
    pageBtn.disabled = !ctx;
    note.hidden = !fellBack;
    note.textContent = fellBack ? NOTHING_HERE : "";
    draw(data, ctx, showingAll);
  }

  function draw(data, ctx, showingAll) {
    clear(list);
    if (!data.entries.length) {
      list.appendChild(h("p", { class: "muted small" }, "Nothing in the log yet. Write the first entry above."));
      return;
    }
    const here = location.hash.split("?")[0];
    const ol = h("ol", { class: "log-entries" });
    for (const e of data.entries) {
      const href = subjectHref(e);
      const to = href && href !== here && !(ctx && ctx.subject_id && !showingAll) ? href : null;
      ol.appendChild(h("li", { class: "log-entry" + (e.kind === "entry" ? " log-own" : "") },
        h("span", { class: "log-icon", "aria-hidden": "true" }, icon(GROUP_ICON[e.group] || "circle", { size: 14 })),
        h("div", { class: "log-body" },
          h("div", { class: "log-meta" }, h("time", { class: "log-time", datetime: e.at, title: fmt.date(e.at) }, fmt.whenText(e.at)), entryWho(e)),
          entryText(e, to),
          e.why ? h("div", { class: "log-why" }, `Why: ${e.why}`) : null,
          entrySubject(e, to) ? h("div", { class: "log-meta" }, entrySubject(e, to)) : null)));
    }
    list.appendChild(ol);
    if (data.total > data.entries.length) {
      list.appendChild(h("div", { class: "logdrawer-more" }, button({ kind: "quiet", sm: true,
        onClick: () => { shown += PAGE; refresh(); } }, `Show more (${fmt.num(data.total - data.entries.length)} older)`)));
    }
  }

  // ---- writing
  async function add() {
    const text = ta.value.trim();
    if (!text) { ta.focus(); return; }
    const ctx = context();
    const payload = { text };
    if (ctx && ctx.subject_kind) {
      payload.subject_kind = ctx.subject_kind;
      payload.subject_id = ctx.subject_id;
      if (ctx.subject_kind === "codebook") payload.title = ctx.subject_id;
      else if (ctx.subject_kind === "document") { const t = await titleOf(ctx); if (t && t !== ctx.label) payload.title = t; }
    }
    addBtn.disabled = true;
    try {
      await api("POST", `/api/projects/${P(App.project)}/log`, payload);
      ta.value = "";
      shown = PAGE;
      toast("Added to the research log.", "ok");
      await refresh();
    } catch (e) { showError(e); } finally { addBtn.disabled = false; }
  }

  // ---- when to read again, and when to close
  window.addEventListener("hashchange", () => { shown = PAGE; refresh(); });
  App.onChange(() => {
    if (open) { shown = PAGE; refresh(); }
    // 0.18 Team tab: another project's count is not this one's; the Team panel reads the new project's (even hidden)
    // the team line hides until the poller's state of the new project arrives
    if (App.project !== countFor) { countFor = App.project; sync = null; teamBtn.hidden = true; setTeamCount(0); if (team) team.refresh(); }
    else if (open && team && tab === "team") team.refresh();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && open && !e.defaultPrevented && !document.querySelector("#dialogs dialog[open]")) close(aside.contains(document.activeElement)); });
  document.addEventListener("click", (e) => {
    if (open && overlay() && !aside.contains(e.target) && !btn.contains(e.target) && !teamBtn.contains(e.target) && !e.target.closest(".sidebar, .topbar, .toasts, #dialogs")) close(false);
  });

  if (session("logdrawer-open") === true) openIt(false);
}
