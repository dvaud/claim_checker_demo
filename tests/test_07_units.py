"""0.7 unit tests: offsets, concordance exactness, abbreviations, running heads, k-means determinism, highlight
placement, the FlexiConc export, the SDG pack, and the new CLI commands."""
from __future__ import annotations

import json
import random
import re
import sqlite3
from pathlib import Path

import pytest

from helpers import make_pdf

from enlens_claims import concordance, terms, themes
from enlens_claims.textutil import token_spans, tokens

SAMPLES = [
    "Green hydrogen’s water footprint—in arid regions—can rise; it’s “stress” on aquifers (e.g. Morocco).",
    "Proton exchange membrane (PEM) electrolysers cost USD 1,000/kW in 2020, and alkaline ones less.",
    "Ligatures: ﬁnance ﬂows; accents: café, naïve, Zürich; dashes – and — ; non‑breaking hyphen.",
    "ÉLECTROLYSE   à   l'échelle   industrielle\n\nNew paragraph with  double  spaces.",
    "",
]


@pytest.mark.parametrize("text", SAMPLES)
def test_token_spans_agree_with_tokens(text):
    spans = token_spans(text)
    assert [s[2] for s in spans] == tokens(text)
    for a, b, stem, _word in spans:
        assert a < b and tokens(text[a:b]) == [stem]   # the offsets cover exactly the word


def test_concordance_exact_counts_equal_a_regular_expression(loaded):
    texts = [r[0] for r in loaded.query("SELECT text FROM passages WHERE section='body'")]
    for q in ("water", "hydrogen", "Morocco", "water stress", "export hubs", "jobs"):
        res = concordance.search(loaded, q, exact=True, mode="phrase", limit=500)
        rx = re.compile(r"(?<![^\W_])" + re.escape(q) + r"(?![^\W_])", re.I)
        assert res["total"] == sum(len(rx.findall(t)) for t in texts), q
    # every line's keyword is the words searched for, at the offsets given
    res = concordance.search(loaded, "water stress", mode="phrase", limit=50)
    assert res["total"] >= 1
    full = {r["doc_id"]: r["text"] for r in loaded.query("SELECT doc_id, text FROM documents")}
    for line in res["lines"]:
        assert line["node"].lower() == "water stress"
        assert full[line["doc_id"]][line["start"]:line["end"]].lower() == "water stress"


def test_concordance_modes(loaded):
    any_ = concordance.search(loaded, "water farming", mode="any")["total"]
    all_ = concordance.search(loaded, "water farming", mode="all")["total"]
    near = concordance.search(loaded, "compete groundwater", mode="near", near=5)["total"]
    assert any_ >= all_ >= 1 and near >= 1
    with pytest.raises(ValueError):
        concordance.search(loaded, "water", mode="nonsense")


def test_schwartz_hearst_abbreviations():
    got = dict(terms.abbreviations("Proton exchange membrane (PEM) electrolysers and solid oxide electrolysis cells "
                                   "(SOEC) are compared with the levelised cost of hydrogen (LCOH)."))
    assert got.get("PEM", "").lower() == "proton exchange membrane"
    assert got.get("SOEC", "").lower() == "solid oxide electrolysis cells"
    assert got.get("LCOH", "").lower() == "levelised cost of hydrogen"
    # not an abbreviation: no capital letter, or not ending in a letter or digit
    assert not terms.abbreviations("the (cost-) of capital and (see below) the rate")


def test_running_heads_are_left_out_of_the_glossary():
    head = "Journal of Energy in Southern Africa Vol 33 February 2022"
    rows, start = [], 0
    for page in range(1, 7):
        text = (f"{80 + page} {head} " + "Body text here. " * 12 + "The electrolyser stack degrades with cycling. "
                + "More body text. " * 12)
        rows.append({"passage_id": f"p{page}", "doc_id": "d1", "page": page, "start": start, "text": text})
        start += len(text) + 2
    edges, boiler = terms.running_heads(rows)
    keys = {k for d, k in boiler if d == "d1"}
    assert any("southern" in k for k in keys) and all("degrad" not in k for k in keys)
    assert set(edges) == {f"p{i}" for i in range(1, 7)}


def test_kmeans_is_deterministic_for_a_seed():
    rng = random.Random(3)
    vecs = []
    for i in range(60):
        v = {f"t{(i % 3) * 10 + j}": rng.random() + 1 for j in range(5)}
        n = sum(x * x for x in v.values()) ** 0.5
        vecs.append({t: x / n for t, x in v.items()})
    a1, s1, _ = themes.kmeans_sparse(vecs, 3, seed=5)
    a2, s2, _ = themes.kmeans_sparse(vecs, 3, seed=5)
    assert a1 == a2 and s1 == s2
    # the three planted groups are found
    groups = {}
    for i, a in enumerate(a1):
        groups.setdefault(i % 3, set()).add(a)
    assert all(len(g) == 1 for g in groups.values())
    np = pytest.importorskip("numpy")
    X = np.array([[v.get(f"t{j}", 0.0) for j in range(30)] for v in vecs])
    d1 = themes.kmeans_dense(X, 3, seed=5)
    d2 = themes.kmeans_dense(X, 3, seed=5)
    assert d1[0] == d2[0] and d1[1] == d2[1]


def test_highlights_land_inside_the_page(tmp_path):
    from pypdf import PdfReader

    from enlens_claims import annotate

    pdf = make_pdf(tmp_path / "a.pdf", ["Green hydrogen needs water. Its production can increase water stress in "
                                        "arid regions such as Morocco.", "A second page about export hubs and jobs."])
    marks = [annotate.Mark(0, 0, "increase water stress in arid regions", "supports", "Supports: H1", "judgements", 1),
             annotate.Mark(0, 0, "export hubs and jobs", "label", "8.5", "labels", 2),
             annotate.Mark(0, 0, "words that are nowhere in the file", "refutes", "H2", "judgements", 1)]
    for use_pdfminer in (True, False):
        for m in marks:
            m.placed, m.quads = False, []
        annotate.place(pdf, marks, use_pdfminer=use_pdfminer)
        assert [m.placed for m in marks] == [True, True, False]
        reader = PdfReader(str(pdf))
        for m in marks[:2]:
            box = reader.pages[m.page - 1].mediabox
            for x0, y0, x1, y1 in m.quads:
                assert float(box.left) - 1 <= x0 < x1 <= float(box.right) + 1
                assert float(box.bottom) - 1 <= y0 < y1 <= float(box.top) + 1
    out = annotate.write_pdf(pdf, marks, title="H1")
    (tmp_path / "out.pdf").write_bytes(out)
    annots = [a.get_object() for p in PdfReader(str(tmp_path / "out.pdf")).pages for a in (p.get("/Annots") or [])]
    kinds = [a["/Subtype"] for a in annots]
    assert kinds.count("/Highlight") == 2 and "/Text" in kinds   # the mark that was not found is listed in a note
    for a in annots:
        if a["/Subtype"] == "/Highlight":
            assert len(a["/QuadPoints"]) % 8 == 0


def test_flexiconc_export_reads_back(loaded, tmp_path):
    from enlens_claims import flexiconc_export, profile

    terms.build(loaded)
    profile.keyword_pass(loaded, "sdg")
    out = tmp_path / "fc.sqlite"
    stats = flexiconc_export.export(loaded, out, embeddings=False)
    n_docs = loaded.scalar("SELECT COUNT(*) FROM documents")
    assert stats["documents"] == n_docs and stats["sentences"] > 0
    cx = sqlite3.connect(out)
    assert cx.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == n_docs
    cx.close()
    doc = loaded.query("SELECT doc_id FROM documents ORDER BY doc_id")[0]["doc_id"]
    d = flexiconc_export.read_document(out, doc)
    assert d["full_text"] and d["sentence_analyses"]
    for s in d["sentence_analyses"]:
        assert d["full_text"][s["doc_start"]:s["doc_end"]] == s["sentence_text"]


def test_sdg_pack_is_untouched_by_07(loaded):
    """The SDG / VCA pipeline makes the same tasks as before: 0.7 adds kinds, it does not change the old ones."""
    from enlens_claims import tasks
    from enlens_claims.prompts import VERSIONS

    assert VERSIONS["extract"].startswith("extract-") and VERSIONS["split"].startswith("split-")
    assert {"label", "link", "theme", "resolve"} <= set(tasks.KINDS)
    assert not ({"label", "link", "theme", "resolve"} & {"extract", "split", "verify_set", "verify", "audit"})


def test_new_cli_commands(loaded, tmp_path, capsys):
    from enlens_claims.cli import main

    ws = str(loaded.root)
    run = lambda *a: main(["--ws", ws, *a])  # noqa: E731
    out = tmp_path / "hits.csv"
    assert run("search", "water", "--out", str(out)) == 0
    assert out.exists() and "water" in out.read_text(encoding="utf-8-sig").lower()
    assert run("search", "water stress", "--mode", "phrase", "--collocates") == 0
    assert run("terms", "--rebuild") == 0
    assert run("terms", "--q", "water") == 0
    assert run("concept", "water") in (0, 1)
    assert run("profile", "--keywords-only", "--out", str(tmp_path / "profile.xlsx")) == 0
    assert (tmp_path / "profile.xlsx").exists()
    assert run("profile", "--backend", "baseline", "--limit", "3") == 0
    with pytest.raises(ValueError, match="at least 5"):   # three small documents are too few for themes
        run("themes", "--k", "2", "--mode", "words")
    doc = loaded.query("SELECT doc_id FROM documents WHERE kind='pdf'")[0]["doc_id"]
    assert run("resolve", doc, "--backend", "baseline") == 0
    assert run("annotate", doc, "--layers", "labels", "--out", str(tmp_path / "a.pdf")) == 0
    assert (tmp_path / "a.pdf").read_bytes()[:4] == b"%PDF"
    assert run("export-flexiconc", str(tmp_path / "fc.sqlite"), "--no-embeddings") == 0
    assert run("acceptance", "search", "--queries", "water", "hydrogen") == 0
    printed = capsys.readouterr().out
    assert '"all_equal": true' in printed
    assert run("acceptance", "samples", "--folder", str(tmp_path / "acc")) == 0
    assert (tmp_path / "acc" / "f2_labels.csv").exists()
    assert run("acceptance", "measure", "--folder", str(tmp_path / "acc")) == 0


def test_new_kinds_ask_again_when_a_quote_is_wrong(loaded):
    """label, link, theme and resolve: a first answer whose quote is not in the text is asked again with the
    problems listed, and the second (right) answer is stored."""
    import fake_servers

    from enlens_claims import ingest, profile, references
    from enlens_claims.llm import OllamaBackend

    demo = Path(__file__).resolve().parent.parent / "tools" / "demo_corpus"
    ingest.ingest(loaded, [demo])
    srv, url = fake_servers.start("ollama")
    fake_servers.WRONG_FIRST.update({"label", "link", "theme", "resolve"})
    try:
        be, model = OllamaBackend(base_url=url, seed=42), fake_servers.FAKE_MODEL
        profile.keyword_pass(loaded, "sdg")
        r = profile.run_labels(loaded, "sdg", be, model, limit=2)
        terms.build(loaded)
        ids = [t["term_id"] for t in loaded.query("SELECT term_id FROM terms ORDER BY tf DESC LIMIT 2")]
        terms.judge_links(loaded, [(ids[0], ids[1])], be, model)
        run = themes.run(loaded, k=5, seed=0, mode="words")
        themes.name_with_model(loaded, run, be, model)
        paper = loaded.query("SELECT doc_id FROM documents WHERE kind='pdf'")[0]["doc_id"]
        references.resolve_document(loaded, paper, be, model)
    finally:
        srv.shutdown()
        fake_servers.WRONG_FIRST.clear()
    rows = loaded.query("SELECT t.kind, t.status, MAX(r.attempt) AS n, MIN(r.valid) AS first_valid FROM tasks t "
                        "JOIN results r ON r.task_id=t.task_id WHERE t.kind IN ('label','link','theme','resolve') "
                        "GROUP BY t.task_id")
    kinds = {r["kind"] for r in rows if r["n"] >= 2 and r["first_valid"] == 0}
    assert {"label", "link", "theme"} <= kinds, rows
    assert all(r["status"] == "done" for r in rows)
    assert r is not None
    assert loaded.scalar("SELECT COUNT(*) FROM labels WHERE source='model'") > 0
    assert loaded.scalar("SELECT COUNT(*) FROM concept_links WHERE source='model'") == 1
