"""Read with the new reader (0.15, roadmap A0): a document of a project read again by the current reader, with every
result in it moved to the same words in the new text.

Documents already in a project are never read again by themselves: every result points into a document's text by
passage id (`<doc_id>:<seq>`) and by character offsets, and a new reader gives other text and other passages. A person
asks for it, one document at a time:

- `check(ws, doc_id)`: whether it can be done now: the document was read by an older reader, its original file is there
  and unchanged, and none of its tasks waits for Claude Code or is being answered by it;
- `preview(ws, doc_id)`: the file read again (nothing is stored) and where every result would go;
- `move(ws, doc_id)`: done, in one transaction (on any error nothing changes); returns the same report.

How results move:

1. Alignment (`_Map`). Each sentence of the old text (a sentence not found whole: each run of a few words of it) is
   found in the new text as `textutil.find_quote` finds quotes (case, typography and spacing aside), and failing that
   with hyphens ignored like spaces (reader 1 wrote "longterm" where reader 2 keeps "long-term"). A piece found once
   ties its old offsets to new ones; a piece found in several places is tied to the one nearest where its neighbours
   say it is, when that one is clearly the nearest.
2. A result with a quote is moved by finding its quote again, the place nearest where it is expected, and only among
   the places near where its old passage's text now is: a quote whose words are gone from there is not placed
   somewhere else that happens to say the same. Its passage is the new passage holding the quote's start, its page
   the page there. A result without a quote goes with its passage: to the new passage most of the old passage's text
   is in. An old and a new passage are "one to one" when most of the old passage is in the new one and the new one
   holds little else.
3. Ids made from passage ids are made again for the new passage, and whatever names them follows: labels (and the
   reviews of them), a check's grades (`verifications.ver_id`), second opinions, judgements, task ids
   (`label:<framework>:<passage>`, `extract:<passage>`, `reread:<check>:<passage>:<n>`, `verify:<claim>:<passage>`),
   the SDG pack's claims and interactions. New passage ids have the old form (`doc:0005`), so an old id left behind
   would name other text: every reference to an old passage of the document is moved or turned into a tombstone,
   `<doc_id>:r<reader>-<seq>` ("passage 5 of reader 1's reading"), which names no passage and never will.
4. A check keeps the excerpt it showed (the text in its task's payload) as its record: only its pointers into the
   document move. Each excerpt so kept says which reader's text it is (`reader`) and keeps where its paragraphs began
   (`breaks`) and where its quotes were in it (`quotes_at`), so the result page shows the same words with the
   highlight inside them (claimcheck.result). An excerpt whose quote (the AI's, or the person's judgement in force)
   cannot be placed points nowhere: its passage id becomes a tombstone and its offsets NULL, and the result page
   shows it as it shows an excerpt of a removed document. Two excerpts of one check that now fall in one passage
   cannot both have it: the second points nowhere.
5. What is derived is made again: keyword labels (deleted; the keyword pass for the document remakes them, as after
   adding documents; a keyword label a person reviewed is moved with its passage instead), the term index
   (`term_mentions` of the document; the corpus version changes so it is rebuilt), the document's embeddings (made
   again on demand), reference chains (`mentions`, and the `resolve` tasks and answers they came from, so the next
   request reads the new windows) and inferred interactions (made again by the SDG pack's analysis).
6. Tasks: one not answered yet whose id names an old passage is dropped (it is asked again for the new passages). An
   answered one is a record: when its passage maps one to one it takes the new passage's id (the new passage counts
   as read: no model reads it again); otherwise its passage part becomes a tombstone, it is marked done and is never
   asked again. A task whose payload names old passages (a check's round, a theme's name, a link, an add-on's task)
   keeps its id; the passage ids in its payload are moved (a check's: with its excerpts) or made tombstones.
7. A theme run keeps a passage where it maps one to one; other passages of the document leave the run. A run that was
   up to date stays so only when every body passage of the document maps one to one; otherwise it is out of date
   (`theme_runs.corpus_version`), as after adding a document.
8. The ledger of what was sent to Claude (`ai_sent`) is history: its rows stay, each naming the new passage where the
   old one maps one to one, otherwise a tombstone. The share of the document Claude has read counts passages that
   exist, so the share read in passages that have no place now is kept with the document (`documents.sent_share`)
   and added to it: a cap on what Claude may read of it is not loosened by reading it again.
9. Add-on tables are left alone; the report names those with rows about the document.
10. Where results are now: a result placed in text the new reader leaves out of searches (author and article details,
   end notes, a table, a running head...) is kept as it is, and a check's judgement counts as before (a check keeps its
   record): the report lists it (`left_out`) with the kind of text in words (reader.KIND_TEXT). A result with no place
   says where its words went when that can be told (three of its words in a row in a block left out, near where its
   passage now is).

A stored answer of a task kept this way reads quotes in the excerpt it showed; `tasks.doc_span` places them in the
document as it reads now (a stronger model reading a round again, an excerpt read again, a second opinion).
"""
from __future__ import annotations

import bisect
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import __version__, ingest
from .store import Workspace, now
from .textutil import _normalise_spans, _word_edge, normalise, split_sentences

# what each kind of result is, for the person (the report's `kind_text`)
KIND_TEXT = {
    "check": "an excerpt a check read",
    "judgement": "a person's own judgement of an excerpt",
    "second_opinion": "a second model's judgement of an excerpt",
    "sdg_check": "an SDG pack check of a claim against an excerpt",
    "label": "a code label",
    "claim": "a claim the SDG pack read from the text",
    "theme_member": "a passage in a theme run",
}
WHY = {
    "gone": "Its words are not in the new reading where they were.",
    "lost": "Its passage could not be found in the new reading.",
    "shared": "It now falls in the same passage as another excerpt of the same check, and one passage holds one "
              "excerpt of a check.",
    "shared_label": "Its passage now holds the same label already.",
}
# a moved result in text the new reader leaves out of searches (front matter, a table, page furniture...): whose words,
# and what happens to it
LEFT_OUT_NOTE = {
    "check": ("This excerpt's", "the check keeps it, and its judgement counts as before."),
    "sdg_check": ("This excerpt's", "the check keeps it, and its judgement counts as before."),
    "label": ("This label's", "the label is kept."),
    "claim": ("This claim's", "the claim is kept."),
}
SLACK = 400              # characters around where an old passage's text is now, in which its quotes are looked for
_KEYWORD_SOURCES = ("keywords", "meaning", "both")
_PK = {"tasks": ("task_id",), "results": ("task_id",), "labels": ("label_id",), "verifications": ("ver_id",),
       "judgements": ("passage_id",), "second_opinions": ("passage_id",), "theme_members": ("passage_id",),
       "claims": ("claim_id",), "claim_targets": ("claim_id",), "interactions": ("inter_id",)}
_READINGS: dict[tuple, Any] = {}   # the last readings of files (preview, then move, read a file once)


# ------------------------------------------------------------------------------------------------------------------
# ids
# ------------------------------------------------------------------------------------------------------------------
_TOMB = re.compile(r":r\d+-\d+$")


def tombstone(passage_id: str, reader: int) -> str:
    """The id that stands for an old passage after its document was read again: "d1:0005" read by reader 1 becomes
    "d1:r1-0005". It names no passage (a passage id ends in digits after the colon) and never will."""
    doc, _, seq = passage_id.rpartition(":")
    return f"{doc}:r{reader}-{seq}"


def is_tombstone(passage_id: str | None) -> bool:
    return bool(passage_id) and bool(_TOMB.search(passage_id))


def _pid_re(doc_id: str) -> re.Pattern:
    """The passage ids of a document inside a longer id ("label:sdg:d1:0005", "reread:u1:d1:0005:2")."""
    return re.compile(r"(?<![\w-])" + re.escape(doc_id) + r":\d{4,}(?![\w-])")


def _h(*parts: str) -> str:
    from .tasks import _h as th

    return th(*parts)


# ------------------------------------------------------------------------------------------------------------------
# finding words again
# ------------------------------------------------------------------------------------------------------------------
_WORD = re.compile(r"[^\W_]+")


def _packed(s: str) -> str:
    """Normalised text with spaces, hyphens and cell bars left out: what must be equal for a quote to be the same
    words."""
    return normalise(s).replace(" ", "").replace("-", "").replace("|", "")


class _Finder:
    """Every place a quote is in one text, as `find_quote` finds it (exact after normalisation, then with spaces
    ignored where the text has more), and failing both with hyphens and table cell bars ignored like spaces (reader 1
    wrote "longterm" for "long-term", and a table's cells without the " | " reader 2 puts between them). The text
    is normalised once, so thousands of searches are quick."""

    def __init__(self, text: str):
        self.text = text
        self.nh, self.hs, self.he = _normalise_spans(text)
        self._packs: dict[str, tuple] = {}
        self._cache: dict[str, list[tuple[int, int]]] = {}

    def _pack(self, drop: str) -> tuple:
        got = self._packs.get(drop)
        if got is None:
            chars, starts, ends, gap = [], [], [], []
            prev = False
            for c, a, b in zip(self.nh, self.hs, self.he):
                if c in drop:
                    prev = True
                    continue
                chars.append(c)
                starts.append(a)
                ends.append(b)
                gap.append(prev)
                prev = False
            got = self._packs[drop] = ("".join(chars), starts, ends, gap)
        return got

    def all(self, quote: str) -> list[tuple[int, int]]:
        q = (quote or "").strip()
        if q in self._cache:
            return self._cache[q]
        out: list[tuple[int, int]] = []
        nq = _normalise_spans(q)[0]
        if len(nq) >= 3:
            pos = self.nh.find(nq)
            while pos >= 0:
                end = pos + len(nq)
                if _word_edge(self.text, self.nh, self.hs, pos, True) and _word_edge(self.text, self.nh, self.hs, end):
                    out.append((self.hs[pos], self.he[end - 1]))
                pos = self.nh.find(nq, pos + 1)
            for drop in (" ", " -|"):  # last: hyphens and the cell bars of a table (reader 2) as spaces
                if out:
                    break
                out = self._loose(nq, drop)
        self._cache[q] = out
        return out

    def _loose(self, nq: str, drop: str) -> list[tuple[int, int]]:
        sh, starts, ends, gap = self._pack(drop)
        qc, qgap, prev = [], [], False
        for c in nq:
            if c in drop:
                prev = True
                continue
            qc.append(c)
            qgap.append(prev)
            prev = False
        sq = "".join(qc)
        if len(sq) < 3:
            return []

        def edge(i: int, start: bool = False) -> bool:
            return i <= 0 or i >= len(sh) or gap[i] or _word_edge(self.text, sh, starts, i, start)

        out = []
        pos = sh.find(sq)
        while pos >= 0:
            end = pos + len(sq)
            # a space (or hyphen) the quote puts between two words must be a word edge in the text too
            if edge(pos, True) and edge(end) and all(edge(pos + k) for k in range(1, len(sq)) if qgap[k]):
                out.append((starts[pos], ends[end - 1]))
            pos = sh.find(sq, pos + 1)
        return out


def _worth(s: str) -> bool:
    """A piece long enough to be found in one place only: three words and twenty characters at least."""
    return len(_WORD.findall(s)) >= 3 and len(normalise(s)) >= 20


def _chunks(text: str, a: int, b: int, n: int = 6) -> list[tuple[int, int]]:
    """Runs of `n` words of text[a:b] (the last one joined to the one before when it is short)."""
    toks = [(m.start() + a, m.end() + a) for m in re.finditer(r"\S+", text[a:b])]
    out = []
    for i in range(0, len(toks), n):
        grp = toks[i:i + n]
        if out and len(grp) < 3:
            out[-1] = (out[-1][0], grp[-1][1])
        else:
            out.append((grp[0][0], grp[-1][1]))
    return out


class _P:
    """A passage, old or new."""

    __slots__ = ("pid", "seq", "start", "end", "text", "section", "page")

    def __init__(self, pid, seq, start, end, text, section, page):
        self.pid, self.seq, self.start, self.end, self.text, self.section, self.page = (
            pid, seq, start, end, text, section, page)


class _Map:
    """Where the old text is in the new text: anchors (old span, new span, old passage), the old passages' new places,
    and quotes found again."""

    def __init__(self, old_text: str, old: list[_P], new_text: str, new: list[_P], new_spans: list, paginated: bool):
        self.t1, self.t2 = old_text, new_text
        self.old = sorted(old, key=lambda p: p.start)
        self.new = sorted(new, key=lambda p: p.start)
        self.by_old = {p.pid: p for p in self.old}
        self.by_new = {p.pid: p for p in self.new}
        self.old_starts = [p.start for p in self.old]
        self.new_starts = [p.start for p in self.new]
        self.spans, self.ends, self.paginated = new_spans, [e + 2 for _s, e in new_spans], paginated
        self.f = _Finder(new_text)
        self.anchors: list[tuple[int, int, int, int, str]] = []
        self._align()
        self._passages()

    # --- alignment ---------------------------------------------------------------------------------------------
    def _align(self) -> None:
        unique: list[tuple] = []
        ambiguous: list[tuple] = []

        def look(a: int, b: int, pid: str) -> bool:
            s = self.t1[a:b]
            if not _worth(s):
                return True  # too short to say: not looked for, and not cut up either
            c = self.f.all(s)
            if len(c) == 1:
                unique.append((a, b, c[0][0], c[0][1], pid))
            elif c:
                ambiguous.append((a, b, c, pid))
            return bool(c)

        for p in self.old:
            for a, b in split_sentences(self.t1[p.start:p.end], offset=p.start):
                if not look(a, b, p.pid) and b - a > 40:
                    for ca, cb in _chunks(self.t1, a, b):
                        look(ca, cb, p.pid)
        unique.sort()
        self.anchors = unique
        self._index()
        # a piece found in several places: the one nearest where the pieces around it say, when clearly nearest
        extra = []
        for a, b, cands, pid in ambiguous:
            exp = self.expect(a)
            ds = sorted((abs(c[0] - exp), c) for c in cands)
            if ds[0][0] <= max(1500, 3 * (b - a)) and (len(ds) == 1 or ds[0][0] * 2 < ds[1][0]):
                extra.append((a, b, ds[0][1][0], ds[0][1][1], pid))
        if extra:
            self.anchors = sorted(unique + extra)
            self._index()

    def _index(self) -> None:
        self.a_old = [x[0] for x in self.anchors]
        self.regions: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for _a, _b, na, nb, pid in self.anchors:
            self.regions[pid].append((na, nb))

    def expect(self, pos: int) -> int:
        """Where an old offset is expected in the new text: from the anchors around it (within 3,000 characters),
        else at the same share of the text."""
        i = bisect.bisect_right(self.a_old, pos) - 1
        best = None
        if i >= 0:
            a, b, na, nb, _p = self.anchors[i]
            if pos < b:
                return na + min(pos - a, nb - na)
            best = (pos - b, nb + (pos - b))
        if i + 1 < len(self.anchors):
            a, b, na, nb, _p = self.anchors[i + 1]
            if best is None or a - pos < best[0]:
                best = (a - pos, na - (a - pos))
        if best is not None and best[0] <= 3000:
            return max(0, best[1])
        return int(pos * len(self.t2) / max(1, len(self.t1)))

    # --- passages ----------------------------------------------------------------------------------------------
    def _passages(self) -> None:
        ov: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.found: dict[str, int] = defaultdict(int)
        for a, b, na, nb, pid in self.anchors:
            self.found[pid] += b - a
            j = max(0, bisect.bisect_right(self.new_starts, na) - 1)
            while j < len(self.new) and self.new[j].start < nb:
                q = self.new[j]
                o = min(nb, q.end) - max(na, q.start)
                if o > 0:
                    ov[pid][q.pid] += o
                j += 1
        src: dict[str, dict[str, int]] = defaultdict(dict)
        for pid, qs in ov.items():
            for q, n in qs.items():
                src[q][pid] = n
        self.main: dict[str, str] = {}
        self.one: dict[str, str] = {}
        for p in self.old:
            qs = ov.get(p.pid)
            if not qs:
                continue
            q, n = max(qs.items(), key=lambda x: (x[1], x[0]))
            total = sum(qs.values())
            if self.found[p.pid] >= 0.4 * max(1, len(p.text)):
                self.main[p.pid] = q
            new = self.by_new[q]
            if (n >= 0.8 * total and self.found[p.pid] >= 0.6 * max(1, len(p.text))
                    and n >= 0.8 * sum(src[q].values()) and n >= 0.6 * max(1, len(new.text))):
                self.one[p.pid] = q
        self.ov = ov

    def passage_at(self, pos: int) -> _P:
        """The new passage holding a new offset (in a gap between passages: the nearest)."""
        i = bisect.bisect_right(self.new_starts, pos) - 1
        if i >= 0 and pos < self.new[i].end:
            return self.new[i]
        cands = [self.new[k] for k in (i, i + 1) if 0 <= k < len(self.new)]
        return min(cands, key=lambda q: min(abs(pos - q.start), abs(pos - q.end)))

    def old_at(self, pos: int | None) -> _P | None:
        if pos is None:
            return None
        i = bisect.bisect_right(self.old_starts, pos) - 1
        return self.old[i] if i >= 0 and pos < self.old[i].end + 2 else None

    def page_at(self, pos: int) -> int | None:
        return ingest.page_of(pos, self.spans, self.ends) if self.paginated and self.spans else None

    # --- what the new reader leaves out ------------------------------------------------------------------------
    def set_blocks(self, blocks: list[tuple[int, int, str, bool]]) -> None:
        """The new reading's blocks: (start, end, kind, whether features read it, after a person's corrections)."""
        self.blocks = sorted(blocks)
        self.b_starts = [b[0] for b in self.blocks]

    def left_out(self, pos: int) -> str | None:
        """The kind (reader.KINDS) of the block left out of searches that holds a new offset, or None."""
        i = bisect.bisect_right(getattr(self, "b_starts", []), pos) - 1
        if i >= 0 and pos < self.blocks[i][1] and not self.blocks[i][3]:
            return self.blocks[i][2]
        return None

    def left_out_passage(self, pid: str) -> str | None:
        """The kind of the blocks of a new passage when none of them is read by features (most of its text), else
        None."""
        q = self.by_new.get(pid)
        if q is None or not getattr(self, "blocks", None):
            return None
        mine = [(min(q.end, b[1]) - max(q.start, b[0]), b[2], b[3]) for b in self.blocks
                if b[0] < q.end and b[1] > q.start]
        if not mine or any(inc for _n, _k, inc in mine):
            return None
        return max(mine)[1]

    def words_left_out(self, quote: str | None, old_start: int | None, pid: str | None) -> str | None:
        """Where a quote that could not be placed went, when that can be told: the kind of a block left out of
        searches, near where its old passage now is, that holds three of its words in a row. Else None."""
        p = self.by_old.get(pid) if pid else None
        if not quote or p is None or not self.regions.get(p.pid) or not getattr(self, "blocks", None):
            return None
        words = _WORD.findall(normalise(quote))
        runs = {"".join(words[i:i + 3]) for i in range(len(words) - 2)}
        runs = {r for r in runs if len(r) >= 10}
        if not runs:
            return None
        exp = self.expect(old_start if old_start is not None else p.start)
        reach = SLACK + len(quote)
        for a, b, kind, inc in self.blocks:
            if inc or b < exp - reach or a > exp + reach:
                continue
            text = "".join(_WORD.findall(normalise(self.t2[a:b])))
            if any(r in text for r in runs):
                return kind
        return None

    # --- quotes ------------------------------------------------------------------------------------------------
    def place(self, quote: str | None, old_start: int | None, pid: str | None) -> tuple[int, int] | None:
        """Where a quote of the old passage `pid` (at `old_start` in the old text) is in the new text, or None."""
        if not quote or len(normalise(quote)) < 3:
            return None
        p = self.by_old.get(pid) if pid else self.old_at(old_start)
        if old_start is None:
            old_start = p.start if p is not None else 0
        cands = self.f.all(quote)
        if not cands:
            return None
        reg = self.regions.get(p.pid) if p is not None else None
        slack = SLACK + len(quote)
        exp = self.expect(old_start)
        if reg:
            cands = [c for c in cands if any(lo - slack <= c[0] <= hi + slack for lo, hi in reg)]
        elif len(cands) > 1:
            return None  # its passage is not in the new text, and the words are in several places: which one?
        else:  # its passage is not in the new text: the words only where they are expected, not elsewhere
            cands = [c for c in cands if abs(c[0] - exp) <= slack + (len(p.text) if p is not None else 0)]
        if not cands:
            return None
        best = min(cands, key=lambda c: (abs(c[0] - exp), c[0]))
        return best if _packed(self.t2[best[0]:best[1]]) == _packed(quote) else None


def find_near(cx, doc_id: str, text: str, a: int, b: int, start: int, end: int,
              anchor: list | None = None) -> tuple[int, int] | None:
    """Where characters a..b of an excerpt kept from an earlier reading (`text`, the check's record) are in its
    document now, or None. The excerpt's pointer is the passage at start..end; with `anchor` ([offset in the excerpt,
    offset in the document], written when the excerpt was moved) the place is expected exactly there, else near that
    passage. Only places within the reach of the whole excerpt are taken, the nearest to the one expected. Used to
    place a quote a model or a person gives in such an excerpt (tasks.doc_span, claimcheck.set_judgement)."""
    quote = text[a:b]
    if not quote.strip():
        return None
    row = cx.execute("SELECT text FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if row is None or row[0] is None:
        return None
    doc = row[0]
    if anchor and len(anchor) == 2 and all(isinstance(x, int) for x in anchor):
        exp = anchor[1] + (a - anchor[0])
        lo, hi = exp - a - SLACK, exp + (len(text) - a) + SLACK
    else:
        exp = start + a
        lo, hi = start - len(text) - SLACK, end + len(text) + SLACK
    lo, hi = max(0, lo), min(len(doc), hi)
    cands = [(x + lo, y + lo) for x, y in _Finder(doc[lo:hi]).all(quote)]
    cands = [c for c in cands if _packed(doc[c[0]:c[1]]) == _packed(quote)]
    if not cands:
        return None
    return min(cands, key=lambda c: (abs(c[0] - exp), c[0]))


# ------------------------------------------------------------------------------------------------------------------
# can it be done now
# ------------------------------------------------------------------------------------------------------------------
def check(ws: Workspace, doc_id: str) -> dict:
    """Whether the document can be read with the new reader now, in words for a researcher:
    {"ok": bool, "reason": str | None, "reader": n (the one that read it), "new_reader": ingest.READER}."""
    return _public(_check(ws, ws._conn(), doc_id))


def _old_pids(cx, doc_id: str) -> list[str]:
    return [r[0] for r in cx.execute("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq", (doc_id,))]


def _doc_tasks(cx, doc_id: str, old: set[str]) -> list[dict]:
    """The tasks about this document: their id names one of its passages (or it is one of its reference windows), or
    their payload names its passages."""
    from .access import ids_in

    rx = _pid_re(doc_id)
    out = []
    for r in cx.execute("SELECT rowid AS rid, * FROM tasks WHERE instr(task_id, ?) > 0 OR instr(payload_json, ?) > 0",
                        (doc_id, doc_id)).fetchall():
        t = dict(r)
        try:
            t["payload"] = json.loads(t["payload_json"] or "{}")
        except ValueError:
            t["payload"] = {}
        t["id_pids"] = [m.group(0) for m in rx.finditer(t["task_id"]) if m.group(0) in old]
        t["pay_pids"] = ids_in(t["payload"])[0] & old
        t["resolve"] = t["kind"] == "resolve" and t["task_id"].startswith(f"resolve:{doc_id}:")
        if t["id_pids"] or t["pay_pids"] or t["resolve"]:
            out.append(t)
    return out


def _busy(cx, tasks: list[dict]) -> str | None:
    from .taskqueue import _cutoff

    ids = {t["task_id"] for t in tasks}
    cutoff = _cutoff()
    out = [t for t in tasks if t.get("claimed_by") and (t.get("claimed_at") or "") >= cutoff]
    held = set()
    for (tj,) in cx.execute("SELECT task_ids_json FROM task_claims WHERE finished_at IS NULL AND expires_at > ?",
                            (now(),)).fetchall():
        try:
            held |= set(json.loads(tj or "[]")) & ids
        except ValueError:
            pass
    n_out = len({t["task_id"] for t in out} | held)
    if n_out:
        return (f"Claude Code is working on this document right now ({n_out} {'task' if n_out == 1 else 'tasks'}). "
                "Wait until it has finished, then read it with the new reader.")
    queued = [t for t in tasks if int(t.get("queued") or 0) and (t["status"] in ("pending", "retry") or (
        t["status"] == "done" and int(t.get("again") or 0)))]
    if queued:
        return (f"Some of this document's work waits for Claude Code ({len(queued)} "
                f"{'task' if len(queued) == 1 else 'tasks'}). Let Claude Code answer it, or take it out of the queue, "
                "then read the document with the new reader.")
    exported = [t for t in tasks if t["status"] == "exported"]
    if exported:
        return (f"Some of this document's tasks were handed out as files to be answered elsewhere ({len(exported)}). "
                "Bring their answers in first, then read the document with the new reader.")
    return None


def _check(ws: Workspace, cx, doc_id: str, verify_file: bool = True) -> dict:
    from .sources import original_file

    row = cx.execute("SELECT reader, sha1, path FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if row is None:
        raise KeyError(doc_id)
    reader = int(row["reader"] or 1)
    out: dict = {"ok": False, "reason": None, "reader": reader, "new_reader": ingest.READER}
    if reader >= ingest.READER:
        out["reason"] = "This document was read by the current reader already: there is nothing to do."
        return out
    f = original_file(ws, doc_id, verify=False)
    if not f["available"]:
        out["reason"] = ("No original file was recorded for this document, so it cannot be read again."
                         if not f["recorded"] else
                         f"The original file is no longer at {f['recorded']}. Put it back there to read the document "
                         "with the new reader.")
        return out
    out["path"] = f["path"]
    if verify_file:
        want = (row["sha1"] or "").split("~")[0]  # a sync-clash copy's is "<sha1>~<mark>" (sync.py)
        try:
            got = ingest._sha1(Path(f["path"]))
        except OSError as e:
            out["reason"] = f"The original file could not be read ({e})."
            return out
        if not want or got != want:
            out["reason"] = (f"The file at {f['path']} has changed since it was added, so reading it now would not "
                             "give the text your results come from. Put the file as it was back in its place.")
            return out
    busy = _busy(cx, _doc_tasks(cx, doc_id, set(_old_pids(cx, doc_id))))
    if busy:
        out["reason"] = busy
        return out
    out["ok"] = True
    return out


def _public(c: dict) -> dict:
    return {k: c[k] for k in ("ok", "reason", "reader", "new_reader")}


# ------------------------------------------------------------------------------------------------------------------
# reading the file again
# ------------------------------------------------------------------------------------------------------------------
def _read(ws: Workspace, doc_id: str, path: str, ocr=None, should_stop=None):
    """The file read by the current reader (nothing is stored). The last two readings are kept, so a preview and the
    move that follows read the file once."""
    p = Path(path)
    st = p.stat()
    cfg = ws.config["passages"]
    ocr = ocr if ocr is not None else ingest.OcrOptions()
    key = (str(p.resolve()), st.st_mtime_ns, st.st_size, ingest.READER, int(cfg["max_chars"]), int(cfg["min_chars"]),
           ocr.mode, ocr.lang)
    doc = _READINGS.get(key)
    if doc is None:
        doc = ingest.read_document(p, reader=ingest.READER, ocr=ocr, max_chars=int(cfg["max_chars"]),
                                   min_chars=int(cfg["min_chars"]), should_stop=should_stop)
        _READINGS[key] = doc
        while len(_READINGS) > 2:
            _READINGS.pop(next(iter(_READINGS)))
    return doc


# ------------------------------------------------------------------------------------------------------------------
# the plan: what moves where (reads only)
# ------------------------------------------------------------------------------------------------------------------
class _Plan:
    def __init__(self):
        self.updates: dict[str, dict[int, dict]] = defaultdict(dict)
        self.deletes: dict[str, set[int]] = defaultdict(set)
        self.counts: dict[str, dict[str, int]] = defaultdict(lambda: {"moved": 0, "not_placed": 0, "left_out": 0})
        self.not_placed: list[dict] = []
        self.left_out: list[dict] = []        # moved results whose words are in text the new reader leaves out
        self.locate: list[tuple] = []        # (entry, passage_id, offset) for "where it was"
        self.renamed: dict[str, str] = {}     # task ids
        self.dropped: dict[str, str] = {}     # task ids dropped -> the id their ledger rows take
        self.kept: list[str] = []             # the new ids of answered tasks named by a passage, kept
        self.after: list = []                 # (sql, args) run after the new reading is stored

    def upd(self, table: str, rid: int, **cols) -> None:
        self.updates[table].setdefault(rid, {}).update(cols)

    def miss(self, kind: str, what: str, quote: str | None, pid: str | None, offset: int | None, why: str,
             page: int | None = None, left_out: str | None = None) -> None:
        """A result with no place in the new reading; `left_out`: the kind of block its words went to, when known."""
        words = _kind_words(left_out)
        e = {"kind": kind, "kind_text": KIND_TEXT[kind], "what": what, "quote": _short(quote), "page": page,
             "where": None, "left_out_kind": words,
             "why": f"Its words are in the {words}, which the new reader sets aside." if words else WHY[why]}
        self.not_placed.append(e)
        if pid:
            self.locate.append((e, pid, offset))

    def moved_into(self, kind: str, left_out: str | None, what: str, quote: str | None, page: int | None) -> None:
        """A result placed in the new reading; noted when its words are in text the new reader leaves out."""
        self.counts[kind]["moved"] += 1
        if not left_out:
            return
        self.counts[kind]["left_out"] += 1
        words = _kind_words(left_out)
        whose, keeps = LEFT_OUT_NOTE[kind]
        self.left_out.append({"kind": kind, "kind_text": KIND_TEXT[kind], "what": what, "quote": _short(quote),
                              "page": page, "where": f"page {page}" if page else None, "left_out_kind": words,
                              "note": f"{whose} words are in the {words}, which the new reader leaves out of "
                                      f"searches; {keeps}"})


def _kind_words(kind: str | None) -> str | None:
    from .reader import KIND_TEXT as BLOCKS

    return BLOCKS.get(kind, kind) if kind else None


def _short(s: str | None, n: int = 140) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def _rows(cx, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in cx.execute(sql, args).fetchall()]


def _in(cx, sql: str, ids: list[str], args=()) -> list[dict]:
    """Rows of `sql` (with one `{}` for an IN list) for many ids, in chunks."""
    out = []
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        out += _rows(cx, sql.format(",".join("?" * len(chunk))), (*args, *chunk))
    return out


def _plan(ws: Workspace, cx, doc_id: str, new_doc) -> tuple[_Plan, dict]:
    from . import profile
    from .access import shares
    from .claimcheck import _breaks

    drow = dict(cx.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone())
    reader = int(drow["reader"] or 1)
    old_text = drow["text"] or ""
    old = [_P(r["passage_id"], r["seq"], r["start"], r["end"], r["text"], r["section"], r["page"])
           for r in cx.execute("SELECT * FROM passages WHERE doc_id=? ORDER BY seq", (doc_id,))]
    old_set = {p.pid for p in old}
    old_spans = [(r[0], r[1]) for r in cx.execute("SELECT start, end FROM pages WHERE doc_id=? ORDER BY page",
                                                  (doc_id,))]
    new_pids = [f"{doc_id}:{p.seq:04d}" for p in new_doc.passages]
    new = [_P(pid, p.seq, p.start, p.end, new_doc.text[p.start:p.end], p.section, p.page)
           for pid, p in zip(new_pids, new_doc.passages)]
    m = _Map(old_text, old, new_doc.text, new, new_doc.page_spans, new_doc.raw.paginated)
    from . import reader as reader2

    choices = {r[0]: r[1] for r in cx.execute("SELECT fp, included FROM block_choices WHERE doc_id=?", (doc_id,))}
    new_blocks = getattr(new_doc, "blocks", None) or []
    counts = reader2.choose_inclusion([(new_doc.text[b.start:b.end], b.kind) for b in new_blocks], choices) \
        if choices else [b.included for b in new_blocks]
    m.set_blocks([(b.start, b.end, b.kind, bool(c)) for b, c in zip(new_blocks, counts)])
    tomb = {p.pid: tombstone(p.pid, reader) for p in old}
    by_old = m.by_old
    plan = _Plan()

    def old_page(pos: int | None, pid: str | None = None) -> int | None:
        if pos is not None and old_spans:
            return ingest.page_of(pos, old_spans)
        p = by_old.get(pid) if pid else None
        return p.page if p is not None else None

    def taskmap(pid: str) -> str:
        return m.one.get(pid) or tomb[pid]

    # --- tasks ---------------------------------------------------------------------------------------------------
    tasks = _doc_tasks(cx, doc_id, old_set)
    valid = {r["task_id"] for r in _in(cx, "SELECT DISTINCT task_id FROM results WHERE valid=1 AND task_id IN ({})",
                                        [t["task_id"] for t in tasks])}
    excerpt_tasks = [t for t in tasks if not t["resolve"] and t["payload"].get("subject_kind")
                     and t["payload"].get("subject_id")
                     and ("passages" in t["payload"] or "passage_id" in t["payload"])]
    plain_tasks = [t for t in tasks if not t["resolve"] and t not in excerpt_tasks]

    def drop_task(t: dict, ledger_id: str) -> None:
        plan.deletes["tasks"].add(t["rid"])
        plan.dropped[t["task_id"]] = ledger_id
        for r in cx.execute("SELECT rowid FROM results WHERE task_id=?", (t["task_id"],)):
            plan.deletes["results"].add(r[0])

    def tomb_id(task_id: str) -> str:
        """A task id with each old passage in it a tombstone (a reference window: its seq part)."""
        if task_id.startswith(f"resolve:{doc_id}:"):
            head = f"resolve:{doc_id}:"
            return f"{head}r{reader}-{task_id[len(head):]}"
        return _pid_re(doc_id).sub(lambda mm: tomb.get(mm.group(0), mm.group(0)), task_id)

    n_chains = cx.execute("SELECT COUNT(*) FROM mentions WHERE doc_id=?", (doc_id,)).fetchone()[0]
    for t in tasks:
        if t["resolve"]:
            drop_task(t, tomb_id(t["task_id"]))

    # --- the SDG pack's claims (extract tasks) -----------------------------------------------------------------
    claim_map: dict[str, str] = {}
    claims = [c for c in _rows(cx, "SELECT rowid AS rid, * FROM claims WHERE doc_id=?", (doc_id,))
              if c["passage_id"] in old_set]
    for t in plain_tasks:
        if t["id_pids"] and t["status"] != "done" and t["task_id"] not in valid and not any(
                c["task_id"] == t["task_id"] for c in claims):
            drop_task(t, tomb_id(t["task_id"]))
            continue
        new_id = t["task_id"]
        record = False
        if t["id_pids"]:
            new_id = _pid_re(doc_id).sub(lambda mm: taskmap(mm.group(0)) if mm.group(0) in old_set else mm.group(0),
                                         t["task_id"])
            record = any(taskmap(p) == tomb[p] for p in t["id_pids"])
        pl = _map_payload(t["payload"], lambda pid: taskmap(pid) if pid in old_set else pid)
        if pl.get("passage_id") in m.by_new and t["payload"].get("passage_id") in old_set:
            pl["page"] = m.by_new[pl["passage_id"]].page
        cols: dict = {"payload_json": json.dumps(pl, ensure_ascii=False)}
        if new_id != t["task_id"]:
            cols["task_id"] = new_id
            plan.renamed[t["task_id"]] = new_id
        if record:  # a record of what was asked about a passage that has no place now: never asked again
            cols.update(status="done", again=0, queued=0, queued_at=None, claimed_by=None, claimed_at=None)
        if t["id_pids"]:
            plan.kept.append(new_id)
        plan.upd("tasks", t["rid"], **cols)

    for c in claims:
        p = by_old[c["passage_id"]]
        t_old = c["task_id"] or ""
        t_new = plan.renamed.get(t_old, t_old)
        new_cid = c["claim_id"]
        if t_new != t_old:
            for i in range(0, 500):
                if c["claim_id"] == f"c{_h(t_old, str(i))}":
                    new_cid = f"c{_h(t_new, str(i))}"
                    break
        claim_map[c["claim_id"]] = new_cid
        evs = _rows(cx, "SELECT rowid AS rid, * FROM evidence WHERE claim_id=?", (c["claim_id"],))
        placed_evs = []
        for ev in evs:
            got = m.place(ev["quote"], ev["start"], p.pid)
            plan.upd("evidence", ev["rid"], claim_id=new_cid, start=got[0] if got else None,
                     end=got[1] if got else None, page=(m.page_at(got[0]) if got else ev["page"]))
            if got:
                placed_evs.append((ev["field"] == "claim", got))
        first = next((g for is_claim, g in placed_evs if is_claim), placed_evs[0][1] if placed_evs else None)
        q = m.one.get(p.pid)
        if q is None and first is not None:
            q = m.passage_at(first[0]).pid
        ev0 = next((e for e in evs if e["field"] == "claim"), evs[0] if evs else None)
        if q is None:
            plan.counts["claim"]["not_placed"] += 1
            plan.miss("claim", f"Claim: {_short(c['claim'], 90)}", ev0["quote"] if ev0 else None, p.pid,
                      ev0["start"] if ev0 else p.start, "gone", old_page(ev0["start"] if ev0 else None, p.pid),
                      m.words_left_out(ev0["quote"] if ev0 else None, ev0["start"] if ev0 else None, p.pid))
        else:
            plan.moved_into("claim", m.left_out(first[0]) if first else m.left_out_passage(q),
                            f"Claim: {_short(c['claim'], 90)}", ev0["quote"] if ev0 else None,
                            m.page_at(first[0]) if first else m.by_new[q].page)
        plan.upd("claims", c["rid"], claim_id=new_cid, task_id=t_new, passage_id=q or tomb[p.pid])
        for r in cx.execute("SELECT rowid FROM claim_targets WHERE claim_id=?", (c["claim_id"],)).fetchall():
            plan.upd("claim_targets", r[0], claim_id=new_cid)
    # their reviews, and the interactions they state
    for old_cid, new_cid in claim_map.items():
        if old_cid != new_cid:
            for r in cx.execute("SELECT rowid FROM reviews WHERE item_kind='claim' AND item_id=?",
                                (old_cid,)).fetchall():
                plan.upd("reviews", r[0], item_id=new_cid)
    for it in _rows(cx, "SELECT rowid AS rid, * FROM interactions WHERE doc_id=?", (doc_id,)):
        if it["kind"] != "stated":
            plan.deletes["interactions"].add(it["rid"])  # inferred: made again by the SDG pack's analysis
            continue
        head, _, j = (it["claim_id"] or "").rpartition("#")
        if head not in plan.renamed and not _pid_re(doc_id).search(head):
            continue
        t_new = plan.renamed.get(head, head)
        pid = (_pid_re(doc_id).search(head) or [None])[0]
        got = m.place(it["quote"], it["start"], pid if pid in old_set else None)
        cols = {"start": got[0] if got else None, "end": got[1] if got else None,
                "page": m.page_at(got[0]) if got else it["page"]}
        if t_new != head:
            cols.update(claim_id=f"{t_new}#{j}", inter_id=f"i{_h(t_new, j)}"
                        if it["inter_id"] == f"i{_h(head, j)}" else it["inter_id"])
        plan.upd("interactions", it["rid"], **cols)

    # --- excerpts: checks (and the SDG pack's checks of claims), with judgements and second opinions ----------------
    vrows = [v for v in _rows(cx, "SELECT rowid AS rid, * FROM verifications WHERE doc_id=?", (doc_id,))
             if v["passage_id"] in old_set]
    vrows += [v for v in _in(cx, "SELECT rowid AS rid, * FROM verifications WHERE passage_id IN ({})", sorted(old_set))
              if v["rid"] not in {x["rid"] for x in vrows}]
    jrows = _in(cx, "SELECT rowid AS rid, * FROM judgements WHERE passage_id IN ({})", sorted(old_set))
    srows = _in(cx, "SELECT rowid AS rid, * FROM second_opinions WHERE passage_id IN ({})", sorted(old_set))
    subjects: dict[tuple, set[str]] = defaultdict(set)
    by_sp: dict[tuple, list[dict]] = defaultdict(list)
    for v in vrows:
        s = (v["subject_kind"], v["subject_id"])
        subjects[s].add(v["passage_id"])
        by_sp[(s, v["passage_id"])].append(v)
    for j in jrows:
        subjects[("user_claim", j["claim_id"])].add(j["passage_id"])
    for r in srows:
        subjects[("user_claim", r["subject_id"])].add(r["passage_id"])
    tasks_of: dict[tuple, list[dict]] = defaultdict(list)
    for t in excerpt_tasks:
        s = (t["payload"]["subject_kind"], t["payload"]["subject_id"])
        tasks_of[s].append(t)
        subjects[s] |= t["pay_pids"] | set(t["id_pids"])
    texts = {r[0]: r[1] for r in cx.execute("SELECT claim_id, text FROM user_claims")}
    breaks = _breaks(ws, [(pid, doc_id, by_old[pid].start, by_old[pid].end)
                          for s, pids in subjects.items() if s[0] == "user_claim" for pid in pids])
    keys: dict[tuple, dict[str, str]] = {}
    anchors: dict[tuple, dict] = defaultdict(dict)
    for s, pids in subjects.items():
        keys[s] = _excerpt_keys(m, s, sorted(pids, key=lambda x: by_old[x].start), by_sp, tomb, plan, texts, old_page,
                                anchors[s])
    jby = defaultdict(list)
    for j in jrows:
        jby[(("user_claim", j["claim_id"]), j["passage_id"])].append(j)
    sby = defaultdict(list)
    for r in srows:
        sby[(("user_claim", r["subject_id"]), r["passage_id"])].append(r)
    for s, kmap in keys.items():
        user = s[0] == "user_claim"
        subj_new = claim_map.get(s[1], s[1]) if s[0] == "claim" else s[1]
        kind = "check" if user else "sdg_check"
        # the tasks of this subject first (a grade's id is made from its task's): their excerpts' pointers move; the
        # excerpt itself is the record and stays as it was shown
        for t in tasks_of.get(s, []):
            if t["id_pids"] and t["status"] != "done" and t["task_id"] not in valid:
                drop_task(t, tomb_id(t["task_id"]))  # a reading again or a pairwise check not answered: asked again
                continue
            _excerpt_task(plan, t, s, subj_new, kmap, m, reader, breaks if user else {}, by_sp, jby, by_old, doc_id,
                          anchors[s])
        for pid, key in kmap.items():
            p = by_old[pid]
            placed = not is_tombstone(key)
            if placed:
                q_key, at = anchors[s].get(pid, (None, None))
                what = (f"Check: {_short(texts.get(s[1]), 90)}" if user and texts.get(s[1])
                        else f"Check of {s[0].replace('_', ' ')} {s[1]}")
                # an excerpt with a judgement (the AI's quote, a person's verdict) is noted where its words now are
                judged = any(v["quote"] or v.get("user_verdict") for v in by_sp.get((s, pid), []))
                where = (m.left_out(at[0]) if at else m.left_out_passage(key)) if judged else None
                plan.moved_into(kind, where, what, q_key or p.text, m.page_at(at[0]) if at else m.by_new[key].page)
            else:
                plan.counts[kind]["not_placed"] += 1

            def pl(q, st):
                return m.place(q, st, pid) if placed and q else None

            for v in by_sp.get((s, pid), []):
                a = pl(v["quote"], v["start"])
                u = pl(v["user_quote"], v["user_start"])
                ref = pl(v["refers_to"], v["refers_start"])
                ver = _ver_id(v, tasks_of.get(s, []), pid, key, plan.renamed, claim_map, s)
                plan.upd("verifications", v["rid"], ver_id=ver, passage_id=key, subject_id=subj_new,
                         start=a[0] if a else None, end=a[1] if a else None,
                         user_start=u[0] if u else None, user_end=u[1] if u else None,
                         refers_start=ref[0] if ref else None, refers_end=ref[1] if ref else None,
                         page=(m.page_at(a[0]) if a else m.by_new[key].page) if placed else v["page"])
            for j in jby.get((s, pid), []):
                u = pl(j["quote"], j["start"])
                plan.upd("judgements", j["rid"], passage_id=key, start=u[0] if u else None, end=u[1] if u else None)
                if j["verdict"] or j["note"]:
                    plan.counts["judgement"]["moved" if placed else "not_placed"] += 1
            for r in sby.get((s, pid), []):
                a = pl(r["quote"], r["start"])
                plan.upd("second_opinions", r["rid"], passage_id=key, start=a[0] if a else None,
                         end=a[1] if a else None)
                plan.counts["second_opinion"]["moved" if placed else "not_placed"] += 1

    # --- results of renamed tasks --------------------------------------------------------------------------------
    for old_id, new_id in plan.renamed.items():
        for r in cx.execute("SELECT rowid FROM results WHERE task_id=?", (old_id,)).fetchall():
            plan.upd("results", r[0], task_id=new_id)

    # --- labels --------------------------------------------------------------------------------------------------
    labs = [x for x in _rows(cx, "SELECT rowid AS rid, * FROM labels WHERE doc_id=?", (doc_id,))
            if x["passage_id"] in old_set]
    reviewed = {r["item_id"] for r in _in(cx, "SELECT DISTINCT item_id FROM reviews WHERE item_kind='label' AND "
                                              "item_id IN ({})", [x["label_id"] for x in labs])}
    taken: set[str] = set()
    n_keyword = 0
    labs.sort(key=lambda x: ({"person": 0, "model": 1}.get(x["source"], 2), by_old[x["passage_id"]].start,
                             x["start"] or 0, x["label_id"]))
    for lb in labs:
        pid = lb["passage_id"]
        if lb["source"] in _KEYWORD_SOURCES and lb["label_id"] not in reviewed:
            plan.deletes["labels"].add(lb["rid"])  # made again by the keyword pass
            n_keyword += 1
            continue
        got = None
        if lb["quote"]:
            got = m.place(lb["quote"], lb["start"], pid)
            q = m.passage_at(got[0]).pid if got else None
            why = "gone"
        else:
            q = m.main.get(pid)
            why = "lost"
        new_id = profile.label_id(lb["framework"], q, lb["code"], lb["source"]) if q else None
        if new_id is not None and new_id in taken:
            q, new_id, why = None, None, "shared_label"
        what = f"Code {lb['code']} ({lb['framework']})"
        if q is None:
            new_id = profile.label_id(lb["framework"], tomb[pid], lb["code"], lb["source"])
            plan.counts["label"]["not_placed"] += 1
            plan.miss("label", what, lb["quote"], pid, lb["start"], why, old_page(lb["start"], pid),
                      m.words_left_out(lb["quote"], lb["start"], pid) if why == "gone" else None)
            cols = {"label_id": new_id, "passage_id": tomb[pid], "start": None, "end": None}
        else:
            plan.moved_into("label", m.left_out(got[0]) if got else m.left_out_passage(q), what,
                            lb["quote"] or m.by_new[q].text, m.page_at(got[0]) if got else m.by_new[q].page)
            cols = {"label_id": new_id, "passage_id": q, "start": got[0] if got else None,
                    "end": got[1] if got else None, "page": m.by_new[q].page}
        taken.add(new_id)
        if lb["task_id"] in plan.renamed:
            cols["task_id"] = plan.renamed[lb["task_id"]]
        plan.upd("labels", lb["rid"], **cols)
        if new_id != lb["label_id"]:
            for r in cx.execute("SELECT rowid FROM reviews WHERE item_kind='label' AND item_id=?",
                                (lb["label_id"],)).fetchall():
                plan.upd("reviews", r[0], item_id=new_id)

    # --- themes --------------------------------------------------------------------------------------------------
    cur = ws.corpus_version()
    runs_touched: dict[str, dict] = {}
    for tm in _in(cx, "SELECT rowid AS rid, * FROM theme_members WHERE passage_id IN ({})", sorted(old_set)):
        r = runs_touched.setdefault(tm["run_id"], {"kept": 0, "taken_out": 0})
        q = m.one.get(tm["passage_id"])
        if q:
            plan.upd("theme_members", tm["rid"], passage_id=q)
            r["kept"] += 1
            plan.counts["theme_member"]["moved"] += 1
        else:
            plan.deletes["theme_members"].add(tm["rid"])
            r["taken_out"] += 1
            plan.counts["theme_member"]["not_placed"] += 1
    for rv in _rows(cx, "SELECT rowid AS rid, item_id FROM reviews WHERE item_kind='theme_member'"):
        rkey, _, pid = (rv["item_id"] or "").partition(":")
        if pid in old_set:
            plan.upd("reviews", rv["rid"], item_id=f"{rkey}:{m.one.get(pid) or tomb[pid]}")
    for th in _rows(cx, "SELECT rowid AS rid, run_id, theme_id, reps_json, quotes_json FROM themes"):
        cols = {}
        reps = json.loads(th["reps_json"] or "[]")
        if any(x in old_set for x in reps):
            cols["reps_json"] = json.dumps([m.one[x] if x in old_set else x for x in reps
                                            if x not in old_set or x in m.one])
        quotes = json.loads(th["quotes_json"] or "null")
        if isinstance(quotes, dict) and any(isinstance(v, dict) and v.get("passage_id") in old_set
                                            for v in quotes.values()):
            for v in quotes.values():
                if isinstance(v, dict) and v.get("passage_id") in old_set:
                    got = m.place(v.get("quote"), None, v["passage_id"])
                    v["passage_id"] = m.passage_at(got[0]).pid if got else tomb[v["passage_id"]]
            cols["quotes_json"] = json.dumps(quotes, ensure_ascii=False)
        if cols:
            plan.upd("themes", th["rid"], **cols)
    body_old = [p for p in old if p.section == "body"]
    body_new = {q.pid for q in new if q.section == "body"}
    images = [m.one.get(p.pid) for p in body_old]
    whole = all(images) and set(images) == body_new and len(set(images)) == len(images)
    fresh = [r[0] for r in cx.execute("SELECT run_id FROM theme_runs WHERE corpus_version=?", (cur,))]
    theme_info = {"runs_kept_up_to_date": len(fresh) if whole else 0,
                  "runs_out_of_date": 0 if whole else len(fresh),
                  "runs": [{"run_id": k, **v} for k, v in runs_touched.items()]}
    if whole and fresh:
        plan.after.append(("UPDATE theme_runs SET corpus_version=? WHERE corpus_version=?", (cur + 1, cur)))

    # --- the ledger of what was sent to Claude --------------------------------------------------------------------
    for r in _rows(cx, "SELECT rowid AS rid, passage_id, task_id FROM ai_sent WHERE doc_id=?", (doc_id,)):
        cols = {}
        if r["passage_id"] in old_set:
            cols["passage_id"] = m.one.get(r["passage_id"]) or tomb[r["passage_id"]]
        tid = r["task_id"]
        if tid in plan.renamed:
            cols["task_id"] = plan.renamed[tid]
        elif tid in plan.dropped:
            cols["task_id"] = plan.dropped[tid]
        if cols:
            plan.upd("ai_sent", r["rid"], **cols)
    if plan.renamed or plan.dropped:
        moved = {**plan.renamed, **plan.dropped}
        for r in _rows(cx, "SELECT rowid AS rid, task_ids_json FROM task_claims WHERE instr(task_ids_json, ?) > 0",
                       (doc_id,)):
            try:
                ids = json.loads(r["task_ids_json"] or "[]")
            except ValueError:
                continue
            if any(i in moved for i in ids):
                plan.upd("task_claims", r["rid"], task_ids_json=json.dumps([moved.get(i, i) for i in ids]))

    # --- what is made again ----------------------------------------------------------------------------------------
    for r in _in(cx, "SELECT rowid AS rid FROM embeddings WHERE passage_id IN ({})", sorted(old_set | set(new_pids))):
        plan.deletes["embeddings"].add(r["rid"])
    n_emb = len(plan.deletes["embeddings"])
    plan.deletes["term_mentions"] |= {r[0] for r in cx.execute("SELECT rowid FROM term_mentions WHERE doc_id=?",
                                                               (doc_id,))}
    plan.deletes["mentions"] |= {r[0] for r in cx.execute("SELECT rowid FROM mentions WHERE doc_id=?", (doc_id,))}

    # --- a bibliography match's evidence (where the title stands) --------------------------------------------------
    for r in _rows(cx, "SELECT rowid AS rid, evidence_json FROM bib_links WHERE doc_id=?", (doc_id,)):
        try:
            ev = json.loads(r["evidence_json"] or "{}")
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("offset") is not None:
            words = (ev.get("excerpt") or "")[ev.get("start", 0):ev.get("end", 0)]
            got = m.place(words, ev["offset"], None) if words else None
            if got:
                ev["offset"] = got[0]
            else:
                ev.pop("offset")
            plan.upd("bib_links", r["rid"], evidence_json=json.dumps(ev, ensure_ascii=False))

    # --- the SDG pack's screening of passages that map one to one is kept -------------------------------------------
    for r in cx.execute("SELECT passage_id, screen_score, screened FROM passages WHERE doc_id=? AND (screened != 0 OR "
                        "screen_score != 0)", (doc_id,)).fetchall():
        if r[0] in m.one:
            plan.after.append(("UPDATE passages SET screen_score=?, screened=? WHERE passage_id=?",
                               (r[1], r[2], m.one[r[0]])))

    # --- the report ------------------------------------------------------------------------------------------------
    from .claimcheck import locate

    if plan.locate:
        where = locate(ws, [(i, pid, off) for i, (_e, pid, off) in enumerate(plan.locate)])
        for i, (e, _pid, _off) in enumerate(plan.locate):
            e["where"] = (where.get(i) or {}).get("location") or (f"page {e['page']}" if e["page"] else None)
    # the share of the document Claude has read: of the passages sent, those that keep their place count as the new
    # passage; the share of those that have no place now is kept with the document and still counts (access.shares)
    sent = {r[0] for r in cx.execute("SELECT DISTINCT passage_id FROM ai_sent WHERE doc_id=?", (doc_id,))}
    total_old = sum(len(p.text) for p in old) or 1
    total_new = sum(len(q.text) for q in new) or 1
    after_sent = {m.one[p] for p in sent if p in m.one}
    before_share = shares(cx, [doc_id]).get(doc_id, {}).get("share", 0.0)
    sent_share = min(1.0, float(drow.get("sent_share") or 0.0)
                     + sum(len(by_old[p].text) for p in sent if p in old_set and p not in m.one) / total_old)
    after_share = round(min(1.0, sum(len(m.by_new[q].text) for q in after_sent) / total_new + sent_share), 4)
    report = {
        "doc_id": doc_id, "title": drow["title"] or "", "reader": reader, "new_reader": ingest.READER,
        "ok": True, "reason": None, "moved": False,
        "counts": {k: dict(v) for k, v in plan.counts.items()},
        "not_placed": plan.not_placed,
        "left_out": plan.left_out,
        "remade": {"keyword_labels": n_keyword, "embeddings": n_emb, "reference_chains": n_chains,
                   "inferred_interactions": len(plan.deletes["interactions"]),
                   "term_index": True},
        # tasks: not answered and asked again; answered, kept under the new passage's id; answered, kept as a record
        # under a tombstone (never asked again)
        "tasks": {"asked_again": len(plan.dropped),
                  "moved": sum(1 for n in plan.kept if not _pid_has_tomb(n, doc_id)),
                  "kept_as_records": sum(1 for n in plan.kept if _pid_has_tomb(n, doc_id))},
        "themes": theme_info,
        "passages": {"before": len(old), "after": len(new), "one_to_one": len(m.one),
                     "body_before": len(body_old), "body_after": len(body_new)},
        "ai_share": {"before": before_share, "after": after_share},
        "addons": _addon_rows(cx, doc_id, old_set),
        "reading": dict(getattr(new_doc, "reading", None) or {}),
        "warnings": [],
    }
    _warnings(report, drow)
    return plan, {"report": report, "new_pids": new_pids, "map": m, "old_text": old_text, "reader": reader,
                  "drow": drow, "sent_share": round(sent_share, 6) or None}


def _pid_has_tomb(task_id: str, doc_id: str) -> bool:
    return bool(re.search(re.escape(doc_id) + r":r\d+-", task_id))


def _excerpt_task(plan: _Plan, t: dict, s: tuple, subj_new: str, kmap: dict[str, str], m: _Map, reader: int,
                  breaks: dict, by_sp: dict, jby: dict, by_old: dict, doc_id: str, anchors: dict) -> None:
    """A task that showed excerpts (a check's round, a second opinion, a reading again, an SDG pack check): each
    excerpt of the document takes its new pointer; its text stays as it was shown, marked with the reader whose text
    it is, where its paragraphs began and where its quotes were in it, and (`anchor`) a point of it tied to its place
    in the document now: [offset in the excerpt, offset in the document], so a quote given in it later is placed
    exactly (tasks.doc_span)."""
    pl_new = json.loads(json.dumps(t["payload"]))
    if s[0] == "claim":
        pl_new["subject_id"] = subj_new
    many = isinstance(pl_new.get("passages"), list)
    for it in (pl_new["passages"] if many else [pl_new]):
        pid = it.get("passage_id")
        if pid not in kmap:
            continue
        key = kmap[pid]
        it["passage_id"] = key
        if not is_tombstone(key):
            it["page"] = m.by_new[key].page
        if "context_start" in it:
            it["context_start"] = None  # an offset in the old text; the context itself is part of the record
        if many:
            it.setdefault("reader", reader)
            if s[0] == "user_claim":
                it.setdefault("breaks", breaks.get(pid, []))
            if "quotes_at" not in it:
                text, base, qa = it.get("text") or "", by_old[pid].start, {}
                quotes = [(v["quote"], v["start"]) for v in by_sp.get((s, pid), [])]
                quotes += [(v["user_quote"], v["user_start"]) for v in by_sp.get((s, pid), [])]
                quotes += [(j["quote"], j["start"]) for j in jby.get((s, pid), [])]
                for q, st in quotes:
                    if q and st is not None and 0 <= st - base and text[st - base:st - base + len(q)] == q:
                        qa[q] = st - base
                it["quotes_at"] = qa
        it.pop("anchor", None)  # a pointer into the reading before: made again below, or none
        if not is_tombstone(key):
            q, (ds, _de) = anchors.get(pid, (None, (None, None)))
            text = it.get("text") or ""
            local = (it.get("quotes_at") or {}).get(q) if q else None
            if q and not (isinstance(local, int) and text[local:local + len(q)] == q):
                local = text.find(q)
            if q and local is not None and local >= 0:
                it["anchor"] = [local, ds]
            elif text == by_old[pid].text:  # no quote: where the excerpt's first words found are
                first = next((x for x in m.anchors if x[4] == pid), None)
                if first is not None:
                    it["anchor"] = [first[0] - by_old[pid].start, first[2]]
    new_id = t["task_id"]
    if t["id_pids"]:
        new_id = _pid_re(doc_id).sub(lambda mm: kmap.get(mm.group(0), mm.group(0)), new_id)
    if s[0] == "claim" and subj_new != s[1]:
        new_id = new_id.replace(s[1], subj_new)
    cols = {"payload_json": json.dumps(pl_new, ensure_ascii=False)}
    if new_id != t["task_id"]:
        cols["task_id"] = new_id
        plan.renamed[t["task_id"]] = new_id
    if t["id_pids"]:
        plan.kept.append(new_id)
    plan.upd("tasks", t["rid"], **cols)


def _map_payload(obj: Any, f) -> Any:
    """A copy of a payload with every `passage_id` (at any depth) mapped by `f`."""
    if isinstance(obj, dict):
        return {k: (f(v) if k == "passage_id" and isinstance(v, str) else _map_payload(v, f)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_map_payload(v, f) for v in obj]
    return obj


def _excerpt_keys(m: _Map, s: tuple, pids: list[str], by_sp: dict, tomb: dict, plan: _Plan, texts: dict,
                  old_page, anchors: dict) -> dict[str, str]:
    """The new passage of each excerpt of one subject (a check's part, an SDG pack claim): the passage holding its
    quote (the AI's; and the person's judgement in force must be found too), or without a quote the passage most of
    its text is in; a tombstone where that cannot be found, or where another excerpt of the subject took the
    passage."""
    found = []
    for pid in pids:
        p = m.by_old[pid]
        rows = by_sp.get((s, pid), [])
        prim = next((v for v in rows if v["quote"]), rows[0] if rows else None)
        ai_q = prim["quote"] if prim else None
        user = next((v for v in rows if v.get("user_quote") and v.get("user_verdict")), None)
        ai = m.place(ai_q, prim["start"], pid) if ai_q else None
        us = m.place(user["user_quote"], user["user_start"], pid) if user else None
        if ai_q:
            ok, anchor, key_q, why = ai is not None and (user is None or us is not None), ai, ai_q, "gone"
        elif user:
            ok, anchor, key_q, why = us is not None, us, user["user_quote"], "gone"
        else:
            ok, anchor, key_q, why = pid in m.main, None, None, "lost"
        if not ok:  # what the person sees in the list: the quote shown, where it was
            key_q = user["user_quote"] if user else ai_q
        at = (user["user_start"] if user and not ai_q else prim["start"] if prim else None)
        found.append((pid, ok, anchor, why, key_q, at, p))
    order = sorted(found, key=lambda x: (not x[1], x[2] is None, x[2][0] if x[2] else x[6].start))
    out: dict[str, str] = {}
    used: set[str] = set()
    for pid, ok, anchor, why, q, at, p in order:
        key = (m.passage_at(anchor[0]).pid if anchor else m.main.get(pid)) if ok else None
        if key is not None and key in used:
            key, why = None, "shared"
        if key is not None and anchor:
            anchors[pid] = (q if anchor is not None and q else None, anchor)
        if key is None:
            out[pid] = tomb[pid]
            kind = "check" if s[0] == "user_claim" else "sdg_check"
            what = (f"Check: {_short(texts.get(s[1]), 90)}" if s[0] == "user_claim" and texts.get(s[1])
                    else f"Check of {s[0].replace('_', ' ')} {s[1]}")
            plan.miss(kind, what, q or p.text, pid, at if at is not None else p.start, why, old_page(at, pid),
                      m.words_left_out(q, at, pid) if why == "gone" else None)
        else:
            used.add(key)
            out[pid] = key
    return out


def _ver_id(v: dict, tasks: list[dict], pid: str, key: str, renamed: dict, claim_map: dict, s: tuple) -> str:
    """A check's grade's id made again: `v<hash(task, passage)>` (a round, a reading again) or `v<hash(task)>` (a
    pairwise check), from the task that stored it, under its new id and the new passage."""
    for t in tasks:
        tid = t["task_id"]
        new_t = renamed.get(tid, tid)
        if v["ver_id"] == f"v{_h(tid, pid)}":
            return f"v{_h(new_t, key)}"
        if v["ver_id"] == f"v{_h(tid)}":
            return f"v{_h(new_t)}"
    return v["ver_id"]


def _addon_rows(cx, doc_id: str, old: set[str]) -> list[dict]:
    """Add-on tables (any table ENLENS itself does not make) with rows naming this document or its passages."""
    import sqlite3

    from .store import MIGRATIONS, SCHEMA, _add_columns

    mem = sqlite3.connect(":memory:")
    try:
        mem.executescript(SCHEMA)
        _add_columns(mem, MIGRATIONS)
        core = {r[0] for r in mem.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        mem.close()
    out = []
    for (t,) in cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        if t in core:
            continue
        cols = {r[1] for r in cx.execute(f"PRAGMA table_info({t})")}
        n = 0
        if "doc_id" in cols:
            n = cx.execute(f"SELECT COUNT(*) FROM {t} WHERE doc_id=?", (doc_id,)).fetchone()[0]
        if not n and "passage_id" in cols and old:
            ids = sorted(old)
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                n += cx.execute(f"SELECT COUNT(*) FROM {t} WHERE passage_id IN ({','.join('?' * len(chunk))})",
                                chunk).fetchone()[0]
        if n:
            out.append({"table": t, "rows": int(n)})
    return out


def _warnings(report: dict, drow: dict) -> None:
    w = report["warnings"]
    n = len(report["not_placed"])
    if n == 1:
        w.append("1 result has no place in the new reading (listed below). It is kept as it was, but no longer points "
                 "at any words in the text.")
    elif n:
        w.append(f"{n} results have no place in the new reading (listed below). They are kept as they were, but no "
                 "longer point at any words in the text.")
    n = len(report["left_out"])
    if n:
        w.append(f"{n} {'result is' if n == 1 else 'results are'} now in text the new reader leaves out of searches "
                 f"(listed below): {'it is' if n == 1 else 'they are'} kept, and judgements count as before.")
    if report["addons"]:
        names = ", ".join(a["table"] for a in report["addons"])
        w.append(f"An add-on's results were not moved ({names}): they may point at the old reading of this document.")
    th = report["themes"]
    if th["runs_out_of_date"]:
        w.append("Theme runs become out of date: find the themes again to include this document's new passages.")
    if (report["reading"] or {}).get("quality") == "poor":
        w.append("The new reader read this file poorly (see the reading report): look at it before moving your "
                 "results.")


# ------------------------------------------------------------------------------------------------------------------
# preview and move
# ------------------------------------------------------------------------------------------------------------------
def preview(ws: Workspace, doc_id: str, ocr=None, should_stop=None) -> dict:
    """Read the original file with the new reader (nothing is stored) and work out where every result would go.

    Returns the report (see `move`), with "moved": False; when the document cannot be read again now, only
    {"ok": False, "reason", "reader", "new_reader", "doc_id", "title"}."""
    cx = ws._conn()
    c = _check(ws, cx, doc_id)
    title = cx.execute("SELECT title FROM documents WHERE doc_id=?", (doc_id,)).fetchone()[0] or ""
    if not c["ok"]:
        return {**_public(c), "doc_id": doc_id, "title": title}
    new_doc = _read(ws, doc_id, c["path"], ocr, should_stop)
    empty = _empty(new_doc)
    if empty:
        return {**_public(c), "ok": False, "reason": empty, "doc_id": doc_id, "title": title}
    _plan_, info = _plan(ws, cx, doc_id, new_doc)
    return info["report"]


def _empty(new_doc) -> str | None:
    if len((new_doc.text or "").strip()) < 100:
        return ("The new reader found almost no text in this file (it may be scanned pages that could not be "
                "recognised), so nothing would be left for your results to point at. Nothing was changed.")
    return None


class WouldLose(ValueError):
    """0.15.7: `move(..., keep_all=True)` left the document as it was, because some of its results would find no place
    in the new reading; `report` is what the move would have done (as `preview` gives it)."""

    def __init__(self, report: dict):
        n = len(report.get("not_placed") or [])
        super().__init__(f"{n} of its results would not find their place in the new reading. See which on the "
                         "document's page (Reading), then move it from there.")
        self.report = report


def move(ws: Workspace, doc_id: str, person_id: str | None = None, ocr=None, should_stop=None,
         keep_all: bool = False) -> dict:
    """Read the document with the new reader and move every result to the same words in the new text, in one
    transaction: on any error nothing changes. Raises ValueError (in words for a researcher) when it cannot be done
    now (see `check`); with `keep_all` (0.15.7, moving several documents at once), WouldLose when any result would
    find no place, and nothing changes. Returns the report:

    {"doc_id", "title", "reader" (before), "new_reader", "ok": True, "reason": None, "moved": True,
     "counts": {kind: {"moved": n, "not_placed": n, "left_out": n (of the moved)}} for the kinds of result found
       (KIND_TEXT; for "theme_member", "moved" are the passages a run keeps and "not_placed" those taken out of it),
     "not_placed": [{"kind", "kind_text", "what", "quote", "page", "where", "left_out_kind", "why"}]: results with
       no place in the new reading, with where they were (`page`, `where`: in the reading before); `left_out_kind`:
       the kind of text their words went to when that can be told (reader.KIND_TEXT words, else None),
     "left_out": [{"kind", "kind_text", "what", "quote", "page", "where", "left_out_kind", "note"}]: results placed in
       text the new reader leaves out of searches (`page`, `where`: in the new reading),
     "remade": {"keyword_labels", "embeddings", "reference_chains", "inferred_interactions", "term_index"},
     "tasks": {"asked_again", "kept_as_records", "moved"},
     "themes": {"runs_kept_up_to_date", "runs_out_of_date", "runs": [{"run_id", "kept", "taken_out"}]},
     "passages": {"before", "after", "one_to_one", "body_before", "body_after"},
     "ai_share": {"before", "after"}, "addons": [{"table", "rows"}], "reading": {the new reading report},
     "warnings": [str]}
    """
    from .people import me

    c = _check(ws, ws._conn(), doc_id)
    if not c["ok"]:
        raise ValueError(c["reason"])
    new_doc = _read(ws, doc_id, c["path"], ocr, should_stop)
    empty = _empty(new_doc)
    if empty:
        raise ValueError(empty)
    who = person_id or me()
    with ws.connect() as cx:
        c = _check(ws, cx, doc_id, verify_file=False)  # again, holding the database: nothing changed meanwhile
        if not c["ok"]:
            raise ValueError(c["reason"])
        want = (cx.execute("SELECT sha1 FROM documents WHERE doc_id=?", (doc_id,)).fetchone()[0] or "").split("~")[0]
        if new_doc.raw.sha1 != want:  # the file changed between its check and its reading
            raise ValueError("The original file changed while it was being read. Nothing was changed; try again.")
        plan, info = _plan(ws, cx, doc_id, new_doc)
        if keep_all and info["report"].get("not_placed"):
            raise WouldLose(info["report"])  # before anything is written: the transaction has nothing to undo
        _apply(ws, cx, doc_id, plan, info, new_doc, who)
    report = info["report"]
    report["moved"] = True
    return report


def _apply(ws: Workspace, cx, doc_id: str, plan: _Plan, info: dict, new_doc, who: str) -> None:
    from .sync import text_fp

    for table, rids in plan.deletes.items():
        ids = sorted(rids)
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            cx.execute(f"DELETE FROM {table} WHERE rowid IN ({','.join('?' * len(chunk))})", chunk)
    for table, rows in plan.updates.items():
        rows = {rid: cols for rid, cols in rows.items() if rid not in plan.deletes.get(table, set())}
        keys = _PK.get(table, ())
        moving = {rid: cols for rid, cols in rows.items() if any(k in cols for k in keys)}
        for rid, cols in moving.items():  # first out of the way, so ids that change places never collide
            sets = ", ".join(f"{k}=?" for k in keys if k in cols)
            cx.execute(f"UPDATE {table} SET {sets} WHERE rowid=?",
                       (*[f"\x01moving\x01{table}\x01{rid}" for k in keys if k in cols], rid))
        for rid, cols in rows.items():
            sets = ", ".join(f"{k}=?" for k in cols)
            cx.execute(f"UPDATE {table} SET {sets} WHERE rowid=?", (*cols.values(), rid))
    # the document's own rows: its old reading out, the new one in
    for t in ("pages", "paragraphs", "headings", "passages", "blocks", "doc_tables"):
        cx.execute(f"DELETE FROM {t} WHERE doc_id=?", (doc_id,))
    drow = info["drow"]
    fps = json.loads(drow.get("old_fps") or "[]")
    fps.append(text_fp(info["old_text"]))
    raw = new_doc.raw
    # what Claude had read of passages that have no place now still counts (access.shares)
    sent = info["sent_share"]
    cx.execute("UPDATE documents SET text=?, n_chars=?, n_pages=?, reader=?, app_version=?, text_fp=?, "
               "reading_json=NULL, ocr_pages=?, scanned_pages=?, old_fps=?, sent_share=? WHERE doc_id=?",
               (new_doc.text, len(new_doc.text), len(new_doc.page_spans) if raw.paginated else None, ingest.READER,
                __version__, text_fp(new_doc.text), raw.ocr_pages if raw.kind == "pdf" else drow.get("ocr_pages"),
                raw.scanned_pages if raw.kind == "pdf" else drow.get("scanned_pages"), json.dumps(fps), sent, doc_id))
    ingest.store_reading(cx, new_doc, doc_id)  # with the person's corrections of its blocks applied again
    for sql, args in plan.after:
        cx.execute(sql, args)
    ws.bump_corpus(cx)
    log = ws.meta(f"read_again:{doc_id}") or []
    rep = info["report"]
    log.append({"at": now(), "person_id": who, "from_reader": info["reader"], "to_reader": ingest.READER,
                "app_version": __version__, "not_placed": len(rep["not_placed"]),
                "counts": rep["counts"]})
    ws.set_meta(f"read_again:{doc_id}", log, cx)
