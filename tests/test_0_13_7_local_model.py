"""0.13.7: a model on this computer without a terminal.

Switching to a privacy option must be easy for anyone. A local model used to need a terminal (`ollama pull qwen3:8b`)
and the first screen said "This is the technical part… ask whoever installs the app". Now the app downloads the model
into Ollama with one button (POST /api/servers/pull, a job with its progress and a Stop button), notices Ollama
starting by itself, and "Use a local model" no longer skips the step when no model answers. Nothing of the person's
is sent: Ollama fetches the model from ollama.com. These tests use the stand-in Ollama (tests/fake_servers.py), never
a real one.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

import fake_servers
from helpers import manual_text
from enlens_claims import llm
from enlens_claims.llm import BackendError, OllamaBackend
from test_app import Api, api, home  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"
DEAD = "http://127.0.0.1:9"


@pytest.fixture
def ollama():
    """A new Ollama: running, with no model yet; the names a real one would list."""
    srv, url = fake_servers.start("ollama")
    srv.aliases = {"qwen3:8b": fake_servers.FAKE_MODEL, "nomic-embed-text:latest": fake_servers.FAKE_EMBED}
    srv.installed = []
    llm._DETECTED.clear()
    yield srv, url
    srv.shutdown()
    llm._DETECTED.clear()


def _ollama_row(api):
    st, info = api("GET", "/api/servers")
    assert st == 200
    return info, next((x for x in info["servers"] if x["kind"] == "ollama"), None)


# ---------------------------------------------------------------------------------------------- the client
def test_pull_reports_progress_and_the_model_answers(ollama, home):  # noqa: F811
    srv, url = ollama
    seen = []
    assert OllamaBackend(base_url=url).pull("qwen3:8b", on_progress=seen.append) == "success"
    assert srv.pulled == ["qwen3:8b"] and srv.installed == ["qwen3:8b"]
    sizes = [p for p in seen if p["total"]]
    assert sizes and sizes[-1]["done"] == sizes[-1]["total"] == 5_200_000_000
    assert [p["done"] for p in sizes] == sorted(p["done"] for p in sizes)   # it only goes up
    assert seen[0]["status"] == "pulling manifest" and seen[-1]["status"] == "success"
    # the automatic choice now finds it, and it answers
    be, model = home.make_backend(dict(home.DEFAULTS, backend="auto", ollama_url=url))
    assert model == "qwen3:8b" and isinstance(be, OllamaBackend)


def test_pull_says_what_went_wrong(ollama):
    srv, url = ollama
    be = OllamaBackend(base_url=url)
    with pytest.raises(BackendError, match="library has no model called qwen9:1b"):
        be.pull("qwen9:1b")
    srv.pull_fail = "write /root/.ollama/models/blobs/sha256-x: no space left on device"
    with pytest.raises(BackendError, match="not enough free disk space for qwen3:8b"):
        be.pull("qwen3:8b")
    assert srv.installed == []   # a download that broke off lists nothing
    with pytest.raises(BackendError, match="Could not reach Ollama"):
        OllamaBackend(base_url=DEAD).pull("qwen3:8b")
    offline = llm.pull_error("qwen3:8b", 'pull model manifest: Get "https://registry.ollama.ai/v2/": dial tcp: '
                                         "lookup registry.ollama.ai: no such host")
    assert offline.startswith("Ollama could not reach ollama.com to download qwen3:8b. Is this computer online?")
    assert llm.pull_error("x", "something new") == "Ollama could not download x: something new"


def test_stopping_a_pull(ollama):
    srv, url = ollama
    srv.pull_seconds = 2.0
    calls = []
    assert OllamaBackend(base_url=url).pull("qwen3:8b", should_stop=lambda: calls.append(1) or len(calls) > 2) == "stopped"
    assert srv.installed == []
    deadline = time.time() + 5
    while not srv.disconnects and time.time() < deadline:   # the stand-in notices the app stopped reading
        time.sleep(0.05)
    assert srv.disconnects == 1


def test_model_names():
    for good in ("qwen3:8b", "nomic-embed-text", "library/qwen3:8b", "hf.co/user/model:Q4_K_M", "llama3.1:8b"):
        assert llm.valid_model_name(good), good
    for bad in ("", "qwen3:8b; rm -rf /", "../etc", "a b", "-flag", "x" * 121, "http://evil/x", None, 3):
        assert not llm.valid_model_name(bad), bad
    assert [m["name"] for m in llm.SUGGESTED_MODELS] == ["qwen3:8b", "nomic-embed-text"]
    assert [m["use"] for m in llm.SUGGESTED_MODELS] == ["chat", "embed"]


# ---------------------------------------------------------------------------------------------- the API
def test_download_from_the_app(ollama, api, monkeypatch):  # noqa: F811
    from enlens_claims import modeladvice

    # 0.18.0rc2 (M8): the models suggested fit the computer: this test means a 16 GB one (GitHub's Mac runner has 7 GB)
    monkeypatch.setattr(modeladvice, "computer", lambda *a, **k: {"memory": 16 * 1024 ** 3, "disk_free": 200 * 1024 ** 3,
                                                                  "system": "mac", "unified": True, "gpu": None})
    srv, url = ollama
    assert api("PUT", "/api/settings", {"backend": "auto", "ollama_url": url, "ollama_model": ""})[0] == 200
    info, row = _ollama_row(api)
    assert row["chat_models"] == [] and row["embedding_models"] == []
    assert [m["name"] for m in info["suggested"]] == ["qwen3:8b", "nomic-embed-text"]
    st, r = api("POST", "/api/servers/pull", {"models": ["qwen3:8b", "nomic-embed-text"], "url": row["url"]})
    assert st == 200 and r["job"]["kind"] == "model-pull" and r["job"]["project"] is None
    assert r["job"]["title"] == "Downloading qwen3:8b and nomic-embed-text"
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done", job
    assert job["result"] == {"url": row["url"], "models": ["qwen3:8b", "nomic-embed-text"],
                             "listed": {"qwen3:8b": "qwen3:8b", "nomic-embed-text": "nomic-embed-text:latest"},
                             "chosen": None}   # no "use": nothing is chosen
    assert job["progress"]["model"] == "nomic-embed-text" and job["progress"]["index"] == 1
    assert job["progress"]["count"] == 2 and job["progress"]["done"] == job["progress"]["total"] > 0
    _, row = _ollama_row(api)   # listed at once (the servers' cache was cleared)
    assert row["chat_models"] == ["qwen3:8b"] and row["embedding_models"] == ["nomic-embed-text:latest"]
    # as the page does next: the downloaded model becomes the AI, and the test finds it
    assert api("PUT", "/api/settings", {"backend": "ollama", "ollama_url": url, "ollama_model": "qwen3:8b"})[0] == 200
    st, t = api("POST", "/api/servers/test")
    assert st == 200 and t["model_available"] is True and t["model"] == "qwen3:8b"


def test_the_download_chooses_the_model_even_with_the_page_closed(ollama, api):  # noqa: F811
    """With "use", the app chooses the model when the download is done: a person may close the tab during 5 GB."""
    srv, url = ollama
    api("PUT", "/api/settings", {"backend": "auto", "ollama_url": url, "ollama_model": "", "embed_backend": "off"})
    job = api.wait(api("POST", "/api/servers/pull", {"models": ["qwen3:8b", "nomic-embed-text"], "use": "ai"})[1]["job"]["id"])
    chosen = {"backend": "ollama", "ollama_url": url, "ollama_model": "qwen3:8b", "embed_backend": "ollama",
              "embed_model": "nomic-embed-text:latest", "embed_url": ""}
    assert job["result"]["chosen"] == chosen
    s = api("GET", "/api/state")[1]["settings"]
    assert {k: s[k] for k in chosen} == chosen
    assert api("POST", "/api/servers/test")[1]["model_available"] is True
    # the local model for documents marked Only a local AI, with Claude Code as the AI
    srv.installed = []
    api("PUT", "/api/settings", {"backend": "claude_code", "allow_claude_code": True})
    job = api.wait(api("POST", "/api/servers/pull", {"model": "qwen3:8b", "use": "restricted"})[1]["job"]["id"])
    assert job["result"]["chosen"] == {"restricted_server": "ollama", "restricted_model": "qwen3:8b"}
    st = api("GET", "/api/state")[1]
    assert st["settings"]["backend"] == "claude_code" and st["restricted"]["model"] == "qwen3:8b"
    # search by meaning only
    srv.installed = ["qwen3:8b"]
    api("PUT", "/api/settings", {"embed_backend": "off", "embed_model": ""})
    job = api.wait(api("POST", "/api/servers/pull", {"model": "nomic-embed-text", "use": "embed"})[1]["job"]["id"])
    assert job["result"]["chosen"] == {"embed_backend": "ollama", "embed_model": "nomic-embed-text:latest", "embed_url": ""}
    assert api("GET", "/api/state")[1]["settings"]["backend"] == "claude_code"


def test_a_choice_made_meanwhile_stands(ollama, api):  # noqa: F811
    srv, url = ollama
    srv.pull_seconds = 1.5
    api("PUT", "/api/settings", {"backend": "auto", "ollama_url": url, "ollama_model": ""})
    jid = api("POST", "/api/servers/pull", {"model": "qwen3:8b", "use": "ai"})[1]["job"]["id"]
    api("PUT", "/api/settings", {"backend": "baseline"})   # the person chose something else during the download
    job = api.wait(jid)
    assert job["state"] == "done" and job["result"]["chosen"] is None
    assert api("GET", "/api/state")[1]["settings"]["backend"] == "baseline"
    assert api("POST", "/api/servers/pull", {"model": "qwen3:8b", "use": "everything"})[0] == 400


def test_download_guards(ollama, api):  # noqa: F811
    srv, url = ollama
    api("PUT", "/api/settings", {"ollama_url": url})
    for body in ({}, {"model": ""}, {"model": "qwen3:8b; rm -rf /"}, {"models": []}, {"models": "qwen3:8b"},
                 {"models": ["a", "b", "c", "d", "e"]}, {"models": [3]}):
        st, r = api("POST", "/api/servers/pull", body)
        assert st == 400 and "Name the model" in r["error"], body
    # only an Ollama that answers on this computer (or at the address in Settings) is asked
    st, r = api("POST", "/api/servers/pull", {"model": "qwen3:8b", "url": "http://evil.example:11434"})
    assert st == 409 and "No Ollama is running" in r["error"]
    api("PUT", "/api/settings", {"ollama_url": DEAD})
    llm._DETECTED.clear()
    st, r = api("POST", "/api/servers/pull", {"model": "qwen3:8b"})
    assert st == 409 and "Open the Ollama app" in r["error"]
    assert srv.pulled == [] and not [p for p, _ in srv.requests if p == "/api/pull"]


def test_one_download_at_a_time_and_stop(ollama, api):  # noqa: F811
    srv, url = ollama
    srv.pull_seconds = 3.0
    api("PUT", "/api/settings", {"ollama_url": url})
    first = api("POST", "/api/servers/pull", {"model": "qwen3:8b"})[1]["job"]
    again = api("POST", "/api/servers/pull", {"model": "nomic-embed-text"})[1]["job"]
    assert again["id"] == first["id"]   # the running download is shown again, not a second one started
    time.sleep(0.5)
    assert api("POST", f"/api/jobs/{first['id']}/cancel")[0] == 200
    job = api.wait(first["id"])
    assert job["state"] == "cancelled" and job["result"] is None
    assert srv.installed == []
    st, jobs = api("GET", "/api/jobs")
    assert any(j["kind"] == "model-pull" and j["state"] == "cancelled" for j in jobs["jobs"])


def test_a_failed_download_says_why(ollama, api):  # noqa: F811
    srv, url = ollama
    srv.pull_fail = "write blobs: no space left on device"
    api("PUT", "/api/settings", {"ollama_url": url})
    job = api.wait(api("POST", "/api/servers/pull", {"model": "qwen3:8b"})[1]["job"]["id"])
    assert job["state"] == "error" and job["error"].startswith("There is not enough free disk space for qwen3:8b")


def test_local_only_may_download(ollama, api, monkeypatch):  # noqa: F811
    """A download sends nothing of the person's, so it is allowed where cloud models are switched off."""
    srv, url = ollama
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    api("PUT", "/api/settings", {"backend": "auto", "ollama_url": url})
    job = api.wait(api("POST", "/api/servers/pull", {"model": "qwen3:8b"})[1]["job"]["id"])
    assert job["state"] == "done" and srv.pulled == ["qwen3:8b"]


def test_messages_point_to_the_app_not_a_terminal(ollama, home):  # noqa: F811
    srv, url = ollama
    with pytest.raises(BackendError, match="download one in Settings → AI"):
        home.make_backend(dict(home.DEFAULTS, backend="auto", ollama_url=url))
    with pytest.raises(BackendError, match="Download one in Settings → AI"):
        home.make_backend(dict(home.DEFAULTS, backend="ollama", ollama_url=url, ollama_model=""))


# ---------------------------------------------------------------------------------------------- the page
def test_page_files():
    setup = (STATIC / "views" / "setup.js").read_text(encoding="utf-8")
    settings = (STATIC / "views" / "settings.js").read_text(encoding="utf-8")
    access = (STATIC / "views" / "ai-access.js").read_text(encoding="utf-8")
    helper = (STATIC / "views" / "local-model.js").read_text(encoding="utf-8")
    for name, js in (("setup.js", setup), ("settings.js", settings), ("ai-access.js", access)):
        assert "ollama pull" not in js and "In a terminal" not in js, name   # no terminal on a working screen
        assert 'from "./local-model.js"' in js and "localModelHelp(" in js, name
    assert "This is the technical part" not in setup
    assert '"Get a model on this computer (free, no terminal)"' in access   # folded for people who use Claude
    # "Use a local model" (the automatic choice) counts as set up only when a model answers
    assert 'if (!cc && modelOk && (s.backend || "auto") === "auto") modelOk = hasChatModel((await lookForServers()).servers);' in setup
    assert "if (opts.test) testBtn.click();" in setup   # a model just downloaded is tested at once
    assert 'api("POST", "/api/servers/pull", { models: names(), url: ollama.url, use: opts.use || "" })' in helper
    assert 'use: "ai"' in setup and 'use: "ai"' in settings and 'use: "embed"' in settings and 'use: "restricted"' in access
    # 0.17.0 (design guide): the outside link is the link component (kind "external" opens a new tab with rel noopener)
    assert "https://ollama.com/download" in helper and 'link({ kind: "external"' in helper
    assert "none of your documents are sent" in helper and "/cancel" in helper
    assert 'x.kind === "model-pull"' in helper   # a download already running is shown again
    assert "el.isConnected" in helper and "LOOK_EVERY = 3000" in helper   # looks again only while on the page
    registry = (STATIC / "registry.js").read_text(encoding="utf-8")
    assert '"model-pull": { icon: "download", text: "Downloading a model", link: "#/settings/model" }' in registry
    from _static import rule  # 0.17.0: reads the cascade, so it holds when the rules move

    assert rule(".local-help")
    guide = rule(".local-help .guide")
    assert guide["margin"] == "0" and guide["padding"] == "0" and guide["list-style"] == "none"


def test_the_docs_say_so():
    api_md = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    assert "POST /api/servers/pull" in api_md
    manual = manual_text()  # the hub and its pages
    assert "Download qwen3:8b" in manual
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")  # 0.14.0: the README keeps only the newest series
    assert "**A model on this computer, without a terminal.**" in changelog
