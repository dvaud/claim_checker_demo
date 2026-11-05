"""0.13.5: fixes found while building Margin on ENLENS.

- Accented names in zips that do not mark them as UTF-8 (Finder's Compress) are read right.
- *Import a project* takes a project folder zipped by hand, not only a zip made with *Download as a zip*.
- The icon is drawn four times larger and scaled down: its edges are smooth.
- "Second opinion" everywhere: the job's name, its progress lines, the line under a result, the errors, Settings.
"""
from __future__ import annotations

import unicodedata
import zipfile
from pathlib import Path

import pytest

from enlens_claims import bundle, ingest
from enlens_claims.ingest import zip_name
from enlens_claims.sources import original_file

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


def test_accented_names_in_a_finder_zip_are_read_right(tmp_path):
    """Finder does not mark zip names as UTF-8: Python read "másolat" as "ma╠üsolat"."""
    nfd = unicodedata.normalize("NFD", "Meadows másolat.md")
    info = zipfile.ZipInfo(nfd.encode("utf-8").decode("cp437"))
    info.flag_bits = 0
    assert zip_name(info) == nfd
    plain = zipfile.ZipInfo("Ăn ‘quoted’.md")
    plain.flag_bits = 0x800
    assert zip_name(plain) == "Ăn ‘quoted’.md"
    odd = zipfile.ZipInfo("caf\x82.md")  # a real code page 437 name that is not UTF-8 stays as it was read
    odd.flag_bits = 0
    assert zip_name(odd) == "caf\x82.md"

    # unpacked under its right name when added as documents
    # as Finder writes it: the name's UTF-8 bytes, without the UTF-8 flag (zipfile would set it, so it is patched in)
    raw = nfd.encode("utf-8")
    stand_in = b"x" * len(raw)
    z = tmp_path / "finder.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(stand_in.decode(), "# Meadows\n\nWater stress rises near the plant in summer.")
    z.write_bytes(z.read_bytes().replace(stand_in, raw))
    with zipfile.ZipFile(z) as zf:
        assert not zf.infolist()[0].flag_bits & 0x800 and zf.namelist() != [nfd]
    out = ingest.discover([z], tmp_path / "unpacked")
    assert [unicodedata.normalize("NFC", p.name) for p in out] == ["Meadows másolat.md"]


def test_a_project_folder_zipped_by_hand_imports_too(loaded, tmp_path):
    """Finder's Compress puts the project in a folder of its own and adds __MACOSX: ENLENS 0.13.5 takes it."""
    up = loaded.root / "uploads" / "batch1"
    up.mkdir(parents=True)
    (up / "field.txt").write_text("Field notes on hydrogen. Water stress rises near the plant in summer. " * 3)
    ingest.ingest(loaded, [up / "field.txt"])
    n = loaded.scalar("SELECT COUNT(*) FROM documents")
    z = tmp_path / "Tovertafel.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in loaded.root.rglob("*"):
            if f.is_file():
                arc = f"{loaded.root.name}/" + f.relative_to(loaded.root).as_posix()
                zf.write(f, arc)
                zf.writestr("__MACOSX/" + arc.rsplit("/", 1)[0] + "/._" + f.name, b"\0\5\26\7")
    ws2 = bundle.import_project(z, tmp_path / "copy")
    assert ws2.scalar("SELECT COUNT(*) FROM documents") == n
    assert not (tmp_path / "copy" / loaded.root.name).exists() and not (tmp_path / "copy" / "__MACOSX").exists()
    doc = ws2.query("SELECT doc_id, path FROM documents WHERE path LIKE '%field.txt'")[0]
    assert doc["path"] == str((tmp_path / "copy" / "uploads" / "batch1" / "field.txt").resolve())
    assert original_file(ws2, doc["doc_id"])["inside"]

    with zipfile.ZipFile(tmp_path / "two.zip", "w") as zf:
        zf.write(loaded.db_path, "A/enlens.sqlite")
        zf.write(loaded.db_path, "B/enlens.sqlite")
    with pytest.raises(ValueError, match="holds 2 projects"):
        bundle.import_project(tmp_path / "two.zip", tmp_path / "two")
    with zipfile.ZipFile(tmp_path / "docs.zip", "w") as zf:
        zf.writestr("paper.md", "# A paper")
    with pytest.raises(ValueError, match="no ENLENS project.*Add documents"):
        bundle.import_project(tmp_path / "docs.zip", tmp_path / "docs")


def test_a_zip_made_with_download_still_imports(loaded, tmp_path):
    z = tmp_path / "p.zip"
    bundle.export_project(loaded, z)
    ws2 = bundle.import_project(z, tmp_path / "again")
    assert ws2.scalar("SELECT COUNT(*) FROM documents") == loaded.scalar("SELECT COUNT(*) FROM documents")


def test_the_import_dialog_says_a_folder_zipped_by_hand_works():
    js = (STATIC / "views" / "projects.js").read_text(encoding="utf-8")
    assert "A project folder zipped by hand works too" in js


def test_the_icon_has_smooth_edges():
    pytest.importorskip("PIL")
    from enlens_claims.gui.launcher import draw_icon

    img = draw_icon(64)
    assert img.size == (64, 64)
    alpha = img.getchannel("A").histogram()
    # the disc's rim is blended into the background: drawn at one size it would be only 0 or 255
    assert sum(alpha[1:255]) > 40


def test_second_opinion_everywhere():
    from enlens_claims import claimcheck, home, runs
    from enlens_claims.gui import server

    src = {m.__name__: Path(m.__file__).read_text(encoding="utf-8") for m in (claimcheck, home, runs, server)}
    page = {f: (STATIC / f).read_text(encoding="utf-8")
            for f in ("app.js", "views/result.js", "views/settings.js", "views/history.js")}
    for text in list(src.values()) + list(page.values()):
        for old in ("Second AI model", "The second model is reading", "The second model read",
                    "Choose a second model", "The second model must be", "The second model is the same",
                    "(a second model, the context length)", '"the second model"', "add a second model"):
            assert old not in text, old
    assert '"second-opinion": { icon: "cpu", text: "Second opinion"' in (STATIC / "registry.js").read_text()  # 0.13.6
    assert "The second opinion read" in page["views/result.js"]
    from enlens_claims import taskkinds  # 0.13.6: the run's name lives in the registry

    assert taskkinds.get("second").run_name == "Second opinion"
    assert "The model for second opinions is the same as the main model" in src["enlens_claims.gui.server"]
