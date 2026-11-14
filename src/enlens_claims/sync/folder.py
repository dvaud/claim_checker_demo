"""Working together through a shared folder (0.18, roadmap L5, and the groundwork of L3).

A team that already shares a folder (OneDrive, Dropbox, a university network drive) uses it to exchange its work item
by item, without a server and without sending zips by hand: each copy of a project writes what its person shared into
its own subfolder, as small numbered files that are never changed afterwards, and brings in what the others wrote,
with the rules of a merge from a zip (sync.merge). The project's database never goes into the folder; the zip
exchange stays, for one-off sharing and for colleagues without the folder.

The folder is chosen once per project and kept in the project's `config.json` (`shared_folder`), never in the database
or a zip: each computer has its own path to it ("C:\\Users\\Dávid\\OneDrive - Uni\\Team", "/Users/anna/Dropbox/Team").
In it, one folder per project, named by the project's id:

    <shared folder>/ENLENS-<project id, 8 characters>/
      project.json                which project, made by whom and when (written once, by whoever comes first)
      <person id>/                one per copy: ONLY that copy writes here, and it never reads its own
        person.json               the person's name, ENLENS version and sync format; whether they keep documents
                                  marked Only a local AI or No AI out of the folder
        head.json                 {"last": 41, "snapshot": 1}: the last bundle, written last and whole
        bundles/000041.zip        numbered without gaps, never rewritten
        docs/<id>.<text>.zip      the reading of a document (its text, pages and passages), once in the whole folder
        files/<sha1>.<ext>        the original file of a document, once in the whole folder
        read.json                 {"<person id>": 40}: how far this copy has brought in each colleague's bundles
        waiting.json              where this copy cannot go on reading a colleague, and why (only while it is held up)

**A bundle** (`bundles/NNNNNN.zip`) holds `bundle.json` (its format, `formats.stamp(needs=3)`: a copy before 0.18,
or one without the owner's rules (L2), cannot read it right and must not try; who wrote it, its number, the items it holds with their state and fingerprint, and a
stub of each document it names), `rows.sqlite` (a project database holding only those items' rows, `sharing.rows_of`,
with their marks and sync states, and the project's own rows written since the last bundle, `sharing.ProjectRows`)
and `frameworks/` (the codebooks among its items). Each item is written whole, as it is now, whenever it changed: a
later bundle with the same item supersedes earlier ones. A bundle written when this copy starts afresh in a folder
holds everything it shares (a *snapshot*, named in `head.json`): a colleague new to the folder starts there.

**What is written** (privacy, design note §2.6): only the items shared and the marks of those taken back
(`sharing.rows_of` is the one definition of an item's rows, the same as for a zip for a colleague); never a private
item, never this copy's own tables (versions, the log of work brought in, the glossary, the search index), never a
check or a set of themes with work under way (no queued task ever travels); the project's rows by the same rules as
`sharing.strip`, and the bibliography's attachments without their paths. Documents of every AI setting travel, as they
do in a zip, with the stricter setting winning in every copy; with the switch *Keep documents marked Only a local AI or
No AI out of the shared folder* (`config.json` `shared_folder_keep_out`, off by default; on in every copy once anyone
in the team has it on), their readings, files and the AI work on them are not written, nor the passages of them that a
shared check handed to the AI (`_keep_words_out`): colleagues add those files themselves, and whatever names them still
merges (merge.py's stubs, `sync_folder_docs`). What a person shared goes as it is: an excerpt's quoted words, a note's
words, a document's title. What a copy wrote of such a document before the switch was in force, or before the document
was marked, it takes out of its own subfolder at its next round, and starts afresh there (`_take_words_out`): a bundle
is never rewritten, so every bundle it wrote goes, and one new bundle holds all it shares. The same when an item it
wrote is taken back (*Unshare*) or removed: it leaves the folder, and only its mark or the note of its removal goes on
(`_taken_back_since`). No copy puts back a reading or file a colleague took out before it has heard why (`_taken_out`),
and a colleague's switch that cannot be read at the moment counts as last seen (`keep_out_state`). A document that
reached this copy another way (a colleague keeps it out, and this copy's person added the file) is as strict here as
the folder said, from the moment it is added (`hold_settings`). The folder is never the project's own folder, nor one
that holds it or ENLENS's folder (`check_folder`).

**Reading.** For each colleague, the bundles not brought in yet, in order, go into one scratch project, fed to
`merge._Merge` as a colleague's zip is: every rule of a merge holds. A reading is fetched only for a document new
here, a file only with it (and checked against its sha1), so a large corpus is not copied every round. It stops at a
gap (a bundle the cloud has not delivered yet, or one still arriving: tried again next round), at a bundle of a newer
format (that person's stream only, in the plain words of `formats.problem`; the others go on), and before a bundle
whose new documents have not arrived; a damaged bundle, one larger than ENLENS reads (`_MAX_META` and the others: a
colleague's file never fills this computer's memory), or one whose merge fails, stops that colleague's stream only.
Each bundle is unpacked once per round (`_Opened`). Before anyone's work is merged, what the waiting bundles say an
item's owner took back is noted (`_withdrawals_first`), so the order in which colleagues are read changes nothing.
A copy held up says where in its own subfolder (`waiting.json`); the writer's copy reads it, and when the bundle is
damaged or gone on its own computer too, or names a reading no copy can write again, it starts afresh, so nobody waits
for ever for what will never come (`_asked_to_begin_again`).
Names that are not exactly ENLENS's own are never read: a cloud service's conflict copies (`000041 (1).zip`) and
half-written `.part` files. What was brought in is recorded (`sync_folder_read`, with the writer's epoch, and
`read.json`) and logged as `sync.bring_in` logs it.

`sync_now(ws)` reads, then writes (so a copy writes with its colleagues' decisions in force: the stricter AI setting,
what they took back); `status(ws)` says what the Team tab shows. Both are safe when the folder is not
there: nothing in the project changes until a merge, which reads only the scratch copy, runs in one transaction. A
round can be stopped part-way (`should_stop`: the person stops it, the app quits); it ends between two steps, and the
next round carries on from there. A round looks only at what changed since the last one (`changes.py`: counters kept by
triggers, and what the round remembers in this process), so a round that finds nothing new costs almost nothing.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
import zlib
from pathlib import Path
from typing import Any, Callable, Iterable

from .. import __version__, people, sharing
from ..store import Workspace, now, scratch as scratch_settings
from . import changes, formats
from .common import (DOC_ID, LOCAL_ONLY, READING_TABLES as _READING_TABLES, UNFINISHED, _TOKEN, _cols, _pk, _rows, _sha,
                     base_id, text_fp)
from .fingerprints import _PERSONAL, _running, record_seen_since

FOLDER = "shared_folder"            # config.json: the folder the team shares (a path on this computer)
KEEP_OUT = "shared_folder_keep_out"  # config.json: keep documents marked Only a local AI or No AI out of it
TEAM = "ENLENS-"
BUNDLE_FORMAT = "enlens-bundle"
NEEDS = 4                           # a bundle needs format 4 (formats.py): a copy without roles must not merge it
JOB = "folder-sync"                 # the kind of job of a round (gui/api_folder.py)
_BUNDLE = re.compile(r"(\d{6,})\.zip")
_READING = re.compile(r"[0-9a-f]{12}\.[0-9a-f]{16}\.zip")
_FILE = re.compile(r"([0-9a-f]{40})\.([a-z0-9]{1,8})")
_NOT_IN_FP = {"sync_seen", "sync_copies"}            # they travel, but change whenever copies exchange
_VOLATILE = {"queued", "queued_at", "claimed_by", "claimed_at"}  # where a task waits, not what it is
_RESTRICTED = ("local", "none")
_HELD_UP = ("gap", "arriving", "damaged", "documents")  # why a colleague's bundle cannot be read (yet): `_waiting_json`
# The most of a colleague's file that is read, by what it is (its size unpacked, as the zip says it; a zip member is
# never read past that size). Each is many times what ENLENS writes for a large project: a bundle's description holds a
# short stub per document (100,000 documents are about 50 MB), a reading one document's text and passages (a book of
# a thousand pages is about 20 MB), a codebook a few thousand codes. The database is unpacked to disk, never into
# memory, and read a slice at a time. A file larger than these is held up with a plain message: a damaged or hostile
# file cannot fill this computer's memory or disk.
_MAX_META = 64 * 1024 ** 2        # bundle.json
_MAX_ROWS = 4 * 1024 ** 3         # rows.sqlite
_MAX_READING = 256 * 1024 ** 2    # reading.json of a document
_MAX_CODEBOOK = 64 * 1024 ** 2    # each file of a codebook

Progress = Callable[[str, str, dict], None]
ShouldStop = Callable[[], bool]   # a round asked to stop part-way (the job was cancelled, the app quits): `sync_now`


class FolderProblem(ValueError):
    """Why the shared folder cannot be used now, in words for a researcher."""

    def __init__(self, message: str, kind: str = "folder"):
        super().__init__(message)
        self.kind = kind


# ---------------------------------------------------------------------------------------------
# small helpers: files written whole, read without trust
# ---------------------------------------------------------------------------------------------
def _json(path: Path) -> dict | None:
    try:
        out = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return out if isinstance(out, dict) else None


def _put_bytes(path: Path, data: bytes) -> None:
    """Written whole or not at all: a reader (or the cloud service) never sees half a file under its name."""
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    os.replace(part, path)


def _put_json(path: Path, obj: dict) -> None:
    _put_bytes(path, json.dumps(obj, indent=1, ensure_ascii=False).encode("utf-8"))


def _copy_whole(src: Path, dest: Path) -> None:
    part = dest.with_name(dest.name + ".part")
    shutil.copyfile(src, part)
    os.replace(part, dest)


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _say(progress: Progress | None, step: str, message: str, info: dict | None = None) -> None:
    if progress:
        progress(step, message, info or {})


def _who(name: str | None) -> str:
    return (name or "").strip() or "a colleague"


def reading_name(doc_id: str, fp: str) -> str:
    """The file name of a reading in `docs/`: short, lower case, the same in every copy (a document id may hold capital
    letters, and two names that differ only in case are one file on Windows and macOS)."""
    return f"{_sha(doc_id)[:12]}.{fp}.zip"


def _ext(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", Path(name).suffix.lower())[:8] or "bin"


def _safe_name(name: str | None, fallback: str) -> str:
    """A file name to keep an original under in this project: its own name without folders or characters file
    systems refuse, not too long."""
    n = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', " ", Path(str(name or "").replace("\\", "/")).name).strip(" .")
    if not n:
        return fallback
    if len(n) > 100:
        stem, suf = Path(n).stem, Path(n).suffix[:12]
        n = stem[:100 - len(suf)].rstrip(" .") + suf
    return n


# ---------------------------------------------------------------------------------------------
# the folder of a project
# ---------------------------------------------------------------------------------------------
def chosen(ws: Workspace) -> Path | None:
    """The shared folder chosen for this project on this computer (None: none). 0.18.0rc2 (L6): with a storage space
    of the team's own, the copy of the space kept on this computer (`space.mirror_of`), which every rule here works on
    as on a shared folder."""
    from . import space

    m = space.mirror_of(ws)
    if m is not None:
        return m
    v = ws.config.get(FOLDER)
    return Path(v) if isinstance(v, str) and v.strip() else None


def team_name(ws: Workspace) -> str:
    return f"{TEAM}{ws.project_uid()[:8]}"


def _set_config(ws: Workspace, **changes: Any) -> None:
    try:
        cfg = json.loads(ws.config_path.read_text(encoding="utf-8")) if ws.config_path.exists() else {}
    except (OSError, ValueError):
        cfg = {}
    for k, v in changes.items():
        if v is None:
            cfg.pop(k, None)
        else:
            cfg[k] = v
    ws.config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    ws._config_cache = None


def _within(a: Path, b: Path) -> bool:
    """Whether `a` is `b` or inside it, as the file system sees names: without regard to letter case on Windows and
    macOS, and with accents written either way (macOS writes them decomposed)."""
    import sys
    import unicodedata

    fold = sys.platform in ("win32", "darwin")

    def parts(x: Path) -> list[str]:
        return [unicodedata.normalize("NFC", s).casefold() if fold else unicodedata.normalize("NFC", s)
                for s in x.parts]

    pa, pb = parts(a), parts(b)
    return pa[:len(pb)] == pb


def check_folder(ws: Workspace, raw: Any) -> Path:
    """The folder a person chose, checked: it exists, ENLENS can write in it, it is not inside the project's own folder,
    and it does not hold the project nor ENLENS's own folder (the cloud service would copy the project's database,
    every private item in it, to the team). The project's own folder in it (`ENLENS-<id>`) chosen by mistake stands
    for the folder that holds it. Raises FolderProblem."""
    if not isinstance(raw, str) or not raw.strip():
        raise FolderProblem("Choose the folder your team shares (OneDrive, Dropbox, a network drive).")
    p = Path(raw.strip()).expanduser()
    if not p.is_absolute():
        raise FolderProblem(f"Give the whole path of the folder (“{raw.strip()[:200]}” is not one).")
    try:
        p = p.resolve()
    except OSError as e:
        raise FolderProblem(f"The folder {p} cannot be reached ({e.strerror or e}).") from e
    if not p.is_dir():
        raise FolderProblem(f"There is no folder {p} on this computer. Choose the folder your team shares; if it is on "
                            "a network drive or in the cloud, make sure it is connected.")
    if p.name == team_name(ws):
        p = p.parent
    from ..home import home

    root = Path(ws.root).resolve()
    if _within(p, root):
        raise FolderProblem("The shared folder cannot be inside this project's own folder: choose the folder your team "
                            "shares (OneDrive, Dropbox, a network drive).")
    if _within(root, p):
        raise FolderProblem("The shared folder cannot be a folder that holds this project: the cloud service would copy "
                            "the project's own database, with everything you keep private, to your team. Choose or make "
                            "a folder beside it, for example “ENLENS team” in the folder you share.")
    if _within(home().resolve(), p):
        raise FolderProblem("The shared folder cannot be a folder that holds ENLENS's own folder, where every project's "
                            "database is kept: the cloud service would copy them to your team. Choose or make a folder "
                            "beside it.")
    probe = p / f".enlens-test-{uuid.uuid4().hex[:8]}"
    try:
        probe.write_bytes(b"ENLENS")
        probe.unlink()
    except OSError as e:
        raise FolderProblem(f"ENLENS cannot write in {p} ({e.strerror or e}). Choose a folder you may write in.") from e
    return p


def set_folder(ws: Workspace, raw: Any) -> dict:
    """Use this shared folder for the project (checked: `check_folder`). Nothing is written in it until the next round
    (`sync_now`). Returns `status`."""
    p = check_folder(ws, raw)
    from . import space

    if space.configured(ws) is not None:  # (a folder instead of the storage space: the space is left on this computer)
        space.leave(ws)
    before = chosen(ws)
    _set_config(ws, **{FOLDER: str(p)})
    if before is None or Path(before) != p:
        _note(ws, "folder-chosen", f"Chose the shared folder {p} for working together.")
        there = str((_json(p / team_name(ws) / "project.json") or {}).get("folder_id") or "")
        with ws.connect() as cx:  # another folder: this copy's record holds for it only once its project.json says so
            row = cx.execute("SELECT fp FROM sync_written WHERE kind='head' AND key=''").fetchone()
            if not (there and row and row[0] == there):  # (the same folder chosen again: what it wrote there stays)
                cx.execute("UPDATE sync_written SET fp='' WHERE kind='head' AND key=''")
    return status(ws)


def clear_folder(ws: Workspace) -> dict:
    """Stop using the shared folder for the project. Nothing in the folder is removed (it is the team's), and what came
    in stays. Returns `status`."""
    from . import space

    if space.configured(ws) is not None:
        space.leave(ws)
        return status(ws)
    before = chosen(ws)
    _set_config(ws, **{FOLDER: None})
    if before is not None:
        _note(ws, "folder-cleared", f"Stopped working together through the shared folder {before}.")
    return status(ws)


def set_keep_out(ws: Workspace, on: bool) -> dict:
    """The project's switch: keep documents marked Only a local AI or No AI out of the shared folder (their readings,
    files and the AI work on them). Returns `status`."""
    _set_config(ws, **{KEEP_OUT: bool(on)})
    return status(ws)


def _note(ws: Workspace, kind: str, text: str) -> None:
    """The research log says when the folder was chosen or left (an entry about this copy only: never sent)."""
    from .. import researchlog

    with ws.connect() as cx:
        researchlog.record(cx, "sync", text, data={"shared_folder": kind})


def _people_dirs(team: Path) -> list[Path]:
    """The subfolders of the copies in the project's folder: exactly a person id, nothing else."""
    try:
        return sorted(p for p in team.iterdir() if people.ID_RE.fullmatch(p.name) and p.is_dir())
    except OSError:
        return []


def keep_out_state(ws: Workspace, team: Path | None = None, me: str | None = None, last_known: bool = False) -> dict:
    """{"mine": the switch in this copy, "colleagues": [names of those who have it on], "in_force": either}: documents
    marked Only a local AI or No AI stay out of the folder in every copy once anyone has the switch on (the stricter
    wins, as with the AI settings themselves).

    `last_known` (no `team`): the folder cannot be read now (offline), so the colleagues are those this copy last saw
    with the switch on (`_remember_switches`, in the project's database, never in the folder), and the answer says so
    ("last_known": true), so the Team tab does not lose who keeps it on while the folder is away."""
    mine = bool(ws.config.get(KEEP_OUT))
    by = []
    if team is None and last_known:
        cx = ws._conn()
        me = me or people.me()
        names = {r[0]: r[1] for r in cx.execute("SELECT person_id, name FROM people")}
        by = [_who(names.get(pid)) for pid, on in cx.execute("SELECT key, fp FROM sync_written WHERE kind='keep' "
                                                             "ORDER BY key") if on == "1" and pid != me]
        return {"mine": mine, "colleagues": by, "in_force": mine or bool(by), "last_known": True}
    if team is not None:
        me = me or people.me()
        cx = ws._conn()
        last = {r[0]: r[1] for r in cx.execute("SELECT key, fp FROM sync_written WHERE kind='keep'")}
        for p in _people_dirs(team):
            if p.name != me:
                pj = _json(p / "person.json")
                # a file that cannot be read just now (the cloud service is replacing it, the drive is slow) says
                # nothing: the switch is as this copy last saw it (`_remember_switches`), never off for a round
                on = pj.get("keep_out") is True if pj is not None else last.get(p.name) == "1"
                if on:
                    name = (pj or {}).get("name") or (cx.execute("SELECT name FROM people WHERE person_id=?",
                                                                  (p.name,)).fetchone() or [None])[0]
                    by.append(_who(name))
    return {"mine": mine, "colleagues": by, "in_force": mine or bool(by)}


def _switches(team: Path, me: str) -> list[tuple[str, dict | None]]:
    """[(person id, their `person.json` or None)] of every copy's subfolder (this copy's own without its file): what
    `_remember_switches` keeps, read from the folder before the project's database is written."""
    return [(p.name, _json(p / "person.json") if p.name != me else None) for p in _people_dirs(team)]


def _remember_switches(cx: sqlite3.Connection, team: Path, me: str,
                       found: list[tuple[str, dict | None]] | None = None) -> None:
    """How each colleague's switch stands, as last read from their `person.json` (`sync_written` kind "keep"; the Team
    tab shows it while the folder cannot be read, `keep_out_state`). A colleague whose subfolder is gone (they left)
    is forgotten, as `keep_out_state` leaves them out while the folder can be read. Every colleague's subfolder seen is
    noted (kind "seen", `seen_there`). `found`: the folder as `_switches` read it (None: read now)."""
    found = _switches(team, me) if found is None else found
    last = {r[0]: r[1] for r in cx.execute("SELECT key, fp FROM sync_written WHERE kind='keep'")}
    seen = {r[0] for r in cx.execute("SELECT key FROM sync_written WHERE kind='seen'")}
    cx.executemany("INSERT OR IGNORE INTO sync_written(kind, key, fp, seq, at) VALUES ('seen', ?, '', NULL, ?)",
                   [(pid, now()) for pid, _pj in found if pid != me and pid not in seen])
    for pid, pj in found:
        on = None if pj is None else "1" if pj.get("keep_out") is True else "0"
        if on is not None and last.get(pid) != on:  # (written only when it changed)
            cx.execute("INSERT OR REPLACE INTO sync_written(kind, key, fp, seq, at) VALUES ('keep', ?, ?, NULL, ?)",
                       (pid, on, now()))
    if found:  # (a listing that failed says nothing of who left)
        there = {pid for pid, _pj in found}
        for pid in set(last) - there:
            cx.execute("DELETE FROM sync_written WHERE kind='keep' AND key=?", (pid,))


def seen_there(cx: sqlite3.Connection, pid: str) -> bool:
    """Whether this copy has seen a colleague's subfolder in the folder it uses now: it brought in their work, or a
    round found their subfolder (`_remember_switches`). A subfolder never seen is not one that went: its person may
    not have chosen the folder yet, or the cloud service has not delivered it."""
    return bool(cx.execute("SELECT 1 FROM sync_folder_read WHERE person_id=?", (pid,)).fetchone() or
                cx.execute("SELECT 1 FROM sync_written WHERE kind IN ('seen', 'keep') AND key=?", (pid,)).fetchone())


def _open_team(ws: Workspace, create: bool) -> tuple[Path, dict]:
    """The project's folder in the shared folder, and what its `project.json` says. Raises FolderProblem when no
    folder is chosen, when it cannot be reached, or when the folder of this name holds another project."""
    base = chosen(ws)
    if base is None:
        raise FolderProblem("Choose a shared folder for this project first.", "no_folder")
    if not base.is_dir():
        raise FolderProblem(f"The shared folder {base} cannot be reached: the drive may not be connected, or the folder "
                            "was moved or renamed. Nothing was changed; ENLENS tries again on the next round.",
                            "unreachable")
    uid = ws.project_uid()
    team = base / team_name(ws)
    if create:
        team.mkdir(exist_ok=True)
    info = _json(team / "project.json")
    if info is None and create:
        # not there (a new folder), or not brought by the cloud service yet, or removed by hand. Made anew only when
        # no colleague wrote here, or as this copy knows it (its folder_id): a new identity would make every copy start
        # over
        me = people.me()
        row = ws._conn().execute("SELECT fp FROM sync_written WHERE kind='head' AND key=''").fetchone()
        known_id = row[0] if row and row[0] else None
        if known_id is None and any(p.name != me for p in _people_dirs(team)):
            raise FolderProblem(f"The shared folder has not brought this project's own file ({team.name}/project.json) "
                                "to this computer yet. Nothing was written or read; ENLENS tries again on the next "
                                "round.", "arriving")
        _put_json(team / "project.json", {"project_uid": uid, "name": Path(ws.root).name,
                                          "made_by": {"id": me, "name": people.my_name()},
                                          "made_at": now(), "folder_id": known_id or uuid.uuid4().hex,
                                          "app_version": __version__})
        info = _json(team / "project.json")
    info = info or {}
    known = {uid, *(ws.meta("project_uids_known") or [])}
    if info.get("project_uid") and info["project_uid"] not in known:
        raise FolderProblem(f"The folder {team.name} in the shared folder holds another project (“"
                            f"{str(info.get('name') or '?')[:80]}”). Nothing was written or read.", "other_project")
    return team, info


# ---------------------------------------------------------------------------------------------
# an item as it is written
# ---------------------------------------------------------------------------------------------
def _mark(r: dict | None) -> dict | None:
    """An item's mark as it leaves: a withdrawn item's without its title (`sharing.strip` does the same)."""
    if r is None:
        return None
    return {"state": r.get("state"), "owner": r.get("owner"), "by": r.get("by"), "at": r.get("at"),
            "title": r.get("title") if r.get("state") == "shared" else None}


def _codebook_files(ws: Workspace, name: str) -> dict[str, bytes]:
    """A codebook's CSV and side file: the project's own, or one this project uses from the home folder."""
    from ..home import home

    out = {}
    for folder in (Path(ws.root) / "frameworks", home() / "frameworks"):
        if (folder / f"{name}.csv").is_file():
            for ext in ("csv", "json"):
                f = folder / f"{name}.{ext}"
                if f.is_file():
                    out[f"frameworks/{name}.{ext}"] = f.read_bytes()
            break
    return out


def item_fp(kind: str, key: str, got: dict[str, list[dict]], mark: dict | None, files: dict[str, bytes]) -> str:
    """An item's fingerprint as written: its rows, its mark and its files, without what differs between copies holding
    the same (row numbers, a review's number, the judgement in force, where a task waits, the sync states)."""
    parts = [kind, key, json.dumps(mark, sort_keys=True, default=str)]
    for t in sorted(got):
        if t in _NOT_IN_FP:
            continue
        rows = sorted(json.dumps({c: v for c, v in r.items() if c not in (sharing.ROWID, "review_id")
                                  and c not in _PERSONAL and not (t == "tasks" and c in _VOLATILE)},
                                 sort_keys=True, default=str, ensure_ascii=False) for r in got[t])
        parts.append(t + "\n" + "\n".join(rows))
    parts += [f"{n}:{_sha(files[n])}" for n in sorted(files)]
    return _sha(*parts)[:20]


def _busy(kind: str, got: dict[str, list[dict]]) -> bool:
    """Work under way on the item: a check or a set of themes with a task not answered (a colleague's merge would leave
    it out until done, as from a zip), or a codebook whose labelling runs. Queued work never travels."""
    unit = {"hypotheses": got.get("hypotheses", []), "tasks": got.get("tasks", [])}
    if kind in ("check", "themes"):
        hyp = unit["hypotheses"][0] if unit["hypotheses"] else {}
        if hyp.get("queue") == "waiting" or any(t.get("status") in UNFINISHED for t in unit["tasks"]):
            return True
    return kind in ("check", "themes", "codebook") and _running(unit)


_TEXT_KEYS = ("text", "before", "after", "context")  # where a task's payload holds a document's own words


def _blank(obj: Any, kept_out: set[str]) -> Any:
    """A task's payload with the words of documents kept out of the folder taken out: each passage of such a document
    keeps its ids, title and page, its text is empty and it says `kept_out`."""
    if isinstance(obj, list):
        return [_blank(v, kept_out) for v in obj]
    if not isinstance(obj, dict):
        return obj
    doc = obj.get("doc_id") if isinstance(obj.get("doc_id"), str) else None
    pid = obj.get("passage_id") if isinstance(obj.get("passage_id"), str) else None
    if doc in kept_out or (pid and pid.split(":", 1)[0] in kept_out):
        return {k: ("" if k in _TEXT_KEYS and isinstance(v, str) else _blank(v, kept_out)) for k, v in obj.items()} | \
            {"kept_out": True}
    return {k: _blank(v, kept_out) for k, v in obj.items()}


def _keep_words_out(got: dict[str, list[dict]], kept_out: set[str]) -> dict[str, list[dict]]:
    """With the switch on: the passages a shared item handed to the AI from documents kept out of the folder (in its
    tasks' payloads) are written without their text (`_blank`). What the person shared goes as it is (an excerpt's
    quoted words, a note's words, a judgement, the AI's answers, which hold only its quotes). Tasks and answers are
    never part of a unit's fingerprint (fingerprints._fp), so the colleague's copy compares the item alike, and what
    came this way never replaces the writer's own; the result pages read the passages' ids, not their text."""
    if not kept_out or not got.get("tasks"):
        return got
    tasks = []
    for t in got["tasks"]:
        if sharing.task_names_kept_out(t["task_id"], t.get("payload_json"), kept_out):
            try:
                t = dict(t, payload_json=json.dumps(_blank(json.loads(t.get("payload_json") or "null"), kept_out),
                                                    ensure_ascii=False))
            except ValueError:
                t = dict(t, payload_json=None)
        tasks.append(t)
    return {**got, "tasks": tasks}


def kept_out_docs(ws: Workspace, cx: sqlite3.Connection, in_force: bool) -> set[str]:
    """The documents whose words stay out of the folder while the switch is in force: those marked Only a local AI or
    No AI here, and those this copy does not hold (removed here, or never added) that a colleague's copy marks so
    (`sync_folder_docs`): a check shared here may still hold their passages in what it handed to the AI. And those this
    copy wrote in words and has removed since, unless they were last written as a document an AI in the cloud may
    read (`_words_fp`; one written before that was recorded counts as restricted): their reading and file stay in
    this copy's subfolder until it takes them out (`_take_words_out`), and nothing else here says how they were set."""
    if not in_force:
        return set()
    levels = ai_settings(ws, cx)
    heard = {r[0] for r in cx.execute("SELECT doc_id FROM sync_folder_docs WHERE ai_access IN ('local', 'none')")}
    gone = {d for d, fp in cx.execute("SELECT key, fp FROM sync_written WHERE kind='words'")
            if d not in levels and _words_said(fp).get("ai") != "cloud"}
    return {d for d, lv in levels.items() if lv in _RESTRICTED} | (heard - set(levels)) | gone


def _words_fp(level: str | None, sha1: str | None) -> str:
    """What this copy keeps of a document it wrote in words (`sync_written` kind "words"): who might read it with AI
    then, and its file, so they are known after the document is removed here."""
    return json.dumps({"ai": level, "sha1": (sha1 or "").split("~")[0] or None}, sort_keys=True)


def _words_said(fp: str | None) -> dict:
    try:
        out = json.loads(fp or "")
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


def _item(ws: Workspace, cx: sqlite3.Connection, kind: str, key: str, r: dict, kept_out: set[str] = frozenset()) -> dict:
    """An item as this copy would write it now: {"kind", "key", "state", "fp", "rows", "files", "busy"}."""
    mark = _mark(r)
    if r.get("state") != "shared":  # taken back: its mark alone
        return {"kind": kind, "key": key, "state": r.get("state"), "fp": item_fp(kind, key, {}, mark, {}), "rows": {},
                "files": {}, "busy": False, "title": None, "mark": mark}
    got = _keep_words_out(sharing.rows_of(cx, kind, key), kept_out)
    files = _codebook_files(ws, key) if kind == "codebook" else {}
    return {"kind": kind, "key": key, "state": "shared", "fp": item_fp(kind, key, got, mark, files), "rows": got,
            "files": files, "busy": _busy(kind, got), "title": r.get("title") or key, "mark": mark,
            "here": sharing.exists(cx, ws.root, kind, key)}  # (False: removed here; it is its note of removal)


def ai_settings(ws: Workspace, cx: sqlite3.Connection) -> dict[str, str]:
    """Who may read each document with AI, as the project says: its own setting, else the project's default; a
    colleague's other reading of a file (a sync-clash copy) at least as strict as yours. Not as this installation
    allows (cloud models switched off on this computer belong to the computer, not to the document): that neither
    keeps a document out of the folder nor reaches a colleague's copy, as in a zip (merge.py works the levels out in
    the receiving copy)."""
    from ..access import LEVELS, most

    dflt = ws.config.get("ai_access_default")
    dflt = dflt if dflt in LEVELS else "cloud"
    out = {d: (lv if lv in LEVELS else dflt) for d, lv in cx.execute("SELECT doc_id, ai_access FROM documents")}
    for k, o in cx.execute("SELECT key, of_key FROM sync_copies WHERE kind='document'").fetchall():
        if k in out and o in out:
            out[k] = most([out[k], out[o]])
    return out


def hold_settings(ws: Workspace, cx: sqlite3.Connection, doc_ids: Iterable[str] | None = None) -> list[dict]:
    """The stricter AI setting holds for a document that reaches this copy by another way than the folder: a document
    a colleague keeps out of it, whose file this copy's person adds themselves (ingest calls this, in the transaction
    that adds it) or that comes in a third colleague's zip (merge.py calls it for the new documents), is as strict here
    as the folder said (`sync_folder_docs.ai_access`). Without this it would follow this project's setting for new
    documents until the colleague's next change to it came in: an AI could read it here meanwhile, and this copy
    would write its words into the folder. Only at that moment, for the documents named (`doc_ids`; None: every
    document): a document both copies hold is the merge's (`_stricter`), and a setting two colleagues both loosen
    stays loosened. Returns [{"doc_id", "title", "was", "now"}] of the documents made stricter; the research log says
    so."""
    from .. import researchlog
    from ..access import RANK, most, relabel

    heard = _rows(cx, "SELECT doc_id, sha1, ai_access FROM sync_folder_docs WHERE ai_access IN ('local', 'none')")
    if not heard:
        return []
    by_id = {h["doc_id"]: h["ai_access"] for h in heard}
    by_file = {(h["sha1"] or "").split("~")[0]: h["ai_access"] for h in heard if h["sha1"]}
    levels = ai_settings(ws, cx)
    wanted = None if doc_ids is None else set(doc_ids)
    out = []
    for doc, sha1, title in cx.execute("SELECT doc_id, sha1, title FROM documents").fetchall():
        if wanted is not None and doc not in wanted:
            continue
        said = most([by_id.get(doc), by_file.get((sha1 or "").split("~")[0])])
        if RANK[said] <= RANK[levels.get(doc) or "cloud"]:
            continue
        cx.execute("UPDATE documents SET ai_access=? WHERE doc_id=?", (said, doc))
        out.append({"doc_id": doc, "title": title, "was": levels.get(doc) or "cloud", "now": said})
        researchlog.record(cx, "ai-access", f"Who may read {researchlog.quoted(title, 80)} with AI: "
                                            f"{researchlog.access_words(said)}, as in a colleague's copy of this "
                                            "project (the stricter setting holds in every copy).",
                           "document", doc, title, data={"documents": [doc], "setting": said, "from": "colleague"})
    if out:
        relabel(cx)  # work waiting for an AI that may no longer read it leaves the queue
    return out


def _row_key(table: str, ident: tuple) -> str:
    return _sha("row", table, json.dumps(ident, default=str, ensure_ascii=False))[:20]


# ---------------------------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------------------------
def _reader_cx(ws: Workspace) -> sqlite3.Connection:
    """A connection that reads the project as it is at one moment (a read transaction in WAL mode), without holding
    up the app's writes while a bundle is put together."""
    cx = sqlite3.connect(ws.db_path, timeout=60, isolation_level=None)
    cx.execute("BEGIN")
    return cx


def _written(cx: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """What this copy wrote, but the project's rows (one per row: they are looked up as they are read, `_plan_rows`)."""
    return {(k, key): fp for k, key, fp in cx.execute("SELECT kind, key, fp FROM sync_written WHERE kind != 'row'")}


def _same_folder(cx: sqlite3.Connection, folder_id: str) -> int:
    """This copy's record of the folder holds for the folder it now uses: another folder (another path chosen, or the
    project's folder in it made anew) starts the record afresh, what was written and how far each colleague was read.
    Returns the number of the last bundle this copy wrote (0: none yet in this folder; numbers go on in a new one)."""
    row = cx.execute("SELECT fp, seq FROM sync_written WHERE kind='head' AND key=''").fetchone()
    if row is not None and (row[0] == folder_id or not folder_id):  # (project.json not readable now: no change)
        return int(row[1] or 0)
    if not folder_id:
        return 0
    if row is not None:
        cx.execute("DELETE FROM sync_written WHERE kind != 'head'")
        cx.execute("DELETE FROM sync_folder_read")
    cx.execute("INSERT OR REPLACE INTO sync_written(kind, key, fp, seq, at) VALUES ('head', '', ?, ?, ?)",
               (folder_id, int(row[1] or 0) if row else 0, now()))
    return 0


def _own(mine: Path) -> tuple[dict, int]:
    """(this copy's `head.json`, the number of the last bundle in its subfolder): what `_start` goes on from."""
    head = _json(mine / "head.json") or {}
    try:
        files = max((int(m.group(1)) for f in (mine / "bundles").iterdir() if (m := _BUNDLE.fullmatch(f.name))),
                    default=0)
    except OSError:
        files = 0
    return head, files


def _start(cx: sqlite3.Connection, mine: Path, folder_id: str,
           own: tuple[dict, int] | None = None) -> tuple[int, bool, int, str]:
    """(the number of the next bundle, whether it is a snapshot, the snapshot before it, the epoch). When this copy has not
    written to this folder yet, or the folder lost what it wrote (its subfolder emptied), it starts afresh: everything
    it contributes goes into the next bundle, a snapshot, where a colleague new to the folder starts reading it. What
    came from colleagues (recorded without a bundle number) is in their own subfolders, and is not written again.
    Numbers are never reused: a reader who read up to 40 goes on at 41. Each start afresh is a new epoch (head.json),
    so a reader goes to the new snapshot even when the numbers began anew (this copy lost its record and its subfolder
    both)."""
    _same_folder(cx, folder_id)
    local_last = int(cx.execute("SELECT seq FROM sync_written WHERE kind='head' AND key=''").fetchone()[0] or 0)
    head, files = own if own is not None else _own(mine)
    there = _int(head.get("last")) or 0
    snap = _int(head.get("snapshot")) or 0
    epoch = head.get("epoch") if isinstance(head.get("epoch"), str) and head.get("epoch") else None
    if local_last == 0 or there < local_last or not 0 < snap <= there or not epoch:  # (nothing to go on from)
        cx.execute("DELETE FROM sync_written WHERE kind != 'head' AND seq IS NOT NULL")
    fresh = not cx.execute("SELECT 1 FROM sync_written WHERE kind != 'head' AND seq IS NOT NULL LIMIT 1").fetchone()
    seq = max(local_last, there, files) + 1
    return seq, fresh, (seq if fresh else snap), (uuid.uuid4().hex[:12] if fresh or not epoch else epoch)


def _begin_again(mine: Path) -> list[Path]:
    """This copy's bundles go from its subfolder, so that `_start` starts it afresh: one bundle with everything it
    shares, under a new epoch, where every colleague goes on reading. Its readings and files stay. Returns the bundles
    that could not be removed now (`_remove`; `_prune` removes them on a later round)."""
    (mine / "head.json").unlink(missing_ok=True)  # first: a colleague reading now finds nothing new, not half of it
    try:
        old = sorted(f for f in (mine / "bundles").iterdir() if f.is_file())
    except OSError:
        old = []
    return _remove(old)


OTHER_COMPUTER = ("Another computer is writing into this folder under your name{since}. Nothing was written from "
                  "here, so nothing is lost. If you use ENLENS on both computers, choose “Use both computers”.")


def other_computer(cx: sqlite3.Connection, mine: Path, folder_id: str | None = None) -> dict | None:
    """roles (DESIGN-roles §4.11): whether another computer writes into this copy's subfolder under this person's id (a
    data folder copied to it, a project zip moved by hand): {"since": when it last wrote} or None. Nothing is written
    or deleted in the subfolder while it does (`write`, `read`).

    Its `head.json` names the installation that wrote it last: this one's goes on. Another one, or none (written before
    roles), goes on only when this copy's own record of the folder holds what the file says (the number of its last
    bundle, in this folder): this copy wrote it, from a data folder that has since moved (a copied data folder gets a new
    installation id, home.installation_id). No `head.json`: nothing to take the place of."""
    from .. import home

    h = _json(mine / "head.json")
    if h is None:
        return None
    iid = h.get("installation")
    if isinstance(iid, str) and iid and iid == home.installation_id():
        return None
    row = cx.execute("SELECT fp, seq FROM sync_written WHERE kind='head' AND key=''").fetchone()
    same = row is not None and (not folder_id or row[0] == folder_id)
    if same and int(row[1] or 0) > 0 and _int(h.get("last")) == int(row[1] or 0):
        return None
    return {"since": h.get("at") if isinstance(h.get("at"), str) else None}


def _other_computer_problem(found: dict) -> FolderProblem:
    since = found.get("since")
    return FolderProblem(OTHER_COMPUTER.format(since=f" (since {since[:10]})" if since else ""), "other_computer")


def _claim_head(mine: Path) -> None:
    """A `head.json` this copy wrote (the guard said so) that does not name this installation yet gets its id, so a
    copy of this data folder elsewhere is told apart from the next round on (DESIGN-roles §3.5)."""
    from .. import home

    h = _json(mine / "head.json")
    if h is not None and h.get("installation") != home.installation_id():
        _put_json(mine / "head.json", {**h, "installation": home.installation_id()})


def _remove(files: Iterable[Path]) -> list[Path]:
    """Remove each file that can be removed now; returns those that cannot (on Windows, a file the cloud service is
    copying at this moment): one held file never keeps the others in the folder."""
    left = []
    for f in files:
        try:
            f.unlink(missing_ok=True)
        except OSError:
            left.append(f)
    return left


def _still_there(left: list[Path]) -> FolderProblem:
    return FolderProblem(f"ENLENS could not remove {len(left)} of its files from the shared folder yet (another "
                         "program, such as the cloud service, is using them). Nothing new was written; ENLENS tries "
                         "again on the next round.", "unreachable")


def _asked_to_begin_again(ws: Workspace, cx: sqlite3.Connection, team: Path, mine: Path, me: str,
                          kept_out: set[str]) -> bool:
    """Whether a colleague is held up at a bundle of this copy that will never reach them as it is (their
    `waiting.json`): the bundle is damaged or gone here too, where it was written, or it names a reading that is not in
    the folder and that this copy cannot write again (it no longer holds that reading). Beginning again mends both. A
    bundle that is whole here is only late for them: the cloud service's to deliver, nothing to mend."""
    head = _json(mine / "head.json") or {}
    epoch, last = head.get("epoch"), _int(head.get("last")) or 0
    if not (isinstance(epoch, str) and epoch and last):
        return False
    can_write: set[str] | None = None
    for p in _people_dirs(team):
        note = (_json(p / "waiting.json") or {}).get(me) if p.name != me else None
        if not isinstance(note, dict) or note.get("epoch") != epoch:
            continue
        seq = _int(note.get("seq"))
        if not seq or not 0 < seq <= last:
            continue
        f = mine / "bundles" / f"{seq:06d}.zip"
        try:
            _bundle_meta(f, me, seq, ws.project_uid(), "your", epoch)
            whole = _rows_readable(f)
        except _Stop:
            whole = False
        if not whole:
            return True
        names = [n for n in note.get("readings") or [] if isinstance(n, str) and _READING.fullmatch(n)]
        if note.get("kind") == "documents" and names:
            if can_write is None:
                taken_out = _taken_out(cx, team, me)
                can_write = {n for d, fp in cx.execute("SELECT doc_id, text_fp FROM documents").fetchall()
                             if fp and d not in kept_out and not taken_out("reading", n := reading_name(d, fp))}
            if any(n not in can_write and _find(team, "docs", n) is None for n in names):
                return True
    return False


def _taken_back_since(ws: Workspace, cx: sqlite3.Connection) -> bool:
    """Whether a bundle this copy wrote holds, whole, an item that was taken back since (*Unshare*, by its owner here
    or, for a colleague's item this copy wrote too, by the mark that came in) or removed here since. A bundle is never
    rewritten, so this copy starts afresh: the item then leaves its subfolder, and only its mark, or the note of its
    removal, goes on. Colleagues keep what they brought in; this is about what stays readable in the team's folder."""
    marks = sharing.rows(cx)
    for (ref,) in cx.execute("SELECT key FROM sync_written WHERE kind='content'").fetchall():
        kind, _, key = ref.partition("/")
        if (marks.get((kind, key)) or {}).get("state") != "shared" or not sharing.exists(cx, ws.root, kind, key):
            return True
    return False


def _take_words_out(cx: sqlite3.Connection, mine: Path, kept_out: set[str]) -> int:
    """The switch came into force (in this copy or a colleague's), or a document was marked Only a local AI or No AI
    while it is: what this copy wrote of such a document before goes from its own subfolder. Its readings and its file
    are removed, and, because a bundle is never rewritten and earlier ones may hold its passages (in the AI work on it,
    in what a shared check handed to the AI), every bundle this copy wrote: it then starts afresh (`_start`), with one
    bundle holding everything it shares, without those words. Colleagues go on from there (a new epoch). Only this
    copy's subfolder is touched; what a colleague wrote of the document goes when their copy has its next round, and
    what colleagues brought in already stays with them. Returns how many documents were taken out.

    Which documents: those this copy recorded as written while they were not kept out (`sync_written` kind "words"),
    and any whose reading or file is in its subfolder now (a round that failed half-way recorded nothing). `cx` is only
    read: the files go first, and `write` forgets the record of words written once they are gone."""
    if not kept_out:
        return 0
    sha1s = {d: (s or "").split("~")[0] for d, s in cx.execute("SELECT doc_id, sha1 FROM documents")}
    stays = {s for d, s in sha1s.items() if d not in kept_out}  # (a file two documents share: one of them may stay)
    for d, s in cx.execute("SELECT doc_id, sha1 FROM sync_folder_docs WHERE sha1 IS NOT NULL").fetchall():
        sha1s.setdefault(d, s.split("~")[0])  # (a document not held here any more: its file as the folder named it)
    for d, fp in cx.execute("SELECT key, fp FROM sync_written WHERE kind='words'").fetchall():
        if isinstance(_words_said(fp).get("sha1"), str):
            sha1s.setdefault(d, _words_said(fp)["sha1"])  # (one removed here: its file as this copy wrote it)
    heads = {_sha(d)[:12]: d for d in kept_out}
    files = {sha1s[d]: d for d in kept_out if sha1s.get(d) and sha1s[d] not in stays}
    doomed: list[Path] = []
    gone = {r[0] for r in cx.execute("SELECT key FROM sync_written WHERE kind='words'")} & kept_out
    for sub, names in (("docs", heads), ("files", files)):
        try:
            found = sorted((mine / sub).iterdir())
        except OSError:
            found = []
        for f in found:
            d = names.get(f.name.split(".")[0])
            if d is not None:
                doomed.append(f)
                gone.add(d)
    if not gone:
        return 0
    left = _remove(doomed) + _begin_again(mine)
    if left:  # not done: nothing is written until it is (this copy's record stays, so the next round goes on)
        raise _still_there(left)
    return len(gone)  # (the caller then forgets what was written in words: `write`)


def _taken_out(cx: sqlite3.Connection, team: Path, me: str) -> Callable[[str, str], bool]:
    """`taken_out(kind, name)`: whether a reading or a file this copy once saw in a colleague's subfolder, and that is
    not there now, was taken out by that colleague for a reason this copy has not heard yet. It is then not this copy's
    to put back: the colleague may have just marked the document Only a local AI or No AI (`_take_words_out`), and the
    cloud service delivers that a file is gone before it delivers their new start. Once this copy has read all the
    colleague wrote since, it knows: the document is kept out here too, or the file simply went (removed by hand)
    and is written again. A colleague who left (no subfolder) took nothing out."""
    seen = {(k, key): fp for k, key, fp in cx.execute("SELECT kind, key, fp FROM sync_written WHERE kind IN "
                                                      "('reading', 'file') AND seq IS NULL AND fp != ''")}
    read = _read_upto(cx)
    heard: dict[str, bool] = {}

    def taken_out(kind: str, name: str) -> bool:
        pid = seen.get((kind, name))
        if not pid or pid == me or not (team / pid).is_dir():
            return False
        if pid not in heard:
            head = _json(team / pid / "head.json")
            done, epoch = read.get(pid, (0, None))
            heard[pid] = bool(head) and epoch == head.get("epoch") and done >= (_int(head.get("last")) or 0)
        return not heard[pid]

    return taken_out


def _reading_whole(f: Path) -> bool:
    """Whether a reading in the folder can be read: a zip that is whole, holding a document's row."""
    try:
        with zipfile.ZipFile(f) as zf:
            data = json.loads(zf.read("reading.json")) if zf.testzip() is None else None
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, EOFError):
        return False
    return isinstance(data, dict) and isinstance(data.get("documents"), dict)


def _mend_readings(team: Path, mine: Path, me: str) -> None:
    """A reading in this copy's subfolder that a colleague cannot read (their `waiting.json`), and that is damaged here
    too, is removed: this round writes it again when this copy still holds that reading."""
    for p in _people_dirs(team):
        notes = _json(p / "waiting.json") if p.name != me else None
        for note in (notes or {}).values():
            for n in (note.get("readings") or []) if isinstance(note, dict) else []:
                f = mine / "docs" / n if isinstance(n, str) and _READING.fullmatch(n) else None
                if f is not None and f.is_file() and not _reading_whole(f):
                    _remove([f])


def _checksum(f: Path) -> str:
    """The sha1 of an original file, worked out once while the file stays as it is (`sources._SHA1S`, by its path,
    time and size): a file that changed since its document was added would otherwise be read whole every round."""
    from ..ingest import _sha1
    from ..sources import _SHA1S

    st = f.stat()
    key = (str(f), st.st_mtime_ns, st.st_size)
    if key not in _SHA1S:
        _SHA1S[key] = _sha1(f)
    return _SHA1S[key]


def _doc_tokens(rows: Iterable[dict], docs: set[str], cols: Iterable[str] | None = None) -> set[str]:
    """The documents named in these rows (as a document id, or the head of a passage id or a task id)."""
    out: set[str] = set()
    for r in rows:
        for c, v in r.items():
            if isinstance(v, str) and (cols is None or c in cols):
                out |= {t for t in _TOKEN.findall(v) if t in docs}
    return out


class _Writer:
    """One bundle: what changed since this copy last wrote, put together from one moment of the project."""

    def __init__(self, ws: Workspace, team: Path, me: str, keep_out: bool, progress: Progress | None):
        self.ws, self.team, self.me, self.keep_out, self.progress = ws, team, me, keep_out, progress
        self.items: list[dict] = []
        self.waiting: list[dict] = []
        self.stubs: dict[str, dict] = {}
        self.stub_fps: dict[str, str] = {}
        self.readings: list[tuple[str, str]] = []   # (doc_id, name) to write
        self.files: list[tuple[str, Path]] = []      # (file name, source) to write
        self.found: list[tuple[str, str, str]] = []  # ("reading" | "file", name, whose subfolder) already there
        self.new_rows: dict[str, list[int]] = {}     # the project's rows to write: their row numbers, per table
        self.row_keys: list[str] = []
        self.words: list[tuple[str, str]] = []       # documents not kept out, written in words (`_words_fp`)
        self.rows_written: dict[str, int] = {}
        self.kept_out: set[str] = set()
        self.project: sharing.ProjectRows | None = None
        self.out_stubs: dict[str, dict] = {}
        self.absent: dict[str, dict] = {}
        self.removed: dict[str, dict] = {}
        # what changed since the last round (sync/changes.py): None, look at everything
        self.memory: changes.Memory | None = None
        self.changed: dict[str, set[str]] | None = None
        self.clock: int | None = None
        self.context: tuple | None = None
        self.item_fps: dict[tuple[str, str], dict] = {}
        self.tables: list[str] = []
        self.seen_rows: set[str] | None = None       # every row's key, when every table was read (`_prune_rows`)

    def _in_folder(self, sub: str) -> dict[str, str]:
        """{name: whose subfolder} of what is in `sub` of every copy's subfolder (a reading or a file is stored once
        in the whole folder; this copy's own first)."""
        out: dict[str, str] = {}
        for p in sorted(_people_dirs(self.team), key=lambda p: p.name != self.me):
            try:
                for f in (p / sub).iterdir():
                    out.setdefault(f.name, p.name)
            except OSError:
                continue
        return out

    def plan(self, cx: sqlite3.Connection, memory: changes.Memory | None = None, full: bool = False) -> None:
        """What this round writes, read from one moment of the project (`cx`, a read transaction). With `memory`, what
        did not change since the last round is not looked at again (sync/changes.py); `full`: look at everything (a
        snapshot: everything goes, and what the record holds that is no more is pruned, `_prune_rows`)."""
        from ..sources import original_file

        ws = self.ws
        written = _written(cx)
        levels = ai_settings(ws, cx)
        self.kept_out = kept_out_docs(ws, cx, self.keep_out)
        self.project = sharing.ProjectRows(cx, ws.root, self.kept_out)
        self._what_changed(cx, memory, full)
        self._plan_items(cx, written)
        # the documents: a stub of each, a reading per reading, a file per file. What is in the folder is read from the
        # folder each round, not from this copy's record: a colleague who wrote a reading may leave, with their subfolder
        docs = _rows(cx, "SELECT doc_id, sha1, text_fp, old_fps, title, ai_budget, sent_share, reader, path "
                         "FROM documents ORDER BY doc_id")
        readings_there = self._in_folder("docs")
        files_there = {m.group(1): pid for n, pid in self._in_folder("files").items() if (m := _FILE.fullmatch(n))}
        taken_out = _taken_out(cx, self.team, self.me)
        followed = {r[0]: r[1] for r in cx.execute("SELECT doc, ai_n FROM canon_seen WHERE ai_n IS NOT NULL")}  # 0.18 L2
        for d in docs:
            doc = d["doc_id"]
            kept = doc in self.kept_out
            stub = {"doc_id": doc, "sha1": d["sha1"], "text_fp": d["text_fp"], "old_fps": d["old_fps"],
                    "title": d["title"], "ai_access": levels.get(doc) or "none", "ai_budget": d["ai_budget"],
                    "sent_share": d["sent_share"], "reader": d["reader"], "kept_out": kept, "reading": None,
                    "file": None, "name": None}
            name = reading_name(doc, d["text_fp"]) if d["text_fp"] else None
            if not kept and name and name not in readings_there and taken_out("reading", name):
                name = None  # a colleague took it out of the folder: not put back before this copy has heard why
            if not kept and name:
                stub["reading"] = name
                if name not in readings_there:
                    self.readings.append((doc, name))
                    readings_there[name] = self.me
                elif written.get(("reading", name)) != readings_there[name] and readings_there[name] != self.me:
                    self.found.append(("reading", name, readings_there[name]))  # a colleague wrote it already
                # (a document without a recorded file has none to look for)
                info = original_file(ws, doc, verify=False) if d["path"] else {"available": False}
                plain = (d["sha1"] or "").split("~")[0]
                if info["available"] and re.fullmatch(r"[0-9a-f]{40}", plain):
                    fname = f"{plain}.{_ext(info['name'] or info['path'])}"
                    if plain in files_there:
                        if written.get(("file", plain)) != files_there[plain] and files_there[plain] != self.me:
                            self.found.append(("file", plain, files_there[plain]))
                    elif taken_out("file", plain):
                        fname = None
                    elif _checksum(Path(info["path"])) == plain:  # the file it was read from, not one changed since
                        self.files.append((fname, Path(info["path"])))
                        files_there[plain] = self.me
                    else:
                        fname = None
                    if fname:
                        stub["file"], stub["name"] = fname, info["name"] or Path(info["path"]).name
            if doc in followed:  # 0.18 L2: how far this copy followed the owner on its AI setting (ownership.py)
                stub["canon_ai"] = followed[doc]
            fp = _sha(json.dumps(stub, sort_keys=True, default=str))[:20]
            self.stubs[doc] = stub
            said = _words_fp(levels.get(doc), d["sha1"])
            if not kept and written.get(("words", doc)) != said:  # its words may go now (`_take_words_out`)
                self.words.append((doc, said))
            if written.get(("doc", doc)) != fp:
                self.stub_fps[doc] = fp
        # the project's rows written since the last bundle (each once): their numbers now, read whole when the bundle
        # is written, a slice at a time (a large corpus's AI work is never held in memory at once)
        _say(self.progress, "write", "Looking for what changed", {})
        self._plan_rows(cx)
        if (self.new_rows.get("bib_items") or self.new_rows.get("bib_links")) and not self.new_rows.get("meta"):
            # a colleague's merge takes the bibliography's works and links only with the bibliography they belong to
            row = cx.execute("SELECT rowid FROM meta WHERE key='bibliography'").fetchone()
            if row:
                self.new_rows["meta"] = [row[0]]
        self.absent = {r["doc_id"]: r for r in _rows(cx, "SELECT * FROM sync_folder_docs")}
        self.removed = {r["key"]: r for r in _rows(cx, "SELECT key, title, fp FROM sync_removed WHERE kind='document' "
                                                       "AND fp IS NOT NULL")}

    # ---- what changed since the last round (deep dive S5, sync/changes.py) ------------------------------------
    def _what_changed(self, cx: sqlite3.Connection, memory: changes.Memory | None, full: bool) -> None:
        """What changed since the round this process last remembered (`self.changed`; None: look at everything). What
        the counters cannot see makes it look at everything: another table definition, other documents kept out of the
        folder, other tables of the project's rows, other codebooks of the project's own."""
        self.memory, self.clock = memory, changes.clock(cx)
        self.tables = [t for t, _where, _cols in self.project.tables()]
        books = Path(self.ws.root) / "frameworks"
        self.context = (changes.ident(cx), changes.schema(cx), tuple(sorted(self.kept_out)), tuple(self.tables),
                        tuple(sorted(p.stem for p in books.glob("*.csv"))) if books.is_dir() else ())
        if full or memory is None or memory.context != self.context:
            self.changed = None
        else:
            self.changed = changes.changed_since(cx, memory.upto, memory.ignore)

    def _codebook_sig(self, key: str) -> tuple:
        from ..home import home

        return changes.files_sig(f / f"{key}.{ext}" for f in (Path(self.ws.root) / "frameworks", home() / "frameworks")
                                 for ext in ("csv", "json"))

    def _plan_items(self, cx: sqlite3.Connection, written: dict[tuple[str, str], str]) -> None:
        """The items: shared ones that changed, and the marks of those taken back. An item nothing touched since the
        last round has the fingerprint it had then (`self.memory.items`); it is read whole only when it goes."""
        ws, mem = self.ws, self.memory
        if self.changed is None or mem is None:
            touched, kinds, known = set(), set(), {}
        else:
            (touched, kinds), known = changes.touched(cx, self.changed), mem.items
        for (kind, key), r in sorted(sharing.rows(cx).items()):
            if kind not in sharing.KINDS or r.get("state") not in ("shared", "withdrawn"):
                continue
            mark = _mark(r)
            files = self._codebook_sig(key) if kind == "codebook" else None
            was = known.get((kind, key))
            if was is not None and ((kind, key) in touched or kind in kinds or was["mark"] != mark
                                    or was["files"] != files):
                was = None
            if was is not None and (written.get((kind, key)) == was["fp"] or was["busy"]):
                self.item_fps[(kind, key)] = was
                if written.get((kind, key)) != was["fp"]:
                    self.waiting.append({"kind": kind, "key": key, "title": r.get("title") or key})
                continue
            it = _item(ws, cx, kind, key, r, self.kept_out)
            self.item_fps[(kind, key)] = {"fp": it["fp"], "busy": it["busy"], "mark": mark, "files": files}
            if written.get((kind, key)) == it["fp"]:
                continue
            if it["busy"]:
                self.waiting.append({"kind": kind, "key": key, "title": it["title"]})
                continue
            self.items.append(it)

    def _plan_rows(self, cx: sqlite3.Connection) -> None:
        """The project's rows new or changed since they were written: of the tables that changed since the last round
        (or that a change elsewhere changes, `changes.tables_to_read`), looked up in this copy's record as they are read,
        a slice at a time (S14: the record holds one entry per row, never loaded whole)."""
        mem = self.memory
        if self.changed is None or mem is None or "row" in self.changed.get("sync_written", ()):
            only = None  # (an entry of the record taken away: what it named may have to go again)
        else:
            only = (set(self.tables) - mem.clean) | changes.tables_to_read(self.changed, self.tables,
                                                                             bool(self.kept_out))
            if "results" in only:
                only.add("tasks")
        seen: set[str] = set()
        batch: list[tuple[str, int, str, str]] = []

        def look_up() -> None:
            keys = [h for _t, _i, h, _c in batch]
            was = dict(cx.execute(f"SELECT key, fp FROM sync_written WHERE kind='row' AND key IN "
                                  f"({','.join('?' * len(keys))})", keys)) if keys else {}
            for table, rowid, h, content in batch:
                if was.get(h) != content:  # new, or changed since it was written
                    self.new_rows.setdefault(table, []).append(rowid)
                    self.row_keys.append((h, content))
            batch.clear()

        for table, rowid, ident, content in self.project.scan(only):
            h = _row_key(table, ident)
            if h in seen:
                continue
            seen.add(h)
            batch.append((table, rowid, h, content))
            if len(batch) >= 500:
                look_up()
        look_up()
        self.seen_rows = seen if only is None else None

    def remember(self) -> None:
        """What this round looked at, once it is recorded (or there was nothing to write): the next round looks only at
        what changes after it."""
        mem = self.memory
        if mem is None or self.clock is None:
            return
        mem.upto, mem.context, mem.items, mem.clean, mem.ignore = (self.clock, self.context, dict(self.item_fps),
                                                                   set(self.tables), {})

    def choose_stubs(self, named: set[str]) -> None:
        """The stubs that go: of documents that changed, and of every document the rows that go name (a colleague's
        merge names each by its content: fingerprints._canon)."""
        self.out_stubs = {d: self.stubs[d] for d in self.stub_fps}
        for d in sorted(named - set(self.out_stubs)):
            if d in self.stubs:
                self.out_stubs[d] = self.stubs[d]
            elif d in self.removed:  # removed here: named by its note of removal
                r = self.removed[d]
                self.out_stubs[d] = {"doc_id": d, "text_fp": r["fp"], "title": r["title"], "removed": True}
            elif d in self.absent:  # a colleague's, known here only from the folder: passed on as it was heard,
                a = self.absent[d]  # saying nothing of who may read it with AI (that is its holder's to say)
                self.out_stubs[d] = {"doc_id": d, "sha1": a["sha1"], "text_fp": a["text_fp"], "title": a["title"],
                                     "heard": True, "kept_out": bool(a["kept_out"]), "reading": a["reading"],
                                     "file": a["file"], "name": a["name"]}

    def empty(self) -> bool:
        return not (self.items or self.new_rows or self.stub_fps or self.readings or self.files)

    # ---- the files ---------------------------------------------------------------------------------
    def write_reading(self, cx: sqlite3.Connection, mine: Path, doc: str, name: str) -> None:
        """A document's reading, once: its row (with its text, without this computer's path to its file) and its
        pages, paragraphs, headings, passages, blocks and tables."""
        row = _rows(cx, "SELECT * FROM documents WHERE doc_id=?", (doc,))[0]
        row.pop("path", None)
        data = {"doc_id": doc, "text_fp": row.get("text_fp"), "documents": row}
        for t in _READING_TABLES:
            data[t] = _rows(cx, f"SELECT * FROM {t} WHERE doc_id=?", (doc,))
        part = mine / "docs" / (name + ".part")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("reading.json", json.dumps(data, ensure_ascii=False, default=str))
        os.replace(part, mine / "docs" / name)

    def write_bundle(self, mine: Path, seq: int, snapshot: bool, name: str, epoch: str | None = None) -> Path:
        """The bundle: `bundle.json`, `rows.sqlite` and the codebooks among its items; checked before it is written
        (`_leaks`), so nothing that is not shared can be in it."""
        tmp = Path(tempfile.mkdtemp(prefix="enlens-bundle-"))
        try:
            db = Workspace.create(tmp / "b", scratch=True).db_path
            bcx = scratch_settings(sqlite3.connect(db))
            # 2026-11-12: a file of its own, thrown away if anything fails: its rows are written once (in WAL mode they
            # went to the log and then into the file) and VACUUM's copy is made in memory; a bundle of 4.7 MB wrote
            # 11 MB instead of 27 MB. Not WAL in the zip either: a colleague's ENLENS reads it as one plain file.
            bcx.execute("PRAGMA journal_mode=MEMORY")
            known = set(self.stubs) | set(self.absent) | set(self.removed)
            named: set[str] = set()
            try:
                with bcx:
                    for it in self.items:
                        for table, got in it["rows"].items():
                            _insert(bcx, table, got)
                            named |= _doc_tokens(got, known)
                    for table, ids in self.new_rows.items():
                        for i in range(0, len(ids), 2000):
                            got = self.project.fetch(table, ids[i:i + 2000])
                            _insert(bcx, table, got)
                            named |= _doc_tokens(got, known, ("doc_id", "passage_id", "task_id", "item_id", "key",
                                                              "window"))
                            self.rows_written[table] = self.rows_written.get(table, 0) + len(got)
                    for it in self.items:  # each item's mark, as it was when the item was read
                        m = it["mark"]
                        if m is not None:
                            bcx.execute("INSERT OR REPLACE INTO shares(kind, key, state, owner, by, at, title) VALUES "
                                        "(?,?,?,?,?,?,?)", (it["kind"], it["key"], m["state"], m["owner"], m["by"],
                                                            m["at"], m["title"]))
                problem = _leaks(bcx, self.items)
                if problem:
                    raise FolderProblem("ENLENS stopped before writing to the shared folder: " + problem +
                                        " Nothing was written. Please report this.", "leak")
                bcx.execute("VACUUM")  # nothing left in free pages
            finally:
                bcx.close()
            self.choose_stubs(named)
            meta = {"format": BUNDLE_FORMAT, **formats.stamp(needs=NEEDS), "version": __version__,
                    "project_uid": self.ws.project_uid(), "from": {"id": self.me, "name": name}, "seq": seq,
                    "at": now(), "snapshot": snapshot, "epoch": epoch,
                    "items": [{"kind": it["kind"], "key": it["key"], "state": it["state"], "fp": it["fp"]}
                              for it in self.items],
                    "documents": list(self.out_stubs.values()),
                    "rows": dict(self.rows_written)}
            out = mine / "bundles" / f"{seq:06d}.zip"
            part = out.with_name(out.name + ".part")
            with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                zf.writestr("bundle.json", json.dumps(meta, indent=1, ensure_ascii=False, default=str))
                zf.write(db, "rows.sqlite")
                for it in self.items:
                    for n, data in sorted(it["files"].items()):
                        zf.writestr(n, data)
            os.replace(part, out)
            return out
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _insert(cx: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    have = set(_cols(cx, table))
    cols = [c for c in rows[0] if c in have]
    verb = "OR IGNORE" if _pk(cx, table) else ""
    cx.executemany(f"INSERT {verb} INTO {table}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                   [tuple(r.get(c) for c in cols) for r in rows])


def _leaks(cx: sqlite3.Connection, items: list[dict]) -> str | None:
    """A last look at a bundle's database before it is written: every item in it must be one written as shared (a
    second line of defence: `rows_of` and `ProjectRows` already hold only what may leave)."""
    from ..frameworks import BUNDLED

    shared = {(it["kind"], it["key"]) for it in items if it["state"] == "shared"}

    def keys(kind: str) -> set[str]:
        return {k for c, k in shared if c == kind}

    found = {"check": {r[0] for r in cx.execute("SELECT hyp_id FROM hypotheses")},
             "themes": {r[0] for r in cx.execute("SELECT run_id FROM theme_runs")},
             "note": {r[0] for r in cx.execute("SELECT note_id FROM notes")},
             "log": {r[0] for r in cx.execute("SELECT entry_id FROM research_log WHERE kind='entry'")},
             "codebook": {r[0] for r in cx.execute("SELECT DISTINCT framework FROM labels")} - set(BUNDLED),
             "link": {f"{a}|{b}" for a, b in cx.execute("SELECT a, b FROM concept_links WHERE source IN ('person', "
                                                        "'model')")}}
    for kind, got in found.items():
        extra = got - keys(kind)
        if extra:
            return f"a {sharing.WORDS[kind][0]} that is not shared ({sorted(extra)[0][:40]}) was among what was to go."
    for sk, sid in cx.execute("SELECT subject_kind, subject_id FROM research_log WHERE kind != 'entry' AND "
                              "subject_kind IN (" + ",".join(repr(k) for k in sharing.KINDS) + ")"):
        if (sk, sid) not in shared:
            return "an entry of the research log about an item that is not shared was among what was to go."
    # the rows that hang on a check or a set of themes: each must hang on one that is shared
    checks, runs = keys("check"), keys("themes")
    claims = cx.execute("SELECT claim_id, hyp_id FROM user_claims").fetchall()
    parts = {c for c, h in claims if h in checks}
    if len(parts) != len(claims):
        return "a part of a check that is not shared was among what was to go."
    for table, sql in (("verifications", "SELECT subject_id FROM verifications WHERE subject_kind='user_claim'"),
                       ("second_opinions", "SELECT subject_id FROM second_opinions"),
                       ("judgements", "SELECT claim_id FROM judgements")):
        if any(c not in parts for (c,) in cx.execute(sql)):
            return f"a row of {table} of a check that is not shared was among what was to go."
    kinds = sharing.ITEM_TASK_KINDS
    for (tid,) in cx.execute(f"SELECT task_id FROM tasks WHERE kind IN ({','.join('?' * len(kinds))})", kinds):
        if not _task_of(tid or "", checks, parts, runs):
            return "a task of a check or a set of themes that is not shared was among what was to go."
    if any(r not in runs for (r,) in cx.execute("SELECT DISTINCT run_id FROM theme_members")):
        return "a theme of a set of themes that is not shared was among what was to go."
    if cx.execute("SELECT 1 FROM shares WHERE state NOT IN ('shared', 'withdrawn') OR (state='withdrawn' AND title IS "
                  "NOT NULL)").fetchone():
        return "the mark of an item that is not shared was among what was to go."
    return None


def _task_of(task_id: str, checks: set[str], parts: set[str], runs: set[str]) -> bool:
    """Whether a task of a check or a set of themes is one of these (named as `fingerprints.check_tasks` and
    `themes_tasks` name them: the check's split, each part's readings, readings again and second opinions)."""
    t = task_id[len("second:"):] if task_id.startswith("second:") else task_id
    head, _, rest = t.partition(":")
    owner = rest.split(":", 1)[0]
    if head == "theme":
        return owner in runs
    if head == "decompose":
        return owner in checks
    return head in ("expand", "check", "reread") and owner in parts


def _count_changes(ws: Workspace, cx: sqlite3.Connection) -> None:
    """Deep dive S5: the change counters on every table a round reads (sync/changes.py), in the round's first write
    transaction. A table that had none (new, or made anew) was not counted: this process's rounds look at everything."""
    tables = set(changes.ITEM_TABLES) | {t for t, _w, _c in sharing.ProjectRows(cx, ws.root).tables()}
    if changes.ensure(cx, tables):
        changes.memory(ws.db_path).forget()


def _prune_rows(ws: Workspace, w: _Writer) -> None:
    """Deep dive S14: once a snapshot is written, the record keeps only the project's rows that are still here as they
    would leave (`w.seen_rows`, every table read): a row deleted since, or one without a key that changed (its content
    is its name), no longer holds an entry for ever. The round's own deletions are not a change for the next round."""
    if w.seen_rows is None:
        return
    with ws.connect() as cx:
        stale = [k for (k,) in cx.execute("SELECT key FROM sync_written WHERE kind='row'") if k not in w.seen_rows]
        for i in range(0, len(stale), 500):
            chunk = stale[i:i + 500]
            cx.execute(f"DELETE FROM sync_written WHERE kind='row' AND key IN ({','.join('?' * len(chunk))})", chunk)
        n = cx.execute(f"SELECT n FROM {changes.TABLE} WHERE tbl='sync_written' AND hint='row'").fetchone() \
            if stale and w.memory is not None else None
    if n is not None:
        w.memory.ignore[("sync_written", "row")] = int(n[0])


def write(ws: Workspace, progress: Progress | None = None, should_stop: ShouldStop | None = None) -> dict:
    """Write what changed since the last round into this copy's subfolder: the documents' readings and files new to the
    folder first, then the bundle, then `head.json` (so a colleague who sees the bundle finds what it names, once the
    cloud has brought it). Returns {"seq", "snapshot", "items": [{"kind", "key", "state"}], "documents", "readings",
    "files", "rows", "waiting": [{"kind", "key", "title"}], "kept_out", "taken_out"}; "seq" None when nothing changed
    ("taken_out": the documents whose words this round removed from this copy's subfolder, `_take_words_out`).

    Raises `_Stopped` when `should_stop` says so before a reading, a file or the bundle is written: readings and files
    already written stay in this copy's subfolder (a colleague fetches one only for a bundle that names it) and are
    found there by the next round; nothing is recorded as written, so the next round writes the bundle whole."""
    team, info = _open_team(ws, create=True)
    me, name = people.me(), people.my_name()
    _settle(ws)  # 0.18 L2: what this person changed of the documents goes as proposals; the owner's word is followed
    mine = team / me
    folder_id = str(info.get("folder_id") or "")
    if not folder_id:  # project.json without one (written by hand?): this copy's record stays as it is
        row = ws._conn().execute("SELECT fp FROM sync_written WHERE kind='head' AND key=''").fetchone()
        folder_id = row[0] if row and row[0] else ""
    # roles (DESIGN-roles §4.11): before anything is written or deleted there (also not `_take_words_out`, `_begin_again`)
    found = other_computer(ws._conn(), mine, folder_id)
    if found is not None:
        raise _other_computer_problem(found)
    _claim_head(mine)
    for sub in ("bundles", "docs", "files"):
        (mine / sub).mkdir(parents=True, exist_ok=True)
    keep = keep_out_state(ws, team, me)
    with ws.connect() as cx:  # as before a zip is made (sync.before_sending): who decided what, and every state
        people.adopt(cx, me)
        people.remember(cx, me, name)
        _count_changes(ws, cx)
        _same_folder(cx, folder_id)
        kept_out = kept_out_docs(ws, cx, keep["in_force"])
        taken_back = _taken_back_since(ws, cx)
    record_seen_since(ws)  # (the fingerprints of what changed, without the write lock)
    # this copy's own subfolder, looked at and tidied without holding the project's write lock (a slow network or
    # cloud folder would hold up every change made in the app meanwhile): only this copy writes there, a round at a
    # time, and its record changes only once the files are gone
    taken_out = _take_words_out(ws._conn(), mine, kept_out)
    if taken_out:
        with ws.connect() as cx:
            cx.execute("DELETE FROM sync_written WHERE kind='words'")
    if taken_back:
        left = _begin_again(mine)
        if left:
            raise _still_there(left)
    elif _asked_to_begin_again(ws, ws._conn(), team, mine, me, kept_out):
        _begin_again(mine)
    _mend_readings(team, mine, me)
    found, own = _switches(team, me), _own(mine)
    with ws.connect() as cx:
        _remember_switches(cx, team, me, found)
        seq, fresh, snap, epoch = _start(cx, mine, folder_id, own)
    _person(mine, me, name, keep["mine"])
    w = _Writer(ws, team, me, keep["in_force"], progress)
    rcx = _reader_cx(ws)
    try:
        w.plan(rcx, changes.memory(ws.db_path), full=fresh)
        out = {"seq": None, "snapshot": False, "items": [], "documents": 0, "readings": 0, "files": 0, "rows": 0,
               "waiting": w.waiting, "kept_out": len(w.kept_out), "taken_out": taken_out}
        if w.empty():
            if w.found:
                with ws.connect() as cx:
                    _record(cx, [(k, n, pid, None) for k, n, pid in w.found])
            w.remember()
            if not fresh:
                _prune(mine, snap)
            return out
        for i, (doc, rname) in enumerate(w.readings, 1):
            _stop_here(should_stop)
            _say(progress, "write", f"Writing document {i} of {len(w.readings)} to the shared folder",
                 {"index": i, "total": len(w.readings)})
            w.write_reading(rcx, mine, doc, rname)
        for i, (fname, src) in enumerate(w.files, 1):
            _stop_here(should_stop)
            _say(progress, "write", f"Copying file {i} of {len(w.files)} to the shared folder",
                 {"index": i, "total": len(w.files)})
            _copy_whole(src, mine / "files" / fname)
        _stop_here(should_stop)
        _say(progress, "write", "Writing what you shared", {})
        w.write_bundle(mine, seq, fresh, name, epoch)
    finally:
        rcx.rollback()
        rcx.close()
    from .. import home

    _put_json(mine / "head.json", {"last": seq, "snapshot": snap, "epoch": epoch, "at": now(),
                                   "installation": home.installation_id(), **formats.stamp(needs=NEEDS)})
    _prune(mine, snap)
    at = now()
    with ws.connect() as cx:
        _record(cx, [(it["kind"], it["key"], it["fp"], seq) for it in w.items]
                + [("doc", d, fp, seq) for d, fp in w.stub_fps.items()]
                + [("reading", n, "", seq) for _d, n in w.readings] + [(k, n, pid, None) for k, n, pid in w.found]
                + [("file", f.split(".")[0], "", seq) for f, _src in w.files]
                + [("row", h, content, seq) for h, content in w.row_keys]
                + [("words", d, said, seq) for d, said in w.words]
                + [("content", f"{it['kind']}/{it['key']}", "", seq) for it in w.items if it.get("here")]
                + [("head", "", folder_id, seq)], at)
    w.remember()
    if fresh:
        _prune_rows(ws, w)
    out.update(seq=seq, snapshot=fresh, documents=len(w.out_stubs), readings=len(w.readings), files=len(w.files),
               rows=sum(w.rows_written.values()),
               items=[{"kind": it["kind"], "key": it["key"], "state": it["state"], "title": it["title"]}
                      for it in w.items])
    return out


def _settle(ws: Workspace) -> dict | None:
    """0.18 L2 (ownership.py): one look at this copy before it writes. A fault there never stops the round."""
    try:
        from .. import ownership

        return ownership.settle(ws, leaving=True)
    except Exception:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        return None


def _not_wanted(cx: sqlite3.Connection) -> set[str]:
    """0.18 L2: the documents the owner removed or declined: a colleague's work does not bring them back."""
    from ..ownership import not_wanted

    return not_wanted(cx)


def fetch_documents(ws: Workspace, doc_ids: Iterable[str]) -> list[str]:
    """0.18 L2: bring in documents this copy has heard of in the shared folder (`sync_folder_docs`) but does not
    hold, outside a round's own reading: one the owner accepted after this copy had left it aside. Each comes in as
    a colleague's document does (merge.py), from its reading in the folder, with its file when that is there.
    Returns the ids that came in; one whose reading is not in the folder (kept out, or not there any more) stays
    out, to be added by hand."""
    from .merge import _Merge

    from ..ownership import canon

    team, _info = _open_team(ws, create=False)
    index, backup = _Index(team), _once(ws)
    cx = ws._conn()
    held = {r[0] for r in cx.execute("SELECT doc_id FROM documents")}
    want = [d for d in dict.fromkeys(doc_ids) if d not in held]
    rows = {r["doc_id"]: r for r in _rows(cx, "SELECT * FROM sync_folder_docs")}
    names = {r[0]: r[1] for r in cx.execute("SELECT person_id, name FROM people")}
    K = canon(cx)
    out: list[str] = []
    for d in want:
        r = rows.get(d)
        if (r is None or not r.get("reading")) and d in K:
            r = _stub_from_canon(team, K[d], index) or r  # read while this copy held it: no stub; the folder has it
        s = _clean_stub({**r, "ai_access": r.get("ai_access") or "none"}) if r else None
        if s is None or not s.get("reading") or s.get("kept_out"):
            continue
        tmp = Path(tempfile.mkdtemp(prefix="enlens-fetch-"))
        scratch = None
        try:
            scratch = Workspace.create(tmp / "work", scratch=True)
            with scratch.connect() as scx:
                scratch.set_meta("project_uid", ws.project_uid(), scx)
                try:
                    ok = _put_reading(scx, scratch, team, s, index)
                except _Stop:  # (larger than ENLENS reads: it stays out, to be added by hand)
                    ok = False
            if not ok:
                continue
            pid = r.get("person_id") or people.UNKNOWN
            backup()
            report = _Merge(ws, scratch, {"from": {"id": pid, "name": names.get(pid) or ""}, "name": Path(ws.root).name,
                                          "version": __version__, "sync_format": formats.FORMAT}).run()
            if report["documents"]["new"] or report["documents"]["clash"]:
                out.append(d)
        finally:
            if scratch is not None:
                scratch.close_all()
            shutil.rmtree(tmp, ignore_errors=True)
    return out


def _stub_from_canon(team: Path, k: dict, index: _Index | None = None) -> dict | None:
    """0.18 L2: what a stub would say of a document the project holds (its row in `canon`), when this copy kept none:
    it held the document when the folder named it (and has removed it since). The reading and the file are named as
    every copy names them (`reading_name`, the sha1); `_put_reading` checks that they are what canon says."""
    if k.get("state") != "in" or not k.get("text_fp"):
        return None
    index = index or _Index(team)
    name = reading_name(k["doc"], k["text_fp"])
    f = index.find("docs", name)
    if f is None:
        return None
    plain = (k.get("sha1") or "").split("~")[0]
    file = index.file_of(plain) if re.fullmatch(r"[0-9a-f]{40}", plain) else None
    return {"doc_id": k["doc"], "text_fp": k["text_fp"], "sha1": k.get("sha1"), "title": k.get("title"),
            "ai_access": k.get("ai_access") or "none", "reading": name, "file": file, "name": None, "kept_out": 0,
            "person_id": f.parent.parent.name}


def _prune(mine: Path, snapshot: int) -> None:
    """The bundles this copy wrote before its snapshot go: nobody reads them again (a colleague who has read less than
    the snapshot starts there, `_start_at`), and they would only fill the team's cloud storage. Best effort: one that
    cannot be removed now (the cloud service holds it) is removed after a later start afresh."""
    try:
        old = [f for f in (mine / "bundles").iterdir() if (m := _BUNDLE.fullmatch(f.name)) and int(m.group(1)) < snapshot]
    except OSError:
        return
    for f in old:
        try:
            f.unlink()
        except OSError:
            pass


def _record(cx: sqlite3.Connection, rows: list[tuple], at: str | None = None) -> None:
    # (an upsert, not INSERT OR REPLACE: a replaced entry is deleted first, and with recursive triggers, the default of
    # some SQLite builds, that deletion would count as a change to the record, sync/changes.py)
    at = at or now()
    cx.executemany("INSERT INTO sync_written(kind, key, fp, seq, at) VALUES (?,?,?,?,?) ON CONFLICT(kind, key) DO UPDATE "
                   "SET fp=excluded.fp, seq=excluded.seq, at=excluded.at",
                   [(k, key, fp, seq, at) for k, key, fp, seq in rows])


class _Stopped(Exception):
    """The round was asked to stop (`should_stop`). It ends between two steps, so the project is as if the round had
    not reached the step it stopped before: work brought in is recorded as read only once it is in the project, and
    nothing is recorded as written before its bundle is whole in the folder. The next round carries on from there."""


def _stop_here(should_stop: ShouldStop | None) -> None:
    if should_stop is not None and should_stop():
        raise _Stopped()


def _person(mine: Path, me: str, name: str, keep_out: bool) -> None:
    """`person.json`, written when what it says changed (the cloud service copies every write)."""
    want = {"person_id": me, "name": name, "app_version": __version__, **formats.stamp(needs=NEEDS),
            "keep_out": keep_out}
    have = _json(mine / "person.json") or {}
    if {k: have.get(k) for k in want} != want:
        _put_json(mine / "person.json", {**want, "updated_at": now()})


# ---------------------------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------------------------
class _Stop(Exception):
    """One colleague's bundles stop here this round (a gap, a bundle still arriving, a newer format, documents not
    there yet): the reason, in words, and its kind."""

    def __init__(self, kind: str, message: str, seq: int | None = None, readings: Iterable[str] = ()):
        super().__init__(message)
        self.kind, self.message, self.seq, self.readings = kind, message, seq, sorted(set(readings))


def _read_upto(cx: sqlite3.Connection) -> dict[str, tuple[int, str | None]]:
    """{person_id: (the last of their bundles brought in, the start (epoch) it belongs to)}."""
    return {r[0]: (int(r[1] or 0), r[2]) for r in cx.execute("SELECT person_id, seq, epoch FROM sync_folder_read")}


def _start_at(head: dict, done: int, epoch: str | None) -> int:
    """Where to go on reading a colleague: after the last bundle brought in; at their snapshot when this copy has read
    less than it (new to them, or their earlier bundles are gone), or when they started again from nothing (another
    epoch: their numbers began anew)."""
    snap = _int(head.get("snapshot")) or 0
    if snap and (done < snap or (epoch and head.get("epoch") and head["epoch"] != epoch)):
        return snap
    return done + 1


_META_SEEN: dict[tuple, tuple[Any, frozenset[str]]] = {}  # what bundles said, by (path, modified, size): `_described`


def _too_large(who: str, seq: int | None, what: str, cap: int) -> _Stop:
    return _Stop("too_large", f"{who}'s work number {seq} in the shared folder holds {what} larger than ENLENS reads "
                              f"({cap // 1024 ** 2} MB). It is left aside; nothing was changed. Ask them to tell the "
                              "makers of ENLENS.", seq)


def _member(zf: zipfile.ZipFile, name: str, cap: int, who: str, seq: int | None, what: str) -> zipfile.ZipInfo:
    """A member of a colleague's zip, checked against its cap before a byte of it is read. KeyError: not there."""
    info = zf.getinfo(name)
    if info.file_size > cap:
        raise _too_large(who, seq, what, cap)
    return info


def _described(f: Path, who: str, seq: int) -> tuple[Any, frozenset[str]]:
    """(what `bundle.json` says, the names in the zip): read once per bundle as it is on disk (a bundle is never
    rewritten; the Team tab asks every few seconds while one waits). Only `bundle.json` is unpacked: the rest of a
    bundle is checked as it is read (`_unpack`). Raises OSError (FileNotFoundError: not there), zipfile.BadZipFile and
    the like when the zip cannot be read (yet), _Stop when it is too large."""
    st = f.stat()
    key = (str(f), st.st_mtime_ns, st.st_size)
    if key not in _META_SEEN:
        with zipfile.ZipFile(f) as zf:
            with zf.open(_member(zf, "bundle.json", _MAX_META, who, seq, "a description")) as src:
                meta = json.loads(src.read())
            names = frozenset(zf.namelist())
        if len(_META_SEEN) > 256:
            _META_SEEN.clear()
        _META_SEEN[key] = (meta, names)
    return _META_SEEN[key]


def _bundle_meta(f: Path, pid: str, seq: int, uid: str, who: str, epoch: str | None = None) -> dict:
    """What a bundle says about itself, once its description can be read and it is what its name says. Raises _Stop.
    Whether the rest of it is whole is known when it is unpacked (`_unpack`): every member is read through its
    checksum there."""
    bad = False
    try:
        meta, names = _described(f, who, seq)
    except FileNotFoundError:
        raise _Stop("gap", f"Waiting for {who}'s work number {seq}: the shared folder has not received it yet (the "
                           "cloud service may still be copying it). ENLENS tries again on the next round.", seq) from None
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, EOFError, zlib.error):
        bad, meta, names = True, None, frozenset()
    if bad or not isinstance(meta, dict):
        raise _Stop("arriving", f"{who}'s work number {seq} cannot be read yet: it may still be arriving in the shared "
                                "folder. ENLENS tries again on the next round.", seq)
    if "rows.sqlite" not in names:
        raise _Stop("damaged", f"{who}'s work number {seq} in the shared folder is damaged (it holds no database). It "
                               "is left aside; nothing was changed.", seq)
    if meta.get("format") != BUNDLE_FORMAT or _int(meta.get("seq")) != seq or \
            (meta.get("from") or {}).get("id") != pid or meta.get("project_uid") != uid:
        raise _Stop("damaged", f"{who}'s work number {seq} in the shared folder is not what its name says (another "
                               "project, another person, or a damaged file). It is left aside; nothing was changed.",
                    seq)
    if epoch and isinstance(meta.get("epoch"), str) and meta["epoch"] != epoch:
        raise _Stop("arriving", f"{who}'s work number {seq} in the shared folder is still the one from before they "
                                "started afresh: the new one has not arrived yet. ENLENS tries again on the next "
                                "round.", seq)
    newer = formats.problem(meta, f"{who}'s work in the shared folder", "and the next round brings it in")
    if newer:
        raise _Stop("newer_format", newer, seq)
    return meta


def _unpack(f: Path, dest: Path, who: str, seq: int | None) -> None:
    """A bundle's database (`rows.sqlite`) and its codebooks, unpacked once into `dest` and checked: each member read
    through its checksum (a bundle still arriving, or damaged in the cloud, fails here), each within its cap (`_MAX_*`),
    and the database a whole SQLite file with a table `shares` (a crafted or damaged file must not stop the round).
    Raises _Stop: "gap" (the bundle went), "arriving" (it cannot be read whole), "damaged", "too_large"."""
    from ..frameworks import BUNDLED, NAME_RE

    try:
        with zipfile.ZipFile(f) as zf:
            plan = [("rows.sqlite", _member(zf, "rows.sqlite", _MAX_ROWS, who, seq, "a database"))]
            for n in zf.namelist():
                stem, _, ext = n[len("frameworks/"):].rpartition(".")
                if n.startswith("frameworks/") and n.count("/") == 1 and ext in ("csv", "json") and \
                        NAME_RE.match(stem) and stem not in BUNDLED:
                    plan.append((n, _member(zf, n, _MAX_CODEBOOK, who, seq, "a codebook")))
            for n, info in plan:
                out = dest / n
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
    except FileNotFoundError:
        raise _Stop("gap", f"Waiting for {who}'s work number {seq}: it went from the shared folder while it was read "
                           "(they may have started afresh). ENLENS tries again on the next round.", seq) from None
    except KeyError:
        raise _Stop("damaged", f"{who}'s work number {seq} in the shared folder is damaged (it holds no database). It "
                               "is left aside; nothing was changed.", seq) from None
    except (zipfile.BadZipFile, OSError, EOFError, zlib.error, ValueError):
        raise _Stop("arriving", f"{who}'s work number {seq} cannot be read yet: it may still be arriving in the shared "
                                "folder. ENLENS tries again on the next round.", seq) from None
    try:
        cx = sqlite3.connect(dest / "rows.sqlite")
        try:
            ok = cx.execute("PRAGMA quick_check").fetchone()
            whole = bool(ok and ok[0] == "ok" and cx.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND "
                                                             "name='shares'").fetchone())
        finally:
            cx.close()
    except sqlite3.DatabaseError:
        whole = False
    if not whole:
        raise _Stop("damaged", f"{who}'s work number {seq} in the shared folder is damaged (its database cannot be "
                               "read). It is left aside; nothing was changed.", seq)


def _rows_readable(f: Path) -> bool:
    """Whether a bundle's database and codebooks can be read whole (`_unpack`)."""
    tmp = Path(tempfile.mkdtemp(prefix="enlens-check-"))
    try:
        _unpack(f, tmp, "your", None)
        return True
    except _Stop:
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class _Opened:
    """The colleagues' bundles of one round, each unpacked once (`_unpack`) into a scratch folder that lasts the round:
    the withdrawals read first (`_withdrawals_first`), the check before a bundle is taken and the merge all read the
    same files, and a bundle's database is never held in memory whole."""

    def __init__(self) -> None:
        self.tmp: Path | None = None
        self.got: dict[tuple, Path] = {}
        self.last: dict[str, tuple] = {}

    def __call__(self, f: Path, who: str, seq: int) -> Path:
        """The folder bundle `f` was unpacked into (`rows.sqlite`, `frameworks/`). Raises _Stop, and OSError when the
        bundle cannot be looked at (`read` tells a bundle that went from a folder that went). A bundle that went after
        it was unpacked, from a subfolder still there (its writer started afresh), is read as it was unpacked: the
        round merges what it checked. A folder that went changes nothing."""
        try:
            st = f.stat()
        except FileNotFoundError:
            if str(f) in self.last and f.parent.parent.is_dir():
                return self.got[self.last[str(f)]]
            raise
        key = (str(f), st.st_mtime_ns, st.st_size)
        if key not in self.got:
            if self.tmp is None:
                self.tmp = Path(tempfile.mkdtemp(prefix="enlens-round-"))
            dest = self.tmp / str(len(self.got))
            dest.mkdir()
            try:
                _unpack(f, dest, who, seq)
            except BaseException:
                shutil.rmtree(dest, ignore_errors=True)
                raise
            self.got[key] = dest
        self.last[str(f)] = key
        return self.got[key]

    def close(self) -> None:
        if self.tmp is not None:
            shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp, self.got, self.last = None, {}, {}


def _find(team: Path, sub: str, name: str) -> Path | None:
    """A reading or a file, in whichever copy's subfolder it was written."""
    for p in _people_dirs(team):
        f = p / sub / name
        if f.is_file():
            return f
    return None


class _Index:
    """Where each reading and file is in the folder, listed once per round (`_find` looks in every copy's subfolder
    for each document): the same answers as `_find`, which is asked again for a name not in the list (one that
    arrived since)."""

    def __init__(self, team: Path) -> None:
        self.team = team
        self.subs: dict[str, dict[str, Path]] = {}

    def listing(self, sub: str) -> dict[str, Path]:
        if sub not in self.subs:
            out: dict[str, Path] = {}
            for p in _people_dirs(self.team):
                try:
                    for f in (p / sub).iterdir():
                        out.setdefault(f.name, f)
                except OSError:
                    continue
            self.subs[sub] = out
        return self.subs[sub]

    def find(self, sub: str, name: str) -> Path | None:
        f = self.listing(sub).get(name)
        return f if f is not None and f.is_file() else _find(self.team, sub, name)

    def file_of(self, sha1: str) -> str | None:
        """The name of an original file in the folder with this checksum (`<sha1>.<ext>`)."""
        return next((n for n in sorted(self.listing("files")) if n.startswith(sha1 + ".") and _FILE.fullmatch(n)),
                    None)


def _clean_stub(s: Any) -> dict | None:
    if not isinstance(s, dict) or not isinstance(s.get("doc_id"), str) or not DOC_ID.fullmatch(s["doc_id"]):
        return None
    if not isinstance(s.get("text_fp"), str) or not re.fullmatch(r"[0-9a-f]{16}", s["text_fp"]):
        return None
    out = dict(s)
    if not (isinstance(out.get("reading"), str) and _READING.fullmatch(out["reading"])):
        out["reading"] = None
    if not (isinstance(out.get("file"), str) and _FILE.fullmatch(out["file"])):
        out["file"] = None
    from ..access import LEVELS

    if out.get("heard"):  # passed on by a copy that does not hold it: it says nothing of its AI setting (a merge only
        out["ai_access"] = "cloud"  # ever makes a setting stricter, so this one changes nothing)
    elif out.get("ai_access") not in LEVELS:
        out["ai_access"] = "none"  # not said: the strictest
    return out


def _needs_reading(s: dict, held: set[tuple[str, str]], removed: set[str]) -> bool:
    """Whether a document of theirs must come with its reading: one new here, that they did not remove or keep out of
    the folder. One this copy holds in the same reading, or removed, is named by its stub alone."""
    d = s["doc_id"]
    if s.get("removed") or (base_id(d), s["text_fp"]) in held or d in removed or base_id(d) in removed:
        return False
    return bool(s.get("reading")) and not s.get("kept_out")


def _put_stub(scx: sqlite3.Connection, s: dict) -> None:
    """A document of theirs known by its stub alone (merge.py's `stubs`): no text, only what names it."""
    sha = s.get("sha1") if isinstance(s.get("sha1"), str) and s.get("sha1") else f"stub~{s['doc_id']}"
    scx.execute("DELETE FROM documents WHERE doc_id=? OR sha1=?", (s["doc_id"], sha))
    scx.execute("INSERT INTO documents(doc_id, sha1, text_fp, old_fps, title, ai_access, ai_budget, sent_share, reader, "
                "text) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                (s["doc_id"], sha, s["text_fp"], s.get("old_fps") if isinstance(s.get("old_fps"), str) else None,
                 str(s.get("title") or "")[:500] or None, s.get("ai_access"),
                 s.get("ai_budget") if isinstance(s.get("ai_budget"), (int, float)) else None,
                 s.get("sent_share") if isinstance(s.get("sent_share"), (int, float)) else None,
                 s.get("reader") if isinstance(s.get("reader"), int) else None))


def _put_reading(scx: sqlite3.Connection, scratch: Workspace, team: Path, s: dict,
                 index: _Index | None = None) -> bool:
    """A document new here, from its reading in the folder (checked: the reading of that document, with that text),
    with its original file when the folder has it (checked against its sha1). False when the reading is not there or
    is not what the stub says. Raises _Stop ("too_large") for a reading larger than ENLENS reads."""
    from ..ingest import _sha1

    index = index or _Index(team)
    f = index.find("docs", s["reading"])
    if f is None:
        return False
    try:
        with zipfile.ZipFile(f) as zf:
            info = zf.getinfo("reading.json")
            if info.file_size > _MAX_READING:
                raise _Stop("too_large", f"The reading of “{str(s.get('title') or s['doc_id'])[:60]}” in the shared "
                                         f"folder is larger than ENLENS reads ({_MAX_READING // 1024 ** 2} MB). It is "
                                         "left aside; nothing was changed.")
            with zf.open(info) as src:
                data = json.loads(src.read())
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, EOFError, zlib.error):
        return False
    doc = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(doc, dict) or data.get("doc_id") != s["doc_id"] or text_fp(doc.get("text")) != s["text_fp"]:
        return False
    d = s["doc_id"]
    row = {**doc, "doc_id": d, "title": s.get("title") or doc.get("title"), "ai_access": s["ai_access"],
           "ai_budget": s.get("ai_budget"), "sent_share": s.get("sent_share"), "old_fps": s.get("old_fps"),
           "path": None}
    scx.execute("DELETE FROM documents WHERE doc_id=? OR sha1=?", (d, row.get("sha1")))
    _insert(scx, "documents", [row])
    for t in _READING_TABLES:
        rows = [dict(r, doc_id=d) for r in data.get(t) or [] if isinstance(r, dict)]
        if t == "passages":
            rows = [r for r in rows if str(r.get("passage_id") or "").startswith(d + ":")]
        scx.execute(f"DELETE FROM {t} WHERE doc_id=?", (d,))
        _insert(scx, t, rows)
    plain = (row.get("sha1") or "").split("~")[0]
    src = index.find("files", s["file"]) if s.get("file") and s["file"].startswith(plain + ".") else None
    if src is not None:
        dest = Path(scratch.root) / "originals" / d / _safe_name(s.get("name"), s["file"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        if _sha1(dest) == plain:
            scx.execute("UPDATE documents SET path=? WHERE doc_id=?", (str(dest), d))
        else:
            dest.unlink(missing_ok=True)
    return True


def _apply_bundle(scx: sqlite3.Connection, scratch: Workspace, unpacked: Path, meta: dict) -> None:
    """One bundle (unpacked by `_unpack`) into the scratch copy: the items it holds replace what earlier bundles held
    of them (each item is written whole), then its rows, a slice at a time, and its codebooks go in."""
    fw = Path(scratch.root) / "frameworks"
    for it in meta.get("items") or []:
        kind, key = (it.get("kind"), it.get("key")) if isinstance(it, dict) else (None, None)
        if kind in sharing.KINDS and isinstance(key, str) and key:
            sharing.drop(scx, kind, [key])
            scx.execute("DELETE FROM shares WHERE kind=? AND key=?", (kind, key))
            if kind == "codebook":
                for ext in ("csv", "json"):
                    (fw / f"{key}.{ext}").unlink(missing_ok=True)
    bcx = sqlite3.connect(unpacked / "rows.sqlite")
    try:
        here = {r[0] for r in scx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables = [r[0] for r in bcx.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for t in tables:
            if t not in here or t.startswith("sqlite_") or (t in LOCAL_ONLY and t != "meta") or t == "documents" \
                    or t in _READING_TABLES:
                continue
            cur = bcx.execute(f"SELECT * FROM {t}")
            names = [c[0] for c in cur.description]
            cols = [c for c in _cols(scx, t) if c in names]
            at = [names.index(c) for c in cols]
            keyed = bool(_pk(scx, t)) or t == "reviews"
            insert = f"INSERT {'OR REPLACE' if keyed else ''} INTO {t}({','.join(cols)}) VALUES " \
                     f"({','.join('?' * len(cols))})"
            # a table without a key (the ledger of what was sent to Claude): each row once
            have = None if keyed else {tuple(r) for r in scx.execute(f"SELECT {','.join(cols)} FROM {t}")}
            while rows := cur.fetchmany(5000):
                if t == "meta":  # only what a merge reads of a colleague's settings
                    k = names.index("key") if "key" in names else None
                    rows = [r for r in rows if k is not None and (r[k] == "bibliography" or
                                                                  str(r[k] or "").startswith("codebook_followed:"))]
                vals = [tuple(r[i] for i in at) for r in rows]
                if have is not None:
                    vals = [v for v in dict.fromkeys(vals) if v not in have]
                    have.update(vals)
                if vals:
                    scx.executemany(insert, vals)
    finally:
        bcx.close()
    for f in sorted((unpacked / "frameworks").glob("*")) if (unpacked / "frameworks").is_dir() else []:
        fw.mkdir(exist_ok=True)  # (`_unpack` unpacked only the codebooks a bundle may carry)
        shutil.copyfile(f, fw / f.name)


def _take(ws: Workspace, team: Path, pdir: Path, start: int, last: int, who: str, held: set, removed: set,
          epoch: str | None = None, opened: _Opened | None = None,
          index: _Index | None = None) -> tuple[list[tuple[int, Path, dict]], _Stop | None]:
    """The bundles of one colleague that can come in now, in order, and why the rest cannot (yet). Each is unpacked
    once for the round (`opened`)."""
    uid = ws.project_uid()
    opened = opened if opened is not None else _Opened()
    index = index or _Index(team)
    take: list[tuple[int, Path, dict]] = []
    for seq in range(start, last + 1):
        f = pdir / "bundles" / f"{seq:06d}.zip"
        try:
            meta = _bundle_meta(f, pdir.name, seq, uid, who, epoch)
            opened(f, who, seq)
        except _Stop as e:
            return take, e
        missing, readings = [], []
        for s in meta.get("documents") or []:
            s = _clean_stub(s)
            if s is not None and _needs_reading(s, held, removed) and index.find("docs", s["reading"]) is None:
                missing.append(str(s.get("title") or s["doc_id"]))
                readings.append(s["reading"])
        if missing:
            names = ", ".join(f"“{m[:60]}”" for m in missing[:3]) + (" and more" if len(missing) > 3 else "")
            return take, _Stop("documents", f"Waiting for {len(missing)} of {who}'s documents to arrive in the shared "
                                            f"folder ({names}): their work that reads them comes in once they are "
                                            "there. ENLENS tries again on the next round.", seq, readings)
        take.append((seq, f, meta))
    return take, None


def _merge_bundles(ws: Workspace, team: Path, pid: str, who_name: str, person: dict,
                   take: list[tuple[int, Path, dict]], progress: Progress | None, epoch: str | None = None,
                   should_stop: ShouldStop | None = None, opened: _Opened | None = None,
                   index: _Index | None = None, backup: Callable[[], Any] | None = None) -> dict:
    """One colleague's bundles, merged as one colleague's zip: one scratch project fed to `merge._Merge`. Asked to stop
    (`_Stopped`) while the scratch copy is put together, nothing of it reaches the project and nothing is recorded as
    read; the merge itself, once begun, runs to its end (one transaction), and what it brought in is recorded with it.
    `backup`: the copy of the database made before the merge (one per round: `_once`)."""
    from . import _backup, log_bring_in
    from .merge import _Merge

    opened = opened if opened is not None else _Opened()
    index = index or _Index(team)

    with ws.connect() as cx:
        held = {(base_id(d), fp) for d, fp in cx.execute("SELECT doc_id, text_fp FROM documents") if fp}
        removed = {r[0] for r in cx.execute("SELECT key FROM sync_removed WHERE kind='document'")}
        removed |= _not_wanted(cx)  # 0.18 L2
    tmp = Path(tempfile.mkdtemp(prefix="enlens-folder-"))
    scratch = None
    try:
        scratch = Workspace.create(tmp / "work", scratch=True)
        stubs: dict[str, dict] = {}
        latest: dict[tuple[str, str], str] = {}
        with scratch.connect() as scx:
            scratch.set_meta("project_uid", ws.project_uid(), scx)
            for i, (seq, f, meta) in enumerate(take, 1):
                _stop_here(should_stop)
                _say(progress, "read", f"Reading {_who(who_name)}'s work ({i} of {len(take)})",
                     {"index": i, "total": len(take), "person": pid})
                _apply_bundle(scx, scratch, opened(f, _who(who_name), seq), meta)
                for s in meta.get("documents") or []:
                    s = _clean_stub(s)
                    if s is not None:
                        stubs[s["doc_id"]] = s
                for it in meta.get("items") or []:
                    if isinstance(it, dict) and it.get("kind") in sharing.KINDS and isinstance(it.get("key"), str):
                        latest[(it["kind"], it["key"])] = str(it.get("fp") or "")
            only_stub: dict[str, dict] = {}
            new = [s for s in stubs.values() if _needs_reading(s, held, removed)]
            for i, s in enumerate(new, 1):
                _stop_here(should_stop)
                _say(progress, "read", f"Fetching document {i} of {len(new)} from the shared folder",
                     {"index": i, "total": len(new)})
                if not _put_reading(scx, scratch, team, s, index):
                    raise _Stop("documents", f"A document of {_who(who_name)}'s (“{str(s.get('title') or '')[:60]}”) "
                                             "could not be read from the shared folder yet. ENLENS tries again on the "
                                             "next round.", take[0][0], [s["reading"]])
            for d, s in stubs.items():
                if not _needs_reading(s, held, removed):
                    _put_stub(scx, s)
                    only_stub[d] = s
        version = person.get("app_version") or take[-1][2].get("version")
        info = {"from": {"id": pid, "name": who_name}, "name": Path(ws.root).name, "version": version,
                "sync_format": max(formats.of(m)[0] for _s, _f, m in take), "stubs": only_stub,
                "canon_ai": {d: s.get("canon_ai") for d, s in stubs.items()}}  # 0.18 L2
        _stop_here(should_stop)
        (backup or (lambda: _backup(ws)))()
        merge = _Merge(ws, scratch, info)
        report = merge.run()
        report["via"] = "folder"
        report["bundles"] = [take[0][0], take[-1][0]]
        with ws.connect() as cx:
            log_bring_in(cx, report, " from the shared folder")
            cx.execute("INSERT OR REPLACE INTO sync_folder_read(person_id, seq, at, epoch) VALUES (?,?,?,?)",
                       (pid, take[-1][0], now(), epoch))
            _not_again(ws, cx, merge, scratch, latest,
                       kept_out_docs(ws, cx, keep_out_state(ws, team)["in_force"]))
        return report
    finally:
        if scratch is not None:
            scratch.close_all()
        shutil.rmtree(tmp, ignore_errors=True)


def _not_again(ws: Workspace, cx: sqlite3.Connection, merge, scratch: Workspace,
               latest: dict[tuple[str, str], str], kept_out: set[str]) -> None:
    """What came in from a colleague's bundles is in the folder already: this copy does not write it back. An item
    whose state here is now theirs (the same fingerprint, as this copy would write it) and the project's rows that came
    (as they are here now) are recorded as written, until this copy changes them."""
    marks = sharing.rows(cx)
    rows: list[tuple] = []
    for (kind, key), fp in latest.items():
        r = marks.get((kind, key))
        if r is not None and r.get("state") in ("shared", "withdrawn") and \
                _item(ws, cx, kind, key, r, kept_out)["fp"] == fp:
            rows.append((kind, key, fp, None))
    icx = scratch._conn()

    def named_here(table: str, r: dict) -> dict:
        cols = list(r)
        return dict(zip(cols, merge._row(r, cols)))

    came = {_row_key(t, ident): content for t, ident, content in
            sharing.ProjectRows(icx, scratch.root).identities(named_here)}
    for table, _rowid, ident, content in sharing.ProjectRows(cx, ws.root).scan():
        h = _row_key(table, ident)
        if came.get(h) == content:  # as it came: a row this copy holds otherwise is its own to write
            rows.append(("row", h, content, None))
    _record(cx, rows)


def read(ws: Workspace, progress: Progress | None = None, should_stop: ShouldStop | None = None) -> dict:
    """Bring in what each colleague wrote since this copy last read it (see the module's notes), then the original
    files of documents here that arrived since. Returns {"people": [{"id", "name", "bundles": [first, last] | None,
    "report": a merge's report | None}], "files": n, "problems": [{"kind", "person": {"id", "name"}, "message",
    "seq"}], "stopped": bool}.

    `should_stop` is asked before each colleague's work, between the steps of bringing it in, and between the files
    fetched: once it says yes, reading ends there ("stopped"), with each colleague either brought in and recorded as
    read, or left as it was for the next round."""
    team, info = _open_team(ws, create=False)
    me = people.me()
    out: dict[str, Any] = {"people": [], "files": 0, "problems": [], "stopped": False}
    if not team.is_dir():
        return out
    with ws.connect() as cx:
        _same_folder(cx, str(info.get("folder_id") or ""))
    opened, index = _Opened(), _Index(team)
    try:
        _withdrawals_first(ws, team, me, opened, should_stop)
        _read_people(ws, team, me, out, progress, should_stop, opened, index)
    finally:
        opened.close()
    return out


def _withdrawals_first(ws: Workspace, team: Path, me: str, opened: _Opened, should_stop: ShouldStop | None) -> None:
    """Before anyone's work is merged in a round: every item this copy does not hold that a colleague's waiting
    bundles say its owner took back (*Unshare*) is noted here as taken back (`sharing.receive`, by the owner's word
    only). A merge keeps out an item its owner took back only when it knows of it (share_merge.py `_withhold`);
    without this, an item came in through a colleague who still held it whenever that colleague's work was read before
    the owner's (in the order of their ids). An item held here is the merge's, as before (its report says it was taken
    back). Of an item in several bundles of one colleague, the last says how it stands (a later bundle holds it
    whole)."""
    uid = ws.project_uid()
    with ws.connect() as cx:
        read_upto = _read_upto(cx)
    said: list[dict] = []
    for pdir in _people_dirs(team):
        if pdir.name == me:
            continue
        if should_stop is not None and should_stop():
            return
        head = _json(pdir / "head.json") or {}
        last = _int(head.get("last")) or 0
        done, epoch = read_upto.get(pdir.name, (0, None))
        head_epoch = head.get("epoch") if isinstance(head.get("epoch"), str) else None
        marks: dict[tuple[str, str], dict] = {}
        for seq in range(_start_at(head, done, epoch), last + 1):
            f = pdir / "bundles" / f"{seq:06d}.zip"
            try:
                _bundle_meta(f, pdir.name, seq, uid, "a colleague", head_epoch)
                bcx = sqlite3.connect(opened(f, "a colleague", seq) / "rows.sqlite")
                try:
                    marks.update({(r["kind"], r["key"]): r for r in _rows(bcx, "SELECT * FROM shares")})
                finally:
                    bcx.close()
            except (_Stop, OSError, sqlite3.Error):
                break  # (said again, in its words, when this colleague's work is read)
        said += [r for r in marks.values() if r.get("state") == "withdrawn"]
    if not said:
        return
    root = Path(ws.root)
    with ws.connect() as cx:
        for r in said:
            kind, key = r.get("kind"), r.get("key")
            if kind in sharing.KINDS and isinstance(key, str) and key and not sharing.exists(cx, root, kind, key):
                sharing.receive(cx, kind, key, r, me, False, had=False)


def _once(ws: Workspace) -> Callable[[], None]:
    """The copy of the database made before a merge (`sync._backup`), made once however many merges follow: the state
    before the round (or before what `fetch_documents` brings in) is the one to go back to."""
    from . import _backup

    done: list[bool] = []

    def backup() -> None:
        if not done:
            _backup(ws)
            done.append(True)

    return backup


def _read_people(ws: Workspace, team: Path, me: str, out: dict, progress: Progress | None,
                 should_stop: ShouldStop | None, opened: _Opened, index: _Index) -> None:
    """`read`'s work for each colleague, in turn (see `read`)."""
    held_up: dict[str, dict] = {}
    reached: set[str] = set()   # the colleagues this round got to (asked to stop, it may not reach them all)
    backup = _once(ws)
    for pdir in _people_dirs(team):
        pid = pdir.name
        if pid == me:
            continue
        if should_stop is not None and should_stop():
            out["stopped"] = True
            break
        reached.add(pid)
        head_epoch = None
        person = _json(pdir / "person.json") or {}
        who_name = str(person.get("name") or "").strip()[:60]
        who = _who(who_name)
        head = _json(pdir / "head.json")
        if not head:
            continue  # nothing written yet (or its head has not arrived)
        last = _int(head.get("last")) or 0
        with ws.connect() as cx:
            done, epoch = _read_upto(cx).get(pid, (0, None))
            held = {(base_id(d), fp) for d, fp in cx.execute("SELECT doc_id, text_fp FROM documents") if fp}
            removed = {r[0] for r in cx.execute("SELECT key FROM sync_removed WHERE kind='document'")}
            removed |= _not_wanted(cx)  # 0.18 L2
        start = _start_at(head, done, epoch)
        entry = {"id": pid, "name": who_name, "bundles": None, "report": None}
        if start > last:
            out["people"].append(entry)
            continue
        try:
            head_epoch = head.get("epoch") if isinstance(head.get("epoch"), str) else None
            take, stop = _take(ws, team, pdir, start, last, who, held, removed, head_epoch, opened, index)
            if take:
                entry["report"] = _merge_bundles(ws, team, pid, who_name, person, take, progress, head_epoch,
                                                 should_stop, opened, index, backup)
                entry["bundles"] = [take[0][0], take[-1][0]]
        except _Stopped:  # nothing of this colleague's came in: as before, for the next round
            reached.discard(pid)
            out["stopped"] = True
            break
        except _Stop as e:
            stop = e
        except OSError as e:  # the folder went away in the middle: nothing came in
            if isinstance(e, FileNotFoundError) and pdir.is_dir():
                # only a file of theirs went while it was read (they started afresh): the folder is there, and the
                # next round reads their new start (an unreachable folder would hold the rounds back for long)
                stop = _Stop("gap", f"Some of {who}'s work went from the shared folder while it was brought in (they "
                                    "may have started afresh). Nothing was changed; ENLENS tries again on the next "
                                    "round.")
            else:
                stop = _Stop("unreachable", f"The shared folder could not be read while {who}'s work was brought in "
                                            f"({e.strerror or e}). Nothing was changed; ENLENS tries again on the next "
                                            "round.")
        except Exception as e:  # noqa: BLE001 - one colleague's work that cannot be merged never stops the others'
            import traceback

            traceback.print_exc()
            stop = _Stop("failed", f"ENLENS could not finish bringing in {who}'s work ({str(e)[:200]}). The others' "
                                   "work came in. ENLENS tries again on the next round (bringing the same work in "
                                   "twice changes nothing); if this stays, please report it.")
        if stop is not None:
            out["problems"].append({"kind": stop.kind, "person": {"id": pid, "name": who_name}, "message": stop.message,
                                    "seq": stop.seq})
            if stop.kind in _HELD_UP and stop.seq and head_epoch:
                held_up[pid] = {"seq": stop.seq, "kind": stop.kind, "epoch": head_epoch, "readings": stop.readings}
        out["people"].append(entry)
    try:
        if not out["stopped"]:
            out["files"] = fetch_files(ws, team, progress, should_stop)
    except _Stopped:
        out["stopped"] = True
    except OSError:
        pass  # tried again on the next round
    try:
        if other_computer(ws._conn(), team / me) is None:  # roles: never in a subfolder another computer writes
            _read_json(ws, team / me)
            _waiting_json(team / me, held_up, reached if out["stopped"] else None)
    except OSError:
        pass


def _waiting_json(mine: Path, held_up: dict[str, dict], reached: set[str] | None = None) -> None:
    """`waiting.json`: where this copy cannot go on reading a colleague ({person id: {"seq", "kind", "epoch",
    "readings"}}: the bundle, why, which start of theirs it belongs to, the readings waited for). A cloud service
    usually delivers in the end; when it never will (the bundle is damaged or gone where it was written, a reading no
    copy can write again), only its writer can mend it, and their copy reads this to know (`_asked_to_begin_again`).
    Removed when nothing holds this copy up. `reached`: the colleagues a stopped round got to (None: all of them); the
    note on each of the others stays as the last round left it."""
    if not mine.is_dir():
        return
    f = mine / "waiting.json"
    if reached is not None:
        before = _json(f) or {}
        held_up = {**{k: v for k, v in before.items() if k not in reached}, **held_up}
    if not held_up:
        f.unlink(missing_ok=True)
    elif _json(f) != held_up:
        _put_json(f, held_up)


def _read_json(ws: Workspace, mine: Path) -> None:
    """`read.json`: how far this copy has read each colleague (a writer may one day remove what everyone has read)."""
    if not mine.is_dir():
        return
    want = {pid: seq for pid, (seq, _epoch) in _read_upto(ws._conn()).items()}
    if (_json(mine / "read.json") or {}) != want:
        _put_json(mine / "read.json", want)


def fetch_files(ws: Workspace, team: Path, progress: Progress | None = None,
                should_stop: ShouldStop | None = None) -> int:
    """The original files of documents this copy holds without one (a colleague's document whose file reached the
    folder after its reading did), each checked against its sha1. Returns how many were fetched (raises `_Stopped`
    between two files when `should_stop` says so: those fetched are in place, the others come next round)."""
    from ..ingest import _sha1
    from ..sources import original_file

    index: dict[str, Path] = {}
    for p in _people_dirs(team):
        try:
            for f in (p / "files").iterdir():
                m = _FILE.fullmatch(f.name)
                if m and m.group(1) not in index:
                    index[m.group(1)] = f
        except OSError:
            continue
    if not index:
        return 0
    names = {r[0]: r[1] for r in ws.query("SELECT sha1, name FROM sync_folder_docs WHERE name IS NOT NULL")}
    n = 0
    for r in ws.query("SELECT doc_id, sha1 FROM documents"):
        plain = (r["sha1"] or "").split("~")[0]
        if plain not in index or original_file(ws, r["doc_id"], verify=False)["available"]:
            continue
        _stop_here(should_stop)
        src = index[plain]
        dest = Path(ws.root) / "originals" / r["doc_id"] / _safe_name(names.get(r["sha1"]) or names.get(plain),
                                                                       src.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        shutil.copyfile(src, part)
        if _sha1(part) != plain:
            part.unlink(missing_ok=True)
            continue
        os.replace(part, dest)
        with ws.connect() as cx:
            cx.execute("UPDATE documents SET path=? WHERE doc_id=?", (str(dest), r["doc_id"]))
        n += 1
        _say(progress, "files", f"Fetched {n} original files from the shared folder", {"index": n})
    return n


# ---------------------------------------------------------------------------------------------
# one round, and what the Team tab shows
# ---------------------------------------------------------------------------------------------
def sync_now(ws: Workspace, progress: Progress | None = None, should_stop: ShouldStop | None = None) -> dict:
    """One round, through the project's storage space (`space.sync_now`, 0.18.0rc2) or its shared folder
    (`_sync_now`)."""
    from . import space

    if space.configured(ws) is not None:
        return space.sync_now(ws, progress, should_stop)
    return _sync_now(ws, progress, should_stop)


def _sync_now(ws: Workspace, progress: Progress | None = None, should_stop: ShouldStop | None = None) -> dict:
    """One round: bring in what colleagues wrote, then write what changed. Returns {"at", "folder", "wrote": `write`'s
    report | None, "read": `read`'s "people", "files", "problems": [{"kind", "person", "message", "seq"}], "stopped"}.
    A folder that cannot be reached is a problem in the report, not an error: nothing changed, and the next round tries
    again. Raises FolderProblem only when no folder is chosen.

    `should_stop` (the job's cancel, when the person stops the round or the app quits) is asked between the steps of
    the round: before each colleague's work is brought in, while it is put together, before files are fetched, and
    before anything is written. Once it says yes, the round ends there with "stopped" true and no problem: what was
    brought in is in the project and recorded as read, the rest is as before, and the next round carries on.

    Reading comes first, so this copy writes with what its colleagues decided already in force: what came from them is
    not written back (`_not_again`), and a document a colleague has just marked Only a local AI or No AI is kept out
    here too before anything of it is written (the stricter setting wins in the merge; `_take_words_out`)."""
    out: dict[str, Any] = {"at": now(), "folder": str(chosen(ws) or "") or None, "wrote": None, "read": [], "files": 0,
                           "problems": [], "stopped": False}
    if chosen(ws) is None:
        raise FolderProblem("Choose a shared folder for this project first.", "no_folder")
    try:
        _open_team(ws, create=True)  # (the project's own folder there, made by whoever comes first)
    except FolderProblem as e:
        out["problems"].append({"kind": e.kind, "person": None, "message": str(e), "seq": None})
        return out
    except OSError:
        pass  # said below
    _read_into(ws, out, progress, should_stop)
    if any(x["person"] is None for x in out["problems"]):  # the folder itself: nothing to write to either
        return out
    if out["stopped"] or (should_stop is not None and should_stop()):
        out["stopped"] = True
        return out
    from .report import marks_before, tell_marks  # K3 (DEC-1): marks the project's word applies in `write`'s settle

    reports = [e["report"] for e in out["read"] if isinstance(e, dict) and isinstance(e.get("report"), dict)]
    before = [(r, marks_before(ws, r)) for r in reports]
    try:
        out["wrote"] = write(ws, progress, should_stop)
        told: set[str] = set()
        for r, b in before:
            tell_marks(ws, r, b, told)
        from ..ownership import moves_due  # 0.18 L2: new readings the owner accepted, due in this copy

        out["moves_due"] = moves_due(ws)
    except _Stopped:
        out["stopped"] = True
    except FolderProblem as e:
        out["problems"].append({"kind": e.kind, "person": None, "message": str(e), "seq": None})
    except OSError as e:
        out["problems"].append({"kind": "unreachable", "person": None, "seq": None,
                                "message": f"ENLENS could not write to the shared folder ({e.strerror or e}). Nothing "
                                           "was changed; ENLENS tries again on the next round."})
    return out


def _read_into(ws: Workspace, out: dict, progress: Progress | None, should_stop: ShouldStop | None = None) -> None:
    try:
        got = read(ws, progress, should_stop)
    except FolderProblem as e:
        out["problems"].append({"kind": e.kind, "person": None, "message": str(e), "seq": None})
        return
    except OSError as e:
        out["problems"].append({"kind": "unreachable", "person": None, "seq": None,
                                "message": f"ENLENS could not read the shared folder ({e.strerror or e}). Nothing was "
                                           "changed; ENLENS tries again on the next round."})
        return
    out["read"], out["files"], out["stopped"] = got["people"], got["files"], got["stopped"]
    out["problems"] += got["problems"]


def status(ws: Workspace) -> dict:
    """What the Team tab shows of the shared folder, without changing anything: {"folder", "team_folder", "reachable",
    "keep_out": {"mine", "colleagues", "in_force", "last_known" (only while the folder cannot be read: the colleagues
    as last seen)}, "me": {"id", "name", "last_written", "last_written_at"},
    "people": [{"id", "name", "app_version", "sync_format", "keep_out", "last_bundle", "read_up_to", "last_read_at",
    "waiting", "has_read_mine"}], "problems": [{"kind", "person", "message", "seq"}], "not_here": [{"doc_id",
    "title", "from"}], "other_computer": {"since"} | None (roles: another computer writes into this copy's subfolder
    under this person's id, `other_computer`; also a problem of that kind)}."""
    me = people.me()
    base = chosen(ws)
    cx = ws._conn()
    head = cx.execute("SELECT seq, at FROM sync_written WHERE kind='head' AND key=''").fetchone()
    out: dict[str, Any] = {"folder": str(base) if base else None, "team_folder": None, "reachable": None, "space": None,
                           # until the folder is read: who kept the switch on when it last was (offline: kept so)
                           "keep_out": keep_out_state(ws, last_known=base is not None), "problems": [], "people": [],
                           "not_here": [], "other_computer": None,
                           "me": {"id": me, "name": people.my_name(), "last_written": head[0] if head else None,
                                  "last_written_at": head[1] if head else None}}
    held = {r[0] for r in cx.execute("SELECT doc_id FROM documents")}
    shas = {(r[0] or "").split("~")[0] for r in cx.execute("SELECT sha1 FROM documents")}
    names = {r[0]: r[1] for r in cx.execute("SELECT person_id, name FROM people")}
    out["not_here"] = [{"doc_id": r[0], "title": r[1], "from": _who(names.get(r[2]))}
                       for r in cx.execute("SELECT doc_id, title, person_id, sha1 FROM sync_folder_docs WHERE "
                                           "kept_out=1 ORDER BY title").fetchall()
                       if r[0] not in held and (r[3] or "").split("~")[0] not in shas]
    if base is None:
        return out
    from . import space

    out["space"] = space.status(ws)  # 0.18.0rc2 (L6): the storage space, when the project has one ("folder" is the
    #                                   copy of it on this computer, which the rounds work on)
    try:
        team = base / team_name(ws)
        out["team_folder"] = str(team)
        out["reachable"] = base.is_dir()
        if not out["reachable"]:
            out["problems"].append({"kind": "unreachable", "person": None, "seq": None,
                                    "message": f"The shared folder {base} cannot be reached: the drive may not be "
                                               "connected, or the folder was moved or renamed."})
            return out
        try:
            _open_team(ws, create=False)
        except FolderProblem as e:
            out["problems"].append({"kind": e.kind, "person": None, "message": str(e), "seq": None})
            return out
        out["keep_out"] = keep_out_state(ws, team, me)
        found = other_computer(cx, team / me)  # roles (DESIGN-roles §4.11, §5.6)
        if found is not None:
            out["other_computer"] = found
            out["problems"].append({"kind": "other_computer", "person": None, "seq": None,
                                    "message": str(_other_computer_problem(found))})
        done = {r[0]: (int(r[1] or 0), r[2], r[3]) for r in cx.execute("SELECT person_id, seq, at, epoch FROM "
                                                                        "sync_folder_read")}
        uid = ws.project_uid()
        for p in _people_dirs(team):
            if p.name == me:
                continue
            pj = _json(p / "person.json") or {}
            hd = _json(p / "head.json") or {}
            rd = _json(p / "read.json") or {}
            last = _int(hd.get("last"))
            upto, at, epoch = done.get(p.name, (0, None, None))
            name = str(pj.get("name") or names.get(p.name) or "").strip()
            start = _start_at(hd, upto, epoch)  # where reading goes on (see `read`)
            entry = {"id": p.name, "name": _who(name), "app_version": pj.get("app_version"),
                     "sync_format": _int(pj.get("sync_format")), "keep_out": pj.get("keep_out") is True,
                     "last_bundle": last, "read_up_to": upto or None, "last_read_at": at,
                     "waiting": max(0, (last or 0) - start + 1), "has_read_mine": _int(rd.get(me))}
            out["people"].append(entry)
            if last and entry["waiting"]:
                try:
                    _bundle_meta(p / "bundles" / f"{start:06d}.zip", p.name, start, uid, _who(name),
                                 hd.get("epoch") if isinstance(hd.get("epoch"), str) else None)
                except _Stop as e:
                    out["problems"].append({"kind": e.kind, "person": {"id": p.name, "name": name},
                                            "message": e.message, "seq": e.seq})
    except OSError as e:
        out["reachable"] = False
        out["problems"].append({"kind": "unreachable", "person": None, "seq": None,
                                "message": f"The shared folder cannot be read ({e.strerror or e})."})
    return out
