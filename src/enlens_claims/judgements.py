"""A person's judgement of an excerpt, re-reading an excerpt, and removing a hypothesis or claim. `claimcheck`
re-exports every name here. What stays in `claimcheck` is reached as `_cc.name` at call time.
"""
from __future__ import annotations

import json
from typing import Callable

from . import access, tasks
from .search import passage_index, rank_passages
from .store import Workspace
from .textutil import find_selection
from .verdicts import GRADES, USER_VERDICTS


_KEEP = object()


def set_judgement(ws: Workspace, claim_id: str, passage_id: str, verdict: str | None, note: str | None = None,
                  quote=_KEEP, threshold: float | None = None) -> dict:
    """`_set_judgement`, and what it did to the answer (0.18.1, N4): the hypothesis's status before and after, and
    when it changed, a sentence naming this judgement as the change that moved it, also written into the research log.
    Returns {"hyp_id", "before", "after", "moved"} ("moved" is the sentence, or None). `threshold`: the strictness
    the person looks at the result with (the page's own), so the sentence names the answer they see."""
    from . import assessment, researchlog

    hyp = ws.query("SELECT COALESCE(hyp_id, claim_id) FROM user_claims WHERE claim_id=?", (claim_id,))
    hyp_id = hyp[0][0] if hyp else None
    try:  # a claim checked on its own (check_claim) has no hypothesis to say anything about
        before = hypothesis_result(ws, hyp_id, threshold) if hyp_id else None
    except KeyError:
        before = None
    _set_judgement(ws, claim_id, passage_id, verdict, note, quote)
    if before is None:
        return {"hyp_id": None, "before": None, "after": None, "moved": None}
    after = hypothesis_result(ws, hyp_id, threshold)
    moved = assessment.judgement_moved(ws, before, after, claim_id, passage_id)
    if moved:
        with ws.connect() as cx:
            researchlog.record(cx, "verdict-moved", moved, "check", hyp_id, title=after["text"],
                               data={"from": before["status"], "to": after["status"], "claim_id": claim_id,
                                     "passage_id": passage_id, "verdict": verdict})
    return {"hyp_id": hyp_id, "before": before["status"], "after": after["status"], "moved": moved}


def _set_judgement(ws: Workspace, claim_id: str, passage_id: str, verdict: str | None, note: str | None = None,
                   quote=_KEEP) -> None:
    """A person's own judgement of an excerpt the AI read. It replaces the AI's in the answer (and always counts);
    `verdict` None removes it. The AI's judgement is kept and shown beside it. With `verdict` None and a `note`,
    only the comment is kept: a comment alone is not a judgement (it does not count as agreeing with the AI).

    `quote` is the sentence the person points to (text of this excerpt, found as quotes are); it is shown and exported
    instead of the AI's quote. Left out, an earlier one is kept; None or "" removes it.
    """
    if verdict is not None and verdict not in USER_VERDICTS:
        raise ValueError(f"The judgement must be one of {', '.join(USER_VERDICTS)} (or empty to remove yours).")
    from . import people

    me = people.me()
    with ws.connect() as cx:
        row = cx.execute("SELECT p.text, p.start, p.doc_id, p.end FROM verifications v LEFT JOIN passages p ON "
                         "p.passage_id=v.passage_id WHERE v.subject_kind='user_claim' AND v.subject_id=? AND "
                         "v.passage_id=?", (claim_id, passage_id)).fetchone()
        if row is None:
            raise KeyError(f"{claim_id}/{passage_id}")
        people.adopt(cx, me)  # a judgement from before 0.14 is yours
        # 0.14: your own earlier sentence, not a colleague's (theirs may be the one in force here)
        mine = cx.execute("SELECT quote, start, end FROM judgements WHERE claim_id=? AND passage_id=? AND person_id=?",
                          (claim_id, passage_id, me)).fetchone()
        uq, us, ue = tuple(mine) if mine else (None, None, None)
        if not verdict:
            uq = us = ue = None
        elif quote is not _KEEP:
            q = (quote or "").strip()
            if not q:
                uq = us = ue = None
            else:
                text, base = row[0], row[1]
                kept = None  # 0.15: an excerpt kept from an earlier reading of its document (Read with the new reader)
                for t in _cc._check_tasks(ws, claim_id):
                    for p in json.loads(t["payload_json"])["passages"]:
                        if p["passage_id"] == passage_id and (text is None or p.get("reader") is not None):
                            kept = p
                if kept is not None:  # the sentence is chosen in the excerpt as it was shown, the check's record
                    text, base = kept["text"], None
                hit = find_selection(text or "", q)  # 0.14.3: a selection cutting a word is widened to whole words
                if not hit:
                    raise ValueError("The sentence must be text from this excerpt (select it in the excerpt).")
                uq = (text or "")[hit[0]:hit[1]]
                us, ue = (base + hit[0], base + hit[1]) if base is not None else (None, None)
                if kept is not None and row[0] is not None:  # its place in the document as it reads now, if any
                    from .reread import find_near

                    us, ue = (find_near(cx, row[2], text, hit[0], hit[1], row[1], row[3], kept.get("anchor"))
                              or (None, None))
        comment = (note or "").strip()[:2000] or None
        was = cx.execute("SELECT verdict, note, quote FROM judgements WHERE claim_id=? AND passage_id=? AND person_id=?",
                         (claim_id, passage_id, me)).fetchone()
        if tuple(was or (None, None, None)) != ((verdict or None), comment, (uq if verdict else None)):
            from . import history  # 0.16: your judgements in the check as they were, to compare and restore

            hyp = cx.execute("SELECT COALESCE(hyp_id, claim_id) FROM user_claims WHERE claim_id=?",
                             (claim_id,)).fetchone()
            if hyp:
                history.snapshot(ws, cx, "check", hyp[0], "your judgement of an excerpt")
        people.record(cx, claim_id, passage_id, me, verdict, comment, None, uq, us, ue)
        people.refresh(cx, [claim_id], me)  # yours is in force; removed, a colleague's counts again (if any)


def reread_excerpt(ws: Workspace, claim_id: str, passage_id: str, backend, model: str, note: str | None = None,
                   progress: _cc.Progress | None = None, should_stop: Callable[[], bool] | None = None,
                   readers=None) -> dict:
    """Ask the AI to read one excerpt again, alone, with the check prompt; a person's comment (`note`, or the
    comment saved with their judgement) is added as a hint. The new judgement replaces the AI's for this excerpt;
    the earlier ones are kept (`ai_history` in `result`). A person's own judgement is not changed and still counts.

    Returns {"before": {verdict, confidence}, "after": {verdict, confidence, scope_note}, "ok": bool}.
    """
    say = _cc._adapt(progress)
    _cc._stopper(should_stop)()
    uc = ws.query("SELECT * FROM user_claims WHERE claim_id=?", (claim_id,))
    if not uc:
        raise KeyError(claim_id)
    uc = dict(uc[0])
    shown = None
    for t in _cc._check_tasks(ws, claim_id):
        for p in json.loads(t["payload_json"])["passages"]:
            if p["passage_id"] == passage_id:
                shown = (t, p)
    if shown is None:
        raise KeyError(f"{claim_id}/{passage_id}")
    rnd, p = shown
    v = ws.query("SELECT * FROM verifications WHERE subject_kind='user_claim' AND subject_id=? AND passage_id=?",
                 (claim_id, passage_id))
    v = dict(v[0]) if v else None
    if note is None and v:
        note = v.get("user_note")
    # 0.11: the excerpt is read again by a model its document's setting allows: the main one, or the local model
    level = access.levels(ws, [p["doc_id"]]).get(p["doc_id"], "none")
    reader = _cc._readers(backend, model, readers).for_level(level)
    if reader is None:
        raise ValueError("This excerpt's document is marked No AI: no model may read it. Give your own judgement."
                         if level == "none" else "This excerpt's document is marked Only a local AI, and no local "
                         "model is chosen for such documents (Settings → AI). Give your own judgement, or choose one.")
    backend, model = reader
    used = _cc._used(backend, model)
    payload = _cc._payload(ws, claim_id, uc["text"], uc["target"], uc.get("framework"), [p])
    if (note or "").strip():
        payload["reader_note"] = " ".join(note.split())[:1000]
    payload["previous_at"] = ws.scalar("SELECT received_at FROM results WHERE task_id=? AND valid=1 ORDER BY attempt DESC "
                                       "LIMIT 1", (rnd["task_id"],))
    n = int(ws.scalar("SELECT COUNT(*) FROM tasks WHERE +kind='reread' AND task_id >= ? AND task_id < ?",
                      tasks.id_range(f"reread:{claim_id}:{passage_id}:")) or 0) + 1
    tid = f"reread:{claim_id}:{passage_id}:{n}"
    if n > 1:
        payload["previous_at"] = ws.scalar("SELECT received_at FROM results WHERE task_id=? AND valid=1 ORDER BY attempt "
                                           "DESC LIMIT 1", (f"reread:{claim_id}:{passage_id}:{n - 1}",)) or payload["previous_at"]
    _cc._add_task(ws, tid, "reread", used, payload)
    say("grade", "The AI is reading the excerpt again", {})
    before = {"verdict": v["verdict"] if v and v["verdict"] in GRADES else None,
              "confidence": v["confidence"] if v and v["verdict"] in GRADES else None}
    try:
        ok, _errs = tasks.run_one(ws, tid, backend, model)
    except BaseException:
        with ws.connect() as cx:  # stopped: nothing changes, and it can be asked again
            cx.execute("DELETE FROM results WHERE task_id=?", (tid,))
            cx.execute("DELETE FROM tasks WHERE task_id=?", (tid,))
        raise
    now_v = ws.query("SELECT verdict, confidence, scope_note FROM verifications WHERE subject_kind='user_claim' AND "
                     "subject_id=? AND passage_id=?", (claim_id, passage_id))
    after = ({"verdict": now_v[0]["verdict"] if now_v[0]["verdict"] in GRADES else None,
              "confidence": now_v[0]["confidence"] if now_v[0]["verdict"] in GRADES else None,
              "scope_note": now_v[0]["scope_note"],
              "rationale": json.loads(ws.scalar("SELECT reread_json FROM verifications WHERE subject_kind='user_claim' "
                                                "AND subject_id=? AND passage_id=?", (claim_id, passage_id)) or "{}"
                                      ).get("rationale")} if now_v and ok else None)
    say("grade_done", "Read again; the quote was checked against the document" if ok else
        "The AI's answers could not be used, even after three tries; its earlier judgement stays", {"ok": ok})
    return {"claim_id": claim_id, "passage_id": passage_id, "ok": ok, "before": before, "after": after}


def more_available(ws: Workspace, claim_id: str, semantic: bool = False) -> bool:
    """Whether reading further would find any excerpt not read yet: with keywords, one that shares a word with the
    claim or the words searched so far; with semantic search (`semantic`), any readable excerpt not read yet."""
    uc = ws.query("SELECT * FROM user_claims WHERE claim_id=?", (claim_id,))
    if not uc:
        raise KeyError(claim_id)
    uc = dict(uc[0])
    seen = {p["passage_id"] for r in _cc._check_tasks(ws, claim_id) for p in json.loads(r["payload_json"])["passages"]}
    opts = json.loads(uc["options_json"] or "{}")
    docs = set(opts.get("doc_ids") or [])
    if semantic:
        idx = passage_index(ws)
        from .docrole import not_evidence_docs  # K2, N3: a theory or working document is never evidence, unless
        #                                          named by hand
        with ws.connect() as cx:
            theory = not_evidence_docs(cx) - docs
        return any(pid not in seen and (not docs or d in docs) and d not in theory
                   for pid, d in zip(idx.ids, idx.doc_of))
    return bool(rank_passages(ws, uc["text"], json.loads(uc["terms_json"] or "[]"), k=1,
                              doc_ids=list(docs) or None, exclude=seen))


def delete_claim(ws: Workspace, claim_id: str, why: str | None = None, _log: bool = True) -> None:
    with ws.connect() as cx:
        hyp = cx.execute("SELECT hyp_id FROM user_claims WHERE claim_id=?", (claim_id,)).fetchone()
        cx.execute("DELETE FROM verifications WHERE subject_kind='user_claim' AND subject_id=?", (claim_id,))
        for tid in (f"expand:{claim_id}", f"check:{claim_id}"):
            cx.execute("DELETE FROM results WHERE task_id=?", (tid,))
            cx.execute("DELETE FROM tasks WHERE task_id=?", (tid,))
        for prefix in (f"check:{claim_id}:", f"reread:{claim_id}:", f"second:check:{claim_id}:"):
            lo_hi = tasks.id_range(prefix)  # ranges on the keys (results' key starts with task_id)
            cx.execute("DELETE FROM results WHERE task_id >= ? AND task_id < ?", lo_hi)
            cx.execute("DELETE FROM tasks WHERE task_id >= ? AND task_id < ?", lo_hi)
        cx.execute("DELETE FROM second_opinions WHERE subject_id=?", (claim_id,))
        cx.execute("DELETE FROM user_claims WHERE claim_id=?", (claim_id,))
        hid = hyp[0] if hyp and hyp[0] else claim_id
        if not cx.execute("SELECT 1 FROM user_claims WHERE hyp_id=?", (hid,)).fetchone():
            _note_removed(ws, cx, hid, why, _log)
            cx.execute("DELETE FROM results WHERE task_id=?", (f"decompose:{hid}",))
            cx.execute("DELETE FROM tasks WHERE task_id=?", (f"decompose:{hid}",))
            cx.execute("DELETE FROM hypotheses WHERE hyp_id=?", (hid,))


def delete_hypothesis(ws: Workspace, hyp_id: str, why: str | None = None, unmade: bool = False) -> None:
    """Remove a check. 0.16: the research log says so, with the person's reason (`why`) when they gave one; a check
    the app takes back before it was made (stopped, withdrawn, interrupted: `unmade`) leaves nothing in the log."""
    with ws.connect() as cx:
        if unmade:
            cx.execute("DELETE FROM research_log WHERE subject_kind='check' AND subject_id=? AND kind='check-added'",
                       (hyp_id,))
        else:
            _log_removed(cx, hyp_id, why)
        for (cid,) in cx.execute("SELECT claim_id FROM user_claims WHERE hyp_id=?", (hyp_id,)).fetchall():
            delete_claim(ws, cid, _log=False)  # nested: one transaction
        _note_removed(ws, cx, hyp_id, log=False)
        cx.execute("DELETE FROM results WHERE task_id=?", (f"decompose:{hyp_id}",))
        cx.execute("DELETE FROM tasks WHERE task_id=?", (f"decompose:{hyp_id}",))
        cx.execute("DELETE FROM hypotheses WHERE hyp_id=?", (hyp_id,))


def _note_removed(ws: Workspace, cx, hyp_id: str, why: str | None = None, log: bool = True) -> None:
    """0.14: a removed check does not come back with a colleague's work (sync.py); its own sync-clash mark goes."""
    row = cx.execute("SELECT text FROM hypotheses WHERE hyp_id=?", (hyp_id,)).fetchone()
    if row:
        ws.removed(cx, "check", hyp_id, row[0])
        if log:
            _log_removed(cx, hyp_id, why)
    cx.execute("DELETE FROM sync_copies WHERE kind='check' AND key=?", (hyp_id,))


def _log_removed(cx, hyp_id: str, why: str | None) -> None:
    """0.16: a check removed, in the research log (the claim dropped, and why)."""
    from . import researchlog

    row = cx.execute("SELECT text FROM hypotheses WHERE hyp_id=?", (hyp_id,)).fetchone()
    if row:
        researchlog.record(cx, "check-removed", f"Removed the check of {researchlog.quoted(row[0], 200)}.", "check",
                           hyp_id, row[0], why=why)


def set_note(ws: Workspace, hyp_id: str, note: str) -> None:
    from . import history

    with ws.connect() as cx:
        history.snapshot(ws, cx, "check", hyp_id, "the note on the check")
        if not cx.execute("UPDATE hypotheses SET note=? WHERE hyp_id=?", ((note or "").strip()[:4000], hyp_id)).rowcount:
            raise KeyError(hyp_id)


# at the end, so that this module can be imported before `claimcheck` (they refer to each other; both are read at call time)
from .check_results import hypothesis_result  # noqa: E402
from . import claimcheck as _cc  # noqa: E402
