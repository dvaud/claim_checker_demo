"""The keyword index of a project, made quickly from what is kept on disk (0.16, H2).

Before 0.16 the index (BM25 over the passages' words, `retrieve.BM25`) was built from every passage the first time a
project was searched after the app started or its documents changed: every passage's text read into memory and split
into words again (most of the time), and a second index as large when reference lists were included in a search.
Now:

- each document's words are kept in `cache/search.sqlite` in the project folder (which word occurs how often in
  which of its passages, and each passage's length): one row per document, written when the document is new or
  changed, the same in every program that writes it, and used again while the document's passages and ENLENS's word
  rule are unchanged (`textutil.py`: its code is the row's stamp, so an update that leaves it alone keeps them);
- the index is built in memory from those rows, as one snapshot of the project, and holds no passage text: a
  search reads the passages it shows from the project (`_Rows`), the most recent kept in memory.

The ranking stays ENLENS's own (the review of H2 ruled out SQLite's FTS5, whose BM25 and word splitting differ): the
same BM25 (k1 = 1.5, b = 0.75) with the same numbers summed in the same order, over the same passages numbered in
the order of their ids, so every search ranks exactly as before. The file is a file of its own, opened for one load
and closed (nothing stays open: Windows can remove the project), never in a project's zip or a sync; a missing,
damaged or unwritable file only means splitting the words again, as before 0.16.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import sys
import threading
import zlib
from array import array
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Iterator

from . import textutil
from .retrieve import BM25
from .store import Workspace
from .textutil import tokens

FORMAT = 3                 # raise it when what a row holds changes
ROW_CACHE = 50_000         # passages kept in memory once read (their text), most recently used first
_FIELDS = "p.passage_id, p.doc_id, p.seq, p.page, p.text, d.title, p.start, p.section"
_COLUMNS = ["doc_id", "fp", "stamp", "passages", "words", "triples"]


def stamp() -> str:
    """What a kept row was made with: the format and ENLENS's word rule as this program uses it
    (`textutil.RULE_DIGEST`, taken when textutil was imported), not ENLENS's version."""
    return f"{FORMAT}:{textutil.RULE_DIGEST}:{sys.byteorder}"


class Unavailable(Exception):
    """A cache file cannot be made or opened."""


class Changed(ValueError):
    """A passage the index holds is no longer in the project: the documents changed while this ran (a ValueError, so
    the app and the connector say it in words)."""


def connect_cache(path, timeout: float = 60, **kw) -> sqlite3.Connection:
    """A connection to a cache file of the project folder (in WAL mode). A file that is not a database (damaged, or
    something else by that name) is put aside and made again: what it held can always be made again. A busy or
    locked file is left alone (OperationalError)."""
    for attempt in (1, 2):
        cx = sqlite3.connect(path, timeout=timeout, **kw)
        try:
            cx.execute("PRAGMA journal_mode=WAL")
            cx.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            return cx
        except sqlite3.OperationalError:   # busy or locked (another program): not damaged, left alone
            cx.close()
            raise
        except sqlite3.DatabaseError:
            cx.close()
            if attempt == 2:
                raise
            for extra in ("", "-wal", "-shm"):
                try:
                    Path(str(path) + extra).unlink(missing_ok=True)
                except OSError:
                    raise Unavailable(f"{path} is damaged and cannot be replaced.") from None
    raise AssertionError("not reached")


# ---------------------------------------------------------------------------------------------
# each document's words, kept
# ---------------------------------------------------------------------------------------------
def _fingerprints(cx: sqlite3.Connection) -> dict[str, str]:
    """Each document's passages as the index reads them: ids, sections and text, in the order of their ids."""
    fps: dict[str, "hashlib._Hash"] = {}
    for doc_id, pid, section, text in cx.execute(
            "SELECT doc_id, passage_id, section, text FROM passages ORDER BY doc_id, passage_id"):
        h = fps.get(doc_id)
        if h is None:
            h = fps[doc_id] = hashlib.sha1()
        h.update(f"{pid}\x1e{section}\x1e".encode())
        h.update((text or "").encode("utf-8", "surrogatepass"))
        h.update(b"\x1f")
    return {d: h.hexdigest() for d, h in fps.items()}


def _words(cx: sqlite3.Connection, doc_id: str) -> tuple[list, list, array]:
    """A document's passages ([id, body, length] in the order of their ids), its words, and (passage number, word
    number, count) for each word of each passage, in the order of the passages."""
    passages: list = []
    vocab: dict[str, int] = {}
    triples = array("I")
    for n, (pid, section, text) in enumerate(cx.execute(
            "SELECT passage_id, section, text FROM passages WHERE doc_id=? ORDER BY passage_id", (doc_id,))):
        toks = tokens(text or "")
        passages.append([pid, int(section == "body"), len(toks)])
        for t, f in Counter(toks).items():
            k = vocab.get(t)
            if k is None:
                k = vocab[t] = len(vocab)
            triples.extend((n, k, f))
    return passages, list(vocab), triples


def _open(ws: Workspace) -> sqlite3.Connection | None:
    """The file, with its table; a file damaged inside or of another layout is made again. None when it cannot be."""
    path = ws.root / "cache" / "search.sqlite"
    for attempt in (1, 2):
        try:
            (ws.root / "cache").mkdir(exist_ok=True)
            cx = connect_cache(path)
        except (OSError, sqlite3.Error, Unavailable):
            return None
        try:
            have = [r[1] for r in cx.execute("PRAGMA table_info(docs)")]
            if have and have != _COLUMNS:
                cx.execute("DROP TABLE docs")
            cx.execute("CREATE TABLE IF NOT EXISTS docs(doc_id TEXT PRIMARY KEY, fp TEXT, stamp TEXT, passages BLOB, "
                       "words BLOB, triples BLOB)")
            cx.execute("SELECT COUNT(*), SUM(length(passages)), SUM(length(words)), SUM(length(triples)) "
                       "FROM docs").fetchone()  # reads every page: damage beyond the first shows here
            return cx
        except sqlite3.OperationalError:   # busy: left alone, this load goes without it
            cx.close()
            return None
        except sqlite3.DatabaseError:      # damaged inside: made again
            cx.close()
            if attempt == 2 or not _remove(path):
                return None
    return None


def _remove(path) -> bool:
    try:
        for extra in ("", "-wal", "-shm"):
            Path(str(path) + extra).unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _blobs(p: list, v: list, tr: array) -> tuple[bytes, bytes, bytes]:
    return (zlib.compress(json.dumps(p).encode(), 1), zlib.compress(json.dumps(v).encode(), 1),
            zlib.compress(tr.tobytes(), 1))


def _unpack(blob: bytes, kind: str):
    """A kept list (passages, words) or the triples; None when it cannot be read."""
    try:
        raw = zlib.decompress(blob)
        if kind == "triples":
            tr = array("I")
            tr.frombytes(raw)
            return tr if len(tr) % 3 == 0 else None
        v = json.loads(raw)
        return v if isinstance(v, list) else None
    except (ValueError, TypeError, zlib.error):
        return None


def _kept(ws: Workspace, snap: sqlite3.Connection, fps: dict[str, str]) -> dict[str, list]:
    """Every document's words: {doc: [passages, packed words, packed triples]}. The kept rows that match its
    passages in this snapshot, the others split again from the same snapshot (and kept). The words stay packed until
    the index takes them in, one document at a time."""
    out: dict[str, list] = {}
    st = stamp()
    cx = _open(ws)
    try:
        if cx is not None:
            try:
                for d, fp, s_, pb, wb, tb in cx.execute("SELECT doc_id, fp, stamp, passages, words, triples FROM docs"):
                    if fps.get(d) == fp and s_ == st and wb and tb:
                        ps = _unpack(pb, "passages") if pb else None
                        if ps is not None:
                            out[d] = [ps, wb, tb]
            except sqlite3.Error:   # damaged in a way the first look missed: every document split again
                out.clear()
        rows = []
        for d in fps:
            if d in out:
                continue
            ps, v, tr = _words(snap, d)
            pb, wb, tb = _blobs(ps, v, tr)
            out[d] = [ps, wb, tb]
            rows.append((d, fps[d], st, pb, wb, tb))
        if cx is not None and rows:
            try:
                cx.execute("PRAGMA synchronous=NORMAL")
                with cx:   # one transaction: a cache, written in one go
                    cx.executemany("INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?,?)", rows)
                    gone = [r[0] for r in cx.execute("SELECT doc_id FROM docs") if r[0] not in fps]
                    cx.executemany("DELETE FROM docs WHERE doc_id=?", [(d,) for d in gone])
            except sqlite3.Error:
                pass   # kept next time, or not: the index is made either way
    finally:
        if cx is not None:
            cx.close()
    return out


# ---------------------------------------------------------------------------------------------
# the index: BM25 in memory, the rows read when needed
# ---------------------------------------------------------------------------------------------
class _Pairs:
    """A word's postings, (passage number, count) pairs packed in one array: reads as the list of pairs of
    `retrieve.BM25.postings` (iterated, counted, sliced, compared)."""
    __slots__ = ("a",)

    def __init__(self, a: array):
        self.a = a

    def __len__(self) -> int:
        return len(self.a) // 2

    def __iter__(self) -> Iterator[tuple[int, int]]:
        a = self.a
        return zip(a[0::2], a[1::2])

    def __getitem__(self, k):
        if isinstance(k, slice):
            return list(self)[k]
        n = len(self)
        if k < 0:
            k += n
        if not 0 <= k < n:
            raise IndexError(k)
        return self.a[2 * k], self.a[2 * k + 1]

    def __bool__(self) -> bool:
        return bool(self.a)

    def __eq__(self, other) -> bool:
        return list(self) == list(other)

    def __repr__(self) -> str:
        return repr(list(self))


class PackedBM25(BM25):
    """`retrieve.BM25` over postings built from the kept words: the same numbers (lengths, idf, norms) computed by
    the same expressions, and BM25's own `sparse`, `score` and `top`, so the scores are the same bit for bit."""

    def __init__(self, lens: list[int], postings: dict[str, _Pairs], k1: float = 1.5, b: float = 0.75):  # noqa: D107
        self.k1, self.b = k1, b
        self.lens: list[int] = lens
        n = len(lens)
        self.n = n
        self.avg = (sum(lens) / n) if n else 0.0
        self.postings = postings
        self.idf = {t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in postings.items()}
        avg = self.avg or 1
        self._norm = [k1 * (1 - b + b * ln / avg) for ln in lens]


class _Rows:
    """The passages of the index by number, read from the project when first asked for (`prefetch` reads many in
    one go), the most recently used kept in memory. Behaves as the list of rows of the index in memory; a passage
    gone from the project meanwhile raises `Changed`."""

    def __init__(self, ws: Workspace, ids: list[str]):
        self.ws, self.ids = ws, ids
        self.cache: OrderedDict[int, dict] = OrderedDict()
        self.lock = threading.Lock()

    def __len__(self) -> int:
        return len(self.ids)

    def __bool__(self) -> bool:
        return bool(self.ids)

    def _read(self, wanted: list[int]) -> dict[int, dict]:
        out: dict[int, dict] = {}
        wanted = list(dict.fromkeys(wanted))   # a passage asked for twice is read once
        for k in range(0, len(wanted), 500):
            at = {self.ids[i]: i for i in wanted[k:k + 500]}
            for r in self.ws.query(f"SELECT {_FIELDS} FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
                                   f"WHERE p.passage_id IN ({','.join('?' * len(at))})", list(at)):
                out[at[r["passage_id"]]] = dict(r)
        if len(out) < len(wanted):
            raise Changed("The documents changed while this ran (a passage it was reading is gone). Run it again.")
        return out

    def prefetch(self, indices) -> None:
        with self.lock:
            missing = sorted({i for i in indices if i not in self.cache})
        if not missing:
            return
        got = self._read(missing)
        with self.lock:
            for i in missing[-ROW_CACHE:]:
                self.cache[i] = got[i]
                self.cache.move_to_end(i)
            while len(self.cache) > ROW_CACHE:
                self.cache.popitem(last=False)

    def __getitem__(self, i: int) -> dict:
        if i < 0:
            i += len(self.ids)
        if not 0 <= i < len(self.ids):
            raise IndexError(i)
        with self.lock:
            hit = self.cache.get(i)
            if hit is not None:
                self.cache.move_to_end(i)
                return hit
        got = self._read([i])[i]
        with self.lock:
            self.cache[i] = got
            while len(self.cache) > ROW_CACHE:
                self.cache.popitem(last=False)
        return got

    def __iter__(self) -> Iterator[dict]:
        for k in range(0, len(self.ids), 2000):
            got = self._read(list(range(k, min(k + 2000, len(self.ids)))))
            for i in range(k, min(k + 2000, len(self.ids))):
                yield got[i]


def load(ws: Workspace, all_sections: bool):
    """The index of the project as it is now: its passages numbered in the order of their ids (body passages only,
    unless `all_sections`), the BM25 over their words, and the rows read when needed. Returns (rows, bm25, pos, ids,
    doc_of). The passages are read in one read transaction of a connection of its own, so the fingerprints and the
    words split are of the same state (0.16 review: a document changed between them was kept under the wrong one)."""
    snap = sqlite3.connect(ws.db_path, timeout=60, isolation_level=None)
    try:
        snap.execute("BEGIN")
        fps = _fingerprints(snap)
        kept = _kept(ws, snap, fps)
        # a kept row whose words cannot be unpacked (damaged inside a blob): split again, from the same snapshot
        def words_of(d: str) -> tuple[list, list, array]:
            ps, wb, tb = kept[d]
            v, tr = _unpack(wb, "words"), _unpack(tb, "triples")
            return (ps, v, tr) if v is not None and tr is not None else _words(snap, d)

        everything = sorted((pid, d, body, ln) for d, (ps, _w, _t) in kept.items() for pid, body, ln in ps)
        rows = everything if all_sections else [r for r in everything if r[2] == 1]
        ids = [r[0] for r in rows]
        doc_of = [r[1] for r in rows]
        pos = {pid: i for i, pid in enumerate(ids)}
        # postings in the order of the passages: documents in the order of their first passage here, each document's
        # passages in the order of their ids; a word whose list comes out of order (documents whose ids interleave)
        # is sorted at the end
        first: dict[str, int] = {}
        for i, d in enumerate(doc_of):
            first.setdefault(d, i)
        lists: dict[str, array] = {}
        last: dict[str, int] = {}
        unsorted: set[str] = set()
        for d in sorted(first, key=first.__getitem__):
            ps, vocab, tr = words_of(d)
            where = [pos.get(p[0], -1) for p in ps]
            for x in range(0, len(tr), 3):
                i = where[tr[x]]
                if i < 0:
                    continue
                t = vocab[tr[x + 1]]
                a = lists.get(t)
                if a is None:
                    a = lists[t] = array("I")
                elif i < last[t]:
                    unsorted.add(t)
                a.append(i)
                a.append(tr[x + 2])
                last[t] = i
    finally:
        try:
            snap.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        snap.close()
    for t in unsorted:
        pairs = sorted(zip(lists[t][0::2], lists[t][1::2]))
        lists[t] = array("I", [v for p in pairs for v in p])
    bm25 = PackedBM25([r[3] for r in rows], {t: _Pairs(a) for t, a in lists.items()})
    return _Rows(ws, ids), bm25, pos, ids, doc_of
