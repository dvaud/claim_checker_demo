"""0.17.0: the design guide (docs/DESIGN.md) kept true. Each element has its look in one place (one section of
components.css, one helper in lib.js); pages place components and never restyle them; colours are tokens; actions are
buttons and places are links; the live reference (#/design) draws every helper. These read the files as text: no
browser, no network.
"""
from __future__ import annotations

import re
from pathlib import Path

from _static import STATIC, all_css, css_blocks, index_html, js_code, release_sheets, rule

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
COMPONENTS = (STATIC / "components.css").read_text(encoding="utf-8")
VIEWS = (STATIC / "views.css").read_text(encoding="utf-8")
APP = (STATIC / "app.css").read_text(encoding="utf-8")
TOKENS = (STATIC / "tokens.css").read_text(encoding="utf-8")
LIB = (STATIC / "lib.js").read_text(encoding="utf-8")
VIEW_JS = {p.name: p.read_text(encoding="utf-8") for p in sorted((STATIC / "views").glob("*.js"))}
ALL_JS = {**{p.name: p.read_text(encoding="utf-8") for p in sorted(STATIC.glob("*.js"))}, **VIEW_JS}

# the tokens of 0.17.0rc4 (tokens.css, and the drawer's width): a fork's site.css may use any of them (the promise of
# docs/EXTENDING.md: tokens are added, never renamed or removed)
RC4_TOKENS = """--accent --accent-soft --accent-strong --accent-text --bad --bad-line --bad-soft --bg --bg-2 --border --border-strong
--content-w --faint --focus --font-mono --font-serif --font-ui --heat-4 --hl-blue --hl-blue-line --hl-green --hl-green-line
--hl-pink --hl-pink-line --hl-yellow --hl-yellow-line --logdrawer-w --mark --mark-line --mixed --mixed-line --mixed-soft
--muted --none --none-line --none-soft --ok --ok-line --ok-soft --on-accent --partly --partly-line --partly-soft --radius
--radius-sm --shadow --shadow-lg --sidebar-w --surface --surface-2 --surface-3 --text --text-2 --warn --warn-soft""".split()

# what a page may set on a component: where it sits, never how it looks (docs/DESIGN.md, section 8)
PLACEMENT = re.compile(r"^(display|position|top|right|bottom|left|inset|z-index|order|flex(-[a-z]+)?|grid(-[a-z]+)*|gap|"
                       r"row-gap|column-gap|align-[a-z]+|justify-[a-z]+|place-[a-z]+|margin(-[a-z]+)?|width|min-width|"
                       r"max-width|height|min-height|max-height|overflow(-[xy])?|vertical-align|white-space|text-align|"
                       r"visibility|text-overflow|overflow-wrap|scroll-margin(-[a-z]+)*)$")
# class names that are parts or utilities, not components, though a component's section mentions them
NOT_COMPONENTS = {"icon", "small", "muted", "mono", "serif", "count", "title", "page", "pn", "num", "actions", "spacer",
                  "current", "grow", "it", "sep", "msg", "elapsed", "spinner", "passage"}


def _sections():
    """components.css as {heading: text}, in order."""
    parts = re.split(r"^/\* ==== (.+?) \*/\s*$", COMPONENTS, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def _subject(selector: str) -> set[str]:
    s = re.sub(r":(not|has|is|where)\([^)]*\)", "", selector)
    last = re.split(r"[\s>+~]+", s.strip())[-1]
    return set(re.findall(r"\.([\w-]+)", last))


def _component_classes() -> dict[str, set[str]]:
    """{class: the sections that give it a look}. A section may place another component inside itself (a button's
    margin in the drawer's foot); only a rule that sets more than placement counts as styling the class."""
    out: dict[str, set[str]] = {}
    for head, text in _sections().items():
        for _m, sels, decls in css_blocks(text):
            if all(PLACEMENT.match(k) for k in decls):
                continue
            for sel in sels:
                for c in _subject(sel) - NOT_COMPONENTS:
                    out.setdefault(c, set()).add(head)
    return out


def test_the_sheets_are_four_and_site_css_comes_last():
    assert release_sheets() == ["/static/tokens.css", "/static/app.css", "/static/components.css", "/static/views.css"]
    after = re.findall(r'<link rel="stylesheet" href="([^"]+)">', index_html().split("<!-- release stylesheets end -->", 1)[1])
    assert after == ["/static/site.css"]
    # every per-release stylesheet is folded in and gone
    left = sorted(p.name for p in STATIC.glob("*.css"))
    assert left == ["app.css", "components.css", "site.css", "tokens.css", "views.css"], left


def test_every_section_of_components_css_is_a_section_of_the_guide():
    heads = list(_sections())
    assert len(heads) >= 25
    for head in heads:
        num, name = head.split(" ", 1)
        assert re.search(rf"^### {re.escape(num)} {re.escape(name)}\s*$", GUIDE, flags=re.M), f"no '### {head}' in docs/DESIGN.md"
    nums = [tuple(int(x) for x in h.split(" ")[0].split(".")) for h in heads]
    assert nums == sorted(nums), "the sections follow the guide's order"


def test_a_component_is_styled_in_one_section_only():
    twice = {c: s for c, s in _component_classes().items() if len(s) > 1}
    assert not twice, twice


# every helper of lib.js that draws a component and takes a page's class (docs/DESIGN.md 4: "a page's own class for
# placement"); a page may import one under another name (card as cardBox)
COMPONENT_HELPERS = {"button", "iconButton", "downloadButton", "fileButton", "link", "tag", "notice", "card", "fold",
                     "choice", "optionCards", "input", "select", "textarea", "searchField", "menu", "drawer", "statusBadge",
                     "personMark", "listRow", "listGroup",
                     "keptFold"}   # views/result.js's fold whose open state survives a redraw: keptFold(key, { class }, …)


def _calls(js: str, name: str):
    """The text of each object literal passed first to name(…): from its "{" to the matching "}" (strings skipped)."""
    for m in re.finditer(rf"(?<![\w.]){re.escape(name)}\(\s*(?:`[^`]*`\s*,\s*|\"[^\"]*\"\s*,\s*)?\{{", js):
        i, depth, quote = m.end() - 1, 0, None
        for j in range(i, len(js)):
            ch = js[j]
            if quote:
                if ch == "\\":
                    continue
                if ch == quote and js[j - 1] != "\\":
                    quote = None
            elif ch in "\"'`":
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield js[i:j + 1]
                    break


def _helper_names(js: str) -> set[str]:
    """The names this file calls the component helpers by, its import aliases included."""
    names = set(COMPONENT_HELPERS)
    for imp in re.findall(r"import\s*\{([^}]*)\}\s*from\s*\"\.\.?/(?:\.\./)?lib\.js\"", js):
        for alias in re.findall(r"\b(\w+)\s+as\s+(\w+)", imp):
            if alias[0] in COMPONENT_HELPERS:
                names.add(alias[1])
    return names


def _classes_given(obj: str) -> set[str]:
    """The classes an object literal passed to a helper names in its `class:`, at the object's top level only (nested
    objects and arrow bodies left out), whatever comes before it."""
    flat, depth = [], 0
    for ch in re.sub(r"\$\{[^{}]*\}", " ", obj)[1:-1]:
        depth += ch == "{"
        if depth == 0:
            flat.append(ch)
        depth -= ch == "}"
    out: set[str] = set()
    for m in re.finditer(r"\bclass:\s*(`[^`]*`|\"[^\"]*\"|'[^']*'|[^,]+)", "".join(flat)):
        out |= set(re.findall(r"[\"'`]([^\"'`]*)[\"'`]", m.group(1)) and
                   " ".join(re.findall(r"[\"'`]([^\"'`]*)[\"'`]", re.sub(r"\$\{[^}]*\}", " ", m.group(1)))).split())
    return out


def _placement_hooks() -> set[str]:
    """The page's own classes given to a component through its helper (button({ class: "agree-btn" })): they may only
    place it. Every class passed to a helper's `class:`, at the object's top level, whatever comes before it."""
    out: set[str] = set()
    for js in ALL_JS.values():
        for name in _helper_names(js):
            for obj in _calls(js, name):
                out |= _classes_given(obj)
        # a class added later to an element a helper made (moreBtn.classList.add("more-toggle"))
        for m in re.finditer(r"(\w+)\s*=\s*(?:button|iconButton|link|tag|card|notice|panelToggle)\(", js):
            out |= set(re.findall(rf"\b{m.group(1)}\.classList\.add\(\"([\w-]+)\"\)", js))
    return {c for c in out if re.fullmatch(r"[a-z][\w-]*", c)} - NOT_COMPONENTS


def test_pages_place_components_and_never_restyle_them():
    """In views.css a component's class, or a page's class given to a component through its helper, gets only its
    place. A rule that reaches into a component (`.also-read > summary`, the summary of a fold) counts as styling it."""
    comps = set(_component_classes()) | _placement_hooks()
    bad = []
    for media, sels, decls in css_blocks(VIEWS):
        look = [k for k in decls if not PLACEMENT.match(k)]
        if not look:
            continue
        for sel in sels:
            subject = _subject(sel)
            hit = subject & comps
            last = re.split(r"[\s>+~]+", sel.strip())[-1]
            if not subject and re.match(r"^(summary|a|h[1-4]|svg|button|input|textarea|select)\b", last):
                # a component's own part (a fold's summary, a card's title, an icon), reached through it, is its look
                parts = [x for x in re.split(r"[\s>+~]+", re.sub(r":(not|has|is|where)\([^)]*\)", "", sel).strip()) if "." in x]
                hit = set(re.findall(r"\.([\w-]+)", parts[-1])) & comps if parts else set()
            if hit:
                bad.append(f"{media} {sel} ({', '.join(sorted(hit))}): {', '.join(look)}")
    assert not bad, "\n".join(bad)


# buttons that hold an icon or a colour and no words: they have a size of their own
_NO_WORDS = {"icon-btn", "icon-btn-sm", "hl-swatch"}


def _button_classes() -> set[str]:
    """Every class a button can carry: the Buttons component's own, the classes a script gives a button through its
    helper (also added later with classList.add), and the classes of the buttons made by hand or in index.html."""
    out = {"btn", "btn-primary", "btn-ghost", "btn-danger", "btn-outline-danger", "btn-sm", "btn-toggle", "btn-opens",
           "btn-wrap", "seg-btn", "link-jump", "menu-item"}
    makers = {"button", "downloadButton", "fileButton", "drawerButton"}
    for js in ALL_JS.values():
        names = makers | {alias for own, alias in re.findall(r"\b(\w+)\s+as\s+(\w+)", js) if own in makers}
        for name in names:
            for obj in _calls(js, name):
                out |= _classes_given(obj)
        for m in re.finditer(r"(\w+)\s*=\s*(?:" + "|".join(sorted(names)) + r"|panelToggle)\(", js):
            out |= set(re.findall(rf"\b{m.group(1)}\.classList\.add\(\"([\w-]+)\"\)", js))
        for m in re.finditer(r"""h\("button",\s*\{[^}]*?class:\s*([`"'])(.*?)\1""", js):
            out |= set(re.sub(r"\$\{[^}]*\}", " ", m.group(2)).split())
    for classes in re.findall(r'<button[^>]*class="([^"]*)"', index_html()):
        out |= set(classes.split())
    return {c for c in out if re.fullmatch(r"[a-z][\w-]*", c)} - NOT_COMPONENTS


def _buttons_fixed_to_a_width(css: str, classes: set[str]) -> list[str]:
    """The rules of `css` that give a button a width as a length (`width: 9rem`): its words can then be wider than it."""
    length = re.compile(r"-?[\d.]+(px|rem|em|ch|vw)|calc\(.*\)|(min|max|clamp)\((?![^)]*%).*\)")
    bad = []
    for media, sels, decls in css_blocks(css):
        width = decls.get("width", "")
        if not length.fullmatch(width):
            continue
        for sel in sels:
            last = re.split(r"[\s>+~]+", sel.strip())[-1]
            if "::" in last or _subject(sel) & _NO_WORDS:
                continue
            if _subject(sel) & classes or re.match(r"^button\b", last):
                bad.append(f"{media} {sel}: width {width}".strip())
    return bad


def test_no_button_is_fixed_to_a_width():
    """docs/DESIGN.md 4.1: a button is as wide as its words and padding need. Where a row keeps its buttons in the
    same place on every card, each has a min-width for its longest label, never a width: a fixed one clips a longer
    label (Judge differently…, in a slot of 9rem, lost its padding). Icon buttons and colour swatches hold no words."""
    classes = _button_classes()
    assert {"agree-btn", "dismiss-btn", "judge-toggle", "next-review", "code-btn", "access-why", "bib-chosen-chip"} <= classes
    bad = _buttons_fixed_to_a_width(COMPONENTS, classes) + _buttons_fixed_to_a_width(VIEWS, classes)
    assert not bad, "\n".join(bad)
    # the rule that clipped it is seen, and a slot as a min-width is not
    assert _buttons_fixed_to_a_width(".result .judge-row .judge-toggle { width: 9rem; justify-content: center; }", classes) == \
        [".result .judge-row .judge-toggle: width 9rem"]
    assert _buttons_fixed_to_a_width(".result .judge-row .judge-toggle { min-width: 11rem; } .code-btn { width: 100%; } "
                                     ".icon-btn { width: 32px; } .result .judge-row > .slot-gap { width: 7.5rem; }", classes) == []
    # the judging row's slots hold their longest labels
    assert rule(".result .judge-row .judge-toggle").get("min-width") == "11rem"
    assert rule(".result .judge-row .agree-btn").get("min-width") == "6.5rem"
    assert rule(".result .judge-row .dismiss-btn").get("min-width") == "7.5rem"


def test_the_placement_hooks_are_found():
    # the guard above reads every class a page passes to a helper, through import aliases and after nested objects
    hooks = _placement_hooks()
    assert {"ex-table-card", "answer", "part-card", "also-read", "agree-btn"} & hooks or not hooks
    assert "map-doc-dl" in hooks and "next-review" in hooks


def test_pages_never_restyle_a_link():
    # a link's colour, underline and weight are the Links component's (and the title link's serif comes with it)
    for media, sels, decls in css_blocks(VIEWS):
        for sel in sels:
            last = re.split(r"[\s>+~]+", sel.strip())[-1]
            if re.match(r"^a(\b|:|\[|$)", last):
                bad = {"color", "text-decoration", "font-weight", "font-family"} & set(decls)
                assert not bad, f"{media} {sel}: {bad}"


def test_app_css_holds_no_component():
    comps = set(_component_classes())
    for _m, sels, decls in css_blocks(APP):
        for sel in sels:
            if _subject(sel) & comps:   # the page frame may place a component (a card's margin in .view), nothing more
                assert all(PLACEMENT.match(k) for k in decls), sel


def test_colours_are_tokens_and_themes_live_in_tokens_css():
    for name, text in (("app.css", APP), ("components.css", COMPONENTS), ("views.css", VIEWS)):
        css = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css), f"a colour outside the tokens in {name}"
        assert "prefers-color-scheme" not in css and "data-theme" not in css, f"a theme rule in {name}"
        assert not re.findall(r"(?<![\w-])(--[a-z0-9-]+)\s*:", css) or name == "views.css" and \
            set(re.findall(r"(?<![\w-])(--[a-z0-9-]+)\s*:", css)) <= {"--swatch"}, f"{name} sets a token"


def test_type_is_set_from_the_scale_only():
    """docs/DESIGN.md 3.2: every size and weight is a token of the type scale (--fs-*, --fw-*). Only code and keys, set
    inside running text, take a size relative to it (em)."""
    scale = set(re.findall(r"(--fs-[a-z-]+)\s*:", TOKENS))
    assert {"--fs-display", "--fs-title", "--fs-lead", "--fs-section", "--fs-body", "--fs-doc", "--fs-small", "--fs-xs",
            "--fs-label", "--fs-title-sm"} <= scale
    for name, text in (("app.css", APP), ("components.css", COMPONENTS), ("views.css", VIEWS)):
        for _m, sels, decls in css_blocks(text):
            size, weight = decls.get("font-size"), decls.get("font-weight")
            if size and size not in ("inherit", "1em") and not size.endswith("em") or size and size.endswith("rem"):
                assert re.fullmatch(r"var\(--fs-[a-z-]+\)", size), f"{name} {sels}: font-size {size}"
            if weight:
                assert weight in ("var(--fw-regular)", "var(--fw-strong)", "inherit"), f"{name} {sels}: font-weight {weight}"


def test_every_token_of_the_last_release_is_still_defined():
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", re.sub(r"/\*.*?\*/", "", TOKENS, flags=re.S)))
    missing = [t for t in RC4_TOKENS if t not in defined]
    assert not missing, missing
    used = set(re.findall(r"var\((--[a-z0-9-]+)", all_css()))
    assert used <= defined | {"--swatch"}, used - defined


def test_no_inline_visual_styles():
    visual = re.compile(r"style:\s*\{[^}]*\b(color|background|font\w*|border\w*|padding\w*|borderRadius|boxShadow|textDecoration)\s*:")
    for name, js in ALL_JS.items():
        assert not visual.search(js), f"an inline visual style in {name}: {visual.search(js).group(0)}"


def test_inline_styles_hold_only_values_computed_at_run_time():
    """docs/DESIGN.md 9.2 rule 3: a page's spacing is a class of its block in views.css; `style: {…}` only carries a
    value computed while the page runs (a bar's width from a count, a position from a measurement)."""
    fixed = re.compile(r"style:\s*\{(\s*\w+:\s*(?:\"[^\"`$]*\"|'[^'`$]*'|-?\d+(?:\.\d+)?)\s*,?)+\s*\}")
    bad = [f"views/{n}: {m.group(0)}" for n, js in VIEW_JS.items() if n != "design.js" for m in fixed.finditer(js)
           if "visibility" not in m.group(0)]   # a hidden copy used only to measure
    assert not bad, "\n".join(bad)


# the classes a page must never spell: they are made by the helpers of lib.js (docs/DESIGN.md, section 8.5)
SPELLED = re.compile(r"""class:\s*[`"']([^`"']*)[`"']""")
HELPER_CLASSES = {"btn", "btn-primary", "btn-ghost", "btn-danger", "btn-outline-danger", "btn-sm", "btn-lg", "link-btn",
                  "danger-link", "icon-btn", "chip", "chip-code", "warn-chip", "chip-btn", "badge", "badge-accent",
                  "badge-warn", "notice", "notice-info", "notice-ok", "notice-warn", "notice-error", "card", "seg-on",
                  "fold", "menu-item", "menu-list", "input", "select", "textarea", "link-title", "link-next", "link-back",
                  "link-external", "link-jump", "card-sm", "fold-sm", "empty", "seg", "seg-btn", "option-card", "option-cards",
                  "badge", "work-state", "ai-where", "ai-tag", "chip-count", "person-mark", "search-field", "drawer"}


def test_pages_use_the_helpers_instead_of_spelling_component_classes():
    bad = []
    for name, js in VIEW_JS.items():
        for m in SPELLED.finditer(js):
            words = set(re.sub(r"\$\{[^}]*\}", " ", m.group(1)).split())
            if words & HELPER_CLASSES:
                line = js.count("\n", 0, m.start()) + 1
                bad.append(f"views/{name}:{line}: {m.group(0)}")
    assert not bad, "\n".join(bad)


def test_no_action_is_drawn_as_a_link_and_no_link_as_a_button():
    css = all_css()
    for gone in (".link-btn", ".danger-link", ".btn-lg", ".seg-on", ".chip-btn"):
        assert not re.search(re.escape(gone) + r"(?![\w-])", css), gone
    for name, js in ALL_JS.items():
        for gone in ("link-btn", "danger-link", "btn-lg"):
            assert not re.search(rf"(?<![\w-]){gone}(?![\w-])", js), f"{gone} in {name}"
        # an <a> with a button's class: only a download, made by downloadButton() (it makes a file: an action)
        for m in re.finditer(r'h\("a",\s*\{[^}]*class:\s*[`"\']([^`"\']*)', js):
            assert "btn" not in m.group(1).split(), f"a link drawn as a button in {name}: {m.group(0)}"
    dl = LIB[LIB.index("export function downloadButton("):LIB.index("export function fileButton(")]
    assert 'h("a", withClass(cls, { href: o.href, download: ""' in dl


def test_a_next_step_has_an_address_and_stepping_through_a_page_is_a_button():
    """docs/DESIGN.md 4.3 and 6: a next-step link goes to the page where the work is done, so it always has an
    address; link() draws a <button> as a link only for a move on the page (kind "jump"). What steps through a page's
    own content and changes the page as it goes (Next to review: it switches the evidence to cards and opens folds)
    is a button: the result page's main one."""
    assert not re.search(r"button\.link-next(?![\w-])", all_css())
    fn = LIB[LIB.index("export function link("):LIB.index("export function tag(")]
    assert fn.count('h("button"') == 1 and 'if (kind === "jump") return h("button"' in fn
    seen = 0
    for name, js in ALL_JS.items():
        for helper in _helper_names(js) & ({"link"} | set(re.findall(r"\blink\s+as\s+(\w+)", js))):
            for obj in _calls(js, helper):
                if re.search(r'\bkind:\s*"next"', obj):
                    seen += 1
                    assert re.search(r"\bhref\b", obj), f"a next-step link without an address in {name}: {obj[:90]}"
    assert seen >= 10
    result = VIEW_JS["result.js"]
    assert 'button({ kind: "main", class: "next-review", onClick: nextToReview' in result
    assert 'button({ sm: true, onClick: () => nextToReview({ quiet: true }) }' in result
    assert not re.search(r"\blink\(\{[^}]*nextToReview", result)


# the classes 0.17.0 removed (named in CHANGELOG.md for forks): a look merged into a component, so none may come back,
# neither styled nor spelled in the JavaScript
REMOVED_CLASSES = """link-btn danger-link btn-lg seg-on chip-btn seg-pick seg-choice so-seg nav-ai nav-ai-uses nav-ai-optional
nav-legend badge-accent badge-warn badge-provisional badge-job status-prefix chip-weak chip-counted chip-yours chip-scope
chip-second chip-agrees chip-disagrees chip-flag chip-wait-you new-badge access-option route-card rc-badge cb-start-opt
note-pick-item ps-item ps-sep logdrawer-seg logdrawer-entry logdrawer-entry-link card-verdict person-mark-partly bc-sup
bc-part bc-ref map-key-doc ev-words""".split()


def test_the_removed_classes_stay_gone():
    code = all_css() + "".join(ALL_JS.values()) + index_html()
    left = [c for c in REMOVED_CLASSES if re.search(r"(?<![\w-])" + re.escape(c) + r"(?![\w-])", code)]
    assert not left, f"classes the guide removed are back: {left}"


def test_states_are_attributes_not_classes():
    # the open drawer and the chosen option are attributes (body[data-drawer], aria-checked/aria-pressed)
    css = all_css()
    assert 'body[data-drawer="open"]' in css and ".logdrawer-open" not in css
    assert '.seg-btn[aria-checked="true"]' in css and "is-active" not in css


def test_every_helper_is_on_the_reference_page():
    ref = VIEW_JS["design.js"]
    helpers = ["button", "downloadButton", "fileButton", "iconButton", "link", "tag", "notice", "card", "fold", "choice",
               "optionCards", "input", "select", "textarea", "searchField", "menu", "workState", "aiWhere", "drawer",
               "drawerButton", "field", "switchControl", "rangeControl", "spinner", "emptyState", "statusBadge", "gradeBadge",
               "codeChip", "pageHead", "downloadLinks", "helpMark", "popNote", "toast", "dialog", "confirmDialog", "heatCell",
               "strongerMark", "aiTag", "viewTabs", "featureEyebrow", "personMark", "reviewedMark", "severityTag", "compare",
               "shareState", "absentDocument", "listRow", "listGroup", "noticeList"]
    for name in helpers:
        assert re.search(rf"export function {name}\(", LIB + (STATIC / "features.js").read_text(encoding="utf-8")), name
        assert re.search(rf"\b{name}\(", ref), f"{name} is not drawn on the reference page (views/design.js)"
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'renderDesign' in app and '[/^\\/design$/, "", renderDesign]' in app
    # unlisted: not a place of the sidebar, not a row of Find
    assert "#/design" not in index_html() and "#/design" not in (STATIC / "finder-index.js").read_text(encoding="utf-8")


def test_the_reference_page_follows_the_guide_section_by_section():
    """#/design has one section per section of the guide, under the guide's number and title and in the guide's order:
    a reviewer with the guide open at 4.12 finds 4.12 on the page. Every element (4.x) and every piece of the
    navigation (5.x) is there; of the identity (3.x), the sections that can be drawn."""
    ref = VIEW_JS["design.js"]
    shown = re.findall(r'\bsection\("(\d+\.\d+)",\s*"([^"]+)"', ref)
    guide = re.findall(r"^### (\d+\.\d+) (.+?)\s*$", GUIDE, flags=re.M)
    assert shown and "`${num} ${title}`" in ref, "views/design.js draws each section with section(number, title, …)"
    titles = dict(guide)
    for num, title in shown:
        assert titles.get(num) == title, f"#/design has {num} {title!r}; the guide has {titles.get(num)!r}"
    order = [n for n, _ in guide]
    nums = [n for n, _ in shown]
    assert nums == [n for n in order if n in nums], "the sections of #/design are in the guide's order, each once"
    missing = [n for n in order if n.startswith(("4.", "5.")) and n not in nums]
    assert not missing, f"sections of the guide that #/design does not show: {missing}"
    assert {"3.1", "3.2"} <= set(nums)   # the colour tokens and the type scale
    # no sample leads away from the page: its links point at the page itself (or outside the app), and the view tabs
    # it shows are a sample (a click stays), not tabs of its own
    hrefs = set(re.findall(r"\bhref:\s*([^,}\s]+)", ref))
    assert hrefs and all(x == "HERE" or x.startswith('"https://') for x in hrefs), hrefs
    assert 'tabsDemo.addEventListener("click"' in ref and "tabsDemo" not in ref[ref.index("page.append("):]


def test_the_guide_names_only_what_exists():
    # every helper the guide's table of helpers names exists, and every file it names is there
    for name in set(re.findall(r"`([a-zA-Z]+)\(\)`", GUIDE)):
        assert re.search(rf"(export )?(async )?function {name}\(|const {name} = ", LIB + "".join(ALL_JS.values())), name
    for f in set(re.findall(r"`((?:views/)?[a-z-]+\.(?:css|js))`", GUIDE)):
        assert (STATIC / f).exists() or (ROOT / f).exists(), f
    for c in set(re.findall(r"`\.([a-z][\w-]+)`", GUIDE)):
        assert re.search(rf"\.{re.escape(c)}(?![\w-])", all_css()), f".{c} is named in the guide but styled nowhere"


# ---- a helper's name stays the helper's --------------------------------------------------------------------------------
# The pages import the helpers by name (fold, card, link, tag…). A page that once had a local of the same name (a `fold`
# object, a `card` element) and renamed it must rename every use: a use left behind now reads the imported function, and
# `fold.kinds` fails only when that line runs. These tests read the scripts as text, so this guard reads the names.

_NOT_PARAMETERS = {"if", "for", "while", "switch", "catch", "with", "function", "return", "typeof", "await", "new"}
_OF_A_FUNCTION = {"call", "apply", "bind", "name", "length"}   # what any function has: fold.call(…) is no slip


def _exported_functions() -> set[str]:
    """Every function a script of the app exports: the helpers of lib.js and features.js, and the pages' own."""
    out: set[str] = set()
    for js in ALL_JS.values():
        code = js_code(js)
        out |= set(re.findall(r"^export\s+(?:async\s+)?function\s*\*?\s*([\w$]+)", code, flags=re.M))
        out |= set(re.findall(r"^export\s+const\s+([\w$]+)\s*=\s*(?:async\s+)?(?:function\b|\([^()]*\)\s*=>|[\w$]+\s*=>)",
                              code, flags=re.M))
    return out


def _imported_functions(code: str, functions: set[str]) -> set[str]:
    """The names this script knows imported functions by (`card as cardBox` gives cardBox)."""
    names: set[str] = set()
    for clause in re.findall(r"\bimport\s*\{([^}]*)\}\s*from\b", code):
        for part in clause.split(","):
            words = part.split()
            if words and words[0] in functions:
                names.add(words[-1])
    return names


def _brackets(code: str) -> tuple[dict[int, int], list[int], list[int]]:
    """The script's brackets paired (each position to its partner), and its blocks: for each character the innermost
    {…} it is in (0: the script itself; a brace belongs to the block it opens or closes), and each block's parent."""
    pair: dict[int, int] = {}
    open_at: list[int] = []
    block_of, parent, blocks = [0] * len(code), [0], [0]
    for i, ch in enumerate(code):
        if ch == "{":
            parent.append(blocks[-1])
            blocks.append(len(parent) - 1)
        block_of[i] = blocks[-1]
        if ch in "([{":
            open_at.append(i)
        elif ch in ")]}":
            assert open_at and code[open_at[-1]] + ch in ("()", "[]", "{}"), f"brackets do not pair at character {i}"
            j = open_at.pop()
            pair[i], pair[j] = j, i
            if ch == "}":
                blocks.pop()
    assert not open_at, "a bracket is never closed"
    return pair, block_of, parent


def _bound_names(text: str) -> list[str]:
    """The names a parameter list or a destructuring pattern binds: `a, { b, c: d }, [e] = [], ...rest` binds a, b, d,
    e and rest (a key before ":" and a default after "=" bind nothing)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "=":                          # a default value: on to the next "," or closing bracket of this level
            depth, i = 0, i + 1
            while i < n and not (depth == 0 and text[i] in ",)]}"):
                depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(text[i], 0)
                i += 1
        elif c.isalpha() or c in "_$":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            key = re.match(r"\s*:", text[j:]) is not None
            member = i > 0 and text[i - 1] == "." and text[max(0, i - 3):i] != "..."
            if not key and not member:
                out.append(text[i:j])
            i = j
        else:
            i += 1
    return out


def _declarations(code: str, pair: dict[int, int]) -> list[tuple[str, int]]:
    """Every local name the script declares, each with a position inside the block it holds in: const, let and var
    (lists and destructuring too), functions, and the parameters of functions, arrow functions, methods and catch,
    which hold in the function's body (or, for an arrow function without braces, in the block around it)."""
    out: list[tuple[str, int]] = []
    n = len(code)

    def body(i: int, otherwise: int) -> int:
        m = re.compile(r"\s*(?:=>\s*)?\{").match(code, i)
        return m.end() - 1 if m else otherwise

    for m in re.finditer(r"\b(?:const|let|var)\b", code):
        i = m.end()
        while i < n:
            while i < n and code[i] in " \t\r\n":
                i += 1
            if i >= n:
                break
            if code[i] in "[{":
                out += [(name, m.start()) for name in _bound_names(code[i + 1:pair[i]])]
                i = pair[i] + 1
            else:
                word = re.compile(r"[\w$]+").match(code, i)
                if not word:
                    break
                out.append((word.group(0), m.start()))
                i = word.end()
            while i < n and code[i] not in ",;)]}":   # past its first value, to the next name or the statement's end
                i = pair[i] + 1 if code[i] in "([{" else i + 1
            if i >= n or code[i] != ",":
                break
            i += 1
    for m in re.finditer(r"\bfunction\b\s*\*?\s*([\w$]*)\s*\(", code):
        end = pair[m.end() - 1]
        if m.group(1):
            out.append((m.group(1), m.start()))
        out += [(name, body(end + 1, m.start())) for name in _bound_names(code[m.end():end])]
    for m in re.finditer(r"=>", code):
        k = m.start() - 1
        while k >= 0 and code[k] in " \t\r\n":
            k -= 1
        at = body(m.start(), m.start())
        if k >= 0 and code[k] == ")":
            out += [(name, at) for name in _bound_names(code[pair[k] + 1:k])]
        else:
            a = k
            while a >= 0 and (code[a].isalnum() or code[a] in "_$"):
                a -= 1
            if a < k:
                out.append((code[a + 1:k + 1], at))
    for m in re.finditer(r"(?<![\w$.])([\w$]+)\s*\(", code):      # a method: name(parameters) {
        if m.group(1) in _NOT_PARAMETERS:
            continue
        end = pair[m.end() - 1]
        brace = re.compile(r"\s*\{").match(code, end + 1)
        if brace:
            out += [(name, brace.end() - 1) for name in _bound_names(code[m.end():end])]
    for m in re.finditer(r"\bcatch\s*\(\s*([\w$]+)\s*\)\s*\{", code):
        out.append((m.group(1), m.end() - 1))
    return out


def helpers_used_as_objects(js: str, functions: set[str]) -> list[str]:
    """Each place where `js` uses an imported function as an object (`fold.kinds`, `...card.rows`, `link[0]`) and no
    local of that name holds there: "line 631: fold.kinds". A local declared in the same block, or in a block around
    it, makes the name the local's; one declared in another function does not."""
    code = js_code(js)
    pair, block_of, parent = _brackets(code)
    declared: dict[str, set[int]] = {}
    for name, at in _declarations(code, pair):
        declared.setdefault(name, set()).add(block_of[at])
    found = []
    for name in sorted(_imported_functions(code, functions)):
        use = re.compile(rf"(?:(?<![\w$.])|(?<=\.\.\.)){re.escape(name)}\s*(?:\?\.|\.(?!\.)|\[)\s*([\w$]*)")
        for m in use.finditer(code):
            if m.group(1) in _OF_A_FUNCTION:
                continue
            block, around = block_of[m.start()], set()
            while True:
                around.add(block)
                if block == 0:
                    break
                block = parent[block]
            if not around & declared.get(name, set()):
                found.append(f"line {code.count(chr(10), 0, m.start()) + 1}: {' '.join(m.group(0).split())}")
    return found


def test_an_imported_helper_is_never_used_as_an_object():
    """docs/DESIGN.md 9.2, rule 4: the pages use the helpers by name. A local a page renamed leaves no use behind that
    now reads the helper (`fold.kinds` on a document's page: the page showed an error instead of the document)."""
    functions = _exported_functions()
    assert {"fold", "card", "link", "tag", "button", "notice", "choice", "h", "icon", "replace"} <= functions
    bad = [f"{name}: {where}" for name, js in ALL_JS.items() for where in helpers_used_as_objects(js, functions)]
    assert not bad, "an imported helper used as an object, with no local of its name there:\n" + "\n".join(bad)


def test_the_guard_sees_a_use_left_behind_by_a_rename():
    # the slip itself: the local `fold` became `leftFold` when the helper fold() was imported, and one use kept the old name
    functions = _exported_functions()
    slip = """import { h, icon, replace, fold } from "../lib.js";
export function renderDocument(view, blocks) {
  let leftFold = null, lastPage = null;
  function place(b, row) {
    if (!leftFold) leftFold = { el: h("details", { class: "dv-fold" }), kinds: new Map() };   // fold.kinds in a comment
    leftFold.kinds.set(b.kind, (leftFold.kinds.get(b.kind) || 0) + 1);
    replace(leftFold.sum, icon("chevron-right"), h("span", {}, `Left out: ${[...fold.kinds].map(([k, n]) => `${n} ${k}`).join(", ")}`));
  }
  view.appendChild(fold({ class: "section" }, "More", "fold.kinds in a string"));
}
"""
    assert helpers_used_as_objects(slip, functions) == ["line 7: fold.kinds"]
    # a local of that name in another function does not excuse it; one in the same function, or around it, does
    elsewhere = slip.replace("  view.appendChild(", "  const open = (row) => { const fold = row.closest(\"details\"); if (fold) fold.open = true; };\n  view.appendChild(")
    assert helpers_used_as_objects(elsewhere, functions) == ["line 7: fold.kinds"]
    for own in ("  function place(b, row) {\n    const fold = leftFold || { kinds: new Map() };",   # in the same function
                "  function place(b, row, fold) {",                                                # a parameter
                "  let fold = null;\n  function place(b, row) {"):                                  # in the function around
        assert helpers_used_as_objects(slip.replace("  function place(b, row) {", own), functions) == [], own
    # an import under another name is followed, and what every function has is no slip
    alias = 'import { card as cardBox } from "../lib.js";\nconst f = () => { const card = cardBox({}); card.appendChild(x); return cardBox.name; };\n'
    assert helpers_used_as_objects(alias, functions) == []
    assert helpers_used_as_objects(alias.replace("card.appendChild", "cardBox.appendChild"), functions) == ["line 2: cardBox.appendChild"]
