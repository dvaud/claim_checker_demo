"""Roadmap K1 "In and out" (with G5): a REFI-QDA codebook (`.qdc`) or the codebook of a `.qdpx` project brought in
from NVivo, ATLAS.ti or MAXQDA (qdc_import.py). No AI. ENLENS's own export comes back as it went; the shapes the
three programs write (deep trees, headings that cannot be coded, codes without a description, with and without the
namespace) map as the module says; hostile files are refused before they are parsed."""
from __future__ import annotations

import base64
import io
import json
import zipfile

import pytest

from enlens_claims import codebooks, frameworks, qdc_import, qdpx

CB_NS = 'xmlns="urn:QDA-XML:codebook:1.0"'


def _qdc(codes: str, ns: str = CB_NS, origin: str = "NVivo 14") -> bytes:
    return f'<?xml version="1.0" encoding="utf-8"?>\n<CodeBook {ns} origin="{origin}"><Codes>{codes}</Codes></CodeBook>'.encode()


def _make(ws, data: bytes, name: str = "imp", title: str = "") -> dict:
    return codebooks.create(ws, name, title, "project", "qdc",
                            {"file": base64.b64encode(data).decode(), "filename": "x.qdc"})


def _codes(got: dict) -> dict:
    return {c["code"]: c for c in got["codes"]}


SOURCE_CSV = (
    "code,description,group,group_name,when_to_use,when_not_to_use,keywords,examples\n"
    "commute,Fewer trips to the office,transport,Getting to work,A text says trips fell,Only cars counted,"
    "\"commuting; Paris, France; trips\",\"Workers commute less often\nThe office stood empty\"\n"
    "6.4,\"By 2030, substantially increase water-use efficiency across all sectors and ensure sustainable withdrawals\""
    ",water,Water,,,,\n"
    "wellbeing,How people feel at home,,,,,,\n"
    "loneliness,Feeling cut off from colleagues,people,people,,,,\n"
)


def test_an_enlens_export_comes_back_as_it_went(ws):
    codebooks.create(ws, "orig", "Remote work", "project", "csv", {"csv": SOURCE_CSV})
    body = qdpx.codebook_xml(ws, "orig")
    got = _make(ws, body, "back")
    before = frameworks.get("orig", ws).codes
    after = frameworks.get("back", ws).codes
    assert set(before) == set(after)
    for k, c in before.items():
        d = after[k]
        assert (d.description, d.group, d.group_name, d.include, d.exclude, d.keywords, d.examples) == \
            (c.description, c.group, c.group_name, c.include, c.exclude, c.keywords, c.examples), k
    assert after["commute"].keywords == ("commuting", "Paris, France", "trips")   # a comma inside a keyword survives
    assert "6.4" in after                                                          # the number, not "6.4 By 2030 …"
    assert got["imported"]["notes"][0] == "4 codes in 3 groups brought in."
    assert len(got["imported"]["notes"]) == 1


def test_an_enlens_project_file_gives_its_one_codebook_without_the_hypotheses(ws, tmp_path):
    codebooks.create(ws, "orig", "Remote work", "project", "csv", {"csv": SOURCE_CSV})
    out = tmp_path / "p.qdpx"
    qdpx.export_project(ws, out, framework="orig")
    got = codebooks.create(ws, "fromproj", "", "project", "qdc", prepared=qdc_import.from_path(out))
    assert got["title"] == "Remote work"
    assert set(_codes(got)) == {"commute", "6.4", "wellbeing", "loneliness"}
    assert {g["group"]: g["group_name"] for g in got["groups"] if g["group"]} == \
        {"transport": "Getting to work", "water": "Water", "people": "people"}


NVIVO = _qdc("""
<Code guid="a1" name="Emotions" isCodable="true" color="#FF0000">
  <Code guid="a2" name="Positive" isCodable="true">
    <Code guid="a3" name="Joy" isCodable="true"><Description>Moments of delight at work</Description></Code>
    <Code guid="a4" name="Relief" isCodable="true"/>
  </Code>
  <Code guid="a5" name="Anger" isCodable="true"><Description>Open frustration</Description></Code>
</Code>
<Code guid="b1" name="Workplace" isCodable="true"><Description>Where the work happens</Description>
  <Code guid="b2" name="Office" isCodable="true"><Description>The firm's building</Description></Code>
  <Code guid="b3" name="Joy" isCodable="true"><Description>Pleasure in the place itself</Description></Code>
</Code>
<Code guid="c1" name="Uncategorised idea" isCodable="true"/>
""")


def test_an_nvivo_tree_three_deep_folds_into_its_top_group(ws):
    got = _make(ws, NVIVO, "nv", "NVivo codes")
    c = _codes(got)
    assert [g["group"] for g in got["groups"] if g["group"]] == ["Emotions", "Workplace"]
    # three levels down: a code of the top group, its place in the tree at the end of its definition
    assert c["Joy"]["group"] == "Emotions"
    assert c["Joy"]["description"] == "Moments of delight at work (In the tree: Emotions › Positive › Joy.)"
    assert c["Relief"]["description"] == "Emotions › Positive › Relief"   # no description: its place stands in
    assert c["Anger"]["description"] == "Open frustration"
    # a heading without a description is no code; one with a description is a code too
    assert "Emotions" not in c and "Positive" not in c
    assert c["Workplace"]["group"] == "Workplace" and c["Workplace"]["description"] == "Where the work happens"
    assert c["Joy (2)"]["group"] == "Workplace"                                  # the same name in another branch
    assert c["Uncategorised idea"]["group"] == "" and c["Uncategorised idea"]["description"] == "Uncategorised idea"
    s = got["imported"]
    assert (s["codes"], s["groups"], s["folded"], s["parents_as_codes"], s["headings"], s["no_description"]) == \
        (7, 2, 2, 1, 1, 2)
    assert s["renamed"] == [{"from": "Joy", "to": "Joy (2)"}]
    assert any("Joy (2)" in n for n in s["notes"])


ATLAS = _qdc("""
<Code guid="x1" name="Barriers" isCodable="false"><Description>&lt;p&gt;Things in the way&lt;/p&gt;</Description>
  <Code guid="x2" name="Cost" isCodable="true"><Description>&lt;p&gt;Money &lt;b&gt;spent&lt;/b&gt;&lt;/p&gt;&lt;p&gt;Second part&lt;/p&gt;</Description></Code>
  <Code guid="x3" name="Unused heading" isCodable="false"/>
</Code>
<Code guid="x4" name="A very long code name that a program allows but ENLENS cuts" isCodable="true"/>
""", ns="", origin="ATLAS.ti 24")


def test_atlas_ti_without_the_namespace_html_descriptions_and_codes_that_cannot_be_coded(ws):
    got = _make(ws, ATLAS, "at")
    c = _codes(got)
    assert c["Cost"]["description"] == "Money spent Second part" and c["Cost"]["group"] == "Barriers"
    long = next(k for k in c if k.startswith("A very long"))
    assert len(long) <= 40 and long.endswith("…")
    assert c[long]["description"] == "A very long code name that a program allows but ENLENS cuts"
    s = got["imported"]
    assert (s["not_codable"], s["group_descriptions"], s["cut"]) == (1, 1, 1)
    assert "Unused heading" not in c


MAXQDA = _qdc("""
<Code guid="m1" name="Work" isCodable="true">
  <Code guid="m2" name="Hours" isCodable="true"><Description>Time spent working</Description></Code>
  <Code guid="m3" name="hours" isCodable="true"><Description>Lower-case twin</Description></Code>
</Code>
""", origin="MAXQDA 2024").replace(b"<Codes>", b"<Codes>").replace(b"</CodeBook>", b'<Sets><Set guid="s1" name="Mine"/></Sets></CodeBook>')


def test_maxqda_names_that_differ_only_by_case_and_sets_noted(ws):
    got = _make(ws, MAXQDA, "mx")
    c = _codes(got)
    assert set(c) == {"Hours", "hours (2)"}
    assert got["imported"]["sets"] == 1 and any("sets" in n or "set left out" in n for n in got["imported"]["notes"])
    # the codebook is an ordinary editor codebook: a CSV that opens in a spreadsheet, with its side file
    f = ws.root / "frameworks"
    assert (f / "mx.csv").read_text(encoding="utf-8").startswith("code,description,group,group_name")
    assert json.loads((f / "mx.json").read_text(encoding="utf-8"))["editor"] is True
    log = ws.query("SELECT text FROM research_log WHERE kind='codebook-added' ORDER BY at DESC LIMIT 1")
    assert "REFI-QDA" in log[0]["text"]


@pytest.mark.parametrize("data, says", [
    (_qdc(""), "no codes"),
    (_qdc('<Code guid="h" name="Heading" isCodable="false"/>'), "no codes"),
    (b"<Project><Sources/></Project>", "no codebook"),
    (b"<CodeBook><Codes><Code name='x'>", "not well-formed"),
    (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><CodeBook><Codes><Code name="&lol;"/></Codes></CodeBook>',
     "DOCTYPE"),
    (b'<CodeBook><Codes><!ENTITY x SYSTEM "file:///etc/passwd"></Codes></CodeBook>', "ENTITY"),
    ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x><CodeBook/>'.encode("utf-16"), "DOCTYPE"),
])
def test_files_that_are_refused(ws, data, says):
    with pytest.raises(ValueError, match=says):
        _make(ws, data)
    assert not (ws.root / "frameworks" / "imp.csv").exists()


def test_a_utf16_file_with_accents_reads(ws):
    body = '<?xml version="1.0" encoding="UTF-16"?><CodeBook xmlns="urn:QDA-XML:codebook:1.0"><Codes>' \
           '<Code guid="u" name="Élmény" isCodable="true"><Description>Ő és ű</Description></Code></Codes></CodeBook>'
    got = _make(ws, body.encode("utf-16"))
    assert _codes(got)["Élmény"]["description"] == "Ő és ű"


def test_size_limits_and_a_zip_bomb(ws, monkeypatch, tmp_path):
    monkeypatch.setattr(qdc_import, "MAX_QDC", 1000)
    with pytest.raises(ValueError, match="larger than"):
        _make(ws, _qdc("<Code name='x' isCodable='true'/>" * 100))
    # a .qdpx whose project.qde unpacks past the limit stops there
    monkeypatch.setattr(qdc_import, "MAX_QDE", 10_000)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.qde", b"<Project>" + b" " * 200_000 + b"</Project>")
    with pytest.raises(ValueError, match="larger than"):
        qdc_import.read_tree(buf.getvalue())
    monkeypatch.setattr(qdc_import, "MAX_MEMBERS", 3)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(4):
            zf.writestr(f"sources/{i}.txt", "x")
    with pytest.raises(ValueError, match="more than 3"):
        qdc_import.read_tree(buf.getvalue())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("other.txt", "x")
    with pytest.raises(ValueError, match="no project.qde"):
        qdc_import.read_tree(buf.getvalue())
    with pytest.raises(ValueError, match="not a zip"):
        qdc_import.read_tree(b"PK\x03\x04 broken")


def test_a_qdpx_from_another_program_keeps_only_its_codebook(ws):
    qde = ('<?xml version="1.0" encoding="utf-8"?><Project xmlns="urn:QDA-XML:project:1.0" name="Interviews" '
           'origin="NVivo 14"><CodeBook><Codes><Code guid="p1" name="Trust" isCodable="true">'
           '<Description>Faith in the employer</Description></Code></Codes></CodeBook>'
           '<Sources><TextSource guid="s1" name="Int 1"><PlainTextSelection guid="q" startPosition="0" endPosition="3">'
           '<Coding guid="cc"><CodeRef targetGUID="p1"/></Coding></PlainTextSelection></TextSource></Sources></Project>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.qde", qde)
        zf.writestr("sources/s1.txt", "Int one")
    got = _make(ws, buf.getvalue(), "proj")
    assert got["title"] == "Interviews" and list(_codes(got)) == ["Trust"]


def test_through_the_app(home_api):
    api = home_api
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    st, res = api("POST", "/api/projects/Demo/codebooks",
                  {"name": "nv", "title": "From NVivo", "start": "qdc",
                   "source": {"file": base64.b64encode(NVIVO).decode(), "filename": "nvivo.qdc"}})
    assert st == 200, res
    assert res["codebook"]["name"] == "nv" and res["codebook"]["imported"]["codes"] == 7
    st, res = api("POST", "/api/projects/Demo/codebooks",
                  {"name": "bad", "title": "Bad", "start": "qdc", "source": {"file": base64.b64encode(b"<x/>").decode()}})
    assert st == 400 and "no codebook" in json.dumps(res)
    # a path is never read from the app's API
    st, res = api("POST", "/api/projects/Demo/codebooks",
                  {"name": "p", "title": "P", "start": "qdc", "source": {"path": "/etc/passwd"}})
    assert st == 400


@pytest.fixture
def home_api(tmp_path, monkeypatch):
    import threading

    from test_app import Api

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
    srv.shutdown()
    srv.server_close()


def test_the_command_line(ws, tmp_path, capsys):
    from enlens_claims import cli

    f = tmp_path / "My NVivo codes.qdc"
    f.write_bytes(NVIVO)
    assert cli.main(["--ws", str(ws.root), "import-qdc", str(f)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["codebook"] == "my_nvivo_codes" and out["codes"] == 7 and out["groups"] == 2
    assert cli.main(["--ws", str(ws.root), "import-qdc", str(f), "again", "--title", "Again"]) == 0
    assert frameworks.get("again", ws).title == "Again"
    assert cli.main(["--ws", str(ws.root), "import-qdc", str(f), "again"]) == 2       # the name is taken
    assert "exists already" in capsys.readouterr().err
    assert cli.main(["--ws", str(ws.root), "import-qdc", str(tmp_path / "none.qdc")]) == 2
