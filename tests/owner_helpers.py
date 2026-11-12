"""0.18.0 (roadmap L2): what the tests of one owner and several collaborators share: copies of one project, each
with its own person and ENLENS folder, working through one shared folder (and zips), and the things a person does
to the documents of their copy."""
from __future__ import annotations

from pathlib import Path

from enlens_claims import access, bundle, claimcheck, ingest, ownership, reread
from enlens_claims import reader as reader2
from enlens_claims.llm import BaselineBackend
from enlens_claims.store import now
from enlens_claims.sync import folder
from test_0_14_0_shared_projects import Person

TEXTS = {
    "desalination": ("Desalination for hydrogen export in arid regions\n\n"
                     "Seawater desalination adds little to the cost of electrolytic hydrogen in arid export regions. "
                     "The energy needed to desalinate the feed water is below one percent of the energy the "
                     "electrolyser itself uses.\n\n"
                     "Brine disposal near the coast can harm marine life when it is not diluted. Operators in the "
                     "study diluted brine before discharge and monitored salinity near the outfall.\n\n"
                     "Local communities asked for a share of the desalinated water. Two of the five projects agreed "
                     "to supply drinking water to nearby towns as part of their permits.\n"),
    "jobs": ("Local jobs from electrolyser plants\n\n"
             "Electrolyser plants create local jobs mainly during construction. A typical plant of one hundred "
             "megawatts employs about four hundred workers while it is built.\n\n"
             "Permanent jobs are fewer. Operation and maintenance of the same plant employs about thirty people, "
             "most of them technicians trained in the region.\n\n"
             "Training programmes with local colleges raised the share of local hires from one third to two thirds "
             "within three years in the cases studied.\n"),
    "grid": ("Grid effects of large electrolysers\n\n"
             "Large electrolysers can stabilise a grid with much wind power when they follow the supply. Flexible "
             "operation lowered curtailment of wind farms by a fifth in the model.\n\n"
             "Running electrolysers at a constant load raised peak demand and needed new transmission lines. The "
             "cost of those lines was not counted in most hydrogen cost studies.\n\n"
             "Operators were paid for flexibility in only one of the four markets that were compared.\n"),
    "interview": ("Interview with a plant manager\n\n"
                  "The manager said the plant had trouble finding welders in the first year. Recruitment from the "
                  "capital solved it, at a higher wage than planned.\n\n"
                  "She asked that her remarks on the water permit be kept within the research team. The permit "
                  "talks with the province were still going on at the time of the interview.\n\n"
                  "The plant expects to double its output when the second electrolyser arrives next spring.\n"),
}


def sync(*people_: Person, rounds: int = 2) -> list[dict]:
    """Rounds of the shared folder for these copies, in this order; then the new readings that are due."""
    out = []
    for _ in range(rounds):
        for p in people_:
            with p:
                r = folder.sync_now(p.ws)
                bad = [x for x in r["problems"] if x["kind"] not in ("documents",)]
                assert not bad, (p.name, bad)
                for d in r.get("moves_due") or []:
                    ownership.move_now(p.ws, d)
                out.append(r)
    return out


def add_doc(p: Person, tmp: Path, key: str, reader: int | None = None, ai: str | None = None, text: str | None = None) -> str:
    """Add one text document to a person's copy; returns its id. `reader`: as an earlier reader read it."""
    d = tmp / f"added-{p.name}"
    d.mkdir(exist_ok=True)
    f = d / f"{key}.txt"
    f.write_text(text or TEXTS[key], encoding="utf-8")
    with p:
        before = {r[0] for r in p.ws.query("SELECT doc_id FROM documents")}
        was = ingest.READER
        if reader is not None:
            ingest.READER = reader
        try:
            ingest.ingest(p.ws, [f], **({"ai_access": ai} if ai else {}))
        finally:
            ingest.READER = was
        new = [r[0] for r in p.ws.query("SELECT doc_id FROM documents") if r[0] not in before]
    assert len(new) == 1, new
    return new[0]


def has(p: Person, doc: str) -> bool:
    with p:
        return bool(p.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,)))


def level(p: Person, doc: str) -> str:
    with p:
        return folder.ai_settings(p.ws, p.ws._conn()).get(doc)


def set_level(p: Person, doc: str, lv: str) -> dict:
    with p:
        return access.set_documents(p.ws, [doc], setting=lv)


def reader_of(p: Person, doc: str) -> int:
    with p:
        return p.ws.scalar("SELECT COALESCE(reader, 1) FROM documents WHERE doc_id=?", (doc,))


def move(p: Person, doc: str) -> dict:
    with p:
        return reread.move(p.ws, doc, p.id)


def leave_out(p: Person, doc: str, n: int = 0, included: bool = False) -> str:
    """Leave out (or restore) the n-th block that is read (left out) now; returns the block's fingerprint."""
    with p:
        with p.ws.connect() as cx:
            (text,) = cx.execute("SELECT text FROM documents WHERE doc_id=?", (doc,)).fetchone()
            rows = cx.execute("SELECT start, end, kind FROM blocks WHERE doc_id=? AND included=? ORDER BY n",
                              (doc, 0 if included else 1)).fetchall()
            a, z, kind = rows[n]
            fp = reader2.block_fp(text[a:z])
            cx.execute("INSERT OR REPLACE INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES "
                       "(?,?,?,?,?,?)", (doc, fp, 1 if included else 0, kind, p.id, now()))
            reader2.apply_choices(cx, doc)
            p.ws.bump_corpus(cx)
    return fp


def choices(p: Person, doc: str) -> dict:
    with p:
        return {r[0]: r[1] for r in p.ws.query("SELECT fp, included FROM block_choices WHERE doc_id=?", (doc,))}


def included(p: Person, doc: str) -> list[int]:
    with p:
        return [r[0] for r in p.ws.query("SELECT included FROM blocks WHERE doc_id=? ORDER BY n", (doc,))]


def view(p: Person) -> dict:
    with p:
        ownership.settle(p.ws, apply=False)
        return ownership.view(p.ws)


def proposals(p: Person, state: str | None = None, kind: str | None = None) -> list[dict]:
    return [x for x in view(p)["proposals"] if (state is None or x["state"] == state)
            and (kind is None or x["kind"] == kind)]


def accept(p: Person, pid: str, reason: str | None = None) -> dict:
    with p:
        out = ownership.accept(p.ws, pid, reason)
        for d in ownership.moves_due(p.ws):
            ownership.move_now(p.ws, d)
        return out


def decline(p: Person, pid: str, reason: str | None = None) -> dict:
    with p:
        return ownership.decline(p.ws, pid, reason)


def check(p: Person, text: str, k: int = 3) -> str:
    with p:
        return claimcheck.check_hypothesis(p.ws, text, BaselineBackend(), "baseline", k=k)


def log_kinds(p: Person) -> list[str]:
    with p:
        return [r[0] for r in p.ws.query("SELECT kind FROM research_log ORDER BY at, rowid")]


def join(p: Person, source: Person, tmp: Path, shared: Path, scope: str = "all") -> None:
    """A new copy for `p` from `source`'s zip, working through the shared folder."""
    with source:
        source.n += 1
        f = source.files / f"{source.name}-for-{p.name}-{source.n}.zip"
        bundle.export_project(source.ws, f, scope=scope)
    with p:
        p.ws = bundle.import_project(f, tmp / f"{p.name}-project")
        folder.set_folder(p.ws, str(shared))


def docs_of(p: Person) -> set[str]:
    with p:
        return {r[0] for r in p.ws.query("SELECT doc_id FROM documents")}


# ---- roles (DESIGN-roles §6.6): a file never loosens an AI setting, and a take-over is never followed unasked -------
def allow(p: Person, doc: str | None = None) -> dict:
    """*Allow here*: this person takes the looser AI setting the project now has (one document, or every offer)."""
    with p:
        ownership.settle(p.ws, apply=False)
        return ownership.answer_loosening(p.ws, [doc] if doc else None, True)


def follow(p: Person, owner: str | None = None) -> dict:
    """This person answers the questions about who owns the project by following (the record naming `owner`, else
    each one asked, in order of place)."""
    with p:
        ownership.settle(p.ws, apply=False)
        for _ in range(10):
            qs = [q for q in ownership.owner_questions(p.ws._conn()) if owner is None or q["owner"] == owner]
            if not qs:
                break
            q = min(qs, key=lambda q: (q["seq"], q["by"]))
            ownership.follow_owner(p.ws, q["seq"], q["by"])
        return ownership.view(p.ws)


def set_role(p: Person, person: Person, role: str) -> dict:
    with p:
        return ownership.set_role(p.ws, person.id, role)
