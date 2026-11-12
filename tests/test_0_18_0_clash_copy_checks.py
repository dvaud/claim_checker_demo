"""0.18.0 stage 5: a check with excerpts on a document and on its sync-clash copy keeps them all, in every copy.

Found by the long random run of L2 (seeds 22 and 25), and older than L2: a colleague's newer reading of a file comes in
as a sync-clash copy `<id>-<mark>`; once the original is read again, the document and its copy hold the same text. A
check with an excerpt on each then reached a third copy that holds the file once: its merge put both excerpts on its
one document as one row, its version of the check differed from the maker's only by that, it went back through the
folder, and the maker's next merge took it as newer: the maker lost an excerpt of their own check.

Now a colleague's merge keeps two excerpts apart when only the naming of documents makes them one (sync.merge `_put`):
its version of the check is then the maker's, and nothing goes back as newer.
"""
from __future__ import annotations

import pytest

from enlens_claims import claimcheck, reread, sharing
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import folder
from owner_helpers import add_doc, join, sync
from owner_more_helpers import as_before_018, small_project
from test_0_14_0_shared_projects import Person


def _excerpts(p: Person, hid: str) -> list[tuple[str, str]]:
    with p:
        return sorted((r[0], r[1]) for r in p.ws.query(
            "SELECT v.doc_id, v.passage_id FROM verifications v JOIN user_claims c ON c.claim_id=v.subject_id WHERE "
            "v.subject_kind='user_claim' AND c.hyp_id=?", (hid,)))


def _round(p: Person) -> dict:
    with p:
        out = folder.sync_now(p.ws)
    assert not [x for x in out["problems"] if x["kind"] != "documents"], out["problems"]
    return out


@pytest.fixture
def team(tmp_path, monkeypatch):
    """Anna, Ben and Carol, three copies of one project exchanged before 0.18 (no owner), one shared folder."""
    shared = tmp_path / "Shared folder"
    shared.mkdir()
    anna, ben, carol = (Person(tmp_path, n, monkeypatch) for n in ("Anna", "Ben", "Carol"))
    anna.ws = small_project(anna, tmp_path / "anna-project", keys=("desalination", "jobs"))
    for p in (ben, carol):
        join(p, anna, tmp_path, shared)
    with anna:
        folder.set_folder(anna.ws, str(shared))
    for p in (anna, ben, carol):
        as_before_018(p)
    sync(anna, ben, carol, rounds=1)
    return anna, ben, carol, tmp_path


def test_a_check_on_a_document_and_its_clash_copy_keeps_both_excerpts(team):
    anna, ben, carol, tmp = team
    g = add_doc(ben, tmp, "grid")             # Ben and Carol read the file with today's reader
    assert add_doc(carol, tmp, "grid") == g
    assert add_doc(anna, tmp, "grid", reader=1) == g   # Anna's copy read it with an earlier one
    _round(ben)
    _round(anna)                              # Ben's reading comes to Anna as a sync-clash copy of hers
    with anna:
        copies = [r[0] for r in anna.ws.query("SELECT doc_id FROM documents WHERE doc_id LIKE ?", (g + "-%",))]
    assert len(copies) == 1
    gc = copies[0]
    with anna:                                # Anna reads hers again: the document and its copy hold the same text
        reread.move(anna.ws, g, anna.id)
        fps = {r[0]: r[1] for r in anna.ws.query("SELECT doc_id, text_fp FROM documents WHERE doc_id IN (?, ?)",
                                                 (g, gc))}
        assert fps[g] == fps[gc]
        hid = claimcheck.check_hypothesis(anna.ws, "Flexible electrolysers lower wind curtailment.", BaselineBackend(),
                                          "baseline", k=2, per_doc=1, doc_ids=[g, gc])
        sharing.share(anna.ws, [{"kind": "check", "key": hid}])
    mine = _excerpts(anna, hid)
    assert sorted({d for d, _p in mine}) == sorted([g, gc]) and len(mine) == 2
    for _ in range(3):                        # Carol brings it in (she holds the file once), then everyone, again
        for p in (anna, carol, ben):
            _round(p)
        assert _excerpts(anna, hid) == mine   # Anna keeps both of her excerpts, where they were
    assert len(_excerpts(carol, hid)) == 2 and len(_excerpts(ben, hid)) == 2
    # and the team goes quiet: nobody writes the check again
    for p in (anna, carol, ben):
        assert not [it for it in _round(p)["wrote"]["items"] if it["key"] == hid], p.name
