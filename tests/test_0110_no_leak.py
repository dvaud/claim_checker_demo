"""0.11: no text of a restricted document ever reaches a cloud model, in any feature.

A project has three documents: one Claude may read, one marked "Only a local AI" (every sentence carries LOCALMARK)
and one marked "No AI" (NONEMARK). Every kind of AI task is run through a recording stand-in for Claude, through the
queue for Claude Code (the stand-in Claude Code takes the batches), and through the connector's tools; no marker may
appear in anything they were given. The local model may read LOCALMARK but never NONEMARK.
"""
from __future__ import annotations

import json

import pytest
from helpers_0110 import LOCAL_MARK, NONE_MARK, Cloud, Local, mixed_project, use_local_model

from enlens_claims import access, claimcheck, home, profile, references, tasks, terms, themes
from enlens_claims.store import Workspace

HYP = "Green hydrogen production can increase water stress in arid regions."


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Mixed")
    ids = mixed_project(ws, tmp_path / "corpus")
    cloud, local = Cloud(), Local()
    use_local_model(monkeypatch, local)
    return ws, ids, cloud, local


def _no_leak(cloud: Cloud, local: Local | None = None):
    assert cloud.sent, "the cloud model was asked nothing: the test proves nothing"
    assert cloud.leaked() == [], f"restricted text reached the cloud model: {cloud.leaked()}"
    if local is not None:
        assert NONE_MARK.lower() not in local.text(), "a document marked No AI reached the local model"


def test_every_task_kind_through_a_cloud_model(env):
    ws, ids, cloud, local = env
    # checks: search words, parts, rounds, a further round, a batch
    hid = claimcheck.check_hypothesis(ws, HYP + " It also creates jobs.", cloud, "claude-opus", decompose=True, k=12,
                                      per_doc=4)
    res = claimcheck.hypothesis_result(ws, hid)
    shown = {x["doc_id"] for p in res["parts"] for x in p["passages"]}
    assert ids["local"] in shown and ids["none"] in shown and ids["cloud"] in shown  # all three compete
    for p in res["parts"]:
        claimcheck.continue_check(ws, p["claim_id"], cloud, "claude-opus", k=12)
    claimcheck.check_batch(ws, [{"text": "Electrolysis needs fresh water."}, {"text": "Hydrogen creates local jobs."}],
                           cloud, "claude-opus", k=12, per_doc=4)
    # a second opinion, reading an excerpt again (one Claude may read, one only the local model may)
    claimcheck.second_opinion(ws, [hid], cloud, "claude-opus", "claude-opus")
    part = claimcheck.hypothesis_result(ws, hid)["parts"][0]
    by = {x["doc_id"]: x for x in part["passages"]}
    claimcheck.reread_excerpt(ws, part["claim_id"], by[ids["cloud"]]["passage_id"], cloud, "claude-opus")
    claimcheck.reread_excerpt(ws, part["claim_id"], by[ids["local"]]["passage_id"], cloud, "claude-opus")
    with pytest.raises(ValueError, match="No AI"):
        claimcheck.reread_excerpt(ws, part["claim_id"], by[ids["none"]]["passage_id"], cloud, "claude-opus")
    # Profile's AI pass over all passages, themes and their names, concepts and their links, references
    profile.ensure_pass1(ws, "sdg")
    profile.run_labels(ws, "sdg", cloud, "claude-haiku", all_passages=True)
    terms.ensure(ws)
    run_id = themes.run(ws, k=3, mode="words")
    themes.name_with_model(ws, run_id, cloud, "claude-sonnet")
    ts = [r["term_id"] for r in ws.query("SELECT term_id FROM terms ORDER BY tf DESC LIMIT 8")]
    marked = [r["term_id"] for r in ws.query("SELECT term_id FROM terms WHERE label LIKE ?", (f"%{LOCAL_MARK.lower()}%",))]
    pairs = [(a, b) for i, a in enumerate(ts) for b in ts[i + 1:]][:10] + [(ts[0], m) for m in marked[:2]]
    terms.judge_links(ws, pairs, cloud, "claude-haiku")
    references.resolve_document(ws, ids["cloud"], cloud, "claude-sonnet")
    references.resolve_document(ws, ids["local"], cloud, "claude-sonnet")
    with pytest.raises(ValueError, match="No AI"):
        references.resolve_document(ws, ids["none"], cloud, "claude-sonnet")
    _no_leak(cloud, local)
    assert local.sent and LOCAL_MARK.lower() in local.text()  # the local model did read the local document
    kinds = set(cloud.kinds)
    assert {"expand", "decompose", "check", "second", "reread", "label", "theme", "link", "resolve"} <= kinds


def test_the_sdg_pack_and_the_file_queue(env, vca_xlsx):
    ws, ids, cloud, local = env
    from enlens_claims import sources, vca

    vca.load_into(ws, vca_xlsx)
    sources.match(ws)
    tasks.make_extract(ws, "claude-sonnet", only_screened=False)
    tasks.make_verify_vca(ws, "claude-opus", k=12, beyond_cited=True, per_doc=4)
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE access='local'")  # the split made local parts
    for kind in ("extract", "verify_set"):
        tasks.run(ws, kind, cloud)
    files = tasks.export(ws, "extract")
    written = "".join(f.read_text() for f in files).lower()
    _no_leak(cloud, local)
    assert LOCAL_MARK.lower() not in written and NONE_MARK.lower() not in written


def test_the_queue_for_claude_code(env):
    """Checks, labels and theme names by queue: the stand-in Claude Code takes every batch it is given."""
    ws, ids, _cloud, local = env
    import fake_claude_code

    from enlens_claims import taskqueue

    seen: list[str] = []

    class Recording(fake_claude_code.DirectTools):
        def next_tasks(self, project, kind=None, n=None, model=None, taken_by=None, helper=None):
            got = super().next_tasks(project, kind, n, model, taken_by, helper)
            seen.append(json.dumps(got, ensure_ascii=False))
            return got

    with tasks.queueing():
        hid = claimcheck.queue_check(ws, HYP, None, k=12, per_doc=4)
        profile.ensure_pass1(ws, "sdg")
        plan = profile.label_plan(ws, "sdg", all_passages=True)
        profile.make_label_tasks(ws, "sdg", plan["passage_ids"], "haiku", all_passages=True)
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE queued=1 AND access != 'cloud'") == 0
    for _ in range(6):
        fake_claude_code.run("Mixed", tools=Recording(), wrong_first=False)
        claimcheck.run_local_parts(ws, [hid], access.Readers(None, ""))
        taskqueue.advance(ws)
    text = "\n".join(seen).lower()
    assert seen and "zqx" not in text
    res = claimcheck.hypothesis_result(ws, hid)
    who = {x["doc_id"]: x["read_by"] for p in res["parts"] for x in p["passages"]}
    assert who.get(ids["cloud"]) == "claude" and who.get(ids["local"]) == "local" and who.get(ids["none"]) == "you"
    assert res["status"] != "waiting"
    # the ledger has what Claude Code took, and nothing of the restricted documents
    sent = {r["doc_id"] for r in access.ledger(ws)}
    assert ids["cloud"] in sent and not sent & {ids["local"], ids["none"]}


def test_the_connector_tools(env):
    pytest.importorskip("mcp")
    import asyncio

    from mcp import Client

    from enlens_claims.mcp_server import build_server

    ws, ids, _cloud, _local = env
    out: list[str] = []

    async def run():
        async with Client(build_server()) as c:
            async def call(name, args):
                r = await c.call_tool(name, args)
                assert not r.is_error, r.content[0].text
                out.append(r.content[0].text)
                return json.loads(r.content[0].text)

            docs = (await call("list_documents", {"project": "Mixed"}))["documents"]
            assert {d["ai_access"] for d in docs} == {"cloud", "local", "none"}
            assert any(d["title"] == "Restricted document 1" for d in docs)
            s = await call("search_corpus", {"project": "Mixed", "query": "water", "lines": 200})
            assert s["restricted_hits"] > 0 and s["lines"]
            await call("find_concept", {"project": "Mixed", "name": "green hydrogen"})
            for d in ids.values():
                await call("document_profile", {"project": "Mixed", "document_id": d})
            st = await call("start_check", {"project": "Mixed", "claim": HYP, "search_terms": ["water", "groundwater"],
                                            "passages": 12, "per_document": 4})
            assert st["passages"] and st["restricted_passages"] > 0
            grades = [{"passage": 1, "verdict": "supports", "confidence": 0.9,
                       "quote": " ".join(st["passages"][0]["text"].split()[:6])}]
            await call("submit_grades", {"check_id": st["check_id"], "grades": grades, "summary": "One passage."})
            await call("more_passages", {"check_id": st["check_id"], "passages": 12})
            g = await call("get_check", {"check_id": st["check_id"]})
            assert g.get("restricted_evidence") is not None or g.get("restricted_note")

    asyncio.run(run())
    text = "\n".join(out).lower()
    assert "zqx" not in text, "restricted text or a restricted title reached the connector's answers"


def test_without_a_local_model_restricted_excerpts_wait_for_a_person(env, monkeypatch):
    ws, ids, cloud, _local = env
    use_local_model(monkeypatch, None)
    hid = claimcheck.check_hypothesis(ws, HYP, cloud, "claude-opus", k=12, per_doc=4)
    res = claimcheck.hypothesis_result(ws, hid)
    waiting = [x for p in res["parts"] for x in p["passages"] if x["waiting_for_you"]]
    assert waiting and {x["doc_id"] for x in waiting} == {ids["local"], ids["none"]}
    assert res["waiting_for_you"] == len(waiting)
    # a person's judgement of one of them counts like any other
    x = waiting[0]
    claimcheck.set_judgement(ws, res["parts"][0]["claim_id"], x["passage_id"], "supports")
    assert claimcheck.hypothesis_result(ws, hid)["waiting_for_you"] == len(waiting) - 1
    _no_leak(cloud)


def test_a_project_reopened_keeps_its_settings(env):
    ws, ids, _cloud, _local = env
    again = Workspace.open(ws.root)
    assert access.levels(again, list(ids.values())) == {ids["cloud"]: "cloud", ids["local"]: "local", ids["none"]: "none"}
