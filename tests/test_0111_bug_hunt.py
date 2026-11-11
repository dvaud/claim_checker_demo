"""0.11.1: the defects found in the deep review, each proved by the behaviour it broke.

The project of helpers_0110 (one document per AI setting, markers in every sentence of the restricted ones) is used
where a defect concerned what Claude may see.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from helpers_0110 import LOCAL_MARK, Cloud, Local, mixed_project, use_local_model

from enlens_claims import access, claimcheck, home, taskqueue, tasks
from enlens_claims.llm import BackendError

HYP = "Green hydrogen production can increase water stress in arid regions."


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Mixed")
    ids = mixed_project(ws, tmp_path / "corpus")
    return ws, ids


class Chatty(Local):
    """A local model whose note paraphrases the licensed passages (as a real one would)."""

    def complete(self, kind, system, user, model, payload=None):
        out = json.loads(super().complete(kind, system, user, model, payload))
        if isinstance(out, dict) and "rationale" in out:
            out["rationale"] = f"The licensed study says {LOCAL_MARK} throughout."
        return json.dumps(out)


# ---------------------------------------------------------------------------------------------
# what Claude may see
# ---------------------------------------------------------------------------------------------
def test_the_summary_is_the_main_parts_not_the_local_models(mixed, monkeypatch):
    """The local part is answered after the main part: its note must not become the check's summary, which the
    connector hands to a Claude chat."""
    ws, ids = mixed
    cloud, local = Cloud(), Chatty()
    use_local_model(monkeypatch, local)
    hid = claimcheck.check_hypothesis(ws, HYP, cloud, "claude-opus", k=12, per_doc=4)
    res = claimcheck.hypothesis_result(ws, hid)
    assert local.sent, "the local model read nothing: the test proves nothing"
    assert LOCAL_MARK.lower() not in (res["parts"][0]["rationale"] or "").lower()
    assert res["model"] == "claude-opus"
    from enlens_claims import mcp_server

    summary = mcp_server._summary(ws, res["parts"][0]["claim_id"])
    assert LOCAL_MARK.lower() not in json.dumps(summary).lower()


def test_removing_a_document_takes_its_tasks_out_of_the_queue(mixed):
    ws, ids = mixed
    with tasks.queueing():
        claimcheck.queue_check(ws, HYP, None, k=12, per_doc=4, expand=False)
    waiting = ws.query("SELECT task_id FROM tasks WHERE kind='check' AND queued=1")
    assert waiting
    ws.remove_document(ids["cloud"])  # the only document Claude may read: every check task named its passages
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='check' AND COALESCE(queued, 0)=1") == 0
    assert not taskqueue.next_tasks(ws, "check").get("tasks")


def test_a_claude_chat_is_recorded_without_context_passages(mixed):
    ws, ids = mixed
    r = claimcheck.open_check(ws, HYP, terms=["water"], k=12, per_doc=4)
    shown = {p["text"] for p in r["passages"]}
    rows = access.ledger(ws)
    texts = {ws.scalar("SELECT text FROM passages WHERE passage_id=?", (x["passage_id"],)) for x in rows}
    assert rows and texts == shown  # exactly what the chat saw, not the passage before each excerpt


def test_the_connector_hides_a_no_ai_title_in_its_warnings(mixed, tmp_path):
    from enlens_claims import mcp_server

    ws, ids = mixed
    short = tmp_path / "short"
    short.mkdir()
    (short / "Private notes of Alice.txt").write_text("Alice said the plant uses water from the river. " * 8)  # under 1000 chars
    out = mcp_server._ingest(ws, str(short), None, ai_access="none")
    assert out.get("warnings")
    assert "Alice" not in json.dumps(out)


# ---------------------------------------------------------------------------------------------
# the queue
# ---------------------------------------------------------------------------------------------
def test_waiting_ends_when_the_task_leaves_the_queue(mixed):
    ws, ids = mixed
    with tasks.queueing():
        claimcheck.queue_check(ws, HYP, None, k=12, per_doc=4, expand=False)
    tid = ws.scalar("SELECT task_id FROM tasks WHERE kind='check' AND queued=1")

    class Be:
        should_stop = None
        progress = None

    def later():
        time.sleep(0.3)
        access.set_documents(ws, [ids["cloud"]], "local")  # the document's setting changes while the app waits

    threading.Thread(target=later, daemon=True).start()
    ok, errors = taskqueue.wait_for(ws, tid, Be(), poll=0.1)
    assert not ok and errors and "no longer handed to Claude Code" in errors[0]


def test_answering_here_skips_a_task_claude_code_took_meanwhile(mixed):
    ws, ids = mixed
    with tasks.queueing():
        claimcheck.queue_check(ws, HYP, None, k=12, per_doc=4, expand=False)
    got = taskqueue.next_tasks(ws, "check")  # a Claude Code session holds it now
    assert got["tasks"]
    local = Local()
    out = taskqueue.run_here(ws, local, kinds=["check"])
    assert out["answered"] == 0 and out["failed"] == 0 and not local.sent
    assert ws.scalar("SELECT claimed_by FROM tasks WHERE task_id=?", (got["tasks"][0]["task_id"],)) == got["claim"]


def test_a_model_test_records_nothing_before_a_batch_is_taken(mixed):
    ws, ids = mixed
    pid = ws.scalar("SELECT passage_id FROM passages WHERE doc_id=?", (ids["cloud"],))
    payload = {"passages": [{"passage_id": pid, "doc_id": ids["cloud"], "text": "x", "n": 1}], "terms": ["water"]}

    class Be:
        name = "claude_code"
        should_stop = staticmethod(lambda: True)
        progress = None

    taskqueue.answer_on_copy(ws, [("theme:test:1", "theme", payload, "sonnet")], Be(), "test",
                             should_stop=lambda: True)
    assert access.ledger(ws) == []  # stopped before Claude Code took anything


def test_a_changed_setting_relabels_only_what_changed(mixed):
    ws, ids = mixed
    with tasks.queueing():
        claimcheck.queue_check(ws, HYP, None, k=12, per_doc=4, expand=False)
    with ws.connect() as cx:
        assert access.relabel(cx) == 0  # nothing changed: nothing to write
    assert access.set_documents(ws, [ids["cloud"]], "local")["tasks_changed"] >= 1


# ---------------------------------------------------------------------------------------------
# a person's judgement, the status, the summary
# ---------------------------------------------------------------------------------------------
def test_answering_a_check_again_keeps_a_persons_judgement(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    local = Local()
    hid = claimcheck.check_hypothesis(ws, HYP, local, "qwen", k=12, per_doc=4)
    part = claimcheck.hypothesis_result(ws, hid)["parts"][0]
    p = next(x for x in part["passages"] if x["doc_id"] == ids["cloud"])
    claimcheck.set_judgement(ws, part["claim_id"], p["passage_id"], "refutes", "my note")
    monkeypatch.setitem(tasks.prompts.VERSIONS, "check", "check-test-again")
    assert tasks.refresh(ws, "check") >= 1  # queued again under a new prompt version
    tid = ws.scalar("SELECT task_id FROM tasks WHERE kind='check' AND status='pending'")
    tasks.run_one(ws, tid, local, "qwen")
    row = ws.query("SELECT user_verdict, user_note, ai_history_json FROM verifications WHERE subject_id=? AND passage_id=?",
                   (part["claim_id"], p["passage_id"]))[0]
    assert (row["user_verdict"], row["user_note"]) == ("refutes", "my note")
    assert json.loads(row["ai_history_json"])[-1]["why"] == "answered again"


def test_the_results_list_and_the_result_page_agree_on_waiting(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, Local())
    with tasks.queueing():
        hid = claimcheck.queue_check(ws, HYP, None, k=12, per_doc=4, expand=False)
    assert claimcheck.hypothesis_result(ws, hid)["status"] == "waiting"
    assert [h["status"] for h in claimcheck.history(ws) if h["hyp_id"] == hid] == ["waiting"]
    # the main part is answered, the local part is not yet: both still say waiting
    main = ws.scalar("SELECT task_id FROM tasks WHERE kind='check' AND task_id NOT LIKE '%:local' AND task_id NOT "
                     "LIKE '%:person'")
    tasks.run_one(ws, main, Cloud(), "claude-opus")
    with ws.connect() as cx:
        cx.execute("UPDATE hypotheses SET queue=NULL WHERE hyp_id=?", (hid,))
    assert ws.scalar("SELECT status FROM tasks WHERE task_id=?", (main + ":local",)) == "pending"
    assert claimcheck.hypothesis_result(ws, hid)["status"] == "waiting"
    assert [h["status"] for h in claimcheck.history(ws) if h["hyp_id"] == hid] == ["waiting"]


def test_judging_an_excerpt_no_model_read_is_not_a_correction(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    hid = claimcheck.check_hypothesis(ws, HYP, Cloud(), "claude-opus", k=12, per_doc=4)
    part = claimcheck.hypothesis_result(ws, hid)["parts"][0]
    p = next(x for x in part["passages"] if x["waiting_for_you"])
    claimcheck.set_judgement(ws, part["claim_id"], p["passage_id"], "supports")
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["corrected"] == 0 and res["reviewed"] >= 1
    assert [h["corrected"] for h in claimcheck.history(ws) if h["hyp_id"] == hid] == [0]


def test_a_single_reworded_part_is_checked_by_queue_as_reworded(mixed):
    ws, ids = mixed
    text = "Electrolysis plants in deserts raise the water stress of the region around them."
    with tasks.queueing():
        hid = claimcheck.queue_check(ws, HYP, None, parts=[text], edited={"parts": True}, expand=False)
    claims = ws.query("SELECT text, part FROM user_claims WHERE hyp_id=?", (hid,))
    assert [(c["text"], c["part"]) for c in claims] == [(text, 0)]
    assert ws.scalar("SELECT decomposed FROM hypotheses WHERE hyp_id=?", (hid,)) == 0


def test_the_round_number_when_nothing_more_is_found(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    hid = claimcheck.check_hypothesis(ws, HYP, Cloud(), "claude-opus", k=50, per_doc=50)
    cid = claimcheck.hypothesis_result(ws, hid)["parts"][0]["claim_id"]
    r = claimcheck.more_passages(ws, cid, k=50, model="claude-opus", terms=["hydrogen"])
    assert r["round"] == 2  # not the number of parts of the first round plus one


def test_a_failed_local_part_is_shown(mixed, monkeypatch):
    class Garbage(Local):
        def complete(self, kind, system, user, model, payload=None):
            self.sent.append(user)
            return "not json at all"

    ws, ids = mixed
    use_local_model(monkeypatch, Garbage())
    notes = []
    hid = claimcheck.check_hypothesis(ws, HYP, Cloud(), "claude-opus", k=12, per_doc=4,
                                      progress=lambda s, m, i=None: notes.append((s, m)))
    part = claimcheck.hypothesis_result(ws, hid)["parts"][0]
    assert part["status"] != "failed"  # the main part succeeded
    assert part["local_failed"]["passages"] >= 1 and part["local_failed"]["errors"]
    assert {x["read_by"] for x in part["passages"] if x["doc_id"] == ids["local"]} == {"local"}
    assert any(s == "note" and "could not be used" in m for s, m in notes)
    # "Read them now" tries the part again (here with a model that answers)
    use_local_model(monkeypatch, Local())
    assert claimcheck.run_local_parts(ws, [hid], access.Readers(None, ""), retry_failed=True) == 1
    assert "local_failed" not in claimcheck.hypothesis_result(ws, hid)["parts"][0]


def test_the_sdg_verifier_is_told_about_excerpts_read_elsewhere():
    from enlens_claims import prompts

    pl = {"claim": "x", "target": "6.4", "target_description": "water", "passages": [{"text": "t", "title": "a"}],
          "read_elsewhere": 2}
    assert "2 other excerpts" in prompts.user_prompt("verify_set", pl)


# ---------------------------------------------------------------------------------------------
# settings, projects, the app
# ---------------------------------------------------------------------------------------------
def test_local_only_with_cloud_still_allowed_in_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    home.update_settings({"allow_cloud": True})
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    s = home.load_settings()
    assert s["allow_cloud"] is False and s["allow_claude_code"] is False
    home.update_settings({"threshold": 0.7})  # used to be refused: "Cloud models are switched off"
    assert home.load_settings()["threshold"] == 0.7


def test_a_stale_link_does_not_decide_where_a_new_project_goes(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    home.home()
    home._save_links({"Old": str(tmp_path / "gone")})
    ws = home.create_project("Old")
    assert ws.root == home.home() / "projects" / "Old" and "Old" not in home._links()


def test_the_tracker_takes_notes_without_a_phantom_part():
    from enlens_claims.gui.progress import Tracker

    t = Tracker()
    t.step("grade", "Claude is reading 3 excerpts", {"part": 1, "parts": 2, "claim": "a"})
    t.step("note", "The local model could not be reached; those excerpts wait for your judgement", {})
    t.step("grade_done", "done", {"part": 1, "parts": 2, "claim": "a"})
    st = t.state()
    assert [p["part"] for p in st["parts"]] == [1]
    assert st["parts"][0]["steps"][-1]["state"] == "done" or any(s["key"] == "grade" and s["state"] == "done"
                                                                for s in st["parts"][0]["steps"])
    assert st["notes"] == ["The local model could not be reached; those excerpts wait for your judgement"]
    assert "could not be reached" in st["message"] or st["message"] == "done"


def test_the_app_refuses_a_key_on_a_local_only_installation_and_speaks_plainly(tmp_path, monkeypatch):
    import test_app

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api = test_app.Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
    try:
        assert api("PUT", "/api/settings", {"backend": "baseline"})[0] == 200
        assert api("POST", "/api/projects", {"name": "P"})[0] == 200
        st, body = api("POST", "/api/projects/P/themes", {"k": "abc"})
        assert st == 400 and body["error"] == "k must be a whole number."
        assert api("GET", "/api/projects/P/passages/nothing/terms")[0] == 404
        assert api("GET", "/api/state")[1]["installation"].get("updates")
        monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
        st, body = api("POST", "/api/settings/key", {"key": "sk-ant-x"})
        assert st == 403 and "switched off" in body["error"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_ollama_is_started_for_the_restricted_model_too(monkeypatch):
    from enlens_claims.gui import launcher

    asked = []

    def urlopen(url, timeout=0):
        asked.append(url)
        raise OSError("not running")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    for s in ({"backend": "claude_code", "restricted_server": "ollama"},
              {"backend": "claude_code", "embed_backend": "ollama", "embed_model": "nomic-embed-text"}):
        launcher.start_ollama(s)
    assert len(asked) == 2  # both settings made it look for Ollama
    asked.clear()
    launcher.start_ollama({"backend": "claude_code", "restricted_server": "", "embed_backend": "off"})
    assert asked == []


def test_a_stop_before_the_first_token_closes_the_response():
    """Ollama sends its headers with the first token; a Stop pressed while it still reads the prompt used to let
    it generate the whole answer."""
    from enlens_claims.llm import OllamaBackend

    class Resp:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

        def close(self):
            self.closed = True

        def read(self):
            return b"{}"

        def __iter__(self):
            for i in range(40):
                if self.closed:
                    return
                yield json.dumps({"message": {"content": "x"}, "done": i == 39}).encode()

    resp = Resp()

    def opener(req, timeout=None):
        time.sleep(0.4)
        return resp

    be = OllamaBackend(opener=opener)
    be.should_stop = lambda: True
    with pytest.raises(BackendError, match="Stopped"):
        be.complete("check", "sys", "user", "model", {})
    time.sleep(0.6)
    assert resp.closed


def test_the_claude_api_retries_once_at_most(monkeypatch):
    import sys
    import types

    seen = {}

    class Anthropic:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Anthropic))
    from enlens_claims.llm import AnthropicBackend

    AnthropicBackend(api_key="k")
    assert seen["max_retries"] == 1


def test_the_api_extra_hint_fits_the_one_line_install(monkeypatch):
    from enlens_claims import installation, llm

    monkeypatch.setattr(installation, "kind", lambda: "script")
    hint = llm._anthropic_install_hint()
    from enlens_claims import __version__

    assert "uv tool install" in hint and "anthropic" in hint and f"v{__version__}" in hint


# ---------------------------------------------------------------------------------------------
# the command line, updating, the installer
# ---------------------------------------------------------------------------------------------
def test_prepare_hands_claude_code_only_what_it_may_read(mixed, monkeypatch):
    from enlens_claims import cli, themes

    ws, ids = mixed
    themes.run(ws, k=2, mode="words")
    monkeypatch.setattr(home, "load_settings", lambda: {**home.DEFAULTS, "backend": "claude_code"})
    with tasks.queueing():
        run = themes.runs(ws)[0]["run_id"]
        n = themes.make_name_tasks(ws, run, "sonnet", {"cloud"})
    rows = ws.query("SELECT access, queued FROM tasks WHERE kind='theme'")
    assert n == len(rows) and all(r["access"] == "cloud" for r in rows)
    # `prepare check --file` keeps the framework and code of each line
    hyps = Path(ws.root) / "hyps.csv"
    hyps.write_text("hypothesis,code\n" + f"{HYP},6.4\n")
    rc = cli.main(["--ws", str(ws.root), "prepare", "check", "--file", str(hyps), "--no-expand"])
    assert rc == 0
    assert ws.query("SELECT framework, code FROM hypotheses ORDER BY rowid DESC LIMIT 1")[0]["code"] == "6.4"
    # withdraw without a kind takes the waiting checks with it
    assert cli.main(["--ws", str(ws.root), "queue", "withdraw"]) == 0
    assert ws.scalar("SELECT COUNT(*) FROM hypotheses WHERE queue='waiting'") == 0


def test_update_keeps_an_extra_whose_packages_grew(tmp_path):
    """The extras to reinstall are read before the merge, against the pyproject the copy was installed from."""
    from enlens_claims import update

    root = tmp_path / "copy"
    (root / "src" / "enlens_claims").mkdir(parents=True)
    (root / "src" / "enlens_claims" / "__init__.py").write_text('__version__ = "0.11.0"\n')
    py = root / "pyproject.toml"
    py.write_text('[project]\nname = "enlens-claims"\n[project.optional-dependencies]\nconnector = ["pydantic>=2"]\n')
    calls = []

    class R:
        def __init__(self, out="", rc=0):
            self.stdout, self.stderr, self.returncode = out, "", rc

    def run(cmd, cwd):
        calls.append(cmd)
        if cmd[:2] == ["git", "status"]:
            return R("")
        if cmd[:2] == ["git", "rev-parse"]:
            return R("origin/main")
        if cmd[:2] == ["git", "rev-list"]:
            return R("1" if "HEAD..origin/main" in cmd else "0")
        if cmd[:2] == ["git", "merge"]:  # the new version wants one more package in the extra
            py.write_text('[project]\nname = "enlens-claims"\n[project.optional-dependencies]\n'
                          'connector = ["pydantic>=2", "a-package-nobody-has>=1"]\n')
            (root / "src" / "enlens_claims" / "__init__.py").write_text('__version__ = "0.11.1"\n')
            return R("")
        return R("")

    out = update.update_git(root=root, run=run, python="py")
    assert out["reinstalled"] and out["extras"] == ["connector"]
    assert any("[connector]" in c[-1] for c in calls if c[:1] == ["py"])


def test_update_on_a_detached_head_says_what_to_do(tmp_path):
    from enlens_claims import update

    root = tmp_path / "copy"
    root.mkdir()

    class R:
        def __init__(self, out="", rc=0):
            self.stdout, self.stderr, self.returncode = out, "", rc

    def run(cmd, cwd):
        if cmd[:2] == ["git", "status"]:
            return R("")
        if cmd == ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]:
            return R("", 128)
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return R("HEAD")
        return R("")

    with pytest.raises(update.UpdateError, match="git checkout main"):
        update.update_git(root=root, run=run)


def test_the_extras_of_a_pyproject_without_tomllib():
    from enlens_claims.update import _extras_in

    text = ("[project]\nname = \"x\"\n[project.optional-dependencies]\nfast = [\"numpy>=1.24\"]  # c\n"
            "ocr = [\n  \"pypdfium2>=4.20\",\n  \"pillow>=10\",\n]\ndev = []\n[tool.other]\nx = [\"y\"]\n")
    assert _extras_in(text) == {"fast": ["numpy>=1.24"], "ocr": ["pypdfium2>=4.20", "pillow>=10"], "dev": []}


def test_the_installer_downloads_uvs_installer_before_running_it():
    sh = (Path(__file__).parent.parent / "install" / "install.sh").read_text()
    assert "curl -LsSf -o" in sh and "| sh >" not in sh
    ps = (Path(__file__).parent.parent / "install" / "install.ps1").read_text()
    assert "$LASTEXITCODE -ne 0" in ps


# ---------------------------------------------------------------------------------------------
# documents and the exploring layer
# ---------------------------------------------------------------------------------------------
def test_a_bad_word_file_is_listed_under_failed(ws, tmp_path):
    from enlens_claims import ingest

    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "broken.docx").write_bytes(b"not a zip at all")
    (folder / "fine.txt").write_text("A fine document about hydrogen and water. " * 40)
    stats = ingest.ingest(ws, [folder])
    assert stats["added"] == 1 and any("broken.docx" in f for f in stats["failed"])


def test_a_forced_cut_loses_no_character():
    from enlens_claims.ingest import make_passages

    text = "x" * 2500
    spans = [(0, len(text))]
    ps = make_passages(text, spans, max_chars=1100, min_chars=200)
    covered = set()
    for p in ps:
        covered |= set(range(p.start, p.end))
    assert covered == set(range(len(text)))


def test_coverage_totals_belong_to_one_pass():
    from enlens_claims import frameworks
    from enlens_claims.profile import _coverage

    fw = frameworks.get("sdg", None)
    code = next(iter(fw.codes))
    have = fw.code_stems(code)
    totals = {}
    a, _s = _coverage(fw, code, have, {t: 1.0 for t in have}, totals)
    b, _s = _coverage(fw, code, have, {t: 5.0 for t in have}, {})  # another index, other weights: its own totals
    assert a == 1.0 and b == 1.0 and code in totals


def test_label_indexes_and_the_set_based_removal(loaded):
    ws = loaded
    names = {r[0] for r in ws.query("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"ix_labels_passage_fw", "ix_labels_task"} <= names and "ix_labels_passage" not in names
    from enlens_claims import profile

    profile.ensure_pass1(ws, "sdg")
    docs = [r[0] for r in ws.query("SELECT doc_id FROM documents ORDER BY doc_id")]
    gone, kept = docs[0], docs[1]
    with ws.connect() as cx:
        for d in (gone, kept):
            for (pid,) in cx.execute("SELECT passage_id FROM passages WHERE doc_id=?", (d,)).fetchall():
                cx.execute("INSERT INTO tasks(task_id, kind, model, status, attempts, created_at) VALUES (?,?,?,?,0,?)",
                           (f"label:sdg:{pid}", "label", "m", "pending", "now"))
                cx.execute("INSERT INTO tasks(task_id, kind, model, status, attempts, created_at) VALUES (?,?,?,?,0,?)",
                           (f"extract:{pid}", "extract", "m", "pending", "now"))
    before_kept = ws.scalar("SELECT COUNT(*) FROM tasks WHERE task_id IN (SELECT 'extract:' || passage_id FROM passages WHERE doc_id=?)", (kept,))
    ws.remove_document(gone)
    assert ws.scalar("SELECT COUNT(*) FROM labels WHERE doc_id=?", (gone,)) == 0
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE task_id LIKE ?", (f"label:sdg:{gone}%",)) == 0
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE task_id LIKE ?", (f"extract:{gone}%",)) == 0
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE task_id IN (SELECT 'extract:' || passage_id FROM passages WHERE doc_id=?)", (kept,)) == before_kept
    assert ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=?", (kept,)) > 0


def test_passages_with_a_code_match_the_full_table(loaded):
    from enlens_claims import profile

    ws = loaded
    profile.ensure_pass1(ws, "sdg")
    codes = {r["code"] for r in profile.effective(ws, "sdg")}
    assert codes
    for code in list(codes)[:3]:
        assert profile.passages_with_code(ws, "sdg", code) == {r["passage_id"] for r in profile.effective(ws, "sdg")
                                                              if r["code"] == code}


def test_a_themes_passages_follow_merges_and_moves(mixed):
    from enlens_claims import themes

    ws, _ids = mixed
    run = themes.run(ws, k=3, mode="words")
    v = themes.view(ws, run)
    ids = [t["theme_id"] for t in v["themes"]]
    a, b = ids[0], ids[1]
    members = lambda *ts: {r[0] for r in ws.query(  # noqa: E731
        f"SELECT passage_id FROM theme_members WHERE run_id=? AND theme_id IN ({','.join('?' * len(ts))})", (run, *ts))}
    shown = lambda t: {p["passage_id"] for p in themes.theme_passages(ws, run, t, limit=200)["passages"]}  # noqa: E731
    moved = next(iter(members(b)))
    themes.edit(ws, run, "move", None, a, passage_id=moved)  # one passage of b into a
    assert shown(a) == members(a) | {moved} and moved not in shown(b)
    themes.edit(ws, run, "merge", b, a)                       # then b into a
    assert shown(a) == members(a, b)


def test_a_search_export_is_one_search(loaded, monkeypatch):
    from enlens_claims import concordance

    ws = loaded
    page = concordance.search(ws, "the", limit=2)
    assert page["total"] > 2 and len(page["lines"]) == 2
    whole = concordance.search(ws, "the", limit=None)
    assert len(whole["lines"]) == whole["total"]


def test_an_unclosed_front_matter_is_no_front_matter(tmp_path):
    from enlens_claims.claude_setup import frontmatter

    f = tmp_path / "x.md"
    f.write_text("---\nname: x\nno end here\n")
    assert frontmatter(f) == {}


def test_the_page_files():
    static = Path(__file__).parent.parent / "src" / "enlens_claims" / "gui" / "static"
    index = (static / "index.html").read_text()
    from _static import rule  # 0.17.0: the release's rules are in the cascade, not in a sheet of its own

    assert rule(".progress-notes") and rule(".progress-notes li")
    assert "progress-notes" in (static / "views" / "progress.js").read_text()
    assert "local_failed" in (static / "views" / "result.js").read_text()
    feats = (static / "features.js").read_text()
    for key in ("history", "sources"):
        block = feats[feats.index(f"  {key}: {{"):]
        assert 'ai: "optional"' in block[:block.index("\n  },")], key
    # the helpers live in lib.js once
    lib = (static / "lib.js").read_text()
    for name in ("plural", "shortTitle", "auditorName", "heatCell"):
        assert f"export function {name}" in lib, name
    assert "export async function runningJob" in lib
    for view in ("profile.js", "concepts.js", "themes.js"):
        assert "function plural(" not in (static / "views" / view).read_text(), view
