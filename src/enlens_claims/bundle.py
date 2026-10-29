"""A whole project in one zip file, to hand to a colleague or move to another computer.

    enlens --ws X export-project out.zip
    enlens import-project in.zip --ws Y

The zip holds:
- `enlens.sqlite`: a consistent copy of the project's database, made with SQLite's backup API (the project can be
  in use while it is copied);
- `config.json`, and the project's own codebooks (`frameworks/`);
- `uploads/`: the files added through the app;
- the original file of every other document: kept at its place when it is inside the project folder, and as
  `originals/<doc_id>/<name>` when it was read from somewhere else on the computer;
- `bundle.json`: what is where (the version that made it and, per document, its file in the zip).

Everything is written to a temporary file on disk and copied in chunks, never held in memory. Importing unpacks
with the same guards as adding a zip of sources (no path can leave the project folder, a size budget against zip
bombs), opens the database (which adds the columns of this version) and points each document at its file in the
new folder.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from . import __version__
from .store import Workspace

STORED = {".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".docx", ".xlsx", ".pptx", ".gz"}  # compressed
MAX_IMPORT = 8 * 1024 ** 3


def _add(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    kind = zipfile.ZIP_STORED if path.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
    zf.write(path, arcname, compress_type=kind)


def export_project(ws: Workspace, out: str | Path) -> dict:
    """Write the project to the zip file `out`; returns what it holds."""
    from .sources import original_file

    out = Path(out)
    root = ws.root.resolve()
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
        files: dict[str, str] = {}
        missing: list[str] = []
        stats = {"documents": 0, "uploads": 0, "originals": 0, "missing": missing}
        part = out.with_name(out.name + ".part")
        with zipfile.ZipFile(part, "w", allowZip64=True) as zf:
            zf.write(db, "enlens.sqlite", compress_type=zipfile.ZIP_DEFLATED)
            if ws.config_path.exists():
                zf.write(ws.config_path, "config.json")
            for folder in ("uploads", "frameworks"):
                base = root / folder
                if base.is_dir():
                    for f in sorted(base.rglob("*")):
                        if f.is_file() and not f.is_symlink():
                            _add(zf, f, f.relative_to(root).as_posix())
                            stats["uploads"] += folder == "uploads"
            written = {n for n in zf.namelist()}
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
                files[r["doc_id"]] = arc
            zf.writestr("bundle.json", json.dumps({"format": "enlens-project", "version": __version__,
                                                   "name": ws.root.name, "files": files}, indent=1))
        part.replace(out)
        stats["size"] = out.stat().st_size
        return stats
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def import_project(zip_path: str | Path, dest: str | Path) -> Workspace:
    """Unpack a project zip into the folder `dest` (which must not exist yet, or be empty) and open it."""
    from .ingest import _safe_extract

    zip_path, dest = Path(zip_path), Path(dest)
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("This is not a zip file.")
    if dest.exists() and any(dest.iterdir()):
        raise ValueError(f"The folder {dest} is not empty: choose another name.")
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        if "enlens.sqlite" not in names:
            raise ValueError("This zip holds no ENLENS project (there is no enlens.sqlite in it). To add documents, "
                             "use Add documents instead.")
        total = sum(i.file_size for i in zf.infolist())
        if total > MAX_IMPORT:
            raise ValueError(f"The project in this zip is larger than {MAX_IMPORT // 1024 ** 3} GB unpacked.")
        staging = dest.with_name(dest.name + ".importing")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            _safe_extract(zf, staging, [MAX_IMPORT])
            if not (staging / "enlens.sqlite").is_file():
                raise ValueError("The project's database could not be unpacked.")
            try:
                meta = json.loads((staging / "bundle.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
            if dest.exists():
                dest.rmdir()
            staging.replace(dest)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    ws = Workspace.open(dest)  # adds the tables and columns of this version
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
    for sub in ("tasks", "results", "exports", "report"):
        (dest / sub).mkdir(exist_ok=True)
    (dest / "bundle.json").unlink(missing_ok=True)
    return ws
