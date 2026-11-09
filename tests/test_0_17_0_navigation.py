"""0.17.0: the navigation. Thirteen sidebar entries became seven places; a place's views are tabs on its pages; the
groups say once whether they use the AI, with the one AI mark; the foot has one status area of a fixed size, and an
update takes Quit's place; Find opens the feature finder; old addresses open their new home. Checked as the browser
files they are, like the other page tests."""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


def _read(name):
    return (STATIC / name).read_text(encoding="utf-8")


def _nav():
    html = _read("index.html")
    nav = html[html.index('<nav class="nav" aria-label="Main" id="nav">'):]
    return nav[:nav.index("</nav>")]


def test_seven_places_in_two_groups_with_no_counts_and_no_tagline():
    nav = _nav()
    routes = re.findall(r'data-route="([a-z]+)"', nav)
    assert routes == ["overview", "documents", "search", "codes", "concepts", "themes", "hypotheses"]
    assert re.findall(r'data-section="([a-z]+)"', nav) == ["explore", "check"]
    assert "count" not in nav and "nav-ai" not in nav and "nav-legend" not in nav
    html = _read("index.html")
    brand = html[html.index('<a class="brand" href="#/overview"'):html.index("</a>", html.index('<a class="brand" href="#/overview"'))]
    assert "<small>" not in brand  # no tagline under the name
    # the project, then Find, then the places
    assert html.index('id="project-switch"') < html.index('id="find-btn"') < html.index('id="nav"')


def test_places_and_their_views():
    features = _read("features.js")
    for place in ("overview", "documents", "search", "codes", "concepts", "themes", "hypotheses"):
        assert re.search(rf"^  {place}: \{{ title: ", features, re.M), place
    for view, href in (("researchlog", "#/log"), ("annotations", "#/notes"), ("bibliography", "#/bibliography"),
                       ("profile", "#/profile"), ("codebooks", "#/codebooks"), ("answers", "#/hypotheses"), ("map", "#/map")):
        assert re.search(rf'\["{view}", "[^"]+", "{re.escape(href)}"', features), view
    assert '["profile", "By document", "#/profile", "tag"]' in features  # Profile's new name, under Codes
    assert "export function viewTabs(place, current)" in features and 'class: "settings-tabs view-tabs"' in features
    # each view's page shows its place's title and the tabs
    for f, place, view in (("views/sources.js", "documents", "sources"), ("views/notes.js", "documents", "annotations"),
                           ("views/bibliography.js", "documents", "bibliography"), ("views/profile.js", "codes", "profile"),
                           ("views/codebooks.js", "codes", "codebooks"), ("views/overview.js", "overview", "overview"),
                           ("views/log.js", "overview", "researchlog")):
        assert f'viewTabs("{place}", "{view}")' in _read(f), f


def test_one_ai_mark():
    features = _read("features.js")
    marks = features[features.index("const AI_TEXT = {"):features.index("export function aiTag(")]
    assert '"No AI"' in marks and '"AI on request"' in marks and '"Uses the AI"' in marks
    fn = features[features.index("export function aiTag("):features.index("\n}\n", features.index("export function aiTag("))]
    assert 'icon("cpu"' in fn and "title: plain" in fn   # the chip, always; the long words in its tooltip
    app = _read("app.js")
    assert 'GROUP_AI = { explore: "optional", check: "uses" }' in app and "g.appendChild(aiTag(level))" in app


def test_old_addresses_open_their_new_home():
    app = _read("app.js")
    for path, place in (("check", "hypotheses"), ("batch", "hypotheses"), ("history", "hypotheses"), ("map", "hypotheses"),
                        ("profile", "codes"), ("codebooks", "codes"), ("notes", "documents"), ("bibliography", "documents"),
                        ("log", "overview"), ("hypotheses", "hypotheses")):
        assert re.search(rf'\[/\^\\/{path}\$/, "{place}", render', app), path
    assert "renderCheck" not in app and "renderBatch" not in app and "renderHistory" not in app
    reg = _read("registry.js")
    assert 'link: "#/check"' not in reg and 'link: "#/history"' not in reg and "#/hypotheses?batch=" in reg


def test_the_status_area_has_one_fixed_size():
    html = _read("index.html")
    area = html[html.index('<div class="status-area" id="status-area">'):]
    area = area[:area.index('<div class="sidebar-app">')]
    assert 'id="work-indicator"' in area and 'id="privacy-indicator"' in area
    assert "jobs-indicator" not in html and "queue-indicator" not in html  # the panels are gone
    css = _read("navigation.css")
    assert re.search(r"\.status-area \{ height: \d+px;", css)
    assert "@media (max-height: 759px) { .status-area { height:" in css
    app = _read("app.js")
    draw = app[app.index("async function drawStatus()"):app.index("// 0.14.2: the theme is a small icon")]
    assert "privacy.hidden = !!w;" in draw and "box.hidden = !w;" in draw   # the work takes the AI line's place
    assert 'class: "work-who"' in draw   # and keeps where text goes, in a word
    assert "details" not in draw and "ps-menu" not in draw   # never a panel


def test_update_takes_quits_place_and_quit_stays_in_settings():
    html = _read("index.html")
    row = html[html.index('<div class="sidebar-app-row">'):html.index("</aside>")]
    assert row.index('id="update-btn"') < row.index('id="quit-btn"') < row.index('id="theme-btn"')
    app = _read("app.js")
    show = app[app.index("function showUpdate("):app.index("function updatePopup(")]
    assert "if (quit) quit.hidden = true;" in show and 'const to = "Update";' in show
    assert "Updates.quit = () => quitApp();" in app
    settings = _read("views/settings.js")
    assert "Updates.quit()" in settings and 'queue: "model"' in settings and "queueSection()" in settings
    assert "export function queueSection()" in _read("views/queue.js")
    assert "export async function startClaudeNow(project)" in _read("lib.js")


def test_find_opens_the_feature_finder():
    app = _read("app.js")
    assert 'import { openFinder } from "./finder.js";' in app
    assert 'btn.addEventListener("click", () => openFinder());' in app
    assert '(e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k"' in app
    assert "finderBox()" in _read("views/overview.js")
