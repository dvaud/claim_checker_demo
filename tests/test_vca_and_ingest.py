import os
import zipfile
from pathlib import Path

import pytest

from enlens_claims import ingest, sources, vca
from enlens_claims.retrieve import screen

REAL_XLSX = Path(os.environ.get(
    "ENLENS_VCA_XLSX",
    "/tmp/claude-0/-home-claude/12a8b3dc-c29e-5901-9802-f0034d70c22a/scratchpad/repo/ENLENS_CrossDoc/app_data/43621_2024_374_MOESM1_ESM.xlsx"))


def test_fake_workbook_cells(vca_xlsx):
    vts = {v.target: v for v in vca.load_workbook_targets(vca_xlsx)}
    assert vts["6.4"].cells == {"production": "direct_negative", "transportation": "", "end_use": ""}
    assert vts["8.5"].cells["production"] == "indirect_positive"
    assert vts["1.1"].cells["production"] == "indirect_negative"
    assert vts["6.4"].horizon == "short_term" and vts["1.1"].horizon == "medium_long_term"
    assert vts["7.1"].justification == ""


@pytest.mark.skipif(not REAL_XLSX.exists(), reason="real VCA workbook not available")
def test_real_workbook_matches_published_totals():
    s = vca.summary(vca.load_workbook_targets(REAL_XLSX))
    # Peyerl & van der Zwaan (2024): 61 targets, 30 direct and 119 indirect influences, 86 positive and 63 negative
    assert s == {"targets": 169, "justified": 61, "direct": 30, "indirect": 119, "positive": 86, "negative": 63,
                 "short_term": 47, "medium_long_term": 14}


def test_reference_splitting():
    items = vca.split_references("(1) IRENA. A report. 2022 (2) Smith J. A paper title here. J X 2020. https://doi.org/10.1234/abc.")
    assert len(items) == 2
    assert vca.ref_key(items[1]) == ("doi:10.1234/abc", "10.1234/abc")
    assert vca.ref_kind(items[0], None) == "report"


def test_ingest_pdf_pages_offsets_and_references(ws, corpus):
    stats = ingest.ingest(ws, [corpus])
    assert stats["added"] == 3
    doc = ws.query("SELECT * FROM documents WHERE kind='pdf'")[0]
    assert doc["n_pages"] == 3 and doc["doi"] == "10.9999/papera.2023"
    assert doc["title"].startswith("Water footprint")
    ps = ws.query("SELECT * FROM passages WHERE doc_id=? ORDER BY seq", (doc["doc_id"],))
    for p in ps:  # stored text and offsets agree
        assert doc["text"][p["start"]:p["end"]] == p["text"]
    water = [p for p in ps if "water stress" in p["text"]][0]
    assert water["page"] == 1 and water["section"] == "body"
    assert any(p["section"] in ("references", "reference_like") for p in ps if "Smith J" in p["text"])
    assert ingest.ingest(ws, [corpus])["duplicates"] == 3


def test_zip_input_and_zip_slip_guard(ws, tmp_path, corpus):
    z = tmp_path / "upload.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(corpus / "irena_jobs_report.txt", "nested/irena.txt")
        zf.writestr("../escape.txt", "Hydrogen escapes the folder and should not be written outside it." * 3)
    stats = ingest.ingest(ws, [z])
    assert stats["added"] == 1
    assert not (tmp_path / "escape.txt").exists()


def test_source_matching_by_doi_and_title(loaded):
    rows = {r["ref_key"]: r["method"] for r in loaded.query("SELECT * FROM doc_refs")}
    assert rows.get("doi:10.9999/papera.2023") == "doi"
    assert any(k.startswith("ref:irena") and m == "title" for k, m in rows.items())
    cov = {c["target"]: c for c in sources.coverage(loaded)}
    assert cov["6.4"]["available"] == 2 and cov["1.1"]["available"] == 0


def test_screen_keeps_hydrogen_impact_passages(loaded):
    s = screen(loaded)
    assert s["screened_in"] >= 1
    birds = loaded.query("SELECT p.screened FROM passages p JOIN documents d ON d.doc_id=p.doc_id WHERE d.kind='html'")
    assert all(r[0] == 0 for r in birds)


def test_manifest_declares_the_reference(ws, vca_xlsx, tmp_path):
    import zipfile

    from helpers import REPORT_B_TEXT

    vca.load_into(ws, vca_xlsx)
    z = tmp_path / "enlens_sources.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("sources/A_1_jobs.txt", REPORT_B_TEXT.replace("Hydrogen jobs outlook", "A differently titled file"))
        zf.writestr("manifest.csv", "file,priority,reference,doi\nsources/A_1_jobs.txt,A,"
                    "IRENA. Hydrogen jobs outlook for exporting countries. 2022,\n")
    stats = ingest.ingest(ws, [z])
    assert stats["declared"] == 1
    m = sources.match(ws)
    assert m["by_manifest"] == 1
    assert sources.coverage(ws)[1]["available"] == 1  # 8.5 cites only this report


def test_old_workspace_is_migrated(tmp_path):
    import sqlite3

    from enlens_claims.store import Workspace

    root = tmp_path / "old"
    root.mkdir()
    cx = sqlite3.connect(root / "enlens.sqlite")
    cx.execute("CREATE TABLE documents(doc_id TEXT PRIMARY KEY, path TEXT, sha1 TEXT UNIQUE, title TEXT, doi TEXT, kind TEXT, "
               "n_pages INT, n_chars INT, text TEXT, added_at TEXT)")
    cx.commit()
    cx.close()
    ws = Workspace.open(root)
    cols = {r[1] for r in ws.query("PRAGMA table_info(documents)")}
    assert "declared_ref" in cols


def test_reference_fixes_and_duplicate_merge():
    refs = {}
    for item in [
        "Olabi AG, Ali M, Al-murisi M, et al. Recent progress in Green Ammonia: Production, applications, assessment; "
        "barriers, and its role in achieving the sustainable development goals. Energy Convers Manag 2023. https://doi.org/10.1016/j.enconman.2022.116594",
        "Olabi AG, Ali M, Al-murisi M, et al. Recent progress in Green Ammonia : Production , applications , assessment ; "
        "barriers , and its role in achieving the sustainable development goals",
        "Mneimneh F, Ghazzawi H, Hejjeh MA. Roadmap to Achieving Sustainable Development via Green Hydrogen. Energies 2023;16:1368. "
        "https://doi.org/doi.org/10.3390/ en16031368",
        "Gore, K., Rigot-müller, P. & Coughlan, J. Cost assessment of alternative fuels for maritime transportation in Ireland",
        "https://doi.org/10.1016/j.trd.2022.103416",
    ]:
        k, doi = vca.ref_key(item)
        refs[k] = {"reference": item, "doi": doi, "targets": [str(len(refs) + 1) + ".1"]}
    alias = vca.merge_references(refs)
    canon = {k: alias.get(k, k) for k in refs}
    assert len(set(canon.values())) == 3
    olabi = canon["doi:10.1016/j.enconman.2022.116594"]
    assert olabi == "doi:10.1016/j.enconman.2022.116594" and set(refs[olabi]["targets"]) == {"1.1", "2.1"}
    mn = [k for k in refs if "mneimneh" in k][0]
    assert refs[mn]["doi"] == "10.3390/en16031368"
    gore = canon["doi:10.1016/j.trd.2022.103416"]
    assert "Gore" in refs[gore]["reference"] and refs[gore]["doi"] == "10.1016/j.trd.2022.103416"


def test_manifest_rows_sharing_one_file(ws, vca_xlsx, tmp_path):
    import zipfile

    from helpers import REPORT_B_TEXT

    vca.load_into(ws, vca_xlsx)
    z = tmp_path / "src.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("sources/A_1.txt", REPORT_B_TEXT)
        zf.writestr("manifest.csv", "file,reference,doi\nsources/A_1.txt,IRENA. Hydrogen jobs outlook for exporting countries. 2022,\n"
                    "sources/A_1.txt,Author A. Something not in the VCA list at all. 2020,\n")
    ingest.ingest(ws, [z])
    m = sources.match(ws)
    assert m["by_manifest"] == 1 and m["manifest_references_not_in_vca"]


def test_markdown_without_pages_and_unreadable_text(ws, tmp_path):
    d = tmp_path / "md"
    d.mkdir()
    good = "Green hydrogen production can increase water stress in arid regions. " * 8
    junk = "".join(f"(cid:{n})" for n in range(40, 120)) * 3
    (d / "B_1_paper.md").write_text(good + "\n\n" + junk)
    (d / "manifest.csv").write_text("file,reference,doi,markdown_file\nsources/B_1_paper.pdf,Ref one,,markdown/B_1_paper.md\n")
    stats = ingest.ingest(ws, [d])
    assert stats["declared"] == 1
    ps = ws.query("SELECT page, section FROM passages")
    assert all(p["page"] is None for p in ps)
    assert {p["section"] for p in ps} >= {"body", "unreadable"}
    assert ws.scalar("SELECT n_pages FROM documents") is None


def test_markdown_tables_are_flattened():
    t = ingest.strip_markdown("# Title\n| a | b |\n| --- | :-: |\n| water | stress |\nplain line")
    assert t.split("\n") == ["Title", " a b ", " water stress ", "plain line"]


def test_pdf_to_text_tool_keeps_pages_and_manifest(ws, vca_xlsx, tmp_path):
    import subprocess
    import sys
    import zipfile

    from helpers import PAPER_A_PAGES, make_pdf

    src = tmp_path / "sources"
    src.mkdir()
    make_pdf(src / "A_1_paper.pdf", PAPER_A_PAGES)
    man = tmp_path / "manifest.csv"
    man.write_text("file,reference,doi\nsources/A_1_paper.pdf,Author A. Water footprint of electrolytic hydrogen. 2023,10.9999/papera.2023\n")
    tool = Path(__file__).parent.parent / "tools" / "pdf_to_text.py"
    r = subprocess.run([sys.executable, str(tool), str(src), str(man)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    z = tmp_path / "enlens_text.zip"
    assert set(zipfile.ZipFile(z).namelist()) == {"manifest.csv", "sources/A_1_paper.txt"}
    vca.load_into(ws, vca_xlsx)
    stats = ingest.ingest(ws, [z])
    assert stats["declared"] == 1
    assert ws.scalar("SELECT n_pages FROM documents") == 3
    assert ws.scalar("SELECT page FROM passages WHERE text LIKE '%water stress%'") == 1
    assert sources.match(ws)["by_manifest"] == 1


def test_shifted_glyph_text_is_unreadable_but_tables_are_not():
    prose = "Green hydrogen production can increase water stress in arid regions and the local supply of jobs. " * 3
    shifted = "".join(chr(ord(c) - 29) if c.isalpha() and ord(c) - 29 > 32 else c for c in prose)  # '5HQHZDEOH' style
    garble = "\t,\x01\x02 -\x03\x04 .)\x05/ \x06\x07! 73;\x08, 4&\x0e$!# " * 12
    table = "Table 3.1 Investment 2000-2009 2010-2020 Cumulative USD billion " + " ".join(
        f"Algeria {i} {i * 3.5} Egypt {i + 1} {i * 2.25}" for i in range(20))
    assert not ingest.unreadable(prose)
    assert ingest.unreadable(shifted) and ingest.unreadable(garble)
    assert not ingest.unreadable(table)


def test_unreadable_document_does_not_count_as_available(ws, vca_xlsx, tmp_path):
    import zipfile

    from helpers import REPORT_B_TEXT

    vca.load_into(ws, vca_xlsx)
    garble = "\f".join("\t,\x01\x02 -\x03\x04 .)\x05/ \x06\x07! 73;\x08, 4&\x0e$!# " * 40 for _ in range(6))
    z = tmp_path / "enlens_text.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("sources/A_1_jobs.txt", "Hydrogen jobs outlook. " + garble)
        zf.writestr("sources/A_2_agenda.txt", REPORT_B_TEXT)
        zf.writestr("manifest.csv", "file,reference,doi\nsources/A_1_jobs.pdf,"
                    "IRENA. Hydrogen jobs outlook for exporting countries. 2022,\n"
                    "sources/A_2_agenda.pdf,IRENA. Hydrogen jobs outlook for exporting countries. 2022,\n")
    stats = ingest.ingest(ws, [z], exclude=["A_2_*"])
    assert stats["excluded"] == ["A_2_agenda.txt"] and stats["added"] == 1
    assert stats["mostly_unreadable"] == ["A_1_jobs.txt"]
    assert sources.match(ws)["by_manifest"] == 1  # still linked, so the gap is visible
    cov = {c["target"]: c for c in sources.coverage(ws)}
    assert cov["8.5"]["available"] == 0 and cov["8.5"]["unreadable"] == 1
    assert sources.docs_for_target(ws, "8.5") == []


def test_notes_beside_the_sources_are_not_ingested(ws, tmp_path):
    from helpers import REPORT_B_TEXT

    d = tmp_path / "upload"
    (d / "sources").mkdir(parents=True)
    (d / "sources" / "A_1.txt").write_text(REPORT_B_TEXT)
    (d / "sources" / "B_2.txt").write_text(REPORT_B_TEXT.replace("Hydrogen", "Ammonia"))
    (d / "problems.txt").write_text("A_10.pdf: unreadable text layer on 18 of 19 pages. " * 5)
    (d / "manifest.csv").write_text("file,reference,doi\nsources/A_1.pdf,IRENA. Hydrogen jobs outlook. 2022,\n")
    stats = ingest.ingest(ws, [d])
    assert stats["added"] == 2 and stats["not_in_manifest"] == ["B_2.txt"]
    assert ws.scalar("SELECT COUNT(*) FROM documents WHERE path LIKE '%problems%'") == 0
