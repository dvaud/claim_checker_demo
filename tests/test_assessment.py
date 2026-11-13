"""The assessment in words (roadmap N4, 0.18.1): sentences made by rules under a hypothesis's verdict."""
import json

from enlens_claims import assessment, claimcheck

CLAIM = "Green hydrogen production can increase water stress in arid regions."


def _x(pid, doc, verdict, conf=0.9, quote=None, access="cloud", user=None, title=None, location="page 3", **kw):
    """An excerpt of a result, as `claimcheck._result` gives it."""
    eff = user if user and user != "not_relevant" else (None if user == "not_relevant" else verdict)
    d = {"passage_id": pid, "doc_id": doc, "title": title or f"Report {doc}", "location": location,
         "verdict": eff, "ai_verdict": verdict, "confidence": conf if verdict else None,
         "user_verdict": user, "user_note": None, "judged_by": "you" if user else None, "reviewed": bool(user),
         "counted": bool(eff) and ((conf or 0) >= 0.7 or bool(user)), "quote": quote, "access": access,
         "read_by": "ai", "ai_read": True, "round_failed": False, "waiting_for_you": False, "waiting_local": False}
    d.update(kw)
    return d


def _res(passages, status, balance=None, parts=None, thr=0.7, text="Irrigation raised yields because water was cheap"):
    p = {"claim_id": "c1", "part": 1, "claim": text, "status": status, "balance": balance or {}, "passages": passages}
    return {"hyp_id": "h1", "text": text, "status": status, "threshold": thr, "balance": balance or {},
            "parts": parts or [p]}


def _rules(a):
    return [s["rule"] for s in a["sentences"]]


def test_verdict_and_both_sides_quoted(ws):
    xs = [_x("p1", "d1", "supports", quote="yields rose by a third"),
          _x("p2", "d2", "supports", quote="harvests grew in every district"),
          _x("p3", "d3", "refutes", quote="no measurable change in yields")]
    bal = {"docs_supporting": 2, "docs_partly": 0, "docs_refuting": 1, "docs_both": 0, "docs_counted": 3}
    a = assessment.assess(ws, "h1", _res(xs, "contested", bal))
    s = a["sentences"]
    assert s[0]["rule"] == "verdict" and s[0]["text"] == ("Mixed evidence. Two documents support the hypothesis and "
                                                          "one document contradicts it.")
    against = next(x for x in s if x["rule"] == "against")
    assert "“no measurable change in yields” (Report d3, page 3)" in against["text"] and against["refs"] == ["c1/p3"]
    pro = next(x for x in s if x["rule"] == "for")  # mixed evidence: the supporting side is quoted too
    assert "yields rose by a third" in pro["text"] and "harvests grew" in pro["text"]
    assert a["moved_by"] is None


def test_contradicting_side_always_quoted_and_no_for_side_without_it(ws):
    xs = [_x("p3", "d3", "refutes", quote="no measurable change in yields")]
    a = assessment.assess(ws, "h1", _res(xs, "contradicted", {"docs_refuting": 1, "docs_counted": 1}))
    assert _rules(a)[:2] == ["verdict", "against"] and "for" not in _rules(a)
    xs = [_x("p1", "d1", "supports", quote="yields rose by a third")]
    a = assessment.assess(ws, "h1", _res(xs, "supported", {"docs_supporting": 1, "docs_counted": 1}))
    assert "against" not in _rules(a) and "for" not in _rules(a)


def test_one_document_carries_most_of_the_support(ws):
    xs = [_x(f"p{i}", "d1", "supports", quote="yields rose") for i in range(4)] + [
        _x("q1", "d2", "supports", quote="harvests grew"), _x("q2", "d3", "partially_supports", quote="some growth")]
    bal = {"docs_supporting": 2, "docs_partly": 1, "docs_counted": 3}
    a = assessment.assess(ws, "h1", _res(xs, "supported", bal))
    c = next(x for x in a["sentences"] if x["rule"] == "concentration")
    assert c["text"] == "Most of the support comes from one document (Report d1, 4 of 6 excerpts)."
    assert len(c["refs"]) == 4
    one = assessment.assess(ws, "h1", _res(xs[:2], "supported", {"docs_supporting": 1, "docs_counted": 1}))
    assert any(x["text"] == "All the support comes from one document: Report d1 (two excerpts)."
               for x in one["sentences"])


def test_support_from_one_year_named_from_the_bibliography(ws):
    with ws.connect() as cx:
        for d, who in (("d1", "Smith"), ("d2", "Jones")):
            cx.execute("INSERT INTO bib_items(item_key, item_type, title, creators_json, year, seq) VALUES (?,?,?,?,?,?)",
                       (f"k{d}", "report", f"Work {d}", json.dumps([{"last": who}]), "2021", 1))
            cx.execute("INSERT INTO bib_links(item_key, doc_id, status) VALUES (?,?,?)", (f"k{d}", d, "confirmed"))
    xs = [_x("p1", "d1", "supports", quote="yields rose"), _x("p2", "d2", "supports", quote="harvests grew")]
    a = assessment.assess(ws, "h1", _res(xs, "supported", {"docs_supporting": 2, "docs_counted": 2}))
    assert any(s["text"] == "All the support comes from documents of 2021." for s in a["sentences"])
    xs.append(_x("p3", "d3", "refutes", quote="no change at all"))
    with ws.connect() as cx:
        cx.execute("INSERT INTO bib_items(item_key, item_type, title, creators_json, year, seq) VALUES (?,?,?,?,?,?)",
                   ("kd3", "report", "Work d3", json.dumps([{"last": "Jones"}]), "2022", 1))
        cx.execute("INSERT INTO bib_links(item_key, doc_id, status) VALUES (?,?,?)", ("kd3", "d3", "confirmed"))
    a = assessment.assess(ws, "h1", _res(xs, "contested", {"docs_supporting": 2, "docs_refuting": 1,
                                                           "docs_counted": 3}))
    assert "(Jones 2022, page 3)" in next(s for s in a["sentences"] if s["rule"] == "against")["text"]


def test_each_part_what_holds_and_what_has_no_evidence(ws):
    p1 = {"claim_id": "c1", "part": 1, "claim": "Irrigation raised yields", "status": "supported",
          "balance": {"docs_counted": 2}, "passages": [_x("p1", "d1", "supports", quote="yields rose")]}
    p2 = {"claim_id": "c2", "part": 2, "claim": "because irrigation expanded", "status": "unsupported",
          "balance": {}, "passages": [_x("p2", "d1", None)]}
    res = _res([], "partially_supported", {"docs_supporting": 1, "docs_counted": 1}, parts=[p1, p2])
    a = assessment.assess(ws, "h1", res)
    parts = [s["text"] for s in a["sentences"] if s["rule"] == "part"]
    assert parts == ["Part 1, “Irrigation raised yields”, holds (two documents).",
                     "Part 2, “because irrigation expanded”, has no evidence: nothing found was about it."]


def test_what_is_not_counted(ws):
    xs = [_x("p1", "d1", "supports", quote="yields rose"), _x("p2", "d2", "supports", conf=0.5, quote="maybe more"),
          _x("p3", "d3", None, read_by="you", ai_read=False, waiting_for_you=True, access="none"),
          _x("p4", "d4", None, waiting_local=True, ai_read=False, access="local")]
    a = assessment.assess(ws, "h1", _res(xs, "supported", {"docs_supporting": 1, "docs_counted": 1}))
    by = {s["rule"]: s for s in a["sentences"]}
    assert by["below-strictness"]["text"].startswith("One excerpt about the hypothesis is not counted") and \
        "(0.70)" in by["below-strictness"]["text"] and by["below-strictness"]["refs"] == ["c1/p2"]
    assert by["waiting-for-you"]["refs"] == ["c1/p3"] and "no AI may read" in by["waiting-for-you"]["text"]
    assert by["waiting-local"]["refs"] == ["c1/p4"]


def test_restricted_documents_never_quoted(ws):
    secret = "the secret field notes say yields fell"
    xs = [_x("p1", "d1", "supports", quote="yields rose"),
          _x("p2", "d2", "refutes", quote=secret, access="none", title="Private interviews"),
          _x("p3", "d3", "refutes", quote=secret, access="local", title="Local report")]
    a = assessment.assess(ws, "h1", _res(xs, "contested", {"docs_supporting": 1, "docs_refuting": 2,
                                                           "docs_counted": 3}))
    words = assessment.text(a)
    assert secret not in words and "Private interviews" not in words and "Local report" not in words
    assert "two documents not quoted here" in words


def test_moved_by_names_the_one_judgement(ws):
    xs = [_x("p1", "d1", "supports", quote="yields rose"),
          _x("p2", "d2", "supports", quote="no change in yields", user="refutes")]
    a = assessment.assess(ws, "h1", _res(xs, "contested", {"docs_supporting": 1, "docs_refuting": 1,
                                                           "docs_counted": 2}))
    m = a["moved_by"]
    assert m["text"] == "Your judgement on Report d2, page 3 turned this from Supported to Mixed evidence."
    assert m["from"] == "supported" and m["to"] == "contested" and m["refs"] == ["c1/p2"]
    assert a["sentences"][-1]["rule"] == "moved-by"
    # a judgement that agrees with the AI moves nothing
    xs[1] = _x("p2", "d2", "supports", quote="yields rose too", user="supports")
    assert assessment.assess(ws, "h1", _res(xs, "supported", {"docs_supporting": 2, "docs_counted": 2}))["moved_by"] is None


def test_moved_by_says_nothing_when_its_status_is_not_the_one_shown(ws):
    xs = [_x("p1", "d1", "supports", quote="yields rose"),
          _x("p2", "d2", "supports", quote="no change in yields", user="refutes")]
    assert assessment.assess(ws, "h1", _res(xs, "supported", {}))["moved_by"] is None


def test_the_same_text_twice(ws):
    xs = [_x("p2", "d2", "supports", quote="harvests grew"), _x("p1", "d1", "supports", quote="yields rose"),
          _x("p3", "d3", "refutes", quote="no change"), _x("p4", "d3", "refutes", quote="none at all", conf=0.95)]
    bal = {"docs_supporting": 2, "docs_refuting": 1, "docs_counted": 3}
    a = assessment.assess(ws, "h1", _res(xs, "contested", bal))
    b = assessment.assess(ws, "h1", _res(list(reversed(xs)), "contested", bal))
    assert a == b


# ---------------------------------------------------------------------------------------------
# in a real check: the result, the exports and the research log
# ---------------------------------------------------------------------------------------------
class _Judge:
    """Says every excerpt supports the claim, quoting its first words."""
    name = "judge"

    def complete(self, kind, system, user, model, payload):
        if kind == "expand":
            return '{"terms": ["water"]}'
        ev = [{"passage": i, "verdict": "supports", "confidence": 0.9, "quote": " ".join(p["text"].split()[:5])}
              for i, p in enumerate(payload["passages"], 1)]
        return json.dumps({"evidence": ev})


def test_in_a_check_follows_the_persons_judgement(loaded):
    hid = claimcheck.check_hypothesis(loaded, CLAIM, _Judge(), "m", k=3, expand=False)
    res = claimcheck.hypothesis_result(loaded, hid)
    assert res["status"] == "supported" and res["assessment"]["sentences"][0]["rule"] == "verdict"
    assert res["assessment"]["moved_by"] is None
    x = res["parts"][0]["passages"][0]
    out = claimcheck.set_judgement(loaded, res["parts"][0]["claim_id"], x["passage_id"], "refutes")
    assert out["before"] == "supported" and out["after"] in ("contested", "contradicted")
    assert out["moved"].startswith("Your judgement on ") and " to " in out["moved"]
    log = loaded.query("SELECT kind, text, subject_id FROM research_log WHERE kind='verdict-moved'")
    assert [(r["text"], r["subject_id"]) for r in log] == [(out["moved"], hid)]
    res = claimcheck.hypothesis_result(loaded, hid)
    assert res["assessment"]["moved_by"] and res["assessment"]["moved_by"]["refs"] == [
        f"{res['parts'][0]['claim_id']}/{x['passage_id']}"]
    # the same judgement again moves nothing more, and is not logged twice
    again = claimcheck.set_judgement(loaded, res["parts"][0]["claim_id"], x["passage_id"], "refutes")
    assert again["moved"] is None and len(loaded.query("SELECT 1 FROM research_log WHERE kind='verdict-moved'")) == 1
    # the sentence names the answer at the strictness the page shows (review, 0.18.1)
    strict = claimcheck.set_judgement(loaded, res["parts"][0]["claim_id"], x["passage_id"], None, threshold=0.95)
    assert strict["after"] == claimcheck.hypothesis_result(loaded, hid, 0.95)["status"]
    claimcheck.set_judgement(loaded, res["parts"][0]["claim_id"], x["passage_id"], "refutes")
    res = claimcheck.hypothesis_result(loaded, hid)
    row = claimcheck.summary_table(loaded, hyp_ids=[hid])[0]
    assert row["Assessment"] == assessment.text(res["assessment"]) and row["Assessment"]
    assert claimcheck.hypothesis_rows(res)[0]["assessment"] == row["Assessment"]
