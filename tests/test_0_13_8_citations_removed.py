"""0.13.8: Check citations (0.13.7) is taken out of ENLENS; it continues as a project of its own.

What stays: the fix found while building it (an add-on's floor goes with every excerpt of a check, `_add_round`),
and the data of a project that used it: 0.13.8 deletes nothing; its checks are ordinary results.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from test_app import api, home  # noqa: F401  (fixtures)

from enlens_claims import access, claimcheck, prompts, store
from enlens_claims.store import Workspace

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"


def _note(ws, nid, setting):
    with ws.connect() as cx:
        cx.execute("INSERT OR REPLACE INTO fake_notes(note_id, text, ai_access) VALUES (?,?,?)", (nid, "x", setting))


# ---------------------------------------------------------------------------------------------- what stays
def test_an_addon_floor_goes_with_every_excerpt(addon, loaded):
    """0.13.7's fix: the floor labelled the round's task as restricted, yet its excerpts were split by their documents'
    settings alone, so they went to the main model (refused, or never handed out by the queue)."""
    ws = Workspace.open(loaded.root)  # opened again: with the add-on's table
    _note(ws, "local-note", "local")
    _note(ws, "cloud-note", "cloud")
    ps = [dict(r) for r in ws.query("SELECT passage_id, doc_id, page FROM passages WHERE section='body' LIMIT 3")]
    assert ps and set(access.levels(ws, [p["doc_id"] for p in ps]).values()) == {"cloud"}

    def round_(cid, note, local_reader):
        payload = {"subject_kind": "user_claim", "subject_id": cid, "claim": "Water use rises.", "passages": ps,
                   "fake_note_id": note}
        return claimcheck._add_round(ws, cid, f"check:{cid}:r1", payload, "sonnet", local_reader=local_reader)

    # a note only a local AI may read: every excerpt goes to the local model with it
    parts = round_("c1", "local-note", True)
    assert set(parts) == {"local"}
    assert ws.scalar("SELECT access FROM tasks WHERE task_id=?", (parts["local"],)) == "local"
    # without a local model, the person judges them
    assert set(round_("c2", "local-note", False)) == {"person"}
    # a note Claude may read: the documents' settings decide, as before
    parts = round_("c3", "cloud-note", True)
    assert set(parts) == {"main"}
    assert ws.scalar("SELECT access FROM tasks WHERE task_id=?", (parts["main"],)) == "cloud"


# ---------------------------------------------------------------------------------------------- what goes
def test_check_citations_is_gone():
    assert importlib.util.find_spec("enlens_claims.citations") is None
    from enlens_claims.gui.server import DOWNLOADS, ROUTES, App

    assert not [p.pattern for _m, p, _h in ROUTES if "citation" in p.pattern]
    assert not [d for d in DOWNLOADS if "citation" in d] and not hasattr(App, "start_citations")
    assert "cite_texts" not in store.SCHEMA and "cite_refs" not in store.SCHEMA
    assert not hasattr(access, "citing_level") and not hasattr(access, "text_floor")
    assert "extra" not in claimcheck.check_hypothesis.__code__.co_varnames
    assert "THE CLAIM IN ITS TEXT" not in Path(prompts.__file__).read_text(encoding="utf-8")
    # the page: no sidebar entry, route, feature, job kind, origin, view or rules
    assert not (STATIC / "views" / "citations.js").exists()
    for name in ("index.html", "app.js", "features.js", "registry.js", "views/overview.js", "views/result.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert not re.search(r"citation", text, re.I), name
    assert ".cite-" not in (STATIC / "app.css").read_text(encoding="utf-8")
    # the Overview's compact row is as in 0.13.6 (three cards)
    assert ".ov-grid-small { grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }" in \
        (STATIC / "v09.css").read_text(encoding="utf-8")
    for doc in ("docs/API.md", "docs/MANUAL.md"):
        assert "/citations" not in (ROOT / doc).read_text(encoding="utf-8")
        assert "Checking citations" not in (ROOT / doc).read_text(encoding="utf-8")


def test_a_project_that_used_check_citations_keeps_its_data(api, home, corpus):  # noqa: F811
    """Nothing is deleted: the 0.13.7 tables stay as they are, and a citation's check is a result like any other."""
    from enlens_claims import ingest

    home.create_project("Old")
    ws = home.open_project("Old")
    ingest.ingest(ws, [corpus])
    with ws.connect() as cx:  # what 0.13.7 left behind
        cx.execute("CREATE TABLE cite_texts(text_id TEXT PRIMARY KEY, title TEXT, source TEXT, doc_id TEXT, "
                   "file_name TEXT, body TEXT, pages_json TEXT, ai_access TEXT, numeric_unread INT DEFAULT 0, "
                   "cut INT DEFAULT 0, created_at TEXT)")
        cx.execute("INSERT INTO cite_texts(text_id, title, source, body, ai_access) "
                   "VALUES ('t1', 'Draft', 'paste', 'x', 'cloud')")
    hid = claimcheck.create_hypothesis(ws, "Hydrogen plants need a lot of fresh water.", origin="citation",
                                       origin_id="t1-c1-w1")
    claimcheck.new_claim(ws, "Hydrogen plants need a lot of fresh water.", hyp_id=hid, claim_id=f"c-{hid}")
    home._OPEN.clear()

    st, hs = api("GET", "/api/projects/Old/hypotheses")
    assert st == 200 and hid in [h["hyp_id"] for h in hs["hypotheses"]]
    st, r = api("GET", f"/api/projects/Old/hypotheses/{hid}")
    assert st == 200 and r["origin"] == "citation"
    st, o = api("GET", "/api/projects/Old/overview")
    assert st == 200 and o["hypotheses"] == 1 and "citations" not in o
    ws = home.open_project("Old")
    assert ws.scalar("SELECT COUNT(*) FROM cite_texts") == 1  # untouched
    # and it can be removed from Results like any other check
    assert api("DELETE", f"/api/projects/Old/hypotheses/{hid}", {})[0] == 200
