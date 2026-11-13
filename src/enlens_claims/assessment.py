"""The assessment in words (roadmap N4, 0.18.1): a few sentences under a hypothesis's verdict, made by rules from the
judgements that count, never written by an AI.

Every sentence has one rule (`rule`) and points to the excerpts it rests on (`refs`, "claim_id/passage_id", the same
pair the page's excerpt cards and the judgement route use). The words come only from the hypothesis, the quotes and
the person's own comments; the counts from what `claimcheck` already works out (`claim_status`, `balance`,
`aggregate`). So the text reads the same twice, and it changes no verdict: it says what the verdict rests on.

It follows the person's judgement: the verdict is worked out again without the person's own judgements (and their
colleagues'), and when that gives another answer, `moved_by` names the judgement that moved it ("Your judgement on
Jones 2022, page 12 turned this from Supported to Mixed evidence"). `claimcheck.set_judgement` writes the same into
the research log when a judgement changes the answer.

Excerpts of documents no AI may read, or only a local AI may read, are never quoted here: the text may go into an
export or to Claude (the connector), so they are counted, not quoted (as the connector reports them).
"""
from __future__ import annotations

import re
from collections import Counter

from .store import Workspace

SHORT = {"supported": "Supported", "partially_supported": "Partly supported", "contested": "Mixed evidence",
         "contradicted": "Contradicted", "uncertain": "Only uncertain evidence", "unsupported": "No evidence found",
         "no_passages": "Nothing matched", "not_checked": "Not finished", "failed": "Did not work",
         "waiting": "Waiting for the AI"}
GRADES = ("supports", "partially_supports", "refutes")
EVIDENCE = ("supported", "partially_supported", "contested", "contradicted", "uncertain", "unsupported")
MAX_QUOTES = 2      # quotes per side: enough to show both sides, short enough to read under the verdict
QUOTE_CHARS = 220   # a longer quote is cut at a word, with an ellipsis


def _n(k: int, one: str, many: str | None = None) -> str:
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}
    return f"{words.get(k, k)} {one if k == 1 else (many or one + 's')}"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _quote(q: str) -> str:
    q = " ".join((q or "").split())
    if len(q) > QUOTE_CHARS:
        q = q[:QUOTE_CHARS].rsplit(" ", 1)[0] + "…"
    return f"“{q}”"


def _and(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else f"{', '.join(xs[:-1])} and {xs[-1]}"


def _works(ws: Workspace, doc_ids: list[str]) -> dict[str, dict]:
    """The work each document is (bibliography): a short citation ("Jones 2022"), its year and its type."""
    out: dict[str, dict] = {}
    if not doc_ids:
        return out
    import json

    from .bibliography import cite, type_text

    marks = ",".join("?" * len(doc_ids))
    try:
        rows = ws.query("SELECT l.doc_id, b.creators_json, b.year, b.item_type FROM bib_links l JOIN bib_items b ON "
                        f"b.item_key=l.item_key WHERE l.status IN ('auto', 'confirmed') AND l.doc_id IN ({marks}) "
                        "ORDER BY b.seq", doc_ids)
    except Exception:  # noqa: BLE001 - a project without a bibliography table yet
        rows = []
    for r in rows:
        if r["doc_id"] in out:
            continue
        c = cite(json.loads(r["creators_json"] or "[]"), r["year"])
        out[r["doc_id"]] = {"cite": re.sub(r" \((\d{4}[a-z]?)\)$", r" \1", c) if c else None,
                            "year": (r["year"] or "")[:4] or None, "type": type_text(r["item_type"])}
    return out


class _Names:
    def __init__(self, ws: Workspace, items: list[dict]):
        self.works = _works(ws, sorted({x["doc_id"] for x in items}))

    def doc(self, x: dict) -> str:
        w = self.works.get(x["doc_id"]) or {}
        t = w.get("cite") or " ".join((x.get("title") or "an untitled document").split())
        return t if len(t) <= 80 else t[:80].rsplit(" ", 1)[0] + "…"

    def place(self, x: dict) -> str:
        return f"{self.doc(x)}, {x['location']}" if x.get("location") else self.doc(x)


def _ref(x: dict) -> str:
    return f"{x['claim_id']}/{x['passage_id']}"


def _quotable(x: dict) -> bool:
    return x.get("access") == "cloud"


def _items(res: dict) -> list[dict]:
    out = []
    for p in res.get("parts") or []:
        for x in p.get("passages") or []:
            out.append({**x, "claim_id": p["claim_id"], "part": p.get("part") or 0})
    return out


def _best(xs: list[dict]) -> list[dict]:
    """One excerpt per document, the strongest, in a fixed order: the person's own first, then by certainty."""
    by_doc: dict[str, dict] = {}
    for x in sorted(xs, key=lambda x: (not x.get("user_verdict"), -(x.get("confidence") or 0), x["doc_id"],
                                       x["passage_id"])):
        by_doc.setdefault(x["doc_id"], x)
    return list(by_doc.values())


def _side_sentence(xs: list[dict], names: _Names, lead: str, rule: str) -> dict | None:
    """Quotes for one side: "Against it: “…” (Jones 2022, page 12)." Excerpts of documents kept from Claude are counted."""
    best = _best(xs)
    quoted = [x for x in best if _quotable(x) and x.get("quote")][:MAX_QUOTES]
    plain = [x for x in best if _quotable(x) and not x.get("quote")][:max(0, MAX_QUOTES - len(quoted))]
    kept = [x for x in best if not _quotable(x)]
    bits = []
    for x in quoted:
        note = f"; your comment: {_quote(x['user_note'])}" if x.get("user_note") and x.get("judged_by") == "you" else ""
        bits.append(f"{_quote(x['quote'])} ({names.place(x)}{note})")
    for x in plain:
        bits.append(names.place(x))
    if kept:
        bits.append(f"{_n(len(kept), 'document')} not quoted here, as no AI may read {'it' if len(kept) == 1 else 'them'} "
                    "or only a local one may")
    if not bits:
        return None
    more = len(best) - len(quoted) - len(plain) - len(kept)
    tail = f"; and {_n(more, 'other document')}" if more > 0 else ""
    shown = quoted + plain + kept
    return {"text": f"{lead}: {'; '.join(bits)}{tail}.", "rule": rule, "refs": [_ref(x) for x in shown]}


def _verdict_sentence(res: dict) -> dict:
    st = res.get("status")
    b = res.get("balance") or {}
    head = SHORT.get(st, st or "")
    sup, part, ref = b.get("docs_supporting", 0), b.get("docs_partly", 0), b.get("docs_refuting", 0)
    sides = []
    if sup:
        sides.append(f"{_n(sup, 'document')} {'supports' if sup == 1 else 'support'} the hypothesis")
    if part:
        sides.append(f"{_n(part, 'document')} partly {'supports' if part == 1 else 'support'} it")
    if ref:
        sides.append(f"{_n(ref, 'document')} {'contradicts' if ref == 1 else 'contradict'} it")
    if sides:
        text = f"{head}. {_cap(_and(sides))}."
        if b.get("docs_both"):
            text += f" {_cap(_n(b['docs_both'], 'document'))} {'is' if b['docs_both'] == 1 else 'are'} on both sides."
    elif st == "uncertain":
        text = f"{head}. Excerpts were found, but none was judged with enough certainty to count."
    elif st == "unsupported":
        text = f"{head}. None of the excerpts read is about the hypothesis."
    elif st == "no_passages":
        text = f"{head}. No part of the documents uses words close to the hypothesis."
    elif st == "waiting":
        text = f"{head}. The excerpts have not all been judged yet."
    elif st == "failed":
        text = f"{head}. The AI's answers could not be used."
    else:
        text = f"{head}."
    return {"text": text, "rule": "verdict", "refs": []}


def _concentration(counted_pos: list[dict], names: _Names) -> dict | None:
    """A warning when one document, one year or one kind of document carries most of the support."""
    if not counted_pos:
        return None
    docs = Counter(x["doc_id"] for x in counted_pos)
    n_docs, n_ex = len(docs), len(counted_pos)
    top, k = sorted(docs.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    refs = [_ref(x) for x in counted_pos if x["doc_id"] == top]
    first = next(x for x in counted_pos if x["doc_id"] == top)
    if n_docs == 1:
        ex = f" ({_n(n_ex, 'excerpt')})" if n_ex > 1 else ""
        return {"text": f"All the support comes from one document: {names.doc(first)}{ex}.", "rule": "concentration",
                "refs": refs}
    if n_ex >= 3 and k * 2 > n_ex:
        return {"text": f"Most of the support comes from one document ({names.doc(first)}, {k} of {n_ex} excerpts).",
                "rule": "concentration", "refs": refs}
    for key, what in (("year", "of {}"), ("type", "of one kind ({})")):
        vals = {d: (names.works.get(d) or {}).get(key) for d in docs}
        if all(vals.values()) and len(set(vals.values())) == 1 and n_docs >= 2:
            v = next(iter(vals.values()))
            return {"text": f"All the support comes from documents {what.format(v.lower() if key == 'type' else v)}.",
                    "rule": "concentration", "refs": [_ref(x) for x in counted_pos]}
    return None


def _part_sentences(res: dict) -> list[dict]:
    parts = res.get("parts") or []
    if len(parts) < 2:
        return []
    out = []
    for p in parts:
        st, b = p.get("status"), p.get("balance") or {}
        what = {"supported": "holds", "partially_supported": "partly holds", "contested": "has evidence on both sides",
                "contradicted": "is contradicted", "uncertain": "has only uncertain evidence",
                "unsupported": "has no evidence: nothing found was about it",
                "no_passages": "has no evidence: nothing in the documents matched it",
                "not_checked": "is not judged yet", "waiting": "is not judged yet",
                "failed": "could not be checked"}.get(st, SHORT.get(st, st or ""))
        n = b.get("docs_counted") or 0
        docs = f" ({_n(n, 'document')})" if n and st in ("supported", "partially_supported", "contested",
                                                         "contradicted") else ""
        refs = [f"{p['claim_id']}/{x['passage_id']}" for x in p.get("passages") or [] if x.get("counted")]
        out.append({"text": f"Part {p.get('part') or len(out) + 1}, {_quote(p.get('claim') or '')}, {what}{docs}.",
                    "rule": "part", "refs": refs})
    return out


def _not_counted(items: list[dict], thr: float) -> list[dict]:
    out = []
    below = [x for x in items if x.get("verdict") and not x.get("counted") and not x.get("round_failed")]
    if below:
        out.append({"text": f"{_cap(_n(len(below), 'excerpt'))} about the hypothesis {'is' if len(below) == 1 else 'are'} "
                            f"not counted: the AI was less sure of {'it' if len(below) == 1 else 'them'} than your "
                            f"strictness setting ({thr:.2f}) asks.", "rule": "below-strictness",
                    "refs": [_ref(x) for x in below]})
    you = [x for x in items if x.get("waiting_for_you")]
    if you:
        out.append({"text": f"{_cap(_n(len(you), 'excerpt'))} from documents no AI may read "
                            f"{'waits' if len(you) == 1 else 'wait'} for your own judgement: until then "
                            f"{'it is' if len(you) == 1 else 'they are'} not counted.", "rule": "waiting-for-you",
                    "refs": [_ref(x) for x in you]})
    local = [x for x in items if x.get("waiting_local")]
    if local:
        one = len(local) == 1
        out.append({"text": f"{_cap(_n(len(local), 'excerpt'))} {'waits' if one else 'wait'} for the local model and "
                            f"{'is' if one else 'are'} not counted yet.",
                    "rule": "waiting-local", "refs": [_ref(x) for x in local]})
    return out


# ---------------------------------------------------------------------------------------------
# what the person's judgements did
# ---------------------------------------------------------------------------------------------
def _as_ai(x: dict) -> dict:
    """An excerpt's row as `claim_status` takes it, without a person's judgement."""
    from .claimcheck import PERSON

    if x.get("read_by") == "you":
        return {"verdict": "not_enough_info", "confidence": None, "model": PERSON, "user_verdict": None,
                "doc_id": x["doc_id"]}
    v = x.get("ai_verdict")
    return {"verdict": v if v in GRADES else "not_enough_info", "confidence": x.get("confidence") if v else None,
            "model": "ai", "user_verdict": None, "doc_id": x["doc_id"]}


def _with_person(x: dict) -> dict:
    from .claimcheck import effective

    d = _as_ai(x)
    if x.get("user_verdict"):
        d["user_verdict"] = x["user_verdict"]
    return effective(d)


def _usable(x: dict) -> bool:
    """An excerpt whose judgement is stored and counts somewhere (not one of a round that failed, nor one not
    answered yet)."""
    return not x.get("round_failed") and (x.get("ai_read") or x.get("read_by") == "you") and not x.get("waiting_local")


def _status(res: dict, thr: float, judged: set[str] | None) -> str | None:
    """The hypothesis's status with the person's judgements of the excerpts in `judged` only (None: all of them).
    None when a part's status does not come from its judgements (it waits, failed, matched nothing)."""
    from .claimcheck import aggregate, claim_status

    statuses = []
    for p in res.get("parts") or []:
        if p.get("status") not in EVIDENCE + ("not_checked",):
            return None
        rows = [(_with_person(x) if judged is None or _ref({**x, "claim_id": p["claim_id"]}) in judged else _as_ai(x))
                for x in p.get("passages") or [] if _usable(x)]
        statuses.append(claim_status(rows, thr))
    if not statuses:
        return None
    return statuses[0] if len(statuses) == 1 else aggregate(statuses)


def moved_by(res: dict, names: _Names | None = None, ws: Workspace | None = None) -> dict | None:
    """What the person's judgements (theirs, or a colleague's where they made none) did to the answer: None when the
    answer is the same without them. Names the one judgement that moved it, when one alone did."""
    thr = res.get("threshold") or 0.0
    items = _items(res)
    judged = [x for x in items if x.get("user_verdict") and _usable(x)]
    if not judged:
        return None
    now = _status(res, thr, None)
    if now is None or now != res.get("status"):
        return None  # worked out again, it is not the answer shown: say nothing rather than something wrong
    before = _status(res, thr, set())
    if before is None or before == now:
        return None
    all_refs = {_ref(x) for x in judged}
    movers = [x for x in judged if _status(res, thr, all_refs - {_ref(x)}) != now]
    names = names or (_Names(ws, items) if ws is not None else None)
    fr, to = SHORT.get(before, before), SHORT.get(now, now)
    if len(movers) == 1 and names is not None:
        x = movers[0]
        who = "Your" if x.get("judged_by") in (None, "you") else f"{x['judged_by']}’s"
        text = f"{who} judgement on {names.place(x)} turned this from {fr} to {to}."
        refs = [_ref(x)]
    else:
        mine = all(x.get("judged_by") in (None, "you") for x in judged)
        text = (f"{'Your' if mine else 'The people’s own'} judgements ({len(judged)}) turned this from {fr} to {to}; "
                f"by the AI's judgements alone it would be {fr}.")
        refs = sorted(all_refs)
    return {"text": text, "rule": "moved-by", "refs": refs, "from": before, "to": now}


def judgement_moved(ws: Workspace, before: dict, after: dict, claim_id: str, passage_id: str) -> str | None:
    """The sentence for the research log when one judgement changed a hypothesis's answer (`before` and `after` are
    its `hypothesis_result`): "Your judgement on Jones 2022, page 12 turned “…” from Supported to Mixed evidence."
    None when the answer stayed the same, or did not come from the judgements (a check still waiting)."""
    b, a = before.get("status"), after.get("status")
    if b == a or b not in EVIDENCE + ("not_checked",) or a not in EVIDENCE + ("not_checked",):
        return None
    x = next((x for x in _items(after) if x["claim_id"] == claim_id and x["passage_id"] == passage_id), None)
    if x is None:
        return None
    hyp = " ".join((after.get("text") or "").split())
    hyp = hyp if len(hyp) <= 160 else hyp[:160].rsplit(" ", 1)[0] + "…"
    return (f"Your judgement on {_Names(ws, [x]).place(x)} turned “{hyp}” from {SHORT.get(b, b)} to "
            f"{SHORT.get(a, a)}.")


# ---------------------------------------------------------------------------------------------
# the assessment
# ---------------------------------------------------------------------------------------------
def assess(ws: Workspace, hypothesis: str | dict, res: dict | None = None) -> dict:
    """The assessment of a hypothesis, from `claimcheck.hypothesis_result` (passed as `res`, or the hyp_id's result
    is read): {"sentences": [{"text", "rule", "refs"}], "moved_by": {"text", "rule", "refs", "from", "to"} | None}."""
    if res is None:
        from .claimcheck import hypothesis_result

        res = hypothesis_result(ws, hypothesis if isinstance(hypothesis, str) else hypothesis["hyp_id"])
    items = _items(res)
    names = _Names(ws, items)
    thr = res.get("threshold") or 0.0
    counted = [x for x in items if x.get("counted") and x.get("verdict") in GRADES]
    pos = [x for x in counted if x["verdict"] in ("supports", "partially_supports")]
    neg = [x for x in counted if x["verdict"] == "refutes"]
    sentences = [_verdict_sentence(res)]
    if res.get("status") in EVIDENCE:
        if neg:
            s = _side_sentence(neg, names, "Against it", "against")
            if s:
                sentences.append(s)
        if neg and pos:  # mixed evidence: both sides quoted
            sup = [x for x in pos if x["verdict"] == "supports"] or pos
            s = _side_sentence(sup, names, "For it", "for")
            if s:
                sentences.append(s)
        c = _concentration(pos, names)
        if c:
            sentences.append(c)
    sentences += _part_sentences(res)
    sentences += _not_counted(items, thr)
    moved = moved_by(res, names)
    if moved:
        sentences.append({k: moved[k] for k in ("text", "rule", "refs")})
    return {"sentences": sentences, "moved_by": moved}


def text(a: dict) -> str:
    """The assessment as one paragraph (exports, the research log)."""
    return " ".join(s["text"] for s in a.get("sentences") or [])
