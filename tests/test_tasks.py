import json

from enlens_claims import tasks
from enlens_claims.llm import AnthropicBackend, LocalBackend
from enlens_claims.retrieve import screen


def _water_task(ws):
    screen(ws)
    tasks.make_extract(ws, model="test-model")
    rows = ws.query("SELECT * FROM tasks WHERE kind='extract'")
    t = [r for r in rows if "water stress" in json.loads(r["payload_json"])["text"]][0]
    return t, json.loads(t["payload_json"])


GOOD = {
    "claims": [{
        "claim": "Green hydrogen production can increase water stress in arid regions.",
        "activity": "electrolysis", "segment": "production",
        "targets": [{"target": "SDG 6.4", "direction": "negative", "influence": "direct"}],
        "place": "arid regions such as Morocco", "countries": ["Morocco"], "scale": "local", "side": "producer",
        "horizon": "not stated", "condition": None, "policy_lever": None, "confidence": 0.9,
        "evidence": [{"field": "claim", "quote": "Its production can increase water stress in arid regions"},
                     {"field": "place", "quote": "arid regions such as Morocco"}],
    }],
    "interactions": [],
}


def test_valid_claim_is_stored_with_document_offsets(loaded):
    t, payload = _water_task(loaded)
    ok, errors = tasks.ingest_result(loaded, t["task_id"], json.dumps(GOOD))
    assert ok and not errors
    c = loaded.query("SELECT * FROM claims")[0]
    assert c["status"] == "auto" and c["horizon"] == "not_stated" and c["model"] == "test-model"
    assert [tuple(r) for r in loaded.query("SELECT target, direction, influence FROM claim_targets")] == [("6.4", "negative", "direct")]
    text = loaded.scalar("SELECT text FROM documents WHERE doc_id=?", (payload["doc_id"],))
    for ev in loaded.query("SELECT * FROM evidence"):
        assert text[ev["start"]:ev["end"]] == ev["quote"]
    assert loaded.scalar("SELECT status FROM tasks WHERE task_id=?", (t["task_id"],)) == "done"


def test_invented_quote_is_rejected_and_task_retried(loaded):
    t, _ = _water_task(loaded)
    bad = json.loads(json.dumps(GOOD))
    bad["claims"][0]["evidence"] = [{"field": "claim", "quote": "Its production increases water stress by 30% in arid regions"}]
    ok, errors = tasks.ingest_result(loaded, t["task_id"], bad)
    assert not ok and any("quote not found" in e for e in errors)
    assert loaded.scalar("SELECT COUNT(*) FROM claims") == 0
    assert loaded.scalar("SELECT status FROM tasks WHERE task_id=?", (t["task_id"],)) == "retry"
    system, user = tasks.render(loaded, loaded.query("SELECT * FROM tasks WHERE task_id=?", (t["task_id"],))[0])
    assert "YOUR PREVIOUS ANSWER HAD THESE PROBLEMS" in user and "quote not found" in user


def test_unknown_target_and_low_confidence(loaded):
    t, _ = _water_task(loaded)
    out = json.loads(json.dumps(GOOD))
    out["claims"].append(dict(out["claims"][0], targets=[{"target": "18.2", "direction": "negative"}]))
    out["claims"][0]["confidence"] = 0.5
    ok, errors = tasks.ingest_result(loaded, t["task_id"], out)
    assert ok  # one usable claim is enough
    assert any("unknown SDG target" in e for e in errors)
    assert loaded.scalar("SELECT status FROM claims") == "needs_review"


def test_empty_answer_is_valid_and_garbage_is_not(loaded):
    t, _ = _water_task(loaded)
    assert tasks.ingest_result(loaded, t["task_id"], '```json\n{"claims": [], "interactions": []}\n```')[0]
    t2 = loaded.query("SELECT * FROM tasks WHERE kind='extract' AND status='pending' LIMIT 1")[0]
    ok, errors = tasks.ingest_result(loaded, t2["task_id"], "I could not find anything.")
    assert not ok and errors == ["no JSON object in the response"]


def test_file_queue_roundtrip(loaded):
    _water_task(loaded)
    files = tasks.export(loaded, "extract", batch_size=2)
    assert files and (loaded.root / "tasks" / "extract" / "SYSTEM.md").exists()
    first = json.loads(files[0].read_text().splitlines()[0])
    assert "PASSAGE:" in first["user"] and "task_id" in first
    res = loaded.root / "results" / "extract" / files[0].name
    lines = [json.dumps({"task_id": json.loads(l)["task_id"], "model": "worker-x", "output": {"claims": [], "interactions": []}})
             for l in files[0].read_text().splitlines()]
    res.write_text("\n".join(lines) + "\n")
    stats = tasks.import_results(loaded, [loaded.root / "results"])
    assert stats["ok"] == len(lines) and stats["invalid"] == 0
    assert tasks.import_results(loaded, [res])["skipped_done"] == len(lines)
    assert tasks.requeue(loaded, "extract") >= 0
    assert loaded.scalar("SELECT model FROM results WHERE valid=1 LIMIT 1") == "worker-x"


def test_split_requires_quotes_from_the_justification(loaded):
    tasks.make_split(loaded, model="m")
    t = loaded.query("SELECT * FROM tasks WHERE task_id='split:6.4'")[0]
    bad = {"claims": [{"text": "Hydrogen raises water stress.", "quote": "water stress doubles", "direction": "negative"}]}
    assert not tasks.ingest_result(loaded, t["task_id"], bad)[0]
    good = {"claims": [{"text": "Electrolysis needs large amounts of fresh water.", "quote": "Electrolysis needs large amounts of fresh water",
                        "segment": "production", "direction": "negative", "horizon": "short_term"},
                       {"text": "Hydrogen production can increase water stress in arid regions.",
                        "quote": "Hydrogen production can increase water stress in arid regions", "segment": "production",
                        "direction": "negative"}]}
    assert tasks.ingest_result(loaded, t["task_id"], good)[0]
    assert loaded.scalar("SELECT COUNT(*) FROM vca_claims WHERE target='6.4'") == 2


def test_verify_tasks_only_from_cited_sources_and_quote_check(loaded):
    tasks.make_split(loaded, model="m")
    for tid, quote in (("split:6.4", "Hydrogen production can increase water stress in arid regions"),
                       ("split:1.1", "Dependence on imported equipment limits local economic benefits")):
        tasks.ingest_result(loaded, tid, {"claims": [{"text": quote + ".", "quote": quote, "direction": "negative"}]})
    s = tasks.make_verify_vca(loaded, model="m", k=2, pairwise=True)
    assert s["vca_claims_without_sources"] == 1 and s["tasks"] >= 1  # 1.1's paper was not provided
    t = loaded.query("SELECT * FROM tasks WHERE kind='verify' ORDER BY task_id")[0]
    p = json.loads(t["payload_json"])
    assert not tasks.ingest_result(loaded, t["task_id"], {"verdict": "supports", "confidence": 0.9, "quote": "not in the passage at all"})[0]
    words = p["text"].split()
    assert tasks.ingest_result(loaded, t["task_id"], {"verdict": "supports", "confidence": 0.9, "quote": " ".join(words[:6])})[0]
    v = loaded.query("SELECT * FROM verifications")[0]
    text = loaded.scalar("SELECT text FROM documents WHERE doc_id=?", (v["doc_id"],))
    assert text[v["start"]:v["end"]] == v["quote"]


def test_local_backend_posts_openai_format():
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": '{"claims": []}'}}]}).encode()

    def opener(req, timeout):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        return Resp()

    b = LocalBackend(base_url="http://localhost:9/v1", opener=opener)
    assert b.complete("extract", "SYS", "USER", "qwen", {}) == '{"claims": []}'
    assert seen["url"] == "http://localhost:9/v1/chat/completions"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "SYS"} and seen["body"]["model"] == "qwen"


def test_anthropic_backend_uses_cached_system_prompt():
    calls = {}

    class Block:
        type, text = "text", '{"verdict": "supports"}'

    class Msgs:
        def create(self, **kw):
            calls.update(kw)
            return type("M", (), {"content": [Block()]})()

    client = type("C", (), {"messages": Msgs()})()
    out = AnthropicBackend(client=client).complete("verify", "SYS", "USER", "claude-opus-5-5", {})
    assert out == '{"verdict": "supports"}'
    assert calls["model"] == "claude-opus-5-5" and calls["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_refresh_requeues_after_prompt_change_and_keeps_history(loaded, monkeypatch):
    from enlens_claims import prompts

    tasks.make_split(loaded, model="m")
    good = {"claims": [{"text": "Electrolysis needs large amounts of fresh water.",
                        "quote": "Electrolysis needs large amounts of fresh water", "direction": "negative"}]}
    assert tasks.ingest_result(loaded, "split:6.4", good)[0]
    monkeypatch.setitem(prompts.VERSIONS, "split", "split-test")
    assert tasks.refresh(loaded, "split") == 3
    assert loaded.scalar("SELECT status FROM tasks WHERE task_id='split:6.4'") == "pending"
    assert tasks.ingest_result(loaded, "split:6.4", good)[0]
    assert [r[0] for r in loaded.query("SELECT prompt_version FROM results WHERE task_id='split:6.4' ORDER BY attempt")] == ["split-v2", "split-test"]


def test_per_target_selection_bounds_extraction(loaded):
    screen(loaded)
    all_n = loaded.scalar("SELECT COUNT(*) FROM passages WHERE section='body' AND screened=1")
    picked = tasks.select_per_target(loaded, 1)
    assert 0 < len(picked) <= all_n
    assert tasks.make_extract(loaded, model="m", per_target=1) == len(picked)


def test_check_results_reports_problems_without_storing(loaded):
    _water_task(loaded)
    files = tasks.export(loaded, "extract", batch_size=50)
    tid = json.loads(files[0].read_text().splitlines()[0])["task_id"]
    res = loaded.root / "results" / "extract" / "batch_0001.jsonl"
    bad_claim = {"claim": "Electrolysis raises local water stress.", "activity": "electrolysis", "segment": "production",
                 "targets": [{"target": "6.4", "direction": "negative", "influence": "direct"}], "confidence": 0.9,
                 "evidence": [{"field": "claim", "quote": "a sentence that is nowhere in the passage"}]}
    res.write_text(json.dumps({"task_id": tid, "model": "w", "output": {"claims": [bad_claim]}}) + "\n" + "{oops\n")
    out = tasks.check_results(loaded, [res])
    assert out["lines"] == 2 and out["ok"] == 0 and len(out["problems"]) == 2
    assert any("quote not found" in e for e in out["problems"][0]["errors"])
    assert loaded.scalar("SELECT COUNT(*) FROM results") == 0 and loaded.scalar("SELECT COUNT(*) FROM claims") == 0
    assert loaded.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) != "done"


def _two_vca_claims(ws):
    tasks.make_split(ws, model="m")
    for tid, quote in (("split:6.4", "Hydrogen production can increase water stress in arid regions"),
                       ("split:1.1", "Dependence on imported equipment limits local economic benefits")):
        tasks.ingest_result(ws, tid, {"claims": [{"text": quote + ".", "quote": quote, "direction": "negative"}]})


def test_set_wise_verification_grades_passages(loaded):
    from enlens_claims import analysis

    _two_vca_claims(loaded)
    s = tasks.make_verify_vca(loaded, model="m", k=3)
    assert s == {"tasks": 1, "vca_claims_without_sources": 1}
    t = loaded.query("SELECT * FROM tasks WHERE kind='verify_set'")[0]
    p = json.loads(t["payload_json"])
    assert 1 <= len(p["passages"]) <= 3 and len({x["doc_id"] for x in p["passages"]}) == min(2, len(p["passages"]))
    user = tasks.render(loaded, t)[1]
    assert "P1 |" in user and p["claim"] in user
    first = p["passages"][0]["text"]
    q = " ".join(first.split()[:6])
    # a quote attributed to the wrong passage, or a passage number that was not shown, is rejected
    if len(p["passages"]) > 1 and q not in p["passages"][1]["text"]:
        ok, errs = tasks.ingest_result(loaded, t["task_id"], {"evidence": [{"passage": 2, "verdict": "supports", "confidence": 0.9, "quote": q}]})
        assert not ok and "not found in passage P2" in errs[0]
    ok, errs = tasks.ingest_result(loaded, t["task_id"], {"evidence": [{"passage": 9, "verdict": "supports", "confidence": 0.9, "quote": q}]})
    assert not ok and "no passage P9" in errs[0]
    ok, errs = tasks.ingest_result(loaded, t["task_id"], {"evidence": [{"passage": "P1", "verdict": "partial", "confidence": 0.8, "quote": q}],
                                                          "rationale": "mechanism only"})
    assert ok, errs
    rows = loaded.query("SELECT verdict, quote, start, end, doc_id FROM verifications ORDER BY verdict")
    assert len(rows) == len(p["passages"]) and rows[-1]["verdict"] == "partially_supports"
    assert sum(r["verdict"] == "not_enough_info" for r in rows) == len(p["passages"]) - 1
    text = loaded.scalar("SELECT text FROM documents WHERE doc_id=?", (rows[-1]["doc_id"],))
    assert text[rows[-1]["start"]:rows[-1]["end"]] == rows[-1]["quote"]
    status = {x["target"]: x["status"] for x in analysis.vca_support(loaded)}
    assert status == {"6.4": "partially_supported", "1.1": "source_missing"}


def test_extraction_selection_needs_hydrogen(loaded):
    from enlens_claims.retrieve import H2_RE, screen

    screen(loaded)
    with_h2 = tasks.select_per_target(loaded, 3, only_screened=False)
    anything = tasks.select_per_target(loaded, 3, only_screened=False, hydrogen_only=False)
    rows = {r["passage_id"]: r for r in loaded.query("SELECT p.passage_id, p.text, q.text AS prev FROM passages p LEFT JOIN "
                                                       "passages q ON q.doc_id=p.doc_id AND q.seq=p.seq-1")}
    assert set(with_h2) <= set(anything)
    assert all(H2_RE.search(rows[i]["text"]) or H2_RE.search((rows[i]["prev"] or "")[-500:]) for i in with_h2)


def test_audit_of_vca_checks_is_kept_apart(loaded):
    from enlens_claims import analysis

    _two_vca_claims(loaded)
    tasks.make_verify_vca(loaded, model="m", k=3)
    t = loaded.query("SELECT * FROM tasks WHERE kind='verify_set'")[0]
    q = " ".join(json.loads(t["payload_json"])["passages"][0]["text"].split()[:6])
    assert tasks.ingest_result(loaded, t["task_id"], {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": q}]})[0]
    assert tasks.make_audit_vca(loaded, "second-model", sample=1.0) == 1
    a = loaded.query("SELECT * FROM tasks WHERE task_id LIKE '%:audit:%'")[0]
    assert tasks.ingest_result(loaded, a["task_id"], {"evidence": []}, model="second-model")[0]
    assert {x["target"]: x["status"] for x in analysis.vca_support(loaded)}["6.4"] == "supported"  # audit does not change it
    s = analysis.audit_summary(loaded)["vca_checks"]
    assert s["claims"] == 1 and s["status_agreement"] == 0.0 and s["confusion"] == {"supported -> unsupported": 1}
    sens = analysis.status_sensitivity(loaded, (0.5, 0.95))
    assert sens[0]["supported"] == 1 and sens[1]["unsupported"] == 1


def test_new_documents_reach_claims_already_checked(loaded, tmp_path):
    from enlens_claims import ingest, sources

    _two_vca_claims(loaded)
    assert tasks.make_verify_vca(loaded, model="m", k=3)["tasks"] == 1
    assert tasks.make_verify_vca(loaded, model="m", k=3)["tasks"] == 0      # same passages: not asked again
    extra = tmp_path / "more"
    extra.mkdir()
    (extra / "water.txt").write_text(
        "Hydrogen production can increase water stress in arid regions, because electrolysis withdraws fresh water "
        "that local farms and households also need. Water stress from electrolysis plants is reported in several "
        "arid export regions and can increase quickly as projects scale up. " * 2)
    (extra / "manifest.csv").write_text("file,reference,doi\nwater.txt,Author A. Water footprint of electrolytic hydrogen. 2023,10.9999/papera.2023\n")
    ingest.ingest(loaded, [extra])
    sources.match(loaded)
    assert tasks.make_verify_vca(loaded, model="m", k=3)["tasks"] == 1      # the new document changes the best set
    ids = [r[0] for r in loaded.query("SELECT task_id FROM tasks WHERE kind='verify_set' ORDER BY task_id")]
    assert ids[0] == "verify_set:6.4#1" and ids[1].startswith("verify_set:6.4#1:set:")
