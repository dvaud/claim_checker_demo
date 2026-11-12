"""The research log (0.16, roadmap F4): a dated record of what was decided in a project.

The app writes an entry by itself when something is decided: documents added or removed, who may read a document
with AI, a document read again with the new reader, a hypothesis checked or a check removed, themes found, removed,
renamed or merged, a codebook made, changed, moved or removed, a note used as evidence, an earlier version restored,
a colleague's work brought in. A person adds entries of their own (field notes, decisions, reasons), and can say *why*
next to any entry of theirs. It is a record for reflexivity in qualitative work and an audit trail: the app's entries
cannot be removed, only a person's own entries can.

Each entry names who made it (people.py), and what it is about (`subject_kind`, `subject_id`, `title` as it was then,
so the entry still reads well once the thing is gone). An entry about a change keeps the state before it
(`version_id`, history.py): *Compare* and *Restore* start from the log.

Entries travel with the project: a colleague's entries come in when their work is brought in (sync.py), yours stay
as you wrote them, and an entry you removed does not come back.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any

from . import __version__
from .store import Workspace, now

# what an entry is about, in groups for the page's filter: {kind: group}
GROUPS = {
    "entry": "entries",
    "documents-added": "documents", "document-removed": "documents", "ai-access": "documents", "reread": "documents",
    "check-added": "checks", "check-removed": "checks", "evidence-added": "checks",
    "themes-found": "themes", "themes-removed": "themes", "theme-removed": "themes", "theme-restored": "themes",
    "theme-renamed": "themes", "theme-merged": "themes", "theme-separated": "themes",
    "codebook-added": "codebooks", "codebook-changed": "codebooks", "codebook-removed": "codebooks",
    "codebook-moved": "codebooks", "codebook-copied": "codebooks",
    "glossary-words": "themes",
    "restored": "history",
    "sync": "together",
    "shared": "together", "unshared": "together",  # 0.18 (sharing.py)
    # 0.18 L2 (ownership.py): a change proposed to the owner, the owner's word on it, and who the owner is
    "proposal": "together", "proposal-accepted": "together", "proposal-declined": "together",
    "proposal-taken-back": "together", "owner": "together",
}
GROUP_NAMES = {"entries": "Your own entries", "documents": "Documents", "checks": "Checks", "themes": "Themes",
               "codebooks": "Codebooks", "history": "Restored versions", "together": "Work together"}
MAX_TEXT = 10000
MAX_WHY = 2000
_ID = re.compile(r"e[0-9a-f]{16}")


def _new_id() -> str:
    return "e" + uuid.uuid4().hex[:16]


def _me() -> str:
    from .people import me

    return me()


def record(cx: sqlite3.Connection, kind: str, text: str, subject_kind: str | None = None, subject_id: str | None = None,
           title: str | None = None, data: Any = None, version_id: str | None = None, why: str | None = None,
           person_id: str | None = None, at: str | None = None) -> str:
    """Write an entry in the transaction `cx` (it is part of the change it records: undone with it). Returns its id."""
    eid = _new_id()
    cx.execute("INSERT INTO research_log(entry_id, at, person_id, kind, subject_kind, subject_id, title, text, why, "
               "version_id, data_json, app_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (eid, at or now(), person_id or _me(), kind, subject_kind, subject_id, (title or None) and title[:300],
                (text or "")[:MAX_TEXT], ((why or "").strip()[:MAX_WHY] or None), version_id,
                json.dumps(data, ensure_ascii=False) if data is not None else None, __version__))
    return eid


def access_words(level: str | None, many: bool = False) -> str:
    """Who may read documents with AI, in the words of a log entry."""
    it = "them" if many else "it"
    return {"cloud": f"Claude may read {it}", "local": f"only a local AI may read {it}",
            "none": f"no AI may read {it}"}.get(level or "", str(level))


def day(at: str | None) -> str:
    """A date in an entry's words: "9 Nov 2026"."""
    try:
        import datetime as _dt

        d = _dt.date.fromisoformat((at or "")[:10])
        return f"{d.day} {d.strftime('%b')} {d.year}"
    except ValueError:
        return (at or "")[:10]


def quoted(s: str | None, n: int = 120) -> str:
    """A title or a hypothesis in an entry's sentence: in quotes, cut short, without its own full stop (the sentence
    has one)."""
    s = " ".join((s or "").split())
    if s.endswith(".") and not s.endswith(".."):
        s = s[:-1]
    return f"“{s[:n - 1] + '…' if len(s) > n else s}”"


# ---------------------------------------------------------------------------------------------
# a person's own entries, and their reasons
# ---------------------------------------------------------------------------------------------
def add(ws: Workspace, text: str, subject_kind: str | None = None, subject_id: str | None = None,
        title: str | None = None) -> dict:
    """A person's own entry (a field note, a decision, a reason)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Write the entry first.")
    if len(text) > MAX_TEXT:
        raise ValueError(f"Keep an entry under {MAX_TEXT:,} characters.")
    with ws.connect() as cx:
        eid = record(cx, "entry", text, subject_kind, subject_id, title)
    return entry(ws, eid)


def _own(cx: sqlite3.Connection, entry_id: str) -> sqlite3.Row:
    row = cx.execute("SELECT * FROM research_log WHERE entry_id=?", (entry_id,)).fetchone()
    if row is None:
        raise KeyError(entry_id)
    if row["person_id"] != _me():
        raise PermissionError("This entry is a colleague's: only they can change it.")
    return row


def update(ws: Workspace, entry_id: str, text: str | None = None, why: str | None = None) -> dict:
    """Change your own entry's words (`text`), or say why next to any entry of yours (`why`; "" takes it away)."""
    with ws.connect() as cx:
        row = _own(cx, entry_id)
        sets, args = [], []
        if text is not None:
            if row["kind"] != "entry":
                raise ValueError("The app's own entries keep their words; say why beside them instead.")
            t = text.strip()
            if not t:
                raise ValueError("An entry cannot be empty: remove it instead.")
            sets.append("text=?")
            args.append(t[:MAX_TEXT])
        if why is not None:
            sets.append("why=?")
            args.append(why.strip()[:MAX_WHY] or None)
        if sets:
            cx.execute(f"UPDATE research_log SET {', '.join(sets)}, edited_at=? WHERE entry_id=?",
                       (*args, now(), entry_id))
    return entry(ws, entry_id)


def remove(ws: Workspace, entry_id: str) -> None:
    """Remove one of your own entries. The app's entries stay: they are the record of what happened."""
    with ws.connect() as cx:
        row = _own(cx, entry_id)
        if row["kind"] != "entry":
            raise ValueError("The app's own entries are the record of what happened and cannot be removed.")
        cx.execute("DELETE FROM research_log WHERE entry_id=?", (entry_id,))
        # not brought back by a colleague's copy of the project (sync.py)
        cx.execute("INSERT OR REPLACE INTO sync_removed(kind, key, title, at, person_id) VALUES ('log', ?, ?, ?, ?)",
                   (entry_id, (row["text"] or "")[:80], now(), row["person_id"]))


# ---------------------------------------------------------------------------------------------
# reading the log
# ---------------------------------------------------------------------------------------------
def _view(r: sqlite3.Row | dict, names: dict[str, str], me: str, versions: set[str]) -> dict:
    d = dict(r)
    data = d.pop("data_json", None)
    d["data"] = json.loads(data) if data else None
    d["group"] = GROUPS.get(d["kind"], "other")
    d["mine"] = d["person_id"] == me
    d["who"] = names.get(d["person_id"] or "", "a colleague")
    d["can_edit"] = d["mine"] and d["kind"] == "entry"
    d["can_why"] = d["mine"]
    d["has_version"] = bool(d.get("version_id")) and d["version_id"] in versions
    return d


def _versions_present(ws: Workspace, ids: list[str]) -> set[str]:
    from . import history

    return history.present(ws, ids)


def entry(ws: Workspace, entry_id: str) -> dict:
    from .people import names

    rows = ws.query("SELECT * FROM research_log WHERE entry_id=?", (entry_id,))
    if not rows:
        raise KeyError(entry_id)
    return _view(rows[0], names(ws), _me(), _versions_present(ws, [rows[0]["version_id"] or ""]))


def entries(ws: Workspace, group: str | None = None, q: str | None = None, subject_kind: str | None = None,
            subject_id: str | None = None, offset: int = 0, limit: int | None = 200, oldest_first: bool = False) -> dict:
    """The log, newest first: {entries, total, groups: {group: count}}. `group` keeps one group ("entries",
    "documents", ...), `q` entries whose words, title or reason contain it, `subject_*` those about one thing.
    `limit` None: every entry (the downloads; a page asks for at most 2,000 at a time)."""
    from .people import names

    where, args = [], []
    if group:
        kinds = [k for k, g in GROUPS.items() if g == group]
        if not kinds:
            raise ValueError(f"Unknown group {group!r}.")
        where.append(f"kind IN ({','.join('?' * len(kinds))})")
        args += kinds
    if subject_kind:
        where.append("subject_kind=?")
        args.append(subject_kind)
    if subject_id:
        where.append("subject_id=?")
        args.append(subject_id)
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    order = "ASC" if oldest_first else "DESC"
    first = max(0, int(offset))
    most = None if limit is None else max(1, min(int(limit), 2000))
    if q and q.strip():
        # the words are looked for here, not by the database: its lower() and LIKE know the letters a to z only,
        # so "Életminőség" was not found by "életminőség"
        word = q.strip().casefold()
        rows = [r for r in ws.query(f"SELECT * FROM research_log {sql_where} ORDER BY at {order}, rowid {order}", args)
                if any(word in (r[c] or "").casefold() for c in ("text", "title", "why"))]
        total = len(rows)
        rows = rows[first:] if most is None else rows[first:first + most]
    else:
        total = int(ws.scalar(f"SELECT COUNT(*) FROM research_log {sql_where}", args) or 0)
        rows = ws.query(f"SELECT * FROM research_log {sql_where} ORDER BY at {order}, rowid {order} LIMIT ? OFFSET ?",
                        (*args, -1 if most is None else most, first))
    counts: dict[str, int] = {}
    for kind, n in ws.query("SELECT kind, COUNT(*) FROM research_log GROUP BY kind"):
        g = GROUPS.get(kind, "other")
        counts[g] = counts.get(g, 0) + n
    versions = _versions_present(ws, [r["version_id"] for r in rows if r["version_id"]])
    nm, me = names(ws), _me()
    return {"entries": [_view(r, nm, me, versions) for r in rows], "total": total, "groups": counts,
            "group_names": GROUP_NAMES}


def table(ws: Workspace) -> list[dict]:
    """Every entry, oldest first, as rows for a spreadsheet."""
    out = []
    for e in entries(ws, limit=None, oldest_first=True)["entries"]:  # every entry: 2,000 was all a download held
        out.append({"When (UTC)": e["at"], "Who": e["who"], "What": GROUP_NAMES.get(e["group"], e["group"]),
                    "Entry": e["text"], "About": e["title"] or "", "Why": e["why"] or "",
                    "ENLENS version": e.get("app_version") or ""})
    return out


def markdown(ws: Workspace, project: str) -> str:
    """The log as a Markdown file, oldest first, a heading per day: for a thesis appendix or an audit."""
    lines = [f"# Research log: {project}", "", f"Written by ENLENS {__version__} on {now()[:10]}. Times are UTC.", ""]
    day = None
    for e in entries(ws, limit=None, oldest_first=True)["entries"]:
        d = (e["at"] or "")[:10]
        if d != day:
            day = d
            lines += [f"## {d}", ""]
        who = "" if e["mine"] else f" ({e['who']})"
        text = " ".join(e["text"].split()) if e["kind"] != "entry" else e["text"].strip().replace("\n", "\n  ")
        lines.append(f"- **{(e['at'] or '')[11:16]}**{who} {text}")
        if e["why"]:
            lines.append(f"  *Why:* {' '.join(e['why'].split())}")
    if day is None:
        lines.append("Nothing in the log yet.")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------------------------
# a colleague's entries (sync.py)
# ---------------------------------------------------------------------------------------------
def merge(cx: sqlite3.Connection, rows: list[dict], fix, sender: str | None = None, report: dict | None = None) -> int:
    """Bring in a colleague's entries: those not here come in (unless removed here); one of theirs they changed since
    (a later `edited_at`) is brought up to date. Yours are never changed. `fix(row) -> row` rewrites the ids of a
    merge (documents, checks). Returns how many came in or changed.

    Roles (DESIGN-roles §4.8), with `sender` (who sent the file): a row of a third person comes in labelled "via" the
    sender (`sync_via`); it brings up to date only a row that came relayed itself; its author's own row takes its
    place whatever its time. Without `sender`: as before."""
    me = _me()
    gone = {r[0] for r in cx.execute("SELECT key FROM sync_removed WHERE kind='log'")}
    cols = [r[1] for r in cx.execute("PRAGMA table_info(research_log)")]
    via_here: set[str] = set()
    if sender:
        from .people import first_hand, note_via, relayed

        via_here = relayed(cx, "log")
    n = 0
    for r in rows:
        if not isinstance(r.get("entry_id"), str) or not _ID.fullmatch(r["entry_id"]) or r["entry_id"] in gone:
            continue
        r = fix(r)
        if r is None:
            continue
        have = cx.execute("SELECT person_id, edited_at FROM research_log WHERE entry_id=?", (r["entry_id"],)).fetchone()
        use = [c for c in cols if c in r]
        if have is None and r.get("person_id") == me:
            # nothing in a colleague's file is written in your name: an entry of yours that is not here is one
            # you removed, or one the file made up
            continue
        third = bool(sender) and bool(r.get("person_id")) and r["person_id"] != sender
        if have is None:
            if third:
                note_via(cx, "log", r["entry_id"], r["person_id"], sender)
                if report is not None:
                    report["via"] = report.get("via", 0) + 1
            cx.execute(f"INSERT INTO research_log({','.join(use)}) VALUES ({','.join('?' * len(use))})",
                       [r[c] for c in use])
            n += 1
        elif have[0] != me and have[0] == r.get("person_id") and (
                (r.get("edited_at") or "") > (have[1] or "") or (sender and not third and r["entry_id"] in via_here)):
            if third and r["entry_id"] not in via_here:
                continue  # relayed: never in place of the author's own row
            if sender and not third and r["entry_id"] in via_here:
                first_hand(cx, "log", [r["entry_id"]])
            elif third:
                note_via(cx, "log", r["entry_id"], r["person_id"], sender)
            sets = [c for c in use if c != "entry_id"]
            cx.execute(f"UPDATE research_log SET {', '.join(c + '=?' for c in sets)} WHERE entry_id=?",
                       [*(r[c] for c in sets), r["entry_id"]])
            n += 1
    return n
