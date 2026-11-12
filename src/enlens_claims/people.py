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
    # roles (§4.8): one human on two computers (`same_as`) is one person: their later judgement of an excerpt
    # counts (an earlier one of the group does not), and both computers' judgements are "yours"
    groups = _groups(cx)
    later = ""
    if groups:
        later = (" AND NOT EXISTS (SELECT 1 FROM judgements k WHERE k.claim_id=j.claim_id AND k.passage_id=j.passage_id "
                 f"AND k.person_id != j.person_id AND ({_grp_sql(groups, 'k.person_id')}) = "
                 f"({_grp_sql(groups, 'j.person_id')}) AND k.at > j.at)")
    pick = ("(SELECT {col} FROM judgements j WHERE j.claim_id=verifications.subject_id AND "
            "j.passage_id=verifications.passage_id AND (j.verdict IS NOT NULL OR j.note IS NOT NULL)" + later +
            " ORDER BY {order}, j.at DESC LIMIT 1)")
    mine = "j.person_id = ?"
    if m in groups:
        mine = "j.person_id IN (" + ",".join(f"'{p}'" for p in sorted(group(cx, m))) + ") AND ? IS NOT NULL"
    in_force = f"(j.verdict IS NOT NULL) DESC, ({mine}) DESC"  # a verdict first; of verdicts, yours
    own_note = f"({mine}) DESC, (j.verdict IS NOT NULL) DESC"   # your row first (as before 0.14.3)
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
    groups = _groups(ws._conn())
    if groups:
        return _others_grouped(ws, ids, groups, who, m)
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


def _others_grouped(ws: Workspace, ids: list[str], groups: dict[str, str], who: dict[str, str],
                    m: str) -> dict[tuple[str, str], list[dict]]:
    """`others` where some person works on two computers: each human once, with their later judgement, shown with
    that computer's name; the group of the judgement in force is left out."""
    rows = [dict(r) for r in ws.query(
        "SELECT j.claim_id, j.passage_id, j.person_id, j.verdict, j.note, j.at, v.user_by FROM judgements j JOIN "
        "verifications v ON v.subject_kind='user_claim' AND v.subject_id=j.claim_id AND v.passage_id=j.passage_id "
        f"WHERE j.claim_id IN ({','.join('?' * len(ids))})", ids)]
    mine = {p for p, h in groups.items() if h == groups.get(m)} | {m}
    out: dict[tuple[str, str], list[dict]] = {}
    for (c, p, g), r in sorted(_latest_in_group(rows, groups).items(), key=lambda kv: kv[1]["at"] or "", reverse=True):
        if g == groups.get(r["user_by"] or "", r["user_by"]) or (r["verdict"] is None and r["note"] is None):
            continue
        out.setdefault((c, p), []).append({"mine": r["person_id"] in mine, "name": who.get(r["person_id"], "a colleague"),
                                           "verdict": r["verdict"], "note": r["note"], "at": r["at"]})
    return out


def agreement(ws: Workspace) -> list[dict]:
    """How often you and each colleague judged the same excerpts alike: [{"person_id", "name", "both", "agreed",
    "rate", "kappa"}], most excerpts in common first. Cohen's kappa over the four answers (supports, partly
    supports, contradicts, not about it); None below KAPPA_MIN excerpts in common (it says little on so few) or when it
    cannot be computed (one answer only)."""
    m = me()
    who = names(ws)
    pairs: dict[str, list[tuple[str, str]]] = {}
    groups = _groups(ws._conn())
    if groups:  # roles (§4.8): one human on two computers counts once, with their later judgement
        latest = _latest_in_group([dict(r) for r in ws.query("SELECT claim_id, passage_id, person_id, verdict, at "
                                                             "FROM judgements")], groups)
        g_me = groups.get(m, m)
        by_excerpt: dict[tuple[str, str], dict[str, str]] = {}
        for (c, p, g), r in latest.items():
            if r["verdict"] is not None:
                by_excerpt.setdefault((c, p), {})[g] = r["verdict"]
        for got in by_excerpt.values():
            if g_me in got:
                for g, v in got.items():
                    if g != g_me:
                        pairs.setdefault(g, []).append((got[g_me], v))
    rows = [] if groups else ws.query(
        "SELECT o.person_id, y.verdict AS mine, o.verdict AS theirs FROM judgements y JOIN judgements o ON "
        "o.claim_id=y.claim_id AND o.passage_id=y.passage_id AND o.person_id != y.person_id WHERE y.person_id=? AND "
        "y.verdict IS NOT NULL AND o.verdict IS NOT NULL", (m,))
    for r in rows:
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


# ---------------------------------------------------------------------------------------------
# rows of a third person, and one human on two computers (DESIGN-roles §4.8)
# ---------------------------------------------------------------------------------------------
# A row of a colleague's file is first-hand when its author sent the file (the subfolder's person, a zip's sender);
# else it was relayed, and is noted in `sync_via` (this copy's own bookkeeping, never sent): shown as "Anna, via
# Carol's file" until the author's own file brings the row. Keys: judgement `claim|passage|person`, review
# `review_key`, note `note_id`, log `entry_id`, proposal `id`.
def via(cx: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """{(kind, key): the person who relayed it} of rows that came from a third person (`sync_via`)."""
    try:
        return {(r[0], r[1]): r[2] for r in cx.execute("SELECT kind, key, via FROM sync_via")}
    except sqlite3.OperationalError:  # a database from before the table (an incoming file of 0.17)
        return {}


def relayed(cx: sqlite3.Connection, kind: str) -> set[str]:
    """The keys of the rows of one kind this copy holds only as relayed."""
    return {r[0] for r in cx.execute("SELECT key FROM sync_via WHERE kind=?", (kind,))}


def note_via(cx: sqlite3.Connection, kind: str, key: str, author: str | None, sender: str) -> None:
    """A row of `author` taken (or brought up to date) from `sender`'s file."""
    cx.execute("INSERT OR REPLACE INTO sync_via(kind, key, author, via, at) VALUES (?,?,?,?,?)",
               (kind, key, author, sender, now()))


def first_hand(cx: sqlite3.Connection, kind: str, keys: Iterable[str]) -> None:
    """These rows came from their author's own file: no longer "via" anyone."""
    keys = list(keys)
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        cx.execute(f"DELETE FROM sync_via WHERE kind=? AND key IN ({','.join('?' * len(chunk))})", (kind, *chunk))


def _groups(cx: sqlite3.Connection) -> dict[str, str]:
    """{person: the id of their group} of everyone in a `same_as` group of two or more ids (the Owner's word, by the
    role rows that count: `ownership.roles`); {} in most projects. A group's id is the one the others are the same as
    (the id with no `same_as` of its own; the smallest when that is not one id)."""
    try:
        if not cx.execute("SELECT 1 FROM roles WHERE same_as IS NOT NULL LIMIT 1").fetchone():
            return {}
    except sqlite3.OperationalError:
        return {}
    from . import ownership

    links = [(p, r.get("same_as")) for p, r in ownership.roles(cx).items()
             if r.get("same_as") and ID_RE.fullmatch(p) and ID_RE.fullmatch(r["same_as"]) and r["same_as"] != p]
    up: dict[str, str] = {}

    def root(x: str) -> str:
        while up.get(x, x) != x:
            x = up[x]
        return x

    for a, b in links:
        ra, rb = root(a), root(b)
        if ra != rb:
            up[max(ra, rb)] = min(ra, rb)
    members: dict[str, set[str]] = {}
    for p in {x for link in links for x in link}:
        members.setdefault(root(p), set()).add(p)
    pointing = {a for a, _ in links}
    out = {}
    for ids in members.values():
        heads = sorted(ids - pointing)
        head = heads[0] if len(heads) == 1 else min(ids)
        out.update({p: head for p in ids})
    return out


def group(cx: sqlite3.Connection, person: str) -> set[str]:
    """The ids that are one human with `person` (the Owner's `same_as`, connected sets), `person` included."""
    g = _groups(cx)
    if person not in g:
        return {person}
    return {p for p, h in g.items() if h == g[person]}


def _grp_sql(groups: dict[str, str], col: str) -> str:
    """SQL for the group id of the person in `col` (ids are checked: `ID_RE`, so they can stand in the text)."""
    if not groups:
        return col
    return f"CASE {col} " + " ".join(f"WHEN '{p}' THEN '{h}'" for p, h in sorted(groups.items())) + f" ELSE {col} END"


def _latest_in_group(rows: list[dict], groups: dict[str, str]) -> dict[tuple[str, str, str], dict]:
    """{(claim, passage, group): the row that counts}: of one human's judgements of an excerpt on several computers,
    the later (`at`) counts. That use of the time is between one person's own computers (BRIEF §2.6)."""
    out: dict[tuple[str, str, str], dict] = {}
    for r in rows:
        k = (r["claim_id"], r["passage_id"], groups.get(r["person_id"], r["person_id"]))
        if k not in out or (r["at"] or "") > (out[k]["at"] or ""):
            out[k] = r
    return out
