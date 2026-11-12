"""0.18.0 (roadmap L2), builder C: what the adversarial tests of one owner and several collaborators share, beside
`owner_helpers.py` (builder A's, imported from, never changed here).

- people whose ENLENS folder lies under a name with accents (a Windows home such as `C:\\Users\\Dávid`), composed or
  decomposed (NFC / NFD);
- a small project of plain text documents (fast: no PDF), and a team made from it;
- the exchange by zips only (each person brings in everyone's file), and the shared folder read byte by byte;
- the state of the L2 tables in one copy, in a form two copies can be compared by;
- an older project: one exchanged before 0.18 (no owner), and a zip as ENLENS 0.17 wrote it;
- what a person made, to tell later that nothing of it was lost.
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

from enlens_claims import bundle, ingest, ownership, people, sharing
from enlens_claims.store import Workspace
from enlens_claims.sync import folder
from owner_helpers import TEXTS
from test_0_14_0_shared_projects import Person

L2_TABLES = ("ownership", "proposals", "decisions", "canon", "canon_seen")


class PersonAt(Person):
    """A Person whose ENLENS folder is `home` (a path with accents, spaces, capitals), not `tmp/home-<name>`."""

    def __init__(self, tmp: Path, name: str, monkeypatch, home: Path):
        self.name, self.home, self.mp = name, home, monkeypatch
        self.ws = None
        self.files = tmp / f"sent-{name}"
        self.files.mkdir(parents=True, exist_ok=True)
        self.n = 0
        home.mkdir(parents=True, exist_ok=True)
        with self:
            from enlens_claims import home as home_

            home_.update_settings({"your_name": name})
            self.id = people.me()


def small_project(p: Person, where: Path, keys=("desalination", "jobs", "grid"), reader: int | None = None,
                  ai: str | None = None, names: dict[str, str] | None = None) -> Workspace:
    """A project of a few short text documents, made by `p` (fast: no PDF, no VCA workbook). `names`: a file name per
    key (accents, capitals)."""
    src = where.parent / f"{where.name}-files"
    src.mkdir(parents=True, exist_ok=True)
    files = []
    for k in keys:
        f = src / ((names or {}).get(k) or f"{k}.txt")
        f.write_text(TEXTS[k], encoding="utf-8")
        files.append(f)
    with p:
        ws = Workspace.create(where)
        was = ingest.READER
        if reader is not None:
            ingest.READER = reader
        try:
            ingest.ingest(ws, files, **({"ai_access": ai} if ai else {}))
        finally:
            ingest.READER = was
    p.ws = ws
    return ws


def join_zip(p: Person, source: Person, where: Path, scope: str = "all") -> Path:
    """A copy for `p` made from `source`'s zip (no shared folder). Returns the zip."""
    with source:
        source.n += 1
        f = source.files / f"{source.name}-for-{p.name}-{source.n}.zip"
        bundle.export_project(source.ws, f, scope=scope)
    with p:
        p.ws = bundle.import_project(f, where)
    return f


def send(p: Person, scope: str = "shared") -> Path:
    with p:
        p.n += 1
        out = p.files / f"{p.name}-{p.n}.zip"
        bundle.export_project(p.ws, out, scope=scope)
    return out


def zips(*people_: Person, rounds: int = 1, scope: str = "shared") -> list[dict]:
    """Rounds of zips only: each person, in this order, sends a file to every other, who brings it in at once; then the
    new readings due are made."""
    out = []
    for _ in range(rounds):
        for s in people_:
            f = send(s, scope)
            for r in people_:
                if r is not s:
                    out.append(r.bring_in(f))
                    with r:
                        for d in ownership.moves_due(r.ws):
                            ownership.move_now(r.ws, d)
    return out


def everything(shared: Path) -> list[tuple[str, bytes]]:
    """Every file in the folder, and every file inside each zip, as bytes."""
    out = []
    for f in sorted(shared.rglob("*")):
        if not f.is_file():
            continue
        data = f.read_bytes()
        out.append((str(f.relative_to(shared)), data))
        if zipfile.is_zipfile(f):
            with zipfile.ZipFile(f) as zf:
                out += [(f"{f.relative_to(shared)}!{n}", zf.read(n)) for n in zf.namelist()]
    return out


def bundle_dbs(shared: Path, tmp: Path) -> list[sqlite3.Connection]:
    """Each bundle's `rows.sqlite`, open (the caller closes them)."""
    out = []
    tmp.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate(sorted(shared.rglob("bundles/*.zip"))):
        db = tmp / f"bundle-{i}.sqlite"
        with zipfile.ZipFile(b) as zf:
            db.write_bytes(zf.read("rows.sqlite"))
        out.append(sqlite3.connect(db))
    return out


def file_names(shared: Path) -> set[str]:
    return {f.relative_to(shared).as_posix() for f in shared.rglob("*") if f.is_file()}


# ---- the state of one copy ---------------------------------------------------------------------------------------
def owner_of(p: Person) -> str | None:
    with p:
        return ownership.owner(p.ws._conn())


def canon_of(p: Person) -> dict[str, tuple]:
    """{doc: (state, reader, ai level, blocks)} as this copy reads canon."""
    with p:
        K = ownership.canon(p.ws._conn())
    return {d: (k["state"], k["reader"] or 1, k["ai_access"], json.dumps(k["blocks"], sort_keys=True))
            for d, k in K.items()}


def states_of(p: Person) -> dict[str, str]:
    """{proposal id: its state}, as this copy sees it (without writing anything)."""
    with p:
        return {x["id"]: x["state"] for x in ownership.view(p.ws)["proposals"]}


def waiting(p: Person) -> list[dict]:
    with p:
        return [x for x in ownership.view(p.ws)["proposals"] if x["state"] == "waiting"]


def levels_of(p: Person) -> dict[str, str]:
    with p:
        return dict(folder.ai_settings(p.ws, p.ws._conn()))


def readers_of(p: Person) -> dict[str, int]:
    with p:
        return {r[0]: r[1] for r in p.ws.query("SELECT doc_id, COALESCE(reader, 1) FROM documents")}


def choices_of(p: Person) -> dict[str, dict[str, int]]:
    with p:
        out: dict[str, dict[str, int]] = {}
        for d, fp, inc in p.ws.query("SELECT doc_id, fp, included FROM block_choices"):
            out.setdefault(d, {})[fp] = inc
        return out


def seen_of(p: Person) -> dict[str, dict]:
    with p:
        cx = p.ws._conn()
        cur = cx.execute("SELECT * FROM canon_seen")
        cols = [c[0] for c in cur.description]
        return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}


def log_rows(p: Person, kinds=("proposal", "proposal-accepted", "proposal-declined", "proposal-taken-back",
                               "owner")) -> list[tuple]:
    """(entry id, kind, data) of the research log's L2 entries in this copy."""
    with p:
        q = ",".join("?" * len(kinds))
        return [tuple(r) for r in p.ws.query(f"SELECT entry_id, kind, data_json FROM research_log WHERE kind IN ({q}) "
                                             "ORDER BY at, rowid", kinds)]


# ---- what a person made ------------------------------------------------------------------------------------------
def results_of(p: Person, hyp_ids) -> dict[str, tuple]:
    """{hyp id: (excerpts, sorted judgements of this person)} of the given checks, in this person's copy (absent: not
    there)."""
    out = {}
    with p:
        cx = p.ws._conn()
        for h in hyp_ids:
            if not cx.execute("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h,)).fetchone():
                continue
            n = cx.execute("SELECT COUNT(*) FROM verifications v JOIN user_claims c ON c.claim_id=v.subject_id WHERE "
                           "v.subject_kind='user_claim' AND c.hyp_id=?", (h,)).fetchone()[0]
            js = sorted((r[0], r[1]) for r in cx.execute(
                "SELECT j.verdict, j.note FROM judgements j JOIN user_claims c ON c.claim_id=j.claim_id WHERE "
                "c.hyp_id=? AND j.person_id=?", (h, p.id)))
            out[h] = (n, tuple(js))
    return out


# ---- older projects ----------------------------------------------------------------------------------------------
def as_before_018(p: Person) -> None:
    """Make `p`'s copy one exchanged before 0.18: no L2 rows at all, and a zip brought in once (`sync_log`)."""
    with p:
        with p.ws.connect() as cx:
            for t in L2_TABLES:
                cx.execute(f"DELETE FROM {t}")
            cx.execute("INSERT INTO sync_log(at, person_id, report_json) VALUES (?,?,?)",
                       ("2026-01-05T10:00:00+00:00", people.UNKNOWN, "{}"))


def as_017_zip(src: Path, out: Path, sql: list[tuple] = ()) -> Path:
    """A zip as ENLENS 0.17 wrote it, made from a 0.18 zip: the five L2 tables and `shares` dropped from its database,
    and no `sync_format` in its `bundle.json`. `sql`: (statement, args) run on its database first (what a 0.17 copy
    did that a 0.18 copy would not let happen)."""
    tmp = out.with_suffix(".unpacked")
    tmp.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as zf:
        names = zf.namelist()
        data = {n: zf.read(n) for n in names}
    db = tmp / "enlens.sqlite"
    db.write_bytes(data["enlens.sqlite"])
    cx = sqlite3.connect(db)
    try:
        for stmt, args in sql:
            cx.execute(stmt, args)
        for t in L2_TABLES + ("shares",):
            cx.execute(f"DROP TABLE IF EXISTS {t}")
        cx.commit()
        cx.execute("VACUUM")
    finally:
        cx.close()
    data["enlens.sqlite"] = db.read_bytes()
    meta = json.loads(data["bundle.json"])
    for k in ("sync_format", "sync_needs", "scope"):
        meta.pop(k, None)
    meta["version"] = "0.17.0"
    data["bundle.json"] = json.dumps(meta).encode("utf-8")
    with zipfile.ZipFile(out, "w") as zf:
        for n in names:
            zf.writestr(n, data[n])
    return out


def keep_out_on(p: Person) -> None:
    with p:
        folder.set_keep_out(p.ws, True)


def shared_items(p: Person, kind: str = "check") -> set[str]:
    with p:
        return sharing.shared_keys(p.ws._conn(), kind)
