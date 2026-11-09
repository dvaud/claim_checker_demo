"""0.16: the speed changes, which give the same results, quicker. Files read at once in reading processes store exactly
what reading them one at a time stores (and a process that fails leaves the file to be read here); the quick check of
phrase patterns finds the same codes; the keyword pass, the words nearby, the Profile page and the themes by words
(k-means) give the very same rows as the plain way of before 0.16, and `enlens measure --timings` times the new steps.
The old code is copied into this file where the source no longer holds it."""
from __future__ import annotations

import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from helpers import make_pdf

from enlens_claims import concordance, frameworks, home, ingest, measure, profile, readworker, terms, textutil, themes
from enlens_claims.concordance import (CHUNK, WINDOW, _candidates, _code_passages, _hits_in, _rarest, parse,
                                       passage_index)
from enlens_claims.store import Workspace
from enlens_claims.textutil import token_spans

SRC = str(Path(ingest.__file__).resolve().parents[1])
OFF = ingest.OcrOptions(mode="off")


# ---------------------------------------------------------------------------------------------
# a folder to read
# ---------------------------------------------------------------------------------------------
def _page(i: int, p: int) -> str:
    topics = ["green hydrogen", "water stress", "the electricity grid", "ammonia exports", "offshore wind",
              "decent work and jobs", "poverty and the poor", "drinking water and sanitation"]
    a, b = topics[(i + p) % len(topics)], topics[(2 * i + p + 3) % len(topics)]
    return (f"Report {i}, page {p}. The study of {a} in region {i * 7 + p} finds that {a} depends on {b}.\n"
            f"A second paragraph, number {p}, says that {b} and {a} return in the plan of {i} with new costs "
            f"of {i * 13 + p} million euros a year, and that the plan needs a long text to count as a passage.")


def _folder(tmp_path: Path) -> Path:
    d = tmp_path / "batch"
    d.mkdir()
    for i in range(5):
        make_pdf(d / f"paper_{i}.pdf", [_page(i, p) for p in range(3)], title=f"Paper number {i}")
    for i in range(2):
        (d / f"note_{i}.txt").write_text("\n\n".join(_page(10 + i, p) for p in range(4)) + "\n")
    (d / "copy_of_paper_1.pdf").write_bytes((d / "paper_1.pdf").read_bytes())  # a duplicate
    (d / "broken.pdf").write_bytes(b"this is not a pdf at all \x00\x01\x02 junk" * 20)
    (d / "damaged.docx").write_bytes(b"PK\x03\x04 not a zip file, only its first bytes" * 10)  # a read that raises
    return d


def _rows(ws: Workspace) -> dict:
    out = {}
    cols = [r[1] for r in ws.query("PRAGMA table_info(documents)") if r[1] != "added_at"]
    out["documents"] = [tuple(r) for r in ws.query(f"SELECT {', '.join(cols)} FROM documents ORDER BY rowid")]
    out["passages"] = [tuple(r) for r in ws.query("SELECT * FROM passages ORDER BY rowid")]
    if ws.query("SELECT name FROM sqlite_master WHERE type='table' AND name='blocks'"):
        out["blocks"] = [tuple(r) for r in ws.query("SELECT * FROM blocks ORDER BY rowid")]
    return out


def _ingest_in(tmp_path: Path, name: str, folder: Path, **kw) -> tuple[dict, dict]:
    ws = Workspace.create(tmp_path / name)
    stats = ingest.ingest(ws, [folder], ocr=OFF, **kw)
    return stats, _rows(ws)


def _one_at_a_time(tmp_path: Path, folder: Path) -> tuple[dict, dict]:
    stats, rows = _ingest_in(tmp_path, "one", folder, workers=1)
    assert "read_at_once" not in stats
    return stats, rows


def _without_read_at_once(stats: dict) -> dict:
    return {k: v for k, v in stats.items() if k != "read_at_once"}


def test_reading_at_once_stores_what_reading_one_at_a_time_stores(tmp_path, monkeypatch):
    folder = _folder(tmp_path)
    s1, rows1 = _one_at_a_time(tmp_path, folder)
    here = []  # files read in this process: none, when the reading processes work (on every system the tests run on)
    plain = ingest._Readings.here
    monkeypatch.setattr(ingest._Readings, "here", lambda self, i: here.append(i) or plain(self, i))
    s2, rows2 = _ingest_in(tmp_path, "two", folder, workers=2)
    assert here == []
    monkeypatch.setattr(ingest._Readings, "here", plain)
    assert s2["read_at_once"] == 2
    assert _without_read_at_once(s2) == _without_read_at_once(s1)
    assert s1["duplicates"] == 1 and s1["empty_files"] == ["broken.pdf"] and s1["failed"] and len(rows1["documents"]) == 7  # the batch has what it should
    assert rows2 == rows1
    s3, rows3 = _ingest_in(tmp_path, "three", folder, workers=3)
    assert s3["read_at_once"] == 3 and _without_read_at_once(s3) == _without_read_at_once(s1) and rows3 == rows1


# ---------------------------------------------------------------------------------------------
# a reading process that fails: the file is read here
# ---------------------------------------------------------------------------------------------
def _same_as_one_at_a_time(tmp_path: Path):
    folder = _folder(tmp_path)
    s1, rows1 = _one_at_a_time(tmp_path, folder)
    s2, rows2 = _ingest_in(tmp_path, "failing", folder, workers=2)
    assert _without_read_at_once(s2) == _without_read_at_once(s1)
    assert rows2 == rows1


def test_a_reading_process_that_cannot_start_leaves_the_file_to_be_read_here(tmp_path, monkeypatch):
    real = subprocess.Popen

    def popen(args, *a, **kw):
        if any("enlens_claims.readworker" in str(a) for a in args):
            raise OSError("cannot start")
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", popen)
    _same_as_one_at_a_time(tmp_path)


def test_a_reading_process_that_ends_at_once_leaves_the_file_to_be_read_here(tmp_path, monkeypatch):
    started = []

    def process(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        started.append(p)
        return p

    monkeypatch.setattr(ingest._Readings, "_process", process)
    try:
        _same_as_one_at_a_time(tmp_path)
    finally:
        for p in started:
            p.kill()
            p.wait()
            for pipe in (p.stdin, p.stdout):
                try:  # 0.16.0rc2: a job still in the buffer goes to a process that has ended (as ingest closes it)
                    pipe.close()
                except OSError:
                    pass
    assert started


def test_an_answer_that_cannot_come_back_leaves_the_file_to_be_read_here(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest._Readings, "_away", lambda self, i: ("redo",))
    _same_as_one_at_a_time(tmp_path)


# ---------------------------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------------------------
def test_stop_ends_the_reading_and_leaves_no_process_running(tmp_path, monkeypatch):
    folder = _folder(tmp_path)
    started = []
    orig = ingest._Readings._process

    def process(self):
        p = orig(self)
        if p not in started:
            started.append(p)
        return p

    monkeypatch.setattr(ingest._Readings, "_process", process)
    ws = Workspace.create(tmp_path / "stopped")
    reported = []
    stats = ingest.ingest(ws, [folder], ocr=OFF, workers=2, progress=lambda i, n, name: reported.append(name),
                          should_stop=lambda: bool(reported))
    assert stats["stopped"] is True
    files = sorted(p.name for p in folder.iterdir())
    stored = {r[0] for r in ws.query("SELECT path FROM documents")}
    assert len(stored) <= 1 and all(Path(p).name == files[0] for p in stored)  # only what was stored before the stop
    assert all(p.poll() is not None for p in started)


def test_closing_the_readings_ends_every_reading_process(tmp_path, monkeypatch):
    folder = _folder(tmp_path)
    files = sorted(p for p in folder.iterdir() if p.suffix in (".pdf", ".txt"))
    started = []
    orig = ingest._Readings._process

    def process(self):
        p = orig(self)
        if p not in started:
            started.append(p)
        return p

    monkeypatch.setattr(ingest._Readings, "_process", process)
    r = ingest._Readings(files, OFF, 1100, 200, None, workers=2)
    assert r.get(0)[0] in ("ok", "failed")
    r.close()
    assert started and all(p.poll() is not None for p in started)
    assert r.stop_dir and not os.path.exists(r.stop_dir)


# ---------------------------------------------------------------------------------------------
# the reading process
# ---------------------------------------------------------------------------------------------
def test_the_reading_process_answers_what_reading_here_gives(tmp_path):
    folder = _folder(tmp_path)
    env = dict(os.environ, PYTHONPATH=SRC)
    p = subprocess.Popen([sys.executable, "-m", "enlens_claims.readworker"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    try:
        for f in [folder / "note_0.txt", folder / "paper_2.pdf", folder / "broken.pdf", folder / "missing.txt"]:
            readworker.send(p.stdin, (f, OFF, 1100, 200, "", frozenset()))
            got = readworker.receive(p.stdout)
            want = ingest._read_whole(f, OFF, 1100, 200)
            assert got[0] == want[0], f.name
            if want[0] == "ok":
                assert got[1] == want[1] and got[2] == want[2]
                assert (got[2].passages or f.name == "broken.pdf") and got[2].text == want[2].text and got[2].title == want[2].title
            else:
                assert got == want
        p.stdin.close()
        assert p.wait(timeout=10) == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stdout.close()


# ---------------------------------------------------------------------------------------------
# how many files are read at once
# ---------------------------------------------------------------------------------------------
def _sized(tmp_path: Path, n: int, size: int) -> list[Path]:
    out = []
    for i in range(n):
        f = tmp_path / f"f{i}.txt"
        f.write_bytes(b"x" * size)
        out.append(f)
    return out


def test_the_environment_sets_how_many_files_are_read_at_once(tmp_path, monkeypatch):
    files = _sized(tmp_path, 5, 10)
    monkeypatch.setenv("ENLENS_READ_WORKERS", "3")
    assert ingest.read_workers(files) == 3
    monkeypatch.setenv("ENLENS_READ_WORKERS", "9")
    assert ingest.read_workers(files) == 5
    monkeypatch.setenv("ENLENS_READ_WORKERS", "0")
    assert ingest.read_workers(files) == 1
    monkeypatch.setenv("ENLENS_READ_WORKERS", "x")
    assert ingest.read_workers(files) == 1


def test_small_batches_and_little_memory_are_read_one_at_a_time(tmp_path, monkeypatch):
    from enlens_claims import llm

    monkeypatch.delenv("ENLENS_READ_WORKERS", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    monkeypatch.setattr(llm, "free_memory", lambda: 64 * 1024 ** 3)
    big = _sized(tmp_path, 5, ingest.POOL_MIN_BYTES)
    assert ingest.read_workers(big[:1]) == 1  # one file
    assert ingest.read_workers([]) == 1  # no file
    small_dir = tmp_path / "small"
    small_dir.mkdir()
    assert ingest.read_workers(_sized(small_dir, 5, 1000)) == 1  # a batch under POOL_MIN_BYTES
    monkeypatch.setattr(llm, "free_memory", lambda: 100 * 1024 ** 2)
    assert ingest.read_workers(big) == 1  # a computer short of memory
    monkeypatch.setattr(llm, "free_memory", lambda: 64 * 1024 ** 3)
    assert ingest.read_workers(big) == ingest.READ_WORKERS == 3
    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    assert ingest.read_workers(big) == 1  # one processor less than the computer has
    monkeypatch.setattr(os, "cpu_count", lambda: 3)
    assert ingest.read_workers(big) == 2


# ---------------------------------------------------------------------------------------------
# phrase patterns: the same codes with the quick check
# ---------------------------------------------------------------------------------------------
def _plain_hits(fw, text: str) -> set[str]:
    """Before 0.16: every pattern searched in the lower-cased text."""
    if not hasattr(fw, "_plain"):
        fw._plain = [(re.compile(p.lower()), c) for p, c in fw.lexicon if c in fw.codes]
    low = text.lower()
    return {c for rx, c in fw._plain if rx.search(low)}


def _lexicon_texts(fw, n: int = 2000) -> list[str]:
    rng = random.Random(16)
    frags = sorted({w for p, _c in fw.lexicon for w in re.findall(r"[a-z]{2,}", p)})
    frags += ["ports", "port.", "R&D", "Fresh water", "freshwater", "fresh  water", "GDP", "gdp.", "Jobs", "job", "jobless",
              "labour", "labor", "poor", "poorly", "Poverty", "water use", "water-use", "waterway", "stress"]
    texts = ["ports", "port.", "R&D", "Fresh water", "freshwater", "GDP", "", "no words of the lexicon here"]
    for _ in range(n):
        parts = [rng.choice(frags) for _ in range(rng.randint(1, 7))]
        parts = [w.upper() if rng.random() < 0.15 else w.capitalize() if rng.random() < 0.3 else w for w in parts]
        texts.append("".join(parts) if rng.random() < 0.3 else rng.choice([" ", ", ", ". ", "-"]).join(parts))
    return texts


def test_the_quick_check_of_phrase_patterns_finds_the_same_codes(loaded):
    fw = frameworks.get("sdg", None)
    fw.lexicon_hits("")
    assert fw._lex and any(n for _rx, _c, n in fw._lex)  # the quick check is in use
    texts = [r[0] for r in loaded.query("SELECT text FROM passages")] + _lexicon_texts(fw)
    found = 0
    for t in texts:
        want = _plain_hits(fw, t)
        assert fw.lexicon_hits(t) == want, t
        found += bool(want)
    assert found > 100


def test_needles_name_what_a_text_must_contain(tmp_path):
    n = frameworks.needles
    assert n(re.compile("poverty|\\bpoor\\b")) == ("poverty", "poor")
    assert n(re.compile("(?i)water")) is None
    assert n(re.compile("[ab]c")) is None
    assert n(re.compile("s?tress")) is None
    assert n(re.compile("x|")) is None
    assert n(re.compile("(?<=x)y")) is None
    assert n(re.compile("^\\bjobs?\\b")) == ("job",)
    assert n(re.compile("fresh ?water")) == ("fresh",)
    assert n(re.compile("water (stress|use)")) == ("water ",)


# ---------------------------------------------------------------------------------------------
# the keyword pass
# ---------------------------------------------------------------------------------------------
WORDS = ["Hydrogen production in arid regions", "café société naïve résumé", "ﬁnancial ﬂow oﬃce", "co­operation of states",
         "“typographic” ‘quotes’ and it’s", "the of and to a in is it", "", "   ", "1,000 MW of 2030 targets",
         "Électrolyseurs: déjà-vu, Zürich", "water-stress; jobs, poverty. R&D!", "x y z 1", "Straße naïveté ﬁrst"]


def test_the_words_of_a_passage_are_those_tokens_and_surface_words_give(loaded):
    texts = [r[0] for r in loaded.query("SELECT text FROM passages")] + WORDS + _lexicon_texts(
        frameworks.get("sdg", None), 300)
    for t in texts:
        assert profile._words(t) == (textutil.tokens(t), textutil.surface_words(t)), t
        assert list(profile._words(t)[1]) == list(textutil.surface_words(t))  # and in the same order


def _label_rows(ws: Workspace) -> list[tuple]:
    cols = [r[1] for r in ws.query("PRAGMA table_info(labels)") if r[1] != "created_at"]
    return [tuple(r) for r in ws.query(f"SELECT {', '.join(cols)} FROM labels ORDER BY label_id")]


def test_the_keyword_pass_gives_the_labels_of_before_0_16(loaded, monkeypatch):
    stats_new = profile.keyword_pass(loaded, "sdg")
    new = _label_rows(loaded)
    assert new and len(new) > 5
    monkeypatch.setattr(profile, "_words", lambda t: (textutil.tokens(t), textutil.surface_words(t)))
    monkeypatch.setattr(frameworks.Framework, "lexicon_hits",
                        lambda self, text: _plain_hits(self, text))
    stats_old = profile.keyword_pass(loaded, "sdg")
    old = _label_rows(loaded)
    assert old == new
    assert {k: v for k, v in stats_old.items() if k != "seconds"} == {k: v for k, v in stats_new.items() if k != "seconds"}


# ---------------------------------------------------------------------------------------------
# words nearby
# ---------------------------------------------------------------------------------------------
def _old_collocates(ws: Workspace, q: str, mode: str = "any", docs: list[str] | None = None, exact: bool = False,
                    near: int = 5, all_sections: bool = False, window: int = WINDOW, min_count: int = 3, n: int = 40,
                    code: str | None = None, order: str = "typical") -> dict:
    """`concordance.collocates` as it was before 0.16 (commit 187e340)."""
    query = parse(q, mode, exact, near)
    idx = passage_index(ws, all_sections=all_sections)
    allowed_docs = set(docs) if docs else None
    allowed_passages = _code_passages(ws, code)
    rare = _rarest(idx, query) if mode == "all" else None
    qstems = {st for st, _w in query.words} | {st for ph in query.phrases for st, _w in ph}
    near_counts: Counter[str] = Counter()
    surface: dict[str, Counter] = {}
    hits = 0
    window_words = 0
    scope: set[int] | None = None
    if allowed_docs is not None or allowed_passages is not None:
        scope = {i for i, (pid, doc) in enumerate(zip(idx.ids, idx.doc_of))
                 if (allowed_docs is None or doc in allowed_docs)
                 and (allowed_passages is None or pid in allowed_passages)}
    cands = [i for i in _candidates(idx, query) if scope is None or i in scope]
    for r in (r for k in range(0, len(cands), CHUNK) for r in idx.read(cands[k:k + CHUNK])):
        found = _hits_in(r["text"], query, rare)
        if not found:
            continue
        toks = token_spans(r["text"])  # content words only, as the index counts them
        for a, b, _m in found:
            hits += 1
            left = [t for t in toks if t[1] <= a][-window:]
            right = [t for t in toks if t[0] >= b][:window]
            for t in left + right:
                window_words += 1
                if t[2] in qstems or any(ch.isdigit() for ch in t[3]):
                    continue
                near_counts[t[2]] += 1
                surface.setdefault(t[2], Counter())[t[3]] += 1
    total = (sum(idx.bm25.lens) if scope is None else sum(idx.bm25.lens[i] for i in scope)) or 1
    floor = max(min_count, hits // 1000)
    out = []
    for st, c in near_counts.items():
        if c < floor:
            continue
        corpus = sum(f for i, f in idx.bm25.postings.get(st, ()) if scope is None or i in scope)
        if not corpus:
            continue
        expected = corpus * window_words / total
        pmi = math.log2(c / expected) if expected > 0 else 0.0
        out.append({"word": surface[st].most_common(1)[0][0], "stem": st, "count": c, "corpus": corpus,
                    "pmi": round(pmi, 2)})
    if order == "often":
        out.sort(key=lambda x: (-x["count"], -x["pmi"], x["word"]))
    else:
        out.sort(key=lambda x: (-x["pmi"], -x["count"], x["word"]))
    return {"query": q, "hits": hits, "window": window, "order": order, "window_words": window_words, "min_count": floor,
            "words": out[:max(1, n)]}


def test_the_words_nearby_are_those_of_before_0_16(loaded):
    docs = [r[0] for r in loaded.query("SELECT doc_id FROM documents ORDER BY doc_id")]
    cases = [("hydrogen", {}), ("water", {}), ('"water stress"', {}), ("water hydrogen", {"mode": "all"}),
             ("hydrogen jobs", {"mode": "near", "near": 4}), ("Water", {"exact": True}),
             ("hydrogen", {"docs": docs[:2]}), ("the", {"all_sections": True}), ("hydrogen", {"all_sections": True}),
             ("electrolysis", {"min_count": 1})]
    seen_words = 0
    for q, kw in cases:
        for window in (1, 3, 5, 15):
            for order in ("typical", "often"):
                args = dict(kw, window=window, order=order)
                want = _old_collocates(loaded, q, **args)
                got = concordance.collocates(loaded, q, **args)
                assert got == want, (q, args)
                seen_words += len(got["words"])
        low = dict(kw, min_count=1)
        assert concordance.collocates(loaded, q, **low) == _old_collocates(loaded, q, **low)
    assert seen_words > 50


# ---------------------------------------------------------------------------------------------
# the Profile page
# ---------------------------------------------------------------------------------------------
def _grid_and_stats_agree(ws: Workspace, docs: list[str]) -> None:
    full = profile.effective(ws, "sdg")
    assert profile.stats(ws, "sdg") == profile.stats(ws, "sdg", labs=full)
    for level in ("code", "group"):
        assert profile.grid(ws, "sdg", None, level) == profile.grid(ws, "sdg", None, level, labs=full)
        assert profile.grid(ws, "sdg", docs, level) == profile.grid(ws, "sdg", docs, level,
                                                                    labs=profile.effective(ws, "sdg", doc_ids=docs))
    light = profile.effective(ws, "sdg", light=True)
    assert [r["label_id"] for r in light] == [r["label_id"] for r in full]
    assert all(r[k] == f[k] for r, f in zip(light, full) for k in r)  # what the light rows hold is what the full ones do


def test_the_profile_page_counts_the_same_from_light_rows(loaded):
    profile.keyword_pass(loaded, "sdg")
    docs = [r[0] for r in loaded.query("SELECT doc_id FROM documents ORDER BY doc_id")]
    assert profile.stats(loaded, "sdg")["labels"] > 5
    _grid_and_stats_agree(loaded, docs[:2])
    # a person rejects one label, changes another and adds one of their own
    labs = profile.effective(loaded, "sdg")
    profile.set_label(loaded, labs[0]["label_id"], "reject")
    profile.set_label(loaded, labs[1]["label_id"], "change", relevance="mentioned", direction="hinders")
    profile.set_label(loaded, labs[2]["label_id"], "accept")
    pid = next(r[0] for r in loaded.query("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id"))
    profile.add_label(loaded, "sdg", pid, "6.4", relevance="main", direction="hinders")
    assert profile.effective(loaded, "sdg")  # still some
    _grid_and_stats_agree(loaded, docs[:2])
    _grid_and_stats_agree(loaded, docs[1:])


class _Api:
    def __init__(self, base: str, token: str):
        self.base, self.token = base, token

    def get(self, path: str):
        req = urllib.request.Request(self.base + path, headers={"X-Enlens-Token": self.token})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())


def test_the_profile_api_returns_the_grid_and_counts_of_the_direct_calls(tmp_path, corpus, vca_xlsx):
    from enlens_claims import sources, vca
    from enlens_claims.gui.server import make_server

    ws = home.create_project("Demo")
    vca.load_into(ws, vca_xlsx)
    ingest.ingest(ws, [corpus])
    sources.match(ws)
    profile.keyword_pass(ws, "sdg")
    labs = profile.effective(ws, "sdg")
    profile.set_label(ws, labs[0]["label_id"], "reject")
    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        api = _Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
        for level in ("code", "group"):
            got = api.get(f"/api/projects/Demo/profile?level={level}")
            assert got["grid"] == json.loads(json.dumps(profile.grid(ws, "sdg", None, level)))
            assert got["stats"] == json.loads(json.dumps(profile.stats(ws, "sdg")))
            assert got["stats"]["pass1"]["at"] == profile.pass1_status(ws, "sdg")["at"]
        doc = ws.query("SELECT doc_id FROM documents ORDER BY doc_id")[0][0]
        got = api.get(f"/api/projects/Demo/profile?docs={doc}")
        assert got["grid"] == json.loads(json.dumps(profile.grid(ws, "sdg", [doc], "code")))
        assert got["stats"] == json.loads(json.dumps(profile.stats(ws, "sdg")))
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------------------------
# themes by words
# ---------------------------------------------------------------------------------------------
def _old_kmeans_sparse(vecs: list[dict], k: int, seed: int = 0, should_stop=None):
    """`themes.kmeans_sparse` as it was before 0.16 (commit 187e340)."""
    rng = random.Random(seed)
    n = len(vecs)
    k = min(k, n)
    first = rng.randrange(n)
    centres = [dict(vecs[first])]
    best = themes._sdot_one(vecs, centres[0])
    for _ in range(1, k):
        d = [max(0.0, 1.0 - b) ** 2 for b in best]
        total = sum(d)
        if total <= 0:
            pick = next(i for i in range(n) if vecs[i] is not centres[0])
        else:
            target, acc, pick = rng.random() * total, 0.0, n - 1
            for i, x in enumerate(d):
                acc += x
                if acc > target:
                    pick = i
                    break
        centres.append(dict(vecs[pick]))
        sims = themes._sdot_one(vecs, centres[-1])
        best = [max(a, b) for a, b in zip(best, sims)]
    assign: list[int] | None = None
    for _it in range(themes.MAX_ITER):
        if should_stop and should_stop():
            raise themes._stopped()
        inv = themes._inverted(centres)
        new, sim = [], []
        for v in vecs:
            acc = themes._sdot(v, inv, k)
            j = max(range(k), key=lambda x: (acc[x], -x))
            new.append(j)
            sim.append(acc[j])
        if new == assign:
            break
        assign = new
        sums: list[dict] = [defaultdict(float) for _ in range(k)]
        for v, j in zip(vecs, assign):
            s = sums[j]
            for t, w in v.items():
                s[t] += w
        for j in range(k):
            if not sums[j]:  # an empty theme takes the passage farthest from its own centre
                far = min(range(n), key=lambda i: (sim[i], i))
                sums[j] = defaultdict(float, vecs[far])
                assign[far] = j
            top = sorted(sums[j].items(), key=lambda x: (-x[1], x[0]))[:themes.CENTROID_TERMS]
            centres[j] = themes._unit_sparse(dict(top))
    inv = themes._inverted(centres)
    assign, sim = [], []
    for v in vecs:
        acc = themes._sdot(v, inv, k)
        j = max(range(k), key=lambda x: (acc[x], -x))
        assign.append(j)
        sim.append(acc[j])
    return assign, sim, centres


def _random_vectors(rng: random.Random, n: int, vocab: int) -> list[dict]:
    terms_ = [f"t{i:03d}" for i in range(vocab)]
    out = []
    for _ in range(n):
        base = rng.randrange(0, max(1, vocab - 8), 4)  # topics share a slice of the words
        pool = terms_[base:base + 10] + rng.sample(terms_, 3)
        v = {t: rng.random() + 0.05 for t in rng.sample(pool, rng.randint(2, min(8, len(pool))))}
        out.append(themes._unit_sparse(v))
    out += [dict(out[0]), dict(out[0]), dict(out[n // 2])]  # exact ties: the same vector again
    out += [{"only_here_1": 1.0}, {"only_here_2": 1.0}, {"only_here_3": 0.6, "only_here_4": 0.8}]  # no shared terms
    out.append({})  # no terms at all
    rng.shuffle(out)
    return out


def test_k_means_of_the_words_gives_the_same_themes_as_before_0_16():
    for n, vocab, seeds in ((8, 20, (0, 1)), (40, 60, (0, 3)), (150, 120, (0, 7)), (400, 200, (0,))):
        vecs = _random_vectors(random.Random(n), n, vocab)
        for k in (2, 3, 5, 8, 12):
            for seed in seeds:
                assert themes.kmeans_sparse(vecs, k, seed) == _old_kmeans_sparse(vecs, k, seed), (n, k, seed)
    # all vectors alike: every similarity ties
    same = [{"a": 1.0}] * 6 + [{"a": 0.6, "b": 0.8}] * 4
    for k in (2, 4):
        assert themes.kmeans_sparse(same, k, 0) == _old_kmeans_sparse(same, k, 0)


def test_assign_picks_the_first_of_the_highest():
    vecs = [{"a": 1.0}, {"z": 1.0}, {"a": 0.5, "b": 0.5}]
    inv = themes._inverted([{"a": 1.0}, {"a": 1.0}, {"b": 1.0}])
    assign, sim = themes._assign(vecs, inv, 3)
    want = [max(range(3), key=lambda x: (acc[x], -x)) for acc in (themes._sdot(v, inv, 3) for v in vecs)]
    assert assign == want == [0, 0, 2 if themes._sdot(vecs[2], inv, 3)[2] > 0.5 else 0]
    assert sim == [max(themes._sdot(v, inv, 3)) for v in vecs]


def _themes_text(i: int) -> str:
    return "\n\n".join(
        f"Report {i}, part {p}. The {a} matters for the {b}; the {a} costs more than the {c}. The {c} and the {b} "
        f"return in part {p} of this long text, so that it counts as a passage of its own."
        for p, (a, b, c) in enumerate(
            (["proton exchange membrane", "green hydrogen", "water stress", "electricity grid", "ammonia export",
              "solid oxide cell", "hydrogen valley", "offshore wind", "commuters", "tidal energy"][(i + p + o) % 10]
             for o in (0, 3, 7)) for p in range(6)))


def _members(ws: Workspace, run_id: str) -> list[tuple]:
    return [tuple(r) for r in ws.query("SELECT theme_id, passage_id, similarity FROM theme_members WHERE run_id=? "
                                       "ORDER BY passage_id", (run_id,))]


def test_a_theme_run_by_words_has_the_members_of_before_0_16(ws, tmp_path, monkeypatch):
    d = tmp_path / "themes_corpus"
    d.mkdir()
    for i in range(9):
        (d / f"report_{i}.txt").write_text(_themes_text(i))
    ingest.ingest(ws, [d])
    terms.build(ws)
    new = themes.run(ws, k=4, seed=0, mode="words")
    new_members = _members(ws, new)
    assert len(new_members) > 20 and len({m[0] for m in new_members}) > 1
    monkeypatch.setattr(themes, "kmeans_sparse", _old_kmeans_sparse)
    old = themes.run(ws, k=4, seed=0, mode="words")
    assert _members(ws, old) == new_members
    if old != new:  # the run id is new each time; the themes drawn from the members are the same too
        cols = "theme_id, size, terms_json"
        mine = lambda r: [tuple(x) for x in ws.query(  # noqa: E731
            f"SELECT {cols} FROM themes WHERE run_id=? ORDER BY theme_id", (r,))]
        assert mine(old) == mine(new)


# ---------------------------------------------------------------------------------------------
# enlens measure --timings
# ---------------------------------------------------------------------------------------------
def test_the_timings_have_the_new_steps(loaded):
    t = measure.measure_timings(loaded)
    steps = t["steps"]
    assert "profile" not in t["skipped"]
    assert steps["collocates"]["hits"] > 0 and steps["collocates"]["word"] and steps["collocates"]["seconds"] >= 0
    assert steps["keyword_pass_seconds"] >= 0 and steps["keyword_pass_candidates"]
    assert steps["profile_page_seconds"] >= 0


def test_the_timings_report_names_the_new_steps(loaded):
    out = measure.measure_project(loaded.root, [1], timings=True)
    steps = out["timings"]["steps"]
    assert {"collocates", "keyword_pass_seconds", "profile_page_seconds"} <= set(steps)
    md = measure.to_markdown({**measure.run(readers=[1]), "project": out})
    assert f"Words nearby \"{steps['collocates']['word']}\"" in md
    assert "found by keywords in every passage" in md and "The Profile page's grid and counts" in md


# ---------------------------------------------------------------------------------------------
# what the review of 0.16.0rc1 found: quitting, a crash, duplicates
# ---------------------------------------------------------------------------------------------
_SLOW_ADD = r'''
import os, sys, threading, time
from pathlib import Path
from enlens_claims import ingest
from enlens_claims.store import Workspace
folder, pids, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
plain = ingest._Readings._process
def record(self):
    p = plain(self)
    with open(pids, "a") as f:
        f.write(f"{p.pid}\n")
    return p
ingest._Readings._process = record
ws = Workspace.create(folder.parent / "ws")
stop = threading.Event()
threading.Thread(target=ingest.ingest, args=(ws, [folder]), kwargs={"workers": 2, "should_stop": stop.is_set,
                 "ocr": ingest.OcrOptions(mode="off")}, daemon=True).start()
while not pids.exists() or len(pids.read_text().split()) < 2:
    time.sleep(0.05)
time.sleep(0.5)
if mode == "quit":
    stop.set()        # as Quit does: the job is told to stop, then the app ends
    time.sleep(0.3)
    sys.exit(0)
time.sleep(60)        # "crash": the test kills this process
'''


def _long_texts(folder: Path, n: int = 3) -> None:
    folder.mkdir()
    words = " ".join(f"word{w} about electrolysers and water." for w in range(40))
    for i in range(n):
        (folder / f"long_{i}.txt").write_text("\n\n".join(f"Hydrogen paragraph {k}. {words}" for k in range(25000)))


def _alive(pid: int) -> bool:
    if os.name == "nt":
        from enlens_claims import procs

        return procs.windows_command_line(pid) is not procs.GONE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _gone_within(pids: list[int], seconds: float) -> bool:
    import time

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not any(_alive(p) for p in pids):
            return True
        time.sleep(0.1)
    return False


def test_quitting_does_not_wait_for_the_files_being_read(tmp_path):
    """Quit (and an update's restart) ended the app at once while a file was being read before 0.16; the reading
    threads must not hold the app open, and the reading processes end with it."""
    import time

    _long_texts(tmp_path / "batch")
    (tmp_path / "add.py").write_text(_SLOW_ADD)
    env = {**os.environ, "PYTHONPATH": SRC}
    t = time.monotonic()
    subprocess.run([sys.executable, str(tmp_path / "add.py"), str(tmp_path / "batch"), str(tmp_path / "pids"), "quit"],
                   env=env, timeout=120, check=True)
    assert time.monotonic() - t < 25  # each file takes far longer to read than this
    pids = [int(x) for x in (tmp_path / "pids").read_text().split()]
    assert pids and _gone_within(pids, 5)


def test_a_crash_of_the_app_leaves_no_reading_behind(tmp_path):
    import time

    _long_texts(tmp_path / "batch")
    (tmp_path / "add.py").write_text(_SLOW_ADD)
    env = {**os.environ, "PYTHONPATH": SRC}
    app = subprocess.Popen([sys.executable, str(tmp_path / "add.py"), str(tmp_path / "batch"), str(tmp_path / "pids"),
                            "crash"], env=env)
    try:
        end = time.monotonic() + 60
        while time.monotonic() < end and (not (tmp_path / "pids").exists()
                                          or len((tmp_path / "pids").read_text().split()) < 2):
            time.sleep(0.05)
        time.sleep(0.5)
        pids = [int(x) for x in (tmp_path / "pids").read_text().split()]
        assert pids and all(_alive(p) for p in pids)
        app.kill()  # as a forced quit or a crash: no exit handler runs
        app.wait(timeout=10)
        assert _gone_within(pids, 5)
    finally:
        if app.poll() is None:
            app.kill()


def test_a_duplicate_is_read_but_not_made_into_a_document(tmp_path, monkeypatch):
    """As before 0.16: a file already in the project is read (its checksum says so) and counted, never built."""
    folder = _folder(tmp_path)
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [folder], ocr=OFF, workers=1)
    built = []
    plain = ingest.build_document
    monkeypatch.setattr(ingest, "build_document", lambda *a, **k: built.append(1) or plain(*a, **k))
    again = ingest.ingest(ws, [folder], ocr=OFF, workers=1)
    # only broken.pdf, which the first add read into too little text to keep (so it is no duplicate), is built again
    assert built == [1] and again["added"] == 0 and again["duplicates"] >= 6 and again["empty_files"] == ["broken.pdf"]
    pdf = folder / "paper_2.pdf"
    raw = ingest.read_file(pdf, OFF)
    got = ingest._read_whole(pdf, OFF, 1100, 200, None, frozenset([raw.sha1]))
    assert got[0] == "ok" and got[2] is None and got[1].sha1 == raw.sha1
    assert ingest._checksum(pdf) == raw.sha1 and ingest._checksum(folder / "note_0.txt") == ingest.read_file(
        folder / "note_0.txt", OFF).sha1
    s2 = ingest.ingest(ws, [folder], ocr=OFF, workers=2)  # the same through the reading processes
    assert s2["added"] == 0 and s2["duplicates"] == again["duplicates"] and s2.get("failed") == again.get("failed")


def test_no_reading_thread_to_be_had_reads_here_without_waiting(tmp_path, monkeypatch):
    folder = _folder(tmp_path)
    s1, rows1 = _one_at_a_time(tmp_path, folder)
    plain_start = threading.Thread.start

    def start(self):
        if self.name.startswith("enlens-read-"):
            raise RuntimeError("can't start new thread")
        return plain_start(self)

    monkeypatch.setattr(threading.Thread, "start", start)
    out = {}
    t = threading.Thread(target=lambda: out.update(r=_ingest_in(tmp_path, "nothreads", folder, workers=2)), daemon=True)
    plain_start(t)
    t.join(120)
    assert not t.is_alive(), "adding hung with no reading thread"
    s2, rows2 = out["r"]
    assert "read_at_once" not in s2 and s2 == s1 and rows2 == rows1


def test_once_enlens_is_ending_no_reading_process_starts(tmp_path, monkeypatch):
    """Before an update's restart the reading processes are ended; a file still to read is read here, and no new
    reading process starts that the restart (same process number) would leave running."""
    folder = _folder(tmp_path)
    s1, rows1 = _one_at_a_time(tmp_path, folder)
    monkeypatch.setattr(ingest, "_ENDING", False)  # restored after the test
    ingest.end_reading_processes()
    started = []
    real = subprocess.Popen
    monkeypatch.setattr(subprocess, "Popen", lambda args, *a, **k: started.append(args) or real(args, *a, **k))
    s2, rows2 = _ingest_in(tmp_path, "ending", folder, workers=2)
    assert started == [] and _without_read_at_once(s2) == _without_read_at_once(s1) and rows2 == rows1
