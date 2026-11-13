"""Fewer and smaller AI tasks (roadmap H4, 0.18.1): answers kept by the question asked, and a small codebook once per
batch of the queue."""
import json

from enlens_claims import claimcheck, prompts, taskqueue, tasks

CLAIM = "Green hydrogen production can increase water stress in arid regions."


class _Model:
    name = "ollama"
    base_url = "http://127.0.0.1:9"

    def __init__(self):
        self.calls = 0

    def complete(self, kind, system, user, model, payload):
        self.calls += 1
        ev = [{"passage": i, "verdict": "supports", "confidence": 0.9, "quote": " ".join(p["text"].split()[:6])}
              for i, p in enumerate(payload["passages"], 1)]
        return json.dumps({"evidence": ev})


def _check(ws, queued=False, kind="check"):
    cid = claimcheck.new_claim(ws, CLAIM)
    picked = [dict(r) for r in ws.query("SELECT p.passage_id, p.doc_id, d.title, p.page, p.text FROM passages p "
                                        "JOIN documents d ON d.doc_id=p.doc_id ORDER BY p.passage_id LIMIT 2")]
    with ws.connect() as cx, tasks.queueing(queued):
        tasks._insert_task(cx, f"{kind}:{cid}", kind, "sonnet", claimcheck._payload(ws, cid, CLAIM, None, None, picked))
    return f"{kind}:{cid}"


def test_the_same_question_under_another_id_is_not_asked_again(loaded):
    m = _Model()
    a, b = _check(loaded), _check(loaded)
    assert tasks.run_one(loaded, a, m, "m")[0] and m.calls == 1
    assert tasks.run_one(loaded, b, m, "m")[0] and m.calls == 1  # answered from the kept answer
    assert loaded.scalar("SELECT status FROM tasks WHERE task_id=?", (b,)) == "done"
    assert loaded.scalar("SELECT route FROM results WHERE task_id=?", (b,)).endswith("(kept answer)")
    assert loaded.query("SELECT COUNT(*) FROM verifications WHERE subject_id=?", (b.split(":")[1],))[0][0] == 2
    assert tasks.avoided(loaded) == {"check": 1}
    # another model is another question
    c = _check(loaded)
    assert tasks.run_one(loaded, c, m, "other")[0] and m.calls == 2


def test_a_kept_answer_that_does_not_fit_is_not_used(loaded):
    m = _Model()
    a, b = _check(loaded), _check(loaded)
    tasks.run_one(loaded, a, m, "m")
    bad = json.dumps({"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": "not in it at all"}]})
    with loaded.connect() as cx:
        cx.execute("UPDATE ai_cache SET raw_json=?", (bad,))
    assert tasks.run_one(loaded, b, m, "m")[0] and m.calls == 2
    assert loaded.scalar("SELECT COUNT(*) FROM results WHERE task_id=? AND valid=0", (b,)) == 0  # the try left no trace
    assert tasks.avoided(loaded) == {}


def test_readings_asked_again_on_purpose_are_never_from_the_cache(loaded):
    m = _Model()
    a, b = _check(loaded, kind="second"), _check(loaded, kind="second")
    tasks.run_one(loaded, a, m, "m")
    tasks.run_one(loaded, b, m, "m")
    assert m.calls == 2 and not loaded.scalar("SELECT COUNT(*) FROM ai_cache")
    c, d = _check(loaded), _check(loaded)
    with loaded.connect() as cx:
        cx.execute("UPDATE tasks SET forced_model='m' WHERE task_id IN (?, ?)", (c, d))
    tasks.run_one(loaded, c, m, "m")
    tasks.run_one(loaded, d, m, "m")
    assert m.calls == 4


def test_the_queue_answers_from_kept_answers_before_handing_out(loaded):
    m = _Model()
    a = _check(loaded)
    b = _check(loaded, queued=True)
    model = taskqueue.effective_model(loaded.query("SELECT * FROM tasks WHERE task_id=?", (b,))[0],
                                      taskqueue.router(loaded))
    tasks.run_one(loaded, a, m, model)
    assert taskqueue.next_tasks(loaded, "check")["claim"] is None
    assert loaded.scalar("SELECT status FROM tasks WHERE task_id=?", (b,)) == "done"


def _label(code_sets, fw="sdg"):
    return [{"framework": fw, "framework_title": "SDG", "text": f"Passage {i} on water.", "title": "Doc", "page": 1,
             "candidates": [{"code": c, "description": f"About {c}."} for c in codes]}
            for i, codes in enumerate(code_sets)]


def test_a_small_codebook_goes_once_per_batch():
    shared = prompts.shared_codebook("label", _label([["6.4", "6.1"], ["6.4", "13.2"]]))
    assert shared["codebook"].count("6.4: About 6.4.") == 1 and "13.2: About 13.2." in shared["codebook"]
    assert all("About" not in p for p in shared["prompts"])
    assert "CANDIDATE CODES (described in the batch's codebook): 6.4, 6.1" in shared["prompts"][0]
    assert prompts.shared_codebook("label", _label([["6.4"]])) is None                        # one task
    assert prompts.shared_codebook("check", _label([["6.4"], ["6.1"]])) is None               # not labels
    assert prompts.shared_codebook("label", _label([["6.4"]]) + _label([["6.1"]], "x")) is None  # two codebooks
    many = [[f"{g}.{t}" for t in range(1, 25)] for g in (1, 2)]
    assert prompts.shared_codebook("label", _label(many)) is None                             # 48 codes
    # without it, the prompt is the one of before, word for word
    p = _label([["6.4"]])[0]
    assert prompts.user_prompt("label", p) == prompts.user_prompt("label", p, codes_once=False)
    assert "CANDIDATE CODES:\n6.4: About 6.4." in prompts.user_prompt("label", p)
