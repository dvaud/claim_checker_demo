"""Leftovers of the deep dive that change no behaviour: the file queue's export loads only what it writes, and the
other refactors (one graded row, one streaming helper, one Ollama probe, one spacing pass) give what they gave."""
from __future__ import annotations

import json
import time

import pytest

from enlens_claims import prompts, tasks
from enlens_claims import home as core


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    return core.create_project("Small leftovers")


def _expand(cx, tid, status="pending", access_="cloud", attempts=0):
    cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, created_at, "
               "queued, access) VALUES (?,?,?,?,?,?,?,?,0,?)",
               (tid, "expand", "sonnet", "old-version", json.dumps({"claim": f"claim of {tid}"}), status, attempts,
                "2026-01-01T00:00:00", access_))


# ---------------------------------------------------------------------------------------------
# 1: tasks.export
# ---------------------------------------------------------------------------------------------
def _written(files):
    return [json.loads(line) for f in files for line in f.read_text(encoding="utf-8").splitlines()]


def test_export_writes_the_waiting_cloud_tasks_in_order_and_marks_them(ws):
    with ws.connect() as cx:
        for i in range(7):
            _expand(cx, f"t{i}", status="retry" if i == 2 else "pending")
        _expand(cx, "t7", access_="local")
        _expand(cx, "t8", access_="none")
        _expand(cx, "t9", status="done")
        _expand(cx, "ta", access_=None)  # an unset setting reads as cloud
        _expand(cx, "tb", access_="")
    files = tasks.export(ws, "expand", batch_size=3)
    assert [f.name for f in files] == ["batch_0001.jsonl", "batch_0002.jsonl", "batch_0003.jsonl"]
    got = _written(files)
    assert [r["task_id"] for r in got] == ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "ta", "tb"]
    assert got[0]["user"] == prompts.user_prompt("expand", {"claim": "claim of t0"})
    marked = {r["task_id"]: (r["status"], r["prompt_version"]) for r in ws.query("SELECT * FROM tasks")}
    new = prompts.VERSIONS.get("expand") or "old-version"
    assert marked["t0"] == ("exported", new) and marked["tb"] == ("exported", new)
    assert marked["t7"] == ("pending", "old-version") and marked["t8"] == ("pending", "old-version")
    assert marked["t9"] == ("done", "old-version")
    # a second export writes nothing new, and numbers after the highest batch
    assert tasks.export(ws, "expand") == []


def test_export_limit_and_a_retry_with_its_problems(ws):
    with ws.connect() as cx:
        for i in range(5):
            _expand(cx, f"t{i}")
        cx.execute("UPDATE tasks SET status='retry', attempts=1 WHERE task_id='t1'")
        cx.execute("INSERT INTO results(task_id, attempt, kind, model, prompt_version, raw_json, valid, errors_json, "
                   "received_at) VALUES ('t1', 1, 'expand', 'm', '1', '{}', 0, ?, 'now')", (json.dumps(["too short"]),))
    files = tasks.export(ws, "expand", batch_size=2, limit=3)
    got = _written(files)
    assert [r["task_id"] for r in got] == ["t0", "t1", "t2"]
    assert "YOUR PREVIOUS ANSWER HAD THESE PROBLEMS" in got[1]["user"] and "too short" in got[1]["user"]
    assert "PROBLEMS" not in got[0]["user"]
    assert {r["task_id"] for r in ws.query("SELECT task_id FROM tasks WHERE status='exported'")} == {"t0", "t1", "t2"}
    more = tasks.export(ws, "expand", batch_size=2)
    assert [f.name for f in more] == ["batch_0003.jsonl"] and [r["task_id"] for r in _written(more)] == ["t3", "t4"]


def test_export_of_many_waiting_tasks_reads_payloads_a_batch_at_a_time(ws, monkeypatch):
    n = 3000
    with ws.connect() as cx:
        cx.executemany("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, "
                       "created_at, queued, access) VALUES (?,?,?,?,?,?,0,?,0,?)",
                       [(f"t{i:05d}", "expand", "sonnet", "1", json.dumps({"claim": "x" * 50}), "pending",
                         "2026-01-01T00:00:00", "cloud") for i in range(n)])
    widest = {"rows": 0}
    real = type(ws).query

    def watching(self, sql, args=()):
        rows = real(self, sql, args)
        if rows and "payload_json" in rows[0].keys():
            widest["rows"] = max(widest["rows"], len(rows))
        return rows

    monkeypatch.setattr(type(ws), "query", watching)
    started = time.time()
    files = tasks.export(ws, "expand", batch_size=100)
    print(f"export of {n} waiting tasks: {time.time() - started:.2f} s")
    assert len(_written(files)) == n and len(files) == 30
    assert widest["rows"] <= 500  # never every payload at once


# ---------------------------------------------------------------------------------------------
# 2 (C13): the graded row and the history entry of an excerpt, stored by three paths
# ---------------------------------------------------------------------------------------------
def _graded_fixture(loaded):
    p = loaded.query("SELECT * FROM passages WHERE LENGTH(text) > 120 ORDER BY passage_id LIMIT 1")[0]
    line = max(p["text"].splitlines(), key=len)  # a quote within one line, so it is found as it stands
    quote = " ".join(line.split()[2:8])
    assert quote in p["text"]
    payload = {"subject_kind": "claim", "subject_id": "c1", "terms": [],
               "passages": [{"passage_id": p["passage_id"], "doc_id": p["doc_id"], "text": p["text"],
                             "page": p["page"], "n": 1},
                            {"passage_id": "gone-passage", "doc_id": "gone-doc", "text": "Nothing else here at all.",
                             "page": 4, "n": 2}]}
    return p, quote, payload


def _answer(verdict, quote, note=None, n=1, conf=0.7):
    return {"evidence": [{"passage": n, "verdict": verdict, "confidence": conf, "quote": quote,
                          **({"scope_note": note} if note else {})}], "rationale": "r"}


def _task(status="pending"):
    return {"task_id": "check:c1", "status": status, "prompt_version": "pv1"}


def test_a_check_stores_a_graded_excerpt_and_a_second_reading_keeps_the_history(loaded):
    p, quote, payload = _graded_fixture(loaded)
    start = p["text"].find(quote)
    ws = loaded
    with ws.connect() as cx:
        assert tasks._store_verify_set(cx, _task(), payload, _answer("supports", quote, "other group"), "m1", schema=tasks.CheckOut)[0]
    row = ws.query("SELECT * FROM verifications WHERE passage_id=?", (p["passage_id"],))[0]
    assert (row["verdict"], row["confidence"], row["quote"]) == ("partially_supports", 0.7, quote)  # capped by the note
    assert (row["start"], row["end"], row["scope_note"], row["page"]) == (
        p["start"] + start, p["start"] + start + len(quote), "other group", p["page"])
    gone = ws.query("SELECT * FROM verifications WHERE passage_id='gone-passage'")[0]  # not graded
    assert (gone["verdict"], gone["confidence"], gone["quote"], gone["start"], gone["end"], gone["page"]) == (
        "not_enough_info", None, None, None, None, 4)
    ws.query("SELECT 1")
    with ws.connect() as cx:
        cx.execute("UPDATE verifications SET user_verdict='refutes', user_note='mine' WHERE ver_id=?", (row["ver_id"],))
        assert tasks._store_verify_set(cx, _task("done"), payload, _answer("refutes", quote), "m2", schema=tasks.CheckOut)[0]
    again = ws.query("SELECT * FROM verifications WHERE ver_id=?", (row["ver_id"],))[0]
    assert (again["verdict"], again["user_verdict"], again["user_note"], again["scope_note"]) == (
        "refutes", "refutes", "mine", None)
    hist = json.loads(again["ai_history_json"])
    assert len(hist) == 1 and hist[0]["why"] == "stepped up" and hist[0]["at"] is None and hist[0]["replaced_at"]
    assert {k: hist[0][k] for k in ("verdict", "confidence", "quote", "scope_note", "model", "prompt_version")} == {
        "verdict": "partially_supports", "confidence": 0.7, "quote": quote, "scope_note": "other group",
        "model": "m1", "prompt_version": "pv1"}
    assert list(hist[0]) == ["verdict", "confidence", "quote", "scope_note", "model", "prompt_version", "at",
                             "replaced_at", "why"]


def test_an_excerpt_read_again_replaces_the_grade_and_keeps_the_earlier_one(loaded):
    p, quote, payload = _graded_fixture(loaded)
    payload["passages"] = payload["passages"][:1]
    payload["previous_at"] = "2026-01-02T03:04:05"
    start = p["start"] + p["text"].find(quote)
    ws = loaded
    with ws.connect() as cx:  # nothing graded before: a row is inserted
        assert tasks._store_reread(cx, _task(), payload, _answer("supports", quote, "other setting"), "m1")[0]
    row = ws.query("SELECT * FROM verifications WHERE passage_id=?", (p["passage_id"],))[0]
    assert (row["verdict"], row["quote"], row["start"], row["end"], row["scope_note"], row["ai_history_json"]) == (
        "partially_supports", quote, start, start + len(quote), "other setting", "[]")
    with ws.connect() as cx:  # graded before: replaced, the earlier grade joins the history
        assert tasks._store_reread(cx, _task(), payload, _answer("refutes", quote), "m2")[0]
        assert tasks._store_reread(cx, _task(), payload, {"evidence": []}, "m3")[0]  # now not graded
    row = ws.query("SELECT * FROM verifications WHERE passage_id=?", (p["passage_id"],))[0]
    assert (row["verdict"], row["confidence"], row["quote"], row["start"], row["end"], row["scope_note"]) == (
        "not_enough_info", None, None, None, None, None)
    hist = json.loads(row["ai_history_json"])
    assert [h["verdict"] for h in hist] == ["partially_supports", "refutes"]
    assert hist[0]["at"] == "2026-01-02T03:04:05" and "why" not in hist[0]
    assert list(hist[0]) == ["verdict", "confidence", "quote", "scope_note", "model", "prompt_version", "at",
                             "replaced_at"]
    assert (hist[0]["model"], hist[1]["model"]) == ("m1", "m2")


def test_a_second_opinion_is_kept_apart(loaded):
    p, quote, payload = _graded_fixture(loaded)
    payload["second_model"] = "second-m"
    start = p["start"] + p["text"].find(quote)
    with loaded.connect() as cx:
        assert tasks._store_second(cx, _task(), payload, _answer("supports", quote, "other group"), "x")[0]
    got = {r["passage_id"]: dict(r) for r in loaded.query("SELECT * FROM second_opinions")}
    a, b = got[p["passage_id"]], got["gone-passage"]
    assert (a["model"], a["verdict"], a["confidence"], a["quote"], a["start"], a["end"], a["scope_note"]) == (
        "second-m", "partially_supports", 0.7, quote, start, start + len(quote), "other group")
    assert (b["verdict"], b["confidence"], b["quote"], b["start"], b["end"], b["scope_note"]) == (
        "not_enough_info", None, None, None, None, None)
    assert loaded.scalar("SELECT COUNT(*) FROM verifications") == 0


# ---------------------------------------------------------------------------------------------
# 3 (C11): the streaming plumbing of OllamaBackend._stream and LocalBackend._run
# ---------------------------------------------------------------------------------------------
class _Resp:
    """A streamed response: yields its lines (waiting `gap` seconds before each), and notes when it was closed."""

    def __init__(self, lines, gap=0.0, whole=None):
        self.lines, self.gap, self.closed, self._whole = list(lines), gap, False, whole

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True

    def __iter__(self):
        for line in self.lines:
            if self.closed:
                return
            if self.gap:
                time.sleep(self.gap)
            yield line

    def read(self):
        return self._whole

    def close(self):
        self.closed = True


def _info():
    return {"task": "check", "model": "m", "phase": "waiting", "thinking_tokens": 0, "answer_tokens": 0,
            "first_token_after": None, "rate": None, "tail": "", "seconds": 0.0}


def _ollama(lines, **kw):
    from enlens_claims.llm import OllamaBackend

    resp = _Resp(lines, kw.pop("gap", 0.0))
    be = OllamaBackend(base_url="http://127.0.0.1:9", opener=lambda req, timeout=None: resp, **kw)
    return be, resp


def _chunk(**msg):
    return json.dumps({"message": msg, "done": False}).encode()


def _ollama_stream(be, budget=0):
    info = _info()
    seen: list[dict] = []
    be.progress = seen.append
    return be._stream({"model": "m"}, "m", info, time.time(), budget), info, seen


def test_ollama_stream_collects_the_answer_and_skips_lines_that_do_not_parse():
    lines = [_chunk(thinking="hm"), b"", b"not json", b"[1, 2]", _chunk(content='{"a"'), _chunk(content=": 1}"),
             json.dumps({"message": {}, "done": True, "eval_count": 7}).encode(), _chunk(content="never read")]
    be, resp = _ollama(lines)
    (content, final), info, seen = _ollama_stream(be)
    assert "".join(content) == '{"a": 1}' and final["eval_count"] == 7
    assert (info["thinking_tokens"], info["answer_tokens"], info["phase"]) == (1, 2, "writing")
    assert info["first_token_after"] is not None and info["tail"] == '{"a": 1}'
    assert resp.closed and seen  # the response is closed at the end; progress was told


def test_ollama_stream_reports_an_error_chunk_a_budget_and_blank_space():
    from enlens_claims.llm import AnswerError, BackendError, _BudgetReached

    be, resp = _ollama([_chunk(content="x"), json.dumps({"error": "model crashed"}).encode()])
    with pytest.raises(BackendError, match="Ollama stopped with an error: model crashed"):
        _ollama_stream(be)
    assert resp.closed
    be, _ = _ollama([_chunk(thinking=f"t{i} ") for i in range(10)])
    with pytest.raises(_BudgetReached) as got:
        _ollama_stream(be, budget=4)
    assert got.value.thinking == "t0 t1 t2 t3 "
    be, resp = _ollama([_chunk(content=" ")] * 60)
    with pytest.raises(AnswerError, match="stuck writing blank space"):
        _ollama_stream(be)
    assert resp.closed


def test_ollama_stream_stops_stalls_and_times_out_in_its_own_words():
    from enlens_claims.llm import BackendError

    be, resp = _ollama([_chunk(content="x")] * 5, gap=0.3)
    be.should_stop = lambda: True
    with pytest.raises(BackendError, match="^Stopped.$"):
        _ollama_stream(be)
    time.sleep(0.5)
    assert resp.closed
    be, resp = _ollama([_chunk(content="x")], gap=5, stall_timeout=1)
    with pytest.raises(BackendError, match="sent nothing for 1 seconds before starting its answer"):
        _ollama_stream(be)
    assert resp.closed
    be, resp = _ollama([_chunk(content="x")] * 10, gap=0.4, timeout=1)
    with pytest.raises(BackendError, match="was still answering after 1 seconds"):
        _ollama_stream(be)
    assert resp.closed


def test_ollama_stream_names_http_and_connection_errors():
    from urllib.error import HTTPError, URLError

    from enlens_claims.llm import BackendError, OllamaBackend

    def failing(exc):
        def opener(req, timeout=None):
            raise exc
        return OllamaBackend(base_url="http://127.0.0.1:9", opener=opener)

    for exc, said in ((HTTPError("u", 404, "Not Found", {}, None), "Ollama has no model 'm'"),
                      (HTTPError("u", 500, "Boom", {}, None), "Ollama returned an error (500)"),
                      (URLError("refused"), "Could not reach Ollama at http://127.0.0.1:9"),
                      (TimeoutError("timed out"), "sent nothing for 600 seconds before starting its answer")):
        with pytest.raises(BackendError, match=said.replace("(", r"\(").replace(")", r"\)")):
            _ollama_stream(failing(exc))


def _local(lines=(), whole=None, **kw):
    from enlens_claims.llm import LocalBackend

    resp = _Resp(lines, kw.pop("gap", 0.0), whole)
    if whole is not None:
        resp._fake_whole = True
    be = LocalBackend(base_url="http://127.0.0.1:9/v1", opener=lambda req, timeout=None: resp, **kw)
    seen: list[dict] = []
    be.progress = seen.append
    return be, resp, seen


def _sse(**delta):
    return b"data: " + json.dumps({"choices": [{"delta": delta}]}).encode() + b"\n"


def _run(be, cap=500):
    return be._run("check", "m", {"model": "m"}, 10, cap)


def test_local_run_streams_the_answer_until_done():
    done = b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}).encode() + b"\n"
    be, resp, seen = _local([_sse(reasoning_content="hm"), b"data: {broken\n", b"\n", _sse(content='{"a"'),
                             _sse(content=": 1}"), done, b"data: [DONE]\n", _sse(content="never read")])
    assert _run(be) == '{"a": 1}'
    assert resp.closed and seen[-1]["phase"] == "done" and seen[-1]["stats"]["output_tokens"] == 2
    assert (seen[-1]["thinking_tokens"], seen[-1]["thinks"]) == (1, True)


def test_local_run_reads_a_server_that_ignores_stream():
    body = json.dumps({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}).encode()
    be, resp, _ = _local(whole=body)
    assert _run(be) == "{}" and resp.closed
    be, _, _ = _local([body])  # the same body delivered as a line that is not "data:"
    assert _run(be) == "{}"
    from enlens_claims.llm import BackendError

    for bad, said in ((b"<html>", "not JSON"),
                      (json.dumps({"error": {"message": "no model"}}).encode(), "returned an error: no model")):
        be, _, _ = _local(whole=bad)
        with pytest.raises(BackendError, match=said):
            _run(be)


def test_local_run_rejects_a_cut_answer_blank_space_and_an_error_chunk():
    from enlens_claims.llm import AnswerError, BackendError

    be, _, _ = _local([_sse(content="{"), b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "length"}]}).encode() + b"\n"])
    with pytest.raises(AnswerError, match="cut off at 500 tokens"):
        _run(be)
    be, resp, _ = _local([_sse(content=" ")] * 60)
    with pytest.raises(AnswerError, match="stuck writing blank space"):
        _run(be)
    assert resp.closed
    be, _, _ = _local([b"data: " + json.dumps({"error": {"message": "out of memory"}}).encode() + b"\n"])
    with pytest.raises(BackendError, match="The local server stopped with an error: out of memory"):
        _run(be)


def test_local_run_stops_stalls_and_times_out_in_its_own_words():
    from enlens_claims.llm import BackendError

    be, resp, _ = _local([_sse(content="x")] * 5, gap=0.3)
    be.should_stop = lambda: True
    with pytest.raises(BackendError, match="^Stopped.$"):
        _run(be)
    time.sleep(0.5)
    assert resp.closed
    be, resp, _ = _local([_sse(content="x")], gap=5, stall_timeout=1)
    with pytest.raises(BackendError, match="^m sent nothing for 1 seconds.$"):
        _run(be)
    assert resp.closed
    be, resp, _ = _local([_sse(content="x")] * 10, gap=3, timeout=1)  # checked while waiting, as before
    with pytest.raises(BackendError, match="was still answering after 1 seconds"):
        _run(be)
    assert resp.closed


# ---------------------------------------------------------------------------------------------
# 4 (P13): one probe of "does an Ollama answer here"
# ---------------------------------------------------------------------------------------------
@pytest.fixture
def version_server():
    import threading
    from http.server import BaseHTTPRequestHandler

    from enlens_claims.gui.server import QuickServer

    state = {"code": 200, "body": b'{"version": "0.40.1"}', "wait": 0.0, "paths": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            state["paths"].append(self.path)
            if state["wait"]:
                time.sleep(state["wait"])
            self.send_response(state["code"])
            self.send_header("Content-Length", str(len(state["body"])))
            self.end_headers()
            try:
                self.wfile.write(state["body"])
            except OSError:
                pass

    srv = QuickServer(("127.0.0.1", 0), H)   # (no 35-second wait for this computer's name on a Mac)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{srv.server_address[1]}"
    yield state
    srv.shutdown()
    srv.server_close()


def test_the_setup_probe_says_whether_an_ollama_answers(version_server):
    from enlens_claims import ollama_setup

    assert ollama_setup.answers(version_server["url"]) is True
    assert ollama_setup.answers(version_server["url"] + "/") is True
    assert version_server["paths"][-1] == "/api/version"
    version_server["body"] = b"not json at all"  # any 200 counts, as before
    assert ollama_setup.answers(version_server["url"]) is True
    version_server["code"] = 500
    assert ollama_setup.answers(version_server["url"]) is False
    assert ollama_setup.answers("http://127.0.0.1:9") is False
    assert ollama_setup.answers("not a url") is False


def test_the_setup_probe_waits_at_most_a_second_and_a_half(version_server, monkeypatch):
    import urllib.request

    from enlens_claims import ollama_setup

    seen = []
    real = urllib.request.urlopen
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: seen.append(timeout) or real(req, timeout=timeout))
    ollama_setup.answers(version_server["url"])
    assert seen == [1.5]
    version_server["wait"] = 2.5
    started = time.time()
    assert ollama_setup.answers(version_server["url"]) is False
    assert time.time() - started < 2.4


def test_detecting_local_servers_finds_an_ollama_with_its_version_and_keeps_its_time_limit(version_server, monkeypatch):
    import urllib.request

    from enlens_claims import llm

    seen = []
    real = urllib.request.urlopen
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: seen.append(
        (getattr(req, "full_url", req), timeout)) or real(req, timeout=timeout))
    monkeypatch.setattr(llm, "OPENAI_PORTS", ())
    version_server["body"] = b'{"version": "0.40.1"}'
    llm._DETECTED.clear()
    got = llm.detect_local(version_server["url"], timeout=0.6, cache_seconds=0)
    assert [(g["kind"], g["version"], g["url"]) for g in got] == [("ollama", "0.40.1", version_server["url"])]
    assert (version_server["url"] + "/api/version", 0.6) in seen
    llm._DETECTED.clear()
    assert llm.detect_local("http://127.0.0.1:9", timeout=0.6, cache_seconds=0) == []


# ---------------------------------------------------------------------------------------------
# 5 (R20): the "spacing" pass of finding a quote. The code before 0.17.2 is kept below as the oracle: textutil's
# find_quote and reread's _Finder must give what it gave, for a table of hand-picked cases and for many quotes cut
# at random from a text that PDF extraction has damaged.
# ---------------------------------------------------------------------------------------------
def _oracle_find_quote(haystack, quote, whole_words=True):
    from enlens_claims.textutil import _normalise_spans, _word_edge, normalise

    q = (quote or "").strip()
    if len(normalise(q)) < 3:
        return None
    nh, hstart, hend = _normalise_spans(haystack)
    nq = _normalise_spans(q)[0]
    pos = nh.find(nq) if nq else -1
    while pos >= 0:
        end = pos + len(nq)
        if not whole_words or (_word_edge(haystack, nh, hstart, pos, True) and _word_edge(haystack, nh, hstart, end)):
            return hstart[pos], hend[end - 1], "exact"
        pos = nh.find(nq, pos + 1)
    chars, starts, ends, gap = [], [], [], []
    prev = False
    for c, a, b in zip(nh, hstart, hend):
        if c == " ":
            prev = True
            continue
        chars.append(c)
        starts.append(a)
        ends.append(b)
        gap.append(prev)
        prev = False
    sh = "".join(chars)
    qc, qgap = [], []
    prev = False
    for c in nq:
        if c == " ":
            prev = True
            continue
        qc.append(c)
        qgap.append(prev)
        prev = False
    sq = "".join(qc)
    if not sq:
        return None

    def edge(i, start=False):
        return i <= 0 or i >= len(sh) or gap[i] or _word_edge(haystack, sh, starts, i, start)

    pos = sh.find(sq)
    while pos >= 0:
        end = pos + len(sq)
        if not whole_words or (edge(pos, True) and edge(end)
                               and all(edge(pos + k) for k in range(1, len(sq)) if qgap[k])):
            return starts[pos], ends[end - 1], "spacing"
        pos = sh.find(sq, pos + 1)
    return None


def _oracle_all(text, quote):
    """reread._Finder.all as it was."""
    from enlens_claims.textutil import _normalise_spans, _word_edge, normalise

    q = (quote or "").strip()
    out = []
    nh, hs, he = _normalise_spans(text)
    nq = _normalise_spans(q)[0]
    if len(nq) >= 3:
        pos = nh.find(nq)
        while pos >= 0:
            end = pos + len(nq)
            if _word_edge(text, nh, hs, pos, True) and _word_edge(text, nh, hs, end):
                out.append((hs[pos], he[end - 1]))
            pos = nh.find(nq, pos + 1)
        for drop in (" ", " -|"):
            if out:
                break
            chars, starts, ends, gap = [], [], [], []
            prev = False
            for c, a, b in zip(nh, hs, he):
                if c in drop:
                    prev = True
                    continue
                chars.append(c)
                starts.append(a)
                ends.append(b)
                gap.append(prev)
                prev = False
            sh = "".join(chars)
            qc, qgap, prev = [], [], False
            for c in nq:
                if c in drop:
                    prev = True
                    continue
                qc.append(c)
                qgap.append(prev)
                prev = False
            sq = "".join(qc)
            if len(sq) < 3:
                continue

            def edge(i, start=False, sh=sh, gap=gap, starts=starts):
                return i <= 0 or i >= len(sh) or gap[i] or _word_edge(text, sh, starts, i, start)

            out = []
            pos = sh.find(sq)
            while pos >= 0:
                end = pos + len(sq)
                if edge(pos, True) and edge(end) and all(edge(pos + k) for k in range(1, len(sq)) if qgap[k]):
                    out.append((starts[pos], ends[end - 1]))
                pos = sh.find(sq, pos + 1)
    return out


DAMAGED = ("Electrolysis needs large amounts of fresh water. The ﬁrst plants wi ll start in 2030.106 But the long-term\n"
           "costs of addition al capacity are high, and the nowhere-to-go brine is a problem. A re-use rule | applies "
           "to table | cells. Hydro gen use rose by 2,500 tonnes; the 5 percent share of 2.5 percent growth held.\n"
           "projects44 shifted; “smart quotes” and the  extra   spaces   stay. The word another is not not.")
QUOTES = [
    "fresh water", "FRESH   WATER", "fresh  wa ter", "freshwater", "fresh waterfall", "ﬁrst plants", "first plants",
    "first plants will start", "wi ll start in 2030", "will start in 2030", "start in 2030.106 But",
    "long-term costs", "longterm costs", "long term costs", "addition al capacity", "additional capacity",
    "additionalcapacity", "now here", "nowhere", "nowhere-to-go", "now here to go", "re-use rule", "reuse rule",
    "re use rule", "rule applies to table cells", "rule | applies", "table cells", "Hydrogen use rose", "Hydro gen use",
    "rose by 2,500 tonnes", "rose by 2", "5 percent", "2.5 percent growth", "percent share of 2.5", "projects44",
    "projects 44", "smart quotes", "\"smart quotes\"", "extra spaces stay", "extraspaces", "not", "another",
    "is not not", "legal", "it", "no", "", "   ", "not in the text at all", "a b c", "w i l l", "the  first",
    "Electrolysis needs large amounts of fresh water. The first plants wi ll start",
]


def _same_as_before(text, quote):
    from enlens_claims import textutil
    from enlens_claims.reread import _Finder

    for whole in (True, False):
        assert textutil.find_quote(text, quote, whole_words=whole) == _oracle_find_quote(text, quote, whole), (quote, whole)
    assert _Finder(text).all(quote) == _oracle_all(text, quote), quote


def test_quotes_are_found_as_before_in_a_table_of_cases():
    for text in (DAMAGED, DAMAGED.replace("\n", " "), "", "x", DAMAGED.upper(), DAMAGED[40:120]):
        for quote in QUOTES:
            _same_as_before(text, quote)


def test_the_spacing_pass_still_finds_what_it_should():
    from enlens_claims import textutil
    from enlens_claims.reread import _Finder

    t = DAMAGED
    hit = textutil.find_quote(t, "will start in 2030")
    assert hit[2] == "spacing" and t[hit[0]:hit[1]] == "wi ll start in 2030"
    hit = textutil.find_quote(t, "additional capacity")
    assert hit[2] == "spacing" and t[hit[0]:hit[1]] == "addition al capacity"
    assert textutil.find_quote(t, "nowhere")[2] == "exact"
    assert textutil.find_quote(t, "now here to go") is None  # may not join two words the quote keeps apart
    assert textutil.find_quote(t, "not in the text at all") is None and textutil.find_quote(t, "it") is None
    assert textutil.find_quote(t, "ﬁrst plants")[2] == "exact"  # a ligature is normalised on both sides
    assert [t[a:b] for a, b in _Finder(t).all("longterm costs")] == ["long-term\ncosts"]  # hyphens, last
    assert [t[a:b] for a, b in _Finder(t).all("reuse rule applies")] == ["re-use rule | applies"]


def test_quotes_cut_at_random_from_damaged_text_are_found_as_before():
    import random

    from enlens_claims import textutil  # noqa: F401

    rng = random.Random(20261112)
    text = DAMAGED
    for _ in range(600):
        a = rng.randrange(0, len(text) - 6)
        piece = text[a:a + rng.randrange(4, 70)]
        mode = rng.randrange(4)
        if mode == 1:
            piece = piece.replace(" ", "")
        elif mode == 2:
            piece = piece.replace("-", " ").replace("|", "")
        elif mode == 3 and len(piece) > 8:
            k = rng.randrange(2, len(piece) - 2)
            piece = piece[:k] + " " + piece[k:]
        _same_as_before(text, piece)


# ---------------------------------------------------------------------------------------------
# 6 (H11): a quote stored with an answer has a length cap
# ---------------------------------------------------------------------------------------------
LONG = " ".join(f"Sentence number {i} says something about water use." for i in range(40))  # about 2,000 characters


def _cut(n):  # whole sentences, at most n characters
    return LONG[:LONG.rfind(".", 0, n) + 1]


def _check_task(cx, tid="check:c9"):
    payload = {"subject_kind": "claim", "subject_id": "c9", "terms": [], "claim": "Water use is high.",
               "passages": [{"passage_id": "p-long", "doc_id": "d-long", "text": LONG, "page": 1, "n": 1}]}
    cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, created_at, "
               "queued, access) VALUES (?,?,?,?,?,?,0,?,0,?)",
               (tid, "check", "sonnet", "pv", json.dumps(payload), "pending", "2026-01-01T00:00:00", "cloud"))
    return tid


def _grade(quote):
    return {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": quote}], "rationale": "r"}


def test_the_cap_is_above_any_honest_quote_and_below_a_page():
    from enlens_claims import textutil

    assert textutil.MAX_QUOTE_CHARS == 600


def test_an_answer_with_a_very_long_quote_is_rejected_like_a_quote_not_found(ws):
    with ws.connect() as cx:
        tid = _check_task(cx)
    over = _cut(900)
    assert tasks.find_quote(LONG, over)  # it is in the passage: only its length is wrong
    ok, errors = tasks.ingest_result(ws, tid, _grade(over))
    assert not ok and len(errors) == 1
    assert "too long" in errors[0] and f"{len(over)} characters" in errors[0] and "600" in errors[0]
    assert ws.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) == "retry"
    assert ws.scalar("SELECT COUNT(*) FROM verifications") == 0  # nothing stored
    assert "too long" in ws.scalar("SELECT errors_json FROM results WHERE task_id=?", (tid,))
    # the helper is told what to fix when it is asked again, as for a quote that was not found
    assert "too long" in tasks.render(ws, ws.query("SELECT * FROM tasks WHERE task_id=?", (tid,))[0])[1]
    short = _cut(590)
    ok, errors = tasks.ingest_result(ws, tid, _grade(short))
    assert ok and not errors and 500 < len(short) <= 590
    assert ws.scalar("SELECT LENGTH(quote) FROM verifications") == len(short)


def test_the_cap_counts_the_quote_as_a_reader_sees_it_and_holds_for_every_kind_of_quote(ws):
    spaced = _cut(300).replace(" ", "     ")  # the extra whitespace is not part of a quote's length
    with ws.connect() as cx:
        tid = _check_task(cx)
    assert tasks.ingest_result(ws, tid, _grade(spaced))[0]
    from enlens_claims import taskkinds

    got = taskkinds.long_quote_problems({"claims": [{"evidence": [{"quote": "x" * 601}]}], "quote_a": "y" * 700,
                                        "quote_b": "ok", "name_quote": {"passage": 1, "quote": "z" * 601},
                                        "reason": "r" * 900})
    assert len(got) == 3 and all("too long" in g for g in got)
    assert taskkinds.long_quote_problems({"quote": "x" * 600}) == []
    assert taskkinds.long_quote_problems({"quote": None, "other": 5}) == []
    assert taskkinds.long_quote_problems("not a dict") == []


def test_an_add_ons_quote_fields_are_capped_too(ws):
    from enlens_claims import taskkinds

    kind = taskkinds.TaskKind(name="addon-x", quote_fields=("cite",), quote_from=lambda p: "word " * 400,
                              store=lambda cx, t, p, o, m: (True, []))
    assert taskkinds.long_quote_problems({"cite": "q" * 700}, kind.quote_fields) and not taskkinds.long_quote_problems(
        {"cite": "q" * 500}, kind.quote_fields)


# ---------------------------------------------------------------------------------------------
# 7 (E18): notes after a re-read, and a listing that writes
# ---------------------------------------------------------------------------------------------
@pytest.fixture
def demo(tmp_path):
    from pathlib import Path

    from enlens_claims import ingest
    from enlens_claims.store import Workspace

    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"])
    return ws


class _Writes:
    """The statements that change the database while it is in use (the project's connection is traced)."""

    def __init__(self, ws):
        self.cx, self.seen = ws._conn(), []

    def __enter__(self):
        self.cx.set_trace_callback(lambda sql: self.seen.append(sql) if sql.lstrip()[:6].upper() in (
            "UPDATE", "INSERT", "DELETE") else None)
        return self.seen

    def __exit__(self, *a):
        self.cx.set_trace_callback(None)


def _one_note(ws, words="commuting emissions"):
    from enlens_claims import notes

    for doc, text in ws.query("SELECT doc_id, text FROM documents ORDER BY doc_id"):
        i = text.find(words)
        if i >= 0:
            return doc, text, i, notes.add(ws, doc, i, i + len(words), None, "mine")
    raise AssertionError(words)


def test_listing_notes_whose_words_differ_only_in_typography_writes_nothing(demo):
    from enlens_claims import notes

    words = "commuting emissions"
    doc, text, i, n = _one_note(demo, words)
    with demo.connect() as cx:  # a new reading wrote the same words with other capitals
        cx.execute("UPDATE documents SET text=? WHERE doc_id=?", (text.replace(words, "Commuting Emissions", 1), doc))
    with _Writes(demo) as wrote:
        for _ in range(3):
            got = notes.for_document(demo, doc)
            assert [(g["start"], g["end"], g["lost"]) for g in got] == [(i, i + len(words), False)]
            assert notes.search(demo)["notes"][0]["quote"] == words
            assert notes.get(demo, n["note_id"])["quote"] == words
    assert wrote == []  # nothing was written by listing them


def test_a_note_whose_words_moved_is_written_down_once(demo):
    from enlens_claims import notes

    words = "commuting emissions"
    doc, text, i, n = _one_note(demo, words)
    with demo.connect() as cx:
        cx.execute("UPDATE documents SET text=? WHERE doc_id=?", ("A new first line.\n\n" + text, doc))
    with _Writes(demo) as wrote:
        got = notes.get(demo, n["note_id"])
    assert (got["start"], got["end"]) == (i + 19, i + 19 + len(words))
    assert demo.scalar("SELECT start FROM notes WHERE note_id=?", (n["note_id"],)) == i + 19
    assert len(wrote) == 1 and wrote[0].lstrip().upper().startswith("UPDATE NOTES")  # the new place is written down...
    with _Writes(demo) as wrote:
        notes.for_document(demo, doc)
    assert wrote == []  # ...once


def test_a_note_followed_to_its_new_place_after_a_re_read_gets_that_places_page(demo):
    from enlens_claims import notes

    words = "commuting emissions"
    doc, text, i, n = _one_note(demo, words)
    spans = [(0, 50), (50, len(text) // 2), (len(text) // 2, len(text) + 100)]  # three pages of the new reading
    new_text = "A new first line.\n\n" + text
    spans = [(0, 30), (30, len(new_text) // 2), (len(new_text) // 2, len(new_text))]
    with demo.connect() as cx:
        moved = notes.move(cx, doc, new_text, spans)
    assert moved == {"moved": 1, "lost": 0}
    row = demo.query("SELECT start, end, page, quote FROM notes WHERE note_id=?", (n["note_id"],))[0]
    place = i + 19
    assert (row["start"], row["end"], row["quote"]) == (place, place + len(words), words)
    want = 1 if place < 30 else (2 if place < len(new_text) // 2 else 3)
    assert row["page"] == want
    with demo.connect() as cx:  # a reading with no pages leaves the note with no page
        notes.move(cx, doc, new_text, None)
    assert demo.scalar("SELECT page FROM notes WHERE note_id=?", (n["note_id"],)) is None
