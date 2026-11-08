"""0.15.1: of a work's files ENLENS adds the real document (PDF, then Word, then text) and a web page only when
nothing else can be read; and a long title, whole on a document's title page, is proposed for a work that has no
author and no year. The tests never touch a real Zotero."""
from __future__ import annotations

from pathlib import Path

LONG = ("Developing and evaluating serious games and input techniques for people with moderate to severe dementia "
        "using heuristic evaluation")


def _files(folder: Path, *names: str) -> list[dict]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for n in names:
        (folder / n).write_bytes(b"x " + n.encode())
        out.append({"path": str(folder / n), "name": n})
    return out


def _save(ws, works: list[dict]) -> None:
    from enlens_claims import bibliography as b
    b.save(ws, works, {"kind": "file", "name": "x.bib", "format": "bibtex"})


def _work(key, title, files=(), creators=(), year=None):
    from enlens_claims import bibliography as b
    return b._work(key, "webpage", title, list(creators), year, None, None, None, None, None, list(files))


def _names(ws, keys=None) -> list[str]:
    from enlens_claims import bibliography as b
    return [p.name for p in b.files_to_add(ws, keys)]


def test_the_pdf_is_chosen_over_an_earlier_web_page(ws, tmp_path):
    _save(ws, [_work("w1", "A page", _files(tmp_path / "s", "snapshot.html", "thesis.pdf"))])
    assert _names(ws) == ["thesis.pdf"]


def test_a_web_page_is_chosen_when_it_is_the_only_readable_file(ws, tmp_path):
    _save(ws, [_work("w1", "A page", _files(tmp_path / "s", "image.png", "snapshot.html"))])
    assert _names(ws) == ["snapshot.html"]


def test_word_beats_text_and_the_order_of_zotero_breaks_ties(ws, tmp_path):
    _save(ws, [_work("w1", "One", _files(tmp_path / "a", "notes.txt", "paper.docx", "page.htm")),
               _work("w2", "Two", _files(tmp_path / "b", "first.pdf", "second.pdf")),
               _work("w3", "Three", _files(tmp_path / "c", "a.md", "b.txt"))])
    assert _names(ws) == ["paper.docx", "first.pdf", "a.md"]


def _doc_folder(tmp_path: Path, title_line: str, name="thesis.md") -> Path:
    d = tmp_path / "docs"
    d.mkdir(exist_ok=True)
    (d / name).write_text(f"{title_line}\n\n" + "The study describes games for people living with dementia. " * 12)
    return d


def _links(ws) -> list[tuple]:
    return [(r["item_key"], r["status"]) for r in ws.query("SELECT item_key, status FROM bib_links")]


def test_a_long_exact_title_alone_is_proposed_never_linked(ws, tmp_path):
    from enlens_claims import ingest
    ingest.ingest(ws, [_doc_folder(tmp_path, f"{LONG}. A thesis")])
    _save(ws, [_work("w1", LONG)])
    assert _links(ws) == [("w1", "probable")]
    ev = ws.query("SELECT evidence_json, score FROM bib_links")[0]
    assert abs(ev["score"] - 0.5) < 1e-9 and '"author": null' in ev["evidence_json"] and '"year": null' in ev["evidence_json"]


def test_a_short_title_or_a_partial_title_alone_is_not_proposed(ws, tmp_path):
    from enlens_claims import ingest
    ingest.ingest(ws, [_doc_folder(tmp_path, f"{LONG}. A thesis")])
    _save(ws, [_work("short", "Serious games dementia"),
               _work("five", "Serious games for people with dementia"),   # 5 significant words
               _work("partial", LONG + " in care homes across several European countries")])
    assert _links(ws) == []


def test_a_title_found_only_in_words_is_not_proposed(ws, tmp_path):
    from enlens_claims import ingest
    ingest.ingest(ws, [_doc_folder(tmp_path, "Heuristic evaluation, serious games and input techniques: dementia, "
                                             "people with moderate to severe symptoms, developing and evaluating")])
    _save(ws, [_work("w1", LONG)])
    assert _links(ws) == []


def test_a_pair_with_an_author_outranks_a_title_alone(ws, tmp_path):
    from enlens_claims import ingest
    d = tmp_path / "docs"
    d.mkdir()
    (d / "one.md").write_text(f"{LONG}\nJ. Moreau\n\n" + "Games for dementia. " * 20)
    ingest.ingest(ws, [d])
    _save(ws, [_work("bare", LONG), _work("author", LONG, creators=[{"last": "Moreau", "first": "J."}])])
    assert _links(ws) == [("author", "probable")]


def test_the_whole_case_the_text_document_is_proposed_and_the_snapshot_is_not_added(ws, tmp_path):
    from enlens_claims import bibliography as b
    from enlens_claims import ingest
    ingest.ingest(ws, [_doc_folder(tmp_path, f"{LONG}. Master's thesis, University of Somewhere")])
    _save(ws, [_work("w1", LONG, _files(tmp_path / "z", "snapshot.html", "thesis.pdf"))])
    assert _links(ws) == [("w1", "probable")]
    assert b.files_to_add(ws) == []
    assert [r["doc"]["file"] for r in b.view(ws)["confirm"]] == ["thesis.md"]
