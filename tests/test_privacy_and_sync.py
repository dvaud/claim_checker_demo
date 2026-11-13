"""0.14.3: privacy, sharing (sync) and adding documents. Each defect of the 0.14.2 review, proved by the behaviour it
broke.

- the connector's check summary, written by a local main model, paraphrased documents kept from Claude;
- a project zip whose database cannot be read stayed in projects/ and broke the connector for every project;
- "Download as a zip" carried the files of removed documents;
- sharing: a removed sync-clash copy came back, a round running here was deleted, colleagues on versions with other
  columns had a sync clash on every check, a copy kept a looser AI setting than its original, a crafted file could
  replace your judgement;
- adding documents: one damaged or password-protected zip or Word file stopped the whole add, text files that are not
  UTF-8 were garbled, Stop did not reach OCR, the pdfminer fallback hid scanned pages, a password-protected PDF was
  "without text";
- glossary terms of restricted documents went to an embedding model on another computer.
"""
from __future__ import annotations

import asyncio
import json
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest
from helpers import PAPER_A_PAGES, make_pdf
from helpers_0110 import LOCAL_MARK, Local, mixed_project, use_local_model
from test_0_14_0_shared_projects import CLAIM, Person, _claim, _excerpts, anna_and_ben  # noqa: F401 (fixture)

from enlens_claims import access, bundle, claimcheck, concordance, home, ingest, mcp_server, sync, tasks, terms
from enlens_claims.llm import BaselineBackend
from enlens_claims.store import Workspace

HYP = "Green hydrogen production can increase water stress in arid regions."


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Mixed")
    ids = mixed_project(ws, tmp_path / "corpus")
    return ws, ids


class Chatty(Local):
    """A model on this computer whose summary, and its note on each excerpt it grades, paraphrase every excerpt it
    read (as a real one could)."""

    def complete(self, kind, system, user, model, payload=None):
        out = json.loads(super().complete(kind, system, user, model, payload))
        if kind == "check" and isinstance(out, dict):
            texts = sorted((p["text"][:120] for p in (payload or {}).get("passages", [])),
                           key=lambda t: LOCAL_MARK not in t)  # what it read of the licensed study first
            out["rationale"] = "It read: " + " | ".join(texts)
            for ev in out.get("evidence") or []:
                ev["scope_note"] = "Unlike the others: " + " | ".join(texts)[:300]
        return json.dumps(out)


# ---------------------------------------------------------------------------------------------
# 1. the connector's summary of a check
# ---------------------------------------------------------------------------------------------
def test_a_local_main_models_summary_does_not_reach_the_chat(mixed, monkeypatch):
    ws, ids = mixed
    local = Chatty()
    use_local_model(monkeypatch, None)
    hid = claimcheck.check_hypothesis(ws, HYP, local, "local-model", k=12, per_doc=4)
    cid = claimcheck.hypothesis_result(ws, hid)["parts"][0]["claim_id"]
    r = claimcheck.result(ws, cid)
    assert LOCAL_MARK.lower() in (r["rationale"] or "").lower(), "the main model read no restricted text"
    assert any(LOCAL_MARK.lower() in (p.get("scope_note") or "").lower() for p in r["passages"]
               if p["doc_id"] == ids["cloud"]), "no note on a cloud excerpt names restricted text: proves nothing"
    s = mcp_server._summary(ws, cid)
    assert s["summary"] is None and "the summary and its notes on excerpts" in s["restricted_note"]
    assert s["evidence"] and not any("about_another_group" in e for e in s["evidence"])
    assert LOCAL_MARK.lower() not in json.dumps(s).lower()


def test_a_claude_summary_is_shown_until_its_document_is_kept_from_claude(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, Local())
    cloud = Chatty()
    cloud.name, cloud.base_url = "anthropic", None  # Claude: its part of the round holds only what Claude may read
    hid = claimcheck.check_hypothesis(ws, HYP, cloud, "claude-opus", k=12, per_doc=4)
    cid = claimcheck.hypothesis_result(ws, hid)["parts"][0]["claim_id"]
    s = mcp_server._summary(ws, cid)
    assert s["summary"] and s["summary"].startswith("It read:")
    assert any(e.get("about_another_group") for e in s["evidence"])
    access.set_documents(ws, [ids["cloud"]], "local")  # the document the summary is about is now kept from Claude
    s = mcp_server._summary(ws, cid)
    assert s["summary"] is None and "summary" in s["restricted_note"]


# ---------------------------------------------------------------------------------------------
# 2. a project zip whose database cannot be read
# ---------------------------------------------------------------------------------------------
def _run(fn):
    from mcp import Client

    from enlens_claims.mcp_server import build_server

    async def go():
        async with Client(build_server()) as c:
            async def call(name, args):
                r = await c.call_tool(name, args)
                assert not r.is_error, r.content[0].text
                return json.loads(r.content[0].text)
            return await fn(call)

    return asyncio.run(go())


def test_a_zip_whose_database_cannot_be_read_leaves_nothing_behind(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    home.create_project("Good")
    projects = home.home() / "projects"
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("enlens.sqlite", b"this is not sqlite" * 100)
        zf.writestr("bundle.json", json.dumps({"format": "enlens-project", "name": "Bad"}))
    with pytest.raises(ValueError, match="database in this zip cannot be read"):
        bundle.import_project(z, projects / "Bad")
    assert sorted(p.name for p in projects.iterdir()) == ["Good"] and home.list_projects() == ["Good"]
    # a damaged zip (one changed byte: its checksum fails): a plain message, nothing left either
    crc = tmp_path / "crc.zip"
    with zipfile.ZipFile(crc, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("enlens.sqlite", (projects / "Good" / "enlens.sqlite").read_bytes())
        zf.writestr("uploads/a.txt", b"A" * 1000)
    data = bytearray(crc.read_bytes())
    data[data.find(b"AAAA")] = ord("B")
    crc.write_bytes(bytes(data))
    with pytest.raises(ValueError, match="could not be unpacked .*damaged zip"):
        bundle.import_project(crc, projects / "Crc")
    assert sorted(p.name for p in projects.iterdir()) == ["Good"]


def test_one_damaged_project_does_not_stop_the_connector(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    good = home.create_project("Good")
    with good.connect() as cx:
        cx.execute("INSERT INTO user_claims(claim_id, text, hyp_id) VALUES ('c1', 'A claim', 'c1')")
    broken = home.home() / "projects" / "Broken"  # sorted before "Good": it was opened first, and raised
    broken.mkdir()
    (broken / "enlens.sqlite").write_bytes(b"garbage " * 200)
    assert home.list_projects() == ["Broken", "Good"]
    assert mcp_server._find_check("c1")[0] == "Good"
    with pytest.raises(ValueError, match="No check 'nope' in any project.*could not be opened.*Broken"):
        mcp_server._find_check("nope")
    with pytest.raises(ValueError, match="No batch"):
        mcp_server._find_claim("q123")
    with pytest.raises(ValueError, match="Broken.*cannot be opened"):
        mcp_server._project("Broken")

    async def fn(call):
        listed = (await call("list_projects", {}))["projects"]
        assert {"project": "Good", "documents": 0, "checks": 1} in listed
        assert any(p["project"] == "Broken" and p.get("unreadable") for p in listed)
        q = await call("queue_status", {})
        assert q["unreadable"] == ["Broken"]

    _run(fn)


def test_a_folder_being_imported_is_not_a_project(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    Workspace.create(home.home() / "projects" / "Field.importing")
    assert home.list_projects() == []
    assert home.safe_name("Field.importing") == "Field importing"
    assert not home.safe_name("x" * 50 + ".importing and more").endswith(".importing")  # also once cut to 60


# ---------------------------------------------------------------------------------------------
# 3. the project zip holds the files of the documents the project has, nothing else of uploads/
# ---------------------------------------------------------------------------------------------
def test_the_project_zip_leaves_removed_and_failed_uploads_out(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    ws = home.create_project("P")
    folder = home.save_uploads(ws, [("confidential-hr-report.txt", b"Confidential staff appraisal of named people. " * 30),
                                    ("public.txt", b"Public report on hydrogen and water in arid regions. " * 30),
                                    ("broken.docx", b"not a Word file at all")])
    st = ingest.ingest(ws, [folder], ai_access="cloud")
    assert st["added"] == 2 and st["failed"]
    ws.remove_document(ws.scalar("SELECT doc_id FROM documents WHERE title LIKE 'Confidential%'"))  # added by mistake
    out = tmp_path / "send.zip"
    stats = bundle.export_project(ws, out)
    with zipfile.ZipFile(out) as zf:
        uploads = [n for n in zf.namelist() if n.startswith("uploads/")]
    assert uploads == [f"uploads/{folder.name}/public.txt"] and stats["uploads"] == 1
    ws2 = bundle.import_project(out, tmp_path / "copy")
    from enlens_claims.sources import original_file

    assert all(original_file(ws2, d)["available"] for (d,) in ws2.query("SELECT doc_id FROM documents"))


# ---------------------------------------------------------------------------------------------
# 4-6, 10, 14. sharing
# ---------------------------------------------------------------------------------------------
def _read_again(ben: Person) -> str:
    """Ben's copy reads the paper into other text: the next file from Anna brings her reading in as a copy."""
    with ben:
        doc = ben.ws.scalar("SELECT doc_id FROM documents WHERE title LIKE 'Water footprint%'")
        with ben.ws.connect() as cx:
            cx.execute("UPDATE documents SET text = text || ' (read again)', text_fp=NULL WHERE doc_id=?", (doc,))
    return doc


def test_a_removed_sync_clash_copy_of_a_document_stays_removed(anna_and_ben):
    anna, ben = anna_and_ben
    _read_again(ben)
    rep = ben.bring_in(anna.send())
    copy = rep["documents"]["clash"][0]["doc_id"]
    with ben:
        ben.ws.remove_document(copy)  # Ben settles the clash: he removes Anna's reading
    rep = ben.bring_in(anna.send())
    assert not rep["documents"]["clash"] and rep["documents"]["removed_here"]
    assert any("you removed earlier did not come back" in line for line in rep["lines"])
    with ben:
        assert not ben.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (copy,))
        assert not ben.ws.scalar("SELECT 1 FROM passages WHERE doc_id=?", (copy,))


def test_a_round_running_here_is_not_replaced(anna_and_ben):
    anna, ben = anna_and_ben
    with ben:
        cid = _claim(ben.ws, anna.hid)
        p = ben.ws.query("SELECT passage_id, doc_id, text FROM passages WHERE section='body' LIMIT 1")[0]
        payload = {"subject_id": cid, "claim": "x", "passages": [{"passage_id": p[0], "doc_id": p[1], "text": p[2]}]}
        with ben.ws.connect() as cx:  # Ben's next round, queued for Claude Code (a round only adds tasks)
            tasks._insert_task(cx, f"check:{cid}:r2", "check", "opus", payload)
            cx.execute("UPDATE tasks SET queued=1 WHERE task_id=?", (f"check:{cid}:r2",))
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["running_here"] == [CLAIM] and rep["checks"]["updated"] == 0
    assert any(line.startswith("Still running in your copy") for line in rep["lines"])
    with ben:
        assert ben.ws.scalar("SELECT status FROM tasks WHERE task_id=?", (f"check:{cid}:r2",)) == "pending"
        assert ben.ws.scalar("SELECT queued FROM tasks WHERE task_id=?", (f"check:{cid}:r2",)) == 1
        # a task left unanswered by a run that stopped (not in the queue, no helper) does not count as running: it
        # would keep the older version for good
        with ben.ws.connect() as cx:
            cx.execute("UPDATE tasks SET queued=0 WHERE task_id=?", (f"check:{cid}:r2",))
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["running_here"]


def test_a_sync_clash_copy_running_here_gets_no_second_copy(anna_and_ben):
    anna, ben = anna_and_ben
    with ben:
        claimcheck.set_note(ben.ws, anna.hid, "Ben's note")
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")
    copy = ben.bring_in(anna.send())["checks"]["clash"][0]["hyp_id"]  # both changed it: Anna's version beside Ben's
    with ben:
        cid = ben.ws.scalar("SELECT claim_id FROM user_claims WHERE hyp_id=?", (copy,))
        p = ben.ws.query("SELECT passage_id, doc_id, text FROM passages WHERE section='body' LIMIT 1")[0]
        payload = {"subject_id": cid, "claim": "x", "passages": [{"passage_id": p[0], "doc_id": p[1], "text": p[2]}]}
        with ben.ws.connect() as cx:  # Ben reads more excerpts for Anna's version, queued for Claude Code
            tasks._insert_task(cx, f"check:{cid}:r2", "check", "opus", payload)
            cx.execute("UPDATE tasks SET queued=1 WHERE task_id=?", (f"check:{cid}:r2",))
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's second note")
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["running_here"] == [CLAIM] and not rep["checks"]["clash"]
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM sync_copies WHERE kind='check' AND of_key=?", (anna.hid,)) == 1
        assert ben.ws.scalar("SELECT queued FROM tasks WHERE task_id=?", (f"check:{cid}:r2",)) == 1


def test_a_colleague_on_a_version_with_more_columns_is_no_sync_clash(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        with anna.ws.connect() as cx:  # Anna's newer ENLENS added columns, one of them with a default
            cx.execute("ALTER TABLE verifications ADD COLUMN cited_by TEXT")
            cx.execute("ALTER TABLE hypotheses ADD COLUMN reviewed INT DEFAULT 0")
    # roles (H5, DESIGN-roles §4.9): a colleague's change of Anna's own check would come in beside hers, so the
    # change is Anna's here (her copy has the columns), and Ben's copy is the one that takes it, both ways round
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's first note")  # only Anna changed the check
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["clash"]
    rep = anna.bring_in(ben.send())  # and the other way round: Ben's copy, without the columns, is the same check
    assert rep["checks"]["updated"] == 0 and not rep["checks"]["clash"]
    with ben:  # Ben updates too, to a version that adds a column with a default: his earlier states still count
        with ben.ws.connect() as cx:
            cx.execute("ALTER TABLE user_claims ADD COLUMN weight INT DEFAULT 0")
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["clash"]


def _legacy_record_seen(ws, cx):
    """What 0.14.0 to 0.14.2 wrote down: one fingerprint per unit, over every column (`SELECT *`)."""
    canon = sync._canon(cx)
    rows = [("check", h, sync._fp(sync._check_unit(cx, h), canon)) for (h,) in cx.execute("SELECT hyp_id FROM hypotheses")]
    rows += [("themes", r, sync._fp(sync._themes_unit(cx, r), canon)) for (r,) in cx.execute("SELECT run_id FROM theme_runs")]
    cx.executemany("INSERT OR IGNORE INTO sync_seen(kind, key, fp) VALUES (?,?,?)", rows)


@pytest.fixture
def anna_on_0142(loaded, tmp_path, monkeypatch):
    """Anna and Ben, both on 0.14.2 so far (their copies hold only 0.14.2 fingerprints); then Ben updates to this
    version. Anna's sending stays 0.14.2's (`anna_sends`)."""
    real = sync.record_seen
    monkeypatch.setattr(sync, "record_seen", _legacy_record_seen)
    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    anna.ws = loaded
    with anna:
        anna.hid = claimcheck.check_hypothesis(loaded, CLAIM, BaselineBackend(), "baseline", k=3)
    first = anna.send()
    with ben:
        ben.ws = bundle.import_project(first, tmp_path / "ben-project")
    monkeypatch.setattr(sync, "record_seen", real)  # Ben updates

    def anna_sends() -> Path:
        with monkeypatch.context() as m:
            m.setattr(sync, "record_seen", _legacy_record_seen)
            return anna.send()

    return anna, ben, anna_sends


def test_fingerprints_of_0142_are_still_recognised(anna_on_0142):
    anna, ben, anna_sends = anna_on_0142
    with ben:
        claimcheck.set_note(ben.ws, anna.hid, "Ben's note")  # only Ben changed it
    rep = ben.bring_in(anna_sends())
    assert rep["checks"]["yours_newer"] == 1 and not rep["checks"]["clash"]
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")  # now Anna changed it too: a real clash
    rep = ben.bring_in(anna_sends())
    assert len(rep["checks"]["clash"]) == 1


def test_a_0142_colleagues_change_is_brought_up_to_date(anna_on_0142):
    anna, ben, anna_sends = anna_on_0142
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")  # only Anna changed it
    rep = ben.bring_in(anna_sends())
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["clash"]
    # and Ben's file says what a 0.14.2 copy looks for: the fingerprint over every column
    ben.send()
    with ben:
        cx = ben.ws._conn()
        legacy = sync._fp(sync._check_unit(cx, anna.hid), sync._canon(cx))
        assert ben.ws.scalar("SELECT 1 FROM sync_seen WHERE kind='check' AND key=? AND fp=?", (anna.hid, legacy))


def test_a_sync_clash_copy_of_a_document_follows_its_original_setting(anna_and_ben):
    anna, ben = anna_and_ben
    doc = _read_again(ben)
    copy = ben.bring_in(anna.send())["documents"]["clash"][0]["doc_id"]
    with ben:
        access.set_documents(ben.ws, [doc], "local")  # Ben keeps the paper from Claude: Anna's reading of it too
        assert access.levels(ben.ws, [doc, copy]) == {doc: "local", copy: "local"}
        assert access.levels(ben.ws)[copy] == "local"
        access.set_documents(ben.ws, [doc], "none")
        assert access.levels(ben.ws, [copy]) == {copy: "none"} and copy in access.restricted_titles(ben.ws)
        access.set_documents(ben.ws, [doc], "cloud")
        access.set_documents(ben.ws, [copy], "local")  # the copy's own, stricter setting still counts
        assert access.levels(ben.ws, [doc, copy]) == {doc: "cloud", copy: "local"}


def test_a_colleagues_file_cannot_decide_in_your_name(anna_and_ben):
    anna, ben = anna_and_ben
    with ben:
        cid = _claim(ben.ws, anna.hid)
        pid = _excerpts(ben.ws, anna.hid)[0]["passage_id"]
        claimcheck.set_judgement(ben.ws, cid, pid, "supports", note="Ben's own")
    with anna:  # a crafted file: a later judgement and a review under Ben's name
        with anna.ws.connect() as cx:
            cx.execute("INSERT INTO judgements(claim_id, passage_id, person_id, verdict, note, at) VALUES (?,?,?,?,?,?)",
                       (cid, pid, ben.id, "refutes", "forged", "2999-01-01T00:00:00+00:00"))
            cx.execute("INSERT INTO reviews(item_kind, item_id, field, proposed, decision, decided_at, person_id) "
                       "VALUES ('label', 'forged-label', 'code', 'A', 'reject', '2999-01-01T00:00:00+00:00', ?)", (ben.id,))
    ben.bring_in(anna.send())
    with ben:
        got = {p["passage_id"]: p for p in _excerpts(ben.ws, anna.hid)}[pid]
        assert got["user_verdict"] == "supports" and got["judged_by"] == "you"
        assert ben.ws.query("SELECT verdict, note FROM judgements WHERE passage_id=? AND person_id=?",
                            (pid, ben.id))[0][:] == ("supports", "Ben's own")
        assert not ben.ws.scalar("SELECT 1 FROM reviews WHERE item_id='forged-label'")
    # roles (review L2, the owner's call): a file no longer takes a judgement back under your name either. Since a
    # second computer is its own person, nothing honest writes under this id from elsewhere; a move keeps the id, but
    # the old computer stops. The file's row is refused and recorded (DESIGN-roles §4.10)
    with anna:
        with anna.ws.connect() as cx:
            cx.execute("UPDATE judgements SET verdict=NULL, note=NULL, at='2999-01-02T00:00:00+00:00' WHERE person_id=?",
                       (ben.id,))
    ben.bring_in(anna.send())
    with ben:
        got = {p["passage_id"]: p for p in _excerpts(ben.ws, anna.hid)}[pid]
        assert got["judged_by"] == "you" and got["user_verdict"] == "supports"
        assert ben.ws.scalar("SELECT 1 FROM sync_refused WHERE kind='judgement'")


# ---------------------------------------------------------------------------------------------
# 7, 8, 11-13. adding documents
# ---------------------------------------------------------------------------------------------
_W = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
      + "".join(f"<w:p><w:r><w:t>Paragraph {i} about water use of electrolysis in arid regions.</w:t></w:r></w:p>"
                for i in range(12)) + "</w:body></w:document>")


def _protected_zip(path: Path, name: str, text: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(name, text)
    d = bytearray(path.read_bytes())
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):  # marked as encrypted (general purpose bit 0)
        i = d.find(sig)
        struct.pack_into("<H", d, i + off, struct.unpack_from("<H", d, i + off)[0] | 1)
    path.write_bytes(bytes(d))


def test_one_bad_zip_or_word_file_does_not_stop_the_add(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    src = tmp_path / "src"
    src.mkdir()
    (src / "a_good.txt").write_text("A good text file about hydrogen and the water it needs. " * 10)
    _protected_zip(src / "b_protected.zip", "secret.txt", "Report text about electrolysis water demand. " * 20)
    damaged = src / "c_damaged.zip"  # one good file and one with a changed byte (its checksum fails)
    with zipfile.ZipFile(damaged, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("fine.txt", "A report on desalination for hydrogen plants by the sea. " * 10)
        zf.writestr("hurt.txt", "Report text about electrolysis water demand. " * 20)
        zf.writestr("n" * 246 + ".txt", "A file with a very long name about seawater electrolysis. " * 10)
    d = bytearray(damaged.read_bytes())
    d[d.find(b"Report text")] = ord("X")
    damaged.write_bytes(bytes(d))
    with zipfile.ZipFile(src / "d_badcore.docx", "w") as zf:  # damaged document properties, a readable text
        zf.writestr("word/document.xml", _W)
        zf.writestr("docProps/core.xml", "<cp:coreProperties><dc:title>oops")
    ws = home.create_project("P")
    out = mcp_server._ingest(ws, str(src), None, ai_access="cloud")
    assert out["documents_added"] == 4
    texts = " ".join(r[0] for r in ws.query("SELECT text FROM documents"))
    assert all(t in texts for t in ("A good text file", "desalination", "Paragraph 3 about water", "very long name"))
    failed = " | ".join(out["could_not_read"])
    assert "b_protected.zip: password-protected zip" in failed and "(secret.txt)" in failed
    assert "c_damaged.zip: damaged zip" in failed and "(hurt.txt)" in failed
    left = [p.name for p in (ws.root / "inputs").rglob("*") if p.is_file()]
    assert "hurt.txt" not in left and not [n for n in left if n.endswith(".part")]  # never half a file
    # documents marked No AI: only how many could not be read (a file name can name a person)
    out = mcp_server._ingest(ws, str(src / "b_protected.zip"), None, ai_access="none")
    assert out["could_not_read"] == 1


def test_text_files_that_are_not_utf8_are_read_as_written(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    src = tmp_path / "src"
    src.mkdir()
    hu = ("Az elektrolízissel előállított zöld hidrogén vízigénye a száraz régiókban növelheti a vízhiányt. "
          "Ez különösen fontos a sivatagi exportközpontokban, ahol a tengervíz sótalanítása szükséges. ") * 6
    (src / "hungarian.txt").write_bytes(hu.encode("cp1250"))  # Notepad on a Hungarian Windows
    fr = ("L'électrolyse de l'eau à grande échelle exige beaucoup d'eau douce, très rare dans les régions arides. "
          "Le dessalement coûte cher mais reste sûr pour les usines côtières. ") * 5
    (src / "french.txt").write_bytes(fr.encode("cp1252"))
    page = ("<html><head><meta http-equiv='Content-Type' content='text/html; charset=iso-8859-2'><title>Wodór</title>"
            "</head><body><p>" + "Produkcja zielonego wodoru zwiększa zużycie wody na suchych terenach i nie jest to "
                                 "łatwe do zmiany. " * 6 + "</p></body></html>")
    (src / "polish.html").write_bytes(page.encode("iso-8859-2"))
    (src / "utf16.txt").write_bytes(("Notes on the water footprint of hydrogen in Morocco – über alles. " * 6)
                                    .encode("utf-16"))  # with its byte-order mark
    ws = home.create_project("P")
    st = ingest.ingest(ws, [src], ai_access="cloud")
    assert st["added"] == 4 and not st.get("mostly_unreadable")
    text = "\n".join(r[0] for r in ws.query("SELECT text FROM documents"))
    assert "�" not in text
    for words in ("előállított zöld hidrogén", "vízhiányt", "très rare", "côtières", "zwiększa zużycie wody",
                  "łatwe do zmiany", "über alles"):
        assert words in text, words
    assert not ws.scalar("SELECT COUNT(*) FROM passages WHERE section='unreadable'")
    assert concordance.search(ws, "vízhiányt", "any", None, "doc", 0, 5, False, 5)["total"] == 6
    assert ingest.decode_text(b"plain ascii") == "plain ascii"
    assert ingest.decode_text("Grüße".encode("cp1252")) == "Grüße"  # the same in both: Windows-1252
    # a letter that is the same in neither, and no other: the reading whose characters are letters
    assert ingest.decode_text("Wała łąka, żaba była".encode("cp1250")) == "Wała łąka, żaba była"
    # UTF-8 with one damaged byte (scraped text, a cut-off letter) stays UTF-8: only that byte is lost
    damaged = "Az önkormányzati fejlődés és a vízhiány. ".encode("utf-8") * 5 + b"\x92 end " + "ő".encode("utf-8")[:1]
    got = ingest.decode_text(damaged)
    assert got.startswith("Az önkormányzati fejlődés") and got.count("�") == 2


def test_a_password_protected_pdf_is_named_as_such(tmp_path, monkeypatch):
    from pypdf import PdfWriter

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    src = tmp_path / "src"
    src.mkdir()
    plain = tmp_path / "plain.pdf"
    make_pdf(plain, PAPER_A_PAGES, title="Water footprint of electrolytic hydrogen")
    for name, user in (("owner_only.pdf", ""), ("needs_password.pdf", "secret")):
        w = PdfWriter(clone_from=str(plain))
        w.encrypt(user_password=user, owner_password="owner", algorithm="RC4-128")
        with open(src / name, "wb") as f:
            w.write(f)
    ws = home.create_project("P")
    st = ingest.ingest(ws, [src], ai_access="cloud")
    assert st["added"] == 1 and not st.get("empty_files")  # the one without a password to open it is read
    assert st["failed"] == ["needs_password.pdf: " + ingest.PROTECTED_PDF]


def test_scanned_pages_are_found_when_pdfminer_reads_the_text(tmp_path, monkeypatch):
    """pdfminer ends every page with a form feed: split as it was, a 2-page PDF had 3 pages, so its scanned page was
    not found and not recognised."""
    pytest.importorskip("pdfminer")  # the optional extra (the release's tests run without it)
    import pdfminer.high_level

    pdf = tmp_path / "two.pdf"
    make_pdf(pdf, ["Short.", ""])
    monkeypatch.setattr(pdfminer.high_level, "extract_text",
                        lambda p: "The first page, read by pdfminer: water use of electrolysis in arid regions.\f\f")
    monkeypatch.setattr(ingest, "ocr_status", lambda max_age=60.0: {"available": True})
    asked = []

    def ocr(path, numbers, lang, should_stop=None):
        asked.append(list(numbers))
        return {1: "The second page, recognised: desalinated seawater for the plant."}

    monkeypatch.setattr(ingest, "_ocr_pages", ocr)
    raw = ingest.read_file(pdf, ingest.OcrOptions())
    assert asked == [[1]] and len(raw.pages) == 2
    assert raw.ocr_pages == 1 and raw.scanned_pages == 1 and "desalinated" in raw.pages[1]


def test_stop_reaches_the_text_recognition_of_a_long_scan(tmp_path, monkeypatch):
    pytest.importorskip("pypdfium2")
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    scan = tmp_path / "src" / "scan.pdf"
    scan.parent.mkdir()
    make_pdf(scan, [""] * 5)  # five pages without text
    monkeypatch.setattr(ingest, "ocr_status", lambda max_age=60.0: {"available": True})
    monkeypatch.setattr(ingest, "find_tesseract", lambda: "/no/tesseract")
    pages = []

    def tesseract(cmd, **kw):
        pages.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"Recognised text of a scanned page about water. " * 5, b"")

    monkeypatch.setattr(subprocess, "run", tesseract)
    stop = {"now": False}

    def should_stop():
        if len(pages) >= 2:
            stop["now"] = True
        return stop["now"]

    ws = home.create_project("P")
    st = ingest.ingest(ws, [scan.parent], ai_access="cloud", should_stop=should_stop)
    assert st.get("stopped") and len(pages) == 2  # stopped before the third page, not after the fifth
    assert not ws.scalar("SELECT COUNT(*) FROM documents")


# ---------------------------------------------------------------------------------------------
# 9. glossary terms and an embedding model on another computer
# ---------------------------------------------------------------------------------------------
class Embedder:
    def __init__(self, url: str):
        self.base_url, self.model, self.sent = url, "fake-embed", []

    def embed(self, texts):
        self.sent += list(texts)
        return [[float(len(t) % 7), float(sum(map(ord, t)) % 11), 1.0] for t in texts]


def test_glossary_terms_of_restricted_documents_stay_off_another_computer(mixed, tmp_path):
    pytest.importorskip("numpy")
    ws, ids = mixed
    extra = tmp_path / "licensed"  # two licensed studies share a term no other document has
    extra.mkdir()
    for i in range(2):
        (extra / f"study_{i}.txt").write_text((f"Study {i}. The Zqxsecret compound lowers the water use of electrolysis. "
                                               "The Zqxsecret compound is made in Morocco. ") * 4)
    ingest.ingest(ws, [extra], ai_access="local")
    terms.build(ws)
    secret = [r[0] for r in ws.query("SELECT term_id FROM terms WHERE label LIKE '%zqx%'")]
    assert secret, "no restricted term in the glossary: the test proves nothing"
    cloud = [d for d, lv in access.levels(ws).items() if lv == "cloud"]
    assert not terms.terms_in_docs(ws, secret, cloud)
    far = Embedder("http://10.1.2.3:11434")
    terms.meaning_variants(ws, far)
    assert far.sent and not [t for t in far.sent if "zqx" in t.lower()]
    near = Embedder("http://localhost:11434")  # on this computer: every term may be embedded
    terms.meaning_variants(ws, near)
    assert any("zqx" in t.lower() for t in near.sent)
