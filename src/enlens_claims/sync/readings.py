"""Another reading of a document both copies have (0.18, roadmap A0's open point).

*Read with the new reader* (reread.py) gives a document other text and other passages, and remembers the fingerprints
of the texts it had before (`documents.old_fps`). Before 0.18 the sync did not look at them: a colleague who still had
the older reading (or a newer one) brought it in as a document of its own, a sync-clash copy, with their results on it.

Now a reading this copy knows as one of the same document is the same document. Two readings are known as one when
they are readings of the same file (the same document id and file, `sha1`) and their histories meet: the one is among
the other's earlier readings, or both were read again from one reading. Then:

- each copy keeps the reading it has: nobody's text or results change because a colleague reads with another reader
  (moving one's own document stays the person's choice, *Read with the new reader*);
- the colleague's results on their reading are placed on this copy's reading the way reread.py moves results: each
  result by its quote, nearest where it was; a check keeps the excerpt it showed as its record; notes follow their
  words. This is done in the colleague's copy as it was unpacked for the merge (a scratch copy), before the merge,
  so the merge's own rules then apply as to any document both copies read alike;
- what has no place on this copy's reading is kept as a record, as reread.py keeps it (a check's excerpt points
  nowhere but keeps its text and judgement, an answered task keeps a tombstone id, a note keeps its words): never lost.
  The report says how many;
- what Claude had read of the colleague's reading in passages that have no place here still counts toward what Claude
  has read of the document here (`documents.sent_share`), so a cap is never loosened by a reading;
- a check or a set of themes the colleague did not change since it was last exchanged is told by its state before the
  move (`before_move`), so the reading alone never makes a sync clash; one they changed is compared as always (a change
  both made, a move here and a new round there, is a sync clash: both are kept);
- a unit placed on this copy's reading and kept here is written down as the placement of the colleague's state
  (`sync_seen` kind `placed:check` or `placed:themes`, fingerprint "<placed>=<theirs>"). When this copy's version goes
  back to them and is placed on their reading again, they know it as their own state, not a newer one, so a round trip
  never replaces their version with one that lost places;
- when some result of theirs found no place here (`lossy_move`), a version of theirs that would replace yours comes in
  beside yours instead (a sync-clash copy), so your results keep their places.

Readings whose histories do not meet (the same file read on two computers with text recognition on one of them, or
by two versions of ENLENS when it was added) are still documents of their own, as before.
"""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from .common import DOC_ID, _rows, base_id, text_fp

_READING_TABLES = ("pages", "paragraphs", "headings", "passages", "blocks", "doc_tables")


def _fps(raw: str | None) -> list[str]:
    try:
        out = json.loads(raw or "[]")
    except ValueError:
        return []
    return [x for x in out if isinstance(x, str)] if isinstance(out, list) else []


def _plain_sha(sha: str | None) -> str:
    return (sha or "").split("~")[0]


class _Reading:
    """A document's reading as this copy stores it, in the shape reread.py reads a new reading in (`_plan`): its text,
    passages, page spans and blocks, and its rows to store under the colleague's id of the document (`as_id`)."""

    def __init__(self, cx: sqlite3.Connection, local: str, as_id: str):
        row = _rows(cx, "SELECT * FROM documents WHERE doc_id=?", (local,))[0]
        self.doc = row
        self.text = row["text"] or ""
        self.rows: dict[str, list[dict]] = {}
        for t in _READING_TABLES:
            rows = _rows(cx, f"SELECT * FROM {t} WHERE doc_id=?", (local,))
            for r in rows:
                r["doc_id"] = as_id
                if t == "passages":
                    r["passage_id"] = f"{as_id}:{int(r['seq']):04d}"
            self.rows[t] = rows
        self.passages = [SimpleNamespace(seq=int(p["seq"]), start=p["start"], end=p["end"], page=p["page"],
                                         section=p["section"])
                         for p in sorted(self.rows["passages"], key=lambda p: int(p["seq"]))]
        pages = sorted(self.rows["pages"], key=lambda p: int(p["page"]))
        self.page_spans = [(p["start"], p["end"]) for p in pages]
        self.raw = SimpleNamespace(paginated=bool(pages))
        self.blocks = [SimpleNamespace(start=b["start"], end=b["end"], kind=b["kind"], included=bool(b["included"]))
                       for b in sorted(self.rows["blocks"], key=lambda b: int(b["n"]))]
        try:
            self.reading = json.loads(row.get("reading_json") or "{}")
        except ValueError:
            self.reading = {}


def place_on(inc, icx: sqlite3.Connection, iid: str, reading: _Reading) -> dict:
    """In the colleague's copy `inc` (a scratch copy unpacked for the merge), move every result on its reading of
    `iid` onto `reading` (this copy's), as reread.py moves results, and give the document that reading. Returns
    {"placed", "not_placed", "notes_lost", "share_added"}."""
    from .. import notes, reread

    drow = _rows(icx, "SELECT * FROM documents WHERE doc_id=?", (iid,))[0]
    plan, info = reread._plan(inc, icx, iid, reading)
    reread._write_plan(icx, plan)
    for t in _READING_TABLES:
        icx.execute(f"DELETE FROM {t} WHERE doc_id=?", (iid,))
    moved_notes = notes.move(icx, iid, reading.text)  # before the text changes: it reads the old text's length
    old = _fps(drow.get("old_fps"))
    before = text_fp(drow.get("text"))
    old += [before] if before not in old else []
    mine = reading.doc
    icx.execute("UPDATE documents SET text=?, n_chars=?, n_pages=?, reader=?, text_fp=?, reading_json=?, ocr_pages=?, "
                "scanned_pages=?, old_fps=?, sent_share=? WHERE doc_id=?",
                (reading.text, len(reading.text), mine.get("n_pages"), mine.get("reader"), text_fp(reading.text),
                 mine.get("reading_json"), mine.get("ocr_pages"), mine.get("scanned_pages"), json.dumps(old),
                 info["sent_share"], iid))
    for t, rows in reading.rows.items():
        if rows:
            cols = [c[1] for c in icx.execute(f"PRAGMA table_info({t})") if c[1] in rows[0]]
            icx.executemany(f"INSERT OR REPLACE INTO {t}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                            [tuple(r[c] for c in cols) for r in rows])
    for sql, args in plan.after:
        icx.execute(sql, args)
    rep = info["report"]
    placed = sum(v.get("moved", 0) for v in rep["counts"].values())
    return {"placed": placed, "not_placed": len(rep["not_placed"]), "notes_lost": moved_notes["lost"],
            "share_added": max(0.0, float(info["sent_share"] or 0) - float(drow.get("sent_share") or 0))}


def unit_states(cx: sqlite3.Connection, doc_id: str) -> dict[tuple[str, str], tuple[str, str]]:
    """The fingerprints of the checks and sets of themes that point into a document (before and after *Read with the
    new reader* moves it: `remember_move`)."""
    from .fingerprints import _canon, _check_unit, _fingerprints, _themes_unit

    hyps = {r[0] for r in cx.execute("SELECT DISTINCT u.hyp_id FROM verifications v JOIN user_claims u ON "
                                     "u.claim_id=v.subject_id WHERE v.subject_kind='user_claim' AND v.doc_id=?",
                                     (doc_id,)) if r[0]}
    head = f"{doc_id}:"
    runs = {r[0] for r in cx.execute("SELECT DISTINCT run_id FROM theme_members WHERE substr(passage_id, 1, ?) = ?",
                                     (len(head), head))}
    fps, canon = _fingerprints(cx), _canon(cx)
    out = {("check", h): fps(_check_unit(cx, h), canon) for h in hyps}
    out.update({("themes", rid): fps(_themes_unit(cx, rid), canon) for rid in runs})
    return out


def remember_move(cx: sqlite3.Connection, doc_id: str, before: dict[tuple[str, str], tuple[str, str]]) -> int:
    """After *Read with the new reader* moved a document here (reread.py): a check or set of themes whose state before
    was one exchanged with colleagues is written down as moved from it (`placed:` states), so a colleague who still has
    that state knows this copy's moved version as the same, not as a newer one. Returns how many."""
    after = unit_states(cx, doc_id)
    n = 0
    for (kind, key), fp in before.items():
        new = after.get((kind, key))
        seen = {r[0] for r in cx.execute("SELECT fp FROM sync_seen WHERE kind=? AND key=?", (kind, key))}
        if new and new[0] != fp[0] and (fp[0] in seen or fp[1] in seen):
            n += cx.execute("INSERT OR IGNORE INTO sync_seen(kind, key, fp) VALUES (?,?,?)",
                            (f"placed:{kind}", key, f"{new[0]}={fp[0]}")).rowcount
    return n


class ReadingRules:
    """A part of `merge._Merge`: the colleague's readings this copy knows as other readings of its own documents."""

    def _placed(self, cx: sqlite3.Connection, kind: str, key: str, fp_in: tuple, pre: tuple | None) -> None:
        """A unit of theirs placed on your reading and now kept here: its state here is the placement of theirs."""
        if pre is not None and pre[0] != fp_in[0]:
            cx.execute("INSERT OR IGNORE INTO sync_seen(kind, key, fp) VALUES (?,?,?)",
                       (f"placed:{kind}", key, f"{fp_in[0]}={pre[0]}"))

    def _other_readings(self, cx: sqlite3.Connection) -> None:
        """Before the merge: each incoming document that is another reading of one here gets this copy's reading,
        with the colleague's results placed on it (see the module's notes)."""
        here: dict[str, list[dict]] = {}
        for r in _rows(cx, "SELECT doc_id, text_fp, old_fps, sha1 FROM documents"):
            here.setdefault(base_id(r["doc_id"]), []).append(r)
        same = {(base_id(r["doc_id"]), r["text_fp"]) for rs in here.values() for r in rs}
        cols = {c[1] for c in self.icx.execute("PRAGMA table_info(documents)")}
        old_col = "old_fps" if "old_fps" in cols else "NULL AS old_fps"
        moves: list[tuple[str, str]] = []
        for d in _rows(self.icx, f"SELECT doc_id, text_fp, {old_col}, sha1, title FROM documents ORDER BY doc_id"):
            iid = d["doc_id"]
            if not isinstance(iid, str) or not DOC_ID.fullmatch(iid) or (base_id(iid), d["text_fp"]) in same:
                continue  # never a path; or the same reading as one here, which the merge knows already
            if iid in self.stubs:
                continue  # 0.18: known only by its stub (sync/folder.py): no reading of theirs to place
            theirs = {d["text_fp"]} | set(_fps(d["old_fps"]))
            known = [r for r in here.get(base_id(iid), [])
                     if _plain_sha(r["sha1"]) == _plain_sha(d["sha1"])
                     and theirs & ({r["text_fp"]} | set(_fps(r["old_fps"])))]
            if known:  # yours of the same id first, then a copy of it
                local = min(known, key=lambda r: (r["doc_id"] != iid, r["doc_id"]))["doc_id"]
                moves.append((iid, local))
        for kind, key, fp in self.icx.execute("SELECT kind, key, fp FROM sync_seen WHERE kind IN ('placed:check', "
                                              "'placed:themes')").fetchall():
            placed, _, theirs = (fp or "").partition("=")
            if placed and theirs:
                self.placed_there.setdefault((kind.split(":", 1)[1], key), {})[placed] = theirs
        if not moves:
            return
        # the state of each check and set of themes before the move, to tell one the colleague did not change
        from .fingerprints import _canon, _check_unit, _fingerprints, _themes_unit

        fps, canon = _fingerprints(cx), _canon(self.icx)
        for (hid,) in self.icx.execute("SELECT hyp_id FROM hypotheses").fetchall():
            self.before_move[("check", hid)] = fps(_check_unit(self.icx, hid), canon)
        for (rid,) in self.icx.execute("SELECT run_id FROM theme_runs").fetchall():
            self.before_move[("themes", rid)] = fps(_themes_unit(self.icx, rid), canon)
        fps_in = {r[0]: r[1] for r in self.icx.execute("SELECT doc_id, text_fp FROM documents")}  # their readings
        for iid, local in moves:
            title = self.icx.execute("SELECT title FROM documents WHERE doc_id=?", (iid,)).fetchone()[0]
            try:
                with self.inc.connect() as icx:  # one document at a time: a failure leaves that one as it was
                    got = place_on(self.inc, icx, iid, _Reading(cx, local, iid))
            except Exception as e:  # noqa: BLE001 - it comes in as a document of its own, as before 0.18
                self.r["documents"]["other_reading"].append({"title": title, "doc_id": local, "failed": str(e)[:200]})
                continue
            share = got.pop("share_added")
            # what Claude read there in passages with no place here still counts here, once per colleague and reading
            # (the same file brought in again adds nothing)
            row = cx.execute("SELECT value FROM meta WHERE key=?", (f"sent_share_from:{local}",)).fetchone()
            try:
                done = json.loads(row[0]) if row else {}
            except ValueError:
                done = {}
            mark = f"{self.sender['id']}:{fps_in.get(iid) or ''}"
            add = share - float(done.get(mark) or 0.0)
            if add > 1e-9:
                cx.execute("UPDATE documents SET sent_share=MIN(1.0, COALESCE(sent_share, 0) + ?) WHERE doc_id=?",
                           (round(add, 6), local))
                done[mark] = share
                cx.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"sent_share_from:{local}", json.dumps(done)))
            if got["not_placed"]:
                self.lossy_move = True
            self.r["documents"]["other_reading"].append({"title": title, "doc_id": local, **got})
