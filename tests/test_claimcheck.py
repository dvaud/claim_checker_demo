import json

import pytest

import fake_servers
from enlens_claims import benchmark, claimcheck, tasks
from enlens_claims.llm import AnthropicBackend, BackendError, BaselineBackend, OllamaBackend
from enlens_claims.retrieve import screen
from enlens_claims.schema import output_schema

CLAIM = "Green hydrogen production can increase water stress in arid regions."


# ---------------------------------------------------------------------------------------------
# claim checks
# ---------------------------------------------------------------------------------------------
def test_check_claim_with_baseline(loaded):
    steps = []
    cid = claimcheck.check_claim(loaded, CLAIM, BaselineBackend(), "baseline", target="6.4", k=4,
                                 progress=lambda s, m: steps.append(s))
    assert steps == ["terms", "rank", "grade"]
    r = claimcheck.result(loaded, cid)
    assert r["status"] in ("supported", "partially_supported") and r["terms"]
    graded = [p for p in r["passages"] if p["verdict"]]
    assert graded and graded[0]["verdict"] == "supports"
    for p in graded:  # the stored offsets point at the quote inside the passage shown
        assert p["text"][p["quote_start"]:p["quote_end"]] == p["quote"]
    assert r["target_description"].startswith("By 2030, substantially increase water-use efficiency")
    h = claimcheck.history(loaded)
    assert h[0]["claim_id"] == cid and h[0]["supports"] >= 1
    assert claimcheck.export_rows(loaded)[0]["claim"] == CLAIM
    claimcheck.delete_claim(loaded, cid)
    assert claimcheck.history(loaded) == [] and not loaded.query("SELECT 1 FROM verifications WHERE subject_kind='user_claim'")


def test_check_claim_limits_and_errors(loaded, tmp_path):
    from enlens_claims.store import Workspace

    empty = Workspace.create(tmp_path / "empty")
    with pytest.raises(ValueError, match="no readable documents"):
        claimcheck.check_claim(empty, CLAIM, BaselineBackend(), "baseline")
    with pytest.raises(ValueError, match="at least 10"):
        claimcheck.new_claim(loaded, "short")
    with pytest.raises(ValueError, match="Unknown SDG target"):
        claimcheck.new_claim(loaded, CLAIM, target="99.9")
    doc = loaded.scalar("SELECT doc_id FROM documents WHERE kind='html'")
    cid = claimcheck.check_claim(loaded, CLAIM, BaselineBackend(), "baseline", doc_ids=[doc], expand=False)
    r = claimcheck.result(loaded, cid)
    assert all(p["doc_id"] == doc for p in r["passages"]) and r["terms"] == []


def test_failed_check_reports_the_errors(loaded):
    class Bad:
        name = "bad"

        def complete(self, kind, system, user, model, payload):
            if kind == "expand":
                return '{"terms": ["water"]}'
            return '{"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": "words not in it"}]}'

    cid = claimcheck.check_claim(loaded, CLAIM, Bad(), "m", k=3)
    r = claimcheck.result(loaded, cid)
    assert r["status"] == "failed" and any("not found" in e for e in r["errors"])
    assert loaded.scalar("SELECT attempts FROM tasks WHERE task_id=?", (f"check:{cid}",)) == tasks.MAX_ATTEMPTS


def test_suggest_targets_uses_common_wording():
    codes = [s["code"] for s in claimcheck.suggest_targets(CLAIM)]
    assert codes[0] == "6.4"
    assert claimcheck.suggest_targets("Hydrogen projects create local jobs")[0]["code"] == "8.5"


# ---------------------------------------------------------------------------------------------
# backends
# ---------------------------------------------------------------------------------------------
def test_output_schemas_are_self_contained():
    for kind in ("extract", "split", "verify", "verify_set", "check", "expand"):
        s = json.dumps(output_schema(kind))
        assert "$ref" not in s and "$defs" not in s
    ext = output_schema("extract")
    assert "7.b" in ext["properties"]["claims"]["items"]["properties"]["targets"]["items"]["properties"]["target"]["enum"]


def test_ollama_backend_over_http(loaded):
    srv, url = fake_servers.start("ollama", trained_context=8192)
    try:
        be = OllamaBackend(base_url=url, num_ctx=16384)
        info = be.check(fake_servers.FAKE_MODEL)
        assert info["model_available"] and info["model"]["parameters"] == "8B" and "warning" in info
        cid = claimcheck.check_claim(loaded, CLAIM, be, fake_servers.FAKE_MODEL, k=3)
        r = claimcheck.result(loaded, cid)
        assert r["status"] == "supported" and r["model"] == fake_servers.FAKE_MODEL
        chat = [b for p, b in srv.requests if p == "/api/chat"]
        assert len(chat) == 2
        for body in chat:  # context length and answer schema go with every request; no streaming
            assert body["options"]["num_ctx"] == 16384 and body["options"]["temperature"] == 0
            assert body["format"]["type"] == "object" and body["stream"] is False and "think" not in body
        with pytest.raises(BackendError, match="ollama pull nope"):
            be.complete("expand", "You prepare a search", "CLAIM:\nx", "nope", {})
        small = OllamaBackend(base_url=url, num_ctx=4096)
        system = tasks.prompts.system_prompt("extract")
        with pytest.raises(BackendError, match="context length is 4,096"):
            small.complete("extract", system, "PASSAGE:\nabc", fake_servers.FAKE_MODEL, {})
        srv.requests.clear()
        OllamaBackend(base_url=url, think=False).complete("expand", "You prepare a search", "CLAIM:\nwater stress",
                                                           fake_servers.FAKE_MODEL, {})
        assert "think" not in srv.requests[-1][1]  # the fake model does not report the thinking capability
        srv.thinking = True
        OllamaBackend(base_url=url, think=False).complete("expand", "You prepare a search", "CLAIM:\nwater stress",
                                                           fake_servers.FAKE_MODEL, {})
        assert srv.requests[-1][1]["think"] is False
    finally:
        srv.shutdown()


def test_ollama_not_running_message():
    be = OllamaBackend(base_url="http://127.0.0.1:9", timeout=2)
    with pytest.raises(BackendError, match="Start the Ollama app"):
        be.models()


def test_anthropic_backend_with_the_real_sdk(loaded):
    pytest.importorskip("anthropic")
    srv, url = fake_servers.start("anthropic")
    try:
        be = AnthropicBackend(api_key="good-key", base_url=url)
        assert be.check("claude-opus-5-5")["model_available"]
        cid = claimcheck.check_claim(loaded, CLAIM, be, "claude-opus-5-5", k=3)
        assert claimcheck.result(loaded, cid)["status"] == "supported"
        sent = [b for p, b in srv.requests if p.startswith("/v1/messages")]
        assert sent[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
        with pytest.raises(BackendError, match="rejected the key"):
            AnthropicBackend(api_key="bad-key", base_url=url).check()
    finally:
        srv.shutdown()


def test_missing_key_is_a_plain_error(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(BackendError, match="No Claude API key"):
        AnthropicBackend()


# ---------------------------------------------------------------------------------------------
# benchmark
# ---------------------------------------------------------------------------------------------
def test_benchmark_compares_with_reference_and_stores_nothing(loaded):
    tasks.make_split(loaded, model="m")
    tasks.run(loaded, "split", BaselineBackend())
    tasks.make_verify_vca(loaded, model="ref", k=3)
    tasks.run(loaded, "verify_set", BaselineBackend())
    screen(loaded)
    tasks.make_extract(loaded, model="ref")
    tasks.run(loaded, "extract", BaselineBackend())
    before = loaded.counts()
    res = benchmark.run(loaded, BaselineBackend(), "baseline", sample=5)
    assert loaded.counts() == before
    vs, ex = res["kinds"]["verify_set"], res["kinds"]["extract"]
    assert vs["tasks"] >= 1 and vs["same_status"] == 1.0 and vs["usable"] == 1.0
    assert ex["tasks"] >= 1 and ex["same_has_claims"] == 1.0
    assert any("Checking claims" in line for line in benchmark.verdict(res))


def test_cli_check_and_backend_check(loaded, capsys):
    from enlens_claims.cli import main

    assert main(["--ws", str(loaded.root), "check", CLAIM, "--backend", "baseline", "--k", "3"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] in ("supported", "partially_supported") and out["graded"]
    assert main(["backend-check", "--backend", "ollama", "--url", "http://127.0.0.1:9"]) == 1
    assert "Start the Ollama app" in capsys.readouterr().out


def test_a_stopped_check_leaves_no_history(loaded):
    class Down:
        name = "down"

        def complete(self, *a):
            raise BackendError("Could not reach Ollama")

    with pytest.raises(BackendError):
        claimcheck.check_claim(loaded, CLAIM, Down(), "m")
    assert claimcheck.history(loaded) == [] and not loaded.query("SELECT 1 FROM tasks WHERE kind IN ('expand','check')")
