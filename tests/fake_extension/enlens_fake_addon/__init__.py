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

from enlens_claims import access, claimcheck, taskkinds

# ---- 0.13.5: the name and the look -------------------------------------------------------------------------------
BRAND = {"name": "Fieldnotes", "tagline": "a stand-in app on ENLENS", "welcome_title": "Welcome to Fieldnotes",
         "not_a_brand_key": "ignored"}
STATIC = Path(__file__).with_name("static")

# ---- 0.13.6: tables ------------------------------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS fake_notes(note_id TEXT PRIMARY KEY, text TEXT, ai_access TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS fake_tags(note_id TEXT, tag TEXT, quote TEXT, confidence REAL, model TEXT,
  PRIMARY KEY(note_id, tag));
"""
MIGRATIONS = [("fake_notes", "colour", "TEXT")]
INDEXES = "CREATE INDEX IF NOT EXISTS ix_fake_notes_colour ON fake_notes(colour);"


# ---- 0.13.6: routes ------------------------------------------------------------------------------------------------
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


# ---- 0.13.6: extra keys --------------------------------------------------------------------------------------------
def state(app):
    return {"fake": {"ready": True}, "version": "not the add-on's to change"}


def overview(ws):
    return {"fake_notes": int(ws.scalar("SELECT COUNT(*) FROM fake_notes") or 0), "documents": -1}


# ---- 0.13.6: access ------------------------------------------------------------------------------------------------
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


# ---- 0.13.6: a kind of AI task of its own -------------------------------------------------------------------------
# The AI gives a note's tags, each with the sentence of the note it comes from. ENLENS checks the answer against
# TagsOut and every quote against the note's text before store_tags sees it.
from pydantic import BaseModel, Field  # noqa: E402


class Tag(BaseModel):
    tag: str = Field(min_length=1, max_length=40)
    quote: str
    confidence: float = Field(ge=0, le=1)


class TagsOut(BaseModel):
    tags: list[Tag] = Field(default_factory=list, max_length=5)


def tags_system() -> str:
    return ("You tag a researcher's note with up to five short tags. For each tag, quote the sentence of the note it "
            'comes from exactly. Output format\n{"tags": [{"tag": "water", "quote": "...", "confidence": 0.8}]}')


def tags_user(payload: dict) -> str:
    return f"NOTE:\n{payload['text']}"


def store_tags(cx, t, payload, obj, model):
    for x in obj["tags"]:
        cx.execute("INSERT OR REPLACE INTO fake_tags(note_id, tag, quote, confidence, model) VALUES (?,?,?,?,?)",
                   (payload["fake_note_id"], x["tag"], x["quote"], x["confidence"], model))
    return True, []


def tags_demo(payload: dict) -> dict:
    """The offline demo: the note's first sentence, tagged with its first long word."""
    first = payload["text"].split(". ")[0].strip()
    word = next((w.strip(".,").lower() for w in first.split() if len(w) > 4), "note")
    return {"tags": [{"tag": word, "quote": first, "confidence": 0.5}]}


TAG_KIND = taskkinds.register(taskkinds.TaskKind(
    name="fake_tag", prompt_version="fake-tag-v1", system=tags_system, user=tags_user, schema=TagsOut,
    quote_from=lambda payload: payload["text"], store=store_tags, certainty="tags",
    claude=("haiku", "sonnet"), local="small", helper="fake-tagger",
    helper_file=str(Path(__file__).with_name("agents") / "fake-tagger.md"), helper_model="haiku",
    batch=7, order=7.5, noun=("note to tag", "notes to tag"), short="notes to tag", title="Tagging notes",
    run_name="Tags of notes", output_cap=300, demo=tags_demo, size=lambda k, max_chars: 600 + max_chars))


def tag_task(cx, note_id: str, text: str) -> str:
    """Make the task that tags a note (the add-on's own code would do this from a button)."""
    from enlens_claims import tasks

    tid = f"fake_tag:{note_id}"
    tasks._insert_task(cx, tid, "fake_tag", "haiku", {"fake_note_id": note_id, "text": text})
    return tid
