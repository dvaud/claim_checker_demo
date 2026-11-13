"""0.18 L2 (ownership.py): how a colleague's copy's word on the owner, on proposals and on the documents as accepted
comes into this one. A mixin of `_Merge` (merge.py), run before the documents are looked at."""
from __future__ import annotations

import sqlite3

from .common import _cols, _rows


STEP = 2 ** 32  # a row numbered more than this above the highest number held here is not taken (review, H2)
_NUM_COLS = {"canon": ("n", "state_n", "read_n", "ai_n", "blocks_n"), "decisions": ("n",), "roles": ("n",)}


def _n0(v):
    """An answer's number: NULL (written before roles) is 0; one not an integer in 0 … 2**53 is not taken."""
    from ..ownership import _num

    return 0 if v is None else _num(v)


def _n1(v):
    from ..ownership import _num

    n = _num(v)
    return n if n is not None and n >= 1 else None


class OwnerRules:
    def _ownership(self, cx: sqlite3.Connection) -> None:
        """Each of the five tables by its own rule (see ownership.py's notes; DESIGN-roles §4): a record of who the
        owner is that is not held is added, and one held is never replaced (changed after review, C1: two records of
        one writer for one place live side by side, and the second is a question); a proposal is added, and one its
        maker took back is taken back here; of two answers, two rows about a document or two roles by one writer, the
        higher number stays (equal and different: the smaller digest). Which of them counts is worked out when they
        are read, alike in every copy; then this copy pins what it follows without a click (`ownership.pin_owner`).
        Then the documents this merge must not bring back (`not_wanted`) are known.

        A row written in this person's name (`by`) comes from this copy and from nowhere else: one in a colleague's
        file that this copy does not hold is not taken (a record of who the owner is, a role, a proposal, an answer, a
        row of the documents), and it is recorded (`sync_refused`, ownership.record_refused): this copy answers it with
        its own row (`ownership.settle`) and the Team tab says so. So is an event said to be this person's (`*_by`) in
        another writer's row that this copy never made (review, C2). A number that is not an integer in 0 … 2**53, or
        that is more than `STEP` above the highest number held here, is not taken (review, H2)."""
        from .. import ownership

        self.not_wanted: set[str] = set()
        there = {r[0] for r in self.icx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rep = self.r.setdefault("proposals", {"new": [], "decided": 0, "owner": None})
        if {"ownership", "proposals", "decisions", "canon"} <= there:
            me, via = self.me, self.sender["id"]
            before = ownership.owner(cx)
            refused: list[tuple] = []
            # who the owner is: a record not held is added; none held is ever replaced
            held = {(r["seq"], r["by"], r["owner"]) for r in _rows(cx, "SELECT seq, by, owner FROM ownership")}
            cols = _cols(cx, "ownership")
            for r in _rows(self.icx, "SELECT * FROM ownership"):
                k = (r.get("seq"), r.get("by"), r.get("owner"))
                if k in held:
                    continue
                if r.get("by") == me:
                    refused.append(("ownership", f"{r.get('seq')}|{r.get('owner')}", r,
                                    r.get("seq") if isinstance(r.get("seq"), int) else None))
                    continue
                cx.execute(f"INSERT OR IGNORE INTO ownership({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                           [r.get(c) for c in cols])
                held.add(k)
            # proposals
            have = {r[0]: r[1] for r in cx.execute("SELECT id, taken_back_at FROM proposals")}
            for p in _rows(self.icx, "SELECT * FROM proposals"):
                if p.get("by") == me:
                    if p["id"] not in have:
                        refused.append(("proposals", p["id"], p, None))
                    continue
                self._via_proposal(cx, p, p["id"] not in have)  # roles-p2: a third person's proposal is "via" (§4.8)
                if p["id"] not in have:
                    self._insert(cx, "proposals", [p])
                    if not p["taken_back_at"]:
                        rep["new"].append({"id": p["id"], "kind": p["kind"], "title": p["title"], "by": p["by"]})
                elif p["taken_back_at"] and not have[p["id"]]:
                    cx.execute("UPDATE proposals SET taken_back_at=? WHERE id=?", (p["taken_back_at"], p["id"]))
            # answers, rows of the documents, roles: one row per key and writer, the higher number stays. A writer
            # numbers each row above every row of its own (`_Ctx.put`, `_own_role_n`), so the number alone says which
            # is newer; the place a row names does not (0.18.1: rival take-overs settled on an earlier place made the
            # owner's new rows of that place lose, in every other copy, to their own older rows of a later place)
            rep["decided"] = self._own_rows(cx, "decisions", ("proposal", "by"), lambda r: (_n0(r.get("n")),),
                                            refused)
            self._own_rows(cx, "canon", ("doc", "by"), lambda r: (_n1(r.get("n")),), refused)
            if "roles" in there:
                self._own_rows(cx, "roles", ("person", "by"), lambda r: (_n1(r.get("n")),), refused)
            refused += self._events_in_my_name(cx)
            for kind, key, row, n in refused:
                ownership.record_refused(cx, kind, key, row, via, n)
            ownership.pin_owner(cx, me)
            ownership.note_format(cx, via, self.format_in)
            after = ownership.owner(cx)
            if after != before:
                rep["owner"] = after
        self.not_wanted = ownership.not_wanted(cx, self.me)

    def _own_rows(self, cx: sqlite3.Connection, table: str, key: tuple[str, str], rank, refused: list) -> int:
        """Merge `table` (one row per `key`): a colleague's row replaces the one held when its `rank` is higher, or
        equal with a smaller digest of a different row; a row in this person's name is refused unless held as it is
        (or an older one of it). A row whose number is not taken (`rank` None) is left out. Returns the rows taken."""
        from ..ownership import _digest, _num

        cols = _cols(cx, table)
        rows_here = _rows(cx, f"SELECT * FROM {table}")
        held = {tuple(r[c] for c in key): r for r in rows_here}
        nums = [c for c in _NUM_COLS.get(table, ()) if c in cols]
        top = max([_num(r.get(c)) or 0 for r in rows_here for c in nums] + [0])
        taken = 0
        for r in _rows(self.icx, f"SELECT * FROM {table}"):
            rk = rank(r)
            if any(x is None for x in rk):
                continue
            if any((_num(r.get(c)) or 0) > top + STEP for c in nums):
                # a number far above every number held here: not taken. Taken, the next numbers would run to the top of
                # the range in a few files, and no row could be written above them (review, H2)
                rep = self.r.setdefault("proposals", {"new": [], "decided": 0, "owner": None})
                rep["too_high"] = rep.get("too_high", 0) + 1
                continue
            k = tuple(r.get(c) for c in key)
            h = held.get(k)
            same = h is not None and all(h.get(c) == r.get(c) for c in cols if c in r)
            if h is not None:
                hk = rank(h)
                hk = tuple(x if x is not None else -1 for x in hk)
            if r.get("by") == self.me:
                if h is None or (not same and rk >= hk):
                    refused.append((table, str(k[0]), r, rk[-1]))
                continue
            if h is None or rk > hk or (rk == hk and not same and
                                        _digest({c: r.get(c) for c in cols}) < _digest({c: h.get(c) for c in cols})):
                cx.execute(f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                           [r.get(c) for c in cols])
                held[k] = {c: r.get(c) for c in cols}
                taken += 1
        return taken

    def _events_in_my_name(self, cx: sqlite3.Connection) -> list[tuple]:
        """Events said to be this person's (`state_by`, `read_by`, `ai_by`, `blocks_by` = this copy's person) in rows of
        `canon` written by someone else, which this copy never made: its own row of that document neither has the
        event nor lists it (review, C2). They are recorded like a row in this person's name; the rules never take them
        for this person's own word (`ownership._Ctx.made_here`)."""
        import json

        from ..ownership import PARTS, _num

        out = []
        mine: dict[str, set] = {}
        for r in _rows(cx, "SELECT * FROM canon WHERE by=?", (self.me,)):
            ev = set()
            hist = json.loads(r.get("hist_json") or "{}") if (r.get("hist_json") or "").startswith("{") else {}
            for p in PARTS:
                ev.add((r.get(f"{p}_n"), r.get(f"{p}_by") or self.me))
                for h in (hist.get(p) or []) if isinstance(hist, dict) else []:
                    if isinstance(h, list) and len(h) == 2:
                        ev.add((h[0], h[1]))
            try:
                for h in json.loads(r.get("ai_hist_json") or "[]"):
                    if isinstance(h, list) and len(h) >= 2:
                        ev.add((h[0], h[2] if len(h) == 3 else self.me))
            except (TypeError, ValueError):
                pass
            mine[r["doc"]] = ev
        for r in _rows(self.icx, "SELECT * FROM canon WHERE by != ?", (self.me,)):
            for p in PARTS:
                n = _num(r.get(f"{p}_n"))
                if r.get(f"{p}_by") == self.me and n and (n, self.me) not in mine.get(r["doc"], set()):
                    out.append(("event", f"{r['doc']}|{p}|{n}", {"doc": r["doc"], "part": p, "n": n, "row_by": r["by"],
                                                                "title": r.get("title")}, n))
        return out

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
            if ch:
                R = ownership.roles(cx, ch)
                dec = ownership._decisions(cx, ch, R)
                self._owner_state = (ch, ownership.canon(cx, ch, R, dec), dec, ownership._proposals(cx))
            else:
                self._owner_state = None
        if self._owner_state is None:
            return None
        ch, K, dec, props = self._owner_state
        k = K.get(doc)
        if k is not None and k["state"] == "removed" and \
                not ownership.made_here(cx, self.me, doc, "state", (k["state_n"], k["state_by"])):
            return "owner"  # (DESIGN-roles §4.6 row 14: the removal is the project's, by someone else's word)
        for p in props.values():
            if p["doc"] != doc:
                continue
            st = ownership.state_of(p, K, dec)[0]
            if p["kind"] == "remove" and p["by"] == self.sender["id"] and st == "waiting":
                return "proposed"
            if p["kind"] == "add" and p["by"] == self.me and k is None and st in ("declined", "taken_back"):
                return st
        return None
