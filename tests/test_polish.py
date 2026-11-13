"""0.18.0: fixes from the audit of stages 1 and 2 (private until shared, the shared folder); each test failed before
its fix.
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import access, claimcheck, ingest, sharing, sync
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import folder
from enlens_claims.sync.common import text_fp
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_folder_privacy import _everything
from test_folder_robustness import _bundles, _note_here, _note_round, _upto, started  # noqa: F401  (fixture)
from test_shared_folder import _check, _has, _join, _round, pair, shared_dir, trio  # noqa: F401  (fixtures)


def _interview(p: Person, tmp_path: Path) -> tuple[str, str, str, str]:
    """A document with a confidential remark, read by a shared check: (doc_id, sha1, text_fp, hyp_id)."""
    src = tmp_path / f"interviews-{p.name}"
    src.mkdir()
    (src / "short interview.txt").write_text("Interview with the mayor, spring 2026\n\n"
                                             "Electrolysers in the valley create local jobs for welders. "
                                             "The mayor mentioned the zebrafish permit in confidence.")
    with p:
        ingest.ingest(p.ws, [src])
        doc, sha, text = p.ws.query("SELECT doc_id, sha1, text FROM documents WHERE path LIKE "
                                    "'%short interview.txt'")[0]
        fp = text_fp(text)
        hid = claimcheck.check_hypothesis(p.ws, "Electrolysers create local jobs.", BaselineBackend(), "baseline",
                                          k=1, per_doc=1, doc_ids=[doc])
        sharing.share(p.ws, [{"kind": "check", "key": hid}])
    return doc, sha, fp, hid


def _words(shared_dir: Path, word: bytes) -> list[str]:
    return [n for n, d in _everything(shared_dir) if word in d]


# --- privacy: the switch, turned on after the documents went ---------------------------------------------------------
def test_the_switch_turned_on_later_takes_the_documents_words_out_of_this_copys_subfolder(pair, shared_dir, tmp_path):
    anna, ben = pair
    doc, sha, fp, hid = _interview(anna, tmp_path)
    with anna:
        access.set_documents(anna.ws, [doc], "none")
    _round(anna)
    assert _words(shared_dir, b"zebrafish")  # the switch is off: documents of every AI setting travel
    assert list(shared_dir.rglob(folder.reading_name(doc, fp))) and list(shared_dir.rglob(f"{sha}.*"))
    with anna:
        folder.set_keep_out(anna.ws, True)
    _round(anna)
    assert _words(shared_dir, b"zebrafish") == []
    assert not list(shared_dir.rglob(folder.reading_name(doc, fp))) and not list(shared_dir.rglob(f"{sha}.*"))
    # what Anna shared is still there for a colleague, whole: Ben starts at her new start
    _round(ben)
    with ben:
        assert _has(ben.ws, hid)


def test_a_document_marked_for_no_ai_while_the_switch_is_on_leaves_the_folder(pair, shared_dir, tmp_path):
    anna, ben = pair
    with anna:
        folder.set_keep_out(anna.ws, True)
    doc, sha, fp, hid = _interview(anna, tmp_path)
    _round(anna)
    assert _words(shared_dir, b"zebrafish")  # not marked yet
    with anna:
        access.set_documents(anna.ws, [doc], "local")
    _round(anna)
    assert _words(shared_dir, b"zebrafish") == []


# --- privacy: the switch and the AI work that names a kept-out document only through something else ----------------
def test_reviews_of_ai_work_on_a_kept_out_document_and_links_that_quote_it_stay(loaded):
    ws = loaded
    doc, pid, text = ws.query("SELECT doc_id, passage_id, text FROM passages LIMIT 1")[0]
    other, otext = ws.query("SELECT doc_id, text FROM passages WHERE doc_id != ? LIMIT 1", (doc,))[0]
    quote, oquote = " ".join(text.split()[:6]), " ".join(otext.split()[:6])
    with ws.connect() as cx:
        cx.execute("INSERT INTO claims(claim_id, task_id, doc_id, passage_id, claim) VALUES ('c9', 'extract:x', ?, ?, "
                   "'what the document says')", (doc, pid))
        cx.execute("INSERT INTO claim_targets(claim_id, target, direction) VALUES ('c9', '7.2', 'positive')")
        cx.execute("INSERT INTO reviews(item_kind, item_id, field, proposed, decision, corrected, decided_at) VALUES "
                   "('claim', 'c9', 'claim', 'what the document says', 'correct', 'what it really says', '2026-11-11')")
        cx.execute("INSERT INTO concept_links VALUES ('t1', 't2', 'same', 'abbreviation', 1.0, ?, NULL, NULL, 'now')",
                   (quote,))
        cx.execute("INSERT INTO concept_links VALUES ('t3', 't4', 'same', 'abbreviation', 1.0, ?, NULL, NULL, 'now')",
                   (oquote,))

    def got(kept_out):
        rows = sharing.ProjectRows(ws._conn(), ws.root, kept_out)
        out = {}
        for t, rid, *_ in rows.scan():
            if t in ("reviews", "claim_targets", "concept_links", "claims"):
                out.setdefault(t, []).append(rows.fetch(t, [rid])[0])
        return out

    kept = got({doc})
    assert not kept.get("claims") and not kept.get("reviews") and not kept.get("claim_targets")
    assert [(r["a"], r["b"]) for r in kept["concept_links"]] == [("t3", "t4")]  # the other document's link goes
    free = got(set())  # without the switch everything goes, as in a zip
    assert len(free["reviews"]) == 1 and len(free["claim_targets"]) == 1 and len(free["concept_links"]) == 2


# --- a colleague held up for ever: the writer's copy mends it --------------------------------------------------------
def _head(shared_dir: Path, p: Person) -> dict:
    return json.loads((_bundles(shared_dir, p).parent / "head.json").read_text(encoding="utf-8"))


def test_a_bundle_damaged_where_it_was_written_is_mended_by_its_writer(started, shared_dir):
    anna, ben = started
    seq = _note_round(anna, anna.h2, "seen once")
    f = _bundles(shared_dir, anna) / f"{seq:06d}.zip"
    f.write_bytes(f.read_bytes()[:200])  # the disk, or the cloud service, lost most of it
    with ben:
        out = folder.sync_now(ben.ws)
    assert [x["kind"] for x in out["problems"]] == ["arriving"] and _note_here(ben, anna.h2) is None
    waiting = json.loads((_bundles(shared_dir, ben).parent / "waiting.json").read_text(encoding="utf-8"))
    assert waiting[anna.id]["seq"] == seq and waiting[anna.id]["epoch"] == _head(shared_dir, anna)["epoch"]
    before = _head(shared_dir, anna)
    w = _round(anna)["wrote"]  # Anna's copy sees that Ben waits for a bundle that is not whole here either
    assert w["snapshot"] and w["seq"] == seq + 1 and _head(shared_dir, anna)["epoch"] != before["epoch"]
    _round(ben)
    assert _note_here(ben, anna.h2) == "seen once" and _upto(ben, anna) == seq + 1
    assert not (_bundles(shared_dir, ben).parent / "waiting.json").exists()  # nothing holds Ben up any more
    assert not _round(anna)["wrote"]["snapshot"]  # and Anna does not begin again a second time


def test_a_bundle_only_late_for_a_colleague_starts_nobody_afresh(started, shared_dir, tmp_path):
    anna, ben = started
    seq = _note_round(anna, anna.h2, "seen once")
    f = _bundles(shared_dir, anna) / f"{seq:06d}.zip"
    away = tmp_path / "not delivered yet.zip"
    f.rename(away)
    with ben:
        assert [x["kind"] for x in folder.sync_now(ben.ws)["problems"]] == ["gap"]
    away.rename(f)  # (it is whole on Anna's computer: only Ben's cloud service is behind)
    assert _round(anna)["wrote"]["seq"] is None
    _round(ben)
    assert _note_here(ben, anna.h2) == "seen once"


def test_a_reading_no_copy_can_write_again_no_longer_holds_a_colleague_up(started, shared_dir, tmp_path):
    anna, ben = started
    doc, sha, fp, hid = _interview(anna, tmp_path)
    _round(anna)
    reading = next(shared_dir.rglob(folder.reading_name(doc, fp)))
    reading.unlink()  # removed from the folder by hand
    with anna:
        anna.ws.remove_document(doc)  # and Anna no longer holds the document
    with ben:
        out = folder.sync_now(ben.ws)
    assert [x["kind"] for x in out["problems"]] == ["documents"]
    with ben:
        assert not _has(ben.ws, hid)
    assert _round(anna)["wrote"]["snapshot"]
    _round(ben)
    with ben:
        assert _has(ben.ws, hid)  # the check came, as a record of a document that is no longer in the project


def test_a_reading_removed_by_hand_is_written_again_without_starting_afresh(started, shared_dir, tmp_path):
    anna, ben = started
    doc, sha, fp, hid = _interview(anna, tmp_path)
    _round(anna)
    next(shared_dir.rglob(folder.reading_name(doc, fp))).unlink()
    with ben:
        assert [x["kind"] for x in folder.sync_now(ben.ws)["problems"]] == ["documents"]
    w = _round(anna)["wrote"]
    assert w["readings"] == 1 and not w["snapshot"]
    _round(ben)
    with ben:
        assert _has(ben.ws, hid) and ben.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))


def test_a_colleague_never_writes_back_a_document_just_taken_out_of_the_folder(pair, shared_dir, tmp_path):
    anna, ben = pair
    with anna:
        folder.set_keep_out(anna.ws, True)
    doc, sha, fp, hid = _interview(anna, tmp_path)
    _round(anna)
    _round(ben)  # Ben holds the document now, as one any AI may read
    with anna:
        access.set_documents(anna.ws, [doc], "local")
    _round(anna)
    assert _words(shared_dir, b"zebrafish") == []
    _round(ben)  # Ben's copy hears of the stricter setting before it writes anything
    assert _words(shared_dir, b"zebrafish") == []
    with ben:
        assert access.levels(ben.ws, [doc], budget=False)[doc] == "local"


# --- an item its owner removed ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("backwards", [False, True])
def test_a_check_its_owner_removed_is_never_passed_on_by_a_colleague_who_keeps_it(trio, shared_dir, monkeypatch,
                                                                                    backwards):
    from test_shared_folder import _bundle_rows

    anna, ben, carol = trio
    real = folder._people_dirs  # (colleagues are read in the order of their ids: either may come first)
    monkeypatch.setattr(folder, "_people_dirs", lambda team: sorted(real(team), reverse=backwards))
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    _round(anna)
    _round(ben)
    with anna:
        claimcheck.delete_hypothesis(anna.ws, h2)
    _round(anna)
    out = _round(ben)
    _round(ben)
    with ben:
        assert _has(ben.ws, h2)  # nothing is taken from anyone
        assert sharing.state(ben.ws._conn(), "check", h2)["state"] == "withdrawn"  # but it is no longer sent
    assert out["read"][0]["report"]["shares"]["withdrawn"] == ["Electrolysers create local jobs."]
    ben_dir = _bundles(shared_dir, ben).parent
    assert not _bundle_rows(ben_dir, "SELECT 1 FROM hypotheses WHERE hyp_id=?", (h2,))
    _join(carol, shared_dir)
    _round(carol)
    with carol:
        assert not _has(carol.ws, h2)
        assert carol.ws.scalar("SELECT 1 FROM sync_removed WHERE kind='check' AND key=?", (h2,))  # known as removed
    # Ben removing his copy of a check of Anna's decides nothing about it
    with anna:
        h3 = _check(anna.ws, "Hydrogen needs water.")
        sharing.share(anna.ws, [{"kind": "check", "key": h3}])
    _round(anna)
    _round(ben)
    _round(carol)
    with ben:
        claimcheck.delete_hypothesis(ben.ws, h3)
    _round(ben)
    _round(carol)
    _round(anna)
    with carol:
        assert _has(carol.ws, h3) and sharing.state(carol.ws._conn(), "check", h3)["state"] == "shared"
    with anna:
        assert _has(anna.ws, h3) and sharing.state(anna.ws._conn(), "check", h3)["state"] == "shared"


# --- a zip for a colleague ------------------------------------------------------------------------------------------
def test_a_zip_for_a_colleague_names_no_folder_of_this_computer_for_a_document(anna_and_ben, tmp_path):
    from enlens_claims import bundle

    anna, ben = anna_and_ben
    doc, sha, fp, hid = _interview(anna, tmp_path)
    with anna:
        gone = anna.ws.query("SELECT doc_id, path FROM documents WHERE doc_id != ? ORDER BY doc_id LIMIT 1", (doc,))[0]
        Path(gone["path"]).unlink()  # its file is no longer where it was added from
        out = tmp_path / "for-ben.zip"
        bundle.export_project(anna.ws, out, scope="shared")
    db = tmp_path / "sent.sqlite"
    with zipfile.ZipFile(out) as zf:
        db.write_bytes(zf.read("enlens.sqlite"))
    cx = sqlite3.connect(db)
    try:
        assert [r[0] for r in cx.execute("SELECT path FROM documents WHERE path IS NOT NULL")] == []
    finally:
        cx.close()
    ben.bring_in(out)
    with ben:
        path = ben.ws.scalar("SELECT path FROM documents WHERE doc_id=?", (doc,))
        assert path and Path(path).is_file() and Path(path).is_relative_to(Path(ben.ws.root).resolve())


def test_removing_a_copy_of_a_check_whose_maker_nobody_knows_takes_nothing_back(pair):
    """Projects exchanged before 0.18: every item counts as shared, and for the oldest nobody knows who made them."""
    anna, ben = pair
    for p in (anna, ben):
        with p, p.ws.connect() as cx:
            cx.execute("INSERT OR REPLACE INTO shares(kind, key, state, owner, by, at, title) VALUES ('check', ?, "
                       "'shared', NULL, NULL, NULL, 'old')", (anna.hid,))
    _round(anna)
    _round(ben)
    with ben:
        claimcheck.delete_hypothesis(ben.ws, anna.hid)
    _round(ben)
    _round(anna)
    with anna:
        assert _has(anna.ws, anna.hid) and sharing.state(anna.ws._conn(), "check", anna.hid)["state"] == "shared"


# --- the folder does not keep what nobody reads again ---------------------------------------------------------------
def test_bundles_before_a_new_start_are_removed(started, shared_dir):
    anna, ben = started
    _note_round(anna, anna.h2, "seen once")
    old = sorted(f.name for f in _bundles(shared_dir, anna).glob("*.zip"))
    assert len(old) == 2
    with anna, anna.ws.connect() as cx:
        cx.execute("DELETE FROM sync_written WHERE kind != 'head'")  # (this copy lost its record: it starts afresh)
    with anna:
        claimcheck.set_note(anna.ws, anna.h2, "seen twice")
    w = _round(anna)["wrote"]
    assert w["snapshot"] and [f.name for f in _bundles(shared_dir, anna).glob("*.zip")] == [f"{w['seq']:06d}.zip"]
    _round(ben)
    assert _note_here(ben, anna.h2) == "seen twice"


# --- the stricter AI setting holds for a document a colleague adds by hand ------------------------------------------
def test_a_kept_out_document_a_colleague_adds_by_hand_is_as_strict_there_and_stays_out(pair, shared_dir, tmp_path):
    anna, ben = pair
    with anna:
        folder.set_keep_out(anna.ws, True)
    doc, sha, fp, hid = _interview(anna, tmp_path)
    with anna:
        access.set_documents(anna.ws, [doc], "none")
    _round(anna)
    _round(ben)  # Ben hears of the document (its title, that Anna keeps it out), not its words
    assert _words(shared_dir, b"zebrafish") == []
    with ben:
        ingest.ingest(ben.ws, [tmp_path / f"interviews-{anna.name}"])  # he adds the file himself
        assert ben.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))
        assert access.levels(ben.ws, [doc], budget=False)[doc] == "none"  # at once: no AI of his reads it meanwhile
    _round(ben)
    assert _words(shared_dir, b"zebrafish") == []


# --- what was taken back leaves the folder ----------------------------------------------------------------------------
def test_an_item_taken_back_leaves_the_bundles_its_owner_and_a_colleague_wrote(pair, shared_dir):
    anna, ben = pair
    with anna:
        hid = _check(anna.ws, "A hunch about desalination brine.")
        sharing.share(anna.ws, [{"kind": "check", "key": hid}])
    _round(anna)
    _round(ben)
    with ben:  # Ben adds to the check: his copy writes it too
        claimcheck.set_note(ben.ws, hid, "Ben agrees")
    _round(ben)
    _round(anna)
    assert len(_words(shared_dir, b"desalination brine")) >= 2
    with anna:
        # roles (H5, DESIGN-roles §4.9): Anna's own check keeps her version; Ben's comes in beside it, a sync-clash
        # copy, which is an item of its own in her list: she takes back both
        assert _note_here(anna, hid) is None
        copies = [k for k, v in sync.copies_of(anna.ws, "check").items() if v["of"] == hid]
        assert len(copies) == 1 and _note_here(anna, copies[0]) == "Ben agrees"
        sharing.unshare(anna.ws, [{"kind": "check", "key": k} for k in [hid] + copies])
    _round(anna)
    _round(ben)
    assert _words(shared_dir, b"desalination brine") == []
    with ben:
        assert _has(ben.ws, hid)  # what Ben has stays with him
        assert sharing.state(ben.ws._conn(), "check", hid)["state"] == "withdrawn"


# --- from an independent review of the fixes above --------------------------------------------------------------------
def test_a_colleague_does_not_put_back_what_was_taken_out_before_hearing_why(pair, shared_dir, tmp_path):
    """The cloud service may deliver that a reading is gone before it delivers its writer's new start."""
    anna, ben = pair
    with anna:
        folder.set_keep_out(anna.ws, True)
    doc, sha, fp, hid = _interview(anna, tmp_path)
    _round(anna)
    _round(ben)  # Ben holds the document, as one any AI may read, and has seen its reading in the folder
    with anna:
        access.set_documents(anna.ws, [doc], "local")
    _round(anna)
    hers = _bundles(shared_dir, anna).parent
    late = tmp_path / "not delivered yet"
    late.mkdir()
    for f in [hers / "head.json", *sorted((hers / "bundles").glob("*.zip"))]:
        f.rename(late / f.name)
    _round(ben)
    assert _words(shared_dir, b"zebrafish") == []
    (late / "head.json").rename(hers / "head.json")
    for f in sorted(late.glob("*.zip")):
        f.rename(hers / "bundles" / f.name)
    _round(ben)
    assert _words(shared_dir, b"zebrafish") == []
    with ben:
        assert access.levels(ben.ws, [doc], budget=False)[doc] == "local"


def test_the_switch_stays_in_force_while_a_colleagues_file_cannot_be_read(pair, shared_dir, tmp_path):
    anna, ben = pair
    with anna:
        folder.set_keep_out(anna.ws, True)
    _round(anna)
    _round(ben)
    with ben:
        assert folder.status(ben.ws)["keep_out"]["in_force"]
    src = tmp_path / "bens"
    src.mkdir()
    (src / "ben local.txt").write_text("Ben's notes for the local model\n\n" +
                                       "Notes for the local model only, about the zebrafish permit. " * 10)
    with ben:
        ingest.ingest(ben.ws, [src])
        bdoc = ben.ws.scalar("SELECT doc_id FROM documents WHERE path LIKE '%ben local.txt'")
        access.set_documents(ben.ws, [bdoc], "local")
    pj = _bundles(shared_dir, anna).parent / "person.json"
    held = pj.read_bytes()
    pj.write_bytes(held[:20])  # the cloud service is replacing it just now
    _round(ben)
    assert _words(shared_dir, b"zebrafish") == []
    pj.write_bytes(held)


def test_a_document_this_copy_removed_is_still_kept_out_of_what_it_writes(pair, shared_dir, tmp_path):
    anna, ben = pair
    with anna:
        folder.set_keep_out(anna.ws, True)
    doc, sha, fp, hid = _interview(anna, tmp_path)
    _round(anna)
    _round(ben)
    with ben:
        claimcheck.set_note(ben.ws, hid, "Ben agrees")  # his copy writes the check too, with what it handed to the AI
    _round(ben)
    assert any(ben.id in n for n in _words(shared_dir, b"zebrafish"))
    with ben:
        ben.ws.remove_document(doc)
    _round(ben)
    with anna:
        access.set_documents(anna.ws, [doc], "local")
    _round(anna)
    _round(ben)
    with ben:
        claimcheck.set_note(ben.ws, hid, "Ben agrees twice")
    _round(ben)
    assert _words(shared_dir, b"zebrafish") == []


def test_a_shared_check_its_owner_removed_leaves_the_owners_bundles(pair, shared_dir):
    anna, ben = pair
    with anna:
        hid = _check(anna.ws, "A hunch about desalination brine.")
        sharing.share(anna.ws, [{"kind": "check", "key": hid}])
    _round(anna)
    _round(ben)
    with anna:
        claimcheck.delete_hypothesis(anna.ws, hid)
    w = _round(anna)["wrote"]
    assert w["snapshot"]
    from test_shared_folder import _bundle_rows

    assert not _bundle_rows(_bundles(shared_dir, anna).parent, "SELECT 1 FROM hypotheses WHERE hyp_id=?", (hid,))
    assert not _round(anna)["wrote"]["snapshot"]  # once
    _round(ben)
    with ben:
        assert _has(ben.ws, hid) and sharing.state(ben.ws._conn(), "check", hid)["state"] == "withdrawn"


def test_a_setting_two_colleagues_both_loosen_stays_loosened(pair, shared_dir):
    anna, ben = pair
    with anna:
        doc = anna.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        access.set_documents(anna.ws, [doc], "local")
    _round(anna)
    _round(ben)
    _round(anna)
    with ben:
        assert access.levels(ben.ws, [doc], budget=False)[doc] == "local"
    for p in (anna, ben):  # marked by mistake: both set it back
        with p:
            access.set_documents(p.ws, [doc], "cloud")
    for p in (anna, ben, anna, ben):
        _round(p)
    # roles (review H1): Ben's own proposal was answered by nobody; the owner set it so herself. That is not the event
    # an accept of his made, so his copy is offered it rather than set: one click of his
    from enlens_claims import ownership

    with ben:
        assert access.levels(ben.ws, [doc], budget=False)[doc] == "local"
        assert [o["doc"] for o in ownership.view(ben.ws)["offers"]] == [doc]
        ownership.answer_loosening(ben.ws, [doc], True)
    for p in (anna, ben):
        with p:
            assert access.levels(p.ws, [doc], budget=False)[doc] == "cloud"


def test_a_reading_damaged_in_the_folder_is_written_again_by_the_copy_that_wrote_it(started, shared_dir, tmp_path):
    anna, ben = started
    doc, sha, fp, hid = _interview(anna, tmp_path)
    _round(anna)
    reading = next(shared_dir.rglob(folder.reading_name(doc, fp)))
    whole = reading.read_bytes()
    reading.write_bytes(whole[:100])
    with ben:
        out = folder.sync_now(ben.ws)
    assert [x["kind"] for x in out["problems"]] == ["documents"]
    _round(anna)
    assert reading.read_bytes() != whole[:100]
    _round(ben)
    with ben:
        assert _has(ben.ws, hid) and ben.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))


def test_a_kept_out_document_that_comes_in_a_third_colleagues_zip_is_as_strict(trio, shared_dir, tmp_path):
    anna, ben, carol = trio
    with anna:
        folder.set_keep_out(anna.ws, True)
    doc, sha, fp, hid = _interview(anna, tmp_path)
    with anna:
        access.set_documents(anna.ws, [doc], "none")
    _round(anna)
    _round(ben)  # Ben has heard of the document; he does not hold it
    with carol:  # Carol added the same file to her copy long ago, and nobody told her copy
        ingest.ingest(carol.ws, [tmp_path / f"interviews-{anna.name}"])
        assert access.levels(carol.ws, [doc], budget=False)[doc] == "cloud"
    ben.bring_in(carol.send())
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))
        assert access.levels(ben.ws, [doc], budget=False)[doc] == "none"


def test_a_file_the_cloud_service_holds_does_not_keep_the_rest_in_the_folder(pair, shared_dir, tmp_path, monkeypatch):
    anna, ben = pair
    doc, sha, fp, hid = _interview(anna, tmp_path)
    with anna:
        access.set_documents(anna.ws, [doc], "none")
    _round(anna)
    with anna:
        folder.set_keep_out(anna.ws, True)
    real = Path.unlink
    locked = {"on": True}

    def unlink(self, missing_ok=False):
        if locked["on"] and self.name == "000001.zip":
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    with anna:
        out = folder.sync_now(anna.ws)
    assert [x["kind"] for x in out["problems"]] == ["unreachable"] and out["wrote"] is None
    left = _words(shared_dir, b"zebrafish")
    assert left and all("000001.zip" in n for n in left)  # its reading and its file went all the same
    locked["on"] = False
    _round(anna)
    assert _words(shared_dir, b"zebrafish") == []
