"""Roadmap K1 "In and out" (with G5): a REFI-QDA codebook (`.qdc`) or the codebook of a `.qdpx` project brought in
from NVivo, ATLAS.ti or MAXQDA (qdc_import.py). No AI. ENLENS's own export comes back (all a .qdc carries); the shapes the
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
""", origin="MAXQDA 2024").replace(b"</CodeBook>", b'<Sets><Set guid="s1" name="Mine"><MemberCode targetGUID="m2"/></Set>'
                                    b'<Set guid="s2" name="Documents"><MemberSource targetGUID="d1"/></Set></Sets></CodeBook>')


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


_LAUGHS = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "lollollollol"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">'
           '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;">]><CodeBook><Codes><Code name="x" isCodable="true">'
           '<Description>&c;</Description></Code></Codes></CodeBook>')


@pytest.mark.parametrize("data, says", [
    (_qdc(""), "no codes"),
    (_qdc('<Code guid="h" name="Heading" isCodable="false"/>'), "no codes"),
    (b"<Project><Sources/></Project>", "no codebook"),
    (b"<CodeBook><Codes><Code name='x'>", "not well-formed"),
    (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><CodeBook><Codes><Code name="&lol;"/></Codes></CodeBook>',
     "DOCTYPE"),
    (b'<CodeBook><Codes><!ENTITY x SYSTEM "file:///etc/passwd"></Codes></CodeBook>', "ENTITY"),
    ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x><CodeBook/>'.encode("utf-16"), "DOCTYPE"),
    # without a byte order mark (QDC-1): the zero bytes say how it is encoded, and the guard still sees the DOCTYPE
    *[(_LAUGHS.encode(enc), "DOCTYPE") for enc in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")],
    (b"<CodeBook><Codes><Code name='a\x00b'/></Codes></CodeBook>", "zero bytes"),
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
    # a project file ENLENS wrote with several codebooks: the answer names them, and one is chosen (QDC-4)
    two = base64.b64encode(_enlens_project("Remote work", "SDG targets")).decode()
    st, res = api("POST", "/api/projects/Demo/codebooks", {"name": "two", "title": "Two", "start": "qdc",
                                                           "source": {"file": two}})
    assert st == 400 and res["codebooks"] == ["Remote work", "SDG targets"]
    st, res = api("POST", "/api/projects/Demo/codebooks", {"name": "two", "title": "Two", "start": "qdc",
                                                           "source": {"file": two, "codebook": "Remote work"}})
    assert st == 200 and [c["code"] for c in res["codebook"]["codes"]] == ["Remote work code"]


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


# ---- review fixes ---------------------------------------------------------------------------------------------------
def _zip(members: dict[str, bytes], method=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for n, b in members.items():
            z.writestr(n, b)
    return buf.getvalue()


def test_a_project_outside_the_codebook_is_not_kept_element_by_element():
    """Elements of a project outside its codebook leave the tree as they end (a cleared element would stay attached:
    600,000 of them took about 80 MB at their peak, now about 6 MB)."""
    import tracemalloc
    many = "<a/>" * 600_000
    raw = (f'<Project xmlns="urn:QDA-XML:project:1.0" name="P"><Sources>{many}</Sources>'
           f'<CodeBook><Codes><Code name="Joy" isCodable="true"/></Codes></CodeBook><Notes>{many}</Notes></Project>').encode()
    tracemalloc.start()
    try:
        got = qdc_import._read(raw)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert [r.name for r in got.roots] == ["Joy"] and got.title == "P"
    assert peak < 30 * 1024 ** 2, peak


def test_a_damaged_or_locked_project_file_is_refused_plainly(ws):
    good = _zip({"project.qde": b'<Project><CodeBook><Codes><Code name="A"/></Codes></CodeBook></Project>'})
    i = good.index(b"PK\x01\x02")          # the central directory: its CRC of the member made wrong
    cd = bytearray(good)
    crc_at = i + 16
    cd[crc_at:crc_at + 4] = b"\x00\x00\x00\x00"
    lh = bytearray(cd)
    lh[14:18] = b"\x00\x00\x00\x00"         # and the local header's, so the reader checks against 0
    with pytest.raises(ValueError, match="damaged or locked"):
        qdc_import.read_tree(bytes(lh))
    with pytest.raises(ValueError, match="damaged or locked"):
        _make(ws, bytes(lh))


def test_a_project_zipped_again_inside_a_folder_reads():
    data = _zip({"MyProj/project.qde": b'<Project xmlns="urn:QDA-XML:project:1.0"><CodeBook><Codes>'
                                       b'<Code name="Joy"/></Codes></CodeBook></Project>', "MyProj/Sources/a.txt": b"x"})
    roots, info = qdc_import.read_tree(data)
    assert [r.name for r in roots] == ["Joy"] and info["zip"]


@pytest.mark.parametrize("origin, want", [
    ("ENLENS 0.18.8", ["Paris, France"]),
    ("ENLENS 0.19.0", ["Paris, France"]),
    ("ENLENS 0.18.7", ["Paris", "France"]),     # 0.18.7 joined keywords with ", "
    ("NVivo 14", ["Paris", "France"]),
])
def test_one_keyword_with_a_comma(origin, want):
    data = _qdc('<Code name="place" isCodable="true"><Description>Where it is\n\nKeywords: Paris, France</Description></Code>',
                origin=origin)
    st = qdc_import.to_state(*qdc_import.read_tree(data))
    assert st["codes"][0]["keywords"] == want


def test_a_long_definition_is_shortened_keeping_its_place_in_the_tree():
    long = "word " * 1200
    data = _qdc(f'<Code name="Top"><Code name="Mid"><Code name="Leaf" isCodable="true"><Description>{long}</Description>'
                '</Code></Code></Code>')
    st = qdc_import.to_state(*qdc_import.read_tree(data))
    d = st["codes"][0]["description"]
    assert len(d) <= qdc_import.DEF_MAX and d.endswith("(In the tree: Top › Mid › Leaf.)")
    assert any("shortened" in n for n in st["summary"]["notes"])


def test_enlens_readings_only_for_enlens_files():
    data = _qdc('<Code name="2 Methods" isCodable="true"><Description>Methods</Description></Code>'
                '<Code name="Hypotheses (ENLENS)" isCodable="true"><Description>Our own</Description></Code>')
    st = qdc_import.to_state(*qdc_import.read_tree(data))
    assert sorted(c["code"] for c in st["codes"]) == ["2 Methods", "Hypotheses (ENLENS)"]


# ---- audit fixes (2026-11-14) ---------------------------------------------------------------------------------------
def test_the_parser_itself_refuses_a_doctype(monkeypatch):
    """QDC-1: the DOCTYPE is refused by the parser, not only by the first look at the text, so a file whose encoding
    that look gets wrong is still refused before any entity is declared."""
    import re
    monkeypatch.setattr(qdc_import, "_DANGER", re.compile(r"(?!)"))   # the first look sees nothing
    for data in (_LAUGHS.encode(), _LAUGHS.encode("utf-16-le"), _LAUGHS.encode("utf-16")):
        with pytest.raises(ValueError, match="DOCTYPE"):
            qdc_import.read_tree(data)


def test_utf16_without_a_byte_order_mark_reads():
    body = '<?xml version="1.0" encoding="UTF-16"?><CodeBook><Codes><Code name="Élmény"/></Codes></CodeBook>'
    for enc in ("utf-16-le", "utf-16-be"):
        roots, _ = qdc_import.read_tree(body.encode(enc))
        assert [r.name for r in roots] == ["Élmény"]


def _quick(fn, limit=2.0):
    import time
    t = time.perf_counter()
    out = fn()
    assert time.perf_counter() - t < limit
    return out


def test_too_many_codes_are_refused_as_they_are_read():
    """QDC-2: the reader stops past 10,000 codes before the tree is built; 5,001 named codes are refused after."""
    with pytest.raises(ValueError, match="more than 10,000 codes"):
        _quick(lambda: qdc_import.read_tree(_qdc('<Code name="a"/>' * 20_000)))
    with pytest.raises(ValueError, match="at most 5,000 codes"):
        qdc_import.to_state(*qdc_import.read_tree(_qdc("".join(f'<Code name="c{i}"/>' for i in range(5001)))))


def test_hostile_names_and_descriptions_cost_time_in_step_with_their_length():
    """QDC-2: many codes of one name, and descriptions or names that made the patterns quadratic."""
    st = _quick(lambda: qdc_import.to_state(*qdc_import.read_tree(_qdc('<Code name="a"/>' * 5000))))
    assert len({c["code"] for c in st["codes"]}) == 5000 and st["codes"][-1]["code"] == "a (5000)"
    many_groups = '<Code name="g"><Code name="x"/></Code>' * 2000
    st = _quick(lambda: qdc_import.to_state(*qdc_import.read_tree(_qdc(many_groups))))
    assert len({g["group"].lower() for g in st["groups"]}) == 2000
    for desc in (("&lt;" + " " * 4000) * 20, "&lt;p&gt;" + "&lt;" * 40_000, "&lt;b " + "x" * 100_000 + "&gt;" * 3):
        _quick(lambda: qdc_import.to_state(*qdc_import.read_tree(_qdc(f'<Code name="a"><Description>{desc}</Description></Code>'))))
    name = " ".join(["w"] * 4000)
    _quick(lambda: qdc_import.to_state(*qdc_import.read_tree(_qdc(
        f'<Code name="{name}" isCodable="false"><Description>zzz</Description><Code name="c"/></Code>', origin="ENLENS 0.18.8"))))


def test_a_definition_that_opens_with_a_label_stays_the_definition(ws):
    """QDC-3: the first paragraph is always the definition."""
    csv = ("code,description,group,group_name,when_to_use,when_not_to_use,keywords,examples\n"
           "eg,Example: the classic case of a definition that opens with a label,,,,,,\n"
           "kw,Keywords: are the words a code is matched by,g1,g1,,,a; b,\n")
    codebooks.create(ws, "lab", "Labels", "project", "csv", {"csv": csv})
    got = _make(ws, qdpx.codebook_xml(ws, "lab"), "lab_back")
    c = _codes(got)
    assert c["eg"]["description"] == "Example: the classic case of a definition that opens with a label"
    assert c["kw"]["description"] == "Keywords: are the words a code is matched by" and c["kw"]["keywords"] == ["a", "b"]
    assert not c["eg"]["examples"] and got["imported"]["no_description"] == 0
    st = qdc_import.to_state(*qdc_import.read_tree(_qdc(
        '<Code name="Trust"><Description>Example: when a participant says they rely on the manager</Description></Code>')))
    assert st["codes"][0]["description"].startswith("Example: when") and not st["codes"][0]["examples"]


def _enlens_project(*books: str) -> bytes:
    codes = "".join(f'<Code name="{b} (codebook)" isCodable="false"><Code name="{b} code" isCodable="true">'
                    f'<Description>A code of {b}</Description></Code></Code>' for b in books)
    return _zip({"project.qde": (f'<Project xmlns="urn:QDA-XML:project:1.0" name="ws" origin="ENLENS 0.18.8"><CodeBook>'
                                 f'<Codes>{codes}<Code name="Hypotheses (ENLENS)" isCodable="false"/></Codes></CodeBook>'
                                 f'</Project>').encode()})


def test_a_project_with_several_codebooks_asks_which(ws, tmp_path, capsys):
    """QDC-4: a .qdpx ENLENS wrote with every codebook in use: one is chosen, none merged."""
    data = _enlens_project("Remote work", "SDG targets")
    with pytest.raises(qdc_import.SeveralCodebooks, match="“Remote work”, “SDG targets”") as e:
        qdc_import.from_source({"file": base64.b64encode(data).decode()})
    assert e.value.extra == {"codebooks": ["Remote work", "SDG targets"]}
    st = qdc_import.from_source({"file": base64.b64encode(data).decode(), "codebook": "SDG targets"})
    assert st["title"] == "SDG targets" and [c["code"] for c in st["codes"]] == ["SDG targets code"]
    with pytest.raises(ValueError, match="no codebook called “Other”"):
        qdc_import.from_source({"file": base64.b64encode(data).decode(), "codebook": "Other"})
    # a real export of two codebooks, and the command line
    codebooks.create(ws, "orig", "Remote work", "project", "csv", {"csv": SOURCE_CSV})
    codebooks.create(ws, "other", "Other book", "project", "csv", {"csv": "code,description\nx,An x\n"})
    out = tmp_path / "p.qdpx"
    qdpx.export_project(ws, out)
    with pytest.raises(qdc_import.SeveralCodebooks, match="“Other book”"):
        qdc_import.from_path(out)
    from enlens_claims import cli
    assert cli.main(["--ws", str(ws.root), "import-qdc", str(out)]) == 2
    assert "--codebook" in capsys.readouterr().err
    assert cli.main(["--ws", str(ws.root), "import-qdc", str(out), "rw", "--codebook", "Remote work"]) == 0
    assert json.loads(capsys.readouterr().out)["codes"] == 4 and frameworks.get("rw", ws).title == "Remote work"


def test_sets_and_the_project_attributes_outside_the_codebook():
    """QDC-5: a project's sets (children of <Project>) are counted; its name and origin are read in single quotes."""
    qde = ('<Project xmlns="urn:QDA-XML:project:1.0" name="Interviews" origin="NVivo 14"><CodeBook><Codes>'
           '<Code guid="p0" name="Work"><Code guid="p1" name="Trust"/></Code></Codes></CodeBook>'
           '<Sets><Set guid="s1" name="Feelings"><MemberCode targetGUID="p1"/></Set>'
           '<Set guid="s2" name="Women"><MemberSource targetGUID="d1"/></Set></Sets></Project>')
    st = qdc_import.to_state(*qdc_import.read_tree(_zip({"project.qde": qde.encode()})))
    assert st["summary"]["sets"] == 1 and "1 set left out: ENLENS has no sets." in st["summary"]["notes"]
    qde2 = ("<?xml version='1.0' encoding='utf-8'?><Project xmlns='urn:QDA-XML:project:1.0' name='Interviews' "
            "origin='ENLENS 0.18.8'><CodeBook><Codes><Code name='Remote work (codebook)' isCodable='false'>"
            "<Code name='1 Short' isCodable='true'><Description>Short</Description></Code></Code></Codes></CodeBook></Project>")
    st = qdc_import.to_state(*qdc_import.read_tree(_zip({"project.qde": qde2.encode()})))
    assert st["title"] == "Remote work" and [c["code"] for c in st["codes"]] == ["1"]


def test_sets_over_flat_codes_become_groups():
    """QDC-6: ATLAS.ti-style code groups. Strict: only flat codes, each in at most one set."""
    sets = ('<Sets><Set guid="s1" name="Feelings"><MemberCode targetGUID="a"/><MemberCode targetGUID="b"/></Set>'
            '<Set guid="s2" name="Places"><MemberCode targetGUID="c"/></Set></Sets>')
    flat = '<Code guid="a" name="Joy"/><Code guid="b" name="Fear"/><Code guid="c" name="Home"/><Code guid="d" name="Other"/>'
    data = _qdc(flat, origin="ATLAS.ti 24").replace(b"</CodeBook>", sets.encode() + b"</CodeBook>")
    st = qdc_import.to_state(*qdc_import.read_tree(data))
    assert {c["code"]: c["group"] for c in st["codes"]} == {"Joy": "Feelings", "Fear": "Feelings", "Home": "Places",
                                                          "Other": ""}
    s = st["summary"]
    assert s["sets_as_groups"] == 2 and s["sets"] == 0 and any("2 sets of codes became groups" in n for n in s["notes"])
    twice = sets.replace('<MemberCode targetGUID="c"/>', '<MemberCode targetGUID="a"/>')
    st = qdc_import.to_state(*qdc_import.read_tree(
        _qdc(flat, origin="ATLAS.ti 24").replace(b"</CodeBook>", twice.encode() + b"</CodeBook>")))
    assert all(c["group"] == "" for c in st["codes"]) and st["summary"]["sets"] == 2
    tree = '<Code guid="t" name="Top"><Code guid="a" name="Joy"/></Code><Code guid="b" name="Fear"/>'
    st = qdc_import.to_state(*qdc_import.read_tree(
        _qdc(tree, origin="ATLAS.ti 24").replace(b"</CodeBook>", sets.encode() + b"</CodeBook>")))
    assert st["summary"]["sets_as_groups"] == 0 and st["summary"]["sets"] == 2


def test_one_keyword_with_a_comma_survives_a_real_round_trip(ws, monkeypatch):
    """QDC-7: the exporter marks one keyword holding a comma with ";", so even a build that reports 0.18.7 or 0.0.0
    (a run from the sources) gives it back whole."""
    csv = ("code,description,group,group_name,when_to_use,when_not_to_use,keywords,examples\n"
           "place,Where it is,,,,,\"Paris, France\",\n" "two,Two words,,,,,\"a, b; c\",\n" "plain,Plain,,,,,one,\n")
    codebooks.create(ws, "kw", "Keywords", "project", "csv", {"csv": csv})
    for version in ("0.18.7", "0.0.0", "0.19.0"):
        monkeypatch.setattr(qdpx, "__version__", version)
        body = qdpx.codebook_xml(ws, "kw")
        assert "Keywords: Paris, France;<" in body.decode() and "Keywords: one<" in body.decode()
        c = {x["code"]: x for x in qdc_import.to_state(*qdc_import.read_tree(body))["codes"]}
        assert (c["place"]["keywords"], c["two"]["keywords"], c["plain"]["keywords"]) == \
            (["Paris, France"], ["a, b", "c"], ["one"]), version


def test_the_command_line_takes_the_title_from_an_accented_file_name(ws, tmp_path, capsys):
    """QDC-8: without --title, the file's own name (accents and all) is the title."""
    from enlens_claims import cli
    d = tmp_path / "Dávid mappa"
    d.mkdir()
    for fname, name, title in (("kódkönyv 2024.qdc", "kodkonyv_2024", "kódkönyv 2024"), ("éő.qdc", "eo", "éő")):
        (d / fname).write_bytes(_qdc('<Code name="A"><Description>a</Description></Code>'))
        assert cli.main(["--ws", str(ws.root), "import-qdc", str(d / fname)]) == 0
        out = json.loads(capsys.readouterr().out)
        assert (out["codebook"], out["title"]) == (name, title)


def test_a_deeper_heading_that_cannot_be_coded_has_its_description_counted():
    """QDC-9: Top › Mid (cannot be coded, with a description) › Leaf."""
    st = qdc_import.to_state(*qdc_import.read_tree(_qdc(
        '<Code name="Top"><Code name="Mid" isCodable="false"><Description>Important guidance</Description>'
        '<Code name="Leaf"/></Code></Code>')))
    s = st["summary"]
    assert (s["headings"], s["group_descriptions"]) == (1, 1)
    assert "1 description of a group or a heading was left out: a group, or a step in the tree, has only a name." \
        in s["notes"]
    assert any("has no description or cannot be coded" in n for n in s["notes"])


def test_colours_are_counted():
    """QDC-10: the summary says how many codes had a colour."""
    st = qdc_import.to_state(*qdc_import.read_tree(NVIVO))
    assert st["summary"]["colours"] == 1 and "1 code had a colour: ENLENS keeps none." in st["summary"]["notes"]
