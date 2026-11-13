"""Roadmap N5, first half: how many answers each document is behind, for the Documents list.

- `document_answers` counts as the evidence map does (an excerpt that counts at the strictness; a person's judgement
  always counts), without the map's leave-one-out, and says how many hypotheses were checked and when the last one was;
- the route the Documents list reads it from;
- the map's "Show them in Documents" opens the grouping and the group the Documents list draws.
"""
from __future__ import annotations

import json
from pathlib import Path

from enlens_claims import claimcheck, docrole
from enlens_claims.gui import server

CLAIM = "Green hydrogen production can increase water stress in arid regions."
STATIC = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static"


class Scripted:
    """A backend that answers each task kind from a list of prepared answers (the last one repeats)."""
    name = "scripted"

    def __init__(self, **answers):
        self.answers = {k: list(v) for k, v in answers.items()}

    def complete(self, kind, system, user, model, payload):
        got = self.answers.get(kind) or [{}]
        a = got.pop(0) if len(got) > 1 else got[0]
        return json.dumps(a(payload) if callable(a) else a)


def _grade(verdicts):
    """A check answer grading each passage by its document's title (the first six letters), or by "*"."""
    def answer(payload):
        ev = []
        for i, p in enumerate(payload["passages"], 1):
            v = verdicts.get(p["title"][:6], verdicts.get("*"))
            if v:
                ev.append({"passage": i, "verdict": v[0], "confidence": v[1], "quote": " ".join(p["text"].split()[:6]),
                           "scope_note": None})
        return {"evidence": ev, "rationale": "r"}
    return answer


def test_nothing_checked_yet(loaded):
    assert claimcheck.document_answers(loaded) == {"threshold": claimcheck.document_answers(loaded)["threshold"],
                                                   "answers": {}, "hypotheses": 0, "last_check": None}


def test_the_counts_are_the_evidence_maps(loaded):
    titles = {r["title"][:6]: r["doc_id"] for r in loaded.query("SELECT doc_id, title FROM documents")}
    water = next(t for t in titles if t.startswith("Water"))
    be = Scripted(expand=[{"terms": ["x"]}], check=[_grade({water: ("supports", 0.9), "*": ("refutes", 0.8)})])
    claimcheck.check_hypothesis(loaded, CLAIM, be, "m", k=4, per_doc=1)
    be2 = Scripted(expand=[{"terms": ["x"]}], check=[_grade({water: ("supports", 0.9)})])
    claimcheck.check_hypothesis(loaded, "Hydrogen export hubs create local jobs in Morocco.", be2, "m", k=4, per_doc=1)

    got = claimcheck.document_answers(loaded)
    m = claimcheck.evidence_map(loaded)
    assert got["answers"] == {d["doc_id"]: d["answers"] for d in m["documents"]}
    assert got["answers"][titles[water]] == 2 and got["hypotheses"] == 2 and got["last_check"]
    assert all(n >= 1 for n in got["answers"].values())   # only the documents behind an answer
    # the light map is the map, less who decides what
    light = claimcheck.evidence_map(loaded, decide=False)
    assert light["cells"] == m["cells"] and all(d["decides"] == 0 and not d["key"] for d in light["documents"])
    assert {d["doc_id"]: d["answers"] for d in light["documents"]} == got["answers"]
    # a stricter setting counts fewer excerpts: the refutes at 0.8 no longer count, the supports at 0.9 still do
    strict = claimcheck.document_answers(loaded, 0.85)
    assert strict["answers"] == {titles[water]: 2} and strict["threshold"] == 0.85
    # a theory document is never read by a check, so it is behind no answer from here on
    other = next(d for d in got["answers"] if d != titles[water])
    docrole.set_role(loaded, other, "theory")
    assert other in claimcheck.document_answers(loaded)["answers"]   # the answers already given stand as they are


def test_the_route_and_the_lists_contract():
    assert any(h == "get_map_documents" and p.match("/api/projects/Q/map/documents") for _m, p, h in server.ROUTES)
    assert not any(h == "get_document" and p.match("/api/projects/Q/map/documents") for _m, p, h in server.ROUTES)
    sources = (STATIC / "views" / "sources.js").read_text(encoding="utf-8")
    mapjs = (STATIC / "views" / "map.js").read_text(encoding="utf-8")
    # the map's link opens the grouping "answers" with its group "unused" unfolded: both names are the list's own
    assert 'store(`docs-group:${project}`, "answers")' in mapjs and '"answers:unused"' in mapjs
    assert "    answers: { label:" in sources and '{ key: "unused",' in sources
    assert "/map/documents?threshold=" in sources
