"""Roadmap K3, the rest (0.18.8): the per-hypothesis exception, and the suggestion from the bibliography.

A document marked *Non-scientific* (docrole.py, 0.18.6) is read and judged, but no judgement of it counts in an
answer (`verdicts.set_aside`). Two things build on that mark here; the evidence map's own mark for such documents is
drawn in `check_exports.evidence_map`.

**The exception, per hypothesis.** When newspapers, blogs or company brochures are the material a hypothesis is
about (*Local newspapers framed the plant as a job engine*), they are its evidence. The researcher turns on *Count
non-scientific documents in this check* on that hypothesis's page: its answer then counts them as any document (for
every part of a compound hypothesis), and is the one it would have counting them (`status_all_sources`). Stored in
the hypothesis's options (`count_nonscientific`, and `count_nonscientific_why`, the person's reason), so it travels
with the check between copies as its note does: a newer version of the check replaces an older one, and a check
changed on both sides is kept beside as a sync-clash copy (sync/merge.py `_units`). Not a column of its own: a check
whose only change is in a column added after 0.14.2 is not told newer (sync/fingerprints.py, the `old` form). Each
change keeps its time (`count_nonscientific_at`), so turning it off again is never taken for the state before.
Turning it on or off changes the answer at once and goes in the research log with the answers before and after. Off
by default: nothing changes until a person turns it on.

**The suggestion, never a mark.** A document whose bibliography entry has an item type that is usually not scientific
(a newspaper or magazine article, a blog post, a web page, a forum post, a podcast, a broadcast, a video, a
presentation) is suggested as non-scientific on its page, in one quiet line with *Mark* and *No*, never marked by
itself: a press release can be the material, and a web page can be a working paper. *No* is a decision about the
document: it is kept as an entry of the research log (kind `document-suggestion`), which travels with the project, so
the suggestion does not come back in any copy. Level 0: the item type alone, no AI.
"""
from __future__ import annotations

import json
import sqlite3

from .store import Workspace, now

COUNT = "count_nonscientific"           # the key in the hypothesis's options: true (counted in this check)
COUNT_WHY = "count_nonscientific_why"   # the person's reason, when they gave one
COUNT_AT = "count_nonscientific_at"     # when it was last set: each change is a state of its own between copies
DECLINED = "document-suggestion"        # the research log's kind for a suggestion the person said No to

# the bibliography's item types that are usually not scientific (Zotero, CSL JSON, RIS, BibTeX), in the words of
# the suggestion: "Your bibliography lists this as a newspaper article."
TYPE_WORDS = {
    # Zotero
    "newspaperArticle": "a newspaper article", "magazineArticle": "a magazine article", "blogPost": "a blog post",
    "webpage": "a web page", "forumPost": "a forum post", "podcast": "a podcast",
    "radioBroadcast": "a radio broadcast", "tvBroadcast": "a TV broadcast", "videoRecording": "a video recording",
    "presentation": "a presentation",
    # CSL JSON (Zotero's export, Mendeley, citeproc)
    "article-newspaper": "a newspaper article", "article-magazine": "a magazine article",
    "post-weblog": "a blog post", "post": "a post", "broadcast": "a broadcast", "speech": "a presentation",
    # RIS
    "NEWS": "a newspaper article", "MGZN": "a magazine article", "BLOG": "a blog post", "ELEC": "a web page",
    "VIDEO": "a video recording",
    # BibTeX / BibLaTeX
    "online": "a web page", "www": "a web page",
}


# ---- the exception ---------------------------------------------------------------------------------------------------
def _options(raw: str | None) -> dict:
    try:
        o = json.loads(raw or "{}")
    except ValueError:
        return {}
    return o if isinstance(o, dict) else {}


def counting_hyps(cx) -> set[str]:
    """The hypotheses whose check counts the non-scientific documents. `cx`: a connection or a Workspace."""
    sql = "SELECT hyp_id, options_json FROM hypotheses WHERE options_json LIKE ?"
    rows = cx.query(sql, (f"%{COUNT}%",)) if isinstance(cx, Workspace) else cx.execute(sql, (f"%{COUNT}%",)).fetchall()
    return {r[0] for r in rows if _options(r[1]).get(COUNT) is True}


def setting(options: dict | str | None) -> tuple[bool, str | None]:
    """(counts the non-scientific documents, why) from a hypothesis's options (a dict, or its JSON)."""
    o = _options(options) if not isinstance(options, dict) else options
    return o.get(COUNT) is True, (o.get(COUNT_WHY) or None) if o.get(COUNT) is True else None


def _row(cx, hyp_id: str | None):
    if not hyp_id:
        return None
    sql = "SELECT options_json FROM hypotheses WHERE hyp_id=?"
    rows = cx.query(sql, (hyp_id,)) if isinstance(cx, Workspace) else cx.execute(sql, (hyp_id,)).fetchall()
    return rows[0][0] if rows else None


def counts_here(cx, hyp_id: str | None) -> bool:
    """Whether this hypothesis's check counts the non-scientific documents."""
    return setting(_row(cx, hyp_id))[0]


def why_here(cx, hyp_id: str | None) -> str | None:
    return setting(_row(cx, hyp_id))[1]


REASON = "they are the material this hypothesis is about"


def set_counting(ws: Workspace, hyp_id: str, on: bool, why: str | None = None) -> dict:
    """Count the non-scientific documents in this hypothesis's check (`on`), or leave them uncounted again, as in
    every other check. The answer changes at once: returns {"hyp_id", "count_nonscientific", "changed", "was",
    "was_text", "now", "now_text"}; the research log keeps the change with both answers."""
    from . import researchlog
    from .check_results import hypothesis_result

    on = bool(on)
    why = (why or "").strip()[:researchlog.MAX_WHY] or None
    rows = ws.query("SELECT text, options_json FROM hypotheses WHERE hyp_id=?", (hyp_id,))
    if not rows:
        raise KeyError(hyp_id)
    text, opts = rows[0][0] or "", _options(rows[0][1])
    before = hypothesis_result(ws, hyp_id)
    if counts_here(ws, hyp_id) == on:
        return {"hyp_id": hyp_id, "count_nonscientific": on, "changed": False, "was": before["status"],
                "was_text": before["status_text"], "now": before["status"], "now_text": before["status_text"]}
    # kept as false once turned off, with the time of each change: turned off (or on again) it is a version of its
    # own, never one a colleague's copy has had (which would make theirs look newer)
    opts.pop(COUNT_WHY, None)
    opts.update({COUNT: on, COUNT_AT: now()})
    if on and why:
        opts[COUNT_WHY] = why
    with ws.connect() as cx:
        cx.execute("UPDATE hypotheses SET options_json=? WHERE hyp_id=?", (json.dumps(opts), hyp_id))
        # the log entry is part of the change; the answer after it is known only once it is made (below)
        entry = researchlog.record(
            cx, "check-setting",
            f"Non-scientific documents count in the check of {researchlog.quoted(text, 200)}: {REASON}." if on else
            f"Non-scientific documents no longer count in the check of {researchlog.quoted(text, 200)}: their "
            "judgements are shown, never counted, as in every other check.",
            "check", hyp_id, text, data={"count_nonscientific": on}, why=why)
    after = hypothesis_result(ws, hyp_id)
    out = {"hyp_id": hyp_id, "count_nonscientific": on, "changed": True, "was": before["status"],
           "was_text": before["status_text"], "now": after["status"], "now_text": after["status_text"]}
    more = (f" The answer changed from {out['was_text']} to {out['now_text']}."
            if (out["was"], out["was_text"]) != (out["now"], out["now_text"]) else
            f" The answer stays {out['now_text']}.")
    with ws.connect() as cx:
        cx.execute("UPDATE research_log SET text=text || ?, data_json=? WHERE entry_id=?",
                   (more, json.dumps({"count_nonscientific": on, **{k: out[k] for k in
                                                                  ("was", "was_text", "now", "now_text")}}), entry))
    return out


# ---- the suggestion from the bibliography ---------------------------------------------------------------------------
def type_words(item_type: str | None) -> str | None:
    """The suggestion's words for a bibliography item type that is usually not scientific; None for any other."""
    if not item_type:
        return None
    low = item_type.lower()
    return TYPE_WORDS.get(item_type) or (TYPE_WORDS[low] if low in ("online", "www") else None)


def declined(ws: Workspace) -> set[str]:
    """The documents whose suggestion the person (or a colleague) said No to."""
    try:
        return {r[0] for r in ws.query("SELECT DISTINCT subject_id FROM research_log WHERE kind=? AND "
                                       "subject_kind='document'", (DECLINED,))}
    except sqlite3.OperationalError:
        return set()


def suggestions(ws: Workspace) -> dict[str, dict]:
    """{doc_id: {"item_type", "words"}}: the documents to suggest as non-scientific, from the item type of the work
    the bibliography links them to (linked or confirmed), not marked yet, not declined, and not a working document
    (never a source anyway)."""
    from .docrole import WORKING, nonscientific_docs

    try:
        rows = ws.query("SELECT l.doc_id, b.item_type FROM bib_links l JOIN bib_items b ON b.item_key=l.item_key "
                        "JOIN documents d ON d.doc_id=l.doc_id WHERE l.status IN ('auto', 'confirmed') "
                        "AND d.role IS NOT ? ORDER BY b.seq", (WORKING,))
    except sqlite3.OperationalError:   # no bibliography tables, or a database before the role column
        return {}
    skip = nonscientific_docs(ws) | declined(ws)
    out: dict[str, dict] = {}
    for doc, item_type in rows:
        words = type_words(item_type)
        if doc in skip or doc in out or not words:
            continue
        out[doc] = {"item_type": item_type, "words": words}
    return out


def suggestion(ws: Workspace, doc_id: str) -> dict | None:
    """The suggestion for one document ({"item_type", "words", "text"}), or None."""
    s = suggestions(ws).get(doc_id)
    if not s:
        return None
    return {**s, "text": f"Your bibliography lists this as {s['words']}. Mark it as non-scientific?"}


def decline(ws: Workspace, doc_id: str, why: str | None = None) -> dict:
    """The person's *No* to the suggestion: kept in the research log (it travels with the project), so it is not
    suggested again here or in a colleague's copy. Returns {"doc_id", "declined": True}."""
    from . import researchlog

    rows = ws.query("SELECT title FROM documents WHERE doc_id=?", (doc_id,))
    if not rows:
        raise KeyError(doc_id)
    s = suggestions(ws).get(doc_id)
    if doc_id in declined(ws):
        return {"doc_id": doc_id, "declined": True}
    words = s["words"] if s else "a kind of work that is usually not scientific"
    with ws.connect() as cx:
        researchlog.record(cx, DECLINED, f"Kept as scientific: the bibliography lists it as {words}, and it was not "
                                         "marked as non-scientific. Its judgements count in answers.",
                           "document", doc_id, rows[0][0], data={"declined": "nonscientific",
                                                                 "item_type": s["item_type"] if s else None}, why=why)
    return {"doc_id": doc_id, "declined": True}
