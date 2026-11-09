"""The manual is a hub (docs/MANUAL.md) and short pages (docs/manual/*.md): it holds together.

Not a release's feature but a standing check of the documentation (see docs/DEVELOPING.md, *The manual*): every page is
reached from the hub, every relative link and #anchor in the manual, the README and DEVELOPING.md resolves (a file, and
a heading as GitHub names it), every picture the manual shows exists and every picture in docs/images/manual is shown,
and each page keeps its shape (the way back to the hub, one title, the *In short* box) and stays short.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
HUB = DOCS / "MANUAL.md"
PAGES = sorted((DOCS / "manual").glob("*.md"))
IMAGES = DOCS / "images" / "manual"
CHECKED = [HUB, *PAGES, ROOT / "README.md", DOCS / "DEVELOPING.md"]

# pages that are lists to look things up in, not reading: no *In short* box
REFERENCE = {"glossary.md", "troubleshooting.md"}
MAX_WORDS_HUB = 1200
MAX_WORDS_PAGE = 5000   # the SDG pack is the longest page; a page that grows past this is split


def _prose(text: str) -> str:
    """The text without fenced code blocks (a `# comment` in bash is not a heading, a link in code is not a link)."""
    return re.sub(r"^(```|~~~).*?^\1[ \t]*$", "", text, flags=re.M | re.S)


def _slug(heading: str) -> str:
    """The anchor GitHub gives a heading: the text as shown, lower case, punctuation dropped, spaces as hyphens."""
    text = re.sub(r"`([^`]*)`", r"\1", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text).replace("*", "")
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    for m in re.finditer(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", _prose(path.read_text(encoding="utf-8")), re.M):
        base = _slug(m.group(1))
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.add(base if n == 0 else f"{base}-{n}")
    return out


def _links(path: Path) -> list[str]:
    text = _prose(path.read_text(encoding="utf-8"))
    text = re.sub(r"`[^`\n]*`", "", text)  # inline code
    found = re.findall(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", text)
    found += re.findall(r"<(?:img|a|source)\b[^>]*?\b(?:src|href|srcset)=\"([^\"]+)\"", text)
    return [u for u in found if not re.match(r"[a-z][a-z0-9+.-]*:", u, re.I)]  # http(s), mailto…: not ours


def _words(path: Path) -> int:
    return len(re.findall(r"\w+", _prose(path.read_text(encoding="utf-8"))))


def test_every_page_is_reached_from_the_hub():
    assert PAGES, "docs/manual/ has no pages"
    linked = {(HUB.parent / u.split("#")[0]).resolve() for u in _links(HUB)}
    assert [p.name for p in PAGES if p.resolve() not in linked] == []


def test_every_link_and_anchor_resolves():
    problems = []
    for doc in CHECKED:
        for url in _links(doc):
            target, _, anchor = url.partition("#")
            path = (doc.parent / target).resolve() if target else doc
            if not path.exists():
                problems.append(f"{doc.relative_to(ROOT)}: {url} (no such file)")
            elif anchor and path.suffix == ".md" and anchor not in _anchors(path):
                problems.append(f"{doc.relative_to(ROOT)}: {url} (no such heading)")
    assert problems == []


def test_every_picture_is_there_and_shown():
    shown = {(page.parent / u).resolve() for page in [HUB, *PAGES] for u in _links(page) if u.endswith(".png")}
    assert [str(p.relative_to(ROOT)) for p in shown if not p.exists()] == []
    assert [p.name for p in sorted(IMAGES.glob("*.png")) if p.resolve() not in shown] == []
    for p in IMAGES.glob("*.png"):
        assert p.stat().st_size < 300_000, f"{p.name}: make it smaller (tools/manual_screenshots.py)"


def test_each_page_keeps_its_shape_and_stays_short():
    assert _words(HUB) <= MAX_WORDS_HUB
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        assert text.startswith("[Manual](../MANUAL.md) › "), page.name
        assert len(re.findall(r"^# ", _prose(text), re.M)) == 1, page.name
        if page.name not in REFERENCE:
            assert "> **In short**" in text, page.name
        assert _words(page) <= MAX_WORDS_PAGE, f"{page.name} has {_words(page)} words: split it"


def test_the_hub_and_the_old_anchors():
    """The README and DEVELOPING.md link into the pages, not to the anchors of the one-file manual of 0.15.4."""
    for doc in (ROOT / "README.md", DOCS / "DEVELOPING.md"):
        assert not re.search(r"MANUAL\.md#", doc.read_text(encoding="utf-8")), doc.name
