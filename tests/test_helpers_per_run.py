"""How fast Claude Code works, and which helpers it starts (0.13.10).

The researcher picks a speed beside every Start Claude Code (Settings' claude_speed: slower 1, normal 2, faster 4
helpers at once); "Choose the helpers for this run" names the helpers one by one for one run. The app passes the plan
to /enlens-run as --parallel and --helpers, /enlens-run passes them to the connector's queue_status, and each group
then says how many helpers to start for it (`start`), so the sums are done by ENLENS, not by the orchestrating model.
The stand-in Claude Code (tests/fake_claude_code.py, fake_claude_cli.py) follows `start` as the plugin's skill says."""
import json
import re
import time
from pathlib import Path

import pytest

import fake_claude_code as fcc
from test_queue import _queued_labels
from test_subscription_first import fake_claude  # noqa: F401  (fixture)
from test_app import CLAIM, Api, api, home  # noqa: F401  (fixtures)

SRC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims"
STATIC = SRC / "gui" / "static"


def _groups(*spec):
    return [{"kind": k, "model": m, "helper": hp, "waiting": n} for k, m, hp, n in spec]


GROUPS = (("expand", "sonnet", "enlens-namer", 3), ("check", "sonnet", "enlens-checker", 12),
          ("label", "haiku", "enlens-labeller", 500))


# ---------------------------------------------------------------------------------------------
# the plan: how many helpers each group gets
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("parallel, starts", [(1, [1, 0, 0]), (2, [1, 1, 0]), (4, [1, 2, 1]), (8, [1, 4, 3])])
def test_the_helpers_are_shared_out_in_the_queue_order(parallel, starts):
    from enlens_claims import taskqueue

    g = _groups(*GROUPS)
    assert taskqueue.plan_helpers(g, parallel) == []
    assert [x["start"] for x in g] == starts
    assert sum(starts) == parallel
    # never more helpers than batches: three sets of search words are one batch of five
    assert g[0]["start"] == 1


def test_named_helpers_start_as_many_as_named_and_the_others_wait():
    from enlens_claims import taskqueue

    g = _groups(*GROUPS)
    left = taskqueue.plan_helpers(g, 8, {"enlens-checker": 2, "enlens-labeller": 3})
    assert [x["kind"] for x in left] == ["expand"]
    assert [x["start"] for x in g] == [0, 2, 3]
    # the total caps the helpers named
    g = _groups(*GROUPS)
    taskqueue.plan_helpers(g, 2, {"enlens-checker": 4, "enlens-labeller": 4})
    assert [x["start"] for x in g] == [0, 1, 1]
    # one helper over several groups: its count is shared by them
    g = _groups(("check", "sonnet", "enlens-checker", 5), ("reread", "sonnet", "enlens-checker", 5))
    taskqueue.plan_helpers(g, 8, {"enlens-checker": 3})
    assert [x["start"] for x in g] == [2, 1]


def test_the_helpers_of_a_run_are_checked():
    from enlens_claims import taskqueue

    assert taskqueue.clean_helpers("checker=2, labeller=1") == {"enlens-checker": 2, "enlens-labeller": 1}
    assert taskqueue.clean_helpers({"enlens-auditor": 1, "Namer": 0}) == {"enlens-auditor": 1, "enlens-namer": 0}
    assert taskqueue.clean_helpers("checker") == {"enlens-checker": 1}
    assert taskqueue.clean_helpers(None) is None and taskqueue.clean_helpers("") is None
    assert taskqueue.helpers_arg({"enlens-checker": 2, "enlens-namer": 0, "enlens-labeller": 1}) == "checker=2,labeller=1"
    for bad, says in (("painter=1", "Unknown helper"), ("checker=5", "0 to 4"), ("checker=x", "0 to 4"),
                      ({"checker": True}, "0 to 4"), ({"checker": 2.7}, "0 to 4"), ("checker=0", "at least one"),
                      (["checker"], "helpers must")):
        with pytest.raises(ValueError, match=says):
            taskqueue.clean_helpers(bad)
    assert taskqueue.clean_parallel("3") == 3 and taskqueue.clean_parallel(3.0) == 3
    assert taskqueue.clean_helpers({"checker": 2.0}) == {"enlens-checker": 2}
    for bad in (0, 9, "many", True, 3.9, "3.9"):
        with pytest.raises(ValueError, match="1 to 8"):
            taskqueue.clean_parallel(bad)


def test_a_plan_without_numbers_follows_the_speed_of_settings(home):  # noqa: F811
    from enlens_claims import taskqueue

    assert taskqueue.run_plan() == {"parallel": 2, "helpers": None}
    home.update_settings({"claude_speed": "faster"})
    assert taskqueue.run_plan() == {"parallel": 4, "helpers": None}
    home.update_settings({"claude_speed": "slower"})
    assert taskqueue.run_plan() == {"parallel": 1, "helpers": None}
    assert taskqueue.run_plan(3) == {"parallel": 3, "helpers": None}
    # the helpers named one by one: as many at once as named in all (at most 8)
    assert taskqueue.run_plan(None, "checker=2,labeller=1")["parallel"] == 3
    assert taskqueue.run_plan(None, "checker=4,labeller=4,namer=4")["parallel"] == 8
    # never more at once than the helpers named add up to (what the run then says it has)
    assert taskqueue.run_plan(8, "checker=1")["parallel"] == 1
    with pytest.raises(ValueError, match="claude_speed"):
        home.update_settings({"claude_speed": "warp"})


# ---------------------------------------------------------------------------------------------
# the connector and the stand-in Claude Code follow the plan
# ---------------------------------------------------------------------------------------------
def _labels_and_a_check(home, corpus, name):
    from enlens_claims import claimcheck, routing

    ws, _pids = _queued_labels(home, corpus, name)
    claimcheck.queue_check(ws, CLAIM, routing.from_settings(home.load_settings()), k=3)
    return ws


def test_queue_status_gives_each_group_its_helpers(home, corpus):  # noqa: F811
    from enlens_claims import taskqueue

    ws = _labels_and_a_check(home, corpus, "H")
    tools = fcc.DirectTools()
    st = tools.queue_status("H")
    assert [(g["kind"], g["start"]) for g in st["groups"]] == [("expand", 1), ("label", 1)]
    assert st["parallel"] == 2 and "not_this_run" not in st
    labels = st["groups"][1]["waiting"]
    batches = -(-labels // taskqueue.BATCH["label"])   # a helper takes a batch at a time: no more helpers than batches
    st = tools.queue_status("H", parallel=4)
    assert [(g["kind"], g["start"]) for g in st["groups"]] == [("expand", 1), ("label", min(3, batches))]
    # only the labeller in this run: the search words wait, and the run says so
    st = tools.queue_status("H", helpers="labeller=2")
    assert [(g["kind"], g["start"]) for g in st["groups"]] == [("label", min(2, batches))]
    assert [g["kind"] for g in st["not_this_run"]] == ["expand"] and st["helpers"] == {"labeller": 2}
    # one kind only
    st = tools.queue_status("H", kind="expand", parallel=4)
    assert [(g["kind"], g["start"]) for g in st["groups"]] == [("expand", 1)]
    with pytest.raises(ValueError, match="Unknown kind"):
        taskqueue.run_status(ws, "H", kind="paint")


def test_a_run_with_named_helpers_leaves_the_others_waiting(home, corpus):  # noqa: F811
    ws = _labels_and_a_check(home, corpus, "N")
    cc = fcc.FakeClaudeCode(fcc.DirectTools(), wrong_first=False)
    cc.run("N", helpers="labeller=1")
    assert {e["helper"] for e in cc.log} == {"enlens-labeller"}
    assert all(set(p) <= {("label", "enlens-labeller")} for p in cc.plans)
    left = ws.query("SELECT kind, COUNT(*) AS n FROM tasks WHERE queued=1 AND status IN ('pending', 'retry') GROUP BY kind")
    assert [(r["kind"], r["n"]) for r in left] == [("expand", 1)]
    # the next run, at the speed of Settings, answers it
    cc = fcc.FakeClaudeCode(fcc.DirectTools(), wrong_first=False)
    cc.run("N")
    assert "enlens-namer" in {e["helper"] for e in cc.log}


def test_the_connector_takes_the_plan(home, corpus):  # noqa: F811
    pytest.importorskip("mcp")
    _labels_and_a_check(home, corpus, "C")
    out = fcc.run("C", helpers="namer=1", parallel=1)
    assert out["batches"] >= 1 and {e["helper"] for e in out["log"]} == {"enlens-namer"}


# ---------------------------------------------------------------------------------------------
# the app: the speed, the helpers for one run, and the command it starts
# ---------------------------------------------------------------------------------------------
def test_the_command_carries_the_plan(home):  # noqa: F811
    from enlens_claims import claude_setup, taskqueue

    args = claude_setup.run_args("My project", "/usr/bin/claude", {"parallel": 4, "helpers": None})
    assert args[2] == '/enlens-run:enlens-run "My project" --parallel 4'
    plan = taskqueue.run_plan(3, {"enlens-checker": 2, "enlens-labeller": 1, "enlens-namer": 0})
    args = claude_setup.run_args("P", "/usr/bin/claude", plan)
    assert args[2] == '/enlens-run:enlens-run "P" --parallel 3 --helpers checker=2,labeller=1'
    assert args[args.index("--allowedTools") + 1] == "Agent"  # still only the queue tools and the helpers


def _wait_done(api, project):  # noqa: F811
    for _ in range(300):
        q = api("GET", f"/api/projects/{project}/queue")[1]
        if not q["runner"]["running"]:
            return q
        time.sleep(0.2)
    raise AssertionError("the run did not end")


def test_start_claude_code_at_the_chosen_speed(api, corpus, fake_claude):  # noqa: F811
    from enlens_claims import home as core

    _queued_labels(core, corpus, "S")
    st, q = api("GET", "/api/projects/S/queue")
    assert st == 200 and q["speed"]["chosen"] == "normal" and q["speed"]["options"] == {"slower": 1, "normal": 2, "faster": 4}
    assert q["speed"]["max_parallel"] == 8 and q["speed"]["max_per_helper"] == 4
    assert [r["helper"] for r in q["speed"]["helpers"]] == ["enlens-labeller"]
    row = q["speed"]["helpers"][0]
    assert row["name"] == "labeller" and row["models"] == ["haiku"] and row["kinds"] == ["Codebook labels"]
    assert row["waiting"] == q["waiting"] and row["batches"] == -(-q["waiting"] // 20)
    assert "enlens-auditor" in q["speed"]["all_helpers"]
    assert api("PUT", "/api/settings", {"claude_speed": "faster"})[0] == 200
    assert api("PUT", "/api/settings", {"claude_speed": "warp"})[0] == 400
    assert api("POST", "/api/projects/S/queue/claude-code", {})[0] == 200
    q = _wait_done(api, "S")
    assert q["runner"]["exit_code"] == 0 and q["runner"]["parallel"] == 4 and q["runner"]["helpers"] is None
    assert "with 4 helpers at once" in q["runner"]["report"] and q["waiting"] == 0


def test_start_claude_code_with_the_helpers_chosen_for_this_run(api, corpus, fake_claude):  # noqa: F811
    from enlens_claims import home as core

    ws = _labels_and_a_check(core, corpus, "R")
    for bad in ({"helpers": {"painter": 1}}, {"helpers": {"labeller": 0}}, {"parallel": 12}):
        st, r = api("POST", "/api/projects/R/queue/claude-code", bad)
        assert st == 400, r
    st, r = api("POST", "/api/projects/R/queue/claude-code", {"parallel": 3, "helpers": {"enlens-labeller": 2,
                                                                                         "enlens-namer": 0}})
    assert st == 200, r
    q = _wait_done(api, "R")
    # 3 in all asked, but the helpers named add up to 2: the run has 2 at once, and says so
    assert q["runner"]["exit_code"] == 0 and q["runner"]["parallel"] == 2 and q["runner"]["helpers"] == {"labeller": 2}
    assert "with 2 helpers at once (labeller=2)" in q["runner"]["report"]
    left = ws.query("SELECT kind FROM tasks WHERE queued=1 AND status IN ('pending', 'retry')")
    assert {r["kind"] for r in left} == {"expand"}   # the namer was given 0: its work waits for the next run


# ---------------------------------------------------------------------------------------------
# the plugin's skill, and the page
# ---------------------------------------------------------------------------------------------
def test_the_skill_follows_start(home):  # noqa: F811
    from enlens_claims import claude_setup

    root = claude_setup.write_plugin()
    assert claude_setup.check_files(root) == []
    skill = (root / "plugins" / "enlens-run" / "SKILL.md").read_text()
    head = claude_setup.frontmatter(root / "plugins" / "enlens-run" / "SKILL.md")
    assert "--helpers" in head["argument-hint"] and "--parallel N" in head["argument-hint"]
    assert "`start`" in skill and "do not work it out yourself" in skill
    assert "`kind`, `parallel` and `helpers`" in skill and "not_this_run" in skill
    assert "reported back" in skill   # never asks again while one of its helpers still works


def test_the_page_offers_the_speed_and_the_helpers_for_one_run():
    from enlens_claims import taskqueue

    lib = (STATIC / "lib.js").read_text(encoding="utf-8")
    # the page's default speeds are the queue's
    m = re.search(r"options = \{ slower: (\d), normal: (\d), faster: (\d) \}", lib)
    assert m and dict(zip(("slower", "normal", "faster"), map(int, m.groups()))) == taskqueue.SPEEDS
    assert "export function speedPicker" in lib and "Choose the helpers for this run" in lib
    assert "/queue/claude-code`, body)" in lib and "RUN_CHOICE.delete(project)" in lib
    settings = (STATIC / "views" / "settings.js").read_text(encoding="utf-8")
    assert "speedPicker(" in settings and 'speed: "model"' in settings
    queue = (STATIC / "views" / "queue.js").read_text(encoding="utf-8")   # 0.17.0: the queue moved to Settings › AI
    assert 'el.matches(".sc-helpers select")' in queue and "defers < 6" in queue   # waits, a while, for an open list
    assert "choiceChanged(project, box)" in lib and "FOLD_SEQ" in lib   # two folds of one project agree, ids apart
    assert "opts.custom && opts.custom()" in lib   # the speed shown, picked again, undoes a choice of helpers
    from _static import rule  # 0.17.0: reads the cascade, so it holds when the rules move

    assert rule(".sc-speed") and rule(".sc-helper")   # no stylesheet of its own (since 0.13.6)
    assert not list(STATIC.glob("v01310*.css"))
    assert json.loads((STATIC / "brand.json").read_text())["name"]
