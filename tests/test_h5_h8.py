"""H5 and H8 (DESIGN-roles §4.9): the proofs of the deep dive (design/roles 36d3b53, `test_0_17_2_proofs_h5_h8.py`),
turned round. Each `test_poc_…` passed while the weakness was there; renamed, its last assertions are now the other way.

H5 (sync/merge.py, the branch "yours is older"): a colleague's version never replaces this person's own check or set
of themes; it comes in beside it (a sync clash), whatever the sender's list of states says. A unit that is not this
person's own (its maker's later version), or that this copy took from that sender and did not change since
(`sync_from`), is still brought up to date, and the version it had is kept for Compare and Restore.

H8 (codebooks.follow_merged, sync/codebook_merge.py): a codebook's list of renames and merges is checked (events that
do not fit are skipped and counted), following never deletes a label, and only the codebook's own maker moves this
copy's labels at once; anyone else's changes wait as an offer (*Follow* / *Keep mine*).
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

from enlens_claims import claimcheck, codebooks, profile
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync.fingerprints import _canon, _check_unit, _fingerprints
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_codebook_merge import _edit, _set, shared_codebook  # noqa: F401  (fixture)

BENS = "Ben's own later work on his check"
ANNAS = "Anna's version"


def _rezip(src: Path, out: Path, change) -> Path:
    """A colleague's zip, changed with ordinary tools: unpacked, `change(folder)`, packed again."""
    work = out.with_suffix("")
    work.mkdir()
    with zipfile.ZipFile(src) as zf:
        zf.extractall(work)
    change(work)
    with zipfile.ZipFile(out, "w") as zf:
        for p in sorted(work.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(work).as_posix())
    return out


# ---- H5 ------------------------------------------------------------------------------------------------------
def _bens_check_both_changed(anna: Person, ben: Person) -> str:
    """Ben makes a check of his own and sends it; Anna brings it in. Then each changes it without the other's
    version: what the merge calls "both changed it"."""
    with ben:
        hid = claimcheck.check_hypothesis(ben.ws, "Electrolyser plants create local jobs.", BaselineBackend(),
                                          "baseline", k=2)
    anna.bring_in(ben.send())
    with ben:
        claimcheck.set_note(ben.ws, hid, BENS)   # never sent to anyone
    with anna:
        assert anna.ws.scalar("SELECT COALESCE(note, '') FROM hypotheses WHERE hyp_id=?", (hid,)) == ""
        claimcheck.set_note(anna.ws, hid, ANNAS)
    return hid


def _notes(p: Person) -> list[str]:
    with p:
        return sorted(r[0] or "" for r in p.ws.query("SELECT note FROM hypotheses"))


def test_control_h5_a_check_both_changed_is_kept_twice(anna_and_ben):  # noqa: F811
    anna, ben = anna_and_ben
    hid = _bens_check_both_changed(anna, ben)
    rep = ben.bring_in(anna.send())
    assert len(rep["checks"]["clash"]) == 1 and rep["checks"]["updated"] == 0
    with ben:
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (hid,)) == BENS
    assert BENS in _notes(ben) and ANNAS in _notes(ben)


def test_h5_a_senders_list_of_states_never_replaces_the_receivers_own_check(anna_and_ben, tmp_path):  # noqa: F811
    anna, ben = anna_and_ben
    hid = _bens_check_both_changed(anna, ben)
    # the state of Ben's version, as anyone works it out who knows what it says (in a shared folder: it is there)
    with ben:
        cx = ben.ws._conn()
        fps = _fingerprints(cx)(_check_unit(cx, hid), _canon(cx))

    def claim_to_have_had_it(work: Path) -> None:
        db = sqlite3.connect(work / "enlens.sqlite")
        db.executemany("INSERT OR IGNORE INTO sync_seen(kind, key, fp) VALUES ('check', ?, ?)", [(hid, fp) for fp in fps])
        db.commit()
        db.close()

    forged = _rezip(anna.send(), tmp_path / "anna-forged.zip", claim_to_have_had_it)
    rep = ben.bring_in(forged)
    # Ben's own check keeps his version; Anna's comes in beside it as a sync-clash copy
    assert rep["checks"]["updated"] == 0 and len(rep["checks"]["clash"]) == 1
    with ben:
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (hid,)) == BENS
    assert BENS in _notes(ben) and ANNAS in _notes(ben)


def test_h5_a_check_of_its_maker_is_still_brought_up_to_date_and_the_version_before_is_kept(anna_and_ben):  # noqa: F811
    """Anna's own check, in Ben's copy: her later version replaces the one there (it is not Ben's), and the version his
    copy had is kept for Compare and Restore."""
    anna, ben = anna_and_ben
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's later note")
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["clash"]
    with ben:
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (anna.hid,)) == "Anna's later note"
        assert ben.ws.scalar("SELECT person FROM sync_from WHERE kind='check' AND key=?", (anna.hid,)) == anna.id
        labels = [r[0] for r in ben.ws.query("SELECT label FROM versions WHERE kind='check' AND key=?", (anna.hid,))]
    assert any("Anna's version" in x for x in labels), labels


def test_h5_a_check_taken_from_a_colleague_and_unchanged_since_follows_that_colleague(anna_and_ben):  # noqa: F811
    """Ben's own check, which his copy holds as Anna gave it (here: his copy lost it and took it back from her file,
    as a copy rebuilt from a colleague's does). `sync_from` says so: her later version is brought up to date."""
    anna, ben = anna_and_ben
    with ben:
        hid = claimcheck.check_hypothesis(ben.ws, "Electrolyser plants create local jobs.", BaselineBackend(),
                                          "baseline", k=2)
    anna.bring_in(ben.send())
    with ben:
        claimcheck.delete_hypothesis(ben.ws, hid)
        with ben.ws.connect() as cx:  # lost, not removed: nothing says it must stay out
            cx.execute("DELETE FROM sync_removed WHERE kind='check' AND key=?", (hid,))
    assert ben.bring_in(anna.send())["checks"]["new"] == 1
    with ben:
        assert ben.ws.scalar("SELECT person FROM sync_from WHERE kind='check' AND key=?", (hid,)) == anna.id
    with anna:
        claimcheck.set_note(anna.ws, hid, ANNAS)
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["clash"]
    with ben:
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (hid,)) == ANNAS
        # once Ben changes it himself, it is his again: Anna's next version (made on his) comes in beside it
        claimcheck.set_note(ben.ws, hid, BENS)
    anna.bring_in(ben.send())
    with anna:
        claimcheck.set_note(anna.ws, hid, ANNAS + ", again")
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["updated"] == 0 and len(rep["checks"]["clash"]) == 1


# ---- H8 ------------------------------------------------------------------------------------------------------
def _own_labels(p: Person) -> list[tuple[str, str]]:
    with p:
        return sorted((r[0], r[1]) for r in p.ws.query("SELECT passage_id, code FROM labels WHERE framework='water' AND "
                                                       "source='person'"))


def test_h8_a_colleagues_rename_waits_as_an_offer_for_the_codebooks_own_maker(shared_codebook):  # noqa: F811
    """No forgery: Anna made the codebook and labelled a passage with its code A. Ben renames A in his copy. Anna's
    codebook comes up to date, but her own label keeps A until she says *Follow*."""
    anna, ben = shared_codebook
    with anna:
        pid = anna.ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
        profile.add_label(anna.ws, "water", pid, "A")
    with ben:
        _edit(ben.ws, "water", _set("code", "A", "Ben's name for it"))
    rep = anna.bring_in(ben.send())
    assert rep["codebooks"]["updated"] == ["water"]
    assert _own_labels(anna) == [(pid, "A")]
    assert any("Follow" in line for line in rep["lines"]), rep["lines"]
    with anna:
        got = codebooks.offers(anna.ws)
        assert [(o["name"], o["from"], o["labels"]) for o in got] == [("water", ben.id, 1)]
        assert got[0]["events"] == [{"op": "rename", "from": "A", "to": "Ben's name for it"}]
        assert codebooks.answer_offer(anna.ws, "water", True)["moved"] == 1
        assert codebooks.offers(anna.ws) == []
    assert _own_labels(anna) == [(pid, "Ben's name for it")]
    anna.bring_in(ben.send())  # the same file again: no new offer
    with anna:
        assert codebooks.offers(anna.ws) == []


def test_h8_keep_mine_leaves_the_labels_and_ends_the_offer(shared_codebook):  # noqa: F811
    anna, ben = shared_codebook
    with anna:
        pid = anna.ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
        profile.add_label(anna.ws, "water", pid, "A")
    with ben:
        _edit(ben.ws, "water", _set("code", "A", "Ben's name for it"))
    anna.bring_in(ben.send())
    with anna:
        assert codebooks.answer_offer(anna.ws, "water", False)["moved"] == 0
        assert codebooks.offers(anna.ws) == []
        assert codebooks.follow(anna.ws, "water") == 0  # a later save does not move it either
    assert _own_labels(anna) == [(pid, "A")]  # it waits under Removed codes, as any label of a code that is gone


def test_h8_the_makers_rename_moves_the_labels_of_the_others_at_once(shared_codebook):  # noqa: F811
    anna, ben = shared_codebook
    with ben:
        pid = ben.ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
        profile.add_label(ben.ws, "water", pid, "A")
    with anna:
        _edit(anna.ws, "water", _set("code", "A", "Water use"))
    ben.bring_in(anna.send())
    assert _own_labels(ben) == [(pid, "Water use")]
    with ben:
        assert codebooks.offers(ben.ws) == []


def test_h8_a_list_of_changes_made_by_hand_deletes_no_label(shared_codebook, tmp_path):  # noqa: F811
    """Ben labelled one passage with A and with C. Anna's file says, in the codebook's side file, that A was merged
    into B and then taken out of B again as C. The unmerge does not fit the list (it does not give A back): it is
    skipped and counted, and no label is lost."""
    anna, ben = shared_codebook
    with ben:
        pid = ben.ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
        profile.add_label(ben.ws, "water", pid, "A")
        profile.add_label(ben.ws, "water", pid, "C")
    assert _own_labels(ben) == [(pid, "A"), (pid, "C")]
    far = "9999-01-01T00:00:00+00:00"

    def add_changes(work: Path) -> None:
        side = work / "frameworks" / "water.json"
        meta = json.loads(side.read_text(encoding="utf-8"))
        meta["events"] = list(meta.get("events") or []) + [
            {"op": "merge", "from": "A", "to": "B", "id": "forged000001", "at": far, "seq": 1},
            {"op": "unmerge", "from": "B", "to": "C", "was": "A", "id": "forged000002", "at": far, "seq": 2}]
        side.write_text(json.dumps(meta), encoding="utf-8")

    forged = _rezip(anna.send(), tmp_path / "anna-forged.zip", add_changes)
    rep = ben.bring_in(forged)
    with ben:
        still_a_code = "A" in {c["code"] for c in codebooks.load(ben.ws, "water")["codes"]}
        rows = sorted(tuple(r) for r in ben.ws.query("SELECT code, COALESCE(merged_from, '') FROM labels WHERE "
                                                     "framework='water' AND source='person'"))
    assert rep["codebooks"]["updated"] == ["water"] and still_a_code
    assert rep["codebooks"]["skipped_events"] == 1
    # the merge is in the file of the codebook's maker (Anna): Ben's label A follows it into B, marked as merged
    # from A (so a restore gives it back), as any merge does. Two labels before, two after
    assert rows == [("B", "A"), ("C", "")]


def test_h8_following_an_unmerge_never_deletes_a_label(shared_codebook):  # noqa: F811
    """The one DELETE of `_follow_one` was an unmerge where the label is there under the name it goes back to
    already. The label now stays."""
    from enlens_claims.profile import label_id

    anna, _ben = shared_codebook
    with anna:
        ws = anna.ws
        pid = ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
        with ws.connect() as cx:
            for code, mf in (("B", "A"), ("A", None)):
                cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, source, merged_from, "
                           "created_at) VALUES (?,?,?,?,?,'person',?,'2026-01-01')",
                           (label_id("water", pid, code, "person"), pid, pid.split(":")[0], "water", code, mf))
            codebooks._follow_one(cx, "water", {"op": "unmerge", "from": "B", "to": "A", "was": "A", "id": "x",
                                                "at": "2999-01-01"}, label_id)
        assert ws.scalar("SELECT COUNT(*) FROM labels WHERE framework='water' AND source='person'") == 2


def test_h8_the_list_is_checked():
    ev = [{"op": "rename", "from": "A", "to": "A", "id": "1"},                       # from == to
          {"op": "merge", "from": "A", "to": "B", "id": "2", "uid": "u1"},
          {"op": "rename", "from": "B", "to": "Bx", "id": "3", "uid": "u2"},
          {"op": "unmerge", "from": "Bx", "to": "A", "was": "A", "id": "4", "uid": "u1"},  # B renamed since: fits
          {"op": "unmerge", "from": "B", "to": "C", "was": "A", "id": "5"},           # does not give A back
          {"op": "unmerge", "from": "Q", "to": "Z", "was": "Z", "id": "6"},           # no merge of Z before it
          {"op": "unmerge", "from": "Bx", "to": "A", "was": "A", "id": "7", "uid": "u1"},  # its merge was undone
          {"op": "merge", "from": "D", "to": "Bx", "id": "8", "uid": "u3"},
          {"op": "unmerge", "from": "Bx", "to": "D2", "was": "D", "id": "9", "uid": "u3"}]  # the app's: back as D2
    ok, skipped = codebooks.checked_events(ev)
    assert [e["id"] for e in ok] == ["2", "3", "4", "8", "9"] and skipped == ["1", "5", "6", "7"]
