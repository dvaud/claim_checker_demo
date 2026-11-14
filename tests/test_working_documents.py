"""0.19.0 (roadmap N3): a working document is the researcher's own draft or notes, kept in the project, never a source.

It is the third value of a document's role (docrole.py), beside evidence and theory. It is read, searched, opened,
noted and labelled with codebooks (its codes are its own: a row of the profile's grid, never in the corpus's code
counts), and a sentence of it can be checked against the corpus; it is left out of themes, the excerpts a check reads,
key terms and the glossary's counts, as a theory document is."""
from __future__ import annotations

import pytest

from enlens_claims import docrole, ingest, profile, search, terms, themes, theorycodes
from enlens_claims.store import Workspace
from owner_helpers import TEXTS

DRAFT = ("My chapter draft on hydrogen jobs\n\n"
         "I argue that electrolyser plants create local jobs for workers in the region, and that the jobs last "
         "beyond the construction phase. Desalination for the electrolysers needs water and workers too.\n\n"
         "The grid connection of the plants shapes where the jobs go, and local workers gain most.\n")


@pytest.fixture
def project(tmp_path) -> tuple[Workspace, str, list[str]]:
    """Three evidence documents and the researcher's draft (not marked yet): (ws, the draft's id, the evidence's ids)."""
    ws = Workspace.create(tmp_path / "proj")
    d = tmp_path / "docs"
    d.mkdir()
    for key in ("desalination", "jobs", "grid"):
        (d / f"{key}.txt").write_text(TEXTS[key], encoding="utf-8")
    (d / "draft.txt").write_text(DRAFT, encoding="utf-8")
    ingest.ingest(ws, [d])
    ids = {r[1]: r[0] for r in ws.query("SELECT doc_id, title FROM documents")}
    draft = next(i for t, i in ids.items() if t.startswith("My chapter"))
    yield ws, draft, sorted(i for i in ids.values() if i != draft)
    ws.close_all()


def test_marking_a_working_document_is_one_role_of_three(project):
    ws, draft, ev = project
    out = docrole.set_role(ws, draft, "working", why="my own chapter")
    assert out["changed"] and docrole.role_of(ws, draft) == "working"
    assert docrole.working_docs(ws._conn()) == {draft} and not docrole.theory_docs(ws._conn())
    assert docrole.not_evidence_docs(ws._conn()) == {draft}
    log = ws.query("SELECT text, why FROM research_log WHERE subject_id=? AND kind='document-role'", (draft,))
    assert [r[1] for r in log] == ["my own chapter"] and "working document" in log[0][0]
    # one role at a time: theory replaces it, and both are never a source
    docrole.set_role(ws, draft, "theory")
    assert docrole.role_of(ws, draft) == "theory" and not docrole.working_docs(ws._conn())
    assert ws.scalar("SELECT COUNT(*) FROM block_choices WHERE doc_id=? AND fp LIKE 'role:%'", (draft,)) == 1
    docrole.set_role(ws, ev[0], "working")
    assert docrole.not_evidence_docs(ws._conn()) == {draft, ev[0]}
    docrole.set_role(ws, draft, None)
    assert docrole.not_evidence_docs(ws._conn()) == {ev[0]}


def test_a_working_document_is_left_out_of_themes_and_key_terms(project):
    ws, draft, ev = project
    docrole.set_role(ws, draft, "working")
    got, _ = themes._passages(ws)
    assert {p["doc_id"] for p in got} == set(ev)
    assert set(terms._body_docs(ws)) == set(ev)


def test_a_check_never_reads_a_working_document_but_search_finds_it(project):
    ws, draft, ev = project
    claim = "Electrolyser plants create local jobs"
    words = ["jobs", "workers", "electrolyser"]
    assert draft in {p["doc_id"] for p in search.rank_passages(ws, claim, words, k=12, per_doc=4)}   # (unmarked)
    docrole.set_role(ws, draft, "working")
    found = search.rank_passages(ws, claim, words, k=12, per_doc=4)
    assert found and draft not in {p["doc_id"] for p in found}
    assert draft not in search.docs_matching(ws, claim, words, {draft, *ev})
    # named by hand, it is read (as a theory document is)
    only = search.rank_passages(ws, claim, words, k=4, per_doc=4, doc_ids=[draft])
    assert {p["doc_id"] for p in only} == {draft}
    # the Search page still finds it
    assert draft in {p["doc_id"] for p in search.rank_passages(ws, claim, words, k=12, per_doc=4,
                                                                 evidence_only=False)}


def test_a_working_document_is_labelled_but_its_codes_are_never_the_corpus(project):
    ws, draft, ev = project
    profile.keyword_pass(ws, "sdg")
    whole = profile.grid(ws, "sdg")
    stats_whole = profile.stats(ws, "sdg")
    assert draft in {d["doc_id"] for d in whole["documents"]}, "the draft needs a keyword code for this test"
    docrole.set_role(ws, draft, "working")
    profile.keyword_pass(ws, "sdg")                    # labelled again, with the role
    assert ws.scalar("SELECT COUNT(*) FROM labels WHERE doc_id=?", (draft,)) > 0
    plan = profile.label_plan(ws, "sdg", all_passages=True)
    assert plan["passages"] == ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'")   # all, the draft too
    g = profile.grid(ws, "sdg")
    rows = g["documents"]
    assert rows[-1]["doc_id"] == draft and rows[-1]["working"] is True              # its own row, last
    assert not any(r.get("working") for r in rows[:-1])
    corpus = [r["doc_id"] for r in rows[:-1]]
    for c in g["codes"]:                                # the totals are the corpus's alone
        assert c["passages"] == sum(g["cells"].get(d, {}).get(c["code"], 0) for d in corpus)
        assert c["documents"] == sum(1 for d in corpus if g["cells"].get(d, {}).get(c["code"]))
    st = profile.stats(ws, "sdg")
    assert st["documents"] == stats_whole["documents"] - 1 and st["labels"] < stats_whole["labels"]
    sheet = profile.grid_table(g)                       # the spreadsheet says which row is the draft (review)
    assert sheet[-1]["Document"].endswith("(your working document, not in the totals)")
    assert not any("working document" in r["Document"] for r in sheet[:-1])
    # its own page shows its codes
    assert profile.doc_profile(ws, "sdg", draft)["codes"]


def test_a_codes_examples_never_come_from_a_working_document(project):
    ws, draft, ev = project
    docrole.set_role(ws, draft, "working")
    kept = theorycodes.keep_evidence_examples(ws, [{"code": "jobs", "examples": [
        {"quote": "mine", "doc_id": draft}, {"quote": "theirs", "doc_id": ev[0]}]}])
    assert [e["doc_id"] for e in kept[0]["examples"]] == [ev[0]]
    assert all(e["doc_id"] != draft for e in theorycodes.suggest_examples(ws, "jobs"))


def test_a_codes_examples_never_quote_the_document_it_is_made_from(project):
    ws, draft, ev = project                              # (review: `exclude_doc` was dropped once)
    assert all(e["doc_id"] != ev[1] for e in theorycodes.suggest_examples(ws, "jobs", exclude_doc=ev[1]))


def test_the_proposal_and_the_log_say_working_document():
    from enlens_claims import ownership

    assert ownership.what({"kind": "blocks", "title": "Draft", "detail": {"role": "working"}}) == \
        "marking “Draft” as a working document (never a source)"
    # theory to working (and back) is a role set and one taken away: the role set wins, in either order (review)
    for delta in ({"role:working": [1, "role"], "role:theory": None}, {"role:theory": None, "role:working": [1, "role"]}):
        assert ownership._delta_words(delta)["role"] == "working"
    assert ownership._delta_words({"role:theory": None})["role"] == "evidence"
    # a document has one role: a proposal accepted over another role replaces it (review)
    got = ownership._apply_delta({"role:theory": [1, "role"], "x": [0, None]}, {"role:working": [1, "role"]})
    assert got == {"role:working": [1, "role"], "x": [0, None]}


def test_a_check_started_from_a_document_is_listed_on_it(project):
    """0.19.0 (N3's leftover): a check started from a working document's text remembers the document (`origin`
    "document"), so the document's page lists it with its answer, and the check's result names the document."""
    from enlens_claims import claimcheck
    from enlens_claims.check_results import hypothesis_result

    ws, draft, ev = project
    docrole.set_role(ws, draft, "working")
    assert docrole.checks_started_from(ws, draft) == []
    first = claimcheck.create_hypothesis(ws, "Electrolyser plants create local jobs in the region.",
                                         origin=docrole.ORIGIN, origin_id=draft)
    other = claimcheck.create_hypothesis(ws, "Desalination plants need workers for the electrolysers.")
    second = claimcheck.create_hypothesis(ws, "Local workers gain most from the grid connection.",
                                          origin=docrole.ORIGIN, origin_id=draft)
    for hid in (first, other, second):  # each with its part, as a check makes them (one without is left out)
        claimcheck.new_claim(ws, ws.scalar("SELECT text FROM hypotheses WHERE hyp_id=?", (hid,)), hyp_id=hid)
    got = docrole.checks_started_from(ws, draft)
    assert [g["hyp_id"] for g in got] == [second, first]
    assert all(g["text"] and g["status"] and g["status_text"] for g in got)
    assert docrole.checks_started_from(ws, ev[0]) == []
    r = hypothesis_result(ws, first)
    assert (r["origin"], r["origin_id"], r["origin_title"]) == ("document", draft, "My chapter draft on hydrogen jobs")
    assert "origin_title" not in hypothesis_result(ws, other)
    # its role changed back to evidence: the checks started from it stay listed
    docrole.set_role(ws, draft, None)
    assert {g["hyp_id"] for g in docrole.checks_started_from(ws, draft)} == {first, second}


def test_the_list_on_a_document_gives_each_check_with_its_answer(project):
    """N3C-2, N3C-3: a judged check with its answer; a check by queue that waits for its parts is listed, one
    interrupted before it had parts is not (the checks list leaves it out too); newest first, by the order of making
    when two share a time; the file's name when the document has no title (a Windows path too); no link once the
    document is removed."""
    from enlens_claims import claimcheck
    from enlens_claims.check_results import hypothesis_result
    from enlens_claims.llm import BaselineBackend
    from enlens_claims.verdicts import STATUS_TEXT

    ws, draft, ev = project
    docrole.set_role(ws, draft, "working")
    judged = claimcheck.check_hypothesis(ws, "Electrolyser plants create local jobs in the region.", BaselineBackend(),
                                         "baseline", k=3, origin=docrole.ORIGIN, origin_id=draft)
    waiting = claimcheck.queue_check(ws, "Local workers gain most from the grid connection.", None, decompose=True,
                                     origin=docrole.ORIGIN, origin_id=draft)
    interrupted = claimcheck.create_hypothesis(ws, "Desalination plants need workers for the electrolysers.",
                                               origin=docrole.ORIGIN, origin_id=draft)
    with ws.connect() as cx:  # made in the same second: the order of making decides
        cx.execute("UPDATE hypotheses SET created_at='2026-11-14T10:00:00'")
    got = docrole.checks_started_from(ws, draft)
    assert [g["hyp_id"] for g in got] == [waiting, judged] and interrupted not in {g["hyp_id"] for g in got}
    assert (got[0]["status"], got[0]["status_text"]) == ("waiting", STATUS_TEXT["waiting"])
    answer = hypothesis_result(ws, judged)["status"]
    assert got[1]["status"] == answer and answer not in ("waiting", "running")
    assert got[1]["status_text"] == STATUS_TEXT[answer]
    # the file's name when the document has no title, from a path written on Windows too (N3C-4)
    with ws.connect() as cx:
        cx.execute("UPDATE documents SET title=NULL, path=? WHERE doc_id=?",
                   ("C:\\Users\\Dávid\\Documents\\draft chapter.docx", draft))
    assert hypothesis_result(ws, judged)["origin_title"] == "draft chapter.docx"
    with ws.connect() as cx:
        cx.execute("UPDATE documents SET path=? WHERE doc_id=?", ("/home/abel/drafts/draft chapter.txt", draft))
    assert hypothesis_result(ws, judged)["origin_title"] == "draft chapter.txt"
    ws.remove_document(draft)
    r = hypothesis_result(ws, judged)
    assert r["origin"] == "document" and "origin_title" not in r   # no link to a page that is gone


# ---- N3C-1: the words keep the AI setting of the document they come from -----------------------------------------
@pytest.fixture
def drafts(tmp_path, monkeypatch):
    """The mixed corpus (helpers_mixed_corpus) with the documents marked Only a local AI and No AI as working
    documents: the drafts the words come from. The open report is the one source."""
    from helpers_mixed_corpus import mixed_project

    from enlens_claims import home

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Drafts")
    ids = mixed_project(ws, tmp_path / "corpus")
    for k in ("local", "none"):
        docrole.set_role(ws, ids[k], "working")
    yield ws, ids
    ws.close_all()


def _words(mark: str) -> str:
    return f"Green hydrogen production can increase water stress in arid regions {mark}."


def _excerpts(res: dict) -> list[dict]:
    return [p for part in res["parts"] for p in part["passages"]]


def test_words_from_a_draft_marked_only_a_local_ai_are_read_on_this_computer(drafts, monkeypatch):
    from helpers_mixed_corpus import LOCAL_MARK, Cloud, Local, use_local_model

    from enlens_claims import access, claimcheck, judgements
    from enlens_claims.check_results import hypothesis_result

    ws, ids = drafts
    cloud, local = Cloud(), Local()
    use_local_model(monkeypatch, local)
    hid = claimcheck.check_hypothesis(ws, _words(LOCAL_MARK), cloud, "claude-opus", k=6, per_doc=3, decompose=True,
                                      expand=True, origin=docrole.ORIGIN, origin_id=ids["local"])
    assert cloud.sent == []  # Claude was sent nothing: not the words, not the excerpts they were checked against
    assert {"decompose", "expand", "check"} <= set(local.kinds) and LOCAL_MARK.lower() in local.text()
    res = hypothesis_result(ws, hid)
    assert res["words_access"] == "local"
    ex = _excerpts(res)
    assert ex and {p["doc_id"] for p in ex} == {ids["cloud"]} and {p["read_by"] for p in ex} == {"local"}
    # every task holding the words says so, so the queue for Claude Code never hands one out
    assert {r[0] for r in ws.query("SELECT access FROM tasks")} == {"local"}
    # read again: by the local model too
    part = res["parts"][0]
    judgements.reread_excerpt(ws, part["claim_id"], part["passages"][0]["passage_id"], cloud, "claude-opus")
    assert cloud.sent == [] and local.kinds[-1] == "reread"
    # a second opinion from Claude: not given on them
    out = claimcheck.second_opinion(ws, [hid], cloud, "claude-sonnet", "claude-opus")
    assert out["rounds"] == 0 and out["restricted"] == len(ex) and cloud.sent == []
    # the document marked Claude may read it since: the words may go to Claude from now on
    access.set_documents(ws, [ids["local"]], "cloud")
    with ws.connect() as cx:
        assert access.label_payload(cx, {"subject_kind": "user_claim", "subject_id": part["claim_id"]}) == "cloud"
    assert "words_access" not in hypothesis_result(ws, hid)


def test_words_from_a_draft_marked_no_ai_are_read_by_no_model(drafts, monkeypatch):
    from helpers_mixed_corpus import NONE_MARK, Cloud, Local, use_local_model

    from enlens_claims import claimcheck, judgements
    from enlens_claims.check_results import hypothesis_result

    ws, ids = drafts
    cloud, local = Cloud(), Local()
    use_local_model(monkeypatch, local)
    steps = []
    hid = claimcheck.check_hypothesis(ws, _words(NONE_MARK), cloud, "claude-opus", k=6, per_doc=3, decompose=True,
                                      expand=True, origin=docrole.ORIGIN, origin_id=ids["none"],
                                      progress=lambda s, m, i=None: steps.append(m))
    assert cloud.sent == [] and local.sent == []
    assert claimcheck.NO_MODEL_SPLIT in steps and claimcheck.NO_MODEL_TERMS in steps
    res = hypothesis_result(ws, hid)
    ex = _excerpts(res)
    assert res["words_access"] == "none" and ex and {p["read_by"] for p in ex} == {"you"}
    assert all(p["waiting_for_you"] for p in ex)
    part = res["parts"][0]
    with pytest.raises(ValueError, match="comes from a document marked No AI"):
        judgements.reread_excerpt(ws, part["claim_id"], ex[0]["passage_id"], cloud, "claude-opus")
    assert cloud.sent == [] and local.sent == []
    # a second opinion leaves them out too
    out = claimcheck.second_opinion(ws, [hid], cloud, "claude-sonnet", "claude-opus")
    assert out["rounds"] == 0 and cloud.sent == []


def test_look_before_checking_and_a_check_by_queue_keep_the_words_here(drafts, monkeypatch):
    from helpers_mixed_corpus import LOCAL_MARK, NONE_MARK, Cloud, Local, use_local_model

    from enlens_claims import access, claimcheck

    ws, ids = drafts
    cloud, local = Cloud(), Local()
    use_local_model(monkeypatch, local)
    # Look before checking: the local model proposes for the draft marked Only a local AI, nobody for No AI
    claimcheck.prepare_check(ws, _words(LOCAL_MARK), cloud, "claude-opus", decompose=True, expand=True,
                             origin=docrole.ORIGIN, origin_id=ids["local"])
    assert cloud.sent == [] and "expand" in local.kinds
    n = len(local.sent)
    got = claimcheck.prepare_check(ws, _words(NONE_MARK), cloud, "claude-opus", decompose=True, expand=True,
                                   origin=docrole.ORIGIN, origin_id=ids["none"])
    assert got == {"parts": [{"text": _words(NONE_MARK), "role": None}], "terms": [[]], "split": False}
    assert cloud.sent == [] and len(local.sent) == n
    # by queue (Claude Code): no step of these checks waits for Claude Code; each is checked as written
    for key, mark in (("local", LOCAL_MARK), ("none", NONE_MARK)):
        hid = claimcheck.queue_check(ws, _words(mark), None, k=6, per_doc=3, decompose=True, expand=True,
                                     origin=docrole.ORIGIN, origin_id=ids[key])
        rows = ws.query("SELECT task_id, kind, access, queued FROM tasks WHERE task_id LIKE ?", (f"%{hid}%",))
        assert rows and {r["kind"] for r in rows} == {"check"}            # no split, no search words asked
        assert not any(r["queued"] for r in rows) and "cloud" not in {r["access"] for r in rows}
        ends = {r["task_id"].rsplit(":", 1)[-1] for r in rows}
        assert ends == ({"local"} if key == "local" else {"person"})
    assert claimcheck.run_local_parts(ws, None, access.Readers(None, "")) == 1
    assert cloud.sent == [] and LOCAL_MARK.lower() in local.sent[-1].lower()


def test_a_claude_chat_is_not_shown_the_checks_of_a_draft_kept_here(drafts):
    pytest.importorskip("mcp")
    import asyncio
    import json

    from helpers_mixed_corpus import LOCAL_MARK, NONE_MARK
    from mcp import Client

    from enlens_claims import access, claimcheck
    from enlens_claims.mcp_server import build_server

    ws, ids = drafts
    made = {}
    for key, mark in (("cloud", "shared"), ("local", LOCAL_MARK), ("none", NONE_MARK)):
        hid = claimcheck.create_hypothesis(ws, _words(mark), origin=docrole.ORIGIN, origin_id=ids[key])
        claimcheck.new_claim(ws, _words(mark), hyp_id=hid, claim_id=f"c-{key}")
        made[key] = hid
    assert access.hidden_hypotheses(ws) == {made["local"], made["none"]}

    async def run():
        async with Client(build_server()) as c:
            r = await c.call_tool("list_checks", {"project": "Drafts"})
            listed = json.loads(r.content[0].text)["checks"]
            assert [x["check_id"] for x in listed] == ["c-cloud"]
            assert not any(m.lower() in r.content[0].text.lower() for m in (LOCAL_MARK, NONE_MARK))
            for key in ("local", "none"):
                r = await c.call_tool("get_check", {"check_id": f"c-{key}"})
                assert r.is_error and "kept on this computer" in r.content[0].text

    asyncio.run(run())
    # the setting follows the document: marked Claude may read it, the check is shown; removed, it is not
    access.set_documents(ws, [ids["local"]], "cloud")
    assert access.hidden_hypotheses(ws) == {made["none"]}
    ws.remove_document(ids["local"])
    assert access.hidden_hypotheses(ws) == {made["local"], made["none"]}


# ---- the routes ---------------------------------------------------------------------------------------------------
def test_the_routes(api, tmp_path):  # noqa: F811
    d = tmp_path / "in"
    d.mkdir()
    (d / "draft.txt").write_text(DRAFT, encoding="utf-8")
    assert api("POST", "/api/projects", {"name": "Mine"})[0] == 200
    from enlens_claims import home

    ws = Workspace.open(home.project_path("Mine"))
    try:
        ingest.ingest(ws, [d])
        draft = ws.scalar("SELECT doc_id FROM documents")
    finally:
        ws.close_all()
    st, body = api("PUT", f"/api/projects/Mine/documents/{draft}/role", {"role": "working"})
    assert st == 200 and body["role"] == "working" and body["changed"]
    assert api("GET", "/api/projects/Mine/document-roles")[1] == {"roles": {draft: "working"}, "nonscientific": []}
    assert api("GET", f"/api/projects/Mine/documents/{draft}/role")[1]["role"] == "working"
    assert api("PUT", f"/api/projects/Mine/documents/{draft}/role", {"role": "draft"})[0] == 400


def test_a_check_started_from_a_document_by_the_route(api, corpus):  # noqa: F811
    """POST /checks with `from_doc`: the check remembers the document; GET …/role lists it under `started`; the result
    names the document. A document not in the project is refused before anything starts."""
    import time

    from test_queue import _project

    docs = _project(api, corpus)
    doc = sorted(docs.values())[0]
    claim = "Electrolysis needs large amounts of fresh water in dry regions."
    assert api("POST", "/api/projects/P/checks", {"text": claim, "k": 3, "from_doc": "nope"})[0] == 400
    assert api("POST", "/api/projects/P/prepare", {"text": claim, "from_doc": "nope"})[0] == 400  # Look before checking
    st, r = api("POST", "/api/projects/P/checks", {"text": claim, "k": 3, "from_doc": doc})
    assert st == 200
    jid = r["job"]["id"]
    try:
        end, started = time.time() + 15, []
        while time.time() < end and not started:
            started = api("GET", f"/api/projects/P/documents/{doc}/role")[1]["started"]
            time.sleep(0.2)
        assert [s["text"] for s in started] == [claim]
        res = api("GET", f"/api/projects/P/hypotheses/{started[0]['hyp_id']}")[1]
        assert res["origin"] == "document" and res["origin_id"] == doc and res["origin_title"]
        other = sorted(docs.values())[1]
        assert api("GET", f"/api/projects/P/documents/{other}/role")[1]["started"] == []
    finally:
        api("POST", f"/api/jobs/{jid}/cancel")
        api.wait(jid)


from test_app import api, home  # noqa: E402,F401  (fixtures)


# ---- the pages ----------------------------------------------------------------------------------------------------
def _js(name: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static" / name).read_text(
        encoding="utf-8")


def _block(src: str, start: str, end: str = "\n  }\n") -> str:
    i = src.index(start)
    return src[i:src.index(end, i)]


def test_the_hypotheses_page_says_who_reads_the_words_and_keeps_the_tie_only_while_it_holds():
    """N3C-1, N3C-5: before Check, one sentence per AI setting says who reads the words; the note shows while the box
    holds one hypothesis from the document; the tie is dropped for a list, after the check, when the page is opened
    without the document's words, and when the document is gone (said in plain words); Look before checking sends
    the document too."""
    hyp = _js("views/hypotheses.js")
    who = _block(hyp, "export const WHO_READS = {", "\n};\n")
    assert "only a local model on this computer reads these words" in who and "no model reads these words" in who
    assert "The AI you chose reads these words" in who
    assert 'if (query.text && query.from) draft.fromDoc = String(query.from); else delete draft.fromDoc;' in hyp
    note = _block(hyp, "function drawFromNote(lost)")
    assert 'composerMode(ta.value) === "single"' in note and "d.title || d.file" in note and "WHO_READS[d.ai_access]" in note
    assert "untie();" in _block(hyp, "function applyMode()")                      # a list keeps no document
    one = _block(hyp, "async function checkOne(seen)")
    assert "if (fromDoc) body.from_doc = fromDoc;" in one and "untie();" in one
    assert "if (lostDoc(err)) untie(true); else showError(err);" in one
    look = hyp[hyp.index('lookBtn.addEventListener("click"'):hyp.index("function drawPrepared()")]
    assert "if (fromDoc) body.from_doc = fromDoc;" in look and "if (lostDoc(e)) untie(true);" in look
    assert "|| \"your document\"" not in hyp


def test_the_document_page_shows_eight_checks_and_folds_the_rest():
    """N3C-6: as the list of what was made with a document in, the newest eight, then the others in a fold."""
    role = _js("views/doc-role.js")
    started = _block(role, "function startedList(started)", "\n}\n")
    assert "const STARTED_SHOWN = 8;" in role and "started.slice(0, STARTED_SHOWN)" in started
    assert 'fold({ sm: true, class: "doc-started-more" }, `and ${plural(rest.length, "more check")}`' in started


def test_an_excerpt_waiting_for_a_person_says_why():
    """N3C-1: on the result, an excerpt of a document Claude may read can wait because the hypothesis's words come
    from a draft kept here; the card says so instead of blaming the excerpt's document."""
    res = _js("views/result.js")
    assert "fact(waitReason(p.access, current && current.words_access))" in res
    reason = _block(res, "export function waitReason(", "\n}\n")
    assert '"the hypothesis comes from a document marked No AI"' in reason
