"""Your own codebook (0.16, roadmap K1): make and change a codebook in the app.

A codebook stays a CSV file (frameworks.py), kept with one project (`<project>/frameworks/`) or with all of them
(`<ENLENS_HOME>/frameworks/`), so it still opens in a spreadsheet. The editor writes the optional columns too
(`when_to_use`, `when_not_to_use`, `keywords`: the words it is matched by besides its description, `examples`: quotes
from the documents, one per line), and a side file `<name>.json` with what a spreadsheet cannot hold:

- `ids`: a stable id for each code, so a rename is told from a code removed and another added;
- `events`: renames, merges and changes of wording, with their time. Labels follow a rename and a merge (`follow`),
  in this project at once and in every other project that uses the codebook the next time it is opened; only labels
  made before the change move, so a later code that takes an old name keeps its own. A label moved by a merge keeps
  the code it had (`labels.merged_from`), so restoring the codebook from before the merge gives it back;
- `removed`: codes taken out, with their definitions. Their labels are not deleted: they wait under *Removed codes*
  (`removed_codes`) until the code comes back;
- `places`: where each example quote was found (the quote check: every example is words of a document);
- `groups`: the groups in their order, `ordered`: the codes keep the editor's order.

An edit changes no result by itself: labels are moved, never made or deleted. A code whose wording changed says which
of its labels the AI made with the earlier wording (`stale`) and can have only those passages labelled again
(`relabel_passages`). *Try it* (`try_codes`) counts, without AI, how many passages and documents the keyword pass
would pick for each code. Each saved change keeps the codebook as it was (`history/<name>/<version>.json` beside the
file: history.py's *Compare* and *Restore*) and goes into the research log.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from . import frameworks, history
from .frameworks import BUNDLED, NAME_RE, Code
from .review import csv_cell, csv_uncell
from .store import Workspace, now
from .textutil import fast_normalise, normalise

MAX_CODES = 5000
MAX_EXAMPLES = 8
KEEP = 200  # versions kept of each codebook
_UID = re.compile(r"k[0-9a-f]{10}")
_VID = re.compile(r"c[0-9a-f]{16}")
COLUMNS = ("code", "description", "group", "group_name", "when_to_use", "when_not_to_use", "keywords", "examples")


def _me() -> str:
    from .people import me

    return me()


def _home_folder() -> Path:
    from .home import home

    return home() / "frameworks"


def folder(ws: Workspace | None, where: str) -> Path:
    return _home_folder() if where == "home" else Path(ws.root) / "frameworks"


def locate(ws: Workspace, name: str) -> tuple[str, Path | None]:
    """Where a codebook is kept: ("project" | "home", its folder), or ("bundled", None). The project's own copy of a
    codebook comes before the one for all projects, as frameworks.available reads them."""
    if name in BUNDLED:
        return "bundled", None
    if not NAME_RE.match(name or ""):
        raise KeyError(name)
    for where in ("project", "home"):
        f = folder(ws, where)
        if (f / f"{name}.csv").is_file():
            return where, f
    raise KeyError(name)


def _meta(f: Path, name: str) -> dict:
    try:
        m = json.loads((f / f"{name}.json").read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def default_uid(name: str, code: str) -> str:
    """The id of a code that has none written down yet: the same for the same name, so versions from before the
    editor still compare code by code."""
    return "k" + hashlib.sha1(f"{name}\0{code}".encode()).hexdigest()[:10]


# ---------------------------------------------------------------------------------------------
# a codebook as the editor sees it
# ---------------------------------------------------------------------------------------------
def _state(name: str, codes: dict[str, Code], meta: dict, title: str, label: str, directional: bool) -> dict:
    ids = meta.get("ids") or {}
    places = meta.get("places") or {}
    groups: list[dict] = []
    seen = set()
    for g in meta.get("groups") or []:
        if isinstance(g, dict) and g.get("group") is not None and g["group"] not in seen:
            seen.add(g["group"])
            groups.append({"group": str(g["group"]), "group_name": str(g.get("group_name") or "")})
    order = list(codes.values())
    if not meta.get("ordered"):
        order.sort(key=lambda c: frameworks._natural(c.code))
    out = []
    for c in order:
        if c.group not in seen:
            seen.add(c.group)
            groups.append({"group": c.group, "group_name": c.group_name})
        uid = ids.get(c.code) if _UID.fullmatch(str(ids.get(c.code) or "")) else default_uid(name, c.code)
        at = {p.get("quote"): p for p in places.get(uid, []) if isinstance(p, dict)}
        out.append({"uid": uid, "code": c.code, "description": c.description, "group": c.group,
                    "include": c.include, "exclude": c.exclude, "keywords": list(c.keywords),
                    "examples": [{"quote": q, **{k: v for k, v in (at.get(q) or {}).items() if k != "quote"}}
                                 for q in c.examples]})
    for g in groups:  # a group's name is the one its codes carry
        names = [c.group_name for c in codes.values() if c.group == g["group"] and c.group_name]
        if names:
            g["group_name"] = names[0]
    return {"name": name, "title": title, "label": label, "directional": bool(directional), "groups": groups,
            "codes": out}


def state_of(ws: Workspace, name: str) -> dict:
    fw = frameworks.get(name, ws)
    return _state(name, fw.codes, json.loads(json.dumps(fw.meta or {})), fw.title, fw.label, fw.directional)


def load(ws: Workspace, name: str) -> dict:
    """The codebook for the editor: its state, where it is kept, how it is used here, its removed codes with their
    labels, and the codes whose wording changed since the AI labelled with them."""
    follow(ws, name)
    where, f = locate(ws, name)
    st = state_of(ws, name)
    st["where"] = where
    st["editable"] = where != "bundled"
    st["shadows_home"] = where == "project" and (_home_folder() / f"{name}.csv").is_file()
    st["in_home"] = (_home_folder() / f"{name}.csv").is_file()
    by_code = {r[0]: r[1] for r in ws.query("SELECT code, COUNT(*) FROM labels WHERE framework=? GROUP BY code", (name,))}
    st["used"] = {"labels": sum(by_code.values()), "by_code": by_code,
                  "checks": int(ws.scalar("SELECT COUNT(*) FROM hypotheses WHERE framework=?", (name,)) or 0)}
    st["removed"] = removed_codes(ws, name)
    st["stale"] = stale(ws, name)
    st["versions"] = len(_version_files(ws, name))
    st["profile_default"] = name == _profile_default()
    st["clashes"] = clashes(ws, name)  # 0.18: a colleague's version of a code you both changed (sync)
    return st


def clashes(ws: Workspace, name: str) -> list[dict]:
    """0.18 (sync/codebook_merge.py): the codes you and a colleague both changed since you last exchanged the
    codebook. Yours is in the codebook; theirs waits here until you keep one of the two (`settle_clash`):
    [{"uid", "code" (yours now, or None when you removed it), "theirs": {their version}, "name", "at"}]."""
    fw = frameworks.get(name, ws)
    by_uid = {c["uid"]: c for c in state_of(ws, name)["codes"]}
    out = []
    for uid, c in ((fw.meta or {}).get("clashes") or {}).items():
        if not isinstance(c, dict):
            continue
        theirs = {k: c.get(k) for k in ("code", "description", "group", "group_name", "include", "exclude",
                                        "keywords", "examples")}
        out.append({"uid": uid, "code": (by_uid.get(uid) or {}).get("code"), "removed_here": bool(c.get("removed_here")),
                    "theirs": theirs, "person_id": c.get("person_id"), "name": c.get("name") or "a colleague",
                    "at": c.get("at")})
    return out


def settle_clash(ws: Workspace, name: str, uid: str, keep: str, why: str | None = None) -> dict:
    """0.18: keep your version of a code you and a colleague both changed (`keep` "mine": theirs is set aside), or
    theirs ("theirs": it replaces yours, or comes back when you had removed it; labels follow a new name as in any
    edit). Each is a change of the codebook: a version is kept and the research log says so. Returns the codebook."""
    from . import researchlog

    if keep not in ("mine", "theirs"):
        raise ValueError("Say which version to keep: yours or theirs.")
    where, f = locate(ws, name)
    if where == "bundled":
        raise KeyError(name)
    fw = frameworks.get(name, ws)
    clash = ((fw.meta or {}).get("clashes") or {}).get(uid)
    if not isinstance(clash, dict):
        raise KeyError(uid)
    who = clash.get("name") or "a colleague"
    if keep == "theirs":
        st = state_of(ws, name)
        theirs = {"uid": uid, "code": str(clash.get("code") or ""), "description": str(clash.get("description") or ""),
                  "group": str(clash.get("group") or ""), "include": str(clash.get("include") or ""),
                  "exclude": str(clash.get("exclude") or ""), "keywords": list(clash.get("keywords") or []),
                  "examples": [{"quote": q} for q in (clash.get("examples") or []) if isinstance(q, str)]}
        codes = [theirs if c["uid"] == uid else c for c in st["codes"]]
        if not any(c["uid"] == uid for c in st["codes"]):
            codes.append(theirs)  # you had removed it: it comes back as they have it
        if theirs["group"] not in {g["group"] for g in st["groups"]}:
            st["groups"].append({"group": theirs["group"], "group_name": str(clash.get("group_name") or "")})
        save(ws, name, {**st, "codes": codes}, why=why, label=f"keeping {who}'s version of a code")
    where, f = locate(ws, name)
    meta = _meta(f, name)
    (meta.get("clashes") or {}).pop(uid, None)
    if not meta.get("clashes"):
        meta.pop("clashes", None)
    vid = _keep_version(f, name, "settling a sync clash") if keep == "mine" else None
    try:
        _write(f, name, frameworks.decode((f / f"{name}.csv").read_bytes()), meta)
    except BaseException:
        _kept(f, name, vid, False)
        raise
    _kept(f, name, vid, True)
    if keep == "mine":
        with ws.connect() as cx:
            researchlog.record(cx, "codebook-changed", f"Kept your version of the code "
                                                       f"{researchlog.quoted(clash.get('code'), 60)} in the codebook "
                                                       f"{researchlog.quoted(meta.get('title') or name, 80)}; {who}'s "
                                                       "version was set aside.", "codebook", name,
                               meta.get("title") or name, version_id=vid, why=why)
    return load(ws, name)


def _profile_default() -> str:
    from .home import load_settings

    return load_settings().get("profile_framework") or "sdg"


def removed_codes(ws: Workspace, name: str) -> list[dict]:
    """Codes this project has labels of that the codebook no longer holds: their labels wait here. With the code's
    definition when the editor removed it."""
    try:
        fw = frameworks.get(name, ws)
    except ValueError:
        return []
    meta = fw.meta or {}
    gone = {(v or {}).get("code"): (uid, v) for uid, v in (meta.get("removed") or {}).items() if isinstance(v, dict)}
    out = []
    for code, n in ws.query("SELECT code, COUNT(*) FROM labels WHERE framework=? GROUP BY code ORDER BY code", (name,)):
        if code in fw.codes:
            continue
        uid, v = gone.get(code, (None, {}))
        out.append({"code": code, "labels": n, "uid": uid, "description": v.get("description") or "",
                    "removed_at": v.get("at"), "definition": v or None})
    return out


def stale(ws: Workspace, name: str) -> dict[str, dict]:
    """{code: {"since", "passages"}}: codes whose wording (definition, when to use it or not) changed after the AI
    labelled passages with it, and how many such passages."""
    try:
        fw = frameworks.get(name, ws)
    except ValueError:
        return {}
    meta = fw.meta or {}
    ids = meta.get("ids") or {}
    by_uid = {}
    for e in meta.get("events") or []:
        if isinstance(e, dict) and e.get("op") == "reword" and e.get("uid"):
            by_uid[e["uid"]] = max(by_uid.get(e["uid"], ""), str(e.get("at") or ""))
    out = {}
    for code in fw.codes:
        since = by_uid.get(ids.get(code) or default_uid(name, code))
        if not since:
            continue
        n = int(ws.scalar("SELECT COUNT(DISTINCT passage_id) FROM labels WHERE framework=? AND code=? AND "
                          "source='model' AND COALESCE(created_at, '') < ?", (name, code, since)) or 0)
        if n:
            out[code] = {"since": since, "passages": n}
    return out


def list_all(ws: Workspace) -> dict:
    """Every codebook this project can use, with where it is kept and how it is used here."""
    follow(ws)
    out = []
    labels = {r[0]: r[1] for r in ws.query("SELECT framework, COUNT(*) FROM labels GROUP BY framework")}
    checks = {r[0]: r[1] for r in ws.query("SELECT framework, COUNT(*) FROM hypotheses WHERE framework IS NOT NULL "
                                           "GROUP BY framework")}
    default = _profile_default()
    for fw in frameworks.available(ws).values():
        info = fw.info()
        try:
            where = locate(ws, fw.name)[0]
        except KeyError:
            where = fw.source
        info.update(where=where, editable=where not in ("bundled", "origin"), labels=labels.get(fw.name, 0),
                    checks=checks.get(fw.name, 0), editor=bool((fw.meta or {}).get("editor")),
                    profile_default=fw.name == default,
                    shadows_home=where == "project" and (_home_folder() / f"{fw.name}.csv").is_file())
        out.append(info)
    return {"codebooks": out, "problems": frameworks.problems(ws)}


# ---------------------------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------------------------
def _clean_text(v: Any, n: int = 2000) -> str:
    return " ".join(str(v or "").split())[:n]


def _clean_state(st: dict) -> dict:
    """The editor's state as sent, cleaned and checked. Raises ValueError naming the problem."""
    codes = []
    names: dict[str, str] = {}
    groups = []
    gseen = set()
    for g in st.get("groups") or []:
        if not isinstance(g, dict):
            continue
        key = _clean_text(g.get("group"), 60)
        if key in gseen:
            continue
        gseen.add(key)
        groups.append({"group": key, "group_name": _clean_text(g.get("group_name"), 120)})
    for i, c in enumerate(st.get("codes") or [], 1):
        if not isinstance(c, dict):
            continue
        code = _clean_text(c.get("code"), 200)
        desc = _clean_text(c.get("description"), 4000)
        if not code:
            raise ValueError(f"Code {i} has no name.")
        if len(code) > 40:
            raise ValueError(f"The code name {code[:40]!r}… is longer than 40 characters: keep the name short and say "
                             "more in its definition.")
        if not desc:
            raise ValueError(f"The code {code!r} has no definition. Say in a sentence what it is about.")
        low = code.lower()
        if low in names:
            raise ValueError(f"Two codes are called {code!r}: give each its own name.")
        names[low] = code
        uid = str(c.get("uid") or "")
        group = _clean_text(c.get("group"), 60)
        if group not in gseen:
            gseen.add(group)
            groups.append({"group": group, "group_name": ""})
        kws = []
        for k in (c.get("keywords") or []):
            k = _clean_text(k, 80).replace(";", ",")
            if k and k not in kws:
                kws.append(k)
        exs = []
        for e in (c.get("examples") or [])[:MAX_EXAMPLES]:
            e = e if isinstance(e, dict) else {"quote": e}
            q = _clean_text(e.get("quote"), 600)
            if q and q not in [x["quote"] for x in exs]:
                exs.append({k: v for k, v in e.items() if k in ("doc_id", "title", "page", "start", "end", "project")}
                           | {"quote": q})
        codes.append({"uid": uid if _UID.fullmatch(uid) else "", "code": code, "description": desc, "group": group,
                      "include": _clean_text(c.get("include"), 2000), "exclude": _clean_text(c.get("exclude"), 2000),
                      "keywords": kws[:40], "examples": exs, "split_from": str(c.get("split_from") or "") or None})
    if len(codes) > MAX_CODES:
        raise ValueError(f"A codebook can hold at most {MAX_CODES:,} codes.")
    used = {c["group"] for c in codes}
    groups = [g for g in groups if g["group"] in used or g["group_name"] or g["group"]]
    return {"title": _clean_text(st.get("title"), 200), "label": _clean_text(st.get("label"), 40) or "code",
            "directional": bool(st.get("directional")), "groups": groups, "codes": codes}


def _csv_text(codes: list[dict], groups: list[dict]) -> str:
    gname = {g["group"]: g["group_name"] for g in groups}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    for c in codes:
        # 0.17.2: through csv_cell like every other CSV ENLENS writes; frameworks.parse_csv takes the apostrophe off
        w.writerow([csv_cell(x) for x in
                    (c["code"], c["description"], c["group"], gname.get(c["group"], ""), c["include"], c["exclude"],
                     "; ".join(c["keywords"]), "\n".join(e["quote"] for e in c["examples"]))])
    return buf.getvalue()


def _name_ok(name: str) -> str:
    """A codebook's name, checked before it reaches a path (it comes from a URL): else KeyError."""
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise KeyError(name)
    return name


_BUSY = ("The codebook's file is open in another program (a spreadsheet?), or cannot be written: close it and save "
         "again. Nothing was changed.")


def _write(f: Path, name: str, csv_text: str, meta: dict) -> None:
    """Both files of a codebook, or neither: when the second cannot be put in place (Windows refuses while a file is
    open in a spreadsheet), the first is put back as it was."""
    _name_ok(name)
    f.mkdir(parents=True, exist_ok=True)
    csv_p, side_p = f / f"{name}.csv", f / f"{name}.json"
    tmp = f / f".{name}.csv.part"
    side = f / f".{name}.json.part"
    old_csv = csv_p.read_bytes() if csv_p.is_file() else None
    try:
        tmp.write_text(csv_text, encoding="utf-8")
        side.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(csv_p)
    except OSError:
        tmp.unlink(missing_ok=True)
        side.unlink(missing_ok=True)
        raise ValueError(_BUSY) from None
    try:
        side.replace(side_p)
    except OSError:
        try:
            if old_csv is None:
                csv_p.unlink(missing_ok=True)
            else:
                csv_p.write_bytes(old_csv)
        finally:
            side.unlink(missing_ok=True)
        raise ValueError(_BUSY) from None


def _version_dir(f: Path, name: str) -> Path:
    return f / "history" / name


def _keep_version(f: Path, name: str, label: str) -> str | None:
    """The codebook's files as they are now, as a version (before a change). Returns its id. The oldest beyond KEEP
    are not pruned here: only once the change is written (`_kept`), so a change that fails loses no real version."""
    csv_p = f / f"{name}.csv"
    if not csv_p.is_file():
        return None
    meta_p = f / f"{name}.json"
    vid = "c" + uuid.uuid4().hex[:16]
    d = _version_dir(f, name)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{vid}.json").write_text(json.dumps({
        "version_id": vid, "at": now(), "ns": time.time_ns(), "person_id": _me(), "label": label[:200],
        "csv": frameworks.decode(csv_p.read_bytes()),
        "meta": json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.is_file() else {}},
        ensure_ascii=False), encoding="utf-8")
    return vid


def _kept(f: Path, name: str, vid: str | None, written: bool) -> None:
    """After a change: written, the oldest versions beyond KEEP go; not written (the file is open in a spreadsheet),
    the version kept for it goes, so the history shows no change that never happened."""
    d = _version_dir(f, name)
    if not written:
        if vid:
            (d / f"{vid}.json").unlink(missing_ok=True)
        return
    for p in sorted(d.glob("c*.json"), key=_order)[:-KEEP] if d.is_dir() else []:
        p.unlink(missing_ok=True)


def _order(p: Path) -> tuple:
    """A version file's place in time: when it was made, to the nanosecond (two saves in one second keep their
    order), else the file's own time."""
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return (str(d.get("at") or ""), int(d.get("ns") or 0), p.stat().st_mtime_ns)
    except (OSError, ValueError):
        return ("", 0, 0)


def _version_files(ws: Workspace, name: str) -> list[Path]:
    _name_ok(name)
    out = []
    for where in ("project", "home"):
        d = _version_dir(folder(ws, where), name)
        if d.is_dir():
            out += [p for p in d.glob("c*.json") if _VID.fullmatch(p.stem)]
    return out


def versions_present(ws: Workspace, ids: list[str]) -> set[str]:
    want = {i for i in ids if _VID.fullmatch(i or "")}
    if not want:
        return set()
    found = set()
    for where in ("project", "home"):
        hist = folder(ws, where) / "history"
        if hist.is_dir():
            for p in hist.glob("*/c*.json"):
                if p.stem in want:
                    found.add(p.stem)
    return found


def _new_uid() -> str:
    return "k" + uuid.uuid4().hex[:10]


def save(ws: Workspace, name: str, state: dict, merges: list[dict] | None = None, why: str | None = None,
         label: str = "changing the codebook", restoring: str | None = None) -> dict:
    """Write the editor's state of a codebook (see the module's notes). `merges`: [{"from": uid, "into": uid}], codes
    merged into others (their labels go with them). Returns {"changes": [...], "version_id", "codebook": load()}."""
    from . import researchlog

    where, f = locate(ws, name)
    if where == "bundled":
        raise ValueError("The SDG codebooks ship with the app: make a copy to change one.")
    new = _clean_state(state)
    cur = state_of(ws, name)
    fw = frameworks.get(name, ws)
    meta = json.loads(json.dumps(fw.meta or {}))
    at = now()
    cur_by_uid = {c["uid"]: c for c in cur["codes"]}
    merges = [m for m in (merges or []) if isinstance(m, dict) and m.get("from") in cur_by_uid]
    merged_into = {m["from"]: str(m.get("into") or "") for m in merges}
    removed_meta = {k: v for k, v in (meta.get("removed") or {}).items() if isinstance(v, dict)}
    events = [e for e in (meta.get("events") or []) if isinstance(e, dict)]
    new_events, changes = [], []
    orphan_codes = {r[0] for r in ws.query("SELECT DISTINCT code FROM labels WHERE framework=?", (name,))} - set(fw.codes)

    for c in new["codes"]:
        if c["uid"] and c["uid"] not in cur_by_uid and c["uid"] not in removed_meta and not restoring:
            c["uid"] = ""  # an id the codebook never had: a new code
    new_uids = {c["uid"] for c in new["codes"] if c["uid"]}
    cur_name = {u: c["code"] for u, c in cur_by_uid.items()}
    new_name = {c["uid"]: c["code"] for c in new["codes"] if c["uid"]}
    # merges: the code it goes into must stay
    for src, dst in merged_into.items():
        if src in new_uids:
            raise ValueError(f"{cur_name[src]!r} is merged and kept at once: take one of the two back.")
        if dst not in new_uids:
            raise ValueError(f"{cur_name[src]!r} is merged into a code that is not in the codebook any more.")
    # a code may not take the name of a code removed or merged away in this same change: their labels would mix
    freed = {cur_name[u] for u in cur_by_uid if u not in new_uids}
    for c in new["codes"]:
        if c["code"] in freed and cur_name.get(c["uid"]) != c["code"]:
            raise ValueError(f"{c['code']!r} is the name of a code you remove or merge in this same change, and its "
                             "labels would mix with this code's. Choose another name.")
    # a code may not take the name of codes whose labels wait under Removed codes (unless it is that code coming back)
    for c in new["codes"]:
        if c["code"] in orphan_codes and not (c["uid"] and removed_meta.get(c["uid"], {}).get("code") == c["code"]):
            raise ValueError(f"{c['code']!r} is the name of a removed code whose labels wait under Removed codes. "
                             "Bring that code back from there, or choose another name.")
    # what changed, code by code
    for u, old in cur_by_uid.items():
        if u in new_uids:
            nc = next(c for c in new["codes"] if c["uid"] == u)
            if nc["code"] != old["code"]:
                new_events.append({"op": "rename", "from": old["code"], "to": nc["code"], "uid": u})
                changes.append(f"renamed {researchlog.quoted(old['code'], 60)} to {researchlog.quoted(nc['code'], 60)}")
            if (nc["description"], nc["include"], nc["exclude"]) != (old["description"], old["include"], old["exclude"]):
                new_events.append({"op": "reword", "uid": u, "code": nc["code"]})
                changes.append(f"changed the wording of {researchlog.quoted(nc['code'], 60)}")
            if nc["keywords"] != old["keywords"]:
                changes.append(f"changed the words {researchlog.quoted(nc['code'], 60)} is matched by")
            if nc["group"] != old["group"]:
                changes.append(f"moved {researchlog.quoted(nc['code'], 60)} to another group")
            if [e["quote"] for e in nc["examples"]] != [e["quote"] for e in old["examples"]]:
                changes.append(f"changed the examples of {researchlog.quoted(nc['code'], 60)}")
        elif u in merged_into:
            into = new_name[merged_into[u]]
            new_events.append({"op": "merge", "from": old["code"], "to": into, "uid": u, "into_uid": merged_into[u]})
            changes.append(f"merged {researchlog.quoted(old['code'], 60)} into {researchlog.quoted(into, 60)}")
            removed_meta[u] = {**{k: old[k] for k in ("code", "description", "group", "include", "exclude",
                                                       "keywords")},
                               "examples": [e["quote"] for e in old["examples"]], "at": at, "merged_into": into,
                               "merged_into_uid": merged_into[u]}
        else:
            changes.append(f"removed {researchlog.quoted(old['code'], 60)} (its labels wait under Removed codes)")
            removed_meta[u] = {**{k: old[k] for k in ("code", "description", "group", "include", "exclude",
                                                       "keywords")},
                               "examples": [e["quote"] for e in old["examples"]], "at": at}
    for c in new["codes"]:
        if c["uid"] and c["uid"] in cur_by_uid:
            continue
        if c["uid"] and c["uid"] in removed_meta:
            gone = removed_meta.pop(c["uid"])
            if gone.get("merged_into"):  # its labels went to another code: they come back with it
                into = next((e for e in reversed(events) if e.get("op") == "merge" and e.get("uid") == c["uid"]), None)
                if into:
                    now_name = cur_name.get(into.get("into_uid"), into.get("to"))
                    new_events.append({"op": "unmerge", "from": now_name, "to": c["code"], "was": into.get("from"),
                                       "uid": c["uid"]})
            elif gone.get("code") and gone["code"] != c["code"]:  # it comes back under another name: so do its labels
                new_events.append({"op": "rename", "from": gone["code"], "to": c["code"], "uid": c["uid"]})
            changes.append(f"brought {researchlog.quoted(c['code'], 60)} back")
            continue
        c["uid"] = _new_uid()
        split = c.get("split_from")
        if split and split in cur_by_uid:
            changes.append(f"split {researchlog.quoted(cur_name[split], 60)}: added {researchlog.quoted(c['code'], 60)}")
        else:
            changes.append(f"added {researchlog.quoted(c['code'], 60)}")
    if new["title"] and new["title"] != cur["title"]:
        changes.append(f"renamed the codebook to {researchlog.quoted(new['title'], 80)}")
    if new["label"] != cur["label"]:
        changes.append(f"called a code “{new['label']}”")
    if new["directional"] != cur["directional"]:
        changes.append("its codes are aims a text helps or hinders" if new["directional"] else
                       "its codes are no longer aims a text helps or hinders")
    if [c["uid"] for c in new["codes"] if c["uid"] in cur_by_uid] != [c["uid"] for c in cur["codes"]
                                                                     if c["uid"] in new_uids] and not changes:
        changes.append("changed the order of the codes")
    if [g["group_name"] for g in new["groups"]] != [g["group_name"] for g in cur["groups"]] and not changes:
        changes.append("changed the groups")
    if not changes:
        return {"changes": [], "version_id": None, "codebook": load(ws, name)}
    # the order labels follow them in: codes coming back from a merge first (by the names they have now), then
    # renames (in two steps through a name of their own when names are swapped), then merges
    renames = [e for e in new_events if e["op"] == "rename"]
    if any(e["to"] in {r["from"] for r in renames} for e in renames):
        renames = ([{**e, "to": f"~{e['uid']}"} for e in renames] + [{**e, "from": f"~{e['uid']}"} for e in renames])
    new_events = ([e for e in new_events if e["op"] == "unmerge"] + renames
                  + [e for e in new_events if e["op"] == "merge"] + [e for e in new_events if e["op"] == "reword"])
    for i, e in enumerate(new_events):
        e.update(id=uuid.uuid4().hex[:12], at=at, seq=i)
    # the examples: each must be words of a document (here, or in the project it was found in)
    places = {}
    where_found = find_examples(ws, [e["quote"] for c in new["codes"] for e in c["examples"] if not e.get("doc_id")])
    for c in new["codes"]:
        kept = []
        for e in c["examples"]:
            if not e.get("doc_id"):
                got = where_found.get(" ".join((e["quote"] or "").split()))
                if got:
                    e.update(got)
            kept.append({k: e.get(k) for k in ("quote", "doc_id", "title", "page", "start", "end", "project")
                         if e.get(k) is not None})
        if kept:
            places[c["uid"]] = kept
    meta.update({"title": new["title"] or cur["title"], "label": new["label"], "editor": True, "ordered": True,
                 "ids": {c["code"]: c["uid"] for c in new["codes"]}, "groups": new["groups"], "places": places,
                 "removed": removed_meta, "events": events + new_events})
    if new["directional"]:
        meta["directional"] = True
    else:
        meta.pop("directional", None)
    vid = _keep_version(f, name, label)
    try:
        _write(f, name, _csv_text(new["codes"], new["groups"]), meta)
    except BaseException:
        _kept(f, name, vid, False)
        raise
    _kept(f, name, vid, True)
    follow(ws, name)
    text = (f"Restored the codebook {researchlog.quoted(meta['title'], 80)} to its version of {restoring}: "
            if restoring else f"Changed the codebook {researchlog.quoted(meta['title'], 80)}: ")
    with ws.connect() as cx:
        researchlog.record(cx, "restored" if restoring else "codebook-changed",
                           text + "; ".join(changes[:12]) + (f"; and {len(changes) - 12} more" if len(changes) > 12
                                                             else "") + ".",
                           "codebook", name, meta["title"], version_id=vid, why=why,
                           data={"changes": changes, "where": where})
    return {"changes": changes, "version_id": vid, "codebook": load(ws, name)}


# ---------------------------------------------------------------------------------------------
# labels follow renames and merges
# ---------------------------------------------------------------------------------------------
def follow(ws: Workspace, name: str | None = None) -> int:
    """Move this project's labels (and checks tagged with a code) as the codebooks' renames and merges say, once per
    change, in the order the codebook lists them (its saves' order). A colleague's labels that come in follow the
    changes their copy had not followed (`follow_merged`, from sync.py). Returns how many labels moved."""
    from .profile import label_id

    fws = frameworks.available(ws)
    moved = 0
    for fw in ([fws[name]] if name and name in fws else [] if name else list(fws.values())):
        events = _events(fw.meta or {})
        if not events:
            continue
        key = f"codebook_followed:{fw.name}"
        if not set(e["id"] for e in events) - set(ws.meta(key) or []):
            continue
        ok, _skipped = checked_events(events)  # roles (H8): an event that does not fit the list moves nothing
        with ws.connect() as cx:  # read again inside the write lock: two requests at once apply a change once
            done = set(ws.meta(key) or [])
            for e in ok:
                if e["id"] not in done:
                    moved += _follow_one(cx, fw.name, e, label_id)
            ws.set_meta(key, sorted({e["id"] for e in events}), cx)
    return moved


def _events(meta: dict) -> list[dict]:
    """A codebook's renames, merges and unmerges, in its order."""
    return [e for e in (meta.get("events") or [])
            if isinstance(e, dict) and e.get("op") in ("rename", "merge", "unmerge") and e.get("id")]


def checked_events(events: list[dict]) -> tuple[list[dict], list[str]]:
    """Roles (H8, DESIGN-roles §4.9): the events of a codebook's list that fit it, and the ids of those that do not.
    A rename and a merge need two names. An unmerge needs an earlier merge of the list of the code it gives back
    (`was`), into the code it takes the labels from (`from`, as that code is named by then: renames between them are
    followed), and it gives the labels back to that code (`to == was`), or, made by the app (both events name the
    code's id), to the name the code came back under. A list written by hand otherwise moves labels anywhere."""
    ok, skipped = [], []
    merges: list[dict] = []   # {"was", "into" (its name now), "uid"} of the merges so far
    for e in events:
        src, dst = str(e.get("from") or ""), str(e.get("to") or "")
        if not src or not dst or src == dst:
            skipped.append(e["id"])
            continue
        if e["op"] == "unmerge":
            was = str(e.get("was") or "")
            fits = [m for m in merges if m["was"] == was and m["into"] == src and
                    (dst == was or (e.get("uid") and m["uid"] == e.get("uid")))]
            if not fits:
                skipped.append(e["id"])
                continue
            merges.remove(fits[-1])
        elif e["op"] == "rename":
            for m in merges:
                if m["into"] == src:
                    m["into"] = dst
        else:
            merges.append({"was": src, "into": dst, "uid": e.get("uid")})
        ok.append(e)
    return ok, skipped


def _follow_one(cx, fw: str, e: dict, label_id: Callable, only: set | None = None, hyps: set | None = None) -> int:
    """One change, followed by the labels made up to it. `only`: these labels alone (their ids, kept up to date as
    they change), and `hyps`: the checks whose tags follow it (None: every label and check)."""
    at = str(e.get("at") or "")
    src, dst = str(e.get("from") or ""), str(e.get("to") or "")
    if not src or not dst or src == dst:
        return 0
    if e["op"] == "unmerge":
        rows = cx.execute("SELECT label_id, passage_id, source FROM labels WHERE framework=? AND code=? AND "
                          "merged_from=? AND COALESCE(created_at, '') <= ?", (fw, src, e.get("was") or "", at)).fetchall()
    else:
        # labels made up to the change (the same second included: a label made after it has the new name)
        rows = cx.execute("SELECT label_id, passage_id, source FROM labels WHERE framework=? AND code=? AND "
                          "COALESCE(created_at, '') <= ?", (fw, src, at)).fetchall()
    if only is not None:
        rows = [r for r in rows if r[0] in only]
    n = 0
    for old_id, pid, source in rows:
        new_id = label_id(fw, pid, dst, source or "")
        if only is not None and new_id != old_id:
            only.discard(old_id)
            only.add(new_id)
        if new_id != old_id and cx.execute("SELECT 1 FROM labels WHERE label_id=?", (new_id,)).fetchone():
            if e["op"] == "merge":
                # the passage has the code it goes into already: this label stays as it is, marked, and waits under
                # Removed codes (so restoring the codebook from before the merge gives it back)
                cx.execute("UPDATE labels SET merged_from=COALESCE(merged_from, ?) WHERE label_id=?", (src, old_id))
            elif e["op"] == "rename":  # a label there under the new name already: never lost, left as it is
                pass
            # an unmerge, and the label is there under the name it goes back to already: roles (H8) this label stays
            # too, marked as merged (following never deletes a label: a list of changes from someone else's file
            # once deleted labels this way)
            n += 1
            continue
        merged = (src if e["op"] == "merge" else None)
        cx.execute("UPDATE labels SET label_id=?, code=?, merged_from=CASE WHEN ? = 'merge' THEN "
                   "COALESCE(merged_from, ?) WHEN ? = 'unmerge' THEN NULL ELSE merged_from END WHERE label_id=?",
                   (new_id, dst, e["op"], merged, e["op"], old_id))
        if new_id != old_id:
            cx.execute("UPDATE reviews SET item_id=? WHERE item_kind='label' AND item_id=?", (new_id, old_id))
        n += 1
    if e["op"] == "unmerge":  # the labels that stayed (the passage had both codes) count again as they are
        for (lid,) in cx.execute("SELECT label_id FROM labels WHERE framework=? AND code=? AND merged_from=?",
                                 (fw, e.get("was") or "", e.get("was") or "")).fetchall():
            if only is None or lid in only:
                cx.execute("UPDATE labels SET merged_from=NULL WHERE label_id=?", (lid,))
    if e["op"] in ("rename", "merge") and (hyps is None or hyps):  # checks tagged with the code
        some = "" if hyps is None else f" AND hyp_id IN ({','.join('?' * len(hyps))})"
        ids = [] if hyps is None else sorted(hyps)
        cx.execute(f"UPDATE hypotheses SET code=? WHERE framework=? AND code=? AND COALESCE(created_at, '') <= ?{some}",
                   (dst, fw, src, at, *ids))
        cx.execute(f"UPDATE user_claims SET target=? WHERE framework=? AND target=? AND COALESCE(created_at, '') <= ?"
                   f"{some}", (dst, fw, src, at, *ids))
    return n


def follow_merged(cx, ws: Workspace, name: str, meta: dict, theirs_done: set, incoming: set, hyps_before: set,
                  sender: str | None = None, at_once: bool = True, report: dict | None = None) -> None:
    """0.16 (sync.py): a colleague's work came in. This copy's labels follow the codebook's changes this copy had not
    followed; the labels that came in follow those the colleague's copy had not followed (each kind of label once, so
    a swap of two names or a name used again is not undone). Then every change counts as followed here.

    Roles (H8, DESIGN-roles §4.9): only the events that fit the list are followed (`checked_events`; the others are
    counted in `report["skipped_events"]`). This copy's own labels follow at once only when `at_once` (the sender
    made the codebook and this person did not); otherwise the events wait for this person's word (`offers`,
    `answer_offer`), from `sender`, when they would move a label of theirs."""
    from .profile import label_id

    events = _events(meta)
    if not events:
        return
    ok, skipped = checked_events(events)
    key = f"codebook_followed:{name}"
    row = cx.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    mine_done = set(json.loads(row[0]) if row else [])
    if report is not None:
        report["skipped_events"] = report.get("skipped_events", 0) + len([i for i in skipped if i not in mine_done])
    incoming = set(incoming)
    mine = {r[0] for r in cx.execute("SELECT label_id FROM labels WHERE framework=?", (name,))} - incoming
    waiting = []
    for e in ok:
        if e["id"] not in mine_done:
            if at_once:
                _follow_one(cx, name, e, label_id, only=mine, hyps=hyps_before)
            else:
                waiting.append(e)
        if e["id"] not in theirs_done and incoming:
            _follow_one(cx, name, e, label_id, only=incoming, hyps=set())
    if waiting and _moves_any(cx, name, waiting, mine):
        okey = f"codebook_offers:{name}"
        got = cx.execute("SELECT value FROM meta WHERE key=?", (okey,)).fetchone()
        offer = json.loads(got[0]) if got else {}
        ids = list(offer.get("events") or []) + [e["id"] for e in waiting if e["id"] not in (offer.get("events") or [])]
        cx.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                   (okey, json.dumps({"events": ids, "from": sender, "at": now()})))
        if report is not None:
            report.setdefault("offered", []).append(name)
    cx.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(sorted(e["id"] for e in events))))


def _moves_any(cx, name: str, events: list[dict], only: set | None = None) -> int:
    """How many labels (of `only`, when given) these events would take from a code: the labels of a code some event
    takes labels from (an estimate: the time of each event is not looked at)."""
    froms = {str(e.get("from") or "") for e in events}
    if not froms:
        return 0
    q = ",".join("?" * len(froms))
    ids = {r[0] for r in cx.execute(f"SELECT label_id FROM labels WHERE framework=? AND code IN ({q})", (name, *froms))}
    return len(ids & only if only is not None else ids)


# ---------------------------------------------------------------------------------------------
# making, moving, copying and removing codebooks
# ---------------------------------------------------------------------------------------------
def _free_name(ws: Workspace, name: str) -> str:
    n = (name or "").strip().lower().replace(" ", "_")
    n = re.sub(r"[^a-z0-9_-]", "", n)[:40]
    if not NAME_RE.match(n) or n in BUNDLED:
        raise ValueError("Give the codebook a short name: letters, digits, - or _ (and not 'sdg' or 'sdg_goals').")
    if n in frameworks.available(ws) or (_home_folder() / f"{n}.csv").exists():
        raise ValueError(f"A codebook called {n!r} exists already: choose another name.")
    return n


def create(ws: Workspace, name: str, title: str = "", where: str = "project", start: str = "fresh",
           source: dict | None = None, label: str = "code") -> dict:
    """A new codebook. `start`: "fresh" (empty), "themes" (`source`: {"codes": [...]} drafts from `from_themes`, the
    ones a person kept), "theory" (0.18.1: `source`: {"codes": [...], "doc_id"} drafts from `theorycodes.candidates`,
    the ones a person kept, examples from theory documents dropped), "copy" (`source`: {"of": a codebook's name}), "csv" (`source`: {"csv": text})."""
    from . import researchlog

    if where not in ("project", "home"):
        raise ValueError("A codebook is kept with this project or with all projects.")
    n = _free_name(ws, name)
    source = source or {}
    state: dict = {"title": title or n.replace("_", " ").capitalize(), "label": label or "code", "directional": False,
                   "groups": [], "codes": []}
    how = "an empty codebook"
    if start == "copy":
        of = frameworks.get(str(source.get("of") or ""), ws)
        st = _state(of.name, of.codes, json.loads(json.dumps(of.meta or {})), of.title, of.label, of.directional)
        state.update(groups=st["groups"], codes=[{**c, "uid": ""} for c in st["codes"]], label=of.label,
                     directional=of.directional, title=title or f"{of.title} (copy)")
        how = f"a copy of {researchlog.quoted(of.title, 80)}"
    elif start == "csv":
        codes = frameworks.parse_csv(frameworks.decode(str(source.get("csv") or "").encode("utf-8")), extra=True)
        st = _state(n, codes, {}, state["title"], state["label"], False)
        state.update(groups=st["groups"], codes=[{**c, "uid": ""} for c in st["codes"]])
        how = "a CSV file"
    elif start == "themes":
        picked = [c for c in (source.get("codes") or []) if isinstance(c, dict)]
        if not picked:
            raise ValueError("Tick at least one theme to start from.")
        state["codes"] = picked
        how = f"{len(picked)} theme{'s' if len(picked) != 1 else ''}"
    elif start == "theory":
        # 0.18.1 (K2 part 2, theorycodes.py): the concepts of a theory document a person ticked, each with its
        # definition quoted from the theory; examples only from the evidence documents
        from . import theorycodes

        picked = theorycodes.keep_evidence_examples(ws, [c for c in (source.get("codes") or []) if isinstance(c, dict)])
        if not picked:
            raise ValueError("Tick at least one concept to start from.")
        state["codes"] = picked
        doc = ws.query("SELECT title FROM documents WHERE doc_id=?", (str(source.get("doc_id") or ""),))
        how = (f"{len(picked)} concept{'s' if len(picked) != 1 else ''} of the theory document "
               f"{researchlog.quoted(doc[0]['title'], 80)}" if doc else
               f"{len(picked)} concept{'s' if len(picked) != 1 else ''} of a theory document")
    elif start != "fresh":
        raise ValueError("Start fresh, from themes, from a theory document, from a copy or from a CSV file.")
    clean = _clean_state(state)
    for c in clean["codes"]:
        c["uid"] = _new_uid()
    f = folder(ws, where)
    meta = {"title": clean["title"], "label": clean["label"], "editor": True, "ordered": True,
            "ids": {c["code"]: c["uid"] for c in clean["codes"]}, "groups": clean["groups"], "events": [],
            "removed": {}, "places": {c["uid"]: [{k: v for k, v in e.items() if v is not None} for e in c["examples"]]
                                      for c in clean["codes"] if c["examples"]}}
    if clean["directional"]:
        meta["directional"] = True
    _write(f, n, _csv_text(clean["codes"], clean["groups"]), meta)
    with ws.connect() as cx:
        researchlog.record(cx, "codebook-added", f"Made the codebook {researchlog.quoted(clean['title'], 80)} from "
                                                 f"{how}, kept {'with all projects' if where == 'home' else 'in this project'}"
                                                 f" ({len(clean['codes'])} code{'s' if len(clean['codes']) != 1 else ''}).",
                           "codebook", n, clean["title"], data={"where": where, "start": start})
    return load(ws, n)


def remove(ws: Workspace, name: str, why: str | None = None) -> None:
    """Remove a codebook's files (its history stays beside them, so it can be made again from a version). Labels made
    with it stay in the projects: they are results."""
    from . import researchlog

    where, f = locate(ws, name)
    if where == "bundled":
        raise ValueError("The SDG codebooks ship with the app and cannot be removed.")
    title = frameworks.get(name, ws).title
    vid = _keep_version(f, name, "removing the codebook")
    try:
        (f / f"{name}.csv").unlink(missing_ok=True)
    except OSError:   # open in a spreadsheet (Windows): nothing was removed
        _kept(f, name, vid, False)
        raise ValueError(_BUSY) from None
    _kept(f, name, vid, True)
    (f / f"{name}.json").unlink(missing_ok=True)
    with ws.connect() as cx:
        researchlog.record(cx, "codebook-removed", f"Removed the codebook {researchlog.quoted(title, 80)} "
                                                   f"({'from all projects' if where == 'home' else 'from this project'}).",
                           "codebook", name, title, why=why, version_id=vid, data={"where": where})


def move(ws: Workspace, name: str, to: str) -> dict:
    """Keep a codebook with all projects (`to` "home") or with this project only ("project"), with its history."""
    from . import researchlog

    where, f = locate(ws, name)
    if where == "bundled":
        raise ValueError("The SDG codebooks ship with the app.")
    if to not in ("project", "home") or to == where:
        raise ValueError("It is kept there already.")
    dest = folder(ws, to)
    if (dest / f"{name}.csv").exists():
        raise ValueError("A codebook of that name is kept there already.")
    dest.mkdir(parents=True, exist_ok=True)
    for ext in ("csv", "json"):
        if (f / f"{name}.{ext}").is_file():
            shutil.move(str(f / f"{name}.{ext}"), str(dest / f"{name}.{ext}"))
    hist = _version_dir(f, name)
    if hist.is_dir():
        _version_dir(dest, name).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(hist), str(_version_dir(dest, name)))
    title = frameworks.get(name, ws).title
    with ws.connect() as cx:
        researchlog.record(cx, "codebook-moved", f"The codebook {researchlog.quoted(title, 80)} is now kept "
                                                 f"{'with all projects' if to == 'home' else 'in this project only'}.",
                           "codebook", name, title, data={"from": where, "to": to})
    return load(ws, name)


def copy_here(ws: Workspace, name: str) -> dict:
    """This project's own copy of a codebook kept with all projects, under the same name (it comes first here, so
    the labels made with it stay with it), to change for this project alone."""
    from . import researchlog

    where, f = locate(ws, name)
    if where != "home":
        raise ValueError("Only a codebook kept with all projects can be copied into this project.")
    dest = folder(ws, "project")
    dest.mkdir(parents=True, exist_ok=True)
    for ext in ("csv", "json"):
        if (f / f"{name}.{ext}").is_file():
            shutil.copy2(f / f"{name}.{ext}", dest / f"{name}.{ext}")
    title = frameworks.get(name, ws).title
    with ws.connect() as cx:
        researchlog.record(cx, "codebook-copied", f"Took this project's own copy of the codebook "
                                                  f"{researchlog.quoted(title, 80)}, to change it here only.",
                           "codebook", name, title)
    return load(ws, name)


def csv_of(ws: Workspace, name: str) -> tuple[str, bytes]:
    where, f = locate(ws, name)
    if where == "bundled":
        fw = frameworks.get(name, ws)
        st = _state(name, fw.codes, {}, fw.title, fw.label, fw.directional)
        return f"{name}.csv", _csv_text(_clean_state(st)["codes"], st["groups"]).encode("utf-8-sig")
    return f"{name}.csv", _protected_csv(frameworks.decode((f / f"{name}.csv").read_bytes())).encode("utf-8")


def _protected_csv(text: str) -> str:
    """A codebook's file as an export a spreadsheet will not run: every cell through `csv_cell`. The file may have been
    written before 0.17.2 or be a CSV someone imported as it was, so each cell is first taken back to what it says
    (`csv_uncell`): one that is protected already stays as it is, not protected twice. The columns, their order and
    the file's separator stay."""
    text = text.lstrip("\ufeff")
    delim = frameworks._delimiter(text)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delim, lineterminator="\n")
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        w.writerow([csv_cell(csv_uncell(x)) for x in row])
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------
# examples, themes, trying a codebook
# ---------------------------------------------------------------------------------------------
def find_example(ws: Workspace, quote: str, doc_id: str | None = None) -> dict | None:
    """Where an example quote is in this project's documents (the quote check): {doc_id, title, page, start, end,
    project}, or None. The quote must be the documents' own words (as every quote is found)."""
    return find_examples(ws, [quote], doc_id).get(" ".join((quote or "").split()))


_LOOKED: "OrderedDict[tuple, dict | None]" = OrderedDict()   # quotes looked for, by project, documents and quote
_LOOKED_MAX = 2000
_LOOKED_LOCK = threading.Lock()


def _needle(q: str) -> tuple[str, bool]:
    """What a passage must hold for `find_quote` to find the quote in it, compared with spaces left out (its spacing
    pass joins words split by spaces): the longest run of letters and digits of the quote's normalised words that are
    plain ASCII (True), which every passage that holds the quote holds in `fast_normalise`'s folding too; for a quote
    without such a run, all of its folded words (False: a capital sigma and Hangul compose differently there, so this
    one is a best effort)."""
    flat = "".join(normalise(q).split())
    runs = re.findall(r"[a-z0-9]+", flat)
    best = max(runs, key=len, default="")
    if len(best) >= 3:
        return best, True
    return "".join(fast_normalise(q).split()).replace("ς", "σ"), False


def find_examples(ws: Workspace, quotes: list[str], doc_id: str | None = None) -> dict[str, dict | None]:
    """Where each example quote is (`find_example`), with one reading of the passages for them all. Each passage's
    text is folded as the quote check folds it (`fast_normalise`, spaces left out) and `find_quote` decides only where
    it holds the quote's words: SQLite's lower() and LIKE fold only ASCII letters, so a quote with a capital accented
    letter, or a ligature in the passage, was never found. A quote looked for against the same documents (the
    project's corpus version) is not looked for again: a codebook's every save looked again for every example
    without a place."""
    from .textutil import find_quote

    out: dict[str, dict | None] = {}
    todo: dict[str, tuple[str, bool]] = {}
    base = (str(ws.db_path.resolve()), ws.corpus_version(), doc_id)
    for quote in quotes:
        q = " ".join((quote or "").split())
        if q in out or q in todo:
            continue
        if len(q) < 8:
            out[q] = None
            continue
        with _LOOKED_LOCK:
            seen = base + (q,) in _LOOKED
            if seen:
                _LOOKED.move_to_end(base + (q,))
                out[q] = _LOOKED[base + (q,)]
        if not seen:
            todo[q] = _needle(q)
    if todo:
        sql = ("SELECT passage_id, doc_id, page, start, text FROM passages " +
               ("WHERE doc_id=? ORDER BY seq" if doc_id else "ORDER BY rowid"))
        found: dict[str, dict] = {}
        cur = ws._conn().execute(sql, (doc_id,) if doc_id else ())
        while len(found) < len(todo):
            rows = cur.fetchmany(500)
            if not rows:
                break
            for r in rows:
                text = r["text"] or ""
                flat = None
                for q, (needle, ascii_) in todo.items():
                    if q in found:
                        continue
                    if flat is None:
                        flat = "".join(fast_normalise(text).split())
                        folded = flat.replace("ς", "σ")
                    if needle not in (flat if ascii_ else folded):
                        continue
                    hit = find_quote(text, q)
                    if hit:
                        title = ws.scalar("SELECT title FROM documents WHERE doc_id=?", (r["doc_id"],))
                        found[q] = {"doc_id": r["doc_id"], "title": title, "page": r["page"],
                                    "start": r["start"] + hit[0], "end": r["start"] + hit[1],
                                    "project": ws.project_uid(), "quote": text[hit[0]:hit[1]]}
        cur.close()
        with _LOOKED_LOCK:
            for q in todo:
                out[q] = found.get(q)
                _LOOKED[base + (q,)] = out[q]
            while len(_LOOKED) > _LOOKED_MAX:
                _LOOKED.popitem(last=False)
    return {q: (dict(v) if v else None) for q, v in out.items()}


def _sentence_at(text: str, n: int = 260) -> tuple[str, int, int]:
    """A whole sentence of a passage to show as an example (its first of a fair length): (its words with the spacing
    evened out, where it starts and ends in `text`)."""
    text = text or ""
    for m in re.finditer(r"\S[^.!?]*[.!?]+(?=\s|$)", text):
        words = " ".join(m.group().split())
        if 40 <= len(words) <= n:
            return words, m.start(), m.end()
    cut = text[:n]
    if len(text) > n and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    lead = len(cut) - len(cut.lstrip())
    return " ".join(cut.split()), lead, len(cut.rstrip())


def _sentence(text: str, n: int = 260) -> str:
    return _sentence_at(text, n)[0]


def theme_sources(ws: Workspace, all_projects: bool = False) -> list[dict]:
    """The sets of themes a codebook can start from: this project's (and, with `all_projects`, every project's), each
    theme shown (not removed, merges applied) as a draft code: a short name made of words of its name (0.16.1,
    codenames.py: `names` from the shortest to the longest, `pick` the one chosen, `sure` whether the documents showed
    it specific enough), its description (where the AI named it), its key terms as the words it is matched by, and its
    best passages as examples."""
    from . import codenames, home, themes

    out = []
    projects = [(None, ws)]
    if all_projects:
        here = Path(ws.root).resolve()
        for pname in home.list_projects():
            if home.is_temporary(pname) or home.project_path(pname).resolve() == here:
                continue
            try:
                projects.append((pname, home.open_project(pname)))
            except Exception:  # noqa: BLE001 - a project that cannot be opened is left out
                continue
    for pname, w in projects:
        for run in themes.runs(w):
            try:
                v = themes.view(w, run["run_id"])
            except Exception:  # noqa: BLE001
                continue
            try:
                short = codenames.for_run(w, run["run_id"], v["themes"])
            except Exception:  # noqa: BLE001 - names by cutting at a word, as a last resort
                short = {}
            drafts = []
            for t in v["themes"]:
                nm = short.get(t["theme_id"]) or {"names": [codenames.cut(t["name"]) or f"Theme {t['theme_id']}"],
                                                  "pick": 0, "sure": False}
                examples = []
                for rep in (t.get("representatives") or [])[:3]:
                    pid = rep.get("passage_id") if isinstance(rep, dict) else rep
                    r = w.query("SELECT p.doc_id, p.page, p.start, p.text, d.title FROM passages p JOIN documents d ON "
                                "d.doc_id=p.doc_id WHERE p.passage_id=?", (pid,))
                    if r:
                        q, a, z = _sentence_at(r[0]["text"])
                        examples.append({"quote": q, "doc_id": r[0]["doc_id"], "title": r[0]["title"],
                                         "page": r[0]["page"], "project": w.project_uid(),
                                         "start": r[0]["start"] + a, "end": r[0]["start"] + z})
                desc = (t.get("description") or "").strip()
                drafts.append({"theme_id": t["theme_id"], "name": t["name"], "size": t["size"],
                               "named_by": t.get("name_source"), "names": nm["names"], "pick": nm["pick"],
                               "sure": nm["sure"],
                               "code": {"code": nm["names"][nm["pick"]],
                                        "description": desc or f"Passages about {t['name']}.",
                                        "described": bool(desc), "group": "", "keywords": list(t.get("terms") or [])[:8],
                                        "include": "", "exclude": "", "examples": examples}})
            if drafts:
                out.append({"project": pname, "here": pname is None, "run_id": run["run_id"],
                            "created_at": run["created_at"], "mode": run["mode"], "themes": drafts})
    if all_projects and len(projects) > 1:
        try:  # this project's keyword index stays the most recent in memory: other projects' were loaded to name codes
            from .search import passage_index
            passage_index(ws)
        except Exception:  # noqa: BLE001
            pass
    return out


def _draft(state: dict) -> frameworks.Framework:
    clean = _clean_state(state)
    gname = {g["group"]: g["group_name"] for g in clean["groups"]}
    codes = {c["code"]: Code(c["code"], c["description"], c["group"], gname.get(c["group"], ""), c["include"],
                             c["exclude"], tuple(c["keywords"])) for c in clean["codes"]}
    return frameworks.Framework("draft", clean["title"] or "draft", clean["label"], codes, "draft",
                                directional=clean["directional"], ordered=True)


def try_codes(ws: Workspace, state: dict, progress: Callable[[int, int], None] | None = None) -> dict:
    """Without AI: for each code of a codebook (as the editor has it, saved or not), how many passages and documents
    the keyword pass would pick, with three of them. The same rules as the Profile page's keyword pass (meaning
    search left out): a code that picks nothing, or nearly everything, shows before any AI labels."""
    from .profile import MAX_CANDIDATES, keyword_candidates, rank_candidates
    from .search import passage_index

    from .concordance import CHUNK

    fw = _draft(state)
    idx = passage_index(ws)
    n_rows = len(idx.doc_of)
    idf = idx.bm25.idf
    totals: dict[str, float] = {}
    per: dict[str, dict] = {c: {"passages": 0, "docs": set(), "examples": []} for c in fw.codes}
    titles = {r[0]: r[1] for r in ws.query("SELECT doc_id, title FROM documents")}
    # the passages' text a chunk at a time, not all of it at once
    rows = (r for k in range(0, n_rows, CHUNK) for r in idx.read(range(k, min(k + CHUNK, n_rows))))
    for n, r in enumerate(rows, 1):
        cands = keyword_candidates(fw, r["text"], idf, totals)
        for code, _c in rank_candidates(cands)[:MAX_CANDIDATES]:
            p = per[code]
            p["passages"] += 1
            p["docs"].add(r["doc_id"])
            if len(p["examples"]) < 3 and r["doc_id"] not in {x["doc_id"] for x in p["examples"]}:
                p["examples"].append({"passage_id": r["passage_id"], "doc_id": r["doc_id"],
                                      "title": titles.get(r["doc_id"]), "page": r["page"],
                                      "text": _sentence(r["text"], 300)})
        if progress and n % 500 == 0:
            progress(n, n_rows)
    total_docs = len(set(idx.doc_of))
    out = {}
    for code, p in per.items():
        share = p["passages"] / max(1, n_rows)
        out[code] = {"passages": p["passages"], "documents": len(p["docs"]), "examples": p["examples"],
                     "share": round(share, 4),
                     "note": ("matches nothing: add words it is matched by, or change its definition"
                              if not p["passages"] else
                              "matches a large part of the documents: its words may be too common" if share > 0.25
                              else None)}
    return {"passages": n_rows, "documents": total_docs, "codes": out}


def relabel_passages(ws: Workspace, name: str, code: str) -> list[str]:
    """The passages the AI labelled with `code` before its wording changed: their label tasks are taken back (the
    labels stay until the new answers replace them), so a labelling run reads them again with the new wording."""
    st = stale(ws, name).get(code)
    if not st:
        return []
    pids = [r[0] for r in ws.query("SELECT DISTINCT passage_id FROM labels WHERE framework=? AND code=? AND "
                                   "source='model' AND COALESCE(created_at, '') < ?", (name, code, st["since"]))]
    with ws.connect() as cx:
        for pid in pids:
            cx.execute("DELETE FROM tasks WHERE task_id=? AND status IN ('done', 'failed')", (f"label:{name}:{pid}",))
    return pids


# ---------------------------------------------------------------------------------------------
# history.py: a codebook's versions are files beside it
# ---------------------------------------------------------------------------------------------
def _title_of(ws: Workspace, name: str) -> str:
    from .researchlog import quoted

    try:
        return f"the codebook {quoted(frameworks.get(name, ws).title, 80)}"
    except ValueError:
        return f"the codebook {name}"


def _find_version(ws: Workspace, name: str, vid: str) -> Path:
    _name_ok(name)
    if not _VID.fullmatch(vid or ""):
        raise KeyError(vid)
    for p in _version_files(ws, name):
        if p.stem == vid:
            return p
    raise KeyError(vid)


def _versions(ws: Workspace, name: str) -> list[dict]:
    out = []
    for p in _version_files(ws, name):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({**{k: d.get(k) for k in ("version_id", "at", "person_id", "label")}, "_ns": int(d.get("ns") or 0)})
    out.sort(key=lambda d: (d.get("at") or "", d["_ns"]), reverse=True)
    for d in out:
        d.pop("_ns")
    return out


def _load_version(ws: Workspace, name: str, vid: str) -> tuple[dict, dict]:
    d = json.loads(_find_version(ws, name, vid).read_text(encoding="utf-8"))
    meta = d.get("meta") or {}
    codes = frameworks.parse_csv(d.get("csv") or "code,description\n", allow_empty=True, extra=bool(meta.get("editor")))
    st = _state(name, codes, meta, meta.get("title") or name, meta.get("label") or "code",
                bool(meta.get("directional")))
    return {k: d.get(k) for k in ("version_id", "at", "person_id", "label")}, st


def _capture(ws: Workspace, cx, name: str) -> dict | None:
    try:
        return state_of(ws, name)
    except (ValueError, KeyError):  # removed: compared with nothing, so Restore says what comes back
        return {"name": name, "title": "", "label": "code", "directional": False, "groups": [], "codes": []}


def _changes(ws: Workspace, old: dict, new: dict, name: str) -> list[dict]:
    out = []
    a = {c["uid"]: c for c in old["codes"]}
    b = {c["uid"]: c for c in new["codes"]}
    for u, c in a.items():
        if u not in b:
            out.append({"what": f"Code {c['code']}", "before": c["description"], "after": "(not in the codebook)"})
            continue
        d = b[u]
        if c["code"] != d["code"]:
            out.append({"what": "Code name", "before": c["code"], "after": d["code"]})
        for key, words in (("description", "Definition"), ("include", "When to use it"),
                           ("exclude", "When not to use it")):
            if c[key] != d[key]:
                out.append({"what": f"{words} of {d['code']}", "before": c[key], "after": d[key]})
        if c["keywords"] != d["keywords"]:
            out.append({"what": f"Words {d['code']} is matched by", "before": "; ".join(c["keywords"]),
                        "after": "; ".join(d["keywords"])})
        if c["group"] != d["group"]:
            out.append({"what": f"Group of {d['code']}", "before": c["group"], "after": d["group"]})
        if [e["quote"] for e in c["examples"]] != [e["quote"] for e in d["examples"]]:
            out.append({"what": f"Examples of {d['code']}", "before": f"{len(c['examples'])}",
                        "after": f"{len(d['examples'])}"})
    for u, d in b.items():
        if u not in a:
            out.append({"what": f"Code {d['code']}", "before": "(not in the codebook)", "after": d["description"]})
    if old["title"] != new["title"]:
        out.append({"what": "Title", "before": old["title"], "after": new["title"]})
    if [u for u in a if u in b] != [u for u in b if u in a] and not out:
        out.append({"what": "Order of the codes", "before": "", "after": "changed"})
    return out


def _restore(ws: Workspace, name: str, vid: str) -> dict:
    from . import researchlog

    meta, st = _load_version(ws, name, vid)
    when = history._when(meta.get("at") or "")
    try:
        locate(ws, name)
    except KeyError:  # the codebook was removed: its files come back as they were in that version
        p = _find_version(ws, name, vid)
        d = json.loads(p.read_text(encoding="utf-8"))
        if name in frameworks.available(ws):
            raise ValueError("Another codebook of that name is in use now.") from None
        _write(p.parent.parent.parent, name, d.get("csv") or "code,description\n", d.get("meta") or {})
        follow(ws, name)
        with ws.connect() as cx:
            researchlog.record(cx, "restored", f"Brought back the codebook {researchlog.quoted(st['title'], 80)} as it "
                                               f"was on {when}.", "codebook", name, st["title"],
                               data={"kind": "codebook", "version_id": vid})
        return {"restored": True, "changes": [{"what": "Codebook", "before": "(removed)", "after": st["title"]}]}
    cur = state_of(ws, name)
    changes = _changes(ws, cur, st, name)
    if not changes:
        return {"restored": False, "changes": []}
    # a code the version had merged into another (one that is a code of its own now): merged again, labels and all
    vmeta = json.loads(_find_version(ws, name, vid).read_text(encoding="utf-8")).get("meta") or {}
    gone = vmeta.get("removed") or {}
    in_version = {c["uid"]: c["code"] for c in st["codes"]}
    by_name = {v: k for k, v in in_version.items()}
    merges = []
    for c in cur["codes"]:
        g = gone.get(c["uid"]) if isinstance(gone.get(c["uid"]), dict) else None
        if c["uid"] in in_version or not g or not g.get("merged_into"):
            continue
        into = g.get("merged_into_uid") if g.get("merged_into_uid") in in_version else by_name.get(g["merged_into"])
        if into:
            merges.append({"from": c["uid"], "into": into})
    res = save(ws, name, st, merges=merges, label=f"restoring the version of {when}", restoring=when)
    return {"restored": True, "changes": changes, "version_id": res["version_id"]}


history.KINDS["codebook"] = history.Kind(_title_of, _capture, _changes, lambda *a: None, stored="own",
                                         versions=_versions, load=_load_version, restore=_restore)


# ---------------------------------------------------------------------------------------------
# roles (DESIGN-roles §4.9, H8): a colleague's renames and merges, offered
# ---------------------------------------------------------------------------------------------
def _offer(ws: Workspace, name: str) -> tuple[dict | None, list[dict]]:
    """The waiting offer of codebook `name` and its events (in the codebook's order); (None, []) when none."""
    raw = ws.meta(f"codebook_offers:{name}")
    if not isinstance(raw, dict):
        return None, []
    fw = frameworks.available(ws).get(name)
    ids = set(raw.get("events") or [])
    return raw, [e for e in _events((fw.meta if fw else None) or {}) if e["id"] in ids]


def offers(ws: Workspace) -> list[dict]:
    """A colleague's renames and merges waiting before they move this person's own labels: {"name", "from", "events":
    [{"op", "from", "to"}], "labels": n}."""
    out = []
    for (key,) in ws.query("SELECT key FROM meta WHERE key LIKE 'codebook_offers:%' ORDER BY key"):
        name = key.split(":", 1)[1]
        raw, events = _offer(ws, name)
        if raw is None:
            continue
        n = _moves_any(ws._conn(), name, events)
        out.append({"name": name, "from": raw.get("from"), "at": raw.get("at"),
                    "events": [{"op": e["op"], "from": e.get("from"), "to": e.get("to")} for e in events
                               if not str(e.get("to") or "").startswith("~")],
                    "labels": n})
    return out


def answer_offer(ws: Workspace, name: str, follow: bool) -> dict:
    """Follow the waiting events of codebook `name` on this person's own labels (*Follow*), or keep the labels as
    they are (*Keep mine*: the events count as followed; labels of a code that is gone wait under *Removed codes*).
    Returns {"name", "followed", "moved"}."""
    from . import researchlog
    from .profile import label_id

    raw, events = _offer(ws, name)
    if raw is None:
        raise KeyError(name)
    moved = 0
    title = _title_of(ws, name)
    with ws.connect() as cx:
        if follow:
            ok, _ = checked_events(events)
            for e in ok:
                moved += _follow_one(cx, name, e, label_id)
        cx.execute("DELETE FROM meta WHERE key=?", (f"codebook_offers:{name}",))
        who = (cx.execute("SELECT name FROM people WHERE person_id=?", (raw.get("from"),)).fetchone() or [None])[0]
        researchlog.record(cx, "codebook-changed",
                           (f"Followed {who or 'a colleague'}'s renames and merges of the codebook "
                            f"{researchlog.quoted(title, 80)}: {moved} label{'s' if moved != 1 else ''} "
                            "moved." if follow else
                            f"Kept the labels as they were after {who or 'a colleague'}'s renames and merges of the "
                            f"codebook {researchlog.quoted(title, 80)}."), "codebook", name, title)
    return {"name": name, "followed": follow, "moved": moved}
