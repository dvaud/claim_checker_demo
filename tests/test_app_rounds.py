"""0.18.0 stage 5: the rounds of the shared folder in the real app.

- A round the poller started stays out of the sidebar's work box for its first 20 s, then shows (app.js drawStatus).
  Before stage 5 nothing looked again while only such a round ran, so a long one showed only when something else
  redrew the box (27 s into a 30 s round in a browser check; a shorter one not at all): the work box now looks again
  when it reaches 20 s, and the light look at the poller (syncNewsInit) redraws the box while a round runs and looks
  just after the next round is due. The rules are in views/team-state.js (pure, so they run in Node here).
- `enlens-gui`, the ENLENS icon and the restart after an update all go through `server.serve()`, which starts the
  poller and stops it when the app stops; tools/dev_server.py starts it too, unless `--no-poller`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from test_app import Api, home  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
STATE = (STATIC / "views" / "team-state.js").read_text(encoding="utf-8")
DEV = (ROOT / "tools" / "dev_server.py").read_text(encoding="utf-8")


def _wait(cond, timeout=10.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


# ------------------------------------------------------------------ item 3: a long round shows in the work box
NODE = r"""
import * as T from "./team-state.js";
const run = (s, extra = {}) => ({ id: "r", kind: "folder-sync", state: "running", background: true, seconds: s, ...extra });
const out = {};
out.quiet = [T.quietRound(run(0)), T.quietRound(run(19.9)), T.quietRound(run(20)), T.quietRound(run(5, { background: false })),
  T.quietRound(run(5, { state: "done" })), T.quietRound(run(5, { state: "queued", seconds: 0 })), T.quietRound(null)];
out.again = [T.quietRoundAgainIn([]), T.quietRoundAgainIn([run(0)]), T.quietRoundAgainIn([run(12.5)]),
  T.quietRoundAgainIn([run(19.9)]), T.quietRoundAgainIn([run(3), run(15)]), T.quietRoundAgainIn([run(0, { state: "queued" })]),
  T.quietRoundAgainIn([run(25)]), T.quietRoundAgainIn([run(5, { background: false })])];
const p = { folder: true, state: "waiting", next_round_in: 100 };
out.look = [T.nextSyncLook(null), T.nextSyncLook(p), T.nextSyncLook({ ...p, next_round_in: 10 }),
  T.nextSyncLook({ ...p, state: "due", next_round_in: 0 }), T.nextSyncLook({ ...p, next_round_in: 24 }),
  T.nextSyncLook({ ...p, next_round_in: 25 }), T.nextSyncLook({ ...p, state: "busy", next_round_in: 0 }),
  T.nextSyncLook({ ...p, state: "offline", next_round_in: 3 }), T.nextSyncLook({ ...p, state: "paused", next_round_in: 3 }),
  T.nextSyncLook({ ...p, folder: false, next_round_in: 3 }), T.nextSyncLook({ ...p, state: "running", next_round_in: null })];
// a 30 s round the poller starts 1 s after a look that said it was due in 1 s: when does the work box first show it?
// (the page as app.js runs it: the sync look, then drawStatus looking again as quietRoundAgainIn says)
const shown = (startsAt, lasts, firstLook, dueIn) => {
  let t = firstLook + T.nextSyncLook({ ...p, next_round_in: dueIn }) / 1000;   // the next look after the first one
  while (t < startsAt + lasts) {
    if (t >= startsAt) {                       // the look sees the round run: drawStatus, then again until it shows
      let at = t;
      for (;;) {
        const job = run(at - startsAt);
        if (!T.quietRound(job)) return Math.round((at - startsAt) * 10) / 10;
        at += T.quietRoundAgainIn([job]) / 1000;
        if (at >= startsAt + lasts) return null;
      }
    }
    t += T.nextSyncLook({ ...p, next_round_in: null }) / 1000;
  }
  return null;
};
out.timeline = [shown(1, 30, 0, 1), shown(29, 30, 0, 100), shown(0.5, 40, 0, 100), shown(1, 15, 0, 1)];
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def node_out(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("Node is not installed")
    d = tmp_path_factory.mktemp("rounds-node")
    (d / "package.json").write_text('{"type": "module"}')
    (d / "team-state.js").write_text(STATE, encoding="utf-8")
    (d / "run.mjs").write_text(NODE, encoding="utf-8")
    r = subprocess.run([shutil.which("node"), str(d / "run.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a_round_of_the_poller_is_quiet_for_its_first_20_seconds(node_out):
    assert node_out["quiet"] == [True, True, False, False, False, True, False]


def test_the_work_box_looks_again_when_a_quiet_round_reaches_20_seconds(node_out):
    # none; 20 s after a round began; 7.5 s later; at least half a second; the longest running; a round still waiting
    # counts from 0; a round past 20 s is shown already (no extra look); a job of the person's is not quiet
    assert node_out["again"] == [None, 20250, 7750, 500, 5250, 20250, None, None]


def test_the_poller_is_looked_at_just_after_the_next_round_is_due(node_out):
    # every 30 s, or 5 s after a round due sooner; never sooner than 5 s; not while it waits, is offline or paused
    assert node_out["look"] == [30000, 30000, 15000, 5000, 29000, 30000, 30000, 30000, 30000, 30000, 30000]


def test_a_long_round_shows_once_it_has_run_20_seconds(node_out):
    # a 30 s round due 1 s after a look: shown at 20 s; one due long after the look before it (a change made it come
    # sooner) is seen by the next look, at 20 s when it is younger then, else at that look (at worst 30 s after the
    # look before it); a round of 15 s never shows
    first, sooner, worst, short = node_out["timeline"]
    assert 20 <= first < 21 and 20 <= sooner < 21 and worst == 29.5 and short is None


def test_the_work_box_and_the_look_at_the_poller_use_these_rules():
    assert 'import { quietRound, quietRoundAgainIn, nextSyncLook } from "./views/team-state.js";' in APP
    assert "const active = jobs.filter((j) => !TERMINAL.has(j.state) && !quietRound(j));" in APP
    status = APP[APP.index("async function drawStatus()"):APP.index("function themeInit()")]
    assert "const quietIn = quietRoundAgainIn(jobs);" in status
    assert "if (again) statusTimer = setTimeout(renderStatus, again);" in status
    news = APP[APP.index("function syncNewsInit()"):APP.index("async function boot()")]
    assert "if (s.folder && s.round) renderStatus();" in news
    assert "timer = setTimeout(look, nextSyncLook(s));" in news and "setInterval(" not in news
    assert "export const QUIET_SECONDS = 20;" in STATE


# ------------------------------------------------------------------ item 4: the real app starts the poller
def test_serve_starts_the_poller_and_stopping_the_app_stops_it(home, monkeypatch):  # noqa: F811
    from enlens_claims.gui import server

    box = {}
    real = server.make_server

    def capture(*a, **kw):
        srv, app = real(*a, **kw)
        box["app"] = app
        return srv, app

    monkeypatch.setattr(server, "make_server", capture)
    monkeypatch.setattr(server, "_repair_plugin", lambda: None)
    monkeypatch.setattr(server, "_repair_icons", lambda: None)
    t = threading.Thread(target=lambda: server.serve("127.0.0.1", 0, open_browser=False), daemon=True)
    t.start()
    assert _wait(lambda: "app" in box and box["app"].poller.running())
    assert box["app"].poller.overview()["running"] is True
    box["app"].stop()
    t.join(10)
    assert not t.is_alive() and not box["app"].poller.running()


def test_enlens_gui_the_icon_and_a_restart_go_through_serve(home, monkeypatch):  # noqa: F811
    from enlens_claims.gui import launch, launcher, server

    called = []
    monkeypatch.setattr(server, "serve", lambda host, port, open_browser=True, launcher=False:
                        called.append((host, port, open_browser, launcher)) or 0)
    assert launch.main(["--headless", "--port", "0"]) == 0                    # enlens-gui
    monkeypatch.setattr(launcher, "running", lambda: None)
    monkeypatch.setattr(launcher, "detach", lambda: None)
    monkeypatch.setattr(launcher, "log_to_file", lambda: None)
    assert launch.main(["--launcher", "--headless", "--no-start-ollama", "--port", "0"]) == 0   # the ENLENS icon
    assert called == [("127.0.0.1", 0, False, False), ("127.0.0.1", 0, False, True)]
    # (read without tomllib, which Python 3.10, the oldest ENLENS supports and CI runs, does not have)
    assert re.search(r'^enlens-gui\s*=\s*"enlens_claims\.gui\.launch:main"\s*$',
                     (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert launcher._args(None, False)[:3] == ["-m", "enlens_claims.gui.launch", "--launcher"]
    assert server.restart_command("127.0.0.1", 8765, True)[1:3] == ["-m", "enlens_claims.gui.launch"]


def _dev_server(tmp_path, *flags) -> tuple[subprocess.Popen, str, str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUNBUFFERED": "1",
           "HOME": str(tmp_path / "home-dir")}
    env.pop("ENLENS_CLAUDE", None)
    (tmp_path / "home-dir").mkdir(exist_ok=True)
    proc = subprocess.Popen([sys.executable, str(ROOT / "tools" / "dev_server.py"), "--port", "0", "--empty",
                             "--home", str(tmp_path / "dev-home"), *flags], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env, cwd=str(tmp_path))
    base = token = ""
    t0 = time.time()
    while time.time() - t0 < 60 and not (base and token):
        line = proc.stdout.readline()
        if not line:
            break
        if line.startswith("app: "):
            base = line.split("app: ", 1)[1].strip().rstrip("/")
        if line.startswith("token: "):
            token = line.split("token: ", 1)[1].strip()
    assert base and token, "the dev server did not start"
    return proc, base, token


@pytest.mark.parametrize("flags,running", [((), True), (("--no-poller",), False)], ids=["default", "no-poller"])
def test_the_dev_server_starts_the_poller_unless_asked_not_to(tmp_path, flags, running):
    proc, base, token = _dev_server(tmp_path, *flags)
    try:
        st, r = Api(base, token)("GET", "/api/sync-poller")
        assert st == 200 and r["running"] is running
    finally:
        proc.terminate()
        proc.wait(15)
    assert "app.poller.start()" in DEV and "app.poller.stop()" in DEV and '"--no-poller"' in DEV


# ------------------------------------------------------------------ the work box names a round (registry.js)
def test_a_round_and_a_new_reading_have_their_own_row_in_the_work_box(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("no Node here")
    js = tmp_path / "rows.mjs"
    js.write_text(f"""
const reg = await import({json.dumps((STATIC / "registry.js").as_uri())});
console.log(JSON.stringify([reg.jobRow({{ id: "j1", kind: "folder-sync", title: "Working together: the shared folder" }}),
  reg.jobRow({{ id: "j2", kind: "new_reader", title: "Reading 2 documents with the new reader, as the owner accepted" }})]));
""", encoding="utf-8")
    sync, move = json.loads(subprocess.run([node, str(js)], capture_output=True, text=True, check=True).stdout)
    assert sync["text"] == "Working together" and sync["drawer"] == "team" and sync["icon"] == "users"
    assert sync["tooltip"] == "Working together" and move["tooltip"] == "Reading with the new reader"
    assert move["text"] == "Reading with the new reader" and move["href"] == "#/sources" and "drawer" not in move
    # both run on this computer: the work box says so, not the AI's name; a round's row opens the Team tab
    assert 'LOCAL_JOB_KINDS = new Set(["index", "folder-sync", "new_reader"])' in APP
    assert 'new CustomEvent("enlens-drawer", { detail: { tab: w.drawer } })' in APP
