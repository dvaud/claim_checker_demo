"""A stand-in add-on for ENLENS's tests, as tests/fake_claude_cli.py stands in for Claude Code.

It is a separate package: tests put this folder on sys.path, where the entry point in
enlens_fake_addon-0.1.dist-info/entry_points.txt names it under `enlens.extensions`. Each ENLENS version that adds an
extension point adds what this add-on does with it, so every extension point is tried from outside ENLENS.

It keeps "notes" (a table of its own), each with an AI setting like a document's; a hypothesis made from a note says
so (origin "fake-note"). A note that no cloud model may read keeps every task holding its text on this computer, and
the hypotheses made from it out of a Claude chat.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from enlens_claims import access, claimcheck

# ---- 0.13.5: the name and the look -------------------------------------------------------------------------------
BRAND = {"name": "Fieldnotes", "tagline": "a stand-in app on ENLENS", "welcome_title": "Welcome to Fieldnotes",
         "not_a_brand_key": "ignored"}
STATIC = Path(__file__).with_name("static")

# ---- 0.14: tables ------------------------------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS fake_notes(note_id TEXT PRIMARY KEY, text TEXT, ai_access TEXT, created_at TEXT);
"""
MIGRATIONS = [("fake_notes", "colour", "TEXT")]
INDEXES = "CREATE INDEX IF NOT EXISTS ix_fake_notes_colour ON fake_notes(colour);"


# ---- 0.14: routes ------------------------------------------------------------------------------------------------
def hello(h, q):
    return {"hello": "from the stand-in add-on", "project": h.app.settings().get("project")}


def post_note(h, name, q):
    ws = h.app.ws(name)
    body = h._body()
    nid = str(body.get("note_id") or "n1")
    with ws.connect() as cx:
        cx.execute("INSERT OR REPLACE INTO fake_notes(note_id, text, ai_access, colour) VALUES (?,?,?,?)",
                   (nid, str(body.get("text") or ""), body.get("ai_access"), body.get("colour")))
    hid = None
    if body.get("hypothesis"):
        hid = claimcheck.create_hypothesis(ws, str(body["hypothesis"]), origin="fake-note", origin_id=nid)
    return {"note_id": nid, "hyp_id": hid}


def get_notes_csv(h, name, q):
    ws = h.app.ws(name)
    rows = ws.query("SELECT note_id, text FROM fake_notes ORDER BY note_id")
    body = "note_id,text\n" + "".join(f"{r[0]},{r[1]}\n" for r in rows)
    h._send(200, body.encode(), "text/csv; charset=utf-8")
    return None


def post_labels(h, name, q):
    """A job of the add-on's own that waits in the queue for Claude Code: the AI labels two passages."""
    from enlens_claims import profile

    app = h.app
    ws = app.ws(name)
    profile.ensure_pass1(ws, "sdg")
    job = app.start_queued_job("fake-labels", "Stand-in labels", name, lambda job, be, model, prog:
                               profile.run_labels(ws, "sdg", be, model, limit=2, progress=prog,
                                                  should_stop=job.cancel.is_set),
                               withdraw=("label",))
    return {"job": job.view()}


ROUTES = [
    ("GET", r"/api/fake/hello", hello),
    ("POST", r"/api/projects/([^/]+)/fake/notes", post_note),
    ("GET", r"/api/projects/([^/]+)/fake/notes\.csv", get_notes_csv),
    ("POST", r"/api/projects/([^/]+)/fake/labels", post_labels),
]
DOWNLOADS = {"get_notes_csv"}


# ---- 0.14: extra keys --------------------------------------------------------------------------------------------
def state(app):
    return {"fake": {"ready": True}, "version": "not the add-on's to change"}


def overview(ws):
    return {"fake_notes": int(ws.scalar("SELECT COUNT(*) FROM fake_notes") or 0), "documents": -1}


# ---- 0.14: access ------------------------------------------------------------------------------------------------
def _floor(cx, payload, dflt):
    """A task holding a note's text may go no further than the note's setting."""
    nid = payload.get("fake_note_id") if isinstance(payload, dict) else None
    if not isinstance(nid, str):
        return None
    try:
        row = cx.execute("SELECT ai_access FROM fake_notes WHERE note_id=?", (nid,)).fetchone()
    except sqlite3.OperationalError:
        return "none"
    if row is None:
        return "none"  # a note removed since: keep its text here
    return row[0] or dflt or "cloud"


def _hidden(ws):
    try:
        return {r[0] for r in ws.query("SELECT h.hyp_id FROM hypotheses h JOIN fake_notes n ON h.origin='fake-note' "
                                       "AND h.origin_id=n.note_id WHERE COALESCE(n.ai_access, 'cloud') != 'cloud'")}
    except sqlite3.OperationalError:  # a project opened before the add-on was there
        return set()


access.register_floor(_floor)
access.register_hidden(_hidden)
