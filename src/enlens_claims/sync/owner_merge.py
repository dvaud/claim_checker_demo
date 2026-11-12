"""0.18 L2 (ownership.py): how a colleague's copy's word on the owner, on proposals and on the documents as accepted
comes into this one. A mixin of `_Merge` (merge.py), run before the documents are looked at."""
from __future__ import annotations

import sqlite3

from .common import _cols, _rows


class OwnerRules:
    def _ownership(self, cx: sqlite3.Connection) -> None:
        """Each of the four tables by its own rule (see ownership.py's notes): records of who the owner is and
        decisions are added (which of them counts is worked out when they are read, alike in every copy); a proposal
        is added, and one its maker took back is taken back here; of two rows about a document by one writer, the
        later one stays. Then the documents this merge must not bring back (`not_wanted`) are known.

        A row written in this person's name (`by`) comes from this copy and from nowhere else: one in a colleague's
        file that this copy does not hold is not taken (a record of who the owner is, a proposal, a decision, a row
        of the documents as accepted). Without this, one row "by the owner" with a high number, sent to the owner's
        own copy, changed there who may read a document with AI, as if the owner had decided it."""
        from .. import ownership

        self.not_wanted: set[str] = set()
        there = {r[0] for r in self.icx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rep = self.r.setdefault("proposals", {"new": [], "decided": 0, "owner": None})
        if {"ownership", "proposals", "decisions", "canon"} <= there:
            before = ownership.owner(cx)

            def theirs(sql: str) -> list[dict]:
                return [r for r in _rows(self.icx, sql) if r.get("by") != self.me]

            self._insert(cx, "ownership", theirs("SELECT * FROM ownership"))
            have = {r[0]: r[1] for r in cx.execute("SELECT id, taken_back_at FROM proposals")}
            for p in theirs("SELECT * FROM proposals"):
                if p["id"] not in have:
                    self._insert(cx, "proposals", [p])
                    if p["by"] != self.me and not p["taken_back_at"]:
                        rep["new"].append({"id": p["id"], "kind": p["kind"], "title": p["title"], "by": p["by"]})
                elif p["taken_back_at"] and not have[p["id"]] and p["by"] != self.me:
                    cx.execute("UPDATE proposals SET taken_back_at=? WHERE id=?", (p["taken_back_at"], p["id"]))
            rep["decided"] = self._insert(cx, "decisions", theirs("SELECT * FROM decisions"))
            mine = {(r[0], r[1]): (r[2] or 0, r[3] or 0) for r in cx.execute("SELECT doc, by, owner_seq, n FROM canon")}
            cols = _cols(cx, "canon")
            for r in theirs("SELECT * FROM canon"):
                if (r["owner_seq"] or 0, r["n"] or 0) > mine.get((r["doc"], r["by"]), (-1, -1)):
                    cx.execute(f"INSERT OR REPLACE INTO canon({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                               [r.get(c) for c in cols])
            after = ownership.owner(cx)
            if after != before:
                rep["owner"] = after
        self.not_wanted = ownership.not_wanted(cx, self.me)

    def _their_ai_n(self, iid: str):
        """How far the sender's copy has followed the owner's word on who may read this document with AI (the number
        of the owner's change): from the shared folder's stub, or from their copy's own record in a zip."""
        if iid in self.canon_ai:
            return self.canon_ai[iid]
        try:
            row = self.icx.execute("SELECT ai_n FROM canon_seen WHERE doc=?", (iid,)).fetchone()
        except sqlite3.Error:
            return None
        return row[0] if row else None

    def _came_from(self, cx: sqlite3.Connection) -> None:
        """The documents that came in now are the sender's, not this person's own additions: a collaborator's copy
        does not propose them in its own name (a sender without the owner's rules, format 2 or older, cannot propose:
        those are then this copy's to propose, ownership.settle)."""
        if self.format_in < 3 or self.sender["id"] == self.me:
            return
        for iid in self.new_docs:
            cx.execute("INSERT INTO canon_seen(doc, came_from) VALUES (?,?) ON CONFLICT(doc) DO UPDATE SET "
                       "came_from=excluded.came_from, gone=NULL", (self.docs[iid], self.sender["id"]))

    def _removal_kind(self, cx: sqlite3.Connection, doc: str) -> str | None:
        """What a colleague's removal of a document this copy holds is, in a project with an owner: "proposed" (their
        proposal waits for the owner), "owner" (the owner removed it from the project: it leaves this copy too),
        "declined" / "taken_back" (this person's own addition the owner did not accept, or that they took back: it
        stays in this copy only). None: as before 0.18 (no owner, or none of these)."""
        from .. import ownership

        if not hasattr(self, "_owner_state"):
            ch = ownership.chain(cx)
            self._owner_state = (ch, ownership.canon(cx, ch), ownership._decisions(cx, ch), ownership._proposals(cx)) \
                if ch else None
        if self._owner_state is None:
            return None
        ch, K, dec, props = self._owner_state
        k = K.get(doc)
        if k is not None and k["state"] == "removed" and ch[-1]["owner"] != self.me:
            return "owner"
        for p in props.values():
            if p["doc"] != doc:
                continue
            st = ownership.state_of(p, K, dec)[0]
            if p["kind"] == "remove" and p["by"] == self.sender["id"] and st == "waiting":
                return "proposed"
            if p["kind"] == "add" and p["by"] == self.me and k is None and st in ("declined", "taken_back"):
                return st
        return None
