"""Roles (DESIGN-roles §6): what the tests of the Owner, Co-owners and Members share, beside `owner_helpers.py` and
`owner_more_helpers.py`: a crew of four copies in one shared folder (Anna the Owner, Ben and Carol Co-owners, Dana a
Member), the state of one copy in a form copies can be compared by, and a bare database to try the merge rules on."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from enlens_claims import ownership
from enlens_claims.store import Workspace
from enlens_claims.sync import folder
from owner_helpers import add_doc, set_role, sync
from owner_more_helpers import join_zip, small_project
from test_0_14_0_shared_projects import Person


def make_crew(tmp_path: Path, monkeypatch, shared: Path, co=("Ben", "Carol")) -> tuple[Person, ...]:
    """Anna's small project (three text documents, an interview read by reader 3, an old report by reader 1); Ben, Carol and Dana have copies
    from her zips; all four work through the shared folder. The names in `co` are made Co-owners."""
    anna = Person(tmp_path, "Anna", monkeypatch)
    small_project(anna, tmp_path / "anna-project")
    add_doc(anna, tmp_path, "interview", reader=3)  # (an older reader that has blocks)
    add_doc(anna, tmp_path, "old", reader=1, text=OLD)  # (read by the first reader: reading it again changes its text)
    others = []
    for name in ("Ben", "Carol", "Dana"):
        p = Person(tmp_path, name, monkeypatch)
        join_zip(p, anna, tmp_path / f"{name.lower()}-project")
        others.append(p)
    crew = (anna, *others)
    for p in crew:
        with p:
            folder.set_folder(p.ws, str(shared))
    sync(*crew)
    for p in others:
        if p.name in co:
            set_role(anna, p, "co")
    sync(*crew)
    return crew


def doc_of(p: Person, title_part: str) -> str:
    with p:
        rows = [r[0] for r in p.ws.query("SELECT doc_id FROM documents WHERE title LIKE ?", (f"%{title_part}%",))]
    assert len(rows) == 1, (title_part, rows)
    return rows[0]


def project(p: Person) -> dict:
    """What a copy computes: the owner, the roles, and each document part by part with its event."""
    with p:
        cx = p.ws._conn()
        ch = ownership.chain(cx)
        K = ownership.canon(cx, ch)
        R = ownership.roles(cx, ch)
    return {"chain": [(r["seq"], r["owner"], r["by"], r["kind"]) for r in ch],
            "roles": {x: (r["role"], r["grant"], r["same_as"]) for x, r in R.items()},
            "canon": {d: ((k["state"], k["state_n"], k["state_by"]), (k["ai_access"], k["ai_n"], k["ai_by"]))
                      + ((k["reader"], k["text_fp"], k["read_n"], k["read_by"]),
                         (json.dumps(k["blocks"], sort_keys=True), k["blocks_n"], k["blocks_by"]))
                      for d, k in K.items()}}


def row_keys(p: Person) -> dict[str, set]:
    """The rows of the tables that travel, by writer and number: a round that writes none leaves them as they are."""
    with p:
        cx = p.ws._conn()
        return {"canon": {tuple(r) for r in cx.execute("SELECT doc, by, n FROM canon")},
                "decisions": {tuple(r) for r in cx.execute("SELECT proposal, by, n FROM decisions")},
                "roles": {tuple(r) for r in cx.execute("SELECT person, by, n FROM roles")},
                "ownership": {tuple(r) for r in cx.execute("SELECT seq, by FROM ownership")}}


def clash_entries(p: Person) -> list[str]:
    """The research log's entries of this copy's person about changes made at the same time."""
    with p:
        out = []
        for (data,) in p.ws.query("SELECT data_json FROM research_log WHERE person_id=? AND data_json LIKE "
                                  "'%clash%'", (p.id,)):
            d = json.loads(data or "{}")
            out.append(d.get("clash") if isinstance(d.get("clash"), str) else d.get("proposal"))
        return out


# ---- a bare database to try the merge rules on -------------------------------------------------------------------
A, B, C, D = (f"p{c * 12}" for c in "abcd")
OLD = ("An older field report\n\nThe pipeline to the harbour was delayed by two years because of a permit dispute. "
       "Local fishermen asked for a share of the water.\n\nThe report was read once by an early reader and kept "
       "as it was since then, so a newer reader reads it otherwise.\n")  # person ids: A the Owner, B and C Co-owners, D a Member


def bare(tmp_path: Path, co=(B, C)) -> Workspace:
    """A project database with A as its owner (pinned) and `co` Co-owners, no documents."""
    ws = Workspace.create(tmp_path / ("bare-" + hashlib.sha1(str(tmp_path).encode()).hexdigest()[:6]))
    with ws.connect() as cx:
        cx.execute("INSERT INTO ownership(seq, owner, by, at, kind, after) VALUES (1, ?, ?, '2026', 'made', NULL)", (A, A))
        cx.execute("INSERT INTO owner_pins(seq, by, owner, state, at) VALUES (1, ?, ?, 'followed', '2026')", (A, A))
        for i, x in enumerate(co):
            cx.execute("INSERT INTO roles(person, by, owner_seq, n, role, grant, same_as, at) VALUES (?,?,1,?,'co',?,"
                       "NULL,'2026')", (x, A, i + 1, "g" + x))
    return ws


def put_row(ws: Workspace, doc: str, by: str, n: int, *, grant: str | None = "auto", state=None, read=None, ai=None,
            blocks=None, knew: dict | None = None, via: dict | None = None, ai_hist=None) -> None:
    """A row of `canon`. Each part is (value, (n, by)); missing parts are ("in" / reader 1 / "cloud" / {}) at event
    (1, A). `knew`: {part: [events]} its writer had followed besides its own."""
    grant = ("g" + by if by != A else None) if grant == "auto" else grant
    st, st_e = state or ("in", (1, A))
    (fp, rd), rd_e = read or (("fp1", 1), (1, A))
    lv, ai_e = ai or ("cloud", (1, A))
    bl, bl_e = blocks or ({}, (1, A))
    hist = {p: [list(e) for e in sorted(set(map(tuple, (knew or {}).get(p, []))) | {tuple(ev)})]
            for p, ev in (("state", st_e), ("read", rd_e), ("blocks", bl_e))}
    if via:
        hist["via"] = via
    ah = ai_hist if ai_hist is not None else [[e[0], "cloud", e[1]] for e in (knew or {}).get("ai", [])] + \
        [[ai_e[0], lv, ai_e[1]]]
    with ws.connect() as cx:
        cx.execute("INSERT OR REPLACE INTO canon(doc, by, owner_seq, n, grant, state, state_n, state_by, sha1, title, "
                   "text_fp, reader, read_n, read_by, ai_access, ai_n, ai_by, ai_hist_json, blocks_json, blocks_n, "
                   "blocks_by, hist_json, at) VALUES (?,?,1,?,?,?,?,?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,'2026')",
                   (doc, by, n, grant, st, st_e[0], st_e[1], doc, fp, rd, rd_e[0], rd_e[1], lv, ai_e[0], ai_e[1],
                    json.dumps(ah), json.dumps(bl, sort_keys=True), bl_e[0], bl_e[1], json.dumps(hist)))


def answer(ws: Workspace, pid: str, by: str, n: int, verdict: str, knew=(), grant: str | None = "auto") -> None:
    grant = ("g" + by if by != A else None) if grant == "auto" else grant
    with ws.connect() as cx:
        cx.execute("INSERT OR REPLACE INTO decisions(proposal, by, owner_seq, verdict, reason, at, auto, n, grant, "
                   "knew_json) VALUES (?,?,1,?,NULL,'2026',0,?,?,?)",
                   (pid, by, verdict, n, grant, json.dumps([list(k) for k in knew])))


def K(ws: Workspace) -> dict:
    return ownership.canon(ws._conn())
