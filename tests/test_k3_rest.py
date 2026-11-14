"""0.18.8 (roadmap K3, the rest): the per-hypothesis exception (*Count non-scientific documents in this check*), the
suggestion from the bibliography's item type (never a mark by itself), the evidence map's own mark for a
non-scientific document (read, not counted), and the Excel summary's answer counting them."""
from __future__ import annotations

from enlens_claims import assessment, claimcheck, docrole, nonscientific
from enlens_claims.check_exports import document_answers, evidence_map, map_table, summary_table
from enlens_claims.check_results import hypothesis_result
from enlens_claims.llm import BaselineBackend
from enlens_claims.verdicts import UNSUPPORTED_NONSCI
from test_nonscientific_documents import CLAIM, NEWS, _first, _judge, project  # noqa: F401  (fixture)


def _log(ws, kind: str) -> list:
    return ws.query("SELECT text, data_json, why, subject_id FROM research_log WHERE kind=? ORDER BY at", (kind,))


# ---- 1. the exception, per hypothesis ------------------------------------------------------------------------------
def test_the_exception_counts_them_in_this_check_only(project):
    ws, news, _study, hid = project
    other = claimcheck.check_hypothesis(ws, "The hydrogen plant brings jobs to the coast", BaselineBackend(),
                                        "baseline", k=8, per_doc=4)
    _first(ws, hid, news, "supports")
    _first(ws, other, news, "supports")
    docrole.set_nonscientific(ws, news, True)
    assert hypothesis_result(ws, hid)["status"] == hypothesis_result(ws, other)["status"] == "unsupported"
    assert not hypothesis_result(ws, hid)["count_nonscientific"]          # off by default
    out = nonscientific.set_counting(ws, hid, True, why="The press coverage is what the study is about.")
    assert out["changed"] and (out["was"], out["now"]) == ("unsupported", "supported")
    assert out["was_text"] == UNSUPPORTED_NONSCI
    r = hypothesis_result(ws, hid)
    assert (r["status"], r["status_all_sources"], r["status_without_nonscientific"]) == \
        ("supported", "supported", "unsupported")
    assert r["count_nonscientific"] and r["count_nonscientific_why"].startswith("The press coverage")
    assert r["nonscientific_read"] and r["balance"]["docs_counted"] == 1
    xs = [x for p in r["parts"] for x in p["passages"] if x["doc_id"] == news]
    assert all(x["nonscientific_counted"] and not x["nonscientific"] for x in xs)
    assert any(x["counted"] for x in xs)
    # the other check is left as it was
    assert hypothesis_result(ws, other)["status"] == "unsupported"
    rows = {h["hyp_id"]: h for h in claimcheck.history(ws)}
    assert (rows[hid]["status"], rows[hid]["count_nonscientific"], rows[hid]["supports"]) == ("supported", True, 1)
    assert (rows[other]["status"], rows[other]["count_nonscientific"]) == ("unsupported", False)
    # the assessment in words says so, why, and the answer without them
    said = {s["rule"]: s["text"] for s in assessment.assess(ws, hid, r)["sentences"]}
    assert "non-scientific" not in said
    text = said["non-scientific-counted"]
    assert text.startswith("Non-scientific documents count in this check, as set on this hypothesis: The press")
    assert "One non-scientific document supports it" in text
    assert "the answer would be No evidence found" in text
    # the research log keeps both answers
    log = _log(ws, "check-setting")
    assert len(log) == 1 and log[0][3] == hid and log[0][2].startswith("The press coverage")
    assert f"changed from {UNSUPPORTED_NONSCI} to Supported by your documents" in log[0][0]
    # a second time changes nothing; off again brings the rule back
    assert nonscientific.set_counting(ws, hid, True)["changed"] is False
    back = nonscientific.set_counting(ws, hid, False)
    assert (back["was"], back["now"]) == ("supported", "unsupported")
    r = hypothesis_result(ws, hid)
    assert r["status"] == "unsupported" and not r["count_nonscientific"] and r["count_nonscientific_why"] is None
    assert len(_log(ws, "check-setting")) == 2


def test_the_exception_without_non_scientific_documents_changes_nothing(project):
    ws, _news, study, hid = project
    _judge(ws, hid, {study: "supports"})
    out = nonscientific.set_counting(ws, hid, True)
    assert out["changed"] and out["was"] == out["now"] == "supported"
    assert "The answer stays Supported by your documents" in _log(ws, "check-setting")[0][0]
    r = hypothesis_result(ws, hid)
    said = {s["rule"]: s["text"] for s in assessment.assess(ws, hid, r)["sentences"]}
    assert said["non-scientific-counted"].endswith(f"{nonscientific.REASON}.")   # the reason, even with none read
    try:
        nonscientific.set_counting(ws, "no-such-check", True)
    except KeyError:
        pass
    else:
        raise AssertionError("an unknown check is a KeyError")


def test_the_exception_holds_for_every_part(project):
    ws, news, study, _hid = project
    hid = claimcheck.check_hypothesis(ws, "Electrolyser plants create local jobs and hire workers", BaselineBackend(),
                                      "baseline", k=8, per_doc=4, decompose=True,
                                      parts=[CLAIM, "Electrolyser plants hire workers"])
    r = hypothesis_result(ws, hid)
    assert len(r["parts"]) == 2
    _judge(ws, hid, {news: "supports", study: "not_relevant"})
    docrole.set_nonscientific(ws, news, True)
    r = hypothesis_result(ws, hid)
    assert [p["status"] for p in r["parts"]] == ["unsupported", "unsupported"]
    nonscientific.set_counting(ws, hid, True)
    r = hypothesis_result(ws, hid)
    assert [p["status"] for p in r["parts"]] == ["supported", "supported"] and r["status"] == "supported"
    assert all(p["count_nonscientific"] for p in r["parts"])
    assert r["status_without_nonscientific"] == "unsupported"
    assert next(h for h in claimcheck.history(ws) if h["hyp_id"] == hid)["status"] == "supported"


# ---- 3. the evidence map: their own mark --------------------------------------------------------------------------
def test_the_map_shows_them_with_their_own_mark_and_counts_nothing_of_them(project):
    ws, news, study, hid = project
    _judge(ws, hid, {study: "supports", news: "refutes"})
    docrole.set_nonscientific(ws, news, True)
    m = evidence_map(ws)
    h = next(x for x in m["hypotheses"] if x["hyp_id"] == hid)
    assert (h["status"], h["docs_counted"], h["single_document"], h["count_nonscientific"]) == \
        ("supported", 1, True, False)
    cell = m["cells"][hid][news]
    assert cell == {"side": "refutes", "excerpts": cell["excerpts"], "nonscientific": True, "counted": False}
    assert "counted" not in m["cells"][hid][study]
    d = {x["doc_id"]: x for x in m["documents"]}
    assert d[news]["answers"] == 0 and d[news]["decides"] == 0 and d[news]["nonscientific"]
    assert d[study]["answers"] == 1 and not d[study]["nonscientific"]
    assert m["nonscientific_shown"] == 1 and m["documents_without_evidence"] == 0
    assert news not in document_answers(ws)["answers"]         # the Documents list counts no answer of it
    sheet = map_table(m)
    assert any(str(v).startswith("[− ") for row in sheet for v in row.values())
    assert "In brackets: a non-scientific document" in sheet[-1]["Hypothesis"]
    # where the hypothesis counts them, the cell counts too
    nonscientific.set_counting(ws, hid, True)
    m = evidence_map(ws)
    h = next(x for x in m["hypotheses"] if x["hyp_id"] == hid)
    assert (h["status"], h["docs_counted"], h["count_nonscientific"]) == ("contested", 2, True)
    assert m["cells"][hid][news]["counted"] is True and m["cells"][hid][news]["nonscientific"]
    assert next(x for x in m["documents"] if x["doc_id"] == news)["answers"] == 1
    assert document_answers(ws)["answers"][news] == 1


# ---- 4. the Excel summary -------------------------------------------------------------------------------------------
def test_the_summary_has_the_answer_counting_them_and_the_exception(project):
    ws, news, _study, hid = project
    _first(ws, hid, news, "supports")
    row = summary_table(ws)[0]
    assert row["Answer counting non-scientific documents"] == "" and row["Non-scientific documents counted here"] == ""
    docrole.set_nonscientific(ws, news, True)
    row = summary_table(ws)[0]
    assert row["Answer"] == UNSUPPORTED_NONSCI
    assert row["Answer counting non-scientific documents"] == "Supported by your documents"
    nonscientific.set_counting(ws, hid, True, why="Newspapers are the material here")
    row = summary_table(ws)[0]
    assert row["Answer"] == "Supported by your documents" and row["Answer counting non-scientific documents"] == ""
    assert row["Non-scientific documents counted here"] == "yes: Newspapers are the material here"
    assert "Non-scientific documents count in this check" in row["Assessment"]
    from enlens_claims.check_exports import export_table

    counted = [r["Counted in the answer"] for r in export_table(ws) if r["Document"].startswith("Hydrogen boom")]
    assert "yes: a non-scientific document, counted in this check" in counted


# ---- 2. the suggestion from the bibliography ------------------------------------------------------------------------
def _bib(ws, doc: str, item_type: str, key: str = "zotero:user:ABCD1234") -> None:
    with ws.connect() as cx:
        cx.execute("INSERT INTO bib_items(item_key, item_type, title, creators_json, seq) VALUES (?,?,?,?,?)",
                   (key, item_type, "A work", "[]", 1))
        cx.execute("INSERT INTO bib_links(item_key, doc_id, status, method) VALUES (?,?,?,?)",
                   (key, doc, "confirmed", "test"))


def test_the_bibliography_suggests_and_never_marks(project):
    ws, news, study, _hid = project
    _bib(ws, news, "newspaperArticle")
    _bib(ws, study, "journalArticle", key="zotero:user:EFGH5678")
    assert nonscientific.suggestions(ws) == {news: {"item_type": "newspaperArticle", "words": "a newspaper article"}}
    assert nonscientific.suggestion(ws, news)["text"] == \
        "Your bibliography lists this as a newspaper article. Mark it as non-scientific?"
    assert nonscientific.suggestion(ws, study) is None
    assert not docrole.is_nonscientific(ws, news)                      # suggested, never marked by itself
    # marked: no longer suggested; counted again: suggested again (nobody said No)
    docrole.set_nonscientific(ws, news, True)
    assert nonscientific.suggestions(ws) == {}
    docrole.set_nonscientific(ws, news, False)
    assert news in nonscientific.suggestions(ws)
    # No is remembered, as a decision in the research log
    assert nonscientific.decline(ws, news) == {"doc_id": news, "declined": True}
    assert nonscientific.suggestions(ws) == {} and nonscientific.declined(ws) == {news}
    log = _log(ws, "document-suggestion")
    assert len(log) == 1 and "lists it as a newspaper article" in log[0][0]
    nonscientific.decline(ws, news)
    assert len(_log(ws, "document-suggestion")) == 1                     # once
    # a working document is never suggested
    _bib(ws, study, "blogPost", key="zotero:user:IJKL9012")
    with ws.connect() as cx:
        cx.execute("DELETE FROM bib_links WHERE item_key='zotero:user:EFGH5678'")
    assert study in nonscientific.suggestions(ws)
    docrole.set_role(ws, study, "working")
    assert study not in nonscientific.suggestions(ws)


def test_the_item_types_in_words():
    assert nonscientific.type_words("magazineArticle") == "a magazine article"
    assert nonscientific.type_words("article-newspaper") == "a newspaper article"
    assert nonscientific.type_words("post-weblog") == "a blog post"
    assert nonscientific.type_words("NEWS") == "a newspaper article"
    assert nonscientific.type_words("Online") == "a web page"
    for t in ("journalArticle", "article-journal", "book", "report", "JOUR", "thesis", None, ""):
        assert nonscientific.type_words(t) is None


# ---- the routes -----------------------------------------------------------------------------------------------------
def test_the_routes(api, tmp_path):  # noqa: F811
    from enlens_claims import home, ingest
    from enlens_claims.store import Workspace

    d = tmp_path / "in"
    d.mkdir()
    (d / "news.txt").write_text(NEWS, encoding="utf-8")
    assert api("POST", "/api/projects", {"name": "News"})[0] == 200
    ws = Workspace.open(home.project_path("News"))
    try:
        ingest.ingest(ws, [d])
        news = ws.scalar("SELECT doc_id FROM documents")
        hid = claimcheck.check_hypothesis(ws, CLAIM, BaselineBackend(), "baseline", k=4)
        _bib(ws, news, "webpage")
    finally:
        ws.close_all()
    assert api("GET", "/api/projects/News/document-roles")[1]["suggested"] == {news: "a web page"}
    st, body = api("GET", f"/api/projects/News/documents/{news}/nonscientific-suggestion")
    assert st == 200 and body["suggestion"]["words"] == "a web page"
    assert api("POST", f"/api/projects/News/documents/{news}/nonscientific-suggestion", {"answer": "yes"})[0] == 400
    assert api("POST", "/api/projects/News/documents/nope/nonscientific-suggestion", {"answer": "no"})[0] == 404
    assert api("GET", "/api/projects/News/documents/nope/nonscientific-suggestion")[0] == 404
    st, body = api("POST", f"/api/projects/News/documents/{news}/nonscientific-suggestion", {"answer": "no"})
    assert st == 200 and body["declined"]
    assert api("GET", f"/api/projects/News/documents/{news}/nonscientific-suggestion")[1]["suggestion"] is None
    assert api("GET", "/api/projects/News/document-roles")[1]["suggested"] == {}
    st, body = api("PUT", f"/api/projects/News/hypotheses/{hid}/nonscientific", {"count": True, "why": "Media study"})
    assert st == 200 and body["changed"] and body["count_nonscientific"]
    assert api("GET", f"/api/projects/News/hypotheses/{hid}")[1]["count_nonscientific"] is True
    assert api("PUT", f"/api/projects/News/hypotheses/{hid}/nonscientific", {"count": "yes"})[0] == 400
    assert api("PUT", "/api/projects/News/hypotheses/nope/nonscientific", {"count": True})[0] == 404


# ---- between copies -------------------------------------------------------------------------------------------------
def test_the_exception_and_a_no_travel_with_the_project(anna_and_ben):  # noqa: F811
    anna, ben = anna_and_ben
    with anna:
        doc = anna.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        nonscientific.set_counting(anna.ws, anna.hid, True, why="Reports are the material")
        nonscientific.decline(anna.ws, doc)
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["updated"] == 1
    with ben:
        assert nonscientific.counts_here(ben.ws, anna.hid)
        assert nonscientific.why_here(ben.ws, anna.hid) == "Reports are the material"
        assert hypothesis_result(ben.ws, anna.hid)["count_nonscientific"]
        assert doc in nonscientific.declined(ben.ws)
    # turned off later by Ben: as for a note, it is Anna's own check, so Ben's version comes in beside hers (roles,
    # H5), and that copy holds his setting
    with ben:
        nonscientific.set_counting(ben.ws, anna.hid, False)
        assert not nonscientific.counts_here(ben.ws, anna.hid)
    rep = anna.bring_in(ben.send())
    assert rep["checks"]["updated"] == 0 and len(rep["checks"]["clash"]) == 1
    with anna:
        assert nonscientific.counts_here(anna.ws, anna.hid)
        assert not nonscientific.counts_here(anna.ws, rep["checks"]["clash"][0]["hyp_id"])

from test_shared_projects import anna_and_ben  # noqa: E402,F401  (fixture)
from test_app import api, home  # noqa: E402,F401  (fixtures)
