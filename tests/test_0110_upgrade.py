"""0.11: a project made before 0.11 opens as it was, and the headless Claude Code run is closed.

- a 0.10 project: its documents stay readable by Claude (its default becomes `cloud`), its queued tasks get their
  setting (on an installation without cloud models they leave the queue), the answers given on a Claude route enter
  the ledger, and the Documents page shows the one-time banner;
- a project zip made before 0.11 asks the import question once; zips carry each document's setting and note;
- the headless run denies the built-in tools that read files or run commands, and starts in an empty folder.
"""
from __future__ import annotations

import json
import sqlite3

import pytest
from helpers_0110 import mixed_project, write_corpus

from enlens_claims import access, bundle, claimcheck, home, ingest, tasks
from enlens_claims.store import Workspace

HYP = "Green hydrogen production can increase water stress in arid regions."


def _make_010(path, corpus) -> Workspace:
    """A project as 0.10 left it: no AI settings, no ledger; a check answered by Claude Code; a task in the queue."""
    ws = Workspace.create(path)
    ingest.ingest(ws, [write_corpus(corpus)])
    from helpers_0110 import Cloud

    claimcheck.check_hypothesis(ws, HYP, Cloud(), "claude-opus", k=6, per_doc=2, expand=False)
    with ws.connect() as cx:
        cx.execute("UPDATE results SET route='Claude Code'")
        cx.execute("DELETE FROM ai_sent")
    with tasks.queueing():
        claimcheck.queue_check(ws, "Electrolysis needs fresh water.", None, k=6, per_doc=2, expand=False)
    ws.close()
    cx = sqlite3.connect(ws.db_path)
    for t, c in (("documents", "ai_access"), ("documents", "ai_note"), ("documents", "ai_budget"), ("tasks", "access")):
        cx.execute(f"ALTER TABLE {t} DROP COLUMN {c}")
    cx.execute("DROP TABLE ai_sent")
    cx.execute("DELETE FROM meta WHERE key IN ('ai_access_upgraded', 'ai_sent_since')")
    cx.commit()
    cx.close()
    cfg = json.loads(ws.config_path.read_text())
    cfg.pop("ai_access_default", None)
    ws.config_path.write_text(json.dumps(cfg))
    return ws


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    return tmp_path


def test_a_010_project_opens_unchanged(env):
    old = _make_010(env / "old", env / "c")
    ws = Workspace.open(old.root)
    assert access.default_chosen(ws) and access.default(ws) == "cloud"
    assert set(access.levels(ws).values()) == {"cloud"}
    info = access.project_info(ws)
    assert info["banner"] is True and info["ask"] is False and info["ledger_since"]
    q = ws.query("SELECT access, queued FROM tasks WHERE COALESCE(queued, 0)=1")
    assert q and {r["access"] for r in q} == {"cloud"}  # still in the queue
    rows = access.ledger(ws)
    assert rows and {r["route"] for r in rows} == {"Claude Code"}  # the answers given on a Claude route
    n = len(rows)
    Workspace.open(old.root)  # once only
    assert len(access.ledger(ws)) == n
    access.dismiss_banner(ws)
    assert access.project_info(ws)["banner"] is False


def test_on_an_installation_without_cloud_models_queued_tasks_leave(env, monkeypatch):
    old = _make_010(env / "old", env / "c")
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    ws = Workspace.open(old.root)
    assert access.default(ws) == "local"
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE COALESCE(queued, 0)=1") == 0


def test_project_zips_carry_the_settings(env):
    ws = home.create_project("Mixed")
    ids = mixed_project(ws, env / "corpus")
    access.set_documents(ws, [ids["local"]], note="publisher licence")
    z = env / "mixed.zip"
    bundle.export_project(ws, z)
    back = bundle.import_project(z, env / "back")
    assert access.levels(back)[ids["local"]] == "local" and access.levels(back)[ids["none"]] == "none"
    assert back.scalar("SELECT ai_note FROM documents WHERE doc_id=?", (ids["local"],)) == "publisher licence"
    assert not access.project_info(back)["ask"]


def test_a_zip_made_before_011_asks_once(env):
    old = _make_010(env / "old", env / "c")
    # a 0.10 zip: the database without the 0.11 columns (bundle.export_project copies it as it is)
    z = env / "old.zip"
    import zipfile

    with zipfile.ZipFile(z, "w") as zf:
        zf.write(old.db_path, "enlens.sqlite")
        zf.write(old.config_path, "config.json")
        zf.writestr("bundle.json", json.dumps({"version": "0.10.2", "files": {}}))
    back = bundle.import_project(z, env / "back")
    info = access.project_info(back)
    assert info["ask"] is True and not info["chosen"]
    access.set_default(back, "local")
    assert access.project_info(back)["ask"] is False and set(access.levels(back).values()) == {"local"}


def test_the_headless_run_is_closed(env, monkeypatch):
    from enlens_claims import claude_setup

    args = claude_setup.run_args("P", "/usr/bin/claude")
    denied = args[args.index("--disallowedTools") + 1].split(",")
    assert {"Read", "Grep", "Glob", "Bash", "Write", "Edit", "WebFetch"} <= set(denied)
    assert args.index("--disallowedTools") < args.index("--allowedTools")
    tools = args[args.index("--allowedTools") + 1:]
    assert tools[0] == "Agent" and not set(tools) & set(denied)
    # it starts in an empty folder, not in the data folder that holds every project's database
    (home.home() / "claude-runs" / "work").mkdir(parents=True)
    (home.home() / "claude-runs" / "work" / "left.txt").write_text("x")
    seen = {}

    class P:
        def __init__(self, args, cwd=None, **kw):
            seen["cwd"], seen["args"] = cwd, args

        def poll(self):
            return 0

    monkeypatch.setattr(claude_setup.subprocess, "Popen", P)
    monkeypatch.setattr(claude_setup, "find_claude", lambda: "/usr/bin/claude")
    monkeypatch.setattr(claude_setup, "setup_info", lambda: {"ready": True})
    monkeypatch.setattr(claude_setup, "status", lambda refresh=False: {"installed": True})
    claude_setup.start_run("P")
    work = home.home() / "claude-runs" / "work"
    assert seen["cwd"] == str(work) and list(work.iterdir()) == []
    assert "--disallowedTools" in seen["args"]


def test_the_account_kind_from_claude_code(env, monkeypatch, tmp_path):
    """When `claude auth status` says the plan, the panel shows it (the stand-in says nothing: the person picks)."""
    from enlens_claims import claude_setup

    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\nif [ \"$1\" = auth ]; then echo '{\"loggedIn\": true, \"subscriptionType\": \"max\"}'; "
                    "else echo 2.1.0; fi\n")
    fake.chmod(0o755)
    monkeypatch.setenv("ENLENS_CLAUDE", str(fake))
    claude_setup._STATUS.update(at=0.0, value=None)
    st = claude_setup.status(refresh=True)
    assert st["account"] == "personal" and st["plan"] == "max"
