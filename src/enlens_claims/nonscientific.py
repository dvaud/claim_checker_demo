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
changed on both sides is kept beside as a sync-clash copy (sync/merge.py `_units`). A change made by someone who is not
the check's author arrives in the author's copy as a sync-clash copy too, never in place of theirs (rule H5,
`merge._may_replace`), as a note does; the page says so under the switch. Not a column of its own: a check whose only
change is in a column added after 0.14.2 is not told newer (sync/fingerprints.py, the `old` form). Each change keeps
its time (`count_nonscientific_at`), so turning it off again is never taken for the state before. Turning it on or
off, or giving a new reason while it is on, goes in the research log (with the answers before and after). Off by
default: nothing changes until a person turns it on.

**The suggestion, never a mark.** A document whose bibliography entry has an item type that is usually not scientific
(a newspaper or magazine article, a blog post, a web page, a forum post, a podcast, a broadcast) is suggested as
non-scientific on its page, in one quiet line with *Mark* and *No*, never marked by itself: a press release can be the
material, and a web page can be a working paper. Theory and working documents are never suggested. *No* is a
decision about the document, kept as an entry of the research log (kind `document-suggestion`), which travels with
the project. Whose *No* decides (`declined`): the Owner's or a Co-owner's for every copy; a Member's hides the
suggestion in their own copy only (in a project with no owner, as before 0.18, everyone's counts). *Suggest again*
takes a *No* back: the person who said it can, and the Owner and Co-owners can take back anyone's; it is a log entry
too, naming the entries it supersedes. Level 0: the item type alone, no AI.
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
    "radioBroadcast": "a radio broadcast", "tvBroadcast": "a TV broadcast",
    # CSL JSON (Zotero's export, Mendeley, citeproc)
    "article-newspaper": "a newspaper article", "article-magazine": "a magazine article",
    "post-weblog": "a blog post", "post": "a post", "broadcast": "a broadcast",
    # RIS
    "NEWS": "a newspaper article", "MGZN": "a magazine article", "BLOG": "a blog post", "ELEC": "a web page",
    # BibTeX / BibLaTeX
    "online": "a web page", "www": "a web page",
}
# not suggested: a presentation, a speech or a video can be a scholar's talk (a conference paper, a lecture)


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
    every other check; a new `why` while it is on replaces the reason. The answer changes at once: returns
    {"hyp_id", "count_nonscientific", "changed", "why_changed", "was", "was_text", "now", "now_text"}. The setting is
    saved first; the research log then keeps the change in one entry, with both answers."""
    from . import researchlog
    from .check_results import hypothesis_result

    on = bool(on)
    why = (why or "").strip()[:researchlog.MAX_WHY] or None
    rows = ws.query("SELECT text, options_json FROM hypotheses WHERE hyp_id=?", (hyp_id,))
    if not rows:
        raise KeyError(hyp_id)
    text, opts = rows[0][0] or "", _options(rows[0][1])
    was_on, was_why = setting(opts)
    new_why = on and was_on and why is not None and why != was_why
    before = hypothesis_result(ws, hyp_id)
    if was_on == on and not new_why:
        return {"hyp_id": hyp_id, "count_nonscientific": on, "changed": False, "why_changed": False,
                "was": before["status"], "was_text": before["status_text"], "now": before["status"],
                "now_text": before["status_text"]}
    # kept as false once turned off, with the time of each change: turned off (or on again) it is a version of its
    # own, never one a colleague's copy has had (which would make theirs look newer)
    opts.pop(COUNT_WHY, None)
    opts.update({COUNT: on, COUNT_AT: now()})
    if on and why:
        opts[COUNT_WHY] = why
    with ws.connect() as cx:
        cx.execute("UPDATE hypotheses SET options_json=? WHERE hyp_id=?", (json.dumps(opts), hyp_id))
    after = hypothesis_result(ws, hyp_id)
    out = {"hyp_id": hyp_id, "count_nonscientific": on, "changed": True, "why_changed": bool(new_why),
           "was": before["status"], "was_text": before["status_text"], "now": after["status"],
           "now_text": after["status_text"]}
    check = researchlog.quoted(text, 200)
    if new_why:
        said = f"A new reason for counting non-scientific documents in the check of {check}."
    elif on:
        said = f"Non-scientific documents count in the check of {check}: {REASON}."
    else:
        said = (f"Non-scientific documents no longer count in the check of {check}: their judgements are shown, never "
                "counted, as in every other check.")
    said += (f" The answer changed from {out['was_text']} to {out['now_text']}."
             if (out["was"], out["was_text"]) != (out["now"], out["now_text"]) else
             f" The answer stays {out['now_text']}.")
    data = {"count_nonscientific": on, **{k: out[k] for k in ("was", "was_text", "now", "now_text")},
            **({"why_changed": True} if new_why else {})}
    with ws.connect() as cx:
        researchlog.record(cx, "check-setting", said, "check", hyp_id, text, data=data, why=why)
    return out


# ---- the suggestion from the bibliography ---------------------------------------------------------------------------
def type_words(item_type: str | None) -> str | None:
    """The suggestion's words for a bibliography item type that is usually not scientific; None for any other."""
    if not item_type:
        return None
    low = item_type.lower()
    return TYPE_WORDS.get(item_type) or (TYPE_WORDS[low] if low in ("online", "www") else None)


class NoSuggestion(ValueError):
    """Nothing to answer: the document has no suggestion now (marked already, a No already counts, or its item type
    is a scientific one), or no No this person may take back. A list drawn before is stale."""


def _standing(ws: Workspace) -> list[dict]:
    """The *No* entries still standing (none of them taken back by a *Suggest again*), oldest first:
    [{"entry_id", "doc_id", "person_id"}]."""
    try:
        rows = ws.query("SELECT entry_id, subject_id, person_id, data_json FROM research_log WHERE kind=? AND "
                        "subject_kind='document' ORDER BY at, entry_id", (DECLINED,))
    except sqlite3.OperationalError:
        return []
    taken_back: set[str] = set()
    nos = []
    for eid, doc, pid, data in rows:
        d = _options(data)
        if d.get("suggest_again"):
            taken_back.update(x for x in d.get("supersedes") or [] if isinstance(x, str))
        else:
            nos.append({"entry_id": eid, "doc_id": doc, "person_id": pid})
    return [n for n in nos if n["entry_id"] not in taken_back]


def _deciders(ws: Workspace):
    """(me, decides(person)): whether a person's *No* counts in every copy: the Owner's or a Co-owner's (in a
    project with no owner, as before 0.18, everyone's)."""
    from . import ownership, people

    me = people.me()
    cx = ws._conn()
    seen: dict[str, bool] = {}

    def decides(person: str | None) -> bool:
        if person not in seen:
            try:
                seen[person] = ownership.may_write(cx, person or people.UNKNOWN)
            except sqlite3.OperationalError:
                seen[person] = True
        return seen[person]

    return me, decides


def declined(ws: Workspace) -> set[str]:
    """The documents whose suggestion is answered No in this copy: by the Owner or a Co-owner (for everyone), or by
    this person (a Member's own No hides it in their own copy only)."""
    me, decides = _deciders(ws)
    return {n["doc_id"] for n in _standing(ws) if n["person_id"] == me or decides(n["person_id"])}


def suggestions(ws: Workspace) -> dict[str, dict]:
    """{doc_id: {"item_type", "words"}}: the documents to suggest as non-scientific, from the item type of the work
    the bibliography links them to (linked or confirmed), not marked yet, not declined, and neither a theory nor a
    working document (never evidence anyway)."""
    from .docrole import ROLES, nonscientific_docs

    try:
        rows = ws.query("SELECT l.doc_id, b.item_type FROM bib_links l JOIN bib_items b ON b.item_key=l.item_key "
                        "JOIN documents d ON d.doc_id=l.doc_id WHERE l.status IN ('auto', 'confirmed') "
                        f"AND (d.role IS NULL OR d.role NOT IN ({','.join('?' * len(ROLES))})) ORDER BY b.seq",
                        ROLES)
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
    """The person's *No* to the current suggestion: kept in the research log (it travels with the project). The
    Owner's or a Co-owner's hides it in every copy, a Member's in their own (`declined`). Nothing is written when there
    is no suggestion now (NoSuggestion): a stale list, or a document of a scientific kind, never logs a *No*. Returns
    {"doc_id", "declined": True}."""
    from . import researchlog

    rows = ws.query("SELECT title FROM documents WHERE doc_id=?", (doc_id,))
    if not rows:
        raise KeyError(doc_id)
    s = suggestions(ws).get(doc_id)
    if not s:
        raise NoSuggestion(doc_id)
    with ws.connect() as cx:
        researchlog.record(cx, DECLINED, f"Kept as scientific: the bibliography lists it as {s['words']}, and it was "
                                         "not marked as non-scientific. Its judgements count in answers.",
                           "document", doc_id, rows[0][0], data={"declined": "nonscientific",
                                                                 "item_type": s["item_type"]}, why=why)
    return {"doc_id": doc_id, "declined": True}


def _may_take_back(ws: Workspace, doc_id: str) -> tuple[list[dict], list[dict]]:
    """(the standing Nos that hide the suggestion here, those of them this person may take back): their own, and
    anyone's when they are the Owner or a Co-owner."""
    me, decides = _deciders(ws)
    nos = [n for n in _standing(ws) if n["doc_id"] == doc_id]
    hiding = [n for n in nos if n["person_id"] == me or decides(n["person_id"])]
    mine = [n for n in nos if n["person_id"] == me or decides(me)]
    return hiding, mine


def answered_no(ws: Workspace, doc_id: str) -> dict | None:
    """For the document's page: {"by": [names], "may_suggest_again": bool} when a No hides the suggestion here and the
    document is not marked; None otherwise. *Suggest again* is offered only when this person may take back every No
    that hides it (else it would not come back)."""
    from . import people
    from .docrole import is_nonscientific

    hiding, mine = _may_take_back(ws, doc_id)
    if not hiding or is_nonscientific(ws, doc_id):
        return None
    names, me = people.names(ws), people.me()
    by = list(dict.fromkeys("you" if n["person_id"] == me else names.get(n["person_id"]) or "a colleague"
                            for n in hiding))
    ids = {n["entry_id"] for n in mine}
    return {"by": by, "may_suggest_again": all(n["entry_id"] in ids for n in hiding)}


def suggest_again(ws: Workspace, doc_id: str) -> dict:
    """Take back the Nos to this document's suggestion that this person may (their own; anyone's for the Owner or a
    Co-owner): one research-log entry that names them (`supersedes`), so it travels and they stop counting in every
    copy. NoSuggestion when there is none to take back. Returns {"doc_id", "suggestion": the suggestion now, or
    None}."""
    from . import researchlog

    rows = ws.query("SELECT title FROM documents WHERE doc_id=?", (doc_id,))
    if not rows:
        raise KeyError(doc_id)
    _hiding, mine = _may_take_back(ws, doc_id)
    if not mine:
        raise NoSuggestion(doc_id)
    with ws.connect() as cx:
        researchlog.record(cx, DECLINED, "Suggested as non-scientific again: the No to the bibliography's suggestion "
                                         "was taken back.", "document", doc_id, rows[0][0],
                           data={"suggest_again": True, "supersedes": [n["entry_id"] for n in mine]})
    return {"doc_id": doc_id, "suggestion": suggestion(ws, doc_id)}
