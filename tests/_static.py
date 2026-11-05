"""Shared checks of the page's stylesheets (0.13.5).

index.html links ENLENS's stylesheets in release order, then the marker `<!-- release stylesheets end -->`, then
`site.css` (the installation's own look) last. A release adds its sheet just above the marker, so a test of a
release's sheet says which sheets it must follow, not that it is linked last.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
MARKER = "<!-- release stylesheets end -->"
SITE = "/static/site.css"
LINK = r'<link rel="stylesheet" href="([^"]+)">'


def index_html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def release_sheets(index: str | None = None) -> list[str]:
    """ENLENS's own stylesheets, in the order index.html links them (above the marker)."""
    index = index if index is not None else index_html()
    assert index.count(MARKER) == 1, "index.html must hold the marker once"
    return re.findall(LINK, index.split(MARKER, 1)[0])


def assert_sheet_after(sheet: str, earlier: str, index: str | None = None) -> None:
    """`sheet` is one of ENLENS's sheets, linked after `earlier` and every sheet before it, and before site.css."""
    index = index if index is not None else index_html()
    sheets = release_sheets(index)
    assert sheet in sheets, f"{sheet} is not linked above the marker"
    assert earlier in sheets, f"{earlier} is not linked above the marker"
    assert sheets.index(earlier) < sheets.index(sheet), f"{sheet} must come after {earlier}"
    after = re.findall(LINK, index.split(MARKER, 1)[1])
    assert after == [SITE], f"only site.css may follow the marker, found {after}"


def defined_tokens() -> set[str]:
    """The custom properties ENLENS defines (tokens.css, and any app.css still defines)."""
    css = "".join((STATIC / f).read_text(encoding="utf-8") for f in ("tokens.css", "app.css"))
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
