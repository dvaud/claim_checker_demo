"""History inside the app (0.16, roadmap F5): earlier versions of what a person changes, to compare and restore.

Before a person changes a set of themes (a name, a merge, a theme removed, a passage moved), their judgements in a
check (a verdict, a comment, the sentence they point to, the check's note) or a codebook (codebooks.py), the state
before the change is kept as a version. *Compare* says in words what changed since a version; *Restore* puts it back,
after keeping the state it replaces as a version too, so a restore can itself be undone. The research log
(researchlog.py) is their story: an entry about a change names the version from before it.

What a version holds is only what a person made: the names, merges, moves and removals of a theme set (not the
themes found, which a run makes again from the same settings), and your own judgements in a check (not the AI's
answers, nor a colleague's judgements, which stay theirs). Versions of themes and checks are kept in the project's
database (`versions`), the latest `KEEP` of each; codebooks keep theirs beside their file, so a codebook used by all
projects has one history (codebooks.py). Versions are this copy's: they do not travel to colleagues.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from .store import Workspace, now

KEEP = 200  # versions kept of each set of themes or check (the oldest go first)


@dataclass
class Kind:
    title: Callable[[Workspace, str], str]                      # what it is called ("the themes of 12 Nov")
    capture: Callable[[Workspace, sqlite3.Connection, str], Any]  # its state now (JSON-able)
    changes: Callable[[Workspace, Any, Any, str], list[dict]]  # what differs from an old state to a new one, in words
    apply: Callable[[Workspace, sqlite3.Connection, str, Any], None]  # put a state back (in the transaction)
    stored: str = "db"                                          # db | own (the kind keeps its versions itself)
    versions: Callable | None = None                             # own: (ws, key) -> [version meta]
    load: Callable | None = None                                 # own: (ws, key, version_id) -> (meta, state)
    restore: Callable | None = None                              # own: (ws, key, version_id) -> result


KINDS: dict[str, Kind] = {}


def _kind(kind: str) -> Kind | None:
    if kind == "codebook" and kind not in KINDS:
        from . import codebooks  # noqa: F401 - it adds its kind on import
    return KINDS.get(kind)


def _me() -> str:
    from .people import me

    return me()


def snapshot(ws: Workspace, cx: sqlite3.Connection, kind: str, key: str, label: str) -> str | None:
    """Keep the state of `kind`/`key` before a change (`label`: the change, in a few words). Returns the version's id,
    or that of the latest version when nothing changed since it (None when the thing does not exist)."""
    k = KINDS[kind]
    state = k.capture(ws, cx, key)
    if state is None:
        return None
    data = json.dumps(state, ensure_ascii=False, sort_keys=True)
    last = cx.execute("SELECT version_id, data_json FROM versions WHERE kind=? AND key=? ORDER BY at DESC, rowid DESC "
                      "LIMIT 1", (kind, key)).fetchone()
    if last and last[1] == data:
        return last[0]
    vid = "v" + uuid.uuid4().hex[:16]
    cx.execute("INSERT INTO versions(version_id, kind, key, at, person_id, label, data_json) VALUES (?,?,?,?,?,?,?)",
               (vid, kind, key, now(), _me(), label[:200], data))
    old = cx.execute("SELECT version_id FROM versions WHERE kind=? AND key=? ORDER BY at DESC, rowid DESC LIMIT -1 "
                     "OFFSET ?", (kind, key, KEEP)).fetchall()
    if old:
        cx.executemany("DELETE FROM versions WHERE version_id=?", old)
    return vid


def present(ws: Workspace, ids: list[str]) -> set[str]:
    """Which of these version ids can still be compared and restored."""
    ids = [i for i in ids if i]
    if not ids:
        return set()
    out = {r[0] for r in ws.query(f"SELECT version_id FROM versions WHERE version_id IN ({','.join('?' * len(ids))})",
                                  ids)}
    rest = [i for i in ids if i not in out]
    if rest:
        from . import codebooks

        out |= codebooks.versions_present(ws, rest)
    return out


def _names(ws: Workspace) -> dict[str, str]:
    from .people import names

    return names(ws)


def versions(ws: Workspace, kind: str, key: str) -> dict:
    """{title, versions: [{version_id, at, label, who, mine}], newest first}."""
    k = _kind(kind)
    if k is None:
        raise KeyError(kind)
    nm = _names(ws)
    if k.stored == "own":
        rows = k.versions(ws, key)
    else:
        rows = [dict(r) for r in ws.query("SELECT version_id, at, person_id, label FROM versions WHERE kind=? AND key=? "
                                          "ORDER BY at DESC, rowid DESC", (kind, key))]
    for r in rows:
        r["who"] = nm.get(r.get("person_id") or "", "a colleague")
        r["mine"] = r.get("person_id") == _me()
    return {"kind": kind, "key": key, "title": k.title(ws, key), "versions": rows}


def _load(ws: Workspace, kind: str, key: str, version_id: str) -> tuple[dict, Any]:
    k = _kind(kind)
    if k.stored == "own":
        return k.load(ws, key, version_id)
    rows = ws.query("SELECT version_id, at, person_id, label, data_json FROM versions WHERE version_id=? AND kind=? AND "
                    "key=?", (version_id, kind, key))
    if not rows:
        raise KeyError(version_id)
    meta = dict(rows[0])
    return meta, json.loads(meta.pop("data_json"))


def compare(ws: Workspace, kind: str, key: str, version_id: str) -> dict:
    """What changed from a version to now: {version, title, changes: [{what, before, after}], same: bool}."""
    k = _kind(kind)
    if k is None:
        raise KeyError(kind)
    meta, old = _load(ws, kind, key, version_id)
    with ws.connect() as cx:
        cur = k.capture(ws, cx, key)
    if cur is None:
        raise KeyError(key)
    changes = k.changes(ws, old, cur, key)
    meta["who"] = _names(ws).get(meta.get("person_id") or "", "a colleague")
    return {"kind": kind, "key": key, "title": k.title(ws, key), "version": meta, "changes": changes,
            "same": not changes}


def restore(ws: Workspace, kind: str, key: str, version_id: str) -> dict:
    """Put a version back. The state it replaces is kept as a version first, and the research log says so."""
    from . import researchlog

    k = _kind(kind)
    if k is None:
        raise KeyError(kind)
    if k.stored == "own":
        return k.restore(ws, key, version_id)
    meta, old = _load(ws, kind, key, version_id)
    title = k.title(ws, key)
    with ws.connect() as cx:
        cur = k.capture(ws, cx, key)
        if cur is None:
            raise KeyError(key)
        changes = k.changes(ws, cur, old, key)
        if not changes:
            return {"restored": False, "changes": []}
        before = snapshot(ws, cx, kind, key, f"restoring the version of {meta['at'][:16].replace('T', ' ')}")
        k.apply(ws, cx, key, old)
        researchlog.record(cx, "restored", f"Restored {title} to its version of {_when(meta['at'])} "
                                           f"({_n(len(changes), 'change')}).",
                           {"themes": "themes", "check": "check"}.get(kind, kind), key, title, version_id=before,
                           data={"kind": kind, "version_id": version_id, "changes": len(changes)})
    return {"restored": True, "changes": changes}


def _when(at: str) -> str:
    from .researchlog import day

    return f"{day(at)}, {(at or '')[11:16]} UTC"


def _n(k: int, one: str, many: str | None = None) -> str:
    return f"{k} {one if k == 1 else (many or one + 's')}"


# ---------------------------------------------------------------------------------------------
# a set of themes: a person's names, merges, moves and removals
# ---------------------------------------------------------------------------------------------
def _themes_title(ws: Workspace, run_id: str) -> str:
    r = ws.query("SELECT created_at, k FROM theme_runs WHERE run_id=?", (run_id,))
    from .researchlog import day

    return f"the themes found on {day(r[0]['created_at'])}" if r else "a set of themes"


def _themes_capture(ws: Workspace, cx: sqlite3.Connection, run_id: str) -> dict | None:
    from .themes import _edits

    r = cx.execute("SELECT run_key FROM theme_runs WHERE run_id=?", (run_id,)).fetchone()
    if r is None:
        return None
    e = _edits(ws, r[0])
    removed = sorted(x[0] for x in cx.execute("SELECT theme_id FROM themes WHERE run_id=? AND removed_at IS NOT NULL",
                                              (run_id,)))
    return {"names": {str(k): v for k, v in e["names"].items()}, "merges": {str(k): v for k, v in e["merges"].items()},
            "moves": e["moves"], "removed": removed}


def _theme_names(ws: Workspace, run_id: str) -> dict[int, str]:
    return {r[0]: (r[1] or f"Theme {r[0] + 1}") for r in ws.query("SELECT theme_id, name FROM themes WHERE run_id=?",
                                                                  (run_id,))}


def _themes_changes(ws: Workspace, old: dict, new: dict, run_id: str) -> list[dict]:
    found = _theme_names(ws, run_id)

    def name(t: str | int, state: dict) -> str:
        return state["names"].get(str(t)) or found.get(int(t), f"Theme {int(t) + 1}")

    out = []
    for t in sorted({*old["names"], *new["names"]}, key=int):
        a, b = old["names"].get(t), new["names"].get(t)
        if a != b:
            out.append({"what": "Name of a theme", "before": a or found.get(int(t), ""),
                        "after": b or found.get(int(t), "")})
    for t in sorted({*old["merges"], *new["merges"]}, key=int):
        a, b = old["merges"].get(t), new["merges"].get(t)
        if a != b:
            out.append({"what": f"{name(t, new)} merged into",
                        "before": name(a, old) if a is not None else "(separate)",
                        "after": name(b, new) if b is not None else "(separate)"})
    for t in sorted(set(old["removed"]) ^ set(new["removed"])):
        out.append({"what": name(t, new), "before": "removed" if t in old["removed"] else "shown",
                    "after": "removed" if t in new["removed"] else "shown"})
    moved = sum(1 for p in {*old["moves"], *new["moves"]} if old["moves"].get(p) != new["moves"].get(p))
    if moved:
        out.append({"what": "Passages moved to another theme", "before": "", "after": _n(moved, "passage")})
    return out


def _themes_apply(ws: Workspace, cx: sqlite3.Connection, run_id: str, state: dict) -> None:
    cur = _themes_capture(ws, cx, run_id)
    rkey = cx.execute("SELECT run_key FROM theme_runs WHERE run_id=?", (run_id,)).fetchone()[0]
    ids = {x[0] for x in cx.execute("SELECT theme_id FROM themes WHERE run_id=?", (run_id,))}
    me, at = _me(), now()
    rows = []
    for t in {*cur["names"], *state["names"]}:
        if int(t) in ids and cur["names"].get(t) != state["names"].get(t):
            rows.append(("theme", f"{rkey}:{t}", "name", state["names"].get(t) or ""))
    for t in {*cur["merges"], *state["merges"]}:
        if int(t) in ids and cur["merges"].get(t) != state["merges"].get(t):
            v = state["merges"].get(t)
            rows.append(("theme", f"{rkey}:{t}", "merge", str(int(v)) if v is not None and int(v) in ids else ""))
    members = {x[0] for x in cx.execute("SELECT passage_id FROM theme_members WHERE run_id=?", (run_id,))}
    for p in {*cur["moves"], *state["moves"]}:
        if p in members and cur["moves"].get(p) != state["moves"].get(p):
            v = state["moves"].get(p)
            rows.append(("theme_member", f"{rkey}:{p}", "theme", str(int(v)) if v is not None and int(v) in ids else ""))
    cx.executemany("INSERT INTO reviews(item_kind, item_id, field, decision, corrected, reviewer, decided_at, person_id) "
                   "VALUES (?, ?, ?, 'change', ?, '', ?, ?)", [(*r, at, me) for r in rows])
    cx.execute("UPDATE themes SET removed_at=NULL WHERE run_id=?", (run_id,))
    for t in state["removed"]:
        cx.execute("UPDATE themes SET removed_at=? WHERE run_id=? AND theme_id=?", (at, run_id, int(t)))


KINDS["themes"] = Kind(_themes_title, _themes_capture, _themes_changes, _themes_apply)


# ---------------------------------------------------------------------------------------------
# a check: your judgements of its excerpts, and its note
# ---------------------------------------------------------------------------------------------
def _check_title(ws: Workspace, hyp_id: str) -> str:
    from .researchlog import quoted

    r = ws.query("SELECT text FROM hypotheses WHERE hyp_id=?", (hyp_id,))
    return f"the check of {quoted(r[0][0], 90)}" if r else "a check"


def _check_capture(ws: Workspace, cx: sqlite3.Connection, hyp_id: str) -> dict | None:
    h = cx.execute("SELECT note FROM hypotheses WHERE hyp_id=?", (hyp_id,)).fetchone()
    if h is None:
        return None
    me = _me()
    rows = cx.execute("SELECT j.claim_id, j.passage_id, j.verdict, j.note, j.quote, j.start, j.end FROM judgements j "
                      "JOIN user_claims u ON u.claim_id=j.claim_id WHERE COALESCE(u.hyp_id, u.claim_id)=? AND "
                      "j.person_id=? AND (j.verdict IS NOT NULL OR j.note IS NOT NULL)", (hyp_id, me)).fetchall()
    return {"note": h[0] or "", "judgements": {f"{r[0]}|{r[1]}": {"verdict": r[2], "note": r[3], "quote": r[4],
                                                                  "start": r[5], "end": r[6]} for r in rows}}


_VERDICT_WORDS = {"supports": "supports", "partially_supports": "partly supports", "refutes": "contradicts",
                  "not_relevant": "not about it", None: "not judged"}


def _check_changes(ws: Workspace, old: dict, new: dict, hyp_id: str) -> list[dict]:
    out = []
    if (old.get("note") or "") != (new.get("note") or ""):
        out.append({"what": "Note on the check", "before": old.get("note") or "", "after": new.get("note") or ""})
    keys = sorted({*old["judgements"], *new["judgements"]})
    where = {}
    if keys:
        pids = sorted({k.split("|", 1)[1] for k in keys})
        for r in ws.query(f"SELECT p.passage_id, p.page, d.title FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
                          f"WHERE p.passage_id IN ({','.join('?' * len(pids))})", pids):
            where[r[0]] = (r[2] or "a document") + (f", p. {r[1]}" if r[1] is not None else "")
    for k in keys:
        a = old["judgements"].get(k) or {}
        b = new["judgements"].get(k) or {}
        place = where.get(k.split("|", 1)[1], "an excerpt no longer in the project")
        if a.get("verdict") != b.get("verdict"):
            out.append({"what": f"Your judgement of {place}", "before": _VERDICT_WORDS.get(a.get("verdict"), ""),
                        "after": _VERDICT_WORDS.get(b.get("verdict"), "")})
        if (a.get("note") or "") != (b.get("note") or ""):
            out.append({"what": f"Your comment on {place}", "before": a.get("note") or "", "after": b.get("note") or ""})
        if (a.get("quote") or "") != (b.get("quote") or "") and a.get("verdict") and b.get("verdict"):
            out.append({"what": f"The sentence you point to in {place}", "before": a.get("quote") or "",
                        "after": b.get("quote") or ""})
    return out


def _check_apply(ws: Workspace, cx: sqlite3.Connection, hyp_id: str, state: dict) -> None:
    from . import people

    cur = _check_capture(ws, cx, hyp_id)
    me = _me()
    cx.execute("UPDATE hypotheses SET note=? WHERE hyp_id=?", (state.get("note") or None, hyp_id))
    claims = set()
    for k in {*cur["judgements"], *state["judgements"]}:
        if cur["judgements"].get(k) == state["judgements"].get(k):
            continue
        cid, pid = k.split("|", 1)
        if not cx.execute("SELECT 1 FROM verifications WHERE subject_kind='user_claim' AND subject_id=? AND "
                          "passage_id=?", (cid, pid)).fetchone():
            continue  # the excerpt is gone (a part removed): nothing to put back
        j = state["judgements"].get(k) or {}
        people.record(cx, cid, pid, me, j.get("verdict"), j.get("note"), None, j.get("quote"), j.get("start"),
                      j.get("end"))
        claims.add(cid)
    if claims:
        people.refresh(cx, claims, me)


KINDS["check"] = Kind(_check_title, _check_capture, _check_changes, _check_apply)
