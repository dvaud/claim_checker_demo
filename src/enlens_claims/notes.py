"""Notes and highlights on passages (0.16, roadmap F2): a person's own notes tied to exact words of a document.

A note is a span of a document's text (character offsets into `documents.text`, and the words themselves as `quote`),
with the person's words about it (`text`; empty for a plain highlight) and a colour. The words are checked against the
document when the note is made, as every quote is (`textutil.find_selection`: a selection cut inside a word is widened
to whole words), and found again by their words when the document's text has changed since (a document moved to the new
reader): the note follows its words, or says it could not find them and keeps them.

Notes are searchable (`search`), and a note can be used as evidence in a check (`use_as_evidence`): the passage that
holds its words becomes an excerpt of the check, judged by the person, with the note's words as the sentence they point
to. Nothing here uses AI or leaves the computer. Notes travel with the project; each person's notes are their own
(a colleague's are shown and cannot be changed here), and a note removed does not come back with a colleague's work.
"""
from __future__ import annotations

import bisect
import json
import re
import sqlite3
import uuid

from .store import Workspace, now
from .textutil import find_selection

COLOURS = ("yellow", "green", "blue", "pink")
MAX_QUOTE = 4000
MAX_TEXT = 10000
_ID = re.compile(r"n[0-9a-f]{16}")


def _me() -> str:
    from .people import me

    return me()


def _page(cx: sqlite3.Connection, doc_id: str, pos: int) -> int | None:
    rows = cx.execute("SELECT page, start FROM pages WHERE doc_id=? ORDER BY start", (doc_id,)).fetchall()
    if not rows:
        return None
    i = bisect.bisect_right([r[1] for r in rows], pos) - 1
    return rows[max(0, i)][0]


def _title(cx: sqlite3.Connection, doc_id: str) -> tuple[str | None, bool]:
    """(the document's title, whether it is still in the project)."""
    row = cx.execute("SELECT title FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if row:
        return row[0], True
    row = cx.execute("SELECT title FROM sync_removed WHERE kind='document' AND key=?", (doc_id,)).fetchone()
    return (row[0] if row else None), False


def _hits(text: str, quote: str, lo: int, hi: int, most: int = 200) -> list[tuple[int, int]]:
    """Every place of the words between `lo` and `hi` (as a quote is found), in order."""
    pos = lo
    while pos > 0 and lo - pos < 200 and not text[pos - 1].isspace():  # from a word's start: a match is whole words
        pos -= 1
    out = []
    while pos < hi and len(out) < most:
        hit = find_selection(text[pos:hi], quote)
        if not hit:
            break
        out.append((pos + hit[0], pos + hit[1]))
        pos += max(hit[1], hit[0] + 1)   # the next one after this one, not inside it
    return out


def find(text: str, quote: str, near: int | None = None) -> tuple[int, int] | None:
    """Where the words of a note are in a text: as a quote is found (whole words, typography and spacing evened out),
    the place nearest `near` (near it first, then anywhere)."""
    if near is not None:
        for lo, hi in ((max(0, near - 3000), near + len(quote) + 3000), (0, len(text))):
            hits = _hits(text, quote, lo, min(hi, len(text)))
            if hits:
                return min(hits, key=lambda h: (abs(h[0] - near), h[0]))
        return None
    hit = find_selection(text, quote)
    return (hit[0], hit[1]) if hit else None


# ---------------------------------------------------------------------------------------------
# making and changing notes
# ---------------------------------------------------------------------------------------------
def add(ws: Workspace, doc_id: str, start: int, end: int, quote: str | None = None, text: str = "",
        colour: str = "yellow") -> dict:
    """A note (or a highlight, with no `text`) on the words of `doc_id` between `start` and `end`. `quote` is the
    words as the page showed them: they must be the document's own words there (else nearby), as every quote is."""
    colour = colour if colour in COLOURS else "yellow"
    text = (text or "").strip()
    if len(text) > MAX_TEXT:
        raise ValueError(f"Keep a note under {MAX_TEXT:,} characters.")
    with ws.connect() as cx:
        row = cx.execute("SELECT text, title FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        if row is None:
            raise KeyError(doc_id)
        body = row[0] or ""
        try:
            a, b = int(start), int(end)
        except (TypeError, ValueError):
            raise ValueError("Select the words to note in the text.") from None
        if not (0 <= a < b <= len(body)):
            raise ValueError("Select the words to note in the text.")
        want = (quote if quote is not None else body[a:b]).strip()
        if not want:
            raise ValueError("Select the words to note in the text.")
        if len(want) > MAX_QUOTE:
            raise ValueError(f"Select fewer words (at most {MAX_QUOTE:,} characters); a note can say more.")
        # the words selected, where they were selected (widened to whole words), else the nearest place of them
        got = find(body[:b + 50], want, a) if a < b else None
        if got is None or abs(got[0] - a) > 50:
            got = find(body, want, a)
        if got is None:
            raise ValueError("These words are not in the document's text: select them in the text.")
        a, b = got
        nid = "n" + uuid.uuid4().hex[:16]
        at = now()
        cx.execute("INSERT INTO notes(note_id, doc_id, start, end, quote, page, text, colour, person_id, created_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)", (nid, doc_id, a, b, body[a:b], _page(cx, doc_id, a), text or None,
                                                     colour, _me(), at))
    return get(ws, nid)


def _own(cx: sqlite3.Connection, note_id: str) -> sqlite3.Row:
    row = cx.execute("SELECT * FROM notes WHERE note_id=?", (note_id,)).fetchone()
    if row is None:
        raise KeyError(note_id)
    if row["person_id"] != _me():
        raise PermissionError("This note is a colleague's: only they can change it.")
    return row


def update(ws: Workspace, note_id: str, text: str | None = None, colour: str | None = None) -> dict:
    """Change your note's words (`text`; "" leaves a plain highlight) or its colour."""
    with ws.connect() as cx:
        _own(cx, note_id)
        sets, args = [], []
        if text is not None:
            t = text.strip()
            if len(t) > MAX_TEXT:
                raise ValueError(f"Keep a note under {MAX_TEXT:,} characters.")
            sets.append("text=?")
            args.append(t or None)
        if colour is not None:
            if colour not in COLOURS:
                raise ValueError(f"The colour must be one of {', '.join(COLOURS)}.")
            sets.append("colour=?")
            args.append(colour)
        if sets:
            cx.execute(f"UPDATE notes SET {', '.join(sets)}, edited_at=? WHERE note_id=?", (*args, now(), note_id))
    return get(ws, note_id)


def remove(ws: Workspace, note_id: str) -> None:
    with ws.connect() as cx:
        row = _own(cx, note_id)
        cx.execute("DELETE FROM notes WHERE note_id=?", (note_id,))
        cx.execute("INSERT OR REPLACE INTO sync_removed(kind, key, title, at, person_id) VALUES ('note', ?, ?, ?, ?)",
                   (note_id, (row["quote"] or "")[:80], now(), row["person_id"]))


# ---------------------------------------------------------------------------------------------
# reading notes
# ---------------------------------------------------------------------------------------------
def _placed(cx: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict]:
    """Notes as views, each checked against its document's text as it reads now: words that moved (the document was
    read again) are found again and their place written down; words that cannot be found are marked `lost`."""
    me = _me()
    texts: dict[str, tuple] = {}
    out = []
    for r in rows:
        d = dict(r)
        did = d["doc_id"]
        if did not in texts:
            row = cx.execute("SELECT text, title FROM documents WHERE doc_id=?", (did,)).fetchone()
            texts[did] = (row[0] or "", row[1], True) if row else (None, *_title(cx, did))
        body, title, present = texts[did]
        d["title"], d["present"], d["lost"] = title, present, False
        if present and body[d["start"]:d["end"]] != d["quote"]:
            got = find(body, d["quote"] or "", d["start"])
            if got is None:
                d["lost"] = True
            else:
                d["start"], d["end"] = got
                d["page"] = _page(cx, did, got[0])
                cx.execute("UPDATE notes SET start=?, end=?, page=? WHERE note_id=?", (*got, d["page"], d["note_id"]))
        d["mine"] = d["person_id"] == me
        out.append(d)
    if out:
        nm = None
        for d in out:
            if not d["mine"]:
                nm = nm or _names_of(cx)
                d["who"] = nm.get(d["person_id"], "a colleague")
            else:
                d["who"] = "you"
    return out


def _names_of(cx: sqlite3.Connection) -> dict[str, str]:
    return {r[0]: (r[1] or "a colleague") for r in cx.execute("SELECT person_id, name FROM people")}


def get(ws: Workspace, note_id: str) -> dict:
    with ws.connect() as cx:
        rows = cx.execute("SELECT * FROM notes WHERE note_id=?", (note_id,)).fetchall()
        if not rows:
            raise KeyError(note_id)
        return _placed(cx, rows)[0]


def for_document(ws: Workspace, doc_id: str) -> list[dict]:
    """A document's notes in the order of its text."""
    with ws.connect() as cx:
        return sorted(_placed(cx, cx.execute("SELECT * FROM notes WHERE doc_id=?", (doc_id,)).fetchall()),
                      key=lambda d: (d["lost"], d["start"], d["end"]))


def search(ws: Workspace, q: str | None = None, doc_id: str | None = None, colour: str | None = None,
           mine: bool = False, offset: int = 0, limit: int = 200) -> dict:
    """Notes whose words or note contain `q` (every word of it, in any order), newest first: {notes, total,
    documents: [{doc_id, title, notes}]}."""
    where, args = [], []
    for w in (q or "").lower().split()[:12]:
        like = "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(lower(COALESCE(text, '')) LIKE ? ESCAPE '\\' OR lower(quote) LIKE ? ESCAPE '\\')")
        args += [like, like]
    if doc_id:
        where.append("doc_id=?")
        args.append(doc_id)
    if colour:
        where.append("colour=?")
        args.append(colour)
    if mine:
        where.append("person_id=?")
        args.append(_me())
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    with ws.connect() as cx:
        total = cx.execute(f"SELECT COUNT(*) FROM notes {sql_where}", args).fetchone()[0]
        rows = cx.execute(f"SELECT * FROM notes {sql_where} ORDER BY COALESCE(edited_at, created_at) DESC, rowid DESC "
                          "LIMIT ? OFFSET ?", (*args, max(1, min(int(limit), 100000)), max(0, int(offset)))).fetchall()
        out = _placed(cx, rows)
        docs = []
        for did, n in cx.execute("SELECT doc_id, COUNT(*) FROM notes GROUP BY doc_id").fetchall():
            title, present = _title(cx, did)
            docs.append({"doc_id": did, "title": title, "present": present, "notes": n})
    docs.sort(key=lambda d: (not d["present"], (d["title"] or "").lower()))
    return {"notes": out, "total": total, "documents": docs, "colours": list(COLOURS)}


def counts(ws: Workspace) -> dict[str, int]:
    """{doc_id: number of notes} (the Documents list shows it)."""
    return {r[0]: r[1] for r in ws.query("SELECT doc_id, COUNT(*) FROM notes GROUP BY doc_id")}


def table(ws: Workspace) -> list[dict]:
    out = []
    for n in sorted(search(ws, limit=100000)["notes"], key=lambda n: ((n["title"] or "").lower(), n["start"])):
        out.append({"Document": n["title"] or n["doc_id"], "Page": n["page"] if n["page"] is not None else "",
                    "Words": n["quote"], "Note": n["text"] or "", "Colour": n["colour"], "Who": n["who"],
                    "Made (UTC)": n["created_at"], "Changed (UTC)": n["edited_at"] or "",
                    "Found in the text now": "no" if n["lost"] else ("yes" if n["present"] else "document removed")})
    return out


def markdown(ws: Workspace, project: str) -> str:
    from . import __version__

    lines = [f"# Notes: {project}", "", f"Written by ENLENS {__version__} on {now()[:10]}.", ""]
    title = None
    for n in sorted(search(ws, limit=100000)["notes"], key=lambda n: ((n["title"] or "").lower(), n["doc_id"],
                                                                     n["start"])):
        t = n["title"] or n["doc_id"]
        if t != title:
            title = t
            lines += [f"## {t}" + ("" if n["present"] else " (removed from the project)"), ""]
        page = f"p. {n['page']}: " if n["page"] is not None else ""
        quote = " ".join((n["quote"] or "").split())
        who = "" if n["mine"] else f" ({n['who']})"
        lines.append(f"- {page}> {quote}{who}")
        if n["text"]:
            lines.append("  " + n["text"].strip().replace("\n", "\n  "))
    if title is None:
        lines.append("No notes yet.")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------------------------
# a note as evidence in a check
# ---------------------------------------------------------------------------------------------
def use_as_evidence(ws: Workspace, note_id: str, claim_id: str, verdict: str, comment: str | None = None) -> dict:
    """The passage holding a note's words becomes an excerpt of a check's part (`claim_id`), judged by you (`verdict`:
    supports, partially_supports, refutes, not_relevant) with the note's words as the sentence you point to. When the
    check shows that passage already, your judgement of it is set. Returns {hyp_id, claim_id, passage_id, new}."""
    from . import claimcheck, researchlog

    if verdict not in claimcheck.USER_VERDICTS:
        raise ValueError(f"The judgement must be one of {', '.join(claimcheck.USER_VERDICTS)}.")
    n = get(ws, note_id)
    if n["lost"] or not n["present"]:
        raise ValueError("This note's words are not in the document's text now, so they cannot be an excerpt.")
    uc = ws.query("SELECT claim_id, hyp_id, text, target, framework FROM user_claims WHERE claim_id=?", (claim_id,))
    if not uc:
        raise KeyError(claim_id)
    uc = dict(uc[0])
    rows = ws.query("SELECT p.passage_id, p.doc_id, p.page, p.text, p.start, p.end, d.title FROM passages p JOIN "
                    "documents d ON d.doc_id=p.doc_id WHERE p.doc_id=? AND p.start<=? AND p.end>=? ORDER BY p.seq",
                    (n["doc_id"], n["start"], n["end"]))
    if not rows:
        inside = ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=? AND end>? AND start<?",
                           (n["doc_id"], n["start"], n["end"])) or 0
        if inside:
            raise ValueError("These words run across two passages of the document. Note a shorter span within one "
                             "paragraph to use it as evidence.")
        raise ValueError("These words are in text left out of the document's reading, which no check reads. Restore "
                         "it in the document's Reading panel first.")
    p = dict(rows[0])
    shown = {q["passage_id"] for t in claimcheck._check_tasks(ws, claim_id)
             for q in json.loads(t["payload_json"])["passages"]}
    new = p["passage_id"] not in shown
    with ws.connect() as cx:
        if new:
            groups = claimcheck._rounds(ws, claim_id)
            n_round = len(groups) + 1
            base = f"check:{claim_id}:r{n_round}" if groups else f"check:{claim_id}"
            picked = [{"passage_id": p["passage_id"], "doc_id": p["doc_id"], "title": p["title"], "page": p["page"],
                       "text": p["text"], "found_by": "note"}]
            payload = claimcheck._payload(ws, claim_id, uc["text"], uc["target"], uc.get("framework"), picked)
            payload["from_note"] = note_id
            claimcheck._add_round(ws, claim_id, base, payload, claimcheck.PERSON, main_levels=(), local_reader=False,
                                  cx=cx)
        claimcheck.set_judgement(ws, claim_id, p["passage_id"], verdict, comment, quote=n["quote"])
        hyp = cx.execute("SELECT text FROM hypotheses WHERE hyp_id=?", (uc["hyp_id"] or claim_id,)).fetchone()
        verdict_words = {"supports": "supports", "partially_supports": "partly supports", "refutes": "contradicts",
                         "not_relevant": "is not about"}[verdict]
        researchlog.record(cx, "evidence-added",
                           f"Used a note on {researchlog.quoted(p['title'], 80)} as evidence: it {verdict_words} "
                           f"{researchlog.quoted(hyp[0] if hyp else uc['text'])}.",
                           "check", uc["hyp_id"] or claim_id, hyp[0] if hyp else uc["text"],
                           data={"note_id": note_id, "doc_id": p["doc_id"], "passage_id": p["passage_id"],
                                 "verdict": verdict, "claim_id": claim_id})
    return {"hyp_id": uc["hyp_id"] or claim_id, "claim_id": claim_id, "passage_id": p["passage_id"], "new": new}


def move(cx: sqlite3.Connection, doc_id: str, new_text: str) -> dict:
    """The notes of a document read again into `new_text` (reread.py): each follows its words, nearest its old place
    in proportion; those whose words cannot be found keep them and are marked lost when shown. {moved, lost}."""
    rows = cx.execute("SELECT note_id, start, quote FROM notes WHERE doc_id=?", (doc_id,)).fetchall()
    old_len = cx.execute("SELECT length(text) FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    scale = (len(new_text) / old_len[0]) if old_len and old_len[0] else 1.0
    moved = lost = 0
    for nid, start, quote in rows:
        got = find(new_text, quote or "", int((start or 0) * scale))
        if got is None:
            lost += 1
            continue
        cx.execute("UPDATE notes SET start=?, end=? WHERE note_id=?", (*got, nid))
        moved += 1
    return {"moved": moved, "lost": lost}


def merge(cx: sqlite3.Connection, rows: list[dict], fix) -> int:
    """A colleague's notes (sync.py): those not here come in (unless removed here, or their document did not come in);
    one of theirs they changed since is brought up to date. Yours are never changed."""
    me = _me()
    gone = {r[0] for r in cx.execute("SELECT key FROM sync_removed WHERE kind='note'")}
    docs = {r[0] for r in cx.execute("SELECT doc_id FROM documents")}
    cols = [r[1] for r in cx.execute("PRAGMA table_info(notes)")]
    n = 0
    for r in rows:
        if not isinstance(r.get("note_id"), str) or not _ID.fullmatch(r["note_id"]) or r["note_id"] in gone:
            continue
        r = fix(r)
        if r is None or r.get("doc_id") not in docs:
            continue
        have = cx.execute("SELECT person_id, edited_at FROM notes WHERE note_id=?", (r["note_id"],)).fetchone()
        use = [c for c in cols if c in r]
        if have is None:
            cx.execute(f"INSERT INTO notes({','.join(use)}) VALUES ({','.join('?' * len(use))})", [r[c] for c in use])
            n += 1
        elif have[0] != me and have[0] == r.get("person_id") and (r.get("edited_at") or "") > (have[1] or ""):
            sets = [c for c in use if c != "note_id"]
            cx.execute(f"UPDATE notes SET {', '.join(c + '=?' for c in sets)} WHERE note_id=?",
                       [*(r[c] for c in sets), r["note_id"]])
            n += 1
    return n
