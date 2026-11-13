"""The validation report's AI half (0.18.4, roadmap J4.3, validation.py): scoring maths, the run file, the report,
and the release workflow's step when no run was recorded. No real AI: answers are made by hand or by the offline
baseline backend."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enlens_claims import validation as v
from enlens_claims.cli import main

ROOT = Path(__file__).resolve().parents[1]
CODES = ["A", "B", "C"]


# --------------------------------------------------------------------------------------------- scoring maths
def test_kappa_by_hand():
    assert v.kappa([]) is None
    assert v.kappa([("x", "x"), ("y", "y")]) == 1.0
    assert v.kappa([("x", "x"), ("x", "x")]) is None  # one category only: chance agreement is complete
    # 2x2: agree 7 of 10; rater a says yes 5 times, rater b 6 times: pe = .5*.6 + .5*.4 = .5, kappa = (.7-.5)/.5 = .4
    pairs = [(1, 1)] * 4 + [(1, 0)] * 1 + [(0, 1)] * 2 + [(0, 0)] * 3
    assert v.kappa(pairs) == pytest.approx(0.4)
    # three categories, as the verdicts are
    three = [("s", "s"), ("s", "s"), ("c", "c"), ("u", "u"), ("u", "s"), ("c", "u")]
    # a: s 2, c 2, u 2; b: s 3, c 1, u 2: pe = (2*3 + 2*1 + 2*2) / 36 = 1/3, po = 4/6, kappa = (2/3-1/3)/(2/3) = .5
    assert v.kappa(three) == pytest.approx(0.5)


def _check(i, gold, got, compound=False, quote_first=False, accepted=True):
    ans = {"task_id": f"check:{i}", "kind": "check", "status": "done", "attempts": 2 if quote_first else 1,
           "accepted_first": not quote_first, "quote_problem_first": quote_first, "first_errors": [],
           "models": ["sonnet"] if accepted else [], "model": "sonnet", "prompt_version": "check-v5",
           "app_version": "0.18.4", "answered_at": "2026-11-13T10:00:00+00:00", "route": "Claude Code",
           "helper": "enlens-checker", "answer": {"evidence": []}}
    return {"id": i, "hypothesis": f"hypothesis {i}", "compound": compound, "gold": gold, "got": got, "parts": 1,
            "answers": [ans]}


def _label(k, gold, got, mentioned=(), quote_first=False):
    ans = {"task_id": f"label:validation:{k}", "kind": "label", "status": "done", "attempts": 1,
           "accepted_first": True, "quote_problem_first": quote_first, "first_errors": [], "models": ["haiku"],
           "model": "haiku", "prompt_version": "label-v1", "app_version": "0.18.4",
           "answered_at": "2026-11-13T10:00:00+00:00", "route": "Claude Code", "helper": "enlens-labeller",
           "answer": {"labels": [{"code": c} for c in got or []]}}
    return {"key": f"doc.txt#{k}", "passage_id": f"p{k}", "gold": list(gold), "mentioned": list(mentioned),
            "got": None if got is None else list(got), "answers": [ans]}


def _pass(checks=None, labels=None):
    return {"project": "Validation", "prepared_at": "2026-11-13T09:00:00+00:00", "prepared_by": "0.18.4",
            "settings": {"k": 8, "per_doc": 2, "decompose": "compound", "expand": True},
            "gold_fingerprint_prepared": "abc",
            "checks": checks if checks is not None else [
                _check("H1", "supported", "supported"), _check("H2", "contradicted", "contested", quote_first=True),
                _check("H3", "unsupported", "unsupported"), _check("H4", "partially_supported", "supported", True),
                _check("H5", "contested", None, accepted=False)],
            "labels": labels if labels is not None else [
                _label("1", ["A"], ["A"]), _label("2", ["A", "B"], ["A"]), _label("3", [], ["C"]),
                _label("4", ["B"], ["B", "C"], mentioned=["C"]), _label("5", ["C"], None)]}


GOLD = {"fingerprint": "abc", "hypotheses": [{}] * 5, "labels": [{}] * 5, "codes": CODES}


def test_score_checks():
    s = v.score_checks(_pass()["checks"])
    assert s["n"] == 5 and s["answered"] == 4
    assert s["accuracy"] == 0.4                       # H1, H3 right
    assert s["per_verdict"]["contradicted"] == 0.0
    assert s["confusion"]["contested"] == {"no answer": 1}
    # found evidence or not: H1 yes/yes, H2 no/no (contested is not grounded), H3 no/no, H4 yes/yes, H5 no/no
    assert s["grounded_accuracy"] == 1.0
    assert s["compound_n"] == 1 and s["compound_accuracy"] == 0.0 and s["simple_accuracy"] == 0.5
    pairs = [("supported", "supported"), ("contradicted", "contested"), ("unsupported", "unsupported"),
             ("partially_supported", "supported"), ("contested", "no answer")]
    assert s["kappa"] == v.kappa(pairs)


def test_score_labels_leave_out_codes_only_mentioned():
    s = v.score_labels(_pass()["labels"], CODES)
    # passage 4: C is only mentioned, so its C is neither right nor wrong: 2 decisions there, 3 elsewhere
    assert s["code_decisions"] == 14
    # wrong: passage 2 B missed, passage 3 C added, passage 5 (no answer) C missed
    assert s["code_accuracy"] == round(11 / 14, 3)
    assert s["same_codes"] == 0.4                     # passages 1 and 4 (C mentioned, so B is the whole answer)
    assert s["answered"] == 4
    assert s["per_code"]["A"] == {"gold": 2, "precision": 1.0, "recall": 1.0}
    assert s["per_code"]["B"] == {"gold": 2, "precision": 1.0, "recall": 0.5}
    assert s["per_code"]["C"]["precision"] == 0.0     # passage 3 only: passage 4's C is mentioned, not counted


def test_quote_failures_and_repeatability():
    p1 = _pass()
    q = v.quote_failures(p1["checks"], ("check",))
    assert q == {"answers": 5, "first_rejected_for_quotes": 0.2, "never_accepted": 0.2}
    p2 = _pass(checks=[_check("H1", "supported", "supported"), _check("H2", "contradicted", "contradicted"),
                       _check("H3", "unsupported", "unsupported"), _check("H4", "partially_supported", "supported"),
                       _check("H5", "contested", "contested")],
               labels=[_label("1", ["A"], ["A"]), _label("2", ["A", "B"], ["A", "B"]), _label("3", [], ["C"]),
                       _label("4", ["B"], ["B", "C"]), _label("5", ["C"], ["C"])])
    r = v.repeatability(p1, p2, CODES)
    assert r["checks"]["same_status"] == 0.6
    assert r["labels"]["same_codes"] == 0.6
    assert r["labels"]["code_agreement"] == round(13 / 15, 3)


def test_quote_problem_wording():
    assert v._quote_problem(["evidence[0]: quote not found in passage P2: 'x'"])
    assert v._quote_problem(["labels[1]: quote not found in the passage: 'y'"])
    assert not v._quote_problem(["the answer is not valid JSON"])


# --------------------------------------------------------------------------------------------- the run file
def test_run_file_round_trip(tmp_path):
    run = v.make_run([_pass(), _pass()], GOLD, date="2026-11-13")
    assert run["route"] == "claude-code"
    assert run["models"] == {"check": {"sonnet": 10}, "label": {"haiku": 10}}
    assert run["prompt_versions"]["check"] == {"check-v5": 10}
    assert run["enlens_versions"] == {"0.18.4": 20}
    p = v.write_run(run, tmp_path / "runs")
    assert p.name == "2026-11-13-claude-code.json"
    assert v.read_run(p) == json.loads(json.dumps(run))
    p2 = v.write_run(run, tmp_path / "runs")           # never overwrites a recorded run
    assert p2.name == "2026-11-13-claude-code-2.json" and p.exists()
    older = dict(run, date="2026-10-01")
    v.write_run(older, tmp_path / "runs")
    assert v.latest_run(tmp_path / "runs") == p2
    assert v.latest_run(tmp_path / "nothing") is None
    (tmp_path / "bad.json").write_text('{"format": 99}')
    with pytest.raises(ValueError):
        v.read_run(tmp_path / "bad.json")


# --------------------------------------------------------------------------------------------- the report
def test_report_rendering():
    one = v.to_markdown(v.make_run([_pass()], GOLD, date="2026-11-13"))
    assert one.startswith("# Validation report: the AI's answers against known right answers")
    assert "Recorded on 2026-11-13 through the route **claude-code**" in one
    assert "**Right verdict:** 40% of 5 hypotheses" in one
    assert "| check | sonnet (5) | check-v5 (5) |" in one
    assert "| Contradicted | 0 | 0 | 1 | 0 | 0 | 0 | 0% |" in one
    assert "**Exactly the right codes:** 40% of 5 passages (4 answered)" in one
    assert "Checks: 20% of 5 answers were first rejected for a quote" in one
    assert "one pass only, so repeatability was not measured" in one
    assert "## Limits" in one and "invented" in one and "English only" in one
    assert "the gold set has changed" not in one
    two = v.to_markdown(v.make_run([_pass(), _pass()], GOLD, date="2026-11-13"), gold_fingerprint="other")
    assert "the same verdict for 100% of 5 hypotheses" in two
    assert "the gold set has changed since this run (now `other`)" in two


def test_report_command_writes_the_newest_run(tmp_path, capsys):
    runs = tmp_path / "runs"
    v.write_run(v.make_run([_pass()], GOLD, date="2026-11-01"), runs)
    v.write_run(v.make_run([_pass(), _pass()], GOLD, date="2026-11-13"), runs)
    out = tmp_path / "dist" / "validation-report-ai.md"
    assert main(["validate", "report", "--latest", str(runs), "--out", str(out)]) == 0
    assert "2026-11-13-claude-code.json" in capsys.readouterr().out
    assert "Recorded on 2026-11-13" in out.read_text("utf-8")


def test_no_run_file_is_said_and_not_a_failure(tmp_path, capsys):
    """The release workflow renders the AI half from the newest committed run file; with none, it says so, writes
    nothing (so no empty file goes out with the release) and does not fail."""
    out = tmp_path / "dist" / "validation-report-ai.md"
    assert main(["validate", "report", "--latest", str(tmp_path / "runs"), "--out", str(out)]) == 0
    assert "No recorded AI run" in capsys.readouterr().out
    assert not out.exists()


def test_release_workflow_renders_the_ai_half():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8")
    step = wf[wf.index("validate report"):][:300]
    assert "--latest tools/validation/runs" in step and "--out dist/validation-report-ai.md" in step
    # beside the half without AI, before the files are uploaded with the release
    assert wf.index("measure --report dist/validation-report.md") < wf.index("validate report") \
        < wf.index("actions/upload-artifact")


def test_runs_kept_in_git_are_readable():
    """Every run file committed in tools/validation/runs reads and renders (the release depends on the newest)."""
    for p in sorted((v.default_folder() / "runs").glob("*.json")):
        assert v.to_markdown(v.read_run(p)).startswith("# Validation report")


# --------------------------------------------------------------------------------------------- prepare and collect
PARA = ("{lead}. " + "This invented paragraph about remote work at the fictional firm Northbridge Tools says that "
        "{claim}. It goes on with plain words so that the paragraph is long enough to be one passage of its own in "
        "ENLENS, with nothing else in it worth noting for the purpose of this small test.")


@pytest.fixture
def mini_gold(tmp_path):
    g = tmp_path / "gold" / "validation"
    (g / "documents").mkdir(parents=True)
    paras = [PARA.format(lead="Findings", claim="home working lowered commuting emissions by a fifth"),
             PARA.format(lead="Wellbeing", claim="staff who worked from home reported less stress"),
             PARA.format(lead="Offices", claim="the firm closed one of its two office buildings")]
    (g / "documents" / "firm.txt").write_text("An invented report (fictional)\n\n" + "\n\n".join(paras) + "\n",
                                              encoding="utf-8")
    (g / "codebook.csv").write_text("code,description\nCOMMUTE,Commuting and its emissions\n"
                                    "WELLBEING,Stress and wellbeing of staff\nOFFICE,Office space and buildings\n",
                                    encoding="utf-8")
    (g / "hypotheses.csv").write_text(
        "id,hypothesis,verdict,compound,evidence,note\n"
        "H01,Home working lowers commuting emissions.,supported,no,,\n"
        "H02,Home working raises pay and lowers stress.,partially_supported,yes,,\n", encoding="utf-8")
    (g / "labels.csv").write_text(
        "file,anchor,codes,mentioned,note\n"
        "firm.txt,Findings. This invented paragraph,COMMUTE,,\n"
        "firm.txt,Wellbeing. This invented paragraph,WELLBEING,,\n"
        "firm.txt,Offices. This invented paragraph,OFFICE,COMMUTE,\n", encoding="utf-8")
    return g


def test_load_gold_checks_itself(mini_gold):
    g = v.load_gold(mini_gold)
    assert [h["compound"] for h in g["hypotheses"]] == [False, True]
    assert g["codes"] == ["COMMUTE", "OFFICE", "WELLBEING"]
    assert v.load_gold(mini_gold)["fingerprint"] == g["fingerprint"]
    (mini_gold / "labels.csv").write_text("file,anchor,codes,mentioned\nfirm.txt,Findings.,NOPE,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not in the codebook"):
        v.load_gold(mini_gold)


def test_prepare_answer_collect(mini_gold, tmp_path):
    """Prepare queues a check per hypothesis and a label task per gold passage; the offline baseline answers them
    here (no AI), and collect gives one record per gold item with how each answer was made."""
    from enlens_claims import taskqueue
    from enlens_claims.llm import get_backend
    from enlens_claims.store import Workspace

    ws = Workspace.create(tmp_path / "ws")
    out = v.prepare(ws, mini_gold)
    assert out["documents"] == 1 and out["hypotheses"] == 2 and out["label_tasks"] == 3
    with pytest.raises(ValueError, match="empty project"):
        v.prepare(ws, mini_gold)
    waiting = dict(ws.query("SELECT kind, COUNT(*) FROM tasks WHERE queued=1 GROUP BY kind"))
    assert waiting["label"] == 3 and waiting["decompose"] == 1  # only the compound one is split
    be = get_backend("baseline")
    for _ in range(4):  # a check's steps follow one another (search words, then the excerpts)
        if not taskqueue.run_here(ws, be)["answered"]:
            break
    p = v.collect(ws, mini_gold)
    assert [c["id"] for c in p["checks"]] == ["H01", "H02"]
    assert all(c["got"] for c in p["checks"]) and all(c["answers"] for c in p["checks"])
    assert {a["kind"] for a in p["checks"][1]["answers"]} >= {"decompose", "expand"}
    assert len(p["labels"]) == 3 and all(lb["got"] is not None for lb in p["labels"])
    a = p["labels"][0]["answers"][0]
    assert a["model"] and a["prompt_version"] == "label-v1" and a["app_version"] and a["answered_at"]
    run = v.make_run([p], v.load_gold(mini_gold), date="2026-11-13")
    assert v.to_markdown(run).startswith("# Validation report")
