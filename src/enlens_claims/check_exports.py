"""What a check's results become outside the page: the evidence map, calibration, the rows of a spreadsheet and its
workbook. `claimcheck` re-exports every name here. What stays in `claimcheck` is reached as `_cc.name` at call time.
"""
from __future__ import annotations

import json
from typing import Callable

from .store import Workspace
from .verdicts import GRADES, STATUS_TEXT, _status_of_rounds, aggregate, effective


def evidence_map(ws: Workspace, threshold: float | None = None, batch_id: str | None = None,
                 hyp_ids: list[str] | None = None, cache=None) -> dict:
    """Which documents say what about which hypotheses, as a grid (computed in a few queries).

    `cells[hyp_id][doc_id]` = {"side": "supports" | "partly" | "refutes" | "both", "excerpts": n}, by the rule of
    `who_says_what` (judgements that count at this strictness; a person's always count). A hypothesis that rests on
    one document has `single_document`; a document `decides` an answer when leaving out its excerpts would change
    that answer, and is `key` when it decides at least two answers and a fifth of them.
    """
    thr = _threshold(ws, threshold)
    checks = _cc._light_checks(ws, titles=True)  # read once, for the history below too
    if cache is not None and batch_id is None and cache.thr == thr:
        hs = cache.history()
    else:
        hs = _cc.history(ws, thr, batch_id=batch_id, _checks=checks)
    if hyp_ids is not None:
        keep = set(hyp_ids)
        hs = [h for h in hs if h["hyp_id"] in keep]
    want = {h["hyp_id"] for h in hs}
    claims: dict[str, list[tuple[str, str | None]]] = {}
    for r in ws.query("SELECT claim_id, hyp_id, stage FROM user_claims ORDER BY part, rowid"):
        if (r["hyp_id"] or r["claim_id"]) in want:
            claims.setdefault(r["hyp_id"] or r["claim_id"], []).append((r["claim_id"], r["stage"]))
    tasks_of = checks
    titles: dict[str, str] = {}
    for r in sorted((r for rows in checks.values() for r in rows), key=lambda r: r["n"]):  # the order made
        for _pid, did, title in r["excerpts"]:
            titles.setdefault(did, title or "")
    # 0.14.3: rounds as the result page and the Results list see them (grouped, a part no model answers neutral,
    # waiting when a part still waits): the map worked them out on its own and disagreed with both
    rounds: dict[str, tuple[list[str], bool]] = {}
    counting: dict[str, Callable] = {}
    for cid, rows in tasks_of.items():
        groups = _cc._group_rounds(rows)
        sts = [_cc._round_status(g) for g in groups]
        rounds[cid] = (sts, bool(groups) and _cc._round_waiting(groups[-1]))
        counting[cid] = _cc._counting(groups, sts)[0]  # not the AI's judgements of a round that failed
    in_project = {r["doc_id"]: r["title"] or "" for r in ws.query("SELECT doc_id, title FROM documents")}
    titles.update(in_project)
    ver: dict[str, list[dict]] = {}
    for v in ws.query("SELECT subject_id, passage_id, verdict, confidence, doc_id, user_verdict, model FROM "
                      "verifications WHERE subject_kind='user_claim'"):
        if counting.get(v["subject_id"], lambda _v: True)(v):
            ver.setdefault(v["subject_id"], []).append(effective(v))

    def status_of(hid: str, leave_out: str | None = None) -> str:
        sts = []
        for cid, stage in claims.get(hid, []):
            vs = [v for v in ver.get(cid, []) if v["doc_id"] != leave_out]
            rs, wt = rounds.get(cid, ([], False))
            sts.append(_status_of_rounds(rs, vs, thr, stage, wt))
        return sts[0] if len(sts) == 1 else aggregate(sts)

    cells: dict[str, dict[str, dict]] = {}
    answers: dict[str, int] = {}
    decides: dict[str, int] = {}
    hyps = []
    for h in hs:
        hid = h["hyp_id"]
        per_doc: dict[str, dict[str, int]] = {}
        # an answer not given yet (waiting, failed, not judged) is not decided by any document
        decided = h["status"] not in ("waiting", "failed", "not_checked", "no_passages")
        for cid, _stage in claims.get(hid, []):
            for v in ver.get(cid, []):
                if v["verdict"] in GRADES and v["confidence"] is not None and v["confidence"] >= thr:
                    c = per_doc.setdefault(v["doc_id"], {"supports": 0, "partially_supports": 0, "refutes": 0})
                    c[v["verdict"]] += 1
        row = {}
        for doc, c in per_doc.items():
            positive = "supports" if c["supports"] else "partly" if c["partially_supports"] else None
            side = "both" if positive and c["refutes"] else positive or "refutes"
            row[doc] = {"side": side, "excerpts": sum(c.values())}
            answers[doc] = answers.get(doc, 0) + 1
            if decided and status_of(hid, doc) != h["status"]:
                decides[doc] = decides.get(doc, 0) + 1
        cells[hid] = row
        hyps.append({"hyp_id": hid, "text": h["text"], "status": h["status"],
                     "status_text": h.get("status_text") or STATUS_TEXT.get(h["status"], h["status"]),
                     "docs_counted": len(row),
                     "single_document": len(row) == 1, "batch_id": h["batch_id"]})
    docs = []
    for doc in sorted(answers, key=lambda d: (-answers[d], -decides.get(d, 0), titles.get(d, "").lower())):
        n = decides.get(doc, 0)
        docs.append({"doc_id": doc, "title": titles.get(doc, ""), "answers": answers[doc], "decides": n,
                     "key": n >= 2 and n >= 0.2 * max(1, len(hyps)), "in_project": doc in in_project})
    return {"threshold": thr, "hypotheses": hyps, "documents": docs, "cells": cells,
            "documents_without_evidence": len(set(in_project) - set(answers))}


MAP_SYMBOL = {"supports": "+", "partly": "(+)", "refutes": "−", "both": "±"}


def map_table(m: dict) -> list[dict]:
    """The evidence map as rows for a spreadsheet: one row per hypothesis, one column per document."""
    rows = []
    heads = []
    for d in m["documents"]:
        name = (d["title"] or d["doc_id"])[:60]
        while name in heads or name in ("Hypothesis", "Answer", "Documents it rests on"):
            name += " "
        heads.append(name)
    for h in m["hypotheses"]:
        row = {"Hypothesis": h["text"], "Answer": h["status_text"],
               "Documents it rests on": h["docs_counted"] if not h["single_document"] else "1 (only one document)"}
        for d, name in zip(m["documents"], heads):
            c = m["cells"].get(h["hyp_id"], {}).get(d["doc_id"])
            row[name] = f"{MAP_SYMBOL[c['side']]} {c['excerpts']}" if c else ""
        rows.append(row)
    if rows:
        rows.append({"Hypothesis": "Key: + supports, (+) partly supports, − contradicts, ± both; the number is how many "
                                   "excerpts of that document count", "Answer": "", "Documents it rests on": ""})
    return rows


CALIBRATION_BINS = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9)


def calibration(ws: Workspace) -> dict:
    """How often a person agreed with the AI, by how sure the AI was: from the excerpts a person judged that also
    have an AI judgement for or against. Agreeing means giving the same judgement; marking an AI "supports" as not
    about the hypothesis is a disagreement. For an excerpt the AI was asked to read again, its first judgement is
    used (the later ones may follow the person's own hint).

    Returns {"bins": [{"from", "to", "judged", "agreed", "rate"}], "total", "agreed", "suggestion": {"threshold",
    "reason"} | null, "note"}. The suggestion is the lowest strictness (a bin with at least 3 judgements) from which
    on you agreed with at least 80% of the AI's judgements, once at least 20 were judged.
    """
    from .people import me

    rows = []
    # 0.14: your own judgements only (a colleague's in force where you made none says nothing about you)
    for r in ws.query("SELECT verdict, confidence, user_verdict, ai_history_json FROM verifications "
                      "WHERE subject_kind='user_claim' AND user_verdict IS NOT NULL AND COALESCE(user_by, ?) = ?",
                      (me(), me())):
        first = json.loads(r["ai_history_json"] or "[]")
        if first:  # read again (perhaps with the person's hint): the AI's own first judgement is the one to compare
            r = {"verdict": first[0].get("verdict"), "confidence": first[0].get("confidence"),
                 "user_verdict": r["user_verdict"]}
        if r["verdict"] in GRADES and r["confidence"] is not None:
            rows.append(r)
    edges = list(CALIBRATION_BINS) + [1.0000001]
    bins = [{"from": a, "to": min(1.0, b), "judged": 0, "agreed": 0, "rate": None} for a, b in zip(edges, edges[1:])]
    for r in rows:
        c = float(r["confidence"])
        for b, hi in zip(bins, edges[1:]):
            if b["from"] <= c < hi:
                b["judged"] += 1
                b["agreed"] += int(r["user_verdict"] == r["verdict"])
                break
    for b in bins:
        b["rate"] = round(b["agreed"] / b["judged"], 3) if b["judged"] else None
    total, agreed = sum(b["judged"] for b in bins), sum(b["agreed"] for b in bins)
    out = {"bins": bins, "total": total, "agreed": agreed, "suggestion": None, "minimum": 20, "note": ""}
    if total < 20:
        out["note"] = f"Judge at least 20 of the AI's judgements to get a suggestion ({total} so far)."
        return out
    for i, b in enumerate(bins):
        if b["from"] < 0.5 or b["judged"] < 3:  # start where there is something to go on
            continue
        judged = sum(x["judged"] for x in bins[i:])
        ok = sum(x["agreed"] for x in bins[i:])
        if judged and ok / judged >= 0.8:
            out["suggestion"] = {"threshold": b["from"],
                                 "reason": f"When the AI was at least {round(b['from'] * 100)}% sure, you agreed with it in "
                                           f"{round(100 * ok / judged)}% of the {judged} excerpts you judged."}
            break
    if out["suggestion"] is None:
        out["note"] = "Even when the AI was very sure, you agreed with it less than 80% of the time: keep reviewing."
    return out


def export_rows(ws: Workspace, threshold: float | None = None) -> list[dict]:
    """One row per graded passage of every check (one row for a check with no grade), for a spreadsheet."""
    rows = []
    for h in _cc.history(ws, threshold):
        res = hypothesis_result(ws, h["hyp_id"], threshold)
        for part in res["parts"]:
            graded = [p for p in part["passages"] if p["verdict"] or p["user_verdict"]] or [None]
            for p in graded:
                rows.append({"hyp_id": res["hyp_id"], "claim_id": part["claim_id"], "checked_at": res["created_at"],
                             "hypothesis": res["text"], "part": part["part"], "claim": part["claim"],
                             "framework": res["framework"] or "", "target": res["code"] or "", "status": res["status"],
                             "part_status": part["status"], "model": h["model"],
                             "verdict": (p["verdict"] or "") if p else "", "ai_verdict": (p["ai_verdict"] or "") if p else "",
                             "confidence": p["confidence"] if p and p["confidence"] is not None else "",
                             "counted": (int(p["counted"]) if p else ""),
                             "user_verdict": (p["user_verdict"] or "") if p else "",
                             "user_note": (p["user_note"] or "") if p else "",
                             "quote": (p["quote"] or "") if p else "", "source": p["title"] if p else "",
                             "page": (p["page"] or "") if p else "", "location": (p["location"] or "") if p else "",
                             "found_by": p["found_by"] if p else "", "note": res["note"] or ""})
    return rows


def hypothesis_rows(res: dict) -> list[dict]:
    """The rows of one hypothesis result for CSV: every passage read, graded or not."""
    out = []
    for part in res["parts"]:
        for p in part["passages"]:
            out.append({"hypothesis": res["text"], "status": res["status"], "part": part["part"], "claim": part["claim"],
                        "part_status": part["status"], "verdict": p["verdict"] or "", "ai_verdict": p["ai_verdict"] or "",
                        "confidence": p["confidence"] if p["confidence"] is not None else "", "counted": int(p["counted"]),
                        "user_verdict": p["user_verdict"] or "", "user_note": p["user_note"] or "",
                        "quote": p["quote"] or "", "source": p["title"], "page": p["page"] or "",
                        "location": p["location"] or "", "found_by": p["found_by"], "note": res["note"] or "",
                        "assessment": _assessment_text(res)})
    return out


def _assessment_text(res: dict) -> str:
    """0.18.1 (N4): the assessment in words, as one paragraph, for the exports that carry a verdict."""
    from . import assessment

    return assessment.text(res["assessment"]) if res.get("assessment") else ""


JUDGEMENT_TEXT = {"supports": "Supports", "partially_supports": "Partly supports", "refutes": "Contradicts",
                  "not_relevant": "Not about the hypothesis", None: "Not about the hypothesis"}


def _local_dt(iso: str | None):
    """A local date and time (without zone) that Excel shows as a date; the text as given if it is not one."""
    import datetime as _dt

    try:
        return _dt.datetime.fromisoformat(iso).astimezone().replace(tzinfo=None, microsecond=0)
    except (TypeError, ValueError):
        return iso or ""


class ResultCache:
    """The history and the results of a project at one strictness, computed once for an Excel file (0.11.1: the
    sheets of one download each ran the history and every hypothesis's result again, two or three times over)."""

    def __init__(self, ws: Workspace, threshold: float | None = None):
        self.ws = ws
        self.thr = _threshold(ws, threshold)
        self._history: list[dict] | None = None
        self._results: dict[str, dict] = {}

    def history(self) -> list[dict]:
        if self._history is None:
            self._history = _cc.history(self.ws, self.thr)
        return self._history

    def result(self, hyp_id: str) -> dict:
        if hyp_id not in self._results:
            self._results[hyp_id] = hypothesis_result(self.ws, hyp_id, self.thr)
        return self._results[hyp_id]


def export_table(ws: Workspace, threshold: float | None = None, hyp_ids: list[str] | None = None,
                 every_excerpt: bool = True, cache: ResultCache | None = None) -> list[dict]:
    """Rows for a spreadsheet a person will read: the app's own words, local times, notes and corrections.

    One row per excerpt read, the ones judged not about the hypothesis included (without `every_excerpt`, only the
    judged ones); a hypothesis without any excerpt still gets one row.
    """
    cache = cache or ResultCache(ws, threshold)
    ids = hyp_ids if hyp_ids is not None else [h["hyp_id"] for h in cache.history()]
    rows = []
    results = [cache.result(hid) for hid in ids]
    seconds = any(r["second_read"] for r in results)  # columns for a second model only when one was asked
    for res in results:
        n_parts = len(res["parts"])
        for part in res["parts"]:
            chosen = [p for p in part["passages"] if every_excerpt or p["verdict"] or p["user_verdict"]] or [None]
            for p in chosen:
                # 0.14.3: an excerpt no AI judged (its document may not be read by any AI, or its part waits or
                # failed) says so, instead of "Judged by: the AI / Not about the hypothesis"
                unread = not_read_text(p) if p else None
                # an excerpt of a round whose check failed: nothing the AI said about it counts
                failed = bool(p and p.get("round_failed") and not p["user_verdict"])
                judged_by = ((p.get("judged_by") or "you") if p["user_verdict"] else
                             "nobody: the check did not work" if failed else
                             "nobody yet" if unread else "the AI") if p else ""
                judgement = ("Not counted: the check did not work" if failed else
                             "Not judged yet" if unread and not p["user_verdict"]
                             else JUDGEMENT_TEXT.get(p["verdict"], "")) if p else ""
                if p and p.get("round_failed") and not unread:
                    unread = f"{JUDGEMENT_TEXT.get(p['ai_verdict'])} (not counted: the check did not work)"
                cert = certainty_word(p["confidence"]) if p and p["ai_verdict"] else ""
                rows.append({
                    "Checked on": _local_dt(res["created_at"]),
                    "Hypothesis": res["text"],
                    "Answer": res.get("status_text") or STATUS_TEXT.get(res["status"], res["status"]),
                    "Part": f"{part['part']} of {n_parts}" if n_parts > 1 else "",
                    "Part checked": part["claim"] if n_parts > 1 else "",
                    "Answer for this part": _part_text(part) if n_parts > 1 else "",
                    "Judgement": judgement,
                    "Judged by": judged_by,
                    "AI's own judgement": (unread or JUDGEMENT_TEXT.get(p["ai_verdict"])) if p else "",
                    "AI certainty": f"{cert} ({round(p['confidence'] * 100)}%)" if cert else "",
                    "Counted in the answer": ("yes" if p["counted"] else "no") if p else "",
                    "Quote": (p["quote"] or "") if p else "",
                    "Quote chosen by": (p["quote_by"] or "") if p and p["quote"] else "",
                    "Document": p["title"] if p else "",
                    "Where": (p["location"] or "") if p else "",
                    "Your comment on this excerpt": (p["user_note"] or "") if p else "",
                    "About another group (AI's note)": (p["scope_note"] or "") if p else "",
                    "What the quote refers to (AI)": (f"{p['refers_to']} ({p['refers_location']})" if p["refers_location"]
                                                      else p["refers_to"]) if p and p.get("refers_to") else "",
                    "Words that found this excerpt": ", ".join(p.get("matched") or []) if p else "",
                    "AI's earlier judgement (before reading it again)": _earlier(p) if p else "",
                    "Excerpt (the text the AI read)": p["text"] if p else "",
                    "Your notes on this result": res["note"] or "",
                    "Code": f"{res.get('code_label') or ''} {res['code']}".strip() if res["code"] else "",
                })
                if seconds:
                    so = p["second"] if p else None
                    rows[-1].update({
                        "Second model": so["model"] if so else "",
                        "Second model's judgement": JUDGEMENT_TEXT.get(so["verdict"]) if so else "",
                        "Second model's certainty": (f"{certainty_word(so['confidence'])} ({round(so['confidence'] * 100)}%)"
                                                     if so and so["confidence"] is not None else ""),
                        "The two models agree": ("yes" if so["agrees"] else "no") if so else "",
                    })
    return rows


def not_read_text(p: dict) -> str | None:
    """0.14.3: why no AI judged an excerpt of a result (`result` passages), in words for a spreadsheet; None when a
    model did judge it."""
    if p.get("ai_read", True):
        return None
    if p.get("read_by") == "you":  # marked No AI (or Only a local AI, with no local model)
        return "Not read by an AI: kept for your own judgement"
    if p.get("waiting_local"):
        return "Not read yet: it waits for your local model"
    if p.get("read_by") == "waiting":
        return "Not read yet: it waits for the AI"
    return "Not read: the AI's answer could not be used"


def _part_text(part: dict) -> str:
    """A part's answer in words, as the result page says it."""
    return part.get("status_text") or STATUS_TEXT.get(part["status"], part["status"])


def _earlier(p: dict) -> str:
    """The AI's first judgement of an excerpt it was asked to read again: "Supports (75%)"."""
    if not p.get("ai_history"):
        return ""
    h = p["ai_history"][0]
    return JUDGEMENT_TEXT.get(h["verdict"]) + (f" ({round(h['confidence'] * 100)}%)" if h.get("confidence") is not None else "")


def strictness_text(thr: float) -> str:
    """The strictness as the app words it."""
    word = "relaxed" if thr <= 0.55 else "normal" if thr <= 0.65 else "strict" if thr <= 0.8 else "very strict"
    return f"{word}: judgements count if the AI was at least {round(thr * 100)}% sure; yours always count"


def summary_table(ws: Workspace, threshold: float | None = None, hyp_ids: list[str] | None = None,
                  cache: ResultCache | None = None) -> list[dict]:
    """One row per hypothesis, in the app's words: the answer, who says what, and how much a person reviewed."""
    cache = cache or ResultCache(ws, threshold)
    thr = cache.thr
    rows = []
    wanted = set(hyp_ids) if hyp_ids is not None else None
    for h in cache.history():
        if wanted is not None and h["hyp_id"] not in wanted:
            continue
        res = cache.result(h["hyp_id"])
        parts = res["parts"]
        rows.append({
            "Checked on": _local_dt(res["created_at"]),
            "Hypothesis": res["text"],
            "Answer": res.get("status_text") or STATUS_TEXT.get(res["status"], res["status"]),
            # 0.11.2: a stronger model read the excerpts again and its reading changed the answer
            "Answer before a stronger model read it again": STATUS_TEXT.get(res["status_before_stronger"], "")
            if res.get("status_before_stronger") else "",
            "Assessment": _assessment_text(res),  # 0.18.1 (N4): made by rules, never by an AI
            "Answer for each part": "; ".join(f"{i}. {p['claim']}: {_part_text(p)}"
                                              for i, p in enumerate(parts, 1)) if len(parts) > 1 else "",
            "Documents that support it": res["balance"]["docs_supporting"],
            "Documents that partly support it": res["balance"]["docs_partly"],
            "Documents that contradict it": res["balance"]["docs_refuting"],
            "Excerpts that count": h["supports"] + h["partly"] + h["refutes"],
            "Excerpts too uncertain to count": h["uncounted"],
            "Excerpts read": h["passages_read"],
            "Judgements you reviewed": res["reviewed"],
            "Judgements you changed": res["corrected"],
            "Excerpts not reviewed by you yet": res["to_review"],
            "Excerpts where the second opinion differs": res["disagreements"] if res["second_read"] else "",
            "Documents added since the check": len(res["docs_added_since"]),
            "Your notes on this result": res["note"] or "",
            "Code": f"{res.get('code_label') or ''} {res['code']}".strip() if res["code"] else "",
            "Strictness": strictness_text(thr),
            # 0.14.3: every model whose answers the check used (a stronger model, the local model), from the answers
            "AI model used (for a methods section)": models_text(res),
        })
    return rows


def write_xlsx(rows: list[dict], path_or_buffer, title: str = "Results", summary: list[dict] | None = None,
               extra: list[tuple[str, list[dict]]] | None = None) -> None:
    """A tidy Excel file: bold header, wrapped long columns, frozen header row, filters. With `summary`, a first sheet
    "Summary" (one row per hypothesis) comes before the sheet of excerpts; `extra` sheets (name, rows) follow it."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    from .review import append_row  # text is written as text, never as a formula Excel would run

    widths = {"Hypothesis": 50, "Part checked": 40, "Quote": 70, "Document": 40, "Your comment on this excerpt": 40,
              "Your notes on this result": 40, "Excerpt (the text the AI read)": 90, "Answer for each part": 60,
              "Strictness": 40, "About another group (AI's note)": 30, "What the quote refers to (AI)": 30,
              "Words that found this excerpt": 25, "Reason": 40, "Representative passages": 90,
              "Name": 30, "Key terms": 40, "Description": 50, "Left": 45, "Right": 45}
    wb = Workbook()
    sheets = ([("Summary", summary)] if summary is not None else []) + [(title, rows)] + list(extra or [])
    for i, (name, data) in enumerate(sheets):
        sh = wb.active if i == 0 else wb.create_sheet()
        sh.title = name[:31]
        headers = list(data[0]) if data else ["Hypothesis", "Answer"]
        append_row(sh, headers)  # a column may be named after a document (the evidence map)
        for c in sh[1]:
            c.font = Font(bold=True)
        for r in data:
            append_row(sh, [r.get(h, "") for h in headers])
        for j, h in enumerate(headers, 1):
            sh.column_dimensions[get_column_letter(j)].width = widths.get(h, max(12, min(30, len(h) + 2)))
            if h == "Checked on":
                sh.column_dimensions[get_column_letter(j)].width = 17
                for cell in sh[get_column_letter(j)][1:]:
                    cell.number_format = "yyyy-mm-dd hh:mm"
            if h in widths:
                for cell in sh[get_column_letter(j)][1:]:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
        sh.freeze_panes = "A2"
        if data:
            sh.auto_filter.ref = sh.dimensions
    wb.save(path_or_buffer)


# at the end, so that this module can be imported before `claimcheck` (they refer to each other; both are read at call time)
from .check_results import _threshold, certainty_word, hypothesis_result, models_text  # noqa: E402
from . import claimcheck as _cc  # noqa: E402
