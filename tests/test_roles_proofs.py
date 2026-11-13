"""Roles (DESIGN-roles §6.1): the deep dive's proofs of concept turned round (SYNC-1, SYNC-2, H3).

Each proof showed what one copy could do to the others by editing its own database with any SQLite tool. They passed
while the weakness was there; turned round, they say what the rules do now:
- SYNC-1: a back-dated record no longer makes its writer the owner anywhere: who the owner is follows each copy's own
  pins, never a clock; the other record is a question to each copy's person.
- SYNC-2: a forged owner opens nothing to Claude in anyone else's copy (its rows do not count there), and nothing is
  even offered.
- H3: a row of the documents written in the real owner's name is refused by the owner's copy, recorded, and answered
  with her own row above it; a third copy is only *offered* the looser setting meanwhile, and a removal is restorable
  from the third copy's own archive (removed.py).
"""
from __future__ import annotations

import json

import pytest

from enlens_claims import ownership
from owner_helpers import add_doc, has, level, set_level, sync, view
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_owner import shared_dir, team  # noqa: F401  (fixtures)


def _forge_owner(p: Person, follow: bool = False) -> None:
    """What a collaborator does with any SQLite tool: one back-dated record saying they made the project (and, with
    `follow`, their own copy made to follow it, which a file cannot carry to anyone)."""
    with p:
        with p.ws.connect() as cx:
            cx.execute("INSERT OR REPLACE INTO ownership(seq, owner, by, at, kind, after, why) VALUES "
                       "(1, ?, ?, '2000-01-01T00:00:00+00:00', 'made', NULL, NULL)", (p.id, p.id))
            if follow:
                cx.execute("DELETE FROM owner_pins")
                cx.execute("INSERT INTO owner_pins(seq, by, owner, state, at) VALUES (1, ?, ?, 'followed', '2000')",
                           (p.id, p.id))


def _forge_canon(p: Person, doc: str, **change) -> str:
    """A row of the documents in the real owner's name, with a number far above any other."""
    with p:
        with p.ws.connect() as cx:
            cur = cx.execute("SELECT * FROM canon WHERE doc=? ORDER BY owner_seq DESC, n DESC LIMIT 1", (doc,))
            cols = [c[0] for c in cur.description]
            r = dict(zip(cols, cur.fetchone()))
            n = 10 ** 6
            bump = change.pop("_bump", ())
            r.update(n=n, at="2030-01-01T00:00:00+00:00", **change)
            for part in bump:
                r[f"{part}_n"] = n
            if "ai_access" in change:
                r["ai_hist_json"] = json.dumps(json.loads(r["ai_hist_json"] or "[]") + [[n, change["ai_access"]]])
            cx.execute(f"INSERT OR REPLACE INTO canon({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       [r[c] for c in cols])
            return r["by"]


def _archives_built() -> bool:
    """Whether removed.py (piece P3) is built here: its stubs raise NotImplementedError."""
    import inspect

    from enlens_claims import removed

    return "NotImplementedError" not in inspect.getsource(removed.archive)


needs_archives = pytest.mark.skipif(not _archives_built(), reason="removed.py (P3) is not built on this branch yet: "
                                                                  "the archive of a removal is its stub")


# ---- SYNC-1 --------------------------------------------------------------------------------------------------
def test_a_backdated_record_makes_nobody_the_owner_and_is_a_question(team):
    anna, ben, carol = team
    assert view(ben)["owner"]["id"] == anna.id
    _forge_owner(carol)
    sync(carol, ben, anna)
    for p in team:
        assert view(p)["owner"]["id"] == anna.id, p.name
    for p in (anna, ben):
        assert [(q["kind"], q["owner"], q["now"]) for q in view(p)["questions"]] == [("founder", carol.id, anna.id)]
    with ben:  # *Keep Anna*: not asked again
        ownership.keep_owner(ben.ws, 1, carol.id)
    assert not view(ben)["questions"] and view(ben)["owner"]["id"] == anna.id


# ---- SYNC-2 --------------------------------------------------------------------------------------------------
def test_a_forged_owner_opens_nothing_to_claude_in_another_copy_and_offers_nothing(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="local")   # the owner's: only a local AI may read it
    sync(anna, ben, carol)
    assert level(ben, doc) == level(carol, doc) == level(anna, doc) == "local"
    _forge_owner(carol, follow=True)
    with carol:
        ownership.settle(carol.ws)
    assert view(carol)["owner"]["id"] == carol.id            # only in her own copy
    set_level(carol, doc, "cloud")                           # in her own copy, with the app's own button
    sync(carol, ben, anna, rounds=3)
    assert level(ben, doc) == level(anna, doc) == "local"
    assert not view(ben)["offers"] and not view(anna)["offers"]
    assert view(ben)["owner"]["id"] == view(anna)["owner"]["id"] == anna.id


def test_a_forged_owner_removes_a_first_zip_document_from_nobody_else(team, tmp_path):
    anna, ben, carol = team
    with anna:
        doc = sorted(r[0] for r in anna.ws.query("SELECT doc_id FROM documents"))[0]   # of the first zip
    assert has(ben, doc) and has(carol, doc)
    _forge_owner(carol, follow=True)
    with carol:
        ownership.settle(carol.ws)
        carol.ws.remove_document(doc, why="x")
    sync(carol, ben, anna, rounds=3)
    assert has(ben, doc) and has(anna, doc) and not has(carol, doc)


# ---- H3: a row of the documents in the real owner's name -------------------------------------------------------
def test_a_canon_row_in_the_owners_name_is_offered_not_set_and_answered_by_the_owner(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="local")
    sync(anna, ben, carol)
    assert level(anna, doc) == level(ben, doc) == level(carol, doc) == "local"
    by = _forge_canon(carol, doc, ai_access="cloud", _bump=("ai",))
    assert by == anna.id
    sync(carol, ben)
    assert level(ben, doc) == "local"                                         # not set: offered
    assert [(o["doc"], o["to"]) for o in view(ben)["offers"]] == [(doc, "cloud")]
    sync(anna)
    with anna:
        cx = anna.ws._conn()
        assert cx.execute("SELECT via, state FROM sync_refused WHERE kind='canon' AND key=?", (doc,)).fetchone()[:] \
            == (carol.id, "new")
        assert cx.execute("SELECT n FROM canon WHERE doc=? AND by=?", (doc, anna.id)).fetchone()[0] > 10 ** 6
    assert level(anna, doc) == "local"
    assert [r["kind"] for r in view(anna)["refused"]] == ["canon"]
    sync(anna, ben, carol)                                                    # one more round
    assert not view(ben)["offers"] and level(ben, doc) == level(carol, doc) == "local"
    with anna:
        ownership.dismiss_refused(anna.ws, "canon", doc)
    assert not view(anna)["refused"]


@needs_archives
def test_a_canon_row_in_the_owners_name_that_removes_a_document_is_undone_from_the_archive(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs")
    sync(anna, ben, carol)
    with ben:
        labels = ben.ws.query("SELECT COUNT(*) FROM labels WHERE doc_id=?", (doc,))[0][0]
        before = {r[0]: r[1] for r in ben.ws.query("SELECT fp, included FROM block_choices WHERE doc_id=?", (doc,))}
    _forge_canon(carol, doc, state="removed", _bump=("state",))
    sync(carol, ben)
    assert not has(ben, doc)
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM removed_docs WHERE doc_id=?", (doc,))
    sync(anna, ben, carol, rounds=2)                                          # Anna answers with her own row
    assert has(ben, doc) and has(anna, doc) and has(carol, doc)
    with ben:
        assert ben.ws.query("SELECT COUNT(*) FROM labels WHERE doc_id=?", (doc,))[0][0] == labels
        assert {r[0]: r[1] for r in ben.ws.query("SELECT fp, included FROM block_choices WHERE doc_id=?",
                                                 (doc,))} == before
