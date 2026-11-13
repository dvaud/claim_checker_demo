"""0.17.2: the themes by words use numpy for their k-means when it is installed, and a theme's page builds only that
theme.

- the numpy k-means gives the same assignment, the same similarities and the same centres, to the last bit, as the
  pure-Python one (which defines the result), also on ties, empty vectors, empty themes and long vectors;
- without numpy (hidden by a test) the pure-Python one runs and a run of the themes is the same;
- `themes.view(only=...)` gives that theme exactly as the whole view does, and a theme's page the same as before.
"""
from __future__ import annotations

import random
import sys

import pytest

from enlens_claims import themes

from test_remove_themes import topics_corpus
from test_app import Api, api, home  # noqa: F401  (fixtures)

np = pytest.importorskip("numpy")


def _vectors(rng: random.Random, n: int, vocab: int, longest: int = 8) -> list[dict]:
    terms_ = [f"t{i:03d}" for i in range(vocab)]
    out = []
    for _ in range(n):
        base = rng.randrange(0, max(1, vocab - 8), 4)
        pool = terms_[base:base + 10] + rng.sample(terms_, 3)
        v = {t: rng.random() + 0.05 for t in rng.sample(pool, rng.randint(2, min(longest, len(pool))))}
        out.append(themes._unit_sparse(v))
    out += [dict(out[0]), dict(out[0]), dict(out[n // 2])]                                       # exact ties
    out += [{"only_here_1": 1.0}, {"only_here_2": 1.0}, {"only_here_3": 0.6, "only_here_4": 0.8}]  # no shared words
    out.append({})                                                                               # no words at all
    rng.shuffle(out)
    return out


def _same(a, b):
    # lists of ints, floats and dicts: `==` on floats is the exact comparison wanted here
    assert a[0] == b[0]
    assert [float.hex(x) for x in a[1]] == [float.hex(x) for x in b[1]]
    assert len(a[2]) == len(b[2])
    for ca, cb in zip(a[2], b[2]):
        assert list(ca) == list(cb)                       # the same words in the same order
        assert [float.hex(x) for x in ca.values()] == [float.hex(x) for x in cb.values()]


def test_the_numpy_k_means_is_the_pure_python_one_to_the_last_bit():
    for n, vocab, seeds in ((8, 20, (0, 1)), (40, 60, (0, 3)), (150, 120, (0, 7)), (400, 200, (0, 2))):
        vecs = _vectors(random.Random(n), n, vocab)
        for k in (2, 3, 5, 8, 12):
            for seed in seeds:
                _same(themes._kmeans_sparse_py(vecs, k, seed), themes.kmeans_sparse(vecs, k, seed))


def test_the_numpy_k_means_agrees_on_all_alike_few_words_and_long_vectors(monkeypatch):
    same = [{"a": 1.0}] * 6 + [{"a": 0.6, "b": 0.8}] * 4          # every similarity ties; empty themes follow
    for k in (2, 4, 9):
        _same(themes._kmeans_sparse_py(same, k, 0), themes.kmeans_sparse(same, k, 0))
    vecs = _vectors(random.Random(5), 120, 90, longest=12)
    monkeypatch.setattr(themes, "CENTROID_TERMS", 3)                # a centre keeps only its 3 heaviest words
    for k in (3, 7):
        _same(themes._kmeans_sparse_py(vecs, k, 1), themes.kmeans_sparse(vecs, k, 1))
    # more themes than there are passages
    few = _vectors(random.Random(1), 3, 10)[:5]
    _same(themes._kmeans_sparse_py(few, 12, 0), themes.kmeans_sparse(few, 12, 0))


def test_the_numpy_path_is_the_one_that_runs_when_numpy_is_there(monkeypatch):
    vecs = _vectors(random.Random(2), 30, 40)
    want = themes._kmeans_sparse_py(vecs, 4, 0)
    monkeypatch.setattr(themes, "_kmeans_sparse_py", lambda *a, **k: pytest.fail("the pure-Python path ran"))
    _same(want, themes.kmeans_sparse(vecs, 4, 0))


def test_without_numpy_the_pure_python_path_runs(monkeypatch):
    vecs = _vectors(random.Random(3), 30, 40)
    want = themes._kmeans_sparse_py(vecs, 4, 0)
    monkeypatch.setitem(sys.modules, "numpy", None)                 # `import numpy` now raises ImportError
    monkeypatch.setattr(themes, "_kmeans_sparse_np", lambda *a, **k: pytest.fail("the numpy path ran"))
    _same(want, themes.kmeans_sparse(vecs, 4, 0))


def test_a_stop_asked_for_stops_the_numpy_k_means_too():
    vecs = _vectors(random.Random(4), 30, 40)
    with pytest.raises(type(themes._stopped())):
        themes.kmeans_sparse(vecs, 4, 0, should_stop=lambda: True)


def _members(ws, run):
    return [tuple(r) for r in ws.query("SELECT theme_id, passage_id, similarity FROM theme_members WHERE run_id=? "
                                       "ORDER BY passage_id", (run,))]


def test_a_run_of_the_themes_by_words_is_the_same_without_numpy(home, tmp_path, monkeypatch):
    from enlens_claims import ingest

    ws = home.create_project("T")
    ingest.ingest(ws, [topics_corpus(tmp_path / "topics")])
    run = themes.run(ws, k=5, seed=0, mode="words")
    with_np = _members(ws, run)
    monkeypatch.setitem(sys.modules, "numpy", None)
    run2 = themes.run(ws, k=5, seed=0, mode="words")
    assert run2 != run and _members(ws, run2) == with_np


# ---------------------------------------------------------------------------------------------
# a theme's page builds only that theme
# ---------------------------------------------------------------------------------------------
@pytest.fixture
def edited(home, tmp_path):
    from enlens_claims import ingest

    ws = home.create_project("T")
    ingest.ingest(ws, [topics_corpus(tmp_path / "topics")])
    run = themes.run(ws, k=6, seed=0, mode="words")
    v = themes.view(ws, run)
    ids = [t["theme_id"] for t in v["themes"]]
    themes.edit(ws, run, "rename", ids[0], "A name of my own")
    themes.edit(ws, run, "merge", ids[1], ids[2])
    page = themes.theme_passages(ws, run, ids[3], limit=5)
    themes.edit(ws, run, "move", None, ids[4], passage_id=page["passages"][0]["passage_id"])
    themes.edit(ws, run, "remove", ids[5], True)
    return ws, run


def test_the_view_of_one_theme_is_that_theme_exactly_as_the_whole_view_has_it(edited):
    ws, run = edited
    whole = themes.view(ws, run)
    for t in whole["themes"] + whole["removed"]:
        part = themes.view(ws, run, only=t["theme_id"])
        mine = next(x for x in part["themes"] + part["removed"] if x["theme_id"] == t["theme_id"])
        assert mine == t
        for x in whole["themes"] + whole["removed"]:   # the others: the same id, number, name, size and flags
            o = next(y for y in part["themes"] + part["removed"] if y["theme_id"] == x["theme_id"])
            for key in ("number", "name", "size", "removed", "merged_from"):
                assert o[key] == x[key]
        assert [x["theme_id"] for x in part["themes"]] == [x["theme_id"] for x in whole["themes"]]
        assert [x["theme_id"] for x in part["removed"]] == [x["theme_id"] for x in whole["removed"]]


def test_a_themes_page_is_what_it_was_and_makes_no_grids(edited, monkeypatch):
    ws, run = edited
    whole = themes.view(ws, run)
    wanted = {}
    real = themes.view
    monkeypatch.setattr(themes, "view", lambda w, r, framework=None, only=None: real(w, r, framework))  # as before
    for t in whole["themes"] + whole["removed"]:
        for offset in (0, 3):
            wanted[t["theme_id"], offset] = themes.theme_passages(ws, run, t["theme_id"], offset, 4)
    monkeypatch.undo()
    # and now: the grids, the document list and the key terms the glossary leaves out are never made
    monkeypatch.setattr(themes, "_left_out", lambda *a, **k: pytest.fail("the key terms were checked for a page"))
    for (tid, offset), want in wanted.items():
        got = themes.theme_passages(ws, run, tid, offset, 4)
        assert got == want
        assert [o["number"] for o in got["others"]] == [o["number"] for o in want["others"]]
    with pytest.raises(KeyError):
        themes.theme_passages(ws, run, 99999)
