"""Shared projects (0.14): each person keeps their own copy of a project, on their own computer and Claude plan, and
they exchange their work as a file.

The file is the project zip of bundle.py (*Download as a zip*). Since 0.14 it says which project it is
(`project_uid`) and who sent it, and its database holds the fingerprints of every check, theme run and codebook as
they were whenever they were sent or brought in (`sync_seen`). `bring_in` merges such a file into this copy:

- what is new comes in: documents, checks, theme runs, codebooks, AI work, links between terms, the bibliography;
- what both copies have and only one of them changed since it was last exchanged: the newer version is kept;
- what both changed (a *sync clash*): both are kept, the colleague's version as a copy beside yours, marked as such
  (`sync_copies`), so nothing is lost and you choose later;
- a document both of you added from the same file, but read into different text (another ENLENS version, text
  recognition on one computer and not the other): every quote is a position in the text, so the colleague's reading
  comes in as a document of its own, with their results attached to it. 0.18: unless one reading is known as an
  earlier reading of the other (*Read with the new reader*): then it is one document, each keeps their reading, and
  the colleague's results are placed on yours (`readings`);
- what people decided is kept per person (judgements of excerpts, reviews of labels, links and themes: people.py):
  yours count in your copy, a colleague's count where you decided nothing, and the two can be compared;
- who may read a document with AI: the stricter setting of the two copies, with a warning where AI results exist that
  the stricter setting would not have allowed;
- what was removed from this copy (a document, a check, a theme run) does not come back;
- 0.18: only what its owner shared is sent to a colleague (sharing.py); what they took back stays, marked, and is
  not passed on.

AI work on a document that both copies did (labels of a codebook, reference chains) is not doubled: yours is kept.
Nothing is sent anywhere: the merge reads the file on this computer.

0.18: a package, split along what each part does, and every name importable from here as before
(`from enlens_claims import sync; sync.bring_in(...)`):

- `common`: the tables and columns the sync treats alike, documents named by their content (`text_fp`), row helpers;
- `fingerprints`: the units compared (a check, a theme run, a codebook) and how a newer version is told
  (`record_seen`);
- `merge`: `_Merge`, the rules above, step by step; `codebook_merge`, `readings` and `share_merge`: its parts for
  codebooks, for other readings of a document, and for what each person shared (sharing.py);
- `report`: what a merge did, in words (`summary`), and the Projects page's overview (`overview`, `copies_of`);
- `formats`: the format of what is exchanged, so a copy refuses what it would merge wrongly;
- here: the exchange as a zip file (`before_sending`, `peek`, `bring_in`);
- `folder`: 0.18, the exchange through a folder the team shares (OneDrive, Dropbox, a network drive): each copy writes
  what its person shared into its own subfolder as numbered bundles, and brings in the others' through `merge`.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .. import people
from ..store import Workspace, now
from . import formats
from .codebook_merge import CodebookRules  # noqa: F401 - importable from here as before
from .common import (DOC_ID, FORMAT, ID_COLS, LOCAL_ONLY, OWN_RULES, UNFINISHED, _TEXT_COLS, _TOKEN,  # noqa: F401
                     _cols, _pk, _rows, _sha, _tokens, base_id, text_fp, text_fps)
from .fingerprints import (_COLS_0142, _COLS_0142_SETS, _FP_TABLES, _HOW, _PERSONAL, _canon,  # noqa: F401
                           _check_unit, _codebook_fp, _core_columns, _fingerprints, _fp, _home_codebooks, _known,
                           _literal, _plain, _running, _themes_unit, _used_codebooks, record_seen)
from .merge import _Merge  # noqa: F401
from .report import _ORIGINALS, _label, _n, copies_of, history, overview, summary  # noqa: F401


class NotThisProject(ValueError):
    """The file comes from another project (or from an ENLENS before 0.14, which does not say)."""

    def __init__(self, message: str, info: dict):
        super().__init__(message)
        self.info = info


# ---------------------------------------------------------------------------------------------
# sending
# ---------------------------------------------------------------------------------------------
def before_sending(ws: Workspace) -> dict:
    """Ready this copy to be sent (called by bundle.export_project): its judgements and reviews from before 0.14 are
    yours, your name is in it, and the state of every check, theme run and codebook is written down. Returns what
    the file says about itself: {"project_uid", "from": {"id", "name"}, "sent_at"}."""
    me, name = people.me(), people.my_name()
    from .. import ownership  # 0.18 L2: what this person changed of the documents goes along as proposals

    ownership.settle(ws, apply=False, leaving=True)
    with ws.connect() as cx:
        uid = ws.project_uid(cx)
        people.adopt(cx, me)
        people.remember(cx, me, name)
        record_seen(ws, cx)
    return {"project_uid": uid, "from": {"id": me, "name": name}, "sent_at": now()}


def home_codebooks(ws: Workspace) -> list[Path]:
    """The codebooks this project uses that are kept in the home folder (all projects), not in the project: they go
    into the file too, or a colleague could not read the labels made with them."""
    from ..home import home

    out = []
    with ws.connect() as cx:
        names = _used_codebooks(cx)
    for name in sorted(names):
        if not (Path(ws.root) / "frameworks" / f"{name}.csv").is_file():
            for ext in ("csv", "json"):
                p = home() / "frameworks" / f"{name}.{ext}"
                if p.is_file():
                    out.append(p)
    return out


# ---------------------------------------------------------------------------------------------
# bringing a colleague's work in
# ---------------------------------------------------------------------------------------------
def peek(zip_path: str | Path) -> dict:
    """What a project zip says about itself without unpacking it: {"project_uid", "from", "name", "version",
    "sync_format", "sync_needs", "scope"} (0.18: its format, formats.py, and whether it holds only what its sender
    shared, "shared", or the whole project, "all")."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            meta = json.loads(zf.read("bundle.json"))
    except (KeyError, ValueError, zipfile.BadZipFile, OSError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    written, needs = formats.of(meta)
    return {"project_uid": meta.get("project_uid"), "from": meta.get("from") or None, "name": meta.get("name"),
            "version": meta.get("version"), "sync_format": written, "sync_needs": needs,
            "scope": "shared" if meta.get("scope") == "shared" else "all"}


def bring_in(ws: Workspace, zip_path: str | Path, anyway: bool = False) -> dict:
    """Merge a colleague's project zip into this copy (see the module's notes). Raises NotThisProject when the file
    is not known to be this project, unless `anyway`. Returns the report (see `_Merge.report`), also kept in
    `sync_log`."""
    from .. import bundle

    zip_path = Path(zip_path)
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("This is not a zip file. Choose the file your colleague made with “Download as a zip”.")
    if bundle.is_move_zip(zip_path):
        raise ValueError("This file holds everything from another computer, not one project. Bring it in under "
                         "Projects → Import a project (.zip).")
    info = peek(zip_path)
    newer = formats.problem(info)  # 0.18: a newer format this copy would merge wrongly: refused, whatever `anyway`
    if newer:
        raise ValueError(newer)
    mine = ws.meta("project_uid")
    theirs = info["project_uid"]
    known = set(ws.meta("project_uids_known") or [])
    if not anyway and not (theirs and (theirs == mine or theirs in known)):
        who = (info["from"] or {}).get("name") or "a colleague"
        if not theirs:
            msg = (f"This file was made with ENLENS {info['version'] or 'before 0.14'}, which does not say which project "
                   "it is. Bring it in only if it is a copy of this project.")
        else:
            msg = (f"This file is the project “{info['name'] or '?'}” of {who}, which is not known as a copy of this "
                   "project. Bring it in only if you mean to combine the two.")
        raise NotThisProject(msg, info)
    tmp = Path(tempfile.mkdtemp(prefix="enlens-bring-in-"))
    inc = None
    try:
        inc = bundle.import_project(zip_path, tmp / "work", merge_only=True)
        _backup(ws)
        report = _Merge(ws, inc, info).run()
    finally:
        if inc is not None:
            inc.close()
        shutil.rmtree(tmp, ignore_errors=True)
    with ws.connect() as cx:
        if theirs and not mine:
            ws.set_meta("project_uid", theirs, cx)  # now the same project as the colleague's
        elif theirs and theirs != mine and theirs not in known:
            ws.set_meta("project_uids_known", sorted(known | {theirs}), cx)
        log_bring_in(cx, report)
    from .. import ownership  # 0.18 L2: what the owner decided is followed here, and what came in is looked at

    report["owner"] = ownership.settle(ws)
    return report


def log_bring_in(cx: sqlite3.Connection, report: dict, where: str = "") -> None:
    """Keep a merge's report (`sync_log`, the Projects page's history) and say in the research log when whose work came
    in and what it brought (0.16). `where`: how it came (0.18: " from the shared folder")."""
    from .. import researchlog

    cx.execute("INSERT INTO sync_log(at, person_id, report_json) VALUES (?,?,?)",
               (report["at"], report["from"]["id"], json.dumps(report, ensure_ascii=False)))
    who = report["from"]["name"] or "a colleague"
    researchlog.record(cx, "sync", f"Brought in {who}'s work{where}. " + " ".join(report.get("lines") or []),
                       data={"from": report["from"], "version": report.get("version")})


def _backup(ws: Workspace) -> Path:
    """The project's database as it was before the merge (one copy, replaced each time): backups/before-bringing-in."""
    folder = Path(ws.root) / "backups"
    folder.mkdir(exist_ok=True)
    out = folder / "before-bringing-in.sqlite"
    part = out.with_name(out.name + ".part")
    src, dst = sqlite3.connect(ws.db_path, timeout=60), sqlite3.connect(part)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    part.replace(out)
    return out
