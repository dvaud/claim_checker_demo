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
  comes in as a document of its own, with their results attached to it;
- what people decided is kept per person (judgements of excerpts, reviews of labels, links and themes: people.py):
  yours count in your copy, a colleague's count where you decided nothing, and the two can be compared;
- who may read a document with AI: the stricter setting of the two copies, with a warning where AI results exist that
  the stricter setting would not have allowed;
- what was removed from this copy (a document, a check, a theme run) does not come back.

AI work on a document that both copies did (labels of a codebook, reference chains) is not doubled: yours is kept.
Nothing is sent anywhere: the merge reads the file on this computer.

How a version is told newer: a unit's fingerprint names documents by their content (file and text), not by their id
in a copy, so both copies compute the same fingerprint. A unit whose fingerprint here is among the states the other
copy has had (its `sync_seen` and its current one) is older here; the other way round, older there; neither: a clash.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable

from . import people
from .store import Workspace, now

FORMAT = "enlens-project"
_TOKEN = re.compile(r"[A-Za-z0-9_\-]+")
DOC_ID = re.compile(r"[A-Za-z0-9_]{1,64}(-[0-9a-f]{6})?")  # a document id ("d1a2b3c4d5e", a copy "…-0f1e2d"): never a path
UNFINISHED = ("pending", "retry")
_TEXT_COLS = {"text"}  # never rewritten (documents', passages' and hypotheses' own words)
# the tables of a copy that are never merged: derived again from the documents, or about this copy only
LOCAL_ONLY = {"meta", "embeddings", "code_vectors", "terms", "term_mentions", "concepts", "concept_terms", "task_claims",
              "sync_log", "sqlite_sequence"}
# merged by their own rules below; every other table (the SDG pack's, an add-on's) is merged row by row, keeping yours
OWN_RULES = {"documents", "pages", "paragraphs", "headings", "passages", "labels", "mentions", "tasks", "results",
             "ai_sent", "hypotheses", "user_claims", "second_opinions", "judgements", "people", "theme_runs", "themes",
             "theme_members", "reviews", "concept_links", "bib_items", "bib_links", "sync_seen", "sync_copies",
             "sync_removed", "verifications"}
# the columns that hold ids of documents, passages, tasks, checks, runs (rewritten when an id changes in a merge)
ID_COLS = {"doc_id", "passage_id", "task_id", "claim_id", "subject_id", "ver_id", "hyp_id", "run_id", "item_id",
           "label_id", "window", "payload_json", "options_json", "parts_json", "key", "of_key", "origin_id"}


class NotThisProject(ValueError):
    """The file comes from another project (or from an ENLENS before 0.14, which does not say)."""

    def __init__(self, message: str, info: dict):
        super().__init__(message)
        self.info = info


def _sha(*parts: Any) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p if isinstance(p, bytes) else str(p).encode("utf-8")))
        h.update(b"\0")
    return h.hexdigest()


def base_id(doc_id: str) -> str:
    """The document id of a file, without the mark of a sync-clash copy ("d1a2b3c4d5e-0f1e2d" -> "d1a2b3c4d5e")."""
    return doc_id.split("-", 1)[0]


def text_fp(text: str | None) -> str:
    """The fingerprint of a document's text (16 hex digits)."""
    return _sha(text or "")[:16]


def text_fps(db: sqlite3.Connection | Workspace, again: bool = False) -> dict[str, str]:
    """{doc_id: fingerprint of its text}, computed once per document and kept (`documents.text_fp`); `again` works
    every one out anew (a colleague's file: what it says about itself is not trusted)."""
    cx = db._conn() if isinstance(db, Workspace) else db
    out = {}
    missing = []
    for doc_id, fp in cx.execute("SELECT doc_id, text_fp FROM documents").fetchall():
        if fp and not again:
            out[doc_id] = fp
        else:
            missing.append(doc_id)
    for doc_id in missing:
        (text,) = cx.execute("SELECT text FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        out[doc_id] = text_fp(text)
        cx.execute("UPDATE documents SET text_fp=? WHERE doc_id=?", (out[doc_id], doc_id))
    return out


def _tokens(s: str, mp: dict[str, str]) -> str:
    return _TOKEN.sub(lambda m: mp.get(m.group(0), m.group(0)), s) if mp and s else s


def _rows(cx: sqlite3.Connection, sql: str, args: Iterable = ()) -> list[dict]:
    cur = cx.execute(sql, tuple(args))
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _cols(cx: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in cx.execute(f"PRAGMA table_info({table})")]


def _pk(cx: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in sorted(cx.execute(f"PRAGMA table_info({table})"), key=lambda r: r[5]) if r[5]]


# ---------------------------------------------------------------------------------------------
# units: a check, a theme run, a codebook; their rows and fingerprints
# ---------------------------------------------------------------------------------------------
_PERSONAL = {"user_verdict", "user_note", "user_at", "user_quote", "user_start", "user_end", "user_by"}


def _check_unit(cx: sqlite3.Connection, hyp_id: str) -> dict[str, list[dict]]:
    hyp = _rows(cx, "SELECT * FROM hypotheses WHERE hyp_id=?", (hyp_id,))
    claims = _rows(cx, "SELECT * FROM user_claims WHERE hyp_id=? ORDER BY claim_id", (hyp_id,))
    cids = [c["claim_id"] for c in claims]
    q = ",".join("?" * len(cids))
    ver = _rows(cx, f"SELECT * FROM verifications WHERE subject_kind='user_claim' AND subject_id IN ({q}) "
                    "ORDER BY ver_id", cids) if cids else []
    sec = _rows(cx, f"SELECT * FROM second_opinions WHERE subject_id IN ({q}) ORDER BY subject_id, passage_id, model",
                cids) if cids else []
    pats = [f"decompose:{hyp_id}"] + [p for c in cids for p in (f"expand:{c}", f"check:{c}")]
    likes = [p for c in cids for p in (f"check:{c}:%", f"reread:{c}:%", f"second:check:{c}:%")]
    where = " OR ".join(["task_id=?"] * len(pats) + ["task_id LIKE ?"] * len(likes))
    tasks = _rows(cx, f"SELECT * FROM tasks WHERE {where} ORDER BY task_id", pats + likes)
    tids = [t["task_id"] for t in tasks]
    res = _rows(cx, f"SELECT * FROM results WHERE task_id IN ({','.join('?' * len(tids))}) ORDER BY task_id, attempt",
                tids) if tids else []
    return {"hypotheses": hyp, "user_claims": claims, "verifications": ver, "second_opinions": sec, "tasks": tasks,
            "results": res}


def _themes_unit(cx: sqlite3.Connection, run_id: str) -> dict[str, list[dict]]:
    head = f"theme:{run_id}:"
    tasks = _rows(cx, "SELECT * FROM tasks WHERE kind='theme' AND substr(task_id, 1, ?) = ? ORDER BY task_id",
                  (len(head), head))
    tids = [t["task_id"] for t in tasks]
    return {"theme_runs": _rows(cx, "SELECT * FROM theme_runs WHERE run_id=?", (run_id,)),
            "themes": _rows(cx, "SELECT * FROM themes WHERE run_id=? ORDER BY theme_id", (run_id,)),
            "theme_members": _rows(cx, "SELECT * FROM theme_members WHERE run_id=? ORDER BY passage_id", (run_id,)),
            "tasks": tasks,
            "results": _rows(cx, f"SELECT * FROM results WHERE task_id IN ({','.join('?' * len(tids))}) ORDER BY "
                                 "task_id, attempt", tids) if tids else []}


def _fp(unit: dict[str, list[dict]], canon: dict[str, str]) -> str:
    """A unit's fingerprint: what was found and read, with documents named by their content; not how it was produced
    (tasks, results, the ids made from them) and not what people decided (kept per person)."""
    parts = []
    for t in sorted(unit):
        if t in ("tasks", "results"):
            continue
        # each row named by its content, in an order that does not depend on ids
        rows = sorted(_tokens(json.dumps({k: v for k, v in r.items() if k not in _PERSONAL and k not in ("rowid", "ver_id")},
                                         sort_keys=True, ensure_ascii=False, default=str), canon) for r in unit[t])
        parts.append(t + "\n" + "\n".join(rows))
    return _sha("\n\n".join(parts))[:20]


def _canon(cx: sqlite3.Connection) -> dict[str, str]:
    """{doc_id: the document named by its content}: the same in every copy that has the same reading of a file, and
    for a document removed since (checks keep what they read of it), from the note of its removal."""
    out = {d: f"{base_id(d)}.{fp}" for d, fp in cx.execute("SELECT key, fp FROM sync_removed WHERE kind='document' "
                                                            "AND fp IS NOT NULL").fetchall()}
    out.update({d: f"{base_id(d)}.{fp}" for d, fp in text_fps(cx).items()})
    return out


def _codebook_fp(folder: Path, name: str) -> str | None:
    """A codebook's fingerprint: its codes and settings, not its title (a sync-clash copy has its own title)."""
    csv = folder / f"{name}.csv"
    if not csv.is_file():
        return None
    side = folder / f"{name}.json"
    try:
        meta = json.loads(side.read_text(encoding="utf-8")) if side.is_file() else {}
    except ValueError:
        meta = {}
    meta.pop("title", None)
    return _sha(csv.read_bytes(), json.dumps(meta, sort_keys=True))[:20]


def _plain(ids: Iterable[str], key: str, of: str) -> dict[str, str]:
    """For a sync-clash copy `key` of `of` ("h1-0c5ab4" of "h1"): its ids without the copy's mark, so it can be
    compared with the version it was copied from."""
    tag = key[len(of) + 1:] if key.startswith(of + "-") else ""
    return {i: i[:-len(tag) - 1] for i in ids if tag and i.endswith("-" + tag)}


def _home_codebooks() -> Path:
    from .home import home

    return home() / "frameworks"


def _used_codebooks(cx: sqlite3.Connection) -> set[str]:
    from .frameworks import BUNDLED

    names = {r[0] for r in cx.execute("SELECT DISTINCT framework FROM labels UNION SELECT DISTINCT framework FROM "
                                      "hypotheses UNION SELECT DISTINCT framework FROM user_claims") if r[0]}
    return names - set(BUNDLED)


def record_seen(ws: Workspace, cx: sqlite3.Connection) -> None:
    """Write down the fingerprint of every check, theme run and codebook as it is now (when sent or brought in)."""
    canon = _canon(cx)
    rows = []
    for (hid,) in cx.execute("SELECT hyp_id FROM hypotheses").fetchall():
        rows.append(("check", hid, _fp(_check_unit(cx, hid), canon)))
    for (rid,) in cx.execute("SELECT run_id FROM theme_runs").fetchall():
        rows.append(("themes", rid, _fp(_themes_unit(cx, rid), canon)))
    folder = Path(ws.root) / "frameworks"
    for name in sorted(_used_codebooks(cx)):
        fp = _codebook_fp(folder, name)
        if fp:
            rows.append(("codebook", name, fp))
    cx.executemany("INSERT OR IGNORE INTO sync_seen(kind, key, fp) VALUES (?,?,?)", rows)


# ---------------------------------------------------------------------------------------------
# sending
# ---------------------------------------------------------------------------------------------
def before_sending(ws: Workspace) -> dict:
    """Ready this copy to be sent (called by bundle.export_project): its judgements and reviews from before 0.14 are
    yours, your name is in it, and the state of every check, theme run and codebook is written down. Returns what
    the file says about itself: {"project_uid", "from": {"id", "name"}, "sent_at"}."""
    me, name = people.me(), people.my_name()
    with ws.connect() as cx:
        uid = ws.project_uid(cx)
        people.adopt(cx, me)
        people.remember(cx, me, name)
        record_seen(ws, cx)
    return {"project_uid": uid, "from": {"id": me, "name": name}, "sent_at": now()}


def home_codebooks(ws: Workspace) -> list[Path]:
    """The codebooks this project uses that are kept in the home folder (all projects), not in the project: they go
    into the file too, or a colleague could not read the labels made with them."""
    from .home import home

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
    """What a project zip says about itself without unpacking it: {"project_uid", "from", "name", "version"}."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            meta = json.loads(zf.read("bundle.json"))
    except (KeyError, ValueError, zipfile.BadZipFile, OSError):
        meta = {}
    return {"project_uid": meta.get("project_uid"), "from": meta.get("from") or None, "name": meta.get("name"),
            "version": meta.get("version")}


def bring_in(ws: Workspace, zip_path: str | Path, anyway: bool = False) -> dict:
    """Merge a colleague's project zip into this copy (see the module's notes). Raises NotThisProject when the file
    is not known to be this project, unless `anyway`. Returns the report (see `_Merge.report`), also kept in
    `sync_log`."""
    from . import bundle

    zip_path = Path(zip_path)
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("This is not a zip file. Choose the file your colleague made with “Download as a zip”.")
    if bundle.is_move_zip(zip_path):
        raise ValueError("This file holds everything from another computer, not one project. Bring it in under "
                         "Projects → Import a project (.zip).")
    info = peek(zip_path)
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
        inc = bundle.import_project(zip_path, tmp / "work")
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
        cx.execute("INSERT INTO sync_log(at, person_id, report_json) VALUES (?,?,?)",
                   (report["at"], report["from"]["id"], json.dumps(report, ensure_ascii=False)))
    return report


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


class _Merge:
    def __init__(self, ws: Workspace, inc: Workspace, info: dict):
        self.ws, self.inc = ws, inc
        self.icx = inc._conn()
        sender = info.get("from") or {}
        self.sender = {"id": sender.get("id") if people.ID_RE.fullmatch(sender.get("id") or "") else people.UNKNOWN,
                       "name": (sender.get("name") or "").strip()}
        self.me = people.me()
        self.at = now()
        self.ids: dict[str, str] = {}      # an incoming id -> its id here, where they differ
        self.fw: dict[str, str] = {}       # an incoming codebook name -> its name here, where they differ
        self.docs: dict[str, str] = {}     # every incoming document kept -> its id here
        self.skip_docs: set[str] = set()   # incoming documents not brought in (removed here, or not a document id)
        self.new_docs: list[str] = []      # incoming ids of the documents that come in now
        self.claims: set[str] = set()      # checks' parts whose judgements to bring in (ids here)
        self.history: set[tuple[str, str]] = set()  # units whose states in the colleague's copy become this copy's
        self.files: list[tuple[Path, Path]] = []    # files to copy once the database is merged (source, destination)
        self.codebook_marks: list[tuple[str, str]] = []  # sync-clash copies of codebooks made here (name, of)
        self.r = {"from": self.sender, "project": info.get("name"), "version": info.get("version"), "at": self.at,
                  "documents": {"new": [], "clash": [], "removed_here": [], "removed_there": []},
                  "checks": {"new": 0, "updated": 0, "same": 0, "yours_newer": 0, "clash": [], "running": [],
                             "removed_here": [], "removed_there": []},
                  "themes": {"new": 0, "updated": 0, "clash": [], "removed_here": 0},
                  "codebooks": {"new": [], "updated": [], "clash": []},
                  "judgements": 0, "reviews": 0, "labels": 0, "labels_kept_yours": 0, "links": 0, "other_rows": 0,
                  "bibliography": None, "ai_access": []}

    # ---- ids --------------------------------------------------------------------------------
    def _id(self, col: str, value: Any) -> Any:
        if not isinstance(value, str) or not value:
            return value
        if col == "framework":
            return self.fw.get(value, value)
        if col in ("task_id", "item_id") and value.startswith("label:") and self.fw:
            kind, fw, rest = (value.split(":", 2) + ["", ""])[:3]
            value = f"{kind}:{self.fw.get(fw, fw)}:{rest}"
        if col in ID_COLS:
            return _tokens(value, self.ids)
        return value

    def _row(self, r: dict, cols: list[str]) -> tuple:
        if not self.ids and not self.fw:
            return tuple(r.get(c) for c in cols)
        return tuple(r.get(c) if c in _TEXT_COLS else self._id(c, r.get(c)) for c in cols)

    def _insert(self, cx: sqlite3.Connection, table: str, rows: list[dict], verb: str = "OR IGNORE",
                fix=None) -> int:
        if not rows:
            return 0
        here = _cols(cx, table)
        cols = [c for c in here if c in rows[0]]
        vals = []
        for r in rows:
            t = self._row(r, cols)
            if fix:
                t = fix(dict(zip(cols, t)))
                if t is None:
                    continue
                t = tuple(t[c] for c in cols)
            vals.append(t)
        sql = f"INSERT {verb} INTO {table}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        before = cx.total_changes
        cx.executemany(sql, vals)
        return cx.total_changes - before

    def _doc_ok(self, r: dict) -> bool:
        """A row of the incoming copy about a document that is not brought in (removed here) stays out."""
        d = r.get("doc_id")
        if d and d in self.skip_docs:
            return False
        p = r.get("passage_id")
        return not (isinstance(p, str) and p.split(":", 1)[0] in self.skip_docs)

    @staticmethod
    def _seen(cx: sqlite3.Connection, kind: str) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for k, fp in cx.execute("SELECT key, fp FROM sync_seen WHERE kind=?", (kind,)).fetchall():
            out.setdefault(k, set()).add(fp)
        return out

    @staticmethod
    def _copies(cx: sqlite3.Connection, kind: str) -> dict[str, dict]:
        return {r[0]: {"of": r[1], "person_id": r[2], "at": r[3]} for r in
                cx.execute("SELECT key, of_key, person_id, at FROM sync_copies WHERE kind=?", (kind,)).fetchall()}

    def _mark(self, cx: sqlite3.Connection, kind: str, key: str, of: str, person_id: str | None = None,
              at: str | None = None) -> None:
        cx.execute("INSERT OR REPLACE INTO sync_copies(kind, key, of_key, person_id, at) VALUES (?,?,?,?,?)",
                   (kind, key, of, person_id or self.sender["id"], at or self.at))

    # ---- the steps --------------------------------------------------------------------------
    def run(self) -> dict:
        with self.inc.connect() as icx:
            people.adopt(icx, self.sender["id"])  # what the sender decided before 0.14 is theirs
            text_fps(icx, again=True)             # worked out here: what the file says about itself is not trusted
        with self.ws.connect() as cx:
            people.adopt(cx, self.me)            # and what you decided before 0.14 is yours
            self._codebooks(cx)
            self._documents(cx)
            self._document_files(cx)
            self._ai_work(cx)
            self._checks(cx)
            self._judgements(cx)
            self._themes(cx)
            self._reviews(cx)
            links = self._links(cx)
            self._bibliography(cx)
            self._other_tables(cx)
            self._removed(cx)
            self._people(cx)
            # the states the colleague's copy had of what this copy now holds as they do (not of a clash)
            cx.executemany("INSERT OR IGNORE INTO sync_seen(kind, key, fp) VALUES (?,?,?)",
                           [(r["kind"], r["key"], r["fp"]) for r in _rows(self.icx, "SELECT * FROM sync_seen")
                            if (r["kind"], r["key"]) in self.history])
            if self.new_docs:
                self.ws.bump_corpus(cx)
            from .access import relabel

            relabel(cx)
            record_seen(self.ws, cx)
            # last, so a failure undoes the merge: the files of new documents and codebooks
            for src, dest in self.files:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            for name, of in self.codebook_marks:
                self._mark_codebook_title(name, of)
        if links:
            from . import terms

            if terms.status(self.ws)["built"]:
                terms.rebuild_concepts(self.ws)
        self.r["lines"] = summary(self.r)
        return self.r

    # documents ---------------------------------------------------------------------------------
    def _documents(self, cx: sqlite3.Connection) -> None:
        from . import access

        here = text_fps(cx)
        by_content = {(base_id(d), fp): d for d, fp in here.items()}
        removed = {r[0] for r in cx.execute("SELECT key FROM sync_removed WHERE kind='document'")}
        sha_here = {r[0] for r in cx.execute("SELECT sha1 FROM documents")}
        inc_docs = _rows(self.icx, "SELECT * FROM documents ORDER BY doc_id")
        inc_levels = access.levels(self.icx, budget=False)
        levels_here = access.levels(cx, budget=False)
        default_here = access._default_from_cx(cx)
        for d in inc_docs:
            iid, fp, title = d["doc_id"], d["text_fp"], d["title"] or "untitled"
            if not isinstance(iid, str) or not DOC_ID.fullmatch(iid):  # never a path, whatever the file says
                self.skip_docs.add(str(iid))
                continue
            key = (base_id(iid), fp)
            if key in by_content:
                local = by_content[key]
            elif iid in removed or base_id(iid) in removed:
                self.skip_docs.add(iid)
                self.r["documents"]["removed_here"].append(title)
                continue
            elif iid not in here:
                local = iid
            else:  # the same file, read into other text: the colleague's reading is a document of its own
                local = f"{base_id(iid)}-{fp[:6]}"
            if not DOC_ID.fullmatch(local):
                self.skip_docs.add(iid)
                continue
            self.docs[iid] = local
            if local != iid:
                self.ids[iid] = local
            if local in here:
                self._stricter(cx, local, inc_levels.get(iid), d, title)
                continue
            # a document new to this copy: no less strict than the setting for new documents here, nor than your
            # setting of the same file (when this is another reading of it)
            self.new_docs.append(iid)
            original = base_id(iid) if base_id(iid) in here else None
            theirs = inc_levels.get(iid) or "cloud"
            level = access.most([theirs, default_here] + ([levels_here.get(original)] if original else []))
            row = dict(d, doc_id=local, ai_access=level, ai_budget=d.get("ai_budget"), path=None)
            if row["sha1"] in sha_here:  # the file is here already (another reading of it): sha1 is unique
                row["sha1"] = f"{(row['sha1'] or '').split('~')[0]}~{fp[:6]}"
            sha_here.add(row["sha1"])
            self._insert(cx, "documents", [row], verb="OR REPLACE")
            if level != theirs:
                self.r["ai_access"].append({"title": title, "doc_id": local, "theirs": theirs, "now": level,
                                            "why": "yours" if original and level == levels_here.get(original)
                                            else "default", "claude_read_there": self._read_there(iid)})
            if original:
                self._mark(cx, "document", local, original)
                self.r["documents"]["clash"].append({"title": title, "doc_id": local})
            else:
                self.r["documents"]["new"].append(title)
            for table in ("pages", "paragraphs", "headings", "passages"):
                self._insert(cx, table, _rows(self.icx, f"SELECT * FROM {table} WHERE doc_id=?", (iid,)))

    def _read_there(self, iid: str) -> int:
        return self.icx.execute("SELECT COUNT(DISTINCT passage_id) FROM ai_sent WHERE doc_id=?", (iid,)).fetchone()[0]

    def _stricter(self, cx: sqlite3.Connection, local: str, theirs: str | None, d: dict, title: str) -> None:
        """A document both copies have: the stricter AI setting of the two, and the smaller share Claude may read."""
        from . import access

        yours = access.levels(cx, [local], budget=False).get(local) or "cloud"
        theirs = theirs or "cloud"
        if access.RANK[theirs] > access.RANK[yours]:
            cx.execute("UPDATE documents SET ai_access=? WHERE doc_id=?", (theirs, local))
            read = cx.execute("SELECT COUNT(DISTINCT passage_id) FROM ai_sent WHERE doc_id=?", (local,)).fetchone()[0]
            self.r["ai_access"].append({"title": title, "doc_id": local, "yours": yours, "theirs": theirs,
                                        "now": theirs, "why": "theirs", "claude_read_here": read})
        elif access.RANK[yours] > access.RANK[theirs]:
            read = self._read_there(d["doc_id"])
            if read:
                self.r["ai_access"].append({"title": title, "doc_id": local, "yours": yours, "theirs": theirs,
                                            "now": yours, "why": "yours", "claude_read_there": read})
        if d.get("ai_budget") is not None:
            cx.execute("UPDATE documents SET ai_budget=MIN(COALESCE(ai_budget, ?), ?) WHERE doc_id=?",
                       (d["ai_budget"], d["ai_budget"], local))

    def _document_files(self, cx: sqlite3.Connection) -> None:
        """The original file of each new document, copied into this project (originals/<doc_id>/) when it is in the
        colleague's file and is the file the document was read from; another reading of a file that is here already
        points at that file."""
        from .ingest import _sha1

        root, src_root = Path(self.ws.root).resolve(), Path(self.inc.root).resolve()
        for iid in self.new_docs:
            local = self.docs[iid]
            (sha,) = cx.execute("SELECT sha1 FROM documents WHERE doc_id=?", (local,)).fetchone()
            plain = (sha or "").split("~")[0]
            other = cx.execute("SELECT path FROM documents WHERE sha1=? AND doc_id != ?", (plain, local)).fetchone()
            if other and other[0] and Path(other[0]).is_file():
                cx.execute("UPDATE documents SET path=? WHERE doc_id=?", (other[0], local))
                continue
            (src,) = self.icx.execute("SELECT path FROM documents WHERE doc_id=?", (iid,)).fetchone()
            f = Path(src).resolve() if src else None
            # only a file that came in the colleague's zip, and only the file the document was read from
            if not f or not f.is_file() or not f.is_relative_to(src_root) or _sha1(f) != plain:
                continue  # the text is here; the original file is not
            dest = (root / "originals" / local / f.name).resolve()
            if not dest.is_relative_to(root / "originals"):
                continue  # never outside the project's originals
            self.files.append((f, dest))
            cx.execute("UPDATE documents SET path=? WHERE doc_id=?", (str(dest), local))

    # codebooks ---------------------------------------------------------------------------------
    def _codebooks(self, cx: sqlite3.Connection) -> None:
        """The colleague's codebooks: a new one comes in; one of yours they changed (and you did not) is brought up to
        date; one you both changed comes in beside yours as `<name>-<mark>`, and their labels with it. Only decided
        here: the files are written once the database is merged."""
        from .frameworks import BUNDLED, NAME_RE, available

        src, dest = Path(self.inc.root) / "frameworks", Path(self.ws.root) / "frameworks"
        if not src.is_dir():
            return
        here = available(self.ws)
        seen_here, seen_there = self._seen(cx, "codebook"), self._seen(self.icx, "codebook")
        copies_here, copies_there = self._copies(cx, "codebook"), self._copies(self.icx, "codebook")

        def fp_here(name: str) -> str | None:
            return _codebook_fp(dest, name) or _codebook_fp(_home_codebooks(), name)

        for csv in sorted(src.glob("*.csv")):
            name = csv.stem
            if name in BUNDLED or not NAME_RE.match(name):
                continue
            fp_in = _codebook_fp(src, name)
            if name in copies_there and name not in here:  # their copy of a codebook: perhaps your own version
                of = copies_there[name]["of"]
                if of in here and (fp_in == fp_here(of) or fp_in in seen_here.get(of, set())):
                    self.fw[name] = of
                    continue
                self._take_codebook(src, dest, name, name)
                self._mark(cx, "codebook", name, of, copies_there[name]["person_id"], copies_there[name]["at"])
                self.r["codebooks"]["clash"].append({"name": name, "of": of})
                continue
            if name not in here:
                self._take_codebook(src, dest, name, name)
                self.history.add(("codebook", name))
                self.r["codebooks"]["new"].append(name)
                continue
            mine = fp_here(name)
            held = [k for k, v in copies_here.items() if v["of"] == name and _codebook_fp(dest, k) == fp_in]
            if fp_in == mine or fp_in in seen_here.get(name, set()):
                self.history.add(("codebook", name))
                continue  # the same, or an older version of yours
            if held:  # their version is kept here already, beside yours: their labels go with it
                self.fw[name] = held[0]
                continue
            if mine in seen_there.get(name, set()):  # yours is an older version of theirs
                self._take_codebook(src, dest, name, name)
                self.history.add(("codebook", name))
                self.r["codebooks"]["updated"].append(name)
                continue
            new = f"{name}-{fp_in[:6]}"
            self.fw[name] = new
            self._take_codebook(src, dest, name, new)
            self.codebook_marks.append((new, name))
            self._mark(cx, "codebook", new, name)
            self.r["codebooks"]["clash"].append({"name": new, "of": name})

    def _take_codebook(self, src: Path, dest: Path, name: str, new: str) -> None:
        for ext in ("csv", "json"):
            if (src / f"{name}.{ext}").is_file():
                self.files.append((src / f"{name}.{ext}", dest / f"{new}.{ext}"))

    def _mark_codebook_title(self, name: str, of: str) -> None:
        """A sync-clash copy of a codebook says whose version it is in its title."""
        side = Path(self.ws.root) / "frameworks" / f"{name}.json"
        try:
            meta = json.loads(side.read_text(encoding="utf-8")) if side.is_file() else {}
        except ValueError:
            meta = {}
        meta["title"] = f"{meta.get('title') or of} ({self.sender['name'] or 'a colleague'}'s version)"
        side.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # AI work per document ---------------------------------------------------------------------
    def _ai_work(self, cx: sqlite3.Connection) -> None:
        """Labels, reference chains and the tasks that made them, for documents this copy has: a person's own labels
        always; AI work on a document (per codebook) only where this copy has none."""
        from .profile import label_id

        have_model = {(r[0], r[1]) for r in cx.execute("SELECT DISTINCT doc_id, framework FROM labels WHERE "
                                                       "source='model'")}
        have_mentions = {r[0] for r in cx.execute("SELECT DISTINCT doc_id FROM mentions")}
        kept: set[tuple[str, str]] = set()
        rows = []
        for r in _rows(self.icx, "SELECT * FROM labels WHERE source IN ('model', 'person')"):
            if not self._doc_ok(r) or r["doc_id"] not in self.docs:
                continue
            local = (self.docs[r["doc_id"]], self.fw.get(r["framework"], r["framework"]))
            if r["source"] == "model" and local in have_model:
                kept.add(local)
                continue
            rows.append(r)

        def fix(t: dict) -> dict:
            # a label's id is made of its passage and codebook: worked out again where their names here differ
            new = label_id(t["framework"], t["passage_id"], t["code"], t["source"])
            if new != t["label_id"]:
                self.ids[t["label_id"]] = new
                t["label_id"] = new
            return t

        self.r["labels"] = self._insert(cx, "labels", rows, fix=fix)
        self.r["labels_kept_yours"] = len(kept)
        mentions = [r for r in _rows(self.icx, "SELECT * FROM mentions")
                    if self._doc_ok(r) and r["doc_id"] in self.docs and self.docs[r["doc_id"]] not in have_mentions]
        self._insert(cx, "mentions", mentions)
        # the tasks behind them (and every other finished task outside checks and theme runs): how each answer was made
        tasks = [t for t in _rows(self.icx, f"SELECT * FROM tasks WHERE status NOT IN ({','.join('?' * len(UNFINISHED))}) "
                                            "AND kind NOT IN ('check', 'expand', 'decompose', 'reread', 'second', "
                                            "'theme')", UNFINISHED)
                 if not any(x in self.skip_docs for x in _TOKEN.findall(t["task_id"]))]
        added = {self._id("task_id", t["task_id"]) for t in tasks}
        self._insert(cx, "tasks", [dict(t, queued=0, claimed_by=None) for t in tasks])
        if added:
            self._insert(cx, "results", [r for r in _rows(self.icx, "SELECT * FROM results")
                                         if self._id("task_id", r["task_id"]) in added])
        sent = [r for r in _rows(self.icx, "SELECT * FROM ai_sent") if self._doc_ok(r) and r["doc_id"] in self.docs]
        have = {tuple(r) for r in cx.execute("SELECT passage_id, task_id, route, sent_at FROM ai_sent")}
        self._insert(cx, "ai_sent", sent, verb="",
                     fix=lambda t: None if (t["passage_id"], t["task_id"], t["route"], t["sent_at"]) in have else t)

    # checks and theme runs --------------------------------------------------------------------
    def _units(self, cx: sqlite3.Connection, kind: str) -> None:
        """Checks (kind "check") or theme runs ("themes"), one by one:
        - new here: it comes in;
        - the same, or an older version of yours: yours stays (a newer one of theirs replaces yours);
        - both changed: theirs is kept beside yours as a sync-clash copy `<id>-<mark>`, made once; when they change
          it again, that copy is brought up to date;
        - their own sync-clash copy of something: it comes in, marked, unless it is your version of it;
        - removed here, or a check still running there: not brought in."""
        unit_of = _check_unit if kind == "check" else _themes_unit
        canon_in, canon_here = _canon(self.icx), _canon(cx)
        seen_here, seen_there = self._seen(cx, kind), self._seen(self.icx, kind)
        copies_here, copies_there = self._copies(cx, kind), self._copies(self.icx, kind)
        removed = {r[0] for r in cx.execute("SELECT key FROM sync_removed WHERE kind=?", (kind,))}
        if kind == "check":
            keys = self.icx.execute("SELECT hyp_id, text, queue FROM hypotheses ORDER BY created_at").fetchall()
            here = {r[0] for r in cx.execute("SELECT hyp_id FROM hypotheses")}
        else:
            keys = [(r[0], None, None) for r in self.icx.execute("SELECT run_id FROM theme_runs ORDER BY created_at")]
            here = {r[0] for r in cx.execute("SELECT run_id FROM theme_runs")}
        rep = self.r["checks" if kind == "check" else "themes"]

        def own_ids(unit: dict, key: str) -> list[str]:
            return [key] + [c["claim_id"] for c in unit.get("user_claims", [])]

        def fp_as(unit: dict, key: str, of: str, canon: dict) -> str:
            return _fp(unit, {**canon, **_plain(own_ids(unit, key), key, of)})

        def held_copies(key: str) -> list[str]:
            return [ck for ck, c in copies_here.items() if c["of"] == key and ck in here]

        for key, text, queue in keys:
            unit = unit_of(self.icx, key)
            if kind == "themes":
                unit["theme_members"] = [m for m in unit["theme_members"] if self._doc_ok(m)]
            if queue == "waiting" or any(t["status"] in UNFINISHED for t in unit["tasks"]):
                if kind == "check":
                    rep["running"].append(text)
                continue  # still running (a run still being named) in the sender's copy: it comes with a later file
            if key in removed:
                # removed here. When you kept their version of it instead (a sync-clash copy), that copy follows theirs
                if held_copies(key):
                    self._follow(cx, kind, unit, key, held_copies(key), canon_in, canon_here,
                                 seen_there.get(key, set()), rep, removed)
                elif kind == "check":
                    rep["removed_here"].append(text)
                else:
                    rep["removed_here"] += 1
                continue
            if key in copies_there and key not in here:  # their sync-clash copy of something
                of = copies_there[key]["of"]
                fp_plain = fp_as(unit, key, of, canon_in)
                mine = unit_of(cx, of) if of in here else None
                if mine is not None and (fp_plain == _fp(mine, canon_here) or fp_plain in seen_here.get(of, set())):
                    self._route(unit, key, of)  # your own version of it: what they decided on it goes to yours
                    continue
                if of in removed or fp_plain in seen_here.get(of, set()):
                    continue  # a version you had and removed: it does not come back
                self._put(cx, kind, unit)
                self._mark(cx, kind, key, of, copies_there[key]["person_id"], copies_there[key]["at"])
                rep["clash"].append({"hyp_id" if kind == "check" else "run_id": key, "of": of, "text": text})
                continue
            fp_in = _fp(unit, canon_in)
            if key not in here:
                self._put(cx, kind, unit)
                self.history.add((kind, key))
                rep["new"] += 1
                continue
            mine = unit_of(cx, key)
            fp_here = _fp(mine, canon_here)
            if fp_in == fp_here or fp_in in seen_here.get(key, set()):
                self.history.add((kind, key))
                if kind == "check":
                    rep["same" if fp_in == fp_here else "yours_newer"] += 1
                    self.claims |= {c["claim_id"] for c in mine["user_claims"]}
                continue
            if fp_here in seen_there.get(key, set()):  # yours is an older version of theirs
                self._drop(cx, kind, mine)
                self._put(cx, kind, unit)
                self.history.add((kind, key))
                rep["updated"] += 1
                continue
            # both changed it: their version is kept here as a copy (made once, then brought up to date)
            self._follow(cx, kind, unit, key, held_copies(key), canon_in, canon_here, seen_there.get(key, set()), rep,
                         removed, text=text, new=True)

    def _follow(self, cx: sqlite3.Connection, kind: str, unit: dict, key: str, copies: list[str], canon_in: dict,
                canon_here: dict, history_there: set[str], rep: dict, removed: set[str], text: str | None = None,
                new: bool = False) -> None:
        """Their version of `key` goes to the copy of it kept here: as it is (it is that copy already: only what they
        decided on it goes there), brought up to date (the copy is an older version of theirs), or, with `new`, as a
        new copy `<key>-<mark>` (none of the copies is theirs; one you removed does not come back)."""
        unit_of = _check_unit if kind == "check" else _themes_unit
        fp_in = _fp(unit, canon_in)
        older = history_there | {fp_in}
        follow = None
        for ck in copies:
            c = unit_of(cx, ck)
            fp_c = _fp(c, {**canon_here, **_plain([ck] + [x["claim_id"] for x in c.get("user_claims", [])], ck, key)})
            if fp_c == fp_in:
                self._route(unit, key, ck)
                return
            if fp_c in older:
                follow = ck
        if follow:
            self._drop(cx, kind, unit_of(cx, follow))
            self._route(unit, key, follow)
            self._put(cx, kind, unit)
            rep["updated"] += 1
            return
        if not new:
            return  # you changed your copy of theirs too: yours stays
        copy_id = f"{key}-{fp_in[:6]}"
        if copy_id in removed:
            return  # you removed their version of it: it does not come back (until they change it again)
        self._route(unit, key, copy_id)
        self._put(cx, kind, unit)
        self._mark(cx, kind, copy_id, key)
        rep["clash"].append({"hyp_id" if kind == "check" else "run_id": copy_id, "of": key, "text": text})

    def _route(self, unit: dict, key: str, to: str) -> None:
        """Their unit `key` stands for `to` here: their copy of your version (its mark is taken off), or their version
        of your copy (the copy's mark is added). Its ids are rewritten to `to`'s, so what people decided on it goes
        there."""
        if key == to:
            return
        ids = [key] + [c["claim_id"] for c in unit.get("user_claims", [])]
        if to.startswith(key + "-"):
            tag = to[len(key) + 1:]
            mp = {i: f"{i}-{tag}" for i in ids}
        else:
            mp = _plain(ids, key, to)
        self.ids |= mp
        self.claims |= {mp.get(c["claim_id"], c["claim_id"]) for c in unit.get("user_claims", [])}

    def _put(self, cx: sqlite3.Connection, kind: str, unit: dict[str, list[dict]]) -> None:
        tasks_ = [dict(t, queued=0, claimed_by=None, claimed_at=None) for t in unit["tasks"]]
        if kind == "check":
            from .tasks import _h

            # an excerpt's id is made of the task that read it and its passage (tasks.py): made again from their
            # names here, so a later reading of it (a stronger model) finds the same row
            tids = [t["task_id"] for t in unit["tasks"]]
            for v in unit["verifications"]:
                hit = next((t for t in tids if f"v{_h(t, v['passage_id'])}" == v["ver_id"]), None)
                new = f"v{_h(self._id('task_id', hit), self._id('passage_id', v['passage_id']))}" if hit else \
                    (v["ver_id"] if self._id("subject_id", v["subject_id"]) == v["subject_id"]
                     else f"{v['ver_id']}-{_sha(self._id('subject_id', v['subject_id']))[:6]}")
                if new != v["ver_id"]:
                    self.ids[v["ver_id"]] = new
            for table in ("hypotheses", "user_claims", "verifications", "second_opinions"):
                self._insert(cx, table, unit[table], verb="OR REPLACE")
            self.claims |= {self._id("claim_id", c["claim_id"]) for c in unit["user_claims"]}
        else:
            for table in ("theme_runs", "themes", "theme_members"):
                self._insert(cx, table, unit[table], verb="OR REPLACE")
        self._insert(cx, "tasks", tasks_, verb="OR REPLACE")
        self._insert(cx, "results", unit["results"], verb="OR REPLACE")

    @staticmethod
    def _drop(cx: sqlite3.Connection, kind: str, unit: dict[str, list[dict]]) -> None:
        if kind == "check":
            cids = [c["claim_id"] for c in unit["user_claims"]]
            q = ",".join("?" * len(cids))
            if cids:
                cx.execute(f"DELETE FROM verifications WHERE subject_kind='user_claim' AND subject_id IN ({q})", cids)
                cx.execute(f"DELETE FROM second_opinions WHERE subject_id IN ({q})", cids)
                cx.execute(f"DELETE FROM user_claims WHERE claim_id IN ({q})", cids)
            cx.execute("DELETE FROM hypotheses WHERE hyp_id=?", (unit["hypotheses"][0]["hyp_id"],))
        else:
            rid = unit["theme_runs"][0]["run_id"]
            for t in ("theme_members", "themes", "theme_runs"):
                cx.execute(f"DELETE FROM {t} WHERE run_id=?", (rid,))
        for t in unit["tasks"]:
            cx.execute("DELETE FROM results WHERE task_id=?", (t["task_id"],))
            cx.execute("DELETE FROM tasks WHERE task_id=?", (t["task_id"],))

    def _checks(self, cx: sqlite3.Connection) -> None:
        self._units(cx, "check")
        for r in _rows(self.icx, "SELECT key, title FROM sync_removed WHERE kind='check'"):
            if cx.execute("SELECT 1 FROM hypotheses WHERE hyp_id=?", (r["key"],)).fetchone():
                self.r["checks"]["removed_there"].append(r["title"])

    def _themes(self, cx: sqlite3.Connection) -> None:
        self._units(cx, "themes")  # theme edits (reviews) are kept under the run's settings, not its id

    # judgements -----------------------------------------------------------------------------
    def _judgements(self, cx: sqlite3.Connection) -> None:
        """Each person's judgements of the excerpts of the checks this copy has: a newer one of the same person
        replaces theirs (a judgement taken back is a row without a verdict, so it is not brought back); then the one
        in force is worked out again (yours first)."""
        rows = [r for r in _rows(self.icx, "SELECT * FROM judgements") if self._id("claim_id", r["claim_id"]) in self.claims]
        cols = ["claim_id", "passage_id", "person_id", "verdict", "note", "at", "quote", "start", "end"]
        before = cx.total_changes
        cx.executemany(f"INSERT INTO judgements({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
                       "ON CONFLICT(claim_id, passage_id, person_id) DO UPDATE SET verdict=excluded.verdict, "
                       "note=excluded.note, at=excluded.at, quote=excluded.quote, start=excluded.start, end=excluded.end "
                       "WHERE excluded.at > judgements.at OR (excluded.at = judgements.at AND excluded.verdict IS NULL "
                       "AND excluded.note IS NULL)", [self._row(r, cols) for r in rows])
        self.r["judgements"] = cx.total_changes - before
        people.refresh(cx, self.claims, self.me)

    # reviews, links between terms, the bibliography -------------------------------------------
    def _reviews(self, cx: sqlite3.Connection) -> None:
        """Every person's reviews (of labels, links, themes, the SDG pack's claims): a log, so a review that is not
        here yet is added; which one counts is decided when they are read (yours first, people.review_order). A
        review its author took back (*Clear*, *Undo*) is noted as removed: it is not brought back, and it goes from
        the other copies too."""
        gone_here = {r[0] for r in cx.execute("SELECT key FROM sync_removed WHERE kind='review'")}
        for r in _rows(self.icx, "SELECT * FROM sync_removed WHERE kind='review'"):
            try:  # the review's own fields, named as here (a label's id may differ in this copy)
                f = json.loads(r["title"] or "")
            except ValueError:
                f = None
            if isinstance(f, dict):
                f = {c: self._id(c, f.get(c)) for c in people.REVIEW_KEY}
                key = people.review_key(f)
            else:
                f, key = None, r["key"]
            if key not in gone_here:
                people.forget_reviews(cx, keys=[] if f else [key], reviews=[f] if f else [], at=r["at"],
                                      person_id=r["person_id"])
                gone_here.add(key)
        have = {people.review_key(dict(r)) for r in _rows(cx, "SELECT * FROM reviews")}
        rows = []
        for r in _rows(self.icx, "SELECT * FROM reviews ORDER BY review_id"):
            r.pop("review_id", None)
            r["person_id"] = r.get("person_id") or self.sender["id"]
            k = people.review_key({c: self._id(c, v) for c, v in r.items()})
            if k not in have and k not in gone_here:
                have.add(k)
                rows.append(r)
        self.r["reviews"] = self._insert(cx, "reviews", rows, verb="")

    def _links(self, cx: sqlite3.Connection) -> int:
        n = self._insert(cx, "concept_links", _rows(self.icx, "SELECT * FROM concept_links"))
        self.r["links"] = n
        return n

    def _bibliography(self, cx: sqlite3.Connection) -> None:
        theirs = self.inc.meta("bibliography")
        if not theirs:
            return
        mine = self.ws.meta("bibliography")
        same = mine and all(mine.get(k) == theirs.get(k) for k in ("kind", "library", "collection", "format"))
        if mine and not same:
            self.r["bibliography"] = "kept_yours"
            return
        self._insert(cx, "bib_items", _rows(self.icx, "SELECT * FROM bib_items"))
        decided = ("confirmed", "rejected")
        here = {(r[0], r[1]): r[2] for r in cx.execute("SELECT item_key, doc_id, status FROM bib_links")}
        for r in _rows(self.icx, "SELECT * FROM bib_links"):
            if r["doc_id"] not in self.docs:
                continue
            k = (r["item_key"], self.docs[r["doc_id"]])
            if k not in here or (here[k] not in decided and r["status"] in decided):
                self._insert(cx, "bib_links", [r], verb="OR REPLACE")
        if not mine:
            self.ws.set_meta("bibliography", theirs, cx)
        self.r["bibliography"] = "merged" if mine else "new"

    def _other_tables(self, cx: sqlite3.Connection) -> None:
        """The SDG pack's tables, an add-on's, the record of model runs: rows not here yet come in (yours are kept)."""
        here = {r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        n = 0
        for (table,) in self.icx.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            if table in LOCAL_ONLY or table in OWN_RULES or table not in here or table.startswith("sqlite_"):
                continue
            rows = [r for r in _rows(self.icx, f"SELECT * FROM {table}") if self._doc_ok(r)]
            if _pk(cx, table):
                n += self._insert(cx, table, rows)
            else:
                cols = [c for c in _cols(cx, table) if rows and c in rows[0]]
                have = {tuple(r) for r in cx.execute(f"SELECT {','.join(cols)} FROM {table}")} if cols else set()
                n += self._insert(cx, table, rows, verb="",
                                  fix=lambda t: None if tuple(t[c] for c in cols) in have else t)
        # the SDG pack's verifications (of VCA claims) are rows of a shared table: those not here yet
        n += self._insert(cx, "verifications", [r for r in _rows(self.icx, "SELECT * FROM verifications WHERE "
                                                                           "subject_kind != 'user_claim'")
                                                 if self._doc_ok(r)])
        self.r["other_rows"] = n

    def _removed(self, cx: sqlite3.Connection) -> None:
        """What the colleague removed from their copy stays in yours (it is listed); what you do not have is noted as
        removed, so it does not come back with someone else's work either."""
        have_docs = {r[0] for r in cx.execute("SELECT doc_id FROM documents")}
        have_runs = {r[0] for r in cx.execute("SELECT run_id FROM theme_runs")}
        for r in _rows(self.icx, "SELECT * FROM sync_removed WHERE kind IN ('document', 'check', 'themes')"):
            key = r["key"]
            present = key in have_docs if r["kind"] == "document" else \
                bool(cx.execute("SELECT 1 FROM hypotheses WHERE hyp_id=?", (key,)).fetchone()) if r["kind"] == "check" \
                else key in have_runs
            if present:
                if r["kind"] == "document":
                    self.r["documents"]["removed_there"].append(r["title"] or key)
            else:
                cx.execute("INSERT OR IGNORE INTO sync_removed(kind, key, title, at, person_id, fp) VALUES (?,?,?,?,?,?)",
                           (r["kind"], key, r["title"], r["at"], r["person_id"], r.get("fp")))

    def _people(self, cx: sqlite3.Connection) -> None:
        for r in _rows(self.icx, "SELECT * FROM people"):
            if r["person_id"] != self.me:
                people.remember(cx, r["person_id"], r["name"])
        if self.sender["id"] != self.me:
            people.remember(cx, self.sender["id"], self.sender["name"])


# ---------------------------------------------------------------------------------------------
# what it did, in words
# ---------------------------------------------------------------------------------------------
def _n(k: int, one: str, many: str | None = None) -> str:
    return f"{k} {one if k == 1 else (many or one + 's')}"


def summary(r: dict) -> list[str]:
    """The report as a few plain sentences, most important first."""
    who = r["from"]["name"] or "your colleague"
    d, c, t, cb = r["documents"], r["checks"], r["themes"], r["codebooks"]
    out = []
    came = [x for x in (_n(len(d["new"]), "new document") if d["new"] else "",
                        _n(c["new"], "new result") if c["new"] else "",
                        _n(c["updated"], "result", "results") + " brought up to date" if c["updated"] else "",
                        _n(t["new"], "new theme run") if t["new"] else "",
                        _n(len(cb["new"]), "codebook") if cb["new"] else "") if x]
    if came:
        out.append(f"From {who}: " + ", ".join(came) + ".")
    if r["judgements"]:
        out.append(f"{_n(r['judgements'], 'judgement')} of excerpts came in, each under the name of who made it. "
                   "Yours still count where you judged an excerpt yourself.")
    both = [x for x in (_n(len(c["clash"]), "result") if c["clash"] else "",
                        _n(len(t["clash"]), "set of themes", "sets of themes") if t["clash"] else "",
                        _n(len(cb["clash"]), "codebook") if cb["clash"] else "") if x]
    if both:
        out.append(f"Sync clash: {' and '.join(both)} you both changed. {who}'s version came in beside yours, marked "
                   "“sync clash”: nothing was replaced.")
    for x in d["clash"]:
        out.append(f"“{x['title']}” is a file you both added, but the two computers read it into different text. "
                   f"{who}'s reading came in as a document of its own, marked “sync clash”, with what was made from it.")
    for a in r["ai_access"]:
        if a["why"] == "theirs":
            out.append(f"“{a['title']}” is now kept from Claude ({_label(a['now'])}), as in {who}'s copy."
                       + (f" Claude had read {_n(a['claude_read_here'], 'excerpt')} of it here before." if a.get("claude_read_here") else ""))
        elif a["why"] == "yours" and a.get("claude_read_there"):
            out.append(f"{who}'s copy let Claude read “{a['title']}” ({_n(a['claude_read_there'], 'excerpt')}); in yours it "
                       f"stays {_label(a['now']).lower()}. What Claude made of it there came in with the rest.")
        elif a["why"] == "yours":
            out.append(f"“{a['title']}” came in as {_label(a['now']).lower()}, as you keep that file.")
        else:
            out.append(f"“{a['title']}” came in as {_label(a['now']).lower()}, the setting for new documents here.")
    if c["running"]:
        out.append(f"{_n(len(c['running']), 'check')} still running in {who}'s copy did not come in yet: bring in a later "
                   "file when it is done.")
    if d["removed_here"] or c["removed_here"]:
        out.append(f"{_n(len(d['removed_here']) + len(c['removed_here']), 'thing')} you removed earlier did not come back.")
    if d["removed_there"] or c["removed_there"]:
        names = ", ".join(f"“{x}”" for x in (d["removed_there"] + c["removed_there"])[:3])
        out.append(f"{who} removed {names}{' and more' if len(d['removed_there']) + len(c['removed_there']) > 3 else ''} "
                   "from their copy. It stays in yours: remove it here too if you agree.")
    if r["bibliography"] == "kept_yours":
        out.append(f"{who}'s bibliography comes from another Zotero collection or file: yours was kept.")
    if r["labels_kept_yours"]:
        out.append(f"Where you both had the AI label a document, your labels were kept "
                   f"({_n(r['labels_kept_yours'], 'document and codebook', 'documents and codebooks')}).")
    if not out:
        out.append(f"Nothing new: this copy already has everything in {who}'s file.")
    return out


def _label(level: str) -> str:
    from .access import LABEL

    return LABEL.get(level, level)


def history(ws: Workspace, limit: int = 10) -> list[dict]:
    """The colleagues' work brought in, newest first: [{"at", "from", "lines"}]."""
    out = []
    for r in ws.query("SELECT at, report_json FROM sync_log ORDER BY log_id DESC LIMIT ?", (limit,)):
        rep = json.loads(r["report_json"])
        out.append({"at": r["at"], "from": rep.get("from"), "lines": rep.get("lines") or summary(rep)})
    return out


def overview(ws: Workspace) -> dict:
    """For the Projects page: who works on this project, the latest work brought in, and the open sync clashes."""
    who = people.names(ws)
    copies = [{"kind": kind, "key": k, "of_key": v["of"], "name": v["name"], "at": v["at"]}
              for kind in ("check", "document", "themes", "codebook") for k, v in copies_of(ws, kind).items()]
    copies.sort(key=lambda c: c["at"] or "", reverse=True)
    return {"uid": ws.meta("project_uid"), "people": [{"id": k, "name": v} for k, v in who.items()
                                                     if v != "you" and k != people.UNKNOWN],
            "history": history(ws, 5), "clashes": copies, "agreement": people.agreement(ws)}


_ORIGINALS = {"check": "SELECT hyp_id FROM hypotheses", "themes": "SELECT run_id FROM theme_runs",
              "document": "SELECT doc_id FROM documents"}


def copies_of(ws: Workspace, kind: str, settled: bool = False) -> dict[str, dict]:
    """{key: {"of", "name", "at"}} of the sync-clash copies of one kind (check, themes, document, codebook) whose
    other version is still here. A copy whose other version you removed is settled: it is simply yours now (`settled`
    lists those too)."""
    who = people.names(ws)
    here = {r[0] for r in ws.query(_ORIGINALS[kind])} if kind in _ORIGINALS else None
    return {r["key"]: {"of": r["of_key"], "name": who.get(r["person_id"], "a colleague"), "at": r["at"]}
            for r in ws.query("SELECT key, of_key, person_id, at FROM sync_copies WHERE kind=?", (kind,))
            if settled or here is None or (r["of_key"] in here and r["key"] in here)}
