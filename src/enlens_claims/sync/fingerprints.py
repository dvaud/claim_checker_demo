"""The units the sync compares (0.18: split out of sync.py): a check, a theme run and a codebook, their rows, and the
fingerprints that tell a newer version from one changed on both sides.

How a version is told newer: a unit's fingerprint names documents by their content (file and text), not by their id
in a copy, so both copies compute the same fingerprint. A unit whose fingerprint here is among the states the other
copy has had (its `sync_seen` and its current one) is older here; the other way round, older there; neither: a clash.
0.14.3: a fingerprint leaves out empty values, so copies on versions with other columns agree; the form 0.14.0 to
0.14.2 made is worked out and written down too, so their states are recognised (see `_fingerprints`).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from ..store import Workspace
from .common import UNFINISHED, _rows, _sha, _tokens, base_id, text_fps

_PERSONAL = {"user_verdict", "user_note", "user_at", "user_quote", "user_start", "user_end", "user_by"}
# 0.15: how a row was made, not what it says: the ENLENS version (a colleague's older version has no such column)
_HOW = {"rowid", "ver_id", "app_version"}


def check_tasks(hyp_id: str, cids: list[str]) -> tuple[str, list[str]]:
    """0.18: which tasks are a check's (a WHERE clause on `tasks` and its arguments): its split into parts, and each
    part's search words, readings, readings again and second opinions. One definition for the sync's units and for
    what sharing a check covers (sharing.rows_of)."""
    pats = [f"decompose:{hyp_id}"] + [p for c in cids for p in (f"expand:{c}", f"check:{c}")]
    likes = [p for c in cids for p in (f"check:{c}:%", f"reread:{c}:%", f"second:check:{c}:%")]
    return " OR ".join(["task_id=?"] * len(pats) + ["task_id LIKE ?"] * len(likes)), pats + likes


def _check_unit(cx: sqlite3.Connection, hyp_id: str) -> dict[str, list[dict]]:
    hyp = _rows(cx, "SELECT * FROM hypotheses WHERE hyp_id=?", (hyp_id,))
    claims = _rows(cx, "SELECT * FROM user_claims WHERE hyp_id=? ORDER BY claim_id", (hyp_id,))
    cids = [c["claim_id"] for c in claims]
    q = ",".join("?" * len(cids))
    ver = _rows(cx, f"SELECT * FROM verifications WHERE subject_kind='user_claim' AND subject_id IN ({q}) "
                    "ORDER BY ver_id", cids) if cids else []
    sec = _rows(cx, f"SELECT * FROM second_opinions WHERE subject_id IN ({q}) ORDER BY subject_id, passage_id, model",
                cids) if cids else []
    where, args = check_tasks(hyp_id, cids)
    tasks = _rows(cx, f"SELECT * FROM tasks WHERE {where} ORDER BY task_id", args)
    tids = [t["task_id"] for t in tasks]
    res = _rows(cx, f"SELECT * FROM results WHERE task_id IN ({','.join('?' * len(tids))}) ORDER BY task_id, attempt",
                tids) if tids else []
    return {"hypotheses": hyp, "user_claims": claims, "verifications": ver, "second_opinions": sec, "tasks": tasks,
            "results": res}


def themes_tasks(run_id: str) -> tuple[str, tuple]:
    """0.18: which tasks are a theme run's (its naming tasks): a WHERE clause on `tasks` and its arguments."""
    head = f"theme:{run_id}:"
    return "kind='theme' AND substr(task_id, 1, ?) = ?", (len(head), head)


def _themes_unit(cx: sqlite3.Connection, run_id: str) -> dict[str, list[dict]]:
    where, args = themes_tasks(run_id)
    tasks = _rows(cx, f"SELECT * FROM tasks WHERE {where} ORDER BY task_id", args)
    tids = [t["task_id"] for t in tasks]
    return {"theme_runs": _rows(cx, "SELECT * FROM theme_runs WHERE run_id=?", (run_id,)),
            "themes": _rows(cx, "SELECT * FROM themes WHERE run_id=? ORDER BY theme_id", (run_id,)),
            "theme_members": _rows(cx, "SELECT * FROM theme_members WHERE run_id=? ORDER BY passage_id", (run_id,)),
            "tasks": tasks,
            "results": _rows(cx, f"SELECT * FROM results WHERE task_id IN ({','.join('?' * len(tids))}) ORDER BY "
                                 "task_id, attempt", tids) if tids else []}


def _fp(unit: dict[str, list[dict]], canon: dict[str, str], shape=None) -> str:
    """A unit's fingerprint: what was found and read, with documents named by their content; not how it was produced
    (tasks, results, the ids made from them) and not what people decided (kept per person). `shape(table, row)`
    gives the fields of a row that count (see `_fingerprints`); without it, every column (as 0.14.0 to 0.14.2)."""
    parts = []
    for t in sorted(unit):
        if t in ("tasks", "results"):
            continue
        # each row named by its content, in an order that does not depend on ids
        rows = sorted(_tokens(json.dumps({k: v for k, v in (shape(t, r) if shape else r).items()
                                          if k not in _PERSONAL and k not in _HOW},
                                         sort_keys=True, ensure_ascii=False, default=str), canon) for r in unit[t])
        parts.append(t + "\n" + "\n".join(rows))
    return _sha("\n\n".join(parts))[:20]


# 0.14.3: versions differ in their columns. A fingerprint over every column (`SELECT *`, as 0.14.0 to 0.14.2 made
# them) changed whenever a version added one, even an empty one, so colleagues on different versions had a sync
# clash on every check. Now a fingerprint is made of the columns this copy has and leaves out empty values (NULL, or
# the column's declared default), so a column added later changes nothing until it holds something. The fingerprints
# 0.14.0 to 0.14.2 made are inside the files people exchange: they are worked out too (`old`, over the columns those
# versions had, plus any an add-on gives) and written down beside the new ones, so either is recognised.
_FP_TABLES = ("hypotheses", "user_claims", "verifications", "second_opinions", "theme_runs", "themes", "theme_members")
_COLS_0142 = {
    "hypotheses": "hyp_id text framework code options_json decomposed rationale model created_at batch_id note parts_json "
                  "docs_checked_at queue origin origin_id",
    "user_claims": "claim_id text target terms_json rationale options_json model created_at hyp_id part role framework "
                   "stage",
    "verifications": "ver_id subject_kind subject_id passage_id doc_id verdict confidence quote start end page model "
                     "prompt_version user_verdict user_note user_at user_quote user_start user_end scope_note "
                     "ai_history_json reread_json refers_to refers_start refers_end refers_where user_by",
    "second_opinions": "subject_id passage_id model verdict confidence quote start end scope_note at",
    "theme_runs": "run_id mode k seed embed_model chat_model created_at passages run_key settings_json corpus_version",
    "themes": "run_id theme_id name description terms_json size reps_json name_source quotes_json model removed_at "
              "replaces",
    "theme_members": "run_id theme_id passage_id similarity found_in"}
_COLS_0142_SETS = {t: set(v.split()) for t, v in _COLS_0142.items()}
_CORE: dict[str, set[str]] = {}
_NO_DEFAULT = object()


def _core_columns() -> dict[str, set[str]]:
    """The columns this version of ENLENS itself gives the unit tables (not an add-on)."""
    if not _CORE:
        from ..store import MIGRATIONS, SCHEMA, _add_columns

        mem = sqlite3.connect(":memory:")
        try:
            mem.executescript(SCHEMA)
            _add_columns(mem, MIGRATIONS)
            for t in _FP_TABLES:
                _CORE[t] = {r[1] for r in mem.execute(f"PRAGMA table_info({t})")}
        finally:
            mem.close()
    return _CORE


def _literal(sql: str | None) -> Any:
    """A column's declared default as a value (`_NO_DEFAULT` for none, or an expression)."""
    if sql is None:
        return _NO_DEFAULT
    s = sql.strip()
    if s.upper() == "NULL":
        return None
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1].replace("''", "'")
    for cast in (int, float):
        try:
            return cast(s)
        except ValueError:
            pass
    return _NO_DEFAULT


def _fingerprints(cx: sqlite3.Connection):
    """For this copy's database: `fps(unit, canon) -> (new, old)`, a unit's fingerprints (the unit may come from a
    colleague's database: only the columns this copy has count, the only ones it can keep)."""
    cols, dflt = {}, {}
    for t in _FP_TABLES:
        info = cx.execute(f"PRAGMA table_info({t})").fetchall()
        cols[t] = {r[1] for r in info}
        dflt[t] = {r[1]: v for r in info if (v := _literal(r[4])) is not _NO_DEFAULT}
    core = _core_columns()

    def new(t: str, r: dict) -> dict:
        have, d = cols.get(t), dflt.get(t, {})
        return {k: v for k, v in r.items() if (have is None or k in have) and v is not None
                and not (k in d and v == d[k])}

    def old(t: str, r: dict) -> dict:
        have, since = cols.get(t), core.get(t, set()) - _COLS_0142_SETS.get(t, set())
        return {k: v for k, v in r.items() if (have is None or k in have) and k not in since}

    return lambda unit, canon: (_fp(unit, canon, new), _fp(unit, canon, old))


def _known(fps: tuple[str, str], seen: Iterable[str] | None) -> bool:
    """Whether a unit's state (either form of its fingerprint) is among these states."""
    return bool(seen) and (fps[0] in seen or fps[1] in seen)


def _running(unit: dict[str, list[dict]]) -> bool:
    """0.14.3: whether a check or theme run of this copy has work under way, as the result page counts it as waiting:
    a check by queue not done yet, a task in the queue for Claude Code or taken by a helper (also one waiting for the
    stronger model), or a part for the local model not read yet. A round only adds tasks, so its fingerprint does not
    show it. (A task left unanswered by a run that crashed does not count: it would keep the older version forever.)"""
    hyp = (unit.get("hypotheses") or [{}])[0]
    if hyp.get("queue") == "waiting":
        return True
    for t in unit.get("tasks", []):
        open_ = t["status"] in UNFINISHED or (t["status"] == "done" and t.get("again"))
        if open_ and (t.get("queued") or t.get("claimed_by")):
            return True
        if t["status"] in UNFINISHED and t["task_id"].endswith(":local"):
            return True
    return False


def _canon(cx: sqlite3.Connection) -> dict[str, str]:
    """{doc_id: the document named by its content}: the same in every copy that has the same reading of a file, and
    for a document removed since (checks keep what they read of it), from the note of its removal. 0.18: a document
    this copy knows only from the shared folder (a colleague keeps its file out of the folder, sync/folder.py), from
    what the folder says of it, so a check that read it is compared by content in every copy."""
    out: dict[str, str] = {}
    try:
        out.update({d: f"{base_id(d)}.{fp}" for d, fp in cx.execute("SELECT doc_id, text_fp FROM sync_folder_docs "
                                                                    "WHERE text_fp IS NOT NULL").fetchall()})
    except sqlite3.OperationalError:  # a colleague's copy from before 0.18
        pass
    out.update({d: f"{base_id(d)}.{fp}" for d, fp in cx.execute("SELECT key, fp FROM sync_removed WHERE "
                                                                "kind='document' AND fp IS NOT NULL").fetchall()})
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


HEAD = "~"  # 0.18: the key of a codebook's own settings (title, what a code is called, directional) among its codes


def codebook_state(folder: Path, name: str) -> dict | None:
    """0.18: a codebook as the editor sees it (codebooks._state: each code with its stable id), with its side file
    (`meta`), read from `folder`; None when there is none."""
    from ..codebooks import _state
    from ..frameworks import _load_file

    csv = folder / f"{name}.csv"
    if not csv.is_file():
        return None
    fw = _load_file(csv, "project")
    if fw is None:
        return None
    meta = json.loads(json.dumps(fw.meta or {}))
    st = _state(name, fw.codes, meta, fw.title, fw.label, fw.directional)
    st["meta"] = meta
    return st


def code_fp(code: dict, group_names: dict[str, str]) -> str:
    """0.18: one code's fingerprint: its name, wording, group, the words it is matched by and its examples."""
    return _sha(json.dumps({"code": code["code"], "description": code["description"], "group": code["group"],
                            "group_name": group_names.get(code["group"], ""), "include": code["include"],
                            "exclude": code["exclude"], "keywords": list(code["keywords"]),
                            "examples": [e["quote"] for e in code["examples"]]},
                           sort_keys=True, ensure_ascii=False))[:20]


def head_fp(state: dict) -> str:
    """0.18: the fingerprint of a codebook's own settings."""
    return _sha(json.dumps({"title": state["title"], "label": state["label"], "directional": bool(state["directional"])},
                           sort_keys=True, ensure_ascii=False))[:20]


def code_states(state: dict) -> dict[str, str]:
    """0.18: {key: fingerprint} of each code of a codebook (`<name>/<code id>`) and of its settings (`<name>/~`), as
    `sync_seen` keeps them (kind "code"), so a codebook both copies changed is merged code by code."""
    names = {g["group"]: g["group_name"] for g in state["groups"]}
    out = {f"{state['name']}/{c['uid']}": code_fp(c, names) for c in state["codes"]}
    out[f"{state['name']}/{HEAD}"] = head_fp(state)
    return out


def _plain(ids: Iterable[str], key: str, of: str) -> dict[str, str]:
    """For a sync-clash copy `key` of `of` ("h1-0c5ab4" of "h1"): its ids without the copy's mark, so it can be
    compared with the version it was copied from."""
    tag = key[len(of) + 1:] if key.startswith(of + "-") else ""
    return {i: i[:-len(tag) - 1] for i in ids if tag and i.endswith("-" + tag)}


def _home_codebooks() -> Path:
    from ..home import home

    return home() / "frameworks"


def _used_codebooks(cx: sqlite3.Connection) -> set[str]:
    from ..frameworks import BUNDLED

    names = {r[0] for r in cx.execute("SELECT DISTINCT framework FROM labels UNION SELECT DISTINCT framework FROM "
                                      "hypotheses UNION SELECT DISTINCT framework FROM user_claims") if r[0]}
    return names - set(BUNDLED)


def _codebook_where(ws: Workspace, name: str) -> Path:
    folder = Path(ws.root) / "frameworks"
    return folder if (folder / f"{name}.csv").is_file() else _home_codebooks()


def _codebook_rows(ws: Workspace, name: str) -> list[tuple[str, str, str]]:
    """What `record_seen` writes down of one codebook: its fingerprint and each code's."""
    where = _codebook_where(ws, name)
    fp = _codebook_fp(where, name)
    if not fp:
        return []
    rows = [("codebook", name, fp)]
    st = codebook_state(where, name)
    if st:
        rows += [("code", k, v) for k, v in code_states(st).items()]
    return rows


def _codebooks_seen(ws: Workspace, cx: sqlite3.Connection, used: set[str] | None = None) -> list[str]:
    """The codebooks `record_seen` writes down: the project's own, used or not, and those it uses from the home
    folder (`used`: `_used_codebooks`, when the caller knows it already)."""
    from ..frameworks import BUNDLED, NAME_RE

    folder = Path(ws.root) / "frameworks"
    own = {p.stem for p in folder.glob("*.csv")} if folder.is_dir() else set()
    names = ((_used_codebooks(cx) if used is None else used) | own) - set(BUNDLED)
    return sorted(n for n in names if NAME_RE.match(n))


def record_seen(ws: Workspace, cx: sqlite3.Connection) -> None:
    """Write down the fingerprint of every check, theme run and codebook as it is now (when sent or brought in)."""
    canon = _canon(cx)
    fps = _fingerprints(cx)
    rows = []
    for (hid,) in cx.execute("SELECT hyp_id FROM hypotheses").fetchall():
        rows += [("check", hid, fp) for fp in fps(_check_unit(cx, hid), canon)]  # both forms (0.14.3)
    for (rid,) in cx.execute("SELECT run_id FROM theme_runs").fetchall():
        rows += [("themes", rid, fp) for fp in fps(_themes_unit(cx, rid), canon)]
    # 0.18: the project's own codebooks too, used or not, and each code of each (a codebook both copies changed is
    # merged code by code: codebook_merge.py); one used from the home folder is read there
    for name in _codebooks_seen(ws, cx):
        rows += _codebook_rows(ws, name)
    cx.executemany("INSERT OR IGNORE INTO sync_seen(kind, key, fp) VALUES (?,?,?)", rows)


def record_seen_since(ws: Workspace) -> None:
    """`record_seen` for a round of the shared folder (deep dive S5): what it would write down, worked out for the
    checks, theme runs and codebooks that changed since the last round only (sync/changes.py), from one moment of the
    project read without the write lock; then added in a short transaction of its own. What it adds is what
    `record_seen` would add: a unit that did not change had its fingerprints written down by an earlier round of this
    process (a row of `sync_seen` taken away since counts as a change)."""
    from . import changes

    mem = changes.memory(ws.db_path)
    with mem.lock:
        rcx = sqlite3.connect(ws.db_path, timeout=60, isolation_level=None)
        try:
            rcx.execute("BEGIN")
            now = changes.clock(rcx)
            canon = _canon(rcx)
            ctx = (changes.ident(rcx), changes.schema(rcx), hashlib.sha1(json.dumps(sorted(canon.items())).encode()).hexdigest())
            changed = changes.changed_since(rcx, mem.seen_upto) if mem.seen_context == ctx else None
            fps = _fingerprints(rcx)
            hyps = [r[0] for r in rcx.execute("SELECT hyp_id FROM hypotheses")]
            runs = [r[0] for r in rcx.execute("SELECT run_id FROM theme_runs")]
            if changed is None:
                again: set[tuple[str, str]] | None = None
                lost_books: set[str] = set()
            else:
                keys, kinds = changes.touched(rcx, changed)
                again = {k for k in keys if k[0] in ("check", "themes")} | {
                    (k, key) for k in kinds & {"check", "themes"} for key in (hyps if k == "check" else runs)}
                lost_books = set()
                for h in changed.get("sync_seen", ()):  # a fingerprint taken away: written down again
                    k, _, key = h.partition("|")
                    if k in ("check", "themes"):
                        again.add((k, key))
                    elif k in ("codebook", "code"):
                        lost_books.add(key.split("/", 1)[0])
            rows = []
            units = set()
            for kind, ids, unit in (("check", hyps, _check_unit), ("themes", runs, _themes_unit)):
                for key in ids:
                    units.add((kind, key))
                    if again is None or (kind, key) in again or (kind, key) not in mem.seen_units:
                        rows += [(kind, key, fp) for fp in fps(unit(rcx, key), canon)]
            if changed is None or mem.seen_names is None or {"labels", "hypotheses", "user_claims"} & set(changed):
                used = _used_codebooks(rcx)
            else:
                used = mem.seen_names
            books = {}
            for name in _codebooks_seen(ws, rcx, used):
                books[name] = changes.files_sig(f / f"{name}.{ext}" for f in (Path(ws.root) / "frameworks",
                                                                              _home_codebooks())
                                                for ext in ("csv", "json"))
                if again is None or name in lost_books or mem.seen_books.get(name) != books[name]:
                    rows += _codebook_rows(ws, name)
        finally:
            rcx.rollback()
            rcx.close()
        if rows:
            with ws.connect() as cx:
                cx.executemany("INSERT OR IGNORE INTO sync_seen(kind, key, fp) VALUES (?,?,?)", rows)
        mem.seen_upto, mem.seen_context, mem.seen_units = now, ctx, units
        mem.seen_books, mem.seen_names = books, used
