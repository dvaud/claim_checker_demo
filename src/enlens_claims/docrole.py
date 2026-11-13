"""A document's role (0.18.1, roadmap K2 part 1): evidence, or theory.

A **theory document** is the framework the research is read through (Nicolini's *Practice theory*, Meadows'
*Thinking in Systems*), not evidence about the field. The researcher marks it, never ENLENS: a study that *uses* a
theory is still evidence. A theory document is still read, searched, opened and noted as any other, but it is left
out of what counts as evidence: themes, labelling with codebooks, the excerpts a check reads, key terms and the
glossary's counts (and so the evidence map, which is drawn from the checks' excerpts).

In code the mark is a *role*, never "framework": a framework is a codebook. `documents.role` is NULL (evidence) or
`"theory"`; `"working"` is kept free for N3 (a person's own working documents, also never a source).

**How the mark travels.** It is kept as one of the document's block choices, under the reserved key `role:theory`
(beside the fingerprints of *Leave out* / *Restore* and the `start:` / `end:` marks of where the text starts and
ends). So it is exchanged, merged, proposed, accepted and declined exactly as *Leave out* is (ownership.py, a
proposal of medium severity; the owner's and a Co-owner's mark is the project's at once), with no new sync format:
an older ENLENS keeps the choice and finds no block with that key. `documents.role` is this copy's reading of it, set
whenever the choices are applied (`reader.apply_choices` calls `sync_role`), so every filter is one SQL condition.

Marking or unmarking changes no result by itself. `impact` lists what was made with the document in (theme runs,
codebook labels, checks), so the researcher can make them again without it.

**Non-scientific** (0.18.6) is a mark beside the role, not a role: a document of any role can carry it. A
non-scientific document reports no method or data of its own (a news article, a press release, a company brochure, a
blog). It stays in everything a theory document leaves (themes, labels, check excerpts, key terms), and its excerpts
are read and judged as any other, but no judgement of them counts in an answer, on either side
(`verdicts.set_aside`): on their own they make a hypothesis neither supported nor contested nor contradicted. Unlike
the role, the mark changes answers at once (they are worked out each time they are read): `set_nonscientific`
returns the answers it changed, and the research log keeps them. It travels as the block choice `mark:nonscientific`
(kept apart from `role:`, which `set_role` clears), read into `documents.nonscientific` (1, or NULL) by `sync_role`.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .store import Workspace, now

THEORY = "theory"
ROLES = (THEORY,)          # (N3 will add "working")
KEY = "role:"              # the prefix of a role's block choice
ROLE_TEXT = {THEORY: "Theory", None: "Evidence"}
NONSCIENTIFIC = "nonscientific"
MARK = "mark:"             # 0.18.6: the prefix of a mark's block choice (beside the role, never cleared by set_role)
NONSCI_KEY = MARK + NONSCIENTIFIC


def key(role: str) -> str:
    return KEY + role


def role_from_choices(choices: dict) -> str | None:
    """The role a document's block choices give it ({key: included or [included, kind]}): the first role marked."""
    for r in ROLES:
        v = choices.get(key(r))
        if v is not None and (v[0] if isinstance(v, (list, tuple)) else v):
            return r
    return None


def nonscientific_from_choices(choices: dict) -> bool:
    """Whether a document's block choices mark it Non-scientific (0.18.6)."""
    v = choices.get(NONSCI_KEY)
    return v is not None and bool(v[0] if isinstance(v, (list, tuple)) else v)


def sync_role(cx: sqlite3.Connection, doc_id: str) -> str | None:
    """Set `documents.role` (and, 0.18.6, `documents.nonscientific`) from the document's block choices (called
    wherever the choices are applied)."""
    try:
        rows = {fp: inc for fp, inc in cx.execute("SELECT fp, included FROM block_choices WHERE doc_id=? AND "
                                                   "(fp LIKE ? OR fp LIKE ?)", (doc_id, KEY + "%", MARK + "%"))}
        role = role_from_choices(rows)
        cx.execute("UPDATE documents SET role=? WHERE doc_id=? AND role IS NOT ?", (role, doc_id, role))
    except sqlite3.OperationalError:  # a bare database without the tables or the column (a test, a scratch copy)
        return None
    try:
        ns = 1 if nonscientific_from_choices(rows) else None
        cx.execute("UPDATE documents SET nonscientific=? WHERE doc_id=? AND nonscientific IS NOT ?", (ns, doc_id, ns))
    except sqlite3.OperationalError:  # a database opened before the column (migrations not run)
        pass
    return role


def role_of(ws: Workspace, doc_id: str) -> str | None:
    return ws.scalar("SELECT role FROM documents WHERE doc_id=?", (doc_id,))


def theory_docs(cx: sqlite3.Connection) -> set[str]:
    """The ids of the documents marked as theory."""
    try:
        return {r[0] for r in cx.execute("SELECT doc_id FROM documents WHERE role=?", (THEORY,))}
    except sqlite3.OperationalError:   # a database opened before the column (migrations not run): none
        return set()


def nonscientific_docs(cx) -> set[str]:
    """The ids of the documents marked Non-scientific (0.18.6). `cx`: a connection or a Workspace."""
    try:
        rows = (cx.query if isinstance(cx, Workspace) else cx.execute)(
            "SELECT doc_id FROM documents WHERE nonscientific=1")
        return {r[0] for r in rows}
    except sqlite3.OperationalError:   # a database opened before the column (migrations not run): none
        return set()


def is_nonscientific(ws: Workspace, doc_id: str) -> bool:
    return bool(ws.scalar("SELECT nonscientific FROM documents WHERE doc_id=?", (doc_id,)))


def evidence_sql(col: str = "doc_id") -> str:
    """The one SQL condition that keeps a row of an evidence document, `col` naming its document id: everything that
    must leave theory out filters through it (or `theory_docs`)."""
    return f"{col} NOT IN (SELECT doc_id FROM documents WHERE role='{THEORY}')"


def set_role(ws: Workspace, doc_id: str, role: str | None, why: str | None = None) -> dict:
    """Mark a document as theory (`role` "theory") or as evidence again (None). The research log keeps it; under an
    owner the next look at the copy makes it the project's (an Owner or a Co-owner) or a proposal (a Member), as
    *Leave out* is. Returns {"doc_id", "role", "changed", "impact"}."""
    from . import people, researchlog
    from . import reader as reader2

    if role is not None and role not in ROLES:
        raise ValueError(f"A document's role is one of {', '.join(ROLES)}, or none (evidence).")
    with ws.connect() as cx:
        row = cx.execute("SELECT title, role FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        if row is None:
            raise KeyError(doc_id)
        title, was = row[0], row[1]
        if was == role:
            return {"doc_id": doc_id, "role": role, "changed": False, "impact": impact(ws, doc_id)}
        cx.execute("DELETE FROM block_choices WHERE doc_id=? AND fp LIKE ?", (doc_id, KEY + "%"))
        if role is not None:
            cx.execute("INSERT INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES (?,?,1,'role',?,?)",
                       (doc_id, key(role), people.me(), now()))
        reader2.apply_choices(cx, doc_id)
        sync_role(cx, doc_id)
        ws.bump_corpus(cx)
        text = (f"Marked as theory: the framework the research is read through. It is still read, searched and "
                f"noted, and left out of themes, codebook labels, check excerpts and key terms from now on."
                if role else "Marked as evidence again: it counts in themes, codebook labels, check excerpts and "
                             "key terms from now on.")
        researchlog.record(cx, "document-role", text, "document", doc_id, title, data={"role": role, "was": was},
                           why=why)
    return {"doc_id": doc_id, "role": role, "changed": True, "impact": impact(ws, doc_id)}


def impact(ws: Workspace, doc_id: str) -> dict[str, Any]:
    """What was made with the document in, that marking or unmarking it does not change by itself: {"themes": [{"run_id",
    "created_at", "passages" (of this document)}], "labels": [{"framework", "name", "passages"}], "checks":
    [{"hyp_id", "text", "excerpts"}]}, newest first."""
    from . import frameworks

    themes = [{"run_id": r[0], "created_at": r[1], "passages": r[2]} for r in ws.query(
        "SELECT r.run_id, r.created_at, COUNT(*) FROM theme_members m JOIN theme_runs r ON r.run_id=m.run_id "
        "JOIN passages p ON p.passage_id=m.passage_id WHERE p.doc_id=? GROUP BY r.run_id ORDER BY r.created_at DESC",
        (doc_id,))]
    labels = []
    for fw, n in ws.query("SELECT framework, COUNT(DISTINCT passage_id) FROM labels WHERE doc_id=? GROUP BY framework "
                          "ORDER BY framework", (doc_id,)):
        try:
            name = frameworks.get(fw, ws).title
        except Exception:  # noqa: BLE001 - a codebook removed since: its id
            name = fw
        labels.append({"framework": fw, "name": name, "passages": n})
    checks = [{"hyp_id": r[0], "text": r[1], "excerpts": r[2]} for r in ws.query(
        "SELECT h.hyp_id, h.text, COUNT(*) FROM verifications v JOIN user_claims u ON u.claim_id=v.subject_id "
        "JOIN hypotheses h ON h.hyp_id=u.hyp_id WHERE v.subject_kind='user_claim' AND v.doc_id=? "
        "GROUP BY h.hyp_id ORDER BY h.created_at DESC", (doc_id,))]
    return {"themes": themes, "labels": labels, "checks": checks}


# ---- 0.18.6: Non-scientific ----------------------------------------------------------------------------------------
def _checks_reading(ws: Workspace, doc_id: str) -> list[str]:
    """The checks with an excerpt of the document, newest first."""
    return [r[0] for r in ws.query(
        "SELECT h.hyp_id FROM verifications v JOIN user_claims u ON u.claim_id=v.subject_id JOIN hypotheses h "
        "ON h.hyp_id=u.hyp_id WHERE v.subject_kind='user_claim' AND v.doc_id=? GROUP BY h.hyp_id "
        "ORDER BY h.created_at DESC", (doc_id,))]


def _answers(ws: Workspace, hyp_ids: list[str]) -> dict[str, dict]:
    """{hyp_id: its row of the checks list (status, status_text, status_all_sources, text)}: every check's answer in a
    few queries (`claimcheck.history`), not one full result each."""
    if not hyp_ids:
        return {}
    from .claimcheck import history

    want = set(hyp_ids)
    return {h["hyp_id"]: h for h in history(ws) if h["hyp_id"] in want}


def _text(h: dict) -> str:
    from .verdicts import STATUS_TEXT

    return h.get("status_text") or STATUS_TEXT.get(h["status"], h["status"])


def set_nonscientific(ws: Workspace, doc_id: str, on: bool, why: str | None = None) -> dict:
    """Mark a document as Non-scientific (`on`), or count it as any other again. Answers change at once: returns
    {"doc_id", "nonscientific", "changed", "checks" (how many read it), "answers": [{"hyp_id", "text", "was",
    "was_text", "now", "now_text"}] (the answers the mark changed)}. Under an owner it travels as *Leave out* does (a
    Member's mark is a proposal)."""
    from . import people, researchlog
    from . import reader as reader2

    on = bool(on)
    row = ws.query("SELECT title FROM documents WHERE doc_id=?", (doc_id,))
    if not row:
        raise KeyError(doc_id)
    title = row[0][0]
    checks = _checks_reading(ws, doc_id)
    if is_nonscientific(ws, doc_id) == on:
        return {"doc_id": doc_id, "nonscientific": on, "changed": False, "checks": len(checks), "answers": []}
    before = _answers(ws, checks)
    with ws.connect() as cx:
        cx.execute("DELETE FROM block_choices WHERE doc_id=? AND fp=?", (doc_id, NONSCI_KEY))
        if on:
            cx.execute("INSERT INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES (?,?,1,'mark',?,?)",
                       (doc_id, NONSCI_KEY, people.me(), now()))
        reader2.apply_choices(cx, doc_id)
        sync_role(cx, doc_id)
        ws.bump_corpus(cx)
        # the log entry is part of the change; the answers it changed are known only once it is made (below)
        entry = researchlog.record(
            cx, "document-mark",
            "Marked as non-scientific: it reports no method or data of its own. Its excerpts are still read and "
            "judged, but no judgement of them counts in an answer from now on." if on else
            "Counted as scientific again: its judgements count in answers from now on.",
            "document", doc_id, title, data={"nonscientific": on}, why=why)
    after = _answers(ws, checks)
    answers = [{"hyp_id": hid, "text": after[hid]["text"], "was": before[hid]["status"], "was_text": _text(before[hid]),
                "now": after[hid]["status"], "now_text": _text(after[hid])}
               for hid in checks if hid in before and hid in after
               and (before[hid]["status"], _text(before[hid])) != (after[hid]["status"], _text(after[hid]))]
    if answers:
        import json

        more = " Answers changed: " + "; ".join(f"“{a['text'][:80]}” from {a['was_text']} to {a['now_text']}"
                                                for a in answers) + "."
        with ws.connect() as cx:
            cx.execute("UPDATE research_log SET text=text || ?, data_json=? WHERE entry_id=?",
                       (more, json.dumps({"nonscientific": on, "answers": answers}), entry))
    return {"doc_id": doc_id, "nonscientific": on, "changed": True, "checks": len(checks), "answers": answers}


def counted_without(ws: Workspace, doc_id: str) -> list[dict]:
    """The checks with an excerpt of the document, each with its answer now and the answer counting every
    non-scientific document (`status_all_sources`): [{"hyp_id", "text", "status", "status_text", "all", "all_text"}],
    newest first."""
    from .verdicts import STATUS_TEXT

    checks = _checks_reading(ws, doc_id)
    got = _answers(ws, checks)
    out = []
    for hid in checks:
        h = got.get(hid)
        if h is None:
            continue
        st_all = h.get("status_all_sources") or h["status"]
        out.append({"hyp_id": hid, "text": h["text"], "status": h["status"], "status_text": _text(h),
                    "all": st_all, "all_text": STATUS_TEXT.get(st_all, st_all)})
    return out
