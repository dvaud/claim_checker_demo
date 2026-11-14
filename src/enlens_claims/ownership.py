"""One Owner, Co-owners and Members (0.18, roadmap L2; roles: DESIGN-roles §4).

A project that people work on together has one **Owner**, any number of **Co-owners** and everyone else is a
**Member**. Everyone keeps their own working version; what the project's documents *are* (which documents, how each is
read, who may read each with AI, which passages are left out) is the project's. The Owner and the Co-owners write it:
their changes to the documents are the project's at once, and they answer proposals. Only the Owner sets roles and
hands the project over. A Member may still change the documents in their own copy: each such change is a **proposal**,
accepted or declined according to how much it matters:

    add       a document was added                                  low     accepted at once (the Owner's setting,
                                                                            on by default) or with one click
    reread    a document was read again with the new reader         medium
    blocks    Leave out / Restore, where the text starts and ends   medium
    remove    a document was removed                                high    always someone's decision
    loosen    more AI may read a document than before               high    always someone's decision

What the proposer's copy does at once: it keeps the change (their working version), except a looser AI setting, which
is held until it is accepted. A *stricter* AI setting is never a proposal: it holds in every copy at once (sync/merge.py
`_stricter`).

**How the copies agree, without a clock.** Copies that hold the same rows and gave the same answers compute the same
owner, roles and documents, whatever order the rows came in and whatever any clock said. Five tables travel, each merged
by its own rule (sync/owner_merge.py: one row per key and writer, the higher number stays):

- `ownership`: a chain of records (who made the project, hand-overs, take-overs). Each copy *pins* the record it
  follows for each place (`owner_pins`, this copy's own): its own records, a hand-over by the owner it follows, and the
  first owner it hears of are pinned without a click; anything else (another founder, a take-over) is a question to
  this copy's person (`owner_questions`). Who the owner is never depends on a clock (`chain`).
- `roles`: the Owner's word on who is a Co-owner (`grant`: the id of one grant). A row counts when its writer was the
  owner of the place it names.
- `proposals`: written by the proposer's copy, never changed, except that the proposer may take one back.
- `decisions`: an answer to a proposal, by the Owner or a Co-owner, with the other answers its writer had seen
  (`knew_json`). Two different answers given without each other's count for nothing: the proposal waits again
  (`_decisions`).
- `canon`: the documents as the project has them, one row per document and writer. Each part (state, reading, AI,
  blocks) carries the event that made it, `(number, maker)`, and the events its writer had followed; the parts are
  merged by what each writer knew, never by the highest number (`canon`). Two events neither knew of are "at the same
  time": the document stays, the newer reader counts, the stricter AI setting counts, the larger person id's blocks
  count, and the case is listed (`clashes`).

`settle(ws)` is the one place where a copy looks at itself: it follows what the project decided (`canon_seen`, this
copy's own record of how far it has followed, event by event), then writes what its person changed: a row of `canon` in
a writer's copy, a proposal otherwise. A copy that only follows writes nothing but `canon_seen`, so copies that exchange
until nothing new comes write no row in the last exchange.

**What a file cannot do.** Files are not signed yet (the `sig` columns are empty), so a file can still say it was
written by someone else. What it can no longer do, whoever it says wrote it:
1. loosen an AI setting in this copy: a looser word of the project is offered (`offers`, `answer_loosening`), set only
   by this person's own click; a stricter one holds at once;
2. change the owner other than by a hand-over of the owner this copy follows: anything else is a question;
3. act under this copy's own id: such a row is refused, recorded (`refused`) and answered with this copy's own row;
4. destroy a document for good: a removal caused by a colleague's word is archived first and can be restored for 30
   days (removed.py).
Known limits (DESIGN-roles §10): a forged hand-over in the owner's name is followed by third copies until the owner
takes the project back (`take_project_back`); a late role row of a former owner for a person nobody knew yet counts.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sqlite3
from typing import Any, Iterable

from . import people
from .store import Workspace, now

KINDS = ("add", "reread", "blocks", "remove", "loosen")
SEVERITY = {"add": "low", "reread": "medium", "blocks": "medium", "remove": "high", "loosen": "high"}
ACCEPT_ADDS = "owner_accept_adds"  # meta (this copy's own): the owner accepts added documents at once (default: yes)
NOTICES = "owner_notices"          # meta (this copy's own): hand-overs and role changes made elsewhere, to show
ROLES_SEEN = "roles_seen"          # meta (this copy's own): the roles as this copy last saw them (for the notices)
FORMATS = "sync_formats"           # meta (this copy's own): {person id: the sync format of their last file}
LOOSEN_USED = "loosen_used"        # meta (this copy's own, never sent to a colleague): the accepts of this person's
#                                    loosen proposals whose event this copy has followed (review H1, follow-up)
CLAIM_NOTED = "owner_claim_noted"  # meta (this copy's own): the claims whose notice this copy gave (0.18.1)
LATER = "owner_later"              # meta (this copy's own): {person id: [ids of questions about the owner put off
#                                    with *Not now*]}, so it holds in every browser (0.18.1)
TAKE_OVER_DAYS = 14
RANK = {"cloud": 0, "local": 1, "none": 2}
PARTS = ("state", "read", "ai", "blocks")
MAX_N = 2 ** 53                    # a number above it is not taken (a forged one would leave no number above it)
HIST_CAP = 50
STEP = 2 ** 32                     # a file's number more than this above every number held is not taken (review, H2)
TOP = 1 << 62                      # the tier of a Co-owner's row: always counts while its grant does
_SEEN = ("state_n", "read_n", "ai_n", "ai_level", "blocks_n", "blocks_json", "gone", "came_from", "read_tried",
         "read_note", "read_from", "state_by", "read_by", "ai_by", "blocks_by", "blocks_base", "ai_offer")
_ROW_COLS = ("doc", "by", "owner_seq", "n", "grant", "state", "state_n", "state_by", "sha1", "title", "text_fp", "reader",
             "read_n", "read_by", "ai_access", "ai_n", "ai_by", "ai_hist_json", "blocks_json", "blocks_n", "blocks_by",
             "hist_json", "at")


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
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:12]


def _q(title: str | None, n: int = 80) -> str:
    from .researchlog import quoted

    return quoted(title or "a document", n)


def _level(v: Any) -> str:
    return v if v in RANK else "none"


def _num(v: Any) -> int | None:
    """A number of an event or a row: an integer in 0 … 2**53, else None (not taken)."""
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= MAX_N else None


def _ev(n: Any, by: Any) -> tuple[int, str] | None:
    n = _num(n)
    return (n, by) if n is not None and isinstance(by, str) and by else None


def _has_tables(cx: sqlite3.Connection) -> bool:
    return bool(cx.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ownership'").fetchone())


def _has(cx: sqlite3.Connection, table: str) -> bool:
    return bool(cx.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _names_cx(cx: sqlite3.Connection) -> dict[str, str]:
    return {r[0]: r[1] for r in cx.execute("SELECT person_id, name FROM people") if r[0] and r[1]}


def _meta(cx: sqlite3.Connection, key: str, default: Any) -> Any:
    row = cx.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return _json(row[0], default) if row else default


def _set_meta(cx: sqlite3.Connection, key: str, value: Any) -> None:
    cx.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False)))


def _notice(cx: sqlite3.Connection, kind: str, text: str, key: str) -> None:
    """An info notice for the Team tab (a hand-over by the followed owner, a role changed elsewhere): kept until
    dismissed (`dismiss_refused(ws, "notice", id)`), at most 20."""
    have = _meta(cx, NOTICES, [])
    nid = "n" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    if any(isinstance(x, dict) and x.get("id") == nid for x in have):
        return
    have = [x for x in have if isinstance(x, dict)] + [{"id": nid, "kind": kind, "text": text, "at": now()}]
    _set_meta(cx, NOTICES, have[-20:])


# ---------------------------------------------------------------------------------------------
# who the owner is: records and this copy's pins (§4.1)
# ---------------------------------------------------------------------------------------------
def _valid_record(r: dict) -> bool:
    return isinstance(r.get("seq"), int) and r["seq"] > 0 and bool(people.ID_RE.fullmatch(r.get("owner") or "")) and \
        bool(people.ID_RE.fullmatch(r.get("by") or "")) and r["owner"] != people.UNKNOWN and \
        (r.get("after") is None or bool(people.ID_RE.fullmatch(r.get("after") or "")))


def _records(cx: sqlite3.Connection) -> dict[int, list[dict]]:
    by_seq: dict[int, list[dict]] = {}
    for r in _rows(cx, "SELECT seq, owner, by, at, kind, after, why FROM ownership ORDER BY seq, by"):
        if _valid_record(r):
            by_seq.setdefault(r["seq"], []).append(r)
    return by_seq


def _candidates(by_seq: dict[int, list[dict]], seq: int, prev: str | None) -> list[dict]:
    """The records for place `seq` that follow the owner of the place before (`after`; none for the first place)."""
    return [r for r in by_seq.get(seq, []) if (r["after"] or None) == prev]


def _pins(cx: sqlite3.Connection) -> tuple[dict[int, tuple[str, str]], set[tuple[int, str, str]]]:
    """({place: (by, owner) followed}, {(place, by, owner) refused})."""
    followed: dict[int, tuple[str, str]] = {}
    refused: set[tuple[int, str, str]] = set()
    if not _has(cx, "owner_pins"):
        return followed, refused
    for seq, by, own, state in cx.execute("SELECT seq, by, owner, state FROM owner_pins ORDER BY seq, by, owner"):
        if state == "followed":
            followed.setdefault(seq, (by, own))
        elif state == "refused":
            refused.add((seq, by, own))
    return followed, refused


def _lost(cx: sqlite3.Connection) -> dict[int, set[tuple[str, str]]]:
    """{place: {(by, owner) of the record it followed}} of the places whose followed record is gone from this copy
    (changed after review, C1): no other record is pinned for them without this person's word; the same record, should
    it come back, is followed again."""
    out: dict[int, set[tuple[str, str]]] = {}
    if _has(cx, "owner_pins"):
        for seq, by, own in cx.execute("SELECT seq, by, owner FROM owner_pins WHERE state='lost'"):
            out.setdefault(seq, set()).add((by, own))
    return out


def _walk(by_seq: dict[int, list[dict]], followed: dict[int, tuple[str, str]]) -> list[dict]:
    out: list[dict] = []
    prev: str | None = None
    seq = 1
    while seq in followed:
        by, own = followed[seq]
        r = next((r for r in _candidates(by_seq, seq, prev) if r["by"] == by and r["owner"] == own), None)
        if r is None:
            break
        out.append(r)
        prev = r["owner"]
        seq += 1
    return out


def chain(cx: sqlite3.Connection) -> list[dict]:
    """The records this copy follows, in order: [{"seq", "owner", "by", "at", "kind", "after", "why"}]; the last one
    names the owner. A function of the records and this copy's pins: no clock is read. Empty: the project has no
    owner (or this copy's person has not said yet which of two first owners they follow)."""
    if not _has_tables(cx):
        return []
    return _walk(_records(cx), _pins(cx)[0])


def _chain_0_17(cx: sqlite3.Connection) -> list[dict]:
    """Who the owner was by the rule of 0.17 (of two records for one place: a hand-over over a take-over, then the
    earlier, then the smaller person id). Used once, by the upgrade (store.py), to pin what 0.17 followed."""
    by_seq = _records(cx)
    out: list[dict] = []
    prev: str | None = None
    seq = 1
    while seq in by_seq:
        ok = _candidates(by_seq, seq, prev)
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


def _pin(cx: sqlite3.Connection, r: dict, state: str) -> None:
    if state == "followed":
        cx.execute("DELETE FROM owner_pins WHERE seq=? AND state IN ('followed', 'lost')", (r["seq"],))
    cx.execute("DELETE FROM owner_pins WHERE seq=? AND by=? AND owner=?", (r["seq"], r["by"], r["owner"]))
    cx.execute("INSERT INTO owner_pins(seq, by, owner, state, at) VALUES (?,?,?,?,?)",
               (r["seq"], r["by"], r["owner"], state, now()))


def pin_owner(cx: sqlite3.Connection, me: str) -> list[dict]:
    """Pin the owner records this copy follows without a click (§4.1): its own (a file cannot bring one: the merge
    refuses rows in this copy's name), the one hand-over by the owner it follows, and the first owner it hears of when
    there is one. Two records of one writer for one place are a question, not a choice (changed after review, C1).
    Pins whose record is gone go, and that place is then the person's to answer (`_lost`). Returns the notices
    ({"kind": "handover", "text"}); they are kept for the Team tab too."""
    if not _has_tables(cx) or not _has(cx, "owner_pins"):
        return []
    by_seq = _records(cx)
    if not by_seq:  # (a project with no record of who owns it has nothing to follow, and nothing lost)
        cx.execute("DELETE FROM owner_pins")
        return []
    keys = {(r["seq"], r["by"], r["owner"]) for rs in by_seq.values() for r in rs}
    for seq, by, own, state in cx.execute("SELECT seq, by, owner, state FROM owner_pins WHERE state != 'lost'"
                                          ).fetchall():
        if (seq, by, own) not in keys:
            cx.execute("DELETE FROM owner_pins WHERE seq=? AND by=? AND owner=?", (seq, by, own))
            if state == "followed":
                cx.execute("INSERT OR IGNORE INTO owner_pins(seq, by, owner, state, at) VALUES (?, ?, ?, 'lost', ?)",
                           (seq, by, own, now()))
    followed, refused = _pins(cx)
    lost = _lost(cx)
    ch = _walk(by_seq, followed)
    seq = len(ch) + 1
    prev = ch[-1]["owner"] if ch else None
    cx.execute("DELETE FROM owner_pins WHERE seq>=? AND state='followed'", (seq,))  # (beyond the chain: not reachable)
    names = None
    out = []
    while True:
        c = [r for r in _candidates(by_seq, seq, prev) if (seq, r["by"], r["owner"]) not in refused]
        mine = [r for r in c if r["by"] == me]
        handed = [r for r in c if seq > 1 and r["by"] == prev]
        back = [r for r in c if (r["by"], r["owner"]) in lost.get(seq, ())]
        if seq in lost:
            if len(back) != 1:
                break  # (its record is gone: this person says which to follow)
            pick = back[0]
        elif len(mine) == 1:
            pick = mine[0]
        elif not mine and len(handed) == 1:
            pick = handed[0]
        elif seq == 1 and len(c) == 1:
            pick = c[0]
        else:
            break
        _pin(cx, pick, "followed")
        if pick["by"] != me and seq > 1:
            names = names if names is not None else _names_cx(cx)
            to = "you" if pick["owner"] == me else names.get(pick["owner"], "a colleague")
            text = (f"{names.get(pick['by'], 'A colleague')} handed the project over to {to}: "
                    + ("you are the owner now." if pick["owner"] == me else f"{to} is the owner now."))
            out.append({"kind": "handover", "text": text})
            _notice(cx, "handover", text, f"handover|{pick['seq']}|{pick['by']}|{pick['owner']}")
        prev = pick["owner"]
        seq += 1
    return out


def owner_questions(cx: sqlite3.Connection) -> list[dict]:
    """The owner records this copy's person must answer (§4.1): [{"id", "seq", "kind" ("founder" | "takeover" |
    "other"), "owner", "by", "why", "now" (whom this copy follows for that place, or None), "record_kind", "at"}]."""
    if not _has_tables(cx):
        return []
    me = people.me()
    by_seq = _records(cx)
    followed, refused = _pins(cx)
    ch = _walk(by_seq, followed)
    out: list[dict] = []

    def ask(r: dict, kind: str, now_: str | None) -> None:
        out.append({"id": "o" + hashlib.sha1(f"{r['seq']}|{r['by']}|{r['owner']}".encode()).hexdigest()[:12],
                    "seq": r["seq"], "kind": kind, "owner": r["owner"], "by": r["by"], "why": r["why"], "now": now_,
                    "record_kind": r["kind"], "at": r["at"]})

    prev: str | None = None
    for f in ch:
        for r in _candidates(by_seq, f["seq"], prev):
            if (r["by"], r["owner"]) != (f["by"], f["owner"]) and (f["seq"], r["by"], r["owner"]) not in refused:
                ask(r, "founder" if f["seq"] == 1 else "other", f["owner"])
        prev = f["owner"]
    nxt = len(ch) + 1
    c = [r for r in _candidates(by_seq, nxt, prev) if (nxt, r["by"], r["owner"]) not in refused]
    lost = nxt in _lost(cx) and not [r for r in c if (r["by"], r["owner"]) in _lost(cx)[nxt]]
    if nxt == 1:
        if len(c) > 1 or lost:
            for r in c:
                ask(r, "founder", None)
    else:
        mine = [r for r in c if r["by"] == me]
        handed = [r for r in c if r["by"] == prev]
        for r in c:
            if r["by"] == me and len(mine) == 1 and not lost:
                continue  # (pinned without a click)
            if r["by"] == prev:
                if len(handed) > 1 or lost or mine:  # (one hand-over by the followed owner is pinned without a click)
                    ask(r, "other", prev)
                continue
            ask(r, "takeover", prev)
    return out


def owner(cx: sqlite3.Connection) -> str | None:
    ch = chain(cx)
    return ch[-1]["owner"] if ch else None


def _record(cx: sqlite3.Connection, seq: int, who: str, by: str, kind: str, after: str | None, why: str | None,
            text: str) -> None:
    from . import researchlog

    r = {"seq": seq, "owner": who, "by": by, "at": now(), "kind": kind, "after": after,
         "why": (why or "").strip()[:500] or None}
    cx.execute("INSERT OR REPLACE INTO ownership(seq, owner, by, at, kind, after, why) VALUES (?,?,?,?,?,?,?)",
               (r["seq"], r["owner"], r["by"], r["at"], r["kind"], r["after"], r["why"]))
    if _has(cx, "owner_pins"):
        _pin(cx, r, "followed")  # this copy wrote it: it follows it
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
        if _records(cx).get(1):
            raise NotAllowed("This project has an owner already: say which first owner you follow (Team tab).")
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
    made them the owner. (This computer's clock: only to offer *Take over*.)"""
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
            # gone only once this copy has seen it there: an owner who has not chosen the folder yet, or whose
            # subfolder the cloud service has not delivered, has not left
            if team.is_dir() and (team / people.me()).is_dir() and not (team / who).is_dir() and \
                    folder.seen_there(cx, who):
                return "The owner's folder is no longer in the shared folder."
    except (ImportError, OSError):
        pass
    days = _days_since(_heard(cx, who, ch))
    if days is not None and days >= TAKE_OVER_DAYS:
        return f"Nothing was heard of the owner for {int(days)} days."
    return None


def _co_heard_lately(cx: sqlite3.Connection, ch: list[dict], me: str) -> bool:
    """Whether a Co-owner (other than this person) was heard of in the last `TAKE_OVER_DAYS` days: a Member may take
    the project over only when not (§4.1)."""
    for pid, r in roles(cx, ch).items():
        if pid != me and r["role"] == "co":
            days = _days_since(_heard(cx, pid, ch))
            if days is not None and days < TAKE_OVER_DAYS:
                return True
    return False


def take_over(ws: Workspace, why: str | None = None) -> dict:
    """A Co-owner becomes the owner when the owner has left (`owner_left`); a Member when also no Co-owner was heard of
    for `TAKE_OVER_DAYS`. The other copies are asked whether they follow (a take-over is never followed unasked)."""
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
        if role_of(cx, me) != "co" and _co_heard_lately(cx, ch, me):
            raise NotAllowed("A Co-owner of this project was heard of lately: a Co-owner can take it over, or the "
                             "owner can hand it over to you.")
        # 0.18.1: one record per person and place travels (a copy never replaces a record it holds), so a second
        # take-over at the same place, after another owner, would never reach the colleagues who hold the first: the
        # copies would disagree about the owner without a word (found by the randomised roles test)
        mine = next((r for r in _records(cx).get(ch[-1]["seq"] + 1, []) if r["by"] == me and r["owner"] == me), None)
        if mine is not None and (mine["after"] or None) != ch[-1]["owner"]:
            earlier = people.names(ws).get(mine["after"] or "", "an earlier owner")
            raise NotAllowed(f"You took this project over once before at this point of its history, from {earlier}. "
                             f"Your colleagues keep that take-over, so a second one would not reach them. Ask "
                             f"{people.names(ws).get(ch[-1]['owner'], 'the owner')} to hand the project over to you, "
                             f"or follow your earlier take-over (Team tab).")
        _record(cx, ch[-1]["seq"] + 1, me, me, "takeover", ch[-1]["owner"], why or left,
                "Took this project over from its owner. " + left)
    settle(ws, apply=False)
    return view(ws)


def _find_record(cx: sqlite3.Connection, seq: int, by: str) -> dict | None:
    return next((r for r in _records(cx).get(seq, []) if r["by"] == by), None)


def follow_owner(ws: Workspace, seq: int, by: str) -> dict:
    """This copy's person follows the record (seq, by) as the owner of its place: the other records for that place are
    not asked about again, later pins go, what can be pinned without a click is pinned again, and the copy follows the
    project as that owner has it. Returns the view."""
    from . import researchlog

    me = people.me()
    with ws.connect() as cx:
        by_seq = _records(cx)
        ch = _walk(by_seq, _pins(cx)[0])
        if not isinstance(seq, int) or seq < 1 or seq > len(ch) + 1:
            raise ValueError("Follow the owner of an earlier place first.")
        prev = ch[seq - 2]["owner"] if seq > 1 else None
        r = next((x for x in _candidates(by_seq, seq, prev) if x["by"] == by), None)
        if r is None:
            raise KeyError(f"{seq}/{by}")
        cx.execute("DELETE FROM owner_pins WHERE seq>=? AND state='followed'", (seq,))
        _pin(cx, r, "followed")
        for x in _candidates(by_seq, seq, prev):  # the question is answered: the others of that place are not asked again
            if x is not r:
                _pin(cx, x, "refused")
        pin_owner(cx, me)
        name = "you" if r["owner"] == me else _names_cx(cx).get(r["owner"], "a colleague")
        researchlog.record(cx, "owner", f"Followed {name} as the project's owner.",
                           data={"owner": r["owner"], "seq": seq, "by": by, "followed": True})
    settle(ws, apply=True)
    return view(ws)


def keep_owner(ws: Workspace, seq: int, by: str) -> dict:
    """This copy's person does not follow the record (seq, by): it is not asked again. Returns the view."""
    with ws.connect() as cx:
        r = _find_record(cx, seq, by)
        if r is None:
            raise KeyError(f"{seq}/{by}")
        if _pins(cx)[0].get(seq) == (r["by"], r["owner"]):
            raise ValueError("You follow this record: follow another one instead.")
        _pin(cx, r, "refused")
    return view(ws)


def put_off(ws: Workspace, qid: str) -> dict:
    """*Not now* on a question about the owner (a take-over): it stays in the Team tab until answered, but no longer
    counts on the tab. Kept for this person in the project (0.18.1; before, only in the browser that said it).
    Returns the view."""
    me = people.me()
    with ws.connect() as cx:
        if not any(q["id"] == qid for q in owner_questions(cx)):
            raise KeyError(qid)
        have = _meta(cx, LATER, {})
        have = have if isinstance(have, dict) else {}
        mine = [x for x in have.get(me) or [] if isinstance(x, str)]
        if qid not in mine:
            have[me] = (mine + [qid])[-200:]
            _set_meta(cx, LATER, have)
    return view(ws)


def take_project_back(ws: Workspace) -> dict:
    """A file said this copy's person handed the project over, and they did not (§4.10; the design's `take_back(ws)`,
    whose name the existing `take_back(ws, pid)` of a proposal holds). The refused record is taken in, so this copy
    names the same chain as the others, and a take-over by this person for the next place follows it ("I did not hand
    the project over"); every other copy is asked, as for any take-over."""
    from . import researchlog

    me = people.me()
    with ws.connect() as cx:
        ch = chain(cx)
        if not ch or ch[-1]["owner"] != me:
            raise NotAllowed("Only the owner can take the project back.")
        seq = ch[-1]["seq"] + 1
        cand = []
        for key, what in cx.execute("SELECT key, what_json FROM sync_refused WHERE kind='ownership' AND "
                                    "state='new'").fetchall():
            r = _json(what, {})
            if _valid_record(r) and r.get("seq") == seq and r.get("by") == me and r.get("after") == me and \
                    r.get("owner") != me:
                cand.append((key, r))
        if not cand:
            raise NotAllowed("There is no hand-over in your name to take back.")
        key, r = sorted(cand, key=lambda x: (x[1]["owner"], x[1].get("kind") or ""))[0]
        cx.execute("INSERT OR REPLACE INTO ownership(seq, owner, by, at, kind, after, why) VALUES (?,?,?,?,?,?,?)",
                   (r["seq"], r["owner"], r["by"], r.get("at"), r.get("kind"), r.get("after"), r.get("why")))
        _pin(cx, r, "followed")
        cx.execute("UPDATE sync_refused SET state='answered' WHERE kind='ownership' AND key=?", (key,))
        name = _names_cx(cx).get(r["owner"], "a colleague")
        _record(cx, seq + 1, me, me, "takeover", r["owner"], "I did not hand the project over.",
                f"Took the project back: a file said you handed it over to {name}, and you did not.")
        researchlog.record(cx, "owner", f"Took the project back from {name}.", data={"refused": key})
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


# ---------------------------------------------------------------------------------------------
# roles (§4.2, §4.3)
# ---------------------------------------------------------------------------------------------
def roles(cx: sqlite3.Connection, ch: list[dict] | None = None) -> dict[str, dict]:
    """{person: {"role": "owner" | "co" | "member", "grant", "same_as", "by", "n", "owner_seq"}} by the rows that
    count: a row counts when its writer was the owner of the place it names; per person the row of the latest place,
    then the highest number. The owner is "owner" whatever a row says (and keeps the grant a row gave them, so what
    they wrote as a Co-owner goes on counting); a person with no row is a Member (and not listed)."""
    ch = chain(cx) if ch is None else ch
    if not ch:
        return {}
    owners = {r["seq"]: r["owner"] for r in ch}
    best: dict[str, dict] = {}
    if _has(cx, "roles"):
        for r in _rows(cx, "SELECT person, by, owner_seq, n, role, grant, same_as, at FROM roles"):
            if owners.get(r["owner_seq"]) != r["by"] or r["role"] not in ("co", "member") or _num(r["n"]) is None or \
                    not people.ID_RE.fullmatch(r["person"] or ""):
                continue
            cur = best.get(r["person"])
            if cur is None or (r["owner_seq"], r["n"]) > (cur["owner_seq"], cur["n"]) or \
                    ((r["owner_seq"], r["n"]) == (cur["owner_seq"], cur["n"]) and _digest(r) < _digest(cur)):
                best[r["person"]] = r
    out = {p: {"role": r["role"], "grant": r["grant"] if r["role"] == "co" else None,
               "same_as": r["same_as"] if people.ID_RE.fullmatch(r["same_as"] or "") else None,
               "by": r["by"], "n": r["n"], "owner_seq": r["owner_seq"]} for p, r in best.items()}
    own = ch[-1]["owner"]
    out[own] = {**(out.get(own) or {"grant": None, "same_as": None, "by": None, "n": None, "owner_seq": None}),
                "role": "owner"}
    return out


def role_of(cx: sqlite3.Connection, person: str | None = None) -> str:
    """The role of `person` (default: this copy's person): "owner", "co" or "member". In a project with no owner,
    "owner" for this copy's person when the project was never exchanged (its maker's), else "member"."""
    from . import sharing

    me = people.me()
    person = person or me
    ch = chain(cx)
    if not ch:
        return "owner" if person == me and _has_tables(cx) and not sharing.exchanged(cx, me) else "member"
    return (roles(cx, ch).get(person) or {}).get("role") or "member"


def may_write(cx: sqlite3.Connection, me: str | None = None) -> bool:
    """Whether `me`'s changes to the documents are the project's at once: the Owner or a Co-owner (in a project with
    no owner everyone's are, as before 0.18)."""
    if not _has_tables(cx) or not chain(cx):
        return True
    return role_of(cx, me) in ("owner", "co")


def _counts(r: dict, owners: dict[int, str], R: dict[str, dict]) -> int | None:
    """The tier a row of `canon` or `decisions` counts in (§4.3), None when it does not: an owner's row (no grant) in
    the place it names, when its writer owned that place; a Co-owner's row (its grant) on top, while that grant is the
    writer's."""
    g = r.get("grant")
    if g is None:
        seq = r.get("owner_seq")
        return seq if isinstance(seq, int) and owners.get(seq) == r.get("by") else None
    x = R.get(r.get("by") or "")
    return TOP if x and x["role"] in ("co", "owner") and x.get("grant") == g else None


def _new_grant(person: str, by: str, seq: int, n: int) -> str:
    return "g" + hashlib.sha1(f"{person}|{by}|{seq}|{n}".encode()).hexdigest()[:12]


def _write_role(cx: sqlite3.Connection, person: str, by: str, seq: int, n: int, role: str, grant: str | None,
                same_as: str | None) -> None:
    cx.execute("INSERT OR REPLACE INTO roles(person, by, owner_seq, n, role, grant, same_as, at) VALUES "
               "(?,?,?,?,?,?,?,?)", (person, by, seq, n, role, grant if role == "co" else None, same_as, now()))


def _own_role_n(cx: sqlite3.Connection, me: str) -> int:
    return max([_num(r[0]) or 0 for r in cx.execute("SELECT n FROM roles WHERE by=?", (me,))] + [0])


def set_role(ws: Workspace, person: str, role: str) -> dict:
    """The Owner makes `person` a Co-owner ("co") or a Member ("member"). A Co-owner made a Member: in the same
    transaction and before the role, the Owner's copy writes the project's documents again as its own rows, and the
    demoted person's answers that count as its own, so nothing accepted disappears and no proposal opens again.
    Returns the view."""
    from . import researchlog

    me = people.me()
    if role not in ("co", "member"):
        raise ValueError("A role is a Co-owner or a Member.")
    with ws.connect() as cx:
        ctx = _Ctx(ws, cx, me)
        # the maker of a project never exchanged is its owner (is_owner) though no chain names them yet: nobody else
        # is in such a project, so every person is unknown there (404), not a refusal (403)
        if not is_owner(ws, cx):
            raise NotAllowed("Only the owner sets who is a Co-owner.")
        if not ctx.is_owner or person == me or not people.ID_RE.fullmatch(person or "") or person == people.UNKNOWN or \
                not cx.execute("SELECT 1 FROM people WHERE person_id=?", (person,)).fetchone():
            raise KeyError(person)
        cur = ctx.R.get(person) or {"role": "member", "grant": None, "same_as": None}
        if cur["role"] == role:
            return view(ws)
        n = _own_role_n(cx, me) + 1
        if role == "co":
            grant = _new_grant(person, me, ctx.seq, n)
        else:
            grant = None
            _demote(ctx, person)
        _write_role(cx, person, me, ctx.seq, n, role, grant, cur.get("same_as"))
        name = ctx.names.get(person, "a colleague")
        researchlog.record(cx, "owner", f"Made {name} a {'Co-owner' if role == 'co' else 'Member'}"
                                        + (": their changes to the documents hold for everyone, and they answer "
                                           "proposals." if role == "co" else
                                           ": their changes to the documents are proposals from now on."),
                           data={"person": person, "role": role})
        ctx.save()
        seen = _meta(cx, ROLES_SEEN, {})
        if isinstance(seen, dict):
            seen[person] = role
            _set_meta(cx, ROLES_SEEN, seen)
    settle(ws, apply=True)
    return view(ws)


def _demote(ctx: "_Ctx", x: str) -> None:
    """Before `x` stops being a Co-owner (§4.2): every answer of theirs that counts is written again as the Owner's
    (same verdict and reason, knowing what theirs knew), then every document their rows count for is written again as
    the Owner's row, with the "via" entries naming the Owner's copies of the answers.

    A proposal answered both ways with `x` among the answers is decided by nobody (changed after review, M2): the
    Owner's copy writes, in place of any answer of its own there, a row that counts for nothing and says `x` was made a
    Member (`_decisions` keeps such a proposal answered both ways until an answer given knowing that row)."""
    for pid, d in sorted(ctx.dec.items()):
        xa = d["live"].get(x)
        if xa is None or (x, xa["n"]) not in d["top"]:
            continue
        if d["clash"]:
            knew = {(r["by"], r["n"]) for r in d["live"].values()} | set(d.get("markers") or ())
            ctx.cx.execute("INSERT OR REPLACE INTO decisions(proposal, by, owner_seq, verdict, reason, at, auto, n, "
                           "grant, knew_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (pid, ctx.me, ctx.seq, "withdrawn", f"demoted:{x}", now(), 0, ctx.next_dec_n(), None,
                            json.dumps(sorted([b, m] for b, m in knew))))
            continue
        own = d["live"].get(ctx.me)
        knew = set(xa["knew"]) | {(x, xa["n"])}
        if own is not None:
            knew |= set(own["knew"]) | {(ctx.me, own["n"])}
        n = ctx.next_dec_n()
        ctx.write_decision(pid, xa["verdict"], xa["reason"], bool(xa.get("auto")), n, knew)
        ctx.via_rename[(pid, x, xa["n"])] = [ctx.me, n]
    for doc, k in sorted(ctx.K.items()):
        if any(r["by"] == x and r["grant"] is not None for r in k["rows"]):
            ctx.put(doc, (), keep_own=False)


def set_same_as(ws: Workspace, person: str, other: str | None) -> dict:
    """The Owner says `person` is the same human as `other` (None: nobody); role and grant stay. Returns the view."""
    from . import researchlog

    me = people.me()
    with ws.connect() as cx:
        ch = chain(cx)
        if not is_owner(ws, cx):
            raise NotAllowed("Only the owner says who is the same person.")
        if not ch:   # never exchanged: nobody else is in the project yet
            raise KeyError(person)
        known = {r[0] for r in cx.execute("SELECT person_id FROM people")}
        if person not in known or not people.ID_RE.fullmatch(person or ""):
            raise KeyError(person)
        if other is not None and (other not in known or other == person):
            raise KeyError(other)
        R = roles(cx, ch)
        cur = R.get(person) or {"role": "member", "grant": None, "same_as": None}
        if cur.get("same_as") == other:
            return view(ws)
        role = "co" if cur["role"] == "co" else "member"
        if cur["role"] == "owner":  # the owner's own row: their role in the rows (a Member's, unless they were made Co-owner)
            row = cx.execute("SELECT role, grant FROM roles WHERE person=? AND by=? ORDER BY owner_seq DESC, n DESC "
                             "LIMIT 1", (person, me)).fetchone()
            role = row[0] if row and row[0] in ("co", "member") else "member"
        _write_role(cx, person, me, ch[-1]["seq"], _own_role_n(cx, me) + 1, role, cur.get("grant"), other)
        names = _names_cx(cx)
        researchlog.record(cx, "owner", f"{names.get(person, 'A colleague')} and {names.get(other, 'a colleague')} "
                                        "are the same person." if other else
                           f"{names.get(person, 'A colleague')} is nobody else.",
                           data={"person": person, "same_as": other})
    return view(ws)


def adopt(ws: Workspace, sender: str) -> dict:
    """A new copy made from a colleague's zip (bundle.import_project, for another person than the sender): what the
    sender changed of the project's documents and the project has not taken is the sender's, not this copy's
    person's, so the copy starts as the project has its documents:
    - a document of the project the sender removed from their copy (their proposal waits, or was declined) is not
      removed here: the note of its removal goes, so the next round or zip brings it in (or it is fetched from the
      shared folder: `settle`);
    - its passages the sender left out or restored: as the project reads the document;
    - a new reading the sender made stays (it cannot be undone), and stays theirs: it is not proposed again in this
      person's name (`canon_seen.read_from` names the sender; their proposal of the same reading covers it);
    - the sender's tries to make a new reading the project accepted are forgotten: this copy tries for itself;
    - looser AI settings offered to the sender are not offered here as theirs (`ai_offer` cleared).
    Documents the project does not hold (the sender's own additions) are left to `settle`. Nothing changes in a project
    with no owner. Returns {"restored": [doc ids], "blocks": [doc ids]}."""
    from . import reader as reader2

    out: dict[str, list] = {"restored": [], "blocks": []}
    with ws.connect() as cx:
        if not _has_tables(cx):
            return out
        cx.execute("UPDATE canon_seen SET ai_offer=NULL")
        pin_owner(cx, people.me())
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
                cx.execute("UPDATE canon_seen SET state_n=NULL, state_by=NULL, gone=NULL WHERE doc=?", (doc,))
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
            bj = json.dumps(k["blocks"], sort_keys=True)
            cx.execute("INSERT INTO canon_seen(doc, blocks_n, blocks_by, blocks_json, blocks_base) VALUES (?,?,?,?,?) "
                       "ON CONFLICT(doc) DO UPDATE SET blocks_n=excluded.blocks_n, blocks_by=excluded.blocks_by, "
                       "blocks_json=excluded.blocks_json, blocks_base=excluded.blocks_base",
                       (doc, k["blocks_n"], k["blocks_by"], bj, bj))
        if out["blocks"]:
            ws.bump_corpus(cx)
    return out


# ---------------------------------------------------------------------------------------------
# answers to proposals (§4.5)
# ---------------------------------------------------------------------------------------------
def _decisions(cx: sqlite3.Connection, ch: list[dict], R: dict[str, dict] | None = None) -> dict[str, dict]:
    """{proposal id: {"verdict": "accept" | "decline" | None, "clash": bool, "accepted": [by], "declined": [by],
    "top": {(by, n)}, "live": {by: row}, "by", "reason", "at", "auto"}} for every proposal with an answer that counts.

    The answers that count (`_counts`; of the owners' only the latest place's) and that no other of them lists in
    `knew_json` are its *top*. When they all say the same, that verdict counts; when they differ, they were given
    without each other's word and neither counts (`verdict` None, `clash` True): the proposal waits again. No clock
    and no order decide it (the owner's decision of 2026-11-12)."""
    owners = {r["seq"]: r["owner"] for r in ch}
    if not owners:
        return {}
    R = roles(cx, ch) if R is None else R
    cols = {r[1] for r in cx.execute("PRAGMA table_info(decisions)")}
    # 0.18.1 (roadmap L, after a take-over): once the latest place's owner has written its mark
    # (`_Ctx.restamp_decisions`: the former owners' answers it held when it took the project), a former owner's
    # answer counts only if the mark lists it. One given late (offline, still believing they own the project) then
    # waits for the owner's word, as their late changes to the documents do (`_Ctx.restamp`), instead of showing as
    # *Accepted* although it changes no document.
    top_seq = max(owners)
    mark = cx.execute("SELECT knew_json FROM decisions WHERE proposal=? AND by=? AND owner_seq=? LIMIT 1",
                      (restamp_mark(top_seq), owners[top_seq], top_seq)).fetchone() if top_seq > 1 else None
    held = {(x[0], x[1]) for x in _json(mark[0], []) if isinstance(x, list) and len(x) == 2} if mark else None
    by_p: dict[str, list[dict]] = {}
    markers: dict[str, list[dict]] = {}  # an Owner's row for a proposal answered both ways by a person made a Member
    for r in _rows(cx, "SELECT * FROM decisions"):
        if r["verdict"] == "withdrawn" and str(r.get("reason") or "").startswith("demoted:") and \
                r.get("grant") is None and owners.get(r.get("owner_seq")) == r.get("by") and _num(r.get("n")):
            markers.setdefault(r["proposal"], []).append(r)
            continue
        if r["verdict"] not in ("accept", "decline"):
            continue
        n = 0 if r.get("n") is None else _num(r.get("n"))
        if n is None:
            continue
        r["n"] = n
        if "grant" not in cols:
            r["grant"] = None
        t = _counts(r, owners, R)
        if t is None or (held is not None and r["grant"] is None and t < top_seq and (r["by"], n) not in held):
            continue
        r["tier"] = t
        r["knew"] = {(x[0], x[1]) for x in _json(r.get("knew_json"), [])
                     if isinstance(x, list) and len(x) == 2 and isinstance(x[0], str) and _num(x[1]) is not None}
        by_p.setdefault(r["proposal"], []).append(r)
    out: dict[str, dict] = {}
    for pid in set(markers) - set(by_p):
        by_p[pid] = []
    for pid, rs in by_p.items():
        if not rs:  # only the mark of a demotion: answered both ways, and nobody's answer is left
            mk = markers[pid]
            out[pid] = {"accepted": [], "declined": [], "top": set(), "live": {}, "verdict": None, "clash": True,
                        "by": None, "reason": None, "at": None, "auto": 0,
                        "markers": {(m["by"], m["n"]) for m in mk},
                        "demoted": sorted({m["reason"].split(":", 1)[1] for m in mk})}
            continue
        tiers = [r["tier"] for r in rs if r["grant"] is None]
        mx = max(tiers) if tiers else None
        live = [r for r in rs if r["grant"] is not None or r["tier"] == mx]
        known = set().union(*(r["knew"] for r in live))
        top = [r for r in live if (r["by"], r["n"]) not in known] or live
        verdicts = {r["verdict"] for r in top}
        d: dict[str, Any] = {"accepted": sorted(r["by"] for r in top if r["verdict"] == "accept"),
                             "declined": sorted(r["by"] for r in top if r["verdict"] == "decline"),
                             "top": {(r["by"], r["n"]) for r in top}, "live": {r["by"]: r for r in live}}
        mk = [m for m in markers.get(pid, []) if (m["by"], m["n"]) not in known]
        d["markers"] = {(m["by"], m["n"]) for m in markers.get(pid, [])}
        d["demoted"] = sorted({m["reason"].split(":", 1)[1] for m in mk})
        if len(verdicts) == 1 and not mk:
            rep = min((r for r in top), key=lambda r: (r["grant"] is not None, r["by"]))
            d.update(verdict=rep["verdict"], clash=False, by=rep["by"], reason=rep["reason"], at=rep["at"],
                     auto=rep["auto"])
        else:
            d.update(verdict=None, clash=True, by=None, reason=None, at=None, auto=0)
        out[pid] = d
    return out


def restamp_mark(seq: int) -> str:
    """The `proposal` of the row in which the owner of place `seq` lists the former owners' answers that counted when
    it took the project as its own (`knew_json`; an answer to no proposal, which ENLENS 0.18.0 passes by)."""
    return f"~restamped:{seq}"


def _proposals(cx: sqlite3.Connection) -> dict[str, dict]:
    out = {}
    for r in _rows(cx, "SELECT * FROM proposals ORDER BY at, id"):
        if r["kind"] in KINDS and isinstance(r["doc"], str) and people.ID_RE.fullmatch(r["by"] or ""):
            r["detail"] = _json(r.get("detail_json"), {})
            out[r["id"]] = r
    return out


# ---------------------------------------------------------------------------------------------
# the documents as the project has them (§4.4)
# ---------------------------------------------------------------------------------------------
def _clean_blocks(b: dict) -> dict[str, list]:
    return {str(fp): [1 if v[0] else 0, str(v[1]) if len(v) > 1 and v[1] is not None else None]
            for fp, v in b.items() if isinstance(v, list) and v}


def _vkey(p: str, v: Any) -> str:
    return json.dumps(v, sort_keys=True) if p in ("blocks", "read") else str(v)


def _was_value(p: str, v: Any) -> Any:
    """A "via" entry's value before the accept, read safely (§3.1)."""
    if p == "state":
        return "in" if v == "in" else "removed"
    if p == "ai":
        return _level(v)
    if p == "blocks":
        return _clean_blocks(v) if isinstance(v, dict) else {}
    v = v if isinstance(v, dict) else {}
    return {"text_fp": v.get("text_fp"), "reader": _num(v.get("reader")) or 1, "sha1": v.get("sha1")}


def _parse_row(r: dict) -> dict:
    """One row of `canon`, part by part: {p: {"e": (n, by), "v": value, "knew": {events}, "via": entry | None}}, the
    AI entries [(n, by, level)], and the row's own columns."""
    hist = _json(r.get("hist_json"), {})
    via = hist.get("via") if isinstance(hist.get("via"), dict) else {}
    out: dict[str, Any] = {"by": r["by"], "grant": r.get("grant"), "tier": r.get("tier"), "n": r["n"],
                           "owner_seq": r.get("owner_seq"), "at": r.get("at"), "sha1": r.get("sha1"),
                           "title": r.get("title"), "ai_list": []}
    for p in PARTS:
        e = (_num(r.get(f"{p}_n")) or 0, r.get(f"{p}_by") or r["by"])
        if p == "ai":
            lst = []
            for h in _json(r.get("ai_hist_json"), []):
                if isinstance(h, list) and len(h) in (2, 3) and _num(h[0]) is not None:
                    lst.append((h[0], h[2] if len(h) == 3 and isinstance(h[2], str) and h[2] else r["by"],
                                _level(h[1])))
            out["ai_list"] = lst
            knew = {(a, b) for a, b, _lv in lst}
            v: Any = _level(r.get("ai_access"))
        else:
            knew = {(h[0], h[1]) for h in (hist.get(p) or []) if isinstance(h, list) and len(h) == 2
                    and _num(h[0]) is not None and isinstance(h[1], str)}
            v = ("in" if r.get("state") == "in" else "removed") if p == "state" else \
                {"text_fp": r.get("text_fp"), "reader": _num(r.get("reader")) or 1, "sha1": r.get("sha1")} \
                if p == "read" else _clean_blocks(_json(r.get("blocks_json"), {}))
        vv = via.get(p)
        ok = isinstance(vv, dict) and isinstance(vv.get("p"), str) and isinstance(vv.get("d"), list) and \
            len(vv["d"]) == 2 and isinstance(vv["d"][0], str) and _num(vv["d"][1]) is not None
        out[p] = {"e": e, "v": v, "knew": knew | {e}, "via": vv if ok else None}
    # 0.18.1: the removals proposed for the document that its writer had seen when it last changed the document's
    # state (None: a row of ENLENS 0.18.0, which did not say)
    seen = hist.get("seen")
    out["seen"] = {x for x in seen if isinstance(x, str)} if isinstance(seen, list) else None
    return out


SEEN_CAP = 200  # (removals proposed for one document; more would only make each row longer)


def removal_spent(k: dict, pid: str) -> bool:
    """Whether a proposed removal (`pid`) of a document the project has kept or taken in again since is spent: the
    project went on knowing of it (a writer who had seen it changed the document's state), or the state's last change
    was written by ENLENS 0.18.0, which did not say what it had seen. A change made without knowing of it (at the
    same time) leaves the removal standing: the proposer's copy keeps it out and the proposal waits (roadmap L,
    after 0.17.0)."""
    rows = k.get("rows") or []
    if any(pid in (r.get("seen") or ()) for r in rows):
        return True
    cur = (k["state_n"], k["state_by"])
    maker = [r for r in rows if r["state"]["e"] == cur]
    return not maker or all(r.get("seen") is None for r in maker)


def _void(row: dict, dec: dict[str, dict]) -> tuple[dict | None, dict[str, set]]:
    """A row with the events an accept made that does not count (§4.5) read as what was there before it. Returns
    (the row, or None when it held no document before the accept; {part: void events})."""
    voids: dict[str, set] = {}
    for p in PARTS:
        v = row[p]["via"]
        if v is None:
            continue
        d = dec.get(v["p"])
        if d is not None and d["verdict"] == "accept" and (v["d"][0], v["d"][1]) in d["top"]:
            continue
        voids.setdefault(p, set()).add(row[p]["e"])
        if v.get("was") is None:
            return None, {q: (voids.get(q, set()) | ({row[q]["e"]} if row[q]["via"] else set())) for q in PARTS}
        row[p] = {"e": (_num(v.get("was_n")) or 0, v.get("was_by") if isinstance(v.get("was_by"), str) and
                        v.get("was_by") else row["by"]),
                  "v": _was_value(p, v["was"]), "knew": row[p]["knew"], "via": None}
    return row, voids


def _merge_doc(doc: str, rows: list[dict], voids: dict[str, set]) -> dict:
    """The document as the counting rows say, part by part (§4.4): an event another row knew and replaced is gone;
    what is left, if it differs, was made at the same time: the document stays, the higher reader counts, the stricter
    AI setting counts, the larger person id's blocks count, and a clash is noted."""
    k: dict[str, Any] = {"doc": doc, "same": {}, "hist": {}, "top": {}, "events": {}, "void": voids, "via": {},
                         "clashes": [], "rows": rows,
                         "n": max(r["n"] for r in rows), "owner_seq": max((r["tier"] for r in rows
                                                                          if r["grant"] is None), default=0)}
    for p in PARTS:
        gone: set = set()
        for r in rows:
            gone |= {e for e in r[p]["knew"] if e != r[p]["e"]}
        top = [r for r in rows if r[p]["e"] not in gone] or rows
        vals: dict[str, list[dict]] = {}
        for r in top:
            vals.setdefault(_vkey(p, r[p]["v"]), []).append(r)
        if len(vals) == 1:
            win = next(iter(vals.values()))
        else:
            if p == "state":
                win = vals.get(_vkey(p, "in")) or next(iter(vals.values()))
            elif p == "read":
                win = max(vals.values(), key=lambda rs: (rs[0][p]["v"]["reader"], rs[0][p]["v"]["text_fp"] or ""))
            elif p == "ai":
                win = max(vals.values(), key=lambda rs: RANK[rs[0][p]["v"]])
            else:
                win = max(vals.values(), key=lambda rs: max((r[p]["e"][1], r[p]["e"][0]) for r in rs))
        src = max(win, key=lambda r: r[p]["e"])
        e = src[p]["e"]
        k["same"][p] = {r[p]["e"] for r in win}
        k["top"][p] = {r[p]["e"] for r in top}
        k["hist"][p] = set().union(*(r[p]["knew"] for r in rows)) | k["top"][p]
        k["events"][p] = {r[p]["e"] for r in rows}
        k["via"][p] = src[p]["via"]
        k[f"{p}_n"], k[f"{p}_by"] = e
        v = src[p]["v"]
        if p == "state":
            k["state"] = v
            k["by"], k["at"] = src["by"], src["at"]
        elif p == "read":
            k["text_fp"], k["reader"], k["sha1"] = v["text_fp"], v["reader"], v["sha1"] or src["sha1"]
            k["title"] = src["title"] or next((r["title"] for r in rows if r["title"]), None)
        elif p == "ai":
            k["ai_access"] = v
        else:
            k["blocks"] = dict(v)
        if len(vals) > 1:
            k["clashes"].append({"part": p, "counts": e,
                                 "events": sorted({(r[p]["e"][0], r[p]["e"][1], _vkey(p, r[p]["v"])) for r in top})})
    hist: dict[tuple, str] = {}
    for r in rows:
        for a, b, lv in r["ai_list"]:
            hist.setdefault((a, b), lv)
        hist[r["ai"]["e"]] = r["ai"]["v"]
    k["ai_hist"] = [[a, lv, b] for (a, b), lv in sorted(hist.items())]
    return k


def canon(cx: sqlite3.Connection, ch: list[dict] | None = None, R: dict[str, dict] | None = None,
          dec: dict[str, dict] | None = None, voided: dict[str, dict] | None = None) -> dict[str, dict]:
    """{document id: the document as the project has it} (§4.4), merged part by part from the rows that count
    (`_counts`; of the owners' rows only the latest place's), after the events of accepts that do not count are read
    as what was there before (`_void`). Each document: its values ("state", "text_fp", "reader", "sha1", "title",
    "ai_access", "blocks"), per part `p` the event that counts (`p_n`, `p_by`), "same" / "top" / "hist" / "events" /
    "void" {part: set of events}, "via" {part: the accept that made the event, or None}, "ai_hist" [[n, level, by]],
    "by" / "at" (of the row that gave the state), "clashes", "rows". Numbers of two writers are never compared to
    decide a value. `voided`: filled with {doc: {part: void events}} of documents no counting row holds any more."""
    ch = chain(cx) if ch is None else ch
    owners = {r["seq"]: r["owner"] for r in ch}
    out: dict[str, dict] = {}
    if not owners:
        return out
    R = roles(cx, ch) if R is None else R
    dec = _decisions(cx, ch, R) if dec is None else dec
    cols = {r[1] for r in cx.execute("PRAGMA table_info(canon)")}
    by_doc: dict[str, list[dict]] = {}
    for r in _rows(cx, "SELECT * FROM canon"):
        if _num(r.get("n")) is None or r["n"] < 1 or not isinstance(r.get("doc"), str) or \
                not people.ID_RE.fullmatch(r.get("by") or ""):
            continue
        if "grant" not in cols:
            r["grant"] = None
        t = _counts(r, owners, R)
        if t is None:
            continue
        r["tier"] = t
        by_doc.setdefault(r["doc"], []).append(r)
    for doc, rs in by_doc.items():
        tiers = [r["tier"] for r in rs if r["grant"] is None]
        mx = max(tiers) if tiers else None
        parsed, voids = [], {}
        for r in rs:
            if r["grant"] is not None or r["tier"] == mx:
                row, v = _void(_parse_row(r), dec)
                for p, es in v.items():
                    voids.setdefault(p, set()).update(es)
                if row is not None:
                    parsed.append(row)
        if parsed:
            out[doc] = _merge_doc(doc, parsed, {p: voids.get(p, set()) for p in PARTS})
        elif voids and voided is not None:
            voided[doc] = voids
    return out


def clashes(cx: sqlite3.Connection) -> list[dict]:
    """What was changed at the same time (§4.4, I7): parts of documents ({"id", "kind": "part", "doc", "title", "part",
    "events": [{"n", "by", "value"}], "counts": {"n", "by"}, "people": [ids]}) and proposals answered both ways ({"id",
    "kind": "answer", "doc", "title", "proposal", "what", "accepted": [ids], "declined": [ids], "people"})."""
    ch = chain(cx)
    if not ch:
        return []
    R = roles(cx, ch)
    dec = _decisions(cx, ch, R)
    return _clash_list(canon(cx, ch, R, dec), dec, _proposals(cx))


def _clash_list(K: dict[str, dict], dec: dict[str, dict], props: dict[str, dict]) -> list[dict]:
    out = []
    for doc, k in sorted(K.items()):
        for c in k["clashes"]:
            evs = [{"n": n, "by": by, "value": json.loads(v) if c["part"] in ("blocks", "read") else v}
                   for n, by, v in c["events"]]
            cid = "c" + hashlib.sha1(f"{doc}|{c['part']}|{json.dumps(c['events'])}".encode()).hexdigest()[:12]
            out.append({"id": cid, "kind": "part", "doc": doc, "title": k["title"], "part": c["part"], "events": evs,
                        "counts": {"n": c["counts"][0], "by": c["counts"][1]},
                        "people": sorted({e["by"] for e in evs})})
    for pid, d in sorted(dec.items()):
        if not d["clash"] or pid not in props:
            continue
        p = props[pid]
        demoted = d.get("demoted") or []
        out.append({"id": "a" + pid + ("d" if demoted else ""), "kind": "answer", "doc": p["doc"], "title": p["title"],
                    "part": None, "proposal": pid, "what": what(p), "accepted": d["accepted"],
                    "declined": d["declined"], "demoted": demoted,
                    "people": sorted(set(d["accepted"]) | set(d["declined"]) | set(demoted))})
    return out


def level_at(hist: list, n: int) -> str | None:
    """Who might read a document with AI, as the project had it at change number `n` (the first setting, before
    that). Entries are [n, level] or [n, level, by]."""
    out = None
    for h in sorted((h for h in hist if isinstance(h, list) and len(h) >= 2), key=lambda h: (h[0], str(h[2:]))):
        if out is None or (isinstance(h[0], int) and h[0] <= n):
            out = h[1]
    return out


def stale_strict(cx: sqlite3.Connection, doc: str, theirs: str, their_n: Any) -> bool:
    """Whether a colleague's stricter AI setting of a document is only the one the project has loosened since, in a copy
    that has not followed that change yet (sync/merge.py `_stricter` then leaves this copy's setting as it is). A
    setting made stricter by a person who had followed the project's last word (`their_n`) is never stale; nor is one
    when two changes share that number and differ in level (the stricter one is applied)."""
    k = canon(cx).get(doc)
    if not k or k["state"] != "in":
        return False
    n = their_n if isinstance(their_n, int) else 0
    if n >= k["ai_n"]:
        return False
    s = cx.execute("SELECT ai_n, ai_by FROM canon_seen WHERE doc=?", (doc,)).fetchone()
    if not s or s[0] is None or not _followed_ev(k, "ai", s[0], s[1]):
        return False  # this copy has not followed it either: the stricter setting holds
    at_n = [h for h in k["ai_hist"] if h[0] <= n]
    if at_n:
        top = max(h[0] for h in at_n)
        if len({h[1] for h in at_n if h[0] == top}) > 1:
            return False
    return level_at(k["ai_hist"], n) == theirs


def _followed_ev(k: dict, p: str, n: Any, by: Any) -> bool:
    """Whether the event (n, by) a copy followed is the project's for part `p` (or one of the same value made at the
    same time). `by` NULL: written by 0.17, numbers alone."""
    if n is None:
        return False
    if by is None:
        return n == k[f"{p}_n"] or any(e[0] == n for e in k["same"][p])
    return (n, by) == (k[f"{p}_n"], k[f"{p}_by"]) or (n, by) in k["same"][p]


def not_wanted(cx: sqlite3.Connection, me: str | None = None) -> set[str]:
    """The documents a colleague's work must not bring (back) into this copy: those the project removed, and those a
    collaborator added that were declined (or that they took back), unless this copy's own person proposed them.
    Empty in a project with no owner."""
    ch = chain(cx)
    if not ch:
        return set()
    me = me or people.me()
    R = roles(cx, ch)
    dec = _decisions(cx, ch, R)
    K = canon(cx, ch, R, dec)
    out = {d for d, k in K.items() if k["state"] == "removed"}
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
# one look at this copy (`settle`, §4.6)
# ---------------------------------------------------------------------------------------------
def _cap(events: set, protect: set, must: Iterable = ()) -> list[list]:
    """A history list, newest last, at most `HIST_CAP` entries: an event that is still the current event of a row that
    counts (`protect`) or `must` is never dropped; the cap drops the oldest of the others."""
    keep = set(must) | (events & protect)
    rest = sorted(events - keep, reverse=True)[:max(0, HIST_CAP - len(keep))]
    return [list(e) for e in sorted(keep | set(rest))]


class _Ctx:
    def __init__(self, ws: Workspace, cx: sqlite3.Connection, me: str):
        from .sync.common import text_fps
        from .sync.folder import ai_settings

        self.ws, self.cx, self.me = ws, cx, me
        self.chain = chain(cx)
        self.owner = self.chain[-1]["owner"] if self.chain else None
        self.seq = self.chain[-1]["seq"] if self.chain else 0
        self.is_owner = self.owner == me
        self.R = roles(cx, self.chain) if self.chain else {}
        self.role = (self.R.get(me) or {}).get("role") or "member"
        self.writes = self.role in ("owner", "co")
        self.grant = None if self.is_owner else (self.R.get(me) or {}).get("grant")
        self.dec = _decisions(cx, self.chain, self.R)
        self.voided: dict[str, dict] = {}
        self.K = canon(cx, self.chain, self.R, self.dec, self.voided)
        # this writer's numbers come from its own rows and the events of the rows that count, never from rows that do
        # not count (review, H2: one row of a Member's numbered at the top of the range stopped every writer)
        self.mine_rows = {r["doc"]: _parse_row(dict(r, tier=None)) for r in _rows(cx, "SELECT * FROM canon WHERE by=?",
                                                                                (me,)) if _num(r.get("n")) is not None}
        nums = [0] + [r["n"] for r in self.mine_rows.values()] + \
            [x for r in self.mine_rows.values() for x in (r[p]["e"][0] for p in PARTS)]
        for k in self.K.values():
            for r in k["rows"]:
                nums += [r["n"]] + [r[p]["e"][0] for p in PARTS]
        self.n = max(nums)
        self.top_held = max([0] + [v for row in cx.execute("SELECT n, state_n, read_n, ai_n, blocks_n FROM canon")
                                   for v in (_num(x) for x in row) if v is not None])
        self.dec_n = max([_num(r[0]) or 0 for r in cx.execute("SELECT n FROM decisions WHERE by=?", (me,))] + [0])
        self.props = _proposals(cx)
        self._by_doc: dict[tuple[str, str], list[dict]] | None = None
        self.S = {r["doc"]: r for r in _rows(cx, "SELECT * FROM canon_seen")}
        self.own_rows = {r["doc"]: r for r in _rows(cx, "SELECT doc, state_n, read_n, ai_n, blocks_n FROM canon WHERE "
                                                       "by=?", (me,))}
        self.dirty: set[str] = set()
        self.loosen_used = set(_meta(cx, LOOSEN_USED, []))
        self.loosen_used_new = False
        self.via_rename: dict[tuple, list] = {}
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

    # this copy's record of how far it followed the project
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
        if self.loosen_used_new:
            _set_meta(self.cx, LOOSEN_USED, sorted(self.loosen_used))
            self.loosen_used_new = False
        for d in sorted(self.dirty):
            s = self.S[d]
            self.cx.execute(f"INSERT OR REPLACE INTO canon_seen(doc, {', '.join(_SEEN)}) VALUES "
                            f"({','.join('?' * (len(_SEEN) + 1))})", (d, *[s.get(c) for c in _SEEN]))
        self.dirty.clear()

    def follow(self, doc: str, *parts: str) -> None:
        """This copy has followed the project's word on these parts of the document (§4.6)."""
        k = self.K[doc]
        for p in parts:
            cols: dict[str, Any] = {f"{p}_n": k[f"{p}_n"], f"{p}_by": k[f"{p}_by"]}
            if p == "ai":
                cols["ai_level"] = k["ai_access"]
                cols["ai_offer"] = None
            elif p == "blocks":
                cols["blocks_json"] = json.dumps(k["blocks"], sort_keys=True)
                if not self.made_here(doc, "blocks", (k["blocks_n"], k["blocks_by"])) or \
                        (self.S.get(doc) or {}).get("blocks_base") is None:
                    cols["blocks_base"] = cols["blocks_json"]  # the project's choices from someone else's word
            self.mark(doc, **cols)

    def ev(self, doc: str, p: str) -> tuple[Any, Any] | None:
        s = self.S.get(doc) or {}
        return None if s.get(f"{p}_n") is None else (s[f"{p}_n"], s.get(f"{p}_by"))

    def followed(self, doc: str, p: str) -> bool:
        e, k = self.ev(doc, p), self.K.get(doc)
        return bool(e and k) and _followed_ev(k, p, e[0], e[1])

    def moved_on(self, doc: str, p: str) -> bool:
        """The event this copy followed is one the project knew (and went on from, or made at the same time)."""
        e, k = self.ev(doc, p), self.K.get(doc)
        if not e or not k:
            return False
        if e[1] is None:
            return any(x[0] == e[0] for x in k["hist"][p])
        return e in k["hist"][p]

    def made_here(self, doc: str, p: str, e: tuple | None) -> bool:
        """Whether this copy made the event `e` of part `p`: its own row of the document has it, as its event or in its
        list. A row of someone else saying an event is this person's proves nothing (review, C2)."""
        r = self.mine_rows.get(doc)
        return bool(e and r and e[1] == self.me and (e == r[p]["e"] or tuple(e) in r[p]["knew"]))

    def own_event(self, doc: str, p: str) -> bool:
        e = self.ev(doc, p)
        if not e:
            return False
        if e[1] is None:  # 0.17: this copy's own row said that number
            r = self.own_rows.get(doc)
            return bool(r) and r.get(f"{p}_n") == e[0]
        return self.made_here(doc, p, e)

    def mine_lost(self, doc: str, p: str) -> bool:
        """This copy followed its own event, which the project neither has nor knew (a row of a former owner or of a
        demoted Co-owner, written as far as this person knew with the right to): their own change, to propose."""
        return self.own_event(doc, p) and not self.followed(doc, p) and not self.moved_on(doc, p)

    def void(self, doc: str, p: str) -> bool:
        """The event this copy followed was made by an accept that does not count (§4.5)."""
        e = self.ev(doc, p)
        if not e or e[1] is None:
            return False
        k = self.K.get(doc)
        return e in (k["void"][p] if k else set()) or e in (self.voided.get(doc) or {}).get(p, set())

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

    # answers
    def next_dec_n(self) -> int:
        self.dec_n += 1
        return self.dec_n

    def write_decision(self, pid: str, verdict: str, reason: str | None, auto: bool, n: int, knew: Iterable) -> None:
        self.cx.execute("INSERT OR REPLACE INTO decisions(proposal, by, owner_seq, verdict, reason, at, auto, n, grant, "
                        "knew_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (pid, self.me, self.seq, verdict, (reason or "").strip()[:1000] or None, now(),
                         1 if auto else 0, n, self.grant, json.dumps(sorted([b, m] for b, m in set(knew)))))
        self.dec = _decisions(self.cx, self.chain, self.R)

    # the documents as the project has them (a writer's copy writes them)
    def _renamed(self, via: dict | None) -> dict | None:
        if via is None:
            return None
        to = self.via_rename.get((via.get("p"), via["d"][0], via["d"][1]))
        return {**via, "d": list(to)} if to else via

    def put(self, doc: str, bump: Iterable[str], via: dict | None = None, extra: dict | None = None,
            keep_own: bool = True, **cols: Any) -> dict:
        """Write this writer's row for `doc` (§4.4): it starts from the document as the project has it, with `cols`
        changed. Each part in `bump` gets a new event `(n, me)` whose list gains every event of the part's top (so a
        new word knows both sides of a clash); `via[part]`: the accept that made it (§4.5). Every other part keeps
        this writer's own event while that is in the top (writing one part decides no clash of another), else copies
        the event that counts, with what was known. `extra`: {part: events} the new events also knew (§4.10).
        `keep_own` False (a restamp, a demotion: the other side's rows stop counting with this row): every part not
        numbered anew copies the value that counts."""
        self.n += 1
        e = (self.n, self.me)
        base = self.K.get(doc)
        new = base is None
        bump = tuple(PARTS) if new else tuple(bump)
        mine = next((r for r in (base or {}).get("rows", []) if r["by"] == self.me), None) if keep_own else None
        k: dict[str, Any] = {"doc": doc, "state": "in", "sha1": None, "title": None, "text_fp": None, "reader": None,
                             "ai_access": "none", "blocks": {}}
        if base:
            k.update({c: base[c] for c in ("state", "sha1", "title", "text_fp", "reader", "ai_access")})
            k["blocks"] = dict(base["blocks"])
        k.update(cols)
        k["ai_access"] = _level(k["ai_access"])
        k["blocks"] = _clean_blocks(k.get("blocks") or {})
        lists: dict[str, list] = {}
        vias: dict[str, Any] = {}
        events: dict[str, tuple] = {}
        values = {"state": k["state"], "read": {"text_fp": k["text_fp"], "reader": k["reader"], "sha1": k["sha1"]},
                  "ai": k["ai_access"], "blocks": k["blocks"]}
        for p in PARTS:
            protect = base["events"][p] if base else set()
            if p in bump:
                known = ((base["hist"][p] | base["top"][p]) if base else set()) | set((extra or {}).get(p) or ())
                events[p] = e
                lists[p] = _cap(known | {e}, protect, [e])
                vias[p] = (via or {}).get(p)
            elif mine is not None and mine[p]["e"] in base["top"][p] and mine[p]["e"] not in base["same"][p]:
                events[p] = mine[p]["e"]   # this writer's own side of a clash stays as it was
                values[p] = mine[p]["v"]
                lists[p] = _cap(mine[p]["knew"], protect, [mine[p]["e"]])
                vias[p] = self._renamed(mine[p]["via"])
            else:
                events[p] = (base[f"{p}_n"], base[f"{p}_by"])
                lists[p] = _cap((base["hist"][p] - base["top"][p]) | base["same"][p], protect, [events[p]])
                vias[p] = self._renamed(base["via"][p])
        levels = {(h[0], h[2]): h[1] for h in (base or {}).get("ai_hist", [])}
        levels[events["ai"]] = values["ai"]
        ai_list = [[n, levels.get((n, by), values["ai"]), by] for n, by in lists["ai"]]
        hist = {p: lists[p] for p in ("state", "read", "blocks")}
        own = (self.mine_rows.get(doc) or {}).get("seen") or set()
        if "state" in bump:   # this writer's new state event: what it had seen now
            hist["seen"] = sorted(set(own) | {q["id"] for q in self.about("remove", doc)
                                              if not q["taken_back_at"]})[-SEEN_CAP:]
        else:
            # the state event is kept: so is what its maker had seen when making it (a restamp or another part's
            # change must not empty it, review 1); a maker of ENLENS 0.18.0, who said nothing, is said nothing for
            makers = [r for r in (base or {}).get("rows", []) if r["state"]["e"] == tuple(events["state"])]
            sees = [r["seen"] for r in makers if r.get("seen") is not None]
            if sees:
                hist["seen"] = sorted(set().union(*sees))[-SEEN_CAP:]
            elif not makers:
                hist["seen"] = sorted(own)[-SEEN_CAP:]
        vv = {p: v for p, v in vias.items() if v}
        if vv:
            hist["via"] = vv
        rd = values["read"]
        row = {"doc": doc, "by": self.me, "owner_seq": self.seq, "n": self.n, "grant": self.grant,
               "state": values["state"], "state_n": events["state"][0], "state_by": events["state"][1],
               "sha1": rd["sha1"], "title": k["title"], "text_fp": rd["text_fp"], "reader": rd["reader"],
               "read_n": events["read"][0], "read_by": events["read"][1],
               "ai_access": values["ai"], "ai_n": events["ai"][0], "ai_by": events["ai"][1],
               "ai_hist_json": json.dumps(ai_list), "blocks_json": json.dumps(values["blocks"], sort_keys=True),
               "blocks_n": events["blocks"][0], "blocks_by": events["blocks"][1],
               "hist_json": json.dumps(hist, sort_keys=True), "at": now()}
        self.cx.execute(f"INSERT OR REPLACE INTO canon({', '.join(_ROW_COLS)}) VALUES "
                        f"({','.join('?' * len(_ROW_COLS))})", [row[c] for c in _ROW_COLS])
        self.own_rows[doc] = {"doc": doc, **{f"{p}_n": events[p][0] for p in PARTS}}
        self.mine_rows[doc] = _parse_row(dict(row, tier=None))
        if not self.writes:  # (a row answering a forged one, §4.10, in a copy that cannot write: it counts for nothing)
            return base or {}
        # the document as the project has it now: this row's events, with the rest as before
        row["tier"] = TOP if self.grant is not None else self.seq
        parsed = _parse_row(row)
        rows = [r for r in (base or {}).get("rows", []) if r["by"] != self.me] + [parsed]
        if not new and self.grant is None:
            rows = [r for r in rows if r["grant"] is not None or r["tier"] >= self.seq]
        self.K[doc] = _merge_doc(doc, rows, (base or {}).get("void") or {p: set() for p in PARTS})
        return self.K[doc]

    def restamp(self) -> None:
        """A new owner's copy (place 2 or later) writes every document of the project that has no owner's row of its
        place again, as its own (no part numbered anew, so no copy sees a change). Of the owners' rows only the latest
        place's count, so a row a former owner writes late (offline after a take-over, still believing they own the
        project) never counts over the owner's, also for a document only Co-owners wrote (changed after review, M1):
        their change is then theirs alone (a proposal, or held)."""
        if self.seq <= 1:
            return
        for doc, k in sorted(self.K.items()):
            if not any(r["grant"] is None and r["tier"] == self.seq for r in k["rows"]):
                self.put(doc, (), keep_own=False)

    def restamp_decisions(self) -> None:
        """A new owner's copy (place 2 or later) writes, once, its mark (`restamp_mark`): the former owners' answers
        that count as it takes the project as its own. From then on a former owner's answer counts only if the mark
        lists it (`_decisions`), so one that reaches this copy later shows as waiting. The answers themselves are not
        written again: the documents' changes their accepts made name them (`via`)."""
        if self.seq <= 1 or self.cx.execute("SELECT 1 FROM decisions WHERE proposal=? AND by=? AND owner_seq=?",
                                            (restamp_mark(self.seq), self.me, self.seq)).fetchone():
            return
        held = sorted({(r["by"], r["n"]) for d in self.dec.values() for r in d["live"].values()
                       if r["grant"] is None and r["tier"] < self.seq})
        self.cx.execute("INSERT OR REPLACE INTO decisions(proposal, by, owner_seq, verdict, reason, at, auto, n, grant, "
                        "knew_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (restamp_mark(self.seq), self.me, self.seq, "withdrawn", "restamped", now(), 0,
                         self.next_dec_n(), None, json.dumps([list(x) for x in held])))
        self.dec = _decisions(self.cx, self.chain, self.R)

    def restamp_roles(self) -> None:
        """A new owner (place 2 or later) writes, once, a row for every person the project knows with the role that
        counts (a Member's too): a former owner's late row then never counts for anyone this owner knew (§4.2)."""
        if self.seq <= 1 or self.cx.execute("SELECT 1 FROM roles WHERE by=? AND owner_seq=? LIMIT 1",
                                            (self.me, self.seq)).fetchone():
            return
        known = {r[0] for r in self.cx.execute("SELECT person_id FROM people") if r[0]} | set(self.R)
        known = sorted(p for p in known if p != self.me and people.ID_RE.fullmatch(p) and p != people.UNKNOWN)
        n = _own_role_n(self.cx, self.me)
        for p in known:
            cur = self.R.get(p) or {"role": "member", "grant": None, "same_as": None}
            n += 1
            _write_role(self.cx, p, self.me, self.seq, n, "co" if cur["role"] == "co" else "member", cur.get("grant"),
                        cur.get("same_as"))

    def put_from_here(self, doc: str, bump: Iterable[str] = (), via: dict | None = None) -> dict:
        """This writer's row for `doc` as this copy has it; this copy has then followed it in every part."""
        L = self.docs[doc]
        k = self.put(doc, bump, via=via, state="in", sha1=(L["sha1"] or "").split("~")[0] or None, title=L["title"],
                     text_fp=L["text_fp"], reader=L["reader"], ai_access=_level(self.levels.get(doc)),
                     blocks=dict(self.choices.get(doc) or {}))
        self.follow(doc, *PARTS)
        return k

    # changes to this copy
    def remove_here(self, doc: str, why: str, by: str | None, cause: str = "removed", wish_of: str | None = None) -> None:
        """Remove a document from this copy because a colleague's word said so: as when a person removes it (its
        checks keep their grades as records; the research log says why). It can be restored for 30 days (removed.py:
        an archive of its rows and its file is made first); the note of its removal is the colleague's, not this
        person's, so it is not taken for this person's own wish."""
        from . import removed

        title = self.docs[doc]["title"]
        removed.archive(self.ws, self.cx, doc, by, why, cause)  # (no longer a copy of the whole database)
        self.ws.remove_document(doc, why=why)
        # whose removal it is: `wish_of` when given (0.18.1: a former owner's removal kept by this owner's own rows is
        # noted as the owner's word, but it is not this person's own wish, review 13)
        self.cx.execute("UPDATE sync_removed SET person_id=? WHERE kind='document' AND key=?",
                        (wish_of or by or self.owner, doc))
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
        from . import docrole, researchlog

        was = docrole.role_from_choices(self.choices.get(doc) or {})
        was_ns = docrole.nonscientific_from_choices(self.choices.get(doc) or {})
        self.choices[doc] = dict(want)
        reader2.apply_choices(self.cx, doc)
        self.ws.bump_corpus(self.cx)
        self.report["applied"].append({"kind": "blocks", "doc": doc, "title": self.docs[doc]["title"]})
        role = docrole.role_from_choices(want)
        if role != was:  # 0.18.1 (K2): a theory mark the project took is a log entry of its own, as one's own mark is
            who = self.names.get(by or self.owner, "the owner")
            researchlog.record(self.cx, "document-role",
                               f"Marked as a working document by {who}: never a source, left out of themes, check "
                               "excerpts, key terms and the corpus's code counts from now on." if role == docrole.WORKING
                               else  # 0.18.8 (N3)
                               f"Marked as theory by {who}: it is left out of themes, codebook labels, check excerpts "
                               "and key terms from now on." if role else
                               f"Marked as evidence again by {who}: it counts in themes, codebook labels, check excerpts "
                               "and key terms from now on.", "document", doc, self.docs[doc]["title"],
                               data={"role": role, "was": was, "by": by or self.owner})
        ns = docrole.nonscientific_from_choices(want)
        if ns != was_ns:  # 0.18.6: the Non-scientific mark the project took, as one's own mark is
            who = self.names.get(by or self.owner, "the owner")
            researchlog.record(self.cx, "document-mark",
                               f"Marked as non-scientific by {who}: no judgement of its excerpts counts in an answer "
                               "from now on, except in checks set to count them." if ns else
                               f"Counted as scientific again by {who}: its judgements count in answers from now on.",
                               "document", doc, self.docs[doc]["title"], data={"nonscientific": ns, "by": by or self.owner})


def _changed(k: dict, part: str, det: dict) -> bool:
    """Whether the project's event of `part` is another than the one a proposal was made against (`det`: `part_n`,
    `part_by`; a proposal of 0.17 has the number alone)."""
    n, by = det.get(f"{part}_n") or 0, det.get(f"{part}_by")
    if by is None:
        return (k[f"{part}_n"] or 0) != n
    return (k[f"{part}_n"], k[f"{part}_by"]) != (n, by) and (n, by) not in k["same"][part]


def state_of(p: dict, K: dict[str, dict], dec: dict[str, dict]) -> tuple[str, str | None]:
    """A proposal's state and, for one that no longer needs an answer, why: ("waiting" | "accepted" | "declined" |
    "taken_back" | "replaced" | "moot", words or None). One answered both ways at the same time waits again
    ("answered both ways")."""
    det = p["detail"]
    d = dec.get(p["id"])
    if d is not None and d["clash"] and not p["taken_back_at"]:
        return "waiting", "answered both ways"
    if d is not None and d["verdict"]:
        return ("accepted" if d["verdict"] == "accept" else "declined"), None
    if p["taken_back_at"]:
        return ("replaced" if p["taken_back_at"].startswith("replaced") else "taken_back"), None
    k = K.get(p["doc"])
    kind = p["kind"]
    if kind == "add":
        if k is not None and _changed(k, "state", det):
            if k["state"] == "in":
                return "accepted", "The owner added it too."
            return "moot", "The owner removed this document from the project."
        return "waiting", None
    if k is None:
        return "moot", "The document is not one of the project's documents (it was added by a collaborator and not accepted)."
    if k["state"] == "removed":
        return ("accepted", "The owner removed it.") if kind == "remove" else \
            ("moot", "The document was removed from the project since.")
    if kind == "remove" and _changed(k, "state", det) and removal_spent(k, p["id"]):
        return "moot", "The document was removed from the project and added to it again since."
    if kind == "reread" and (k["reader"] or 1) >= (det.get("to_reader") or 0):
        return "accepted", "The project's reading of it is as new already."
    if kind == "loosen" and _changed(k, "ai", det):
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
            side = fp.split(":", 1)[0] if fp.startswith(("start:", "end:", "role:")) else None
            if side:  # the text starts (or ends) in one place only; 0.18.8 (N3): a document has one role only
                for other in [f for f in out if f.startswith(side + ":")]:
                    out.pop(other)
            out[fp] = [1 if v[0] else 0, v[1] if len(v) > 1 else None]
    return out


def _delta_words(delta: dict) -> dict:
    out: dict[str, Any] = {"left_out": 0, "restored": 0, "undone": 0, "bounds": 0}
    for fp, v in delta.items():
        if fp.startswith(("start:", "end:")):
            out["bounds"] += 1
        elif fp.startswith("role:"):  # 0.18.1 (K2, docrole.py): marked as theory (a role), or as evidence again
            # 0.18.8 (N3): theory to working is a role set and one taken away: the role set wins, in any order
            if v is not None and v[0]:
                out["role"] = fp.split(":", 1)[1]
            else:
                out.setdefault("role", "evidence")
        elif fp.startswith("mark:"):  # 0.18.6 (docrole.py): marked Non-scientific, or counted as scientific again
            out[fp.split(":", 1)[1]] = bool(v is not None and v[0])
        elif v is None:
            out["undone"] += 1
        else:
            out["restored" if v[0] else "left_out"] += 1
    return out


def _empty_report() -> dict:
    return {"owner": None, "proposed": [], "accepted": [], "applied": [], "moves": [], "fetch": [], "notes": []}


def settle(ws: Workspace, apply: bool = True, moves: bool = False, leaving: bool = False, wait: bool = True) -> dict:
    """One look at this copy (see the module's notes). `apply` False: only what is safe at any moment (proposals and
    the writer's rows are written, AI settings are held or followed); a document is removed, blocks are changed and a
    missing document is fetched only with `apply`, which a caller gives when no other work of the project runs (a
    round of the shared folder, a zip brought in, a person's own click). `moves`: also make the new readings that
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
            return {**_empty_report(), "busy": True}
        finally:
            cx0.execute(f"PRAGMA busy_timeout={int(before)}")
    me = people.me()
    if apply:
        _prune(ws)
    with ws.connect() as cx:
        if not _has_tables(cx):
            return _empty_report()
        if leaving:
            ensure_owner(cx, me)
        pin_owner(cx, me)
        ctx = _Ctx(ws, cx, me)
        ctx.applying = apply
        if ctx.owner is None:
            return ctx.report
        _answer_refused(ctx)
        if ctx.is_owner:
            ctx.restamp_decisions()
            ctx.restamp()
            ctx.restamp_roles()
        if ctx.is_owner and apply and accept_adds(ws):
            for p in sorted(ctx.props.values(), key=lambda p: p["id"]):  # (no clock decides whose details count)
                # only a proposal no one has answered: a clash of two answers is never decided by itself (§4.5)
                if p["kind"] == "add" and p["by"] != me and p["id"] not in ctx.dec and ctx.state(p)[0] == "waiting" \
                        and p["doc"] not in ctx.K and p["doc"] not in ctx.removed_by_me:
                    _accept(ctx, p, auto=True)
        for doc in sorted(set(ctx.docs) | set(ctx.K) | set(ctx.voided)):
            _reconcile(ctx, doc, apply)
        _hold_looser(ctx)
        _note_roles(ctx)
        _note_clashes(ctx)
        ctx.save()
        _log(ctx)
        report = ctx.report
    if apply and report["fetch"]:
        report["fetched"] = _fetch(ws, report["fetch"])
        if report["fetched"]:  # what came back (from its archive) is as strict as the project at once (review, L1)
            again = settle(ws, apply=False)
            report["applied"] += again["applied"]
    if moves:
        report["moved"] = [move_now(ws, d) for d in report["moves"]]
    return report


def _prune(ws: Workspace) -> None:
    """Archives of removals older than 30 days go (removed.py; this computer's clock, which decides nothing between
    copies). A fault there never stops the look at this copy."""
    from . import removed

    try:
        removed.prune(ws)
    except (OSError, sqlite3.Error):
        import traceback

        traceback.print_exc()


def _era(p: dict, k: dict | None) -> bool:
    """Whether an addition was proposed since the project last had the document (or never had it): its `state_n` (and
    `state_by`) is the project's event of the document's state then."""
    det = p["detail"]
    if k is None:
        return not det.get("state_n")
    if (det.get("state_n") or 0) != k["state_n"]:
        return False
    return det.get("state_by") is None or det.get("state_by") == k["state_by"]


def _reconcile(ctx: _Ctx, doc: str, apply: bool) -> None:
    L, k, s = ctx.docs.get(doc), ctx.K.get(doc), ctx.S.get(doc) or {}
    me = ctx.me
    # ---- whether the document is one of the project's -------------------------------------------------------
    if L is not None and (k is None or k["state"] == "removed"):
        again = k is not None
        void = ctx.void(doc, "state")
        if again and void:
            ctx.follow(doc, "state")  # an addition answered both ways: it waits again, and stays (§4.5)
        elif again and not ctx.followed(doc, "state") and not ctx.mine_lost(doc, "state"):
            # the project removed it: not followed here yet
            if apply:
                # 0.18.1: whose word it is, in this copy: the removal's maker while they are the owner or a Co-owner
                # here; else (a former owner, a Co-owner made a Member since) the owner, whose rows keep it removed
                # (they wrote the project's documents again under their own place: `_Ctx.restamp`). Found by the
                # randomised roles test: a removal was noted in the name of someone who is a Member in this copy.
                maker = k["state_by"]
                by = maker if maker == ctx.owner or (ctx.R.get(maker) or {}).get("role") == "co" else ctx.owner
                who = ctx.names.get(by, "a colleague")
                if by == ctx.owner and maker == ctx.owner:
                    why = f"The owner ({who}) removed it from the project."
                elif by == ctx.owner:
                    why = (f"{ctx.names.get(maker, 'A former owner')} removed it from the project, and the owner "
                           f"({who}) keeps it removed.")
                else:
                    why = f"{who[0].upper() + who[1:]} (a Co-owner) removed it from the project."
                ctx.remove_here(doc, why, by, wish_of=maker if by == me else None)
                ctx.follow(doc, "state")
            return
        others = [p for p in ctx.about("add", doc) if p["by"] != me and _era(p, k)]
        mine = [p for p in ctx.mine("add", doc) if _era(p, k)]
        open_others = [p for p in others if ctx.state(p)[0] == "waiting"]
        closed_others = [p for p in others if ctx.state(p)[0] in ("declined", "taken_back")]
        if ctx.writes and not void and (again or not others or s.get("gone")) and not s.get("came_from") and \
                not any(ctx.state(p)[0] != "accepted" for p in mine):  # (gone: it left their copy, they added it again)
            ctx.put_from_here(doc, PARTS)  # this writer's own addition
            ctx.mark(doc, gone=None)
        elif mine or open_others:
            pass  # proposed: waiting for an answer (or declined: it stays in the proposer's copy only)
        elif closed_others and not s.get("gone"):  # declined, or taken back by who added it: it leaves this copy
            if apply:
                who = ctx.names.get(closed_others[0]["by"], "a colleague")
                d = ctx.dec.get(closed_others[0]["id"]) or {}
                ctx.remove_here(doc, f"{who} added it and it was not accepted into the project.", d.get("by") or
                                ctx.owner, cause="declined")
            return
        elif ctx.writes:
            pass  # it came from a colleague who has not proposed it (yet): a writer adds it by hand
        elif not s.get("came_from") or s.get("gone"):
            ctx.propose("add", doc, L["title"], (k["state_n"] if again else 0,),
                        {"sha1": (L["sha1"] or "").split("~")[0] or None, "text_fp": L["text_fp"], "reader": L["reader"],
                         "ai_access": _level(ctx.levels.get(doc)), "blocks": ctx.choices.get(doc) or {},
                         "state_n": k["state_n"] if again else 0, "state_by": k["state_by"] if again else None,
                         "again": again})
            ctx.mark(doc, gone=None)
        return
    if L is None:
        if s.get("came_from"):  # it came from a colleague once, and has left this copy since: added again, it is new
            ctx.mark(doc, came_from=None)
        if k is None:
            return
        if k["state"] == "removed":
            ctx.follow(doc, "state")
            return
        at = ctx.removed_by_me.get(doc)
        if ctx.void(doc, "state"):
            # its removal was accepted and answered both ways: the accept does not count, so it comes back, in the
            # accepter's copy too; the proposer keeps their own removal while the proposal waits (§4.5)
            proposer = [p for p in ctx.mine("remove", doc) if ctx.state(p)[0] == "waiting"]
            if at and proposer:
                ctx.follow(doc, "state")
            else:
                if apply:
                    ctx.cx.execute("DELETE FROM sync_removed WHERE kind='document' AND key=?", (doc,))
                    ctx.removed_by_me.pop(doc, None)
                    ctx.report["fetch"].append(doc)
                    ctx.report["notes"].append({"kind": "back", "doc": doc, "title": k["title"],
                                                "why": "answered both ways"})
                    ctx.follow(doc, "state")
                    ctx.mark(doc, gone=None)
                return
        if at and not ctx.followed(doc, "state") and ctx.moved_on(doc, "state") and \
                all(removal_spent(k, q["id"]) for q in ctx.mine("remove", doc) if q["detail"].get("removed_at") == at):
            # this person's removal is spent: the project went on since (took the document out and in again, or kept
            # it at the same time): it comes back here as to every copy
            if not apply:
                return
            ctx.cx.execute("DELETE FROM sync_removed WHERE kind='document' AND key=? AND person_id=?", (doc, me))
            ctx.removed_by_me.pop(doc, None)
            at = None
        if at:  # this copy's person removed it
            mine = [p for p in ctx.mine("remove", doc) if p["detail"].get("removed_at") == at]
            if ctx.writes and not any(ctx.state(p)[0] != "accepted" for p in mine):
                if apply or ctx.followed(doc, "state") or ctx.ev(doc, "state") is None or ctx.mine_lost(doc, "state"):
                    ctx.put(doc, ("state",), state="removed")
                    ctx.follow(doc, "state")
            elif not ctx.writes and not mine:
                ctx.propose("remove", doc, k["title"], (at,), {"removed_at": at, "state_n": k["state_n"],
                                                               "state_by": k["state_by"]})
        elif not ctx.followed(doc, "state") and not ctx.mine_lost(doc, "state"):
            # one of the project's documents that is not here
            if apply:
                ctx.cx.execute("DELETE FROM sync_removed WHERE kind='document' AND key=? AND person_id != ?", (doc, me))
                ctx.report["fetch"].append(doc)
                ctx.follow(doc, "state")
                ctx.mark(doc, gone=None)
        return
    # ---- one of the project's documents, held here ----------------------------------------------------------
    ctx.follow(doc, "state")
    ctx.mark(doc, gone=None)
    _reading(ctx, doc, L, k, s, apply)
    _ai(ctx, doc, k, s, apply)
    _blocks(ctx, doc, L, s, apply)


def _reading(ctx: _Ctx, doc: str, L: dict, k: dict, s: dict, apply: bool) -> None:
    me = ctx.me
    if L["text_fp"] == k["text_fp"] or L["reader"] == (k["reader"] or 1):
        ctx.follow(doc, "read")
    elif L["reader"] > (k["reader"] or 1):  # read again here
        held_for = s.get("read_from")
        # a reading in the zip this copy was made from (`adopt`), or made here for an accept that was then answered
        # both ways (`move_now`), is its proposer's: neither proposed again in this person's name nor written as theirs
        same = [p for p in ctx.about("reread", doc) if p["detail"].get("to_fp") == L["text_fp"]
                and p["by"] in (me, held_for)]
        mine = [p for p in same if p["by"] == me]
        if held_for and held_for != me:
            pass
        elif ctx.writes and not any(ctx.state(p)[0] != "accepted" for p in mine):
            k = ctx.put(doc, ("read",), text_fp=L["text_fp"], reader=L["reader"],
                        sha1=(L["sha1"] or "").split("~")[0] or None)
            ctx.follow(doc, "read")
        elif not ctx.writes and not same:
            ctx.propose("reread", doc, L["title"], (L["text_fp"],),
                        {"from_fp": k["text_fp"], "from_reader": k["reader"] or 1, "to_fp": L["text_fp"],
                         "to_reader": L["reader"]})
    elif (s.get("read_tried") or 0) != k["read_n"]:  # the project reads it with a newer reader: due here
        ctx.report["moves"].append(doc)


def _accepted_loosen(ctx: _Ctx, doc: str, k: dict) -> bool:
    """This person asked for the project's level themselves, and the project's AI event is the very one the accept of
    that proposal made (changed after review, H1: an old accepted proposal allows nothing later; that is an offer).
    Each accept does so once: the first time this copy follows its event, the accept is noted as used here
    (`LOOSEN_USED`, this copy's own), so a later row naming the same accept in its `via` (which its writer controls)
    is an offer too."""
    v = k["via"].get("ai")
    if not v:
        return False
    p = ctx.props.get(v["p"])
    d = ctx.dec.get(v["p"])
    used = f"{v['p']}|{v['d'][0]}|{v['d'][1]}"
    ok = bool(p and p["by"] == ctx.me and p["kind"] == "loosen" and p["doc"] == doc and d and
              d["verdict"] == "accept" and _level(p["detail"].get("to")) == k["ai_access"] and used not in ctx.loosen_used)
    if ok:
        ctx.loosen_used.add(used)
        ctx.loosen_used_new = True
    return ok


def _ai(ctx: _Ctx, doc: str, k: dict, s: dict, apply: bool) -> None:
    """Who may read the document with AI (§4.7): a stricter word of the project holds at once; a looser one is set
    here only by this person's own click (here, in their accepted proposal, or *Allow here*); otherwise it is offered.
    In a writer's copy what still differs is then this person's own change: a row."""
    lv, kv = _level(ctx.levels.get(doc)), k["ai_access"]
    # this person's own word since the event this copy followed: a level the project never had (one it had came here
    # with a colleague's file, as a stricter setting does, before this copy followed the event that made it)
    own_word = s.get("ai_level") is not None and lv != s.get("ai_level") and \
        lv not in {h[1] for h in k["ai_hist"]}
    if not ctx.followed(doc, "ai"):
        offer = _json(s.get("ai_offer"), {})
        ev = (k["ai_n"], k["ai_by"])
        if RANK[kv] > RANK[lv]:
            if ctx.void(doc, "ai"):  # (looked at first: a void event is never this person's own change)
                ctx.set_level(doc, kv, ": held at the project's setting (the proposal was answered both ways).",
                              {"from": "owner", "held": True})
            elif ctx.mine_lost(doc, "ai") and not ctx.writes:
                # this person's own looser setting, written when they could (a former owner, a demoted Co-owner): a
                # proposal now, held at the project's setting meanwhile
                hold_loosening(ctx.ws, ctx.cx, [doc], lv)
                ctx.set_level(doc, kv, ": held at the project's setting (a looser one is to be accepted first).",
                              {"from": "owner", "held": True})
            else:
                ctx.set_level(doc, kv, ", as the project set it (the stricter setting holds in every copy).",
                              {"from": "owner"})
            ctx.follow(doc, "ai")
        elif RANK[kv] < RANK[lv]:
            if s.get("ai_level") is None and lv in {h[1] for h in k["ai_hist"]}:
                # a document new here that came at a level the project had once: that is not this person's word, and
                # the project's looser one is offered (looked at again next time from this level)
                ctx.mark(doc, ai_level=lv)
                ctx.mark(doc, ai_offer=json.dumps({"n": ev[0], "by": ev[1], "level": kv, "state": "open", "at": now()},
                                                  sort_keys=True))
            elif s.get("ai_level") is None:
                ctx.follow(doc, "ai")  # a document new here: as it came (a stricter setting it came with holds)
            elif ctx.made_here(doc, "ai", (k["ai_n"], k["ai_by"])) and \
                    ctx.mine_rows[doc]["ai"]["e"] == (k["ai_n"], k["ai_by"]) and ctx.mine_rows[doc]["ai"]["v"] == kv \
                    and ctx.moved_on(doc, "ai"):
                # this copy's own row holds that very event at that level (review, C2: proven here, not by a row), and
                # the project knew the event this copy followed. 0.18.1: a row written again from the project's
                # (`_Ctx.restamp`: after taking the project back, or another owner of a place) can hold an old event
                # of this person's that this copy went on from, by their own stricter setting or a colleague's: that
                # is not their word now, and is offered (found by the randomised roles test, rule (b))
                ctx.set_level(doc, kv, ", as you set it for the project.", {"from": "owner"})
                ctx.follow(doc, "ai")
            elif _accepted_loosen(ctx, doc, k):
                ctx.set_level(doc, kv, ", as you proposed and the project accepted.", {"from": "proposal"})
                ctx.follow(doc, "ai")
            elif own_word:
                pass  # this person changed it here since: their own word
            elif not (offer.get("state") == "kept" and (offer.get("n"), offer.get("by")) == ev):
                want = {"n": ev[0], "by": ev[1], "level": kv, "state": "open",
                        "at": offer.get("at") if (offer.get("n"), offer.get("by")) == ev else now()}
                if offer != want:
                    ctx.mark(doc, ai_offer=json.dumps(want, sort_keys=True))
        else:
            ctx.follow(doc, "ai")
        lv = _level(ctx.levels.get(doc))
    off = _json((ctx.S.get(doc) or {}).get("ai_offer"), {})
    if off and (off.get("n"), off.get("by")) != (k["ai_n"], k["ai_by"]):
        ctx.mark(doc, ai_offer=None)  # the project's word changed since (or the accept that made it does not count)
    if ctx.writes and lv != kv and (ctx.followed(doc, "ai") or own_word):
        ctx.put(doc, ("ai",), ai_access=lv)
        ctx.follow(doc, "ai")


def _blocks(ctx: _Ctx, doc: str, L: dict, s: dict, apply: bool) -> None:
    """The blocks left out and restored: the project's word first (only with `apply`), with this person's own choices
    on top; then what differs is a row in a writer's copy, a proposal otherwise."""
    k = ctx.K[doc]
    mine_now = ctx.choices.get(doc) or {}
    if s.get("blocks_n") is None and s.get("blocks_json") is None and not mine_now:
        if k["blocks"] and apply:  # a document new here: read as the project reads it
            ctx.set_blocks(doc, k["blocks"])
        if apply or not k["blocks"]:
            ctx.follow(doc, "blocks")
        return
    if not ctx.followed(doc, "blocks") or s.get("blocks_json") is None:
        if not apply:
            return
        e = ctx.ev(doc, "blocks")
        # this copy's own event the project does not have, or lost at the same time: its own choices go on top of the
        # project's (against the project's choices it followed last from someone else, `blocks_base`); otherwise only
        # what this person changed since the event it followed
        lost = ctx.own_event(doc, "blocks") and (ctx.mine_lost(doc, "blocks") or
                                                 (e in k["top"]["blocks"] and e not in k["same"]["blocks"]))
        if lost and s.get("blocks_base") is not None:
            base = _clean_blocks(_json(s["blocks_base"], {}))
        elif s.get("blocks_json") is not None:
            base = _clean_blocks(_json(s["blocks_json"], {}))
        else:
            base = dict(k["blocks"])
        # what the project took of theirs (an accepted proposal) is the project's now, so its later word on those
        # passages holds here too
        taken: dict[str, Any] = {}
        for p in ctx.mine("blocks", doc):
            if ctx.state(p)[0] == "accepted":
                taken.update(p["detail"].get("delta") or {})
        own = {fp: v for fp, v in _delta(mine_now, base).items() if not (fp in taken and _same_choice(taken[fp], v))}
        if ctx.void(doc, "blocks"):  # the proposer's own choices stay on top while the proposal waits again
            for p in ctx.mine("blocks", doc):
                if (ctx.dec.get(p["id"]) or {}).get("clash"):
                    own = {**(p["detail"].get("delta") or {}), **own}
        ctx.set_blocks(doc, _apply_delta(k["blocks"], own))
        ctx.follow(doc, "blocks")
        mine_now = ctx.choices.get(doc) or {}
    if ctx.writes:
        # what this person proposed when they could not write and the project has not taken (it waits, was declined
        # or taken back) stays theirs: it becomes the project's by an answer to that proposal, never along with this
        # person's next change of the document
        own = _own_delta(ctx, doc, mine_now, k["blocks"])
        want = _apply_delta(k["blocks"], own)
        if own and want != k["blocks"]:
            ctx.put(doc, ("blocks",), blocks=want)
            ctx.follow(doc, "blocks")
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
                                                               "blocks_n": k["blocks_n"], "blocks_by": k["blocks_by"],
                                                               **_delta_words(delta)})


def _own_delta(ctx: _Ctx, doc: str, mine_now: dict, project: dict) -> dict:
    """A writer's own changes of a document's blocks against the project's: their copy's choices, without what they
    proposed of them when they could not write and the project has not taken."""
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
    """In a Member's copy no document is open to more AI than the project accepted (a project default made looser, a
    setting changed some other way): it is held at the project's setting."""
    if ctx.writes:
        return
    for doc, L in ctx.docs.items():
        k = ctx.K.get(doc)
        if k is None or k["state"] != "in" or not ctx.followed(doc, "ai"):
            continue
        if RANK[_level(ctx.levels.get(doc))] < RANK[k["ai_access"]]:
            ctx.set_level(doc, k["ai_access"], ": held at the project's setting (a looser one is to be accepted "
                                               "first).", {"from": "owner", "held": True})


def _fetch(ws: Workspace, docs: list[str]) -> list[str]:
    """Bring documents the project has back into this copy: from this copy's archive of removals first (removed.py),
    else from the shared folder."""
    from . import removed

    out, rest = [], []
    for d in docs:
        try:
            ok = removed.restore(ws, d)
        except Exception:  # noqa: BLE001 - the shared folder may still have it
            import traceback

            traceback.print_exc()
            ok = False
        (out if ok else rest).append(d)
    if not rest:
        return out
    try:
        from .sync import folder

        if folder.chosen(ws) is None:
            return out
        return out + folder.fetch_documents(ws, rest)
    except Exception:  # noqa: BLE001 - best effort: the document comes with a colleague's next round, or by hand
        import traceback

        traceback.print_exc()
        return out


# ---------------------------------------------------------------------------------------------
# rows a file brought in this copy's own name (§4.10), clashes and role changes in the research log
# ---------------------------------------------------------------------------------------------
REFUSED_KINDS = ("ownership", "roles", "proposals", "decisions", "canon", "event", "removal", "judgement")


def record_refused(cx: sqlite3.Connection, kind: str, key: str, row: dict, via: str | None, n: int | None) -> bool:
    """A row in this copy's own id that a colleague's file held and this copy does not (sync/owner_merge.py): it was
    not taken. Recorded once (again when a newer one comes), with one entry in the research log. True when new."""
    from . import researchlog

    what = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
    old = cx.execute("SELECT what_json, n FROM sync_refused WHERE kind=? AND key=?", (kind, key)).fetchone()
    if old and (old[0] == what or (old[1] or 0) > (n or 0)):
        return False
    cx.execute("INSERT OR REPLACE INTO sync_refused(kind, key, what_json, via, n, at, state) VALUES (?,?,?,?,?,?,?)",
               (kind, key, what, via, n, now(), "new"))
    who = _names_cx(cx).get(via or "", "A colleague")
    researchlog.record(cx, "owner", _refused_text(kind, row, who, _names_cx(cx)),
                       data={"refused": kind, "key": key, "via": via})
    return True


def _refused_text(kind: str, r: dict, who: str, names: dict[str, str]) -> str:
    if kind == "ownership":
        to = names.get(r.get("owner") or "", "a colleague")
        return (f"{who}'s file says you handed the project over to {to}. You did not: nothing was changed here."
                if r.get("kind") == "handover" else
                f"{who}'s file held a record of who owns the project in your name. It was not taken.")
    if kind == "canon":
        return f"{who}'s file held a change to {_q(r.get('title'))} in your name. It was not taken, and your own word " \
               "was sent again."
    if kind == "roles":
        return f"{who}'s file held a role for {names.get(r.get('person') or '', 'a colleague')} in your name. It " \
               "was not taken."
    if kind == "decisions":
        return f"{who}'s file held an answer to a proposal in your name. It was not taken."
    if kind == "event":
        return f"{who}'s file said a change to {_q(r.get('title'))} was yours. It is not taken for your own word here."
    if kind == "removal":
        return f"{who}'s file said you removed {_q(r.get('title'))}. You did not: nothing was removed here."
    if kind == "judgement":
        return f"{who}'s file held a judgement of an excerpt in your name. It was not taken: yours stays as it is."
    return f"{who}'s file held a proposal in your name ({what(r) if r.get('kind') in KINDS else 'a change'}). It " \
           "was not taken."


def _answer_refused(ctx: _Ctx) -> None:
    """Once per row refused (§4.10): this copy's own row again with a higher number, where the forged one would count,
    so third copies replace it: a document's row (every part numbered anew), a role, an answer."""
    owners = {r["seq"]: r["owner"] for r in ctx.chain}
    for kind, key, what_json in ctx.cx.execute("SELECT kind, key, what_json FROM sync_refused WHERE state='new' AND "
                                               "kind IN ('canon', 'roles', 'decisions')").fetchall():
        r = _json(what_json, {})
        n = _num(r.get("n")) or 0
        if kind == "canon":
            mine = ctx.cx.execute("SELECT n FROM canon WHERE doc=? AND by=?", (key, ctx.me)).fetchone()
            if (mine and (mine[0] or 0) > n) or _counts(r, owners, ctx.R) is None:
                continue
            if n > ctx.top_held + STEP:
                continue  # (no copy takes a row so far above what it holds: nothing to answer, review H2)
            ctx.n = max(ctx.n, n)
            extra = {p: [(_num(r.get(f"{p}_n")) or 0, r.get(f"{p}_by") or ctx.me)] for p in PARTS}
            if key in ctx.K:
                ctx.put(key, PARTS, extra=extra)
            else:
                ctx.put(key, PARTS, extra=extra, state="removed", title=r.get("title"))
        elif kind == "roles":
            seq = r.get("owner_seq")
            if owners.get(seq) != ctx.me:
                continue
            mine = ctx.cx.execute("SELECT n, role, grant, same_as FROM roles WHERE person=? AND by=?",
                                  (key, ctx.me)).fetchone()
            if (mine and (mine[0] or 0) > n) or n > _own_role_n(ctx.cx, ctx.me) + STEP:
                continue
            m = max(n, _own_role_n(ctx.cx, ctx.me)) + 1
            ctx.cx.execute("INSERT OR REPLACE INTO roles(person, by, owner_seq, n, role, grant, same_as, at) VALUES "
                           "(?,?,?,?,?,?,?,?)", (key, ctx.me, seq, m, mine[1] if mine else "member",
                                                 mine[2] if mine else None, mine[3] if mine else None, now()))
        else:
            if _counts(r, owners, ctx.R) is None:
                continue
            mine = ctx.cx.execute("SELECT n, verdict, reason, auto, knew_json FROM decisions WHERE proposal=? AND by=?",
                                  (key, ctx.me)).fetchone()
            if (mine and (mine[0] or 0) > n) or n > ctx.dec_n + STEP:
                continue
            ctx.dec_n = max(ctx.dec_n, n)
            if key.startswith("~restamped:"):
                # a copy of this owner's mark (forged, or an older one from a backup): never answered by an empty
                # row, which would stop every former owner's answer counting (review 3); this copy's own mark is
                # written again above it, or, when it has none yet, `restamp_decisions` writes it (after this)
                if mine:
                    ctx.cx.execute("INSERT OR REPLACE INTO decisions(proposal, by, owner_seq, verdict, reason, at, auto, "
                                   "n, grant, knew_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                   (key, ctx.me, int(key.split(":", 1)[1]) if key.split(":", 1)[1].isdigit() else ctx.seq,
                                    "withdrawn", "restamped",
                                    now(), 0, ctx.next_dec_n(), None, mine[4] or "[]"))
                    ctx.dec = _decisions(ctx.cx, ctx.chain, ctx.R)
                continue
            m = ctx.next_dec_n()
            if mine and mine[1] in ("accept", "decline"):
                knew = [tuple(x) for x in _json(mine[4], []) if isinstance(x, list) and len(x) == 2]
                ctx.write_decision(key, mine[1], mine[2], bool(mine[3]), m, knew)
            else:  # no answer of this person's: a row that counts for nothing replaces the forged one
                ctx.cx.execute("INSERT OR REPLACE INTO decisions(proposal, by, owner_seq, verdict, reason, at, auto, n, "
                               "grant, knew_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (key, ctx.me, ctx.seq, "withdrawn", None, now(), 0, m, ctx.grant, "[]"))
                ctx.dec = _decisions(ctx.cx, ctx.chain, ctx.R)


def refused(cx: sqlite3.Connection) -> list[dict]:
    """The rows a file brought under this copy's own id, still to be shown (`sync_refused`, state 'new'; §4.10):
    [{"kind", "key", "via", "n", "at", "what" (the row), "text"}]."""
    if not _has(cx, "sync_refused"):
        return []
    names = _names_cx(cx)
    out = []
    for kind, key, what_json, via, n, at in cx.execute("SELECT kind, key, what_json, via, n, at FROM sync_refused "
                                                       "WHERE state='new' AND kind != 'clash' ORDER BY at, kind, key"):
        r = _json(what_json, {})
        out.append({"kind": kind, "key": key, "via": via, "n": n, "at": at, "what": r,
                    "text": _refused_text(kind, r, names.get(via or "", "A colleague"), names)
                    if kind in REFUSED_KINDS else f"{names.get(via or '', 'A colleague')}'s file held work in your "
                                                  "name. It was not taken."})
    return out


def dismiss_refused(ws: Workspace, kind: str, key: str) -> dict:
    """Mark a refused row as seen ('dismissed'; §4.10). `kind` "notice": dismiss an info notice (`view()["notices"]`,
    `key` its id). Returns the view."""
    with ws.connect() as cx:
        if kind == "notice":
            have = _meta(cx, NOTICES, [])
            left = [x for x in have if not (isinstance(x, dict) and x.get("id") == key)]
            if len(left) == len(have):
                raise KeyError(key)
            _set_meta(cx, NOTICES, left)
        else:
            cur = cx.execute("UPDATE sync_refused SET state='dismissed' WHERE kind=? AND key=? AND state='new'",
                             (kind, key))
            if not cur.rowcount:
                raise KeyError(f"{kind}/{key}")
    return view(ws)


def _note_roles(ctx: _Ctx) -> None:
    """A role changed elsewhere: an info notice, once (§5.1)."""
    now_roles = {p: r["role"] for p, r in ctx.R.items() if r["role"] in ("co", "member")}
    row = ctx.cx.execute("SELECT value FROM meta WHERE key=?", (ROLES_SEEN,)).fetchone()
    seen = _json(row[0], {}) if row else None
    if seen == now_roles:
        return
    if isinstance(seen, dict):
        for p in sorted(set(now_roles) | set(seen)):
            was, is_ = seen.get(p, "member"), now_roles.get(p, "member")
            if was == is_ or (was == "owner" or is_ == "owner"):
                continue
            by = (ctx.R.get(p) or {}).get("by")
            if by == ctx.me:
                continue
            who = "you" if p == ctx.me else ctx.names.get(p, "a colleague")
            text = f"{ctx.names.get(by or '', 'The owner')} made {who} a " + \
                ("Co-owner." if is_ == "co" else "Member again.")
            _notice(ctx.cx, "role", text, f"role|{p}|{is_}|{(ctx.R.get(p) or {}).get('n')}")
    _set_meta(ctx.cx, ROLES_SEEN, now_roles)


_PART_WORDS = {"state": "kept or removed", "read": "read", "ai": "changed who may read", "blocks": "changed which "
               "passages are read of"}


def _note_clashes(ctx: _Ctx) -> None:
    """Each clash once in the research log (§4.4, I7): a part changed at the same time (in a writer's copy), a proposal
    answered both ways (in every copy). `sync_refused` kind "clash" keeps what was logged."""
    from . import researchlog

    have = {r[0] for r in ctx.cx.execute("SELECT key FROM sync_refused WHERE kind='clash'")}
    for c in _clash_list(ctx.K, ctx.dec, ctx.props):
        if c["id"] in have or (c["kind"] == "part" and not ctx.writes):
            continue
        names = " and ".join(ctx.names.get(p, "a colleague") if p != ctx.me else "you" for p in c["people"])
        if c["kind"] == "answer":
            acc = ", ".join(ctx.names.get(p, "a colleague") if p != ctx.me else "you" for p in c["accepted"])
            dec = ", ".join(ctx.names.get(p, "a colleague") if p != ctx.me else "you" for p in c["declined"])
            if c.get("demoted"):
                gone = ", ".join(ctx.names.get(p, "a colleague") for p in c["demoted"])
                text = (f"{c['what'][0].upper() + c['what'][1:]} was answered both ways, and {gone} is a Member now: "
                        f"that answer no longer counts. Nothing was decided by it; it waits to be decided again.")
            else:
                text = (f"{c['what'][0].upper() + c['what'][1:]} was answered both ways: {acc} accepted, {dec} "
                        "declined, neither knowing the other's answer. Neither counts; it waits to be decided again.")
            researchlog.record(ctx.cx, "proposal", text, "document", c["doc"], c["title"],
                               data={"proposal": c["proposal"], "clash": True})
        else:
            text = f"{names} {_PART_WORDS[c['part']]} {_q(c['title'])} at the same time."
            researchlog.record(ctx.cx, "owner", text, "document", c["doc"], c["title"],
                               data={"clash": c["id"], "part": c["part"]})
        ctx.cx.execute("INSERT OR REPLACE INTO sync_refused(kind, key, what_json, via, n, at, state) VALUES "
                       "(?,?,?,?,?,?,?)", ("clash", c["id"], json.dumps(c, sort_keys=True, default=str), None, None,
                                           now(), "logged"))


def decide_again(ws: Workspace, clash_id: str) -> dict:
    """*Leave it so*, for a part changed at the same time: the part is written again as it is, knowing every event of
    the clash, so the notice goes in every copy. A proposal answered both ways is decided by `accept` or `decline`.
    Returns the view."""
    from . import researchlog

    with ws.connect() as cx:
        ctx = _Ctx(ws, cx, people.me())
        if not ctx.writes:
            raise NotAllowed("Only the owner or a Co-owner can decide this.")
        c = next((x for x in _clash_list(ctx.K, ctx.dec, ctx.props) if x["id"] == clash_id), None)
        if c is None:
            raise KeyError(clash_id)
        if c["kind"] == "answer":
            raise ValueError("A proposal answered both ways is decided by accepting or declining it again.")
        ctx.put(c["doc"], (c["part"],))
        if c["doc"] in ctx.docs:
            ctx.follow(c["doc"], c["part"])
        researchlog.record(cx, "owner", f"Left {_q(c['title'])} as it is after changes made at the same time.",
                           "document", c["doc"], c["title"], data={"clash": clash_id, "part": c["part"]})
        ctx.save()
    settle(ws, apply=True)
    return view(ws)


def offers(cx: sqlite3.Connection) -> list[dict]:
    """Looser AI settings the project has and this copy has not set (§4.7): [{"doc", "title", "from", "to", "by"}]."""
    if not _has(cx, "canon_seen"):
        return []
    from .access import levels as access_levels

    out = []
    here = {r[0]: r[1] for r in cx.execute("SELECT doc_id, title FROM documents")}
    levels = None
    for doc, off in cx.execute("SELECT doc, ai_offer FROM canon_seen WHERE ai_offer IS NOT NULL ORDER BY doc"):
        o = _json(off, {})
        if o.get("state") != "open" or doc not in here:
            continue
        if levels is None:
            levels = access_levels(cx, None, budget=False)
        out.append({"doc": doc, "title": here[doc], "from": _level(levels.get(doc)), "to": _level(o.get("level")),
                    "by": o.get("by")})
    return out


def answer_loosening(ws: Workspace, docs: list[str] | None, allow: bool) -> dict:
    """*Allow here* (`allow`) or *Keep it stricter here* the looser AI settings offered for `docs` (None: all). Allowed:
    the document is set as the project has it, and followed. Kept: not asked again for that change. Returns the view."""
    with ws.connect() as cx:
        ctx = _Ctx(ws, cx, people.me())
        for doc, s in sorted(ctx.S.items()):
            o = _json(s.get("ai_offer"), {})
            if o.get("state") != "open" or (docs is not None and doc not in docs) or doc not in ctx.docs:
                continue
            k = ctx.K.get(doc)
            if allow and k is not None and (k["ai_n"], k["ai_by"]) == (o.get("n"), o.get("by")) and \
                    k["ai_access"] == o.get("level"):
                ctx.set_level(doc, k["ai_access"], ", as the project has it: you allowed it here.",
                              {"from": "owner", "allowed": True})
                ctx.follow(doc, "ai")
            elif allow:  # the project changed it since: the next look offers what it has now
                ctx.mark(doc, ai_offer=None)
            else:
                ctx.mark(doc, ai_offer=json.dumps({**o, "state": "kept"}, sort_keys=True))
        ctx.save()
    return view(ws)


_WHAT = {"add": "adding {t}", "remove": "removing {t} from the project",
         "reread": "reading {t} again with the new reader", "blocks": "changing which passages of {t} are read",
         "loosen": "letting more AI read {t}"}


def what(p: dict) -> str:
    """A proposal in a few words: "removing “Annual report 2024” from the project"."""
    out = _WHAT[p["kind"]].format(t=_q(p.get("title")))
    det = p.get("detail") or _json(p.get("detail_json"), {})
    if p["kind"] == "blocks" and isinstance(det, dict) and det.get("role") and \
            not any(det.get(x) for x in ("left_out", "restored", "undone", "bounds")):
        out = (f"marking {_q(p.get('title'))} as evidence again" if det["role"] == "evidence" else
               f"marking {_q(p.get('title'))} as a working document (never a source)" if det["role"] == "working"
               else f"marking {_q(p.get('title'))} as {det['role']} (the lens, not the evidence)")   # (N3: working)
    elif p["kind"] == "blocks" and isinstance(det, dict) and "nonscientific" in det and \
            not any(det.get(x) for x in ("left_out", "restored", "undone", "bounds")):  # 0.18.6
        out = (f"marking {_q(p.get('title'))} as non-scientific (its judgements no longer count in answers)"
               if det["nonscientific"] else f"counting {_q(p.get('title'))} as scientific again")
    if p["kind"] == "loosen":
        from .researchlog import access_words

        out += f" ({access_words(_level((p.get('detail') or _json(p.get('detail_json'), {})).get('to')))})"
    return out


def _note_claimed(ctx: _Ctx, by_kind: dict[str, list[dict]]) -> None:
    """0.18.1 (roadmap L, after 0.17.0): when a colleague became the owner of a project that had none (*Become the
    owner*), what this person had removed or left out in their own copy before is their proposal now, all at once. Say
    so once, in the Team tab, so the proposals do not come unexplained (the dialog said so to the one who claimed)."""
    first = ctx.chain[0] if ctx.chain else None
    if not first or first["kind"] != "claim" or first["owner"] == ctx.me:
        return
    key = f"claimed:{first['seq']}:{first['by']}"
    noted = _meta(ctx.cx, CLAIM_NOTED, [])
    if key in noted or not getattr(ctx, "applying", False):
        return
    # decided once, in the first look at this copy that applies what the claim brings (the round, or the zip, that
    # brought it): every earlier removal and Leave out of this person's is proposed in that look; a change made
    # afterwards is a proposal like any other, without the notice (review 7)
    _set_meta(ctx.cx, CLAIM_NOTED, (list(noted) + [key])[-20:])
    removed, left_out = len(by_kind.get("remove", [])), len(by_kind.get("blocks", []))
    if not removed and not left_out:
        return
    who = ctx.names.get(first["owner"], "A colleague")
    parts = ([f"{removed} {'document' if removed == 1 else 'documents'} you removed"] if removed else []) + \
        ([f"what you left out of {left_out} {'document' if left_out == 1 else 'documents'}"] if left_out else [])
    _notice(ctx.cx, "claimed", f"{who} became the owner of this project. {' and '.join(parts).capitalize()} in your "
                               f"copy before it had an owner {'is' if removed + left_out == 1 else 'are'} now your "
                               f"{'proposal' if removed + left_out == 1 else 'proposals'} to {who}. Your copy keeps "
                               "them as they are until they are answered; take back any you no longer want.",
            key)


def _log(ctx: _Ctx) -> None:
    """The research log: what this copy proposed now, and what the owner's copy accepted at once."""
    from . import researchlog

    by_kind: dict[str, list[dict]] = {}
    for p in ctx.new:
        by_kind.setdefault(p["kind"], []).append(p)
    _note_claimed(ctx, by_kind)
    for kind, ps in by_kind.items():
        if len(ps) == 1:
            p = ps[0]
            researchlog.record(ctx.cx, "proposal", f"Proposed to the owner: {what(p)}. It waits for an answer"
                                                   + ("; until then it stays as it was here." if kind == "loosen"
                                                      else "; your copy keeps the change."),
                               "document", p["doc"], p["title"], data={"proposal": p["id"], "kind": kind})
        else:
            names = ", ".join(_q(p["title"], 50) for p in ps[:3]) + (" and more" if len(ps) > 3 else "")
            researchlog.record(ctx.cx, "proposal", f"Proposed to the owner: {_WHAT[kind].format(t=f'{len(ps)} documents')} "
                                                   f"({names}). They wait for an answer.",
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
# the Owner's and the Co-owners' word, and the proposer's
# ---------------------------------------------------------------------------------------------
def _decide(ctx: _Ctx, p: dict, verdict: str, reason: str | None, auto: bool, n: int | None = None) -> None:
    """An answer to `p`, knowing every answer that counts now (so it alone is the top, §4.5)."""
    d = ctx.dec.get(p["id"])
    knew = {(b, m) for b, m in (d["top"] | {(r["by"], r["n"]) for r in d["live"].values()} |
                                set(d.get("markers") or ()))} if d else set()
    knew = {x for x in knew if x[0] != ctx.me or x in set((d or {}).get("markers") or ())}
    ctx.write_decision(p["id"], verdict, reason, auto, n if n is not None else ctx.next_dec_n(), knew)


def _was(k: dict | None, part: str) -> Any:
    if k is None:
        return None
    return {"state": k["state"], "ai": k["ai_access"], "blocks": k["blocks"],
            "read": {"text_fp": k["text_fp"], "reader": k["reader"], "sha1": k["sha1"]}}[part]


def _accept(ctx: _Ctx, p: dict, auto: bool = False, reason: str | None = None) -> None:
    """Accept `p` in this writer's copy: the change becomes the project's, each part it numbers anew with a "via" entry
    naming this answer (§4.5: the change counts only while the answer does)."""
    doc, det, kind = p["doc"], p["detail"], p["kind"]
    L, k = ctx.docs.get(doc), ctx.K.get(doc)
    dn = ctx.next_dec_n()

    def via(*parts: str) -> dict:
        return {part: {"p": p["id"], "d": [ctx.me, dn], "was": _was(k, part),
                       "was_n": k[f"{part}_n"] if k else None, "was_by": k[f"{part}_by"] if k else None}
                for part in parts}

    if kind == "add":
        if L is not None:
            if not ctx.choices.get(doc) and det.get("blocks"):
                ctx.set_blocks(doc, _clean_blocks(det["blocks"]), by=p["by"])
            ctx.put_from_here(doc, PARTS, via=via(*PARTS))
            ctx.mark(doc, gone=None, came_from=None)
        else:  # not here (kept out of the shared folder, or removed here once): one of the project's all the same
            ctx.cx.execute("DELETE FROM sync_removed WHERE kind='document' AND key=?", (doc,))
            ctx.removed_by_me.pop(doc, None)
            ctx.put(doc, PARTS, via=via(*PARTS), state="in", sha1=det.get("sha1"), title=p["title"],
                    text_fp=det.get("text_fp"), reader=det.get("reader"), ai_access=_level(det.get("ai_access")),
                    blocks=_clean_blocks(det.get("blocks") or {}))
            ctx.mark(doc, gone=None, came_from=None)
            ctx.report["fetch"].append(doc)
    elif kind == "remove":
        if L is not None:
            ctx.remove_here(doc, f"Accepted {ctx.names.get(p['by'], 'a colleague')}'s proposal to remove it from the "
                                 "project." + (f" {reason.strip()}" if reason and reason.strip() else ""), ctx.me)
        ctx.put(doc, ("state",), via=via("state"), state="removed")
        ctx.follow(doc, "state")
    elif kind == "reread":
        ctx.put(doc, ("read",), via=via("read"), text_fp=det.get("to_fp"), reader=det.get("to_reader"))
    elif kind == "blocks":  # the project's choices with the proposal's on top (not all of this copy's)
        if L is not None:
            ctx.set_blocks(doc, _apply_delta(ctx.choices.get(doc) or {}, det.get("delta") or {}), by=p["by"])
        ctx.put(doc, ("blocks",), via=via("blocks"), blocks=_apply_delta(k["blocks"], det.get("delta") or {}))
        if L is not None:
            ctx.follow(doc, "blocks")
    elif kind == "loosen":
        to = _level(det.get("to"))
        if L is not None:
            ctx.set_level(doc, to, f", as {ctx.names.get(p['by'], 'a colleague')} proposed and it was accepted.",
                          {"from": "proposal", "proposal": p["id"]})
        ctx.put(doc, ("ai",), via=via("ai"), ai_access=to)
        if L is not None:
            ctx.follow(doc, "ai")
    _decide(ctx, p, "accept", reason, auto, dn)
    if auto:
        ctx.report["accepted"].append(p["id"])


def _owner_ctx(ws: Workspace, cx: sqlite3.Connection, pid: str) -> tuple[_Ctx, dict]:
    ctx = _Ctx(ws, cx, people.me())
    p = ctx.props.get(pid)
    if p is None:
        raise KeyError(pid)
    if not ctx.writes:
        raise NotAllowed("Only the owner or a Co-owner can accept or decline a proposal.")
    st, why = ctx.state(p)
    if st != "waiting":
        raise ValueError(f"This proposal no longer waits for an answer ({why or st.replace('_', ' ')}).")
    return ctx, p


def accept(ws: Workspace, pid: str, reason: str | None = None) -> dict:
    """The Owner or a Co-owner accepts a proposal: the change is made in this copy (a new reading through `moves_due`)
    and becomes the project's, so it reaches every copy. Also the way to decide again a proposal answered both ways."""
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
    """The Owner or a Co-owner declines a proposal: nothing changes in the project; the proposer's copy keeps its
    change (a document they added stays in their copy only, and leaves the others)."""
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
    """The proposer takes a waiting proposal back: no one is asked any more. Their copy keeps the change."""
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
    written: in a Member's copy of a project with an owner, a setting looser than the project's is not made; it is
    proposed. Returns {doc id: the setting the document gets here instead} (the project's, when this copy's was
    stricter still) for the documents held. Nothing in an Owner's or a Co-owner's copy."""
    from . import access, researchlog

    me = people.me()
    ch = chain(cx)
    if not ch or may_write(cx, me):
        return {}
    R = roles(cx, ch)
    dec = _decisions(cx, ch, R)
    K = canon(cx, ch, R, dec)
    props = _proposals(cx)
    want = level or access._default_from_cx(cx)
    held: dict[str, str] = {}
    new = []
    for doc in doc_ids:
        k = K.get(doc)
        if k is None or k["state"] != "in" or RANK[_level(want)] >= RANK[k["ai_access"]]:
            continue
        held[doc] = k["ai_access"]
        # the same again while it waits proposes nothing more; asked again after it was declined (or it was taken
        # back), it is a new proposal
        pid, i = _id("loosen", doc, me, want, k["ai_n"]), 0
        while pid in props and state_of(props[pid], K, dec)[0] in ("declined", "taken_back"):
            i += 1
            pid = _id("loosen", doc, me, want, k["ai_n"], i)
        if pid in props or cx.execute("SELECT 1 FROM proposals WHERE id=?", (pid,)).fetchone():
            continue
        title = (cx.execute("SELECT title FROM documents WHERE doc_id=?", (doc,)).fetchone() or [k["title"]])[0]
        det = {"from": k["ai_access"], "to": want, "ai_n": k["ai_n"], "ai_by": k["ai_by"]}
        cx.execute("INSERT INTO proposals(id, kind, doc, title, by, at, detail_json, taken_back_at) VALUES "
                   "(?,?,?,?,?,?,?,NULL)", (pid, "loosen", doc, title, me, now(), json.dumps(det)))
        new.append({"id": pid, "kind": "loosen", "doc": doc, "title": title, "detail": det})
    if len(new) == 1:
        p = new[0]
        researchlog.record(cx, "proposal", f"Proposed to the owner: {what(p)}. Until it is accepted, it is as the "
                                           f"project has it ({researchlog.access_words(_level(p['detail']['from']))}).",
                           "document", p["doc"], p["title"], data={"proposal": p["id"], "kind": "loosen"})
    elif new:  # one entry for one change of several documents
        names = ", ".join(_q(p["title"], 50) for p in new[:3]) + (" and more" if len(new) > 3 else "")
        researchlog.record(cx, "proposal", f"Proposed to the owner: letting more AI read {len(new)} documents ({names}: "
                                           f"{researchlog.access_words(_level(want), True)}). Until it is accepted, "
                                           "each is as the project has it.",
                           "documents", None, None, data={"proposals": [p["id"] for p in new], "kind": "loosen"})
    return held


# ---------------------------------------------------------------------------------------------
# a new reading the project accepted, made here
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
    accepted, still to be made here), tried or not."""
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
    (`force`: results without a place are kept as records, as when a person moves it from its own page). A reading made
    because of an accept is held as its proposer's (`canon_seen.read_from`): should that accept stop counting, this
    copy keeps the reading and neither writes nor proposes it as its own (§4.5). Returns {"doc", "title", "moved",
    "reason", "not_placed"}."""
    from . import reread

    title = ws.scalar("SELECT title FROM documents WHERE doc_id=?", (doc,))
    out = {"doc": doc, "title": title, "moved": False, "reason": None, "not_placed": 0}
    cx = ws._conn()
    k = canon(cx).get(doc)
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
        v = k["via"].get("read")
        if out["moved"] and v:
            p = cx.execute("SELECT by FROM proposals WHERE id=?", (v["p"],)).fetchone()
            if p and p[0]:
                cx.execute("UPDATE canon_seen SET read_from=? WHERE doc=?", (p[0], doc))
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


def _removed_listing(ws: Workspace) -> list[dict]:
    from . import removed

    return removed.listing(ws)


def made_here(cx: sqlite3.Connection, me: str, doc: str, part: str, e: tuple | None) -> bool:
    """Whether this copy made the event `e` of a document's part: its own row of the document has it, as its event or
    in its list (review, C2: a row of someone else's saying an event is this person's proves nothing)."""
    if not e or e[1] != me:
        return False
    r = cx.execute("SELECT * FROM canon WHERE doc=? AND by=?", (doc, me)).fetchone()
    if r is None:
        return False
    cols = [c[0] for c in cx.execute("SELECT * FROM canon LIMIT 0").description]
    row = _parse_row(dict(dict(zip(cols, r)), tier=None))
    return tuple(e) == row[part]["e"] or tuple(e) in row[part]["knew"]


def note_format(cx: sqlite3.Connection, person: str, fmt: int) -> None:
    """The sync format of a colleague's last file (sync/owner_merge.py): a Co-owner on format 3 or older cannot act as
    one (the people list says so)."""
    have = _meta(cx, FORMATS, {})
    if isinstance(have, dict) and have.get(person) != fmt and people.ID_RE.fullmatch(person or ""):
        have[person] = int(fmt)
        _set_meta(cx, FORMATS, have)


def view(ws: Workspace, light: bool = False) -> dict:
    """Everything the page shows of L2 and the roles, without changing anything (`light`: not whether the owner has
    left, which looks at the shared folder):
    {"owner": {"id", "name", "me"} | None, "me", "is_owner", "since", "how" (made | claim | handover | takeover),
     "role" ("owner" | "co" | "member"), "can_write" (this person's changes are the project's), "can_set_roles",
     "can_claim", "can_take_over": words why | None, "accept_adds" (the owner's setting, in the owner's copy),
     "people": [{"id", "name", "me", "owner", "role", "same_as", "needs_update"}],
     "questions": [owner_questions, with "owner_name", "by_name", "now_name"]],
     "offers": [offers], "removed": [removed.listing], "clashes": [clashes, for the Owner and Co-owners],
     "refused": [refused], "notices": [{"id", "kind" ("handover" | "role"), "text", "at"}],
     "proposals": [{"id", "kind", "severity", "doc", "title", "what" (in words), "by": {..}, "at", "state", "note",
                    "reason", "decided_by", "decided_at", "auto", "mine", "can_decide", "can_take_back", "here" (the
                    document is in this copy), "conflicts": [ids of other waiting proposals for the document],
                    "clash": {"accepted": [people], "declined": [people]} | None, "detail": {...}}] newest first,
     "waiting": how many wait for this person's word (proposals to answer in a writer's copy, this person's own
                otherwise; questions, offers, refused rows),
     "to_apply": [{"doc", "title", "kind": "reread", "note", "can_force"}],
     "documents": {doc id: {"state": "proposed" | "declined" | "waiting", "text"}}}"""
    me = people.me()
    cx = ws._conn()
    names = people.names(ws)
    out: dict[str, Any] = {"owner": None, "me": me, "is_owner": False, "since": None, "how": None, "role": "member",
                           "can_write": True, "can_set_roles": False, "can_claim": False, "can_take_over": None,
                           "accept_adds": accept_adds(ws), "people": [], "questions": [], "offers": [], "removed": [],
                           "clashes": [], "refused": [], "notices": [], "proposals": [], "waiting": 0, "to_apply": [],
                           "documents": {}}
    if not _has_tables(cx):
        return out
    ch = chain(cx)
    known = [r[0] for r in cx.execute("SELECT person_id FROM people ORDER BY name") if r[0] != people.UNKNOWN]
    own = ch[-1]["owner"] if ch else None
    R = roles(cx, ch) if ch else {}
    fmts = _meta(cx, FORMATS, {})
    fmts = fmts if isinstance(fmts, dict) else {}
    for pid in dict.fromkeys([me] + known + ([own] if own else [])):
        r = R.get(pid) or {}
        role = r.get("role") or "member"
        out["people"].append({**_person(names, me, pid), "owner": pid == own, "role": role,
                              "same_as": r.get("same_as"),
                              "needs_update": role == "co" and isinstance(fmts.get(pid), int) and fmts[pid] < 4})
    out["questions"] = [{**q, "owner_name": names.get(q["owner"], "a colleague"),
                         "by_name": names.get(q["by"], "a colleague"),
                         "now_name": names.get(q["now"], "a colleague") if q["now"] else None}
                        for q in owner_questions(cx)]
    later = _meta(cx, LATER, {})
    later = set((later.get(me) or []) if isinstance(later, dict) else [])
    out["later"] = [q["id"] for q in out["questions"] if q["id"] in later]
    out["notices"] = [x for x in _meta(cx, NOTICES, []) if isinstance(x, dict)]
    out["refused"] = refused(cx)
    out["removed"] = _removed_listing(ws)
    out["waiting"] = len(out["questions"]) + len(out["refused"])
    if not ch:
        from . import sharing

        if sharing.exchanged(cx, me):
            out["can_claim"] = not _records(cx).get(1)
        else:  # never exchanged: its maker's, written down when it first leaves this computer
            out.update(owner=_person(names, me, me), is_owner=True, how="made", role="owner", can_set_roles=True)
            out["people"][0].update(owner=True, role="owner")
        return out
    writes = R.get(me, {}).get("role") in ("owner", "co")
    out.update(owner=_person(names, me, own), is_owner=own == me, since=ch[-1]["at"], how=ch[-1]["kind"],
               role=(R.get(me) or {}).get("role") or "member", can_write=writes, can_set_roles=own == me)
    if own != me and not light:
        out["can_take_over"] = owner_left(ws, cx, ch)
    dec = _decisions(cx, ch, R)
    K = canon(cx, ch, R, dec)
    props = _proposals(cx)
    out["offers"] = offers(cx)
    if writes:
        out["clashes"] = [{**c, "people": [_person(names, me, x) for x in c["people"]],
                           **({"accepted": [_person(names, me, x) for x in c["accepted"]],
                               "declined": [_person(names, me, x) for x in c["declined"]]}
                              if c["kind"] == "answer" else {})}
                          for c in _clash_list(K, dec, props)]
    out["waiting"] += len(out["offers"])
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
        clash = d is not None and d["clash"] and st == "waiting"
        det = {c: v for c, v in p["detail"].items() if c not in ("blocks", "delta", "state_by", "ai_by", "blocks_by",
                                                                  "read_by")}
        item = {"id": p["id"], "kind": p["kind"], "severity": SEVERITY[p["kind"]], "doc": p["doc"],
                "title": here.get(p["doc"]) or p["title"] or "a document", "what": what(p),
                "by": _person(names, me, p["by"]), "at": p["at"], "state": st, "note": note,
                "reason": d["reason"] if d and d["verdict"] else None,
                "decided_by": _person(names, me, d["by"]) if d and d["verdict"] else None,
                "decided_at": d["at"] if d and d["verdict"] else None, "auto": bool(d and d["verdict"] and d["auto"]),
                "mine": p["by"] == me, "can_decide": writes and st == "waiting",
                "can_take_back": p["by"] == me and st == "waiting", "here": p["doc"] in here,
                "conflicts": [i for i in waiting_by_doc.get(p["doc"], []) if i != p["id"]] if st == "waiting" else [],
                "clash": {"accepted": [_person(names, me, x) for x in d["accepted"]],
                          "declined": [_person(names, me, x) for x in d["declined"]]} if clash else None,
                "detail": det}
        out["proposals"].append(item)
        if st == "waiting" and (writes or p["by"] == me):
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
    for r in _rows(cx, "SELECT doc, read_tried, read_note, read_from FROM canon_seen WHERE read_note IS NOT NULL OR "
                       "read_from IS NOT NULL"):
        k = K.get(r["doc"])
        if k and k["state"] == "in" and r["doc"] in here:
            reader = cx.execute("SELECT COALESCE(reader, 1) FROM documents WHERE doc_id=?", (r["doc"],)).fetchone()[0]
            if reader < (k["reader"] or 1) and r["read_note"] is not None:
                out["to_apply"].append({"doc": r["doc"], "title": here[r["doc"]], "kind": "reread",
                                        "note": r["read_note"], "can_force": r["read_tried"] == k["read_n"]})
            elif reader > (k["reader"] or 1) and r["read_from"] and r["read_from"] != me and \
                    (k["void"]["read"] or any((dec.get(p["id"]) or {}).get("clash") for p in props.values()
                                              if p["doc"] == r["doc"] and p["kind"] == "reread")):
                out["documents"].setdefault(r["doc"], {"state": "waiting", "text": "Read with the newer reader here; "
                                                                                   "the project decides again."})
    return out
