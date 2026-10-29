"""Follow references within a document (F5).

Two outcomes, built on the chat model already in use (a trained coreference model would bring PyTorch and a large
download, against the light core):

1. Inside the check (check-v4). Each grade may carry `refers_to`: the named form its quote depends on ("it" = "the
   planned electrolyser plant"), quoted from the excerpt or from the text just before it, which the check now shows
   as context. Both quotes are checked. A quote that opens with a pronoun but has no `refers_to` is flagged for a
   person to look at (`reference_missing`).
2. Reference chains on demand (`resolve` tasks, prompt resolve-v1): for one document, or for the passages where one
   name occurs, the model reads windows of up to three passages and returns chains of mentions. Each mention is a
   short span with the mention inside it, both checked and placed by offset. Windows overlap by one passage; chains
   of neighbouring windows are joined when they share a mention or a named form.

A chat model misses some mentions a trained coreference model would find. Every mention it does report is checked
against the text, so its precision can be measured; chains are a reading aid, not counts used in profiles (a
concept card can add them on request).
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Callable

from .store import Workspace, now
from .textutil import fast_normalise, find_quote

WINDOW = 3
CONTEXT_CHARS = 300
PRONOUN = re.compile(r"^\W*(it|its|it's|this|that|these|those|they|them|their|theirs|he|she|his|her|hers|such|"
                     r"the latter|the former|both|either|neither|there|here)\b", re.I)


def opens_with_pronoun(quote: str | None) -> bool:
    return bool(quote) and bool(PRONOUN.match(quote))


def context_before(ws: Workspace, passage_id: str, chars: int = CONTEXT_CHARS) -> tuple[str, int | None]:
    """The end of the passage before this one in its document (cut at a word start), and its document offset."""
    r = ws.query("SELECT q.text, q.start FROM passages p JOIN passages q ON q.doc_id=p.doc_id AND q.seq=p.seq - 1 "
                 "WHERE p.passage_id=?", (passage_id,))
    if not r or not r[0]["text"]:
        return "", None
    text, start = r[0]["text"], r[0]["start"]
    if len(text) <= chars:
        return text, start
    cut = len(text) - chars
    m = re.search(r"\s", text[cut:])
    cut = cut + (m.end() if m else 0)
    return text[cut:], (start + cut) if start is not None else None


def locate_reference(passage: dict, refers_to: str) -> tuple[str, int, int, str] | None:
    """(the text, start, end, where) of a `refers_to` in the excerpt or in the context before it; offsets are
    local to that text. None when it is in neither."""
    hit = find_quote(passage.get("text") or "", refers_to)
    if hit:
        return passage["text"][hit[0]:hit[1]], hit[0], hit[1], "excerpt"
    ctx = passage.get("context") or ""
    hit = find_quote(ctx, refers_to) if ctx else None
    if hit:
        return ctx[hit[0]:hit[1]], hit[0], hit[1], "before"
    return None


# ---------------------------------------------------------------------------------------------
# reference chains
# ---------------------------------------------------------------------------------------------
def _body(ws: Workspace, doc_id: str) -> list[dict]:
    return [dict(r) for r in ws.query("SELECT passage_id, seq, page, start, text FROM passages WHERE doc_id=? AND "
                                      "section='body' ORDER BY seq", (doc_id,))]


def windows(ws: Workspace, doc_id: str, name: str | None = None) -> list[list[dict]]:
    """Windows of up to WINDOW passages, overlapping by one. With `name`, only the windows that hold a passage
    mentioning it (by its words, as the search finds them)."""
    ps = _body(ws, doc_id)
    if not ps:
        return []
    step = max(1, WINDOW - 1)
    out = [ps[i:i + WINDOW] for i in range(0, max(1, len(ps) - 1), step)]
    out = [w for w in out if w]
    if name:
        from .textutil import tokens

        want = set(tokens(name))
        if not want:
            raise ValueError("Give a name with at least one word that is not a stop word.")
        keep = {p["passage_id"] for p in ps if want <= set(tokens(p["text"]))}
        out = [w for w in out if any(p["passage_id"] in keep for p in w)]
    return out


def make_tasks(ws: Workspace, doc_id: str, model: str, name: str | None = None) -> list[str]:
    from .tasks import _insert_task

    d = ws.query("SELECT title FROM documents WHERE doc_id=?", (doc_id,))
    if not d:
        raise KeyError(doc_id)
    ids = []
    with ws.connect() as cx:
        for w in windows(ws, doc_id, name):
            tid = f"resolve:{doc_id}:{w[0]['seq']:05d}"
            payload = {"doc_id": doc_id, "title": d[0]["title"] or "", "first_seq": w[0]["seq"], "name": name,
                       "passages": [{"n": i, "passage_id": p["passage_id"], "page": p["page"], "text": p["text"]}
                                    for i, p in enumerate(w, 1)]}
            _insert_task(cx, tid, "resolve", model, payload)
            ids.append(tid)
    return ids


def store_resolve(cx, t, payload: dict, obj: dict, model: str) -> tuple[bool, list[str]]:
    """The handler of a `resolve` answer: every span must be found in its passage and the mention inside its span."""
    from .schema import ResolveOut

    out = ResolveOut.model_validate(obj)
    errors: list[str] = []
    rows = []
    starts = {}
    for p in payload["passages"]:
        r = cx.execute("SELECT start FROM passages WHERE passage_id=?", (p["passage_id"],)).fetchone()
        starts[p["n"]] = r["start"] if r else None
    for ci, ch in enumerate(out.chains):
        placed = []
        for mi, m in enumerate(ch.mentions):
            if m.passage > len(payload["passages"]):
                errors.append(f"chains[{ci}].mentions[{mi}]: there is no passage P{m.passage}")
                continue
            p = payload["passages"][m.passage - 1]
            hit = find_quote(p["text"], m.span)
            if not hit:
                errors.append(f"chains[{ci}].mentions[{mi}]: span not found in passage P{m.passage}: {m.span[:80]!r}")
                continue
            span = p["text"][hit[0]:hit[1]]
            inner = find_quote(span, m.mention) if len(m.mention.strip()) >= 3 else _short_in(span, m.mention)
            if not inner:
                errors.append(f"chains[{ci}].mentions[{mi}]: the mention {m.mention!r} is not inside its span")
                continue
            base = starts[m.passage]
            if base is None:
                continue
            a = base + hit[0] + inner[0]
            b = base + hit[0] + inner[1]
            placed.append((a, b, span[inner[0]:inner[1]], int(bool(m.named)), p["passage_id"]))
        if len(placed) >= 2:
            for a, b, text, named, pid in placed:
                rows.append((payload["doc_id"], None, a, b, text, named, "model", model, pid, f"{t['task_id']}#{ci}"))
    if errors:
        return False, errors
    head = t["task_id"] + "#"
    cx.execute("DELETE FROM mentions WHERE doc_id=? AND substr(window, 1, ?) = ?", (payload["doc_id"], len(head), head))
    cx.executemany("INSERT OR REPLACE INTO mentions VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    _join(cx, payload["doc_id"])
    return True, []


def _short_in(span: str, mention: str) -> tuple[int, int] | None:
    """A mention of one or two letters ("it" is three; "he", "we"): as a whole word inside the span."""
    m = re.search(r"(?<![^\W_])" + re.escape(mention.strip()) + r"(?![^\W_])", span, re.I)
    return (m.start(), m.end()) if m and mention.strip() else None


def _join(cx, doc_id: str) -> None:
    """Number the chains of a document: windows' chains that share a mention (the same offsets) or a named form (the
    same words) are one chain."""
    rows = cx.execute("SELECT rowid, start, end, text, is_named, window FROM mentions WHERE doc_id=?", (doc_id,)).fetchall()
    parent: dict[str, str] = {}

    def find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_span: dict[tuple, str] = {}
    by_name: dict[str, str] = {}
    for r in rows:
        w = r["window"]
        parent.setdefault(w, w)
        key = (r["start"], r["end"])
        if key in by_span:
            union(by_span[key], w)
        else:
            by_span[key] = w
        if r["is_named"]:
            nk = fast_normalise(r["text"])
            if len(nk) >= 3:
                if nk in by_name:
                    union(by_name[nk], w)
                else:
                    by_name[nk] = w
    roots = sorted({find(w) for w in parent}, key=lambda w: min(r["start"] for r in rows if find(r["window"]) == w))
    number = {w: i for i, w in enumerate(roots, 1)}
    for r in rows:
        cx.execute("UPDATE mentions SET chain_id=? WHERE rowid=?", (number[find(r["window"])], r["rowid"]))


def resolve_document(ws: Workspace, doc_id: str, backend, model: str, name: str | None = None,
                     progress: Callable | None = None, should_stop: Callable[[], bool] | None = None) -> dict:
    """Read a document (or the passages where one name occurs) window by window. Resumes after a stop."""
    from . import runs, tasks

    ids = make_tasks(ws, doc_id, model, name)
    todo = [t for t in ids if ws.scalar("SELECT status FROM tasks WHERE task_id=?", (t,)) != "done"]
    rid = runs.start(ws, "resolve", doc_id, backend, model, len(todo))
    done = failed = 0
    for i, tid in enumerate(todo, 1):
        if should_stop and should_stop():
            break
        if progress:
            progress(i, len(todo))
        if ws.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) == "failed":
            with ws.connect() as cx:
                cx.execute("UPDATE tasks SET status='pending', attempts=0 WHERE task_id=?", (tid,))
        ok, _e = tasks.run_one(ws, tid, backend, model)
        done += ok
        failed += not ok
    runs.finish(ws, rid, done + failed)
    return {"doc_id": doc_id, "windows": len(ids), "read": done, "failed": failed,
            "already_read": len(ids) - len(todo), "chains": len(chains(ws, doc_id))}


def chains(ws: Workspace, doc_id: str) -> list[dict]:
    """The document's chains: a name (its most frequent named mention, the longest on a tie) and every mention."""
    from .claimcheck import locate

    rows = ws.query("SELECT DISTINCT chain_id, start, end, text, is_named, passage_id FROM mentions WHERE doc_id=? "
                    "AND chain_id IS NOT NULL ORDER BY chain_id, start", (doc_id,))
    by: dict[int, list[dict]] = defaultdict(list)
    seen = set()
    for r in rows:
        key = (r["chain_id"], r["start"], r["end"])
        if key in seen:
            continue
        seen.add(key)
        by[r["chain_id"]].append(dict(r))
    where = locate(ws, [((m["start"], m["end"]), m["passage_id"], m["start"]) for ms in by.values() for m in ms])
    out = []
    for cid, ms in by.items():
        named = Counter(m["text"] for m in ms if m["is_named"])
        name = max(named, key=lambda x: (named[x], len(x))) if named else ms[0]["text"]
        for m in ms:
            m["location"] = (where.get((m["start"], m["end"])) or {}).get("location") or ""
            m["is_named"] = bool(m["is_named"])
        out.append({"chain_id": cid, "name": name, "mentions": ms, "size": len(ms),
                    "unnamed": sum(1 for m in ms if not m["is_named"])})
    out.sort(key=lambda c: (-c["size"], c["chain_id"]))
    return out


def chain_at(ws: Workspace, doc_id: str, start: int, end: int) -> dict | None:
    """The chain with a mention overlapping a selection (document offsets): "every later mention of this name"."""
    for ch in chains(ws, doc_id):
        if any(m["start"] < end and start < m["end"] for m in ch["mentions"]):
            return ch
    return None


def status(ws: Workspace, doc_id: str) -> dict:
    head = f"resolve:{doc_id}:"
    st = {r[0]: r[1] for r in ws.query("SELECT status, COUNT(*) FROM tasks WHERE kind='resolve' AND substr(task_id, 1, ?) "
                                       "= ? GROUP BY status", (len(head), head))}
    return {"windows_read": st.get("done", 0), "windows_failed": st.get("failed", 0),
            "windows_waiting": sum(v for k, v in st.items() if k not in ("done", "failed")),
            "windows_total": len(windows(ws, doc_id)),
            "chains": int(ws.scalar("SELECT COUNT(DISTINCT chain_id) FROM mentions WHERE doc_id=?", (doc_id,)) or 0)}


def concept_reference_counts(ws: Workspace, labels: list[str]) -> dict[str, int]:
    """Per document, the mentions without a name (pronouns, short descriptions) in chains named by one of these
    wordings: what a concept count can add when references are included."""
    want = {fast_normalise(x) for x in labels if x}
    out: dict[str, int] = Counter()
    docs = [r[0] for r in ws.query("SELECT DISTINCT doc_id FROM mentions")]
    for d in docs:
        for ch in chains(ws, d):
            named = {fast_normalise(m["text"]) for m in ch["mentions"] if m["is_named"]} | {fast_normalise(ch["name"])}
            if any(w in n or n in w for w in want for n in named if len(n) >= 3):
                out[d] += ch["unnamed"]
    return dict(out)


def references_table(ws: Workspace, doc_id: str | None = None) -> list[dict]:
    rows = []
    docs = [doc_id] if doc_id else [r[0] for r in ws.query("SELECT DISTINCT doc_id FROM mentions")]
    titles = {r["doc_id"]: r["title"] or "" for r in ws.query("SELECT doc_id, title FROM documents")}
    for d in docs:
        for ch in chains(ws, d):
            for m in ch["mentions"]:
                rows.append({"Document": titles.get(d, d), "Chain": ch["chain_id"], "Name": ch["name"],
                             "Mention": m["text"], "Named": "yes" if m["is_named"] else "no", "Where": m["location"]})
    return rows


def pronoun_grades(ws: Workspace) -> list[dict]:
    """Grades of hypothesis checks whose quote opens with a pronoun, with their refers_to (for the F5 measure)."""
    out = []
    for r in ws.query("SELECT subject_id, passage_id, quote, refers_to, refers_where FROM verifications WHERE "
                      "subject_kind='user_claim' AND quote IS NOT NULL"):
        if opens_with_pronoun(r["quote"]):
            out.append(dict(r))
    return out


def _payload_json(t) -> dict:
    return json.loads(t["payload_json"])


def stamp() -> str:
    return now()
