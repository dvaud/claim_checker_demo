"""The explore modules after a review of 0.17.0: the glossary, themes, codebook profiles, codebooks and the
concordance cost less time and memory for the same results, and a few wrong results are put right:

- the glossary is the same mention for mention, with its mentions kept as numbers and its text read a document at a
  time; a kept blob that would unpack to too much is taken for a damaged one;
- themes by words group the passages as before (the last round of k-means is not repeated);
- the runs that send several tasks in a row (labels, theme names, concept links) work each task's setting out again
  as its text leaves, so a document's cap holds within one run;
- an example quote with a capital accented letter or a ligature is found; a codebook's history shows only changes
  that were written;
- the concordance keeps its last searches, so another page or another sort of the same search is a slice.
"""
from __future__ import annotations

import zlib
from pathlib import Path

import pytest
from helpers_0110 import Cloud, use_local_model

from enlens_claims import access, terms, themes
from enlens_claims import home as core
from enlens_claims.textutil import stem

# words no list of common words has: each section of the capped report has its own term
WORDS = ["zorbax", "quintel", "mirandol", "feldspar", "cobaltine", "veridian", "tamarack", "osmund", "pellucid",
         "quassia"]


@pytest.fixture
def capped(tmp_path, monkeypatch):
    """One document of ten sections, each naming a term of its own three times, that Claude may read up to 20 % of;
    no local model is chosen (a task over the cap waits for the person)."""
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    use_local_model(monkeypatch, None)
    c = tmp_path / "c"
    c.mkdir()
    paras = [f"Section {i:02d}. The {w} unit of this plant runs on green hydrogen in an arid region. Each {w} unit "
             f"needs fresh water, land and steady sun, and the engineers on site check every {w} unit in some detail "
             f"before the plant takes on the next stage of its work in section {i:02d}." for i, w in enumerate(WORDS)]
    (c / "capped.txt").write_text("Capped report\n\n" + "\n\n".join(paras) + "\n")
    ws = core.create_project("Cap")
    from enlens_claims import ingest

    ingest.ingest(ws, [c], ai_access="cloud")
    doc = ws.scalar("SELECT doc_id FROM documents")
    access.set_documents(ws, [doc], budget=20)
    return ws, doc


def _sent_within_cap(ws, doc: str, cap: float = 20) -> int:
    """Replays what left, task by task in the order sent: each task went while what Claude had read of the document
    was below the cap, or showed only passages it had read already. Returns the number of tasks sent."""
    size = {r[0]: r[1] for r in ws.query("SELECT passage_id, LENGTH(text) FROM passages WHERE doc_id=?", (doc,))}
    total = sum(size.values())
    order: dict[str, set] = {}
    for tid, pid in ws.query("SELECT task_id, passage_id FROM ai_sent WHERE doc_id=? ORDER BY rowid", (doc,)):
        order.setdefault(tid, set()).add(pid)
    read: set[str] = set()
    for tid, pids in order.items():
        share = sum(size[p] for p in read) * 100 / total
        assert share < cap or pids <= read, f"{tid} was sent with {share:.0f} % of the document read already"
        read |= pids
    return len(order)


def test_a_run_of_label_tasks_keeps_within_a_documents_cap(capped):
    ws, doc = capped
    from enlens_claims import profile

    pids = [r[0] for r in ws.query("SELECT passage_id FROM passages WHERE doc_id=? AND section='body' ORDER BY seq "
                                   "LIMIT 5", (doc,))]
    assert len(pids) == 5
    out = profile.run_labels(ws, "sdg", Cloud(), "m", all_passages=True, passage_ids=pids)
    sent = _sent_within_cap(ws, doc)
    assert 0 < sent < 5 and out["skipped_restricted"] == 5 - sent
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='label' AND access='local' AND "
                     "status='pending'") == 5 - sent


def test_a_run_of_link_tasks_keeps_within_a_documents_cap(capped):
    ws, doc = capped
    terms.build(ws)
    ids = [terms.term_id(f"{stem(w)} unit") for w in WORDS]
    assert ws.scalar(f"SELECT COUNT(*) FROM terms WHERE term_id IN ({','.join('?' * len(ids))})", ids) == len(ids)
    pairs = [(ids[i], ids[i + 1]) for i in range(0, len(ids), 2)]
    terms.judge_links(ws, pairs, Cloud(), "m")
    sent = _sent_within_cap(ws, doc)
    assert 0 < sent < len(pairs)
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='link' AND access='local'") == len(pairs) - sent


def test_naming_themes_keeps_within_a_documents_cap(capped):
    ws, doc = capped
    rid = themes.run(ws, k=5, seed=0, mode="words")
    themes.name_with_model(ws, rid, Cloud(), "m")
    sent = _sent_within_cap(ws, doc)
    n = ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='theme'")
    assert 0 < sent < n
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='theme' AND access='local'") == n - sent


# ---------------------------------------------------------------------------------------------
# the glossary: the same mentions, for less memory
# ---------------------------------------------------------------------------------------------
DEMO = Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"


@pytest.fixture
def demo(tmp_path):
    from enlens_claims import ingest
    from enlens_claims.store import Workspace

    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [DEMO])
    return ws


def _glossary(ws) -> list:
    return [[tuple(r) for r in ws.query(q)] for q in ("SELECT * FROM terms ORDER BY rowid",
                                                      "SELECT * FROM term_mentions ORDER BY term_id, passage_id, start, end")]


def _scratch(ws, tmp_path, name: str):
    """The project copied without its kept readings, and its glossary made there from scratch."""
    import shutil

    from enlens_claims.store import Workspace

    copy = tmp_path / name
    shutil.copytree(ws.root, copy, ignore=shutil.ignore_patterns("cache", "*.sqlite-shm"))
    other = Workspace.open(copy)
    assert terms.build(other)["documents_kept"] == 0
    return other


def test_a_glossary_made_from_scratch_writes_its_places_in_the_order_of_the_key_and_keeps_its_index(demo, monkeypatch):
    """0.17.2: the places are written in the order of the table's key (a table WITHOUT ROWID is its key), so its pages
    are filled in order; the one index is made again after them."""
    from enlens_claims import store

    written = []
    real = store._Cx.executemany

    def spy(self, sql, rows):
        if "term_mentions" in sql:
            rows = list(rows)
            written.extend(rows)
        return real(self, sql, rows)

    monkeypatch.setattr(store._Cx, "executemany", spy)
    terms.build(demo)
    monkeypatch.setattr(store._Cx, "executemany", real)
    assert len(written) > 100 and written == sorted(written)
    assert written == [tuple(r) for r in demo.query("SELECT term_id, passage_id, start, end FROM term_mentions "
                                                    "ORDER BY term_id, passage_id, start, end")]
    have = {r[0] for r in demo.query("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='term_mentions'")}
    assert {name for name, _sql in terms._mention_indexes()} <= have and len(terms._mention_indexes()) == 1
    assert "WITHOUT ROWID" in demo.scalar("SELECT sql FROM sqlite_master WHERE name='term_mentions'")


def test_a_document_read_again_while_the_glossary_is_made_starts_the_build_again(demo, tmp_path, monkeypatch):
    terms.build(demo)
    doc = demo.scalar("SELECT doc_id FROM passages WHERE section='body' ORDER BY doc_id LIMIT 1")
    real = terms._body_rows
    calls = {"n": 0}

    def rows(ws, d):
        if d == doc:
            calls["n"] += 1
            if calls["n"] == 2:   # its text changes between the first reading and the second
                with ws.connect() as cx:
                    cx.execute("UPDATE passages SET text=replace(text, 'e', 'a') WHERE doc_id=?", (d,))
                    ws.bump_corpus(cx)
        return real(ws, d)

    monkeypatch.setattr(terms, "_body_rows", rows)
    (demo.root / "cache" / "glossary.sqlite").unlink()   # every document read: its text is read a second time
    terms.build(demo)
    monkeypatch.setattr(terms, "_body_rows", real)
    assert calls["n"] > 3 and not terms.status(demo)["stale"]
    assert _glossary(demo) == _glossary(_scratch(demo, tmp_path, "scratch"))


def test_a_kept_reading_that_unpacks_to_too_much_is_made_again(demo, tmp_path, monkeypatch):
    from enlens_claims import searchindex

    terms.build(demo)
    before = _glossary(demo)
    bomb = zlib.compress(b" " * 50_000)
    with pytest.raises(zlib.error):
        searchindex.unzip(bomb, 10_000)
    assert searchindex.unzip(bomb, 60_000) == b" " * 50_000
    monkeypatch.setattr(searchindex, "MAX_UNPACKED", 1000)   # every kept reading is now "too large"
    assert terms._decode(zlib.compress(b'{"keys": []}' + b" " * 2000), None) is None
    assert searchindex._unpack(zlib.compress(b"[" + b" " * 2000 + b"]"), "words") is None
    st = terms.build(demo)
    assert st["documents_read"] == st["documents_kept"] + st["documents_read"] > 0
    assert _glossary(demo)[1] == before[1]


def _released_passage_term_counts(ws):
    """passage_term_counts as 0.17.0 had it."""
    from collections import Counter, defaultdict

    places = defaultdict(list)
    for pid, tid, a, b in ws.query("SELECT passage_id, term_id, start, end FROM term_mentions"):
        places[pid].append((a, b, tid))
    out = defaultdict(Counter)
    for pid in sorted(places):
        c = out[pid]
        for _a, _b, tid in sorted(places[pid]):
            c[tid] += 1
    return out


def test_the_terms_of_each_passage_are_the_same_in_the_same_order(demo):
    terms.build(demo)
    got, want = terms.passage_term_counts(demo), _released_passage_term_counts(demo)
    assert [(p, list(c.items())) for p, c in got.items()] == [(p, list(c.items())) for p, c in want.items()]
    doc = demo.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
    assert terms._docs_with_terms(demo) == demo.scalar("SELECT COUNT(DISTINCT p.doc_id) FROM term_mentions m JOIN "
                                                       "passages p ON p.passage_id=m.passage_id") > 1
    assert terms.key_terms(demo, doc_id=doc) == terms.key_terms(demo, doc_id=doc, _docs=terms._docs_with_terms(demo))


# ---------------------------------------------------------------------------------------------
# themes by words: the same groups
# ---------------------------------------------------------------------------------------------
def _released_kmeans_sparse(vecs, k, seed=0):
    """kmeans_sparse as 0.17.0 had it (the last round of assigning repeated after it converged)."""
    import random
    from collections import defaultdict

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
    assign = None
    for _it in range(themes.MAX_ITER):
        new, sim = themes._assign(vecs, themes._inverted(centres), k)
        if new == assign:
            break
        assign = new
        sums = [defaultdict(float) for _ in range(k)]
        for v, j in zip(vecs, assign):
            for t, w in v.items():
                sums[j][t] += w
        for j in range(k):
            if not sums[j]:
                far = min(range(n), key=lambda i: (sim[i], i))
                sums[j] = defaultdict(float, vecs[far])
                assign[far] = j
            top = sorted(sums[j].items(), key=lambda x: (-x[1], x[0]))[:themes.CENTROID_TERMS]
            centres[j] = themes._unit_sparse(dict(top))
    assign, sim = themes._assign(vecs, themes._inverted(centres), k)
    return assign, sim, centres


def test_themes_by_words_group_the_passages_as_before(demo):
    terms.build(demo)
    rows, _dropped = themes._passages(demo)
    vecs, _keep = themes._vectors(demo, "words", None, rows, terms.passage_term_counts(demo))
    for seed in (0, 1, 7):
        for k in (2, 5, 9):
            assert themes.kmeans_sparse(vecs, k, seed) == _released_kmeans_sparse(vecs, k, seed)


# ---------------------------------------------------------------------------------------------
# codebook profiles: the same candidates
# ---------------------------------------------------------------------------------------------
def _released_candidates(fw, text, idf):
    from enlens_claims import profile

    toks, _w = profile._words(text)
    have = set(toks)
    lex_hits = fw.lexicon_hits(text) if fw.lexicon else set()
    scores = fw.scores(text, toks, lex_hits)
    cands = {}
    for code, sc in sorted(scores.items(), key=lambda x: -x[1])[:profile.MAX_CANDIDATES * 3]:
        want = fw.code_stems(code)
        if want:
            shared = want & have
            cov = sum(idf.get(t, 1.0) for t in shared) / (sum(idf.get(t, 1.0) for t in want) or 1.0)
            shared = sorted(shared)
        else:
            cov, shared = 0.0, []
        lexicon = code in lex_hits
        if cov < profile.KEYWORD_FLOOR and not lexicon:
            continue
        cands[code] = {"score": round(sc, 3), "coverage": round(cov, 3), "matched": shared, "lexicon": lexicon}
    return cands


def test_the_keyword_pass_finds_the_same_candidates_in_the_same_order(demo):
    from enlens_claims import frameworks, profile, search

    fw = frameworks.get("sdg", demo)
    idx = search.passage_index(demo)
    totals: dict = {}
    for r in idx.read(range(len(idx.ids))):
        got = profile.keyword_candidates(fw, r["text"], idx.bm25.idf, totals)
        assert list(got.items()) == list(_released_candidates(fw, r["text"], idx.bm25.idf).items())


def test_what_the_model_read_of_a_document_is_counted_from_its_own_tasks(demo):
    from enlens_claims import profile, tasks

    docs = [r[0] for r in demo.query("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 2")]
    with demo.connect() as cx:
        for d in docs:
            pids = cx.execute("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 3", (d,)).fetchall()
            for pid, in pids:
                tasks._insert_task(cx, f"label:sdg:{pid}", "label", "m", {"passage_id": pid, "doc_id": d})
        cx.execute("UPDATE tasks SET status='done' WHERE task_id != (SELECT MIN(task_id) FROM tasks)")
    want = demo.scalar("SELECT COUNT(*) FROM tasks WHERE kind='label' AND status='done' AND "
                       "json_extract(payload_json, '$.doc_id')=?", (docs[0],))
    assert profile.doc_profile(demo, "sdg", docs[0])["read_by_model"] == want == 2


# ---------------------------------------------------------------------------------------------
# codebooks: examples found whatever their letters; a history of changes that happened
# ---------------------------------------------------------------------------------------------
def test_an_example_with_a_capital_accented_letter_or_a_ligature_is_found(tmp_path):
    from enlens_claims import codebooks, ingest
    from enlens_claims.store import Workspace

    ws = Workspace.create(tmp_path / "ws")
    c = tmp_path / "c"
    c.mkdir()
    (c / "a.txt").write_text("A report\n\nÖkowind 2026 or before is the plan of the town. The ﬁnancing of the plant "
                             "comes from a green bond, and the ﬂoating panels follow in a later stage of the work.\n")
    ingest.ingest(ws, [c])
    with ws.connect() as cx:   # as a PDF's text can have them (reading a text file folds them)
        cx.execute("UPDATE passages SET text=replace(replace(text, 'financing', 'ﬁnancing'), 'floating', "
                   "'ﬂoating')")
    assert ws.scalar("SELECT COUNT(*) FROM passages WHERE instr(text, 'ﬁnancing') > 0") == 1
    got = codebooks.find_example(ws, "Ökowind 2026 or before is the plan")
    assert got and got["quote"] == "Ökowind 2026 or before is the plan"
    assert "ﬁnancing" in codebooks.find_example(ws, "the financing of the plant comes from a green bond")["quote"]
    assert codebooks.find_example(ws, "the floating panels follow") is not None
    assert codebooks.find_example(ws, "Ökowind 2027 or after") is None
    assert codebooks.find_examples(ws, ["Ökowind 2026 or before", "nothing like this at all"]) == {
        "Ökowind 2026 or before": codebooks.find_example(ws, "Ökowind 2026 or before"),
        "nothing like this at all": None}


def test_a_codebook_change_that_cannot_be_written_leaves_no_version_and_loses_none(demo, monkeypatch):
    from enlens_claims import codebooks

    cb = codebooks.create(demo, "remote", "Remote work", "project", "fresh")
    for i in range(3):
        st = codebooks.state_of(demo, "remote")
        st["codes"] = st["codes"] + [{"code": f"Code {i}", "description": f"The code number {i}.", "group": "",
                                      "include": "", "exclude": "", "keywords": [], "examples": []}]
        codebooks.save(demo, "remote", st)
    files = lambda: sorted(p.name for p in codebooks._version_files(demo, "remote"))  # noqa: E731
    before = files()
    assert len(before) >= 2 and cb
    monkeypatch.setattr(codebooks, "KEEP", len(before))   # a new version would push the oldest out

    def busy(*a, **kw):
        raise ValueError(codebooks._BUSY)

    monkeypatch.setattr(codebooks, "_write", busy)
    st = codebooks.state_of(demo, "remote")
    st["codes"] = st["codes"][1:]
    with pytest.raises(ValueError, match="open in another program"):
        codebooks.save(demo, "remote", st)
    assert files() == before


# ---------------------------------------------------------------------------------------------
# search: the last searches kept, an index kept when only titles change, one codebook per file
# ---------------------------------------------------------------------------------------------
def test_another_page_or_sort_of_a_search_is_the_same_as_the_search_made_afresh(demo, monkeypatch):
    from enlens_claims import concordance

    calls = [("work", "any", {}), ("home office", "near", {"near": 3}), ('"working from home"', "phrase", {}),
             ("commuting emissions", "all", {}), ("work", "any", {"exact": True})]
    for q, mode, kw in calls:
        for sort, off in (("doc", 0), ("doc", 5), ("left", 0), ("right", 3), ("left", 7), ("doc", 2)):
            kept = concordance.search(demo, q, mode, sort=sort, offset=off, limit=5, **kw)
            concordance._KEPT.clear()
            assert kept == concordance.search(demo, q, mode, sort=sort, offset=off, limit=5, **kw)
            concordance._KEPT.clear()
            concordance.search(demo, q, mode, sort="doc", **kw)   # kept with another sort first
    assert concordance._KEPT
    monkeypatch.setattr(concordance, "_search_hits", lambda *a, **kw: pytest.fail("searched again"))
    concordance.search(demo, "work", "any", sort="right", offset=10, limit=5, exact=True)


def test_a_search_by_code_is_not_kept(demo):
    from enlens_claims import concordance

    concordance._KEPT.clear()
    concordance.search(demo, "work", code="sdg:8.5")
    assert not concordance._KEPT


def test_a_title_changed_keeps_the_words_of_the_index_and_shows_the_new_title(demo):
    from enlens_claims import search

    idx = search.passage_index(demo)
    doc = idx.doc_of[0]
    with demo.connect() as cx:
        cx.execute("UPDATE documents SET title='A new title' WHERE doc_id=?", (doc,))
        demo.set_meta("titles_version", 7, cx)
    again = search.passage_index(demo)
    assert again is not idx and again.bm25 is idx.bm25 and again.ids == idx.ids
    assert again.rows[0]["title"] == "A new title"


def test_a_codebook_saved_again_and_again_is_held_once(demo):
    from enlens_claims import codebooks, frameworks

    codebooks.create(demo, "remote", "Remote work", "project", "fresh")
    for i in range(4):
        st = codebooks.state_of(demo, "remote")
        st["codes"] = st["codes"] + [{"code": f"Code {i}", "description": f"The code number {i}.", "group": "",
                                      "include": "", "exclude": "", "keywords": [], "examples": []}]
        codebooks.save(demo, "remote", st)
        frameworks.get("remote", demo)
    path = str(codebooks.locate(demo, "remote")[1] / "remote.csv")
    assert sum(1 for k in frameworks._CACHE if k[0] == path) == 1
