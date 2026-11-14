"""0.18.8 (roadmap K3, the rest): the per-hypothesis exception (*Count non-scientific documents in this check*), the
suggestion from the bibliography's item type (never a mark by itself), the evidence map's own mark for a
non-scientific document (read, not counted), and the Excel summary's answer counting them."""
from __future__ import annotations

import json

import pytest

from enlens_claims import assessment, claimcheck, docrole, judgements, nonscientific
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
    assert nonscientific.REASON not in log[0][0]          # their own reason is the entry's, not the stock one
    assert json.loads(log[0][1]) == {"count_nonscientific": True, "was": "unsupported", "was_text": UNSUPPORTED_NONSCI,
                                     "now": "supported", "now_text": "Supported by your documents"}
    # a second time changes nothing, nor the same reason again
    assert nonscientific.set_counting(ws, hid, True)["changed"] is False
    assert nonscientific.set_counting(ws, hid, True, why=" The press coverage is what the study is about. ")[
        "changed"] is False
    assert len(_log(ws, "check-setting")) == 1
    # a new reason while it is on: kept, and logged once, the answer as it was
    out = nonscientific.set_counting(ws, hid, True, why="Media framing is the topic")
    assert out["changed"] and out["why_changed"] and out["was"] == out["now"] == "supported"
    assert nonscientific.why_here(ws, hid) == "Media framing is the topic"
    log = _log(ws, "check-setting")
    assert len(log) == 2 and log[1][0].startswith("A new reason for counting non-scientific documents")
    assert log[1][2] == "Media framing is the topic" and json.loads(log[1][1])["why_changed"] is True
    # an emptied reason while it is on: taken away, the usual one is given again, logged once (K3-3)
    out = nonscientific.set_counting(ws, hid, True, why="  ")
    assert out["changed"] and out["why_changed"] and out["was"] == out["now"] == "supported"
    assert nonscientific.why_here(ws, hid) is None and hypothesis_result(ws, hid)["count_nonscientific_why"] is None
    log = _log(ws, "check-setting")
    assert len(log) == 3 and log[2][0].startswith("The reason for counting non-scientific documents")
    assert f"the usual one shows again: {nonscientific.REASON}." in log[2][0] and log[2][2] is None
    assert "The answer stays Supported by your documents." in log[2][0]
    said = {s["rule"]: s["text"] for s in assessment.assess(ws, hid, hypothesis_result(ws, hid))["sentences"]}
    assert f"as set on this hypothesis: {nonscientific.REASON}." in said["non-scientific-counted"]
    assert nonscientific.set_counting(ws, hid, True, why="")["changed"] is False     # empty again: nothing new
    assert len(_log(ws, "check-setting")) == 3
    # the setting and its entry carry one time (one change for a sync merge) (K3-7)
    at = json.loads(ws.scalar("SELECT options_json FROM hypotheses WHERE hyp_id=?", (hid,)))[nonscientific.COUNT_AT]
    assert at in {r[0] for r in ws.query("SELECT at FROM research_log WHERE kind='check-setting'")}
    # off again brings the rule back
    back = nonscientific.set_counting(ws, hid, False)
    assert (back["was"], back["now"]) == ("supported", "unsupported")
    r = hypothesis_result(ws, hid)
    assert r["status"] == "unsupported" and not r["count_nonscientific"] and r["count_nonscientific_why"] is None
    assert len(_log(ws, "check-setting")) == 4


def test_the_setting_and_its_entry_are_one_change(project, monkeypatch):
    # K3-7: a failure while the entry is written leaves neither the setting nor an entry; the answers are filled in
    # the same entry once the change is made
    from enlens_claims import researchlog

    ws, news, _study, hid = project
    _first(ws, hid, news, "supports")
    docrole.set_nonscientific(ws, news, True)

    def broken(*a, **k):
        raise RuntimeError("killed")

    monkeypatch.setattr(researchlog, "record", broken)
    with pytest.raises(RuntimeError):
        nonscientific.set_counting(ws, hid, True)
    assert not nonscientific.counts_here(ws, hid) and _log(ws, "check-setting") == []
    assert hypothesis_result(ws, hid)["status"] == "unsupported"
    monkeypatch.undo()
    nonscientific.set_counting(ws, hid, True)
    log = _log(ws, "check-setting")
    assert len(log) == 1 and log[0][0].endswith(f"changed from {UNSUPPORTED_NONSCI} to Supported by your documents.")
    assert json.loads(log[0][1])["now"] == "supported"


def test_the_exception_without_non_scientific_documents_changes_nothing(project):
    ws, _news, study, hid = project
    _judge(ws, hid, {study: "supports"})
    out = nonscientific.set_counting(ws, hid, True)
    assert out["changed"] and out["was"] == out["now"] == "supported"
    assert "The answer stays Supported by your documents" in _log(ws, "check-setting")[0][0]
    assert f": {nonscientific.REASON}." in _log(ws, "check-setting")[0][0]   # no reason given: the stock one
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


def test_parts_that_differ_agree_in_the_checks_list(project):
    # K3-8: part 1 rests on the news article, part 2 on the study; the checks list, the map and the summary say what
    # the result page says, with the exception off and on
    ws, news, study, _hid = project
    hid = claimcheck.check_hypothesis(ws, "Electrolyser plants create local jobs and hire workers", BaselineBackend(),
                                      "baseline", k=8, per_doc=4, decompose=True,
                                      parts=[CLAIM, "Electrolyser plants hire workers"])
    want = [{news: "supports"}, {study: "partially_supports"}]
    for part, by_doc in zip(hypothesis_result(ws, hid)["parts"], want):
        for x in part["passages"]:
            judgements._set_judgement(ws, part["claim_id"], x["passage_id"], by_doc.get(x["doc_id"], "not_relevant"))
    docrole.set_nonscientific(ws, news, True)

    def everywhere():
        r = hypothesis_result(ws, hid)
        row = next(h for h in claimcheck.history(ws) if h["hyp_id"] == hid)
        m = next(x for x in evidence_map(ws)["hypotheses"] if x["hyp_id"] == hid)
        summary = next(x for x in summary_table(ws) if x["Hypothesis"] == r["text"])
        assert row["status"] == m["status"] == r["status"] and summary["Answer"] == r["status_text"]
        assert row["count_nonscientific"] == m["count_nonscientific"] == r["count_nonscientific"]
        return r["status"], [p["status"] for p in r["parts"]]

    assert everywhere() == ("partially_supported", ["unsupported", "partially_supported"])
    nonscientific.set_counting(ws, hid, True)
    assert everywhere() == ("partially_supported", ["supported", "partially_supported"])


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
    # behind no answer, as the Documents list counts it (N5): the non-scientific column is one of them
    assert m["nonscientific_shown"] == m["nonscientific_shown_in_project"] == 1
    assert m["documents_without_evidence"] == 1
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
    assert m["documents_without_evidence"] == 0 and m["nonscientific_shown"] == 0


def test_the_map_flags_a_counting_hypothesis_with_nothing_marked(project):
    # the flag agrees with the checks list (`history`) whatever is marked
    ws, _news, study, hid = project
    _judge(ws, hid, {study: "supports"})
    nonscientific.set_counting(ws, hid, True)
    assert not docrole.nonscientific_docs(ws)
    h = next(x for x in evidence_map(ws)["hypotheses"] if x["hyp_id"] == hid)
    assert h["count_nonscientific"] is True
    assert next(x for x in claimcheck.history(ws) if x["hyp_id"] == hid)["count_nonscientific"] is True


def test_the_answer_before_a_stronger_model_counts_them_with_the_exception(ws):  # noqa: F811
    # K3-8: the first reading is set aside as the answer is, so with the exception on it counts them too
    from test_stronger_model import HYP, Hedging, _step_up

    be = Hedging()
    hid = claimcheck.check_hypothesis(ws, HYP, be, "claude-sonnet", k=4, per_doc=2)
    res = hypothesis_result(ws, hid)
    assert res["status"] == "partially_supported"
    for doc in {x["doc_id"] for p in res["parts"] for x in p["passages"] if x["counted"]}:
        docrole.set_nonscientific(ws, doc, True)
    nonscientific.set_counting(ws, hid, True)
    assert hypothesis_result(ws, hid)["status"] == "partially_supported"
    _step_up(ws, hid, be)
    res = hypothesis_result(ws, hid)
    assert (res["status"], res["status_before_stronger"]) == ("supported", "partially_supported")
    row = next(x for x in claimcheck.history(ws) if x["hyp_id"] == hid)
    assert (row["status"], row["status_before_stronger"]) == ("supported", "partially_supported")
    assert summary_table(ws)[0]["Answer before a stronger model read it again"] == "Partly supported"
    nonscientific.set_counting(ws, hid, False)      # off: both readings set aside, nothing before to show
    res = hypothesis_result(ws, hid)
    assert res["status"] == "unsupported" and res["status_before_stronger"] is None


# ---- the .qdpx export (K3-5, K3-8) ----------------------------------------------------------------------------------
def test_the_qdpx_export_says_which_check_counts_them(project, tmp_path):
    import xml.etree.ElementTree as ET
    import zipfile

    from enlens_claims import qdpx

    ws, news, _study, hid = project
    _first(ws, hid, news, "supports")
    docrole.set_nonscientific(ws, news, True)
    q = "{%s}" % qdpx.NS

    def export():
        path = tmp_path / "p.qdpx"
        qdpx.export_project(ws, path)
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("project.qde"))
        hyp = next(c for c in root.iter(f"{q}Code") if c.get("guid") == qdpx.guid(ws.project_uid(), "hypothesis", hid))
        supports = next(c.get("guid") for c in hyp.findall(f"{q}Code") if c.get("name") == "Supports")
        src = next(s for s in root.iter(f"{q}TextSource") if s.get("name").startswith("Hydrogen boom"))
        coded = sum(1 for r in src.iter(f"{q}CodeRef") if r.get("targetGUID") == supports)
        return hyp.find(f"{q}Description").text, src.find(f"{q}Description").text, coded

    hyp_desc, src_desc, coded = export()          # off: as before the exception
    assert "Non-scientific documents count" not in hyp_desc and coded == 0
    assert "Non-scientific: read and judged, never counted in an answer." in src_desc.split("\n")
    nonscientific.set_counting(ws, hid, True, why="Press coverage is the topic.")
    hyp_desc, src_desc, coded = export()
    assert hyp_desc.endswith("Non-scientific documents count in this check, as set on this hypothesis: Press coverage "
                             "is the topic.")
    assert "Non-scientific: read and judged, never counted in an answer, except in checks set to count them." in \
        src_desc.split("\n")
    assert coded == 1                              # its excerpt sits on Supports, and the descriptions say why
    nonscientific.set_counting(ws, hid, True, why="")
    assert export()[0].endswith(f"as set on this hypothesis: {nonscientific.REASON}.")


def test_the_log_says_a_check_may_count_them(project):
    # K3-5: the entry for a mark says the exception; entries written before are left as they are
    ws, news, _study, _hid = project
    docrole.set_nonscientific(ws, news, True)
    text = _log(ws, "document-mark")[0][0]
    assert "no judgement of them counts in an answer from now on, except in checks set to count them." in text


# ---- the connector (MCP) ------------------------------------------------------------------------------------------
def test_the_connector_marks_what_the_exception_counts(project):
    from enlens_claims import mcp_server

    ws, news, _study, hid = project
    _first(ws, hid, news, "supports")
    docrole.set_nonscientific(ws, news, True)
    nonscientific.set_counting(ws, hid, True)
    cid = hypothesis_result(ws, hid)["parts"][0]["claim_id"]
    out = mcp_server._summary(ws, cid)
    assert out["status"] == "supported" and out["status_without_non_scientific"] == "unsupported"
    assert out["non_scientific_counted_here"] is True and "counted_by_exception" in out["non_scientific_note"]
    marked = [e for e in out["evidence"] if e.get("counted_by_exception")]
    assert marked and all(e["non_scientific"] and e["counted"] for e in marked)
    assert "status_counting_non_scientific" not in out          # nothing set aside here


# ---- the document's page -------------------------------------------------------------------------------------------
def test_the_documents_page_says_which_checks_count_it(project):
    ws, news, _study, hid = project
    other = claimcheck.check_hypothesis(ws, "The hydrogen plant brings jobs to the coast", BaselineBackend(),
                                        "baseline", k=8, per_doc=4)
    docrole.set_nonscientific(ws, news, True)
    nonscientific.set_counting(ws, hid, True)
    got = {a["hyp_id"]: a["count_nonscientific"] for a in docrole.counted_without(ws, news)}
    assert got[hid] is True and got.get(other, False) is False


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
    with pytest.raises(nonscientific.NoSuggestion):                     # nothing to answer now: nothing logged
        nonscientific.decline(ws, news)
    with pytest.raises(nonscientific.NoSuggestion):                     # a journal article is never declined
        nonscientific.decline(ws, study)
    assert len(_log(ws, "document-suggestion")) == 1
    # Suggest again: the No is taken back by a log entry that names it; the suggestion is back
    assert nonscientific.answered_no(ws, news) == {"by": ["you"], "may_suggest_again": True}
    back = nonscientific.suggest_again(ws, news)
    assert back["suggestion"]["words"] == "a newspaper article" and nonscientific.declined(ws) == set()
    log = _log(ws, "document-suggestion")
    assert len(log) == 2 and json.loads(log[1][1])["supersedes"] and nonscientific.answered_no(ws, news) is None
    with pytest.raises(nonscientific.NoSuggestion):                     # nothing left to take back
        nonscientific.suggest_again(ws, news)
    # a theory document is never suggested
    docrole.set_role(ws, news, "theory")
    assert news not in nonscientific.suggestions(ws)
    docrole.set_role(ws, news, None)
    assert news in nonscientific.suggestions(ws)
    # a working document is never suggested
    _bib(ws, study, "blogPost", key="zotero:user:IJKL9012")
    with ws.connect() as cx:
        cx.execute("DELETE FROM bib_links WHERE item_key='zotero:user:EFGH5678'")
    assert study in nonscientific.suggestions(ws)
    docrole.set_role(ws, study, "working")
    assert study not in nonscientific.suggestions(ws)


def test_a_document_with_two_works_is_suggested_from_the_first(project):
    # K3-2: the suggestion takes the first linked work, as the Documents list shows the document (doc_citations)
    from enlens_claims import bibliography

    ws, news, study, _hid = project

    def work(doc, key, item_type, seq):
        with ws.connect() as cx:
            cx.execute("INSERT INTO bib_items(item_key, item_type, title, creators_json, seq) VALUES (?,?,?,?,?)",
                       (key, item_type, f"A {item_type}", "[]", seq))
            cx.execute("INSERT INTO bib_links(item_key, doc_id, status, method) VALUES (?,?,?,?)",
                       (key, doc, "auto", "doi"))

    work(study, "k:article", "journalArticle", 1)      # the paper, then its landing page
    work(study, "k:landing", "webpage", 2)
    work(news, "k:web", "webpage", 3)                  # the article's web page, then a journal entry
    work(news, "k:journal", "journalArticle", 4)
    cites = bibliography.doc_citations(ws)
    assert cites[study]["type"] == "Journal article" and cites[news]["type"] == "Web page"
    assert nonscientific.suggestion(ws, study) is None
    assert nonscientific.suggestions(ws) == {news: {"item_type": "webpage", "words": "a web page"}}
    with pytest.raises(nonscientific.NoSuggestion):    # nor can a No be said to it
        nonscientific.decline(ws, study)


def test_the_item_types_in_words():
    assert nonscientific.type_words("PRESS") == "a press release"          # RIS (K3-4)
    assert nonscientific.type_words("ICOMM") == "an online message"
    assert nonscientific.type_words("electronic") == nonscientific.type_words("Electronic") == "a web page"   # BibLaTeX
    assert nonscientific.type_words("magazineArticle") == "a magazine article"
    assert nonscientific.type_words("article-newspaper") == "a newspaper article"
    assert nonscientific.type_words("post-weblog") == "a blog post"
    assert nonscientific.type_words("NEWS") == "a newspaper article"
    assert nonscientific.type_words("Online") == "a web page"
    for t in ("journalArticle", "article-journal", "book", "report", "JOUR", "thesis", None, "",
              "presentation", "speech", "videoRecording", "VIDEO"):   # a talk or a video can be a scholar's
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
    assert api("GET", "/api/projects/News/nonscientific-suggestions")[1] == {"suggested": {news: "a web page"}}
    st, body = api("GET", f"/api/projects/News/documents/{news}/nonscientific-suggestion")
    assert st == 200 and body["suggestion"]["words"] == "a web page"
    assert api("POST", f"/api/projects/News/documents/{news}/nonscientific-suggestion", {"answer": "yes"})[0] == 400
    assert api("POST", "/api/projects/News/documents/nope/nonscientific-suggestion", {"answer": "no"})[0] == 404
    assert api("GET", "/api/projects/News/documents/nope/nonscientific-suggestion")[0] == 404
    st, body = api("POST", f"/api/projects/News/documents/{news}/nonscientific-suggestion", {"answer": "no"})
    assert st == 200 and body["declined"]
    assert api("GET", f"/api/projects/News/documents/{news}/nonscientific-suggestion")[1]["suggestion"] is None
    assert api("GET", "/api/projects/News/nonscientific-suggestions")[1] == {"suggested": {}}
    # a No again, from a stale list: 409, nothing logged
    st, body = api("POST", f"/api/projects/News/documents/{news}/nonscientific-suggestion", {"answer": "no"})
    assert st == 409 and "no suggestion to answer now" in body["error"]
    st, body = api("GET", f"/api/projects/News/documents/{news}/nonscientific-suggestion")
    assert body["answered_no"] == {"by": ["you"], "may_suggest_again": True}
    st, body = api("POST", f"/api/projects/News/documents/{news}/nonscientific-suggestion", {"answer": "again"})
    assert st == 200 and body["suggestion"]["words"] == "a web page"
    assert api("POST", f"/api/projects/News/documents/{news}/nonscientific-suggestion", {"answer": "again"})[0] == 409
    # No on a document marked already: 409
    assert api("PUT", f"/api/projects/News/documents/{news}/nonscientific", {"nonscientific": True})[0] == 200
    st, body = api("POST", f"/api/projects/News/documents/{news}/nonscientific-suggestion", {"answer": "no"})
    assert st == 409
    assert api("POST", f"/api/projects/News/documents/{news}/nonscientific-suggestion",
               {"answer": "no", "why": ["x"]})[0] == 400
    st, body = api("PUT", f"/api/projects/News/hypotheses/{hid}/nonscientific", {"count": True, "why": "Media study"})
    assert st == 200 and body["changed"] and body["count_nonscientific"]
    assert api("GET", f"/api/projects/News/hypotheses/{hid}")[1]["count_nonscientific"] is True
    assert api("PUT", f"/api/projects/News/hypotheses/{hid}/nonscientific", {"count": "yes"})[0] == 400
    assert api("PUT", f"/api/projects/News/hypotheses/{hid}/nonscientific", {"count": True, "why": 3})[0] == 400
    st, body = api("PUT", f"/api/projects/News/hypotheses/{hid}/nonscientific", {"count": True, "why": "Press study"})
    assert st == 200 and body["why_changed"]
    st, body = api("PUT", f"/api/projects/News/hypotheses/{hid}/nonscientific", {"count": True, "why": ""})
    assert st == 200 and body["why_changed"]            # emptied: the usual reason again (K3-3)
    assert api("GET", f"/api/projects/News/hypotheses/{hid}")[1]["count_nonscientific_why"] is None
    assert api("PUT", "/api/projects/News/hypotheses/nope/nonscientific", {"count": True})[0] == 404


# ---- between copies -------------------------------------------------------------------------------------------------
def test_the_exception_and_a_no_travel_with_the_project(anna_and_ben):  # noqa: F811
    anna, ben = anna_and_ben
    with anna:
        doc = anna.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        nonscientific.set_counting(anna.ws, anna.hid, True, why="Reports are the material")
        _bib(anna.ws, doc, "webpage")
        nonscientific.decline(anna.ws, doc)        # the Owner's No: it counts in every copy
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["updated"] == 1
    with ben:
        assert nonscientific.counts_here(ben.ws, anna.hid)
        assert nonscientific.why_here(ben.ws, anna.hid) == "Reports are the material"
        r = hypothesis_result(ben.ws, anna.hid)
        assert r["count_nonscientific"] and r["count_nonscientific_author"] == "Anna"   # the line under the switch
        assert doc in nonscientific.declined(ben.ws)
    with anna:
        assert hypothesis_result(anna.ws, anna.hid)["count_nonscientific_author"] is None   # her own
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


def test_a_mark_the_project_took_says_a_check_may_count_it(anna_and_ben, tmp_path):  # noqa: F811
    # K3-5: the entry written when the Owner's mark reaches a copy says the exception too
    from enlens_claims.sync import folder
    from owner_helpers import add_doc, sync, view

    shared = tmp_path / "shared"
    shared.mkdir()
    anna, ben = anna_and_ben
    for p in (anna, ben):
        with p:
            folder.set_folder(p.ws, str(shared))
    sync(anna, ben)
    paper = add_doc(anna, tmp_path, "news", text=NEWS)
    sync(anna, ben)
    with anna:
        docrole.set_nonscientific(anna.ws, paper, True)
    view(anna)
    sync(anna, ben, rounds=2)
    with ben:
        assert docrole.is_nonscientific(ben.ws, paper)
        took = [t for t, *_ in _log(ben.ws, "document-mark") if t.startswith("Marked as non-scientific by Anna")]
        assert took and took[-1].endswith("counts in an answer from now on, except in checks set to count them.")
        # DEC-1: the round's "what came in" says it too (the mark is applied when the round writes)
        from enlens_claims import sync as sync_

        said = [x for h in sync_.history(ben.ws, 10) for x in h["lines"] if x.startswith("Anna marked “")]
        assert len(said) == 1 and said[0].endswith("It changes no answer here.")


def test_a_members_no_stays_in_their_copy_and_the_owners_counts_everywhere(anna_and_ben):  # noqa: F811
    from enlens_claims import ownership

    anna, ben = anna_and_ben                  # Anna made the project: its Owner since her first file; Ben a Member
    with anna:
        doc = anna.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
    with anna:
        assert ownership.role_of(anna.ws._conn()) == "owner"
    with ben:
        assert ownership.role_of(ben.ws._conn()) == "member"
    for p in (anna, ben):
        with p:
            _bib(p.ws, doc, "blogPost")
            assert doc in nonscientific.suggestions(p.ws)
    # Ben, a Member, says No: hidden in his copy only
    with ben:
        nonscientific.decline(ben.ws, doc)
        assert doc in nonscientific.declined(ben.ws)
    anna.bring_in(ben.send())
    with anna:
        assert len(_log(anna.ws, "document-suggestion")) == 1             # his No came in, as a log entry
        assert doc not in nonscientific.declined(anna.ws) and doc in nonscientific.suggestions(anna.ws)
        assert nonscientific.answered_no(anna.ws, doc) is None
        # Anna, the Owner, says No: it counts in every copy
        nonscientific.decline(anna.ws, doc)
    ben.bring_in(anna.send())
    with ben:
        assert doc not in nonscientific.suggestions(ben.ws)
        # he may take back his own No, not Anna's: Suggest again is not offered to him
        said = nonscientific.answered_no(ben.ws, doc)
        assert sorted(said["by"]) == ["Anna", "you"] and said["may_suggest_again"] is False
    with anna:
        # the Owner takes back anyone's: both Nos are superseded
        assert nonscientific.answered_no(anna.ws, doc) == {"by": ["you"], "may_suggest_again": True}
        nonscientific.suggest_again(anna.ws, doc)
        assert doc in nonscientific.suggestions(anna.ws)
    ben.bring_in(anna.send())
    with ben:
        assert doc in nonscientific.suggestions(ben.ws) and nonscientific.answered_no(ben.ws, doc) is None


from test_shared_projects import anna_and_ben  # noqa: E402,F401  (fixture)
from test_app import api, home  # noqa: E402,F401  (fixtures)
from test_stronger_model import ws  # noqa: E402,F401  (fixture: a project over the corpus, cloud AI allowed)


# ---- the views (static: the repo tests its views by their words) ---------------------------------------------------
def test_the_views_say_it():
    from pathlib import Path

    views = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static" / "views"
    result = (views / "result.js").read_text(encoding="utf-8")
    assert "Count non-scientific documents in this check" in result and "/nonscientific`, { count: on }" in result
    # K3-3: the reason, under the switch while it is on, made with field() and input(); saved, never opened by itself
    assert 'field("Why they count here (optional)", why' in result and "Save reason" in result
    assert "/nonscientific`, { count: true, why: now }" in result
    assert "if (r.count_nonscientific) sw.appendChild(nonsciReason(r));" in result
    assert "Non-scientific, counted here" in result
    role = (views / "doc-role.js").read_text(encoding="utf-8")
    assert "Your bibliography lists this as ${words}. Mark it as non-scientific? " in role
    assert '{ answer: "no" }' in role
    assert "Suggest again" in role and '{ answer: "again" }' in role
    assert "counted in this check (set on the hypothesis)" in role
    assert "except in checks set to count non-scientific documents" in role
    assert "r.count_nonscientific_author" in result and "as a sync-clash copy" in result
    m = (views / "map.js").read_text(encoding="utf-8")
    assert "Non-scientific: read, not counted" in m and "m-nonsci" in m
    assert "a column per document that counts or is non-scientific" in m and "nonscientific_shown_in_project" in m
    src = (views / "sources.js").read_text(encoding="utf-8")
    assert "Suggested as non-scientific" in src and "except in checks set to count non-scientific documents" in src


# ---- the audit's DEC-1: a colleague's change of what counts is said in what came in ---------------------------------
@pytest.fixture
def owner_and_member(project, tmp_path, monkeypatch):
    """The small project (a study, a news article, one check) as Anna's, its Owner from her first file; Ben's copy, a
    Member's, imported from that file. (ws, news id, anna, ben)"""
    from enlens_claims import bundle
    from test_shared_projects import Person

    ws, news, _study, _hid = project
    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    anna.ws = ws
    first = anna.send()
    with ben:
        ben.ws = bundle.import_project(first, tmp_path / "ben-project")
    yield ws, news, anna, ben
    ben.ws.close_all()


def _said(rep: dict, words: str) -> list[str]:
    return [x for x in rep["lines"] if words in x]


def test_a_members_exception_is_said_to_the_owner_with_both_answers(owner_and_member):
    from enlens_claims import ownership, sync

    _ws, news, anna, ben = owner_and_member
    with anna:
        docrole.set_nonscientific(anna.ws, news, True)        # the Owner's mark: it holds in every copy
    ben.bring_in(anna.send())
    with ben:
        assert ownership.role_of(ben.ws._conn()) == "member" and docrole.is_nonscientific(ben.ws, news)
        jobs = claimcheck.check_hypothesis(ben.ws, "The hydrogen plant brings jobs to the coast", BaselineBackend(),
                                           "baseline", k=8, per_doc=4)
        _first(ben.ws, jobs, news, "supports")               # only the news article speaks to it
        quiet = claimcheck.check_hypothesis(ben.ws, "Electrolysers lower the price of fertiliser", BaselineBackend(),
                                            "baseline", k=4)
        _judge(ben.ws, quiet, {})                            # nothing speaks to it, counted or not
    rep = anna.bring_in(ben.send())
    assert rep["checks"]["new"] == 2 and not _said(rep, "non-scientific")   # new checks: nothing changed here
    with ben:
        nonscientific.set_counting(ben.ws, jobs, True, why="The press coverage is what the study is about.")
        nonscientific.set_counting(ben.ws, quiet, True)
    rep = anna.bring_in(ben.send())
    on = ("Ben set the check “The hydrogen plant brings jobs to the coast” to count the non-scientific documents (the "
          "reason given: “The press coverage is what the study is about”). Its answer here is now Supported by your "
          f"documents; without them it would be {UNSUPPORTED_NONSCI}.")
    same = ("Ben set the check “Electrolysers lower the price of fertiliser” to count the non-scientific documents. "
            "This does not change the answer here: No evidence found either way.")
    assert sorted(rep["lines"][:2]) == sorted([on, same])     # first, before the routine lines
    assert rep["lines"][2].startswith("From Ben: ")
    with anna:
        assert hypothesis_result(anna.ws, jobs)["status"] == "supported"
        assert sync.history(anna.ws, 1)[0]["lines"][:2] == rep["lines"][:2]   # kept as the Team tab reads it
    # the same file again, and Anna's file back in Ben's copy (his own change): no line
    rep = anna.bring_in(ben.files / f"Ben-{ben.n}.zip")
    assert not _said(rep, "non-scientific")
    rep = ben.bring_in(anna.send())
    assert not _said(rep, "non-scientific")
    # turned off again: the opposite line
    with ben:
        nonscientific.set_counting(ben.ws, jobs, False)
    rep = anna.bring_in(ben.send())
    assert rep["lines"][0] == ("Ben set the check “The hydrogen plant brings jobs to the coast” to no longer count the "
                               f"non-scientific documents. Its answer here is now {UNSUPPORTED_NONSCI}; counting them "
                               "it would be Supported by your documents.")
    assert len(_said(rep, "non-scientific")) == 1


def test_a_check_beside_yours_says_its_own_answer(owner_and_member):
    _ws, news, anna, ben = owner_and_member
    with anna:
        docrole.set_nonscientific(anna.ws, news, True)
        hid = claimcheck.check_hypothesis(anna.ws, "The hydrogen plant brings jobs to the coast", BaselineBackend(),
                                          "baseline", k=8, per_doc=4)
        _first(anna.ws, hid, news, "supports")
    ben.bring_in(anna.send())
    with ben:                                                # Anna's check: Ben's change comes in beside it (H5)
        _first(ben.ws, hid, news, "supports")                # his judgements go with his version
        nonscientific.set_counting(ben.ws, hid, True)
    rep = anna.bring_in(ben.send())
    assert len(rep["checks"]["clash"]) == 1
    assert rep["lines"][0] == (
        "Ben set the check “The hydrogen plant brings jobs to the coast” to count the non-scientific documents. You "
        "both changed the check, so Ben's version came in beside yours, marked “sync clash”, and yours stays as "
        "it was. That version's answer here is now Supported by your documents; without them it would be "
        f"{UNSUPPORTED_NONSCI}.")
    with anna:
        assert not nonscientific.counts_here(anna.ws, hid)


def test_a_document_mark_that_came_in_applied_says_the_answers_it_changed(owner_and_member):
    _ws, news, anna, ben = owner_and_member
    with ben:
        hid = ben.ws.scalar("SELECT hyp_id FROM hypotheses")
        text = ben.ws.scalar("SELECT text FROM hypotheses")
        _first(ben.ws, hid, news, "supports")
        assert hypothesis_result(ben.ws, hid)["status"] == "supported"
    with anna:
        docrole.set_nonscientific(anna.ws, news, True)        # the Owner's mark applies in Ben's copy at once
    f = anna.send()
    rep = ben.bring_in(f)
    title = "Hydrogen boom brings jobs to the coast"
    assert rep["lines"][0] == (f"Anna marked “{title}” as non-scientific: no judgement of it counts in an answer here "
                               "now, except in checks set to count them. It changed the answer of 1 check here: "
                               f"“{text}” (now {UNSUPPORTED_NONSCI}).")
    with ben:
        assert docrole.is_nonscientific(ben.ws, news)
        from enlens_claims import sync

        kept = sync.history(ben.ws, 1)[0]
        assert kept["lines"][0] == rep["lines"][0]
        row = json.loads(ben.ws.scalar("SELECT report_json FROM sync_log ORDER BY log_id DESC LIMIT 1"))
        assert "marks_due" not in row["documents"] and row["documents"]["marks"][0]["changed"][0]["hyp_id"] == hid
    assert not _said(ben.bring_in(f), "non-scientific")      # the same file again: no line
    with anna:
        docrole.set_nonscientific(anna.ws, news, False)
    rep = ben.bring_in(anna.send())
    assert rep["lines"][0] == (f"Anna counted “{title}” as scientific again: its judgements count in answers here now. "
                               f"It changed the answer of 1 check here: “{text}” (now Supported by your documents).")
