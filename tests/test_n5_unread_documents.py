"""Roadmap N5, the per-hypothesis half: the documents a check never read, split by whether they hold its words.

- `unread_documents` splits the documents none of whose excerpts a check showed into those with at least two of the
  check's words in one excerpt (`docs_matching(min_words=2)`), those sharing one word only, and those sharing none;
- it leaves out theory documents, documents added after the check, documents with no readable text and documents a
  check limited to some documents was limited away from; Non-scientific documents are in it;
- *Read these* (`read_unread_documents`) adds one round limited to exactly those documents and changes no review;
- the routes, and the result page's block.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enlens_claims import claimcheck, docrole, ingest
from enlens_claims.search import docs_matching
from enlens_claims.gui import server

CLAIM = "Green hydrogen production can increase water stress in arid regions."
STATIC = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static"

# each a document of its own, added before the check; the first words of the text are its title
EXTRA = {
    "desal.txt": "Desalination and water stress. Water stress worries the farmers near the new plant each summer. " * 3,
    "solar.txt": "Solar parks and arid land. Solar parks spread over arid land and the regions around it. " * 3,
    "garden.txt": "Garden notes. The garden needs water every morning when the weather turns warm. " * 3,
    "bread.txt": "Baking bread. A recipe for bread with flour, yeast and salt, baked for an hour. " * 3,
}


class Scripted:
    """A backend that answers each task kind from a prepared answer (a function of the payload, or a dict)."""
    name = "scripted"

    def __init__(self, **answers):
        self.answers = answers

    def complete(self, kind, system, user, model, payload):
        a = self.answers.get(kind, {})
        return json.dumps(a(payload) if callable(a) else a)


def _grade(verdict="supports", confidence=0.8):
    def answer(payload):
        return {"evidence": [{"passage": i, "verdict": verdict, "confidence": confidence,
                              "quote": " ".join(p["text"].split()[:6]), "scope_note": None}
                             for i, p in enumerate(payload["passages"], 1)], "rationale": "r"}
    return answer


BE = Scripted(check=_grade())


@pytest.fixture
def project(loaded, tmp_path):
    (tmp_path / "extra").mkdir()
    for name, text in EXTRA.items():
        (tmp_path / "extra" / name).write_text(text)
    ingest.ingest(loaded, [tmp_path / "extra"])
    ids = {r["title"].split()[0].lower(): r["doc_id"] for r in loaded.query("SELECT doc_id, title FROM documents")}
    return loaded, ids


def _check(ws, **kw):
    """A check that reads one excerpt (the best one, of the paper on water and hydrogen) with the claim's own words."""
    return claimcheck.check_hypothesis(ws, CLAIM, BE, "m", k=1, per_doc=1, expand=False, terms=[], **kw)


def _read(ws, hid):
    return {x["doc_id"] for x in claimcheck.result(ws, hid)["passages"]}


def test_the_split_by_the_checks_own_words(project):
    ws, ids = project
    hid = _check(ws)
    assert _read(ws, hid) == {ids["water"]}   # the paper on water and hydrogen: the one excerpt read
    u = claimcheck.unread_documents(ws, hid)
    assert u["checked"] and u["considered"] == 6
    # two different words of the hypothesis in one excerpt ("water stress"; "arid … regions"; the IRENA report's
    # "hydrogen … production")
    assert {d["doc_id"] for d in u["matching"]} == {ids["desalination"], ids["solar"], ids["irena."]}
    assert u["matching_n"] == 3
    assert u["one_word_n"] == 1                # the garden: "water" alone
    assert {d["doc_id"] for d in u["no_word"]} == {ids["baking"], ids["bird"]} and u["no_word_n"] == 2
    assert [d["title"] for d in u["matching"]] == sorted((d["title"] for d in u["matching"]), key=str.lower)
    # nothing was read by a model, and no result changed
    before = claimcheck.hypothesis_result(ws, hid)
    claimcheck.unread_documents(ws, hid)
    assert claimcheck.hypothesis_result(ws, hid)["status"] == before["status"]
    assert len(claimcheck.result(ws, hid)["passages"]) == 1


def test_the_stricter_bar_rejects_one_common_word(project):
    ws, ids = project
    every = {ids["garden"], ids["desalination"], ids["baking"]}
    assert docs_matching(ws, CLAIM, [], every) == {ids["garden"], ids["desalination"]}   # the old rule: one word
    assert docs_matching(ws, CLAIM, [], every, min_words=2) == {ids["desalination"]}
    # a search word adds its words: "watering the garden" … still one word of the garden's text
    assert docs_matching(ws, CLAIM, ["weather"], every, min_words=2) == {ids["desalination"], ids["garden"]}
    # with fewer words than the bar, every one of them is enough
    assert docs_matching(ws, "water", [], every, min_words=2) == {ids["garden"], ids["desalination"]}


def test_left_out_theory_late_unreadable_and_limited_away(project, tmp_path, monkeypatch):
    ws, ids = project
    hid = _check(ws)
    docrole.set_role(ws, ids["solar"], "theory")            # a lens, not evidence
    docrole.set_nonscientific(ws, ids["irena."], True)       # still read and judged: still in it
    with ws.connect() as cx:                                 # every excerpt left out of the text (or never read)
        cx.execute("UPDATE passages SET section='front' WHERE doc_id=?", (ids["desalination"],))
        ws.bump_corpus(cx)
    from enlens_claims import store

    monkeypatch.setattr(store, "_dt", _Skewed(2))            # a document added after the check
    (tmp_path / "late").mkdir()
    (tmp_path / "late" / "late.txt").write_text("Late study. Water stress rises where hydrogen production grows. " * 3)
    ingest.ingest(ws, [tmp_path / "late"])
    late = ws.scalar("SELECT doc_id FROM documents WHERE title LIKE 'Late%'")
    assert [d["doc_id"] for d in claimcheck.new_documents(ws, hid)] == [late]   # it is the check's "added since"
    u = claimcheck.unread_documents(ws, hid)
    assert {d["doc_id"] for d in u["matching"]} == {ids["irena."]}
    assert u["considered"] == 4 and u["one_word_n"] == 1 and u["no_word_n"] == 2
    every = {d["doc_id"] for d in u["matching"] + u["no_word"]}
    assert not every & {ids["solar"], ids["desalination"], late, ids["water"]}

    # a check limited to some documents: the others were limited away
    hid2 = _check(ws, doc_ids=[ids["water"], ids["irena."], ids["garden"], ids["baking"]])
    assert _read(ws, hid2) == {ids["water"]}
    u2 = claimcheck.unread_documents(ws, hid2)
    assert u2["considered"] == 3 and u2["one_word_n"] == 1                       # the garden
    assert [d["doc_id"] for d in u2["matching"]] == [ids["irena."]]
    assert [d["doc_id"] for d in u2["no_word"]] == [ids["baking"]]             # not the birds: limited away
    # Read these keeps to the limit too
    r = claimcheck.read_unread_documents(ws, hid2, BE, "m", k=8)
    assert {x["doc_id"] for x in claimcheck.result(ws, hid2)["passages"] if x["round"] == 2} == {ids["irena."]}
    assert r["documents"] == 1


def test_a_check_that_read_nothing_has_none(project):
    ws, _ids = project
    hid = claimcheck.check_hypothesis(ws, "Zyxwv qwerty plorb.", BE, "m", k=1, expand=False, terms=[])
    u = claimcheck.unread_documents(ws, hid)
    assert not u["checked"] and u["matching_n"] == u["no_word_n"] == 0 and u["matching"] == u["no_word"] == []
    with pytest.raises(KeyError):
        claimcheck.unread_documents(ws, "h-none")


def test_read_these_adds_one_round_limited_to_them_and_keeps_the_reviews(project):
    ws, ids = project
    hid = _check(ws)
    pid = claimcheck.result(ws, hid)["passages"][0]["passage_id"]
    claimcheck.set_judgement(ws, hid, pid, "refutes", "mine")
    before = claimcheck.unread_documents(ws, hid)
    wanted = {d["doc_id"] for d in before["matching"]}
    r = claimcheck.read_unread_documents(ws, hid, Scripted(check=_grade("refutes", 0.9)), "m", k=8)
    assert r["documents"] == 3 and r["passages"] >= 3 and [x["round"] for x in r["rounds"]] == [2]
    res = claimcheck.result(ws, hid)
    assert {x["doc_id"] for x in res["passages"] if x["round"] == 2} == wanted   # exactly those documents
    first = next(x for x in res["passages"] if x["passage_id"] == pid)
    assert first["user_verdict"] == "refutes" and first["round"] == 1           # the review is kept
    after = claimcheck.unread_documents(ws, hid)
    assert after["matching_n"] == 0 and after["no_word_n"] == before["no_word_n"]
    assert after["one_word_n"] == before["one_word_n"]
    assert claimcheck.new_documents(ws, hid) == []                              # nothing counts as added since
    # nothing left: another press reads nothing and makes no round
    again = claimcheck.read_unread_documents(ws, hid, BE, "m", k=8)
    assert again == {"hyp_id": hid, "documents": 0, "passages": 0, "rounds": []}


def test_the_routes_the_export_and_the_page_contract(project):
    ws, ids = project
    for method, path, handler in (("GET", "/api/projects/Q/hypotheses/h1/unread", "get_unread"),
                                  ("POST", "/api/projects/Q/hypotheses/h1/read-unread", "post_read_unread")):
        assert any(m == method and h == handler and p.match(path) for m, p, h in server.ROUTES)
    hid = _check(ws)
    row = claimcheck.summary_table(ws, hyp_ids=[hid])[0]
    assert row["Documents with the search words never read"] == 3
    keys = list(row)
    assert keys.index("Documents with the search words never read") == keys.index("Documents added since the check") + 1
    js = (STATIC / "views" / "result.js").read_text(encoding="utf-8")
    assert "/unread`" in js and "/read-unread`" in js and '"read-unread"' in js
    assert "never read in this check" in js and "Search with other words" in js
    assert "circle-dashed" not in js[js.index("function unreadCard"):js.index("function openOtherWords")]
    reg = (STATIC / "registry.js").read_text(encoding="utf-8")
    assert '"read-unread": {' in reg


def test_the_endpoints_answer(project):
    from types import SimpleNamespace

    from enlens_claims.gui.api_checks import ChecksApi
    from enlens_claims.gui.api_common import ApiError

    ws, ids = project
    hid = _check(ws)
    started = []
    stub = SimpleNamespace(app=SimpleNamespace(ws=lambda name: ws,
                                               start_read_unread=lambda name, h: started.append((name, h)) or
                                               SimpleNamespace(view=lambda: {"id": "j1", "kind": "read-unread"})))
    got = ChecksApi.get_unread(stub, "Q", hid, {})
    assert set(got) == {"hyp_id", "checked", "considered", "matching", "matching_n", "one_word_n", "no_word",
                        "no_word_n"}
    assert all(set(d) == {"doc_id", "title"} for d in got["matching"] + got["no_word"])
    assert ChecksApi.post_read_unread(stub, "Q", hid, {}) == {"job": {"id": "j1", "kind": "read-unread"}}
    assert started == [("Q", hid)]
    with pytest.raises(ApiError) as e:
        ChecksApi.get_unread(stub, "Q", "h-none", {})
    assert e.value.status == 404
    claimcheck.read_unread_documents(ws, hid, BE, "m", k=8)
    with pytest.raises(ApiError) as e:                                          # nothing left to read
        ChecksApi.post_read_unread(stub, "Q", hid, {})
    assert e.value.status == 400


class _Skewed:
    """Stands in for `datetime` inside `store`, so that `store.now()` runs `seconds` ahead of the real clock."""

    def __init__(self, seconds):
        import datetime as real
        self._real, self._skew = real, real.timedelta(seconds=seconds)
        outer = self

        class _DT:
            @staticmethod
            def now(tz=None):
                return outer._real.datetime.now(tz) + outer._skew
        self.datetime = _DT

    def __getattr__(self, name):
        return getattr(self._real, name)
