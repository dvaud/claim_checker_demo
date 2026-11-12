"""People in a shared project (0.14): who you are to your colleagues, and what each person decided.

Each installation of ENLENS is one person: a random id made once (`settings.person_id`) and the name colleagues see
(`settings.your_name`, asked for when work is first sent). What a person decides is stored under their id:

- a judgement of an excerpt (`judgements`, one row per excerpt and person). The judgement in force is copied to the
  excerpt's own row (`verifications.user_*`, with `user_by`), where every view reads it: your verdict when you made
  one, otherwise the latest verdict a colleague made (a comment alone does not hide it). A colleague's judgement
  never replaces yours (`refresh`);
- a review of a label, of a link between terms or of a theme (`reviews.person_id`). The views read reviews oldest first
  and the last one counts, so yours are read after a colleague's (`review_order`).

Judgements and reviews made before 0.14 name no person: they are this installation's (`adopt` writes that down
before a project is sent, so a colleague sees them under your name).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import sqlite3
import uuid
from typing import Iterable

from .store import Workspace, now

ID_RE = re.compile(r"p[0-9a-f]{12}")
UNKNOWN = "p000000000000"  # the sender of a project zip made before 0.14: "a colleague"
VERDICTS = ("supports", "partially_supports", "refutes", "not_relevant")
KAPPA_MIN = 10  # excerpts both people judged before Cohen's kappa is shown


def me() -> str:
    """This installation's person id, made the first time it is needed."""
    from . import home

    pid = home.load_settings().get("person_id") or ""
    if not ID_RE.fullmatch(pid):
        with home.LOCK:  # made once: two requests of a new installation at once each made their own
            # (strict: settings that cannot be read this moment are not "no id yet": a new id made then took the
            # person's place in every shared project)
            with home.to_change():
                pid = home.load_settings().get("person_id") or ""
            if not ID_RE.fullmatch(pid):
                pid = "p" + uuid.uuid4().hex[:12]
                home.update_settings({"person_id": pid})
    return pid


def my_name() -> str:
    from . import home

    return (home.load_settings().get("your_name") or "").strip()


def remember(cx: sqlite3.Connection, person_id: str, name: str | None) -> None:
    """Note a person's name in the project (the latest name they sent counts)."""
    if not person_id:
        return
    cx.execute("INSERT INTO people(person_id, name, seen_at) VALUES (?,?,?) ON CONFLICT(person_id) DO UPDATE SET "
               "name=COALESCE(NULLIF(excluded.name, ''), people.name), seen_at=excluded.seen_at",
               (person_id, (name or "").strip()[:60], now()))


def names(ws: Workspace) -> dict[str, str]:
    """{person_id: name} of everyone this project knows; your own id is "you"."""
    out = {r["person_id"]: (r["name"] or "a colleague") for r in ws.query("SELECT person_id, name FROM people")}
    out[UNKNOWN] = "a colleague"
    out[me()] = "you"
    return out


def review_order(me_id: str | None = None) -> tuple[str, tuple]:
    """The ORDER BY of a query over `reviews` whose last row per item counts: a colleague's reviews first, then yours
    (reviews from before 0.14 name no person: they are yours)."""
    m = me_id or me()
    return "ORDER BY (COALESCE(person_id, ?) = ?), decided_at, review_id", (m, m)


def mine_sql(me_id: str | None = None) -> tuple[str, tuple]:
    """A condition on `reviews` that keeps your own rows (for "clear" and "undo", which never touch a colleague's)."""
    m = me_id or me()
    return "COALESCE(person_id, ?) = ?", (m, m)


REVIEW_KEY = ("item_kind", "item_id", "field", "decision", "corrected", "person_id", "decided_at")


def review_key(r: dict) -> str:
    """What makes a review the same review in every copy (its row number is this copy's own)."""
    return hashlib.sha1("|".join(str(r.get(c) if r.get(c) is not None else "") for c in REVIEW_KEY).encode()).hexdigest()[:20]


def forget_reviews(cx: sqlite3.Connection, review_ids: Iterable[int] = (), reviews: Iterable[dict] = (),
                   keys: Iterable[str] = (), at: str | None = None, person_id: str | None = None) -> int:
    """Take reviews back: delete them here and note them as removed (`sync_removed`, kind "review", with the review's
    fields), so a colleague's copy of them does not bring them back, and their copies drop them too. By row
    (`review_ids`: your own *Clear* or *Undo*), by their fields (`reviews`: a colleague's taken back), or by `keys`.
    Returns how many were deleted here."""
    m = me()
    cols = [c[0] for c in cx.execute("SELECT * FROM reviews LIMIT 0").description]
    gone: dict[str, dict | None] = {k: None for k in keys}
    ids = list(review_ids)
    if ids:
        for r in cx.execute(f"SELECT * FROM reviews WHERE review_id IN ({','.join('?' * len(ids))})", ids).fetchall():
            row = dict(zip(cols, r))
            row["person_id"] = row.get("person_id") or m
            gone[review_key(row)] = {c: row.get(c) for c in REVIEW_KEY}
    for f in reviews:
        gone[review_key(f)] = {c: f.get(c) for c in REVIEW_KEY}
    n = 0
    if gone:
        for r in cx.execute("SELECT * FROM reviews").fetchall():
            row = dict(zip(cols, r))
            row["person_id"] = row.get("person_id") or m
            if review_key(row) in gone:
                n += cx.execute("DELETE FROM reviews WHERE review_id=?", (row["review_id"],)).rowcount
        cx.executemany("INSERT OR IGNORE INTO sync_removed(kind, key, title, at, person_id) VALUES ('review', ?, ?, ?, ?)",
                       [(k, json.dumps(f) if f else None, at or now(), person_id or m) for k, f in gone.items()])
    return n


# ---------------------------------------------------------------------------------------------
# judgements of excerpts
# ---------------------------------------------------------------------------------------------
def record(cx: sqlite3.Connection, claim_id: str, passage_id: str, person_id: str, verdict: str | None,
           note: str | None, at: str | None, quote: str | None = None, start: int | None = None,
           end: int | None = None) -> None:
    """A person's judgement of an excerpt. No verdict and no note: they took it back, kept as a row without either
    (dated), so an older copy of their judgement in a colleague's file does not bring it back."""
    if not verdict and not note:
        verdict = note = quote = start = end = None
    if not at:  # to the microsecond: of two judgements of one person, the later one wins in every copy
        at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    cx.execute("INSERT OR REPLACE INTO judgements(claim_id, passage_id, person_id, verdict, note, at, quote, start, "
               "end) VALUES (?,?,?,?,?,?,?,?,?)",
               (claim_id, passage_id, person_id, verdict, note, at, quote, start, end))


def refresh(cx: sqlite3.Connection, claim_ids: Iterable[str] | None = None, me_id: str | None = None) -> None:
    """Copy the judgement in force to each excerpt of these checks (all, when None): your verdict when you made one,
    otherwise the latest verdict of a colleague; only where nobody gave a verdict, your comment, otherwise the latest
    comment. 0.14.3: a comment alone is not a judgement, so your comment no longer hides a colleague's verdict (the
    excerpt then fell back to the AI's judgement). The comment copied with it (`user_note`) is your own when you
    wrote anything on the excerpt, so it stays yours to edit; otherwise it is the one of the judgement in force.
    Excerpts nobody judged since 0.14 keep what they have (a judgement from before 0.14, not yet written down as
    yours)."""
    m = me_id or me()
    where, args = "subject_kind='user_claim'", []
    if claim_ids is not None:
        ids = sorted(set(claim_ids))
        if not ids:
            return
        where += f" AND subject_id IN ({','.join('?' * len(ids))})"
        args = ids
    pick = ("(SELECT {col} FROM judgements j WHERE j.claim_id=verifications.subject_id AND "
            "j.passage_id=verifications.passage_id AND (j.verdict IS NOT NULL OR j.note IS NOT NULL) "
            "ORDER BY {order}, j.at DESC LIMIT 1)")
    in_force = "(j.verdict IS NOT NULL) DESC, (j.person_id = ?) DESC"  # a verdict first; of verdicts, yours
    own_note = "(j.person_id = ?) DESC, (j.verdict IS NOT NULL) DESC"   # your row first (as before 0.14.3)
    cols = (("user_verdict", "verdict", in_force), ("user_note", "note", own_note), ("user_at", "at", in_force),
            ("user_quote", "quote", in_force), ("user_start", "start", in_force), ("user_end", "end", in_force),
            ("user_by", "person_id", in_force))
    sets = ", ".join(f"{dst}={pick.format(col=src, order=order)}" for dst, src, order in cols)
    cx.execute(f"UPDATE verifications SET {sets} WHERE {where} AND (user_by IS NOT NULL OR EXISTS (SELECT 1 FROM "
               "judgements j WHERE j.claim_id=verifications.subject_id AND j.passage_id=verifications.passage_id))",
               (m,) * len(cols) + tuple(args))


def adopt(cx: sqlite3.Connection, person_id: str) -> int:
    """Write down as `person_id`'s the judgements and reviews that name no person (made before 0.14, in this copy or,
    for a project zip from before 0.14, in the sender's). Returns how many judgements."""
    cond = ("subject_kind='user_claim' AND user_by IS NULL AND (user_verdict IS NOT NULL OR user_note IS NOT NULL) "
            "AND NOT EXISTS (SELECT 1 FROM judgements j WHERE j.claim_id=verifications.subject_id AND "
            "j.passage_id=verifications.passage_id)")
    n = cx.execute("INSERT OR IGNORE INTO judgements(claim_id, passage_id, person_id, verdict, note, at, quote, start, "
                   f"end) SELECT subject_id, passage_id, ?, user_verdict, user_note, COALESCE(user_at, ?), user_quote, "
                   f"user_start, user_end FROM verifications WHERE {cond}", (person_id, now())).rowcount
    cx.execute("UPDATE verifications SET user_by=? WHERE subject_kind='user_claim' AND user_by IS NULL AND "
               "(user_verdict IS NOT NULL OR user_note IS NOT NULL)", (person_id,))
    cx.execute("UPDATE reviews SET person_id=? WHERE person_id IS NULL", (person_id,))
    return n


def others(ws: Workspace, claim_ids: Iterable[str]) -> dict[tuple[str, str], list[dict]]:
    """The judgements of the excerpts of these checks by everyone but the person whose judgement is in force:
    {(claim_id, passage_id): [{"mine", "name", "verdict", "note", "at"}]}, latest first."""
    ids = sorted(set(claim_ids))
    if not ids:
        return {}
    who, m = names(ws), me()
    rows = ws.query("SELECT j.claim_id, j.passage_id, j.person_id, j.verdict, j.note, j.at FROM judgements j JOIN "
                    "verifications v ON v.subject_kind='user_claim' AND v.subject_id=j.claim_id AND "
                    f"v.passage_id=j.passage_id WHERE j.claim_id IN ({','.join('?' * len(ids))}) AND "
                    "j.person_id != COALESCE(v.user_by, '') AND (j.verdict IS NOT NULL OR j.note IS NOT NULL) "
                    "ORDER BY j.at DESC", ids)
    out: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        out.setdefault((r["claim_id"], r["passage_id"]), []).append(
            {"mine": r["person_id"] == m, "name": who.get(r["person_id"], "a colleague"), "verdict": r["verdict"],
             "note": r["note"], "at": r["at"]})
    return out


def agreement(ws: Workspace) -> list[dict]:
    """How often you and each colleague judged the same excerpts alike: [{"person_id", "name", "both", "agreed",
    "rate", "kappa"}], most excerpts in common first. Cohen's kappa over the four answers (supports, partly
    supports, contradicts, not about it); None below KAPPA_MIN excerpts in common (it says little on so few) or when it
    cannot be computed (one answer only)."""
    m = me()
    who = names(ws)
    pairs: dict[str, list[tuple[str, str]]] = {}
    for r in ws.query("SELECT o.person_id, y.verdict AS mine, o.verdict AS theirs FROM judgements y JOIN judgements o "
                      "ON o.claim_id=y.claim_id AND o.passage_id=y.passage_id AND o.person_id != y.person_id "
                      "WHERE y.person_id=? AND y.verdict IS NOT NULL AND o.verdict IS NOT NULL", (m,)):
        pairs.setdefault(r["person_id"], []).append((r["mine"], r["theirs"]))
    out = []
    for pid, ps in pairs.items():
        n = len(ps)
        agreed = sum(a == b for a, b in ps)
        po = agreed / n
        pe = sum((sum(a == c for a, _ in ps) / n) * (sum(b == c for _, b in ps) / n) for c in VERDICTS)
        kappa = round((po - pe) / (1 - pe), 2) if pe < 1 and n >= KAPPA_MIN else None
        out.append({"person_id": pid, "name": who.get(pid, "a colleague"), "both": n, "agreed": agreed,
                    "rate": round(po, 3), "kappa": kappa})
    return sorted(out, key=lambda x: -x["both"])
