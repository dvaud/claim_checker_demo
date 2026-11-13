"""0.15 (roadmap H1, and the no-AI half of the validation report J4.3): `enlens measure`.

- the reading test: six small PDFs made from text we know, the same bytes every time, readable by pypdf, with their
  truth (the body words, the strings that must not be in the body);
- the figures (recall, precision, order, words run together, words broken apart, boilerplate left) on hand-made cases;
- reader 1 reads the one-column document well; reader 2 (when there is one) does at least as well on recall and
  better on boilerplate for the other documents;
- a project: how many recorded quotes still find their place with each reader, the project never changed;
- the command prints a report, `--json` prints JSON, `--report` writes a file.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pypdf
import pytest

from enlens_claims import ingest, measure
from enlens_claims.cli import main as cli_main

TOOLS = Path(__file__).resolve().parent.parent / "tools"


@pytest.fixture(scope="module")
def known(tmp_path_factory):
    return {c.name: c for c in measure.make_known_texts(tmp_path_factory.mktemp("known"))}


# ---- the documents of known text ------------------------------------------------------------
def test_the_known_texts_are_made_the_same_way_every_time(tmp_path, known):
    again = measure.make_known_texts(tmp_path / "again")
    assert [c.name for c in again] == list(known) and len(again) == 6
    for c in again:
        assert c.path.read_bytes() == known[c.name].path.read_bytes()
        assert (c.body, c.boilerplate) == (known[c.name].body, known[c.name].boilerplate)


def test_the_known_texts_are_readable_pdfs_of_two_or_three_pages(known):
    for c in known.values():
        pages = pypdf.PdfReader(str(c.path)).pages
        assert 2 <= len(pages) <= 3, c.name
        assert len(c.body.split()) > 200 and c.boilerplate
        text = " ".join(p.extract_text() for p in pages)
        # every boilerplate string really is on the page (so a reader that leaves it out can be told from one that does not)
        squash = re.sub(r"\W+", "", text).lower()
        for b in c.boilerplate:
            assert re.sub(r"\W+", "", b).lower() in squash, (c.name, b)


def test_words_are_cut_across_lines_and_compounds_broken_at_their_hyphen(known):
    text = pypdf.PdfReader(str(known["a_one_column"].path)).pages
    ends = [ln.split()[-1] for p in text for ln in p.extract_text().split("\n") if ln.endswith("-")]
    assert len(ends) >= 2
    compounds = [c.split("-")[0] + "-" for c in measure._COMPOUNDS]
    broken = [e for k in known for p in pypdf.PdfReader(str(known[k].path)).pages
              for ln in p.extract_text().split("\n") for e in [ln.split()[-1] if ln.strip() else ""] if e in compounds]
    assert broken, "no true compound is broken at its own hyphen in any document"


def test_the_two_column_document_really_has_two_columns(known):
    page = pypdf.PdfReader(str(known["b_two_columns"].path)).pages[0]
    xs: set[float] = set()
    page.extract_text(visitor_text=lambda t, cm, tm, fd, fs: xs.add(round(tm[4])) if t.strip() else None)
    assert {60, 305} <= xs


# ---- the figures ----------------------------------------------------------------------------
def test_perfect_text_scores_one():
    t = "Cities are often described as hostile places. The long-term pattern is clear."
    f = measure.figures(t, t, ["running head"])
    assert (f["recall"], f["precision"], f["order"]) == (1.0, 1.0, 1.0)
    assert f["run_together"] == f["broken"] == 0 and f["boilerplate_left"] == 0 and f["boilerplate_total"] == 1


def test_a_run_together_pair_is_counted():
    truth = "the bees of the city live in the parks"
    f = measure.figures("the bees ofthe city live in the parks", truth)
    assert f["run_together"] == 1 and f["broken"] == 0 and f["recall"] < 1.0


def test_a_broken_word_is_counted_with_a_space_a_hyphen_or_a_lost_compound_hyphen():
    truth = "an example of a long-term study of the temperature"
    assert measure.figures("an exam ple of a long-term study of the temperature", truth)["broken"] == 1
    assert measure.figures("an exam-ple of a long-term study of the temperature", truth)["broken"] == 1
    assert measure.figures("an example of a long- term study of the temperature", truth)["broken"] == 1
    assert measure.figures("an example of a long-term study of the temperature", truth)["broken"] == 0


def test_a_word_that_is_in_the_truth_twice_apart_is_not_a_broken_word():
    truth = "a part of the whole apart from the rest"
    assert measure.figures(truth, truth)["broken"] == 0


def test_boilerplate_found_in_the_body_is_counted_ignoring_spaces_and_case():
    f = measure.figures("Some text. Urban Pollinator  Review - Volume 12 more text.", "Some text. more text.",
                        ["urban pollinator review - volume 12", "a.b@c.example"])
    assert f["boilerplate_left"] == 1 and f["boilerplate_total"] == 2
    assert f["precision"] < 1.0 and f["recall"] == 1.0


def test_wrong_order_lowers_the_order_figure_not_recall():
    f = measure.figures("c d a b", "a b c d")
    assert f["recall"] == 1.0 and f["order"] == 0.5


def test_empty_output_scores_zero_without_dividing_by_zero():
    f = measure.figures("", "some true words here")
    assert f["recall"] == 0.0 and f["precision"] == 0.0 and f["order"] == 0.0


# ---- the readers on the known texts -----------------------------------------------------------
def test_reader_1_keeps_the_words_of_a_one_column_document(known):
    c = known["a_one_column"]
    f = measure.measure_case(c.path, 1, c.body, c.boilerplate)
    assert f["recall"] > 0.9 and f["order"] > 0.9
    assert f["boilerplate_left"] == 1   # reader 1 keeps the running head in the text


def test_reader_1_keeps_front_and_back_matter_and_table_rows_in_the_body(known):
    for name in ("d_front_and_back_matter", "e_table", "f_footnotes"):
        c = known[name]
        f = measure.measure_case(c.path, 1, c.body, c.boilerplate)
        assert f["boilerplate_left"] > 0 and f["recall"] > 0.9, name


def test_every_reader_reads_a_file_the_same_way_twice(known):
    for r in range(1, ingest.READER + 1):
        for c in known.values():
            assert measure.fingerprint(ingest.read_document(c.path, reader=r)) == \
                measure.fingerprint(ingest.read_document(c.path, reader=r))


def test_run_reports_every_reader_and_the_ones_that_are_not_there(tmp_path):
    res = measure.run(readers=[1, 9], work=tmp_path / "w")
    assert res["readers"]["1"]["available"] is True
    assert res["readers"]["9"]["available"] is False and res["readers"]["9"]["why_not"]
    assert set(res["known"]) == {"a_one_column", "b_two_columns", "c_line_numbers", "d_front_and_back_matter",
                                 "e_table", "f_footnotes"}
    assert all(all(d.values()) for d in res["determinism"].values())
    assert res["summary"]["1"]["recall"] > 0.9
    md = measure.to_markdown(res)
    assert "not available" in md and "Reader 1" in md
    json.dumps(res)


def test_the_report_explains_each_figure_in_words(tmp_path):
    md = measure.to_markdown(measure.run(readers=[1, 9], work=tmp_path / "w"))
    assert md.startswith("# Validation report: reading documents (no AI)")
    from enlens_claims import __version__
    assert __version__ in md
    for label in ("Words kept", "Words that belong", "Reading order", "Words run together", "Words broken apart",
                  "Left-over running heads, notes and references"):
        assert f"### {label}" in md
    assert "ofthe" in md   # the explanations give an example in words


@pytest.mark.skipif(ingest.READER < 2, reason="reader 2 is not the current reader yet")
def test_reader_2_reads_at_least_as_well_and_leaves_more_page_furniture_out(known):
    better = 0
    for name in ("b_two_columns", "c_line_numbers", "d_front_and_back_matter", "e_table", "f_footnotes"):
        c = known[name]
        one = measure.measure_case(c.path, 1, c.body, c.boilerplate)
        two = measure.measure_case(c.path, 2, c.body, c.boilerplate)
        assert two["recall"] >= one["recall"] - 1e-9, (name, one, two)
        assert two["boilerplate_left"] <= one["boilerplate_left"], (name, one, two)
        better += two["boilerplate_left"] < one["boilerplate_left"]
    assert better >= 4


# ---- a folder with truth files --------------------------------------------------------------
def test_a_folder_of_pdfs_with_truth_files_gets_the_figures(tmp_path, known):
    folder = tmp_path / "truth"
    folder.mkdir()
    for name in ("a_one_column", "e_table"):
        (folder / f"{name}.pdf").write_bytes(known[name].path.read_bytes())
        (folder / f"{name}.txt").write_text(known[name].body, encoding="utf-8")
    (folder / "no_truth.pdf").write_bytes(known["f_footnotes"].path.read_bytes())   # no .txt: left out
    out = measure.measure_folder(folder, [1])
    assert out["documents"] == ["a_one_column.pdf", "e_table.pdf"]
    rows = out["readers"]["1"]["documents"]
    assert rows["a_one_column.pdf"]["recall"] > 0.9 and "boilerplate_left" not in rows["a_one_column.pdf"]
    assert out["readers"]["1"]["mean"]["recall"] > 0.9
    md = measure.to_markdown(measure.run(readers=[1], work=tmp_path / "w", folder=folder))
    assert "a_one_column.pdf" in md and "Documents with a known text on file" in md


def test_the_arxiv_tool_makes_plain_text_from_latex():
    spec = importlib.util.spec_from_file_location("arxiv_truth", TOOLS / "arxiv_truth.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    tex = (r"\documentclass{article}\title{A Study of Bees\thanks{Funded.}}\begin{document}\maketitle "
           r"\begin{abstract}We count bees \cite{x}.\end{abstract}\section{Introduction}"
           "Bees are \\emph{useful} and $x^2$ small. % a comment\n\n"
           r"\begin{figure}\includegraphics{a}\caption{No.}\end{figure}"
           "See Figure~\\ref{f}. Next paragraph.\n\\begin{thebibliography}{1}\\bibitem{x} Smith.\\end{thebibliography}"
           r"\end{document}")
    text = tool.detex(tex)
    assert "A Study of Bees" in text and "Introduction" in text and "Bees are useful and small." in text
    assert "comment" not in text and "Smith" not in text and "No." not in text and "\\" not in text
    assert len(tool.PAPERS) == 10 and len(set(tool.PAPERS)) == 10


# ---- a project ------------------------------------------------------------------------------
def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(root.rglob("*"))
            if p.is_file()}


def _quote_project(loaded):
    """The standard test project with quotes recorded for its documents: one that is in the text, one that is not."""
    rows = loaded.query("SELECT doc_id, text, path FROM documents WHERE path LIKE '%.pdf'")
    assert rows
    doc = rows[0]
    first = " ".join(doc["text"].split()[20:30])
    with loaded.connect() as cx:
        pid = cx.execute("SELECT passage_id FROM passages WHERE doc_id=? LIMIT 1", (doc["doc_id"],)).fetchone()[0]
        for k, q in enumerate((first, "words that no document contains anywhere at all")):
            cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, quote, source) "
                       "VALUES (?,?,?,?,?,?,?)", (f"l{k}", pid, doc["doc_id"], "sdg", "6.4", q, "model"))
        cx.execute("INSERT INTO evidence(claim_id, field, quote, doc_id) VALUES (?,?,?,?)",
                   ("c1", "claim", first, doc["doc_id"]))
    return doc["doc_id"], first


def test_quotes_that_still_find_their_place_are_counted_and_the_project_is_not_changed(loaded):
    _doc, _first = _quote_project(loaded)
    before = _snapshot(loaded.root)
    out = measure.measure_project(loaded.root, [1])
    assert _snapshot(loaded.root) == before
    r1 = out["readers"]["1"]
    assert out["quotes_recorded"] == 3 and r1["quotes_total"] == 3
    assert r1["placed"] == 2 and r1["not_placed"] == 1 and r1["documents_read"] >= 1
    assert r1["placed_in_body"] <= r1["placed"]
    assert out["documents"] == len(loaded.query("SELECT 1 FROM documents"))


def test_a_changed_original_is_left_out_of_the_quote_count(loaded):
    _quote_project(loaded)
    row = loaded.query("SELECT path FROM documents WHERE path LIKE '%.pdf'")[0]
    p = Path(row["path"]) if Path(row["path"]).is_absolute() else loaded.root / row["path"]
    if not p.exists():
        pytest.skip("the project keeps no copy of the file here")
    p.write_bytes(p.read_bytes() + b"\n% changed\n")
    out = measure.measure_project(loaded.root, [1])
    assert out["with_original"] < out["documents"] and out["skipped"]
    assert out["readers"]["1"]["quotes_total"] == 0


def test_timings_run_on_a_copy_and_skip_what_cannot_run(loaded):
    before = _snapshot(loaded.root)
    out = measure.measure_project(loaded.root, [1], timings=True)
    t = out["timings"]
    assert _snapshot(loaded.root) == before
    assert "ai_tasks" in t or "ai_tasks" in t["skipped"]
    assert "search_index_seconds" in t["steps"] and len(t["steps"]["searches"]) <= 5
    assert "terms_seconds" in t["steps"]
    assert "themes_seconds" in t["steps"] or "themes" in t["skipped"]   # a tiny project may have too few passages
    assert out["readers"]["1"]["seconds_reading"] >= 0
    assert "Timings" in measure.to_markdown({**measure.run(readers=[1]), "project": out})


def test_a_missing_project_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        measure.measure_project(tmp_path / "nowhere", [1])


# ---- the command ----------------------------------------------------------------------------
def test_the_command_prints_the_report(capsys):
    assert cli_main(["measure", "--reader", "1"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Validation report: reading documents (no AI)") and "Reader 1" in out


def test_the_command_prints_json(capsys):
    assert cli_main(["measure", "--json", "--reader", "1"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["readers"]["1"]["available"] and "known" in data


def test_the_command_writes_a_report_file(tmp_path, capsys):
    f = tmp_path / "report.md"
    assert cli_main(["measure", "--reader", "1", "--report", str(f)]) == 0
    assert f.read_text(encoding="utf-8").startswith("# Validation report")
    assert "Report written" in capsys.readouterr().out


def test_the_command_measures_a_project(loaded, capsys):
    _quote_project(loaded)
    assert cli_main(["measure", "--reader", "1", "--ws", str(loaded.root), "--timings"]) == 0
    out = capsys.readouterr().out
    assert "Quotes that still find their place" in out and "Timings" in out
