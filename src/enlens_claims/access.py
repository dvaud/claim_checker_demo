"""Who may read each document with AI (0.11): per-document AI settings, the guard on every task, and the ledger of
what was sent to Claude.

Every document has one of three settings (`documents.ai_access`; NULL: the project's default, `ai_access_default` in
the project's config):

- ``cloud``  "Claude may read it": the chosen route (Claude Code, the Claude API, or a local model);
- ``local``  "Only a local AI": a model server on this computer, or a person;
- ``none``   "No AI": a person only (search, the keyword profile, concepts and themes without AI still work).

The setting is enforced in code where every AI task passes, never by an instruction in a prompt:

1. `label_payload` (called by `tasks._insert_task`) gives each task the most restricted setting of the documents its
   payload names (any `passage_id` or `doc_id`, at any depth), stored in `tasks.access`;
2. `require` (called by `tasks.run_one` before any backend is asked) refuses a `local` task on a route that leaves
   this computer and a `none` task on any route; the queue for Claude Code only ever hands out `cloud` tasks;
3. the features split their work so that each task is all-cloud or all-local (`Readers` picks the reader of each
   level), and the guard catches a feature that forgets to.

Every passage that leaves for a cloud model is written to `ai_sent` at that moment (`record_sent`), so the Documents
page can show how much of each document Claude has read. An optional cap per document (`documents.ai_budget`, a
percentage) treats a document as `local` for new tasks once Claude has read that share of it.
"""
from __future__ import annotations

import ipaddress
import json
import sqlite3
from typing import Any, Iterable
from urllib.parse import urlparse

from .store import Workspace, now

LEVELS = ("cloud", "local", "none")
RANK = {"cloud": 0, "local": 1, "none": 2}
LABEL = {"cloud": "Claude may read it", "local": "Only a local AI", "none": "No AI"}
WHO = {"cloud": "The chosen route: Claude Code, the Claude API, or a local model",
       "local": "A local model server on this computer, or a person",
       "none": "A person only. Search, keyword Profile, Concepts and Themes without AI still work"}
OFF_COMPUTER = ("claude_code", "anthropic")
ROUTE_NAMES = {"claude_code": "Claude Code", "anthropic": "Claude API", "chat": "Claude app (connector)"}
PROMISE = ("Documents you mark as local stay on this computer. ENLENS never sends their text to Claude, in any "
           "feature, and shows you how much of every other document it has sent.")
_KEEP = object()


class AccessError(RuntimeError):
    """A task was about to be handed to a model its documents' settings do not allow (a bug in a feature: the guard
    stops it before anything is sent)."""


def clean(value: Any, allow_empty: bool = False) -> str | None:
    v = str(value or "").strip().lower()
    if not v and allow_empty:
        return None
    aliases = {"claude": "cloud", "local_only": "local", "local-only": "local", "no_ai": "none", "no-ai": "none",
               "person": "none"}
    v = aliases.get(v, v)
    if v not in LEVELS:
        raise ValueError("The AI setting must be cloud (Claude may read it), local (only a local AI) or none (no AI).")
    return v


def most(levels: Iterable[str | None]) -> str:
    """The most restricted of these settings (cloud when there are none)."""
    out = "cloud"
    for lv in levels:
        if lv and RANK.get(lv, 2) > RANK[out]:
            out = lv if lv in RANK else "none"
    return out


# ---------------------------------------------------------------------------------------------
# the project's default and the settings of documents
# ---------------------------------------------------------------------------------------------
def _local_only() -> bool:
    from .home import local_only

    return local_only()


def default_chosen(ws: Workspace) -> bool:
    """Whether the project's default has been chosen (a new project asks once, with nothing preselected)."""
    return ws.config.get("ai_access_default") in LEVELS


def default(ws: Workspace) -> str:
    """The setting of documents without their own: the project's choice; before it is made, as 0.10 did (Claude
    may read them), or `local` on an installation without cloud models."""
    v = ws.config.get("ai_access_default")
    if v == "cloud" and _local_only():
        return "local"
    if v in LEVELS:
        return v
    return "local" if _local_only() else "cloud"


def _write_config(ws: Workspace, changes: dict) -> None:
    try:
        cfg = json.loads(ws.config_path.read_text(encoding="utf-8")) if ws.config_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        cfg = {}
    cfg.update(changes)
    ws.config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    ws._config_cache = None


def set_default(ws: Workspace, value: str) -> str:
    v = clean(value)
    if v == "cloud" and _local_only():
        raise ValueError("Cloud models are switched off on this computer by whoever installed ENLENS: documents can be "
                         "read by a local AI or by you only.")
    _write_config(ws, {"ai_access_default": v, "ai_access_ask": False})
    with ws.connect() as cx:
        relabel(cx)
    return v


def _share_sql() -> str:
    return ("SELECT COALESCE(SUM(LENGTH(p.text)), 0) FROM passages p WHERE p.doc_id=? AND p.passage_id IN "
            "(SELECT DISTINCT passage_id FROM ai_sent WHERE doc_id=?)")


def shares(cx_or_ws, doc_ids: Iterable[str] | None = None) -> dict[str, dict]:
    """How much of each document Claude has read: {doc_id: {"sent_chars", "chars", "share" (0..1), "passages"}}."""
    q = cx_or_ws.execute if isinstance(cx_or_ws, sqlite3.Connection) else cx_or_ws._conn().execute
    ids = list(doc_ids) if doc_ids is not None else [r[0] for r in q("SELECT doc_id FROM documents")]
    out: dict[str, dict] = {}
    if not ids:
        return out
    marks = ",".join("?" * len(ids))
    total = {r[0]: int(r[1] or 0) for r in q(f"SELECT doc_id, SUM(LENGTH(text)) FROM passages WHERE doc_id IN ({marks}) "
                                              "GROUP BY doc_id", ids)}
    sent = {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in q(
        f"SELECT p.doc_id, SUM(LENGTH(p.text)), COUNT(*) FROM passages p JOIN (SELECT DISTINCT passage_id FROM ai_sent "
        f"WHERE doc_id IN ({marks})) s ON s.passage_id=p.passage_id GROUP BY p.doc_id", ids)}
    for d in ids:
        chars = total.get(d, 0)
        sc, n = sent.get(d, (0, 0))
        out[d] = {"sent_chars": sc, "chars": chars, "passages": n, "share": round(min(1.0, sc / chars), 4) if chars else 0.0}
    return out


def levels(cx_or_ws, doc_ids: Iterable[str] | None = None, budget: bool = True) -> dict[str, str]:
    """The setting that applies to each document now: its own, else the project's default; a `cloud` document whose
    cap is reached counts as `local` (with `budget`)."""
    if isinstance(cx_or_ws, sqlite3.Connection):
        cx = cx_or_ws
        ws = None
        q = cx.execute
    else:
        ws = cx_or_ws
        cx = ws._conn()
        q = cx.execute
    dflt = default(ws) if ws is not None else _default_from_cx(cx)
    ids = list(dict.fromkeys(doc_ids)) if doc_ids is not None else None
    if ids is not None and not ids:
        return {}
    sql = "SELECT doc_id, ai_access, ai_budget FROM documents"
    rows = q(sql + (f" WHERE doc_id IN ({','.join('?' * len(ids))})" if ids is not None else ""), ids or []).fetchall()
    out: dict[str, str] = {}
    capped = []
    for r in rows:
        lv = r[1] if r[1] in LEVELS else dflt
        if lv == "cloud" and _local_only():
            lv = "local"
        out[r[0]] = lv
        if budget and lv == "cloud" and r[2] is not None:
            capped.append((r[0], float(r[2])))
    if capped:
        sh = shares(cx, [d for d, _b in capped])
        for d, b in capped:
            if sh[d]["share"] * 100 >= b:
                out[d] = "local"
    if ids is not None:
        for d in ids:  # a document removed since: what was read from it stays as it was; nothing new is sent
            out.setdefault(d, "none")
    return out


def _default_from_cx(cx: sqlite3.Connection) -> str:
    """The project's default when only a connection is at hand (inside a transaction)."""
    from pathlib import Path

    path = cx.execute("PRAGMA database_list").fetchone()[2]
    return default(Workspace(Path(path).parent)) if path else ("local" if _local_only() else "cloud")


def doc_of_passages(cx, passage_ids: Iterable[str]) -> dict[str, str]:
    ids = list(dict.fromkeys(passage_ids))
    out: dict[str, str] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in cx.execute(f"SELECT passage_id, doc_id FROM passages WHERE passage_id IN ({','.join('?' * len(chunk))})",
                            chunk):
            out[r[0]] = r[1]
    return out


def _walk(obj: Any, pids: set, dids: set) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "passage_id" and isinstance(v, str):
                pids.add(v)
            elif k == "doc_id" and isinstance(v, str):
                dids.add(v)
            else:
                _walk(v, pids, dids)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, pids, dids)


def ids_in(payload: Any) -> tuple[set[str], set[str]]:
    """The passage ids and document ids a payload names, at any depth."""
    pids: set[str] = set()
    dids: set[str] = set()
    _walk(payload, pids, dids)
    return pids, dids


def label_payload(cx, payload: Any) -> str:
    """The most restricted setting of the documents a task's payload names (`cloud` for a task without document
    text, such as the search words of a hypothesis). A passage no longer in the project counts as its document."""
    pids, dids = ids_in(payload)
    if not pids and not dids:
        return "cloud"
    by_p = doc_of_passages(cx, pids)
    docs = set(dids) | set(by_p.values())
    missing = pids - set(by_p)
    lv = levels(cx, docs) if docs else {}
    out = most(lv.values())
    if missing and not docs:
        return "none"  # passages of a removed document, and nothing else to go by: keep them here
    return out


def relabel(cx, task_ids: Iterable[str] | None = None) -> int:
    """Give the tasks not answered yet the setting of their documents now (after a setting changed). A task that is
    no longer `cloud` is taken out of the queue for Claude Code (a batch already handed out has left). Returns the
    number of tasks whose setting changed."""
    sql = ("SELECT task_id, payload_json, access FROM tasks WHERE (status IN ('pending', 'retry') OR "
           "(status='done' AND again=1))")
    args: list = []
    if task_ids is not None:
        ids = list(task_ids)
        if not ids:
            return 0
        sql += f" AND task_id IN ({','.join('?' * len(ids))})"
        args = ids
    n = 0
    for r in cx.execute(sql, args).fetchall():
        try:
            lv = label_payload(cx, json.loads(r["payload_json"] or "{}"))
        except (ValueError, TypeError):
            lv = "none"
        if lv != (r["access"] or "cloud"):
            n += 1
        cx.execute("UPDATE tasks SET access=? WHERE task_id=?", (lv, r["task_id"]))
        if lv != "cloud":
            cx.execute("UPDATE tasks SET queued=0, queued_at=NULL, claimed_by=NULL, claimed_at=NULL WHERE task_id=? "
                       "AND COALESCE(queued, 0)=1", (r["task_id"],))
    return n


def set_documents(ws: Workspace, doc_ids: list[str], setting: Any = _KEEP, note: Any = _KEEP,
                  budget: Any = _KEEP) -> dict:
    """Change the AI setting (and/or the note, the cap) of documents. `setting` None returns them to the project's
    default. Takes effect for every task not answered yet."""
    if not doc_ids:
        raise ValueError("Choose at least one document.")
    lv = None
    if setting is not _KEEP:
        lv = clean(setting, allow_empty=True)
        if lv == "cloud" and _local_only():
            raise ValueError("Cloud models are switched off on this computer by whoever installed ENLENS.")
    if budget is not _KEEP and budget not in (None, ""):
        try:
            budget = float(budget)
        except (TypeError, ValueError):
            raise ValueError("The cap must be a percentage from 1 to 100, or empty for none.") from None
        if not 1 <= budget <= 100:
            raise ValueError("The cap must be a percentage from 1 to 100, or empty for none.")
    elif budget == "":
        budget = None
    with ws.connect() as cx:
        found = {r[0] for r in cx.execute(f"SELECT doc_id FROM documents WHERE doc_id IN ({','.join('?' * len(doc_ids))})",
                                          list(doc_ids))}
        unknown = [d for d in doc_ids if d not in found]
        if unknown:
            raise KeyError(unknown[0])
        for d in doc_ids:
            if setting is not _KEEP:
                cx.execute("UPDATE documents SET ai_access=? WHERE doc_id=?", (lv, d))
            if note is not _KEEP:
                cx.execute("UPDATE documents SET ai_note=? WHERE doc_id=?", ((str(note or "").strip()[:300] or None), d))
            if budget is not _KEEP:
                cx.execute("UPDATE documents SET ai_budget=? WHERE doc_id=?", (budget, d))
        changed = relabel(cx)
    return {"documents": len(doc_ids), "tasks_changed": changed}


def documents_view(ws: Workspace) -> dict[str, dict]:
    """Per document: its setting (`ai_access`: the one that applies; `own`: its own or None), note, cap and the
    share Claude has read."""
    lv = levels(ws)
    raw = {r[0]: r for r in ws.query("SELECT doc_id, ai_access, ai_note, ai_budget FROM documents")}
    sh = shares(ws)
    out = {}
    for d, r in raw.items():
        own = r[1] if r[1] in LEVELS else None
        eff = lv.get(d, default(ws))
        out[d] = {"ai_access": eff, "own": own, "note": r[2] or "", "budget": r[3],
                  "budget_reached": eff == "local" and (own or default(ws)) == "cloud" and r[3] is not None,
                  "sent": sh.get(d, {}).get("share", 0.0), "sent_passages": sh.get(d, {}).get("passages", 0)}
    return out


def restricted_titles(ws: Workspace) -> dict[str, str]:
    """Documents marked "No AI" by their place: {doc_id: "Restricted document 3"} (a title can name a person, so the
    connector shows this instead)."""
    lv = levels(ws, budget=False)
    out = {}
    n = 0
    for (d,) in ws.query("SELECT doc_id FROM documents ORDER BY added_at, rowid"):
        if lv.get(d) == "none":
            n += 1
            out[d] = f"Restricted document {n}"
    return out


# ---------------------------------------------------------------------------------------------
# which model may read what
# ---------------------------------------------------------------------------------------------
def on_this_computer(url: str) -> bool:
    """Whether an address is this computer (localhost, 127.x, ::1)."""
    u = (url or "").strip()
    if not u:
        return False
    if "://" not in u:
        u = "http://" + u
    try:
        host = (urlparse(u).hostname or "").strip("[]").lower()
    except ValueError:
        return False
    if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def backend_levels(backend) -> set[str]:
    """The settings a backend may read: Claude (Claude Code, the Claude API) only `cloud`; a model server on this
    computer (or the offline demo) `cloud` and `local`; a model server on another computer only `cloud`."""
    if backend is None:
        return set()
    name = getattr(backend, "name", "") or ""
    if name in OFF_COMPUTER:
        return {"cloud"}
    if name == "baseline":
        return {"cloud", "local"}
    url = getattr(backend, "base_url", None)
    if url is not None and on_this_computer(url):
        return {"cloud", "local"}
    return {"cloud"}


def is_cloud(backend) -> bool:
    return (getattr(backend, "name", "") or "") in OFF_COMPUTER


def require(backend, task) -> None:
    """Refuse to hand a task to a model its setting does not allow (before anything is sent)."""
    try:
        lv = task["access"] or "cloud"
    except (KeyError, IndexError):
        lv = "cloud"
    if lv == "none":
        raise AccessError(f"Task {task['task_id']} holds text of a document marked No AI: no model may read it.")
    if lv not in backend_levels(backend):
        raise AccessError(f"Task {task['task_id']} holds text of a document marked Only a local AI: "
                          f"{ROUTE_NAMES.get(getattr(backend, 'name', ''), 'this model')} may not read it.")


class Readers:
    """The model that reads each setting: the main one where it may, the local model for restricted documents for
    `local` when the main one is Claude, nobody for `none`."""

    def __init__(self, backend, model: str, settings: dict | None = None):
        self.backend, self.model = backend, model
        self._settings = settings
        self._local: tuple | None = None
        self._local_tried = False
        self.local_problem: str | None = None

    @property
    def main_levels(self) -> set[str]:
        return backend_levels(self.backend)

    def settings(self) -> dict:
        if self._settings is None:
            from .home import load_settings

            self._settings = load_settings()
        return self._settings

    def local(self):
        """(backend, model) of the local model for restricted documents, or None."""
        if "local" in self.main_levels:
            return self.backend, self.model
        if not self._local_tried:
            self._local_tried = True
            from .home import make_restricted_backend
            from .llm import BackendError

            try:
                self._local = make_restricted_backend(self.settings())
            except BackendError as e:
                self._local, self.local_problem = None, str(e)
            if self._local is not None and "local" not in backend_levels(self._local[0]):
                self._local, self.local_problem = None, "The local model for restricted documents is not on this computer."
        return self._local

    def local_configured(self) -> bool:
        """Whether a local model is chosen for restricted documents (without starting it)."""
        if "local" in self.main_levels:
            return True
        from .home import restricted_choice

        return bool(restricted_choice(self.settings()))

    def for_level(self, level: str):
        """(backend, model) that reads tasks of this setting, or None (a person)."""
        if level == "none":
            return None
        if level in self.main_levels:
            return self.backend, self.model
        if level == "local":
            return self.local()
        return None

    def for_task(self, ws: Workspace, task_id: str):
        lv = ws.scalar("SELECT access FROM tasks WHERE task_id=?", (task_id,)) or "cloud"
        return self.for_level(lv)


def split_by_level(ws_or_cx, items: list[dict], key: str = "doc_id") -> dict[str, list[dict]]:
    """Items (passages with a doc_id) grouped by their document's setting, in their order."""
    docs = [it[key] for it in items if it.get(key)]
    lv = levels(ws_or_cx, docs)
    out: dict[str, list[dict]] = {k: [] for k in LEVELS}
    for it in items:
        out[lv.get(it.get(key), "none")].append(it)
    return out


def allowed_docs(ws: Workspace, allowed: set[str]) -> set[str]:
    """The documents whose setting is one of `allowed`."""
    return {d for d, lv in levels(ws).items() if lv in allowed}


# ---------------------------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------------------------
def _with_context(cx, payload: Any, pids: set[str]) -> set[str]:
    """Also the passage shown before an excerpt as its context (the text before it, same document)."""
    extra: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("passage_id"), str) and (o.get("context") or o.get("prev")):
                r = cx.execute("SELECT q.passage_id FROM passages p JOIN passages q ON q.doc_id=p.doc_id AND "
                               "q.seq=p.seq - 1 WHERE p.passage_id=?", (o["passage_id"],)).fetchone()
                if r:
                    extra.add(r[0])
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)

    walk(payload)
    return pids | extra


def record_sent(cx, task_id: str | None, payload: Any, route: str, feature: str | None = None) -> int:
    """Write one ledger row per passage (and context passage) of this payload, as it leaves for a cloud model."""
    pids, _dids = ids_in(payload)
    if not pids:
        return 0
    pids = _with_context(cx, payload, pids)
    docs = doc_of_passages(cx, pids)
    at = now()
    rows = [(p, docs[p], route, task_id, at, feature) for p in sorted(pids) if p in docs]
    cx.executemany("INSERT INTO ai_sent(passage_id, doc_id, route, task_id, sent_at, feature) VALUES (?,?,?,?,?,?)", rows)
    return len(rows)


def record_passages(ws: Workspace, passage_ids: Iterable[str], route: str, feature: str, task_id: str | None = None) -> int:
    with ws.connect() as cx:
        return record_sent(cx, task_id, [{"passage_id": p} for p in passage_ids], route, feature)


FEATURES = {"check": "Check", "reread": "Read again", "second": "Second opinion", "label": "Profile (AI pass)",
            "theme": "Theme names", "link": "Concept links", "resolve": "References", "extract": "SDG pack",
            "split": "SDG pack", "verify": "SDG pack", "verify_set": "SDG pack", "expand": "Search words",
            "decompose": "Parts of a hypothesis"}


def ledger(ws: Workspace, doc_id: str | None = None) -> list[dict]:
    """The rows of the ledger, newest first: passage, document, page, route, feature, task, when."""
    sql = ("SELECT s.passage_id, s.doc_id, d.title, p.page, s.route, COALESCE(s.feature, t.kind) AS feature, s.task_id, "
           "s.sent_at FROM ai_sent s LEFT JOIN documents d ON d.doc_id=s.doc_id LEFT JOIN passages p ON "
           "p.passage_id=s.passage_id LEFT JOIN tasks t ON t.task_id=s.task_id")
    args: list = []
    if doc_id:
        sql += " WHERE s.doc_id=?"
        args.append(doc_id)
    rows = ws.query(sql + " ORDER BY s.sent_at DESC, s.rowid DESC", args)
    return [{"passage_id": r["passage_id"], "doc_id": r["doc_id"], "title": r["title"] or "", "page": r["page"],
             "route": r["route"] or "", "feature": FEATURES.get(r["feature"] or "", r["feature"] or ""),
             "task_id": r["task_id"] or "", "sent_at": r["sent_at"] or ""} for r in rows]


def document_ledger(ws: Workspace, doc_id: str) -> dict:
    """The passages of one document Claude has read: each passage once, with when and for what."""
    seen: dict[str, dict] = {}
    for r in ledger(ws, doc_id):
        x = seen.setdefault(r["passage_id"], {"passage_id": r["passage_id"], "page": r["page"], "times": 0,
                                              "first": r["sent_at"], "last": r["sent_at"], "features": [], "routes": []})
        x["times"] += 1
        x["first"] = min(x["first"], r["sent_at"])
        x["last"] = max(x["last"], r["sent_at"])
        if r["feature"] and r["feature"] not in x["features"]:
            x["features"].append(r["feature"])
        if r["route"] and r["route"] not in x["routes"]:
            x["routes"].append(r["route"])
    items = sorted(seen.values(), key=lambda x: x["last"], reverse=True)
    if items:
        seqs = {r[0]: (r[1], r[2]) for r in ws.query(
            f"SELECT passage_id, seq, substr(text, 1, 160) FROM passages WHERE passage_id IN "
            f"({','.join('?' * len(items))})", [x["passage_id"] for x in items])}
        for x in items:
            s = seqs.get(x["passage_id"])
            x["seq"], x["preview"] = (s[0], s[1]) if s else (None, "")
    sh = shares(ws, [doc_id]).get(doc_id, {})
    return {"doc_id": doc_id, "share": sh.get("share", 0.0), "passages": items,
            "since": ws.meta("ai_sent_since") or None}


# ---------------------------------------------------------------------------------------------
# a project made before 0.11
# ---------------------------------------------------------------------------------------------
def upgrade(ws: Workspace) -> dict:
    """Once, when a project made before 0.11 is opened: its default becomes what it was (Claude may read every
    document; `local` on an installation without cloud models), the tasks not answered yet get their setting (a
    queued one that is no longer `cloud` leaves the queue), and the answers given on a Claude route (from their
    recorded provenance) enter the ledger with the time of the answer."""
    if not default_chosen(ws):
        _write_config(ws, {"ai_access_default": "local" if _local_only() else "cloud", "ai_access_banner": True})
    out = {"relabelled": 0, "backfilled": 0}
    with ws.connect() as cx:
        if cx.execute("SELECT value FROM meta WHERE key='ai_access_upgraded'").fetchone():
            return out
        out["relabelled"] = relabel(cx)
        cx.execute("UPDATE tasks SET access='cloud' WHERE access IS NULL")
        rows = cx.execute("SELECT r.task_id, MIN(r.received_at) AS at, r.route, t.payload_json, t.kind FROM results r "
                          "JOIN tasks t ON t.task_id=r.task_id WHERE r.route IN ('Claude Code', 'Claude API') OR "
                          "r.route IS NULL AND (r.model LIKE 'claude%' OR r.model IN ('opus', 'sonnet', 'haiku', 'fable')) "
                          "GROUP BY r.task_id").fetchall()
        for r in rows:
            try:
                payload = json.loads(r["payload_json"] or "{}")
            except ValueError:
                continue
            pids, _d = ids_in(payload)
            pids = _with_context(cx, payload, pids)
            docs = doc_of_passages(cx, pids)
            route = r["route"] or "Claude"
            cx.executemany("INSERT INTO ai_sent(passage_id, doc_id, route, task_id, sent_at, feature) VALUES "
                           "(?,?,?,?,?,?)", [(p, docs[p], route, r["task_id"], r["at"], r["kind"]) for p in sorted(pids)
                                             if p in docs])
            out["backfilled"] += 1
        cx.execute("INSERT OR REPLACE INTO meta VALUES ('ai_access_upgraded', ?)", (json.dumps(now()),))
        cx.execute("INSERT OR REPLACE INTO meta VALUES ('ai_sent_since', ?)", (json.dumps(now()),))
    return out


def dismiss_banner(ws: Workspace) -> None:
    _write_config(ws, {"ai_access_banner": False})


def project_info(ws: Workspace) -> dict:
    """What the Documents page needs about the project: its default, whether it was chosen, the banner."""
    lv = levels(ws)
    counts = {k: sum(1 for v in lv.values() if v == k) for k in LEVELS}
    return {"default": default(ws), "chosen": default_chosen(ws), "banner": bool(ws.config.get("ai_access_banner")),
            "ask": not default_chosen(ws) and (bool(ws.config.get("ai_access_ask")) or bool(lv)),
            "counts": counts, "labels": LABEL, "who": WHO, "local_only": _local_only(), "promise": PROMISE,
            "ledger_since": ws.meta("ai_sent_since") or None}


def may_read(ws: Workspace, payload: Any, backend) -> bool:
    """Whether this backend may read this payload now (for the tools that send an answered task again: the label
    comparison, the model test)."""
    with ws.connect() as cx:
        return label_payload(cx, payload) in backend_levels(backend)


def sending(ws: Workspace, payload: Any, backend, feature: str, task_id: str | None = None) -> None:
    """Before a tool sends a payload to a backend itself (not through a task): the guard, and the ledger."""
    if not may_read(ws, payload, backend):
        raise AccessError("This text comes from a document this model may not read.")
    if is_cloud(backend):
        with ws.connect() as cx:
            record_sent(cx, task_id, payload, ROUTE_NAMES.get(backend.name, backend.name), feature)
