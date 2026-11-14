"""Reading the results of a check: where an excerpt sits in its document, the result of a claim and of a hypothesis,
which models read it, and the documents added since. `claimcheck` re-exports every name here. What stays in
`claimcheck` is reached as `_cc.name` at call time, so patching `claimcheck.<name>` still works.
"""
from __future__ import annotations

import bisect
import json

from . import access, frameworks, tasks
from .reread import is_tombstone
from .store import Workspace
from .textutil import find_quote
from .verdicts import (
    GRADES, PERSON, STATUS_TEXT, UNSUPPORTED_NONSCI, WAITING_LOCAL, WAITING_YOU, _before_stronger, _queued_open,
    _status_of_rounds, aggregate, balance, changed_by_person, effective, nonsci_text, set_aside, stronger_eligible,
    who_says_what,
)


def _threshold(ws: Workspace, threshold: float | None) -> float:
    return float(ws.config["thresholds"]["support_confidence"]) if threshold is None else float(threshold)


def certainty_word(conf: float | None) -> str:
    """The AI's certainty in words, as the app shows it."""
    if conf is None:
        return ""
    return "high" if conf >= 0.8 else "medium" if conf >= 0.6 else "low"


def _locations(ws: Workspace, ids: list[str], at: dict[str, int] | None = None) -> dict[str, dict]:
    """Where each passage is, as a reader cites it (see `locate`), keyed by passage id."""
    return locate(ws, [(pid, pid, (at or {}).get(pid)) for pid in dict.fromkeys(ids)])


def locate(ws: Workspace, items: list[tuple]) -> dict:
    """Where each of several places is, as a reader cites it: `items` are (key, passage_id, offset or None), the
    offset in document characters (a quote, a concordance hit); the result is keyed by `key`, so one passage can be
    located at several offsets in one call.

    - PDFs (and other paged documents) stored from 0.6 on: the page and the paragraph on that page, of the quote
      when `at` gives its offset ("page 2, paragraph 3"); stored earlier: the page;
    - documents without pages: the paragraph ("paragraph 6 of 8"), or for documents stored before paragraphs were
      kept, how far into the document it starts.
    `span` says what the whole excerpt covers ("page 2, paragraphs 3–4", "pages 2–3", "paragraphs 1–6 of 8").
    """
    out: dict = {}
    if not items:
        return out
    ids = list(dict.fromkeys(pid for _k, pid, _o in items))
    by_id = {}
    for i in range(0, len(ids), 900):  # SQLite's limit on bound parameters
        chunk = ids[i:i + 900]
        for r in ws.query("SELECT p.passage_id, p.doc_id, p.start, p.end, p.page, d.n_chars FROM passages p JOIN "
                          f"documents d ON d.doc_id=p.doc_id WHERE p.passage_id IN ({','.join('?' * len(chunk))})", chunk):
            by_id[r["passage_id"]] = r
    rows = list(by_id.values())
    doc_ids = sorted({r["doc_id"] for r in rows})
    paras: dict[str, list[int]] = {}                          # documents without pages: paragraph starts
    on_page: dict[tuple[str, int], list[int]] = {}            # paged documents: paragraph starts per page
    if doc_ids:
        for r in ws.query(f"SELECT doc_id, start, page FROM paragraphs WHERE doc_id IN ({','.join('?' * len(doc_ids))}) "
                          "ORDER BY doc_id, n", doc_ids):
            if r["page"] is None:
                paras.setdefault(r["doc_id"], []).append(r["start"])
            else:
                on_page.setdefault((r["doc_id"], r["page"]), []).append(r["start"])
    heads: dict[str, list[tuple[int, int]]] = {}
    if doc_ids:
        for r in ws.query(f"SELECT doc_id, start, end FROM headings WHERE doc_id IN ({','.join('?' * len(doc_ids))}) "
                          "ORDER BY doc_id, start", doc_ids):
            heads.setdefault(r["doc_id"], []).append((r["start"], r["end"]))

    def past_heading(doc: str, offset: int) -> int:
        """A quote that starts with a heading is cited at the paragraph the heading introduces."""
        for h0, h1 in heads.get(doc, ()):
            if h0 <= offset < h1:
                return h1 + 1
        return offset

    page_ends: dict[str, list[int]] = {}
    paged = sorted({r["doc_id"] for r in rows if r["page"]})
    if paged:
        for r in ws.query(f"SELECT doc_id, end FROM pages WHERE doc_id IN ({','.join('?' * len(paged))}) "
                          "ORDER BY doc_id, page", paged):
            page_ends.setdefault(r["doc_id"], []).append(r["end"] + 2)

    def page_at(doc: str, offset: int, default: int) -> int:
        ends = page_ends.get(doc)
        return min(len(ends), bisect.bisect_right(ends, offset) + 1) if ends else default

    def para_on(doc: str, page: int, offset: int) -> int | None:
        starts = on_page.get((doc, page))
        return max(1, bisect.bisect_right(starts, offset)) if starts else None

    for key, pid, quote_at in items:
        r = by_id.get(pid)
        if r is None:
            continue
        pct = round(100 * (r["start"] or 0) / max(1, r["n_chars"] or 1))
        starts = paras.get(r["doc_id"])
        a0, b0 = r["start"] or 0, max((r["end"] or 1) - 1, r["start"] or 0)
        span = None  # what the whole excerpt covers (the location says where its quote is)
        if r["page"]:
            first, last = page_at(r["doc_id"], a0, r["page"]), page_at(r["doc_id"], b0, r["page"])
            pa, pb = para_on(r["doc_id"], first, a0), para_on(r["doc_id"], first, b0) if last == first else None
            if last > first:
                span = f"pages {first}–{last}"
            elif pa is not None and pb is not None:
                span = f"page {first}, paragraph {pa}" if pa == pb else f"page {first}, paragraphs {pa}–{pb}"
            else:
                span = f"page {first}"
        elif starts:
            a = max(1, bisect.bisect_right(starts, a0))
            b = max(a, bisect.bisect_right(starts, b0))
            span = f"paragraph {a} of {len(starts)}" if a == b else f"paragraphs {a}–{b} of {len(starts)}"
        if quote_at is not None:
            quote_at = past_heading(r["doc_id"], quote_at)
        if r["page"]:
            off = quote_at if quote_at is not None else a0
            pg = page_at(r["doc_id"], off, r["page"])
            n = para_on(r["doc_id"], pg, off)
            where = (f"page {pg}, paragraph {n}" if n is not None and quote_at is not None
                     else span if quote_at is None else f"page {pg}")
        elif starts and quote_at is not None:  # the paragraph of the quote
            where = f"paragraph {max(1, bisect.bisect_right(starts, quote_at))} of {len(starts)}"
        elif starts:  # no quote: the paragraphs the excerpt spans
            where = span
        else:
            where = "at the start of the document" if pct < 5 else f"about {pct}% into the document"
        out[key] = {"start": r["start"], "end": r["end"], "doc_id": r["doc_id"], "position_pct": pct,
                    "location": where, "span": span or where}
    return out


def _breaks(ws: Workspace, items: list[tuple[str, str, int, int]]) -> dict[str, list[dict]]:
    """Where new paragraphs and headings begin inside each excerpt (offsets local to the excerpt), from the layout
    found when its document was added: {passage_id: [{"at", "kind": "paragraph" | "heading", "end"?}]}.
    `items` are (passage_id, doc_id, start, end) in document offsets. Documents added before 0.6 have no layout."""
    out: dict[str, list[dict]] = {}
    docs = sorted({d for _p, d, _a, _b in items})
    if not docs:
        return out
    q = ",".join("?" * len(docs))
    paras: dict[str, list[int]] = {}
    for r in ws.query(f"SELECT doc_id, start FROM paragraphs WHERE doc_id IN ({q}) ORDER BY doc_id, start", docs):
        paras.setdefault(r["doc_id"], []).append(r["start"])
    heads: dict[str, list[tuple[int, int]]] = {}
    for r in ws.query(f"SELECT doc_id, start, end FROM headings WHERE doc_id IN ({q}) ORDER BY doc_id, start", docs):
        heads.setdefault(r["doc_id"], []).append((r["start"], r["end"]))
    for pid, doc, a, b in items:
        if a is None or b is None:
            continue
        got: list[dict] = []
        hs = heads.get(doc, [])
        for h0, h1 in hs[bisect.bisect_left(hs, (a, -1)):]:
            if h0 >= b:
                break
            got.append({"at": h0 - a, "kind": "heading", "end": min(h1, b) - a})
        starts = paras.get(doc, [])
        taken = {g["at"] for g in got}
        for p0 in starts[bisect.bisect_right(starts, a):]:
            if p0 >= b:
                break
            if p0 - a not in taken:
                got.append({"at": p0 - a, "kind": "paragraph"})
        if got:
            out[pid] = sorted(got, key=lambda g: (g["at"], g["kind"] != "heading"))
    return out


def _round_notes(ws: Workspace, rounds: list) -> list[str | None]:
    """The AI's own short note on each round of excerpts (from its accepted answer)."""
    notes = []
    for r in rounds:
        raw = ws.scalar("SELECT raw_json FROM results WHERE task_id=? AND valid=1 ORDER BY attempt DESC LIMIT 1",
                        (r["task_id"],))
        try:
            notes.append((tasks.parse_json(raw).get("rationale") or None) if raw else None)
        except ValueError:
            notes.append(None)
    return notes


def _readers_of(ws: Workspace, parts: list) -> dict[str, str]:
    """Who read each part of a round (0.11): "claude", "local" (a model on this computer), "ai" (another model
    server), "you" (no model may read it), or "waiting" (not answered yet)."""
    out = {}
    for t in parts:
        if _cc._is_person(t):
            out[t["task_id"]] = "you"
            continue
        local_part = t["task_id"].endswith(":local")  # read by the local model, whatever came of it (0.11.1)
        r = ws.query("SELECT route, model FROM results WHERE task_id=? AND valid=1 ORDER BY attempt DESC LIMIT 1",
                     (t["task_id"],))
        if not r:
            out[t["task_id"]] = "waiting" if t["status"] in ("pending", "retry") else ("local" if local_part else "ai")
            continue
        route, model = r[0]["route"] or "", r[0]["model"] or ""
        if local_part or route in (_cc.ROUTE_NAMES["local"], _cc.ROUTE_NAMES["baseline"]):
            out[t["task_id"]] = "local"
        elif route in (_cc.ROUTE_NAMES["claude_code"], _cc.ROUTE_NAMES["anthropic"]) or model == _cc.CHAT_MODEL or model.startswith("claude"):
            out[t["task_id"]] = "claude"
        else:
            out[t["task_id"]] = "ai"
    return out


def _opens_with_pronoun(q: str | None) -> bool:
    from .references import opens_with_pronoun

    return opens_with_pronoun(q)


def _reference_locations(ws: Workspace, items: list[dict]) -> None:
    """Where each `refers_to` is: "page 4, paragraph 2" (in the excerpt) or "the paragraph before"."""
    todo = []
    for x in items:
        if x.get("refers_start") is not None:
            pid = ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? AND start<=? ORDER BY start DESC LIMIT 1",
                            (x["doc_id"], x["refers_start"]))
            if pid:
                todo.append((x["n"], pid, x["refers_start"]))
    where = locate(ws, todo)
    for x in items:
        if x.get("refers_to"):
            loc = (where.get(x["n"]) or {}).get("location")
            x["refers_location"] = (loc or "") + (" (the text before the excerpt)" if x.get("refers_where") == "before"
                                                  else "")


def _in_excerpt(p: dict, quote: str | None) -> tuple[int, int] | None:
    """Where a quote is in an excerpt as it was shown: where it was when the excerpt was kept (`quotes_at`), else
    its first place in it."""
    text = p.get("text") or ""
    if not quote:
        return None
    at = (p.get("quotes_at") or {}).get(quote)
    if isinstance(at, int) and text[at:at + len(quote)] == quote:
        return at, at + len(quote)
    i = text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    hit = find_quote(text, quote)
    return (hit[0], hit[1]) if hit else None


def _place_kept(item: dict, p: dict, v: dict) -> None:
    """0.15: the highlight of an excerpt kept from an earlier reading of its document (Read with the new reader): in
    the excerpt as it was shown, at the quote shown (the person's, else the AI's). `doc_start` is where the excerpt
    would begin for that quote to land on its place in the document now, so `doc_start + quote_start` is the
    quote's document offset as for any excerpt; a quote with no place in the document now points nowhere (the
    excerpt is shown as one whose document is gone: `in_corpus` false, `not_placed` true)."""
    if item["quote_by"] == "you":
        q, ds = v.get("user_quote"), v.get("user_start")
    elif item["quote_by"]:
        q, ds = v.get("quote"), v.get("start")
    else:
        return
    local = _in_excerpt(p, q)
    if local is None:
        return
    item.update(quote_start=local[0], quote_end=local[1])
    if ds is not None and item["in_corpus"]:
        item["doc_start"] = ds - local[0]
    elif item["in_corpus"]:
        item.update(in_corpus=False, not_placed=True)


def result(ws: Workspace, claim_id: str, threshold: float | None = None) -> dict:
    """One claim's check: status, grades with the quote's position in each passage, search terms, rounds.

    Each passage carries the AI's grade (`ai_verdict`), a person's own judgement if they gave one (`user_verdict`),
    the judgement that counts (`verdict`), and whether it counts at this threshold (`counted`).
    """
    return _result(ws, claim_id, threshold)[0]


def _result(ws: Workspace, claim_id: str, threshold: float | None = None) -> tuple[dict, dict]:
    """`result`, and what `hypothesis_result` needs of it besides (so it does not read it all again per part): the
    judgements that count (`vs`), the rounds (`groups`) and the claim's `stage`."""
    thr = _threshold(ws, threshold)
    rows = ws.query("SELECT * FROM user_claims WHERE claim_id=?", (claim_id,))
    if not rows:
        raise KeyError(claim_id)
    uc = dict(rows[0])
    groups = _cc._rounds(ws, claim_id)
    rounds = [t for g in groups for t in g]
    terms_all = json.loads(uc["terms_json"] or "[]")
    out = {"claim_id": claim_id, "hyp_id": uc.get("hyp_id") or claim_id, "part": uc.get("part") or 0,
           "role": uc.get("role"), "claim": uc["text"], "target": uc["target"], "framework": uc.get("framework"),
           "created_at": uc["created_at"], "terms": terms_all, "rationale": uc["rationale"],
           "model": uc["model"], "options": json.loads(uc["options_json"] or "{}"), "threshold": thr, "passages": [],
           "errors": [], "rounds": len(groups), "rounds_info": [], "waiting_for_you": 0, "waiting_local": 0}
    if uc["target"]:
        try:
            _fw, _c, desc, label = frameworks.resolve(ws, uc.get("framework") or "sdg", uc["target"])
            out["target_description"], out["target_label"] = desc, label
        except ValueError:
            pass
    raw_vs = [dict(v) for v in ws.query("SELECT * FROM verifications WHERE subject_kind='user_claim' AND subject_id=?",
                                        (claim_id,))]
    access_of = access.levels(ws, list({p["doc_id"] for t in rounds for p in json.loads(t["payload_json"])["passages"]}))
    counts, failed = _cc._counting(groups)  # 0.14.3: the AI's judgements in a round that failed count nowhere
    vs_all = [effective(v) for v in raw_vs if counts(v)]
    # 0.18.6 (docrole.py): the judgements of excerpts of Non-scientific documents are read and shown, never counted
    from .docrole import nonscientific_docs

    nonsci = nonscientific_docs(ws)
    vs = set_aside(vs_all, nonsci)
    out["balance"] = balance(vs, thr)
    stage = uc.get("stage")
    extra = {"vs": vs, "groups": groups, "stage": stage}
    if not rounds:
        out["status"] = out["status_any"] = "waiting" if stage in ("terms", "rank", "judge") else "no_passages"
        out["status_all_sources"] = out["status"]
        return out, extra
    readers_of = _readers_of(ws, rounds)
    shown = []
    for r_i, g in enumerate(groups, 1):
        main = _cc._main_part(g) or g[0]
        pls = [json.loads(t["payload_json"]) for t in g]
        note = _round_notes(ws, [main])[0] if not _cc._is_person(main) else None
        out["rounds_info"].append({"round": r_i, "status": _cc._round_status(g), "passages": sum(len(pl["passages"]) for pl in pls),
                                   "terms": pls[0].get("terms", terms_all if r_i == 1 else None), "ai_note": note,
                                   # 0.8: which task it is, and whether a stronger model read it (or will)
                                   "task_id": main["task_id"], "stepped_up": bool(main["step"]) and not main["again"],
                                   "stronger_waiting": bool(main["again"]), "waiting": any(_queued_open(t) for t in g),
                                   # 0.11: who read which excerpts of this round
                                   "parts": [{"task_id": t["task_id"], "read_by": readers_of[t["task_id"]],
                                              "passages": len(pl["passages"]), "status": t["status"]}
                                             for t, pl in zip(g, pls)]})
        for t, pl in zip(g, pls):
            shown += [(r_i, p, t) for p in pl["passages"]]
    for rd in out["rounds_info"]:  # 0.11.2: whether "Ask a stronger model" can still read this search again
        rd["can_step_up"] = stronger_eligible(rd)
    by_passage = {v["passage_id"]: v for v in raw_vs}
    locs = _locations(ws, list({p["passage_id"] for _r, p, _t in shown}),
                      {v["passage_id"]: (v["user_start"] if v.get("user_start") is not None else v["start"])
                       for v in raw_vs if v.get("start") is not None or v.get("user_start") is not None})
    breaks = _breaks(ws, [(pid, lc["doc_id"], lc["start"], lc["end"]) for pid, lc in locs.items()])
    seconds = _second_opinions(ws, [claim_id]).get(claim_id, {})
    # 0.14: who judged each excerpt (yours, or a colleague's where you made none), and everyone else's judgement
    from . import people

    who, me = people.names(ws), people.me()
    others = people.others(ws, [claim_id])
    # 0.14.3: your own verdict on each excerpt (the one in force may be a colleague's, with your comment beside it):
    # what the page sends back with a comment of yours, so a colleague's verdict is never saved as yours
    my_rows = {r["passage_id"]: r["verdict"] for r in ws.query(
        "SELECT passage_id, verdict FROM judgements WHERE claim_id=? AND person_id=?", (claim_id, me))}
    # 0.13.3: the title a document has now (the work's title from the bibliography), not the one the check stored;
    # a document removed since keeps the stored one
    titles_now = {r["doc_id"]: r["title"] for r in ws.query("SELECT doc_id, title FROM documents")}
    for n, (r_i, p, part) in enumerate(shown, 1):
        v = by_passage.get(p["passage_id"])
        loc = locs.get(p["passage_id"], {})
        # 0.15: an excerpt kept from an earlier reading of its document (Read with the new reader, reread.py): its text
        # is the record of what was read, its pointers lead into the document as it reads now
        earlier = p.get("reader") is not None
        item = {"n": n, "round": r_i, "passage_id": p["passage_id"], "doc_id": p["doc_id"],
                "title": titles_now[p["doc_id"]] if p["doc_id"] in titles_now else p["title"], "page": p["page"],
                "location": loc.get("location") or (f"page {p['page']}" if p["page"] else None),
                "position_pct": loc.get("position_pct"), "doc_start": loc.get("start"),
                "span": loc.get("span") or (f"page {p['page']}" if p["page"] else None), "text": p["text"],
                "found_by": p.get("found_by") or "keywords",
                "verdict": None, "ai_verdict": None, "confidence": None, "certainty": "", "user_verdict": None,
                "user_note": None, "counted": False, "quote": None, "quote_start": None, "quote_end": None,
                "in_corpus": p["passage_id"] in locs, "reviewed": False, "changed": False, "quote_by": None,
                "ai_quote": None, "breaks": (p.get("breaks") or []) if earlier else breaks.get(p["passage_id"], []),
                "scope_note": None, "ai_history": [],
                "reread": False, "reread_info": None,
                # 0.7: the words that found it (F6), and what its quote refers to (F5)
                "matched": p.get("matched") or [], "refers_to": None, "refers_where": None, "refers_location": None,
                "refers_start": None, "reference_missing": False,
                # 0.11: who read it (claude, local, ai, you) and whether it still waits for the local model or a person
                "read_by": readers_of[part["task_id"]], "access": access_of.get(p["doc_id"], "none"),
                "waiting_local": part["status"] in ("pending", "retry") and part["task_id"].endswith(":local"),
                "waiting_for_you": False, "judged_by": None, "others": others.get((claim_id, p["passage_id"]), []),
                # 0.14.3: whether a model's judgement of it is stored (not for an excerpt no AI may read, nor for one
                # whose part is not answered yet or failed)
                "ai_read": False, "round_failed": p["passage_id"] in failed, "my_verdict": None,
                # 0.15: the excerpt is the text of an earlier reading of its document (`earlier_reader` read it), and
                # whether its quote has no place in the document as it reads now (it points nowhere)
                "earlier_reading": earlier, "earlier_reader": p.get("reader"), "not_placed": False}
        if v:
            ai = v["verdict"] if v["verdict"] != "not_enough_info" else None
            item["ai_read"] = v.get("model") != PERSON
            eff = effective(v)
            item.update(ai_verdict=ai, user_verdict=v.get("user_verdict"), user_note=v.get("user_note"),
                        verdict=eff["verdict"] if eff["verdict"] != "not_enough_info" else None,
                        reviewed=bool(v.get("user_verdict")), changed=changed_by_person(v),
                        scope_note=v.get("scope_note") if ai else None)
            by = v.get("user_by")
            item["my_verdict"] = (my_rows[p["passage_id"]] if p["passage_id"] in my_rows else
                                  v.get("user_verdict") if not by or by == me else None)
            if v.get("user_verdict") or v.get("user_note"):
                by = v.get("user_by")
                item["judged_by"] = "you" if not by or by == me else who.get(by, "a colleague")
            if v.get("reread_json"):
                item["reread_info"] = json.loads(v["reread_json"])
            hist = json.loads(v.get("ai_history_json") or "[]")
            if hist:  # the AI was asked to read this excerpt again: its earlier judgements, oldest first
                item.update(reread=True, ai_history=[{"verdict": h.get("verdict") if h.get("verdict") in GRADES else None,
                                                      "confidence": h.get("confidence") if h.get("verdict") in GRADES else None,
                                                      "quote": h.get("quote"), "scope_note": h.get("scope_note"),
                                                      "model": h.get("model"), "at": h.get("at"),
                                                      "replaced_at": h.get("replaced_at"), "why": h.get("why")}
                                                     for h in hist])
            base = loc.get("start")
            if ai:
                item.update(confidence=v["confidence"], certainty=certainty_word(v["confidence"]), quote=v["quote"],
                            ai_quote=v["quote"], quote_by="the AI" if v["quote"] else None)
                if v.get("refers_to"):
                    item.update(refers_to=v["refers_to"], refers_where=v.get("refers_where"),
                                refers_start=v.get("refers_start"))
                elif _opens_with_pronoun(v["quote"]) and (v.get("prompt_version") or "") >= "check-v4":
                    item["reference_missing"] = True  # check-v4 could have said what "it" is, and did not
                if earlier:
                    pass  # placed below, in the excerpt as it was shown
                elif base is not None and v["start"] is not None:
                    item.update(quote_start=v["start"] - base, quote_end=v["end"] - base)
                elif v["quote"] and v["quote"] in p["text"]:  # the document was removed later: find the quote in the copy
                    s0 = p["text"].index(v["quote"])
                    item.update(quote_start=s0, quote_end=s0 + len(v["quote"]))
            if v.get("user_quote") and v.get("user_verdict"):  # the sentence the person points to
                item.update(quote=v["user_quote"], quote_by="you")
                if earlier:
                    pass
                elif base is not None and v.get("user_start") is not None:
                    item.update(quote_start=v["user_start"] - base, quote_end=v["user_end"] - base)
                elif v["user_quote"] in p["text"]:
                    s0 = p["text"].index(v["user_quote"])
                    item.update(quote_start=s0, quote_end=s0 + len(v["user_quote"]))
            if earlier:
                _place_kept(item, p, v)
            item["counted"] = (bool(item["verdict"]) and (eff["confidence"] or 0) >= thr and counts(v)
                               and p["doc_id"] not in nonsci)
        item["nonscientific"] = p["doc_id"] in nonsci  # 0.18.6: its judgement is shown, never counted
        if earlier and is_tombstone(p["passage_id"]):
            item["not_placed"] = True  # its quote has no place in the document as it reads now
        so = seconds.get(p["passage_id"])
        item["second"] = ({**so, "agrees": so["verdict"] == item["ai_verdict"]} if so else None)
        item["waiting_for_you"] = item["read_by"] == "you" and not item["user_verdict"]
        out["waiting_for_you"] += item["waiting_for_you"]
        out["waiting_local"] += item["waiting_local"]
        out["passages"].append(item)
    statuses = [_cc._round_status(g) for g in groups]
    waiting = _cc._round_waiting(groups[-1])
    out["status"] = _status_of_rounds(statuses, vs, thr, stage, waiting)
    out["status_any"] = _status_of_rounds(statuses, vs, 0.0, stage, waiting)
    # 0.18.6: the answer counting the Non-scientific documents too (what the mark changed)
    out["status_all_sources"] = (_status_of_rounds(statuses, vs_all, thr, stage, waiting)
                                 if any(v["doc_id"] in nonsci for v in vs_all) else out["status"])
    # 0.11.2: the answer before a stronger model read the excerpts again (its reading counts; the first is kept)
    vs_first, out["stronger"] = _before_stronger([v for v in raw_vs if counts(v)])
    vs_first = set_aside(vs_first, nonsci) if vs_first else vs_first
    out["status_first"] = _status_of_rounds(statuses, vs_first, thr, stage, waiting) if vs_first else out["status"]
    out["waiting"] = out["status"] == "waiting"
    open_ = [t for g in groups for t in g if t["status"] in ("pending", "retry")]
    if out["waiting"] and stage in ("judge", "done", None) and open_ and all(t["task_id"].endswith(":local")
                                                                               for t in open_):
        out["status_text"] = WAITING_LOCAL  # 0.13.11: Claude (Code) is done with this part
    elif out["status"] == "not_checked" and out["waiting_for_you"] and "done" in statuses:
        out["status_text"] = WAITING_YOU  # 0.14.3: read by no AI, and not judged by you yet
    elif nonsci_text(out["status"], out["status_all_sources"]):
        out["status_text"] = UNSUPPORTED_NONSCI  # 0.18.6: only Non-scientific documents speak to it
    out["rounds_task_ids"] = [r["task_id"] for r in rounds]
    out["stepped_up"] = {r["task_id"]: {"step": int(r["step"] or 0), "again": bool(r["again"])} for r in rounds}
    out["round_status"] = statuses[-1]
    if "done" not in statuses or statuses[-1] in ("failed", "retry"):
        last = groups[-1]
        main = _cc._main_part(last)
        bad = (main if main is not None and main["status"] in ("failed", "retry") else
               next((t for t in last if not _cc._is_person(t) and t["status"] in ("failed", "retry")), last[-1]))
        err = ws.query("SELECT errors_json FROM results WHERE task_id=? ORDER BY attempt DESC LIMIT 1", (bad["task_id"],))
        out["errors"] = json.loads(err[0][0]) if err else []
    # a `:local` part that failed while the main part succeeded (0.11.1: it was invisible): its excerpts are shown
    # with no judgement, and the result says why
    failed_local = [t for t in groups[-1] if t["task_id"].endswith(":local") and t["status"] == "failed"]
    if failed_local:
        err = ws.query("SELECT errors_json FROM results WHERE task_id=? ORDER BY attempt DESC LIMIT 1",
                       (failed_local[0]["task_id"],))
        out["local_failed"] = {"passages": sum(len(json.loads(t["payload_json"])["passages"]) for t in failed_local),
                               "errors": (json.loads(err[0][0]) if err else [])[:5]}
    _reference_locations(ws, out["passages"])
    out["who"] = who_says_what(out["passages"])
    out["disagreements"] = sum(1 for x in out["passages"] if x["second"] and not x["second"]["agrees"])
    out["references_missing"] = sum(1 for x in out["passages"] if x["reference_missing"] and not x["reviewed"])
    order = {"supports": 0, "partially_supports": 1, "refutes": 2, None: 3}
    out["passages"].sort(key=lambda x: (order[x["verdict"]], not x["counted"], -(x["confidence"] or 0), x["n"]))
    return out, extra


def hypothesis_result(ws: Workspace, hyp_id: str, threshold: float | None = None) -> dict:
    """A hypothesis with the check of each of its parts and its overall status."""
    thr = _threshold(ws, threshold)
    rows = ws.query("SELECT * FROM hypotheses WHERE hyp_id=?", (hyp_id,))
    if not rows:
        raise KeyError(hyp_id)
    h = dict(rows[0])
    part_ids = [r[0] for r in ws.query("SELECT claim_id FROM user_claims WHERE hyp_id=? ORDER BY part, rowid", (hyp_id,))]
    got = [_result(ws, cid, thr) for cid in part_ids]
    parts = [p for p, _x in got]
    extras = {cid: x for cid, (_p, x) in zip(part_ids, got)}
    out = {"hyp_id": hyp_id, "text": h["text"], "framework": h["framework"], "code": h["code"],
           "created_at": h["created_at"], "options": json.loads(h["options_json"] or "{}"),
           "decomposed": len(parts) > 1, "model": h["model"] or (parts[0]["model"] if parts else None),
           "batch_id": h["batch_id"], "note": h["note"], "threshold": thr, "parts": parts,
           "origin": h.get("origin"), "origin_id": h.get("origin_id")}  # 0.13.6: where it comes from
    if h["code"]:
        try:
            _fw, _c, out["code_description"], out["code_label"] = frameworks.resolve(ws, h["framework"] or "sdg", h["code"])
        except ValueError:
            pass
    if not parts and h.get("queue") == "waiting":
        out["status"] = out["status_any"] = out["status_all_sources"] = "waiting"
    elif len(parts) == 1:
        out["status"], out["status_any"] = parts[0]["status"], parts[0]["status_any"]
        out["status_all_sources"] = parts[0]["status_all_sources"]
    else:
        out["status"] = aggregate([p["status"] for p in parts])
        out["status_any"] = aggregate([p["status_any"] for p in parts])
        out["status_all_sources"] = aggregate([p["status_all_sources"] for p in parts])
    # 0.14.3: as each part counts them (not the AI's judgements of a round that failed): the parts worked them out
    out["balance"] = balance([v for cid in part_ids for v in extras[cid]["vs"]], thr)
    out["documents_in_project"] = int(ws.scalar("SELECT COUNT(*) FROM documents") or 0)
    out["passages_in_project"] = int(ws.scalar("SELECT COUNT(*) FROM passages") or 0)
    out["excerpts_read"] = sum(len(p["passages"]) for p in parts)
    # 0.14.3: a part whose excerpts all wait for your own judgement is not unfinished work of the AI (the result says
    # how many excerpts wait for you instead)
    out["incomplete"] = any(p["status"] in ("failed", "not_checked", "waiting") and p.get("status_text") != WAITING_YOU
                            for p in parts)
    out["queue"] = h.get("queue")
    out["status_text"] = STATUS_TEXT.get(out["status"], out["status"])
    if out["status"] == "waiting" and _cc._only_local(  # only_local_waits, from the rounds the parts read
            [{"claim_id": cid, "stage": extras[cid]["stage"]} for cid in part_ids],
            lambda cid: [t for g in extras[cid]["groups"] for t in g]):
        out["status_text"] = WAITING_LOCAL  # 0.13.11: not "Waiting for Claude Code" once Claude Code is done
    elif out["status"] == "not_checked" and any(p.get("status_text") == WAITING_YOU for p in parts) and all(
            p.get("status_text") == WAITING_YOU for p in parts if p["status"] == "not_checked"):
        out["status_text"] = WAITING_YOU
    elif nonsci_text(out["status"], out["status_all_sources"]):
        out["status_text"] = UNSUPPORTED_NONSCI  # 0.18.6: only Non-scientific documents speak to it
    out["models_used"] = models_used(ws, hyp_id, parts)  # 0.14.3: every model whose answer the check used
    # 0.11.2: the answer the first model gave, when a stronger model read excerpts again and changed it
    firsts = [p.get("status_first", p["status"]) for p in parts]
    out["status_first"] = (firsts[0] if len(firsts) == 1 else aggregate(firsts)) if parts else out["status"]
    out["status_before_stronger"] = out["status_first"] if out["status_first"] != out["status"] else None
    st_info = [p["stronger"] for p in parts if p.get("stronger")]
    out["stronger"] = {"excerpts": sum(x["excerpts"] for x in st_info), "changed": sum(x["changed"] for x in st_info),
                       "first_models": sorted({m for x in st_info for m in x["first_models"]}),
                       "models": sorted({m for x in st_info for m in x["models"]})} if st_info else {}
    for p in parts:
        p["status_before_stronger"] = p["status_first"] if p.get("status_first", p["status"]) != p["status"] else None
    out["rationale"] = parts[0]["rationale"] if len(parts) == 1 else None
    items = [x for p in parts for x in p["passages"]]
    out["waiting_for_you"] = sum(p["waiting_for_you"] for p in parts)  # 0.11: excerpts no model may read
    out["waiting_local"] = sum(p["waiting_local"] for p in parts)      # 0.11: excerpts waiting for the local model
    # 0.14.3: your own judgements (in a shared project a colleague's counts where you made none, but it is not yours:
    # the Excel columns say "you")
    yours = lambda x: x["reviewed"] and x["judged_by"] == "you"  # noqa: E731
    mine = [x for x in items if yours(x)]
    out["corrected"] = sum(1 for x in mine if x["changed"])  # judgements you changed
    out["reviewed"] = len(mine)                               # judgements you looked at (agreed or changed)
    out["to_review"] = len(items) - len(mine)                 # excerpts read that you have not judged yet
    out["to_review_relevant"] = sum(1 for x in items if x["ai_verdict"] and not yours(x))  # of them, the AI's
    out["who"] = who_says_what(items)                                                           # grades for or against
    with_second = [x for x in items if x["second"]]
    out["second_models"] = sorted({x["second"]["model"] for x in with_second})
    out["second_read"] = len(with_second)
    out["disagreements"] = sum(1 for x in with_second if not x["second"]["agrees"])
    out["disagreements_to_review"] = sum(1 for x in with_second if not x["second"]["agrees"] and not yours(x))
    out["docs_added_since"] = new_documents(ws, hyp_id, _seen={x[1] for cid in part_ids for g in extras[cid]["groups"]
                                                               for t in g for x in _cc._excerpts(t)})
    out["docs_added_since_matching"] = sum(1 for d in out["docs_added_since"] if d["matching"])
    # 0.18.1 (N4): the assessment in words under the verdict, made by rules from the judgements above (it changes none)
    from . import assessment

    out["assessment"] = assessment.assess(ws, hyp_id, out)
    return out


MODEL_ROLES = {"decompose": "splitting the hypothesis into parts", "expand": "search words",
               "check": "judging the excerpts", "stepped": "judging again as the stronger model",
               "local": "judging the excerpts of documents marked Only a local AI",
               "reread": "reading an excerpt again"}


def models_used(ws: Workspace, hyp_id: str, parts: list[dict]) -> list[dict]:
    """0.14.3: the models whose accepted answers a check used, in the order they first answered, each with what it did:
    [{"model", "roles": [...]}], for a methods section. Read from the answers themselves, so a stronger model, the
    local model for restricted documents, an excerpt read again and a model changed in Settings before Claude Code
    answered are all named (the check's own record names the model chosen when it started). Second opinions are not
    in it: they never change an answer."""
    ids = [f"decompose:{hyp_id}"]
    for p in parts:
        ids.append(f"expand:{p['claim_id']}")
        ids += p.get("rounds_task_ids") or []
        ids += [r[0] for r in ws.query("SELECT task_id FROM tasks WHERE +kind='reread' AND task_id >= ? AND "
                                       "task_id < ?", tasks.id_range(f"reread:{p['claim_id']}:"))]
    rows: list = []
    for i in range(0, len(ids), 900):  # SQLite's limit on bound parameters
        chunk = ids[i:i + 900]
        rows += ws.query("SELECT task_id, kind, model, step, received_at FROM results WHERE valid=1 AND task_id IN "
                         f"({','.join('?' * len(chunk))})", chunk)
    rows.sort(key=lambda r: (r["received_at"] or "", r["task_id"]))
    out: dict[str, list[str]] = {}
    answered: set[str] = set()  # tasks with an accepted answer before the stronger model's
    for r in rows:
        if not r["model"] or r["model"] == PERSON:
            continue
        role = r["kind"]
        if role == "check":
            # the stronger model reads again only an answered task; one that took the last of three tries after two
            # rejected answers is the task's first answer
            again = int(r["step"] or 0) and r["task_id"] in answered
            role = "local" if r["task_id"].endswith(":local") else "stepped" if again else "check"
        answered.add(r["task_id"])
        roles = out.setdefault(r["model"], [])
        if MODEL_ROLES.get(role) and MODEL_ROLES[role] not in roles:
            roles.append(MODEL_ROLES[role])
    return [{"model": m, "roles": rs} for m, rs in out.items()]


def models_text(res: dict) -> str:
    """The models a check used, in words (`models_used`): "sonnet (search words, judging the excerpts); opus (…)".
    A check no model has answered yet names the model chosen for it."""
    used = res.get("models_used") or []
    if not used:
        return res.get("model") or ""
    return "; ".join(f"{m['model']} ({', '.join(m['roles'])})" if m["roles"] else m["model"] for m in used)


def _second_opinions(ws: Workspace, claim_ids: list[str]) -> dict[str, dict[str, dict]]:
    """The latest second-model grade of each excerpt: {claim_id: {passage_id: {model, verdict, confidence, ...}}}.
    `verdict` is None for an excerpt the second model found not about the claim."""
    out: dict[str, dict[str, dict]] = {}
    if not claim_ids:
        return out
    for r in ws.query(f"SELECT * FROM second_opinions WHERE subject_id IN ({','.join('?' * len(claim_ids))}) "
                      "ORDER BY at, rowid", claim_ids):
        graded = r["verdict"] in GRADES
        out.setdefault(r["subject_id"], {})[r["passage_id"]] = {
            "model": r["model"], "verdict": r["verdict"] if graded else None,
            "confidence": r["confidence"] if graded else None, "quote": r["quote"] if graded else None,
            "scope_note": r["scope_note"] if graded else None, "at": r["at"]}
    return out


def _shown_docs(rounds: list) -> set[str]:
    return {p["doc_id"] for r in rounds for p in json.loads(r["payload_json"])["passages"]}


def new_documents(ws: Workspace, hyp_id: str, matching: bool = True, _seen: set[str] | None = None) -> list[dict]:
    """Documents added to the project after a hypothesis was checked (or after its new documents were last read)
    that none of its rounds read from: [{doc_id, title, added_at, matching}]. `matching` says whether the document
    has an excerpt that shares a word with the hypothesis or its search words (keyword search, nothing is read).
    A check limited to chosen documents has none."""
    h = ws.query("SELECT created_at, docs_checked_at, options_json FROM hypotheses WHERE hyp_id=?", (hyp_id,))
    if not h:
        raise KeyError(hyp_id)
    if json.loads(h[0]["options_json"] or "{}").get("doc_ids"):
        return []
    cutoff = max(h[0]["created_at"] or "", h[0]["docs_checked_at"] or "")
    claims = [dict(r) for r in ws.query("SELECT claim_id, text, terms_json FROM user_claims WHERE hyp_id=?", (hyp_id,))]
    # `_seen`: the documents its rounds read, when the caller has read them (hypothesis_result)
    seen_docs = _seen if _seen is not None else _shown_docs([t for c in claims
                                                             for t in _cc._check_tasks(ws, c["claim_id"])])
    from .docrole import evidence_sql  # 0.18.1 (K2): a theory document added since is no new evidence

    rows = [d for d in ws.query("SELECT doc_id, title, added_at FROM documents WHERE added_at > ? AND "
                                f"{evidence_sql()} ORDER BY added_at, title", (cutoff,)) if d["doc_id"] not in seen_docs]
    hits: set[str] = set()
    if matching and rows:
        from .search import docs_matching

        for c in claims:
            hits |= docs_matching(ws, c["text"], json.loads(c["terms_json"] or "[]"), {d["doc_id"] for d in rows})
    return [{"doc_id": d["doc_id"], "title": d["title"] or "", "added_at": d["added_at"], "matching": d["doc_id"] in hits}
            for d in rows]


UNREAD_MIN_WORDS = 2   # roadmap N5: "holds the search words" = an excerpt with two different words of the check
UNREAD_LIST_MAX = 200  # titles listed in each group (the counts are always whole)


def unread_documents(ws: Workspace, hyp_id: str) -> dict:
    """Roadmap N5, the per-hypothesis half (0.18.7): the documents a check never showed an excerpt of, split by
    whether they hold the check's own words. A neutral count, never a verdict on a document: one never read may be off
    the hypothesis's topic, or say it in other words. Nothing is read by a model and no result changes.

    A check keeps only the excerpts it picked (`rank_passages` drops the rest of its ranking), so whether a document
    "came up" cannot be read from what is stored: the search is asked again, with each part's claim and its search
    words (`terms_json`), one keyword query per part and group (`docs_matching`).

    - *Read in this check*: any round of any part showed an excerpt of it (the excerpts of documents marked Only a
      local AI or No AI too), whatever the judgement.
    - *Left out*: theory documents (never evidence); documents added after the check (or after its new documents were
      last read: they are the check's *documents added since*); documents with no readable excerpt (not read, reading
      failed, or all their text left out in the reading view); documents a check limited to some documents was limited
      away from (a part's own limit, else the hypothesis's). Non-scientific documents are read and judged as any
      other, so they are in it.
    - `matching`: an excerpt holds at least `UNREAD_MIN_WORDS` different words of a part and its search words
      (`docs_matching(min_words=…)`); `one_word`: only single words in common; `no_word`: no word in common.

    {"hyp_id", "checked": whether the check read anything yet, "considered": documents it could have read,
    "matching": [{doc_id, title}], "matching_n", "one_word_n", "no_word": [{doc_id, title}], "no_word_n"}: the lists
    sorted by title, at most `UNREAD_LIST_MAX` each. A check that has read nothing yet has none.
    """
    out: dict = {"hyp_id": hyp_id, "checked": False, "considered": 0, "matching": [], "matching_n": 0,
                 "one_word_n": 0, "no_word": [], "no_word_n": 0}
    split = _unread_split(ws, hyp_id)
    if split is None:
        return out
    out["checked"] = True
    considered, strong, one_word, no_word = split
    if not considered:
        return out
    titles = {r[0]: r[1] or "" for r in ws.query("SELECT doc_id, title FROM documents")}

    def listed(ids: set[str]) -> list[dict]:
        rows = sorted(({"doc_id": d, "title": titles.get(d, "")} for d in ids), key=lambda x: (x["title"].lower(),
                                                                                              x["doc_id"]))
        return rows[:UNREAD_LIST_MAX]

    out.update(considered=len(considered), matching=listed(strong), matching_n=len(strong),
               one_word_n=len(one_word), no_word=listed(no_word), no_word_n=len(no_word))
    return out


def _unread_split(ws: Workspace, hyp_id: str) -> tuple[set[str], set[str], set[str], set[str]] | None:
    """(considered, matching, one word only, no word) for `unread_documents`, or None when the check has read
    nothing yet."""
    h = ws.query("SELECT created_at, docs_checked_at, options_json FROM hypotheses WHERE hyp_id=?", (hyp_id,))
    if not h:
        raise KeyError(hyp_id)
    claims = [dict(r) for r in ws.query("SELECT claim_id, text, terms_json, options_json FROM user_claims WHERE "
                                        "hyp_id=? ORDER BY part, rowid", (hyp_id,))]
    rounds = _cc._light_checks(ws, [c["claim_id"] for c in claims]) if claims else {}
    if not any(rounds.values()):
        return None
    seen = {x[1] for ts in rounds.values() for t in ts for x in _cc._excerpts(t)}
    from .docrole import not_evidence_docs
    from .search import docs_matching, passage_index

    cutoff = max(h[0]["created_at"] or "", h[0]["docs_checked_at"] or "")
    later = {r[0] for r in ws.query("SELECT doc_id FROM documents WHERE added_at > ?", (cutoff,))}
    readable = set(passage_index(ws).doc_of)   # the body text a check searches: none for an unreadable document
    pool = readable - seen - later - not_evidence_docs(ws._conn())   # N3: nor a working document
    hyp_limit = set(json.loads(h[0]["options_json"] or "{}").get("doc_ids") or [])
    strong: set[str] = set()
    some: set[str] = set()
    considered: set[str] = set()
    for c in claims:
        limit = set(json.loads(c["options_json"] or "{}").get("doc_ids") or []) or hyp_limit
        mine = pool & limit if limit else pool
        if not mine:
            continue
        considered |= mine
        terms = json.loads(c["terms_json"] or "[]")
        strong |= docs_matching(ws, c["text"], terms, mine, min_words=UNREAD_MIN_WORDS)
        some |= docs_matching(ws, c["text"], terms, mine - strong)
    return considered, strong, some - strong, considered - strong - some


# last, so that this module can be imported before `claimcheck` (the two refer to each other; `_cc.` is read at call time)
from . import claimcheck as _cc  # noqa: E402
