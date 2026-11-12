"""0.17.2: a codebook's CSV is formula-safe like every other CSV ENLENS writes, and still imports back as it was.

- cells that start with "=", "@", "+x", "-x", "-5", "- item" or an apostrophe export safely (a spreadsheet would run
  the first four as formulas) and read back identical;
- `review.csv_uncell` is the exact inverse of `review.csv_cell` (also for text that already starts with apostrophes);
- a file written before (no apostrophes) reads the same, and the download of an old file is protected too.
"""
from __future__ import annotations

import csv
import io
import json

import pytest

from enlens_claims import codebooks, frameworks, review
from enlens_claims.review import csv_cell, csv_uncell

TRICKY = ["=1+1", "@SUM(A1)", "+x", "-x", "-5", "- item", "'quoted", "'=1", "''=1", "'-x", "+1,200.5", "-3%", "-",
          "plain", "\tTabbed", "=HYPERLINK(\"http://x\",\"y\")"]


@pytest.mark.parametrize("text", TRICKY + ["", "a'b", "'", "''", "'plain", " =not first"])
def test_csv_uncell_undoes_csv_cell_exactly(text):
    assert csv_uncell(csv_cell(text)) == text


def test_csv_uncell_leaves_other_cells_as_they_are():
    for text in ("'quoted", "=1", "-5", "plain", "", "'", "a'=b"):
        assert csv_uncell(text) == text
    assert csv_uncell("'=1") == "=1"
    assert csv_uncell("'quoted") == "'quoted"
    assert csv_uncell(5) == 5 and csv_uncell(None) is None


def _state(ws, name="tricky"):
    cb = codebooks.create(ws, name, "Tricky", "project", "fresh")
    st = json.loads(json.dumps(cb))
    st["groups"] = [{"group": "=g", "group_name": "@Group"}]
    st["codes"] = [dict(code=f"{t}", description=f"{t} desc", group="=g", include=t, exclude=f"- {t}",
                        keywords=[t, "other"], examples=[{"quote": t}, {"quote": "second"}])
                   for t in ("=A", "@B", "+x", "-y", "-5", "- item", "'quoted")]
    st["codes"][0]["description"] = "=cmd|' /C calc'!A0"
    st["codes"][1]["description"] = "@desc"
    st["codes"][2]["description"] = "+x"
    st["codes"][3]["description"] = "-y"
    st["codes"][4]["description"] = "-5"
    st["codes"][5]["description"] = "- item"
    st["codes"][6]["description"] = "'quoted"
    codebooks.save(ws, name, st)
    return codebooks.load(ws, name)


def test_a_codebook_exports_safely_and_imports_back_identical(ws, tmp_path):
    before = _state(ws)
    _, body = codebooks.csv_of(ws, "tricky")
    text = body.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    for row in rows[1:]:
        for cell in row:
            # no cell a spreadsheet would run: nothing starts with = or @, and + or - only as a number or "- "
            assert cell == "" or cell[0] not in "=@\t\r"
            if cell[:1] in "+-":
                assert cell == "-" or cell[1:2] == " " or review._PLAIN_NUMBER.fullmatch(cell)
    assert any(c.startswith("'=A") for c in rows[1])  # the apostrophe is really there
    # the very file the download gives, saved as it is and read as a framework
    got = frameworks.parse_csv(text, allow_empty=True, extra=True)
    assert [c for c in got] == [c["code"] for c in before["codes"]]
    for c in before["codes"]:
        g = got[c["code"]]
        assert g.description == " ".join(c["description"].split())
        assert (g.group, g.group_name) == ("=g", "@Group")
        assert g.include == " ".join(c["include"].split()) and g.exclude == " ".join(c["exclude"].split())
        assert list(g.keywords) == c["keywords"]
        assert list(g.examples) == [e["quote"] for e in c["examples"]]
    # and the codebook the editor reads from its own file is the same as before
    after = codebooks.load(ws, "tricky")
    assert [(c["code"], c["description"], c["include"], c["exclude"], c["keywords"], c["examples"]) for c in after["codes"]] == \
           [(c["code"], c["description"], c["include"], c["exclude"], c["keywords"], c["examples"]) for c in before["codes"]]


def test_the_file_on_disk_is_protected_too(ws):
    _state(ws)
    where, folder = codebooks.locate(ws, "tricky")
    raw = (folder / "tricky.csv").read_text(encoding="utf-8")
    assert "\n'=A," in raw
    assert "\n=A," not in raw


def test_an_old_file_without_apostrophes_still_imports_the_same():
    old = ("code,description,group,group_name\n"
           "Alpha,Plain words,g,Group\n"
           "-5,- item,g,Group\n"
           "Quoted,'quoted text,g,Group\n")
    got = frameworks.parse_csv(old)
    assert list(got) == ["Alpha", "-5", "Quoted"]
    assert got["-5"].description == "- item"
    assert got["Quoted"].description == "'quoted text"


def test_the_download_of_an_old_or_imported_file_is_protected_without_changing_its_columns(ws):
    old = ("code;description;group;extra\n"
           "Alpha;=1+1;g;@x\n"
           "Beta;'=already;g;'-y\n"
           "Gamma;-5;g;- item\n")
    frameworks.save(ws, "imported", old)
    _, body = codebooks.csv_of(ws, "imported")
    assert not body.startswith(b"\xef\xbb\xbf")   # as before: a project's own file is sent without a byte-order mark
    rows = list(csv.reader(io.StringIO(body.decode("utf-8")), delimiter=";"))
    assert rows[0] == ["code", "description", "group", "extra"]
    assert rows[1] == ["Alpha", "'=1+1", "g", "'@x"]
    assert rows[2] == ["Beta", "'=already", "g", "'-y"]  # protected already: not protected twice
    assert rows[3] == ["Gamma", "-5", "g", "- item"]
    # a second download of the same download changes nothing
    again = codebooks._protected_csv(body.decode("utf-8-sig"))
    assert again == body.decode("utf-8-sig").lstrip("﻿")


def test_a_bundled_codebook_still_downloads(ws):
    name, body = codebooks.csv_of(ws, "sdg")
    assert name == "sdg.csv" and body.startswith(b"\xef\xbb\xbfcode,")
