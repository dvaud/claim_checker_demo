"""0.13.3: the result page's rules for the whole app. One type scale and two weights, one card style (no shadow),
colour only where it means something (the AI marks are grey, not the purple of "Mixed evidence"), page subtitles of
one short line, longer explanations in help marks, downloads as one quiet line of links, and tables that no longer
make a phone page scroll sideways."""
from __future__ import annotations

import re
from pathlib import Path

from test_app import api, home  # noqa: F401  (fixtures)
from _static import assert_sheet_after

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
CSS = (STATIC / "v0133.css").read_text()
LIB = (STATIC / "lib.js").read_text()


def view(name: str) -> str:
    return (STATIC / "views" / f"{name}.js").read_text()


def rules(selector: str) -> str:
    """The declarations of every rule of v0133.css whose selector list names `selector` exactly."""
    out = []
    for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)):
        if selector in [s.strip() for s in sel.split(",")]:
            out.append(body)
    return " ".join(out)


def test_the_stylesheet_is_linked_last_and_uses_the_colour_tokens_only(api):  # noqa: F811
    # after every earlier release's sheet, and before site.css (0.13.5: tests/_static.py)
    assert_sheet_after("/static/v0133.css", "/static/v013.css")
    # light and dark both work: no colour of its own, only the tokens of tokens.css
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", CSS)
    st, body = api("GET", "/static/v0133.css", token=False)
    assert st == 200 and b".nav-ai-uses" in body


def test_one_type_scale_and_two_weights():
    assert "font-weight: 600" in rules("h1") and "font-size: 1.05rem" in rules("h2")
    # every button in the regular weight; only the main button (and a danger button) is bold
    assert "font-weight: 400" in rules(".btn")
    assert "font-weight: 600" in rules(".btn-primary") and "font-weight: 600" in rules(".btn-danger")
    assert "font-weight: 400" in rules("details.fold > summary")
    for small in ("small", ".small", ".field-help", ".btn-sm", ".badge", ".chip"):
        assert "font-size: .875rem" in rules(small), small
    # the line above a title: in sentence case and the regular weight, as on the result page
    assert "text-transform: none" in rules(".fe-section") and "font-weight: 400" in rules(".eyebrow")


def test_one_card_style_without_shadows():
    for sel in (".card", ".ov-card"):
        assert "box-shadow: none" in rules(sel), sel
    assert "transform: none" in rules(".ov-card:hover")
    # Settings → AI: the privacy panel inside the Claude box inside the card is not a third box
    assert "border: 0" in rules(".cc-card .terms-panel")


def test_colour_only_where_it_means_something():
    # the AI marks were purple (--mixed), the colour of "Mixed evidence", and "No AI needed" was green
    for sel in (".nav-ai-uses", ".nav-ai-optional"):
        assert "--mixed" not in rules(sel) and rules(sel), sel
    tag = rules(".ai-tag.ai-uses")
    assert "color: var(--muted)" in tag and "background: none" in tag and "border: 0" in tag
    # states and counts are facts: grey, not the colours of the judgements
    assert "var(--text-2)" in rules(".ov-state.ov-made") and "var(--text-2)" in rules(".to-review")
    assert "border-color: transparent" in rules(".badge")
    assert "var(--surface-3)" in rules(".badge.status-uncertain")
    # the separator of the eyebrow ends its first part, so a wrapped line never begins with "·"
    assert 'content: "·"' in rules(".feature-eyebrow .fe-section::after")


def test_downloads_are_a_quiet_line_of_links():
    assert "export function downloadLinks(" in LIB and 'class: "dl-links"' in LIB
    # 0.17.0: the downloads of every answer are in the head of the Hypotheses page; the map is its tab, not a button
    hyp = view("hypotheses")
    head = hyp[hyp.index("const downloads = downloadLinks(["):hyp.index("const tabs = viewTabs(")]
    assert '"Excel (.xlsx)"' in head and '"CSV"' in head and "(for programmers)" in head
    assert "btn-primary" not in head and "actions: downloads" in head and "Show as a map" not in hyp
    search = view("search")
    assert "downloadLinks([" in search and '"Excel (.xlsx)"), ' not in search
    # Profile: the link appears once there is a profile; there is no disabled button before that
    prof = view("profile")
    draw = prof[prof.index("  function draw() {"):prof.index("drawControls();")]
    assert "prof.pass1.done ? downloadLinks([" in draw and "disabled: !prof.pass1.done" not in draw


def test_longer_explanations_sit_in_help_marks():
    assert "export function helpMark(label, text" in LIB and '"link-btn help-mark"' in LIB
    assert "color: var(--muted)" in rules(".help-mark")   # styled on every page now, not only on .result
    # a note opened near the right edge moves left to stay in the window
    pop = LIB[LIB.index("export function popNote("):LIB.index("// A grade with its certainty")]
    assert "r.right > room ? Math.min(r.right - room, r.left - 8) : 0" in pop and "translateX(" in pop
    hist = view("history")
    assert 'helpMark("About a second opinion", why)' in hist and "For comparison only: the answers do not change." in hist
    search = view("search")
    assert 'helpMark("What is a passage?"' in search
    assert 'h("p", { class: "muted small", style: { margin: "-4px 0 8px" } }, "A passage is' not in search
    assert 'helpMark("About the auditor"' in view("settings")
    assert 'helpMark("How the AI labels passages"' in view("profile")
    # the Overview card says one thing; what it is for is its tooltip
    ov = view("overview")
    assert '"ov-use"' not in ov and "title: !opts.compact && f.use ? f.use : null" in ov


def test_page_subtitles_are_one_short_line():
    subs = {}
    # 0.17.0: Check a hypothesis, Check several and Results are one page, Hypotheses
    for name in ("sources", "bibliography", "search", "profile", "concepts", "themes", "hypotheses", "map"):
        js = view(name)
        for m in re.finditer(r"pageHead\(\"[^\"]+\", \{[^\n]*?\bsub: (\"[^\"]*\"|`[^`]*`)", js):
            subs.setdefault(name, []).append(m.group(1))
        m = re.search(r"\n\s+sub: (\"[^\"]*\"|`[^`]*`),", js)
        if m:
            subs.setdefault(name, []).append(m.group(1))
    assert set(subs) >= {"sources", "bibliography", "search", "profile", "concepts", "themes", "hypotheses", "map"}
    for name, found in subs.items():
        for s in found:
            # the project's name is in the sidebar and the top bar; a subtitle no longer repeats it
            assert "project “${project}”" not in s, name
            if "${" not in s:
                assert len(s) <= 130 and s.count(". ") <= 1, (name, s)


def test_the_document_page_has_two_quiet_links_and_no_extra_lines():
    src = view("sources")
    btn = src[src.index("const copyBtn = h("):]
    assert btn.split("\n")[0].count('class: "link-btn it"') == 1
    assert "Opens in a new tab, as the file was when it was added." not in src   # it is in the link's tooltip
    assert '"The text as the app reads it."' not in src


def test_a_table_that_scrolls_in_its_frame_holds_its_hidden_labels():
    # the hidden text of the line buttons (position: absolute) escaped the Search table's frame and made the whole
    # page scroll sideways at 390 px: a positioned frame clips them
    assert "position: relative" in rules(".kwic-wrap")
    for sel in (".table-wrap", ".map-wrap", ".dv-kwic"):
        assert "position: relative" in rules(sel), sel
    assert re.search(r"\.visually-hidden \{ position: absolute", (STATIC / "app.css").read_text())


def test_the_document_pages_bibliography_line_stacks_on_a_phone():
    # wrapped as a row, the library icon could stand alone on a line and a line could begin with "·": on a phone each
    # part (the reference, the work's title, its DOI, Open in Zotero) has a line of its own beside the icon
    phone = CSS[CSS.index("@media (max-width: 600px) {"):]
    assert re.search(r"\.dv-bib \{ display: grid; grid-template-columns: auto minmax\(0, 1fr\);", phone)
    assert ".dv-bib > .sep { display: none; }" in phone and ".dv-bib > :not(.icon):not(.sep) { grid-column: 2; }" in phone
