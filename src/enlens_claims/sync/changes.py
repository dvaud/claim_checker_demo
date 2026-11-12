"""What changed in a project since the shared folder's last round (deep dive after 0.17.0, S5 and S14).

A round of the shared folder (sync/folder.py) compares what this copy would write now with what it wrote before. Done
in full, that fingerprints every check and set of themes and reads every one of the project's rows, also in a round
where nothing changed anywhere (on 1,000 documents and 100 checks, seconds of work every two minutes). This module
lets a round look only at what changed since the last one.

**Change counters.** Once a project uses the shared folder, a trigger on each table a round reads (`ensure`) stamps
every row written, changed or deleted in `sync_changes`: one counter per table and *hint*, the item the row belongs to
as far as the row itself says (a check's id, a part's id, a theme run's id, a codebook's name, `HINTS`; most of the
project's own tables have one counter, hint ''). Each stamp is the next number of one clock (the row with an empty
table name), so "what changed since the last round" is every counter above the clock the round last read. The
triggers use plain SQL only, so every way of writing to the database counts: the app, a merge, an older ENLENS. The
counters name items by their ids, which may be private: they are this copy's own (`sync.common.LOCAL_ONLY`) and never
leave it (`forget`, for a project zip).

**What a round remembers** (`Memory`, in this process only): the clock it last read, each item's fingerprint, which of
the project's tables held nothing new, and what `record_seen` last wrote down. A new process (the app started again)
starts with nothing, so its first round looks at everything, as before. Anything a counter cannot see makes the round
look at everything again: a changed table definition (a new version, an add-on), a table without its triggers or with
another version's, a database replaced by another (a restored backup: its clock is behind; another computer's copy:
its own id, `ident`), the documents kept out of the folder, a codebook's files.

A round that stops or fails before it has recorded what it wrote keeps nothing of this round: the next one looks again
at all it would have looked at, and more.

**What the counters cost.** A trigger makes SQLite keep a statement journal for each row written to a table with a key
and two or more other indexes (labels, tasks, verifications, the research log): on the SQLite builds Python ships with,
about 20 µs a row (100,000 labels added at once: 0.3 s without, 2.3 s with). Tables with fewer indexes cost next to
nothing. Only projects that have used a shared folder have the triggers.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path
from typing import Iterable

TABLE = "sync_changes"
_PREFIX = "enlens_changes_"   # the triggers' names: enlens_changes_<table>_i / _u / _d


def _owner(x: str) -> str:
    """SQL: a task id's kind and owner ("check:c1:p5" -> "check:c1", "second:check:c1:p5" -> "check:c1",
    "decompose:h1" -> "decompose:h1", "theme:r1:3" -> "theme:r1", "label:sdg:p7" -> "label:sdg")."""
    t = f"(CASE WHEN substr({x}, 1, 7) = 'second:' THEN substr({x}, 8) ELSE {x} END)"
    rest = f"substr({t}, instr({t} || ':', ':') + 1)"
    return f"substr({t}, 1, instr({t} || ':', ':') - 1) || ':' || substr({rest}, 1, instr({rest} || ':', ':') - 1)"


# a row's hint, over the row R (NEW or OLD): what item it belongs to, as far as the row says
HINTS = {
    "hypotheses": "R.hyp_id",
    "user_claims": "R.hyp_id",
    "verifications": "R.subject_id",
    "second_opinions": "R.subject_id",
    "judgements": "R.claim_id",
    "tasks": _owner("R.task_id"),
    "results": _owner("R.task_id"),
    "theme_runs": "R.run_id",
    "themes": "R.run_id",
    "theme_members": "R.run_id",
    "labels": "R.framework",
    "reviews": "R.item_kind || '|' || R.item_id",
    "concept_links": "R.a || '|' || R.b",
    "notes": "R.note_id",
    "research_log": "(CASE WHEN R.kind = 'entry' THEN 'log|' || R.entry_id ELSE R.subject_kind || '|' || R.subject_id "
                    "END)",
    "sync_removed": "R.kind || '|' || R.key",
    "sync_copies": "R.kind || '|' || R.key",
    "sync_seen": "R.kind || '|' || R.key",
    "shares": "R.kind || '|' || R.key",
    "meta": "R.key",
    "runs": "R.kind || '|' || R.scope",
    "documents": "R.doc_id",
    "sync_folder_docs": "R.doc_id",
    "canon_seen": "R.doc",
    "sync_written": "R.kind",
}
# only a row taken away counts: what is added to these is the round's own record (sync_written) or never needs
# writing down again (sync_seen: `record_seen` adds what is missing)
DELETE_ONLY = {"sync_seen", "sync_written"}
# and of the record, only the project's rows (a round reads every other entry each time)
WHEN = {"sync_written": "OLD.kind = 'row'"}
# the tables a round reads besides the project's rows (`sharing.ProjectRows.tables`): the items and the documents
ITEM_TABLES = ("hypotheses", "user_claims", "verifications", "second_opinions", "judgements", "tasks", "results",
               "theme_runs", "themes", "theme_members", "labels", "reviews", "concept_links", "notes", "research_log",
               "sync_removed", "sync_copies", "shares", "meta", "runs", "documents", "sync_folder_docs", "canon_seen",
               "sync_seen", "sync_written")


def _trigger_sql(table: str, verb: str) -> str:
    hint = HINTS.get(table, "''")
    stamp = (f"UPDATE {TABLE} SET n = n + 1 WHERE tbl = '' AND hint = '';")

    def put(row: str) -> str:
        h = hint.replace("R.", f"{row}.")
        return (f"INSERT INTO {TABLE}(tbl, hint, n) VALUES ('{table}', COALESCE({h}, ''), COALESCE((SELECT n FROM "
                f"{TABLE} WHERE tbl = '' AND hint = ''), 0)) ON CONFLICT(tbl, hint) DO UPDATE SET n = excluded.n;")

    rows = {"i": [put("NEW")], "u": [put("OLD"), put("NEW")], "d": [put("OLD")]}[verb]
    event = {"i": "INSERT", "u": "UPDATE", "d": "DELETE"}[verb]
    when = f" WHEN {WHEN[table]}" if table in WHEN else ""
    return (f'CREATE TRIGGER "{_PREFIX}{table}_{verb}" AFTER {event} ON "{table}"{when} BEGIN {stamp} '
            f'{" ".join(rows)} END')


def _verbs(table: str) -> tuple[str, ...]:
    return ("d",) if table in DELETE_ONLY else ("i", "u", "d")


def ensure(cx: sqlite3.Connection, tables: Iterable[str]) -> set[str]:
    """The counters' table and the triggers on each of `tables` that is in the database (in the caller's write
    transaction). Returns the tables whose triggers were missing, or other than this version makes them, and are made
    now (a table made or remade since, a project last used by another version): what changed in them before now was
    not counted, or not as this version reads it."""
    import secrets

    cx.execute(f"CREATE TABLE IF NOT EXISTS {TABLE}(tbl TEXT NOT NULL, hint TEXT NOT NULL, n INTEGER NOT NULL, "
               "PRIMARY KEY(tbl, hint)) WITHOUT ROWID")
    cx.execute(f"INSERT OR IGNORE INTO {TABLE}(tbl, hint, n) VALUES ('', '', 0)")
    # which database this is: a copy of the project put in its place (another computer's, synced in) has its own
    cx.execute(f"INSERT OR IGNORE INTO {TABLE}(tbl, hint, n) VALUES ('', 'id', ?)", (secrets.randbits(62),))
    present = {r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    have = {r[0]: r[1] for r in cx.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name LIKE ?",
                                           (_PREFIX + "%",))}
    made = set()
    for t in sorted(set(tables)):
        if t not in present or t == TABLE or t.startswith("sqlite_"):
            continue
        for v in _verbs(t):
            name, sql = f"{_PREFIX}{t}_{v}", _trigger_sql(t, v)
            if have.get(name) != sql:
                cx.execute(f'DROP TRIGGER IF EXISTS "{name}"')
                cx.execute(sql)
                made.add(t)
    return made


def forget(cx: sqlite3.Connection) -> None:
    """A copy of the database that leaves this computer (a project zip) takes neither the counters (they name items
    by their ids, private ones too) nor the triggers (the copy that opens it makes its own). Their pages are
    overwritten, so a copy that is not VACUUMed keeps nothing of them either."""
    cx.execute("PRAGMA secure_delete=ON")
    for (name,) in cx.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE ?",
                              (_PREFIX + "%",)).fetchall():
        cx.execute(f'DROP TRIGGER IF EXISTS "{name}"')
    cx.execute(f"DROP TABLE IF EXISTS {TABLE}")


def ident(cx: sqlite3.Connection) -> int | None:
    """Which database this is (made with the counters)."""
    try:
        row = cx.execute(f"SELECT n FROM {TABLE} WHERE tbl = '' AND hint = 'id'").fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row[0]) if row else None


def clock(cx: sqlite3.Connection) -> int | None:
    """The clock: the number of the last change counted (None: nothing counted here)."""
    try:
        row = cx.execute(f"SELECT n FROM {TABLE} WHERE tbl = '' AND hint = ''").fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row[0]) if row else None


def schema(cx: sqlite3.Connection) -> str:
    """The database's table and trigger definitions: a column added changes what each row says and fires no trigger;
    a table made anew has lost its triggers (what changed in it since was not counted)."""
    h = hashlib.sha1()
    for name, sql in cx.execute("SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'trigger') ORDER BY "
                                "type, name"):
        h.update(f"{name}\0{sql}\0".encode())
    return h.hexdigest()


def files_sig(paths: Iterable[Path]) -> tuple:
    """What tells that files changed: each one's contents (a digest; None when it is not there). Not its time and
    size: a file rewritten at the same size keeps its time when a sync service or a copy carries it over. Codebooks
    are small: this costs next to nothing."""
    out = []
    for p in paths:
        try:
            out.append((str(p), hashlib.sha1(p.read_bytes()).hexdigest()))
        except OSError:
            out.append((str(p), None))
    return tuple(out)


# ---------------------------------------------------------------------------------------------
# from what changed to the items it changed
# ---------------------------------------------------------------------------------------------
def _split(h: str) -> tuple[str, str]:
    a, _, b = h.partition("|")
    return a, b


def touched(cx: sqlite3.Connection, changed: dict[str, set[str]]) -> tuple[set[tuple[str, str]], set[str]]:
    """The items (kind, key) a change may have touched, and the kinds every item of which it may have touched (where a
    row does not say which item it belongs to). Generous: an item looked at again for nothing costs a fingerprint; one
    missed would not be written."""
    keys: set[tuple[str, str]] = set()
    kinds: set[str] = set()
    claims: set[str] = set()
    labels: set[str] = set()
    for h in changed.get("hypotheses", set()) | changed.get("user_claims", set()):
        keys.add(("check", h))
    for t in ("verifications", "second_opinions", "judgements"):
        claims |= changed.get(t, set())
    for t in ("tasks", "results"):
        for h in changed.get(t, ()):
            head, _, owner = h.partition(":")
            if head == "decompose":
                keys.add(("check", owner))
            elif head in ("expand", "check", "reread"):
                claims.add(owner)
            elif head == "theme":
                keys.add(("themes", owner))
            elif head == "label":
                keys.add(("codebook", owner))
            elif head == "link":
                kinds.add("link")  # (a term's id may hold the separator)
    for t in ("theme_runs", "themes", "theme_members"):
        keys |= {("themes", h) for h in changed.get(t, ())}
    keys |= {("codebook", h) for h in changed.get("labels", ())}
    run_keys = None
    for h in changed.get("reviews", ()):
        ik, iid = _split(h)
        if ik == "label":
            labels.add(iid)
        elif ik == "concept_link":
            keys.add(("link", iid))
        elif ik in ("theme", "theme_member"):
            if run_keys is None:
                run_keys = [(rk + ":", rid) for rid, rk in cx.execute("SELECT run_id, run_key FROM theme_runs") if rk]
            keys |= {("themes", rid) for head, rid in run_keys if iid.startswith(head)}
    keys |= {("link", h) for h in changed.get("concept_links", ())}
    keys |= {("note", h) for h in changed.get("notes", ())}
    for h in changed.get("research_log", ()):
        k, key = _split(h)
        keys.add((k, key))
    for t in ("sync_removed", "shares"):
        for h in changed.get(t, ()):
            k, key = _split(h)
            if k == "review":  # a note of a review taken back: its item is in its title
                kinds |= {"codebook", "themes", "link"}
            keys.add((k, key))
    for h in changed.get("meta", ()):
        if h.startswith("codebook_followed:"):
            keys.add(("codebook", h.split(":", 1)[1]))
    for h in changed.get("runs", ()):
        k, scope = _split(h)
        if k == "label":
            keys.add(("codebook", scope))
    ids = sorted(claims)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        keys |= {("check", r[0]) for r in cx.execute(f"SELECT DISTINCT hyp_id FROM user_claims WHERE claim_id IN "
                                                      f"({','.join('?' * len(chunk))})", chunk) if r[0]}
    ids = sorted(labels)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        keys |= {("codebook", r[0]) for r in cx.execute(f"SELECT DISTINCT framework FROM labels WHERE label_id IN "
                                                         f"({','.join('?' * len(chunk))})", chunk) if r[0]}
    return keys, kinds


# what else a table of the project's rows is read with (`sharing.ProjectRows.scan`): a change there changes what the
# table's rows say as they leave, or which of them leave
ROW_DEPENDS = {
    "results": {"tasks"},                     # a task's answers go with the task
    "ai_sent": {"tasks", "shares", "hypotheses", "user_claims", "theme_runs", "labels", "concept_links", "reviews"},
    "reviews": {"labels"},                    # reviews of labels with the bundled codebooks
    "sync_removed": {"labels"},               # notes of such reviews taken back
    "research_log": {"shares"},               # the app's entries about several items
}
# the same while documents are kept out of the folder: what names the AI work on them
KEPT_OUT_DEPENDS = {"concept_links": {"documents"}, "reviews": {"claims", "labels"}, "claim_targets": {"claims"}}


def _counts(table: str, dep: str, hints: set[str]) -> bool:
    """Whether these changes of `dep` change what `table`'s rows say as they leave."""
    if table == "ai_sent" and dep == "labels":  # only through which codebooks are items (a task's id names its codebook)
        from ..frameworks import BUNDLED

        return bool(hints - set(BUNDLED))
    return bool(hints)


def tables_to_read(changed: dict[str, set[str]], project_tables: Iterable[str], kept_out: bool) -> set[str]:
    """The project's tables whose rows must be read again, given what changed."""
    out = set()
    for t in project_tables:
        deps = {t} | ROW_DEPENDS.get(t, set()) | (KEPT_OUT_DEPENDS.get(t, set()) if kept_out else set())
        if any(d in changed and (d == t or _counts(t, d, changed[d])) for d in deps):
            out.add(t)
    if "results" in out:
        out.add("tasks")  # the answers that leave are those of the tasks read in the same pass
    return out


# ---------------------------------------------------------------------------------------------
# what a round remembers (this process only)
# ---------------------------------------------------------------------------------------------
class Memory:
    """What the rounds of one project remember in this process. `upto` and the rest describe the project as it was at
    clock `upto`; None: nothing remembered (look at everything)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.schema: str | None = None
        # the plan of a round (sync/folder.py `_Writer.plan`)
        self.upto: int | None = None
        self.items: dict[tuple[str, str], dict] = {}   # (kind, key) -> {"fp", "busy", "mark", "files"}
        self.clean: set[str] = set()                     # the project's tables that held nothing new at `upto`
        self.context: tuple | None = None                # what the rows were read with (`_Writer._context`)
        self.ignore: dict[tuple[str, str], int] = {}     # counters the round itself set (`ignore_own`)
        # what `record_seen` wrote down (sync/fingerprints.py `record_seen_since`)
        self.seen_upto: int | None = None
        self.seen_units: set[tuple[str, str]] = set()
        self.seen_books: dict[str, tuple] = {}
        self.seen_names: set[str] | None = None
        self.seen_context: tuple | None = None

    def forget(self) -> None:
        lock = self.lock
        self.__init__()
        self.lock = lock


_MEMORY: dict[str, Memory] = {}
_MEMORY_LOCK = threading.Lock()


def memory(db_path: Path | str) -> Memory:
    key = str(Path(db_path).resolve())
    with _MEMORY_LOCK:
        if key not in _MEMORY:
            _MEMORY[key] = Memory()
        return _MEMORY[key]


def forget_all() -> None:
    """Every project's memory goes (tests; a project replaced on disk)."""
    with _MEMORY_LOCK:
        _MEMORY.clear()


def changed_since(cx: sqlite3.Connection, upto: int | None, ignore: dict[tuple[str, str], int] | None = None
                  ) -> dict[str, set[str]] | None:
    """What changed after `upto`, without the counters the round itself set (`ignore`); None when that cannot be known
    (nothing remembered, no counters, or a clock behind `upto`: another database, a backup put back)."""
    now = clock(cx)
    if upto is None or now is None or now < upto:
        return None
    if now == upto:
        return {}
    got: dict[str, set[str]] = {}
    for t, h, n in cx.execute(f"SELECT tbl, hint, n FROM {TABLE} WHERE n > ? AND tbl != ''", (upto,)):
        if ignore and ignore.get((t, h)) == n:
            continue
        got.setdefault(t, set()).add(h)
    return got
