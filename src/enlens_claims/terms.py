"""The term index (F3, F6): a glossary of the corpus, the concepts it is grouped into, and key terms.

No model is needed to build it. After documents are added (and whenever the corpus version changes) the body
passages are read once:

- Candidates are runs of one to four words (`textutil.token_spans`, the checker's own word rule and stemmer) that
  neither start nor end with a stop word or a number, and do not cross punctuation.
- A candidate is kept when it occurs at least MIN_TF times in at least MIN_DF documents. Kept candidates are ranked
  by C-value (Frantzi et al.), which favours a whole term ("proton exchange membrane") over its fragments
  ("exchange membrane"); the best MAX_TERMS become terms, each with every place it occurs (`term_mentions`).
- The stemmer already merges plural and inflected forms. Abbreviations the text defines ("polymer electrolyte
  membrane (PEM)") are found by the Schwartz–Hearst rule and linked to their long form.
- With an embedding model (and numpy), the labels of the most frequent terms are embedded and pairs that are each
  other's nearest neighbour above a cosine threshold are proposed as "possibly the same": a person accepts or
  rejects them.

A concept is a set of terms joined by "same" links from a person, the model (`link` tasks) or the abbreviation rule.
Links are kept by term id (a hash of the term's stems), so they survive a rebuild of the index.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from typing import Callable

from .store import Workspace, now
from .textutil import fast_normalise, is_stop, stem, token_spans

MIN_TF = 3
MIN_DF = 2
MAX_N = 4
MAX_TERMS = 6000
MEANING_TERMS = 3000      # terms embedded for "possibly the same"
MEANING_MIN = 0.85        # cosine from which two mutual nearest neighbours are proposed
_JOIN = re.compile(r"[\s\-‐‑]*")   # what may stand between two words of a term
LINK_RELATIONS = ("same", "broader", "narrower", "related", "different")
_INVERSE = {"broader": "narrower", "narrower": "broader"}


def term_id(stems: str) -> str:
    return "t" + hashlib.sha1(stems.encode()).hexdigest()[:11]


def _runs(text: str, toks: list) -> list[list]:
    """Token runs not interrupted by punctuation (spaces and hyphens may join words of a term)."""
    runs, cur, prev = [], [], None
    for tk in toks:
        if prev is not None and not _JOIN.fullmatch(text[prev[1]:tk[0]]):
            runs.append(cur)
            cur = []
        cur.append(tk)
        prev = tk
    if cur:
        runs.append(cur)
    return runs


# Everyday words of reports that are not terms on their own ("including", "support", "based"): a one-word
# candidate that is one of them is left out of the glossary. They still count inside longer terms ("energy access").
GENERAL = frozenset("""
able about above according across actual actually add added adding addition additional address addressed
affect affected affecting again against ago agree ahead aim aimed aims allow allowed allowing allows almost alone
along already although always among amount amounts analysed analysis annual another answer anything apart appear
applied apply approach approaches appropriate approximately area areas around aspect aspects associated assume
assumed attention available average avoid away back based basis become becomes becoming before began begin
behind being believe below best better beyond big billion bring bringing broad build building built call called
can't carried case cases cause caused central certain change changed changes changing chapter clear clearly close
come comes coming common compared comparison complete completely concern concerned concerns condition conditions
consider considerable considered considering consistent contain contains context continue continued contrast
contribute contribution could create created creating critical current currently data date day days deal decade
decades decided decision deep define defined degree described despite detail detailed details develop developed
developing different difficult directly discuss discussed done down due during each early easy effect effective
effectively effects effort efforts either else enable enabled enables end enough ensure ensuring entire especially
essential establish established estimate estimated estimates even event events eventually ever every evidence
example examples except exist existing expect expected experience explain extent face fact factor factors far
feature features figure figures final finally find finding findings first focus focused follow followed following
form forms forward found four full fully further future gain general generally get getting give given gives giving
go goal going good great greater greatly group groups grow growing growth half hand happen hard having help helps
here high higher highest highly hold however huge idea identified identify impact impacts implemented implications
importance important improve improved improving include included includes including increase increased increases
increasing increasingly indeed indicate indicated indicates information initial instance instead interest into
introduced involve involved involves issue issues item items keep key kind known lack large largely larger largest
last late later latest lead leading leads least leave left less level levels like likely limited line link linked
list little long longer look looking low lower lowest made main mainly major make makes making manner many mean
means measure measures meet meeting method methods might million mind minimum moreover move moving much need
needed needs new next note noted number numbers objective objectives obtain obtained often old one ones open
opportunity order others otherwise outcome outcomes output overall paper part particular particularly parts past
per percent perhaps period periods place play plays point points possible potential potentially present presented
presents previous primarily primary principle problem problems process processes produce produced provide provided
provides providing purpose purposes put quality question questions quite range rapid rapidly rate rates rather
reach reached real really reason reasons recent recently reduce reduced reducing regard regarding related relative
relatively relevant remain remaining remains report reported reports represent represents require required
requirement requirements requires research respect respectively rest result resulting results review right rise
risk role run said same scale scope second section see seen sense series serve set several shall share short show
showed shown shows side significant significantly similar simple simply since single size small smaller so some
something sometimes soon source sources specific specifically stage stages standard start started state stated
states step steps still strong strongly study studies subject substantial success successful such suggest
suggested suggests support supported supporting sure system systems table take taken takes taking term terms than
thing things think third though three through throughout thus time times today together top total toward towards
true turn two type types under understand understanding unit units unless until up upon usually value values
various vary very view way ways well whether whole wide widely will within without work working works world would
year years yet
accordance al annex appendix chap dr et exhibit fig figs ibid journal mr mrs ms online page pages pp table tables vol
volume yes
""".split())


_GENERAL_STEMS = frozenset(stem(w) for w in GENERAL)


def _edge_ok(word: str) -> bool:
    return not is_stop(word) and not word.isdigit() and len(word) <= 30


# 0.8: letter-spaced PDFs. Some PDFs put spaces inside words ("Elec tr oly ser" in the pilot). For the glossary and
# key terms only, adjacent pieces separated by one space are read as one word when, joined, they make a word the
# documents also write whole, and at least one piece is not a word of the documents on its own. The documents' text,
# search and quotes keep the text as read.
FRAGMENT_MAX = 6        # longest piece (letters) that may be part of a split word
FRAGMENT_PIECES = 8     # most pieces one word is joined from
_PIECE = re.compile(r"[^\W\d_]{1,%d}" % FRAGMENT_MAX)


class Joiner:
    """The corpus's whole words, to join the pieces of letter-spaced words (see FRAGMENT_MAX)."""

    def __init__(self, texts):
        self.vocab: Counter[str] = Counter()
        self.split: Counter[str] = Counter()   # how often each run of pieces stands apart ("net zero": often)
        for t in texts:
            toks = token_spans(t, keep_stop=True)
            self.vocab.update(w for _a, _b, _s, w in toks)
            for i in range(len(toks) - 1):
                if not _PIECE.fullmatch(toks[i][3]):
                    continue
                j = i + 1
                while j < len(toks) and j - i < FRAGMENT_PIECES and t[toks[j - 1][1]:toks[j][0]] == " " \
                        and _PIECE.fullmatch(toks[j][3]):
                    self.split[" ".join(x[3] for x in toks[i:j + 1])] += 1
                    j += 1

    def word(self, w: str) -> bool:
        """A piece that is a word of its own: a stop word, or a word of three letters or more the documents use."""
        return is_stop(w) or (len(w) >= 3 and self.vocab.get(w, 0) >= 3)

    def whole(self, pieces: list[str]) -> bool:
        """Whether these pieces are one word split by spaces: written whole at least as often as apart."""
        w = "".join(pieces)
        n = self.vocab.get(w, 0)
        return len(w) >= 5 and n >= 2 and n >= self.split.get(" ".join(pieces), 0) and \
            not all(self.word(p) for p in pieces)

    def join(self, text: str, toks: list) -> list:
        out = []
        i, n = 0, len(toks)
        while i < n:
            best = None
            if _PIECE.fullmatch(toks[i][3]):
                j = i + 1
                while j < n and j - i < FRAGMENT_PIECES and text[toks[j - 1][1]:toks[j][0]] == " " \
                        and _PIECE.fullmatch(toks[j][3]):
                    if self.whole([t[3] for t in toks[i:j + 1]]):
                        best = j
                    j += 1
            if best is None:
                out.append(toks[i])
                i += 1
                continue
            whole = "".join(t[3] for t in toks[i:best + 1])
            out.append((toks[i][0], toks[best][1], stem(whole), whole))
            i = best + 1
        return out


def _grams(text: str, joiner: Joiner | None = None):
    """(start, end, stems key) of every candidate in a text. With a `joiner`, letter-spaced words are read whole."""
    toks = token_spans(text, keep_stop=True)
    if joiner is not None:
        toks = joiner.join(text, toks)
    for run in _runs(text, toks):
        n = len(run)
        for i in range(n):
            if not _edge_ok(run[i][3]):
                continue
            for j in range(i, min(n, i + MAX_N)):
                if not _edge_ok(run[j][3]):
                    continue
                yield run[i][0], run[j][1], " ".join(x[2] for x in run[i:j + 1])


def status(ws: Workspace) -> dict:
    built = ws.meta("terms_corpus_version")
    n = int(ws.scalar("SELECT COUNT(*) FROM terms") or 0)
    return {"built": built is not None, "stale": built is not None and built != ws.corpus_version(),
            "missing": built is None, "terms": n, "built_at": ws.meta("terms_built_at"),
            "concepts": int(ws.scalar("SELECT COUNT(*) FROM concepts") or 0)}


def ensure(ws: Workspace, **kw) -> dict:
    """Build the index when it is missing or out of date (the documents changed); otherwise do nothing."""
    st = status(ws)
    if st["built"] and not st["stale"]:
        return st
    return build(ws, **kw)


EDGE_CHARS = 160      # a page's running head is in the first characters of its first passage, its foot in the last


def _at_edge(a: int, b: int, e: tuple[int, int]) -> bool:
    return b <= e[0] or a >= e[1]


def running_heads(rows, joiner: Joiner | None = None) -> tuple[dict[str, tuple[int, int]], set[tuple[str, str]]]:
    """Running heads and feet ("Journal of Energy in Southern Africa • Vol 33", "IEA. All rights reserved"): the
    candidate terms found at the top or bottom of at least 3 pages, and of at least a third of the pages, of one
    document. Returns {passage_id: (head end, foot start)} for the first and last passage of each page, and the
    (doc_id, term key) pairs that are running heads; their mentions there are left out of the glossary (search still
    finds them)."""
    first: dict[tuple, dict] = {}
    lastp: dict[tuple, dict] = {}
    pages: dict[str, set] = defaultdict(set)
    for r in rows:
        if r["page"] is None:
            continue
        k = (r["doc_id"], r["page"])
        first.setdefault(k, r)
        lastp[k] = r
        pages[r["doc_id"]].add(r["page"])
    edges: dict[str, list[int]] = {}
    for k, r in first.items():
        edges.setdefault(r["passage_id"], [0, 10 ** 9])[0] = EDGE_CHARS
    for k, r in lastp.items():
        edges.setdefault(r["passage_id"], [0, 10 ** 9])[1] = max(0, len(r["text"]) - EDGE_CHARS)
    seen: dict[tuple[str, str], set] = defaultdict(set)
    for r in rows:
        e = edges.get(r["passage_id"])
        if not e:
            continue
        for a, b, key in _grams(r["text"], joiner):
            if _at_edge(a, b, e):
                seen[(r["doc_id"], key)].add(r["page"])
    boiler = {dk for dk, pg in seen.items() if len(pg) >= 3 and len(pg) * 3 >= len(pages[dk[0]])}
    return {pid: (e[0], e[1]) for pid, e in edges.items()}, boiler


def build(ws: Workspace, progress: Callable[[int, int], None] | None = None,
          should_stop: Callable[[], bool] | None = None, embedder=None, max_terms: int = MAX_TERMS) -> dict:
    """(Re)build the glossary of the project's body text. Takes seconds to a minute; nothing is sent anywhere."""
    rows = ws.query("SELECT passage_id, doc_id, page, start, text FROM passages WHERE section='body' ORDER BY doc_id, seq")
    version = ws.corpus_version()
    joiner = Joiner(r["text"] for r in rows)   # 0.8: letter-spaced words read whole (glossary and key terms only)
    edges, boiler = running_heads(rows, joiner)

    def grams(r):
        """The candidate terms of a passage, without the running heads and feet of its document's pages."""
        e = edges.get(r["passage_id"])
        for a, b, key in _grams(r["text"], joiner):
            if e and (r["doc_id"], key) in boiler and _at_edge(a, b, e):
                continue
            yield a, b, key

    tf: Counter[str] = Counter()
    df: Counter[str] = Counter()
    last: dict[str, str] = {}
    for n, r in enumerate(rows, 1):
        if should_stop and n % 200 == 0 and should_stop():
            raise _stopped()
        d = r["doc_id"]
        for _a, _b, key in grams(r):
            tf[key] += 1
            if last.get(key) != d:
                last[key] = d
                df[key] += 1
        if progress and n % 500 == 0:
            progress(n, 2 * len(rows))
    n_docs = len({r["doc_id"] for r in rows})
    min_df = MIN_DF if n_docs >= MIN_DF else 1   # a project of one document (a quick look) still gets its terms
    kept = {k: tf[k] for k in tf if tf[k] >= MIN_TF and df[k] >= min_df and k not in _GENERAL_STEMS}
    del last
    # C-value: log2(|a| + 1) * (f(a) - mean f of the longer kept candidates that contain a)
    containers: dict[str, list[int]] = defaultdict(list)
    for k, f in kept.items():
        parts = k.split(" ")
        if len(parts) < 2:
            continue
        subs = {" ".join(parts[i:j]) for i in range(len(parts)) for j in range(i + 1, len(parts) + 1)
                if j - i < len(parts)}
        for s in subs:
            if s in kept:
                containers[s].append(f)
    cval: dict[str, float] = {}
    for k, f in kept.items():
        n_words = k.count(" ") + 1
        nested = containers.get(k)
        cval[k] = math.log2(n_words + 1) * (f - (sum(nested) / len(nested) if nested else 0.0))
    chosen = sorted((k for k in kept if cval[k] > 0), key=lambda k: (-cval[k], k))[:max(1, int(max_terms))]
    keep = set(chosen)
    # second reading: the places of the chosen terms, their spellings, and the abbreviations the text defines
    mentions: list[tuple] = []
    spell: dict[str, Counter] = defaultdict(Counter)
    passages: Counter[str] = Counter()
    abbrev: Counter[tuple[str, str]] = Counter()
    for n, r in enumerate(rows, 1):
        if should_stop and n % 200 == 0 and should_stop():
            raise _stopped()
        text = r["text"]
        seen = set()
        for a, b, key in grams(r):
            if key in keep:
                tid = term_id(key)
                mentions.append((tid, r["passage_id"], r["doc_id"], r["start"] + a, r["start"] + b))
                spell[key][_spelling(text[a:b], joiner)] += 1
                if key not in seen:
                    seen.add(key)
                    passages[key] += 1
        if "(" in text:
            for short, long in abbreviations(text):
                abbrev[(short, long)] += 1
        if progress and n % 500 == 0:
            progress(len(rows) + n, 2 * len(rows))
    terms = []
    for k in chosen:
        label = _label(spell[k])
        terms.append((term_id(k), label, k, k.count(" ") + 1, df[k], tf[k], passages[k], round(cval[k], 3)))
    with ws.connect() as cx:
        cx.execute("DELETE FROM terms")
        cx.execute("DELETE FROM term_mentions")
        cx.executemany("INSERT INTO terms VALUES (?,?,?,?,?,?,?,?)", terms)
        cx.executemany("INSERT INTO term_mentions VALUES (?,?,?,?,?)", mentions)
        # abbreviation links: the short form and the long form, both terms of the index
        cx.execute("DELETE FROM concept_links WHERE source='abbreviation'")
        best: dict[str, tuple[int, str]] = {}
        for (short, long), c in abbrev.items():
            if c > best.get(short, (0, ""))[0]:
                best[short] = (c, long)
        n_abbr = 0
        for short, (c, long) in best.items():
            ks, kl = _key_of(short), _key_of(long)
            if not ks or not kl or ks == kl or ks not in keep or kl not in keep:
                continue
            a, b = sorted((term_id(ks), term_id(kl)))
            cx.execute("INSERT OR REPLACE INTO concept_links VALUES (?,?,?,?,?,?,?,?,?)",
                       (a, b, "same", "abbreviation", 1.0, f"{long} ({short})", short, None, now()))
            n_abbr += 1
        ws.set_meta("terms_corpus_version", version, cx)
        ws.set_meta("terms_built_at", now(), cx)
    variants = 0
    if embedder is not None:
        try:
            variants = meaning_variants(ws, embedder)
        except Exception as e:  # the glossary is useful without them; say why there are none
            ws.set_meta("terms_meaning_error", str(e)[:300])
    rebuild_concepts(ws)
    return {**status(ws), "candidates": len(kept), "mentions": len(mentions), "abbreviations": n_abbr,
            "meaning_pairs": variants}


def _spelling(span: str, joiner: Joiner | None = None) -> str:
    """How a mention is written, with a letter-spaced word written whole ("Elec tr oly ser" → "Electrolyser")."""
    span = " ".join(span.split())
    if joiner is None:
        return span
    toks = token_spans(span, keep_stop=True)
    joined = joiner.join(span, toks)
    if len(joined) == len(toks):
        return span
    out, pos = [], 0
    for a, b, _st, w in joined:
        piece = span[a:b]
        if " " in piece:
            piece = piece.replace(" ", "")
        out.append(span[pos:a] + piece)
        pos = b
    return "".join(out) + span[pos:]


def _stopped():
    from .llm import BackendError

    return BackendError("Stopped.")


def _label(spellings: Counter) -> str:
    """The spelling a reader would expect: the most frequent one, in lower case unless it is mostly written in
    capitals (an abbreviation) or as a name."""
    if not spellings:
        return ""
    top = spellings.most_common(1)[0][0]
    lower = sum(c for s, c in spellings.items() if s == s.lower())
    if lower * 2 >= sum(spellings.values()):
        return top.lower()
    return top


def _key_of(text: str) -> str | None:
    """The stems key of a phrase as the index writes it (None when it does not start and end with a content word)."""
    toks = token_spans(text, keep_stop=True)
    while toks and not _edge_ok(toks[0][3]):
        toks = toks[1:]
    while toks and not _edge_ok(toks[-1][3]):
        toks = toks[:-1]
    if not toks or len(toks) > MAX_N:
        return None
    return " ".join(t[2] for t in toks)


# ---------------------------------------------------------------------------------------------
# abbreviations (Schwartz & Hearst 2003)
# ---------------------------------------------------------------------------------------------
_PAREN = re.compile(r"\(([^()]{1,60})\)")


def _best_long_form(short: str, long: str) -> str | None:
    """The shortest end of `long` whose letters match `short` from the back, each short-form character found in
    order and the first one at the start of a word (Schwartz & Hearst's algorithm)."""
    s, l_ = len(short) - 1, len(long) - 1
    while s >= 0:
        c = short[s].lower()
        if not c.isalnum():
            s -= 1
            continue
        while (l_ >= 0 and long[l_].lower() != c) or (s == 0 and l_ > 0 and long[l_ - 1].isalnum()):
            l_ -= 1
        if l_ < 0:
            return None
        l_ -= 1
        s -= 1
    start = long.rfind(" ", 0, l_ + 1) + 1
    return long[start:].strip()


def _short_ok(s: str) -> bool:
    """A short form: 2 to 10 characters, at most two words, starting with a letter or digit, with a capital letter
    (lower-case words in brackets are explanations, not abbreviations) and not a number or a Roman numeral."""
    words = s.split()
    return (2 <= len(s) <= 10 and len(words) <= 2 and s[0].isalnum() and s[-1].isalnum()
            and any(c.isupper() for c in s) and any(c.isalpha() for c in s)
            and not re.fullmatch(r"\d+(\.\d+)?%?|[ivxlc]+|[a-z]", s.lower()))


def abbreviations(text: str) -> list[tuple[str, str]]:
    """(short form, long form) pairs defined in `text`: "long form (SF)" and, less often, "SF (long form)"."""
    out = []
    for m in _PAREN.finditer(text):
        inner = m.group(1).strip().split(";")[0].split(",")[0].strip()
        before = text[max(0, m.start() - 200):m.start()]
        before = re.split(r"[.;:!?()\[\]]", before)[-1].strip()
        if _short_ok(inner):
            words = before.split()
            n = min(len(inner) + 5, 2 * len(inner))
            cand = " ".join(words[-n:])
            long = _best_long_form(inner, cand)
            if long and len(long) > len(inner) and len(long.split()) <= MAX_N and " " in long:
                out.append((inner, long))
        else:  # "SF (long form)"
            words = before.split()
            if words and _short_ok(words[-1]) and words[-1].isupper():
                short = words[-1]
                long = _best_long_form(short, inner)
                if long and len(long) > len(short) and len(long.split()) <= MAX_N and " " in long:
                    out.append((short, long))
    return out


# ---------------------------------------------------------------------------------------------
# variants by meaning (optional)
# ---------------------------------------------------------------------------------------------
def meaning_variants(ws: Workspace, embedder, limit: int = MEANING_TERMS, threshold: float = MEANING_MIN) -> int:
    """Propose "possibly the same" for terms whose labels the embedding model places closest to each other (mutual
    nearest neighbours above `threshold`). Needs numpy; the proposals wait for a person's decision."""
    try:
        import numpy as np
    except ImportError:
        return 0
    from .embed import _unit

    rows = ws.query("SELECT term_id, label, stems FROM terms ORDER BY tf DESC, term_id LIMIT ?", (int(limit),))
    if len(rows) < 2:
        return 0
    have = {r["code"]: bytes(r["vec"]) for r in ws.query(
        "SELECT code, vec FROM code_vectors WHERE model=? AND framework='_terms'", (embedder.model,))}
    todo = [r for r in rows if r["term_id"] not in have]
    for i in range(0, len(todo), 64):
        chunk = todo[i:i + 64]
        vecs = embedder.embed([r["label"] for r in chunk])
        with ws.connect() as cx:
            cx.executemany("INSERT OR REPLACE INTO code_vectors VALUES (?,?,?,?,?)",
                           [(embedder.model, "_terms", r["term_id"], "", _unit(v).tobytes()) for r, v in zip(chunk, vecs)])
            for r, v in zip(chunk, vecs):
                have[r["term_id"]] = _unit(v).tobytes()
    ids = [r["term_id"] for r in rows]
    stems = {r["term_id"]: r["stems"].split(" ") for r in rows}
    m = np.frombuffer(b"".join(have[t] for t in ids), dtype=np.float32).reshape(len(ids), -1)
    sims = m @ m.T
    np.fill_diagonal(sims, -1.0)
    nearest = sims.argmax(axis=1)
    linked = {(r["a"], r["b"]) for r in ws.query("SELECT a, b FROM concept_links")}
    out = []
    for i, j in enumerate(nearest):
        j = int(j)
        if i < j and int(nearest[j]) == i and sims[i, j] >= threshold:
            a, b = ids[i], ids[j]
            if _nested(stems[a], stems[b]):
                continue  # "membrane" and "exchange membrane" are related by their words already
            key = tuple(sorted((a, b)))
            if key in linked:
                continue
            out.append((*key, "same", "meaning", round(float(sims[i, j]), 3), None, None, embedder.model, now()))
    with ws.connect() as cx:
        cx.execute("DELETE FROM concept_links WHERE source='meaning'")
        cx.executemany("INSERT OR REPLACE INTO concept_links VALUES (?,?,?,?,?,?,?,?,?)", out)
    return len(out)


def _nested(a: list[str], b: list[str]) -> bool:
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return any(long[i:i + len(short)] == short for i in range(len(long) - len(short) + 1))


# ---------------------------------------------------------------------------------------------
# concepts
# ---------------------------------------------------------------------------------------------
def _decisions(ws: Workspace) -> dict[tuple[str, str], dict]:
    """A person's latest decision on each link: {(a, b): {"decision": accept|reject|change, "relation"}}."""
    out = {}
    for r in ws.query("SELECT item_id, decision, corrected FROM reviews WHERE item_kind='concept_link' "
                      "ORDER BY review_id"):
        a, _, b = (r["item_id"] or "").partition("|")
        out[(a, b)] = {"decision": r["decision"], "relation": r["corrected"] or None}
    return out


def links(ws: Workspace) -> list[dict]:
    """Every link with the person's decision applied: [{a, b, relation, source, confidence, confirmed, ...}]."""
    dec = _decisions(ws)
    out = []
    for r in ws.query("SELECT * FROM concept_links ORDER BY a, b, source"):
        d = dict(r)
        p = dec.get((d["a"], d["b"]))
        d["decision"] = p["decision"] if p else None
        if p and p["decision"] == "reject":
            d["relation_effective"] = None
        elif p and p["decision"] == "change" and p["relation"]:
            d["relation_effective"] = p["relation"]
        else:
            d["relation_effective"] = d["relation"]
        d["confirmed"] = d["source"] in ("person", "abbreviation") or bool(p and p["decision"] in ("accept", "change")) \
            or (d["source"] == "model" and (d["confidence"] or 0) >= 0.6)
        out.append(d)
    return out


def _groups(ws: Workspace) -> dict[str, str]:
    """term_id -> concept_id (the smallest term id of its group) for terms joined by confirmed 'same' links."""
    parent: dict[str, str] = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    for lk in links(ws):
        if lk["relation_effective"] == "same" and lk["confirmed"]:
            for t in (lk["a"], lk["b"]):
                parent.setdefault(t, t)
            ra, rb = find(lk["a"]), find(lk["b"])
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    return {t: find(t) for t in list(parent)}


def rebuild_concepts(ws: Workspace) -> int:
    """Write the concepts (groups of two or more terms of the index) to `concepts` and `concept_terms`."""
    groups = _groups(ws)
    terms = {r["term_id"]: dict(r) for r in ws.query("SELECT term_id, label, tf, n_words FROM terms")}
    members: dict[str, list[str]] = defaultdict(list)
    for t, c in groups.items():
        if t in terms:
            members[c].append(t)
    abbr = {(r["a"], r["b"]): r for r in ws.query("SELECT a, b, quote_a FROM concept_links WHERE source='abbreviation'")}
    rows, cterms = [], []
    for c, ts in members.items():
        if len(ts) < 2:
            continue
        cid = "c" + min(ts)[1:]
        rows.append((cid, _concept_label([terms[t] for t in ts], abbr)))
        for t in ts:
            cterms.append((cid, t, "group"))
    with ws.connect() as cx:
        cx.execute("DELETE FROM concepts")
        cx.execute("DELETE FROM concept_terms")
        cx.executemany("INSERT INTO concepts VALUES (?,?)", rows)
        cx.executemany("INSERT INTO concept_terms VALUES (?,?,?)", cterms)
    return len(rows)


def _concept_label(ts: list[dict], abbr: dict) -> str:
    """The most frequent wording of two words or more (a single word is often too general to name a concept: "home"
    for "remote work"); "long form (ABBR)" when the group holds an abbreviation and its long form."""
    ids = {t["term_id"] for t in ts}
    for (a, b), r in abbr.items():
        if a in ids and b in ids and r["quote_a"]:
            return r["quote_a"]
    return max(ts, key=lambda t: ((t.get("n_words") or 1) > 1, t["tf"], -len(t["label"])))["label"]


def concept_of(ws: Workspace, term: str) -> list[str]:
    """The term ids of the concept a term belongs to (just the term when it is in no group)."""
    row = ws.query("SELECT concept_id FROM concept_terms WHERE term_id=?", (term,))
    if not row:
        return [term]
    return [r[0] for r in ws.query("SELECT term_id FROM concept_terms WHERE concept_id=?", (row[0][0],))]


def find_term(ws: Workspace, text: str) -> str | None:
    """The term id for a typed name or word ("PEM electrolysis", "electrolysers"): its stems, or failing that the
    best term containing its words."""
    key = _key_of(text)
    if key:
        tid = term_id(key)
        if ws.scalar("SELECT 1 FROM terms WHERE term_id=?", (tid,)):
            return tid
    words = [t[2] for t in token_spans(text)]
    if not words:
        return None
    best = None
    for r in ws.query("SELECT term_id, stems, tf FROM terms WHERE stems LIKE ? ORDER BY tf DESC LIMIT 200",
                      (f"%{words[0]}%",)):
        st = r["stems"].split(" ")
        if all(w in st for w in words):
            if best is None or (len(st), -r["tf"]) < best[0]:
                best = ((len(st), -r["tf"]), r["term_id"])
    return best[1] if best else None


def glossary(ws: Workspace, q: str | None = None, offset: int = 0, limit: int = 100, sort: str = "docs") -> dict:
    """The concepts and the terms in no concept, sorted by the number of documents they occur in.

    Each entry: {term_id (its most frequent term, for links), concept, label, wordings, documents, passages,
    mentions}."""
    terms = [dict(r) for r in ws.query("SELECT term_id, label, tf FROM terms")]
    in_concept: dict[str, str] = {r["term_id"]: r["concept_id"] for r in ws.query("SELECT * FROM concept_terms")}
    labels = {r["concept_id"]: r["label"] for r in ws.query("SELECT * FROM concepts")}
    entries: dict[str, dict] = {}
    for t in sorted(terms, key=lambda t: -t["tf"]):
        cid = in_concept.get(t["term_id"])
        key = cid or t["term_id"]
        e = entries.setdefault(key, {"term_id": t["term_id"], "concept": cid, "label": labels.get(cid, t["label"]),
                                     "wordings": [], "mentions": 0})
        e["wordings"].append(t["label"])
        e["mentions"] += t["tf"]
    docs: dict[str, set] = defaultdict(set)
    for r in ws.query("SELECT DISTINCT term_id, doc_id FROM term_mentions"):
        docs[in_concept.get(r["term_id"]) or r["term_id"]].add(r["doc_id"])
    pas = {r["term_id"]: r["n"] for r in ws.query("SELECT term_id, passages AS n FROM terms")}
    for r in ws.query("SELECT ct.concept_id, COUNT(DISTINCT m.passage_id) AS n FROM term_mentions m JOIN concept_terms ct "
                      "ON ct.term_id=m.term_id GROUP BY ct.concept_id"):
        pas[r["concept_id"]] = r["n"]
    for key, e in entries.items():
        e["documents"] = len(docs.get(key, ()))
        e["passages"] = pas.get(key, 0)
    items = list(entries.values())
    if q:
        ql = fast_normalise(q)
        qs = {t[2] for t in token_spans(q)}
        items = [e for e in items if any(ql in fast_normalise(w) for w in e["wordings"]) or
                 (qs and any(qs <= {t[2] for t in token_spans(w)} for w in e["wordings"]))]
    key = {"docs": lambda e: (-e["documents"], -e["mentions"], e["label"]),
           "mentions": lambda e: (-e["mentions"], e["label"]),
           "name": lambda e: (e["label"].lower(),)}.get(sort)
    if key is None:
        raise ValueError("sort must be docs, mentions or name.")
    items.sort(key=key)
    offset, limit = max(0, int(offset)), max(1, min(int(limit), 500))
    return {"total": len(items), "offset": offset, "limit": limit, "items": items[offset:offset + limit],
            **status(ws)}


def card(ws: Workspace, term: str, offset: int = 0, limit: int = 50, with_references: bool = False) -> dict:
    """Everything about the concept of one term: its wordings, the documents that discuss it (with counts and the
    first page), the passages as concordance lines, and related concepts (the same, broader, narrower, or often
    mentioned together)."""
    from .claimcheck import locate
    from .concordance import _context

    if not ws.scalar("SELECT 1 FROM terms WHERE term_id=?", (term,)):
        raise KeyError(term)
    ids = concept_of(ws, term)
    q = ",".join("?" * len(ids))
    members = [dict(r) for r in ws.query(f"SELECT * FROM terms WHERE term_id IN ({q}) ORDER BY tf DESC", ids)]
    cid = ws.scalar("SELECT concept_id FROM concept_terms WHERE term_id=?", (term,))
    label = ws.scalar("SELECT label FROM concepts WHERE concept_id=?", (cid,)) if cid else members[0]["label"]
    all_links = links(ws)
    member_set = set(ids)
    how = {}
    for lk in all_links:
        if lk["relation_effective"] == "same" and lk["confirmed"] and (lk["a"] in member_set or lk["b"] in member_set):
            for t in (lk["a"], lk["b"]):
                how.setdefault(t, set()).add(lk["source"])
    joins: dict[str, list] = {}
    for lk in all_links:
        if lk["relation_effective"] == "same" and lk["confirmed"] and lk["a"] in member_set and lk["b"] in member_set:
            for t in (lk["a"], lk["b"]):
                joins.setdefault(t, []).append({"a": lk["a"], "b": lk["b"], "source": lk["source"],
                                                "decision": lk["decision"]})
    wordings = [{"term_id": m["term_id"], "label": m["label"], "mentions": m["tf"], "documents": m["df"],
                 "joined_by": sorted(how.get(m["term_id"], ())) if len(members) > 1 else [],
                 "joins": joins.get(m["term_id"], []) if len(members) > 1 else []} for m in members]
    # documents
    docs = []
    for r in ws.query(f"SELECT m.doc_id, d.title, COUNT(*) AS n, COUNT(DISTINCT m.passage_id) AS p, MIN(m.start) AS first "
                      f"FROM term_mentions m JOIN documents d ON d.doc_id=m.doc_id WHERE m.term_id IN ({q}) "
                      "GROUP BY m.doc_id ORDER BY n DESC, d.title", ids):
        end = ws.scalar(f"SELECT MAX(end) FROM term_mentions WHERE doc_id=? AND start=? AND term_id IN ({q})",
                        (r["doc_id"], r["first"], *ids))
        docs.append({"doc_id": r["doc_id"], "title": r["title"] or "", "mentions": r["n"], "passages": r["p"],
                     "first": r["first"], "first_end": end})
    if docs:  # the first page (or paragraph) where each document mentions it
        firsts = {}
        for d in docs:
            pid = ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? AND start<=? ORDER BY start DESC LIMIT 1",
                            (d["doc_id"], d["first"]))
            if pid:
                firsts[d["doc_id"]] = (pid, d["first"])
        where = locate(ws, [(doc, pid, off) for doc, (pid, off) in firsts.items()])
        for d in docs:
            d["first_location"] = (where.get(d["doc_id"]) or {}).get("location") or ""
    refs = None
    if with_references:
        from .references import concept_reference_counts

        refs = concept_reference_counts(ws, [m["label"] for m in members])
        for d in docs:
            d["references"] = refs.get(d["doc_id"], 0)
    # passages as concordance lines
    total = int(ws.scalar(f"SELECT COUNT(*) FROM term_mentions WHERE term_id IN ({q})", ids) or 0)
    page = ws.query(f"SELECT m.term_id, m.passage_id, m.doc_id, m.start, m.end, p.text, p.start AS pstart, p.page, "
                    f"d.title FROM term_mentions m JOIN passages p ON p.passage_id=m.passage_id JOIN documents d "
                    f"ON d.doc_id=m.doc_id WHERE m.term_id IN ({q}) ORDER BY d.title, p.seq, m.start LIMIT ? OFFSET ?",
                    (*ids, max(1, min(int(limit), 500)), max(0, int(offset))))
    where = locate(ws, [(i, r["passage_id"], r["start"]) for i, r in enumerate(page)])
    lines = []
    for i, r in enumerate(page):
        a, b = r["start"] - r["pstart"], r["end"] - r["pstart"]
        left, right = _context(r["text"], a, b, 60)
        lines.append({"n": offset + i + 1, "doc_id": r["doc_id"], "title": r["title"] or "", "passage_id": r["passage_id"],
                      "page": r["page"], "location": (where.get(i) or {}).get("location") or "", "left": left,
                      "node": " ".join(r["text"][a:b].split()), "right": right, "marks": [],
                      "start": r["start"], "end": r["end"]})
    related = _related(ws, ids, all_links)
    out = {"term_id": term, "concept_id": cid, "label": label, "wordings": wordings, "documents": docs,
           "mentions": total, "passages": int(ws.scalar(f"SELECT COUNT(DISTINCT passage_id) FROM term_mentions WHERE "
                                                         f"term_id IN ({q})", ids) or 0),
           "lines": lines, "offset": offset, "limit": limit, "related": related,
           "suggested_wordings": suggested_wordings(ws, term), **{"stale": status(ws)["stale"]}}
    if refs is not None:
        out["references_total"] = sum(refs.values())
    return out


def _related(ws: Workspace, ids: list[str], all_links: list[dict]) -> dict:
    """Links to other concepts (same-but-unconfirmed, broader, narrower, related, different) and the concepts most
    often mentioned in the same passages (lift against chance, at least 3 passages together)."""
    member = set(ids)
    info = {r["term_id"]: dict(r) for r in ws.query("SELECT term_id, label, stems, passages FROM terms")}
    grp = {r["term_id"]: r["concept_id"] for r in ws.query("SELECT * FROM concept_terms")}
    linked = []
    for lk in all_links:
        if (lk["a"] in member) == (lk["b"] in member):
            continue
        other, mine = (lk["b"], lk["a"]) if lk["a"] in member else (lk["a"], lk["b"])
        if other not in info:
            continue
        rel = lk["relation_effective"]
        if rel is None:
            continue
        if lk["a"] != mine:  # relations are stored from a to b: seen from this concept, broader means narrower
            rel = _INVERSE.get(rel, rel)
        state = "confirmed" if lk["confirmed"] else "proposed"
        linked.append({"term_id": other, "label": info[other]["label"], "relation": rel, "source": lk["source"],
                       "state": state, "confidence": lk["confidence"], "quote_a": lk["quote_a"], "quote_b": lk["quote_b"],
                       "a": lk["a"], "b": lk["b"], "decision": lk["decision"],
                       "this_term": mine})
    # co-occurrence
    n_pass = int(ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'") or 1)
    q = ",".join("?" * len(ids))
    mine = int(ws.scalar(f"SELECT COUNT(DISTINCT passage_id) FROM term_mentions WHERE term_id IN ({q})", ids) or 0)
    co = []
    if mine:
        rows = ws.query(f"SELECT term_id, COUNT(DISTINCT passage_id) AS n FROM term_mentions WHERE passage_id IN "
                        f"(SELECT passage_id FROM term_mentions WHERE term_id IN ({q})) GROUP BY term_id", ids)
        member_stems = [info[t]["stems"].split(" ") for t in ids if t in info]
        by_concept: dict[str, dict] = {}
        for r in rows:
            t = r["term_id"]
            if t in member or t not in info or r["n"] < 3 or info[t]["passages"] < 5:
                continue
            st = info[t]["stems"].split(" ")
            if any(_nested(st, m) for m in member_stems):
                continue
            lift = r["n"] * n_pass / (mine * info[t]["passages"])
            if lift < 1.5:
                continue
            key = grp.get(t, t)
            e = {"term_id": t, "label": info[t]["label"], "together": r["n"], "lift": round(lift, 2)}
            if key not in by_concept or by_concept[key]["together"] < e["together"]:
                by_concept[key] = e
        co = sorted(by_concept.values(), key=lambda e: (-(e["lift"] * math.log(1 + e["together"])), e["label"]))[:15]
    return {"links": linked, "together": co}


def suggested_wordings(ws: Workspace, term: str) -> list[dict]:
    """Wordings the model proposed for this concept (an `expand` task) that occur in the documents."""
    got = ws.meta(f"concept_wordings:{term}") or []
    out = []
    for w in got:
        tid = find_term(ws, w)
        if tid:
            r = ws.query("SELECT label, tf, df FROM terms WHERE term_id=?", (tid,))[0]
            out.append({"wording": w, "term_id": tid, "label": r["label"], "mentions": r["tf"], "documents": r["df"]})
    members = set(concept_of(ws, term))
    refused = set()   # wordings a person said are not the same: never proposed again
    for r in ws.query("SELECT a, b FROM concept_links WHERE source='person' AND relation='different'"):
        if r["a"] in members:
            refused.add(r["b"])
        if r["b"] in members:
            refused.add(r["a"])
    seen, uniq = set(), []
    for o in out:
        if o["term_id"] not in seen and o["term_id"] not in members and o["term_id"] not in refused:
            seen.add(o["term_id"])
            uniq.append(o)
    return uniq


def set_link(ws: Workspace, a: str, b: str, decision: str, relation: str | None = None, reviewer: str = "",
             note: str | None = None) -> None:
    """A person's decision on a link between two terms: accept or reject a proposed link, change its relation, or
    add a link of their own (decision "add", with a relation). "undo" (0.8) takes the person's latest decision on
    the pair back (the link and its concept return as they were). Concepts are regrouped at once."""
    if decision not in ("accept", "reject", "change", "add", "undo"):
        raise ValueError("decision must be accept, reject, change, add or undo.")
    if relation is not None and relation not in LINK_RELATIONS:
        raise ValueError(f"relation must be one of {', '.join(LINK_RELATIONS)}.")
    for t in (a, b):
        if not ws.scalar("SELECT 1 FROM terms WHERE term_id=?", (t,)):
            raise KeyError(t)
    if a == b:
        raise ValueError("Choose two different terms.")
    if a > b:  # stored from the smaller id; broader/narrower are turned round with it
        a, b = b, a
        relation = _INVERSE.get(relation, relation) if relation else relation
    with ws.connect() as cx:
        if decision == "undo":
            last = cx.execute("SELECT review_id FROM reviews WHERE item_kind='concept_link' AND item_id=? ORDER BY "
                              "review_id DESC LIMIT 1", (f"{a}|{b}",)).fetchone()
            if last is None:
                raise ValueError("There is no decision on these two terms to undo.")
            cx.execute("DELETE FROM reviews WHERE review_id=?", (last[0],))
        elif decision == "add":
            cx.execute("INSERT OR REPLACE INTO concept_links VALUES (?,?,?,?,?,?,?,?,?)",
                       (a, b, relation or "same", "person", 1.0, None, None, None, now()))
        else:
            if not cx.execute("SELECT 1 FROM concept_links WHERE a=? AND b=?", (a, b)).fetchone():
                raise KeyError(f"{a}|{b}")
            cx.execute("INSERT INTO reviews(item_kind, item_id, field, proposed, decision, corrected, reviewer, note, "
                       "decided_at) VALUES ('concept_link', ?, 'relation', NULL, ?, ?, ?, ?, ?)",
                       (f"{a}|{b}", decision, relation, reviewer, note, now()))
    rebuild_concepts(ws)


# ---------------------------------------------------------------------------------------------
# key terms (F6)
# ---------------------------------------------------------------------------------------------
def key_terms(ws: Workspace, doc_id: str | None = None, passage_id: str | None = None, n: int = 20) -> list[dict]:
    """The terms that characterise a document (or a passage) against the corpus: TF-IDF of its terms, with
    sublinear term frequency; a term inside a longer one already chosen with as many mentions is left out."""
    if bool(doc_id) == bool(passage_id):
        raise ValueError("Give a document or a passage.")
    if doc_id:
        rows = ws.query("SELECT m.term_id, COUNT(*) AS tf, t.label, t.stems, t.df AS df FROM term_mentions m "
                        "JOIN terms t ON t.term_id=m.term_id WHERE m.doc_id=? GROUP BY m.term_id", (doc_id,))
        total = int(ws.scalar("SELECT COUNT(DISTINCT doc_id) FROM term_mentions") or 1)
    else:
        rows = ws.query("SELECT m.term_id, COUNT(*) AS tf, t.label, t.stems, t.passages AS df FROM term_mentions m "
                        "JOIN terms t ON t.term_id=m.term_id WHERE m.passage_id=? GROUP BY m.term_id", (passage_id,))
        total = int(ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'") or 1)
    scored = []
    for r in rows:
        idf = math.log((1 + total) / (1 + r["df"])) + 1
        scored.append({"term_id": r["term_id"], "label": r["label"], "mentions": r["tf"],
                       "score": round((1 + math.log(r["tf"])) * idf, 3), "_st": r["stems"].split(" ")})
    scored.sort(key=lambda x: (-x["score"], x["label"]))
    out: list[dict] = []
    for s in scored:
        if any(len(o["_st"]) > len(s["_st"]) and _nested(s["_st"], o["_st"]) and o["mentions"] >= s["mentions"]
               for o in out):
            continue
        out.append(s)
        if len(out) >= n:
            break
    for o in out:
        o.pop("_st")
    return out


def key_term_spans(ws: Workspace, doc_id: str, n: int = 15) -> dict:
    """A document's key terms and where each occurs (document offsets), for underlining them in the viewer."""
    kt = key_terms(ws, doc_id=doc_id, n=n)
    ids = [k["term_id"] for k in kt]
    spans = []
    if ids:
        q = ",".join("?" * len(ids))
        spans = [{"term_id": r["term_id"], "start": r["start"], "end": r["end"]} for r in ws.query(
            f"SELECT term_id, start, end FROM term_mentions WHERE doc_id=? AND term_id IN ({q}) ORDER BY start",
            (doc_id, *ids))]
    return {"terms": kt, "spans": spans}


def key_terms_table(ws: Workspace, n: int = 15) -> list[dict]:
    """Key terms per document, for the Excel sheet "Key terms per document"."""
    rows = []
    for d in ws.query("SELECT doc_id, title FROM documents ORDER BY title"):
        for i, k in enumerate(key_terms(ws, doc_id=d["doc_id"], n=n), 1):
            rows.append({"Document": d["title"] or d["doc_id"], "Rank": i, "Key term": k["label"],
                         "Mentions": k["mentions"], "Score (TF-IDF)": k["score"]})
    return rows


def passage_term_counts(ws: Workspace) -> dict[str, Counter]:
    """{passage_id: Counter(term_id)} over the body text (the vectors of themes by words)."""
    out: dict[str, Counter] = defaultdict(Counter)
    for r in ws.query("SELECT passage_id, term_id FROM term_mentions"):
        out[r["passage_id"]][r["term_id"]] += 1
    return out


# ---------------------------------------------------------------------------------------------
# link tasks (the model judges how two terms relate) and wordings proposed by the model
# ---------------------------------------------------------------------------------------------
def snippets(ws: Workspace, term: str, n: int = 3, width: int = 150, allowed: set[str] | None = None) -> list[dict]:
    """Up to n short passages where a term occurs, from different documents where possible; with `allowed` (0.11),
    only from documents of those AI settings."""
    rows = ws.query("SELECT m.passage_id, m.doc_id, m.start, m.end, p.text, p.start AS pstart, d.title FROM term_mentions m "
                    "JOIN passages p ON p.passage_id=m.passage_id JOIN documents d ON d.doc_id=m.doc_id "
                    "WHERE m.term_id=? ORDER BY m.doc_id, m.start", (term,))
    if allowed is not None:
        from . import access

        lv = access.levels(ws, {r["doc_id"] for r in rows})
        rows = [r for r in rows if lv.get(r["doc_id"]) in allowed]
    picked, docs = [], set()
    for r in rows:
        if r["doc_id"] in docs:
            continue
        docs.add(r["doc_id"])
        picked.append(r)
        if len(picked) >= n:
            break
    for r in rows:
        if len(picked) >= n:
            break
        if r not in picked:
            picked.append(r)
    out = []
    for r in picked:
        a, b = r["start"] - r["pstart"], r["end"] - r["pstart"]
        s0 = max(0, a - width)
        s1 = min(len(r["text"]), b + width)
        text = r["text"][s0:s1].strip()
        out.append({"passage_id": r["passage_id"], "title": r["title"] or "", "text": " ".join(text.split())})
    return out


def make_link_task(ws: Workspace, a: str, b: str, model: str, allowed: set[str] | None = None,
                   local_reader: bool = False) -> str | None:
    """A `link` task for two terms (each with up to three passages where it occurs); returns its id.

    0.11: the passages come from documents of the `allowed` settings (those the reader may read; default: every
    document an AI may read). When a term occurs only in documents the reader may not read, the pair is read by the
    local model with those passages (`local_reader`), or not at all: returns None then (a term is words of the
    documents, so its wording is not sent either)."""
    from .tasks import replace_task

    a, b = sorted((a, b))
    info = {r["term_id"]: r["label"] for r in ws.query("SELECT term_id, label FROM terms WHERE term_id IN (?, ?)", (a, b))}
    if len(info) < 2:
        raise KeyError(a if a not in info else b)
    allowed = set(allowed or {"cloud", "local"})
    sn = {t: snippets(ws, t, allowed=allowed) for t in (a, b)}
    if not all(sn.values()):
        if not (local_reader and "local" not in allowed):
            return None
        sn = {t: snippets(ws, t, allowed=allowed | {"local"}) for t in (a, b)}  # read by the local model
        if not all(sn.values()):
            return None
    payload = {"terms": [{"n": i, "term_id": t, "label": info[t], "snippets": sn[t]} for i, t in enumerate((a, b), 1)]}
    tid = f"link:{a}|{b}"
    with ws.connect() as cx:
        replace_task(cx, tid, "link", model, payload)
    return tid


def proposed_pairs(ws: Workspace, limit: int = 200) -> list[tuple[str, str]]:
    """The pairs the meaning pass proposed that no person and no model has judged yet."""
    dec = _decisions(ws)
    judged = {(r["a"], r["b"]) for r in ws.query("SELECT a, b FROM concept_links WHERE source IN ('model', 'person')")}
    out = []
    for r in ws.query("SELECT a, b FROM concept_links WHERE source='meaning' ORDER BY confidence DESC LIMIT ?", (limit,)):
        if (r["a"], r["b"]) not in judged and (r["a"], r["b"]) not in dec:
            out.append((r["a"], r["b"]))
    return out


def judge_links(ws: Workspace, pairs: list[tuple[str, str]], backend, model: str,
                progress: Callable | None = None, should_stop: Callable[[], bool] | None = None) -> dict:
    """Ask the model how each pair of terms relates (one `link` task per pair, quotes checked)."""
    from . import tasks

    from . import access

    done = failed = 0
    readers = access.Readers(backend, model)
    # every task first (0.8): with Claude Code they all wait in the queue at once, to be answered in batches
    made = [make_link_task(ws, a, b, model, readers.main_levels, readers.local_configured()) for a, b in pairs]
    ids = [t for t in made if t]
    kept = len(made) - len(ids)  # pairs whose terms occur only in documents no model here may read
    try:
        for i, tid in enumerate(ids, 1):
            if should_stop and should_stop():
                break
            if progress:
                progress(i, len(pairs))
            got = readers.for_task(ws, tid)
            if got is None:
                continue
            ok, _errs = tasks.run_one(ws, tid, got[0], got[1])
            done += ok
            failed += not ok
        if getattr(getattr(backend, "router", None), "route", "") == "local":
            tasks.run_stepups(ws, backend, ["link"], should_stop)  # the stronger model once, after the small one
    finally:
        rebuild_concepts(ws)
    return {"pairs": len(pairs), "judged": done, "failed": failed, **({"restricted": kept} if kept else {})}


def propose_wordings(ws: Workspace, term: str, backend, model: str) -> list[dict]:
    """Ask the model for other wordings of a concept (the `expand` task, as for a hypothesis's search words), and
    keep those the documents use."""
    from . import tasks

    from . import access

    ids = concept_of(ws, term)
    # 0.11: only wordings found in documents this model may read are sent
    ids = sorted(terms_in_docs(ws, ids, access.allowed_docs(ws, access.backend_levels(backend))))
    if not ids:
        raise ValueError("This concept occurs only in documents this model may not read, so its wordings are not sent.")
    labels = [r[0] for r in ws.query(f"SELECT label FROM terms WHERE term_id IN ({','.join('?' * len(ids))}) "
                                     "ORDER BY tf DESC", ids)]
    n = int(ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='expand' AND task_id LIKE ?", (f"expand:concept:{term}:%",))
            or 0) + 1
    tid = f"expand:concept:{term}:{n}"
    with ws.connect() as cx:
        tasks._insert_task(cx, tid, "expand", model, {"concept": term, "claim": f"the concept: {labels[0]}"
                                                       + (f" (also written: {', '.join(labels[1:6])})" if labels[1:] else "")})
    tasks.run_one(ws, tid, backend, model)
    return suggested_wordings(ws, term)


def terms_in_docs(ws: Workspace, term_ids, docs) -> set[str]:
    """The terms among these that occur in at least one of these documents (0.11)."""
    ids, docs = list(term_ids), list(docs)
    if not ids or not docs:
        return set()
    return {r[0] for r in ws.query(f"SELECT DISTINCT term_id FROM term_mentions WHERE term_id IN "
                                   f"({','.join('?' * len(ids))}) AND doc_id IN ({','.join('?' * len(docs))})",
                                   [*ids, *docs])}


def stems_of(text: str) -> str:
    return " ".join(stem(w) for w in text.split())
