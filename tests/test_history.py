"""0.16 (roadmap F5): history inside the app.

- before a person changes a set of themes or their judgements in a check, the state before is kept as a version (the
  same state twice is one version; the oldest beyond `history.KEEP` go);
- *Compare* says in words what changed since a version; *Restore* puts it back, keeps the state it replaces as a
  version (so a restore can be undone the same way) and writes it in the research log;
- a version holds only what a person made: a colleague's judgements are not touched by a restore;
- versions are this copy's history: they never travel to a colleague;
- the app's endpoints list, compare and restore; and no endpoint name is defined twice (a clash sent one route to
  another's handler).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from enlens_claims import claimcheck, history, ingest, notes, people, researchlog, sync, themes
from enlens_claims.store import Workspace

from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixtures)
from test_app import Api, api, home  # noqa: F401  (fixtures)

DEMO = Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"


@pytest.fixture
def demo(tmp_path) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [DEMO])
    return ws


def _state(ws, rid):
    v = themes.view(ws, rid)
    return ({t["theme_id"]: t["name"] for t in v["themes"]}, sorted(t["theme_id"] for t in v["removed"]),
            {t["theme_id"]: t["merged_from"] for t in v["themes"] if t["merged_from"]})


def test_a_set_of_themes_compared_and_restored(demo):
    rid = themes.run(demo, k=4)
    start = _state(demo, rid)
    v = themes.view(demo, rid)
    a, b, c = (t["theme_id"] for t in v["themes"][:3])
    themes.edit(demo, rid, "rename", a, "Commuting")
    themes.edit(demo, rid, "merge", b, a)
    themes.edit(demo, rid, "remove", c, True)
    after = _state(demo, rid)
    vs = history.versions(demo, "themes", rid)
    assert len(vs["versions"]) == 3 and vs["versions"][-1]["label"] == "renaming a theme"
    assert vs["title"].startswith("the themes found on ")
    first = vs["versions"][-1]["version_id"]
    cmp = history.compare(demo, "themes", rid, first)
    whats = [c["what"] for c in cmp["changes"]]
    assert "Name of a theme" in whats and any(w.endswith("merged into") for w in whats) and not cmp["same"]
    r = history.restore(demo, "themes", rid, first)
    assert r["restored"] and _state(demo, rid) == start
    e = researchlog.entries(demo)["entries"][0]
    assert e["kind"] == "restored" and e["has_version"] and "(3 changes)" in e["text"]
    # the restore can be undone the same way: the state it replaced is the newest version
    undo = history.versions(demo, "themes", rid)["versions"][0]
    assert undo["label"].startswith("restoring the version of ")
    history.restore(demo, "themes", rid, undo["version_id"])
    assert _state(demo, rid) == after
    assert history.restore(demo, "themes", rid, undo["version_id"]) == {"restored": False, "changes": []}


def test_your_judgements_in_a_check_compared_and_restored(demo):
    doc, text = demo.query("SELECT doc_id, text FROM documents WHERE text LIKE '%commuting emissions%' LIMIT 1")[0]
    i = text.index("commuting emissions")
    n = notes.add(demo, doc, i, i + 19)
    hid = claimcheck.create_hypothesis(demo, "Remote work lowers commuting emissions.")
    cid = claimcheck.new_claim(demo, "Remote work lowers commuting emissions.", hyp_id=hid)
    pid = notes.use_as_evidence(demo, n["note_id"], cid, "supports", "clear")["passage_id"]
    claimcheck.set_judgement(demo, cid, pid, "refutes", "on second reading")
    claimcheck.set_judgement(demo, cid, pid, "refutes", "on second reading")   # the same again: no new version
    claimcheck.set_note(demo, hid, "Ask about the survey's sample.")
    vs = history.versions(demo, "check", hid)["versions"]
    assert [v["label"] for v in vs] == ["the note on the check", "your judgement of an excerpt", "your judgement of an excerpt"]
    cmp = history.compare(demo, "check", hid, vs[1]["version_id"])  # just after the note was used as evidence
    assert {c["what"].split(" of ")[0] for c in cmp["changes"]} >= {"Your judgement", "Note on the check"}
    assert any(c["before"] == "supports" and c["after"] == "contradicts" for c in cmp["changes"])
    history.restore(demo, "check", hid, vs[1]["version_id"])
    ex = claimcheck.hypothesis_result(demo, hid)["parts"][0]["passages"][0]
    assert ex["user_verdict"] == "supports" and ex["user_note"] == "clear"
    assert claimcheck.hypothesis_result(demo, hid)["note"] in (None, "")
    # a colleague's judgement is not part of your history and stays as it is
    with demo.connect() as cx:
        people.record(cx, cid, pid, "p0123456789ab", "refutes", "theirs", None)
        people.refresh(cx, [cid])
    history.restore(demo, "check", hid, vs[0]["version_id"])
    who = {r["person_id"]: r["verdict"] for r in demo.query("SELECT person_id, verdict FROM judgements")}
    assert who["p0123456789ab"] == "refutes"


def test_versions_are_kept_once_and_up_to_a_limit(demo, monkeypatch):
    monkeypatch.setattr(history, "KEEP", 3)
    rid = themes.run(demo, k=4)
    t = themes.view(demo, rid)["themes"][0]["theme_id"]
    for i in range(6):
        themes.edit(demo, rid, "rename", t, f"Name {i}")
    assert len(history.versions(demo, "themes", rid)["versions"]) == 3
    with demo.connect() as cx:
        v1 = history.snapshot(demo, cx, "themes", rid, "nothing changed")
        v2 = history.snapshot(demo, cx, "themes", rid, "nothing changed")
    assert v1 == v2
    with pytest.raises(KeyError):
        history.versions(demo, "nonsense", rid)


def test_versions_stay_in_this_copy(anna_and_ben):
    anna, ben = anna_and_ben
    assert "versions" in sync.LOCAL_ONLY
    with anna:
        ingest.ingest(anna.ws, [DEMO])
        rid = themes.run(anna.ws, k=3)
        themes.edit(anna.ws, rid, "rename", themes.view(anna.ws, rid)["themes"][0]["theme_id"], "Water")
        assert anna.ws.scalar("SELECT COUNT(*) FROM versions") == 1
    ben.bring_in(anna.send())
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM versions") == 0
        e = [x for x in researchlog.entries(ben.ws)["entries"] if x["kind"] == "theme-renamed"][0]
        assert e["who"] == "Anna" and not e["has_version"]   # her entry, without her copy's version


def test_history_through_the_app(api):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    from enlens_claims import home as home_mod

    ws = home_mod.open_project("Demo")
    ingest.ingest(ws, [DEMO])
    rid = themes.run(ws, k=3)
    t = themes.view(ws, rid)["themes"][0]["theme_id"]
    assert api("PUT", f"/api/projects/Demo/themes/{rid}/edit", {"what": "remove", "theme_id": t, "value": True,
                                                                "why": "off-topic"})[0] == 200
    assert researchlog.entries(ws)["entries"][0]["why"] == "off-topic"
    st, r = api("GET", f"/api/projects/Demo/history/themes/{rid}")
    assert st == 200 and len(r["versions"]) == 1 and r["versions"][0]["mine"]
    vid = r["versions"][0]["version_id"]
    st, c = api("GET", f"/api/projects/Demo/history/themes/{rid}/{vid}")
    assert st == 200 and c["changes"][0]["before"] == "shown" and c["changes"][0]["after"] == "removed"
    st, r = api("POST", f"/api/projects/Demo/history/themes/{rid}/{vid}/restore", {})
    assert st == 200 and r["restored"]
    assert api("GET", f"/api/projects/Demo/history/themes/{rid}/vnope")[0] == 404
    assert api("GET", f"/api/projects/Demo/history/other/{rid}")[0] == 404
    st, r = api("DELETE", f"/api/projects/Demo/themes/{rid}?why=found%20again")
    assert st == 200 and researchlog.entries(ws)["entries"][0]["why"] == "found again"


def test_no_endpoint_handler_name_is_defined_twice():
    gui = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui"
    seen: dict[str, str] = {}
    for f in sorted(gui.glob("api_*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                for fn in node.body:
                    if isinstance(fn, ast.FunctionDef) and not fn.name.startswith("_"):
                        assert fn.name not in seen, f"{fn.name} is in {seen.get(fn.name)} and {f.name}"
                        seen[fn.name] = f.name
