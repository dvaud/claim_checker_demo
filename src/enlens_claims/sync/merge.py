"""The merge of a colleague's copy of a project into this one (0.18: split out of sync.py; the rules are in the
package's notes, `enlens_claims.sync`). `_Merge(ws, inc, info).run()` merges the copy `inc` (a project opened from
the colleague's file) into `ws` in one transaction, and returns the report."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .. import people
from ..store import Workspace, now
from .codebook_merge import CodebookRules
from .common import (DOC_ID, ID_COLS, LOCAL_ONLY, OWN_RULES, UNFINISHED, _TEXT_COLS, _TOKEN, _cols, _pk, _rows, _sha,
                     _tokens, base_id, text_fps)
from .fingerprints import (_canon, _check_unit, _fingerprints, _known, _plain, _running, _themes_unit,
                           record_seen)
from .owner_merge import OwnerRules
from .readings import ReadingRules
from .share_merge import ShareRules
from .report import summary


class _Merge(CodebookRules, ReadingRules, ShareRules, OwnerRules):
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
        self.codebook_versions: list[tuple[Path, str]] = []  # 0.18: codebooks merged code by code (folder, name)
        self.new_labels: dict[str, set[str]] = {}  # 0.16: the labels that came in, per codebook here (their ids here)
        self.hyps_before: set[str] = set()          # 0.16: the checks this copy had before the merge
        self.before_move: dict[tuple[str, str], tuple[str, str]] = {}  # 0.18: their units' states before readings.py
        self.format_in = int(info.get("sync_format") or 1)  # 0.18: the sync format of their file (formats.py)
        self.items_before: set[tuple[str, str]] = set()     # 0.18: the items this copy held before (share_merge.py)
        self.placed_there: dict[tuple[str, str], dict[str, str]] = {}  # 0.18: their `placed:` states (readings.py)
        self.lossy_move = False  # 0.18: a result of theirs found no place on your reading (readings.py)
        self.payloads_here: dict[str, str] = {}  # 0.18: this copy's task payloads of units replaced (sync/folder.py)
        # 0.18 (the shared folder, sync/folder.py): their documents known only by a stub, {doc_id: stub}: no reading of
        # them came (this copy has the same reading, they keep the file out of the folder, or they removed it), only
        # what names them, so checks that read them are compared by content
        self.stubs: dict[str, dict] = {k: v for k, v in (info.get("stubs") or {}).items() if isinstance(v, dict)}
        self.stubs_new: set[str] = set()  # those this copy had not heard of before
        # 0.18 L2 (owner_merge.py): how far the sender followed the owner on each document's AI setting, and the
        # documents this merge must not bring back (the owner removed or declined them)
        self.canon_ai: dict = {k: v for k, v in (info.get("canon_ai") or {}).items()}
        self.not_wanted: set[str] = set()
        self.r = {"from": self.sender, "project": info.get("name"), "version": info.get("version"), "at": self.at,
                  "documents": {"new": [], "clash": [], "removed_here": [], "removed_there": [],
                                "not_wanted": [],  # 0.18 L2: the owner removed it from the project, or declined it
                                "other_reading": [],  # 0.18: their reading placed on yours (readings.py)
                                "not_here": []},  # 0.18: theirs, kept out of the shared folder, not here yet
                  "checks": {"new": 0, "updated": 0, "same": 0, "yours_newer": 0, "clash": [], "running": [],
                             "running_here": [], "removed_here": [], "removed_there": []},
                  "themes": {"new": 0, "updated": 0, "clash": [], "removed_here": 0, "running_here": []},
                  "codebooks": {"new": [], "updated": [], "clash": [], "merged": []},  # 0.18: merged code by code
                  "judgements": 0, "reviews": 0, "labels": 0, "labels_kept_yours": 0, "links": 0, "other_rows": 0,
                  "log": 0, "notes": 0,
                  "shares": {"shared": [], "withdrawn": [], "withheld": []},  # 0.18 (share_merge.py)
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
            for d, stub in self.stubs.items():    # 0.18: no text of these came: what the folder says is all there is
                icx.execute("UPDATE documents SET text_fp=? WHERE doc_id=?", (stub.get("text_fp"), d))
        with self.ws.connect() as cx:
            people.adopt(cx, self.me)            # and what you decided before 0.14 is yours
            if self.stubs:
                self._remember_stubs(cx)         # 0.18: before anything is compared (fingerprints._canon reads them)
            self.hyps_before = {r[0] for r in cx.execute("SELECT hyp_id FROM hypotheses")}
            self._withhold(cx)                    # 0.18: what its owner took back and you do not have stays out
            self._ownership(cx)                   # 0.18 L2: the owner, proposals, decisions (before the documents)
            self._other_readings(cx)              # 0.18: first, so the rest finds one reading of each document
            self._codebooks(cx)
            self._documents(cx)
            if self.new_docs:  # 0.18: one a colleague keeps out of the shared folder is as strict here (folder.py)
                from .folder import hold_settings

                hold_settings(self.ws, cx, [self.docs[i] for i in self.new_docs])
                self._came_from(cx)               # 0.18 L2: they are the sender's additions, not this person's
            self._document_files(cx)
            self._ai_work(cx)
            self._checks(cx)
            self._judgements(cx)
            self._themes(cx)
            self._reviews(cx)
            links = self._links(cx)
            self._bibliography(cx)
            self._log_and_notes(cx)
            self._follow_codebooks(cx)
            self._other_tables(cx)
            self._removed(cx)
            self._share_marks(cx)                 # 0.18: who shared what, by the owner's word
            self._people(cx)
            # the states the colleague's copy had of what this copy now holds as they do (not of a clash)
            cx.executemany("INSERT OR IGNORE INTO sync_seen(kind, key, fp) VALUES (?,?,?)",
                           [(r["kind"], r["key"], r["fp"]) for r in _rows(self.icx, "SELECT * FROM sync_seen")
                            if (r["kind"], r["key"]) in self.history])
            if self.new_docs:
                self.ws.bump_corpus(cx)
            from ..access import relabel

            relabel(cx)
            record_seen(self.ws, cx)
            # last, so a failure undoes the merge: the files of new documents and codebooks
            self._keep_codebook_versions()
            for src, dest in self.files:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            for name, of in self.codebook_marks:
                self._mark_codebook_title(name, of)
        if links:
            from .. import terms

            if terms.status(self.ws)["built"]:
                terms.rebuild_concepts(self.ws)
        self.r["lines"] = summary(self.r)
        return self.r

    # documents ---------------------------------------------------------------------------------
    def _remember_stubs(self, cx: sqlite3.Connection) -> None:
        """0.18: what the shared folder says of each of their documents, kept here (`sync_folder_docs`): a document this
        copy does not hold is then still named by its content (fingerprints._canon), and its file can be fetched once it
        arrives. A document they removed is named by the note of its removal there: nothing to keep."""
        from ..access import RANK

        known = {r[0]: (r[1], r[2]) for r in cx.execute("SELECT doc_id, ai_access, ai_by FROM sync_folder_docs")}
        sender = self.sender["id"]

        def level(d: str, s: dict) -> tuple[str, str | None]:
            """(who may read it with AI, who said so): the strictest word heard stands until whoever said it says
            otherwise (their own later stub). A copy that passes on what it heard (`heard`) says nothing of the
            setting: a document kept out of the folder is then at least for a local AI only."""
            have, by = known.get(d, (None, None))
            first_hand = not s.get("heard")
            said = (s.get("ai_access") if first_hand else "local" if s.get("kept_out") else None) or "cloud"
            if have not in RANK or RANK.get(said, 2) >= RANK[have] or (first_hand and by == sender):
                return (said if said in RANK else "none"), (sender if first_hand else by)
            return have, by

        rows = [(d, s.get("text_fp"), s.get("sha1"), s.get("title"), s.get("reading"), s.get("file"), s.get("name"),
                 int(bool(s.get("kept_out"))), sender, self.at, *level(d, s))
                for d, s in self.stubs.items() if not s.get("removed") and DOC_ID.fullmatch(str(d))]
        cx.executemany("INSERT OR REPLACE INTO sync_folder_docs(doc_id, text_fp, sha1, title, reading, file, name, "
                       "kept_out, person_id, at, ai_access, ai_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.stubs_new = {r[0] for r in rows} - set(known)

    def _documents(self, cx: sqlite3.Connection) -> None:
        from .. import access

        here = text_fps(cx)
        by_content = {(base_id(d), fp): d for d, fp in here.items()}
        removed = {r[0] for r in cx.execute("SELECT key FROM sync_removed WHERE kind='document'")}
        removed_here_by_me = {r[0] for r in cx.execute("SELECT key FROM sync_removed WHERE kind='document' AND "
                                                       "person_id=?", (self.me,))}
        removed |= self.not_wanted  # 0.18 L2: what the owner removed or declined does not come back either
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
            stub = self.stubs.get(iid)
            if stub is not None and stub.get("removed"):  # 0.18: one they removed, named by a check of theirs
                self.skip_docs.add(iid)
                continue
            key = (base_id(iid), fp)
            if key in by_content:
                local = by_content[key]
            elif iid in removed or base_id(iid) in removed:
                self.skip_docs.add(iid)
                if stub is None:  # a stub only names it: you heard of its removal when it was removed
                    # 0.18 L2: not one this person removed, but one the owner removed or did not accept
                    owners = iid in self.not_wanted and iid not in removed_here_by_me
                    self.r["documents"]["not_wanted" if owners else "removed_here"].append(title)
                continue
            elif iid not in here:
                local = iid
            else:  # the same file, read into other text: the colleague's reading is a document of its own
                local = f"{base_id(iid)}-{fp[:6]}"
                if local in removed:  # 0.14.3: that reading was here and you removed it: it does not come back
                    self.skip_docs.add(iid)
                    self.ids[iid] = local  # their checks still name it as it was here (a removed document)
                    self.r["documents"]["removed_here"].append(title)
                    continue
            if not DOC_ID.fullmatch(local):
                self.skip_docs.add(iid)
                continue
            if stub is not None and local not in here:
                # 0.18: no reading of it came (they keep the file out of the shared folder): it stays out until you
                # add the file yourself; what of theirs names it keeps its excerpts as records
                self.skip_docs.add(iid)
                if local != iid:
                    self.ids[iid] = local
                if iid in self.stubs_new:
                    self.r["documents"]["not_here"].append({"title": title, "doc_id": iid,
                                                            "kept_out": bool(stub.get("kept_out"))})
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
            for table in ("pages", "paragraphs", "headings", "passages", "blocks", "doc_tables"):
                if table in ("blocks", "doc_tables") and not self.icx.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    continue  # 0.15: a colleague's copy from before 0.15 has no blocks
                self._insert(cx, table, _rows(self.icx, f"SELECT * FROM {table} WHERE doc_id=?", (iid,)))

    def _read_there(self, iid: str) -> int:
        return self.icx.execute("SELECT COUNT(DISTINCT passage_id) FROM ai_sent WHERE doc_id=?", (iid,)).fetchone()[0]

    def _stricter(self, cx: sqlite3.Connection, local: str, theirs: str | None, d: dict, title: str) -> None:
        """A document both copies have: the stricter AI setting of the two, and the smaller share Claude may read."""
        from .. import access

        yours = access.levels(cx, [local], budget=False).get(local) or "cloud"
        theirs = theirs or "cloud"
        if access.RANK[theirs] > access.RANK[yours] and self._stale(cx, local, theirs, d["doc_id"]):
            pass  # 0.18 L2: only the setting the owner has loosened since, in a copy that has not followed it yet
        elif access.RANK[theirs] > access.RANK[yours]:
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

    def _stale(self, cx: sqlite3.Connection, local: str, theirs: str, iid: str) -> bool:
        from ..ownership import stale_strict

        return stale_strict(cx, local, theirs, self._their_ai_n(iid))

    def _document_files(self, cx: sqlite3.Connection) -> None:
        """The original file of each new document, copied into this project (originals/<doc_id>/) when it is in the
        colleague's file and is the file the document was read from; another reading of a file that is here already
        points at that file."""
        from ..ingest import _sha1

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

    # AI work per document ---------------------------------------------------------------------
    def _ai_work(self, cx: sqlite3.Connection) -> None:
        """Labels, reference chains and the tasks that made them, for documents this copy has: a person's own labels
        always; AI work on a document (per codebook) only where this copy has none."""
        from ..profile import label_id

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

        had = {r[0] for r in cx.execute("SELECT label_id FROM labels")}
        came: list[tuple[str, str]] = []

        def fix(t: dict) -> dict:
            # a label's id is made of its passage and codebook: worked out again where their names here differ
            new = label_id(t["framework"], t["passage_id"], t["code"], t["source"])
            if new != t["label_id"]:
                self.ids[t["label_id"]] = new
                t["label_id"] = new
            if t["label_id"] not in had:
                came.append((t["framework"], t["label_id"]))
            return t

        self.r["labels"] = self._insert(cx, "labels", rows, fix=fix)
        for fw_here, lid in came:  # 0.16: they follow the codebook's changes their copy had not followed
            self.new_labels.setdefault(fw_here, set()).add(lid)
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
        - removed here, or a check still running there: not brought in;
        - 0.14.3: yours is older but still running here (work waiting for Claude Code, or being answered): yours stays
          as it is and the report says so (replacing it deleted that work, and the helper's answers then failed)."""
        unit_of = _check_unit if kind == "check" else _themes_unit
        fps = _fingerprints(cx)
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

        def fp_as(unit: dict, key: str, of: str, canon: dict) -> tuple[str, str]:
            return fps(unit, {**canon, **_plain(own_ids(unit, key), key, of)})

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
                                 seen_there.get(key, set()), rep, removed, fps)
                elif kind == "check":
                    rep["removed_here"].append(text)
                else:
                    rep["removed_here"] += 1
                continue
            if key in copies_there and key not in here:  # their sync-clash copy of something
                of = copies_there[key]["of"]
                fp_plain = fp_as(unit, key, of, canon_in)
                mine = unit_of(cx, of) if of in here else None
                if mine is not None and (fp_plain[0] == fps(mine, canon_here)[0] or _known(fp_plain, seen_here.get(of))):
                    self._route(unit, key, of)  # your own version of it: what they decided on it goes to yours
                    continue
                if of in removed or _known(fp_plain, seen_here.get(of)):
                    continue  # a version you had and removed: it does not come back
                self._put(cx, kind, unit)
                self._mark(cx, kind, key, of, copies_there[key]["person_id"], copies_there[key]["at"])
                rep["clash"].append({"hyp_id" if kind == "check" else "run_id": key, "of": of, "text": text})
                continue
            fp_in = fps(unit, canon_in)
            # 0.18 (readings.py): their unit as it was before it was placed on your reading, and what that state was
            # itself a placement of (their copy placed your unit on their reading: `placed:` states)
            pre = self.before_move.get((kind, key))
            placed = pre is not None and pre[0] != fp_in[0]
            alias = self.placed_there.get((kind, key), {}).get(pre[0]) if pre else None
            if key not in here:
                self._put(cx, kind, unit)
                self.history.add((kind, key))
                self._placed(cx, kind, key, fp_in, pre)
                rep["new"] += 1
                continue
            mine = unit_of(cx, key)
            fp_here = fps(mine, canon_here)
            if fp_in[0] == fp_here[0] or _known(fp_in, seen_here.get(key)) or \
                    _known(pre or ("", ""), seen_here.get(key)) or \
                    (alias is not None and (alias == fp_here[0] or alias in seen_here.get(key, set()))):
                self.history.add((kind, key))
                if kind == "check":
                    rep["same" if fp_in[0] == fp_here[0] else "yours_newer"] += 1
                    self.claims |= {c["claim_id"] for c in mine["user_claims"]}
                continue
            # 0.18: a version that lost places when it was placed on your reading never replaces yours (which has
            # them): it comes in beside yours, as when both changed it
            if _known(fp_here, seen_there.get(key)) and not (placed and self.lossy_move):  # yours is older
                if _running(mine):  # 0.14.3: but a round of it runs here: it stays, and the report says so
                    rep["running_here"].append(text if kind == "check" else key)
                    continue
                self._drop(cx, kind, mine)
                self._put(cx, kind, unit)
                self.history.add((kind, key))
                self._placed(cx, kind, key, fp_in, pre)
                rep["updated"] += 1
                continue
            # both changed it: their version is kept here as a copy (made once, then brought up to date)
            self._follow(cx, kind, unit, key, held_copies(key), canon_in, canon_here, seen_there.get(key, set()), rep,
                         removed, fps, text=text, new=True)

    def _follow(self, cx: sqlite3.Connection, kind: str, unit: dict, key: str, copies: list[str], canon_in: dict,
                canon_here: dict, history_there: set[str], rep: dict, removed: set[str], fps,
                text: str | None = None, new: bool = False) -> None:
        """Their version of `key` goes to the copy of it kept here: as it is (it is that copy already: only what they
        decided on it goes there), brought up to date (the copy is an older version of theirs), or, with `new`, as a
        new copy `<key>-<mark>` (none of the copies is theirs; one you removed does not come back)."""
        unit_of = _check_unit if kind == "check" else _themes_unit
        fp_in = fps(unit, canon_in)
        older = set(history_there) | set(fp_in)
        follow = running = None
        for ck in copies:
            c = unit_of(cx, ck)
            fp_c = fps(c, {**canon_here, **_plain([ck] + [x["claim_id"] for x in c.get("user_claims", [])], ck, key)})
            if fp_c[0] == fp_in[0]:
                self._route(unit, key, ck)
                return
            if _known(fp_c, older):
                if _running(c):  # 0.14.3: a copy with work under way here stays as it is (and no second copy)
                    running = ck
                else:
                    follow = ck
        if running and not follow:
            hyp = unit.get("hypotheses") or [{}]
            rep["running_here"].append((text or hyp[0].get("text") or key) if kind == "check" else running)
            return
        if follow:
            self._drop(cx, kind, unit_of(cx, follow))
            self._route(unit, key, follow)
            self._put(cx, kind, unit)
            rep["updated"] += 1
            return
        if not new:
            return  # you changed your copy of theirs too: yours stays
        # the copy's mark is made from the fingerprint 0.14.0 to 0.14.2 made, so every version marks it alike
        copy_id = f"{key}-{fp_in[1][:6]}"
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
            from ..tasks import _h

            # an excerpt's id is made of the task that read it and its passage (tasks.py): made again from their
            # names here, so a later reading of it (a stronger model) finds the same row
            tids = [t["task_id"] for t in unit["tasks"]]
            made: dict[str, str] = {}  # an id made here -> the excerpt of theirs it was made for
            # (those whose passage keeps its name here first: they keep the id it makes)
            for v in sorted(unit["verifications"], key=lambda v: (self._id("passage_id", v["passage_id"]) !=
                                                                  v["passage_id"], v["ver_id"])):
                hit = next((t for t in tids if f"v{_h(t, v['passage_id'])}" == v["ver_id"]), None)
                new = f"v{_h(self._id('task_id', hit), self._id('passage_id', v['passage_id']))}" if hit else \
                    (v["ver_id"] if self._id("subject_id", v["subject_id"]) == v["subject_id"]
                     else f"{v['ver_id']}-{_sha(self._id('subject_id', v['subject_id']))[:6]}")
                if made.get(new, v["ver_id"]) != v["ver_id"]:
                    # 0.18: two excerpts of theirs that only the naming here makes one (a document and its sync-clash
                    # copy that hold the same text, one document here) stay two, as in their copy: one row would make
                    # this copy's version of the check differ from theirs, and it would go back as a newer one
                    new = f"{new}-{_sha(v['passage_id'])[:6]}"
                made[new] = v["ver_id"]
                if new != v["ver_id"]:
                    self.ids[v["ver_id"]] = new
            for table in ("hypotheses", "user_claims", "verifications", "second_opinions"):
                self._insert(cx, table, unit[table], verb="OR REPLACE")
            self.claims |= {self._id("claim_id", c["claim_id"]) for c in unit["user_claims"]}
        else:
            for table in ("theme_runs", "themes", "theme_members"):
                self._insert(cx, table, unit[table], verb="OR REPLACE")
        self._insert(cx, "tasks", tasks_, verb="OR REPLACE", fix=self._payload_here)
        self._insert(cx, "results", unit["results"], verb="OR REPLACE")

    def _payload_here(self, t: dict) -> dict:
        """0.18: a task of theirs whose payload came without the text of a document kept out of the shared folder
        (sync/folder.py) keeps this copy's own payload, with the text, when this copy has the task."""
        if '"kept_out": true' in (t.get("payload_json") or ""):
            here = self.payloads_here.get(t["task_id"])
            if here:
                t = dict(t, payload_json=here)
        return t

    def _drop(self, cx: sqlite3.Connection, kind: str, unit: dict[str, list[dict]]) -> None:
        self.payloads_here.update({t["task_id"]: t["payload_json"] for t in unit["tasks"] if t.get("payload_json")})
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
        in force is worked out again (yours first). 0.14.3: a row under your own name comes in only when it takes a
        judgement back (no verdict, no note): nothing in a colleague's file can decide in your name."""
        rows = [r for r in _rows(self.icx, "SELECT * FROM judgements") if self._id("claim_id", r["claim_id"]) in self.claims
                and (r["person_id"] != self.me or (r["verdict"] is None and r["note"] is None))]
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
            if r["person_id"] == self.me:
                continue  # 0.14.3: yours are here already (or you took them back): a file cannot add one in your name
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

    def _log_and_notes(self, cx: sqlite3.Connection) -> None:
        """0.16: the colleague's research log entries and notes: theirs come in (or are brought up to date), yours stay as
        they are, and what you removed stays removed."""
        from .. import notes, researchlog

        def fix(r: dict) -> dict | None:
            if not self._doc_ok(r):
                return None
            cols = list(r)
            return dict(zip(cols, self._row(r, cols)))

        here = {r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        there = {r[0] for r in self.icx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "research_log" in there and "research_log" in here:
            self.r["log"] = researchlog.merge(cx, _rows(self.icx, "SELECT * FROM research_log ORDER BY at"), fix)
        if "notes" in there and "notes" in here:
            self.r["notes"] = notes.merge(cx, _rows(self.icx, "SELECT * FROM notes"), fix)
        # a note or an entry its own author removed in their copy goes here too (and stays gone)
        for r in _rows(self.icx, "SELECT * FROM sync_removed WHERE kind IN ('note', 'log')"):
            table, col = ("notes", "note_id") if r["kind"] == "note" else ("research_log", "entry_id")
            if table not in here:
                continue
            row = cx.execute(f"SELECT person_id FROM {table} WHERE {col}=?", (r["key"],)).fetchone()
            if row is not None and row[0] != self.me and row[0] == r["person_id"]:
                cx.execute(f"DELETE FROM {table} WHERE {col}=?", (r["key"],))
            if row is None or row[0] == r["person_id"]:
                cx.execute("INSERT OR IGNORE INTO sync_removed(kind, key, title, at, person_id) VALUES (?,?,?,?,?)",
                           (r["kind"], r["key"], r["title"], r["at"], r["person_id"]))

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
                    why = self._removal_kind(cx, key)  # 0.18 L2: what the removal is in a project with an owner
                    if why:
                        self.r["documents"].setdefault("removals", {}).setdefault(why, []).append(r["title"] or key)
            else:
                cx.execute("INSERT OR IGNORE INTO sync_removed(kind, key, title, at, person_id, fp) VALUES (?,?,?,?,?,?)",
                           (r["kind"], key, r["title"], r["at"], r["person_id"], r.get("fp")))

    def _people(self, cx: sqlite3.Connection) -> None:
        for r in _rows(self.icx, "SELECT * FROM people"):
            if r["person_id"] != self.me:
                people.remember(cx, r["person_id"], r["name"])
        if self.sender["id"] != self.me:
            people.remember(cx, self.sender["id"], self.sender["name"])

