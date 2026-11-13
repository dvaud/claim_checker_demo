"""Roles (DESIGN-roles §6.3): a seeded, deterministic run of an Owner, two Co-owners and two Members.

Five copies of one small project, one shared folder, `random.Random(seed)`, 60 steps. A step is one of: add a
document, remove one, make one stricter or looser for AI, leave out or restore a block, read one again; the Owner sets
a role (also demotes and promotes again) or hands the project over; a writer accepts or declines a proposal (also one
answered both ways), a proposer takes one back; a person answers an offer of a looser setting (allow or keep); a round
of the shared folder for a random subset in a random order; a zip from one copy to another, the same zip again, an
older zip later. Person ids are fixed per seed, and the app's clock is a counter.

0.18.1 added:
- *Take-overs*: a Co-owner, or a Member when no Co-owner was heard of lately, takes the project over
  (`ownership.take_over`). The app's wall-clock questions are made deterministic for the run: `owner_left` says the owner
  left only while a take-over is tried (for the owner that copy's person believes in), and `_co_heard_lately` is a coin
  the seeded generator tosses (no Co-owner heard of lately, or one was). A refusal must agree with that (a Co-owner is
  never refused; a Member is refused exactly when a Co-owner was heard of). The other copies are then asked who owns
  the project: a person follows, keeps their owner (`keep_owner`) or says *Not now* (`put_off`) -- also the other way
  round, a copy that has not heard of the take-over at all. The former owner goes on working offline for a few steps
  (no round of theirs, but every other step), which is the interesting case.
- *Zips*: besides any zip between any two copies, a zip from a former owner (by take-over or hand-over) to the new
  owner, and one the other way.
- *The documents switch*: a copy turns `folder.set_keep_out` on or off. A person's switch changes only by their own
  step.
- *The Team tab opened offline*: a copy settles and views (the look writes proposals and rows without exchanging) and
  then does no round for a few steps.

After every step:
(b) no copy's level of a document got looser except by a recorded click of its own person (their own setting, their
    own accept, *Allow here*, or their own proposal of that level);
(c) no document left a copy except by its person's own removal (this step), or by the word of someone who, in that
    copy's own view after the step, is the owner or a Co-owner. The removal's cause is read from `removed_docs` (the
    archive every removal by a colleague's word makes: who, when, why), which must be new this step. A late word of a
    former owner (a person whom the copy no longer follows as the owner, or who is only a Member there) removes
    nothing.
At the end every open question about the owner is answered (also one a person kept or put off), all copies following
the same record for each place (the earliest place first, the smallest writer id among rival records; ids, never
times), then, after open offers are allowed and rounds until no copy writes a file or a row (at most 5;
`ENLENS_ROLES_ROUNDS` allows more):
(a) all copies compute the same owner, roles and documents, and every copy holds the project's documents at the
    project's levels but for kept offers and its own proposals;
(d) the last round wrote no row of `canon`, `decisions` or `roles`;
(e) no `at` decided anything: the run again, with every copy's clock shifted by its own number of days, ends with the
    same documents.

The default run is 2 seeds on this computer, 10 in CI (`CI` set) and 30 in the nightly run (`ENLENS_LONG_RANDOM=1`, or
`ENLENS_L2_LONG=1`); `ENLENS_ROLES_SEEDS`, `ENLENS_ROLES_STEPS` and `ENLENS_ROLES_FIRST_SEED` set each. Marked `heavy`
(each seed writes ~600 MB): a local run of the whole suite leaves it out. A failure names its seed and step and prints the last actions.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import random
import sys
from pathlib import Path

import pytest

from enlens_claims import access, ingest, ownership, people, removed, reread, store
from enlens_claims.sync import folder
from owner_helpers import TEXTS, leave_out
from owner_more_helpers import join_zip, send, small_project
from roles_helpers import OLD
from test_0_14_0_shared_projects import Person

LONG = "1" in (os.environ.get("ENLENS_LONG_RANDOM"), os.environ.get("ENLENS_L2_LONG"))
SEEDS = int(os.environ.get("ENLENS_ROLES_SEEDS") or (30 if LONG else 10 if os.environ.get("CI") else 2))
STEPS = int(os.environ.get("ENLENS_ROLES_STEPS") or 60)
FIRST = int(os.environ.get("ENLENS_ROLES_FIRST_SEED") or 0)
NAMES = ("Anna", "Ben", "Carol", "Dana", "Eve")
RANK = ownership.RANK
LEVELS = ("cloud", "local", "none")
POOL = {"interview": TEXTS["interview"], "old": OLD,
        "brief": ("Hydrogen export policy brief\n\nExport agreements for green hydrogen name water use only in passing. "
                  "Few of them say who pays for desalination.\n\nPorts need new terminals for ammonia, which take "
                  "five to eight years to permit and build.\n")}


class Fixed(Person):
    def __init__(self, tmp: Path, name: str, monkeypatch, pid: str):
        self.name, self.home, self.mp = name, tmp / f"home-{name}", monkeypatch
        self.ws = None
        self.files = tmp / f"sent-{name}"
        self.files.mkdir(parents=True)
        self.n = 0
        with self:
            from enlens_claims import home

            home.update_settings({"your_name": name, "person_id": pid})
            self.id = people.me()


class Run:
    def __init__(self, tmp: Path, mp, seed: int):
        self.tmp, self.seed = tmp, seed
        self.rng = random.Random(seed)
        self.leaving: str | None = None          # the owner a take-over is being tried against (`owner_left` says "left")
        self.quiet = True                        # whether no Co-owner was heard of lately (`_co_heard_lately` says not)
        self.offline: dict[str, int] = {}        # name -> steps left without a round of their own
        self.former: list[tuple[str, str]] = []  # (former owner, new owner) by take-over or hand-over, by name
        self.switched: set[str] = set()          # names who turned the documents switch this step
        mp.setattr(ownership, "owner_left", lambda ws, cx, ch: ("Nothing was heard of the owner for 20 days."
                                                                if ch and self.leaving == ch[-1]["owner"] else None))
        mp.setattr(ownership, "_co_heard_lately", lambda cx, ch, me: not self.quiet)
        self.step = 0
        self.trail: list[str] = []
        self.clicks: set[tuple[str, str, str]] = set()     # (person, doc, level) loosened by their own click
        self.removed_by: set[tuple[str, str]] = set()      # (person, doc) removed by their own hand this step
        self.zips: list[tuple[str, Path]] = []
        self.shared = tmp / "Közös mappa"
        self.shared.mkdir(parents=True)
        ids = sorted("p" + hashlib.sha1(f"roles-{seed}-{n}".encode()).hexdigest()[:12] for n in NAMES)
        self.people = [Fixed(tmp, n, mp, ids[i]) for i, n in enumerate(NAMES)]
        anna = self.people[0]
        small_project(anna, tmp / "anna-project")
        self.add(anna, "old", reader=1)
        for p in self.people[1:]:
            join_zip(p, anna, tmp / f"{p.name}-project")
        for p in self.people:
            with p:
                folder.set_folder(p.ws, str(self.shared))
        for _ in range(2):
            for p in self.people:
                self.sync(p)
        for p in self.people[1:3]:
            with anna:
                ownership.set_role(anna.ws, p.id, "co")
        for p in self.people:
            self.sync(p)

    # ---- small things ---------------------------------------------------------------------------------------------
    def say(self, p: Person, what: str) -> None:
        self.trail.append(f"[{self.step}] {p.name}: {what}")

    def fail(self, msg: str) -> None:
        tail = "\n  ".join(self.trail[-int(os.environ.get("ENLENS_L2_TAIL") or 40):])
        pytest.fail(f"seed {self.seed}, step {self.step}: {msg}\n  last actions:\n  {tail}", pytrace=False)

    def check(self, ok: bool, msg: str) -> None:
        if not ok:
            self.fail(msg)

    def docs(self, p: Person) -> list[str]:
        with p:
            return sorted(r[0] for r in p.ws.query("SELECT doc_id FROM documents"))

    def levels(self, p: Person) -> dict[str, str]:
        with p:
            return dict(folder.ai_settings(p.ws, p.ws._conn()))

    def view(self, p: Person) -> dict:
        with p:
            ownership.settle(p.ws, apply=False)
            return ownership.view(p.ws)

    def sync(self, p: Person) -> dict:
        with p:
            r = folder.sync_now(p.ws)
            bad = [x for x in r["problems"] if x["kind"] not in ("documents",)]
            self.check(not bad, f"{p.name}'s round had problems: {bad}")
            for d in r.get("moves_due") or []:
                ownership.move_now(p.ws, d)
        self.say(p, f"synced (wrote {(r.get('wrote') or {}).get('seq')})")
        return r

    def add(self, p: Person, key: str, reader: int | None = None, ai: str | None = None) -> None:
        d = self.tmp / f"added-{p.name}"
        d.mkdir(exist_ok=True)
        f = d / f"{key}.txt"
        f.write_text(POOL[key], encoding="utf-8")
        with p:
            was = ingest.READER
            if reader is not None:
                ingest.READER = reader
            try:
                ingest.ingest(p.ws, [f], **({"ai_access": ai} if ai else {}))
            finally:
                ingest.READER = was

    # ---- steps ----------------------------------------------------------------------------------------------------
    def s_add(self, p: Person) -> None:
        held = {self.doc_of(k) for k in POOL} & set(self.docs(p))
        keys = sorted(k for k in POOL if self.doc_of(k) not in held)
        if keys:
            k = self.rng.choice(keys)
            ai = self.rng.choice([None, "local", "none"])
            self.add(p, k, reader=1 if k == "old" else None, ai=ai)
            self.say(p, f"added {k} ({self.doc_of(k)}, ai {ai})")

    def name_of(self, pid: str) -> str:
        return next(q.name for q in self.people if q.id == pid)

    def person(self, name: str) -> Person:
        return next(q for q in self.people if q.name == name)

    def doc_of(self, key: str) -> str:
        return "d" + hashlib.sha1(POOL[key].encode("utf-8")).hexdigest()[:10]

    def s_remove(self, p: Person) -> None:
        docs = self.docs(p)
        if len(docs) >= 3:
            d = self.rng.choice(docs)
            with p:
                p.ws.remove_document(d, why="random")
            self.removed_by.add((p.name, d))
            self.say(p, f"removed {d}")

    def s_level(self, p: Person, looser: bool) -> None:
        lv = self.levels(p)
        docs = [d for d in self.docs(p) if (RANK[lv.get(d, "none")] > 0) == looser]
        if not docs:
            return
        d = self.rng.choice(docs)
        now = RANK[lv.get(d, "none")]
        to = self.rng.choice([x for x in LEVELS if (RANK[x] < now if looser else RANK[x] > now)])
        with p:
            access.set_documents(p.ws, [d], setting=to)
        if looser:
            self.clicks.add((p.name, d, to))
        self.say(p, f"set {d} {lv.get(d)} -> {to}")

    def s_blocks(self, p: Person) -> None:
        with p:
            rows = p.ws.query("SELECT doc_id, included, COUNT(*) FROM blocks GROUP BY doc_id, included ORDER BY doc_id, "
                              "included")
        opts = [(r[0], bool(1 - r[1]), r[2]) for r in rows]
        if opts:
            d, restore, n = self.rng.choice(opts)
            k = self.rng.randrange(n)
            leave_out(p, d, k, included=restore)
            self.say(p, f"{'restored' if restore else 'left out'} block {k} of {d}")

    def s_reread(self, p: Person) -> None:
        with p:
            docs = [r[0] for r in p.ws.query("SELECT doc_id FROM documents WHERE COALESCE(reader, 1) < ? ORDER BY "
                                             "doc_id", (ingest.READER,))]
            docs = [d for d in docs if reread.check(p.ws, d)["ok"]]
        if docs:
            d = self.rng.choice(docs)
            with p:
                reread.move(p.ws, d, p.id)
            self.say(p, f"read {d} again")

    def s_role(self, p: Person) -> None:
        v = self.view(p)
        if not v["can_set_roles"]:
            return
        others = sorted(x["id"] for x in v["people"] if not x["me"] and not x["owner"] and
                        x["id"] in {q.id for q in self.people})
        if others:
            who = self.rng.choice(others)
            role = "member" if next(x for x in v["people"] if x["id"] == who)["role"] == "co" else "co"
            with p:
                ownership.set_role(p.ws, who, role)
            self.say(p, f"made {who} {role}")

    def s_hand_over(self, p: Person) -> None:
        v = self.view(p)
        if not v["is_owner"]:
            return
        others = sorted(x["id"] for x in v["people"] if not x["me"] and x["id"] in {q.id for q in self.people})
        if others:
            to = self.rng.choice(others)
            with p:
                ownership.hand_over(p.ws, to, "random")
            self.former.append((p.name, self.name_of(to)))
            self.say(p, f"handed over to {to}")

    def s_decide(self, p: Person) -> None:
        v = self.view(p)
        ws = sorted((x for x in v["proposals"] if x["can_decide"]), key=_key)
        if not ws:
            return
        q = self.rng.choice(ws)
        yes = self.rng.random() < 0.6
        with p:
            if yes:
                ownership.accept(p.ws, q["id"])
                for d in ownership.moves_due(p.ws):
                    ownership.move_now(p.ws, d)
            else:
                ownership.decline(p.ws, q["id"], "random")
        if yes and q["kind"] == "loosen":
            self.clicks.add((p.name, q["doc"], q["detail"]["to"]))
        self.say(p, f"{'accepted' if yes else 'declined'} {q['kind']} of {q['doc']} by {q['by']['name']}"
                    + (" (answered both ways)" if q["clash"] else ""))

    def s_both(self, p: Person) -> None:
        """Two writers answer one proposal differently, neither knowing the other's answer."""
        can = {q.name: {x["id"]: x for x in self.view(q)["proposals"] if x["can_decide"]} for q in self.people}
        pairs = sorted(((a.name, b.name) + _key(can[a.name][pid]), pid) for a in self.people for b in self.people
                       if a is not b for pid in set(can[a.name]) & set(can[b.name]))
        if not pairs:
            return
        (a, b, *_k), pid = self.rng.choice(pairs)
        pa, pb = (next(q for q in self.people if q.name == n) for n in (a, b))
        q = can[a][pid]
        with pa:
            ownership.accept(pa.ws, pid)
            for d in ownership.moves_due(pa.ws):
                ownership.move_now(pa.ws, d)
        with pb:
            ownership.decline(pb.ws, pid, "random")
        if q["kind"] == "loosen":
            self.clicks.add((a, q["doc"], q["detail"]["to"]))
        self.say(pa, f"accepted {q['kind']} of {q['doc']} by {q['by']['name']}, while {b} declined it")

    def s_take_back(self, p: Person) -> None:
        v = self.view(p)
        ws = sorted((x for x in v["proposals"] if x["can_take_back"]), key=_key)
        if ws:
            q = self.rng.choice(ws)
            with p:
                ownership.take_back(p.ws, q["id"])
            self.say(p, f"took back {q['kind']} of {q['doc']}")

    def s_offer(self, p: Person, every: bool = False) -> None:
        offers = sorted(o["doc"] for o in self.view(p)["offers"])
        for d in (offers if every else offers[:1] if offers and self.rng.random() < 0.8 else []):
            yes = every or self.rng.random() < 0.7
            to = next(o["to"] for o in self.view(p)["offers"] if o["doc"] == d)
            with p:
                ownership.answer_loosening(p.ws, [d], yes)
            if yes:
                self.clicks.add((p.name, d, to))
            self.say(p, f"{'allowed' if yes else 'kept stricter'} {d} ({to})")

    def s_rounds(self, p: Person) -> None:
        for q in self.rng.sample(self.people, self.rng.randint(1, 3)):
            if q.name not in self.offline:      # (a copy working offline has no round)
                self.sync(q)

    def s_zip(self, p: Person) -> None:
        to = self.rng.choice([q for q in self.people if q is not p])
        if self.zips and self.rng.random() < 0.3:
            name, f = self.rng.choice(self.zips)      # the same zip again, or an older one, later
            if name == to.name:
                return
        else:
            f = send(p)
            self.zips.append((p.name, f))
        to.bring_in(f)
        with to:
            for d in ownership.moves_due(to.ws):
                ownership.move_now(to.ws, d)
        self.say(to, f"brought in {f.name}")

    # ---- 0.18.1: take-overs, the questions they ask, the documents switch, the Team tab offline ---------------------
    def s_take_over(self, p: Person) -> None:
        v = self.view(p)
        if v["is_owner"] or not v["owner"]:
            return
        old = v["owner"]["id"]
        member = v["role"] != "co"
        self.leaving, self.quiet = old, self.rng.random() < 0.5
        try:
            with p:
                ownership.take_over(p.ws, "random")
            refused = None
        except ownership.NotAllowed as e:
            refused = str(e)
        finally:
            self.leaving = None
        if refused is not None:
            self.check(member and not self.quiet, f"{p.name} ({v['role']}) was refused a take-over: {refused}")
            self.say(p, f"tried to take over from {self.name_of(old)}: refused (a Co-owner was heard of)")
            return
        self.check(not member or self.quiet, f"{p.name} (a Member) took the project over though a Co-owner was heard of")
        self.check(self.view(p)["is_owner"], f"{p.name} took the project over and is not its owner")
        self.former.append((self.name_of(old), p.name))
        gone = self.person(self.name_of(old))
        if gone is not p:
            self.offline[gone.name] = self.rng.randint(2, 6)   # the former owner goes on working, offline
        self.say(p, f"took the project over from {gone.name} ({v['role']}); {gone.name} offline for "
                    f"{self.offline.get(gone.name)} steps")

    def s_answer_owner(self, p: Person) -> None:
        """A person answers a question about who owns the project: follow, keep their owner, or *Not now*."""
        qs = sorted(self.view(p)["questions"], key=lambda q: (q["seq"], q["by"]))
        if not qs:
            return
        q = self.rng.choice(qs)
        how = self.rng.choices(["follow", "keep", "later"], [5, 2, 3])[0]
        with p:
            if how == "follow":
                ownership.follow_owner(p.ws, q["seq"], q["by"])
                for d in ownership.moves_due(p.ws):
                    ownership.move_now(p.ws, d)
            elif how == "keep":
                ownership.keep_owner(p.ws, q["seq"], q["by"])
            else:
                ownership.put_off(p.ws, q["id"])
        self.say(p, f"{how} {q['kind']} of place {q['seq']} by {self.name_of(q['by'])} (owner {self.name_of(q['owner'])})")

    def s_keep_out(self, p: Person) -> None:
        on = self.rng.random() < 0.5
        with p:
            folder.set_keep_out(p.ws, on)
        self.switched.add(p.name)
        self.say(p, f"documents switch {'on' if on else 'off'}")

    def s_team_tab(self, p: Person) -> None:
        """The Team tab opened in a copy that then does no round for a while (its look writes without exchanging)."""
        self.view(p)
        self.offline[p.name] = max(self.offline.get(p.name, 0), self.rng.randint(1, 5))
        self.say(p, f"opened the Team tab, offline for {self.offline[p.name]} steps")

    def s_zip_owner(self, p: Person) -> None:
        """A zip between a former owner and the new one (either way), also an old one later."""
        if not self.former:
            return
        old, new = (self.person(n) for n in self.rng.choice(self.former))
        src, to = (old, new) if self.rng.random() < 0.5 else (new, old)
        if src is to:
            return
        f = send(src)
        self.zips.append((src.name, f))
        to.bring_in(f)
        with to:
            for d in ownership.moves_due(to.ws):
                ownership.move_now(to.ws, d)
        self.say(to, f"brought in {f.name} (a zip of {src.name}, between a former owner and the new one)")

    STEPS = (("add", 2), ("remove", 2), ("tighten", 2), ("loosen", 3), ("blocks", 2), ("reread", 1), ("role", 1),
             ("hand_over", 0.3), ("decide", 5), ("both", 3), ("take_back", 1), ("offer", 2), ("rounds", 4),
             ("zip", 2), ("take_over", 3), ("answer_owner", 6), ("keep_out", 2), ("team_tab", 2), ("zip_owner", 2))

    def one_step(self) -> None:
        self.step += 1
        before = {p.name: self.snapshot(p) for p in self.people}
        self.removed_by, self.switched = set(), set()
        for n in list(self.offline):
            self.offline[n] -= 1
            if self.offline[n] <= 0:
                del self.offline[n]
        a = self.rng.choices([a for a, _w in self.STEPS], [w for _a, w in self.STEPS])[0]
        p = self.rng.choice(self.people)
        if a in ("role", "hand_over", "decide", "take_over", "answer_owner"):  # (by someone who may, as far as their
            # copy knows)
            def may_do(q: Person) -> bool:
                v = self.view(q)
                if a == "decide":
                    return any(x["can_decide"] for x in v["proposals"])
                if a == "take_over":
                    return not v["is_owner"]
                if a == "answer_owner":
                    return bool(v["questions"])
                return v["is_owner"]

            may = [q for q in self.people if may_do(q)]
            if not may:
                self.after_step(before)
                return
            p = self.rng.choice(may)
        if a in ("tighten", "loosen"):
            self.s_level(p, looser=a == "loosen")
        else:
            getattr(self, f"s_{a}")(p)
        self.after_step(before)

    def snapshot(self, p: Person) -> tuple:
        """What a copy held before a step: its documents, its levels, its removal archives (`removed_docs`), its switch."""
        with p:
            archives = {r[0]: tuple(r[1:]) for r in p.ws.query("SELECT doc_id, at, by, cause, archive FROM removed_docs")}
            switch = bool(folder.keep_out_state(p.ws)["mine"])
        return set(self.docs(p)), self.levels(p), archives, switch

    def after_step(self, before: dict) -> None:
        for p in self.people:
            docs_was, lv_was, arch_was, switch_was = before[p.name]
            docs_now, lv_now = set(self.docs(p)), self.levels(p)
            with p:
                arch = {r[0]: tuple(r[1:]) for r in p.ws.query("SELECT doc_id, at, by, cause, archive FROM "
                                                               "removed_docs")}
                switch = bool(folder.keep_out_state(p.ws)["mine"])
                owner = ownership.owner(p.ws._conn())
                role = {x: ownership.role_of(p.ws._conn(), x) for x in {r[1] for r in arch.values() if r[1]}}
            # (b) no looser level but by a click of this copy's own person
            for d in docs_was & docs_now:
                a, b = lv_was.get(d), lv_now.get(d)
                if a and b and RANK[b] < RANK[a]:  # (a click asking for more may get less: a Member's is held)
                    self.check(any(RANK[b] >= RANK[c] for x, y, c in self.clicks if (x, y) == (p.name, d)),
                               f"{p.name}'s copy loosened {d} ({a} -> {b}) without a click of theirs")
            # (b) a person's documents switch changes only by their own hand
            self.check(switch == switch_was or p.name in self.switched,
                       f"{p.name}'s documents switch went {'on' if switch else 'off'} without them")
            # (c) no document left but by its person's own removal, or by the word of someone who, in this copy's own view
            # after the step, is the owner or a Co-owner (the cause is the archive this step made of it)
            for d in docs_was - docs_now:
                if (p.name, d) in self.removed_by:
                    continue
                row = arch.get(d)
                self.check(row is not None and row != arch_was.get(d),
                           f"{p.name}'s copy lost {d} with no removal of its own and no word recorded for it")
                at, by, cause, _archive = row
                self.check(by is not None and role.get(by) in ("owner", "co"),
                           f"{p.name}'s copy lost {d} by the word of {self.name_of(by) if by in {q.id for q in self.people} else by}"
                           f" ({cause}), who is {role.get(by)} in {p.name}'s view (owner there: "
                           f"{self.name_of(owner) if owner else None})")

    # ---- the end --------------------------------------------------------------------------------------------------
    def follow_all(self, p: Person) -> None:
        """Answer every question about the owner (also one the person kept or put off): this copy follows, place by
        place, the record the copies agree on: of the rival records for a place, the smallest writer id (then owner id)."""
        every: dict[int, list[tuple]] = {}
        for q in self.people:
            with q:
                for seq, by, own, after in q.ws.query("SELECT seq, by, owner, after FROM ownership"):
                    every.setdefault(seq, []).append((by, own, after))
        prev, seq, want = None, 1, []
        while True:
            c = sorted(r for r in set(every.get(seq, [])) if (r[2] or None) == prev)
            if not c:
                break
            want.append((seq, c[0][0], c[0][2]))
            prev, seq = c[0][1], seq + 1
        with p:
            for seq, by, after in want:
                ch = ownership.chain(p.ws._conn())
                if len(ch) >= seq and ch[seq - 1]["by"] == by and not [x for x in ownership.owner_questions(p.ws._conn())
                                                                      if x["seq"] == seq]:
                    continue
                if not p.ws.query("SELECT 1 FROM ownership WHERE seq=? AND by=? AND after IS ?", (seq, by, after)):
                    return      # (the record has not reached this copy yet: a later round, a later try)
                ownership.follow_owner(p.ws, seq, by)
                for d in ownership.moves_due(p.ws):
                    ownership.move_now(p.ws, d)
        self.say(p, "followed the agreed record of every place")

    def quiesce(self) -> dict:
        self.step += 1
        self.offline.clear()
        for _ in range(3):
            for p in self.people:
                self.sync(p)
            for p in self.people:
                self.follow_all(p)
            for p in self.people:
                self.s_offer(p, every=True)
        last = None
        for p in self.people:
            self.follow_all(p)
            self.check(not self.view(p)["questions"], f"{p.name} is still asked: {self.view(p)['questions']}")
        for _ in range(5):
            last = {p.name: _rows(p) for p in self.people}
            wrote = any((self.sync(p).get("wrote") or {}).get("seq") is not None for p in self.people)
            # (a round may write a row of its own that only the next round sends: it is not the last one then)
            if not wrote and {p.name: _rows(p) for p in self.people} == last:
                break
        else:
            self.fail("the copies still wrote after the rounds allowed")
        # (d) the last round wrote no row of the tables that decide
        self.check({p.name: _rows(p) for p in self.people} == last, "the last round wrote rows")
        # (a) one project, held as it says
        got = {p.name: _project(p) for p in self.people}
        first = got[self.people[0].name]
        for p in self.people[1:]:
            self.check(got[p.name] == first, f"{p.name} computes another project than {self.people[0].name}: "
                                             f"{_diff(got[p.name], first)}")
        for p in self.people:
            v = self.view(p)
            self.check(not v["questions"], f"{p.name} is still asked: {v['questions']}")
            lv = self.levels(p)
            with p:
                kept = {r[0] for r in p.ws.query("SELECT doc FROM canon_seen WHERE ai_offer LIKE '%\"kept\"%'")}
            mine = {(q["kind"], q["doc"]) for q in v["proposals"] if q["mine"] and q["state"] in
                    ("waiting", "declined", "taken_back", "replaced")}
            for d, (state, _reader, ai, _blocks) in first["canon"].items():
                if state == "in" and d in lv and d not in kept and ("loosen", d) not in mine:
                    self.check(RANK[lv[d]] >= RANK[ai], f"{p.name} lets more AI read {d} ({lv[d]}) than the project "
                                                        f"({ai})")
                    if not any(x[1] == d for x in mine) and lv[d] != ai:
                        # a known limit (P1's report): a stricter setting a Co-owner made, which spread before they
                        # were made a Member and their row stopped counting, stays in a copy that took it (stricter)
                        with p:
                            lost = {r[0] for r in p.ws.query("SELECT ai_access FROM canon WHERE doc=? AND grant IS "
                                                             "NOT NULL", (d,))}
                        self.check(lv[d] in lost and RANK[lv[d]] > RANK[ai],
                                   f"{p.name} reads {d} at {lv[d]}, the project at {ai}")
        return first["canon"]


def _key(q: dict) -> tuple:
    """A proposal's place in a list to choose from, the same whatever the clocks say (its id and a removal's detail
    hold a time)."""
    det = {k: v for k, v in q["detail"].items() if k != "removed_at"}
    return (q["kind"], q["doc"], q["by"]["id"], json.dumps(det, sort_keys=True))


def _rows(p: Person) -> dict:
    with p:
        cx = p.ws._conn()
        return {t: sorted(tuple(r) for r in cx.execute(f"SELECT {k}, by, n FROM {t}"))
                for t, k in (("canon", "doc"), ("decisions", "proposal"), ("roles", "person"))}


def _project(p: Person) -> dict:
    with p:
        cx = p.ws._conn()
        ch = ownership.chain(cx)
        K = ownership.canon(cx, ch)
        R = ownership.roles(cx, ch)
    return {"owner": ch[-1]["owner"] if ch else None, "roles": {x: r["role"] for x, r in R.items()},
            "canon": {d: (k["state"], k["reader"] or 1, k["ai_access"], json.dumps(k["blocks"], sort_keys=True))
                      for d, k in K.items()}}


def _diff(a: dict, b: dict) -> dict:
    out = {}
    for k in set(a) | set(b):
        if isinstance(a.get(k), dict) and isinstance(b.get(k), dict):
            sub = _diff(a[k], b[k])
            if sub:
                out[k] = sub
        elif a.get(k) != b.get(k):
            out[k] = (a.get(k), b.get(k))
    return out


def _clock(monkeypatch, shift: dict[str, int]) -> None:
    """The app's clock made a counter (one second later at each call), shifted per copy by `shift[home]` days."""
    real = store.now
    t = [dt.datetime(2026, 11, 12, 9, 0, tzinfo=dt.timezone.utc)]

    def fake() -> str:
        t[0] += dt.timedelta(seconds=1)
        home = os.environ.get("ENLENS_HOME") or ""
        return (t[0] + dt.timedelta(days=shift.get(Path(home).name, 0))).isoformat()

    for name, mod in list(sys.modules.items()):
        if name.startswith("enlens_claims") and getattr(mod, "now", None) is real:
            monkeypatch.setattr(mod, "now", fake)
    # (a removal's archive is named and dated by its own clock: the test's too, so two never share a name)
    monkeypatch.setattr(removed, "_now", lambda: dt.datetime.fromisoformat(fake()).replace(microsecond=0))


def _run(tmp: Path, monkeypatch, seed: int, shift: dict[str, int]) -> dict:
    with monkeypatch.context() as mp:
        _clock(mp, shift)
        run = Run(tmp, mp, seed)
        for _ in range(STEPS):
            run.one_step()
        return run.quiesce()


@pytest.mark.heavy
@pytest.mark.random
@pytest.mark.parametrize("seed", list(range(FIRST, FIRST + SEEDS)))
def test_a_random_run_of_owner_co_owners_and_members_keeps_the_rules(seed, tmp_path, monkeypatch):
    plain = _run(tmp_path / "a", monkeypatch, seed, {})
    rng = random.Random(seed + 1000)
    shifted = _run(tmp_path / "b", monkeypatch, seed, {f"home-{n}": rng.randint(-400, 400) for n in NAMES})
    assert shifted == plain, _diff(shifted, plain)
