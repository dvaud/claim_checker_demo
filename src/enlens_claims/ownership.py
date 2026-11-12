"""One owner, several collaborators (0.18, roadmap L2).

A project that people work on together has one **owner**. Everyone keeps their own working version; what the
project's documents *are* (which documents, how each is read, who may read each with AI) is the owner's to decide.
A collaborator may still change the documents in their own copy: each such change is a **proposal** to the owner, who
accepts or declines it according to how much it matters:

    add       a document was added                                  low     accepted at once (the owner's setting,
                                                                            on by default) or with one click
    reread    a document was read again with the new reader         medium
    blocks    Leave out / Restore, where the text starts and ends   medium
    remove    a document was removed                                high    always the owner's decision
    loosen    more AI may read a document than before               high    always the owner's decision

What the proposer's copy does at once: it keeps the change (their working version), except a looser AI setting, which
is held until the owner accepts it (privacy first: a looser setting never takes effect anywhere, the proposer's copy
included, before the owner said so). A *stricter* AI setting is never a proposal: it holds in every copy at once, as
before (sync/merge.py `_stricter`).

What the other copies do: a document a collaborator added comes in everywhere at once, provisionally, so the team can
go on working while the owner is away; when the owner declines it, it leaves every copy but the proposer's. Every
other proposal changes nothing in the other copies until the owner accepts it; then it reaches every copy: a removal
removes the document there (its checks keep their grades as records, as when a person removes a document; a backup is
made first), a new reading is made there by `reread.move` through the job queue (each copy's results are placed on it
by its rules; where some would find no place the copy waits for its person's word, `move_now(force=True)`), the blocks
left out or restored are applied there on top of that copy's own, a looser AI setting is taken over there unless that
copy's person made the document stricter themselves meanwhile.

**How the copies agree** (bundles are not signed: this holds between honest copies, design note §4.7). Four tables
travel, in zips and through the shared folder, each merged by its own rule (sync/owner_merge.py):

- `ownership`: a chain of records. Seq 1 is the maker (a project never exchanged becomes its maker's when it first
  leaves the computer) or, for a project exchanged before 0.18 or with no known maker, whoever first says *Become the
  owner*; every later record is a hand-over by the owner before it, or a take-over when that owner has left the
  shared folder or was not heard of for `TAKE_OVER_DAYS`. Of two records for one place in the chain, a hand-over
  counts over a take-over, then the earlier, then the smaller person id: every copy that holds the same records names
  the same owner (`chain`). A project with no record has no owner, and works as before 0.18.
- `proposals`: written by the proposer's copy, never changed, except that the proposer may take one back.
- `decisions`: the owner's word on a proposal; it counts when its writer was the owner of the place in the chain it
  names, and of two that count, the one from the earlier place in the chain.
- `canon`: the documents as the owner accepted them, one row per document and writer; the row of the latest owner
  with the highest number counts (`canon`). Every copy follows these rows (`settle`), and remembers how far it has
  (`canon_seen`, this copy's own): what differs here *after* it followed a row is this copy's own change (a proposal,
  or, in the owner's copy, the next row); what differs *before* is the owner's change still to be applied here.

`settle(ws)` is the one place where a copy looks at itself: it writes the proposals for what its person changed (or,
in the owner's copy, the canon rows), accepts added documents at once in the owner's copy when the owner's setting
says so, and applies what the owner decided. It runs before a copy writes to the shared folder or makes a zip, and
after a colleague's work came in.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from . import people
from .store import Workspace, now

KINDS = ("add", "reread", "blocks", "remove", "loosen")
SEVERITY = {"add": "low", "reread": "medium", "blocks": "medium", "remove": "high", "loosen": "high"}
ACCEPT_ADDS = "owner_accept_adds"  # meta (this copy's own): the owner accepts added documents at once (default: yes)
TAKE_OVER_DAYS = 14
RANK = {"cloud": 0, "local": 1, "none": 2}
_SEEN = ("state_n", "read_n", "ai_n", "ai_level", "blocks_n", "blocks_json", "gone", "came_from", "read_tried",
         "read_note", "read_from")


class NotAllowed(PermissionError):
    """What only the owner (or only the proposer) may do, said in words for a researcher."""


# ---------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------
def _rows(cx: sqlite3.Connection, sql: str, args: Iterable = ()) -> list[dict]:
    cur = cx.execute(sql, tuple(args))
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _json(s: Any, default: Any) -> Any:
    try:
        out = json.loads(s) if s else default
    except (TypeError, ValueError):
        return default
    return out if isinstance(out, type(default)) else default


def _id(*parts: Any) -> str:
    return "q" + hashlib.sha1("\0".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def _digest(obj: Any) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def _q(title: str | None, n: int = 80) -> str:
    from .researchlog import quoted

    return quoted(title or "a document", n)


def _level(v: Any) -> str:
    return v if v in RANK else "none"


def _has_tables(cx: sqlite3.Connection) -> bool:
    return bool(cx.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ownership'").fetchone())


# ---------------------------------------------------------------------------------------------
# who the owner is
# ---------------------------------------------------------------------------------------------
def chain(cx: sqlite3.Connection) -> list[dict]:
    """The records that count, in order (see the module's notes): [{"seq", "owner", "by", "at", "kind", "after",
    "why"}]; the last one names the owner. Empty: the project has no owner."""
    if not _has_tables(cx):
        return []
    by_seq: dict[int, list[dict]] = {}
    for r in _rows(cx, "SELECT * FROM ownership"):
        if isinstance(r["seq"], int) and r["seq"] > 0 and people.ID_RE.fullmatch(r["owner"] or "") and \
                people.ID_RE.fullmatch(r["by"] or "") and r["owner"] != people.UNKNOWN:
            by_seq.setdefault(r["seq"], []).append(r)
    out: list[dict] = []
    prev: str | None = None
    seq = 1
    while seq in by_seq:
        ok = [r for r in by_seq[seq] if (r["after"] or None) == prev]
        if not ok:
            break

        def rank(r: dict) -> tuple:
            first = (r["kind"] == "made") if prev is None else (r["by"] == prev)
            return (0 if first else 1, r["at"] or "", r["by"])

        best = min(ok, key=rank)
        out.append(best)
        prev = best["owner"]
        seq += 1
    return out


def owner(cx: sqlite3.Connection) -> str | None:
    ch = chain(cx)
    return ch[-1]["owner"] if ch else None


def _record(cx: sqlite3.Connection, seq: int, who: str, by: str, kind: str, after: str | None, why: str | None,
            text: str) -> None:
    from . import researchlog

    cx.execute("INSERT OR REPLACE INTO ownership(seq, owner, by, at, kind, after, why) VALUES (?,?,?,?,?,?,?)",
               (seq, who, by, now(), kind, after, (why or "").strip()[:500] or None))
    researchlog.record(cx, "owner", text, why=why, data={"owner": who, "kind": kind, "seq": seq})


def ensure_owner(cx: sqlite3.Connection, me: str) -> bool:
    """A project that was never exchanged and has no owner yet becomes its maker's: called when it first leaves this
    computer (a zip, the shared folder). True when a record was written."""
    from . import sharing

    if cx.execute("SELECT 1 FROM ownership LIMIT 1").fetchone() or sharing.exchanged(cx, me):
        return False
    _record(cx, 1, me, me, "made", None, None, "This project's owner: its maker. Colleagues may change its documents "
                                               "in their own copies; such a change is a proposal the owner accepts or "
                                               "declines.")
    return True


def claim(ws: Workspace) -> dict:
    """*Become the owner* of a project that has none (exchanged before 0.18, or its maker is not known)."""
    from . import sharing

    me = people.me()
    with ws.connect() as cx:
        if chain(cx):
            raise NotAllowed("This project has an owner already.")
        if not sharing.exchanged(cx, me):  # never exchanged: its maker's, written when it first leaves this computer
            raise NotAllowed("You made this project, so you are its owner already.")
        _record(cx, 1, me, me, "claim", None, None, "Became the owner of this project (it had none).")
    settle(ws, apply=False)
    return view(ws)


def hand_over(ws: Workspace, to: str, why: str | None = None) -> dict:
    """The owner hands the project to a colleague; proposals that wait are then theirs to decide. The owner's own
    changes up to this moment are the project's first (written down now, before the record that ends their time)."""
    me = people.me()
    if owner(ws._conn()) == me:
        settle(ws, apply=False)
    with ws.connect() as cx:
        ch = chain(cx)
        if not ch or ch[-1]["owner"] != me:
            raise NotAllowed("Only the owner can hand the project over.")
        if to == me or not cx.execute("SELECT 1 FROM people WHERE person_id=?", (to,)).fetchone() or \
                not people.ID_RE.fullmatch(to or "") or to == people.UNKNOWN:
            raise KeyError(to)
        name = people.names(ws).get(to, "a colleague")
        _record(cx, ch[-1]["seq"] + 1, to, me, "handover", me, why, f"Handed this project over to {name}: they are "
                                                                    "its owner now.")
    return view(ws)


def _heard(cx: sqlite3.Connection, who: str, ch: list[dict]) -> str | None:
    """When this copy last heard of a person: their work brought in (a zip, the shared folder), or the record that
    made them the owner."""
    seen = [r[0] for r in cx.execute("SELECT at FROM sync_folder_read WHERE person_id=?", (who,)) if r[0]]
    seen += [r[0] for r in cx.execute("SELECT MAX(at) FROM sync_log WHERE person_id=?", (who,)) if r[0]]
    seen += [r["at"] for r in ch if r["owner"] == who and r["at"]]
    return max(seen) if seen else None


def _days_since(at: str | None) -> float | None:
    try:
        t = _dt.datetime.fromisoformat((at or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return (_dt.datetime.now(_dt.timezone.utc) - t).total_seconds() / 86400


def owner_left(ws: Workspace, cx: sqlite3.Connection, ch: list[dict]) -> str | None:
    """Why a collaborator may take the project over, in words (None: they may not): the owner's subfolder is gone
    from the shared folder, or the owner was not heard of for `TAKE_OVER_DAYS`."""
    if not ch:
        return None
    who = ch[-1]["owner"]
    try:
        from .sync import folder

        base = folder.chosen(ws)
        if base is not None and base.is_dir():
            team = base / folder.team_name(ws)
            if team.is_dir() and (team / people.me()).is_dir() and not (team / who).is_dir():
                return "The owner's folder is no longer in the shared folder."
    except (ImportError, OSError):
        pass
    days = _days_since(_heard(cx, who, ch))
    if days is not None and days >= TAKE_OVER_DAYS:
        return f"Nothing was heard of the owner for {int(days)} days."
    return None


def take_over(ws: Workspace, why: str | None = None) -> dict:
    """A collaborator becomes the owner when the owner has left (`owner_left`)."""
    me = people.me()
    with ws.connect() as cx:
        ch = chain(cx)
        if not ch:
            raise NotAllowed("This project has no owner: become its owner instead.")
        if ch[-1]["owner"] == me:
            raise NotAllowed("You are the owner already.")
        left = owner_left(ws, cx, ch)
        if not left:
            raise NotAllowed(f"The owner can hand the project over to you. You can take it over yourself only when "
                             f"the owner has left the shared folder or was not heard of for {TAKE_OVER_DAYS} days.")
        _record(cx, ch[-1]["seq"] + 1, me, me, "takeover", ch[-1]["owner"], why or left,
                "Took this project over from its owner. " + left)
    settle(ws, apply=False)
    return view(ws)


def _term(ch: list[dict], me: str) -> int | None:
    """Where this person's time as the owner began: the place in the chain from which every record names them (1 for
    a project never exchanged, whose first record will be its maker's). None: they are not the owner."""
    if not ch:
        return 1
    if ch[-1]["owner"] != me:
        return None
    start = ch[-1]["seq"]
    for r in reversed(ch):
        if r["owner"] != me:
            break
        start = r["seq"]
    return start


def is_owner(ws: Workspace, cx: sqlite3.Connection | None = None) -> bool:
    """Whether this copy's person is the project's owner (the maker of a project never exchanged is)."""
    from . import sharing

    cx = cx or ws._conn()
    me = people.me()
    if not _has_tables(cx):
        return False
    ch = chain(cx)
    return ch[-1]["owner"] == me if ch else not sharing.exchanged(cx, me)


def accept_adds(ws: Workspace, cx: sqlite3.Connection | None = None) -> bool:
    """The owner's setting: documents a collaborator adds are accepted at once (the default). It is this copy's own
    and holds for one time as the owner: after a hand-over (or a take-over) the new owner starts at the default, and
    so does an owner who has the project back."""
    cx = cx or ws._conn()
    v = ws.meta(ACCEPT_ADDS)
    if not isinstance(v, dict) or not _has_tables(cx):
        return True
    term = _term(chain(cx), people.me())
    return bool(v.get("on")) if term is not None and v.get("term") == term else True


def set_accept_adds(ws: Workspace, on: bool) -> dict:
    """Only the owner's copy sets it (NotAllowed otherwise)."""
    with ws.connect() as cx:
        if not is_owner(ws, cx):
            raise NotAllowed("Only the owner decides whether documents collaborators add are accepted at once.")
        ws.set_meta(ACCEPT_ADDS, {"on": bool(on), "term": _term(chain(cx), people.me())}, cx)
    return view(ws)


def adopt(ws: Workspace, sender: str) -> dict:
    """A new copy made from a colleague's zip (bundle.import_project, for another person than the sender): what the
    sender changed of the project's documents and the owner has not accepted is the sender's, not this copy's
    person's, so the copy starts as the project has its documents:
    - a document of the project the sender removed from their copy (their proposal waits, or was declined) is not
      removed here: the note of its removal goes, so the next round or zip brings it in (or it is fetched from the
      shared folder: `settle`);
    - its passages the sender left out or restored: as the project reads the document;
    - a new reading the sender made stays (it cannot be undone), and stays theirs: it is not proposed again in this
      person's name (`canon_seen.read_from` names the sender; their proposal of the same reading covers it);
    - the sender's tries to make a new reading the owner accepted are forgotten: this copy tries for itself.
    Documents the project does not hold (the sender's own additions) are left to `settle`. Nothing changes in a project
    with no owner. Returns {"restored": [doc ids], "blocks": [doc ids]}."""
    from . import reader as reader2

    out: dict[str, list] = {"restored": [], "blocks": []}
    with ws.connect() as cx:
        if not _has_tables(cx):
            return out
        ch = chain(cx)
        if not ch:
            return out
        K = canon(cx, ch)
        held = {r[0] for r in cx.execute("SELECT doc_id FROM documents")}
        clash = {r[0] for r in cx.execute("SELECT key FROM sync_copies WHERE kind='document'")}
        cx.execute("UPDATE canon_seen SET read_tried=NULL, read_note=NULL, read_from=NULL")
        for doc, k in sorted(K.items()):
            if k["state"] != "in" or doc in clash:
                continue
            if doc not in held:
                cx.execute("DELETE FROM sync_removed WHERE kind='document' AND key=?", (doc,))
                cx.execute("UPDATE canon_seen SET state_n=NULL, gone=NULL WHERE doc=?", (doc,))
                out["restored"].append(doc)
                continue
            reader = cx.execute("SELECT COALESCE(reader, 1) FROM documents WHERE doc_id=?", (doc,)).fetchone()[0]
            if reader > (k["reader"] or 1):  # the sender's new reading: theirs (`_reconcile` does not propose it again)
                cx.execute("INSERT INTO canon_seen(doc, read_from) VALUES (?,?) ON CONFLICT(doc) DO UPDATE SET "
                           "read_from=excluded.read_from", (doc, sender))
            have = {fp: [1 if inc else 0, kind] for fp, inc, kind in
                    cx.execute("SELECT fp, included, kind FROM block_choices WHERE doc_id=?", (doc,))}
            if have != k["blocks"]:
                cx.execute("DELETE FROM block_choices WHERE doc_id=?", (doc,))
                cx.executemany("INSERT OR REPLACE INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES "
                               "(?,?,?,?,?,?)", [(doc, fp, v[0], v[1], k["by"], k["at"])
                                                 for fp, v in sorted(k["blocks"].items())])
                reader2.apply_choices(cx, doc)
                out["blocks"].append(doc)
            cx.execute("INSERT INTO canon_seen(doc, blocks_n, blocks_json) VALUES (?,?,?) ON CONFLICT(doc) DO UPDATE "
                       "SET blocks_n=excluded.blocks_n, blocks_json=excluded.blocks_json",
                       (doc, k["blocks_n"], json.dumps(k["blocks"], sort_keys=True)))
        if out["blocks"]:
            ws.bump_corpus(cx)
    return out


# ---------------------------------------------------------------------------------------------
# the documents as accepted, proposals and decisions: reading them
# ---------------------------------------------------------------------------------------------
def canon(cx: sqlite3.Connection, ch: list[dict] | None = None) -> dict[str, dict]:
    """{document id: the row that counts}: written by whoever was the owner of the place in the chain it names; of
    those, the latest owner's with the highest number. `blocks` and `ai_hist` are read from their JSON."""
    ch = chain(cx) if ch is None else ch
    owners = {r["seq"]: r["owner"] for r in ch}
    out: dict[str, dict] = {}
    if not owners:
        return out
    for r in _rows(cx, "SELECT * FROM canon"):
        if owners.get(r["owner_seq"]) != r["by"] or not isinstance(r["n"], int):
            continue
        cur = out.get(r["doc"])
        if cur is None or (r["owner_seq"], r["n"]) > (cur["owner_seq"], cur["n"]):
            out[r["doc"]] = r
    for r in out.values():
        r["blocks"] = _clean_blocks(_json(r.get("blocks_json"), {}))
        r["ai_hist"] = [h for h in _json(r.get("ai_hist_json"), []) if isinstance(h, list) and len(h) == 2]
        r["ai_access"] = _level(r.get("ai_access"))
        for c in ("state_n", "read_n", "ai_n", "blocks_n"):
            r[c] = r[c] if isinstance(r[c], int) else 0
    return out


def _clean_blocks(b: dict) -> dict[str, list]:
    return {str(fp): [1 if v[0] else 0, str(v[1]) if len(v) > 1 and v[1] is not None else None]
            for fp, v in b.items() if isinstance(v, list) and v}


def _decisions(cx: sqlite3.Connection, ch: list[dict]) -> dict[str, dict]:
    """{proposal id: the decision that counts}."""
    owners = {r["seq"]: r["owner"] for r in ch}
    out: dict[str, dict] = {}
    for r in _rows(cx, "SELECT * FROM decisions"):
        if owners.get(r["owner_seq"]) != r["by"] or r["verdict"] not in ("accept", "decline"):
            continue
        # of two answers that count, the later owner's (a former owner's late answer, given offline after a
        # take-over, never overrides the owner's); within one time as owner, the first
        cur = out.get(r["proposal"])
        if cur is None or (-r["owner_seq"], r["at"] or "") < (-cur["owner_seq"], cur["at"] or ""):
            out[r["proposal"]] = r
    return out


def _proposals(cx: sqlite3.Connection) -> dict[str, dict]:
    out = {}
    for r in _rows(cx, "SELECT * FROM proposals ORDER BY at, id"):
        if r["kind"] in KINDS and isinstance(r["doc"], str) and people.ID_RE.fullmatch(r["by"] or ""):
            r["detail"] = _json(r.get("detail_json"), {})
            out[r["id"]] = r
    return out


def level_at(hist: list, n: int) -> str | None:
    """Who might read a document with AI, as the owner had it at change number `n` (the first setting, before that)."""
    out = None
    for at, lv in hist:
        if out is None or (isinstance(at, int) and at <= n):
            out = lv
    return out


def stale_strict(cx: sqlite3.Connection, doc: str, theirs: str, their_n: Any) -> bool:
    """Whether a colleague's stricter AI setting of a document is only the one the owner has loosened since, in a copy
    that has not followed that decision yet (sync/merge.py `_stricter` then leaves this copy's setting as it is). A
    setting made stricter by a person who had followed the owner's last word (`their_n`) is never stale."""
    k = canon(cx).get(doc)
    if not k or k["state"] != "in":
        return False
    n = their_n if isinstance(their_n, int) else 0
    if n >= k["ai_n"]:
        return False
    mine = cx.execute("SELECT ai_n FROM canon_seen WHERE doc=?", (doc,)).fetchone()
    if not mine or (mine[0] or 0) < k["ai_n"]:
        return False  # this copy has not followed it either: the stricter setting holds
    return level_at(k["ai_hist"], n) == theirs


def not_wanted(cx: sqlite3.Connection, me: str | None = None) -> set[str]:
    """The documents a colleague's work must not bring (back) into this copy: those the owner removed, and those a
    collaborator added that the owner declined (or that they took back), unless this copy's own person proposed
    them. Empty in a project with no owner."""
    ch = chain(cx)
    if not ch:
        return set()
    me = me or people.me()
    K = canon(cx, ch)
    out = {d for d, k in K.items() if k["state"] == "removed"}
    dec = _decisions(cx, ch)
    by_doc: dict[str, list[str]] = {}
    for p in _proposals(cx).values():
        if p["kind"] != "add" or p["doc"] in K:
            continue
        d = dec.get(p["id"])
        gone = bool(p["taken_back_at"]) or (d is not None and d["verdict"] == "decline")
        by_doc.setdefault(p["doc"], []).append("mine" if p["by"] == me else "gone" if gone else "open")
    out |= {d for d, st in by_doc.items() if "mine" not in st and "open" not in st}
    mine_again = {r[0] for r in cx.execute("SELECT doc_id FROM documents")}  # (held here: nothing to keep out)
    return out - mine_again


# ---------------------------------------------------------------------------------------------
# one look at this copy (`settle`)
# ---------------------------------------------------------------------------------------------
class _Ctx:
    def __init__(self, ws: Workspace, cx: sqlite3.Connection, me: str):
        from .sync.common import text_fps
        from .sync.folder import ai_settings

        self.ws, self.cx, self.me = ws, cx, me
        self.chain = chain(cx)
        self.owner = self.chain[-1]["owner"] if self.chain else None
        self.seq = self.chain[-1]["seq"] if self.chain else 0
        self.is_owner = self.owner == me
        self.K = canon(cx, self.chain)
        self.n = max([r[0] or 0 for r in cx.execute("SELECT MAX(n) FROM canon")] + [0])
        self.props = _proposals(cx)
        self._by_doc: dict[tuple[str, str], list[dict]] | None = None
        self.dec = _decisions(cx, self.chain)
        self.S = {r["doc"]: r for r in _rows(cx, "SELECT * FROM canon_seen")}
        self.own_rows = {r["doc"]: r for r in _rows(cx, "SELECT doc, state_n, ai_n, blocks_n FROM canon WHERE by=?", (me,))}
        self.dirty: set[str] = set()
        clash = {r[0] for r in cx.execute("SELECT key FROM sync_copies WHERE kind='document'")}
        fps = text_fps(cx)
        self.docs = {r["doc_id"]: dict(r, text_fp=fps.get(r["doc_id"]))
                     for r in _rows(cx, "SELECT doc_id, sha1, COALESCE(reader, 1) AS reader, title FROM documents")
                     if r["doc_id"] not in clash}
        self.levels = ai_settings(ws, cx)
        self.choices: dict[str, dict[str, list]] = {}
        for d, fp, inc, kind in cx.execute("SELECT doc_id, fp, included, kind FROM block_choices"):
            self.choices.setdefault(d, {})[fp] = [1 if inc else 0, kind]
        self.removed_by_me = {r[0]: r[1] for r in cx.execute("SELECT key, at FROM sync_removed WHERE kind='document' "
                                                             "AND person_id=?", (me,))}
        self.names = people.names(ws)
        self.new: list[dict] = []        # proposals written now
        self.report: dict[str, Any] = {"owner": self.owner, "proposed": [], "accepted": [], "applied": [],
                                       "moves": [], "fetch": [], "notes": []}
        self.backed_up = False

    # this copy's record of how far it followed the owner
    def seen(self, doc: str) -> dict:
        s = self.S.get(doc)
        if s is None:
            s = self.S[doc] = {"doc": doc, **{c: None for c in _SEEN}}
        return s

    def mark(self, doc: str, **cols: Any) -> None:
        s = self.seen(doc)
        for c, v in cols.items():
            if s.get(c) != v:
                s[c] = v
                self.dirty.add(doc)

    def save(self) -> None:
        for d in sorted(self.dirty):
            s = self.S[d]
            self.cx.execute(f"INSERT OR REPLACE INTO canon_seen(doc, {', '.join(_SEEN)}) VALUES "
                            f"({','.join('?' * (len(_SEEN) + 1))})", (d, *[s.get(c) for c in _SEEN]))
        self.dirty.clear()

    def ahead_mine(self, doc: str, part: str) -> bool:
        """This copy followed its own row of the document, which does not count (written as the owner as far as this
        person knew: a former owner's late change, the other of two claims made at once): what it says of `part`
        ("state_n", "ai_n", "blocks_n") is this person's own change, a proposal now, not the project's word."""
        s, k, r = self.S.get(doc) or {}, self.K.get(doc), self.own_rows.get(doc)
        return bool(k and r and k["by"] != self.me and isinstance(s.get(part), int) and s[part] > (k.get(part) or 0)
                    and r[part] == s[part])

    # proposals
    def about(self, kind: str, doc: str) -> list[dict]:
        """Everyone's proposals of this kind for this document (looked up by document: a long history of proposals
        and many documents do not make a look at the copy slow)."""
        if self._by_doc is None:
            self._by_doc = {}
            for p in self.props.values():
                self._by_doc.setdefault((p["kind"], p["doc"]), []).append(p)
        return self._by_doc.get((kind, doc), [])

    def mine(self, kind: str, doc: str) -> list[dict]:
        return [p for p in self.about(kind, doc) if p["by"] == self.me]

    def state(self, p: dict) -> tuple[str, str | None]:
        return state_of(p, self.K, self.dec)

    def propose(self, kind: str, doc: str, title: str | None, key: Iterable, detail: dict) -> dict | None:
        pid = _id(kind, doc, self.me, *key)
        if pid in self.props:
            return None
        p = {"id": pid, "kind": kind, "doc": doc, "title": title, "by": self.me, "at": now(), "detail": detail,
             "detail_json": json.dumps(detail, ensure_ascii=False), "taken_back_at": None}
        self.cx.execute("INSERT INTO proposals(id, kind, doc, title, by, at, detail_json, taken_back_at) VALUES "
                        "(?,?,?,?,?,?,?,NULL)", (pid, kind, doc, title, self.me, p["at"], p["detail_json"]))
        self.props[pid] = p
        if self._by_doc is not None:
            self._by_doc.setdefault((kind, doc), []).append(p)
        self.new.append(p)
        self.report["proposed"].append({"id": pid, "kind": kind, "doc": doc, "title": title})
        return p

    # the documents as accepted (the owner's copy writes them)
    def put(self, doc: str, bump: Iterable[str], **cols: Any) -> dict:
        """Write this owner's row for `doc`: the row that counts, with `cols` changed and the parts in `bump`
        ("state", "read", "ai", "blocks") numbered anew."""
        self.n += 1
        k = dict(self.K.get(doc) or {"doc": doc, "state": "in", "state_n": 0, "read_n": 0, "ai_n": 0, "blocks_n": 0,
                                     "ai_hist": [], "blocks": {}, "sha1": None, "title": None, "text_fp": None,
                                     "reader": None, "ai_access": None})
        new = not self.K.get(doc)
        k.update(cols)
        k.update(by=self.me, owner_seq=self.seq, n=self.n, at=now())
        for part in (("state", "read", "ai", "blocks") if new else bump):
            k[f"{part}_n"] = self.n
        if "ai" in bump or new:
            k["ai_hist"] = (k.get("ai_hist") or []) + [[self.n, k["ai_access"]]]
        k["blocks_json"] = json.dumps(k.get("blocks") or {}, sort_keys=True)
        k["ai_hist_json"] = json.dumps(k["ai_hist"][-50:])
        self.cx.execute("INSERT OR REPLACE INTO canon(doc, by, owner_seq, n, state, state_n, sha1, title, text_fp, "
                        "reader, read_n, ai_access, ai_n, ai_hist_json, blocks_json, blocks_n, at) VALUES "
                        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (doc, self.me, self.seq, k["n"], k["state"], k["state_n"], k["sha1"], k["title"], k["text_fp"],
                         k["reader"], k["read_n"], k["ai_access"], k["ai_n"], k["ai_hist_json"], k["blocks_json"],
                         k["blocks_n"], k["at"]))
        self.K[doc] = k
        return k

    def restamp(self) -> None:
        """The owner's copy writes each row of an earlier owner that still counts again, unchanged, as its own (under
        its place in the chain; no part is numbered anew, so no copy sees a change). `canon` takes the row of the
        latest place first, so a row a former owner writes late (offline after a take-over, still believing they own
        the project) never counts over the owner's: their change is then theirs alone (a proposal, or held)."""
        for doc, k in sorted(self.K.items()):
            if k["owner_seq"] < self.seq:
                self.put(doc, ())

    def put_from_here(self, doc: str, bump: Iterable[str] = ()) -> dict:
        """The owner's row for `doc` as this copy has it; this copy has then followed it in every part."""
        L = self.docs[doc]
        k = self.put(doc, bump, state="in", sha1=(L["sha1"] or "").split("~")[0] or None, title=L["title"],
                     text_fp=L["text_fp"], reader=L["reader"], ai_access=_level(self.levels.get(doc)),
                     blocks=dict(self.choices.get(doc) or {}))
        self.mark(doc, state_n=k["state_n"], read_n=k["read_n"], ai_n=k["ai_n"], ai_level=k["ai_access"],
                  blocks_n=k["blocks_n"], blocks_json=json.dumps(k["blocks"], sort_keys=True))
        return k

    # changes to this copy
    def backup(self) -> None:
        if not self.backed_up:
            from .sync import _backup

            try:
                _backup(self.ws)
            except (OSError, sqlite3.Error):
                pass
            self.backed_up = True

    def remove_here(self, doc: str, why: str, by: str | None) -> None:
        """Remove a document from this copy because the owner said so: as when a person removes it (its checks keep
        their grades as records; the research log says why), after a backup; the note of its removal is the owner's,
        not this person's, so it is not taken for this person's own wish."""
        self.backup()
        title = self.docs[doc]["title"]
        self.ws.remove_document(doc, why=why)
        self.cx.execute("UPDATE sync_removed SET person_id=? WHERE kind='document' AND key=?", (by or self.owner, doc))
        self.docs.pop(doc, None)
        self.choices.pop(doc, None)
        self.mark(doc, gone=1, came_from=None)
        self.report["applied"].append({"kind": "remove", "doc": doc, "title": title})

    def set_level(self, doc: str, level: str, text: str, data: dict) -> None:
        from . import researchlog
        from .access import relabel

        title = self.docs[doc]["title"]
        self.cx.execute("UPDATE documents SET ai_access=? WHERE doc_id=?", (level, doc))
        self.levels[doc] = level
        researchlog.record(self.cx, "ai-access", f"Who may read {_q(title)} with AI: "
                                                 f"{researchlog.access_words(level)}{text}",
                           "document", doc, title, data={"documents": [doc], "setting": level, **data})
        relabel(self.cx)
        self.report["applied"].append({"kind": "ai", "doc": doc, "title": title, "now": level})

    def set_blocks(self, doc: str, want: dict[str, list], by: str | None = None) -> None:
        """This copy's choices of the document's blocks become `want`. A choice that stays as it was keeps who made it
        and when; one that is new or changed is `by`'s (the proposer of an accepted change), else the owner's."""
        from . import reader as reader2

        if want == (self.choices.get(doc) or {}):
            return
        had = {r[0]: r[1:] for r in self.cx.execute("SELECT fp, included, person_id, at FROM block_choices WHERE "
                                                    "doc_id=?", (doc,))}
        at = now()
        rows = []
        for fp, v in sorted(want.items()):
            h = had.get(fp)
            same = h is not None and (1 if h[0] else 0) == v[0]
            rows.append((doc, fp, v[0], v[1], (h[1] if same else None) or by or self.owner, (h[2] if same else None) or at))
        self.cx.execute("DELETE FROM block_choices WHERE doc_id=?", (doc,))
        self.cx.executemany("INSERT OR REPLACE INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES "
                            "(?,?,?,?,?,?)", rows)
        self.choices[doc] = dict(want)
        reader2.apply_choices(self.cx, doc)
        self.ws.bump_corpus(self.cx)
        self.report["applied"].append({"kind": "blocks", "doc": doc, "title": self.docs[doc]["title"]})


def state_of(p: dict, K: dict[str, dict], dec: dict[str, dict]) -> tuple[str, str | None]:
    """A proposal's state and, for one that no longer needs an answer, why: ("waiting" | "accepted" | "declined" |
    "taken_back" | "replaced" | "moot", words or None)."""
    det = p["detail"]
    d = dec.get(p["id"])
    if d is not None:
        return ("accepted" if d["verdict"] == "accept" else "declined"), None
    if p["taken_back_at"]:
        return ("replaced" if p["taken_back_at"].startswith("replaced") else "taken_back"), None
    k = K.get(p["doc"])
    kind = p["kind"]
    if kind == "add":
        if k is not None and k["state_n"] > (det.get("state_n") or 0):
            if k["state"] == "in":
                return "accepted", "The owner added it too."
            return "moot", "The owner removed this document from the project."
        return "waiting", None
    if k is None:
        return "moot", "The document is not one of the project's documents (it was added by a collaborator and not accepted)."
    if k["state"] == "removed":
        return ("accepted", "The owner removed it.") if kind == "remove" else \
            ("moot", "The document was removed from the project since.")
    if kind == "remove" and k["state_n"] > (det.get("state_n") or 0):
        return "moot", "The document was removed from the project and added to it again since."
    if kind == "reread" and (k["reader"] or 1) >= (det.get("to_reader") or 0):
        return "accepted", "The project's reading of it is as new already."
    if kind == "loosen" and k["ai_n"] != det.get("ai_n"):
        if RANK[k["ai_access"]] <= RANK[_level(det.get("to"))]:
            return "accepted", "The owner has set it so since."
        return "moot", "Who may read it with AI was changed since: propose it again if it still holds."
    if kind == "blocks" and not _delta(_apply_delta(k["blocks"], det.get("delta") or {}), k["blocks"]):
        return "accepted", "The project reads it so already."
    return "waiting", None


def _delta(mine: dict, base: dict) -> dict:
    """What `mine` changes of the choices `base`: {fp: [included, kind]} set or changed, {fp: None} taken away."""
    out: dict[str, Any] = {fp: v for fp, v in mine.items() if (base.get(fp) or [None])[0] != v[0]}
    out.update({fp: None for fp in base if fp not in mine})
    return out


def _apply_delta(base: dict, delta: dict) -> dict:
    out = dict(base)
    for fp, v in delta.items():
        if v is None:
            out.pop(fp, None)
        elif isinstance(v, list) and v:
            side = fp.split(":", 1)[0] if fp.startswith(("start:", "end:")) else None
            if side:  # the text starts (or ends) in one place only
                for other in [f for f in out if f.startswith(side + ":")]:
                    out.pop(other)
            out[fp] = [1 if v[0] else 0, v[1] if len(v) > 1 else None]
    return out


def _delta_words(delta: dict) -> dict:
    out = {"left_out": 0, "restored": 0, "undone": 0, "bounds": 0}
    for fp, v in delta.items():
        if fp.startswith(("start:", "end:")):
            out["bounds"] += 1
        elif v is None:
            out["undone"] += 1
        else:
            out["restored" if v[0] else "left_out"] += 1
    return out


def settle(ws: Workspace, apply: bool = True, moves: bool = False, leaving: bool = False, wait: bool = True) -> dict:
    """One look at this copy (see the module's notes). `apply` False: only what is safe at any moment (proposals and
    the owner's rows are written, AI settings are held or followed); a document is removed, blocks are changed and a
    missing document is fetched only with `apply`, which a caller gives when no other work of the project runs (a
    round of the shared folder, a zip brought in, the owner's own click). `moves`: also make the new readings that
    are due, here and now (tests, the command line; the app starts a job instead: `moves_due`). `leaving`: the project
    is about to leave this computer (a project never exchanged gets its owner). `wait` False (the page's look): when
    other work holds the project's database now (a document being read again, a merge), nothing is written and the
    report says `"busy": True`; the next look or round writes it.

    Returns {"owner", "proposed": [{"id", "kind", "doc", "title"}], "accepted": [ids accepted at once], "applied":
    [{"kind", "doc", "title"}], "moves": [doc ids whose new reading is due here], "fetch": [doc ids], "notes"}."""
    if not wait:
        cx0 = ws._conn()
        before = cx0.execute("PRAGMA busy_timeout").fetchone()[0]
        cx0.execute("PRAGMA busy_timeout=300")
        try:
            return settle(ws, apply, moves, leaving)
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) and "busy" not in str(e):
                raise
            return {"owner": None, "proposed": [], "accepted": [], "applied": [], "moves": [], "fetch": [], "notes": [],
                    "busy": True}
        finally:
            cx0.execute(f"PRAGMA busy_timeout={int(before)}")
    me = people.me()
    with ws.connect() as cx:
        if not _has_tables(cx):
            return {"owner": None, "proposed": [], "accepted": [], "applied": [], "moves": [], "fetch": [], "notes": []}
        if leaving:
            ensure_owner(cx, me)
        ctx = _Ctx(ws, cx, me)
        if ctx.owner is None:
            return ctx.report
        if ctx.is_owner:
            ctx.restamp()
        if ctx.is_owner and apply and accept_adds(ws):
            for p in list(ctx.props.values()):
                if p["kind"] == "add" and p["by"] != me and ctx.state(p)[0] == "waiting" and p["doc"] not in ctx.K \
                        and p["doc"] not in ctx.removed_by_me:
                    _accept(ctx, p, auto=True)
        for doc in sorted(set(ctx.docs) | set(ctx.K)):
            _reconcile(ctx, doc, apply)
        _hold_looser(ctx)
        ctx.save()
        _log(ctx)
        report = ctx.report
    if apply and report["fetch"]:
        report["fetched"] = _fetch(ws, report["fetch"])
    if moves:
        report["moved"] = [move_now(ws, d) for d in report["moves"]]
    return report


def _reconcile(ctx: _Ctx, doc: str, apply: bool) -> None:
    L, k, s = ctx.docs.get(doc), ctx.K.get(doc), ctx.S.get(doc) or {}
    me = ctx.me
    # ---- whether the document is one of the project's -------------------------------------------------------
    if L is not None and (k is None or k["state"] == "removed"):
        again = k is not None
        if again and (s.get("state_n") or 0) != k["state_n"] and not ctx.ahead_mine(doc, "state_n"):
            # the owner removed it: not followed here yet
            if apply:
                ctx.remove_here(doc, f"The owner ({ctx.names.get(k['by'], 'a colleague')}) removed it from the project.",
                                k["by"])
                ctx.mark(doc, state_n=k["state_n"])
            return
        era = k["state_n"] if again else 0  # an addition proposed since the project last had it (or never had it)
        mine = [p for p in ctx.mine("add", doc) if (p["detail"].get("state_n") or 0) == era]
        others = [p for p in ctx.about("add", doc) if p["by"] != me and (p["detail"].get("state_n") or 0) == era]
        open_others = [p for p in others if ctx.state(p)[0] == "waiting"]
        closed_others = [p for p in others if ctx.state(p)[0] in ("declined", "taken_back")]
        if ctx.is_owner and (again or not others or s.get("gone")) and not s.get("came_from") and \
                not any(ctx.state(p)[0] != "accepted" for p in mine):  # (gone: it left her copy, she added it again)
            ctx.put_from_here(doc, ("state", "read", "ai", "blocks"))  # the owner's own addition
            ctx.mark(doc, gone=None)
        elif mine or open_others:
            pass  # proposed: waiting for the owner (or declined: it stays in the proposer's copy only)
        elif closed_others and not s.get("gone"):  # declined, or taken back by who added it: it leaves this copy
            if apply:
                who = ctx.names.get(closed_others[0]["by"], "a colleague")
                ctx.remove_here(doc, f"{who} added it and the owner did not accept it into the project.", ctx.owner)
            return
        elif ctx.is_owner:
            pass  # it came from a colleague who has not proposed it (yet): the owner's to add by hand
        elif not s.get("came_from") or s.get("gone"):
            ctx.propose("add", doc, L["title"], (k["state_n"] if again else 0,),
                        {"sha1": (L["sha1"] or "").split("~")[0] or None, "text_fp": L["text_fp"], "reader": L["reader"],
                         "ai_access": _level(ctx.levels.get(doc)), "blocks": ctx.choices.get(doc) or {},
                         "state_n": k["state_n"] if again else 0, "again": again})
            ctx.mark(doc, gone=None)
        return
    if L is None:
        if s.get("came_from"):  # it came from a colleague once, and has left this copy since: added again, it is new
            ctx.mark(doc, came_from=None)
        if k is None:
            return
        if k["state"] == "removed":
            ctx.mark(doc, state_n=k["state_n"])
            return
        at = ctx.removed_by_me.get(doc)
        mine = [p for p in ctx.mine("remove", doc) if p["detail"].get("removed_at") == at] if at else []
        if at and (all((p["detail"].get("state_n") or 0) < k["state_n"] for p in mine) if mine
                   else bool(s.get("state_n")) and s["state_n"] < k["state_n"]):  # (followed before, changed since)
            # this person's removal is spent: the project took the document out and in again since (their removal
            # accepted, or the owner's own, then an addition accepted): it comes back here as to every copy
            if not apply:
                return
            ctx.cx.execute("DELETE FROM sync_removed WHERE kind='document' AND key=? AND person_id=?", (doc, me))
            ctx.removed_by_me.pop(doc, None)
            at = None
        if at:  # this copy's person removed it
            if ctx.is_owner and not any(ctx.state(p)[0] != "accepted" for p in mine):
                ctx.put(doc, ("state",), state="removed")
                ctx.mark(doc, state_n=ctx.K[doc]["state_n"])
            elif not ctx.is_owner and not mine:
                ctx.propose("remove", doc, k["title"], (at,), {"removed_at": at, "state_n": k["state_n"]})
        elif (s.get("state_n") or 0) != k["state_n"] and not ctx.ahead_mine(doc, "state_n"):
            # one of the project's documents that is not here
            if apply:
                ctx.cx.execute("DELETE FROM sync_removed WHERE kind='document' AND key=? AND person_id != ?", (doc, me))
                ctx.report["fetch"].append(doc)
                ctx.mark(doc, state_n=k["state_n"], gone=None)
        return
    # ---- one of the project's documents, held here ----------------------------------------------------------
    ctx.mark(doc, state_n=k["state_n"], gone=None)
    # its reading
    if L["text_fp"] == k["text_fp"] or L["reader"] == (k["reader"] or 1):
        ctx.mark(doc, read_n=k["read_n"])
    elif L["reader"] > (k["reader"] or 1):  # read again here
        # a reading in the zip this copy was made from (`adopt`), that its sender proposed, is theirs: not proposed
        # again in this person's name
        same = [p for p in ctx.about("reread", doc) if p["detail"].get("to_fp") == L["text_fp"]
                and p["by"] in (me, s.get("read_from"))]
        mine = [p for p in same if p["by"] == me]
        if ctx.is_owner and not any(ctx.state(p)[0] != "accepted" for p in mine):
            k = ctx.put(doc, ("read",), text_fp=L["text_fp"], reader=L["reader"])
            ctx.mark(doc, read_n=k["read_n"])
        elif not ctx.is_owner and not same:
            ctx.propose("reread", doc, L["title"], (L["text_fp"],),
                        {"from_fp": k["text_fp"], "from_reader": k["reader"] or 1, "to_fp": L["text_fp"],
                         "to_reader": L["reader"]})
    elif (s.get("read_tried") or 0) != k["read_n"]:  # the project reads it with a newer reader: due here
        ctx.report["moves"].append(doc)
    # who may read it with AI. First the project's word not followed here yet (in the owner's copy too: a new owner
    # whose copy has not followed the last changes of the one before must not undo them); then, in the owner's copy,
    # what differs is the owner's own change
    # A copy that followed a row which does not count (`ahead`: a former owner's late one) follows the project's
    # again only where it is stricter: a stricter setting holds at once, and a looser one never comes from such a row.
    # When that row was this person's own, their looser setting is a proposal to the owner now.
    lv, kv = _level(ctx.levels.get(doc)), k["ai_access"]
    behind = (s.get("ai_n") or 0) < k["ai_n"] or s.get("ai_n") is None
    if behind or (s.get("ai_n") or 0) != k["ai_n"]:
        if RANK[kv] > RANK[lv] and not behind and ctx.ahead_mine(doc, "ai_n"):
            hold_loosening(ctx.ws, ctx.cx, [doc], lv)
            ctx.set_level(doc, kv, ": held at the project's setting (a looser one is the owner's to decide).",
                          {"from": "owner", "held": True})
        elif RANK[kv] > RANK[lv]:
            ctx.set_level(doc, kv, ", as the owner set it (the stricter setting holds in every copy).",
                          {"from": "owner"})
        elif RANK[kv] < RANK[lv] and s.get("ai_level") == lv and behind:  # (not made stricter here meanwhile)
            ctx.set_level(doc, kv, ", as the owner decided for the project.", {"from": "owner"})
        ctx.mark(doc, ai_n=k["ai_n"], ai_level=kv)
        lv = _level(ctx.levels.get(doc))
    if ctx.is_owner and lv != kv:
        k = ctx.put(doc, ("ai",), ai_access=lv)
        ctx.mark(doc, ai_n=k["ai_n"], ai_level=lv)
    # the blocks left out and restored: the project's word first (only with `apply`), with this person's own choices
    # on top; then what differs is a proposal, or, in the owner's copy, the owner's own change
    mine_now = ctx.choices.get(doc) or {}
    if not s.get("blocks_n") and s.get("blocks_json") is None and not mine_now:
        if k["blocks"] and apply:  # a document new here: read as the project reads it
            ctx.set_blocks(doc, k["blocks"])
        if apply or not k["blocks"]:
            ctx.mark(doc, blocks_n=k["blocks_n"], blocks_json=json.dumps(k["blocks"], sort_keys=True))
        return
    if ((s.get("blocks_n") or 0) != k["blocks_n"] and not ctx.ahead_mine(doc, "blocks_n")) or s.get("blocks_json") is None:
        if not apply:
            return
        base = _clean_blocks(_json(s.get("blocks_json"), {})) if s.get("blocks_json") is not None else dict(k["blocks"])
        # the project's, with this person's own on top; what the project took of theirs (an accepted proposal) is the
        # project's now, so its later word on those passages holds here too
        taken: dict[str, Any] = {}
        for p in ctx.mine("blocks", doc):
            if ctx.state(p)[0] == "accepted":
                taken.update(p["detail"].get("delta") or {})
        own = {fp: v for fp, v in _delta(mine_now, base).items() if not (fp in taken and _same_choice(taken[fp], v))}
        ctx.set_blocks(doc, _apply_delta(k["blocks"], own))
        ctx.mark(doc, blocks_n=k["blocks_n"], blocks_json=json.dumps(k["blocks"], sort_keys=True))
        mine_now = ctx.choices.get(doc) or {}
    if ctx.is_owner:
        # what this person proposed before they were the owner and the project has not taken (it waits, was declined
        # or taken back) stays theirs: it becomes the project's by an answer to that proposal, never along with the
        # owner's next change of the document
        own = _own_delta(ctx, doc, mine_now, k["blocks"])
        want = _apply_delta(k["blocks"], own)
        if own and want != k["blocks"]:
            k = ctx.put(doc, ("blocks",), blocks=want)
            ctx.mark(doc, blocks_n=k["blocks_n"], blocks_json=json.dumps(k["blocks"], sort_keys=True))
        return
    delta = _delta(mine_now, k["blocks"])
    if delta:
        digest = _digest(delta)
        if not any(p["detail"].get("digest") == digest for p in ctx.mine("blocks", doc)):
            for p in ctx.mine("blocks", doc):  # an earlier one that still waits is replaced by this one
                if ctx.state(p)[0] == "waiting":
                    p["taken_back_at"] = "replaced " + now()
                    ctx.cx.execute("UPDATE proposals SET taken_back_at=? WHERE id=?", (p["taken_back_at"], p["id"]))
            ctx.propose("blocks", doc, L["title"], (digest,), {"delta": delta, "digest": digest,
                                                               "blocks_n": k["blocks_n"], **_delta_words(delta)})


def _own_delta(ctx: _Ctx, doc: str, mine_now: dict, project: dict) -> dict:
    """The owner's own changes of a document's blocks against the project's: their copy's choices, without what they
    proposed of them when they were not the owner and the project has not taken."""
    kept: dict[str, Any] = {}
    for p in ctx.mine("blocks", doc):
        if ctx.state(p)[0] in ("waiting", "declined", "taken_back"):
            kept.update(p["detail"].get("delta") or {})
    return {fp: v for fp, v in _delta(mine_now, project).items() if not (fp in kept and _same_choice(kept[fp], v))}


def _same_choice(a: Any, b: Any) -> bool:
    """Two entries of a delta of block choices say the same: both take a choice away, or both read it in (or out)."""
    return (a is None and b is None) or (isinstance(a, list) and isinstance(b, list) and bool(a) and bool(b)
                                         and (1 if a[0] else 0) == (1 if b[0] else 0))


def _hold_looser(ctx: _Ctx) -> None:
    """In a collaborator's copy no document is open to more AI than the owner accepted (a project default made looser,
    a setting changed some other way): it is held at the project's setting."""
    if ctx.is_owner:
        return
    for doc, L in ctx.docs.items():
        k = ctx.K.get(doc)
        s = ctx.S.get(doc) or {}
        if k is None or k["state"] != "in" or (s.get("ai_n") or 0) != k["ai_n"]:
            continue
        if RANK[_level(ctx.levels.get(doc))] < RANK[k["ai_access"]]:
            ctx.set_level(doc, k["ai_access"], ": held at the project's setting (a looser one is the owner's to "
                                               "decide).", {"from": "owner", "held": True})


def _fetch(ws: Workspace, docs: list[str]) -> list[str]:
    try:
        from .sync import folder

        if folder.chosen(ws) is None:
            return []
        return folder.fetch_documents(ws, docs)
    except Exception:  # noqa: BLE001 - best effort: the document comes with a colleague's next round, or by hand
        import traceback

        traceback.print_exc()
        return []


_WHAT = {"add": "adding {t}", "remove": "removing {t} from the project",
         "reread": "reading {t} again with the new reader", "blocks": "changing which passages of {t} are read",
         "loosen": "letting more AI read {t}"}


def what(p: dict) -> str:
    """A proposal in a few words: "removing “Annual report 2024” from the project"."""
    out = _WHAT[p["kind"]].format(t=_q(p.get("title")))
    if p["kind"] == "loosen":
        from .researchlog import access_words

        out += f" ({access_words(_level(p['detail'].get('to')))})"
    return out


def _log(ctx: _Ctx) -> None:
    """The research log: what this copy proposed now, and what the owner's copy accepted at once."""
    from . import researchlog

    by_kind: dict[str, list[dict]] = {}
    for p in ctx.new:
        by_kind.setdefault(p["kind"], []).append(p)
    for kind, ps in by_kind.items():
        if len(ps) == 1:
            p = ps[0]
            researchlog.record(ctx.cx, "proposal", f"Proposed to the owner: {what(p)}. It waits for the owner's answer"
                                                   + ("; until then it stays as it was here." if kind == "loosen"
                                                      else "; your copy keeps the change."),
                               "document", p["doc"], p["title"], data={"proposal": p["id"], "kind": kind})
        else:
            names = ", ".join(_q(p["title"], 50) for p in ps[:3]) + (" and more" if len(ps) > 3 else "")
            researchlog.record(ctx.cx, "proposal", f"Proposed to the owner: {_WHAT[kind].format(t=f'{len(ps)} documents')} "
                                                   f"({names}). They wait for the owner's answer.",
                               "documents", None, None, data={"proposals": [p["id"] for p in ps], "kind": kind})
    auto = [ctx.props[i] for i in ctx.report["accepted"] if i in ctx.props]
    if auto:
        names = ", ".join(_q(p["title"], 50) for p in auto[:3]) + (" and more" if len(auto) > 3 else "")
        who = sorted({ctx.names.get(p["by"], "a colleague") for p in auto})
        researchlog.record(ctx.cx, "proposal-accepted",
                           f"Accepted at once, as the owner's setting says: {len(auto)} "
                           f"{'document' if len(auto) == 1 else 'documents'} added by {', '.join(who)} ({names}).",
                           "document" if len(auto) == 1 else "documents", auto[0]["doc"] if len(auto) == 1 else None,
                           auto[0]["title"] if len(auto) == 1 else None,
                           data={"proposals": [p["id"] for p in auto], "auto": True})
    ctx.new.clear()


# ---------------------------------------------------------------------------------------------
# the owner's word, and the proposer's
# ---------------------------------------------------------------------------------------------
def _decide(ctx: _Ctx, p: dict, verdict: str, reason: str | None, auto: bool) -> None:
    ctx.cx.execute("INSERT OR REPLACE INTO decisions(proposal, by, owner_seq, verdict, reason, at, auto) VALUES "
                   "(?,?,?,?,?,?,?)", (p["id"], ctx.me, ctx.seq, verdict, (reason or "").strip()[:1000] or None, now(),
                                       1 if auto else 0))
    ctx.dec = _decisions(ctx.cx, ctx.chain)


def _accept(ctx: _Ctx, p: dict, auto: bool = False, reason: str | None = None) -> None:
    doc, det, kind = p["doc"], p["detail"], p["kind"]
    L, k = ctx.docs.get(doc), ctx.K.get(doc)
    if kind == "add":
        if L is not None:
            if not ctx.choices.get(doc) and det.get("blocks"):
                ctx.set_blocks(doc, _clean_blocks(det["blocks"]), by=p["by"])
            ctx.put_from_here(doc, ("state", "read", "ai", "blocks"))
            ctx.mark(doc, state_n=ctx.K[doc]["state_n"], gone=None, came_from=None)
        else:  # not here (kept out of the shared folder, or removed here once): one of the project's all the same
            ctx.cx.execute("DELETE FROM sync_removed WHERE kind='document' AND key=?", (doc,))
            ctx.removed_by_me.pop(doc, None)
            ctx.put(doc, ("state", "read", "ai", "blocks"), state="in", sha1=det.get("sha1"), title=p["title"],
                    text_fp=det.get("text_fp"), reader=det.get("reader"), ai_access=_level(det.get("ai_access")),
                    blocks=_clean_blocks(det.get("blocks") or {}))
            ctx.mark(doc, gone=None, came_from=None)
            ctx.report["fetch"].append(doc)
    elif kind == "remove":
        if L is not None:
            ctx.remove_here(doc, f"Accepted {ctx.names.get(p['by'], 'a colleague')}'s proposal to remove it from the "
                                 "project." + (f" {reason.strip()}" if reason and reason.strip() else ""), ctx.me)
        ctx.put(doc, ("state",), state="removed")
        ctx.mark(doc, state_n=ctx.K[doc]["state_n"])
    elif kind == "reread":
        ctx.put(doc, ("read",), text_fp=det.get("to_fp"), reader=det.get("to_reader"))
    elif kind == "blocks":  # the project's choices with the proposal's on top (not all of the owner's copy's)
        if L is not None:
            ctx.set_blocks(doc, _apply_delta(ctx.choices.get(doc) or {}, det.get("delta") or {}), by=p["by"])
        k = ctx.put(doc, ("blocks",), blocks=_apply_delta(k["blocks"], det.get("delta") or {}))
        ctx.mark(doc, blocks_n=k["blocks_n"], blocks_json=json.dumps(k["blocks"], sort_keys=True))
    elif kind == "loosen":
        to = _level(det.get("to"))
        if L is not None:
            ctx.set_level(doc, to, f", as {ctx.names.get(p['by'], 'a colleague')} proposed and the owner accepted.",
                          {"from": "proposal", "proposal": p["id"]})
        k = ctx.put(doc, ("ai",), ai_access=to)
        ctx.mark(doc, ai_n=k["ai_n"], ai_level=to)
    _decide(ctx, p, "accept", reason, auto)
    if auto:
        ctx.report["accepted"].append(p["id"])


def _owner_ctx(ws: Workspace, cx: sqlite3.Connection, pid: str) -> tuple[_Ctx, dict]:
    ctx = _Ctx(ws, cx, people.me())
    p = ctx.props.get(pid)
    if p is None:
        raise KeyError(pid)
    if not ctx.is_owner:
        raise NotAllowed("Only the owner can accept or decline a proposal.")
    st, why = ctx.state(p)
    if st != "waiting":
        raise ValueError(f"This proposal no longer waits for an answer ({why or st.replace('_', ' ')}).")
    return ctx, p


def accept(ws: Workspace, pid: str, reason: str | None = None) -> dict:
    """The owner accepts a proposal: the change is made in the owner's copy (a new reading through `moves_due`) and
    becomes the project's, so it reaches every copy."""
    from . import researchlog

    with ws.connect() as cx:
        ctx, p = _owner_ctx(ws, cx, pid)
        _accept(ctx, p, reason=reason)
        who = ctx.names.get(p["by"], "a colleague") if p["by"] != ctx.me else "your own"
        researchlog.record(cx, "proposal-accepted", f"Accepted {who}{'' if p['by'] == ctx.me else chr(39) + 's'} "
                                                    f"proposal: {what(p)}. It now holds in every copy.",
                           "document", p["doc"], p["title"], why=reason, data={"proposal": pid, "kind": p["kind"]})
        ctx.save()
        fetch = list(ctx.report["fetch"])
    if fetch:
        _fetch(ws, fetch)
    settle(ws, apply=True)
    return view(ws)


def decline(ws: Workspace, pid: str, reason: str | None = None) -> dict:
    """The owner declines a proposal: nothing changes in the project; the proposer's copy keeps its change (a
    document they added stays in their copy only, and leaves the others)."""
    from . import researchlog

    with ws.connect() as cx:
        ctx, p = _owner_ctx(ws, cx, pid)
        _decide(ctx, p, "decline", reason, False)
        who = ctx.names.get(p["by"], "a colleague") if p["by"] != ctx.me else "your own"
        researchlog.record(cx, "proposal-declined", f"Declined {who}{'' if p['by'] == ctx.me else chr(39) + 's'} "
                                                    f"proposal: {what(p)}.",
                           "document", p["doc"], p["title"], why=reason, data={"proposal": pid, "kind": p["kind"]})
    settle(ws, apply=True)
    return view(ws)


def take_back(ws: Workspace, pid: str) -> dict:
    """The proposer takes a waiting proposal back: the owner is no longer asked. Their copy keeps the change."""
    from . import researchlog

    me = people.me()
    with ws.connect() as cx:
        ctx = _Ctx(ws, cx, me)
        p = ctx.props.get(pid)
        if p is None:
            raise KeyError(pid)
        if p["by"] != me:
            raise NotAllowed("Only who made a proposal can take it back.")
        if ctx.state(p)[0] != "waiting":
            raise ValueError("This proposal no longer waits for an answer.")
        cx.execute("UPDATE proposals SET taken_back_at=? WHERE id=?", (now(), pid))
        researchlog.record(cx, "proposal-taken-back", f"Took back the proposal to the owner: {what(p)}. Your copy "
                                                      "stays as it is.",
                           "document", p["doc"], p["title"], data={"proposal": pid, "kind": p["kind"]})
    return view(ws)


def hold_loosening(ws: Workspace, cx: sqlite3.Connection, doc_ids: Iterable[str], level: str | None) -> dict[str, str]:
    """Called when a person changes who may read documents with AI (access.set_documents), before anything is
    written: in a collaborator's copy of a project with an owner, a setting looser than the project's is not made;
    it is proposed to the owner. Returns {doc id: the setting the document gets here instead} (the project's, when
    this copy's was stricter still) for the documents held."""
    from . import access, researchlog

    me = people.me()
    ch = chain(cx)
    if not ch or ch[-1]["owner"] == me:
        return {}
    K = canon(cx, ch)
    dec = _decisions(cx, ch)
    props = _proposals(cx)
    want = level or access._default_from_cx(cx)
    held: dict[str, str] = {}
    new = []
    for doc in doc_ids:
        k = K.get(doc)
        if k is None or k["state"] != "in" or RANK[_level(want)] >= RANK[k["ai_access"]]:
            continue
        held[doc] = k["ai_access"]
        # the same again while it waits proposes nothing more; asked again after the owner declined it (or it was
        # taken back), it is a new proposal
        pid, i = _id("loosen", doc, me, want, k["ai_n"]), 0
        while pid in props and state_of(props[pid], K, dec)[0] in ("declined", "taken_back"):
            i += 1
            pid = _id("loosen", doc, me, want, k["ai_n"], i)
        if pid in props or cx.execute("SELECT 1 FROM proposals WHERE id=?", (pid,)).fetchone():
            continue
        title = (cx.execute("SELECT title FROM documents WHERE doc_id=?", (doc,)).fetchone() or [k["title"]])[0]
        det = {"from": k["ai_access"], "to": want, "ai_n": k["ai_n"]}
        cx.execute("INSERT INTO proposals(id, kind, doc, title, by, at, detail_json, taken_back_at) VALUES "
                   "(?,?,?,?,?,?,?,NULL)", (pid, "loosen", doc, title, me, now(), json.dumps(det)))
        new.append({"id": pid, "kind": "loosen", "doc": doc, "title": title, "detail": det})
    if len(new) == 1:
        p = new[0]
        researchlog.record(cx, "proposal", f"Proposed to the owner: {what(p)}. Until the owner accepts, it is as the "
                                           f"project has it ({researchlog.access_words(_level(p['detail']['from']))}).",
                           "document", p["doc"], p["title"], data={"proposal": p["id"], "kind": "loosen"})
    elif new:  # one entry for one change of several documents
        names = ", ".join(_q(p["title"], 50) for p in new[:3]) + (" and more" if len(new) > 3 else "")
        researchlog.record(cx, "proposal", f"Proposed to the owner: letting more AI read {len(new)} documents ({names}: "
                                           f"{researchlog.access_words(_level(want), True)}). Until the owner "
                                           "accepts, each is as the project has it.",
                           "documents", None, None, data={"proposals": [p["id"] for p in new], "kind": "loosen"})
    return held


# ---------------------------------------------------------------------------------------------
# a new reading the owner accepted, made here
# ---------------------------------------------------------------------------------------------
def moves_due(ws: Workspace) -> list[str]:
    """The documents the project reads with a newer reader than this copy does, and that this copy has not tried to
    move yet (after a try that left it as it was, it waits for its person: `move_now(force=True)`)."""
    cx = ws._conn()
    if not _has_tables(cx):
        return []
    K = canon(cx)
    if not K:
        return []
    tried = {r[0]: r[1] for r in cx.execute("SELECT doc, read_tried FROM canon_seen")}
    clash = {r[0] for r in cx.execute("SELECT key FROM sync_copies WHERE kind='document'")}
    out = []
    for doc, reader in cx.execute("SELECT doc_id, COALESCE(reader, 1) FROM documents ORDER BY title").fetchall():
        k = K.get(doc)
        if k and k["state"] == "in" and doc not in clash and reader < (k["reader"] or 1) and \
                (tried.get(doc) or 0) != k["read_n"]:
            out.append(doc)
    return out


def behind(ws: Workspace, doc: str) -> bool:
    """Whether this copy reads a document of the project with an older reader than the project now does (a new reading
    the owner accepted, still to be made here), tried or not."""
    cx = ws._conn()
    if not _has_tables(cx) or cx.execute("SELECT 1 FROM sync_copies WHERE kind='document' AND key=?", (doc,)).fetchone():
        return False
    k = canon(cx).get(doc)
    row = cx.execute("SELECT COALESCE(reader, 1) FROM documents WHERE doc_id=?", (doc,)).fetchone()
    return bool(k and row and k["state"] == "in" and row[0] < (k["reader"] or 1))


def move_now(ws: Workspace, doc: str, force: bool = False) -> dict:
    """Read a document with the new reader here, because the project now reads it so (`reread.move`: every result is
    placed on the new text by its rules, all in one transaction). Without `force` it moves only when every result
    finds its place; otherwise the document stays as it is and waits for its person, who may move it all the same
    (`force`: results without a place are kept as records, as when a person moves it from its own page). Returns
    {"doc", "title", "moved", "reason", "not_placed"}."""
    from . import reread

    title = ws.scalar("SELECT title FROM documents WHERE doc_id=?", (doc,))
    out = {"doc": doc, "title": title, "moved": False, "reason": None, "not_placed": 0}
    k = canon(ws._conn()).get(doc)
    if title is None or k is None:
        out["reason"] = "This document is not here."
        return out
    tried = True
    try:
        c = reread.check(ws, doc)
        if not c.get("ok"):
            tried = False  # it cannot be read again now (its file is not here yet, work on it runs): tried again later
            raise ValueError(c.get("reason") or "This document cannot be read again now.")
        r = reread.move(ws, doc, people.me(), keep_all=not force)
        out["moved"] = True
        out["not_placed"] = len(r.get("not_placed") or [])
    except reread.WouldLose as e:
        out["not_placed"] = len(e.report.get("not_placed") or [])
        out["reason"] = (f"{out['not_placed']} of your results on it would not find their place in the new reading. "
                         "It stays as it is in your copy until you move it yourself (they are then kept as records).")
    except ValueError as e:
        out["reason"] = str(e)
    with ws.connect() as cx:
        s = {"read_tried": k["read_n"] if (tried and not out["moved"]) else None, "read_note": out["reason"]}
        cx.execute("INSERT OR IGNORE INTO canon_seen(doc) VALUES (?)", (doc,))
        cx.execute("UPDATE canon_seen SET read_tried=?, read_note=? WHERE doc=?", (s["read_tried"], s["read_note"], doc))
    return out


# ---------------------------------------------------------------------------------------------
# what the Team tab and the Documents page show
# ---------------------------------------------------------------------------------------------
def _person(names: dict[str, str], me: str, pid: str | None) -> dict | None:
    if not pid:
        return None
    return {"id": pid, "name": names.get(pid, "a colleague"), "me": pid == me}


def document_marks(ws: Workspace) -> dict[str, dict]:
    """What the Documents page shows beside a document: `view(ws)["documents"]`, without a look at the shared folder
    (a folder on a network drive that is not there now must not hold the page up)."""
    return view(ws, light=True)["documents"]


def view(ws: Workspace, light: bool = False) -> dict:
    """Everything the page shows of L2, without changing anything (`light`: not whether the owner has left, which
    looks at the shared folder):
    {"owner": {"id", "name", "me"} | None, "me", "is_owner", "since", "how" (made | claim | handover | takeover),
     "can_claim", "can_take_over": words why | None, "accept_adds" (the owner's setting, in the owner's copy),
     "people": [{"id", "name", "me", "owner"}],
     "proposals": [{"id", "kind", "severity", "doc", "title", "what" (in words), "by": {..}, "at", "state", "note",
                    "reason", "decided_by", "decided_at", "auto", "mine", "can_decide", "can_take_back", "here" (the
                    document is in this copy), "conflicts": [ids of other waiting proposals for the document],
                    "detail": {...}}] newest first,
     "waiting": how many wait (for this person's answer in the owner's copy; of this person's own otherwise),
     "to_apply": [{"doc", "title", "kind": "reread", "note", "can_force"}],
     "documents": {doc id: {"state": "proposed" | "declined" | "waiting", "text"}}}"""
    me = people.me()
    cx = ws._conn()
    names = people.names(ws)
    out: dict[str, Any] = {"owner": None, "me": me, "is_owner": False, "since": None, "how": None, "can_claim": False,
                           "can_take_over": None, "accept_adds": accept_adds(ws), "people": [], "proposals": [],
                           "waiting": 0, "to_apply": [], "documents": {}}
    if not _has_tables(cx):
        return out
    ch = chain(cx)
    known = [r[0] for r in cx.execute("SELECT person_id FROM people ORDER BY name") if r[0] != people.UNKNOWN]
    own = ch[-1]["owner"] if ch else None
    for pid in dict.fromkeys([me] + known + ([own] if own else [])):
        out["people"].append({**_person(names, me, pid), "owner": pid == own})
    if not ch:
        from . import sharing

        if sharing.exchanged(cx, me):
            out["can_claim"] = True
        else:  # never exchanged: its maker's, written down when it first leaves this computer
            out.update(owner=_person(names, me, me), is_owner=True, how="made")
            out["people"][0]["owner"] = True
        return out
    out.update(owner=_person(names, me, own), is_owner=own == me, since=ch[-1]["at"], how=ch[-1]["kind"])
    if own != me and not light:
        out["can_take_over"] = owner_left(ws, cx, ch)
    K = canon(cx, ch)
    dec = _decisions(cx, ch)
    props = _proposals(cx)
    here = {r[0]: r[1] for r in cx.execute("SELECT doc_id, title FROM documents")}
    waiting_by_doc: dict[str, list[str]] = {}
    states = {}
    for p in props.values():
        states[p["id"]] = state_of(p, K, dec)
        if states[p["id"]][0] == "waiting":
            waiting_by_doc.setdefault(p["doc"], []).append(p["id"])
    for p in sorted(props.values(), key=lambda p: p["at"] or "", reverse=True):
        st, note = states[p["id"]]
        d = dec.get(p["id"])
        det = {c: v for c, v in p["detail"].items() if c not in ("blocks", "delta")}
        item = {"id": p["id"], "kind": p["kind"], "severity": SEVERITY[p["kind"]], "doc": p["doc"],
                "title": here.get(p["doc"]) or p["title"] or "a document", "what": what(p),
                "by": _person(names, me, p["by"]), "at": p["at"], "state": st, "note": note,
                "reason": d["reason"] if d else None, "decided_by": _person(names, me, d["by"]) if d else None,
                "decided_at": d["at"] if d else None, "auto": bool(d and d["auto"]), "mine": p["by"] == me,
                "can_decide": own == me and st == "waiting", "can_take_back": p["by"] == me and st == "waiting",
                "here": p["doc"] in here,
                "conflicts": [i for i in waiting_by_doc.get(p["doc"], []) if i != p["id"]] if st == "waiting" else [],
                "detail": det}
        out["proposals"].append(item)
        if st == "waiting" and (own == me or p["by"] == me):
            out["waiting"] += 1
        if p["by"] == me and p["kind"] == "add" and p["doc"] in here and p["doc"] not in K:
            if st == "waiting":
                out["documents"][p["doc"]] = {"state": "proposed", "text": "Waiting for the owner: so far it is in "
                                                                           "your copy and comes to your colleagues "
                                                                           "for now."}
            elif st in ("declined", "taken_back", "moot"):
                out["documents"][p["doc"]] = {"state": "declined", "text": "In your copy only"
                                              + (": the owner declined it." if st == "declined" else ".")}
        elif st == "waiting" and p["doc"] in here:
            if p["kind"] == "add":
                out["documents"].setdefault(p["doc"], {
                    "state": "proposed", "text": f"Added by {names.get(p['by'], 'a colleague')}: waiting for the owner."})
            elif p["by"] == me:
                out["documents"].setdefault(p["doc"], {"state": "waiting", "text": f"Waiting for the owner: {what(p)}."})
    for r in _rows(cx, "SELECT doc, read_tried, read_note FROM canon_seen WHERE read_note IS NOT NULL"):
        k = K.get(r["doc"])
        if k and k["state"] == "in" and r["doc"] in here:
            reader = cx.execute("SELECT COALESCE(reader, 1) FROM documents WHERE doc_id=?", (r["doc"],)).fetchone()[0]
            if reader < (k["reader"] or 1):
                out["to_apply"].append({"doc": r["doc"], "title": here[r["doc"]], "kind": "reread",
                                        "note": r["read_note"], "can_force": r["read_tried"] == k["read_n"]})
    return out
