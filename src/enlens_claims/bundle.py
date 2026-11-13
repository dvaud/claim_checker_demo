"""A whole project in one zip file, to hand to a colleague or move to another computer.

    enlens --ws X export-project out.zip
    enlens import-project in.zip --ws Y

The zip holds:
- `enlens.sqlite`: a consistent copy of the project's database, made with SQLite's backup API (the project can be
  in use while it is copied);
- `config.json`, and the project's own codebooks (`frameworks/`);
- the original file of every document the project has: kept at its place when it is inside the project folder
  (`uploads/`, `inputs/`), and as `originals/<doc_id>/<name>` when it was read from somewhere else on the computer.
  0.14.3: nothing else of `uploads/` (the file of a document removed since stays on this computer);
- `bundle.json`: what is where (the version that made it and, per document, its file in the zip); since 0.14 also
  which project it is (`project_uid`) and who sent it (`from`), so a colleague can bring the work into their copy of
  the project (sync.py). Codebooks the project uses from the home folder come along in `frameworks/`. 0.18: its sync
  format (`sync_format`, `sync_needs`: sync/formats.py) and `scope`: "all" (the whole project) or "shared" (only what
  its sender shared, for a colleague: sharing.py).

Everything is written to a temporary file on disk and copied in chunks, never held in memory. Importing unpacks
with the same guards as adding a zip of sources (no path can leave the project folder, a size budget against zip
bombs), opens the database (which adds the columns of this version) and points each document at its file in the
new folder. 0.14.3: the database is checked and opened while the project is still in its staging folder, so a zip
whose database cannot be read leaves nothing in `projects/`.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
import time
import unicodedata
import uuid
import zipfile
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .store import Workspace, scratch

STORED = {".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".docx", ".xlsx", ".pptx", ".gz"}  # compressed
MAX_IMPORT = 8 * 1024 ** 3


def _add(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    kind = zipfile.ZIP_STORED if path.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
    zf.write(path, arcname, compress_type=kind)


SCOPES = ("all", "shared")


def export_project(ws: Workspace, out: str | Path, scope: str = "all") -> dict:
    """Write the project to the zip file `out`; returns what it holds. `scope` (0.18, roadmap L1): "all", the whole
    project (to keep, or to move it to another computer), or "shared", only what you shared (to send to a colleague:
    sharing.strip takes every private item out of the copy of the database, and the codebooks not shared stay here).
    Either way every item says whose it is (sharing.materialise), and the documents and their files go along."""
    from .sources import original_file

    from . import sharing, sync
    from .sync import changes as sync_changes, formats as sync_formats

    if scope not in SCOPES:
        raise ValueError("A project zip holds the whole project or what you shared.")
    out = Path(out)
    root = ws.root.resolve()
    stamp = sync.before_sending(ws)  # 0.14: which project, who sends it, and the state of its checks and themes
    extra_codebooks = sync.home_codebooks(ws)
    tmp_dir = Path(tempfile.mkdtemp(prefix="enlens-export-"))
    try:
        db = tmp_dir / "enlens.sqlite"
        src = sqlite3.connect(ws.db_path, timeout=60)
        dst = sqlite3.connect(db)
        try:
            src.backup(dst)  # a consistent copy, even while the app writes
        finally:
            dst.close()
            src.close()
        # 0.18: every item says whose it is; for a colleague, only what is shared (and nothing left in free pages)
        cx = scratch(sqlite3.connect(db))
        try:
            cx.execute("PRAGMA journal_mode=MEMORY")  # 2026-11-12: a scratch copy: what changes is written once, not twice
            needs = sync_formats.zip_needs(cx)  # roles (DESIGN-roles §3.3): 4 once the project has an owner
            with cx:
                sync_changes.forget(cx)  # this computer's own counters of what changed (sync/changes.py)
                if scope == "shared":
                    left_out = sharing.strip(cx, ws.root, stamp["from"]["id"])
                    shared_books = sharing.shared_keys(cx, "codebook")
                else:
                    sharing.materialise(cx, ws.root, stamp["from"]["id"])
                    left_out, shared_books = {}, None
            if scope == "shared":
                cx.execute("VACUUM")
        finally:
            cx.close()
        files: dict[str, str] = {}
        missing: list[str] = []
        stats = {"documents": 0, "uploads": 0, "originals": 0, "missing": missing, "scope": scope,
                 "left_out": left_out}
        part = out.with_name(out.name + ".part")
        with zipfile.ZipFile(part, "w", allowZip64=True) as zf:
            zf.write(db, "enlens.sqlite", compress_type=zipfile.ZIP_DEFLATED)
            if ws.config_path.exists():
                zf.writestr("config.json", _config_for_zip(ws))
            base = root / "frameworks"  # the project's own codebooks
            if base.is_dir():
                for f in sorted(base.rglob("*")):
                    if f.is_file() and not f.is_symlink() and (shared_books is None or (
                            f.parent == base and f.suffix in (".csv", ".json") and f.stem in shared_books)):
                        _add(zf, f, f.relative_to(root).as_posix())
            for f in extra_codebooks:  # used here, kept in the home folder: a colleague needs them to read the labels
                if shared_books is None or f.stem in shared_books:
                    _add(zf, f, f"frameworks/{f.name}")
            written = {n for n in zf.namelist()}
            # 0.14.3: the file of each document the project has now, and nothing else of `uploads/`: the files of
            # documents removed since (one added by mistake), and uploads that failed or were already in the
            # project, stay on this computer
            for r in ws.query("SELECT doc_id FROM documents ORDER BY doc_id"):
                stats["documents"] += 1
                info = original_file(ws, r["doc_id"], verify=False)
                if not info["available"]:
                    missing.append(info["name"] or r["doc_id"])
                    continue
                f = Path(info["path"])
                if info["inside"]:
                    arc = f.relative_to(root).as_posix()
                else:
                    arc = f"originals/{r['doc_id']}/{f.name}"
                    stats["originals"] += 1
                if arc not in written:
                    _add(zf, f, arc)
                    written.add(arc)
                    stats["uploads"] += arc.startswith("uploads/")
                files[r["doc_id"]] = arc
            zf.writestr("bundle.json", json.dumps({"format": "enlens-project", "version": __version__,
                                                   "name": ws.root.name, **stamp, **sync_formats.stamp(needs=needs),
                                                   "scope": scope, "files": files}, indent=1))
        part.replace(out)
        stats["size"] = out.stat().st_size
        return stats
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _config_for_zip(ws: Workspace) -> str:
    """The project's config.json as it goes into a zip: 0.18, without the path of the shared folder (a path on this
    computer; each computer chooses its own, sync/folder.py)."""
    raw = ws.config_path.read_text(encoding="utf-8")
    try:
        cfg = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(cfg, dict) or "shared_folder" not in cfg:
        return raw
    cfg.pop("shared_folder", None)
    return json.dumps(cfg, indent=2)


def _forget_folder(ws: Workspace, sender: str | None) -> None:
    """0.18: an imported project has no shared folder chosen (a project folder zipped by hand may still hold another
    computer's path), and a copy of a colleague's project starts with no record of one (what the colleague wrote there
    and read from it is theirs: sync/folder.py would take it for its own). A project the same person moved to another
    computer keeps its record, and goes on where it was once the folder is chosen there."""
    from .home import load_settings
    from .sync.folder import FOLDER, _set_config

    if ws.config.get(FOLDER) is not None:
        _set_config(ws, **{FOLDER: None})
    if sender and sender == (load_settings().get("person_id") or ""):
        return
    from .sharing import without_paths

    with ws.connect() as cx:
        for t in ("sync_written", "sync_folder_read", "sync_folder_docs",
                  "sync_via", "sync_from", "sync_refused"):  # roles (DESIGN-roles §3.2): what the sender's copy noted
            cx.execute(f"DELETE FROM {t}")
        cx.execute("UPDATE canon_seen SET ai_offer=NULL")  # roles-p1: offers made to the sender are the sender's
        # the bibliography's attachments name files on the colleague's computer: a path here could name a file of
        # this one, which *Add the files the bibliography has* would then add to the project (as a merge clears them)
        for key, files in cx.execute("SELECT item_key, files_json FROM bib_items").fetchall():
            cx.execute("UPDATE bib_items SET files_json=? WHERE item_key=?", (without_paths(files), key))


def _adopt(ws: Workspace, sender: str | None) -> None:
    """0.18 L2: a copy of a colleague's project starts as the project has its documents: what the colleague changed of
    them and the owner has not accepted stays theirs (ownership.adopt). A project the same person moved to another
    computer is theirs as it was."""
    from .home import load_settings

    if not sender or sender == (load_settings().get("person_id") or ""):
        return
    try:
        from .ownership import adopt
    except ImportError:  # an app built without shared projects
        return
    adopt(ws, sender)


def _project_folder(names: list[str]) -> str:
    """Where in a project zip the project is: "" when its database is at the top (a zip made with "Download as a
    zip"), or the folder that holds it ("Tovertafel/") when the project's folder itself was zipped, as Finder's
    Compress or Windows' "Send to compressed folder" do."""
    dbs = [n for n in names if not n.startswith("__MACOSX") and (n == "enlens.sqlite" or n.endswith("/enlens.sqlite"))]
    if "enlens.sqlite" in dbs:
        return ""
    if len(dbs) == 1:
        return dbs[0][:-len("enlens.sqlite")]
    if dbs:
        folders = ", ".join(sorted(d[:-len("/enlens.sqlite")] for d in dbs)[:6])
        raise ValueError(f"This zip holds {len(dbs)} projects ({folders}). Import one project at a time: zip each "
                         "project's folder on its own, or use “Download as a zip” in the app they come from.")
    raise ValueError("This zip holds no ENLENS project (there is no enlens.sqlite in it). To add documents, "
                     "use Add documents instead.")


def relocate_documents(db: Path, relative, new_root: Path) -> int:
    """Point the documents of the project database `db` at their files in `new_root`. `relative(parts)` gives, for
    the parts of a recorded path, its parts inside the project folder (or None when it was not in it); a path is
    changed only when that file is there. Returns how many were changed."""
    root = Path(new_root).resolve()
    n = 0
    cx = sqlite3.connect(db)
    try:
        with cx:
            for doc_id, path in cx.execute("SELECT doc_id, path FROM documents").fetchall():
                if not path or not Path(path).is_absolute():
                    continue
                rel = relative(Path(path.replace("\\", "/")).parts)
                if not rel:
                    continue
                # the same name may be written with accents composed or not (macOS decomposes them)
                target = next((t for t in (root.joinpath(*(unicodedata.normalize(f, x) for x in rel)).resolve()
                                           for f in ("NFC", "NFD")) if t.is_file()), None)
                if target and target != Path(path) and target.is_relative_to(root):
                    cx.execute("UPDATE documents SET path=? WHERE doc_id=?", (str(target), doc_id))
                    n += 1
    finally:
        cx.close()
    return n


DAMAGED_DB = ("The project's database in this zip cannot be read: the zip is damaged, or it is not an ENLENS project. "
              "Ask for a new copy of the file.")


NOT_ROWS = ("The project's database in this zip holds more than a project's rows (a table that works out its own "
            "values). ENLENS does not open it. Ask for a new copy, made with “Download as a zip”.")


def _rows_only(cx: sqlite3.Connection) -> None:
    """A database that came from someone else is taken for its rows alone. What else a database file can hold goes:
    triggers (they would run at every change this person makes afterwards: one turned *Only a local AI* back to
    *cloud* the moment it was set, another emptied the record of what was sent to Claude) and views (one can stand in
    the place of a table). A table that works out its values itself (a generated column, a virtual table) is refused:
    a setting kept in one could not be changed here. ENLENS's own triggers (sync/changes.py) are this computer's and
    never in a zip: its first round of the shared folder makes them again; an add-on's own come back when the project is
    opened (`store._setup_addons`)."""
    for kind, name in cx.execute("SELECT type, name FROM sqlite_master WHERE type IN ('trigger', 'view')").fetchall():
        cx.execute(f"DROP {'TRIGGER' if kind == 'trigger' else 'VIEW'} IF EXISTS \"{name.replace(chr(34), chr(34) * 2)}\"")
    for name, sql in cx.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall():
        if name.startswith("sqlite_"):
            continue
        quoted = name.replace(chr(34), chr(34) * 2)
        if (sql or "").lstrip().upper().startswith("CREATE VIRTUAL") or any(
                r[6] in (2, 3) for r in cx.execute(f"PRAGMA table_xinfo(\"{quoted}\")")):
            raise ValueError(NOT_ROWS)
    cx.commit()


def _open_staged(folder: Path) -> bool:
    """0.14.3: check the database unpacked into the staging folder and open it there (which adds the tables and
    columns of this version), before the project is put in place. Raises ValueError with a plain message when it
    cannot be read. Returns whether it was made before 0.11 (per-document AI settings)."""
    try:
        cx = sqlite3.connect(folder / "enlens.sqlite")
        try:
            ok = cx.execute("PRAGMA quick_check").fetchone()
            if ok and ok[0] == "ok":
                _rows_only(cx)
            before_011 = "ai_access" not in {r[1] for r in cx.execute("PRAGMA table_info(documents)")}
        finally:
            cx.close()
        if not ok or ok[0] != "ok":
            raise ValueError(DAMAGED_DB)
        ws = Workspace.open(folder)
        ws.close()  # no connection stays open on the folder that is about to move
    except sqlite3.DatabaseError as e:
        raise ValueError(DAMAGED_DB) from e
    return before_011


# config.json: what ENLENS reads of a project's settings, and what each may hold. A project from a zip keeps only these,
# each of its kind and in a sensible range, else ENLENS's own (`store.DEFAULT_CONFIG`): the file comes from someone
# else's computer, and a value of the wrong kind stopped every page of results (a `thresholds` that is not a dict)
_NUMBERS = {"thresholds": {"screen_min_score": (0.0, 100.0), "accept_confidence": (0.0, 1.0),
                           "support_confidence": (0.0, 1.0), "verify_top_k": (1, 200)},
            "passages": {"max_chars": (100, 100000), "min_chars": (0, 100000)}}
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,119}")  # a model's name, as Settings and the routes write it


def _clean_config(raw: Any) -> dict:
    """A project's config.json as a zip brought it, with only what ENLENS knows (see `_NUMBERS`)."""
    from .access import LEVELS
    from .store import DEFAULT_CONFIG

    cfg = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for part, ranges in _NUMBERS.items():
        given = cfg.get(part) if isinstance(cfg.get(part), dict) else {}
        out[part] = {}
        for k, (lo, hi) in ranges.items():
            v = given.get(k)
            ok = isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi and \
                (isinstance(v, int) or not isinstance(lo, int))
            out[part][k] = v if ok else DEFAULT_CONFIG[part][k]
    if out["passages"]["min_chars"] > out["passages"]["max_chars"]:
        out["passages"] = dict(DEFAULT_CONFIG["passages"])
    models = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
    out["models"] = {k: (v if isinstance(v, str) and _MODEL.fullmatch(v) else d)
                     for k, d in DEFAULT_CONFIG["models"].items() for v in [models.get(k)]}
    if cfg.get("ai_access_default") in LEVELS:
        out["ai_access_default"] = cfg["ai_access_default"]
    for k in ("ai_access_ask", "ai_access_banner", "shared_folder_keep_out"):
        if isinstance(cfg.get(k), bool):
            out[k] = cfg[k]
    return out


# what a project zip may hold that is not unpacked: made again here (the search index, the cache of the terms), or the
# sender's own (the copy of their database made before they brought work in)
_NOT_UNPACKED = ("cache/", "backups/")


class _Without:
    """A zip as `ingest._safe_extract` reads it, without what is not unpacked (`_NOT_UNPACKED`)."""

    def __init__(self, zf: zipfile.ZipFile, prefix: str):
        self.zf, self.prefix = zf, prefix

    def infolist(self) -> list[zipfile.ZipInfo]:
        from .ingest import zip_name

        skip = tuple(self.prefix + n for n in _NOT_UNPACKED)
        return [i for i in self.zf.infolist() if not zip_name(i).startswith(skip)]

    def open(self, *a, **k):
        return self.zf.open(*a, **k)


def import_project(zip_path: str | Path, dest: str | Path, merge_only: bool = False) -> Workspace:
    """Unpack a project zip into the folder `dest` (which must not exist yet, or be empty) and open it. The zip is one
    made with export_project, or a project folder zipped by hand (0.13.5). `merge_only` (0.18): unpacked only to be
    merged into a copy (sync.bring_in), not a copy of its own: the sender's copy stays as it was."""
    from .ingest import ZIP_ERRORS, _safe_extract, zip_name, zip_problem

    zip_path, dest = Path(zip_path), Path(dest)
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("This is not a zip file.")
    if dest.exists() and any(dest.iterdir()):
        raise ValueError(f"The folder {dest} is not empty: choose another name.")
    with zipfile.ZipFile(zip_path) as zf:
        prefix = _project_folder([zip_name(i) for i in zf.infolist()])
        total = sum(i.file_size for i in zf.infolist())
        if total > MAX_IMPORT:
            raise ValueError(f"The project in this zip is larger than {MAX_IMPORT // 1024 ** 3} GB unpacked.")
        staging = dest.with_name(dest.name + ".importing")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            try:
                _safe_extract(_Without(zf, prefix), staging, [MAX_IMPORT], strip=prefix)
            except ZIP_ERRORS as e:  # 0.14.3: a damaged or password-protected zip, in words
                raise ValueError(f"This project zip could not be unpacked ({zip_problem(e)}). Ask for a new copy of "
                                 "the file.") from e
            if not (staging / "enlens.sqlite").is_file():
                raise ValueError("The project's database could not be unpacked.")
            try:
                meta = json.loads((staging / "bundle.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            # 0.18.1: a zip from a newer ENLENS that shares work in a way this one does not know yet is refused in
            # words, as the shared folder and *Bring in* refuse it, before anything is opened (ENLENS 0.17.0 to 0.18.0
            # opened it as a new project without a word)
            from .sync import formats as sync_formats

            newer = sync_formats.problem(meta, "This project zip", "then open it again")
            if newer:
                raise ValueError(newer)
            before_011 = _open_staged(staging)
            if dest.exists():
                dest.rmdir()
            staging.replace(dest)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    ws = Workspace.open(dest)  # opened in staging already: the tables and columns of this version are there
    try:
        sent = json.loads(ws.config_path.read_text(encoding="utf-8")) if ws.config_path.exists() else {}
    except (OSError, ValueError):
        sent = {}
    ws.config_path.write_text(json.dumps(_clean_config(sent), indent=2), encoding="utf-8")
    ws._config_cache = None
    if before_011:
        # 0.11: a project made before per-document AI settings: the app asks once who may read its documents
        cfg = json.loads(ws.config_path.read_text(encoding="utf-8")) if ws.config_path.exists() else {}
        cfg.pop("ai_access_default", None)
        cfg.pop("ai_access_banner", None)
        cfg["ai_access_ask"] = True
        ws.config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    root = dest.resolve()
    files = meta.get("files") if isinstance(meta.get("files"), dict) else {}
    with ws.connect() as cx:
        for doc_id, path in cx.execute("SELECT doc_id, path FROM documents").fetchall():
            arc = files.get(doc_id)
            if not arc:
                continue
            target = (root / arc).resolve()
            if target.is_relative_to(root) and target.is_file():
                cx.execute("UPDATE documents SET path=? WHERE doc_id=?", (str(target), doc_id))
    if prefix and not files:
        # a project folder zipped by hand: its documents still point into the folder it was zipped from
        name = prefix.rstrip("/").rsplit("/", 1)[-1]
        relocate_documents(dest / "enlens.sqlite", lambda parts: parts[len(parts) - parts[::-1].index(name):]
                           if name in parts[:-1] else None, root)
    for sub in ("tasks", "results", "exports", "report"):
        (dest / sub).mkdir(exist_ok=True)
    (dest / "bundle.json").unlink(missing_ok=True)
    sender = (meta.get("from") if isinstance(meta.get("from"), dict) else {}).get("id")
    from .people import me

    with ws.connect() as cx:  # roles (DESIGN-roles §3.4): the archives of removals stay on the computer that made them
        cx.execute("DELETE FROM removed_docs")
        # roles (§4.11): whose copy this is, so linking its folder later does not take it for another person's
        ws.set_meta(COPY_FOR, me(), cx)
    _forget_folder(ws, sender)
    if not merge_only:
        _adopt(ws, sender)
    return ws


# ---------------------------------------------------------------------------------------------
# 0.10: Move ENLENS to another computer: every project and the settings in one zip
# ---------------------------------------------------------------------------------------------
MOVE_MANIFEST = "enlens-move.json"
# settings that belong to this computer rather than to the person: not carried over. Roles (DESIGN-roles §4.11): the
# installation's own id never leaves the computer it was made on
MACHINE_SETTINGS = {"project", "benchmark_reference", "claude_plan_detected",  # 0.13.10: found per computer
                    "installation_id", "installation_place"}
# roles: who the person is comes only with "I am moving to this computer" (`import_all`)
PERSON_SETTINGS = ("person_id", "your_name")
# roles: the settings that hold a server's address; one that is not on this computer is taken only when the person
# ticks it (a back end left without its address keeps this computer's own)
SERVER_SETTINGS = ("ollama_url", "openai_url", "embed_url")
_SERVER_OF = {"ollama": "ollama_url", "openai": "openai_url"}  # a server kind and the setting of its address
MODES = ("moving", "both")
NOT_A_MOVE = "This zip was not made with “Move ENLENS to another computer”."
NOT_FRESH = ("This computer already has projects, so it keeps its own name and settings: choose “I will use both "
             "computers”.")


def is_move_zip(zip_path: str | Path) -> bool:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return MOVE_MANIFEST in zf.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def export_all(out: str | Path, progress=None) -> dict:
    """Write every project (each as its own project zip, see export_project) and the settings to the zip `out`. Quick
    looks that were not kept are left out, and so is any saved Claude API key: it never leaves this computer."""
    from . import home

    out = Path(out)
    names = [n for n in home.list_projects() if not home.is_temporary(n)]
    tmp_dir = Path(tempfile.mkdtemp(prefix="enlens-move-"))
    listed, skipped = [], []
    try:
        part = out.with_name(out.name + ".part")
        with zipfile.ZipFile(part, "w", allowZip64=True) as zf:
            for i, name in enumerate(names):
                if progress:
                    progress(i, len(names), name)
                try:
                    ws = home.open_project(name)
                except Exception as e:  # noqa: BLE001 - a project that cannot be opened is reported, not fatal
                    skipped.append({"name": name, "error": str(e)})
                    continue
                arc = f"projects/{i + 1:03d}.zip"
                one = tmp_dir / f"{i + 1:03d}.zip"
                stats = export_project(ws, one)
                zf.write(one, arc, compress_type=zipfile.ZIP_STORED)  # already compressed
                one.unlink()
                listed.append({"name": name, "file": arc, "documents": stats["documents"],
                               "linked": home.is_linked(name), "missing": stats["missing"]})
            settings = {k: v for k, v in home.load_settings().items() if k not in MACHINE_SETTINGS}
            current = home.load_settings().get("project") or ""
            zf.writestr(MOVE_MANIFEST, json.dumps({"format": "enlens-move", "version": __version__,
                                                   "made": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                   "projects": listed, "current": current,
                                                   "settings": settings}, indent=1))
        part.replace(out)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return {"projects": listed, "skipped": skipped, "size": out.stat().st_size}


def _move_meta(zf: zipfile.ZipFile) -> dict:
    try:
        meta = json.loads(zf.read(MOVE_MANIFEST))
    except (KeyError, ValueError) as e:
        raise ValueError(NOT_A_MOVE) from e
    if not isinstance(meta, dict) or meta.get("format") != "enlens-move":
        raise ValueError(NOT_A_MOVE)
    if not isinstance(meta.get("settings"), dict):
        meta["settings"] = {}
    return meta


def _fresh() -> bool:
    """Whether this computer has no project yet (a quick look that was not kept does not count)."""
    from . import home

    return not [n for n in home.list_projects() if not home.is_temporary(n)]


def _their_person(sent: dict) -> dict:
    from .people import ID_RE

    pid = sent.get("person_id")
    return {"id": pid if isinstance(pid, str) and ID_RE.fullmatch(pid) else None,
            "name": " ".join(str(sent.get("your_name") or "").split())[:60]}


def peek_move(zip_path: str | Path) -> dict:
    """What a move zip holds, to ask "moving" or "both computers" before anything is brought in (DESIGN-roles §4.11,
    §5.5): {"made", "version", "projects": [{"name", "documents"}], "person": {"id", "name"}, "settings": {key: value},
    "servers": [{"key", "url", "here"}], "fresh"} ("settings": what *Take the settings too* would take, but the
    servers' addresses, listed in "servers"; "here": the address is this computer, so it is taken with the settings
    without asking; "fresh": this computer has no project, so "moving" is offered)."""
    from . import home
    from .access import on_this_computer

    with zipfile.ZipFile(zip_path) as zf:
        meta = _move_meta(zf)
    sent = meta["settings"]
    projects = [{"name": str(p.get("name") or ""), "documents": p.get("documents") if isinstance(p.get("documents"), int)
                 else None} for p in meta.get("projects") or [] if isinstance(p, dict)]
    shown = {k: v for k, v in sent.items() if k in home.DEFAULTS and k not in MACHINE_SETTINGS
             and k not in PERSON_SETTINGS and k not in SERVER_SETTINGS}
    servers = [{"key": k, "url": str(sent[k]), "here": on_this_computer(str(sent[k]))}
               for k in SERVER_SETTINGS if isinstance(sent.get(k), str) and sent[k].strip()]
    return {"made": meta.get("made"), "version": meta.get("version"), "projects": projects,
            "person": _their_person(sent), "settings": shown, "servers": servers, "fresh": _fresh()}


def _settings_to_take(sent: dict, servers: Iterable[str]) -> dict:
    """The other computer's settings this one takes (*Take the settings too*): never this computer's own (the
    installation, the current project), nor who the person is (`import_all` decides that), nor an address that is not
    on this computer unless its key is in `servers`. A back end, a search server or the local AI for restricted
    documents whose address was not taken keeps this computer's own setting."""
    from . import home
    from .access import on_this_computer

    allowed = set(servers or ())
    wanted = {k: v for k, v in sent.items() if k in home.DEFAULTS and k not in MACHINE_SETTINGS
              and k not in PERSON_SETTINGS}
    dropped = {k for k in SERVER_SETTINGS if isinstance(wanted.get(k), str) and wanted[k].strip()
               and not on_this_computer(wanted[k]) and k not in allowed}
    for k in dropped:
        wanted.pop(k, None)
    if _SERVER_OF.get(str(wanted.get("backend"))) in dropped:
        for k in ("backend", "ollama_model", "openai_model"):
            wanted.pop(k, None)
    embed_url = sent.get("embed_url") if isinstance(sent.get("embed_url"), str) else ""
    if "embed_url" in dropped or (not embed_url.strip() and _SERVER_OF.get(str(wanted.get("embed_backend"))) in dropped):
        for k in ("embed_backend", "embed_url", "embed_model"):
            wanted.pop(k, None)
    if _SERVER_OF.get(str(wanted.get("restricted_server"))) in dropped:
        for k in ("restricted_server", "restricted_model"):
            wanted.pop(k, None)
    return wanted


def _take_settings(wanted: dict) -> bool:
    from . import home

    try:
        home.update_settings(wanted)
    except ValueError:
        # e.g. the old computer used Claude Code and this one keeps everything on it (local only)
        wanted = {k: v for k, v in wanted.items() if k not in ("backend", "allow_cloud", "allow_claude_code")}
        try:
            home.update_settings(wanted)
        except ValueError:
            wanted = {}
    return bool(wanted)


def import_all(zip_path: str | Path, mode: str, settings: bool = False, servers: Iterable[str] = (),
               name: str | None = None) -> dict:
    """Bring in a zip made by export_all: every project as a new project (a name in use gets " (2)"). Roles
    (DESIGN-roles §4.11) — the zip always asks first who this computer is (`mode`, no default):
    - "moving" (only on a computer with no project yet): the person moves here. Their id and name are taken **first**,
      then the projects come in, so they are this person's own, with their record of the shared folder.
    - "both": this computer becomes a person of its own. On a new computer a new person id, named `name` (the dialog
      proposes "<their name> (2)"); a computer in use keeps its own id and name. The projects come in as a colleague's
      do (no record of the shared folder; `ownership.adopt`).
    `settings`: take the other settings too (`_settings_to_take`; `servers`: the addresses not on this computer to
    take as well). Returns {"projects": [{"from", "name", "documents"}], "settings": bool, "current", "made",
    "version", "mode", "person": {"id", "name"}}."""
    from . import home, people

    if mode not in MODES:
        raise ValueError("Say first whether you are moving to this computer or will use both computers.")
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        meta = _move_meta(zf)
        sent = meta["settings"]
        fresh = _fresh()
        theirs = _their_person(sent)
        if mode == "moving":
            if not fresh:
                raise ValueError(NOT_FRESH)
            who = {k: v for k, v in (("person_id", theirs["id"]), ("your_name", theirs["name"])) if v}
            if who:
                home.update_settings(who)
        else:
            mine, my_name = people.me(), people.my_name()
            clean = " ".join(str(name or "").split())
            if fresh or mine == theirs["id"]:  # (a copy of the other computer's data folder is its person too)
                clean = clean or (f"{theirs['name']} (2)" if theirs["name"] else my_name)
                if clean:
                    home.new_identity(clean)
                else:
                    with home.LOCK:
                        home.update_settings({"person_id": "p" + uuid.uuid4().hex[:12]})
            elif clean and not my_name:
                home.update_settings({"your_name": clean})
        done, renamed = [], {}
        tmp_dir = Path(tempfile.mkdtemp(prefix="enlens-move-in-"))
        try:
            for p in meta.get("projects") or []:
                if not isinstance(p, dict):
                    continue
                arc = str(p.get("file") or "")
                if not arc.startswith("projects/") or ".." in arc or arc not in zf.namelist():
                    continue
                one = tmp_dir / "one.zip"
                with zf.open(arc) as src, open(one, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                pname = home.unique_project_name(str(p.get("name") or "Imported project"))
                ws = import_project(one, home.home() / "projects" / pname)
                one.unlink()
                n_docs = ws.scalar("SELECT COUNT(*) FROM documents") or 0
                done.append({"from": p.get("name"), "name": pname, "documents": n_docs})
                renamed[p.get("name")] = pname
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    applied = _take_settings(_settings_to_take(sent, servers)) if settings else False
    current = renamed.get(meta.get("current")) or (done[0]["name"] if done else None)
    if current and (fresh or not home.load_settings().get("project")):
        home.update_settings({"project": current})   # a computer in use stays on the project it was on
    else:
        current = home.load_settings().get("project") or current
    return {"projects": done, "settings": applied, "current": current, "made": meta.get("made"),
            "version": meta.get("version"), "mode": mode, "person": {"id": people.me(), "name": people.my_name()}}


# ---------------------------------------------------------------------------------------------
# roles (DESIGN-roles §4.11): a folder linked as a project is cleaned as an import is
# ---------------------------------------------------------------------------------------------
def _own_triggers(cx: sqlite3.Connection) -> set[str]:
    from .sync.changes import _PREFIX

    return {n for (n,) in cx.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND substr(name, 1, ?) = ?",
                                     (len(_PREFIX), _PREFIX))}


COPY_FOR = "copy_for"  # meta: the person a copy from a zip was made for (`import_project`)


def _maker(cx: sqlite3.Connection) -> dict | None:
    """Who made the project in this database, when it is another person than this one: {"id", "name"} (the last
    author of its research log, else the first person it knows), or None (it is this person's, or nobody's yet: the
    people it knows hold this person, or it is the copy a zip made for this person)."""
    from .people import me

    try:
        known = {pid: (name or "") for pid, name in cx.execute("SELECT person_id, name FROM people")}
    except sqlite3.Error:
        return None
    if not known or me() in known:
        return None
    try:
        row = cx.execute("SELECT value FROM meta WHERE key=?", (COPY_FOR,)).fetchone()
        if row and json.loads(row[0]) == me():
            return None
    except (sqlite3.Error, ValueError):
        pass
    pid = None
    try:
        row = cx.execute("SELECT person_id FROM research_log WHERE person_id IS NOT NULL AND person_id != '' "
                         "ORDER BY at DESC LIMIT 1").fetchone()
        pid = row[0] if row else None
    except sqlite3.Error:
        pass
    if pid is None or pid == me():
        pid = sorted(known)[0]
    return {"id": pid, "name": known.get(pid) or "a colleague"}


def _linked_config(root: Path, other: bool) -> tuple[dict | None, list[str]]:
    """config.json of a folder to link, as it is kept: `_clean_config`, and this computer's choice of a shared folder
    when the folder is this person's own. (None, []) when it needs no change; else (the new config, the keys that
    change: dropped or given another value)."""
    from .sync.folder import FOLDER

    f = root / "config.json"
    try:
        raw = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except (OSError, ValueError):
        raw = "unreadable"
    if raw is None:
        return None, []
    new = _clean_config(raw)
    if not other and isinstance(raw, dict) and isinstance(raw.get(FOLDER), str):
        new[FOLDER] = raw[FOLDER]
    old = raw if isinstance(raw, dict) else {}
    changed = sorted(k for k in old if old.get(k) != new.get(k)) if isinstance(raw, dict) else ["config.json"]
    return (new if new != old else None), changed


def _sqlite(root: Path) -> sqlite3.Connection:
    db = root / "enlens.sqlite"
    if not db.is_file():
        raise ValueError(f"No workspace (enlens.sqlite) in {root}.")
    return sqlite3.connect(db, timeout=60)


def check_linked(path: str | Path) -> dict:
    """What linking an existing folder as a project would clean, without changing anything: {"other": {"id", "name"} |
    None (made by another person), "triggers": n (not counting ENLENS's own change counters, made again by the next
    round), "views": n, "config": [keys changed], "bib_paths": n (the bibliography's works with file paths, cleared
    only for another person's folder), "cache": bool (a cache/ folder, removed only for another person's)}."""
    from .sharing import without_paths

    root = Path(path).expanduser().resolve()
    cx = _sqlite(root)
    try:
        try:
            kinds = cx.execute("SELECT type, name FROM sqlite_master WHERE type IN ('trigger', 'view')").fetchall()
        except sqlite3.DatabaseError as e:
            raise ValueError(DAMAGED_DB.replace("in this zip", "in this folder")) from e
        own = _own_triggers(cx)
        other = _maker(cx)
        try:
            bib = sum(1 for (files,) in cx.execute("SELECT files_json FROM bib_items")
                      if files and without_paths(files) != files)
        except sqlite3.Error:
            bib = 0
    finally:
        cx.close()
    _new, changed = _linked_config(root, other is not None)
    return {"other": other, "triggers": sum(1 for k, n in kinds if k == "trigger" and n not in own),
            "views": sum(1 for k, _n in kinds if k == "view"), "config": changed, "bib_paths": bib,
            "cache": (root / "cache").is_dir()}


def clean_linked(path: str | Path, other: bool) -> dict:
    """Clean a folder before it is linked as a project, as a project from a zip is (`import_project`): always the
    quick check, its rows alone (`_rows_only`: triggers and views go, a table that works out its own values is refused)
    and its config.json (`_clean_config`; the old file kept as config.json.before-linking). `other` (another person
    made it): also no record of a shared folder and no shared-folder path (`_forget_folder`), the bibliography's file
    paths go, cache/ is removed (made again), backups/ is moved to backups.before-linking/, the records of this copy
    alone that came with it go, and the project starts as its maker had its documents (`ownership.adopt`). Returns
    what `check_linked` found."""
    root = Path(path).expanduser().resolve()
    report = check_linked(root)
    cx = _sqlite(root)
    try:
        ok = cx.execute("PRAGMA quick_check").fetchone()
        if not ok or ok[0] != "ok":
            raise ValueError(DAMAGED_DB.replace("in this zip", "in this folder"))
        _rows_only(cx)  # before ENLENS opens it: a trigger would run at the first change opening it makes
    except sqlite3.DatabaseError as e:
        raise ValueError(DAMAGED_DB.replace("in this zip", "in this folder")) from e
    finally:
        cx.close()
    new, _changed = _linked_config(root, other)
    if new is not None:
        f = root / "config.json"
        if f.exists():
            shutil.copyfile(f, root / "config.json.before-linking")
        f.write_text(json.dumps(new, indent=2), encoding="utf-8")
    if other:
        maker = report["other"]
        if (root / "cache").is_dir():
            shutil.rmtree(root / "cache", ignore_errors=True)
        if (root / "backups").is_dir():
            dest = root / "backups.before-linking"
            if dest.exists():
                dest = root / f"backups.before-linking-{time.strftime('%Y%m%d-%H%M%S')}"
            (root / "backups").rename(dest)
        ws = Workspace.open(root)
        try:
            _forget_folder(ws, None)
            with ws.connect() as c:
                for t in ("removed_docs", "sync_via", "sync_from", "sync_refused"):
                    c.execute(f"DELETE FROM {t}")
            if maker and maker.get("id"):
                try:
                    from .ownership import adopt
                except ImportError:  # an app built without shared projects
                    adopt = None
                if adopt is not None:
                    adopt(ws, maker["id"])
        finally:
            ws.close_all()
    return report
