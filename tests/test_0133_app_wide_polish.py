"""0.13.3: the result page's rules for the whole app. One type scale and two weights, one card style (no shadow),
colour only where it means something (the AI marks are grey, not the purple of "Mixed evidence"), page subtitles of
one short line, longer explanations in help marks, downloads as one quiet line of links, and tables that no longer
make a phone page scroll sideways."""
from __future__ import annotations

import re
from pathlib import Path

from test_app import api, home  # noqa: F401  (fixtures)
from _static import MARKER, SITE, all_css, css_blocks, index_html, release_sheets, rule

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
# 0.17.0: this release's rules are read from the cascade (tests/_static.py), not from its own sheet, so the checks
# hold when the design guide moves a rule
LIB = (STATIC / "lib.js").read_text()


def view(name: str) -> str:
    return (STATIC / "views" / f"{name}.js").read_text()


def rules(selector: str) -> str:
    """The declarations the cascade gives the rules whose selector list names `selector` exactly, as "prop: value; ..."."""
    return "; ".join(f"{k}: {v}" for k, v in rule(selector).items())


def test_the_stylesheet_is_linked_last_and_uses_the_colour_tokens_only(api):  # noqa: F811
    # site.css is still the only sheet after the marker (0.17.0: the release's own sheet is no longer linked)
    assert re.findall(r'<link rel="stylesheet" href="([^"]+)">', index_html().split(MARKER, 1)[1]) == [SITE]
    # light and dark both work: no colour of its own, only the tokens of tokens.css. 0.17.0: the whole cascade bar
    # tokens.css, except the few rules that always held a fixed colour (white text on a coloured button, the dialog's
    # backdrop, a page image's white frame, the dark theme's lightened amber)
    allowed = {".btn-danger", "a.btn-danger:hover", ".switch-track::after", ".dialog::backdrop", ".setup-step.done .n",
               ".scrim", ".dv-page-frame", ".dv-pbox-out"}
    css = "\n".join((STATIC / s.removeprefix("/static/")).read_text() for s in release_sheets() if s != "/static/tokens.css")
    for _m, sels, decls in css_blocks(css):
        if re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", " ".join(decls.values())) and not set(sels) & allowed:
            assert any("grade-partially_supports" in s or "status-partially_supported" in s for s in sels), sels
    st, body = api("GET", "/static/app.css", token=False)
    assert st == 200 and b".btn" in body
    # 0.17.0 (design guide): the sidebar's AI pills (.nav-ai-*) are gone; the groups carry the one AI mark (.ai-tag)
    assert rule(".nav-group .ai-tag")


def test_one_type_scale_and_two_weights():
    # 0.17.0 (design guide): the sizes and weights are tokens of tokens.css (--fs-*, --fw-*), named by the rules
    tokens = (STATIC / "tokens.css").read_text()
    assert "--fw-strong: 600" in tokens and "--fw-regular: 400" in tokens and "--fs-section: 1.05rem" in tokens
    assert "--fs-small: .875rem" in tokens
    assert "font-weight: var(--fw-strong)" in rules("h1") and "font-size: var(--fs-section)" in rules("h2")
    # every button in the regular weight; only the main button (and the confirming danger button) is bold
    assert "font-weight: var(--fw-regular)" in rules(".btn")
    assert "font-weight: var(--fw-strong)" in rules(".btn-primary") and "font-weight: var(--fw-strong)" in rules(".btn-danger")
    assert "font-weight: var(--fw-regular)" in rules("details.fold > summary")
    for small in ("small", ".small", ".field-help", ".btn-sm", ".badge", ".chip"):
        assert "font-size: var(--fs-small)" in rules(small), small
    # the line above a title: in sentence case and the regular weight, as on the result page
    assert "text-transform" not in rules(".fe-section") and "font-weight: var(--fw-regular)" in rules(".eyebrow")


def test_one_card_style_without_shadows():
    # 0.17.0 (design guide): cards are flat by their own rule (no shadow at all), and a card placed in a card draws no box
    for sel in (".card", ".ov-card"):
        assert "box-shadow" not in rules(sel) or "box-shadow: none" in rules(sel), sel
    assert "translate" not in rules(".ov-card:hover")
    assert "border: 0" in rules(".card .card")


def test_colour_only_where_it_means_something():
    # the AI marks were purple (--mixed), the colour of "Mixed evidence", and "No AI needed" was green. 0.17.0 (design
    # guide): one AI mark (.ai-tag), grey and without a box everywhere; the sidebar's pills are gone
    tag = rules(".ai-tag")
    assert "color: var(--muted)" in tag and "background" not in tag and "border" not in tag and "--mixed" not in tag
    assert not re.search(r"\.nav-ai(?![\w-])|\.nav-ai-", all_css())
    # states and counts are facts: grey, not the colours of the judgements
    assert "var(--ok)" not in rules(".ov-state.ov-made") and "var(--partly)" not in rules(".to-review")
    assert "border: 1px solid transparent" in rules(".badge")
    assert "var(--surface-3)" in rules(".status-uncertain")
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
    # 0.17.0 (design guide): the help mark is a small icon button, not an action drawn as a link
    assert "export function helpMark(label, text" in LIB and 'iconButton({ icon: "help", label, sm: true' in LIB and 'class: "help-mark"' in LIB
    # 0.17.0 (design guide): the help mark is a small icon button, muted by that component, on every page
    assert "color: var(--muted)" in rules(".icon-btn-sm") and rule(".help-mark")
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
    btn = src[src.index("const copyBtn = "):]
    # 0.17.0 (design guide): a download is a quiet small button (downloadButton), no longer a link-btn
    assert btn.split("\n")[0].count("downloadButton(") == 1 and "link-btn" not in btn.split("\n")[0]
    assert "Opens in a new tab, as the file was when it was added." not in src   # it is in the link's tooltip
    assert '"The text as the app reads it."' not in src


def test_a_table_that_scrolls_in_its_frame_holds_its_hidden_labels():
    # the hidden text of the line buttons (position: absolute) escaped the Search table's frame and made the whole
    # page scroll sideways at 390 px: a positioned frame clips them
    assert "position: relative" in rules(".kwic-wrap")
    for sel in (".table-wrap", ".map-wrap", ".dv-kwic"):
        assert "position: relative" in rules(sel), sel
    assert rule(".visually-hidden")["position"].startswith("absolute")


def test_the_document_pages_bibliography_line_stacks_on_a_phone():
    # wrapped as a row, the library icon could stand alone on a line and a line could begin with "·": on a phone each
    # part (the reference, the work's title, its DOI, Open in Zotero) has a line of its own beside the icon
    phone = "(max-width: 600px)"
    bib = rule(".dv-bib", media=phone)
    assert bib["display"] == "grid" and bib["grid-template-columns"] == "auto minmax(0, 1fr)"
    assert rule(".dv-bib > .sep", media=phone)["display"] == "none"
    assert rule(".dv-bib > :not(.icon):not(.sep)", media=phone)["grid-column"] == "2"
