"""0.17: Set up search by meaning is one job per project. A second press (or a second tab, or a reload while it
runs) gets the job that runs, not a second one embedding the same excerpts; the Documents page shows the running job
in place of the button."""
import threading
from pathlib import Path

from test_app import Api, api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


def _settings(api):
    # a model is chosen, at an address where nothing listens: no real model is ever loaded
    st, _ = api("PUT", "/api/settings", {"embed_backend": "ollama", "embed_model": "stub-embed",
                                         "embed_url": "http://127.0.0.1:9"})
    assert st == 200


def test_a_second_start_returns_the_running_index_job(api, monkeypatch):
    from enlens_claims import embed

    release, started, calls = threading.Event(), threading.Event(), []

    def slow_build(ws, emb, progress=None, should_stop=None, **kw):
        calls.append(1)
        progress(3, 10)
        started.set()
        release.wait(20)
        return {"embedded": 10}

    monkeypatch.setattr(embed, "build", slow_build)
    _settings(api)
    assert api("POST", "/api/projects", {"name": "P"})[0] == 200
    assert api("POST", "/api/projects", {"name": "Q"})[0] == 200
    try:
        st, first = api("POST", "/api/projects/P/index")
        assert st == 200
        assert started.wait(10)
        st, second = api("POST", "/api/projects/P/index")
        assert st == 200
        assert second["job"]["id"] == first["job"]["id"]
        assert second["job"]["kind"] == "index" and second["job"]["state"] in ("queued", "running")
        assert len(calls) == 1                                    # nothing was started twice
        # another project is its own business
        other = api("POST", "/api/projects/Q/index")[1]["job"]["id"]
        assert other != first["job"]["id"]
        # the running job is what /api/jobs lists, once for P
        mine = [j for j in api("GET", "/api/jobs")[1]["jobs"] if j["project"] == "P" and j["kind"] == "index"]
        assert [j["id"] for j in mine] == [first["job"]["id"]]
    finally:
        release.set()
    assert api.wait(first["job"]["id"])["state"] == "done"
    # once it has finished, a new press starts a new job
    release.set()
    again = api("POST", "/api/projects/P/index")[1]["job"]["id"]
    assert again != first["job"]["id"]
    api.wait(again)
    api.wait(other)


def test_the_documents_page_follows_the_running_job():
    js = (STATIC / "views" / "sources.js").read_text(encoding="utf-8")
    draw = js[js.index("function drawIndex(search)"):js.index("// ----------------------------------------------------------------- documents")]
    # the card consults the running job: heading, counts from its progress, a disabled button, no active one
    assert "if (indexJob)" in draw
    assert "Setting up search by meaning…" in draw and "indexJob.progress" in draw
    running = draw[draw.index("if (indexJob)"):draw.index("if (!s.passages)")]
    assert "disabled: true" in running and "Set up search by meaning" not in running
    # started here: the job is kept for the card; found after a reload: the same
    assert js.count("followIndex(") >= 3
    assert "indexJob = indexing" in js
    # when it ends, the counts are read again
    follow = js[js.index("function followIndex"):js.index("function drawIndex(search)")]
    assert "indexJob = null" in follow and "reloadDocs()" in follow


def test_the_sidebar_does_not_call_the_index_job_claude():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'LOCAL_JOB_KINDS = new Set(["index"])' in js and "w.local" in js
