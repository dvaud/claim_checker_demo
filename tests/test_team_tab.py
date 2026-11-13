"""0.18.0 (roadmap L4, with L3 and L5): the Team tab of the right-hand panel (views/team.js, views/team-state.js,
the block "Working together" of views.css, the tabs in views/logdrawer.js).

- the files and how they are wired: its look in 0.17.0's stylesheets (components from components.css, the tab's own
  pieces placed in views.css), the drawer's two tabs (keyboard and screen reader),
  team.js loaded the first time the tab is shown, the sections in order with room for L2;
- the words the brief asks for (the set-up's promise, the switch, the two downloads, a colleague's switch);
- what the tab works out, run in Node when it is installed: the poller's state (the 3-poller contract, and the
  stand-in until it is merged), the sync line, what came in, what you shared, a colleague's line, a pasted path;
- the app's answers have the fields the tab reads (the shared folder and the sharing listing, through the API).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from _static import release_sheets
from test_app import api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static"
TEAM = (STATIC / "views" / "team.js").read_text(encoding="utf-8")
STATE = (STATIC / "views" / "team-state.js").read_text(encoding="utf-8")
DRAWER = (STATIC / "views" / "logdrawer.js").read_text(encoding="utf-8")
VIEWS = (STATIC / "views.css").read_text(encoding="utf-8")
# 0.17.0 (design guide): team.css and the Team tab's part of navigation.css are folded into views.css, one block
CSS = VIEWS[VIEWS.index("/* ==== Working together */"):VIEWS.index("/* ==== Quick look */")]
COMPONENTS = (STATIC / "components.css").read_text(encoding="utf-8")


def _no_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


# ------------------------------------------------------------------ files and wiring
def test_the_team_tab_has_its_block_in_the_views_stylesheet():
    # 0.17.0 (design guide): no stylesheet of its own; the components look as everywhere (components.css), and the
    # tab's own pieces are placed in views.css's block "Working together"
    sheets = release_sheets()
    assert "/static/team.css" not in sheets and not (STATIC / "team.css").exists() and "/static/views.css" in sheets
    css = _no_comments(CSS)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and "rgb(" not in css and "hsl(" not in css  # tokens only
    for sel in re.findall(r"\.([a-z][\w-]*)", css):
        assert sel.split("-")[0] in {"team", "share", "owner", "page", "result", "field", "switch", "ai", "work", "input",
                                     "notice", "list", "chip", "warn"} or sel in {"team"}, sel


def test_the_drawer_has_two_tabs_in_a_marked_block():
    block = DRAWER[DRAWER.index("/* 0.18 Team tab"):DRAWER.index("/* end 0.18 Team tab */")]
    # 0.17.0 (design guide 4.5): tabs without an address are the whole tab pattern, made by tabs({ onTab, panel }) in
    # lib.js; drawer({ tabs }) makes its tabs with it and the drawer's body is their panel. Before, this block made the
    # roles, ids, aria-controls, roving tabindex and keys by hand and these checks read them here; they now read them
    # in the one helper that makes them (and test_place_pieces.py keeps any page from spelling them).
    lib = (STATIC / "lib.js").read_text(encoding="utf-8")
    tabs_fn = lib[lib.index("export function tabs("):]
    tabs_fn = tabs_fn[:tabs_fn.index("\n}\n")]
    drawer_fn = lib[lib.index("export function drawer("):]
    drawer_fn = drawer_fn[:drawer_fn.index("\n}\n")]
    assert 'tabs: [{ key: "log", label: "Research log", icon: "notebook" }, { key: "team", label: "Team", icon: "users" }]' in block
    assert 'drawer({ id: "logdrawer"' in block and "onTab: showTab" in block and "const tabRow = aside.tabs;" in block
    assert 'tabs({ class: "drawer-tabs", label: title, items: tabItems, current, panel: body, onTab:' in drawer_fn
    assert 'role: asButtons ? "tablist" : null' in tabs_fn and 'role: "tab"' in tabs_fn and "withClass(UI.tabs" in tabs_fn
    assert 'tabs: "settings-tabs"' in lib                                  # in the view tabs' look
    assert 'panel.setAttribute("role", "tabpanel")' in tabs_fn            # the drawer's body is the tabs' panel
    assert '"aria-selected"' in tabs_fn and '"aria-controls"' in tabs_fn and '"aria-labelledby"' in tabs_fn
    assert "ArrowRight" in tabs_fn and "Home" in tabs_fn and "End" in tabs_fn   # keys move between the tabs
    assert "b.tabIndex = on ? 0 : -1;" in tabs_fn                         # only the chosen tab in the Tab order
    assert 'import("./team.js")' in block                                 # loaded the first time it is shown
    assert 'session("logdrawer-tab"' in block and "enlens-drawer" in block and "enlens-sync-news" in block
    assert "tabRow.choose(tab)" in block                                  # another page opens it on a tab
    assert not re.search(r"^import .*team\.js", DRAWER, flags=re.M)        # never a static import (Node test of the drawer)
    assert 'tab !== "log"' in DRAWER                                       # the log reads itself only when shown
    # the tab shown says so (aria-selected, which the view tabs' look reads); each tab draws its own sections in the
    # drawer's body
    assert 'b.setAttribute("aria-selected", on ? "true" : "false")' in tabs_fn
    assert 'aside.setSections(tab === "team" ? [teamPanelBox] : logSections)' in block
    assert '.settings-tabs [role="tab"][aria-selected="true"]' in COMPONENTS
    # what came in, in words on the Team tab (DESIGN.md 4.5, 5.5: "Team · 3 new", never a bare number)
    assert 'tabRow.setCount("team", n ? `${n} new` : null)' in block and "row.setCount = (key, words)" in tabs_fn


def _keys(name):
    start = TEAM.index(f"export const {name} = [")
    return re.findall(r'\{ key: "([a-z-]+)", render: \w+ \}|^  ([A-Z_]+_SECTION),', TEAM[start:TEAM.index("];", start)], flags=re.M)


def test_the_sections_come_in_order_with_room_for_the_owner():
    # the Team tab keeps the day-to-day; roles (DESIGN-roles §5, mock-up B): a folder problem that stops this copy
    # ("stop") comes before everything else
    assert [a or b for a, b in _keys("TEAM_SECTIONS")] == ["setup", "stop", "state", "problems", "came-in", "shared", "not-here"]
    assert "export function addTeamSection" in TEAM and 'before: "state"' in TEAM and "Waiting for your word" in TEAM
    assert "export function teamPanel" in TEAM and "show()" in TEAM and "hide()" in TEAM
    # the Team page (#/team) is the team itself: set-up, where it is, the people, the owner, the settings, leaving
    assert [a or b for a, b in _keys("TEAM_PAGE_SECTIONS")] == ["SPACE_SETUP_SECTION", "setup", "folder", "SPACE_SECTION", "people",
                                                                 "ROLES_SECTION", "keep-out", "often", "downloads", "leave"]
    assert "export function renderTeam(view)" in TEAM and "teamPanel({ sections: TEAM_PAGE_SECTIONS, page: true })" in TEAM
    assert "panel.destroy()" in TEAM and 'window.removeEventListener("enlens-sync-news", news)' in TEAM
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'import("./views/team.js").then((m) => m.renderTeam(view, params, query))' in app   # loaded when first opened
    assert '"/team": "Team"' in app
    # the tab links to the page in one quiet line: "Backblaze · 3 people · Manage the team"
    assert 'link({ href: "#/team", id: "team-manage" }, "Manage the team")' in TEAM and "teamSummary(st)" in TEAM


def test_the_tab_keeps_the_day_to_day_and_the_page_the_team():
    """The owner's request (after 0.18.0rc3): joining a team is in the project menu, the team is managed on its own
    page, and the Team tab says little: states, counts and buttons, the longer words behind help marks and folds."""
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    design = (STATIC / "views" / "design.js").read_text(encoding="utf-8")
    setup = (STATIC / "views" / "setup.js").read_text(encoding="utf-8")
    owner = (STATIC / "views" / "owner.js").read_text(encoding="utf-8")
    space = (STATIC / "views" / "team-space.js").read_text(encoding="utf-8")
    # the project menu: Join a team… right under New project…, above Manage projects; then Manage the team
    menu = app[app.index("function renderProjectSwitch()"):app.index("export async function switchProject")]
    assert (menu.index('"New project…"') < menu.index('{ text: "Join a team…", icon: "link", onClick: () => joinDialog(null) }')
            < menu.index('"Manage projects"') < menu.index('{ text: "Manage the team", icon: "users", href: "#/team" }'))
    assert '{ text: "Join a team…", icon: "link" }' in design and '"Manage the team"' in design   # the live reference
    assert "joinDialog(null)" in setup                                     # a first run can start from an invite
    # the tab: nothing waits, no section; empty states in two words; the switches and the set-up on the page
    assert "return null;   // nothing waits: no section" in owner and "if (v.is_owner) body.push(acceptAddsSwitch(ctx, v));" in owner
    assert owner.index("function rolesSection(") < owner.index("if (v.is_owner) body.push(acceptAddsSwitch(ctx, v));")
    assert 'helpMark("About accepting documents at once", ACCEPT_ADDS_HELP)' in owner
    assert TEAM.count('}, "Nothing yet.")') == 2 and "Nothing yet. What your colleagues share" not in TEAM
    assert '{ label: "About documents that stay here", text: KEEP_OUT_HELP }' in TEAM
    assert 'helpMark("About documents not on this computer", NOT_HERE_HELP)' in TEAM
    assert '"Your colleague’s folder is not here yet?"' in TEAM           # the OneDrive how-to in a fold by the field
    assert 'helpMark("About storage spaces", SPACE_HELP)' in space and '"A storage space (recommended)"' in space
    # the sync state in one line: its second line only when it needs you, else the tooltip
    assert 'const SAY_SUB = new Set(["running", "busy", "offline", "failed", "never"]);' in TEAM and "ws.title = s.sub;" in TEAM
    tab = TEAM[TEAM.index("function stateSection(ctx) {"):TEAM.index("// The Team page: how often rounds run")]
    assert "team-every" not in tab and "team-pause-all" not in tab and '"team-pause"' in tab and '"team-sync-now"' in tab


def test_no_inline_look_and_no_link_drawn_as_a_button():
    for name, js in (("team.js", TEAM), ("team-state.js", STATE), ("share.js", (STATIC / "views" / "share.js").read_text(encoding="utf-8"))):
        assert "style:" not in js and ".style." not in js, name
        assert not re.search(r'h\("a", \{[^}]*class: "btn', js), name


def test_the_words_of_the_brief():
    assert "The folder will hold the documents’ text and files, and only what you share of your own work. " in TEAM
    assert "Keep documents marked Only a local AI or No AI out of the shared folder" in TEAM
    assert "It is on for the whole team because" in TEAM
    assert "Mark as seen" in TEAM and "Sync now" in TEAM and "Stop using this folder" in TEAM
    # a document not on this computer: absentDocument() (lib.js), with "Add its file", to the Documents page
    assert "absentDocument(d.title || d.doc_id, { onAdd: () => navigate(\"#/sources\") })" in TEAM
    assert '"Add its file"' in (STATIC / "lib.js").read_text(encoding="utf-8")
    assert "Pause" in TEAM and "Resume" in TEAM and "How often ENLENS looks" in TEAM
    assert "C:\\\\Users\\\\Anna" in TEAM and "/Users/anna/" in TEAM          # a path for Windows and for a Mac
    # the server's refusal is shown as it is, by the field
    assert "if (e.status === 400) showErr(e.message);" in TEAM and 'role: "alert", id: "team-folder-error"' in TEAM
    # (final check: choosing the folder again never turns the switch off by itself; untouched, it is not sent)
    assert ('typed.keepOut === null ? { path: p } : { path: p, keep_out: typed.keepOut }' in TEAM
            and 'typed.keepOut ?? !!(st.keep_out || {}).mine' in TEAM and 'keepOut: null' in TEAM)
    assert 'api("DELETE", `/api/projects/${P(ctx.project)}/shared-folder`' in TEAM
    assert 'api("POST", `/api/projects/${P(ctx.project)}/shared-folder/sync`' in TEAM
    assert 'api("PUT", `/api/projects/${P(ctx.project)}/shared-folder/keep-out`, { keep_out: want })' in TEAM
    assert 'zipButton(project, "shared", { id: "team-zip-shared" })' in TEAM and 'zipButton(project, "all"' in TEAM


def test_the_panel_redraws_only_what_changed_and_keeps_the_place():
    """A redraw under a hand lost what was typed and moved the focus (the independent review): the panel draws again only
    when the app's answers changed, keeps what was typed in the set-up, finds the focus again by id, and follows only
    its own project's round."""
    assert "if (force || sig !== drawn) { drawn = sig; draw(); } else updateLine();" in TEAM
    assert "typed.path = path.value" in TEAM and "value: typed.path" in TEAM and "typed.error" in TEAM
    assert 'fa.matches("input[type=text], textarea, select")' in TEAM
    assert "document.getElementById(had.id)" in TEAM and "textContent.trim() === keep.text" not in TEAM
    assert "(j.project && j.project !== project)" in TEAM and "if (watching) { watching.w.stop(); watching = null; }" in TEAM
    assert "e.status === 404 ? null : prev" in TEAM                       # only a 404 means "no poller yet"
    assert 'role: "status", "aria-live": "polite"' in TEAM and '["offline", "paused", "failed"]' in TEAM
    for i in ("team-keep-out", "team-pause-all", "team-setup-keep-out", "team-sync-now", "team-mark-seen", "team-leave"):
        assert f'"{i}"' in TEAM, i
    assert 'ctx.focusHeading("state")' in TEAM and 'ctx.focusHeading("space-setup")' in TEAM and 'ctx.focusHeading("folder")' in TEAM
    assert "setTeamCount(0); if (team) team.refresh();" in DRAWER         # another project: its own count
    assert 'h("h2", { class: "visually-hidden" }, "Team")' in DRAWER and 'closeLabel: "Close the panel"' in DRAWER


def test_the_poller_is_read_through_its_announced_paths():
    for path in ("/api/projects/${p}/sync-poller", "/api/projects/${p}/sync-poller/seen", '"/api/sync-poller"'):
        assert path in STATE, path
    assert "POLLER_API.state(P(project))" in TEAM and "POLLER_API.seen(P(ctx.project))" in TEAM
    assert "every_minutes" in TEAM and "{ through: ctx.poll.newest_id }" in TEAM
    assert not re.search(r"^import ", STATE, flags=re.M)  # no imports: it runs in Node


# ------------------------------------------------------------------ what the tab works out (Node)
NODE = r"""
import * as T from "./team-state.js";
const NOW = Date.parse("2026-11-11T10:00:00Z");
const iso = (s) => new Date(NOW + s * 1000).toISOString();
const ben = { id: "p8ce2bc0af2e9", name: "Ben Okafor" };
const status = { folder: "/x", reachable: true, problems: [], people: [{ id: ben.id, name: "Ben Okafor", app_version: "0.18.0",
  waiting: 0, last_read_at: iso(-300) }], me: { last_written_at: iso(-600) }, job: null,
  last_round: { state: "done", finished_at: (NOW - 60000) / 1000, result: { at: iso(-60), read: [
    { id: ben.id, name: "Ben Okafor", report: { lines: ["From Ben Okafor: 1 new result."] } },
    { id: "pc0ffeec0ffee", name: "Chloé", report: { lines: ["Nothing new: this copy already has everything in Chloé's file."] } }] } } };
const history = [{ at: iso(-60), from: ben, lines: ["From Ben Okafor: 1 new result."] },
                 { at: iso(-7200), from: ben, lines: ["1 note of Ben Okafor's came in."] },
                 { at: iso(-9000), from: ben, lines: ["Nothing new: this copy already has everything in Ben Okafor's file."] }];
const poller = { project: "Demo", folder: true, paused: false, paused_all: false, state: "waiting", every_seconds: 120,
  next_round_at: iso(100), next_round_in: 100, offline: null, busy: null, round: null,
  last_round: { job: "j1", background: true, state: "done", finished_at: iso(-30), offline: false, problems: [], came_in: 2, error: null },
  came_in: { count: 2, seen_through: 4, rounds: [{ id: 5, at: iso(-30), from: ben, bundles: [3, 3], lines: ["From Ben Okafor: 1 new result."], count: 2 }] } };
const out = {};
// the stand-in: the round of this app, the project's history, what was seen in this browser
const s1 = T.pollerState(status, null, null, null);
out.standin = { live: s1.live, auto: s1.auto, last_at: s1.last_at, came: s1.came_in.map((c) => [c.from, c.lines, c.seen]), unseen: s1.unseen };
const s2 = T.pollerState(status, NOW - 3600000, history, null);
out.history = { came: s2.came_in.map((c) => [c.lines[0], c.seen]), unseen: s2.unseen };
const s3 = T.pollerState({ ...status, last_round: null }, null, null, null);
out.lastFromFolder = s3.last_at === NOW - 300000;
// the poller (3-poller's contract): what came in since you last looked, then what was seen before (the history)
const live = T.pollerState(status, null, history, poller);
out.live = { live: live.live, auto: live.auto, paused: live.paused, next_at: live.next_at, unseen: live.unseen, newest: live.newest_id,
  came: live.came_in.map((c) => [c.lines[0], c.seen]), every: live.every };
out.lines = {
  waiting: T.syncLine(status, live, NOW),
  offline: T.syncLine(status, T.pollerState(status, null, null, { ...poller, state: "offline", offline: { since: iso(-600), failures: 3, retry_seconds: 480 }, next_round_at: iso(470) }), NOW),
  offlineStandin: T.syncLine({ ...status, reachable: false, problems: [{ kind: "unreachable", message: "x" }] }, null, NOW),
  paused: T.syncLine(status, T.pollerState(status, null, null, { ...poller, state: "paused", paused: true }), NOW),
  pausedAll: T.syncLine(status, T.pollerState(status, null, null, { ...poller, state: "paused", paused_all: true }), NOW),
  busy: T.syncLine(status, T.pollerState(status, null, null, { ...poller, state: "busy", busy: { id: "j", kind: "read-new", title: "Reading", message: "Queued: starts when “Reading” has finished" } }), NOW),
  running: T.syncLine({ ...status, job: { id: "r", state: "running", progress: { message: "Reading Ben Okafor's work (1 of 1)" } } }, live, NOW),
  queued: T.syncLine(status, T.pollerState(status, null, null, { ...poller, state: "running", round: { id: "r", state: "queued", waiting_for: { message: "Queued: starts when “X” has finished" } } }), NOW),
  failed: T.syncLine({ ...status, last_round: { ...status.last_round, state: "error", error: "Disk full" } }, null, NOW),
  never: T.syncLine({ ...status, last_round: null, people: [], me: {} }, null, NOW),
};
out.shared = T.myShared({ items: [
  { kind: "check", key: "h1", state: "shared", mine: true, owner: { id: "me" }, here: true, at: "2026-11-11T09:00:00Z" },
  { kind: "check", key: "h2", state: "shared", mine: true, owner: { id: "me" }, here: true, at: "2026-11-11T09:30:00Z" },
  { kind: "check", key: "h3", state: "private", mine: true, owner: { id: "me" }, here: true },
  { kind: "note", key: "n1", state: "withdrawn", mine: true, owner: { id: "me" }, here: true },
  { kind: "check", key: "h9", state: "shared", mine: false, owner: { id: "ben" }, here: true },
  { kind: "log", key: "e1", state: "shared", mine: false, owner: null, here: true },
  { kind: "themes", key: "t1", state: "shared", mine: true, owner: { id: "me" }, here: false }] });
out.person = [T.personLine({ id: "a", app_version: "0.18.0", waiting: 0 }), T.personLine({ id: "a", waiting: 2 }),
  T.personLine({ id: "c", app_version: "0.19.0", waiting: 1 }, [{ kind: "newer_format", person: { id: "c" } }])];
out.paths = ['"C:\\Users\\Anna\\OneDrive\\Team"', "  /Users/anna/Dropbox/Team/ ", "C:\\", "'/Volumes/Team drive'"].map(T.cleanPath);
out.when = [T.whenText(iso(-60), new Date(NOW)), T.whenPhrase(iso(-60), new Date(NOW)), T.inText(iso(100), NOW), T.inText(iso(20), NOW)];
out.news = T.newsLines(["Nothing new: this copy already has everything in Ben's file.", "", "From Ben: 1 new result."]);
// two rounds of a colleague that read alike: the one not seen yet takes away one entry of the history only
const alike = [{ at: iso(-40), from: ben, lines: ["1 judgement of Ben Okafor's came in, under their name."] },
               { at: iso(-4000), from: ben, lines: ["1 judgement of Ben Okafor's came in, under their name."] }];
const one = T.pollerState(status, null, alike, { ...poller, came_in: { count: 1, rounds: [{ id: 9, at: iso(-30), from: ben, lines: alike[0].lines, count: 1 }] } });
out.alike = one.came_in.map((c) => [c.at, c.seen]);
// after a restart the poller has no last round: the last time work was read or written stands for it
out.restart = T.syncLine(status, T.pollerState(status, null, null, { ...poller, last_round: null }), NOW).text;
out.whose = [T.whoseWork(["Ben Okafor"]), T.whoseWork(["Ben", "Chloé"]), T.whoseWork([null])];
// checked against the real poller: a queued Sync now cancelled is the poller's last round, "cancelled"
out.stopped = T.syncLine(status, T.pollerState(status, null, null, { ...poller, last_round: { ...poller.last_round, state: "cancelled" } }), NOW);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def node_out(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("Node is not installed")
    d = tmp_path_factory.mktemp("team-node")
    (d / "package.json").write_text('{"type": "module"}')
    (d / "team-state.js").write_text(STATE, encoding="utf-8")
    (d / "run.mjs").write_text(NODE, encoding="utf-8")
    r = subprocess.run([shutil.which("node"), str(d / "run.mjs")], capture_output=True, text=True,
                       env={**os.environ, "TZ": "Europe/Amsterdam"})  # the times are read in Dutch local time
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


NOW_MS = 1794391200000  # 2026-11-11T10:00:00Z


def test_the_stand_in_reads_the_folder_and_the_history(node_out):
    s = node_out["standin"]
    assert s["live"] is False and s["auto"] is False and s["last_at"] == NOW_MS - 60000
    assert s["came"] == [["Ben Okafor", ["From Ben Okafor: 1 new result."], False]] and s["unseen"] == 1  # "Nothing new" left out
    h = node_out["history"]
    assert h["came"] == [["From Ben Okafor: 1 new result.", False], ["1 note of Ben Okafor's came in.", True]] and h["unseen"] == 1
    assert node_out["lastFromFolder"] is True


def test_the_poller_state_is_mapped_as_announced(node_out):
    live = node_out["live"]
    assert live["live"] is True and live["auto"] is True and live["paused"] is False and live["every"] == 120
    assert live["next_at"] == NOW_MS + 100000 and live["unseen"] == 2 and live["newest"] == 5
    # the round not seen yet, then what was seen before from the history (the same round is not listed twice)
    assert live["came"] == [["From Ben Okafor: 1 new result.", False], ["1 note of Ben Okafor's came in.", True]]


def test_the_sync_line_says_each_state(node_out):
    ln = node_out["lines"]
    assert ln["waiting"] == {"kind": "ok", "text": "Last round: Today 10:59", "sub": "Up to date; next round in about 2 min."}
    assert ln["offline"]["kind"] == "offline" and "tries again by itself in about 8 min" in ln["offline"]["sub"]
    assert ln["offlineStandin"]["kind"] == "offline" and "press Sync now" in ln["offlineStandin"]["sub"]
    assert ln["paused"]["text"] == "Paused" and "Sync now still works" in ln["paused"]["sub"]
    assert ln["pausedAll"]["text"] == "Paused for every project"
    assert ln["busy"] == {"kind": "busy", "text": "The next round waits", "sub": "Queued: starts when “Reading” has finished"}
    assert ln["running"] == {"kind": "running", "text": "Syncing now…", "sub": "Reading Ben Okafor's work (1 of 1)"}
    assert ln["queued"]["text"] == "A round waits its turn" and ln["queued"]["sub"].startswith("Queued:")
    assert ln["failed"]["kind"] == "failed" and ln["failed"]["sub"] == "Disk full"
    assert ln["never"] == {"kind": "never", "text": "No round yet", "sub": "Press Sync now for the first round."}


def test_what_you_shared_and_a_colleagues_line(node_out):
    sh = node_out["shared"]
    assert [i["key"] for i in sh["byKind"]["check"]] == ["h2", "h1"]  # newest first, not a colleague's, not private
    assert [i["key"] for i in sh["byKind"]["log"]] == ["e1"]           # maker not known: anyone may take it back
    assert "themes" not in sh["byKind"] and sh["withdrawn"] == 1 and sh["total"] == 3
    p = node_out["person"]
    assert p[0] == {"text": "ENLENS 0.18.0 · up to date", "warn": False}
    assert p[1]["text"] == "new work waiting (2 rounds): it comes in with the next round"
    assert p[2]["warn"] is True and "newer ENLENS" in p[2]["text"]


def test_rounds_that_read_alike_and_a_restart(node_out):
    assert node_out["alike"] == [[NOW_MS - 30000, False], [NOW_MS - 4000000, True]]
    assert node_out["restart"] == "Last round: Today 10:55"   # Ben's work read at 09:55 UTC
    assert node_out["whose"] == ["Ben Okafor’s work came in.", "Ben’s and Chloé’s work came in.", "A colleague’s work came in."]


def test_a_round_stopped_is_said_so(node_out):
    assert node_out["stopped"] == {"kind": "ok", "text": "Last round stopped: Today 10:59", "sub": "Next round in about 2 min."}


def test_what_the_real_poller_showed():
    """Found against the real poller (0.18 merge): a round due was shown as "Starting…" for 20 s (the tab now looks
    again within seconds); the focus fell off Sync now, Pause and the switches (Sync now is off with aria-disabled, the
    others get the focus back); offline, the people list said no colleague had used the folder."""
    assert "ctx.poll && ctx.poll.due ? SOON : EVERY" in TEAM and "const SOON = 4000;" in TEAM
    assert '"aria-disabled": running ? "true" : null, id: "team-sync-now"' in TEAM
    assert 'if (sync.getAttribute("aria-disabled") !== "true") ctx.startRound(sync);' in TEAM
    assert "const again = id && document.getElementById(id); if (again) again.focus();" in TEAM
    assert "Your colleagues show here again once the shared folder can be reached." in TEAM
    assert 'if (s.kind === "running" && loud(said)) return;' in TEAM


def test_a_pasted_path_and_the_times(node_out):
    assert node_out["paths"] == ["C:\\Users\\Anna\\OneDrive\\Team", "/Users/anna/Dropbox/Team", "C:\\", "/Volumes/Team drive"]
    assert node_out["when"] == ["Today 10:59", "today at 10:59", "in about 2 min", "in less than a minute"]
    assert node_out["news"] == ["From Ben: 1 new result."]


# ------------------------------------------------------------------ the app's answers have what the tab reads
def test_the_answers_have_the_fields_the_tab_reads(api, tmp_path):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    st, r = api("GET", "/api/projects/Demo/shared-folder")
    assert st == 200 and {"folder", "reachable", "keep_out", "me", "people", "problems", "not_here", "job", "last_round"} <= set(r)
    assert {"mine", "colleagues", "in_force"} <= set(r["keep_out"]) and {"name", "last_written_at"} <= set(r["me"])
    st, r = api("GET", "/api/projects/Demo/sharing")
    assert st == 200 and {"items", "counts", "me", "kinds"} <= set(r)
    st, r = api("GET", "/api/projects/Demo/together")
    assert st == 200 and isinstance(r["history"], list)
    shared = tmp_path / "Team folder"
    shared.mkdir()
    st, r = api("PUT", "/api/projects/Demo/shared-folder", {"path": str(shared)})
    assert st == 200 and r["folder"]
    st, r = api("POST", "/api/projects/Demo/shared-folder/sync", {})
    job = api.wait(r["job"]["id"])
    st, r = api("GET", "/api/projects/Demo/shared-folder")
    last = r["last_round"]
    assert last["state"] == "done" and isinstance(last["finished_at"], (int, float))
    assert {"wrote", "read", "problems"} <= set(last["result"]) and "waiting" in last["result"]["wrote"]
    assert job["id"] == last["id"]
    st, r = api("DELETE", "/api/projects/Demo/shared-folder", {})
    assert st == 200 and r["folder"] is None


def test_choosing_the_folder_again_keeps_the_switch(api, tmp_path):  # noqa: F811
    # final check: Stop using this folder, then Use this folder again, turned the keep-out switch off by itself, and
    # the next round wrote a No-AI document's reading and file into the folder
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    shared = tmp_path / "Team folder"
    shared.mkdir()
    st, r = api("PUT", "/api/projects/Demo/shared-folder", {"path": str(shared), "keep_out": True})
    assert st == 200 and r["keep_out"]["mine"] is True
    assert api("DELETE", "/api/projects/Demo/shared-folder", {})[1]["keep_out"]["mine"] is True
    st, r = api("PUT", "/api/projects/Demo/shared-folder", {"path": str(shared)})        # the page sends no switch
    assert st == 200 and r["folder"] and r["keep_out"]["mine"] is True
    st, r = api("PUT", "/api/projects/Demo/shared-folder", {"path": str(tmp_path / "nowhere"), "keep_out": False})
    assert st == 400                                                                   # refused: the switch stays
    assert api("GET", "/api/projects/Demo/shared-folder")[1]["keep_out"]["mine"] is True
    st, r = api("PUT", "/api/projects/Demo/shared-folder", {"path": str(shared), "keep_out": False})
    assert st == 200 and r["keep_out"]["mine"] is False
