"""The documents hold together (0.18.1, roadmap J2.6): every relative link in the README, the changelog and the
documents of docs/ resolves (a file, and a heading in it where the link names one); every feature of the app has a
section in the manual; and the README's *New in* is the changelog's newest entry. (tests/test_manual.py checks the
manual's own pages, their pictures and their shape.)"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import release  # noqa: E402

DOCS = ROOT / "docs"
DOCUMENTS = [ROOT / "README.md", ROOT / "CHANGELOG.md", ROOT / "SECURITY.md", ROOT / "changes" / "README.md",
             *sorted(DOCS.rglob("*.md"))]
# the roadmap is a plan and the changelog a history: they name files and pages that have since moved (CHANGELOG.md is
# checked for the links that point at files of today; see below), so only files that exist are required of them
LOOSE = {"ROADMAP.md", "CHANGELOG.md", "USER_TESTS.md"}


def _prose(text: str) -> str:
    return re.sub(r"^(```|~~~).*?^\1[ \t]*$", "", text, flags=re.M | re.S)


def _slug(heading: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text).replace("*", "")
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def _headings(path: Path) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$",
                                            _prose(path.read_text(encoding="utf-8")), re.M)]


def _anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    for h in _headings(path):
        base = _slug(h)
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.add(base if n == 0 else f"{base}-{n}")
    return out


def _links(path: Path) -> list[str]:
    text = re.sub(r"`[^`\n]*`", "", _prose(path.read_text(encoding="utf-8")))   # code is not a link
    found = re.findall(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", text)
    found += re.findall(r"<(?:img|a|source)\b[^>]*?\b(?:src|href|srcset)=\"([^\"]+)\"", text)
    return [u for u in found if not re.match(r"[a-z][a-z0-9+.-]*:", u, re.I)]


def test_the_documents_are_found():
    assert len(DOCUMENTS) > 25 and all(p.exists() for p in DOCUMENTS)


def test_every_relative_link_in_every_document_resolves():
    problems = []
    for doc in DOCUMENTS:
        for url in _links(doc):
            target, _, anchor = url.partition("#")
            path = (doc.parent / target).resolve() if target else doc
            if not path.exists():
                problems.append(f"{doc.relative_to(ROOT)}: {url} (no such file)")
            elif anchor and path.suffix == ".md" and doc.name not in LOOSE and anchor not in _anchors(path):
                problems.append(f"{doc.relative_to(ROOT)}: {url} (no such heading)")
    assert problems == []


def _features() -> list[dict]:
    """FEATURES of features.js: key, title and href of each entry (read as text, so no JavaScript runs)."""
    text = (ROOT / "src" / "enlens_claims" / "gui" / "static" / "features.js").read_text(encoding="utf-8")
    body = text[text.index("export const FEATURES"):]
    body = body[:body.index("\n};")]
    out = []
    for m in re.finditer(r"^  (\w+): \{\s*\n\s+section: [^,]+, title: \"([^\"]+)\"(?:, icon: \"[^\"]*\")?, href: \"([^\"]+)\"",
                         body, re.M):
        out.append({"key": m.group(1), "title": m.group(2), "href": m.group(3)})
    return out


# A feature's section in the manual: a heading, in a page of docs/manual/, that names it. A feature is found by its
# title ("Search" -> "## Search"), or here, when the manual names it otherwise. Features without any section are listed
# in NOT_YET rather than left unseen: the day the manual has one, the test asks for this entry to be removed.
SECTION_OF = {
    "sources": "first-steps.md",
    "together": "together.md",
    "codebooks": "codebooks.md",
    "profile": "explore.md",
    "check": "check.md",
    "batch": "check.md",
    "history": "check.md",
    "annotations": "notes-and-log.md",
    "researchlog": "notes-and-log.md",
}
NOT_YET: set[str] = set()


def _manual_headings() -> dict[str, list[str]]:
    return {p.name: [h.lower().replace("*", "") for h in _headings(p)] for p in sorted((DOCS / "manual").glob("*.md"))}


def test_every_feature_of_the_app_has_a_section_in_the_manual():
    features = _features()
    assert len(features) >= 10, "features.js was not read"
    manual = _manual_headings()
    lacking, stale = [], []
    for f in features:
        by_title = [name for name, heads in manual.items() if any(f["title"].lower() in h or f["key"] in h for h in heads)]
        named = SECTION_OF.get(f["key"])
        if named and named not in manual:
            stale.append(f"{f['key']}: {named} is not a page of the manual")
        if not by_title and not named:
            lacking.append(f"{f['key']} ({f['title']}, {f['href']})")
        if f["key"] in NOT_YET and (by_title or named):
            stale.append(f"{f['key']} has a section now: remove it from NOT_YET")
    assert stale == []
    lacking = [f for f in lacking if f.split(" ")[0] not in NOT_YET]
    assert lacking == [], \
        f"features with no section in docs/manual/: {lacking} (write one; the manual page names the feature in a heading)"


def test_the_readmes_new_in_is_the_newest_changelog_entry():
    changed = release.sync_notes(check_only=True)
    assert "README.md" not in changed, "README.md's New in does not match the newest entry of CHANGELOG.md: run `python tools/release.py sync-notes`"
    # the app's What's new belongs to the same version
    first = (ROOT / release.WHATS_NEW).read_text("utf-8").splitlines()[0]
    assert first.startswith(f"# {release.release_version()}:"), f"whats-new.md is {first!r}; the newest entry is {release.release_version()}"


def test_the_readme_stays_a_front_door():
    text = (ROOT / "README.md").read_text("utf-8")
    assert text.count(release.NEW_IN_START.split(" (")[0]) == 1 and text.count(release.NEW_IN_END) == 1
    assert len(text.splitlines()) <= 130                         # about 100 lines (docs/DEVELOPING.md, The README)
    assert "## Earlier releases" not in text and "## Layout" not in text      # no copy of the changelog or the layout


@pytest.mark.parametrize("name", ["install.md", "check.md"])
def test_the_pages_the_readme_points_at_are_in_the_manual(name):
    assert f"docs/manual/{name}" in (ROOT / "README.md").read_text("utf-8")
