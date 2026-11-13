"""Taking the project back never loosens a document's AI setting in the owner's own copy (ownership.py, rule 1 of
"What a file cannot do"; found by the randomised roles test, rule (b)).

Anna owns the project, and its document may be read with Claude ("cloud"). A file says she handed the project over to
Ben, which she did not. Ben's copy follows that hand-over (it is the owner he follows who handed it over) and writes the
project's documents again under his place (`_Ctx.restamp`): the document still at "cloud", with the event of Anna's
that made it so. Anna then makes the document stricter ("none"), which holds in her copy at once, and takes the project
back (`ownership.take_project_back`). Her copy now writes the project's documents again under her new place, from
Ben's rows, so her own row of the document holds her old "cloud" event once more. That row is not her word: she went
on from it. Her copy keeps "none" and offers the looser setting, which only her own click puts into force.
"""
from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import ownership
from enlens_claims.store import now
from enlens_claims.sync import folder
from owner_helpers import add_doc, allow, level, set_level, sync, view
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)


def _with_hand_over(src: Path, out: Path, seq: int, frm: str, to: str) -> Path:
    """A zip of a colleague's copy with a hand-over in `frm`'s name added to its records of who owns the project (any
    SQLite tool can: files are not signed yet)."""
    work = out.with_suffix("")
    work.mkdir()
    with zipfile.ZipFile(src) as zf:
        zf.extractall(work)
    cx = sqlite3.connect(work / "enlens.sqlite")
    cx.execute("INSERT INTO ownership(seq, owner, by, at, kind, after, why) VALUES (?,?,?,?,?,?,?)",
               (seq, to, frm, now(), "handover", frm, None))
    cx.commit()
    cx.close()
    with zipfile.ZipFile(out, "w") as zf:
        for p in sorted(work.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(work).as_posix())
    return out


@pytest.fixture
def pair(anna_and_ben, tmp_path):
    """Anna (the maker, so the owner) and Ben in one shared folder."""
    shared = tmp_path / "Közös mappa"
    shared.mkdir()
    anna, ben = anna_and_ben
    for p in (anna, ben):
        with p:
            folder.set_folder(p.ws, str(shared))
    sync(anna, ben)
    return anna, ben


def _offered(p: Person) -> dict[str, str]:
    return {o["doc"]: o["to"] for o in view(p)["offers"]}


def test_taking_the_project_back_keeps_the_owners_stricter_setting(pair, tmp_path):
    anna, ben = pair
    doc = add_doc(anna, tmp_path, "interview", ai="cloud")
    sync(anna, ben)
    assert (level(anna, doc), level(ben, doc)) == ("cloud", "cloud")
    with anna:
        seq = ownership.chain(anna.ws._conn())[-1]["seq"]
    # a file says Anna handed the project over to Ben: his copy follows it and writes the documents under his place
    ben.bring_in(_with_hand_over(anna.send(), tmp_path / "forged.zip", seq + 1, anna.id, ben.id))
    assert view(ben)["owner"]["id"] == ben.id
    sync(ben)
    # Anna, the owner in her copy, makes the document stricter; then Ben's file reaches her (the hand-over is refused)
    set_level(anna, doc, "none")
    sync(anna)
    assert view(anna)["owner"]["id"] == anna.id and level(anna, doc) == "none"
    with anna:
        ownership.take_project_back(anna.ws)
    assert view(anna)["owner"]["id"] == anna.id
    # her copy keeps her stricter setting: the looser one is the project's (Ben's rows, written again as hers) to offer
    assert level(anna, doc) == "none"
    assert _offered(anna) == {doc: "cloud"}
    sync(anna, ben, rounds=3)
    assert level(anna, doc) == "none"
    # only her own click puts the looser setting into force
    allow(anna, doc)
    assert level(anna, doc) == "cloud"
