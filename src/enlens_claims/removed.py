"""Documents a colleague's word removed from this copy, restorable for 30 days (DESIGN-roles §3.4).

A removal that someone else's word causes (the owner or a Co-owner removed the document; an addition was declined or
taken back) applies at once, so no file can destroy a document for good. Before it, `archive` keeps one small archive
per document in the project folder:

    backups/removed/<doc_id>-<YYYYMMDDTHHMMSS>.sqlite   the rows the removal deletes (`Workspace._document_rows`, but
                                                        what is made again: `store.REMADE`), same tables and columns
    backups/removed/<doc_id>-<YYYYMMDDTHHMMSS>/<file>   the original, moved there when it was inside `originals/`

and a row of `removed_docs` lists it. `restore` gives it all back; `prune` removes archives older than `DAYS` days
(the one use of this computer's clock: it decides nothing between copies). A person's own removal is not archived
(their own click). `bundle.export_project` never packs `backups/`, and a project from a zip starts without
`removed_docs` (its archives stay on the computer that made them).
"""
from __future__ import annotations

import datetime as _dt
import re
import shutil
import sqlite3
from pathlib import Path

from .store import REMADE, Workspace

DAYS = 30
CAUSES = ("removed", "declined")
_INFO = "archive_info"
_NAME = re.compile(r"(.+)-(\d{8}T\d{6})(?:-\d+)?")  # an archive's name: <doc_id>-<when>[-<n>]  # the archive's own table: which document, and where its original was


def _now() -> _dt.datetime:
    """This computer's clock (a test puts another in its place)."""
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)


def _folder(ws: Workspace) -> Path:
    return Path(ws.root) / "backups" / "removed"


def _when(at: str | None) -> _dt.datetime | None:
    try:
        t = _dt.datetime.fromisoformat(str(at))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def _safe(doc_id: str) -> bool:
    from .sync.common import DOC_ID

    return bool(DOC_ID.fullmatch(doc_id or ""))


def _remove_files(folder: Path, name: str | None) -> None:
    if not name:
        return
    (folder / f"{name}.sqlite").unlink(missing_ok=True)
    (folder / f"{name}.sqlite.part").unlink(missing_ok=True)
    shutil.rmtree(folder / name, ignore_errors=True)


def _inside(p: Path, root: Path) -> bool:
    try:
        return p.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def archive(ws: Workspace, cx: sqlite3.Connection, doc_id: str, by: str | None, why: str, cause: str) -> None:
    """Keep the rows and the original of a document before a colleague's word removes it (cause: "removed" |
    "declined"). Called in the transaction `cx` that removes it (`ownership._Ctx.remove_here`): the rows are read
    through it, and the archive is written through a connection of its own (ATTACH cannot run inside a transaction).
    An earlier archive of the same document is replaced. Nothing happens for a document this copy does not hold."""
    if cause not in CAUSES:
        raise ValueError(f"cause must be one of {', '.join(CAUSES)}.")
    row = cx.execute("SELECT title, path FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if not row or not _safe(doc_id):
        return
    title, path = row[0], row[1]
    root, folder = Path(ws.root), _folder(ws)
    folder.mkdir(parents=True, exist_ok=True)
    old = cx.execute("SELECT archive FROM removed_docs WHERE doc_id=?", (doc_id,)).fetchone()
    if old:
        _remove_files(folder, old[0])
    when = _now()
    name = base = f"{doc_id}-{when.strftime('%Y%m%dT%H%M%S')}"
    n = 1
    while (folder / name).exists() or (folder / f"{name}.sqlite").exists():  # (one left in the same second)
        n += 1
        name = f"{base}-{n}"
    # the original, when it is the project's own copy (`originals/`): moved, not copied. One left by a removal whose
    # transaction was undone (its archive has no row) is taken from there.
    original, size = None, 0
    if path:
        f = Path(path)
        if not f.is_file():
            f = next((g for g in sorted(folder.glob(f"{doc_id}-*/{f.name}")) if g.is_file()), f)
        if f.is_file() and (_inside(f, root / "originals") or _inside(f, folder)):
            dest = folder / name / f.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            was = (root / "originals" / doc_id / f.name) if _inside(f, folder) else f
            try:
                shutil.move(str(f), str(dest))
                original = was.resolve().relative_to(root.resolve()).as_posix()
                size += dest.stat().st_size
                try:
                    was.parent.rmdir()  # originals/<doc_id>/, when it is empty now
                except OSError:
                    pass
            except (OSError, ValueError):
                original = None
    db = folder / f"{name}.sqlite"
    part = folder / f"{name}.sqlite.part"
    part.unlink(missing_ok=True)
    out = sqlite3.connect(part)
    try:
        made: dict[str, set] = {}
        for tbl, where, args in ws._document_rows(doc_id, cx):
            if tbl in REMADE:
                continue
            cur = cx.execute(f"SELECT * FROM {tbl} WHERE {where}", args)
            cols = [d[0] for d in cur.description]
            if tbl not in made:
                out.execute(f"CREATE TABLE {_quote(tbl)}({', '.join(_quote(c) for c in cols)})")
                made[tbl] = set()
            put = f"INSERT INTO {_quote(tbl)} VALUES ({', '.join('?' * len(cols))})"
            for r in cur:
                if r not in made[tbl]:  # (a row two selectors name, e.g. a task of a label and a reading, once)
                    made[tbl].add(r)
                    out.execute(put, r)
        out.execute(f"CREATE TABLE {_INFO}(key TEXT PRIMARY KEY, value TEXT)")
        out.executemany(f"INSERT INTO {_INFO} VALUES (?, ?)",
                        [("doc_id", doc_id), ("title", title), ("at", when.isoformat()), ("by", by), ("why", why),
                         ("cause", cause), ("original", original)])
        out.commit()
    finally:
        out.close()
    part.replace(db)
    size += db.stat().st_size
    cx.execute("INSERT OR REPLACE INTO removed_docs(doc_id, title, at, by, why, cause, archive, bytes) "
               "VALUES (?,?,?,?,?,?,?,?)", (doc_id, title, when.isoformat(), by, why, cause, name, size))


def _info(src: sqlite3.Connection) -> dict:
    try:
        return {k: v for k, v in src.execute(f"SELECT key, value FROM {_INFO}")}
    except sqlite3.Error:
        return {}


def restore(ws: Workspace, doc_id: str) -> bool:
    """Bring a removed document back from its archive: its rows (`INSERT OR IGNORE`), its original, the passages it
    read (`reader.apply_choices`); the note of its removal goes, and so does the archive. False when there is no
    archive to restore from, or when the same file is in the project again as another document. Two callers: the
    person's *Restore*, and `ownership._fetch` (the project says the document is in again)."""
    from . import researchlog
    from .access import relabel
    from .reader import apply_choices

    row = ws._conn().execute("SELECT archive, title FROM removed_docs WHERE doc_id=?", (doc_id,)).fetchone()
    if not row:
        return False
    name, folder, root = row[0], _folder(ws), Path(ws.root)
    db = folder / f"{name}.sqlite" if name else None
    if db is None or not db.is_file():
        with ws.connect() as cx:
            cx.execute("DELETE FROM removed_docs WHERE doc_id=?", (doc_id,))
        return False
    src = sqlite3.connect(db)
    try:
        info = _info(src)
        tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != ?",
                                            (_INFO,))]
        with ws.connect() as cx:
            if not cx.execute("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)).fetchone():
                doc = src.execute("SELECT sha1 FROM documents WHERE doc_id=?", (doc_id,)).fetchone() \
                    if "documents" in tables else None
                if doc is None or (doc[0] and cx.execute("SELECT 1 FROM documents WHERE sha1=?", (doc[0],)).fetchone()):
                    return False  # the same file was added again since, as a document of its own
                for tbl in tables:
                    here = {r[1] for r in cx.execute(f"PRAGMA table_info({_quote(tbl)})")}
                    cur = src.execute(f"SELECT * FROM {_quote(tbl)}")
                    cols = [d[0] for d in cur.description]
                    keep = [i for i, c in enumerate(cols) if c in here]  # (a column a later version dropped: skipped)
                    if not keep:
                        continue
                    put = (f"INSERT OR IGNORE INTO {_quote(tbl)}({', '.join(_quote(cols[i]) for i in keep)}) "
                           f"VALUES ({', '.join('?' * len(keep))})")
                    cx.executemany(put, ([r[i] for i in keep] for r in cur))
                rel = info.get("original")
                if rel:
                    dest = (root / rel)
                    kept = folder / name / Path(rel).name
                    if _inside(dest, root / "originals"):
                        if kept.is_file() and not dest.exists():
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(kept), str(dest))
                        if dest.is_file():
                            cx.execute("UPDATE documents SET path=? WHERE doc_id=?", (str(dest.resolve()), doc_id))
                apply_choices(cx, doc_id)
                relabel(cx)
                ws.bump_corpus(cx)
                title = row[1] or info.get("title")
                researchlog.record(cx, "document-restored", f"Restored the document {researchlog.quoted(title)}.",
                                   "document", doc_id, title, data={"removed_at": info.get("at"),
                                                                    "removed_by": info.get("by"),
                                                                    "cause": info.get("cause")})
            cx.execute("DELETE FROM sync_removed WHERE kind='document' AND key=?", (doc_id,))
            cx.execute("DELETE FROM removed_docs WHERE doc_id=?", (doc_id,))
    finally:
        src.close()
    _remove_files(folder, name)
    return True


def listing(ws: Workspace) -> list[dict]:
    """The documents that can be restored, newest removal first: {"doc", "title", "at", "by", "why", "cause",
    "until"} ("by": the person id whose word removed it; "until": when `prune` removes the archive)."""
    folder, out = _folder(ws), []
    for r in ws._conn().execute("SELECT doc_id, title, at, by, why, cause, archive FROM removed_docs "
                                "ORDER BY at DESC, doc_id").fetchall():
        if not r[6] or not (folder / f"{r[6]}.sqlite").is_file():
            continue  # (its archive is gone: nothing to restore from)
        t = _when(r[2])
        out.append({"doc": r[0], "title": r[1], "at": r[2], "by": r[3], "why": r[4], "cause": r[5],
                    "until": (t + _dt.timedelta(days=DAYS)).isoformat() if t else None})
    return out


def prune(ws: Workspace) -> int:
    """Remove the archives older than `DAYS` days, with their rows, and archives no row names any more (left by a
    removal that was undone) once they are as old; returns how many archives went."""
    folder = _folder(ws)
    limit = _now() - _dt.timedelta(days=DAYS)
    gone = 0
    with ws.connect() as cx:
        rows = cx.execute("SELECT doc_id, at, archive FROM removed_docs").fetchall()
        named = {r[2] for r in rows if r[2]}
        for doc_id, at, name in rows:
            t = _when(at)
            if t is not None and t >= limit:
                continue
            _remove_files(folder, name)
            cx.execute("DELETE FROM removed_docs WHERE doc_id=?", (doc_id,))
            gone += 1
    if folder.is_dir():
        for f in folder.iterdir():
            stem = f.name.split(".", 1)[0]
            if stem in named:
                continue
            m = _NAME.fullmatch(stem)
            try:
                t = _dt.datetime.strptime(m.group(2), "%Y%m%dT%H%M%S").replace(tzinfo=_dt.timezone.utc) if m else None
            except ValueError:
                t = None
            if t is not None and t < limit:
                if f.is_dir():
                    shutil.rmtree(f, ignore_errors=True)
                else:
                    f.unlink(missing_ok=True)
                gone += f.suffix == ".sqlite"
    return gone

