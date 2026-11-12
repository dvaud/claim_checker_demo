"""0.18.0 (roadmap L2), builder C: a seeded, deterministic long run of one owner and several collaborators.

Three copies of one project (four in the long run), one shared folder, `random.Random(seed)`. Each round each person
does a few random things to their copy: adds a document (from a small pool of texts, so documents come back), removes
one, leaves a passage out or restores one, makes a document stricter or looser for AI, reads one again with the new
reader, makes a check (shared or private) or judges an excerpt of one, takes back what they shared or proposed; the
owner also accepts or declines what waits, switches "accept added documents at once" and, rarely, hands the project
over. Then some of the copies run a round of the shared folder, in a random order. Person ids are fixed per seed.

After **every** round (plan §9.2):
- no result lost: every check a person made is in their copy with as many excerpts and the same judgements of theirs;
- no private item leaked: a check never shared is in no colleague's copy and in no bundle of the folder;
- the stricter setting holds: no collaborator's copy lets more AI read a document than the owner's word it follows,
  and no copy's level became looser in a round except by that word (or the owner's own act);
- the chain agrees: copies that hold the same records of who the owner is name the same owner.
At the end the team goes quiet (everyone syncs until nothing is written, at most 8 rounds) and the copies converge.

The default run (CI) is 10 seeds x 40 rounds x 3 copies, about 45 s (a round of the folder is ~80 ms; 0-2 copies sync
per round). `ENLENS_LONG_RANDOM=1` runs 30 seeds x 80 rounds x 4 copies (1-4 sync per round), about 12 min of CPU;
`ENLENS_L2_SEEDS`, `ENLENS_L2_ROUNDS`, `ENLENS_L2_PEOPLE` and `ENLENS_L2_FIRST_SEED` set each. A failure names the seed
and the round, and prints the last actions (`ENLENS_L2_TAIL=<n>` more of them; `ENLENS_L2_DUMP=<doc id>` what every copy
says of one document). Person ids and the app's clock are fixed, so a seed is the same run every time.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import claimcheck, ingest, ownership, people, reread, sharing
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import folder
from owner_helpers import TEXTS, leave_out
from owner_more_helpers import join_zip, small_project
from test_0_14_0_shared_projects import Person

LONG = os.environ.get("ENLENS_LONG_RANDOM") == "1"
SEEDS = int(os.environ.get("ENLENS_L2_SEEDS") or (30 if LONG else 10))
ROUNDS = int(os.environ.get("ENLENS_L2_ROUNDS") or (80 if LONG else 40))
PEOPLE = int(os.environ.get("ENLENS_L2_PEOPLE") or (4 if LONG else 3))
FIRST = int(os.environ.get("ENLENS_L2_FIRST_SEED") or 0)
NAMES = ("Anna", "Ben", "Carol", "Dana")
RANK = ownership.RANK
OLD = {"interview", "report1", "report2"}  # read by the earlier reader whenever they are added (the same file is always
#                                            read the same way, as one ENLENS would; another reader's reading of a file
#                                            added twice would be a sync-clash copy, outside L2)
LEVELS = ("cloud", "local", "none")

_WORDS = ("electrolyser", "brine", "aquifer", "pipeline", "ammonia", "turbine", "harbour", "membrane", "permit",
          "subsidy", "tariff", "curtailment", "salinity", "cooperative", "apprentice", "reservoir")
_SENT = ("The {a} near the coast needed a new {b} before the {c} could be signed.",
         "Operators said the {a} cost less than the {b} once the {c} was in place.",
         "Local people asked who would pay for the {a} and for the {b} after {n}.",
         "In {n} the {a} doubled while the {b} stayed as it was, the report says of the {c}.",
         "A study of {n} sites found that the {a} mattered more than the {b} for the {c}.")
CLAIMS = ("Desalination adds little to the cost of hydrogen.", "Electrolysers create local jobs.",
          "Flexible electrolysers lower wind curtailment.", "Brine harms marine life near outfalls.",
          "Training programmes raise the share of local hires.", "Ports need new terminals for ammonia.")


def _pool(seed: int) -> dict[str, str]:
    """The texts people add: the four of owner_helpers and six made from the seed (so the same document is added,
    removed and added again over a run)."""
    rng = random.Random(seed * 7919 + 1)
    out = dict(TEXTS)
    for i in range(6):
        w = rng.sample(_WORDS, 6)
        title = f"Field report {i + 1}: the {w[0]} and the {w[1]}"
        paras = []
        for _ in range(3):
            paras.append(" ".join(rng.choice(_SENT).format(a=rng.choice(w), b=rng.choice(w), c=rng.choice(w),
                                                           n=rng.randint(1990, 2030)) for _ in range(3)))
        out[f"report{i + 1}"] = title + "\n\n" + "\n\n".join(paras) + "\n"
    return out


class Fixed(Person):
    """A person whose id is fixed (the same in every run of a seed)."""

    def __init__(self, tmp: Path, name: str, monkeypatch, pid: str):
        self.name, self.home, self.mp = name, tmp / f"home-{name}", monkeypatch
        self.ws = None
        self.files = tmp / f"sent-{name}"
        self.files.mkdir()
        self.n = 0
        with self:
            from enlens_claims import home

            home.update_settings({"your_name": name, "person_id": pid})
            self.id = people.me()
        assert self.id == pid


class Run:
    def __init__(self, tmp: Path, mp, seed: int, n_people: int):
        self.tmp, self.mp, self.seed = tmp, mp, seed
        self.rng = random.Random(seed)
        self.round = 0
        self.trail: list[str] = []
        self.shared = tmp / "Közös mappa" / "ENLENS team"
        self.shared.mkdir(parents=True)
        ids = sorted("p" + hashlib.sha1(f"{seed}-{n}".encode()).hexdigest()[:12] for n in NAMES[:n_people])
        self.people = [Fixed(tmp, n, mp, ids[i]) for i, n in enumerate(NAMES[:n_people])]
        self.texts = _pool(seed)
        self.mine: dict[str, dict[str, tuple]] = {p.name: {} for p in self.people}   # their checks: hyp -> results
        self.private: dict[str, str] = {}                                              # hyp -> maker (never shared)
        self.markers: dict[str, str] = {}                                              # hyp -> its words
        self.ever_shared: set[str] = set()
        self.excerpts: dict[str, list[tuple]] = {}                                     # hyp -> its first excerpts
        self.bundles_seen: set[str] = set()
        self.owner_loosened: set[tuple[str, str]] = set()
        anna = self.people[0]
        small_project(anna, tmp / "Anna-project")
        self.add(anna, "interview", reader=1, quiet=True)
        for p in self.people[1:]:
            join_zip(p, anna, tmp / f"{p.name}-project")
        for p in self.people:
            with p:
                folder.set_folder(p.ws, str(self.shared))
        for p in self.people:
            self.sync(p)

    # ---- small things ---------------------------------------------------------------------------------------------
    def say(self, p: Person, what: str) -> None:
        self.trail.append(f"r{self.round} {p.name}: {what}")

    def dump(self, doc: str) -> str:
        """What every copy says of one document (ENLENS_L2_DUMP=<doc id>, to find out why a seed failed)."""
        out = []
        for p in self.people:
            with p:
                cx = p.ws._conn()
                k = ownership.canon(cx).get(doc) or {}
                s = cx.execute("SELECT * FROM canon_seen WHERE doc=?", (doc,)).fetchone()
                ch = {r[0]: r[1] for r in cx.execute("SELECT fp, included FROM block_choices WHERE doc_id=?", (doc,))}
                props = [(x["kind"], x["by"]["name"], x["state"], x["at"]) for x in ownership.view(p.ws)["proposals"]
                         if x["doc"] == doc]
                rm = [tuple(r) for r in cx.execute("SELECT at, person_id FROM sync_removed WHERE key=?", (doc,))]
            out.append(f"{p.name} ({p.id}): held={bool(self.docs(p).count(doc))} level={self.level(p).get(doc)} "
                       f"canon={ {c: k.get(c) for c in ('state', 'state_n', 'reader', 'ai_access', 'ai_n', 'blocks', 'blocks_n', 'by', 'owner_seq')} } "
                       f"seen={tuple(s) if s else None} choices={ch} removed={rm} proposals={props}")
        return "\n  ".join(out)

    def fail(self, msg: str) -> None:
        if os.environ.get("ENLENS_L2_DUMP"):
            msg += "\n  " + self.dump(os.environ["ENLENS_L2_DUMP"])
        tail = "\n  ".join(self.trail[-int(os.environ.get("ENLENS_L2_TAIL") or 40):])
        pytest.fail(f"seed {self.seed}, round {self.round}: {msg}\n  last actions:\n  {tail}", pytrace=False)

    def check_that(self, ok: bool, msg: str) -> None:
        if not ok:
            self.fail(msg)

    def docs(self, p: Person) -> list[str]:
        with p:
            return sorted(r[0] for r in p.ws.query("SELECT doc_id FROM documents"))

    def level(self, p: Person) -> dict[str, str]:
        with p:
            return dict(folder.ai_settings(p.ws, p.ws._conn()))

    def owner(self, p: Person) -> str | None:
        with p:
            return ownership.owner(p.ws._conn())

    def is_owner(self, p: Person) -> bool:
        return self.owner(p) == p.id

    def doc_of_text(self, key: str) -> str:
        return "d" + hashlib.sha1(self.texts[key].encode("utf-8")).hexdigest()[:10]

    def sync(self, p: Person) -> dict:
        with p:
            r = folder.sync_now(p.ws)
            bad = [x for x in r["problems"] if x["kind"] not in ("documents",)]
            self.check_that(not bad, f"{p.name}'s round had problems: {bad}")
            for d in r.get("moves_due") or []:
                ownership.move_now(p.ws, d)
        self.say(p, f"synced (wrote {(r.get('wrote') or {}).get('seq')})")
        return r

    # ---- actions ------------------------------------------------------------------------------------------------
    def add(self, p: Person, key: str, reader: int | None = None, ai: str | None = None, quiet: bool = False) -> str:
        d = self.tmp / f"added-{p.name}"
        d.mkdir(exist_ok=True)
        f = d / f"{key}.txt"
        f.write_text(self.texts[key], encoding="utf-8")
        with p:
            was = ingest.READER
            if reader is not None:
                ingest.READER = reader
            try:
                ingest.ingest(p.ws, [f], **({"ai_access": ai} if ai else {}))
            finally:
                ingest.READER = was
        if not quiet:
            self.say(p, f"added {key} ({self.doc_of_text(key)}, reader {reader or ingest.READER}, ai {ai})")
        return self.doc_of_text(key)

    def a_add(self, p: Person) -> bool:
        held = set(self.docs(p))
        keys = sorted(k for k in self.texts if self.doc_of_text(k) not in held)
        if not keys:
            return False
        key = self.rng.choice(keys)
        self.add(p, key, reader=1 if key in OLD else None, ai=self.rng.choice([None, None, "local", "none"]))
        return True

    def a_remove(self, p: Person) -> bool:
        docs = self.docs(p)
        if len(docs) < 3:
            return False
        d = self.rng.choice(docs)
        with p:
            p.ws.remove_document(d, why="random")
        self.say(p, f"removed {d}")
        return True

    def a_blocks(self, p: Person) -> bool:
        with p:
            rows = p.ws.query("SELECT doc_id, included, COUNT(*) FROM blocks GROUP BY doc_id, included ORDER BY doc_id, "
                              "included")
        opts = [(r[0], bool(1 - r[1]), r[2]) for r in rows]   # (doc, restore?, how many)
        if not opts:
            return False
        restore = self.rng.random() < 0.3
        opts = [o for o in opts if o[1] == restore] or opts
        d, restore, n = self.rng.choice(opts)
        k = self.rng.randrange(n)
        leave_out(p, d, k, included=restore)
        self.say(p, f"{'restored' if restore else 'left out'} block {k} of {d}")
        return True

    def a_level(self, p: Person, looser: bool) -> bool:
        lv = self.level(p)
        docs = sorted(d for d in self.docs(p) if (RANK[lv.get(d, 'none')] > 0) == looser and
                      (RANK[lv.get(d, 'none')] < 2 or looser))
        if not docs:
            return False
        d = self.rng.choice(docs)
        now = RANK[lv.get(d, "none")]
        to = self.rng.choice([x for x in LEVELS if (RANK[x] < now if looser else RANK[x] > now)])
        with p:
            from enlens_claims import access

            out = access.set_documents(p.ws, [d], setting=to)
        if looser and self.is_owner(p):
            self.owner_loosened.add((p.name, d))
        self.say(p, f"set {d} {lv.get(d)} -> {to}{' (proposed)' if out.get('proposed') else ''}")
        return True

    def a_reread(self, p: Person) -> bool:
        with p:
            docs = [r[0] for r in p.ws.query("SELECT doc_id FROM documents WHERE COALESCE(reader, 1) < ? ORDER BY "
                                             "doc_id", (ingest.READER,))]
            docs = [d for d in docs if reread.check(p.ws, d)["ok"]]
        if not docs:
            return False
        d = self.rng.choice(docs)
        with p:
            reread.move(p.ws, d, p.id)
        self.say(p, f"read {d} again")
        return True

    def a_check(self, p: Person) -> bool:
        token = f"Q{self.seed}x{self.round}x{p.name}x{len(self.markers)}"
        text = f"{self.rng.choice(CLAIMS)} ({token})"
        with p:
            hid = claimcheck.check_hypothesis(p.ws, text, BaselineBackend(), "baseline", k=3)
        self.markers[hid] = token
        share = self.rng.random() < 0.5
        if share:
            with p:
                sharing.share(p.ws, [{"kind": "check", "key": hid}])
            self.ever_shared.add(hid)
        else:
            self.private[hid] = p.name
        self.mine[p.name][hid] = self.results(p, hid)
        with p:
            self.excerpts[hid] = [tuple(r) for r in p.ws.query(
                "SELECT v.doc_id, v.passage_id FROM verifications v JOIN user_claims c ON c.claim_id=v.subject_id "
                "WHERE c.hyp_id=?", (hid,))]
        self.say(p, f"made {'a shared' if share else 'a private'} check {hid} on {self.excerpts[hid]}")
        return True

    def a_share(self, p: Person) -> bool:
        priv = [h for h, who in self.private.items() if who == p.name]  # (in the order made: ids are not seeded)
        if not priv:
            return False
        h = self.rng.choice(priv)
        with p:
            sharing.share(p.ws, [{"kind": "check", "key": h}])
        del self.private[h]
        self.ever_shared.add(h)
        self.say(p, f"shared {h}")
        return True

    def a_unshare(self, p: Person) -> bool:
        with p:
            shared = sharing.shared_keys(p.ws._conn(), "check")
        mine = [h for h in self.mine[p.name] if h in shared]
        if not mine:
            return False
        h = self.rng.choice(mine)
        with p:
            sharing.unshare(p.ws, [{"kind": "check", "key": h}])
        self.say(p, f"unshared {h}")
        return True

    def a_judge(self, p: Person) -> bool:
        hyps = list(self.mine[p.name])
        if not hyps:
            return False
        h = self.rng.choice(hyps)
        with p:
            rows = p.ws.query("SELECT v.subject_id, v.passage_id FROM verifications v JOIN user_claims c ON "
                              "c.claim_id=v.subject_id WHERE v.subject_kind='user_claim' AND c.hyp_id=? ORDER BY "
                              "v.rowid", (h,))
        if not rows:
            return False
        cid, pid = self.rng.choice([tuple(r) for r in rows])
        verdict = self.rng.choice(sorted(claimcheck.USER_VERDICTS))
        with p:
            claimcheck.set_judgement(p.ws, cid, pid, verdict, note=f"r{self.round}")
        self.mine[p.name][h] = self.results(p, h)
        self.say(p, f"judged {pid} of {h}: {verdict}")
        return True

    def a_decide(self, p: Person) -> bool:
        with p:
            ws = [x for x in ownership.view(p.ws)["proposals"] if x["can_decide"]]
        if not ws:
            return False
        q = self.rng.choice(sorted(ws, key=_key))
        yes = self.rng.random() < 0.6
        with p:
            if yes:
                ownership.accept(p.ws, q["id"])
                for d in ownership.moves_due(p.ws):
                    ownership.move_now(p.ws, d)
                if q["kind"] == "loosen":
                    self.owner_loosened.add((p.name, q["doc"]))
            else:
                ownership.decline(p.ws, q["id"], "random")
        self.say(p, f"{'accepted' if yes else 'declined'} {q['kind']} of {q['doc']} by {q['by']['name']}")
        return True

    def a_take_back(self, p: Person) -> bool:
        with p:
            ws = [x for x in ownership.view(p.ws)["proposals"] if x["can_take_back"]]
        if not ws:
            return False
        q = self.rng.choice(sorted(ws, key=_key))
        with p:
            ownership.take_back(p.ws, q["id"])
        self.say(p, f"took back {q['kind']} of {q['doc']}")
        return True

    def a_toggle(self, p: Person) -> bool:
        with p:
            on = ownership.accept_adds(p.ws)
            ownership.set_accept_adds(p.ws, not on)
        self.say(p, f"accept adds at once: {not on}")
        return True

    def a_hand_over(self, p: Person) -> bool:
        with p:
            known = {r[0] for r in p.ws.query("SELECT person_id FROM people")}
        others = sorted(q.id for q in self.people if q is not p and q.id in known)
        if not others:
            return False
        to = self.rng.choice(others)
        with p:
            ownership.hand_over(p.ws, to, "random")
        self.say(p, f"handed over to {to}")
        return True

    WEIGHTS = (("add", 3), ("remove", 2), ("blocks", 3), ("tighten", 2), ("loosen", 2), ("reread", 1), ("check", 2),
               ("judge", 2), ("share", 1), ("unshare", 1), ("take_back", 1), ("decide", 5), ("toggle", 1),
               ("hand_over", 0.25), ("skip", 2))
    OWNER_ONLY = {"decide", "toggle", "hand_over"}

    def act(self, p: Person) -> None:
        owner = self.is_owner(p)
        opts = [(a, w) for a, w in self.WEIGHTS if owner or a not in self.OWNER_ONLY]
        for _ in range(self.rng.choice([0, 1, 1, 2])):
            a = self.rng.choices([a for a, _w in opts], [w for _a, w in opts])[0]
            if a == "skip":
                continue
            if a in ("tighten", "loosen"):
                self.a_level(p, looser=a == "loosen")
            else:
                getattr(self, f"a_{a}")(p)

    # ---- what is checked ------------------------------------------------------------------------------------------
    def results(self, p: Person, h: str) -> tuple | None:
        with p:
            cx = p.ws._conn()
            if not cx.execute("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h,)).fetchone():
                return None
            n = cx.execute("SELECT COUNT(*) FROM verifications v JOIN user_claims c ON c.claim_id=v.subject_id WHERE "
                           "v.subject_kind='user_claim' AND c.hyp_id=?", (h,)).fetchone()[0]
            js = sorted((r[0], r[1], r[2]) for r in cx.execute(
                "SELECT j.passage_id, j.verdict, j.note FROM judgements j JOIN user_claims c ON c.claim_id=j.claim_id "
                "WHERE c.hyp_id=? AND j.person_id=?", (h, p.id)))
        return (n, tuple(js))

    def snapshot_levels(self) -> dict[str, dict[str, str]]:
        return {p.name: self.level(p) for p in self.people}

    def invariants(self, before_levels: dict[str, dict[str, str]]) -> None:
        # no result lost
        for p in self.people:
            for h, want in self.mine[p.name].items():
                got = self.results(p, h)
                if got != want:
                    with p:
                        rows = [tuple(r) for r in p.ws.query(
                            "SELECT v.doc_id, v.passage_id, v.verdict FROM verifications v JOIN user_claims c ON "
                            "c.claim_id=v.subject_id WHERE c.hyp_id=?", (h,))]
                    self.fail(f"{p.name}'s check {h} changed: {want} -> {got}; its excerpts now: {rows}, at first: "
                              f"{self.excerpts.get(h)}")
        # no private item in a colleague's copy, nor in a bundle of the folder
        for p in self.people:
            with p:
                hyps = {r[0] for r in p.ws.query("SELECT hyp_id FROM hypotheses")}
            leaked = {h for h in hyps if h in self.private and self.private[h] != p.name}
            self.check_that(not leaked, f"{p.name}'s copy holds a colleague's private check: {sorted(leaked)}")
        for b in sorted(self.shared.rglob("bundles/*.zip")):
            if str(b) in self.bundles_seen:
                continue
            self.bundles_seen.add(str(b))
            with zipfile.ZipFile(b) as zf:
                raw = zf.read("rows.sqlite")
            db = self.tmp / "bundle-check.sqlite"
            db.write_bytes(raw)
            cx = sqlite3.connect(db)
            try:
                hyps = {r[0] for r in cx.execute("SELECT hyp_id FROM hypotheses")}
            finally:
                cx.close()
            leaked = hyps & set(self.private)
            self.check_that(not leaked, f"bundle {b.relative_to(self.shared)} holds a private check: {sorted(leaked)}")
            for h, who in self.private.items():
                self.check_that(self.markers[h].encode() not in raw, f"bundle {b.name} names {who}'s private check {h}")
        # the stricter setting holds
        for p in self.people:
            with p:
                cx = p.ws._conn()
                ch = ownership.chain(cx)
                K = ownership.canon(cx, ch)
                seen = {r[0]: r[1] for r in cx.execute("SELECT doc, ai_n FROM canon_seen")}
            now = self.level(p)
            owner = ch[-1]["owner"] if ch else None
            for d, lv in now.items():
                k = K.get(d)
                if k is None or k["state"] != "in":
                    continue
                if owner != p.id and seen.get(d) is not None:
                    # looser than the owner's word this copy follows, and than the owner's latest word it holds (a
                    # document added here again since may be at the latest before this copy has looked again)
                    floor = ownership.level_at(k["ai_hist"], seen[d]) or k["ai_access"]
                    self.check_that(RANK[lv] >= min(RANK[floor], RANK[k["ai_access"]]),
                                    f"{p.name}'s copy lets more AI read {d} ({lv}) than the owner's word it follows "
                                    f"({floor}, now {k['ai_access']})")
                was = before_levels[p.name].get(d)
                if was is not None and RANK[lv] < RANK[was] and (p.name, d) not in self.owner_loosened:
                    self.check_that(RANK[lv] >= RANK[k["ai_access"]], f"{p.name}'s copy loosened {d} ({was} -> {lv}) "
                                                                      f"beyond the owner's word ({k['ai_access']})")
        # the chain: the same records name the same owner
        by_records: dict[frozenset, set] = {}
        for p in self.people:
            with p:
                recs = frozenset(tuple(r) for r in p.ws.query("SELECT seq, owner, by, at, kind, after FROM ownership"))
            by_records.setdefault(recs, set()).add(self.owner(p))
        for owners in by_records.values():
            self.check_that(len(owners) == 1, f"copies with the same records name different owners: {owners}")

    def one_round(self) -> None:
        self.round += 1
        before = self.snapshot_levels()
        self.owner_loosened: set[tuple[str, str]] = set()
        for p in self.rng.sample(self.people, len(self.people)):
            self.act(p)
        k = self.rng.randint(1, len(self.people)) if LONG else self.rng.choice([0, 1, 1, 2])  # (a round ~80 ms)
        for p in self.rng.sample(self.people, k):
            self.sync(p)
        self.invariants(before)

    def quiesce(self) -> None:
        self.round += 1
        for _ in range(8):
            wrote = False
            for p in self.people:
                r = self.sync(p)
                wrote = wrote or (r.get("wrote") or {}).get("seq") is not None
            if not wrote:
                break
        else:
            last = []
            for d in sorted(self.shared.glob("*/p*")):
                bs = sorted(d.glob("bundles/*.zip"))
                if bs:
                    with zipfile.ZipFile(bs[-1]) as zf:
                        meta = json.loads(zf.read("bundle.json"))
                    last.append(f"{d.name}: rows {meta.get('rows')}, items {len(meta.get('items') or [])}, "
                                f"documents {[x.get('doc_id') for x in meta.get('documents') or []]}")
            self.fail("the copies still wrote after 8 quiet rounds; their last bundles: " + "; ".join(last))
        self.owner_loosened = set()
        self.invariants(self.snapshot_levels())
        self.converged()

    def converged(self) -> None:
        P = self.people
        owners = {self.owner(p) for p in P}
        self.check_that(len(owners) == 1, f"the copies name different owners: {owners}")
        canons = {}
        for p in P:
            with p:
                K = ownership.canon(p.ws._conn())
            canons[p.name] = {d: (k["state"], k["reader"] or 1, k["ai_access"], json.dumps(k["blocks"], sort_keys=True))
                              for d, k in K.items()}
        first = canons[P[0].name]
        for p in P[1:]:
            self.check_that(canons[p.name] == first, f"{p.name}'s canon differs from {P[0].name}'s: "
                                                      f"{_diff(canons[p.name], first)}")
        views = {}
        for p in P:
            with p:
                views[p.name] = ownership.view(p.ws)
        states = {p.name: {x["id"]: x["state"] for x in views[p.name]["proposals"]} for p in P}
        for p in P[1:]:
            self.check_that(states[p.name] == states[P[0].name], f"{p.name} sees other proposal states than "
                                                                  f"{P[0].name}: {_diff(states[p.name], states[P[0].name])}")
        clash = set()
        for p in P:
            with p:
                clash |= {r[0] for r in p.ws.query("SELECT key FROM sync_copies WHERE kind='document'")}
        docs = {p.name: set(self.docs(p)) - clash for p in P}
        levels = {p.name: self.level(p) for p in P}
        readers = {}
        for p in P:
            with p:
                readers[p.name] = {r[0]: r[1] for r in p.ws.query("SELECT doc_id, COALESCE(reader, 1) FROM documents")}
        props = list(views[P[0].name]["proposals"])
        for d, (state, reader, ai, blocks) in first.items():
            holders = [p for p in P if d in docs[p.name]]
            if state == "removed":
                for p in holders:   # only a person who added it again holds it (plan §3: or who added it too while
                    #                 someone else's proposal to add it again waits)
                    again = [x for x in props if x["kind"] == "add" and x["doc"] == d and
                             (x["by"]["id"] == p.id or x["state"] == "waiting")]
                    self.check_that(bool(again), f"{p.name} holds {d}, which the owner removed")
                continue
            if len(holders) == len(P):
                lv = {levels[p.name].get(d) for p in P}
                self.check_that(lv == {ai}, f"{d}: AI levels {lv} in the copies, the project's is {ai}")
            for p in holders:
                own_rr = [x for x in props if x["kind"] == "reread" and x["doc"] == d and x["by"]["id"] == p.id
                          and x["state"] in ("waiting", "declined", "taken_back")]
                waits = [t for t in views[p.name]["to_apply"] if t["doc"] == d]
                if not own_rr and not waits:
                    self.check_that(readers[p.name][d] == reader, f"{p.name} reads {d} with reader "
                                                                  f"{readers[p.name][d]}, the project with {reader}")
                own_bl = [x for x in props if x["kind"] == "blocks" and x["doc"] == d and x["by"]["id"] == p.id
                          and x["state"] in ("waiting", "declined", "taken_back", "replaced")]
                if not own_bl and (p.id != self.owner(p)):
                    with p:
                        mine = {r[0]: r[1] for r in p.ws.query("SELECT fp, included FROM block_choices WHERE doc_id=?",
                                                               (d,))}
                    want = {fp: v[0] for fp, v in json.loads(blocks).items()}
                    self.check_that(mine == want, f"{p.name}'s blocks of {d} differ from the project's: "
                                                  f"{_diff(mine, want)}")
        for p in P:
            for d in docs[p.name] - set(first):
                adds = [x for x in props if x["kind"] == "add" and x["doc"] == d]
                self.check_that(bool(adds), f"{p.name} holds {d}: not the project's, and nobody proposed it")
                if not any(x["state"] == "waiting" for x in adds):
                    self.check_that(any(x["by"]["id"] == p.id for x in adds),
                                    f"{p.name} holds {d}, which someone else proposed and which does not wait")


def _key(q: dict) -> tuple:
    """A proposal's place in a list to choose from, the same in every run (its id may hold a time)."""
    return (q["kind"], q["doc"], q["by"]["id"], json.dumps(q["detail"], sort_keys=True))


def _diff(a: dict, b: dict) -> dict:
    keys = set(a) | set(b)
    return {k: (a.get(k), b.get(k)) for k in sorted(keys) if a.get(k) != b.get(k)}


@pytest.fixture
def clock(monkeypatch):
    """The app's clock (`store.now`, to the second) made a counter: one second later at each call, from a fixed
    start. A run is then the same every time (no two acts fall in one second by chance, so no tie is broken one way
    in one run and the other way in the next), and a failing seed can be run again to find out why."""
    import datetime as dt
    import sys

    from enlens_claims import store

    real = store.now
    t = [dt.datetime(2026, 11, 11, 9, 0, tzinfo=dt.timezone.utc)]

    def fake() -> str:
        t[0] += dt.timedelta(seconds=1)
        return t[0].isoformat()

    for name, mod in list(sys.modules.items()):
        if name.startswith("enlens_claims") and getattr(mod, "now", None) is real:
            monkeypatch.setattr(mod, "now", fake)
    return fake


# seeds of the default run that show a defect, each also a small test in test_0_18_0_owner_more.py, marked
# xfail(strict=True) with the defect (when it is fixed the seed passes and its mark must go)
KNOWN: dict[int, str] = {}   # (seeds 1, 3, 4 and 8 showed four defects of 14af59e; fixed by builder A in 5e3dc72)


def _seeds():
    for s in range(FIRST, FIRST + SEEDS):
        if s in KNOWN and PEOPLE == 3 and ROUNDS == 40 and not LONG:
            yield pytest.param(s, marks=pytest.mark.xfail(strict=True, reason=KNOWN[s]))
        else:
            yield s


@pytest.mark.parametrize("seed", list(_seeds()))
def test_a_long_random_run_keeps_every_result_every_secret_and_the_stricter_setting(seed, tmp_path, monkeypatch, clock):
    run = Run(tmp_path, monkeypatch, seed, PEOPLE)
    for _ in range(ROUNDS):
        run.one_round()
    run.quiesce()
    if os.environ.get("ENLENS_L2_TRAIL"):
        import re

        same = "\n".join(re.sub(r"\bh[0-9a-f]{12}\b", "h", x) for x in run.trail)   # (check ids are not seeded)
        print("TRAIL", seed, hashlib.sha1(same.encode()).hexdigest())
