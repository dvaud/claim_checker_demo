"""Codebooks in a merge (0.18: split out of sync.py): which of the colleague's codebooks come in, which bring yours up
to date, which are merged code by code and which are kept beside yours, and how labels follow a codebook's renames and
merges afterwards.

`CodebookRules` is a part of `merge._Merge`: its methods use the merge's state (the two copies, the names of
codebooks that differ, the files to copy once the database is merged).

0.18: a codebook both copies changed since they last exchanged it is merged code by code, with the codebook editor's
model (codebooks.py: each code has a stable id, renames and merges are events, removed codes keep their definitions).
Each exchange writes down the state of every code (`sync_seen`, kind "code", key `<codebook>/<code id>`), so for each
code:

- the same in both: nothing to do;
- changed on one side only (the other side's state is one this side had): the newer version, from either side;
- changed on both sides: yours stays, and the colleague's version is kept beside it in the side file (`clashes`), so
  nothing is lost: the editor shows it, and `codebooks.settle_clash` keeps one of the two;
- new on one side: it comes in; removed or merged away on one side, unchanged on the other: it goes (its labels wait
  under *Removed codes*, or follow the merge); removed here but changed there since: it stays removed, and their
  version is kept as a clash;
- the codebook's own settings (its title, what a code is called) are one more such unit (`<codebook>/~`);
- renames and merges of either side are kept in order, so the labels of both follow them (`codebooks.follow_merged`).

A codebook of the same name made separately in each copy (no state in common) is not merged: it is kept beside yours
as a sync-clash copy, as before 0.18.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from .fingerprints import HEAD, _codebook_fp, _home_codebooks, code_fp, codebook_state, head_fp


def _event_order(e: dict) -> tuple:
    """Where a codebook's event (a rename, a merge of codes) goes among the others: by its time, its number, then its
    id, so two copies holding the same events order them alike (the time is to the second; a number that is not one
    counts as 0)."""
    try:
        seq = int(e.get("seq") or 0)
    except (TypeError, ValueError):
        seq = 0
    return str(e.get("at") or ""), seq, str(e.get("id") or "")


class CodebookRules:
    def _codebooks(self, cx: sqlite3.Connection) -> None:
        """The colleague's codebooks: a new one comes in; one of yours they changed (and you did not) is brought up to
        date; one you both changed comes in beside yours as `<name>-<mark>`, and their labels with it. Only decided
        here: the files are written once the database is merged."""
        from ..frameworks import BUNDLED, NAME_RE, available

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
            # 0.18: both changed a codebook they have exchanged before: code by code
            if seen_here.get(name, set()) & seen_there.get(name, set()) and self._merge_codes(cx, src, dest, name):
                continue
            new = f"{name}-{fp_in[:6]}"
            self.fw[name] = new
            self._take_codebook(src, dest, name, new)
            self.codebook_marks.append((new, name))
            self._mark(cx, "codebook", new, name)
            self.r["codebooks"]["clash"].append({"name": new, "of": name})

    def _merge_codes(self, cx: sqlite3.Connection, src: Path, dest: Path, name: str) -> bool:
        """A codebook both copies changed, merged code by code (see the module's notes). Decided here; the merged files
        are written into the colleague's scratch copy and copied in place with the other files, once the database is
        merged, after the version before the merge is kept. False when either version cannot be read (it then comes
        in beside yours, as before 0.18)."""
        where = dest if (dest / f"{name}.csv").is_file() else _home_codebooks()
        mine, theirs = codebook_state(where, name), codebook_state(src, name)
        if mine is None or theirs is None:
            return False
        seen_here, seen_there = self._seen(cx, "code"), self._seen(self.icx, "code")
        m_meta, t_meta = mine.pop("meta"), theirs.pop("meta")
        m_groups = {g["group"]: g["group_name"] for g in mine["groups"]}
        t_groups = {g["group"]: g["group_name"] for g in theirs["groups"]}
        m_codes = {c["uid"]: c for c in mine["codes"]}
        t_codes = {c["uid"]: c for c in theirs["codes"]}
        m_removed = {k: v for k, v in (m_meta.get("removed") or {}).items() if isinstance(v, dict)}
        t_removed = {k: v for k, v in (t_meta.get("removed") or {}).items() if isinstance(v, dict)}
        clashes = {k: v for k, v in (m_meta.get("clashes") or {}).items() if isinstance(v, dict)}
        places = dict(m_meta.get("places") or {})
        who = {"person_id": self.sender["id"], "name": self.sender["name"] or "a colleague", "at": self.at}
        rep = {"name": name, "theirs": [], "clash": [], "added": [], "removed": [], "kept_removed": []}

        def key(uid: str) -> str:
            return f"{name}/{uid}"

        def known(fp: str, seen: dict, uid: str) -> bool:
            return fp in seen.get(key(uid), set())

        out: list[dict] = []
        theirs_in: set[str] = set()  # the codes taken from their version (new there, or newer there)
        for uid, mc in m_codes.items():
            mfp = code_fp(mc, m_groups)
            tc = t_codes.get(uid)
            if tc is None:
                if uid in t_removed and known(mfp, seen_there, uid):  # they removed or merged it, you did not change it
                    m_removed[uid] = t_removed[uid]
                    rep["removed"].append(mc["code"])
                    continue
                out.append(mc)  # yours alone (new here), or changed here after they removed it: it stays
                continue
            tfp = code_fp(tc, t_groups)
            if tfp == mfp or known(tfp, seen_here, uid):
                out.append(mc)          # the same, or yours is newer
                self.history.add(("code", key(uid)))
            elif known(mfp, seen_there, uid):  # theirs is newer
                out.append(tc)
                theirs_in.add(uid)
                places[uid] = (t_meta.get("places") or {}).get(uid) or []
                self.history.add(("code", key(uid)))
                rep["theirs"].append(tc["code"])
            else:                       # both changed it: yours stays, theirs is kept beside it
                out.append(mc)
                clashes[uid] = {**{k: tc[k] for k in ("code", "description", "group", "include", "exclude",
                                                      "keywords")},
                                "group_name": t_groups.get(tc["group"], ""),
                                "examples": [e["quote"] for e in tc["examples"]], **who}
                rep["clash"].append(mc["code"])
        for uid, tc in t_codes.items():
            if uid in m_codes:
                continue
            if uid in m_removed:  # removed (or merged away) here
                if not known(code_fp(tc, t_groups), seen_here, uid):  # but changed there since: kept as a clash
                    clashes[uid] = {**{k: tc[k] for k in ("code", "description", "group", "include", "exclude",
                                                          "keywords")},
                                    "group_name": t_groups.get(tc["group"], ""),
                                    "examples": [e["quote"] for e in tc["examples"]], "removed_here": True, **who}
                    rep["kept_removed"].append(tc["code"])
                continue
            out.append(tc)  # new there
            theirs_in.add(uid)
            places[uid] = (t_meta.get("places") or {}).get(uid) or []
            self.history.add(("code", key(uid)))
            rep["added"].append(tc["code"])
        # two codes may not share a name (labels name their code): one of theirs that came in under the name of another
        # code here takes a name of its own, and only their labels made with it follow it there
        renamed = []
        taken = {c["code"].lower() for c in out if c["uid"] not in theirs_in}
        for c in out:
            if c["uid"] not in theirs_in:
                continue
            if c["code"].lower() in taken:
                old, n = c["code"], 1
                while c["code"].lower() in taken:
                    tail = f" ({who['name']})" if n == 1 else f" ({who['name']} {n})"
                    c["code"] = old[:max(1, 40 - len(tail))].rstrip() + tail
                    n += 1
                renamed.append({"op": "rename", "from": old, "to": c["code"], "uid": c["uid"],
                                "id": uuid.uuid4().hex[:12], "at": self.at, "seq": 0})
                rep.setdefault("renamed", []).append({"from": old, "to": c["code"]})
            taken.add(c["code"].lower())
        # the codebook's own settings
        head = mine
        mh, th = head_fp(mine), head_fp(theirs)
        if th != mh and not known(th, seen_here, HEAD) and known(mh, seen_there, HEAD):
            head = theirs
            self.history.add(("code", key(HEAD)))
        # the groups: yours, then theirs you do not have (a group both have keeps your name for it)
        groups = list(mine["groups"]) + [g for g in theirs["groups"] if g["group"] not in m_groups]
        events = [e for e in (m_meta.get("events") or []) if isinstance(e, dict)]
        have = {e.get("id") for e in events}
        events += [e for e in (t_meta.get("events") or []) if isinstance(e, dict) and e.get("id") not in have]
        events.sort(key=_event_order)
        events += renamed
        if renamed:  # your labels never had their name for it: the rename is followed here only by theirs
            row = cx.execute("SELECT value FROM meta WHERE key=?", (f"codebook_followed:{name}",)).fetchone()
            done = set(json.loads(row[0]) if row else [])
            cx.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                       (f"codebook_followed:{name}", json.dumps(sorted(done | {e["id"] for e in renamed}))))
        uids = {c["uid"] for c in out}
        meta = {**m_meta, "title": head["title"], "label": head["label"], "editor": True, "ordered": True,
                "ids": {c["code"]: c["uid"] for c in out}, "groups": groups,
                "places": {u: v for u, v in places.items() if u in uids and v},
                "removed": {u: v for u, v in m_removed.items() if u not in uids}, "events": events,
                "clashes": {u: v for u, v in clashes.items() if u in uids or u in m_removed}}
        if head["directional"]:
            meta["directional"] = True
        else:
            meta.pop("directional", None)
        if not meta["clashes"]:
            meta.pop("clashes")
        from .. import codebooks

        scratch = Path(self.inc.root) / "merged-codebooks"
        scratch.mkdir(exist_ok=True)
        (scratch / f"{name}.csv").write_text(codebooks._csv_text(out, groups), encoding="utf-8")
        (scratch / f"{name}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
        self._take_codebook(scratch, dest, name, name)
        self.codebook_versions.append((where, name))
        self.history.add(("codebook", name))
        self.r["codebooks"].setdefault("merged", []).append(rep)
        return True

    def _keep_codebook_versions(self) -> None:
        """0.18: before a codebook merged code by code is written, the version it had is kept (history.py's *Compare*
        and *Restore* of the codebook editor)."""
        from .. import codebooks

        who = self.sender["name"] or "a colleague"
        for folder, name in self.codebook_versions:
            codebooks._keep_version(folder, name, f"before bringing in {who}'s changes")

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

    def _follow_codebooks(self, cx: sqlite3.Connection) -> None:
        """0.16 (codebooks.py): labels follow a codebook's renames and merges. Yours follow the changes your copy had not
        followed yet; those that came in follow the changes the colleague's copy had not (its own record of them)."""
        from .. import codebooks
        from ..frameworks import available

        here = Path(self.ws.root) / "frameworks"
        taken = {Path(d).stem: Path(src) for src, d in self.files
                 if Path(d).suffix == ".json" and Path(d).parent == here}
        theirs_of = {v: k for k, v in self.fw.items()}
        now_here = available(self.ws)
        for name in sorted(set(self.new_labels) | set(taken)):
            if name in taken:
                try:
                    meta = json.loads(taken[name].read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    meta = {}
            else:
                meta = (now_here[name].meta if name in now_here else {}) or {}
            if not isinstance(meta, dict):
                continue
            row = self.icx.execute("SELECT value FROM meta WHERE key=?",
                                   (f"codebook_followed:{theirs_of.get(name, name)}",)).fetchone()
            try:
                theirs_done = set(json.loads(row[0])) if row else set()
            except ValueError:
                theirs_done = set()
            codebooks.follow_merged(cx, self.ws, name, meta, theirs_done, self.new_labels.get(name, set()),
                                    self.hyps_before)
