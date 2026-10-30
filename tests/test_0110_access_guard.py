"""0.11: the guard where tasks are made and run.

- `_insert_task` labels a task with the most restricted setting of the documents its payload names, at any depth;
- `run_one` refuses a `local` task on a route that leaves the computer and a `none` task on any route, before the
  backend is asked; the queue for Claude Code hands out only `cloud` tasks;
- changing a document's setting takes effect for every task not answered yet (a queued one leaves the queue);
- the settings themselves: the project's default, a new project asks once, the cap, the import question.
"""
from __future__ import annotations

import json

import pytest
from helpers_0110 import Cloud, Local, mixed_project

from enlens_claims import access, home, ingest, taskqueue, tasks
from enlens_claims.store import Workspace


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Mixed")
    ids = mixed_project(ws, tmp_path / "corpus")
    pid = {k: ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 1", (v,)) for k, v in ids.items()}
    return ws, ids, pid


def _label(pid):
    return {"framework": "sdg", "passage_id": pid, "title": "t", "page": None, "text": "Green hydrogen and water.",
            "candidates": []}


def _insert(ws, tid, payload, kind="check"):
    with ws.connect() as cx:
        tasks._insert_task(cx, tid, kind, "m", payload)
    return ws.scalar("SELECT access FROM tasks WHERE task_id=?", (tid,))


def test_tasks_are_labelled_with_the_most_restricted_document(mixed):
    ws, ids, pid = mixed
    assert _insert(ws, "expand:x", {"claim": "no document text"}, "expand") == "cloud"
    assert _insert(ws, "check:a", {"passages": [{"passage_id": pid["cloud"], "doc_id": ids["cloud"]}]}) == "cloud"
    assert _insert(ws, "check:b", {"passages": [{"passage_id": pid["cloud"]}, {"passage_id": pid["local"]}]}) == "local"
    assert _insert(ws, "check:c", {"passages": [{"passage_id": pid["local"]}, {"doc_id": ids["none"]}]}) == "none"
    # at any depth: the snippets of a link task's terms
    deep = {"terms": [{"n": 1, "snippets": [{"passage_id": pid["cloud"]}]}, {"n": 2, "snippets": [{"passage_id": pid["local"]}]}]}
    assert _insert(ws, "link:a|b", deep, "link") == "local"
    # a passage of a removed document, and nothing else to go by: kept here
    assert _insert(ws, "check:d", {"passages": [{"passage_id": "gone:0001"}]}) == "none"


def test_run_one_refuses_before_the_backend_is_asked(mixed):
    ws, ids, pid = mixed
    _insert(ws, "label:sdg:" + pid["local"], _label(pid["local"]), "label")
    _insert(ws, "label:sdg:" + pid["none"], _label(pid["none"]), "label")
    cloud, local = Cloud(), Local()
    with pytest.raises(access.AccessError, match="Only a local AI"):
        tasks.run_one(ws, "label:sdg:" + pid["local"], cloud, "m")
    with pytest.raises(access.AccessError, match="No AI"):
        tasks.run_one(ws, "label:sdg:" + pid["none"], local, "m")
    assert not cloud.sent and not local.sent
    # a model server on another computer counts as leaving this computer
    far = Local()
    far.base_url = "http://gpu.example.org:11434"
    with pytest.raises(access.AccessError):
        tasks.run_one(ws, "label:sdg:" + pid["local"], far, "m")
    assert not far.sent
    # the local model on this computer may read it
    tasks.run_one(ws, "label:sdg:" + pid["local"], local, "m")
    assert local.sent
    # Claude Code: a task the queue would never hand out is not waited for
    from enlens_claims.llm import ClaudeCodeBackend

    _insert(ws, "label:sdg:other", _label(pid["none"]), "label")
    with pytest.raises(access.AccessError):
        tasks.run_one(ws, "label:sdg:other", ClaudeCodeBackend(), "haiku")


def test_the_queue_only_ever_holds_cloud_tasks(mixed):
    ws, ids, pid = mixed
    with tasks.queueing():
        for k in ("cloud", "local", "none"):
            _insert(ws, f"label:sdg:{pid[k]}", _label(pid[k]), "label")
    q = {r["task_id"]: r["queued"] for r in ws.query("SELECT task_id, queued FROM tasks")}
    assert q == {f"label:sdg:{pid['cloud']}": 1, f"label:sdg:{pid['local']}": 0, f"label:sdg:{pid['none']}": 0}
    with ws.connect() as cx:  # even when someone tries to put them there
        tasks.mark_queued(cx, list(q))
        cx.execute("UPDATE tasks SET queued=1")  # by hand: the queue still skips them
    got = taskqueue.next_tasks(ws, "label", n=10)
    assert [t["task_id"] for t in got["tasks"]] == [f"label:sdg:{pid['cloud']}"]
    assert taskqueue.status(ws)["waiting"] == 0  # the restricted ones are not "waiting for Claude Code"


def test_a_changed_setting_applies_to_tasks_not_answered_yet(mixed):
    ws, ids, pid = mixed
    with tasks.queueing():
        _insert(ws, "label:sdg:a", _label(pid["cloud"]), "label")
        _insert(ws, "label:sdg:b", _label(pid["cloud"]), "label")
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET status='done' WHERE task_id='label:sdg:b'")
    r = access.set_documents(ws, [ids["cloud"]], "local")
    assert r["tasks_changed"] == 1
    a = ws.query("SELECT access, queued FROM tasks WHERE task_id='label:sdg:a'")[0]
    assert (a["access"], a["queued"]) == ("local", 0)  # out of the queue
    assert ws.scalar("SELECT access FROM tasks WHERE task_id='label:sdg:b'") == "cloud"  # answered: as it was read
    access.set_documents(ws, [ids["cloud"]], None)  # back to the project's default
    assert ws.scalar("SELECT access FROM tasks WHERE task_id='label:sdg:a'") == "cloud"
    assert access.documents_view(ws)[ids["cloud"]]["own"] is None


def test_project_default_and_the_question_once(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    from helpers_0110 import write_corpus

    ws = home.create_project("New")
    assert not access.default_chosen(ws) and access.default(ws) == "cloud"   # as 0.10 did, until answered
    write_corpus(tmp_path / "c")
    ingest.ingest(ws, [tmp_path / "c"], ai_access="local")  # the first answer becomes the project's default
    assert access.default_chosen(ws) and access.default(ws) == "local"
    assert {r[0] for r in ws.query("SELECT ai_access FROM documents")} == {None}  # they follow the default
    assert access.project_info(ws)["ask"] is False
    access.set_default(ws, "none")
    assert set(access.levels(ws).values()) == {"none"}
    with pytest.raises(ValueError):
        access.set_default(ws, "everyone")
    # an installation without cloud models: local is the default and cloud cannot be chosen
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    ws2 = home.create_project("Shared")
    assert access.default(ws2) == "local"
    with pytest.raises(ValueError, match="switched off"):
        access.set_default(ws2, "cloud")


def test_the_manifest_sets_the_setting_per_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    from helpers_0110 import write_corpus

    folder = write_corpus(tmp_path / "c")
    (folder / "manifest.csv").write_text("file,reference,ai_access,ai_note\nlicensed_study.txt,Study,local,publisher "
                                         "licence\ninterviews.txt,Interviews,nope,\n")
    ws = Workspace.create(tmp_path / "ws")
    stats = ingest.ingest(ws, [folder], ai_access="cloud")
    view = {r["path"].rsplit("/", 1)[-1]: r for r in ws.query("SELECT path, ai_access, ai_note FROM documents")}
    assert view["licensed_study.txt"]["ai_access"] == "local" and view["licensed_study.txt"]["ai_note"] == "publisher licence"
    assert view["open_report.txt"]["ai_access"] is None  # the answer for all, which is the default
    assert "interviews.txt" in stats["manifest_problems"][0]


def test_the_cap_turns_a_document_local_once_reached(mixed):
    ws, ids, pid = mixed
    access.set_documents(ws, [ids["cloud"]], budget=10)
    assert access.levels(ws, [ids["cloud"]])[ids["cloud"]] == "cloud"
    n = ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=?", (ids["cloud"],))
    with ws.connect() as cx:  # Claude reads one passage of four or so: well past 10 %
        access.record_sent(cx, "t", {"passage_id": pid["cloud"]}, "Claude API", "check")
    assert n >= 2 and access.levels(ws, [ids["cloud"]])[ids["cloud"]] == "local"
    assert access.documents_view(ws)[ids["cloud"]]["budget_reached"] is True
    assert _insert(ws, "check:capped", {"passages": [{"passage_id": pid["cloud"]}]}) == "local"
    with pytest.raises(ValueError, match="percentage"):
        access.set_documents(ws, [ids["cloud"]], budget=150)
    access.set_documents(ws, [ids["cloud"]], budget="")  # no cap
    assert access.levels(ws, [ids["cloud"]])[ids["cloud"]] == "cloud"


def test_an_address_on_this_computer():
    for u in ("http://localhost:11434", "127.0.0.1:1234/v1", "http://[::1]:8080", "http://127.5.0.1"):
        assert access.on_this_computer(u), u
    for u in ("http://gpu.example.org:11434", "https://api.anthropic.com", "", "http://10.0.0.5:11434"):
        assert not access.on_this_computer(u), u


def test_embeddings_on_another_computer_skip_restricted_passages(mixed):
    ws, ids, pid = mixed
    from enlens_claims import embed

    class FarEmbedder:
        model = "far-embed"
        base_url = "https://embeddings.example.org/v1"

        def __init__(self):
            self.seen = []

        def embed(self, texts):
            self.seen += texts
            return [[1.0, 0.0] for _ in texts]

    far = FarEmbedder()
    r = embed.build(ws, far)
    assert not any("zqx" in t.lower() for t in far.seen) and far.seen
    assert r["complete"] and r["restricted_not_embedded"] > 0
    near = FarEmbedder()
    near.base_url, near.model = "http://localhost:11434", "near-embed"
    embed.build(ws, near)
    assert any("zqxlocalmark" in t.lower() for t in near.seen)  # a local embedder reads them all
    assert json.dumps(embed.status(ws, "near-embed"))  # and its status needs no embedder
