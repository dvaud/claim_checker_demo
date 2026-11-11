"""0.11.2: when a stronger model reads a check's excerpts again, its reading is the answer, and the answer says what
the first model had found ("Supported, at first partly supported"). "Ask a stronger model" works on a whole result,
and stays distinct from a second opinion, which never changes the answer."""
from __future__ import annotations

import json

import pytest
from helpers_0110 import Cloud

from enlens_claims import claimcheck, ingest, tasks
from enlens_claims import home as ehome
from test_app import api, home  # noqa: F401,E402  (fixtures)

HYP = "Green hydrogen production can increase water stress in arid regions."


class Hedging(Cloud):
    """A first model that never says more than "partly supports"; with `hedge` off it answers as the fake model does
    (it finds the excerpts that support the hypothesis): the stronger model."""

    def __init__(self):
        super().__init__()
        self.hedge = True

    def complete(self, kind, system, user, model, payload=None):
        out = json.loads(super().complete(kind, system, user, model, payload))
        if self.hedge and isinstance(out, dict):
            for e in out.get("evidence") or []:
                if e.get("verdict") == "supports":
                    e["verdict"] = "partially_supports"
        return json.dumps(out)


@pytest.fixture
def ws(home, monkeypatch, corpus):
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    w = ehome.create_project("Stronger")
    ingest.ingest(w, [corpus])
    return w


def _step_up(ws, hid, be):
    res = claimcheck.hypothesis_result(ws, hid)
    ids = [rd["task_id"] for p in res["parts"] for rd in p["rounds_info"] if claimcheck.stronger_eligible(rd)]
    assert ids, "nothing a stronger model could read again"
    be.hedge = False
    for tid in ids:
        tasks.ask_stronger(ws, tid)
        assert tasks.answer_again(ws, tid, be)
    return ids


def test_the_stronger_models_reading_is_the_answer_and_the_first_one_is_shown(ws):
    be = Hedging()
    hid = claimcheck.check_hypothesis(ws, HYP, be, "claude-sonnet", k=4, per_doc=2)
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["status"] == "partially_supported"
    assert res["status_before_stronger"] is None and res["stronger"] == {}
    assert all(rd["can_step_up"] for rd in res["parts"][0]["rounds_info"])

    _step_up(ws, hid, be)
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["status"] == "supported"                                   # the main outcome is the stronger reading
    assert res["status_before_stronger"] == "partially_supported"         # and says what it was at first
    assert res["parts"][0]["status_before_stronger"] == "partially_supported"
    assert res["stronger"]["changed"] >= 1 and res["stronger"]["excerpts"] >= res["stronger"]["changed"]
    assert not any(rd["can_step_up"] for rd in res["parts"][0]["rounds_info"])   # once at most
    # each excerpt still shows its first reading (nothing is hidden)
    changed = [p for p in res["parts"][0]["passages"] if p["ai_history"]]
    assert changed and all(h["why"] == "stepped up" for p in changed for h in p["ai_history"])
    assert any(p["ai_history"][0]["verdict"] == "partially_supports" and p["ai_verdict"] == "supports" for p in changed)

    # the Results list says the same
    row = next(x for x in claimcheck.history(ws) if x["hyp_id"] == hid)
    assert row["status"] == "supported" and row["status_before_stronger"] == "partially_supported"


def test_no_mark_when_the_stronger_model_agrees(ws):
    be = Hedging()
    be.hedge = False
    hid = claimcheck.check_hypothesis(ws, HYP, be, "claude-sonnet", k=4, per_doc=2)
    _step_up(ws, hid, be)
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["status"] == "supported" and res["status_before_stronger"] is None
    assert res["stronger"]["excerpts"] >= 1 and res["stronger"]["changed"] == 0
    row = next(x for x in claimcheck.history(ws) if x["hyp_id"] == hid)
    assert row["status_before_stronger"] is None


def test_a_persons_judgement_counts_in_both_readings(ws):
    be = Hedging()
    hid = claimcheck.check_hypothesis(ws, HYP, be, "claude-sonnet", k=4, per_doc=2)
    res = claimcheck.hypothesis_result(ws, hid)
    part = res["parts"][0]
    # the person marks every partly-supporting excerpt as not about it: the first reading has nothing left
    for p in part["passages"]:
        if p["ai_verdict"]:
            claimcheck.set_judgement(ws, part["claim_id"], p["passage_id"], "not_relevant")
    assert claimcheck.hypothesis_result(ws, hid)["status"] == "unsupported"
    _step_up(ws, hid, be)
    res = claimcheck.hypothesis_result(ws, hid)
    # the person's judgements stay and count in both: the stronger model changes nothing they decided
    assert res["status"] == "unsupported" and res["status_before_stronger"] is None


def test_ask_a_stronger_model_for_a_whole_result_over_the_api(api, corpus, monkeypatch):
    from enlens_claims.gui import server

    api("PUT", "/api/settings", {"allow_cloud": True, "backend": "anthropic", "embed_backend": "off"})
    ehome.remember_key("sk-test")
    be = Hedging()
    monkeypatch.setattr(server.App, "backend", lambda self: (be, "claude-sonnet"))
    ws = ehome.create_project("S")
    ingest.ingest(ws, [corpus])
    hid = claimcheck.check_hypothesis(ws, HYP, be, "claude-sonnet", k=4, per_doc=2)
    h = api("GET", f"/api/projects/S/hypotheses/{hid}")[1]
    assert h["status"] == "partially_supported" and h["stronger_model"]
    assert api("POST", "/api/projects/S/hypotheses/nope/stronger", {})[0] == 404
    be.hedge = False
    st, r = api("POST", f"/api/projects/S/hypotheses/{hid}/stronger", {})
    assert st == 200, r
    job = api.wait(r["job"]["id"], timeout=60)
    assert job["state"] == "done" and job["result"]["answered"] == len(job["result"]["task_ids"]) >= 1
    h = api("GET", f"/api/projects/S/hypotheses/{hid}")[1]
    assert h["status"] == "supported" and h["status_before_stronger"] == "partially_supported"
    rows = api("GET", "/api/projects/S/hypotheses")[1]["hypotheses"]
    assert any(x["hyp_id"] == hid and x["status_before_stronger"] == "partially_supported" for x in rows)
    st, r = api("POST", f"/api/projects/S/hypotheses/{hid}/stronger", {})   # once at most
    assert st == 400 and "already" in r["error"]


def test_no_stronger_model_on_the_route_is_said_plainly(api, corpus):
    api("PUT", "/api/settings", {"backend": "baseline", "embed_backend": "off"})
    ws = ehome.create_project("B")
    ingest.ingest(ws, [corpus])
    be = Hedging()
    hid = claimcheck.check_hypothesis(ws, HYP, be, "m", k=3, per_doc=2)
    st, r = api("POST", f"/api/projects/B/hypotheses/{hid}/stronger", {})
    assert st == 400 and "no stronger model" in r["error"].lower()


def test_the_page_offers_two_distinct_choices():
    """The result page names the two ways to ask another model by what they do, links the release's styles, and
    asks for a stronger model for the whole result (not per search any more)."""
    from pathlib import Path

    static = Path(claimcheck.__file__).parent / "gui" / "static"
    index = (static / "index.html").read_text()
    from _static import rule  # 0.17.0: the release's rules are in the cascade, not in a sheet of its own

    # 0.17.0 (design guide): the mark is a tag (.chip) on a button, drawn by the Tags section; only its note's place is its own
    assert rule("button.chip") and rule(".was-wrap .pop") and 'was-mark' in (static / "lib.js").read_text()
    js = (static / "views" / "result.js").read_text()
    assert "replaces the AI's judgements" in js and "only for comparison" in js
    assert "/hypotheses/${P(hypId)}/stronger" in js and "/tasks/${P(rd.task_id)}/stronger" not in js
    assert "strongerMark(r.status_before_stronger" in js and "Highlight the quote of:" in js
    assert "models disagree" not in (static / "views" / "history.js").read_text()
