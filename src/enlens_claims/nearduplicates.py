"""Near-duplicate hypotheses (0.18, roadmap N1), without AI.

Two lines of a list that say nearly the same are pointed out before checking ("Lines 1 and 2 are very close: check
them as one?"), and so is a hypothesis checked before in the project that says nearly the same, a colleague's too (one
they shared, which came in through the shared folder or the storage space). An offer, never a merge: the page asks.

**How close.** Each sentence becomes its set of key words: `textutil.tokens` (no stop words, the light stemmer), each
cut once more to a root (`root`: "indicators", "indicates" and "indication" are all "indic"; "observable" and
"observed" are "observ"), less a few words that only join ("based", "during"). Two sentences are close when their sets
share at least MIN_SHARED roots and their Jaccard index (shared / all) is at least THRESHOLD where one sentence's key
words are all in the other's (it adds a word or two: "Remote work increases productivity" and "Remote work increases
employee productivity", 3 of 4), or at least THRESHOLD_SWAP where each has words the other lacks. One word swapped in
a short sentence is most often the claim itself: "Mindfulness training reduces stress among nurses" and "...improves
sleep among nurses" share 3 of 5 (0.6) and are not close; neither are "Teachers' feedback improves student motivation
in secondary schools" and "...student achievement in secondary schools" (5 of 7, 0.71). In a long sentence one word
swapped leaves it very close (6 of 8, 0.75). Same-topic hypotheses that claim different things share the topic's words
but not the rest ("Screen time reduces sleep quality in adolescents" and "Screen time increases anxiety in
adolescents": 3 of 6). Synonyms ("teenagers", "adolescents") are not known: no AI, no thesaurus.

**What keeps close lines apart.** Words that set how much a sentence claims are left out of the comparison and
compared on their own (`marks`): its strength (*is associated with*, *can be observed*, *indicates*, *predicts*,
*causes*), a negation (*not*, *never*, *no*) and a direction (*increases*, *reduces*). Lines whose other words are
close but whose marks differ (one says *indicates*, the other *predicts*; one *increases*, the other *reduces*; one is
negated) are said to be close but different (`differ`: the words that differ), and the page offers no merge. A
strength or a direction only one of the two names does not count as a difference ("increases" and "causes more" are
the same claim worded twice); a negation does.

Nothing is stored: the earlier hypotheses are read each time (a project has hundreds at most; this is cheap).
"""
from __future__ import annotations

import re
from functools import lru_cache

from .textutil import _TOKEN_RE, fast_normalise, is_stop, stem

THRESHOLD = 0.6        # Jaccard index from which two sentences are close, when one's key words are all in the other's
THRESHOLD_SWAP = 0.75  # and when each has key words the other lacks (a word swapped)
MIN_SHARED = 2      # and at least this many key words in common (two short lines that share one word are not close)
MAX_BEFORE = 3      # earlier hypotheses offered per line, the closest first

# endings cut once more after the stemmer, for comparing only (a root need not be a word): the longest first
_ENDINGS = ("abl", "ibl", "ion", "iv", "or", "er", "al", "ly", "at", "ic", "ous")

# words that join a sentence and say nothing of its claim, besides textutil's stop words
_GLUE = {"bas", "dur", "among", "across", "within", "through", "toward", "towards", "whether", "eith", "rath", "upon"}

# the marks: how much a sentence claims. Written as words; compared as roots.
_STRENGTH = {
    "associate": ("associated", "association", "correlated", "correlation", "correlates", "linked", "related",
                  "relationship", "connected", "accompanied"),
    "observe": ("observable", "observed", "observation", "visible", "seen", "detectable", "detected", "noticeable",
                "apparent", "appear", "appears"),
    "indicate": ("indicate", "indicates", "indicator", "indicators", "indication", "suggest", "suggests", "signal",
                 "signals", "sign", "signs", "marker", "markers", "reflect", "reflects"),
    "predict": ("predict", "predicts", "predicted", "prediction", "predictive", "predictor", "forecast", "forecasts",
                "anticipate", "anticipates"),
    "cause": ("cause", "causes", "caused", "causal", "lead", "leads", "drive", "drives", "driven", "determine",
              "determines", "produce", "produces"),
}
_DIRECTION = {
    "more": ("increase", "increases", "increased", "raise", "raises", "raised", "higher", "greater", "improve",
             "improves", "improved", "boost", "boosts", "grow", "grows", "rise", "rises", "strengthen", "strengthens",
             "enhance", "enhances", "accelerate", "accelerates"),
    "less": ("decrease", "decreases", "decreased", "reduce", "reduces", "reduced", "reduction", "lower", "less",
             "fewer", "declines", "decline", "worsen", "worsens", "weaken", "weakens", "fall", "falls", "drop",
             "drops", "lessen", "lessens", "slow", "slows", "hinder", "hinders", "impair", "impairs"),
}
_NOT_RE = re.compile(r"\bcannot\b|n['’]t\b", re.I)  # "doesn't", "can’t": the tokens split them
_NEGATION = {"not", "no", "never", "without", "cannot", "none", "neither", "nor", "lack", "lacks", "fails", "fail"}


@lru_cache(maxsize=65536)
def root(word: str) -> str:
    """A (normalised) word cut to its root, for comparing only: the stemmer's word, less one ending of `_ENDINGS`
    while at least four letters remain (at most twice): 'indicators' -> 'indicator' -> 'indicat' -> 'indic'."""
    r = stem(word)
    for _ in range(2):
        for e in _ENDINGS:
            if r.endswith(e) and len(r) - len(e) >= 4:
                r = r[: -len(e)]
                break
        else:
            break
    return r


def _table(groups: dict[str, tuple[str, ...]]) -> dict[str, str]:
    return {root(w): label for label, words in groups.items() for w in words}


_STRENGTH_ROOTS = _table(_STRENGTH)
_DIRECTION_ROOTS = _table(_DIRECTION)
_MARK_ROOTS = set(_STRENGTH_ROOTS) | set(_DIRECTION_ROOTS)


class Sentence:
    """A sentence as it is compared: its key words (`keys`), and its marks (`strength`, `direction`, `negated`) with
    the words that carry them (`said`: {label: the last word that says it, most often the verb: "Dementia indicators
are observable" says "observable"})."""
    __slots__ = ("text", "keys", "strength", "direction", "negated", "said")

    def __init__(self, text: str):
        self.text = text
        self.strength: set[str] = set()
        self.direction: set[str] = set()
        self.said: dict[str, str] = {}
        keys = set()
        words = _TOKEN_RE.findall(fast_normalise(text or ""))
        nt = _NOT_RE.search(text or "")
        self.negated = bool(nt) or any(w in _NEGATION for w in words)
        if self.negated:
            self.said["not"] = next((w for w in words if w in _NEGATION), None) or (nt.group(0).lower() if nt else "not")
        for w in words:
            r = root(w)
            if r in _STRENGTH_ROOTS:
                self.strength.add(_STRENGTH_ROOTS[r])
                self.said[_STRENGTH_ROOTS[r]] = w
            elif r in _DIRECTION_ROOTS:
                self.direction.add(_DIRECTION_ROOTS[r])
                self.said[_DIRECTION_ROOTS[r]] = w
            elif not is_stop(w) and r not in _GLUE and not r.isdigit():
                keys.add(r)
        self.keys = frozenset(keys)


def similarity(a: Sentence, b: Sentence) -> float:
    """The Jaccard index of two sentences' key words, 0 when they share fewer than MIN_SHARED (1 for the same text)."""
    if " ".join(a.text.lower().split()) == " ".join(b.text.lower().split()):
        return 1.0
    shared = len(a.keys & b.keys)
    if shared < MIN_SHARED:
        return 0.0
    return shared / len(a.keys | b.keys)


def differ(a: Sentence, b: Sentence) -> list[str]:
    """The words that make two close sentences claim different things ([] when none): each one's strength when both
    name one and they are not the same, the same for a direction, and a negation in one only."""
    out: list[str] = []

    def word(s: Sentence, labels: set[str]) -> str:  # the last of them in the sentence
        ws = [s.said[x] for x in labels]
        low = (s.text or "").lower()
        return max(ws, key=lambda w: low.rfind(w))

    for fam in ("strength", "direction"):
        x, y = getattr(a, fam), getattr(b, fam)
        if x and y and x != y:
            out += [word(a, x - y or x), word(b, y - x or y)]
    if a.negated != b.negated:
        out.append(a.said.get("not") or b.said.get("not") or "not")
    return out


def is_close(a: Sentence, b: Sentence, score: float | None = None) -> bool:
    """Whether two sentences say nearly the same, by their key words (see the module's notes)."""
    s = similarity(a, b) if score is None else score
    if s >= THRESHOLD_SWAP or s == 1.0:
        return True
    return s >= THRESHOLD and (a.keys <= b.keys or b.keys <= a.keys)


def close(a: str | Sentence, b: str | Sentence) -> dict | None:
    """{"score", "differ"} when two sentences are close, else None."""
    sa = a if isinstance(a, Sentence) else Sentence(a)
    sb = b if isinstance(b, Sentence) else Sentence(b)
    s = similarity(sa, sb)
    if not is_close(sa, sb, s):
        return None
    return {"score": round(s, 3), "differ": differ(sa, sb)}


def in_list(lines: list[str]) -> list[dict]:
    """The close pairs of a list: [{"a", "b" (0-based, a < b), "score", "differ"}], in the list's order."""
    ss = [Sentence(t) for t in lines]
    out = []
    for i in range(len(ss)):
        for j in range(i + 1, len(ss)):
            c = close(ss[i], ss[j])
            if c:
                out.append({"a": i, "b": j, **c})
    return out


def _owners(ws) -> dict[str, str | None]:
    """{hyp_id: who checked it (a person id)}: the item's owner (sharing.py), else the research log's *added* entry."""
    from . import sharing

    cx = ws._conn()
    out: dict[str, str | None] = {}
    for hid, pid in cx.execute("SELECT subject_id, person_id FROM research_log WHERE kind='check-added' "
                               "AND subject_kind='check' ORDER BY at"):
        if hid and pid:
            out.setdefault(hid, pid)
    for (kind, key), r in sharing.rows(cx).items():
        if kind == "check" and r["owner"]:
            out[key] = r["owner"]
    return out


def checked_before(ws, lines: list[str], skip: set[str] | None = None) -> list[list[dict]]:
    """For each line, the hypotheses checked before in the project that are close to it, the closest first (at most
    MAX_BEFORE): [{"hyp_id", "text", "created_at", "score", "differ", "who": {"id", "name", "mine"} | None}]. A
    colleague's check they took back (withdrawn) is not offered; neither is a close one that claims something
    different (`differ`): its answer is not this line's. `skip`: hypothesis ids left out (the one being checked)."""
    from . import people, sharing

    me = people.me()
    names = people.names(ws)
    marks = sharing.rows(ws._conn())
    owners = _owners(ws)
    earlier = []
    for hid, text, at in ws.query("SELECT hyp_id, text, created_at FROM hypotheses WHERE text IS NOT NULL"):
        if skip and hid in skip:
            continue
        mark = marks.get(("check", hid))
        owner = owners.get(hid) or (None if mark else me)  # no row: made here, by this copy's person
        if mark and mark["state"] == "withdrawn" and owner != me:
            continue
        earlier.append((hid, text, at, owner, Sentence(text)))
    out = []
    for line in lines:
        s = Sentence(line)
        found = []
        for hid, text, at, owner, e in earlier:
            sc = similarity(s, e)
            if not is_close(s, e, sc) or differ(s, e):
                continue
            who = None
            if owner:
                who = {"id": owner, "name": "you" if owner == me else names.get(owner, "a colleague"),
                       "mine": owner == me}
            found.append({"hyp_id": hid, "text": text, "created_at": at, "score": round(sc, 3), "differ": [],
                          "who": who})
        found.sort(key=lambda x: x["created_at"] or "", reverse=True)  # the latest first, then the closest
        found.sort(key=lambda x: -x["score"])
        out.append(found[:MAX_BEFORE])
    return out


def similar(ws, lines: list[str]) -> dict:
    """What the Hypotheses page shows under the box: {"pairs": in_list(lines), "before": checked_before(ws, lines)}."""
    clean = [" ".join(str(t or "").split()) for t in lines]
    return {"pairs": in_list(clean) if len(clean) > 1 else [], "before": checked_before(ws, clean)}

