"""A codebook from a theory document (0.18.1, roadmap K2 part 2, Level 0: no model).

A third way to start in the codebook editor, beside *Start fresh* and *From the themes*: *From a theory document*. The
codes are the theory's own concepts (from Meadows: stock, flow, reinforcing loop, delay, leverage point…), each with a
**definition quoted from the theory, with its page**, so the codebook says where each code comes from. Its examples
come **only from the evidence documents** (never from a theory document), offered by keyword match and kept only when
the researcher ticks them: the labeller then learns what a reinforcing loop looks like in a care home, not in Meadows'
fishery.

The candidates, from the document's own structure and words, best first:

1. **defined in the text**: "a stock is …", "X is defined as …", "by X we mean …", "X refers to …", "we call this X",
   "X (also called Y) is …": the term and the sentence that defines it, quoted;
2. **headings**: short headings (at most five words, numbering taken off: "2.3 Stocks and flows" gives "Stocks and
   flows"), with the first sentence under them as the definition;
3. **frequent phrases**: words and two- or three-word phrases the document uses often (stop words left out at both
   ends), with the first sentence that uses each as the definition.

Every quote is a span of the document's own text (checked by finding it again, as quotes are everywhere). Words set in
italics are not offered: the readers do not keep fonts' slant (only boldness).

0.18.4: **the optional AI draft** (Level 2 or 3, `ai_offer`, `draft_with_ai`). An AI task (`theory_codes`, prompt
theory-codes-v1) gets these candidates and the passages of the document where they are defined or used most, and
drafts the theory's concepts: each a short name, a definition quoted exactly from the document (at least three whole
words; the quote check sends a quote that is not there back to be fixed, as for every kind) and a one-line reason. The
document's own AI setting picks the reader (Claude, a local AI, or none: then no draft is offered). The drafts join the
Level-0 list unticked and marked as the AI's, without the candidates already there; their examples still come only
from the evidence (`suggest_examples`), never from the AI. A draft asked again with the same input reuses its answer.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Callable

from .store import Workspace
from .textutil import split_sentences

MAX_TERM_WORDS = 4
MAX_CANDIDATES = 40
MAX_EXAMPLES = 3
_W = r"[A-Za-zÀ-ÖØ-öø-ÿ][\w'’-]*"
_TERM = rf"((?:{_W}\s+){{0,{MAX_TERM_WORDS - 1}}}{_W})"
# a term at the start of a sentence (an article before it allowed), then the defining words
_DEFINES = [
    re.compile(rf"^(?:(?:A|An|The)\s+)?{_TERM}\s+(?:is|are)\s+(?:defined\s+as|understood\s+as)\s+", re.I),
    re.compile(rf"^(?:(?:A|An|The)\s+)?{_TERM}\s+(?:refers?|refer)\s+to\s+", re.I),
    re.compile(rf"^(?:(?:A|An|The)\s+)?{_TERM}\s+(?:is|are)\s+(?:a|an|the)\s+", re.I),
    re.compile(rf"\bby\s+(?:(?:a|an|the)\s+)?{_TERM},?\s+(?:we|I)\s+mean\b", re.I),
    re.compile(rf"\b(?:we|I)\s+call\s+(?:this|these|it|them|such\s+\w+)\s+(?:(?:a|an|the)\s+)?{_TERM}\b", re.I),
    re.compile(rf"^(?:(?:A|An|The)\s+)?{_TERM}\s*\((?:also\s+(?:called|known\s+as)|or)\s+[^)]{{1,60}}\)\s+(?:is|are)\s+",
               re.I),
]
_NUMBERING = re.compile(r"^\s*(?:(?:chapter|part|section)\s+)?(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.)\s+", re.I)


def _stop() -> frozenset[str]:
    from .stopwords import ENGLISH, STOPWORDS_V1

    return frozenset(STOPWORDS_V1 | ENGLISH | {"chapter", "section", "figure", "table", "example", "page", "part"})


def _norm(term: str) -> str:
    t = term.lower().strip(" .,:;'\"’()")
    return t[:-1] if len(t) > 4 and t.endswith("s") and not t.endswith("ss") else t


MIN_DEFINITION_WORDS = 3


def _words(quote: str) -> int:
    """Whole words in a quote; in a script written without spaces (Chinese, Thai…) a character counts as a word."""
    from .textutil import _unspaced

    n = 0
    for tok in quote.split():
        u = sum(1 for c in tok if _unspaced(c))
        n += u + any(c.isalnum() and not _unspaced(c) for c in tok) if u else 1
    return n


def _clean_term(term: str, stop: frozenset[str]) -> str | None:
    words = term.strip(" .,:;'\"’()").split()
    while words and words[0].lower() in stop:
        words = words[1:]
    while words and words[-1].lower() in stop:
        words = words[:-1]
    if not words or len(words) > MAX_TERM_WORDS or all(w.lower() in stop for w in words):
        return None
    t = " ".join(words)
    return t if 3 <= len(t) <= 60 and not t.isdigit() else None


def _page(ws: Workspace, doc_id: str, at: int) -> int | None:
    r = ws.query("SELECT page FROM pages WHERE doc_id=? AND start<=? AND ?<end", (doc_id, at, at))
    return r[0]["page"] if r else None


def _quote(ws: Workspace, doc_id: str, text: str, a: int, z: int) -> dict:
    q = " ".join(text[a:z].split())
    return {"quote": q, "start": a, "end": z, "page": _page(ws, doc_id, a)}


def _body_sentences(ws: Workspace, doc_id: str, text: str) -> list[tuple[int, int]]:
    """The sentences of the document's body passages (what the reader counts as its text), in order."""
    out: list[tuple[int, int]] = []
    for a, z in ws.query("SELECT start, end FROM passages WHERE doc_id=? AND section='body' ORDER BY start", (doc_id,)):
        # a heading and the paragraph under it share a passage: a sentence never runs over a line break, so "A stock
        # is …" starts its own sentence after the heading "1. Stocks and flows"
        at = a
        for line in re.split(r"(\n+)", text[a:z]):
            if line.strip() and not line.startswith("\n"):
                out += split_sentences(line, at)
            at += len(line)
    return out


def candidates(ws: Workspace, doc_id: str, limit: int = MAX_CANDIDATES, with_examples: bool = True) -> dict:
    """The candidate concepts of a theory document as draft codes: {"doc_id", "title", "role", "concepts": [{"term",
    "how" ("defined" | "heading" | "frequent"), "count", "definition": {"quote", "start", "end", "page"} | None,
    "code": {code, description, described, group, keywords, include, exclude, examples: []}, "suggested":
    [examples from the evidence documents, to tick]}]}. `with_examples` False: no examples looked for (0.18.4: the
    candidates the AI draft is given)."""
    row = ws.query("SELECT title, text, role FROM documents WHERE doc_id=?", (doc_id,))
    if not row:
        raise KeyError(doc_id)
    title, text, role = row[0]["title"] or "", row[0]["text"] or "", row[0]["role"]
    stop = _stop()
    sents = _body_sentences(ws, doc_id, text)
    found: dict[str, dict] = {}

    def add(term: str | None, how: str, span: tuple[int, int] | None) -> None:
        if not term:
            return
        k = _norm(term)
        if k in found:
            if found[k]["definition"] is None and span:
                found[k]["definition"] = _quote(ws, doc_id, text, *span)
            return
        found[k] = {"term": term[0].upper() + term[1:] if term[:1].islower() else term, "how": how,
                    "definition": _quote(ws, doc_id, text, *span) if span else None}

    # 1. defined in the text
    for a, z in sents:
        s = text[a:z].strip()
        lead = len(text[a:z]) - len(text[a:z].lstrip())
        for rx in _DEFINES:
            m = rx.search(s)
            if m:
                t = _clean_term(m.group(1), stop)
                if t and not (m.start() == 0 and t.split()[0] in ("It", "This", "That", "There", "Here")):
                    add(t, "defined", (a + lead, z))
                break
    # 2. headings, with the first sentence under each
    starts = [x[0] for x in sents]
    for r in ws.query("SELECT start, end, text FROM headings WHERE doc_id=? ORDER BY start", (doc_id,)):
        h = _NUMBERING.sub("", " ".join((r["text"] or text[r["start"]:r["end"]]).split()))
        if not h or len(h.split()) > 5 or h.isupper() and len(h) > 40:
            continue
        t = _clean_term(h, stop)
        nxt = next((i for i, st in enumerate(starts) if st >= r["end"]), None)
        add(t, "heading", sents[nxt] if nxt is not None else None)
    # 3. frequent words and phrases (in at least three sentences)
    grams: Counter = Counter()
    first: dict[str, tuple[str, tuple[int, int]]] = {}
    for a, z in sents:
        words = re.findall(_W, text[a:z])
        seen_here = set()
        for n in (1, 2, 3):
            for i in range(len(words) - n + 1):
                g = words[i:i + n]
                if g[0].lower() in stop or g[-1].lower() in stop or any(len(w) < 3 for w in g):
                    continue
                k = _norm(" ".join(g))
                if k in seen_here:
                    continue
                seen_here.add(k)
                grams[k] += 1
                first.setdefault(k, (" ".join(g), (a, z)))
    # a phrase counts over the words it is made of: "feedback loop" beats "feedback" when it is nearly as frequent
    for k, n in sorted(((k, n) for k, n in grams.items() if n >= 3),
                       key=lambda x: (-x[1] * (1 + 0.6 * x[0].count(" ")), x[0])):
        if len(found) >= limit * 2:
            break
        if any(k != o and k in o.split() and grams[o] >= 0.6 * n for o in grams if " " in o and o.count(" ") > k.count(" ")):
            continue
        term, span = first[k]
        add(_clean_term(term.lower() if not term.isupper() else term, stop), "frequent", span)
    for k, c in found.items():
        c["count"] = grams.get(k, 0)
    order = {"defined": 0, "heading": 1, "frequent": 2}
    picked = sorted(found.values(), key=lambda c: (order[c["how"]], -c["count"], c["term"].lower()))[:limit]
    out = [{**c, "code": _draft_code(c["term"], c["definition"], title),
            "suggested": suggest_examples(ws, c["term"], exclude_doc=doc_id) if with_examples else []} for c in picked]
    return {"doc_id": doc_id, "title": title, "role": role, "concepts": out}


def _draft_code(term: str, d: dict | None, title: str) -> dict:
    """A draft code: the term as its name, its definition quoted with the document and page as its description."""
    page = f", p. {d['page']}" if d and d.get("page") else ""
    desc = f"“{d['quote']}” ({title}{page})" if d else f"A concept of {title}."
    return {"code": term[:40], "description": desc[:2000], "described": bool(d), "group": "",
            "keywords": [term.lower()], "include": "", "exclude": "", "examples": []}


def suggest_examples(ws: Workspace, term: str, k: int = MAX_EXAMPLES, exclude_doc: str | None = None) -> list[dict]:
    """Up to `k` sentences of the evidence documents that use the term (its words, by keyword), to offer as examples:
    never from a theory document. Each {"quote", "doc_id", "title", "page", "start", "end", "project"}."""
    from .docrole import theory_docs
    from .search import rank_passages

    theory = theory_docs(ws._conn()) | ({exclude_doc} if exclude_doc else set())   # (never the theory itself, review 16)
    words = [w.lower() for w in re.findall(_W, term)]
    if not words:
        return []
    try:
        found = rank_passages(ws, term, words, k=k * 3, per_doc=1, require_terms=True, evidence_only=True)
    except Exception:  # noqa: BLE001 - no index yet: nothing to offer
        return []
    out = []
    rx = re.compile(r"\b" + r"\W+".join(re.escape(w) for w in words), re.I)
    for p in found:
        if p["doc_id"] in theory:
            continue
        r = ws.query("SELECT p.page, p.start, p.text, d.title FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
                     "WHERE p.passage_id=?", (p["passage_id"],))
        if not r:
            continue
        t = r[0]["text"]
        m = rx.search(t)
        if not m:
            continue
        a, z = next(((a, z) for a, z in split_sentences(t) if a <= m.start() < z), (0, len(t)))
        out.append({"quote": " ".join(t[a:z].split())[:400], "doc_id": p["doc_id"], "title": r[0]["title"],
                    "page": r[0]["page"], "start": r[0]["start"] + a, "end": r[0]["start"] + z,
                    "project": ws.project_uid()})
        if len(out) >= k:
            break
    return out


def keep_evidence_examples(ws: Workspace, codes: list[dict]) -> list[dict]:
    """The codes a person kept, with any example from a theory document taken out (the rule of K2: examples come only
    from the evidence)."""
    from .docrole import theory_docs

    theory = theory_docs(ws._conn())
    out = []
    for c in codes:
        if not isinstance(c, dict):
            continue
        ex = [e for e in (c.get("examples") or []) if isinstance(e, dict) and e.get("doc_id") not in theory]
        out.append({**c, "examples": ex})
    return out



# ---------------------------------------------------------------------------------------------
# 0.18.4 (K2 part 2, Level 2 or 3): the optional AI draft
# ---------------------------------------------------------------------------------------------
AI_KIND = "theory_codes"
AI_MAX_CANDIDATES = 30   # the Level-0 candidates the AI is given as hints
AI_MAX_PASSAGES = 12     # the passages of the document it reads: where the candidates are defined or used most
AI_MAX_CHARS = 24000     # and at most this much of its text
AI_MAX_CONCEPTS = 25

NO_AI = "This document is marked No AI, so no AI drafts its concepts."
WITHDRAWN = ("The request was taken back before the AI answered (the document's AI setting changed, or a draft "
             "was stopped). Nothing was drafted: try again.")
NO_LOCAL = ("Only a local AI may read this document, and no local AI is chosen (Settings, AI: the local model for "
            "documents kept on this computer).")


def _h(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()


def _level(ws: Workspace, doc_id: str) -> str:
    from . import access

    return access.levels(ws, [doc_id]).get(doc_id) or access.default(ws)


def ai_offer(ws: Workspace, doc_id: str, settings: dict | None = None) -> dict:
    """Whether the AI may draft this document's concepts, and who would read it: {"offered", "why" (one line when
    not), "reader": "claude" | "local" | "main" | None}. The document's own AI setting decides, as everywhere: Claude
    may read it (the main AI), only a local AI (the local model, or the main one when it runs on this computer), or no
    AI (not offered)."""
    from . import home

    if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)):
        raise KeyError(doc_id)
    s = settings if settings is not None else home.load_settings()
    lv = _level(ws, doc_id)
    if lv == "none":
        return {"offered": False, "why": NO_AI, "reader": None, "level": lv}
    from .routing import OFF_COMPUTER

    claude = (s.get("backend") or "auto") in OFF_COMPUTER
    if lv == "local":
        if home.main_reads_local(s) or home.restricted_choice(s):
            return {"offered": True, "why": None, "reader": "local", "level": lv}
        return {"offered": False, "why": NO_LOCAL, "reader": None, "level": lv}
    return {"offered": True, "why": None, "reader": "claude" if claude else "main", "level": lv}


def _ai_passages(ws: Workspace, doc_id: str, terms: list[str], defined_at: list[int]) -> list[dict]:
    """The passages of the document the AI reads: those where a candidate is defined first, then those that use the
    candidates most, at most AI_MAX_PASSAGES and AI_MAX_CHARS in all, in the document's order."""
    rows = ws.query("SELECT passage_id, start, end, page, text FROM passages WHERE doc_id=? AND section='body' "
                    "ORDER BY start", (doc_id,)) or \
        ws.query("SELECT passage_id, start, end, page, text FROM passages WHERE doc_id=? ORDER BY start", (doc_id,))
    if not rows:
        return []
    rxs = [re.compile(r"\b" + r"\W+".join(re.escape(w) for w in re.findall(_W, t)) + r"\w*", re.I)
           for t in terms if re.findall(_W, t)]
    defines = {i for i, r in enumerate(rows) for at in defined_at if r["start"] <= at < r["end"]}
    score = []
    for i, r in enumerate(rows):
        hits = [len(rx.findall(r["text"] or "")) for rx in rxs]
        score.append((i not in defines, -(sum(1 for x in hits if x) * 3 + sum(hits)), r["start"], i))
    picked, size = [], 0
    for _d, _s, _a, i in sorted(score):
        if len(picked) >= AI_MAX_PASSAGES:
            break
        n = len(rows[i]["text"] or "")
        if picked and size + n > AI_MAX_CHARS:
            continue
        picked.append(i)
        size += n
    return [{"n": k, "passage_id": rows[i]["passage_id"], "page": rows[i]["page"], "text": rows[i]["text"]}
            for k, i in enumerate(sorted(picked), 1)]


def ai_payload(ws: Workspace, doc_id: str) -> dict:
    """What the AI is given: the document's title, its Level-0 candidates (names only) and its passages."""
    c = candidates(ws, doc_id, AI_MAX_CANDIDATES, with_examples=False)
    terms = [x["term"] for x in c["concepts"]]
    defined_at = [x["definition"]["start"] for x in c["concepts"] if x["how"] == "defined" and x["definition"]]
    return {"doc_id": doc_id, "title": c["title"], "candidates": terms,
            "passages": _ai_passages(ws, doc_id, terms, defined_at)}


def make_ai_task(ws: Workspace, doc_id: str, model: str) -> str:
    """The draft's task (made once per input: the same document text, candidates, prompt version and model give the
    same task, so a draft asked again reuses its answer). Returns its id."""
    from . import prompts
    from .tasks import replace_task

    payload = ai_payload(ws, doc_id)
    if not payload["passages"]:
        raise ValueError("This document has no text to read: read it again first.")
    tid = f"{AI_KIND}:{doc_id}:" + _h(json.dumps(payload, sort_keys=True, ensure_ascii=False),
                                       prompts.VERSIONS.get(AI_KIND) or "", model or "")[:12]
    with ws.connect() as cx:
        replace_task(cx, tid, AI_KIND, model, payload)
    return tid


def store_ai_draft(cx, t, payload: dict, obj: dict, model: str) -> tuple[bool, list[str]]:
    """Check the AI's draft (theory-codes-v1): every definition a quote of at least three whole words, found in the
    passage it names. The answer itself is kept with the task (`results`), and `ai_drafts` reads it."""
    from .schema import TheoryCodesOut
    from .textutil import find_quote, grade_quote_problem, partial_word_hint

    out = TheoryCodesOut.model_validate(obj)
    ps = payload.get("passages") or []
    errors = []
    for i, c in enumerate(out.concepts):
        ev = c.definition
        if ev.passage > len(ps):
            errors.append(f"concepts[{i}] ({c.name}): there is no passage P{ev.passage}")
            continue
        short = grade_quote_problem(ev.quote)
        if short or _words(ev.quote) < MIN_DEFINITION_WORDS:  # a definition needs words: 15 characters are not enough
            errors.append(f"concepts[{i}] ({c.name}): the quote {' '.join(ev.quote.split())[:80]!r} is too short to "
                          f"define the concept: quote at least {MIN_DEFINITION_WORDS} whole words, copied exactly")
            continue
        if _norm(ev.quote) == _norm(c.name):
            errors.append(f"concepts[{i}] ({c.name}): the quote only repeats the concept's name: quote the sentence "
                          "or part of it that says what the concept is")
            continue
        text = ps[ev.passage - 1]["text"]
        if not find_quote(text, ev.quote):
            errors.append(f"concepts[{i}] ({c.name}): quote not found in passage P{ev.passage}: {ev.quote[:80]!r}"
                          + partial_word_hint(text, ev.quote) + ". Copy it character for character, or quote a "
                          "shorter contiguous piece of it.")
    return not errors, errors


def ai_drafts(ws: Workspace, task_id: str, skip: set[str] | None = None) -> list[dict]:
    """The concepts of a draft's accepted answer, shaped as `candidates` shapes them (each "how": "ai", "ai": True, with
    its "reason"), without those whose normalised name is in `skip` (the Level-0 candidates) or repeated. Their
    examples are offered from the evidence documents only (`suggest_examples`), as for every candidate."""
    from .schema import TheoryCodesOut
    from .tasks import parse_json
    from .textutil import find_quote

    t = ws.query("SELECT payload_json, status FROM tasks WHERE task_id=?", (task_id,))
    if not t or t[0]["status"] != "done":
        return []
    r = ws.query("SELECT raw_json, model FROM results WHERE task_id=? AND valid=1 ORDER BY attempt DESC LIMIT 1",
                 (task_id,))
    if not r:
        return []
    payload = json.loads(t[0]["payload_json"])
    doc_id, title = payload["doc_id"], payload.get("title") or ""
    out_ = TheoryCodesOut.model_validate(parse_json(r[0]["raw_json"]))
    starts = {p["passage_id"]: s for p in payload["passages"]
              for s in [ws.scalar("SELECT start FROM passages WHERE passage_id=?", (p["passage_id"],))]}
    seen = set(skip or ())
    out = []
    for c in out_.concepts[:AI_MAX_CONCEPTS]:
        k = _norm(c.name)
        if not k or k in seen:
            continue
        p = payload["passages"][c.definition.passage - 1]
        hit = find_quote(p["text"], c.definition.quote)
        if not hit:
            continue
        seen.add(k)
        base = starts.get(p["passage_id"])
        a, z = (base + hit[0], base + hit[1]) if base is not None else (None, None)
        d = {"quote": " ".join(p["text"][hit[0]:hit[1]].split()), "start": a, "end": z,
             "page": (_page(ws, doc_id, a) if a is not None else None) or p.get("page")}
        term = c.name[0].upper() + c.name[1:] if c.name[:1].islower() else c.name
        out.append({"term": term, "how": "ai", "ai": True, "reason": c.reason, "count": 0, "definition": d,
                    "code": _draft_code(term, d, title), "model": r[0]["model"],
                    "suggested": suggest_examples(ws, term, exclude_doc=doc_id)})
    return out


def draft_with_ai(ws: Workspace, doc_id: str, backend, model: str, progress: Callable | None = None,
                  should_stop: Callable[[], bool] | None = None, readers=None) -> dict:
    """The AI drafts the concepts of a theory document (one task, see the module's notes). The reader is the one the
    document's AI setting allows (`access.Readers`: Claude, or the local model for a document only a local AI may
    read); a document marked No AI is never sent. Written to the research log. Returns {"doc_id", "title", "task_id",
    "ok", "stopped", "problems", "reused", "model", "concepts": [drafts, unticked, without the Level-0 candidates]}."""
    from . import access, researchlog
    from . import runs as runs_mod
    from . import tasks

    title = ws.scalar("SELECT title FROM documents WHERE doc_id=?", (doc_id,))
    if title is None:
        raise KeyError(doc_id)
    lv = _level(ws, doc_id)
    if lv == "none":
        raise ValueError(NO_AI)
    readers = readers or access.Readers(backend, model, should_stop=should_stop)
    got = readers.for_level(lv)
    if got is None:
        raise ValueError(NO_LOCAL if lv == "local" else NO_AI)
    be, call = got
    if progress:
        progress(0, 1)
    tid = make_ai_task(ws, doc_id, call)
    with ws.connect() as cx:  # worked out again as the text is about to leave (an add-on's floor may hold it back)
        now_lv = access.recheck(cx, tid)
    if now_lv is None or now_lv not in access.backend_levels(be):
        raise ValueError(NO_AI if now_lv == "none" else "This document may not be sent to this AI.")
    before = ws.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,))
    rid = runs_mod.start(ws, AI_KIND, doc_id, be, call, 1)
    ok, problems = tasks.run_one(ws, tid, be, call)
    runs_mod.finish(ws, rid, 1)
    if progress:
        progress(1, 1)
    last = ws.query("SELECT model, route FROM results WHERE task_id=? AND valid=1 ORDER BY attempt DESC LIMIT 1", (tid,))
    used = last[0]["model"] if last else call
    reused = before == "done" or bool(last and "kept answer" in (last[0]["route"] or ""))
    if not ok and ws.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) != "failed":
        # stopped, or taken back from the queue: nothing was drafted, and there is nothing to log. Only a stop the
        # person asked for is quiet; a task taken back for another reason (another draft's job stopped, or the
        # document's AI setting changed while it waited) says so.
        stopped = bool(should_stop and should_stop())
        return {"doc_id": doc_id, "title": title, "task_id": tid, "ok": False, "stopped": stopped,
                "withdrawn": not stopped, "why": None if stopped else WITHDRAWN,
                "problems": problems[:5], "reused": False, "model": used, "concepts": []}
    level0 = {_norm(c["term"]) for c in candidates(ws, doc_id, with_examples=False)["concepts"]}
    concepts = ai_drafts(ws, tid, level0) if ok else []
    with ws.connect() as cx:
        if ok:
            text = (f"The AI ({used}) drafted {len(concepts)} concept{'s' if len(concepts) != 1 else ''} of the theory "
                    f"document {researchlog.quoted(title, 80)} for a codebook, each with its definition quoted from it"
                    + (" (the answer kept from the same request before)" if reused else "")
                    + ". They are drafts, offered unticked: none is a code until you tick it.")
        else:
            text = (f"The AI ({used}) could not draft the concepts of the theory document "
                    f"{researchlog.quoted(title, 80)}: its quotes were not found in the text.")
        researchlog.record(cx, "codebook-drafted", text, "document", doc_id, title,
                           data={"task_id": tid, "model": used, "concepts": [c["term"] for c in concepts],
                                 "reused": reused, "ok": ok})
    return {"doc_id": doc_id, "title": title, "task_id": tid, "ok": ok, "stopped": False, "problems": problems[:5],
            "reused": reused, "model": used, "concepts": concepts}


def demo_answer(payload: dict) -> dict:
    """The offline demo's draft: each candidate the passages use, with the first sentence that uses it (no reading)."""
    out = []
    for term in payload.get("candidates") or []:
        rx = re.compile(r"\b" + re.escape(term), re.I)
        for p in payload["passages"]:
            m = rx.search(p["text"])
            if not m:
                continue
            a, z = next(((a, z) for a, z in split_sentences(p["text"]) if a <= m.start() < z), (0, len(p["text"])))
            q = " ".join(p["text"][a:z].split())
            if len(q.split()) >= 3 and len(q) <= 600:
                out.append({"name": " ".join(term.split()[:6]), "definition": {"passage": p["n"], "quote": q},
                            "reason": "Offline demo: a candidate the passages use, not read."})
            break
        if len(out) >= 10:
            break
    return {"concepts": out, "note": "Offline demo: the candidates found without AI, with a sentence that uses each."}


def prompt_size(k: int, max_chars: int) -> int:
    """The longest prompt of a draft, in characters (home.prompt_tokens)."""
    return 600 + AI_MAX_CHARS + AI_MAX_CANDIDATES * 40
