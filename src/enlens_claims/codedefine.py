"""A code's definition drafted from its examples (roadmap K1, the optional Level 2 or 3 part).

The codebook editor is complete without AI. This is the optional help K1 names: *a draft definition and when to use it
for a code, from its example passages only, marked as a draft to rewrite.*

- **What the AI reads.** Only the passages that hold the code's example quotes (each example found again in this
  project's documents, as every example is), with the examples marked in them, and the code's name and group. Not the
  rest of the corpus, not the other codes, and not the definition already written: the draft is the examples' own
  account of the code, beside the person's.
- **What it gives.** A definition (one or two sentences), *when to use it* and *when not to use it*. The definition and
  *when to use it* each name a quote of at least three whole words from one of the passages that shows them (the quote
  check sends a quote that is not there back to be fixed, as for every kind); *when not to use it* says what the
  examples are not, so it has no quote of its own.
- **Who reads it.** Each document's own AI setting, as everywhere: a passage of a document marked *No AI* is never
  sent; one marked *Only a local AI* goes to the local model (then the whole draft is read there), or is left out when
  no local model is chosen. Examples found only in another project are left out. At least `MIN_EXAMPLES` passages
  must remain, or no draft is offered, with one line on why.
- **A draft to rewrite.** The draft is offered beside the fields, not written into them. Taken, its words are marked
  *AI draft* in the editor until the person changes them (codebooks.py keeps the AI's words under `drafted` in the
  codebook's side file, so the mark survives a save and is gone once the words are the person's own). Each draft goes
  into the research log; the same input reuses its answer (one task per input, and H4's kept answers).
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable

from .store import Workspace

KIND = "code_definition"
MIN_EXAMPLES = 2       # passages: one example gives a paraphrase of one quote, not a definition
MAX_PASSAGES = 8       # a code keeps at most codebooks.MAX_EXAMPLES (8) examples
MAX_CHARS = 16000      # and at most this much of their passages' text
MIN_QUOTE_WORDS = 3

NO_EXAMPLES = (f"Add at least {MIN_EXAMPLES} examples from this project’s documents, in different passages, first: the draft is made from the "
               "passages that hold them.")
WITHDRAWN = ("The request was taken back before the AI answered (a document's AI setting changed, or the draft was "
             "stopped). Nothing was drafted: try again.")
FIELDS = ("description", "include", "exclude")   # the editor's names for definition, when to use it, when not


def _h(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()


def _clean(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def _local_reader(settings: dict) -> bool:
    from . import home

    return bool(home.main_reads_local(settings) or home.restricted_choice(settings))


def gather(ws: Workspace, quotes: list[str], settings: dict | None = None) -> dict:
    """The passages the AI would read for these example quotes, and what is left out and why:
    {"passages": [{"n", "passage_id", "doc_id", "page", "text", "examples": [quotes in it]}], "level": the strictest
    setting kept ("cloud" | "local"), "left_out": {"elsewhere", "no_ai", "local"}: examples not found in this project,
    in documents marked No AI, in documents only a local AI may read when none is chosen}."""
    from . import access, codebooks, home

    s = settings if settings is not None else home.load_settings()
    qs = list(dict.fromkeys(_clean(q, 600) for q in quotes if _clean(q, 600)))[:MAX_PASSAGES]
    found = codebooks.find_examples(ws, qs)
    left = {"elsewhere": 0, "no_ai": 0, "local": 0}
    hits = []
    for q in qs:
        got = found.get(q)
        if not got:
            left["elsewhere"] += 1
            continue
        hits.append((q, got))
    lv = access.levels(ws, list({g["doc_id"] for _q, g in hits})) if hits else {}
    local_ok = _local_reader(s)
    by_pid: dict[str, dict] = {}
    for q, g in hits:
        level = lv.get(g["doc_id"]) or access.default(ws)
        if level == "none":
            left["no_ai"] += 1
            continue
        if level == "local" and not local_ok:
            left["local"] += 1
            continue
        row = ws.query("SELECT passage_id, page, text, start FROM passages WHERE doc_id=? AND start<=? AND end>? "
                       "ORDER BY start DESC LIMIT 1", (g["doc_id"], g["start"], g["start"]))
        if not row:
            left["elsewhere"] += 1
            continue
        r = row[0]
        p = by_pid.setdefault(r["passage_id"], {"passage_id": r["passage_id"], "doc_id": g["doc_id"],
                                                "page": r["page"], "text": r["text"] or "", "start": r["start"],
                                                "examples": [], "level": level})
        p["examples"].append(g.get("quote") or q)
    picked, size = [], 0
    for p in by_pid.values():
        if picked and size + len(p["text"]) > MAX_CHARS:
            continue
        picked.append(p)
        size += len(p["text"])
    picked.sort(key=lambda p: (p["doc_id"], p["start"]))
    level = "local" if any(p["level"] == "local" for p in picked) else "cloud"
    return {"passages": [{"n": k, **{x: p[x] for x in ("passage_id", "doc_id", "page", "text", "examples")}}
                         for k, p in enumerate(picked, 1)],
            "level": level, "left_out": left}


def _left_line(left: dict) -> str | None:
    parts = []
    if left.get("elsewhere"):
        parts.append(f"{left['elsewhere']} not found in this project's documents")
    if left.get("no_ai"):
        parts.append(f"{left['no_ai']} in documents marked No AI")
    if left.get("local"):
        parts.append(f"{left['local']} in documents only a local AI may read, and no local AI is chosen")
    if not parts:
        return None
    n = sum(left.values())
    return f"{n} example{'s' if n != 1 else ''} left out: " + "; ".join(parts) + "."


def offer(ws: Workspace, quotes: list[str], settings: dict | None = None) -> dict:
    """Whether the AI may draft a definition from these examples: {"offered", "why" (one line when not), "reader":
    "claude" | "local" | "main" | None, "passages": how many it would read, "left_out", "left_line"}."""
    from . import home

    s = settings if settings is not None else home.load_settings()
    return _offer_of(gather(ws, quotes, s), s)


def _offer_of(g: dict, s: dict) -> dict:
    from .routing import OFF_COMPUTER

    n = len(g["passages"])
    out = {"passages": n, "left_out": g["left_out"], "left_line": _left_line(g["left_out"])}
    if n < MIN_EXAMPLES:
        why = NO_EXAMPLES if not out["left_line"] else (
            f"The AI may read only {n} of this code's example passages ({out['left_line'][:-1]}), and a draft needs "
            f"at least {MIN_EXAMPLES}.")
        return {"offered": False, "why": why, "reader": None, **out}
    if g["level"] == "local":
        return {"offered": True, "why": None, "reader": "local", **out}
    claude = (s.get("backend") or "auto") in OFF_COMPUTER
    return {"offered": True, "why": None, "reader": "claude" if claude else "main", **out}


def payload_for(ws: Workspace, code: str, group: str, quotes: list[str], settings: dict | None = None,
                g: dict | None = None) -> dict:
    g = g if g is not None else gather(ws, quotes, settings)
    return {"code": _clean(code, 60), "group": _clean(group, 120),
            "docs": sorted({p["doc_id"] for p in g["passages"]}),   # for taking the task away with a document
            "passages": [{k: p[k] for k in ("n", "passage_id", "page", "text", "examples")} for p in g["passages"]],
            "left_out": g["left_out"]}


def make_task(ws: Workspace, payload: dict, model: str) -> str:
    """The draft's task, one per input: the same code name, group, passages, prompt version and model give the same
    task, so a draft asked again reuses its answer. Returns its id."""
    from . import prompts
    from .tasks import replace_task

    key = {k: payload[k] for k in ("code", "group", "passages")}
    tid = f"{KIND}:" + _h(json.dumps(key, sort_keys=True, ensure_ascii=False), prompts.VERSIONS.get(KIND) or "",
                          model or "")[:16]
    with ws.connect() as cx:
        replace_task(cx, tid, KIND, model, payload)
    return tid


def _words(q: str) -> int:
    import re

    return len(re.findall(r"\w+", q or ""))


def store_answer(cx, t, payload: dict, obj: dict, model: str) -> tuple[bool, list[str]]:
    """Check the AI's draft (code-definition-v1): the definition and *when to use it* each with a quote of at least
    three whole words, found in the passage it names; a definition that only repeats the code's name is sent back.
    The answer itself is kept with the task (`results`), and `draft_of` reads it."""
    from .schema import CodeDefinitionOut
    from .textutil import find_quote, grade_quote_problem, partial_word_hint

    out = CodeDefinitionOut.model_validate(obj)
    ps = payload.get("passages") or []
    errors = []
    if _clean(out.definition, 600).lower().strip(" .") == _clean(payload.get("code"), 60).lower():
        errors.append("definition: it only repeats the code's name: say in a sentence what the code is about")
    for field, ev in (("definition_quote", out.definition_quote), ("when_to_use_quote", out.when_to_use_quote)):
        if ev.passage > len(ps):
            errors.append(f"{field}: there is no passage P{ev.passage}")
            continue
        if grade_quote_problem(ev.quote) or _words(ev.quote) < MIN_QUOTE_WORDS:
            errors.append(f"{field}: the quote {' '.join(ev.quote.split())[:80]!r} is too short: quote at least "
                          f"{MIN_QUOTE_WORDS} whole words, copied exactly")
            continue
        text = ps[ev.passage - 1]["text"]
        if not find_quote(text, ev.quote):
            errors.append(f"{field}: quote not found in passage P{ev.passage}: {ev.quote[:80]!r}"
                          + partial_word_hint(text, ev.quote) + ". Copy it character for character, or quote a "
                          "shorter contiguous piece of it.")
    return not errors, errors


def draft_of(ws: Workspace, task_id: str) -> dict | None:
    """The accepted answer of a draft, as the editor shows it: {"description", "include", "exclude", "model",
    "quotes": {"description": {quote, doc_id, title, page}, "include": {...}}, "note"}; None when not answered."""
    from .schema import CodeDefinitionOut
    from .tasks import parse_json
    from .textutil import find_quote

    t = ws.query("SELECT payload_json, status FROM tasks WHERE task_id=?", (task_id,))
    if not t or t[0]["status"] != "done":
        return None
    r = ws.query("SELECT raw_json, model FROM results WHERE task_id=? AND valid=1 ORDER BY attempt DESC LIMIT 1",
                 (task_id,))
    if not r:
        return None
    payload = json.loads(t[0]["payload_json"])
    a = CodeDefinitionOut.model_validate(parse_json(r[0]["raw_json"]))
    quotes = {}
    for field, ev in (("description", a.definition_quote), ("include", a.when_to_use_quote)):
        p = payload["passages"][ev.passage - 1]
        hit = find_quote(p["text"], ev.quote)
        if not hit:
            continue
        doc = ws.scalar("SELECT doc_id FROM passages WHERE passage_id=?", (p["passage_id"],))
        quotes[field] = {"quote": " ".join(p["text"][hit[0]:hit[1]].split()), "doc_id": doc, "page": p.get("page"),
                         "title": ws.scalar("SELECT title FROM documents WHERE doc_id=?", (doc,)) if doc else None}
    return {"description": _clean(a.definition, 4000), "include": _clean(a.when_to_use, 2000),
            "exclude": _clean(a.when_not_to_use, 2000), "model": r[0]["model"], "quotes": quotes,
            "note": _clean(a.note, 300) or None}


def draft(ws: Workspace, codebook: str, code: str, group: str, quotes: list[str], backend, model: str,
          progress: Callable | None = None, should_stop: Callable[[], bool] | None = None, readers=None,
          settings: dict | None = None, title: str | None = None) -> dict:
    """The AI drafts a code's definition, *when to use it* and *when not* from the passages that hold its examples
    (one task, see the module's notes). `codebook` is the codebook's name, `title` its title (the name when not
    given). Written to the research log. Returns {"ok", "stopped", "withdrawn", "why",
    "problems", "reused", "model", "task_id", "passages", "left_line", "draft": draft_of(...) or None}."""
    from . import access, researchlog
    from . import runs as runs_mod
    from . import tasks

    from . import home

    s = settings if settings is not None else home.load_settings()
    g = gather(ws, quotes, s)   # once: the reader and the passages sent come from the same reading of the settings
    off = _offer_of(g, s)
    if not off["offered"]:
        raise ValueError(off["why"])
    payload = payload_for(ws, code, group, quotes, s, g)
    readers = readers or access.Readers(backend, model, settings=s, should_stop=should_stop)
    lv = "local" if off["reader"] == "local" else "cloud"
    got = readers.for_level(lv)
    if got is None:
        raise ValueError("No AI may read these examples' documents.")
    be, call = got
    if progress:
        progress(0, 1)
    tid = make_task(ws, payload, call)
    with ws.connect() as cx:  # worked out again as the text is about to leave (an add-on's floor may hold it back)
        now_lv = access.recheck(cx, tid)
    if now_lv is None or now_lv not in access.backend_levels(be):
        raise ValueError("A document of these examples may not be sent to this AI.")
    before = ws.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,))
    rid = runs_mod.start(ws, KIND, payload["code"], be, call, 1)
    ok, problems = tasks.run_one(ws, tid, be, call)
    runs_mod.finish(ws, rid, 1)
    if progress:
        progress(1, 1)
    last = ws.query("SELECT model, route FROM results WHERE task_id=? AND valid=1 ORDER BY attempt DESC LIMIT 1",
                    (tid,))
    used = last[0]["model"] if last else call
    reused = before == "done" or bool(last and "kept answer" in (last[0]["route"] or ""))
    base = {"task_id": tid, "passages": len(payload["passages"]), "left_line": off["left_line"], "model": used,
            "problems": problems[:5]}
    if not ok and ws.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) != "failed":
        stopped = bool(should_stop and should_stop())   # a stop asked for is quiet; a task taken back says so
        return {**base, "ok": False, "stopped": stopped, "withdrawn": not stopped,
                "why": None if stopped else WITHDRAWN, "reused": False, "draft": None}
    d = draft_of(ws, tid) if ok else None
    ok = bool(ok and d)
    n = len(payload["passages"])
    with ws.connect() as cx:
        if ok:
            text = (f"The AI ({used}) drafted a definition, when to use it and when not for the code "
                    f"{researchlog.quoted(payload['code'], 60)} of the codebook {researchlog.quoted(title or codebook, 60)}, "
                    f"from the {n} passages that hold its examples"
                    + (" (the answer kept from the same request before)" if reused else "")
                    + ". It is a draft to rewrite: nothing changes in the codebook until you take it and save.")
        else:
            text = (f"The AI ({used}) could not draft a definition for the code "
                    f"{researchlog.quoted(payload['code'], 60)}: its quotes were not found in the passages.")
        researchlog.record(cx, "codebook-drafted", text, "codebook", codebook, title or codebook,
                           data={"task_id": tid, "model": used, "code": payload["code"], "passages": n,
                                 "reused": reused, "ok": ok, "kind": KIND})
    return {**base, "ok": ok, "stopped": False, "withdrawn": False, "why": None, "reused": reused, "draft": d}


def demo_answer(payload: dict) -> dict:
    """The offline demo's draft: the code's name and its first example, not read."""
    ps = payload.get("passages") or []
    ex = next(((p["n"], e) for p in ps for e in p.get("examples") or [] if _words(e) >= MIN_QUOTE_WORDS),
              (1, " ".join(((ps[0]["text"] if ps else "") or "").split()[:8])))
    name = payload.get("code") or "this code"
    return {"definition": f"Offline demo: passages about {name}, as in its examples.",
            "definition_quote": {"passage": ex[0], "quote": ex[1]},
            "when_to_use": f"Offline demo: when a passage speaks of {name}.",
            "when_to_use_quote": {"passage": ex[0], "quote": ex[1]},
            "when_not_to_use": "Offline demo: not read.", "note": "Offline demo: no AI read the passages."}


def prompt_size(k: int, max_chars: int) -> int:
    """The longest prompt of a draft, in characters (home.prompt_tokens)."""
    return 1200 + MAX_CHARS
