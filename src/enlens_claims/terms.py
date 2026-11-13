"""The term index (F3, F6): a glossary of the corpus, the concepts it is grouped into, and key terms.

No model is needed to build it. After documents are added (and whenever the corpus version changes) the body
passages are read once:

- Candidates are runs of one to four words (`textutil.token_spans`, the checker's own word rule and stemmer) that
  neither start nor end with a common word of the passage's language (0.17: `stopwords`) or a number, and do not
  cross punctuation.
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
import json
import math
import re
import sqlite3
import sys
import threading
import uuid
import zlib
from array import array
from collections import Counter, defaultdict
from itertools import compress
from typing import Callable

from .people import me, mine_sql
from .searchindex import unzip
from .store import DOC_OF, Workspace, now, passage_range
from . import stopwords
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
after alongside anyway know now off oh out say says seem seems try utilise utilised utilize utilized want whereby
""".split())


_GENERAL_STEMS = frozenset(stem(w) for w in GENERAL)


def _edge_ok(word: str, stops: frozenset[str] | None = None) -> bool:
    """Whether a term may start or end with this (normalised) word: no common word of the passage's language (`stops`;
    by default the English rule), no number."""
    s = stopwords.DEFAULT.stops("en") if stops is None else stops
    return len(word) > 1 and word not in s and not word.isdigit() and len(word) <= 30


# 0.8: letter-spaced PDFs. Some PDFs put spaces inside words ("Elec tr oly ser" in the pilot). For the glossary and
# key terms only, adjacent pieces separated by one space are read as one word when, joined, they make a word the
# documents also write whole, and at least one piece is not a word of the documents on its own. The documents' text,
# search and quotes keep the text as read.
FRAGMENT_MAX = 6        # longest piece (letters) that may be part of a split word
FRAGMENT_PIECES = 8     # most pieces one word is joined from
_PIECE = re.compile(r"[^\W\d_]{1,%d}" % FRAGMENT_MAX)


def joiner_counts(texts, words: list | None = None) -> tuple[Counter, Counter]:
    """What the joiner counts in some texts: every word, and every run of pieces that stands apart. Both are sums
    over the texts, so a corpus's counts are the sums of its documents' (0.16, H3: each document's are kept).
    `words`: each text's words (`token_spans(text, keep_stop=True)`), when they are read already."""
    vocab: Counter[str] = Counter()
    split: Counter[str] = Counter()   # how often each run of pieces stands apart ("net zero": often)
    for n, t in enumerate(texts):
        toks = words[n] if words is not None else token_spans(t, keep_stop=True)
        vocab.update(w for _a, _b, _s, w in toks)
        for i in range(len(toks) - 1):
            if not _PIECE.fullmatch(toks[i][3]):
                continue
            j = i + 1
            while j < len(toks) and j - i < FRAGMENT_PIECES and t[toks[j - 1][1]:toks[j][0]] == " " \
                    and _PIECE.fullmatch(toks[j][3]):
                split[" ".join(x[3] for x in toks[i:j + 1])] += 1
                j += 1
    return vocab, split


class Joiner:
    """The corpus's whole words, to join the pieces of letter-spaced words (see FRAGMENT_MAX).

    Every run of pieces that `join` weighs is a key of `split` (the same runs are counted), so whatever the joiner
    does to a text depends only on its decisions (`whole`) for the runs of that text."""

    def __init__(self, texts=(), counts: tuple[Counter, Counter] | None = None):
        self.vocab, self.split = counts if counts is not None else joiner_counts(texts)

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


def _grams(text: str, joiner: Joiner | None = None, stops: frozenset[str] | None = None, toks: list | None = None):
    """(start, end, stems key) of every candidate in a text. With a `joiner`, letter-spaced words are read whole.
    `stops`: the common words of the text's language (by default the English rule); `toks`: its words, when read."""
    if toks is None:
        toks = token_spans(text, keep_stop=True)
    if joiner is not None:
        toks = joiner.join(text, toks)
    for run in _runs(text, toks):
        n = len(run)
        for i in range(n):
            if not _edge_ok(run[i][3], stops):
                continue
            for j in range(i, min(n, i + MAX_N)):
                if not _edge_ok(run[j][3], stops):
                    continue
                yield run[i][0], run[j][1], " ".join(x[2] for x in run[i:j + 1])


def status(ws: Workspace) -> dict:
    """Whether the glossary is made, and whether it is out of date: documents changed (`documents_changed`) or what it
    leaves out changed (`words_changed`, 0.17: a person's choice, or the lists of a newer ENLENS)."""
    built = ws.meta("glossary_corpus_version")
    n = int(ws.scalar("SELECT COUNT(*) FROM terms") or 0)
    docs = built is not None and built != ws.corpus_version()
    # the rules of the last build, as that build noted them: a build by an ENLENS before 0.17 notes none
    noted = ws.meta("terms_words")
    words = built is not None and not (isinstance(noted, dict) and noted.get("digest") == stopwords.rules(ws).digest
                                       and noted.get("build") == ws.meta("terms_build_id"))
    return {"built": built is not None, "stale": docs or words, "documents_changed": docs, "words_changed": words,
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


def running_heads(rows, joiner: Joiner | None = None, stops_of: dict[str, frozenset[str]] | None = None,
                  words: list | None = None,
                  grams_of: dict | None = None) -> tuple[dict[str, tuple[int, int]], set[tuple[str, str]]]:
    """Running heads and feet ("Journal of Energy in Southern Africa • Vol 33", "IEA. All rights reserved"): the
    candidate terms found at the top or bottom of at least 3 pages, and of at least a third of the pages, of one
    document. Returns {passage_id: (head end, foot start)} for the first and last passage of each page, and the
    (doc_id, term key) pairs that are running heads; their mentions there are left out of the glossary (search still
    finds them). `stops_of`: {passage_id: the common words of its language} (by default the English rule).
    `words`: each row's words, when they are read already; `grams_of`: a dict that is given the candidates of each
    first and last passage of a page, so the caller does not find them again."""
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
    for n, r in enumerate(rows):
        e = edges.get(r["passage_id"])
        if not e:
            continue
        gs = list(_grams(r["text"], joiner, (stops_of or {}).get(r["passage_id"]),
                         words[n] if words is not None else None))
        if grams_of is not None:
            grams_of[r["passage_id"]] = gs
        for a, b, key in gs:
            if _at_edge(a, b, e):
                seen[(r["doc_id"], key)].add(r["page"])
    boiler = {dk for dk, pg in seen.items() if len(pg) >= 3 and len(pg) * 3 >= len(pages[dk[0]])}
    return {pid: (e[0], e[1]) for pid, e in edges.items()}, boiler


# ---------------------------------------------------------------------------------------------
# 0.16 (H3): each document's reading is kept, so adding a document does not read every document again
# ---------------------------------------------------------------------------------------------
READING_FORMAT = 2   # raise it when what a kept reading holds changes (a change to this file or textutil.py also)


def _doc_fp(rows) -> str:
    """A document's body text as the glossary reads it: its passages with their pages and places, in order."""
    h = hashlib.sha1()
    for r in rows:
        h.update(f"{r['passage_id']}\x1e{r['page']}\x1e{r['start']}\x1e".encode())
        h.update(r["text"].encode("utf-8", "surrogatepass"))
        h.update(b"\x1f")
    return h.hexdigest()


def _reading_stamp(rules: stopwords.Rules | None = None) -> str:
    """What a kept reading was made with: its format, the code that reads (this file as imported, and the word rule
    of textutil.py), not ENLENS's version, so an update that leaves them alone keeps the readings, and a connector of
    another version shares them with the app (0.16 review)."""
    return f"{_STAMP}:{(rules or stopwords.DEFAULT).reading_digest}"   # 0.17: and the words the project leaves out


def _code_digest() -> str:
    try:
        from pathlib import Path

        code = Path(__file__).read_bytes()
    except OSError:   # installed without its source
        from . import __version__

        code = __version__.encode()
    from .textutil import RULE_DIGEST

    return hashlib.sha1(code + b"|" + RULE_DIGEST.encode()).hexdigest()[:16]


_STAMP = f"{READING_FORMAT}:{_code_digest()}:{sys.byteorder}"   # when this module is imported (0.16 review)


def _blobs(reading: dict, grams: array) -> tuple[bytes, bytes, str]:
    """A reading as kept: its two blobs and their digest (which says which reading a build used)."""
    rb = zlib.compress(json.dumps(reading).encode(), 1)
    gb = zlib.compress(grams.tobytes(), 1)
    return rb, gb, hashlib.sha1(rb + b"\x00" + gb).hexdigest()[:24]


def _decode(rb: bytes | None, gb: bytes | None) -> tuple[dict, array] | None:
    try:
        rd = json.loads(unzip(rb)) if rb else None
        g = array("I")
        g.frombytes(unzip(gb)) if gb else None
    except (ValueError, TypeError, zlib.error):
        return None
    if not isinstance(rd, dict) or not isinstance(rd.get("keys"), list) or len(g) % 4:
        return None
    return rd, g


class _Readings:
    """Where each document's reading is kept: `cache/glossary.sqlite` in the project folder. A file of its own, not
    the project's database, so it is never in a project's zip or a sync; held in memory for one build when it cannot
    be written. A reading that is missing, of another version or cannot be read only means reading that document
    again: nothing in the glossary depends on the file being there. Each reading carries a digest, so a build knows
    whether the reading it finds is the one it (or the last build) used."""

    COLUMNS = ["doc_id", "fp", "stamp", "counts", "reading", "grams", "digest"]

    def __init__(self, ws: Workspace, rules: stopwords.Rules | None = None):
        self.stamp = _reading_stamp(rules)
        self.mem: dict[str, tuple] = {}
        self.cx = None
        try:
            from .searchindex import Unavailable, connect_cache

            folder = ws.root / "cache"
            folder.mkdir(exist_ok=True)
            cx = connect_cache(folder / "glossary.sqlite")
            have = [r[1] for r in cx.execute("PRAGMA table_info(readings)")]
            if have and have != self.COLUMNS:   # an earlier layout: made again
                cx.execute("DROP TABLE readings")
                cx.execute("DROP TABLE IF EXISTS state")
            cx.execute("CREATE TABLE IF NOT EXISTS readings(doc_id TEXT PRIMARY KEY, fp TEXT, stamp TEXT, counts BLOB, "
                       "reading BLOB, grams BLOB, digest TEXT)")
            cx.execute("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT)")
            cx.commit()
            self.cx = cx
        except (OSError, sqlite3.Error, Unavailable):
            self.cx = None

    def _select(self, doc_id: str, fp: str, cols: str):
        if self.cx is None:
            hit = self.mem.get(doc_id)
            if hit is None or hit[0] != fp:
                return None
            row = dict(zip(("fp", "counts", "reading", "grams", "digest"), hit))
            return tuple(row[c.strip()] for c in cols.split(","))
        try:
            return self.cx.execute(f"SELECT {cols} FROM readings WHERE doc_id=? AND fp=? AND stamp=?",
                                   (doc_id, fp, self.stamp)).fetchone()
        except sqlite3.Error:
            return None

    def counts(self, doc_id: str, fp: str) -> tuple[dict, dict] | None:
        """What the document adds to the joiner (its words, its runs of pieces): its text's alone. Or None."""
        r = self._select(doc_id, fp, "counts")
        try:
            v = json.loads(unzip(r[0])) if r and r[0] else None
            return (v["vocab"], v["split"]) if isinstance(v, dict) else None
        except (ValueError, KeyError, TypeError, zlib.error):
            return None

    def joined(self, doc_id: str, fp: str) -> tuple[set, str] | None:
        """The joiner's decisions the reading was made with (its runs read whole), and its digest. Or None."""
        r = self._select(doc_id, fp, "reading, digest")
        try:
            rd = json.loads(unzip(r[0])) if r and r[0] else None
        except (ValueError, TypeError, zlib.error):
            return None
        return (set(rd.get("joined") or ()), r[1]) if isinstance(rd, dict) and r[1] else None

    def digest_of(self, doc_id: str, fp: str) -> str | None:
        """The digest of the kept reading of this text (nothing is unpacked), or None."""
        r = self._select(doc_id, fp, "digest")
        return r[0] if r and r[0] else None

    def load(self, doc_id: str, fp: str, digest: str) -> tuple[dict, array] | None:
        """The reading with that digest (candidates, their places, abbreviations), or None (another program's build
        may have put another there meanwhile)."""
        r = self._select(doc_id, fp, "reading, grams, digest")
        return _decode(r[0], r[1]) if r and r[2] == digest else None

    def put(self, doc_id: str, fp: str, counts: tuple[dict, dict], reading: dict, grams: array) -> str:
        cb = zlib.compress(json.dumps({"vocab": counts[0], "split": counts[1]}).encode(), 1)
        rb, gb, digest = _blobs(reading, grams)
        if self.cx is not None:
            try:
                self.cx.execute("INSERT OR REPLACE INTO readings VALUES (?,?,?,?,?,?,?)",
                                (doc_id, fp, self.stamp, cb, rb, gb, digest))
                self.cx.commit()
                return digest
            except sqlite3.Error:  # a full disk, a locked file: this build goes on in memory
                self.close()
                self.mem.clear()
        self.mem[doc_id] = (fp, cb, rb, gb, digest)
        return digest

    def state(self) -> dict | None:
        if self.cx is None:
            return None
        try:
            r = self.cx.execute("SELECT value FROM state WHERE key='last_build'").fetchone()
            v = json.loads(r[0]) if r else None
            return v if isinstance(v, dict) and v.get("stamp") == self.stamp else None
        except (sqlite3.Error, ValueError):
            return None

    def finish(self, doc_ids: set[str], state: dict | None) -> None:
        """After the build is written: the readings of documents no longer in the project go, and what the build
        wrote is noted (None: nothing may be assumed about the database next time)."""
        if self.cx is None:
            return
        try:
            gone = [r[0] for r in self.cx.execute("SELECT doc_id FROM readings") if r[0] not in doc_ids]
            self.cx.executemany("DELETE FROM readings WHERE doc_id=?", [(d,) for d in gone])
            self.cx.execute("DELETE FROM state WHERE key='last_build'")
            if state is not None:
                self.cx.execute("INSERT INTO state VALUES ('last_build', ?)", (json.dumps({**state, "stamp": self.stamp}),))
            self.cx.commit()
        except sqlite3.Error:
            pass

    def close(self) -> None:
        if self.cx is not None:
            try:
                self.cx.close()
            except sqlite3.Error:
                pass
            self.cx = None


def _read_document(rows, joiner: Joiner, split: dict | None = None, rules: stopwords.Rules | None = None,
                   with_counts: bool = False) -> tuple:
    """One document's candidate terms with their places (running heads and feet left out), as `build` read them
    before 0.16, the joiner's decisions for its runs of pieces, and (0.17) how many of its passages are in each
    language: each passage is read by the common words of its own language (`stopwords`). `split`: the document's
    runs of pieces (counted here when not given); `with_counts`: the document's counts for the joiner are returned
    too, from the words read here."""
    rules = rules or stopwords.DEFAULT
    words = [token_spans(r["text"], keep_stop=True) for r in rows]
    langs = stopwords.fill([stopwords.detect(t[3] for t in toks) for toks in words])
    stops_of = {r["passage_id"]: rules.stops(c) for r, c in zip(rows, langs)}
    found: dict[str, list] = {}   # the candidates of the passages at the top and bottom of a page, found once
    edges, boiler = running_heads(rows, joiner, stops_of, words, found)
    keys: dict[str, int] = {}
    grams = array("I")
    for n, r in enumerate(rows):
        pid = r["passage_id"]
        e = edges.get(pid)
        gs = found.pop(pid, None)
        for a, b, key in gs if gs is not None else _grams(r["text"], joiner, stops_of[pid], words[n]):
            if e and (r["doc_id"], key) in boiler and _at_edge(a, b, e):
                continue
            k = keys.get(key)
            if k is None:
                k = keys[key] = len(keys)
            grams.extend((n, a, b, k))
    abbrev: Counter = Counter()
    for r in rows:
        if "(" in r["text"]:
            for short, long in abbreviations(r["text"]):
                abbrev[(short, long)] += 1
    counts = joiner_counts([r["text"] for r in rows], words) if with_counts or split is None else None
    joined = sorted(k for k in (split if split is not None else counts[1]) if joiner.whole(k.split(" ")))
    reading = {"keys": list(keys), "joined": joined, "abbrev": [[s, lf, c] for (s, lf), c in abbrev.items()],
               "langs": dict(Counter(langs))}
    return (reading, grams, counts) if with_counts else (reading, grams)


_BUILDING: dict[str, threading.Lock] = {}
_BUILDING_GUARD = threading.Lock()


class _Changed(Exception):
    """A document's text changed while the glossary was made (its text is read one document at a time)."""


def build(ws: Workspace, progress: Callable[[int, int], None] | None = None,
          should_stop: Callable[[], bool] | None = None, embedder=None, max_terms: int = MAX_TERMS) -> dict:
    """(Re)build the glossary of the project's body text. Takes seconds to a minute; nothing is sent anywhere.

    0.16 (H3): a document whose text is unchanged, and for whose runs of pieces the joiner decides as before, is not
    read again (its reading is kept, see `_Readings`); and only the mentions that changed are written. The glossary
    is the same as a build from scratch, mention for mention. One build of a project at a time in this process."""
    with _BUILDING_GUARD:
        lock = _BUILDING.setdefault(str(ws.db_path.resolve()), threading.Lock())
    with lock:
        rules = stopwords.rules(ws)
        store = _Readings(ws, rules)
        try:
            for attempt in range(3):
                try:
                    return _build(ws, store, progress, should_stop, embedder, max_terms, rules)
                except _Changed:   # a document was read again or removed meanwhile: start again with its new text
                    if attempt == 2:
                        raise ValueError("The documents kept changing while the glossary was made. Make it again "
                                         "once they are added.") from None
        finally:
            store.close()


def _evidence() -> str:
    """0.18.1 (K2): the condition that leaves out the passages of theory documents (docrole.py), which the glossary
    and key terms never count."""
    from .docrole import evidence_sql

    return evidence_sql()


def _body_docs(ws: Workspace) -> dict[str, int]:
    """The documents with body text, in order, and the number of their body passages. 0.18.1 (K2): not the theory
    documents, which never count for key terms or the glossary's counts."""
    from .docrole import evidence_sql

    return {r[0]: r[1] for r in ws.query(f"SELECT doc_id, COUNT(*) FROM passages WHERE section='body' AND "
                                         f"{evidence_sql()} GROUP BY doc_id ORDER BY doc_id")}


def _body_rows(ws: Workspace, doc_id: str) -> list:
    return ws.query("SELECT passage_id, doc_id, page, start, text FROM passages WHERE section='body' AND doc_id=? "
                    "ORDER BY seq", (doc_id,))


def _mention_indexes() -> list[tuple[str, str]]:
    """The indexes of `term_mentions` as the project's schema makes them (`store.INDEXES`): (name, statement)."""
    from .store import INDEXES

    out = []
    for stmt in INDEXES.split(";"):
        m = re.match(r"\s*CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+(\w+)\s+ON\s+term_mentions\s*\(", stmt, re.I)
        if m:
            out.append((m.group(1), stmt.strip()))
    return out


_LOW = (1 << 32) - 1   # a candidate's count of documents, in the low bits of its entry (its mentions above them)


def _build(ws: Workspace, store: _Readings, progress, should_stop, embedder, max_terms: int,
           rules: stopwords.Rules = stopwords.DEFAULT) -> dict:
    # the corpus version before the text: a document that changes while the glossary is made leaves the glossary
    # marked out of date, never up to date with the old text
    version = ws.corpus_version()
    sizes = _body_docs(ws)
    docs = list(sizes)
    n_rows = sum(sizes.values())
    fps: dict[str, str] = {}

    def rows_of(d: str) -> list:
        """A document's body passages with their text. The text of a large project is never held whole (it is read
        a document at a time when needed), so each later reading is checked against the first."""
        rs = _body_rows(ws, d)
        if _doc_fp(rs) != fps[d]:
            raise _Changed()
        return rs

    def stop_check():
        if should_stop and should_stop():
            raise _stopped()

    # the joiner (0.8: letter-spaced words read whole, glossary and key terms only), from every document's counts
    vocab: Counter[str] = Counter()
    split: Counter[str] = Counter()
    unread: set[str] = set()   # documents with no counts kept: read in full
    for d in docs:
        stop_check()
        rs = _body_rows(ws, d)
        fps[d] = _doc_fp(rs)
        c = store.counts(d, fps[d])
        if c is None:
            c = joiner_counts(r["text"] for r in rs)
            unread.add(d)
        vocab.update(c[0])
        split.update(c[1])
    rs = c = None
    joiner = Joiner(counts=(vocab, split))
    whole_now = {k for k in split if joiner.whole(k.split(" "))}

    # A kept reading holds when the joiner decides each of the document's runs as it did then. The last build noted
    # the runs it read whole and the reading of each document it used: for those readings only the runs whose
    # decision changed since are looked for (none changed: nothing is unpacked); other kept readings are checked
    # in full.
    prev = store.state()
    last_whole = set(prev["whole"]) if prev and isinstance(prev.get("whole"), list) else None
    last_docs = (prev or {}).get("docs") or {}
    last_joins = set((prev or {}).get("joins") or ())
    flipped = whole_now ^ last_whole if last_whole is not None else None
    digests: dict[str, str] = {}   # the reading this build uses, by its digest
    plain: dict[str, bool] = {}    # no word of the document read whole: its spellings are its words as written
    to_read = []
    for d in docs:
        if d not in unread:
            dg = store.digest_of(d, fps[d])
            before = last_docs.get(d)
            if dg and flipped is not None and isinstance(before, list) and before[:2] == [fps[d], dg]:
                mine = store.counts(d, fps[d]) if flipped else None
                if not flipped or (mine is not None and not any(k in mine[1] for k in flipped)):
                    digests[d], plain[d] = dg, d not in last_joins
                    continue
            else:
                got = store.joined(d, fps[d])
                if got is not None:
                    mine = store.counts(d, fps[d])
                    if mine is not None and {k for k in whole_now if k in mine[1]} == got[0]:
                        digests[d], plain[d] = got[1], not got[0]
                        continue
        to_read.append(d)
    mine = None
    total = sum(sizes[d] for d in to_read) + 2 * n_rows
    done = 0

    # first reading: how often each candidate occurs and in how many documents, in one entry per candidate
    seen: dict[str, int] = {}
    langs_of: dict[str, dict] = {}   # passages per language (0.17), per document

    def count(d: str, rd: dict, g: array) -> None:
        keys, get = rd["keys"], seen.get
        for i, n in Counter(g[3::4]).items():
            k = keys[i]
            seen[k] = get(k, 0) + (n << 32) + 1
        langs_of[d] = rd.get("langs") or {}

    for d in to_read:
        stop_check()
        rd, g, c = _read_document(rows_of(d), joiner, None, rules, with_counts=True)
        digests[d], plain[d] = store.put(d, fps[d], c, rd, g), not rd["joined"]
        count(d, rd, g)
        done += 2 * sizes[d]
        if progress:
            progress(done, total)
    rd = g = c = None
    here: dict[str, tuple[dict, array]] = {}   # readings made again here (another build replaced the kept one)

    def reading(d: str) -> tuple[dict, array]:
        """The document's reading this build decided on: kept, or (when another program's build put another in
        its place meanwhile, or the file went) read again here with this build's joiner."""
        got = here.get(d) or store.load(d, fps[d], digests[d])
        if got is None:
            got = here[d] = _read_document(rows_of(d), joiner, None, rules)
            digests[d], plain[d] = _blobs(*got)[2], not got[0]["joined"]
        return got

    for d in docs:
        if d in langs_of:
            continue
        stop_check()
        count(d, *reading(d))
        done += sizes[d]
        if progress:
            progress(done, total)
    languages: Counter[str] = Counter()
    for d in docs:
        languages.update(langs_of.get(d) or {})
    n_docs = len(docs)
    min_df = MIN_DF if n_docs >= MIN_DF else 1   # a project of one document (a quick look) still gets its terms
    kept = {k: v >> 32 for k, v in seen.items() if v >> 32 >= MIN_TF and v & _LOW >= min_df
            and k not in _GENERAL_STEMS and k not in rules.phrases}
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
    tid = {k: term_id(k) for k in chosen}
    tf = {k: seen[k] >> 32 for k in chosen}
    df = {k: seen[k] & _LOW for k in chosen}
    cval = {k: cval[k] for k in chosen}
    n_candidates = len(kept)
    seen.clear()   # every candidate's counts: what the second reading needs is only the chosen terms'
    kept = containers = None
    cidx = {k: i for i, k in enumerate(chosen)}
    tids = [tid[k] for k in chosen]

    # What the last build wrote, when the database still holds exactly that: then only what changed is written. A
    # document's rows stand when the last build wrote them from the reading this build uses (its digest) and they are
    # all still there (outside a build, rows go only a whole document at a time: removing or reading it again); the
    # database must not have been written by any other build since (its id, time and corpus version, which a build of
    # before 0.16 also changes). The count comes from an index; sums of places cost half a second a look (review).
    # 0.17.2: counted per passage on the index of passages (a document's passages are next to each other in it) and
    # summed per document here: the table has no column of documents any more.
    def db_state(cx) -> tuple[dict, list]:
        per: dict[str, list[int]] = {}
        for pid, n in cx.execute("SELECT passage_id, COUNT(*) FROM term_mentions GROUP BY passage_id"):
            d = pid.partition(":")[0]
            if d in per:
                per[d][0] += n
            else:
                per[d] = [n]
        stamps = [json.loads(r[0]) if r and r[0] is not None else None for r in (
            cx.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
            for k in ("terms_build_id", "terms_built_at", "glossary_corpus_version"))]
        return per, stamps

    prev = store.state()
    have, stamps = db_state(ws._conn())
    same: set[str] = set()   # documents whose mentions of the terms kept from the last build stand as they are
    if prev and prev.get("stamps") == stamps and stamps[0]:
        read_now = set(to_read)
        before = prev.get("docs") or {}
        same = {d for d in docs if d not in read_now and before.get(d) == [fps[d], digests[d], *have.get(d, [0])]}
    old_keys = set(prev.get("chosen") or ()) if same else set()
    entering = keep - old_keys

    def second_reading(diff: bool):
        """The places of the chosen terms, their spellings and passages, and the abbreviations the text defines.
        With `diff`, only the mentions to write: every mention of a document read again or new, and the mentions of
        terms new to the glossary in the others. The mentions to write are kept as numbers per term (a document, its
        passage, start and end, four to a mention: a few bytes, where a row of Python objects takes about 150), and
        `rows()` gives them as rows in the order of the table's key (0.17.2: term, passage, place), so the table is
        written in order, its pages full, rather than into the middle of it a row at a time."""
        written: list[tuple[list, list]] = []   # per document with mentions to write: its passages' ids and starts
        by_term: dict[int, array] = {}          # per term (its index in `chosen`): document, passage, start, end
        spell: dict[str, Counter] = defaultdict(Counter)
        passages: Counter[str] = Counter()
        abbrev: Counter[tuple[str, str]] = Counter()
        per_doc: dict[str, list[int]] = {}
        spelt: dict[str, str] = {}  # a mention's spelling by its raw text: the same words recur (0.11.1)
        nonlocal done
        for d in docs:
            stop_check()
            rd, g = reading(d)
            rs = rows_of(d)
            keys = rd["keys"]
            want = {i: cidx[k] for i, k in enumerate(keys) if k in cidx}
            write = {i for i, c in want.items() if not diff or d not in same or chosen[c] in entering}
            single = plain[d]
            seen_at = set()
            n_doc = 0
            w = len(written)   # this document's place in `written`, if it has mentions to write
            wrote = False
            # most candidates are not terms: the places of the terms' are picked out without a step in Python for
            # each of the others (in the order of the text, as before)
            col = g[3::4]
            mask = bytearray(len(keys))
            for i in want:
                mask[i] = 1
            for p in compress(range(len(col)), map(mask.__getitem__, col)):
                i = col[p]
                c = want[i]
                key = chosen[c]
                x = 4 * p
                n, a, b = g[x], g[x + 1], g[x + 2]
                r = rs[n]
                n_doc += 1
                if i in write:
                    m = by_term.get(c)
                    if m is None:
                        m = by_term[c] = array("I")
                    m.extend((w, n, a, b))
                    wrote = True
                raw = r["text"][a:b]
                # a document with no word read whole, and a mention whose words stand one space apart: each run of
                # pieces in it is one of the document's own runs, none read whole, so `_spelling` would change
                # nothing (other spaces, a line break, it may join: 0.16 review)
                if single and " ".join(raw.split()) == raw:
                    sp = raw
                else:
                    sp = spelt.get(raw)
                    if sp is None:
                        sp = spelt[raw] = _spelling(raw, joiner)
                spell[key][sp] += 1
                if (n, i) not in seen_at:
                    seen_at.add((n, i))
                    passages[key] += 1
            for short, long, c in rd["abbrev"]:
                abbrev[(short, long)] += c
            per_doc[d] = [n_doc]
            if wrote:
                written.append(([r["passage_id"] for r in rs], [r["start"] for r in rs]))
            done += sizes[d]
            if progress:
                progress(min(done, total), total)

        def rows():
            for c in sorted(by_term, key=tids.__getitem__):
                t, m = tids[c], by_term[c]
                for x in range(0, len(m), 4):
                    pids, starts = written[m[x]]
                    n = m[x + 1]
                    s = starts[n]
                    yield t, pids[n], s + m[x + 2], s + m[x + 3]

        return rows, spell, passages, abbrev, per_doc

    diff = bool(same)
    mentions, spell, passages, abbrev, per_doc = second_reading(diff)
    terms = []
    for k in chosen:
        label = _label(spell[k])
        terms.append((tid[k], label, k, k.count(" ") + 1, df[k], tf[k], passages[k], round(cval[k], 3)))
    build_id = uuid.uuid4().hex
    built_at = now()

    def write(cx, diff: bool) -> int:
        cx.execute("DELETE FROM terms")
        cx.executemany("INSERT INTO terms VALUES (?,?,?,?,?,?,?,?)", terms)
        made_again = []
        if diff:
            for d in [d for d in set(have) | set(docs) if d not in same]:
                cx.execute("DELETE FROM term_mentions WHERE passage_id >= ? AND passage_id < ?", passage_range(d))
            gone = [term_id(k) for k in old_keys - keep]
            for i in range(0, len(gone), 500):
                chunk = gone[i:i + 500]
                cx.execute(f"DELETE FROM term_mentions WHERE term_id IN ({','.join('?' * len(chunk))})", chunk)
        else:
            cx.execute("DELETE FROM term_mentions")
            # every mention written anew: the indexes are made once after the rows, not kept up row by row (in the
            # same transaction, so a failure leaves them as they were)
            made_again = _mention_indexes()
            for name, _sql in made_again:
                cx.execute(f"DROP INDEX IF EXISTS {name}")
        # the same place of a term twice is one place (the key would refuse the second: the build would stop)
        cx.executemany("INSERT OR IGNORE INTO term_mentions(term_id, passage_id, start, end) VALUES (?,?,?,?)",
                       mentions())
        for _name, sql in made_again:
            cx.execute(sql)
        # abbreviation links: the short form and the long form, both terms of the index
        cx.execute("DELETE FROM concept_links WHERE source='abbreviation'")
        best: dict[str, tuple[int, str]] = {}
        for (short, long), c in abbrev.items():
            if c > best.get(short, (0, ""))[0]:
                best[short] = (c, long)
        n_abbr = 0
        for short, (c, long) in best.items():
            ks, kl = _key_of(short, rules), _key_of(long, rules)
            if not ks or not kl or ks == kl or ks not in keep or kl not in keep:
                continue
            a, b = sorted((term_id(ks), term_id(kl)))
            cx.execute("INSERT OR REPLACE INTO concept_links VALUES (?,?,?,?,?,?,?,?,?)",
                       (a, b, "same", "abbreviation", 1.0, f"{long} ({short})", short, None, now()))
            n_abbr += 1
        ws.set_meta("glossary_corpus_version", version, cx)   # 0.17.2: see store.GLOSSARY_META
        # an ENLENS before 0.17.2 notes its builds here: from now on this build is the one in force
        cx.execute("DELETE FROM meta WHERE key='terms_corpus_version'")
        ws.set_meta("terms_words", {"digest": rules.digest, "build": build_id}, cx)   # 0.17: what it left out
        ws.set_meta("terms_languages", dict(languages), cx)
        ws.set_meta("terms_built_at", built_at, cx)
        ws.set_meta("terms_build_id", build_id, cx)
        return n_abbr

    class _Moved(Exception):
        pass

    try:
        with ws.connect() as cx:
            if diff and db_state(cx) != (have, stamps):   # another build (another program) wrote since this one looked
                raise _Moved()
            n_abbr = write(cx, diff)
    except _Moved:
        done = total - n_rows
        mentions, spell, passages, abbrev, per_doc = second_reading(False)
        with ws.connect() as cx:
            n_abbr = write(cx, False)
    store.finish(set(docs), {"stamps": [build_id, built_at, version], "chosen": chosen,
                             "docs": {d: [fps[d], digests[d], *per_doc.get(d, [0])] for d in docs},
                             "whole": sorted(whole_now), "joins": sorted(d for d in docs if not plain[d])})
    variants = 0
    if embedder is not None:
        try:
            variants = meaning_variants(ws, embedder)
        except Exception as e:  # the glossary is useful without them; say why there are none
            ws.set_meta("terms_meaning_error", str(e)[:300])
    rebuild_concepts(ws)
    return {**status(ws), "candidates": n_candidates, "mentions": sum(v[0] for v in per_doc.values()),
            "abbreviations": n_abbr, "meaning_pairs": variants, "documents_read": len(to_read),
            "documents_kept": len(docs) - len(to_read)}


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


def _key_of(text: str, rules: stopwords.Rules | None = None) -> str | None:
    """The stems key of a phrase as the index writes it (None when it does not start and end with a content word). By
    the English rule and the project's own words (`rules`): no term starts or ends with a common word of any language,
    so this finds a term whatever its language; a phrase is too short to tell its language (0.17 review)."""
    stops = (rules or stopwords.DEFAULT).stops("en")
    toks = token_spans(text, keep_stop=True)
    while toks and not _edge_ok(toks[0][3], stops):
        toks = toks[1:]
    while toks and not _edge_ok(toks[-1][3], stops):
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
    nearest neighbours above `threshold`). Needs numpy; the proposals wait for a person's decision. 0.14.3: with an
    embedding model on another computer, only terms found in documents Claude may read are sent to it (a term is
    words of the documents; as embed.build does for passages)."""
    try:
        import numpy as np
    except ImportError:
        return 0
    from .embed import _restricted_docs, _unit, remote

    rows = ws.query("SELECT term_id, label, stems FROM terms ORDER BY tf DESC, term_id LIMIT ?", (int(limit),))
    if remote(embedder):
        restricted = _restricted_docs(ws)
        if restricted:
            allowed = [r[0] for r in ws.query("SELECT doc_id FROM documents") if r[0] not in restricted]
            ok = terms_in_docs(ws, [r["term_id"] for r in rows], allowed)
            rows = [r for r in rows if r["term_id"] in ok]
    if len(rows) < 2:
        return 0
    with ws.connect() as cx:  # vectors of terms the last build dropped (0.11.1: they stayed for good, a few MB a build)
        cx.execute("DELETE FROM code_vectors WHERE framework='_terms' AND code NOT IN (SELECT term_id FROM terms)")
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
    from .people import review_order

    out = {}
    order, oargs = review_order()  # 0.14: yours count over a colleague's
    for r in ws.query(f"SELECT item_id, decision, corrected FROM reviews WHERE item_kind='concept_link' {order}", oargs):
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
    key = _key_of(text, stopwords.rules(ws))
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
    terms = [dict(r) for r in ws.query("SELECT term_id, label, tf, df FROM terms")]
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
    # documents per entry: a term's own count is kept with it (`df`); only the terms of a concept need the mentions
    # (0.11.1: every mention of the corpus was read for each glossary page)
    docs: dict[str, set] = defaultdict(set)
    # (0.17.2: from the terms of concepts to their places, CROSS JOIN keeping that order: SQLite would otherwise read
    # every place of the glossary to find theirs)
    for r in ws.query(f"SELECT DISTINCT ct.term_id, {DOC_OF.format('m.passage_id')} AS doc_id FROM concept_terms ct "
                      "CROSS JOIN term_mentions m ON m.term_id=ct.term_id"):
        docs[in_concept.get(r["term_id"]) or r["term_id"]].add(r["doc_id"])
    own_docs = {t["term_id"]: t["df"] for t in terms if t["term_id"] not in in_concept}
    pas = {r["term_id"]: r["n"] for r in ws.query("SELECT term_id, passages AS n FROM terms")}
    for r in ws.query("SELECT ct.concept_id, COUNT(DISTINCT m.passage_id) AS n FROM concept_terms ct CROSS JOIN "
                      "term_mentions m ON ct.term_id=m.term_id GROUP BY ct.concept_id"):
        pas[r["concept_id"]] = r["n"]
    for key, e in entries.items():
        e["documents"] = own_docs[key] if key in own_docs else len(docs.get(key, ()))
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
                      f"FROM (SELECT {DOC_OF.format('passage_id')} AS doc_id, passage_id, start FROM term_mentions "
                      f"WHERE term_id IN ({q})) m JOIN documents d ON d.doc_id=m.doc_id "
                      "GROUP BY m.doc_id ORDER BY n DESC, d.title", ids):
        end = ws.scalar(f"SELECT MAX(end) FROM term_mentions WHERE passage_id >= ? AND passage_id < ? AND start=? AND "
                        f"term_id IN ({q})", (*passage_range(r["doc_id"]), r["first"], *ids))
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
    page = ws.query(f"SELECT m.term_id, m.passage_id, p.doc_id, m.start, m.end, p.text, p.start AS pstart, p.page, "
                    f"d.title FROM term_mentions m JOIN passages p ON p.passage_id=m.passage_id JOIN documents d "
                    f"ON d.doc_id=p.doc_id WHERE m.term_id IN ({q}) ORDER BY d.title, p.seq, m.start LIMIT ? OFFSET ?",
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
    n_pass = int(ws.scalar(f"SELECT COUNT(*) FROM passages WHERE section='body' AND {_evidence()}") or 1)
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
            mine, margs = mine_sql()  # 0.14: undo takes back your own decision, never a colleague's
            last = cx.execute(f"SELECT review_id FROM reviews WHERE item_kind='concept_link' AND item_id=? AND {mine} "
                              "ORDER BY review_id DESC LIMIT 1", (f"{a}|{b}", *margs)).fetchone()
            if last is None:
                raise ValueError("There is no decision on these two terms to undo.")
            from .people import forget_reviews

            forget_reviews(cx, review_ids=[last[0]])  # 0.14: taken back for good, in colleagues' copies too
        elif decision == "add":
            cx.execute("INSERT OR REPLACE INTO concept_links VALUES (?,?,?,?,?,?,?,?,?)",
                       (a, b, relation or "same", "person", 1.0, None, None, None, now()))
        else:
            if not cx.execute("SELECT 1 FROM concept_links WHERE a=? AND b=?", (a, b)).fetchone():
                raise KeyError(f"{a}|{b}")
            cx.execute("INSERT INTO reviews(item_kind, item_id, field, proposed, decision, corrected, reviewer, note, "
                       "decided_at, person_id) VALUES ('concept_link', ?, 'relation', NULL, ?, ?, ?, ?, ?, ?)",
                       (f"{a}|{b}", decision, relation, reviewer, note, now(), me()))
    rebuild_concepts(ws)


# ---------------------------------------------------------------------------------------------
# key terms (F6)
# ---------------------------------------------------------------------------------------------
def _docs_with_terms(ws: Workspace) -> int:
    """How many documents the glossary's mentions are in: one look-up per document on the index of passages (its
    passages are a range there, store.passage_range), instead of reading every mention (two seconds on a large
    project, on every opening of a document)."""
    return int(ws.scalar("SELECT COUNT(*) FROM documents d WHERE EXISTS (SELECT 1 FROM term_mentions "
                         "WHERE passage_id >= d.doc_id || ':' AND passage_id < d.doc_id || ';')") or 0)


def _term_info(ws: Workspace) -> dict[str, tuple]:
    """{term_id: (label, stems, df)} of every term of the glossary."""
    return {r[0]: (r[1], r[2], r[3]) for r in ws._conn().execute("SELECT term_id, label, stems, df FROM terms")}


def key_terms(ws: Workspace, doc_id: str | None = None, passage_id: str | None = None, n: int = 20,
              _docs: int | None = None, _info: dict | None = None) -> list[dict]:
    """The terms that characterise a document (or a passage) against the corpus: TF-IDF of its terms, with
    sublinear term frequency; a term inside a longer one already chosen with as many mentions is left out.
    `_docs`: the number of documents with mentions, when the caller has counted them (`key_terms_table`); `_info`:
    `_term_info`, when the caller has read it."""
    if bool(doc_id) == bool(passage_id):
        raise ValueError("Give a document or a passage.")
    if doc_id:
        # 0.17.2: a document's places are a range of the index of passages; counted per term here, as SQLite would
        # sort them all first to count them (seven times slower)
        tf = Counter(r[0] for r in ws._conn().execute(
            "SELECT term_id FROM term_mentions WHERE passage_id >= ? AND passage_id < ?", passage_range(doc_id)))
        info = _info if _info is not None else _term_info(ws)
        rows = [{"term_id": t, "tf": c, "label": info[t][0], "stems": info[t][1], "df": info[t][2]}
                for t, c in sorted(tf.items()) if t in info]
        total = (_docs if _docs is not None else _docs_with_terms(ws)) or 1
    else:
        rows = ws.query("SELECT m.term_id, COUNT(*) AS tf, t.label, t.stems, t.passages AS df FROM term_mentions m "
                        "JOIN terms t ON t.term_id=m.term_id WHERE m.passage_id=? GROUP BY m.term_id", (passage_id,))
        total = int(ws.scalar(f"SELECT COUNT(*) FROM passages WHERE section='body' AND {_evidence()}") or 1)
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
            f"SELECT term_id, start, end FROM term_mentions WHERE passage_id >= ? AND passage_id < ? AND term_id IN ({q}) "
            "ORDER BY start", (*passage_range(doc_id), *ids))]
    return {"terms": kt, "spans": spans}


def key_terms_table(ws: Workspace, n: int = 15) -> list[dict]:
    """Key terms per document, for the Excel sheet "Key terms per document"."""
    rows = []
    docs, info = _docs_with_terms(ws), _term_info(ws)   # once, not per document
    for d in ws.query("SELECT doc_id, title FROM documents ORDER BY title"):
        for i, k in enumerate(key_terms(ws, doc_id=d["doc_id"], n=n, _docs=docs, _info=info), 1):
            rows.append({"Document": d["title"] or d["doc_id"], "Rank": i, "Key term": k["label"],
                         "Mentions": k["mentions"], "Score (TF-IDF)": k["score"]})
    return rows


def passage_term_counts(ws: Workspace) -> dict[str, Counter]:
    """{passage_id: Counter(term_id)} over the body text (the vectors of themes by words). In the order of the text
    (0.16: a build writes only the mentions that changed, so the table's own order is no longer the text's; the order
    of a passage's terms decides the order sums are taken in, and so the last digits of a theme's similarities).
    The mentions come in that order from the database, one at a time (not all held at once and sorted); each term id
    and passage id is one object however often it recurs."""
    out: dict[str, Counter] = defaultdict(Counter)
    ids: dict[str, str] = {}
    pid_now, c = None, None
    for pid, tid in ws._conn().execute("SELECT passage_id, term_id FROM term_mentions "   # the order of its index
                                       "ORDER BY passage_id, start, end, term_id"):
        if pid != pid_now:
            pid_now, c = pid, out[pid]
        t = ids.get(tid)
        if t is None:
            t = ids[tid] = tid
        c[t] += 1
    return out


# ---------------------------------------------------------------------------------------------
# link tasks (the model judges how two terms relate) and wordings proposed by the model
# ---------------------------------------------------------------------------------------------
def snippets(ws: Workspace, term: str, n: int = 3, width: int = 150, allowed: set[str] | None = None) -> list[dict]:
    """Up to n short passages where a term occurs, from different documents where possible; with `allowed` (0.11),
    only from documents of those AI settings."""
    rows = ws.query("SELECT m.passage_id, p.doc_id, m.start, m.end, p.text, p.start AS pstart, d.title FROM term_mentions m "
                    "JOIN passages p ON p.passage_id=m.passage_id JOIN documents d ON d.doc_id=p.doc_id "
                    "WHERE m.term_id=? ORDER BY p.doc_id, m.start", (term,))
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
    dflt = access.default(ws)
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
            # the setting worked out again as the text is about to leave (not the one stored when the tasks were
            # made): a document's cap counts what the tasks before this one sent, and a task over it waits for a
            # model that may read it, or the person
            with ws.connect() as cx:
                if access.recheck(cx, tid, dflt) is None:
                    continue
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
        # worked out again as it leaves, as in the runs of several tasks (an add-on's floor may hold it back)
        if access.recheck(cx, tid) not in access.backend_levels(backend):
            raise ValueError("This concept's wordings may not be sent to this model.")
    tasks.run_one(ws, tid, backend, model)
    return suggested_wordings(ws, term)


def terms_in_docs(ws: Workspace, term_ids, docs) -> set[str]:
    """The terms among these that occur in at least one of these documents (0.11)."""
    ids, docs = list(term_ids), set(docs)
    if not ids or not docs:
        return set()
    # 0.17.2: a term's places in passage order, until one is in these documents (mostly the first)
    cx, out = ws._conn(), set()
    for t in dict.fromkeys(ids):
        for (pid,) in cx.execute("SELECT passage_id FROM term_mentions WHERE term_id=?", (t,)):
            if pid.partition(":")[0] in docs:
                out.add(t)
                break
    return out


def stems_of(text: str) -> str:
    return " ".join(stem(w) for w in text.split())
