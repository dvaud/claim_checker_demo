"""What each person shared, in a merge (0.18, roadmap L1; sharing.py has the rules).

`ShareRules` is a part of `merge._Merge`, in two steps:

- before the merge (`_withhold`): an item its owner took back (*Unshare*) and that this copy does not hold is taken
  out of the colleague's scratch copy, so it does not reach this copy through someone who still has it. The latest mark
  counts, the colleague's or this copy's own;
- after the merge (`_share_marks`): the colleague's marks of the items this copy now holds (and their withdrawals of
  items it does not hold) are noted here, by the owner's word only (`sharing.receive`). An item of the colleague's
  copy without a mark is their own and private (a whole-project zip of 0.18 carries those too): it stays theirs here,
  and this copy never passes it on. A file from before 0.18 (format 1) says nothing of sharing: its items count as
  shared, as everything exchanged before 0.18 does. A shared check or set of themes that its owner removed counts as
  taken back in the copies that keep it (`_removed_by_owner`).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .common import _rows, _tokens


class ShareRules:
    def _local_key(self, kind: str, key: str) -> str:
        """The key of the colleague's item in this copy (a check or a set of themes kept as a sync-clash copy, a
        codebook kept beside yours, have another key here)."""
        if kind == "codebook":
            return self.fw.get(key, key)
        if kind in ("check", "themes"):
            return _tokens(key, self.ids)
        return key

    def _withhold(self, cx: sqlite3.Connection) -> None:
        from .. import sharing

        # the items this copy holds before the merge: one of them without a row is this copy's own
        self.items_before = {(k, key) for k, keys in sharing.items(cx, self.ws.root).items() for key in keys}
        if not sharing.has_table(self.icx):
            return
        here, there = sharing.rows(cx), sharing.rows(self.icx)
        root = Path(self.ws.root)
        gone: dict[str, list[str]] = {}
        for (kind, key), r in there.items():
            mine = here.get((kind, key))
            # the later mark counts; a guess (no one's word: a project from before 0.18) never over one here
            mark = mine if mine is not None and (r.get("by") is None or (mine.get("at") or "") >= (r.get("at") or "")) \
                else r
            if mark.get("state") == "withdrawn" and not sharing.exists(cx, root, kind, key):
                gone.setdefault(kind, []).append(key)
        if not gone:
            return
        with self.inc.connect() as icx:
            for kind, keys in gone.items():
                titles = sharing.items(icx, self.inc.root)[kind]
                self.r["shares"]["withheld"] += [titles.get(k) or k for k in keys if k in titles]
                # its maker's own note that they removed it stays (a removed item that was shared is that note, and
                # its maker sends it): this copy then knows it as removed whichever colleague it hears from first
                notes = [n for n in _rows(icx, "SELECT * FROM sync_removed WHERE kind=?", (kind,))
                         if n["key"] in keys and n["person_id"] and n["person_id"] == there[(kind, n["key"])].get("owner")]
                sharing.drop(icx, kind, keys)
                for n in notes:
                    icx.execute(f"INSERT INTO sync_removed({','.join(n)}) VALUES ({','.join('?' * len(n))})",
                                tuple(n.values()))
                if kind == "codebook":  # their files stay in the scratch copy: they are not taken either
                    for name in keys:
                        for ext in ("csv", "json"):
                            (Path(self.inc.root) / "frameworks" / f"{name}.{ext}").unlink(missing_ok=True)

    def _share_marks(self, cx: sqlite3.Connection) -> None:
        from .. import sharing

        there = sharing.rows(self.icx)
        sender = self.sender["id"]
        default = "shared" if self.format_in < 2 else "private"  # before 0.18 everything exchanged was shared
        for kind, keys in sharing.items(self.icx, self.inc.root).items():
            for key, title in keys.items():
                if (kind, key) not in there:  # before 0.18 (a guess, no one's word) or the sender's own, private
                    there[(kind, key)] = ({"state": "shared", "owner": None, "by": None, "at": None, "title": title}
                                          if default == "shared" else
                                          {"state": "private", "owner": sender, "by": sender, "at": self.at,
                                           "title": title})
        root = Path(self.ws.root)
        coming = {Path(d).stem for _src, d in self.files if Path(d).suffix == ".csv" and Path(d).parent == root / "frameworks"}
        for (kind, key), r in sorted(there.items()):
            local = self._local_key(kind, key)
            present = sharing.exists(cx, root, kind, local) or (kind == "codebook" and local in coming)
            got = sharing.receive(cx, kind, local, r, self.me, present, had=(kind, local) in self.items_before)
            if got in ("shared", "withdrawn") and present:
                self.r["shares"][got].append(self._title_here(cx, kind, local, r.get("title")))
        self._removed_by_owner(cx, there)

    def _title_here(self, cx: sqlite3.Connection, kind: str, local: str, given: str | None = None) -> str:
        """An item's name for the report: the one that came with it, else as this copy knows it (a withdrawal travels
        without a title: the Team tab said 'No longer shared by its owner: "hf864a9b2c80c"'), else its key."""
        from .. import sharing

        if given:
            return given
        row = cx.execute("SELECT title FROM shares WHERE kind=? AND key=?", (kind, local)).fetchone()
        if row and row[0]:
            return row[0]
        if getattr(self, "_share_titles", None) is None:
            self._share_titles = sharing.items(cx, Path(self.ws.root))
        return self._share_titles.get(kind, {}).get(local) or local

    def _removed_by_owner(self, cx: sqlite3.Connection, there: dict) -> None:
        """A shared check or set of themes its owner removed stays in the copies that have it (nothing is taken from
        anyone), but as taken back: this copy no longer passes it on, so it does not reach, through this copy, a
        colleague who never had it. The owner's note of removal counts as their mark, at the time of the removal; a
        colleague who removed their own copy of someone else's item decides nothing (`sharing.receive`)."""
        from .. import sharing

        root = Path(self.ws.root)
        for kind, key, by, at in self.icx.execute("SELECT kind, key, person_id, at FROM sync_removed WHERE kind IN "
                                                  "('check', 'themes')").fetchall():
            local = self._local_key(kind, key)
            if not by or not at or not sharing.exists(cx, root, kind, local):
                continue
            here = cx.execute("SELECT owner FROM shares WHERE kind=? AND key=?", (kind, local)).fetchone()
            owner = here[0] if here else (there.get((kind, key)) or {}).get("owner")
            if owner != by:
                continue  # not its maker's removal (or nobody knows who made it): it says nothing about sharing
            # (a removal is timed to the second, a mark to the microsecond: one in the same second as the mark is later)
            when = at.replace("+00:00", ".999999+00:00") if "." not in at else at
            mark = {"state": "withdrawn", "owner": owner, "by": by, "at": when, "title": None}
            if sharing.receive(cx, kind, local, mark, self.me, True, had=(kind, local) in self.items_before) == \
                    "withdrawn":
                self.r["shares"]["withdrawn"].append(self._title_here(cx, kind, local))
