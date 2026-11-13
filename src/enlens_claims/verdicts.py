"""The statuses and verdicts of a check: the status words, what a person's judgement does to a verification row,
and how grades become a claim's status and a hypothesis's. Pure functions: this module imports nothing from
`claimcheck`, which re-exports every name here.
"""
from __future__ import annotations

import json

PERSON = "person"

STATUS_TEXT = {
    "supported": "Supported by your documents",
    "partially_supported": "Partly supported",
    "contested": "Mixed evidence",
    "contradicted": "Contradicted by your documents",
    "unsupported": "No evidence found",
    "uncertain": "Only uncertain evidence",
    "not_checked": "Not finished yet",
    "no_passages": "Nothing in your documents matched",
    "failed": "The check did not work",
    "waiting": "Waiting for Claude Code",
}
WAITING_LOCAL = "Waiting for your local model"  # 0.13.11: only the excerpts of documents marked Only a local AI wait
# 0.14.3: no excerpt is judged yet, and the ones read wait for the person (documents no AI may read): the status is
# "not_checked", shown in these words where the app shows a status text
WAITING_YOU = "Waiting for your judgement"
STATUS_HELP = {
    "supported": "At least one excerpt says what the hypothesis says, and none says the opposite.",
    "partially_supported": "No excerpt says it all, but at least one says an important part of it. Read the excerpts to "
                           "judge whether the rest follows.",
    "contested": "Some excerpts support the hypothesis and others say the opposite. Read both sides before drawing a "
                 "conclusion.",
    "contradicted": "At least one excerpt says the opposite, and none supports it.",
    "unsupported": "None of the excerpts read was about this hypothesis. That does not prove your documents never say "
                   "it: they may use other words, or the evidence may be in parts not read yet.",
    "uncertain": "The AI found excerpts that may be about this hypothesis, but it was not sure enough about any of "
                 "them for your strictness setting, so none is counted.",
    "not_checked": "No excerpt has been judged yet: they wait for the AI, or for your own judgement where their "
                   "documents may not be read by any AI.",
    "no_passages": "No part of your documents uses words close to this hypothesis. Try other wording, or add documents.",
    "failed": "The AI's answers could not be used, even after three tries. Try again, or choose another AI model in "
              "Settings.",
    "waiting": "The check is prepared and waits in the queue for Claude Code, which reads the excerpts on your own "
               "Claude plan. The answer appears here as soon as Claude Code has read them.",
}
STATUS_NEXT = {  # what a reader can usefully do next
    "supported": "Read the supporting excerpts to see whether they say exactly what you mean.",
    "partially_supported": "Read the excerpts, or look for more evidence in your documents.",
    "contested": "Compare the excerpts on both sides: do they concern the same place, group or period?",
    "contradicted": "Read the contradicting excerpt: it may concern a different situation than yours.",
    "unsupported": "Look for more evidence, or search again with other words your documents might use.",
    "uncertain": "Read the excerpts and judge them yourself, or make the strictness setting more lenient.",
    "no_passages": "Rephrase the hypothesis with words your documents use, or add documents.",
    "failed": "Check again, or choose another AI model in Settings.",
    "not_checked": "",
    "waiting": "Type /enlens-run and the project's name in Claude Code (the queue panel has the command to copy).",
}
GRADES = ("supports", "partially_supports", "refutes")


USER_VERDICTS = ("supports", "partially_supports", "refutes", "not_relevant")


def effective(v) -> dict:
    """A verification row with a person's judgement applied: theirs replaces the AI's and always counts."""
    d = dict(v)
    uv = d.get("user_verdict")
    if uv in ("supports", "partially_supports", "refutes"):
        d.update(verdict=uv, confidence=1.0)
    elif uv == "not_relevant":
        d.update(verdict="not_enough_info", confidence=None)
    return d


def changed_by_person(v) -> bool:
    """Whether a person's judgement differs from the AI's (agreeing with the AI is a review, not a change). An
    excerpt no model read (0.11, waiting for the person) has no AI judgement to change."""
    v = dict(v)
    uv = v.get("user_verdict")
    if not uv or v.get("model") == PERSON:
        return False
    ai = v.get("verdict") if v.get("verdict") in ("supports", "partially_supports", "refutes") else "not_relevant"
    return uv != ai


def first_reading(v) -> dict | None:
    """A verification row as the first model judged it, before a stronger model read it again (0.11.2), or None
    when no stronger model did. A person's own judgement is kept (it counts either way)."""
    d = dict(v)
    hist = json.loads(d.get("ai_history_json") or "[]")
    before = next((x for x in hist if x.get("why") == "stepped up"), None)
    if before is None:
        return None
    ok = before.get("verdict") in ("supports", "partially_supports", "refutes")
    d.update(verdict=before.get("verdict") if ok else "not_enough_info",
             confidence=before.get("confidence") if ok else None, model=before.get("model") or d.get("model"))
    return d


def stronger_eligible(rd: dict) -> bool:
    """Whether a stronger model can still read a search of a result again (`rounds_info[]` of `result`): a model
    answered it, and no stronger model read it or was asked to (0.11.2)."""
    main = next((x for x in rd.get("parts") or [] if x["task_id"] == rd.get("task_id")), None)
    return (rd.get("status") == "done" and not rd.get("stepped_up") and not rd.get("stronger_waiting")
            and not rd.get("waiting") and (main is None or main.get("read_by") not in ("you", "waiting")))


def _before_stronger(raw_vs: list) -> tuple[list | None, dict]:
    """The excerpts' effective judgements as they were before a stronger model read them again, and what it changed:
    (None, {}) when no stronger model read any of them."""
    firsts = [(v, first_reading(v)) for v in raw_vs]
    stepped = [(v, f) for v, f in firsts if f is not None]
    if not stepped:
        return None, {}
    grade = lambda x: x["verdict"] if x["verdict"] in GRADES else None  # noqa: E731
    info = {"excerpts": len(stepped), "changed": sum(1 for v, f in stepped if grade(v) != grade(f)),
            "first_models": sorted({f["model"] for _v, f in stepped if f.get("model")}),
            "models": sorted({v["model"] for v, _f in stepped if v.get("model")})}
    return [effective(f if f is not None else v) for v, f in firsts], info


def _graded(vs, thr: float) -> tuple[list, list, list]:
    strong = [v for v in vs if v["confidence"] is not None and v["confidence"] >= thr]
    return ([v for v in strong if v["verdict"] == "supports"], [v for v in strong if v["verdict"] == "partially_supports"],
            [v for v in strong if v["verdict"] == "refutes"])


def _waits_for_person(v) -> bool:
    """An excerpt no model read (its document may not be read by any AI) that the person has not judged yet."""
    try:
        return v["model"] == PERSON and not v["user_verdict"]
    except (KeyError, IndexError):
        return False


def claim_status(vs, thr: float) -> str:
    """A claim's status from its grades at or above the threshold. Support and contradiction together: contested.

    Grades that exist but all fall below the threshold give "uncertain" (not "nothing found": something was found).
    Rows carrying a person's judgement must be passed through `effective` first.

    0.14.3: excerpts that wait for the person's own judgement (no AI may read them) are left out until the person
    judges them: nobody has read them, so they are not "not about the hypothesis". When nothing else is judged, the
    status is "not_checked" (shown as WAITING_YOU).
    """
    vs = [v for v in vs if not _waits_for_person(v)]
    if not vs:
        return "not_checked"
    sup, part, ref = _graded(vs, thr)
    if (sup or part) and ref:
        return "contested"
    if sup or part or ref:
        return "supported" if sup else "partially_supported" if part else "contradicted"
    if any(v["verdict"] in GRADES for v in vs):
        return "uncertain"
    return "unsupported"


def balance(vs, thr: float) -> dict:
    """Documents on each side, and a lean from -1 (only contradicted) to +1 (only supported).

    Each document counts once per side, with its strongest grade's confidence; a partial grade counts half. A document
    with excerpts on both sides is counted on both (`docs_both`); `docs_counted` counts each document once.
    """
    sup: dict[str, float] = {}
    part: dict[str, float] = {}
    ref: dict[str, float] = {}
    uncounted = 0
    for v in vs:
        c = v["confidence"]
        if v["verdict"] in GRADES and (c is None or c < thr):
            uncounted += 1
        if c is None or c < thr:
            continue
        side = {"supports": sup, "partially_supports": part, "refutes": ref}.get(v["verdict"])
        if side is not None:
            side[v["doc_id"]] = max(side.get(v["doc_id"], 0.0), float(c))
    pos = sum(sup.values()) + 0.5 * sum(c for d, c in part.items() if d not in sup)
    neg = sum(ref.values())
    lean = round((pos - neg) / (pos + neg), 2) if pos + neg else None
    positive = set(sup) | set(part)
    return {"docs_supporting": len(sup), "docs_partly": len(set(part) - set(sup)), "docs_refuting": len(ref),
            "docs_both": len(positive & set(ref)), "docs_counted": len(positive | set(ref)),
            "excerpts_uncounted": uncounted, "lean": lean}


def who_says_what(items: list[dict]) -> list[dict]:
    """The documents behind an answer, by side, by the rule of `balance`: a document is listed as supporting if an
    excerpt that counts supports, as partly supporting only if none supports, and as contradicting if one contradicts
    (so a document can be on both sides). Each entry lists the locations of its excerpts that count on that side."""
    docs: dict[str, dict] = {}
    for x in items:
        if not x.get("counted") or x.get("verdict") not in GRADES:
            continue
        d = docs.setdefault(x["doc_id"], {"doc_id": x["doc_id"], "title": x["title"], "supports": [],
                                          "partially_supports": [], "refutes": []})
        d[x["verdict"]].append(x.get("location") or "")
    out = []
    for d in docs.values():
        sides = [("supports", d["supports"])] if d["supports"] else (
            [("partly", d["partially_supports"])] if d["partially_supports"] else [])
        if d["refutes"]:
            sides.append(("refutes", d["refutes"]))
        for side, locs in sides:
            out.append({"doc_id": d["doc_id"], "title": d["title"], "side": side, "excerpts": len(locs),
                        "locations": list(dict.fromkeys(l for l in locs if l)), "both_sides": len(sides) > 1 and
                        any(sd == "refutes" for sd, _ in sides)})
    order = {"supports": 0, "partly": 1, "refutes": 2}
    return sorted(out, key=lambda e: (order[e["side"]], -e["excerpts"], e["title"]))


def aggregate(statuses: list[str]) -> str:
    """The status of a hypothesis from the statuses of its parts (which must all hold for it to hold).

    - a part contradicted: contradicted (a hypothesis whose necessary part is contradicted does not hold, even if
      other parts are supported; "contested" is kept for sources that disagree about the same claim)
    - otherwise a part contested: contested
    - every part supported: supported
    - some parts (partly) supported: partially_supported
    - only uncertain grades: uncertain
    - nothing found for any part: unsupported (or no_passages when no part matched any passage)
    Parts not graded yet (or waiting for the person's own judgement), or whose grading failed, give no evidence
    either way, but the hypothesis is then at most partially_supported: it holds only if every part does, and one
    is not known (0.14.3: the manual said such parts were simply left out). When no part is left, the hypothesis
    takes their status.
    """
    if "waiting" in statuses:
        return "waiting"  # a check by queue not finished yet (0.8)
    decided = [s for s in statuses if s not in ("failed", "not_checked")]
    if not decided:
        return "failed" if "failed" in statuses else "not_checked"
    if "contradicted" in decided:
        return "contradicted"
    if "contested" in decided:
        return "contested"
    if all(s == "supported" for s in decided) and len(decided) == len(statuses):
        return "supported"
    positive = any(s in ("supported", "partially_supported") for s in decided)
    if positive:
        return "partially_supported"
    if "uncertain" in decided:
        return "uncertain"
    if all(s == "no_passages" for s in decided):
        return "no_passages"
    return "unsupported"


def _queued_open(r) -> bool:
    """A round waiting in the queue for Claude Code (0.8)."""
    try:
        return bool(r["queued"]) and r["status"] in ("pending", "retry")
    except (IndexError, KeyError):
        return False


def _status_of_rounds(round_statuses: list[str], vs, thr: float, stage: str | None = None,
                      waiting: bool = False) -> str:
    if stage in ("terms", "rank", "judge") or waiting:
        return "waiting"
    if not round_statuses:
        return "no_passages"
    if "done" in round_statuses:
        return claim_status(vs, thr)
    return "failed" if round_statuses[-1] in ("failed", "retry") else "not_checked"
