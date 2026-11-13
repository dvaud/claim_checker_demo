"""0.17 (roadmap M2): a quick look uses the codebooks of the project it was opened from, read-only; opened from
nowhere, or when that codebook is gone, it knows only the SDG and the home-wide ones and raises nothing else."""
from __future__ import annotations

import pytest

from enlens_claims import codebooks, frameworks

from test_app import Api, api, home  # noqa: F401  (fixtures)

CSV = "code,description,group,keywords\nAlpha,First idea.,g,alpha\nBeta,Second idea.,g,beta\n"


def _project_with_codebook(home):
    ws = home.create_project("Tovertafel")
    folder = ws.root / "frameworks"
    folder.mkdir(exist_ok=True)
    (folder / "tover_codebook.csv").write_text(CSV, encoding="utf-8")
    return ws, folder


def test_quicklook_sees_origin_codebook_read_only(home):
    _, folder = _project_with_codebook(home)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    ql = home.create_quicklook("Rahimi.pdf", "Tovertafel")
    assert home.quicklook_origin(ql.root.name) == "Tovertafel"
    fw = frameworks.get("tover_codebook", ql)
    assert fw.source == "origin" and set(fw.codes) == {"Alpha", "Beta"}
    assert "tover_codebook" in frameworks.available(ql)
    assert not (ql.root / "frameworks").exists()  # nothing is copied into the quick look
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    row = next(c for c in codebooks.list_all(ql)["codebooks"] if c["name"] == "tover_codebook")
    assert row["editable"] is False
    other = home.create_project("Other")  # a project that is not a quick look still does not see it
    with pytest.raises(ValueError, match="Unknown framework"):
        frameworks.get("tover_codebook", other)


def test_quicklook_without_origin_or_with_gone_origin(home):
    ql = home.create_quicklook("Free.pdf", None)
    assert home.quicklook_origin(ql.root.name) is None
    assert "tover_codebook" not in frameworks.available(ql) and "sdg" in frameworks.available(ql)
    _project_with_codebook(home)
    ql2 = home.create_quicklook("Gone.pdf", "Tovertafel")
    home.remove_project("Tovertafel")
    assert home.quicklook_origin(ql2.root.name) is None
    assert "tover_codebook" not in frameworks.available(ql2)


def test_quicklook_from_a_quicklook_keeps_the_first_origin(home):
    _project_with_codebook(home)
    first = home.create_quicklook("One.pdf", "Tovertafel")
    second = home.create_quicklook("Two.pdf", first.root.name)
    assert home.quicklook_origin(second.root.name) == "Tovertafel"


def test_profile_endpoint_for_quicklook_uses_origin_codebook(api, home):
    _project_with_codebook(home)
    ql = home.create_quicklook("Rahimi.pdf", "Tovertafel")
    st, body = api("GET", f"/api/projects/{ql.root.name}/profile?framework=tover_codebook")
    assert st == 200 and body["framework"] == "tover_codebook"
    st, body = api("GET", "/api/projects/Other/profile?framework=nope")
    assert st != 200  # the panel falls back to SDG on this message
