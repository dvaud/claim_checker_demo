"""Short code names for themes (0.16.1), without AI.

A theme's name says in up to six words what its passages share ("National green hydrogen strategies and markets").
A code name should be as short as an SDG goal's: one or two words ("Hydrogen strategies"). Cutting the name at 40
characters gave "National green hydrogen strategies and d". Here every code name is words of the theme's name, chosen
by what the documents say:

1. The candidates are the parts of the name: each phrase between the joining words ("and", "of", "for", ...) and
   commas, the shorter parts of a phrase that end in its last word ("hydrogen strategies", "strategies"), the word
   pairs the glossary knows as terms ("clean cooking", "critical minerals"), and a phrase with the phrases after it
   ("hydrogen production and demand"). A part the documents nearly always write inside a longer term is left out
   ("cell" of "fuel cell", "cell vehicles" of "fuel cell vehicles").
2. The shortest level first (one or two words), then three words, four, and so on: a candidate is too generic for the
   documents when most of the passages that use it are outside the theme (fewer than PRECISION of them in it), or
   when it is in too few of the theme's passages. Then the next level is tried.
3. Of the candidates good enough at the first level that has one, the best: a glossary term, a phrase's last word
   (its subject), the name's first phrase, most of its passages in the theme.
4. Two themes do not get the same code: the theme it fits best keeps it, the other takes its next best.

Each theme gets a ladder: one name per length, from the shortest to the longest that fits in 40 characters, with the
chosen one marked, so a person can make a code less or more specific before editing it. A name with no evidence
either way (the theme's words are not in the documents, as when Dutch interviews got English theme names) is the best
short name by its form alone, marked unsure. A name a person gave the theme is kept when it fits.

Passages are counted with the keyword index (search.passage_index): for a glossary term the passages it is written
in (`term_mentions`), for other words the passages that have all of them. Nothing is stored.
"""
from __future__ import annotations

import re

from .store import Workspace
from .textutil import is_stop, token_spans, tokens

MAX_CHARS = 40          # a code name's limit (codebooks.py, frameworks.py)
PRECISION = 0.4         # at least this share of the passages using a name must be in the theme...
PRECISION_ONE = 0.5     # ...and for a single word, this share
COVERAGE_ONE = 0.2      # a single word must also be in this share of the theme's passages
MIN_HITS = 3            # and any name in at least this many of them
BOUND = 0.7             # a part written inside the longer term this often is not a name of its own

# joining words split a name into phrases; articles and the like are no word of a code (inside a longer name they
# stay). English, with the commonest of Dutch, German, French, Spanish, Italian, Hungarian and Russian, so a name in
# another language does not give "Van verpleeghuizen" or "Et jeunes employés".
_LINKS = frozenset("""and & or of for in on to by with without from at as into during using amid among across through
via within under over versus vs between around about after before towards toward against beyond per
en of voor op met bij naar tot uit tegen zonder tussen van
und oder von vom für im mit bei zur zum aus nach über unter zwischen gegen ohne durch
et ou pour dans sur avec par entre sans chez vers à au aux
y o para con por sin sobre e ed nel nella su tra
és vagy illetve valamint mint
и или в на с для по из от к о""".split())
_COORD = frozenset({"and", "&", "or", "en", "und", "oder", "et", "ou", "y", "o", "e", "ed", "és", "vagy", "и",
                    "или"})
_FILLER = frozenset("""the a an their its our his her these those this that other
de het een der die das den dem des ein eine einer eines le la les un une du del della di da do il lo gli una uno
el los las az egy""".split())
_WORD = re.compile(r"[^\W_]")
_SEP = re.compile(r"\s*[,;:·|()]\s*|\s+[-–—]\s+")
_PARTICIPLE = re.compile(r"^[a-z]{2,}[^e]ed$")  # "compared", "lived"; not "speed"


def _parse(name: str, terms_only: bool = False) -> list[tuple[str | None, list[str]]]:
    """The phrases of a name, each with the word that joins it to the one before: None for the first, "," after a
    comma, "?" after two joining words in a row ("learning and using X": no phrase to join). Articles stay in a phrase
    (a longer name keeps them) but no code starts or ends with one. A theme named by its key terms ("young employees
    · work from home · job") has its terms as phrases, each kept whole ("·")."""
    name = name or ""
    if terms_only or "·" in name:
        items = [[w for w in i.split() if _WORD.search(w)] for i in name.split("·")]
        return [(None if k == 0 else "·", ws) for k, ws in enumerate(i for i in items if i)]
    out: list[tuple[str | None, list[str]]] = []
    link: str | None = None
    for ci, chunk in enumerate(_SEP.split(name)):
        if ci and out:
            link = ","
        cur: list[str] = []
        for w in chunk.split():
            lw = w.lower()
            if not _WORD.search(w):
                continue  # a dash or other mark left between words
            if lw in _LINKS:
                if any(x.lower() not in _FILLER for x in cur):
                    out.append((link, cur))
                    cur = []
                    link = lw
                elif link == ",":
                    link = lw  # "a, b, and c"
                else:
                    link = "?" if out and link is not None else lw
            else:
                cur.append(w)
        if any(x.lower() not in _FILLER for x in cur):
            out.append((link, cur))
    # "Electrolyser technologies compared": a last word like "compared" is not the subject
    if out and len(_content(out[-1][1])) > 1 and _PARTICIPLE.search(out[-1][1][-1]):
        out[-1] = (out[-1][0], out[-1][1][:-1])
    return out


def _content(words: list[str]) -> list[str]:
    return [w for w in words if w.lower() not in _FILLER]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def cut(text: str, n: int = MAX_CHARS) -> str:
    """`text` in at most `n` characters, cut before a word, never inside one (unless one word is longer), and not
    after a joining word: "National green hydrogen strategies and d" becomes "National green hydrogen strategies"."""
    words: list[str] = []
    for w in " ".join((text or "").split()).split(" "):
        if len(" ".join(words + [w])) > n:
            break
        words.append(w)
    while len(words) > 1 and (words[-1].lower().strip(",;:") in _LINKS | _FILLER or words[-1] in {"-", "–", "—"}):
        words.pop()
    out = " ".join(words).rstrip(",;:- ") or (text or "")[:n]
    return out if _WORD.search(out) else ""


def key(text: str) -> str:
    """Two names that count as the same code: the same words, stemmed, numbers kept ("Fuel cell" and "fuel cells";
    not "Theme 3" and "Theme 4")."""
    return " ".join(t[2] for t in token_spans(text, keep_stop=True) if t[3].isdigit() or not is_stop(t[3]))


class _Evidence:
    """Counts over one theme run's passages: the keyword index's passage numbers, the glossary's terms."""

    def __init__(self, ws: Workspace, run_id: str, merged: dict[int, int]):
        from . import stopwords
        from .search import passage_index
        from .terms import _key_of, term_id

        self.ws, self._key_of, self._term_id = ws, _key_of, term_id
        self._rules = stopwords.rules(ws)   # 0.17: the project's own words are no glossary term
        self.theme: dict[int, set[int]] = {}
        self.idx = None
        try:
            self.idx = passage_index(ws)
        except Exception:  # noqa: BLE001 - no index: names by their form alone
            pass
        if self.idx is not None:
            from .themes import _edits

            rk = ws.query("SELECT run_key FROM theme_runs WHERE run_id=?", (run_id,))
            moves = _edits(ws, rk[0][0])["moves"] if rk else {}
            rows = ws.query("SELECT passage_id, theme_id FROM theme_members WHERE run_id=?", (run_id,))
            ids = {r[1] for r in rows}
            for pid, tid in rows:
                p = self.idx.pos.get(pid)
                if p is not None:
                    to = moves.get(pid)
                    tid = to if to in ids else tid  # a passage a person moved counts where they moved it
                    self.theme.setdefault(merged.get(tid, tid), set()).add(p)
        self.universe: set[int] = set().union(*self.theme.values()) if self.theme else set()
        self._posts: dict[str, set[int]] = {}
        self._terms: dict[str, tuple[str, int] | None] = {}
        self._phrases: dict[str, set[int] | None] = {}

    def term(self, text: str) -> tuple[str, int] | None:
        """(term id, occurrences) of the glossary term written so, None when the glossary has none."""
        n = len(token_spans(text, keep_stop=True))
        k = self._key_of(text, self._rules)
        if not k or len(k.split()) != n:
            return None
        if k not in self._terms:
            tid = self._term_id(k)
            r = self.ws.query("SELECT tf FROM terms WHERE term_id=?", (tid,))
            self._terms[k] = (tid, r[0][0] or 0) if r else None
        return self._terms[k]

    def _post(self, stem: str) -> set[int]:
        if stem not in self._posts:
            pl = self.idx.bm25.postings.get(stem) if self.idx is not None else None
            self._posts[stem] = ({p for p, _f in pl} & self.universe) if pl else set()
        return self._posts[stem]

    def passages(self, text: str) -> set[int]:
        """The run's passages that use these words: the term where the glossary has it, else all the words."""
        if text not in self._phrases:
            got = None
            t = self.term(text) if len(text.split()) > 1 or "-" in text else None
            if t is not None and self.idx is not None:
                got = {self.idx.pos[r[0]] for r in self.ws.query(
                    "SELECT DISTINCT passage_id FROM term_mentions WHERE term_id=?", (t[0],))
                    if r[0] in self.idx.pos} & self.universe
                got = got or None
            self._phrases[text] = got
        got = self._phrases[text]
        if got is not None:
            return got
        st = tokens(text)
        if not st:
            return set()
        out = self._post(st[0])
        for s in st[1:]:
            out = out & self._post(s)
        return out

    def bound(self, longer: list[str], part: list[str]) -> bool:
        """Is `part` written inside `longer` (a word more on its left) most of the times it is written?"""
        a, b = self.term(" ".join(longer)), self.term(" ".join(part))
        return bool(a and b and b[1] and a[1] >= BOUND * b[1])


def _candidates(name: str, ev: _Evidence, terms_only: bool = False) -> list[dict]:
    ph = _parse(name, terms_only)
    out: list[dict] = []
    if any(lk == "·" for lk, _w in ph) or (terms_only and ph):  # each key term on its own, and all of them
        for i, (_link, ws) in enumerate(ph):
            text = " ".join(ws)
            if len(ws) == 1 and _PARTICIPLE.search(text):
                continue
            out.append({"text": text, "parts": [text], "n": len(ws), "phrase": i, "head": True,
                        "term": ev.term(text) is not None, "multi": False})
        if len(ph) > 1:
            out.append({"text": ", ".join(" ".join(ws) for _l, ws in ph), "parts": [" ".join(ws) for _l, ws in ph],
                        "n": sum(len(ws) for _l, ws in ph), "phrase": 0, "head": True, "term": False, "multi": True})
        ph = []
    for i, (_link, ws) in enumerate(ph):
        k = len(ws)
        whole = len(_content(ws))
        for a in range(k):
            for b in range(a + 1, k + 1):
                span, head = ws[a:b], b == k
                if span[0].lower() in _FILLER or span[-1].lower() in _FILLER:
                    continue  # no code starts or ends with "the"
                n = len(_content(span))
                text = " ".join(span)
                term = ev.term(text) is not None if n > 1 or "-" in text else False
                if not head and not (n > 1 and term):
                    continue  # a part that stops before the phrase's last word only when it is a term
                if n == 1 and _PARTICIPLE.search(text):
                    continue  # "learned" is no name
                if a and ev.bound(ws[a - 1:b], span):
                    continue
                if a and not term and n > 1 and ev.term(" ".join(ws[a - 1:a + 1])) is not None:
                    continue  # "minerals mining" would cut the term "critical minerals"
                out.append({"text": text, "parts": [text], "n": n, "phrase": i, "head": head, "term": term,
                            "multi": False})
                if not head or (n == 1 and whole > 1):
                    continue  # grows from a whole phrase or two words or more: not "work and ..." of "remote work"
                t, parts, nn, listed = text, [text], n, False
                for j in range(i + 1, len(ph)):
                    lj, wj = ph[j]
                    if lj == "?":
                        break
                    listed = listed or lj == ","
                    t = f"{t}, {' '.join(wj)}" if lj == "," else f"{t} {lj} {' '.join(wj)}"
                    parts, nn = parts + [" ".join(_content(wj))], nn + len(_content(wj))
                    after = ph[j + 1][0] if j + 1 < len(ph) else None
                    if after == "," or (listed and after in _COORD):
                        continue  # not "health, wellbeing" out of "health, wellbeing and human development"
                    out.append({"text": t, "parts": parts, "n": nn, "phrase": i, "head": True, "term": False,
                                "multi": True})
    seen, kept = set(), []
    for c in out:
        if len(c["text"]) > MAX_CHARS and " and " in c["text"]:
            c["text"] = c["text"].replace(" and ", " & ")
        k_ = key(c["text"])
        if len(c["text"]) <= MAX_CHARS and k_ and k_ not in seen:
            seen.add(k_)
            c["key"] = k_
            kept.append(c)
    return kept


def _judge(c: dict, theme: set[int], ev: _Evidence) -> None:
    used: set[int] = set()
    for p in c["parts"]:
        used |= ev.passages(p)
    hits = len(used & theme)
    c["precision"] = hits / len(used) if used else 0.0
    c["coverage"] = hits / len(theme) if theme else 0.0
    if c["n"] == 1:
        c["ok"] = c["precision"] >= PRECISION_ONE and c["coverage"] >= COVERAGE_ONE and hits >= MIN_HITS
    else:
        c["ok"] = c["precision"] >= PRECISION and hits >= MIN_HITS
    c["shape"] = (2.0 if c["term"] else 0) + (0.6 if c["head"] else 0) + \
        (0.5 if c["phrase"] == 0 else 0.2 if c["phrase"] == 1 else 0) - \
        (0.8 if c["n"] == 1 else 0) - (0.5 if c["multi"] else 0)
    c["score"] = c["shape"] + 2 * c["precision"] + 0.5 * c["coverage"]


def _ladder(cands: list[dict], taken: set[str], kept_name: str | None) -> dict | None:
    free = [c for c in cands if c["key"] not in taken]
    if not free:
        return None
    pick, sure = None, False
    if kept_name:
        pick = next((c for c in free if c["key"] == key(kept_name)), None)
        sure = pick is not None
    if pick is None:
        levels = [[c for c in free if c["n"] <= 2]] + [[c for c in free if c["n"] == n]
                                                         for n in sorted({c["n"] for c in free if c["n"] > 2})]
        for lv in levels:
            ok = [c for c in lv if c["ok"]]
            if ok:
                pick, sure = max(ok, key=lambda c: (c["score"], -len(c["text"]))), True
                break
    if pick is None:
        pool = [c for c in free if c["n"] <= 2] or free
        pick = max(pool, key=lambda c: (c["shape"], c["score"], -len(c["text"])))
    # a chain: each less specific name has its words all in the next one, each more specific one all the words of
    # the one before
    def words(c):
        return set(c["key"].split())

    below, above, cur = [], [], pick
    for n in sorted({c["n"] for c in free if c["n"] < pick["n"]}, reverse=True):
        lv = [c for c in free if c["n"] == n and words(c) <= words(cur)]
        if lv:
            cur = max(lv, key=lambda c: (c["score"], -len(c["text"])))
            below.insert(0, cur)
    cur = pick
    for n in sorted({c["n"] for c in free if c["n"] > pick["n"]}):
        lv = [c for c in free if c["n"] == n and words(cur) <= words(c)]
        if lv:
            cur = max(lv, key=lambda c: (c["score"], -len(c["text"])))
            above.append(cur)
    names = below + [pick] + above
    return {"names": [_cap(c["text"]) for c in names], "pick": names.index(pick), "sure": sure,
            "key": pick["key"]}


def for_run(ws: Workspace, run_id: str, themes: list[dict]) -> dict[int, dict]:
    """theme_id -> {"names": shortest to longest, "pick": the index of the one chosen, "sure": whether the documents
    showed it is specific enough}, for the themes of one run as themes.view gives them (merges applied)."""
    merged = {x: t["theme_id"] for t in themes for x in t.get("merged_from") or []}
    ev = _Evidence(ws, run_id, merged)
    cands: dict[int, list[dict]] = {}
    kept: dict[int, str | None] = {}
    for t in themes:
        tid = t["theme_id"]
        own = " ".join((t.get("name") or "").split())
        cs = _candidates(own, ev, terms_only=t.get("name_source") == "terms")
        kept[tid] = own if t.get("name_source") == "person" and len(own) <= MAX_CHARS and key(own) else None
        if kept[tid]:  # a person's name as they wrote it, articles and all
            same = next((c for c in cs if c["key"] == key(own)), None)
            if same:
                same["text"] = own
            else:
                cs.append({"text": own, "parts": [own], "n": len(_content(own.split())), "phrase": 0,
                           "head": True, "term": False, "multi": True, "key": key(own)})
        for c in cs:
            _judge(c, ev.theme.get(tid, set()), ev)
        cands[tid] = cs
    # the theme a name fits best keeps it: first pass without others, then in order of how well the pick fits
    first = {tid: _ladder(cs, set(), kept[tid]) for tid, cs in cands.items()}

    def strength(tid):  # a name a person gave keeps it first, then the names the documents showed specific
        f = first[tid]
        if not f:
            return (0, 0, 0.0)
        c = next(c for c in cands[tid] if c["key"] == f["key"])
        return (1 if kept[tid] and f["sure"] else 0, 1 if f["sure"] else 0, c["score"])

    out: dict[int, dict] = {}
    taken: set[str] = set()
    for tid in sorted(cands, key=strength, reverse=True):
        lad = _ladder(cands[tid], taken, kept[tid])
        if lad is None:  # every name taken: the theme's own name, cut before a word, with a number if need be
            base = _cap(cut(next(t.get("name") or "" for t in themes if t["theme_id"] == tid)))
            base = base if key(base) else f"Theme {tid}"  # not "And" out of "and of the"
            text, k = base, 2
            while not key(text) or key(text) in taken:
                text = f"{cut(base, MAX_CHARS - len(f' ({k})')) or 'Theme'} ({k})"
                k += 1
            lad = {"names": [text], "pick": 0, "sure": False, "key": key(text)}
        taken.add(lad["key"])
        out[tid] = {k: v for k, v in lad.items() if k != "key"}
    return out
