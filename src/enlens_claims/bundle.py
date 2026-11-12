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
import shutil
import sqlite3
import tempfile
import time
import unicodedata
import zipfile
from pathlib import Path

from . import __version__
from .store import Workspace

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
    from .sync import formats as sync_formats

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
        cx = sqlite3.connect(db)
        try:
            with cx:
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
                                                   "name": ws.root.name, **stamp, **sync_formats.stamp(),
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
    with ws.connect() as cx:
        for t in ("sync_written", "sync_folder_read", "sync_folder_docs"):
            cx.execute(f"DELETE FROM {t}")


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


def _open_staged(folder: Path) -> bool:
    """0.14.3: check the database unpacked into the staging folder and open it there (which adds the tables and
    columns of this version), before the project is put in place. Raises ValueError with a plain message when it
    cannot be read. Returns whether it was made before 0.11 (per-document AI settings)."""
    try:
        cx = sqlite3.connect(folder / "enlens.sqlite")
        try:
            ok = cx.execute("PRAGMA quick_check").fetchone()
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
                _safe_extract(zf, staging, [MAX_IMPORT], strip=prefix)
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
            before_011 = _open_staged(staging)
            if dest.exists():
                dest.rmdir()
            staging.replace(dest)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    ws = Workspace.open(dest)  # opened in staging already: the tables and columns of this version are there
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
    _forget_folder(ws, sender)
    if not merge_only:
        _adopt(ws, sender)
    return ws


# ---------------------------------------------------------------------------------------------
# 0.10: Move ENLENS to another computer: every project and the settings in one zip
# ---------------------------------------------------------------------------------------------
MOVE_MANIFEST = "enlens-move.json"
# settings that belong to this computer rather than to the person: not carried over
MACHINE_SETTINGS = {"project", "benchmark_reference", "claude_plan_detected"}  # 0.13.10: found per computer


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


def import_all(zip_path: str | Path, settings: bool | None = None) -> dict:
    """Bring in a zip made by export_all: every project as a new project (a name in use gets " (2)"), and the
    settings when `settings` is True, or (None) when this computer has no project yet: a new computer takes the old
    one's settings, one in use keeps its own. Returns {"projects": [{"from", "name", "documents"}], "settings": bool}."""
    from . import home

    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        try:
            meta = json.loads(zf.read(MOVE_MANIFEST))
        except (KeyError, ValueError) as e:
            raise ValueError("This zip was not made with “Move ENLENS to another computer”.") from e
        if meta.get("format") != "enlens-move":
            raise ValueError("This zip was not made with “Move ENLENS to another computer”.")
        fresh = not [n for n in home.list_projects() if not home.is_temporary(n)]
        take_settings = fresh if settings is None else settings
        done, renamed = [], {}
        tmp_dir = Path(tempfile.mkdtemp(prefix="enlens-move-in-"))
        try:
            for p in meta.get("projects") or []:
                arc = str(p.get("file") or "")
                if not arc.startswith("projects/") or ".." in arc or arc not in zf.namelist():
                    continue
                one = tmp_dir / "one.zip"
                with zf.open(arc) as src, open(one, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                name = home.unique_project_name(str(p.get("name") or "Imported project"))
                ws = import_project(one, home.home() / "projects" / name)
                one.unlink()
                n_docs = ws.scalar("SELECT COUNT(*) FROM documents") or 0
                done.append({"from": p.get("name"), "name": name, "documents": n_docs})
                renamed[p.get("name")] = name
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    applied = False
    if take_settings and isinstance(meta.get("settings"), dict):
        wanted = {k: v for k, v in meta["settings"].items() if k in home.DEFAULTS and k not in MACHINE_SETTINGS}
        try:
            home.update_settings(wanted)
        except ValueError:
            # e.g. the old computer used Claude Code and this one keeps everything on it (local only)
            wanted = {k: v for k, v in wanted.items() if k not in ("backend", "allow_cloud", "allow_claude_code")}
            try:
                home.update_settings(wanted)
            except ValueError:
                wanted = {}
        applied = bool(wanted)
    current = renamed.get(meta.get("current")) or (done[0]["name"] if done else None)
    if current and (fresh or not home.load_settings().get("project")):
        home.update_settings({"project": current})   # a computer in use stays on the project it was on
    else:
        current = home.load_settings().get("project") or current
    return {"projects": done, "settings": applied, "current": current, "made": meta.get("made"),
            "version": meta.get("version")}
