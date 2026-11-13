"""Text of a document marked "Only a local AI" (or "No AI") never reaches a model server on another computer.

One test per route by which document text reaches a server whose address comes from the settings:

1. embeddings for search by meaning (`embed_url`, `embed_backend`): the passages of restricted documents are not
   posted to an embedding server at another address (real `make_embedder` + `embed.build`, a recording opener);
2. the second model: the backend `make_second_backend` makes for a server at another address may read `cloud`
   only, and `second_opinion` sends it nothing from a restricted document;
3. the backend `auto` resolves to when `ollama_url` or `openai_url` names another computer: `cloud` only;
4. the local model for restricted documents (`restricted_server`) refuses a server at another address, and the
   other routes that embed or send document-derived text (terms, a task handed to such a backend) hold too.

Nothing here starts a model or opens a network connection: servers are recording stand-ins.
"""
from __future__ import annotations

import json

import pytest
from helpers_mixed_corpus import LOCAL_MARK, MARKS, NONE_MARK, Cloud, Local, Recorder, mixed_project, use_local_model

from enlens_claims import access, claimcheck, embed, llm, tasks
from enlens_claims import home as core
from enlens_claims.llm import BackendError

REMOTE = "http://gpu.example.org:11434"
REMOTE_V1 = "https://models.example.org/v1"


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    ws = core.create_project("Mixed")
    ids = mixed_project(ws, tmp_path / "corpus")
    return ws, ids


class Remote(Recorder):
    """A model server on another computer (the backend a remote `ollama_url` makes)."""
    name = "ollama"
    base_url = REMOTE


def _settings(**over) -> dict:
    # think off and a fixed context: building the backend then asks the server nothing
    return {**core.load_settings(), "think": "off", "num_ctx": 8192, **over}


# ---------------------------------------------------------------------------------------------
# 1. embeddings
# ---------------------------------------------------------------------------------------------
class _Resp:
    def __init__(self, body: dict):
        self._b = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


class RecordingOpener:
    """Stands in for `urlopen`: records every address and text posted, answers with unit vectors."""

    def __init__(self):
        self.urls: list[str] = []
        self.texts: list[str] = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode())
        self.urls.append(req.full_url)
        texts = body["input"]
        self.texts += texts
        if req.full_url.endswith("/api/embed"):
            return _Resp({"embeddings": [[1.0, 0.0] for _ in texts]})
        return _Resp({"data": [{"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(texts)]})


@pytest.mark.parametrize("settings, remote", [
    ({"embed_backend": "ollama", "embed_url": REMOTE}, True),
    ({"embed_backend": "openai", "embed_url": REMOTE_V1}, True),
    ({"embed_backend": "ollama", "embed_url": "", "ollama_url": REMOTE}, True),   # the address of the chosen kind
    ({"embed_backend": "openai", "embed_url": "", "openai_url": REMOTE_V1}, True),
    ({"embed_backend": "ollama", "embed_url": "http://localhost:11434"}, False),
    ({"embed_backend": "openai", "embed_url": "http://127.0.0.1:1234/v1"}, False),
])
def test_embeddings_never_post_restricted_passages_to_another_computer(mixed, settings, remote):
    ws, ids = mixed
    emb = core.make_embedder({"embed_model": "some-embed", **settings})
    assert embed.remote(emb) is remote
    seen = RecordingOpener()
    emb.opener = seen
    res = embed.build(ws, emb)
    text = " ".join(seen.texts).lower()
    assert seen.texts and all(u.startswith(emb.base_url) for u in seen.urls)
    if remote:
        assert not any(m in text for m in MARKS), "restricted text was posted to another computer"
        assert res.get("restricted_not_embedded")
    else:  # control: a server on this computer does read them
        assert all(m in text for m in MARKS)
    assert "hydrogen" in text  # the open document was embedded either way


def test_an_embedder_without_an_address_counts_as_another_computer(mixed):
    class Nameless:
        model = "x"

    assert embed.remote(Nameless()) is True  # unknown address: restricted passages stay out


# ---------------------------------------------------------------------------------------------
# 2. the second model
# ---------------------------------------------------------------------------------------------
def test_the_second_model_on_another_computer_may_read_cloud_text_only(mixed, monkeypatch):
    ws, ids = mixed
    monkeypatch.setattr(llm.OllamaBackend, "inventory",
                        lambda self, timeout=None: {"models": ["main-m", "second-m"], "loaded": [], "modified": {}})
    s = _settings(backend="ollama", ollama_url=REMOTE, ollama_model="main-m", second_model="second-m")
    be, model = core.make_second_backend(s)
    assert model == "second-m" and be.base_url == REMOTE
    assert access.backend_levels(be) == {"cloud"}
    # the guard in front of the real server call: a task of a local document is refused before anything is sent
    sent = []
    monkeypatch.setattr(llm.OllamaBackend, "complete", lambda self, *a, **k: sent.append(a) or "{}")
    local_pid = ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 1", (ids["local"],))
    payload = {"claim": "Green hydrogen needs water.", "passages": [
        {"passage_id": local_pid, "title": "t", "page": None, "text": LOCAL_MARK}]}
    with tasks.queueing(False):
        with ws.connect() as cx:
            tasks._insert_task(cx, "second:probe", "second", "second-m", payload)
    row = ws.query("SELECT * FROM tasks WHERE task_id='second:probe'")[0]
    assert row["access"] == "local"
    with pytest.raises(access.AccessError):
        access.require(be, row, ws)
    with pytest.raises(access.AccessError):
        tasks.run_one(ws, "second:probe", be, "second-m")
    assert not sent


def test_second_opinion_sends_a_remote_server_nothing_from_restricted_documents(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, Local())  # Claude reads the open document, the local model the restricted one
    hyp = "Green hydrogen production can increase water stress in arid regions."
    hid = claimcheck.check_hypothesis(ws, hyp, Cloud(), "claude-opus", k=12, per_doc=4)  # all three documents compete
    remote = Remote()
    out = claimcheck.second_opinion(ws, [hid], remote, "main-m", "second-m")
    text = remote.text().lower()
    assert not any(m in text for m in MARKS), "restricted text reached the second model on another computer"
    assert out["restricted"] > 0 and remote.sent  # restricted excerpts were left out, the open one was read
    # control: the same second opinion from a server on this computer may read the local document (not No AI)
    mine = Local()
    claimcheck.second_opinion(ws, [hid], mine, "main-m", "second-m")
    assert LOCAL_MARK.lower() in mine.text().lower() and NONE_MARK.lower() not in mine.text().lower()


# ---------------------------------------------------------------------------------------------
# 3. the backend "auto" with configured addresses
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("found, expect", [
    ({"kind": "ollama", "url": REMOTE, "models": ["m1"], "loaded": [], "modified": {}}, {"cloud"}),
    ({"kind": "openai", "url": REMOTE_V1, "models": ["m1"], "loaded": []}, {"cloud"}),
    ({"kind": "ollama", "url": "http://localhost:11434", "models": ["m1"], "loaded": [], "modified": {}},
     {"cloud", "local"}),
    ({"kind": "openai", "url": "http://127.0.0.1:1234/v1", "models": ["m1"], "loaded": []}, {"cloud", "local"}),
])
def test_auto_with_a_configured_remote_server_reads_cloud_text_only(found, expect, monkeypatch, tmp_path):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    asked = {}

    def detect(ollama_url=None, extra=None, **kw):
        asked.update(ollama_url=ollama_url, extra=extra)
        return [found]

    monkeypatch.setattr(core, "detect_local", detect)
    s = _settings(backend="auto", ollama_url=REMOTE, openai_url=REMOTE_V1, ollama_model="m1", openai_model="m1")
    be, _model = core.make_backend(s)
    assert asked == {"ollama_url": REMOTE, "extra": [REMOTE_V1]}  # the configured addresses are what it looks at
    assert be.base_url.startswith(found["url"].removesuffix("/v1"))
    assert access.backend_levels(be) == expect
    # what the guard then does with a task of a local document
    task = {"task_id": "t", "access": "local"}
    if "local" in expect:
        access.require(be, task)
    else:
        with pytest.raises(access.AccessError):
            access.require(be, task)


def test_auto_that_finds_a_remote_server_gives_restricted_documents_no_model(monkeypatch, tmp_path):
    """`main_reads_local` says yes for auto (it cannot know what auto will find), so no separate local model is made
    for restricted documents; when auto then finds a server on another computer, the guard still keeps their text
    from it, and they wait for a person rather than reach it."""
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(core, "detect_local", lambda ollama_url=None, extra=None, **kw: [
        {"kind": "ollama", "url": REMOTE, "models": ["m1"], "loaded": [], "modified": {}}])
    s = _settings(backend="auto", ollama_url=REMOTE, ollama_model="m1")
    assert core.main_reads_local(s) is True and core.make_restricted_backend(s) is None
    be, model = core.make_backend(s)  # auto, as a check would make it
    readers = access.Readers(be, model, s)
    assert "local" not in readers.main_levels and readers.local() is None
    with pytest.raises(access.AccessError):
        access.require(be, {"task_id": "t", "access": "local"})


# ---------------------------------------------------------------------------------------------
# 4. the local model for restricted documents, and the rest
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("server, key, url", [("ollama", "ollama_url", REMOTE), ("openai", "openai_url", REMOTE_V1)])
def test_the_model_for_restricted_documents_must_be_on_this_computer(server, key, url, tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    s = _settings(backend="claude_code", restricted_server=server, restricted_model="m1", **{key: url})
    with pytest.raises(BackendError, match="must run on this computer"):
        core.make_restricted_backend(s)
    readers = access.Readers(Remote(), "claude-opus", s)  # a main model on another computer
    assert readers.local() is None and readers.local_problem


def test_a_task_of_a_local_document_is_refused_for_every_backend_on_another_computer(mixed):
    ws, ids = mixed
    lp = ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 1", (ids["local"],))
    payload = {"framework": "sdg", "passage_id": lp, "title": "t", "page": None, "text": "x", "candidates": []}
    with tasks.queueing(False):
        with ws.connect() as cx:
            tasks._insert_task(cx, "label:sdg:probe", "label", "m", payload)
    row = ws.query("SELECT * FROM tasks WHERE task_id='label:sdg:probe'")[0]
    makes = {
        "ollama remote": llm.OllamaBackend(base_url=REMOTE),
        "openai remote": llm.LocalBackend(base_url=REMOTE_V1),
        "ollama on a LAN address": llm.OllamaBackend(base_url="http://192.168.1.20:11434"),
        "lookalike host": llm.OllamaBackend(base_url="http://localhost.example.org:11434"),
        "credentials trick": llm.LocalBackend(base_url="http://localhost@evil.example.org:8080/v1"),
    }
    for label, be in makes.items():
        with pytest.raises(access.AccessError):
            access.require(be, row, ws)
        assert access.backend_levels(be) == {"cloud"}, label
    access.require(llm.OllamaBackend(base_url="http://localhost:11434"), row, ws)  # control: this computer
