"""0.9: subscription first, Claude Code set up and started from the app, and the overview.

- a new installation answers with Claude Code on the researcher's own plan; a local-only installation and an
  installation that already chose a local model are left alone;
- `claude_setup` finds the `claude` program, says what is ready (found, signed in, plugin added), adds the plugin by
  itself, and starts Claude Code for one project's queue with only the ENLENS queue tools allowed (the stand-in
  tests/fake_claude_cli.py plays the real program);
- the overview counts what each feature has made; the sidebar marks which features use the AI.
"""
import json
import os
import time
from pathlib import Path

import pytest

from test_app import Api, api, home  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
FAKE = str(Path(__file__).with_name("fake_claude_cli.py"))


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setenv("ENLENS_CLAUDE", FAKE)
    from enlens_claims import claude_setup

    claude_setup._STATUS.update(at=0.0, value=None)
    return claude_setup


def test_a_new_installation_is_subscription_first(home, monkeypatch):  # noqa: F811
    s = home.load_settings()
    assert s["backend"] == "claude_code" and s["allow_claude_code"] is True and s["allow_cloud"] is False
    assert home.BACKEND_LABELS["claude_code"] == "Claude Code (your subscription)"
    assert list(home.BACKEND_LABELS)[0] == "claude_code"
    # an installation that chose a local model keeps it
    home.update_settings({"backend": "ollama", "ollama_model": "qwen3:8b"})
    assert home.load_settings()["backend"] == "ollama"
    # local only: the subscription default becomes the local one, and Claude Code cannot be chosen
    (home.home() / "settings.json").unlink()
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    s = home.load_settings()
    assert s["backend"] == "auto" and s["allow_claude_code"] is False
    with pytest.raises(ValueError, match="switched off"):
        home.update_settings({"backend": "claude_code", "allow_claude_code": True})


def test_claude_code_not_found(home):  # noqa: F811
    from enlens_claims import claude_setup

    st = claude_setup.status(refresh=True)
    assert st["found"] is False and st["ready"] is False
    r = claude_setup.install()
    assert r["steps"][0]["ok"] and not r["steps"][-1]["ok"] and "not found" in r["steps"][-1]["text"]
    assert r["commands"][1] == "claude plugin install enlens-run@enlens"


def test_setup_adds_the_plugin_by_itself(home, fake_claude):  # noqa: F811
    st = fake_claude.status(refresh=True)
    assert st["found"] and st["signed_in"] is True and st["installed"] is False and not st["ready"]
    r = fake_claude.install()
    assert [x["ok"] for x in r["steps"]] == [True, True, True]
    assert r["steps"][1]["step"].startswith("claude plugin marketplace add")
    assert r["status"]["installed"] is True and r["status"]["ready"] is True
    assert json.loads((home.home() / "fake-claude.json").read_text())["marketplace"] == str(fake_claude.folder())


def test_the_run_command_allows_only_the_queue_tools():
    from enlens_claims import claude_setup

    args = claude_setup.run_args('My "big" project', "/usr/bin/claude")
    assert args[:3] == ["/usr/bin/claude", "-p", '/enlens-run:enlens-run "My big project"']
    tools = args[args.index("--allowedTools") + 1:]
    assert tools[0] == "Agent" and all(t.startswith("mcp__plugin_enlens-run_enlens__") for t in tools[1:])
    assert {t.rsplit("__", 1)[1] for t in tools[1:]} == set(claude_setup.QUEUE_TOOLS)
    # a stand-in written in Python runs with this Python
    assert claude_setup.run_args("P", FAKE)[1] == FAKE


def _queued_labels(home, corpus):  # noqa: F811
    from enlens_claims import ingest, profile, tasks

    ws = home.create_project("Q")
    ingest.ingest(ws, [corpus])
    profile.keyword_pass(ws, "sdg")
    plan = profile.label_plan(ws, "sdg", all_passages=True)
    with tasks.queueing():
        profile.make_label_tasks(ws, "sdg", plan["passage_ids"], "haiku", all_passages=True)
    return ws


def _waiting(ws):
    return ws.scalar("SELECT COUNT(*) FROM tasks WHERE COALESCE(queued, 0)=1 AND status IN ('pending', 'retry')")


def test_start_claude_code_from_the_app_answers_the_queue(api, corpus, monkeypatch, fake_claude):  # noqa: F811
    from enlens_claims import home as core

    ws = _queued_labels(core, corpus)
    assert _waiting(ws) > 0
    st, q = api("GET", "/api/projects/Q/queue")
    assert st == 200 and q["can_start"] is True and q["runner"] == {"running": False}
    st, r = api("POST", "/api/projects/Q/queue/claude-code", {})
    assert st == 200, r
    for _ in range(300):
        st, q = api("GET", "/api/projects/Q/queue")
        if not q["runner"]["running"]:
            break
        time.sleep(0.2)
    assert q["runner"]["exit_code"] == 0, q["runner"]
    assert "batches answered for Q" in q["runner"]["report"]
    assert _waiting(ws) == 0
    assert json.loads((core.home() / "fake-claude.json").read_text())["installed"]  # added on the first start
    # the overview counts what is made
    st, o = api("GET", "/api/projects/Q/overview")
    assert st == 200 and o["documents"] == 3 and o["profile"]["labels"] > 0 and o["waiting"] == 0
    assert o["themes"] == {"runs": 0, "themes": 0, "latest": None}


def test_stop_returns_the_taken_batches(api, corpus, monkeypatch, fake_claude):  # noqa: F811
    from enlens_claims import home as core

    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "30")  # it waits before answering anything
    ws = _queued_labels(core, corpus)
    n = _waiting(ws)
    assert api("POST", "/api/projects/Q/queue/claude-code", {})[0] == 200
    assert api("GET", "/api/projects/Q/queue")[1]["runner"]["running"] is True
    st, r = api("POST", "/api/projects/Q/queue/claude-code/stop", {})
    assert st == 200 and r["running"] is False and r["stopped"] is True
    assert _waiting(ws) == n


def test_start_needs_claude_code_chosen(api, corpus, fake_claude):  # noqa: F811
    from enlens_claims import home as core

    _queued_labels(core, corpus)
    assert api("PUT", "/api/settings", {"backend": "baseline"})[0] == 200
    st, r = api("POST", "/api/projects/Q/queue/claude-code", {})
    assert st == 400 and "Claude Code" in r["error"]


def test_setup_endpoint_and_model_test(api, fake_claude):  # noqa: F811
    st, r = api("GET", "/api/claude-setup")
    assert st == 200 and r["status"]["found"] and not r["status"]["ready"]
    st, r = api("POST", "/api/claude-setup", {})
    assert st == 200 and r["status"]["ready"] and all(x["ok"] for x in r["steps"])
    st, t = api("POST", "/api/servers/test")
    assert st == 200 and t["backend"] == "claude_code" and t["model_available"] and "set up" in t["message"]


def test_the_page_puts_exploring_first_and_marks_the_ai():
    static = ROOT / "src" / "enlens_claims" / "gui" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    nav = html[html.index('<nav class="nav"'):html.index("</nav>")]
    order = [nav.index(f'data-route="{r}"') for r in ("overview", "sources", "search", "profile", "concepts", "themes",
                                                       "check", "batch", "history")]
    assert order == sorted(order)
    assert nav.index("Explore the documents") < nav.index("Check hypotheses")
    feats = (static / "features.js").read_text(encoding="utf-8")
    feats = feats[feats.index("export const FEATURES"):]
    for key, ai in (("search", "none"), ("profile", "optional"), ("concepts", "optional"), ("themes", "optional"),
                    ("check", "uses"), ("batch", "uses"), ("history", "none"), ("sources", "none")):
        block = feats[feats.index(f"  {key}: {{"):]
        assert f'ai: "{ai}"' in block[:block.index("\n  },")], key
    app = (static / "app.js").read_text(encoding="utf-8")
    assert "nav-ai" in app and "nav-legend" in app and '[/^\\/?$/, "overview", renderOverview]' in app


def test_a_link_button_keeps_its_colours_on_hover():
    """The general `a:hover` colour outranked `.btn-primary`: a primary button made from a link (Overview's *Set up
    Claude Code*, *Add documents*…) turned its text the colour of its own hover background, so it read as empty."""
    css = (ROOT / "src" / "enlens_claims" / "gui" / "static" / "app.css").read_text(encoding="utf-8")
    assert "a:hover { color: var(--accent-strong); }" in css
    assert "a.btn-primary:hover { color: var(--on-accent); }" in css and "a.btn:hover { color: var(--text); }" in css
