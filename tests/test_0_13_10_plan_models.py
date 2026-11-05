"""The recommended model of each task follows the Claude plan (0.13.10).

ENLENS finds the plan Claude Code is signed in with in the background (`claude auth status`, whenever it asks Claude
Code how it is, and when the app starts), keeps its tier (Settings' claude_plan_detected) and routes every task by
it, also in the connector Claude Code starts: Free has no Opus or Fable and favours Haiku; Pro (and a plan not known)
keeps the table of 0.8, Sonnet for most tasks and Opus sparingly; Max, Team and Enterprise favour Opus, with Haiku and
Sonnet only for the kinds with many tasks at a time. Models chosen per task in Settings come first on every plan."""
import json

import pytest

from test_08_queue import _queued_labels
from test_090_subscription_first import fake_claude  # noqa: F401  (fixture)
from test_app import CLAIM, Api, api, home  # noqa: F401  (fixtures)


def _router(**s):
    from enlens_claims import routing

    return routing.from_settings({"backend": "claude_code", **s})


def _table(r):
    from enlens_claims import routing

    return {k: (r.model(k), r.step_up(k)) for k in routing.KINDS}


def test_the_plan_names_a_tier():
    from enlens_claims import routing

    for plan, tier in (("free", "free"), ("pro", "pro"), ("claude_pro", "pro"), ("max", "max"), ("claude_max", "max"),
                       ("Team", "max"), ("enterprise", "max"), ("", ""), (None, ""), ("something new", "")):
        assert routing.plan_tier(plan) == tier, plan


def test_pro_and_a_plan_not_known_keep_the_table_of_0_8():
    from enlens_claims import routing

    for fable in (False, True):
        before = _table(_router(use_fable=fable))
        assert _table(_router(use_fable=fable, claude_plan="pro")) == before
        assert _table(_router(use_fable=fable, claude_plan_detected="pro")) == before
        for k, (first, up) in routing.CLAUDE_DEFAULTS.items():
            if k in routing.KINDS:
                aud = "fable" if fable else "opus"
                assert before[k][0] == (aud if first == "auditor" else first), k
    assert _table(_router())["split"] == ("opus", "opus")   # the auditor reads the SDG pack's hard cases again


def test_free_has_no_opus_or_fable_and_favours_haiku():
    from enlens_claims import routing

    for fable in (False, True):
        t = _table(_router(claude_plan="free", use_fable=fable))
        assert all(m in ("haiku", "sonnet") and up in ("sonnet", None) for m, up in t.values()), t
    t = _table(_router(claude_plan="free"))
    haiku = {k for k, (m, _up) in t.items() if m == "haiku"}
    assert {"label", "link", "expand", "decompose", "theme", "resolve", "extract"} <= haiku
    assert all(t[k] == ("haiku", "sonnet") for k in haiku)
    # judging excerpts, second opinions and setting the SDG pack's reference claims stay on Sonnet, with nothing above
    for k in ("check", "reread", "second", "audit", "split", "verify", "verify_set"):
        assert t[k] == ("sonnet", None), k
    assert len(haiku) > sum(1 for m, _up in _table(_router()).values() if m == "haiku")   # more Haiku than on Pro
    # a model chosen by hand still comes first, and steps up no higher than Sonnet
    o = _router(claude_plan="free", task_models={"claude": {"check": "haiku", "label": "sonnet"}})
    assert (o.model("check"), o.step_up("check")) == ("haiku", "sonnet")
    assert (o.model("label"), o.step_up("label")) == ("sonnet", None)


def test_max_favours_opus_and_keeps_the_fast_models_for_the_bulk():
    t = _table(_router(claude_plan="max"))
    for k in ("expand", "decompose", "theme", "check", "reread", "second", "split", "verify", "verify_set"):
        assert t[k][0] == "opus", k
    # many tasks at a time: the cheaper models, as on Pro
    assert t["label"] == ("haiku", "sonnet") and t["link"] == ("haiku", "sonnet")
    assert t["resolve"] == ("sonnet", "opus") and t["extract"] == ("sonnet", "opus")
    # a check on Opus has no stronger model unless the auditor runs on Fable
    assert t["check"] == ("opus", None) and t["theme"] == ("opus", None)
    f = _table(_router(claude_plan="max", use_fable=True))
    assert f["check"] == ("opus", "fable") and f["second"] == ("fable", None) and f["theme"] == ("opus", None)
    assert t["split"] == ("opus", "opus")   # the SDG pack's Opus tasks keep their reading by the auditor
    o = _router(claude_plan="max", task_models={"claude": {"check": "sonnet"}})
    assert (o.model("check"), o.step_up("check")) == ("sonnet", "opus")


def test_the_claude_api_and_local_models_do_not_follow_the_plan():
    from enlens_claims import routing

    api_r = routing.from_settings({"backend": "anthropic", "claude_plan": "free"})
    assert api_r.tier == "" and api_r.call_model("check") == "claude-sonnet-5-5" and api_r.step_up("check") == "opus"
    local = routing.from_settings({"backend": "ollama", "claude_plan": "max"}, large="big")
    assert local.tier == "" and local.model("check") == "big"


def test_the_plan_is_found_in_the_background(home, monkeypatch, fake_claude):  # noqa: F811
    from enlens_claims import claude_setup, routing, taskqueue

    assert home.load_settings()["claude_plan"] == "auto" and home.load_settings()["claude_plan_detected"] == ""
    monkeypatch.setenv("FAKE_CLAUDE_PLAN", "max")
    claude_setup.status(refresh=True)
    assert home.load_settings()["claude_plan_detected"] == "max"
    assert taskqueue.router().model("check") == "opus"   # what the connector hands out follows it
    monkeypatch.setenv("FAKE_CLAUDE_PLAN", "team")
    claude_setup.status(refresh=True)
    assert home.load_settings()["claude_plan_detected"] == "max"
    monkeypatch.setenv("FAKE_CLAUDE_PLAN", "pro")
    claude_setup.status(refresh=True)
    assert routing.settings_tier(home.load_settings()) == "pro"
    # signed out: Claude Code says nothing, and nothing changes
    (home.home() / "fake-claude.json").write_text(json.dumps({"logged_in": False}))
    monkeypatch.setenv("FAKE_CLAUDE_PLAN", "free")
    assert claude_setup.status(refresh=True)["signed_in"] is False
    assert home.load_settings()["claude_plan_detected"] == "pro"
    # set by hand, the plan wins over the one found
    home.update_settings({"claude_plan": "free"})
    assert taskqueue.router().model("check") == "sonnet" and taskqueue.router().step_up("check") is None
    with pytest.raises(ValueError, match="claude_plan"):
        home.update_settings({"claude_plan": "platinum"})
    # the plan found belongs to this computer's Claude Code: moving ENLENS does not take it along
    from enlens_claims import bundle

    assert "claude_plan_detected" in bundle.MACHINE_SETTINGS and "claude_plan" not in bundle.MACHINE_SETTINGS


def test_the_app_finds_the_plan_when_it_starts(home, monkeypatch, fake_claude):  # noqa: F811
    from enlens_claims.gui import server

    monkeypatch.setenv("FAKE_CLAUDE_PLAN", "max")
    server._repair_plugin()
    assert home.load_settings()["claude_plan_detected"] == "max"


def test_waiting_work_follows_the_plan(home, corpus):  # noqa: F811
    from enlens_claims import claimcheck, routing, taskqueue

    ws, _pids = _queued_labels(home, corpus, "T")
    claimcheck.queue_check(ws, CLAIM, routing.from_settings(home.load_settings()), k=3)
    models = lambda: {g["kind"]: g["model"] for g in taskqueue.status(ws)["groups"]}  # noqa: E731
    assert models() == {"expand": "sonnet", "label": "haiku"}
    home.update_settings({"claude_plan_detected": "max"})
    assert models() == {"expand": "opus", "label": "haiku"}
    home.update_settings({"claude_plan_detected": "free"})
    assert models() == {"expand": "haiku", "label": "haiku"}
    got = taskqueue.next_tasks(ws, "expand", model="haiku", helper="enlens-namer")
    assert got["claim"] and got["model"] == "haiku"


def test_settings_show_the_plan_the_recommendations_follow(api):  # noqa: F811
    assert api("PUT", "/api/settings", {"backend": "claude_code", "allow_claude_code": True})[0] == 200
    st, r = api("GET", "/api/routing")
    assert st == 200 and r["plan"] == {"tier": "", "chosen": "auto", "detected": "",
                                       "titles": {"free": "Free", "pro": "Pro", "max": "Max, Team or Enterprise"}}
    rows = {x["row"]: x for x in r["rows"]}
    assert rows["check"]["recommended"] == "sonnet" and rows["second"]["recommended"] == "opus"
    assert rows["second"]["recommended_role"] == "auditor"
    assert api("PUT", "/api/settings", {"claude_plan": "free"})[0] == 200
    rows = {x["row"]: x for x in api("GET", "/api/routing")[1]["rows"]}
    assert rows["expand"]["recommended"] == "haiku" and rows["second"]["recommended"] == "sonnet"
    assert all(x["model"] in ("haiku", "sonnet") and x["step_up"] in ("sonnet", None) for x in rows.values())
    assert api("PUT", "/api/settings", {"claude_plan": "max"})[0] == 200
    r = api("GET", "/api/routing")[1]
    assert r["plan"]["tier"] == "max" and {x["row"]: x for x in r["rows"]}["check"]["model"] == "opus"
    assert api("PUT", "/api/settings", {"claude_plan": "gold"})[0] == 400
    assert api("PUT", "/api/settings", {"claude_plan_detected": "gold"})[0] == 400


def test_the_page_shows_the_plan():
    from pathlib import Path

    static = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
    settings = (static / "views" / "settings.js").read_text(encoding="utf-8")
    assert "function planField(" in settings and "The recommendations follow" in settings
    assert "On your Free plan the auditor runs on Sonnet" in settings
    lib = (static / "lib.js").read_text(encoding="utf-8")
    assert "export function planTier(" in lib and 'planTier(s) === "free") return "sonnet"' in lib
