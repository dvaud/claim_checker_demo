"""0.18.0: a codebook both copies changed is merged code by code (sync/codebook_merge.py).

Until 0.18 a codebook edited on both sides came in whole, as a sync-clash copy beside yours. Now, for a codebook the
two copies exchanged before:

- a code changed on one side only: the newer version, from either side;
- a code changed on both sides: yours stays and the colleague's version is kept beside it (the editor lists it,
  `settle_clash` keeps one): nothing is lost;
- a code new on one side comes in; one removed on one side and unchanged on the other goes; renames are followed by
  the labels of both copies;
- the version before the merge is kept, as before any change of a codebook.

A codebook of the same name made separately in each copy is still kept twice (tests/test_shared_projects.py).
"""
from __future__ import annotations

import pytest

from enlens_claims import bundle, codebooks, frameworks, profile
from test_shared_projects import Person
from test_app import api, home  # noqa: F401  (fixtures)


def _codes(ws, name: str) -> dict[str, str]:
    return {c.code: c.description for c in frameworks.get(name, ws).codes.values()}


def _edit(ws, name: str, change) -> None:
    """Change the codebook in the editor: `change(codes)` edits the list of codes (dicts with uid) in place."""
    st = codebooks.load(ws, name)
    codes = [dict(c) for c in st["codes"]]
    change(codes)
    codebooks.save(ws, name, {**st, "codes": codes})


def _set(field: str, code: str, value):
    def change(codes):
        next(c for c in codes if c["code"] == code)[field] = value
    return change


@pytest.fixture
def shared_codebook(loaded, tmp_path, monkeypatch):
    """Anna's project with her codebook "water" (codes A, B, C), made in the editor; Ben's copy from her file."""
    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    anna.ws = loaded
    with anna:
        codebooks.create(loaded, "water", "Water", "project", "csv",
                         {"csv": "code,description\nA,Water use of electrolysis\nB,Jobs near the plant\n"
                                 "C,Desalination plants\n"})
    first = anna.send()
    with ben:
        ben.ws = bundle.import_project(first, tmp_path / "ben-project")
    return anna, ben


def test_codes_changed_on_different_sides_are_merged_without_a_copy(shared_codebook):
    anna, ben = shared_codebook
    with anna:
        _edit(anna.ws, "water", _set("description", "A", "Water drawn by electrolysers"))
        pid = anna.ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
        profile.add_label(anna.ws, "water", pid, "A")
    with ben:
        _edit(ben.ws, "water", _set("description", "B", "Local jobs and training"))
        versions = codebooks.load(ben.ws, "water")["versions"]
    rep = ben.bring_in(anna.send())
    assert not rep["codebooks"]["clash"]
    merged = rep["codebooks"]["merged"]
    assert [(m["name"], m["theirs"], m["clash"]) for m in merged] == [("water", ["A"], [])]
    assert any("merged code by code" in line for line in rep["lines"])
    with ben:
        assert _codes(ben.ws, "water") == {"A": "Water drawn by electrolysers", "B": "Local jobs and training",
                                           "C": "Desalination plants"}
        assert [n for n in frameworks.available(ben.ws) if n.startswith("water")] == ["water"]  # no sync-clash copy
        assert [tuple(r) for r in ben.ws.query("SELECT framework, code FROM labels WHERE source='person'")] == \
            [("water", "A")]
        assert codebooks.load(ben.ws, "water")["versions"] == versions + 1  # his version before the merge is kept
    rep = anna.bring_in(ben.send())  # and back: Anna gets Ben's B, and both copies hold the same codebook
    with anna:
        assert _codes(anna.ws, "water") == _codes(ben.ws, "water")
    rep = ben.bring_in(anna.send())  # nothing new any more
    assert not rep["codebooks"]["merged"] and not rep["codebooks"]["clash"] and not rep["codebooks"]["updated"]


def test_a_code_both_changed_keeps_yours_and_theirs_beside_it(shared_codebook):
    anna, ben = shared_codebook
    with anna:
        _edit(anna.ws, "water", _set("description", "A", "Anna: water drawn by electrolysers"))
        _edit(anna.ws, "water", _set("description", "C", "Anna: desalination"))
    with ben:
        _edit(ben.ws, "water", _set("description", "A", "Ben: water use"))
    rep = ben.bring_in(anna.send())
    m = rep["codebooks"]["merged"][0]
    assert m["clash"] == ["A"] and m["theirs"] == ["C"]
    with ben:
        assert _codes(ben.ws, "water")["A"] == "Ben: water use"
        assert _codes(ben.ws, "water")["C"] == "Anna: desalination"
        cl = codebooks.load(ben.ws, "water")["clashes"]
        assert [(c["code"], c["theirs"]["description"], c["name"]) for c in cl] == \
            [("A", "Anna: water drawn by electrolysers", "Anna")]
        # Ben keeps Anna's version: it replaces his, and the clash is settled
        cb = codebooks.settle_clash(ben.ws, "water", cl[0]["uid"], "theirs")
        assert not cb["clashes"] and _codes(ben.ws, "water")["A"] == "Anna: water drawn by electrolysers"
    rep = anna.bring_in(ben.send())  # Anna's A is now the newer version everywhere: no clash comes back
    assert not (rep["codebooks"]["merged"] and rep["codebooks"]["merged"][0]["clash"])
    with anna:
        assert _codes(anna.ws, "water")["A"] == "Anna: water drawn by electrolysers"


def test_keeping_your_own_version_sets_theirs_aside(shared_codebook):
    anna, ben = shared_codebook
    with anna:
        _edit(anna.ws, "water", _set("description", "A", "Anna's A"))
    with ben:
        _edit(ben.ws, "water", _set("description", "A", "Ben's A"))
    ben.bring_in(anna.send())
    with ben:
        uid = codebooks.load(ben.ws, "water")["clashes"][0]["uid"]
        cb = codebooks.settle_clash(ben.ws, "water", uid, "mine")
        assert not cb["clashes"] and _codes(ben.ws, "water")["A"] == "Ben's A"
        from enlens_claims import researchlog

        assert any("Kept your version of the code" in e["text"] for e in researchlog.entries(ben.ws)["entries"])
        with pytest.raises(KeyError):
            codebooks.settle_clash(ben.ws, "water", uid, "mine")


def test_new_codes_come_in_and_a_code_removed_on_one_side_goes(shared_codebook):
    anna, ben = shared_codebook
    with anna:
        _edit(anna.ws, "water", lambda codes: codes.append({"uid": "", "code": "D", "description": "Pipelines",
                                                            "group": "", "keywords": [], "examples": []}))
    with ben:
        _edit(ben.ws, "water", lambda codes: codes.remove(next(c for c in codes if c["code"] == "B")))
    rep = ben.bring_in(anna.send())
    m = rep["codebooks"]["merged"][0]
    assert m["added"] == ["D"] and not m["clash"] and not m["kept_removed"]
    with ben:
        assert set(_codes(ben.ws, "water")) == {"A", "C", "D"}  # B stays removed: Anna had not changed it
    rep = anna.bring_in(ben.send())
    with anna:
        assert set(_codes(anna.ws, "water")) == {"A", "C", "D"}  # and Ben's removal reaches Anna
        assert "B" in {v["code"] for v in frameworks.get("water", anna.ws).meta["removed"].values()}


def test_a_code_removed_here_but_changed_there_stays_removed_and_theirs_is_kept(shared_codebook):
    anna, ben = shared_codebook
    with anna:
        _edit(anna.ws, "water", _set("description", "B", "Anna: jobs, also in construction"))
    with ben:
        _edit(ben.ws, "water", lambda codes: codes.remove(next(c for c in codes if c["code"] == "B")))
    rep = ben.bring_in(anna.send())
    assert rep["codebooks"]["merged"][0]["kept_removed"] == ["B"]
    with ben:
        assert "B" not in _codes(ben.ws, "water")
        cl = codebooks.load(ben.ws, "water")["clashes"]
        assert [(c["removed_here"], c["theirs"]["code"]) for c in cl] == [(True, "B")]
        codebooks.settle_clash(ben.ws, "water", cl[0]["uid"], "theirs")  # Ben brings Anna's version back
        assert _codes(ben.ws, "water")["B"] == "Anna: jobs, also in construction"


def test_a_rename_on_one_side_is_followed_by_the_labels_of_both(shared_codebook):
    anna, ben = shared_codebook
    with ben:
        pid = ben.ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
        profile.add_label(ben.ws, "water", pid, "A")
        _edit(ben.ws, "water", _set("description", "C", "Ben: desalination"))
    with anna:
        _edit(anna.ws, "water", _set("code", "A", "Water use"))
    rep = ben.bring_in(anna.send())
    assert rep["codebooks"]["merged"][0]["theirs"] == ["Water use"]
    with ben:
        assert set(_codes(ben.ws, "water")) == {"Water use", "B", "C"}
        assert ben.ws.scalar("SELECT code FROM labels WHERE framework='water' AND source='person'") == "Water use"


def test_settling_a_clash_through_the_app(api):  # noqa: F811
    import json

    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    st, r = api("POST", "/api/projects/Demo/codebooks", {"name": "water", "start": "csv",
                                                        "source": {"csv": "code,description\nA,Water use\n"}})
    assert st == 200
    uid = r["codebook"]["codes"][0]["uid"]
    from enlens_claims import home as home_mod

    side = home_mod.open_project("Demo").root / "frameworks" / "water.json"
    meta = json.loads(side.read_text(encoding="utf-8"))  # as a merge leaves it (sync/codebook_merge.py)
    meta["clashes"] = {uid: {"code": "A", "description": "Water drawn by electrolysers", "group": "", "group_name": "",
                             "include": "", "exclude": "", "keywords": [], "examples": [], "person_id": "p0123456789ab",
                             "name": "Anna", "at": "2026-11-11T03:00:00+00:00"}}
    side.write_text(json.dumps(meta), encoding="utf-8")
    st, r = api("GET", "/api/projects/Demo/codebooks/water")
    assert st == 200 and [c["theirs"]["description"] for c in r["codebook"]["clashes"]] == ["Water drawn by electrolysers"]
    assert api("POST", f"/api/projects/Demo/codebooks/water/clashes/{uid}", {"keep": "both"})[0] == 400
    st, r = api("POST", f"/api/projects/Demo/codebooks/water/clashes/{uid}", {"keep": "theirs", "why": "hers is clearer"})
    assert st == 200 and not r["codebook"]["clashes"]
    assert r["codebook"]["codes"][0]["description"] == "Water drawn by electrolysers"
    assert api("POST", f"/api/projects/Demo/codebooks/water/clashes/{uid}", {"keep": "mine"})[0] == 404
