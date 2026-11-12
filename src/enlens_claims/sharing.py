"""Private until shared (0.18, roadmap L1): what a person makes in a project is theirs alone until they share it.

"I could check five hypotheses, but until I find an interesting one there is no reason for others to see it." Each
copy of a shared project sends only what was shared (a zip for a colleague, `bundle.export_project(scope="shared")`,
and the shared folder of 0.18); sharing and taking back (*Unshare*) are deliberate acts, each in the research log.

**The kinds of item, and what sharing one covers.** An item is known in every copy by its kind and key, the same
everywhere (its id travels with it):

- `check` (key: the hypothesis id): the hypothesis, its parts, every excerpt the AI judged and the answers and rounds
  behind them, second opinions, and everyone's judgements of its excerpts. Sharing a check tagged with a code of your
  own codebook shares that codebook too (a colleague could not read the check without it);
- `themes` (key: the theme run's id): the set of themes, its members, the names the AI gave, and the edits people made
  to themes of those settings;
- `codebook` (key: its name): its codes (the CSV and the side file), the labels made with it (the AI's and people's)
  and the reviews of them, and the AI work behind its labels;
- `note` (key: the note's id): a note or a highlight;
- `log` (key: the entry's id): an entry a person wrote in the research log. The entries the app writes by itself follow
  what they are about: about a check, a set of themes or a codebook, they travel when it is shared; about the
  documents (added, removed, read again, who may read them with AI), always, as the documents do; about this copy only
  (work brought in, the glossary's own words), never;
- `link` (key: the two terms' ids, `a|b`): a person's decision about how two terms relate (and their reviews of a link
  the app proposed), and the AI's judgement of the pair.

What is not an item is the project's, shared as before: the documents and their readings (L2 decides changes of the
corpus), who may read each with AI (the stricter setting wins in every copy), the bibliography, AI work on documents
that holds nobody's decision (labels with the bundled SDG codebooks, reference chains, the SDG pack), the links the app
finds by itself (abbreviations, meaning), and the ledger of what was sent to Claude (so a cap on what Claude may read
counts every copy's reading).

**States.** Each item is `private`, `shared` or `withdrawn` (shared once, taken back). A row in `shares` says so, with
the item's `owner` (who made it: only they share or withdraw it; NULL when nobody knows, for items made before 0.18),
who set the state (`by`) and when (`at`). No row: made in this copy by this copy's person, and private. A database that
leaves the computer has a row for every item (`materialise`), so a colleague knows whose each is.

- *Share* (`share`): sends from now on. *Unshare* (`unshare`): stops sending; a colleague's copy marks it withdrawn
  when the mark reaches it, and keeps what it has (nothing is taken from anyone); a copy that does not have it yet does
  not get it from a third person (`sync/share_merge.py`).
- Projects exchanged as zips before 0.18 (they have a `sync_seen` or `sync_log` row) count as shared: their items went
  to colleagues already (`upgrade`, once, when 0.18 first opens the project). A project never sent starts private.
- An item that reached you inside a colleague's whole project zip (not shared by them) stays theirs and private: you
  see it, you never pass it on.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from pathlib import Path
from typing import Iterable, Iterator

KINDS = ("check", "themes", "codebook", "note", "log", "link")
STATES = ("private", "shared", "withdrawn")
WORDS = {"check": ("check", "checks"), "themes": ("set of themes", "sets of themes"), "codebook": ("codebook", "codebooks"),
         "note": ("note", "notes"), "log": ("research log entry", "research log entries"),
         "link": ("link between terms", "links between terms")}
LOCAL_LOG_KINDS = {"sync", "glossary-words"}  # the research log's entries about this copy only: never sent
# the tables about this copy only (sync.LOCAL_ONLY): emptied in a zip sent to a colleague, except `meta`
_LOCAL_TABLES = ("embeddings", "code_vectors", "terms", "term_mentions", "concepts", "concept_terms", "task_claims",
                 "sync_log", "versions", "sync_written", "sync_folder_read", "sync_folder_docs")
# the keys of `meta` a zip for a colleague keeps (besides `codebook_followed:` of shared codebooks and `read_again:`
# of documents): what a colleague's merge or import reads
_META_KEPT = {"project_uid", "project_uids_known", "bibliography", "corpus_version"}


def _at() -> str:
    """Now, to the microsecond: of two marks of one item, the later one counts in every copy."""
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _me() -> str:
    from .people import me

    return me()


def has_table(cx: sqlite3.Connection) -> bool:
    return bool(cx.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shares'").fetchone())


def _q(n: int) -> str:
    return ",".join("?" * n)


# ---------------------------------------------------------------------------------------------
# the items of a project
# ---------------------------------------------------------------------------------------------
def _codebook_names(cx: sqlite3.Connection, root: Path | None) -> set[str]:
    """The project's own codebooks (its `frameworks/`), and those it uses from the home folder."""
    from .frameworks import BUNDLED, NAME_RE

    names = set()
    folder = Path(root) / "frameworks" if root else None
    if folder and folder.is_dir():
        names |= {p.stem for p in folder.glob("*.csv")}
    for sql in ("SELECT DISTINCT framework FROM labels", "SELECT DISTINCT framework FROM hypotheses",
                "SELECT DISTINCT framework FROM user_claims"):
        names |= {r[0] for r in cx.execute(sql) if r[0]}
    return {n for n in names - set(BUNDLED) if NAME_RE.match(n)}


def items(cx: sqlite3.Connection, root: Path | str | None) -> dict[str, dict[str, str]]:
    """{kind: {key: title}} of every item the project holds (`root`: the project folder, for its codebooks)."""
    from .researchlog import day

    out: dict[str, dict[str, str]] = {k: {} for k in KINDS}
    for hid, text in cx.execute("SELECT hyp_id, text FROM hypotheses"):
        out["check"][hid] = text or ""
    for rid, created, k in cx.execute("SELECT run_id, created_at, k FROM theme_runs"):
        out["themes"][rid] = f"{k or ''} themes found on {day(created)}".strip()
    for name in _codebook_names(cx, Path(root) if root else None):
        out["codebook"][name] = name
    for nid, quote in cx.execute("SELECT note_id, quote FROM notes"):
        out["note"][nid] = " ".join((quote or "").split())[:120]
    for eid, text in cx.execute("SELECT entry_id, text FROM research_log WHERE kind='entry'"):
        out["log"][eid] = " ".join((text or "").split())[:120]
    pairs = {f"{a}|{b}" for a, b in cx.execute("SELECT a, b FROM concept_links WHERE source IN ('person', 'model')")}
    pairs |= {r[0] for r in cx.execute("SELECT DISTINCT item_id FROM reviews WHERE item_kind='concept_link'") if r[0]}
    labels = {r[0]: r[1] for r in cx.execute("SELECT term_id, label FROM terms")}
    for p in pairs:
        a, _, b = p.partition("|")
        out["link"][p] = f"{labels.get(a, a)} – {labels.get(b, b)}"
    return out


def exists(cx: sqlite3.Connection, root: Path | str | None, kind: str, key: str) -> bool:
    """Whether the project holds the item now."""
    if kind == "check":
        return bool(cx.execute("SELECT 1 FROM hypotheses WHERE hyp_id=?", (key,)).fetchone())
    if kind == "themes":
        return bool(cx.execute("SELECT 1 FROM theme_runs WHERE run_id=?", (key,)).fetchone())
    if kind == "codebook":  # the project's own, or one kept with all projects that this project uses
        from .home import home

        if root and (Path(root) / "frameworks" / f"{key}.csv").is_file():
            return True
        return (home() / "frameworks" / f"{key}.csv").is_file() and key in _codebook_names(cx, None)
    if kind == "note":
        return bool(cx.execute("SELECT 1 FROM notes WHERE note_id=?", (key,)).fetchone())
    if kind == "log":
        return bool(cx.execute("SELECT 1 FROM research_log WHERE entry_id=? AND kind='entry'", (key,)).fetchone())
    if kind == "link":
        a, _, b = key.partition("|")
        return bool(cx.execute("SELECT 1 FROM concept_links WHERE a=? AND b=? AND source IN ('person', 'model')",
                               (a, b)).fetchone()
                    or cx.execute("SELECT 1 FROM reviews WHERE item_kind='concept_link' AND item_id=?", (key,)).fetchone())
    raise KeyError(kind)


def rows(cx: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    """{(kind, key): {"state", "owner", "by", "at", "title"}} of every row of `shares`."""
    if not has_table(cx):
        return {}
    return {(r[0], r[1]): {"state": r[2], "owner": r[3], "by": r[4], "at": r[5], "title": r[6]}
            for r in cx.execute("SELECT kind, key, state, owner, by, at, title FROM shares")}


def state(cx: sqlite3.Connection, kind: str, key: str, me: str | None = None) -> dict:
    """An item's state here: {"state", "owner", "by", "at", "mine"}. No row: yours, and private."""
    m = me or _me()
    r = cx.execute("SELECT state, owner, by, at FROM shares WHERE kind=? AND key=?", (kind, key)).fetchone()
    if r is None:
        return {"state": "private", "owner": m, "by": None, "at": None, "mine": True}
    return {"state": r[0], "owner": r[1], "by": r[2], "at": r[3], "mine": r[1] == m}


def shared_keys(cx: sqlite3.Connection, kind: str) -> set[str]:
    """The keys of the items of one kind that are shared here (what this copy sends)."""
    return {r[0] for r in cx.execute("SELECT key FROM shares WHERE kind=? AND state='shared'", (kind,))}


# ---------------------------------------------------------------------------------------------
# rows made once: projects from before 0.18, and a database that leaves the computer
# ---------------------------------------------------------------------------------------------
def _makers(cx: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """Who made each item, where the project knows it: the research log names who added a check, found a set of
    themes or made a codebook (since 0.16); a note and an entry name their author."""
    out = {}
    for kind, subject, sk in (("check-added", "check", "check"), ("themes-found", "themes", "themes"),
                              ("codebook-added", "codebook", "codebook")):
        for sid, pid in cx.execute("SELECT subject_id, person_id FROM research_log WHERE kind=? AND subject_kind=? "
                                   "ORDER BY at", (kind, subject)):
            if sid and pid:
                out.setdefault((sk, sid), pid)
    for nid, pid in cx.execute("SELECT note_id, person_id FROM notes"):
        if pid:
            out[("note", nid)] = pid
    for eid, pid in cx.execute("SELECT entry_id, person_id FROM research_log WHERE kind='entry'"):
        if pid:
            out[("log", eid)] = pid
    return out


def exchanged(cx: sqlite3.Connection, me: str | None = None) -> bool:
    """Whether a project was exchanged with a colleague before 0.18: a colleague's work was brought in (`sync_log`), or
    the project knows someone else (it came from a colleague's zip). Not `sync_seen`: 0.14 to 0.17 wrote it for every
    zip, a backup or a move to another computer too. It makes nothing: this installation's person id is read, not made
    (a new project is opened before anyone has one, and making one writes the settings file)."""
    if cx.execute("SELECT 1 FROM sync_log LIMIT 1").fetchone():
        return True
    known = [r[0] for r in cx.execute("SELECT person_id FROM people") if r[0]]
    if not known:
        return False
    if me is None:
        from .home import load_settings

        me = load_settings().get("person_id") or ""
    return any(p != me for p in known)


def upgrade(cx: sqlite3.Connection, root: Path | str | None) -> int:
    """Once, when this version first opens a project (the table `shares` is new): a project already exchanged with a
    colleague (`exchanged`) counts as shared, item by item, with the maker where the project knows it; a project never
    exchanged starts private (no rows). These rows are a guess, not anyone's word (`by` and `at` empty): a real mark,
    here or from a colleague, always counts over them (`receive`). Returns how many items were marked shared."""
    if not exchanged(cx):
        return 0
    makers = _makers(cx)
    out = [(kind, key, "shared", makers.get((kind, key)), None, None, (title or "")[:200])
           for kind, keys in items(cx, root).items() for key, title in keys.items()]
    cx.executemany("INSERT OR IGNORE INTO shares(kind, key, state, owner, by, at, title) VALUES (?,?,?,?,?,?,?)", out)
    return len(out)


def materialise(cx: sqlite3.Connection, root: Path | str | None, me: str) -> int:
    """A row for every item that has none (made here by `me`, private), in a copy of the database about to leave the
    computer, so whoever opens it knows whose each item is."""
    have = set(rows(cx))
    at = _at()
    out = [(kind, key, "private", me, me, at, (title or "")[:200])
           for kind, keys in items(cx, root).items() for key, title in keys.items() if (kind, key) not in have]
    cx.executemany("INSERT OR IGNORE INTO shares(kind, key, state, owner, by, at, title) VALUES (?,?,?,?,?,?,?)", out)
    return len(out)


# ---------------------------------------------------------------------------------------------
# share and unshare
# ---------------------------------------------------------------------------------------------
def _clean_items(raw: Iterable) -> list[tuple[str, str]]:
    out = []
    for it in raw or []:
        kind, key = (it.get("kind"), it.get("key")) if isinstance(it, dict) else (it[0], it[1])
        if kind not in KINDS:
            raise ValueError(f"Unknown kind of item {kind!r}: one of {', '.join(KINDS)}.")
        if not isinstance(key, str) or not key or len(key) > 400:
            raise ValueError("Say which item: its kind and its key.")
        if (kind, key) not in out:
            out.append((kind, key))
    if not out:
        raise ValueError("Choose what to share first.")
    return out


def needs(cx: sqlite3.Connection, root: Path | str | None, kind: str, key: str) -> list[tuple[str, str]]:
    """What sharing an item shares too, so a colleague can read it: a check tagged with a code of a codebook of your
    own needs that codebook."""
    if kind != "check":
        return []
    from .frameworks import BUNDLED

    names = {r[0] for r in cx.execute("SELECT framework FROM hypotheses WHERE hyp_id=? UNION SELECT framework FROM "
                                      "user_claims WHERE hyp_id=?", (key, key)) if r[0] and r[0] not in BUNDLED}
    return [("codebook", n) for n in sorted(names) if exists(cx, root, "codebook", n)]


def _set(cx: sqlite3.Connection, kind: str, key: str, st: str, owner: str | None, by: str, title: str) -> None:
    cx.execute("INSERT INTO shares(kind, key, state, owner, by, at, title) VALUES (?,?,?,?,?,?,?) ON CONFLICT(kind, key) "
               "DO UPDATE SET state=excluded.state, by=excluded.by, at=excluded.at, title=excluded.title",
               (kind, key, st, owner, by, _at(), (title or "")[:200]))


def _may(cx: sqlite3.Connection, kind: str, key: str, me: str, title: str) -> dict:
    """The item's state, when `me` may share it or take it back: theirs, or one whose maker nobody knows."""
    s = state(cx, kind, key, me)
    if s["owner"] not in (None, me):
        who = names_of(cx).get(s["owner"]) or "a colleague"
        raise PermissionError(f"“{title[:80]}” is {who}'s: only they can share it or take it back.")
    return s


def names_of(cx: sqlite3.Connection) -> dict[str, str]:
    return {r[0]: (r[1] or "a colleague") for r in cx.execute("SELECT person_id, name FROM people")}


def _log(cx: sqlite3.Connection, verb: str, done: list[tuple[str, str, str]], why: str | None) -> None:
    from . import researchlog

    if not done:
        return
    if len(done) == 1:
        kind, key, title = done[0]
        text = f"{verb} the {WORDS[kind][0]} {researchlog.quoted(title, 120)}."
        researchlog.record(cx, "shared" if verb == "Shared" else "unshared", text, kind, key, title, why=why,
                           data={"items": [{"kind": kind, "key": key}]})
        return
    by_kind: dict[str, list[str]] = {}
    for kind, _key, title in done:
        by_kind.setdefault(kind, []).append(title)
    parts = [f"{len(t)} {WORDS[k][0] if len(t) == 1 else WORDS[k][1]}" for k, t in by_kind.items()]
    names = "; ".join(researchlog.quoted(t, 60) for _k, _key, t in done[:6]) + ("; …" if len(done) > 6 else "")
    researchlog.record(cx, "shared" if verb == "Shared" else "unshared", f"{verb} {', '.join(parts)}: {names}.",
                       why=why, data={"items": [{"kind": k, "key": key} for k, key, _t in done]})


def share(ws, raw_items: Iterable, why: str | None = None) -> dict:
    """Share items (`[{"kind", "key"}]`) and what they need (`needs`). Raises KeyError for an item the project does not
    hold, PermissionError for a colleague's. Returns {"shared": [items], "also": [items shared because another needs
    them], "already": [items shared before, by you or their owner], "cannot": [items needed that are a colleague's and
    not shared by them: a colleague without them sees the item without them]}; the research log says what was
    shared."""
    me = _me()
    asked = _clean_items(raw_items)
    root = Path(ws.root)
    with ws.connect() as cx:
        titles = items(cx, root)
        todo, also = list(asked), []
        for kind, key in asked:
            if key not in titles[kind] and not exists(cx, root, kind, key):
                raise KeyError(f"{kind}:{key}")
            for dep in needs(cx, root, kind, key):
                if dep not in todo:
                    todo.append(dep)
                    also.append(dep)
        done, already, cannot = [], [], []
        for kind, key in todo:
            title = titles[kind].get(key) or key
            if (kind, key) in also:  # what a shared item needs: a colleague's is shared by them, or stays theirs
                s = state(cx, kind, key, me)
                if s["owner"] not in (None, me):
                    (already if s["state"] == "shared" else cannot).append({"kind": kind, "key": key, "title": title})
                    continue
            s = _may(cx, kind, key, me, title)
            if s["state"] == "shared":
                already.append({"kind": kind, "key": key, "title": title})
                continue
            _set(cx, kind, key, "shared", s["owner"], me, title)  # no row yet: yours (`state`)
            done.append((kind, key, title))
        _log(cx, "Shared", done, why)
    view = lambda k, key, t: {"kind": k, "key": key, "title": t}  # noqa: E731
    return {"shared": [view(*d) for d in done if (d[0], d[1]) not in also],
            "also": [view(*d) for d in done if (d[0], d[1]) in also], "already": already, "cannot": cannot}


def unshare(ws, raw_items: Iterable, why: str | None = None) -> dict:
    """Take shared items back: they stop being sent, and a colleague's copy marks them withdrawn when the mark
    reaches it (what they have stays with them). Returns {"withdrawn": [items], "not_shared": [items]}."""
    me = _me()
    asked = _clean_items(raw_items)
    root = Path(ws.root)
    with ws.connect() as cx:
        titles = items(cx, root)
        done, not_shared = [], []
        for kind, key in asked:
            known = cx.execute("SELECT title FROM shares WHERE kind=? AND key=?", (kind, key)).fetchone()
            if key not in titles[kind] and known is None:
                raise KeyError(f"{kind}:{key}")
            title = titles[kind].get(key) or (known[0] if known else None) or key
            s = _may(cx, kind, key, me, title)
            if s["state"] != "shared":
                not_shared.append({"kind": kind, "key": key, "title": title})
                continue
            _set(cx, kind, key, "withdrawn", s["owner"], me, title)
            done.append((kind, key, title))
        _log(cx, "Unshared", done, why)
    return {"withdrawn": [{"kind": k, "key": key, "title": t} for k, key, t in done], "not_shared": not_shared}


def listing(ws, kind: str | None = None, state_: str | None = None) -> dict:
    """Every item of the project with its state, for the Team tab and an item's own page: {"items": [{"kind", "key",
    "title", "state", "mine", "owner": {"id", "name"} | None, "can_change", "at", "by", "here", "needs"}], "counts":
    {kind: {state: n}}}. Items withdrawn that the project no longer holds are listed too (`here`: False)."""
    from .frameworks import available
    from .people import names

    if kind is not None and kind not in KINDS:
        raise ValueError(f"Unknown kind of item {kind!r}: one of {', '.join(KINDS)}.")
    if state_ is not None and state_ not in STATES:
        raise ValueError(f"Unknown state {state_!r}: one of {', '.join(STATES)}.")
    me = _me()
    who = names(ws)
    cx = ws._conn()
    root = Path(ws.root)
    titles = items(cx, root)
    fws = available(ws)
    for n in titles["codebook"]:
        if n in fws:
            titles["codebook"][n] = fws[n].title
    have = rows(cx)
    out, counts = [], {k: {s: 0 for s in STATES} for k in KINDS}
    keys = {(k, key) for k, ks in titles.items() for key in ks} | set(have)
    for k, key in sorted(keys):
        r = have.get((k, key))
        st = r["state"] if r else "private"
        owner = (r["owner"] if r else me)
        counts[k][st] += 1
        if (kind and k != kind) or (state_ and st != state_):
            continue
        here = key in titles[k]
        out.append({"kind": k, "key": key, "title": titles[k].get(key) or (r or {}).get("title") or key, "state": st,
                    "mine": owner == me, "owner": {"id": owner, "name": who.get(owner, "a colleague")} if owner else None,
                    "can_change": owner in (None, me) and here, "at": (r or {}).get("at"),
                    "by": who.get(r["by"], "a colleague") if r and r.get("by") else None, "here": here,
                    "needs": [{"kind": a, "key": b} for a, b in needs(cx, root, k, key)] if here else []})
    return {"items": out, "counts": counts}


def one(ws, kind: str, key: str) -> dict:
    """One item's state, for its own page (KeyError when the project holds no such item)."""
    got = [i for i in listing(ws, kind)["items"] if i["key"] == key]
    if not got:
        raise KeyError(f"{kind}:{key}")
    return got[0]


# ---------------------------------------------------------------------------------------------
# a colleague's marks (sync/share_merge.py)
# ---------------------------------------------------------------------------------------------
def receive(cx: sqlite3.Connection, kind: str, key: str, r: dict, me: str, present: bool,
            had: bool | None = None) -> str | None:
    """A colleague's mark of an item (their row, `r`). Only an item's owner decides about it: a mark about your own item
    changes nothing here, nor one by someone else than its owner; of two marks the later counts. A withdrawal is noted
    also for an item this copy does not hold (`present`), so a third person's copy does not bring it here later.
    `had`: whether this copy held the item before the merge (an item without a row is then this copy's own; one that
    just came in has no row yet); None: as `present`. Returns the new state here, or None when nothing changed."""
    if kind not in KINDS or r.get("state") not in STATES:
        return None
    here = cx.execute("SELECT state, owner, by, at FROM shares WHERE kind=? AND key=?", (kind, key)).fetchone()
    had = present if had is None else had
    if (here is None and had) or (here is not None and here[1] == me):
        return None  # yours: only you decide
    if not present and here is None and r["state"] != "withdrawn":
        return None  # not here (it did not come in): nothing to note
    if here is not None and r.get("by") is None:
        return None  # a guess (a project from before 0.18) never counts over a mark this copy has
    owner = here[1] if here is not None else r.get("owner")  # a mark never makes anyone the owner of an item here
    if owner and r.get("by") not in (None, owner):
        return None  # a mark only its owner can make
    if here is not None and (r.get("at") or "") <= (here[3] or ""):
        return None
    cx.execute("INSERT INTO shares(kind, key, state, owner, by, at, title) VALUES (?,?,?,?,?,?,?) ON CONFLICT(kind, key) "
               "DO UPDATE SET state=excluded.state, owner=excluded.owner, by=excluded.by, at=excluded.at, "
               "title=COALESCE(excluded.title, shares.title)",
               (kind, key, r["state"], owner, r.get("by"), r.get("at") or _at(), r.get("title")))
    return None if here is not None and here[0] == r["state"] else r["state"]


# ---------------------------------------------------------------------------------------------
# the rows of an item: one definition for taking items out of a copy of the database (a zip for a colleague, the
# merge's scratch copy) and for writing them into the shared folder (sync/folder.py)
# ---------------------------------------------------------------------------------------------
ROWID = "_rowid"  # the key of each row's own row number in what `rows_of` returns


def _select(cx: sqlite3.Connection, table: str, where: str, args: Iterable = ()) -> list[dict]:
    cur = cx.execute(f"SELECT rowid AS {ROWID}, * FROM {table} WHERE {where}", tuple(args))
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _review_fields(title: str | None) -> dict | None:
    """The fields of a review taken back, as its note of removal keeps them (people.forget_reviews); None when the note
    names the review by its key alone."""
    try:
        f = json.loads(title or "")
    except ValueError:
        return None
    return f if isinstance(f, dict) else None


def rows_of(cx: sqlite3.Connection, kind: str, key: str) -> dict[str, list[dict]]:
    """Every row an item covers, {table: [rows]}, each row with its row number (`ROWID`): the one definition of what
    sharing an item covers (see the module's notes). `drop` deletes exactly these rows; the shared folder writes exactly
    these (sync/folder.py), so what leaves a copy for a colleague is the same whichever way it leaves.

    Besides the item's own rows: what the sync tables say about it (its states, a sync-clash mark, its note of removal:
    a removed item that was shared is still an item, made of that note), notes of reviews taken back that are about it,
    and the entries the app wrote in the research log about it (also *Shared* and *Unshared* about it alone)."""
    from .sync.fingerprints import check_tasks, themes_tasks

    out: dict[str, list[dict]] = {}

    def add(table: str, where: str, args: Iterable = ()) -> list[dict]:
        got = _select(cx, table, where, args)
        if got:
            out.setdefault(table, []).extend(got)
        return got

    def add_in(table: str, col: str, ids: Iterable[str], extra: str = "") -> None:
        ids = sorted(set(ids))
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            add(table, f"{extra}{col} IN ({_q(len(chunk))})", chunk)

    def review_notes(test) -> None:
        for r in _select(cx, "sync_removed", "kind='review'"):
            f = _review_fields(r.get("title"))
            if f and test(f.get("item_kind"), str(f.get("item_id") or "")):
                out.setdefault("sync_removed", []).append(r)

    if kind == "check":
        add("hypotheses", "hyp_id=?", (key,))
        cids = [r["claim_id"] for r in add("user_claims", "hyp_id=?", (key,))]
        add_in("verifications", "subject_id", cids, "subject_kind='user_claim' AND ")
        add_in("second_opinions", "subject_id", cids)
        add_in("judgements", "claim_id", cids)
        where, args = check_tasks(key, cids)  # also a check without parts: its split into parts
        add_in("results", "task_id", [r["task_id"] for r in add("tasks", where, args)])
    elif kind == "themes":
        run = add("theme_runs", "run_id=?", (key,))
        add("themes", "run_id=?", (key,))
        add("theme_members", "run_id=?", (key,))
        where, args = themes_tasks(key)
        add_in("results", "task_id", [r["task_id"] for r in add("tasks", where, args)])
        rkey = (run[0].get("run_key") if run else None) or ""
        if rkey:  # the edits people made to themes, kept by the run's settings (themes.py)
            head = rkey + ":"
            add("reviews", "item_kind IN ('theme', 'theme_member') AND substr(item_id, 1, ?) = ?", (len(head), head))
            review_notes(lambda ik, iid: ik in ("theme", "theme_member") and iid.startswith(head))
    elif kind == "codebook":
        lids = {r["label_id"] for r in add("labels", "framework=?", (key,))}
        add_in("reviews", "item_id", lids, "item_kind='label' AND ")
        head = f"label:{key}:"
        tids = [r["task_id"] for r in add("tasks", "substr(task_id, 1, ?) = ?", (len(head), head))]
        add_in("results", "task_id", tids)
        add("sync_seen", "kind='code' AND substr(key, 1, ?) = ?", (len(key) + 1, key + "/"))
        add("meta", "key=?", (f"codebook_followed:{key}",))
        add("runs", "kind='label' AND scope=?", (key,))
        if lids:
            review_notes(lambda ik, iid: ik == "label" and iid in lids)
    elif kind == "note":
        add("notes", "note_id=?", (key,))
    elif kind == "log":
        add("research_log", "entry_id=? AND kind='entry'", (key,))
    elif kind == "link":
        a, _, b = key.partition("|")
        add("concept_links", "a=? AND b=? AND source IN ('person', 'model')", (a, b))
        add("reviews", "item_kind='concept_link' AND item_id=?", (key,))
        add_in("results", "task_id", [r["task_id"] for r in add("tasks", "task_id=?", (f"link:{key}",))])
        review_notes(lambda ik, iid: ik == "concept_link" and iid == key)
    else:
        raise KeyError(kind)
    if kind != "link":  # what the sync tables say about it (a link has no states: it is not a sync unit)
        for t in ("sync_seen", "sync_copies", "sync_removed"):
            add(t, "kind=? AND key=?", (kind, key))
        add("sync_seen", "kind=? AND key=?", (f"placed:{kind}", key))
    # what the app's research log wrote about it
    add("research_log", "kind != 'entry' AND subject_kind=? AND subject_id=?", (kind, key))
    return out


def _delete_rows(cx: sqlite3.Connection, table: str, rowids: Iterable[int]) -> None:
    ids = sorted(set(rowids))
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        cx.execute(f"DELETE FROM {table} WHERE rowid IN ({_q(len(chunk))})", chunk)


def drop(cx: sqlite3.Connection, kind: str, keys: Iterable[str]) -> int:
    """Take items out of a copy of a project's database: exactly their rows (`rows_of`). Never used on a project in
    use: only on a copy about to leave the computer, or the colleague's scratch copy of a merge. The edits people made
    to themes are kept by a theme run's settings, which two runs can share: those a run that stays still uses stay.
    Returns how many items."""
    keys = sorted(set(keys))
    if not keys:
        return 0
    if kind not in KINDS:
        raise KeyError(kind)
    gone: dict[str, set[int]] = {}
    for key in keys:
        for table, got in rows_of(cx, kind, key).items():
            gone.setdefault(table, set()).update(r[ROWID] for r in got)
    if kind == "themes" and (gone.get("reviews") or gone.get("sync_removed")):
        left = tuple(r[0] + ":" for r in cx.execute(f"SELECT run_key FROM theme_runs WHERE run_id NOT IN "
                                                    f"({_q(len(keys))})", keys) if r[0])
        if left:
            for rowid, item in cx.execute("SELECT rowid, item_id FROM reviews WHERE item_kind IN ('theme', "
                                          "'theme_member')").fetchall():
                if (item or "").startswith(left):
                    gone.get("reviews", set()).discard(rowid)
            for rowid, title in cx.execute("SELECT rowid, title FROM sync_removed WHERE kind='review'").fetchall():
                f = _review_fields(title)
                if f and str(f.get("item_id") or "").startswith(left):
                    gone.get("sync_removed", set()).discard(rowid)
    for table, rowids in gone.items():
        _delete_rows(cx, table, rowids)
    return len(keys)


def log_entry_travels(kind: str, subject_kind: str | None, subject_id: str | None, data: str | None,
                      shared: set[tuple[str, str]]) -> bool:
    """Whether an entry the app wrote in the research log (not a person's own: those are items) may leave this copy:
    never one about this copy only (`LOCAL_LOG_KINDS`); one about an item only when it is shared (`shared`: its
    (kind, key)); *Shared* or *Unshared* about several items only when every one of them is."""
    if kind in LOCAL_LOG_KINDS or (subject_kind in KINDS and (subject_kind, subject_id) not in shared):
        return False
    if kind in ("shared", "unshared"):  # an entry about several items names them all: each must be shared
        try:
            listed = [(i.get("kind"), i.get("key")) for i in (json.loads(data or "{}") or {}).get("items") or []
                      if isinstance(i, dict)]
        except (ValueError, AttributeError):
            return False
        return all(i in shared for i in listed)
    return True


def strip(cx: sqlite3.Connection, root: Path | str | None, me: str) -> dict:
    """In a copy of the project's database for a colleague (`bundle.export_project(scope="shared")`): every item that is
    not shared goes, with what is made of it; a withdrawn item leaves only its mark (so the colleague's copy marks it
    withdrawn); the research log keeps the app's entries about shared items and the documents, and none about this copy
    only; the ledger of what was sent to Claude keeps every row, without the task of work not shared; no document says
    where its file is on this computer; the tables about this copy only are emptied. Returns {kind: items taken out}. VACUUM the file after, so
    nothing taken out stays in its free pages."""
    materialise(cx, root, me)
    have = rows(cx)
    out = {}
    for kind in KINDS:
        gone = [key for (k, key), r in have.items() if k == kind and r["state"] != "shared"]
        out[kind] = drop(cx, kind, gone)
    shared = {(k, key) for (k, key), r in have.items() if r["state"] == "shared"}
    marked = {(k, key) for (k, key), r in have.items() if r["state"] == "withdrawn"}
    # a withdrawn item travels as its mark alone: no title (a colleague who never had it learns nothing of it)
    cx.execute("DELETE FROM shares WHERE state='private'")
    cx.execute("UPDATE shares SET title=NULL WHERE state='withdrawn'")
    for eid, kind, sk, sid, data in cx.execute("SELECT entry_id, kind, subject_kind, subject_id, data_json FROM "
                                               "research_log WHERE kind != 'entry'").fetchall():
        if not log_entry_travels(kind, sk, sid, data, shared):
            cx.execute("DELETE FROM research_log WHERE entry_id=?", (eid,))
    # the edits people made to themes of settings no run left here uses (of a set of themes removed long ago)
    left = tuple(r[0] + ":" for r in cx.execute("SELECT run_key FROM theme_runs") if r[0])
    for rowid, item in cx.execute("SELECT rowid, item_id FROM reviews WHERE item_kind IN ('theme', "
                                  "'theme_member')").fetchall():
        if not left or not (item or "").startswith(left):
            cx.execute("DELETE FROM reviews WHERE rowid=?", (rowid,))
    # notes of removal: a removed item's text is in them (a check's hypothesis, an entry's words, a note's quote)
    for kind, key in cx.execute("SELECT kind, key FROM sync_removed WHERE kind IN ('check', 'themes', 'note', "
                                "'log')").fetchall():
        if (kind, key) in marked:
            cx.execute("UPDATE sync_removed SET title=NULL WHERE kind=? AND key=?", (kind, key))
        elif (kind, key) not in shared:
            cx.execute("DELETE FROM sync_removed WHERE kind=? AND key=?", (kind, key))
    run_keys = tuple(r[0] + ":" for r in cx.execute("SELECT run_key FROM theme_runs") if r[0])
    for key, title in cx.execute("SELECT key, title FROM sync_removed WHERE kind='review'").fetchall():
        try:
            f = json.loads(title or "")
        except ValueError:
            f = None
        if not isinstance(f, dict):
            continue  # a review taken back by its key alone: its key says nothing
        ik, iid = f.get("item_kind"), str(f.get("item_id") or "")
        keep = (bool(cx.execute("SELECT 1 FROM labels WHERE label_id=?", (iid,)).fetchone()) if ik == "label" else
                ("link", iid) in shared if ik == "concept_link" else
                bool(run_keys) and iid.startswith(run_keys) if ik in ("theme", "theme_member") else True)
        if not keep:
            cx.execute("DELETE FROM sync_removed WHERE kind='review' AND key=?", (key,))
    # this copy's own settings and state (the glossary's, the queue's, test runs with paths of this computer): only
    # what a colleague's copy reads is kept
    for (k,) in cx.execute("SELECT key FROM meta").fetchall():
        follows = k.startswith("codebook_followed:") and ("codebook", k.split(":", 1)[1]) in shared
        if k not in _META_KEPT and not follows and not k.startswith("read_again:"):
            cx.execute("DELETE FROM meta WHERE key=?", (k,))
    # where each document's file is on this computer stays here (a folder's name can say much): whoever opens the zip
    # finds the files that came in it by what the zip says of them (bundle.import_project)
    cx.execute("UPDATE documents SET path=NULL")
    # the bibliography's attachments go without where they are on this computer
    for key, files in cx.execute("SELECT item_key, files_json FROM bib_items").fetchall():
        cx.execute("UPDATE bib_items SET files_json=? WHERE item_key=?", (without_paths(files), key))
    # the ledger of what was sent to Claude stays whole (a cap on what Claude may read counts every copy's reading),
    # but a row of work that is not shared no longer names its task (a check's id is in it)
    cx.execute("UPDATE ai_sent SET task_id='private' WHERE task_id IS NOT NULL AND task_id NOT IN (SELECT task_id FROM "
               "tasks)")
    present = {r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in _LOCAL_TABLES:
        if t in present:
            cx.execute(f"DELETE FROM {t}")
    return out


# ---------------------------------------------------------------------------------------------
# the project's rows: no one's item (0.18, the shared folder, sync/folder.py)
# ---------------------------------------------------------------------------------------------
# tasks of these kinds belong to checks and theme runs (sync.fingerprints check_tasks, themes_tasks), never to the project
ITEM_TASK_KINDS = ("check", "expand", "decompose", "reread", "second", "theme")
# tables without words of a document in them: a document kept out of the shared folder does not keep these rows out
_NO_TEXT = {"ai_sent", "people", "bib_items", "bib_links", "research_log", "sync_removed", "runs", "meta",
            "ownership", "proposals", "decisions", "canon"}  # 0.18 L2: they name documents, and hold none of their words
# a task's columns that say what became of it (its payload, the passages handed to the AI, is read only when a document
# is kept out of the shared folder, to see which documents it names)
_TASK_COLS = "task_id, kind, status, attempts, model, again, step"


def without_paths(files_json: str | None) -> str | None:
    """A bibliography work's attachments without where they are on this computer (`path`, and what describes the file
    there: `exists`, `mtime`, `size`): their names and types only, as they leave it (a zip for a colleague, the shared
    folder)."""
    try:
        files = json.loads(files_json or "null")
    except ValueError:
        return None
    if not isinstance(files, list):
        return files_json
    local = ("path", "exists", "mtime", "size")
    return json.dumps([{k: v for k, v in f.items() if k not in local} if isinstance(f, dict) else f for f in files],
                      ensure_ascii=False)


def task_names_kept_out(task_id: str | None, payload_json: str | None, kept_out: set[str]) -> bool:
    """Whether a task is about a document whose words must not leave: one its id names (a passage id, a document id), or
    one its payload hands to the AI (the SDG pack's tasks name no document in their id)."""
    if not kept_out:
        return False
    from .access import ids_in
    from .sync.common import _TOKEN

    if any(x in kept_out for x in _TOKEN.findall(task_id or "")):
        return True
    try:
        payload = json.loads(payload_json or "null")
    except ValueError:
        return False
    pids, dids = ids_in(payload)
    return bool(dids & kept_out or {p.split(":", 1)[0] for p in pids} & kept_out)


class ProjectRows:
    """The rows that are the project's and no one's item, as a colleague's merge takes them (sync.merge: the AI work on
    documents that holds nobody's decision, people's reviews of it, the links the app found, the bibliography, the
    app's entries about the documents, notes of documents removed, who is in the project, the SDG pack's and add-ons'
    tables). The shared folder writes these besides the shared items (sync/folder.py); they are what survives `strip`
    of a zip for a colleague outside the items, so the two never disagree about what leaves this copy.

    Positive rules, table by table, never "whatever no item covers": a row left behind by an item removed long ago (a
    task of a check deleted, a review of a label gone) is no one's, and stays here. Readings and the documents
    themselves are not among them: the folder carries those per reading.

    `scan()` gives (table, row number, identity, content) of each row: the identity names the row the same in every
    copy (its key, or its whole content where it has none), the content's digest tells a row changed since it was
    written (a reason added to an entry, a task done after it failed), so a copy writes each row again only when it
    changed. `fetch(table, row numbers)` reads the rows in full. `kept_out`: documents whose words must not leave (the
    shared folder's switch for documents marked Only a local AI or No AI): the rows of AI work on them stay here too,
    also tasks whose payload hands their passages to the AI. Attachments in the bibliography leave without their paths
    on this computer (`without_paths`)."""

    def __init__(self, cx: sqlite3.Connection, root: Path | str | None, kept_out: Iterable[str] = ()):
        self.cx, self.root = cx, root
        self.kept_out = set(kept_out)
        have = rows(cx)
        self.shared = {k for k, r in have.items() if r["state"] == "shared"}
        self._tasks_ok: set[str] | None = None
        self._kept: tuple[set[str], set[str], list[str]] | None = None
        self._pks: dict[str, list[str]] = {}

    # ---- what decides ----------------------------------------------------------------------------
    def _kept_out_work(self) -> tuple[set[str], set[str], list[str]]:
        """What names the AI work on the documents kept out without naming a document: the SDG pack's claims on them,
        the labels on them (a review names its claim or label only), and their texts (a link the app found between two
        terms quotes a document without naming it)."""
        if self._kept is None:
            docs = sorted(self.kept_out)
            claims: set[str] = set()
            labels: set[str] = set()
            texts: list[str] = []
            for i in range(0, len(docs), 500):
                chunk = docs[i:i + 500]
                q = _q(len(chunk))
                claims |= {r[0] for r in self.cx.execute(f"SELECT claim_id FROM claims WHERE doc_id IN ({q})", chunk)}
                labels |= {r[0] for r in self.cx.execute(f"SELECT label_id FROM labels WHERE doc_id IN ({q})", chunk)}
                texts += [" ".join(r[0].split()) for r in
                          self.cx.execute(f"SELECT text FROM documents WHERE doc_id IN ({q})", chunk) if r[0]]
            self._kept = (claims, labels, texts)
        return self._kept

    def _about_kept_out(self, table: str, r: dict) -> bool:
        if not self.kept_out or table in _NO_TEXT:
            return False
        if table in ("reviews", "claim_targets", "concept_links"):
            claims, labels, texts = self._kept_out_work()
            if table == "claim_targets":
                return r.get("claim_id") in claims
            if table == "reviews":  # a review holds the AI's wording and the person's correction of it
                return r.get("item_id") in (claims if r.get("item_kind") == "claim" else
                                            labels if r.get("item_kind") == "label" else ())
            quotes = [" ".join(q.split()) for q in (r.get("quote_a"), r.get("quote_b")) if isinstance(q, str) and q.strip()]
            return any(q in t for q in quotes for t in texts)
        d = r.get("doc_id")
        if isinstance(d, str) and d in self.kept_out:
            return True
        p = r.get("passage_id")
        if isinstance(p, str) and p.split(":", 1)[0] in self.kept_out:
            return True
        from .sync.common import _TOKEN

        t = r.get("task_id")
        if table == "tasks":
            return task_names_kept_out(t, r.get("payload_json"), self.kept_out)
        return isinstance(t, str) and any(x in self.kept_out for x in _TOKEN.findall(t))

    def task_ok(self, task_id: str | None) -> bool:
        """Whether the ledger of what was sent to Claude may name this task: one that is here and is no unshared item's
        (as `strip` leaves it)."""
        if self._tasks_ok is None:
            private: set[str] = set()
            for kind, keys in items(self.cx, self.root).items():
                for key in keys:
                    if (kind, key) not in self.shared:
                        private |= {r["task_id"] for r in rows_of(self.cx, kind, key).get("tasks", [])}
            self._tasks_ok = {r[0] for r in self.cx.execute("SELECT task_id FROM tasks")} - private
        return task_id in self._tasks_ok

    def _bundled_labels(self) -> str:
        from .frameworks import BUNDLED

        return f"SELECT label_id FROM labels WHERE framework IN ({','.join(repr(b) for b in BUNDLED)})"

    def _review_note_ok(self, title: str | None) -> bool:
        f = _review_fields(title)
        if not f:
            return True  # a review taken back by its key alone: its key says nothing
        ik, iid = f.get("item_kind"), str(f.get("item_id") or "")
        if ik in ("concept_link", "theme", "theme_member"):
            return False  # an item's (rows_of)
        if ik == "label":
            return bool(self.cx.execute(f"SELECT 1 FROM ({self._bundled_labels()}) WHERE label_id=?", (iid,)).fetchone())
        return True

    def identity(self, table: str, r: dict) -> tuple:
        """What names a row the same in every copy: its key where it has one (a review: its fields, people.review_key),
        else its whole content."""
        from .people import review_key
        from .sync.common import _pk

        if table == "reviews":
            return (review_key(r),)
        if table == "meta":
            return (r.get("key"),)
        if table == "ai_sent":  # without a key: its content
            return tuple((c, r.get(c)) for c in sorted(r) if c != ROWID)
        if table not in self._pks:
            self._pks[table] = _pk(self.cx, table)
        pk = self._pks[table]
        if pk:
            return tuple(r.get(c) for c in pk)
        return tuple((c, r.get(c)) for c in sorted(r) if c != ROWID)

    # ---- the rows --------------------------------------------------------------------------------
    def _light(self, table: str, where: str = "1", cols: str = "*", args: Iterable = ()) -> list[dict]:
        cur = self.cx.execute(f"SELECT rowid AS {ROWID}, {cols} FROM {table} WHERE {where}", tuple(args))
        names = [c[0] for c in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def tables(self) -> list[tuple[str, str, str]]:
        """(table, which rows, the columns to look at first) of the project's rows."""
        from .frameworks import BUNDLED
        from .sync.common import LOCAL_ONLY, OWN_RULES, UNFINISHED

        bundled = ",".join(repr(b) for b in BUNDLED)
        own = [("labels", f"source IN ('model', 'person') AND framework IN ({bundled})", "*"),
               ("mentions", "1", "*"),
               ("tasks", f"status NOT IN ({','.join(repr(u) for u in UNFINISHED)}) AND kind NOT IN "
                         f"({','.join(repr(k) for k in ITEM_TASK_KINDS)})",
                _TASK_COLS + (", payload_json" if self.kept_out else "")),
               ("results", "1", "task_id, attempt"),
               ("ai_sent", "1", "*"),
               ("reviews", f"item_kind NOT IN ('concept_link', 'theme', 'theme_member') AND (item_kind != 'label' OR "
                           f"item_id IN ({self._bundled_labels()}))", "*"),
               ("concept_links", "source NOT IN ('person', 'model')", "*"),
               ("bib_items", "1", "*"), ("bib_links", "1", "*"),
               ("research_log", "kind != 'entry' AND (subject_kind IS NULL OR subject_kind NOT IN "
                                f"({','.join(repr(k) for k in KINDS)}))", "*"),  # about an item: the item's
               ("sync_removed", "kind IN ('document', 'review')", "*"),
               ("people", "1", "*"),
               ("verifications", "subject_kind != 'user_claim'", "*"),
               ("meta", "key='bibliography'", "*"),
               # 0.18 L2 (ownership.py): who the owner is, proposals, decisions, the documents as accepted
               ("ownership", "1", "*"), ("proposals", "1", "*"), ("decisions", "1", "*"), ("canon", "1", "*")]
        present = {r[0] for r in self.cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        other = sorted(t for t in present if t not in LOCAL_ONLY and t not in OWN_RULES and not t.startswith("sqlite_")
                       and t not in ("meta", "verifications"))
        return [x for x in own if x[0] in present] + [(t, "1", "*") for t in other]

    @staticmethod
    def content(table: str, r: dict) -> str:
        """A digest of what a row says (as it leaves this copy), to tell it changed."""
        import hashlib

        keep = {c: v for c, v in r.items() if c != ROWID and not (table == "tasks" and c == "payload_json")
                and not (table == "people" and c == "seen_at")}  # (when a person was last heard of: every round)
        return hashlib.sha1(json.dumps(keep, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:16]

    def scan(self, only: Iterable[str] | None = None) -> Iterator[tuple[str, int, tuple, str]]:
        """(table, row number, identity, content digest) of every row that is the project's; `only`: of these tables
        only (a task's answers go with the task: name `tasks` with `results`)."""
        from .frameworks import BUNDLED

        only = None if only is None else set(only)
        corpus_tasks: set[str] = set()
        for table, where, cols in self.tables():
            if only is not None and table not in only:
                continue
            for r in self._light(table, where, cols):
                if self._about_kept_out(table, r):
                    continue
                if table == "tasks":
                    tid = r["task_id"] or ""
                    if tid.startswith("link:") or (tid.startswith("label:") and tid.split(":")[1] not in BUNDLED):
                        continue  # a link's or a codebook's (items)
                    corpus_tasks.add(tid)
                elif table == "results" and r["task_id"] not in corpus_tasks:
                    continue
                elif table == "ai_sent":
                    r = self._masked(r)
                elif table == "research_log" and not log_entry_travels(r["kind"], r["subject_kind"], r["subject_id"],
                                                                       r["data_json"], self.shared):
                    continue
                elif table == "sync_removed" and r["kind"] == "review" and not self._review_note_ok(r["title"]):
                    continue
                elif table == "runs" and r["kind"] == "label" and r["scope"] not in BUNDLED:
                    continue  # a codebook's (rows_of)
                elif table == "bib_items":
                    r = dict(r, files_json=without_paths(r.get("files_json")))
                yield table, r[ROWID], self.identity(table, r), self.content(table, r)

    def identities(self, mapper=None) -> Iterator[tuple[str, tuple, str]]:
        """(table, identity, content digest) of every row of the project's tables, without the rules of `scan` about
        what leaves: for a colleague's rows that came in already (sync/folder.py: what this copy then need not write
        again). `mapper(table, row) -> row`: the row as it is named in this copy."""
        for table, where, cols in self.tables():
            for r in self._light(table, where, cols):
                r.pop(ROWID, None)
                if table == "bib_items":
                    r["files_json"] = without_paths(r.get("files_json"))
                r = mapper(table, r) if mapper else r
                yield table, self.identity(table, r), self.content(table, r)

    def _masked(self, r: dict) -> dict:
        if r.get("task_id") is not None and not self.task_ok(r["task_id"]):
            r = dict(r, task_id="private")
        return r

    def fetch(self, table: str, rowids: Iterable[int]) -> list[dict]:
        """These rows in full (without their row numbers); the ledger's tasks of work not shared are masked as
        `strip` masks them."""
        ids = sorted(set(rowids))
        out = []
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for r in _select(self.cx, table, f"rowid IN ({_q(len(chunk))})", chunk):
                if table == "ai_sent":
                    r = self._masked(r)
                elif table == "bib_items":
                    r["files_json"] = without_paths(r.get("files_json"))
                r.pop(ROWID, None)
                out.append(r)
        return out
