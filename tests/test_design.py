"""0.17.0: the design guide (docs/DESIGN.md) kept true. Each element has its look in one place (one section of
components.css, one helper in lib.js); pages place components and never restyle them; colours are tokens; actions are
buttons and places are links; the live reference (#/design) draws every helper. These read the files as text: no
browser, no network.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

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
                       r"visibility|text-overflow|overflow-wrap|overscroll-behavior(-[xy])?|scroll-margin(-[a-z]+)*)$")
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
                     "personMark", "listRow", "listGroup", "inset", "stopButton", "switchControl", "absentDocument",
                     "field", "helpMark", "downloadLinks", "pageHead", "tabs", "strongerMark",
                     # the AI line: its attributes come after its sentence, aiWhere(text, where, { class })
                     "aiWhere", "readsLine",
                     "keptFold"}   # views/result.js's fold whose open state survives a redraw: keptFold(key, { class }, …)


def _option_objects(js: str, name: str):
    """Every object literal passed to name(…) at the call's top level, in any position (aiWhere(text, "cloud",
    { class }) as well as button({ class }, …)). Strings are skipped while matching brackets."""
    for m in re.finditer(rf"(?<![\w.]){re.escape(name)}\(", js):
        depth, quote, start = 0, None, None
        for j in range(m.end() - 1, len(js)):
            ch = js[j]
            if quote:
                if ch == quote and js[j - 1] != "\\":
                    quote = None
                continue
            if ch in "\"'`":
                quote = ch
            elif ch in "([{":
                depth += 1
                if ch == "{" and depth == 2:
                    start = j
            elif ch in ")]}":
                depth -= 1
                if ch == "}" and depth == 1 and start is not None:
                    yield js[start:j + 1]
                    start = None
                if depth == 0:
                    break


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
            for obj in _option_objects(js, name):
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
    makers = {"button", "downloadButton", "fileButton", "drawerButton", "teamLine"}
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
    assert {"agree-btn", "dismiss-btn", "judge-toggle", "next-review", "code-btn", "doc-why", "bib-chosen-chip"} <= classes
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
                bad = {"color", "text-decoration", "font-weight", "font-family", "font-style"} & set(decls)
                assert not bad, f"{media} {sel}: {bad}"


def title_link_classes(scripts: dict[str, str]) -> set[str]:
    """The classes the scripts give to title links (link({ kind: "title", class: … }))."""
    out: set[str] = set()
    for js in scripts.values():
        for name in _helper_names(js) & ({"link"} | set(re.findall(r"\blink\s+as\s+(\w+)", js))):
            for obj in _calls(js, name):
                if re.search(r'\bkind:\s*"title"', obj):
                    out |= _classes_given(obj) | {c for c in re.findall(r'\bclass:\s*"([^"]*)"', obj) for c in c.split()}
    return out


def colours_on_title_links(css: str, classes: set[str]) -> list[str]:
    """Rules that set a colour on an element that may be a title link: their subject names a class some title link
    has, and is not some other element (span.title)."""
    bad = []
    for media, sels, decls in css_blocks(css):
        if "color" not in decls:
            continue
        for sel in sels:
            last = re.split(r"[\s>+~]+", re.sub(r":(not|has|is|where)\([^)]*\)", "", sel).strip())[-1]
            if re.match(r"^[a-z]", last) and not last.startswith("a"):
                continue
            if set(re.findall(r"\.([\w-]+)", last)) & classes:
                bad.append(f"{media} {sel}: color {decls['color']}".strip())
    return bad


def test_a_title_link_keeps_its_colour():
    """docs/DESIGN.md 4.3: a name that opens its item is teal at rest. A rule that colours a class some title link
    carries (`.ev-src .title { color: var(--text) }` painted a theme's documents in the text colour) is caught."""
    classes = title_link_classes(ALL_JS)
    assert "ct-wording" in classes
    bad = colours_on_title_links(COMPONENTS, classes) + colours_on_title_links(VIEWS, classes)
    assert not bad, "\n".join(bad)
    assert colours_on_title_links(".ev-src .title { color: var(--text); }", {"title"}) == [".ev-src .title: color var(--text)"]
    assert colours_on_title_links(".ev-src span.title { color: var(--text); }", {"title"}) == []


# the space between elements on a page (docs/DESIGN.md 3.3): the six steps (--space-*), and 6, 2 and 1 px for small
# things on a line and hairline nudges; a length relative to the text (em) or the window (vh) is allowed
SPACE_PX = {0, 1, 2, 4, 6, 8, 12, 16, 24, 32}


def spaces_off_the_scale(css: str) -> list[str]:
    bad = []
    for media, sels, decls in css_blocks(css):
        for k, v in decls.items():
            if not re.match(r"^(margin(-[a-z]+)?|gap|row-gap|column-gap)$", k):
                continue
            for num, unit in re.findall(r"(?<![\w(*-])-?([\d.]+)(px|rem)\b", re.sub(r"calc\([^;]*\)|var\([^)]*\)", " ", v)):
                if unit == "rem" or float(num) not in SPACE_PX:
                    bad.append(f"{media} {sels[0]}: {k}: {v}".strip())
                    break
    return bad


def test_pages_space_their_pieces_on_the_scale():
    """views.css places pieces with the steps of the spacing scale; a component's own inside (its padding) is set in
    its section of components.css."""
    bad = spaces_off_the_scale(VIEWS)
    assert not bad, "\n".join(bad)
    assert spaces_off_the_scale(".a { margin: 10px 0 14px; } .b { gap: .35rem; }") == [".a: margin: 10px 0 14px", ".b: gap: .35rem"]
    assert spaces_off_the_scale(".a { margin: 6px 0 var(--space-3); gap: 4px 12px; margin-left: -2px; } .b { gap: .7em; }") == []


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
    # Changed on purpose in 0.17.0: a style written as a string or a template string slipped past the check above, so
    # none is allowed at all (a value computed at run time goes in style: { … })
    as_text = re.compile(r"\bstyle:\s*[\"'`]")
    bad = [f"{n}:{js.count(chr(10), 0, m.start()) + 1}" for n, js in ALL_JS.items() for m in as_text.finditer(js)]
    assert not bad, "an inline style written as a string: " + ", ".join(bad)


def test_inline_styles_hold_only_values_computed_at_run_time():
    """docs/DESIGN.md 9.2 rule 3: a page's spacing is a class of its block in views.css; `style: {…}` only carries a
    value computed while the page runs (a bar's width from a count, a position from a measurement)."""
    fixed = re.compile(r"style:\s*\{(\s*\w+:\s*(?:\"[^\"`$]*\"|'[^'`$]*'|-?\d+(?:\.\d+)?)\s*,?)+\s*\}")
    bad = [f"views/{n}: {m.group(0)}" for n, js in VIEW_JS.items() if n != "design.js" for m in fixed.finditer(js)
           if "visibility" not in m.group(0)]   # a hidden copy used only to measure
    assert not bad, "\n".join(bad)


# the classes a page must never spell: they are made by the helpers of lib.js (docs/DESIGN.md, 9.2 rule 4). The parts
# of a component count too: a card's head (card({ title, help, action })), a page head and its parts (pageHead()), a
# row of tabs (tabs(), viewTabs()), a button with its AI mark (withAI()), the Display title (pageHead({ display }))
SPELLED = re.compile(r"""\b(?:class|titleClass):\s*[`"']([^`"']*)[`"']|\.className\s*=\s*[`"']([^`"']*)[`"']|"""
                     r"""\.classList\.(?:add|remove|toggle)\(\s*((?:[`"'][^`"']*[`"']\s*,?\s*)+)""")
HELPER_CLASSES = {"btn", "btn-primary", "btn-ghost", "btn-danger", "btn-outline-danger", "btn-sm", "btn-lg", "link-btn",
                  "danger-link", "icon-btn", "chip", "chip-code", "warn-chip", "chip-btn", "badge", "badge-accent",
                  "badge-warn", "notice", "notice-info", "notice-ok", "notice-warn", "notice-error", "card", "seg-on",
                  "fold", "menu-item", "menu-list", "input", "select", "textarea", "link-title", "link-next", "link-back",
                  "link-external", "link-jump", "card-sm", "fold-sm", "empty", "seg", "seg-btn", "option-card", "option-cards",
                  "badge", "work-state", "ai-where", "ai-tag", "chip-count", "person-mark", "search-field", "drawer",
                  "card-head", "page-head", "page-head-main", "page-head-actions", "page-facts", "settings-tabs", "with-ai",
                  "title-display"}
# the scripts that make the components: they may spell their classes
MAKERS = {"lib.js"}


def hand_spelled(scripts: dict[str, str]) -> list[str]:
    """Each place where a script other than lib.js spells a helper's class: in `class:` or `titleClass:`, in a
    `.className =`, or in `classList.add/remove/toggle("…")` ("views/x.js:12: class: \"card-head\"")."""
    bad = []
    for name, js in scripts.items():
        if name in MAKERS:
            continue
        for m in SPELLED.finditer(js):
            text = " ".join(g for g in m.groups() if g)
            words = set(re.sub(r"\$\{[^}]*\}|[`\"',]", " ", text).split())
            if words & HELPER_CLASSES:
                line = js.count("\n", 0, m.start()) + 1
                bad.append(f"{'views/' if name in VIEW_JS else ''}{name}:{line}: {' '.join(m.group(0).split())}")
    return bad


def test_pages_use_the_helpers_instead_of_spelling_component_classes():
    bad = hand_spelled(ALL_JS)
    assert not bad, "\n".join(bad)


def test_the_guard_sees_a_part_spelled_by_hand():
    # the slips this guard is for: a card's head, a page head, a row of tabs, a button's kind and the AI mark's span,
    # spelled by a page; the same made by the helpers passes
    slips = {
        "views/a.js": 'card({}, h("div", { class: "card-head" }, h("h2", {}, "Testing"), stop));',
        "views/b.js": 'h("header", { class: "page-head result-head" }, h("div", { class: "page-head-main" }, title));',
        "views/c.js": 'h("nav", { class: "settings-tabs", "aria-label": "Settings" }, links);',
        "views/d.js": 'nextBtn.classList.add("btn-primary");',
        "views/e.js": 'btn.className = "btn btn-primary btn-sm update-ready";',
        "views/f.js": 'h("span", { class: "with-ai" }, btn, aiTag("uses"));',
        "views/g.js": 'pageHead(c.label, { titleClass: "title-display ct-title" });',
    }
    found = hand_spelled(slips)
    assert sorted({f.split(":")[0] for f in found}) == sorted(slips), found
    fine = {"views/a.js": 'card({ title: "Testing", action: stop }, pb); el.classList.add("ev-flash");',
            "views/b.js": 'pageHead(r.text, { class: "result-head", display: true, titleClass: "result-hyp" });',
            "views/c.js": 'tabs({ label: "Settings", items, current }); h("div", { class: "btn-row" }, withAI(btn));',
            "lib.js": 'h("div", { class: "card-head" });'}
    assert hand_spelled(fine) == []


# Icons with a reserved meaning (docs/DESIGN.md 3.3): the circle family is a judgement's own (an answer, a grade), and
# the chip is the AI mark's. A script names them only inside the helpers that draw those: the badges and
# judgementIcon() (lib.js), aiTag() (lib.js); icons.js draws every icon and keeps STATUS_ICON.
RESERVED_ICONS = {"circle-check", "circle-half", "circle-x", "circle-minus", "circle-dashed", "circle-dot", "arrows-opposed", "cpu"}
ICON_KEEPERS = {"lib.js": ("GRADE_ICON", "judgementIcon", "gradeBadge", "statusBadge", "aiTag")}


def _spans_of(js: str, names) -> list[tuple[int, int]]:
    """Where each named function or const of a script begins and ends (to the first line that closes it)."""
    out = []
    for n in names:
        for m in re.finditer(rf"^(?:export\s+)?(?:function\s+{n}\(|const\s+{n}\s*=)", js, flags=re.M):
            end = js.find("\n}\n", m.start())
            line_end = js.find("\n", m.start())
            end = line_end if js[m.start():line_end].rstrip().endswith(";") else end
            out.append((m.start(), end if end > 0 else len(js)))
    return out


def reserved_icons_out_of_place(scripts: dict[str, str]) -> list[str]:
    bad = []
    names = "|".join(re.escape(n) for n in sorted(RESERVED_ICONS))
    literal = re.compile(rf"""[`"']({names})[`"']|[`"']circle-\$\{{""")
    for name, js in scripts.items():
        if name == "icons.js":
            continue
        spans = _spans_of(js, ICON_KEEPERS.get(name, ()))
        for m in literal.finditer(js):
            if any(a <= m.start() < b for a, b in spans):
                continue
            bad.append(f"{name}:{js.count(chr(10), 0, m.start()) + 1}: {m.group(0)}")
        # STATUS_ICON is the answers' icons: only lib.js's helpers read it
        if name not in ICON_KEEPERS and re.search(r"\bSTATUS_ICON\b", js):
            bad.append(f"{name}: reads STATUS_ICON")
    return bad


def test_reserved_icons_keep_their_meaning():
    """docs/DESIGN.md 3.3: circle-check means "supports", never "done" (that is `check`); arrows-opposed is mixed
    evidence, never a button's icon; the chip is the AI mark's, never a button's, a tab's or a model line's."""
    bad = reserved_icons_out_of_place({**ALL_JS, "index.html": index_html()})
    assert not bad, "\n".join(bad)
    # the slips it is for: "done" drawn with the judgement's circle, a button with the chip or the mixed arrows; the
    # same icons drawn by the badge helpers and the AI mark pass
    slips = {"views/a.js": 'h("p", {}, icon("circle-check", { size: 14 }), "Zotero is open on this computer.")',
             "views/b.js": 'button({ sm: true }, icon("cpu", { size: 13 }), "Get a second opinion")',
             "views/c.js": 'button({ sm: true }, icon("arrows-opposed", { size: 13 }), "Get a second opinion for all answers")',
             "views/d.js": 'import { STATUS_ICON } from "../icons.js"; icon(STATUS_ICON[k])'}
    assert [b.split(":")[0] for b in reserved_icons_out_of_place(slips)] == list(slips)
    lib = ALL_JS["lib.js"]
    assert reserved_icons_out_of_place({"lib.js": lib}) == []
    assert reserved_icons_out_of_place({"lib.js": lib + '\nexport function doneLine() { return icon("circle-check"); }\n'}) != []


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
def _removed_classes() -> list[str]:
    """The classes 0.17.0 removed, as docs/EXTENDING.md lists them for forks (the block after <!-- removed-classes -->)."""
    text = (ROOT / "docs" / "EXTENDING.md").read_text(encoding="utf-8")
    block = re.search(r"<!-- removed-classes -->\s*```text\n(.*?)```", text, re.S)
    assert block, "docs/EXTENDING.md lists no removed classes"
    return block.group(1).split()


REMOVED_CLASSES = _removed_classes()


def test_the_removed_classes_stay_gone():
    code = all_css() + "".join(ALL_JS.values()) + index_html()
    # a class, not part of an address (app.js asks /api/whats-new)
    left = [c for c in REMOVED_CLASSES if re.search(r"(?<![\w/-])" + re.escape(c) + r"(?![\w-])", code)]
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
               "codeChip", "pageHead", "downloadLinks", "helpMark", "popNote", "toast", "dialog", "confirmDialog", "heatCell", "heatGrid",
               "strongerMark", "aiTag", "viewTabs", "featureEyebrow", "personMark", "reviewedMark", "severityTag", "compare",
               "shareState", "absentDocument", "listRow", "listGroup", "noticeList", "teamLine"]
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


def test_the_project_switch_spans_the_sidebar():
    """docs/DESIGN.md 5.1: the project switch is a field-like box as wide as Find. It is the menu component (4.17),
    which is an inline-block that hugs its button; in the sidebar it is a block, and its summary fills it."""
    assert rule(".project-switch > .menu").get("display") == "block"
    assert rule(".project-switch summary").get("width") == "100%"
    ref = VIEW_JS["design.js"]
    sample = ref[ref.index('sample("The project switch"'):ref.index('sample("Entries')]
    switch = ref[ref.index("const projectSwitch = "):ref.index("const teamLineIn = ")]
    assert "projectSwitch()" in sample   # the reference draws it as the sidebar does
    assert "menu(" in switch and 'listClass: "ps-menu"' in switch


# a helper that draws an AI button for a card drawn elsewhere: the functions that draw that card's AI line
AI_LINE_DRAWN_BY = {
    ("result.js", "secondModelPicker"): ["modelsCard"],
    ("result.js", "readLocalButton"): ["partView", "readLocalNotice"],
    ("concepts.js", "linkRow"): ["relatedCard"],
    ("doc-lookup.js", "lookup"): ["refsPanel"],   # 0.18.4: the References panel moved from sources.js
}


def _functions(code):
    for m in re.finditer(r"\bfunction\s+(\w+)\s*\([^)]*\)\s*\{", code):
        i, depth = m.end() - 1, 0
        for j in range(i, len(code)):
            depth += {"{": 1, "}": -1}.get(code[j], 0)
            if depth == 0:
                yield m.group(1), i, j
                break


def ai_actions_without_their_line(scripts: dict[str, str]) -> list[str]:
    says = lambda body: re.search(r"\b(readsLine|aiWhere)\(", body) is not None
    missing = []
    for name, js in scripts.items():
        if name == "design.js":
            continue
        code = js_code(js)
        funcs = list(_functions(code))
        # a file may hold several inner functions of one name (each page's own draw()): the AI line is looked for in
        # the function that holds the button; a helper named in AI_LINE_DRAWN_BY counts if any function of each
        # named drawer says it
        bodies = lambda f: [code[a:b] for g, a, b in funcs if g == f]
        for m in re.finditer(r"(?<![\w$])(?<![\w$]\.)withAI\(", code):   # also `...withAI(`
            inner = min((f for f in funcs if f[1] < m.start() < f[2]), key=lambda f: f[2] - f[1], default=None)
            fname = inner[0] if inner else "<top>"
            drawn_by = AI_LINE_DRAWN_BY.get((name, fname))
            # the line comes after the action in the source as on the screen: a line written before the action is
            # one that sits above it
            ok = (all(any(says(b) for b in bodies(c)) for c in drawn_by) if drawn_by
                  else bool(inner) and says(code[m.end():inner[2]]))
            if not ok:
                missing.append(f"{name}:{code[:m.start()].count(chr(10)) + 1} {fname}()")
    return missing


def test_a_card_with_ai_actions_says_where_text_goes():
    """docs/DESIGN.md 4.4: every button that sends text to an AI has its mark (withAI()), and the card or section that
    holds it says once, under its AI actions, where the text goes (readsLine() or aiWhere())."""
    missing = ai_actions_without_their_line(VIEW_JS)
    assert not missing, "AI actions whose card does not say where text goes:\n" + "\n".join(missing)


def test_a_table_stacks_by_the_width_of_its_frame():
    """docs/DESIGN.md 4.20: the rows of .table-responsive stack when their frame (.table-wrap) is narrower than 900 px,
    whether a small window or the open drawer narrows it, so no column hides behind a sideways scroll."""
    assert rule(".table-wrap").get("container-type") == "inline-size"
    stacking = [(med, sels) for med, sels, _ in css_blocks(all_css()) if any("table-responsive" in s for s in sels)]
    assert any(med == "@container (max-width: 899px)" for med, _ in stacking)
    assert not [sels for med, sels in stacking if "@media" in med], "a table still stacks by the window's width"
    for name, js in VIEW_JS.items():   # every responsive table sits in a frame, which is what the rule measures
        tables = len(re.findall(r'class:\s*"[^"]*\btable-responsive\b', js))
        assert len(re.findall(r'class:\s*"table-wrap\b', js)) >= tables, f"a responsive table outside .table-wrap in {name}"


def stops_drawn_by_hand(scripts: dict[str, str]) -> list[str]:
    """Stop buttons not made by stopButton(): the stop icon named outside it, or a button whose words are Stop."""
    out = []
    for name, js in scripts.items():
        # the strings matter here ("stop", "Stop"), so only comments are taken out
        code = re.sub(r"/\*.*?\*/", "", re.sub(r"(?m)^\s*//.*$", "", js), flags=re.S)
        if name == "lib.js":   # the stop icon only inside stopButton() itself
            m = re.search(r"export function stopButton\([^)]*\)\s*\{.*?\n\}", code, re.S)
            code = code.replace(m.group(0), "") if m else code
        if re.search(r"""icon\(\s*["']stop["']|icon:\s*["']stop["']""", code):
            out.append(f"{name}: the stop icon outside stopButton()")
        if re.search(r"""\bbutton\([^;]*?["']Stop["']\s*\)""", code):
            out.append(f"{name}: a Stop made with button()")
    return out


def test_a_jobs_stop_is_one_small_quiet_button():
    """docs/DESIGN.md 4.1 and 4.21: a job's Stop is a small quiet button with the stop icon (stopButton()). It ends
    work and removes nothing, so it is never a danger button."""
    assert not stops_drawn_by_hand(ALL_JS)
    assert re.search(r'export function stopButton[^\n]*\n[^\n]*\n\s*return button\(\{ \.\.\.attrs, kind: "quiet", sm: true, icon: "stop" \}', LIB)


def test_the_guard_sees_a_stop_drawn_by_hand():
    slips = ['const s = button({ kind: "danger", sm: true }, icon("stop", { size: 13 }), "Stop");',
             'const s = button({ kind: "quiet", sm: true, icon: "stop" }, "Stop");',
             'const s = button({ kind: "danger", sm: true, onClick: go }, "Stop");']
    for slip in slips:
        assert stops_drawn_by_hand({"x.js": slip}), slip
    assert not stops_drawn_by_hand({"x.js": 'const s = stopButton({ onClick: go });'})


def test_a_page_head_holds_no_next_step_link():
    """docs/DESIGN.md 4.3 and 6: the next-step link is the one way on from an empty state or a notice. A way to another
    page in a page head is a plain link in the line under the title."""
    found = []
    for name, js in VIEW_JS.items():
        code = js_code(js)   # brackets balance here; the strings are blanked, so kind: "next" is read from js itself
        for m in re.finditer(r"(?<![\w.])pageHead\(", code):
            depth, j = 0, m.end() - 1
            for j in range(m.end() - 1, len(code)):
                depth += {"(": 1, ")": -1}.get(code[j], 0)
                if depth == 0:
                    break
            if re.search(r'kind:\s*"next"', js[m.start():j]):
                found.append(f"{name}:{code[:m.start()].count(chr(10)) + 1}")
    assert not found, f"a next-step link in a page head: {found}"


INHERITED_LOOK = {"color", "font-weight", "font-family", "font-style"}


def title_link_wrappers(scripts: dict[str, str]) -> set[str]:
    """The classes of the element that holds a title link: the h(…) call it is written in."""
    out: set[str] = set()
    for js in scripts.values():
        code = js_code(js)
        for m in re.finditer(r"(?<![\w.])link\(\s*\{", code):
            if not re.match(r'\{[^{}]*\bkind:\s*"title"', js[m.end() - 1:m.end() + 200]):
                continue
            depth, i = 0, m.start() - 1
            while i >= 0:   # back to the "(" of the call this link is an argument of
                ch = code[i]
                if ch in ")]}":
                    depth += 1
                elif ch in "([{":
                    if depth == 0 and ch == "(":
                        break
                    depth = max(0, depth - 1) if ch != "(" or depth else depth
                i -= 1
            if i > 0 and re.search(r"(?<![\w.])h\s*$", code[:i]):
                first = re.match(r'\(\s*"[\w-]+"\s*,\s*\{[^{}]*?\bclass:\s*"([^"]*)"', js[i:i + 300])
                if first:
                    out |= set(first.group(1).split())
    return out - NOT_COMPONENTS - {"grow", "it"}


def looks_set_on_title_link_wrappers(css: str, classes: set[str]) -> list[str]:
    bad = []
    for media, sels, decls in css_blocks(css):
        props = INHERITED_LOOK & set(decls)
        if not props:
            continue
        for sel in sels:
            last = re.split(r"[\s>+~]+", re.sub(r":(not|has|is|where)\([^)]*\)", "", sel).strip())[-1]
            if set(re.findall(r"\.([\w-]+)", last)) & classes:
                bad.append(f"{media} {sel}: {sorted(props)}".strip())
    return bad


def test_a_title_links_look_never_comes_from_its_wrapper():
    """docs/DESIGN.md 4.3: a title link's weight, face and colour are its own (components.css 4.3). views.css may set the
    size of the place that holds one, never a look that it would inherit (`.doc-title { font-weight: 600 }` made the
    Documents list's titles bold and no other list's)."""
    classes = title_link_wrappers(VIEW_JS)
    assert {"doc-title", "notes-doc-title"} <= classes, classes
    bad = looks_set_on_title_link_wrappers(VIEWS, classes)
    assert not bad, "\n".join(bad)
    assert looks_set_on_title_link_wrappers(".doc-title { font-weight: var(--fw-strong); }", {"doc-title"})


def _object_at(js: str, i: int) -> str:
    """The object literal that starts at js[i] == "{", to its matching "}" (strings skipped)."""
    code = js_code(js)
    depth = 0
    for j in range(i, len(code)):
        depth += {"{": 1, "}": -1}.get(code[j], 0)
        if depth == 0:
            return js[i:j + 1]
    return js[i:]


def links_without_an_address(scripts: dict[str, str]) -> list[str]:
    """An <a> or a link() with no href: an action drawn as a link. link({ kind: "jump" }) is the one link without one
    (a move on this page, drawn as a <button>)."""
    bad = []
    for name, js in scripts.items():
        if name == "lib.js":
            continue
        for helper in _helper_names(js) & ({"link"} | set(re.findall(r"\blink\s+as\s+(\w+)", js))):
            for m in re.finditer(rf"(?<![\w.]){helper}\(\s*\{{", js):
                obj = _object_at(js, m.end() - 1)
                if not re.search(r"\bhref\b", obj) and not re.search(r'\bkind:\s*"jump"', obj):
                    bad.append(f"{name}: {js[m.start():m.start() + 70]}")
            for m in re.finditer(rf"(?<![\w.]){helper}\(\s*\)", js):
                bad.append(f"{name}: {m.group(0)}")
        for m in re.finditer(r'(?<![\w.])h\(\s*"a"\s*(?:,\s*\{|\))', js):
            obj = _object_at(js, m.end() - 1) if m.group(0).endswith("{") else ""
            if not re.search(r"\bhref\b", obj):
                bad.append(f"{name}: {js[m.start():m.start() + 70]}")
    return bad


def test_every_link_has_an_address():
    """docs/DESIGN.md 4.3 and 10: no action drawn as a link. A link (an <a>, or link()) goes somewhere, so it has an
    href; the one exception is link({ kind: "jump" }), a move on this page."""
    bad = links_without_an_address(ALL_JS)
    assert not bad, "\n".join(bad)
    for slip in ['h("a", { onClick: go, role: "button" }, "Remove")', 'link({ onClick: go }, "Delete")', 'h("a", {}, "x")']:
        assert links_without_an_address({"x.js": 'import { link } from "../lib.js";\n' + slip}), slip
    assert not links_without_an_address({"x.js": 'import { link } from "../lib.js";\nlink({ kind: "jump", onClick: go }, "Up")'})


JUDGEMENT_TOKENS = re.compile(r"var\(--(ok|partly|mixed|bad|none)(-[a-z]+)?\)")
# where a judgement colour may be used: the judgement badges, quotes and highlights, the heat grid, the excerpt cards
JUDGEMENT_SECTIONS = {"4.9", "4.23", "4.25", "4.26"}


def judgement_colours_out_of_place(components: str, views: str, app: str) -> list[str]:
    bad = []
    for num, body in re.findall(r"/\* ==== (\d+\.\d+)[^\n]*\*/(.*?)(?=/\* ==== |\Z)", components, re.S):
        if num not in JUDGEMENT_SECTIONS and JUDGEMENT_TOKENS.search(body):
            bad += [f"components.css § {num}: {m.group(0)}" for m in JUDGEMENT_TOKENS.finditer(body)]
    for name, css in (("views.css", views), ("app.css", app)):
        for media, sels, decls in css_blocks(css):
            if any(JUDGEMENT_TOKENS.search(v) for v in decls.values()):
                # the result page's own evidence says judgements: the answer block, the documents' and the second
                # opinion's dots (.result .who-dot), the excerpt table's edge (.ex-supports …)
                if not all(s.startswith((".answer", ".result .who-dot", ".ex-")) for s in sels):
                    bad.append(f"{name}: {', '.join(sels)}")
    return bad


def test_judgement_colours_mean_a_judgement_only():
    """docs/DESIGN.md 3.1: the five judgement colours (--ok*, --partly*, --mixed*, --bad*, --none*) say a judgement of
    the evidence and nothing else: they appear only in the judgement badges (4.9), quotes and highlights (4.23), the
    heat grid (4.25), the excerpt cards (4.26) and the result page's own evidence (its answer block, the documents'
    dots, the excerpt table's edge)."""
    bad = judgement_colours_out_of_place(COMPONENTS, VIEWS, APP)
    assert not bad, "\n".join(bad)
    assert judgement_colours_out_of_place("", ".foo-thing { background: var(--ok-soft); }", "")
    assert judgement_colours_out_of_place("/* ==== 4.1 Buttons */\n.btn { color: var(--bad); }", "", "")


# every dashed edge, and what is not in force or not there yet about it (docs/DESIGN.md 3.3)
DASHED = {
    ".badge-weak": "a judgement that does not count",
    ".empty": "nothing here yet",
    ".passage-pending mark.quote": "a quote you picked, not saved yet",
    ".dropzone": "files not there yet",
    ".inset-tentative": "not in force: a reading the AI proposed and nobody confirmed, a proposed link, a removed theme",
    ".doc-view .dv-fold .passage-row": "passages left out of the reading",
    ".dv-pbox-out": "a part left out of the reading",
    ".cal-bar.cal-empty": "no excerpts in this band yet",
}


def test_a_dashed_edge_means_not_in_force_or_not_there_yet():
    """docs/DESIGN.md 3.3: a dashed edge has one meaning. Each one is named here with what is not in force or not there
    yet about it; a new one (a sample frame on #/design was dashed) must be argued for here first."""
    found = {sel for _, sels, decls in css_blocks(all_css()) if any("dashed" in v for v in decls.values()) for sel in sels}
    assert found <= set(DASHED), sorted(found - set(DASHED))


# soft teal means here, chosen or found; a message is notice() (docs/DESIGN.md 3.1, 4.12)
SOFT_TEAL_MEANS = {
    '.dropzone[data-over="true"]': "chosen: files about to land here",
    ".bulk-bar": "chosen: the rows you ticked",
    '.doc-view .passage-row[data-found="true"]': "found by words",
    "mark.kt-pin": "chosen: a key term you pinned",
    ".dv-code-id": "found by a code: its mark in the reading view",
    ".dv-term.dv-pinned": "chosen: a term you pinned",
    '.dv-chain-btn[aria-pressed="true"]': "chosen: the chain shown",
    '.picker-item[aria-selected="true"]': "chosen: the row picked",
    '.cb-code-row:has(> .cb-code-sum[aria-expanded="true"])': "here: the code open in the codebook editor",
    '.doc-item[data-open="true"] > .doc-row': "here: the document open in the Documents list",
}

def test_soft_teal_means_here_chosen_or_found():
    """docs/DESIGN.md 3.1: in views.css --accent-soft grounds only what is here, chosen or found; never a notice."""
    bad = [f"{m} {s}" for m, sels, d in css_blocks(VIEWS) for s in sels
           if any("--accent-soft" in str(v) for v in d.values()) and s not in SOFT_TEAL_MEANS]
    assert not bad, "soft teal with no meaning of its own:\n" + "\n".join(bad)

HAND_NOTICES = ["batch-banner", "map-batch-banner", "run-summary", "moved-note", "user-note", "whats-new"]

def test_messages_are_notices():
    code = VIEWS + "".join(VIEW_JS.values())
    left = [c for c in HAND_NOTICES if re.search(r"(?<![\w-])" + c + r"(?![\w-])", code)]
    assert not left, f"hand-drawn notices are back: {left}"

# the page head: its AI line after its actions; a narrow head lays its actions out from the left (4.4, 4.14)
def _call_args(code, name):
    for m in re.finditer(r"\b" + name + r"\(", code):
        i, depth = m.end() - 1, 0
        for j in range(i, len(code)):
            depth += {"(": 1, ")": -1}.get(code[j], 0)
            if depth == 0:
                yield code[i:j + 1]
                break

def test_a_page_heads_ai_line_comes_after_its_actions():
    """docs/DESIGN.md 4.4 and 4.14: a page head's AI line is pageHead({ ai }), drawn after the actions; never meta."""
    bad = []
    for name, js in VIEW_JS.items():
        for args in _call_args(js_code(js), "pageHead"):
            m = re.search(r"\bmeta:\s*", args)
            if m and re.search(r"\b(readsLine|aiWhere)\(", args[m.end():m.end() + 400].split("actions:")[0]):
                bad.append(name)
    body = LIB.split("export function pageHead", 1)[1].split("\nexport function", 1)[0]
    assert "opts.ai" in body and body.index("opts.ai") > body.index("page-head-actions"), "pageHead() draws no ai line after the actions"
    assert not bad, f"an AI line passed as a page head's meta: {bad}"

def test_a_stacked_page_head_lays_its_actions_from_the_left():
    """docs/DESIGN.md 4.14: when the head is too narrow for two columns, its actions are one row from the left."""
    heads = [d for m, s, d in css_blocks(COMPONENTS) if ".page-head" in s and not m]
    assert any("page-head" in str(d.get("container", "")) or d.get("container-type") == "inline-size" for d in heads)
    stacked = [(m, s, d) for m, s, d in css_blocks(COMPONENTS) if m.startswith("@container") and "page-head" in m
               and any(x.startswith(".page-head-actions") for x in s)]
    assert stacked and all(d.get("justify-content") == "flex-start" and d.get("flex-direction", "row") == "row"
                           and d.get("align-items") != "flex-end" for m, s, d in stacked), stacked

# stacked tables share their facts' lines; a concordance line's document is the title column (4.20, 4.24)
def test_a_concordance_title_is_the_title_column():
    """docs/DESIGN.md 4.24: a line's document is the title column (kw-where-title, two lines at most), never a one-line
    column that grows and squeezes the words around the hit."""
    bad = [n for n, js in VIEW_JS.items() for m in re.finditer(r'class: "kw-where"\s*\},\s*link\(\{\s*kind: "title"', js)]
    assert not bad, bad

def test_stacked_facts_share_a_line():
    """docs/DESIGN.md 4.20: in a stacked table a short fact (td.fact, td.num) flows on one line with the others."""
    rules = [d for m, s, d in css_blocks(COMPONENTS) if m.startswith("@container") and "899px" in m
             and any("td.fact" in x for x in s)]
    assert rules and any(d.get("display", "").startswith("inline") for d in rules)
    # a page's column width (td.num { width: 1% }) must not squeeze a stacked cell to its label's first letters
    cells = [d for m, s, d in css_blocks(COMPONENTS) if m.startswith("@container") and "899px" in m and ".table-responsive td" in s]
    assert cells and all(d.get("width") == "auto !important" for d in cells), cells
    pages = [d for m, s, d in css_blocks(VIEWS) if m.startswith("@container") and any(re.search(r"td\.num$", x) for x in s)
             and d.get("display", "").startswith("inline")]
    assert not pages, "a page makes its own stacked facts inline: that is the table's (components.css 4.20)"


def test_list_rows_line_up_and_name_research_items_in_the_serif():
    """docs/DESIGN.md 4.20 (Lists of rows): the rows of a group share their columns, so names start at one x whatever
    the person marks say; listRow() can draw a research item's name in the serif (3.2)."""
    body = LIB.split("export function listRow", 1)[1].split("\nexport function", 1)[0]
    assert re.search(r"link\(\{[^}]*\bserif\b", body), "listRow() cannot pass serif to its title link"
    assert rule(".list-row").get("grid-template-columns") == "subgrid"
    assert "grid-template-columns" in rule(".list-rows")


def test_corners_are_tokens():
    """docs/DESIGN.md 3 and 9: a corner is one of the radius tokens (or 0, or a circle's 50%), never a page's own px."""
    bad = []
    for name, css in (("app.css", APP), ("components.css", COMPONENTS), ("views.css", VIEWS)):
        for media, sels, decls in css_blocks(css):
            for k, v in decls.items():
                if "radius" in k and re.sub(r"var\(--radius[\w-]*\)|\b0\b|50%|\s", "", v):
                    bad.append(f"{name} {', '.join(sels)} {k}: {v}")
    assert not bad, "\n".join(bad)


# The boxes views.css still draws, each with what it is: a piece no component means (a page frame, a floating toolbar,
# a bar). A page draws no new one: a box in a card is inset(), a box of its own is card({ sm }),
# a message is notice() (docs/DESIGN.md 4.11, 4.12, 9.2). A box is any rule with a ground (a surface, the soft teal,
# the quote's yellow, a mixed tint) and padding or an edge of any kind; a state of a listed box (:hover,
# [aria-selected]) and a chosen state named in SOFT_TEAL_MEANS count as listed.
PAGE_BOXES = {
    ".ov-card": "the Overview's place cards: a page's link card, the whole card its link (DESIGN 4.11)",
    ".dv-selbar": "the reading view's floating bar over a selection (a toolbar, with its shadow)",
    ".dv-chain-btn": "a reference chain's chooser in the reading view, pressed when shown",
    ".doc-view .dv-act": "the floating actions beside a selected passage in the reading view",
    ".dv-page-frame": "the reading view's page frame: the document's own page",
    ".refers": "the reading view's 'refers to' box beside a passage",
    ".pf-top li": "the Codes profile's ranked codes, a bar in each row",
    ".cb-card": "a codebook in the list of codebooks: the whole card opens it",
    ".cb-savebar": "the codebook editor's save bar, sticky at the foot",
    ".doc-pick": "a scrolling list of documents to tick, inside a dialog",
    ".dropzone": "the drop zone that waits for files: its dashed frame (not there yet)",
    ".bib-excerpt": "Bibliography: the passage where a document names a work, with its edge as a quote",
    ".picker-group": "the code picker's sticky group head, on the list's ground so rows scroll under it",
    ".copy-code": "a command to copy, in mono on a grey ground (code in running text)",
    ".dz-side": "#/design: a piece of the sidebar on the sidebar's ground",
    ".dz-corner": "#/design: the sample of a corner token",
    ".dz-shadow": "#/design: the sample of a shadow token",
    ".doc-view .dv-table th, .doc-view .dv-table td": "a table inside a document's own text, its words wrapped to the reading column",
    ".dz-frame": "#/design: the frame of a sample",
}


def test_a_page_draws_no_box_of_its_own():
    """docs/DESIGN.md 9: views.css places components; a box with a component's ground and edge drawn by a page is named
    in PAGE_BOXES with what it is, and a new one is inset() or card() instead."""
    found = set()
    for media, sels, decls in css_blocks(VIEWS):
        ground = decls.get("background") or decls.get("background-color") or ""
        if not re.search(r"var\(--(surface|surface-2|surface-3|bg-2|paper|accent-soft|mark)\)|color-mix\(", ground):
            continue
        if any(k.startswith("padding") for k in decls) or any(k.startswith("border") and "radius" not in k for k in decls):
            found |= set(sels)
    # Changed on purpose in 0.17.0: an edge all round with padding is a box too, ground or not (a framed fieldset slipped
    # past the check above)
    for media, sels, decls in css_blocks(VIEWS):
        edge = any(k in ("border", "outline") and not re.match(r"\s*(0|none)\b", v) for k, v in decls.items())
        if edge and any(k.startswith("padding") and not re.fullmatch(r"\s*0\s*", v) for k, v in decls.items()):
            found |= {", ".join(sels)} if len(sels) > 1 else set(sels)
    state = re.compile(r"(:hover|:focus(-visible|-within)?|\[[^\]]*\])+$")
    left = sorted(s for s in found if s not in PAGE_BOXES and s not in SOFT_TEAL_MEANS and state.sub("", s) not in PAGE_BOXES)
    assert not left, "a page draws a box of its own (inset(), card({ sm }) or notice() instead): " + ", ".join(left)
    # and the list holds only boxes still drawn: a piece that became a component leaves it
    stale = sorted(set(PAGE_BOXES) - found)
    assert not stale, "PAGE_BOXES names pieces views.css no longer draws as boxes: " + ", ".join(stale)


# The needs-you and went-wrong icons (docs/DESIGN.md 3.3): each has one meaning and one look, amber or red, so only the
# helpers that give them that look draw them (tag() and notice() of kind attention or error, workState(), aiWhere(),
# field errors; app.js's status area). A page never names them; it says "needs you" with tag({ kind: "attention" }),
# notice({ kind: "attention" }) or workState("attention", …), and a caution that asks nothing of you with the info icon.
# The places below draw the icon themselves, each counted, with what it is.
STATE_ICON_PLACES = {
    "design.js": (3, "the reference: the legend of the reserved icons (3.3, two) and the sidebar's attention card"),
    "settings.js": (1, "the Claude Code set-up's step still to do: its mark in --attention (.cc-step[data-state=todo] .cc-mark)"),
}


def state_icons_out_of_place(scripts: dict[str, str]) -> list[str]:
    """The view scripts (views/*.js, by file name) that name the triangle or the alert circle more often than allowed."""
    bad = []
    for name, js in scripts.items():
        hits = [m for m in re.finditer(r"""[`"'](alert-triangle|alert-circle)[`"']""", js)]
        allowed = STATE_ICON_PLACES.get(name, (0, ""))[0]
        if len(hits) > allowed:
            bad += [f"{name}:{js.count(chr(10), 0, m.start()) + 1}: {m.group(1)}" for m in hits]
    return bad


def test_needs_you_and_went_wrong_icons_come_with_their_look():
    """docs/DESIGN.md 3.3 and 4.12: the triangle is "needs you" in amber, the alert circle "went wrong" in red; a grey
    triangle beside a caution, or an alert circle beside "Unsaved changes", is a misfit."""
    bad = state_icons_out_of_place(VIEW_JS)
    assert not bad, "a page draws a needs-you or went-wrong icon by hand (tag/notice/workState of its kind instead):\n" + "\n".join(bad)
    slips = {"a.js": 'h("p", { class: "answer-next-text" }, icon("alert-triangle", { size: 14 }), "It rests on a single document.")',
             "b.js": 'h("span", { class: "cb-unsaved" }, icon("alert-circle", { size: 14 }), "Unsaved changes")'}
    assert [b.split(":")[0] for b in state_icons_out_of_place(slips)] == list(slips)


def test_a_judged_excerpt_names_each_way_back():
    """docs/DESIGN.md 4.26: after a judgement the toast has Undo for a few seconds; on the card, Take back goes to the AI's
    judgement, and its moved note offers Back to “…” only when your earlier judgement was your own, so no two buttons
    on a card go to the same place and each says where it goes. The place the card left has only Show it."""
    js = VIEW_JS["result.js"]
    ph = js[js.index("const ph = "):js.index("if (oldList)")]
    assert "button(" not in ph and '"Show it"' in ph, "the place a moved card left offers an action besides Show it"
    # the note's way back comes from noteWayBack() (tested below), and sits in its sentence (one line)
    assert "fa.undoText = noteWayBack(prev.verdict, verdict, p.read_by);" in js and "fa.undo = fa.undoText ? undo : null;" in js
    assert 'f.undo ? [" ", button({ kind: "quiet", sm: true, onClick: f.undo }, f.undoText)] : null)), el.firstChild);' in js
    start = js.index('el.insertBefore(notice({ kind: "info", icon: "arrow-right"')
    note = js[start:js.index("el.firstChild);", start)]
    assert '"Undo"' not in note, "the moved note's button says Undo, which does not say where it goes beside Take back"


# The amber and the red mean "needs you" and "went wrong" (docs/DESIGN.md 3.1, 3.3). Only their components wear them
# (tag({ kind: "attention" }), notice(), workState(), a field's error): a page that wants to say "needs you" uses one
# of those, and a fact (a count still to review, nothing found by these words, no AI read it) stays grey. views.css
# names neither colour except here, each with what it is.
PAGE_STATE_COLOURS = {
    '.cc-step[data-state="todo"] .cc-mark': "the Claude Code set-up's step still to do: its mark, the triangle, in amber",
}


def page_state_colours(css: str) -> list[str]:
    """The views.css selectors that paint with the attention or danger colours (any of their tokens), not listed."""
    bad = []
    for media, sels, decls in css_blocks(css):
        if any(re.search(r"var\(--(attention|danger)", v) for v in decls.values()):
            bad += [s for s in sels if s not in PAGE_STATE_COLOURS]
    return bad


def test_a_page_paints_no_amber_or_red_of_its_own():
    bad = page_state_colours(VIEWS)
    assert not bad, "a page paints the attention or danger colour itself (tag/notice/workState instead): " + ", ".join(bad)
    slips = ".to-review { color: var(--attention); }\n.batch-error { color: var(--danger); }\n.x { border-left: 3px solid var(--attention-line); }"
    assert page_state_colours(slips) == [".to-review", ".batch-error", ".x"]


# A caution that asks nothing of you says what an answer rests on: it takes the info icon, grey, wherever it shows
# (docs/DESIGN.md 3.3, 4.10, 4.12). Amber with the triangle is for what needs you, so these words never wear it.
CALM_CAUTIONS = ("rests on one document", "rests on a single document")


def calm_cautions_in_amber(scripts: dict[str, str]) -> list[str]:
    """The tags and notices of kind attention whose own words are a calm caution."""
    pat = re.compile(r"""(?:tag|notice)\(\{\s*kind:\s*"attention"[^}]*\}\s*,\s*(?:h\("p",\s*\{\}\s*,\s*)?[`"']([^`"']*)""")
    return [f"{name}:{js.count(chr(10), 0, m.start()) + 1}: {m.group(1)}" for name, js in scripts.items()
            for m in pat.finditer(js) if any(c in m.group(1).lower() for c in CALM_CAUTIONS)]


def test_a_calm_caution_is_never_amber():
    bad = calm_cautions_in_amber(VIEW_JS)
    assert not bad, "a caution that asks nothing of you wears the attention look (tag({ icon: \"info\" }) instead):\n" + "\n".join(bad)
    slips = {"m.js": 'x.single_document ? tag({ kind: "attention" }, "rests on one document") : null',
             "r.js": 'notice({ kind: "attention" }, h("p", {}, "It rests on a single document."))',
             "ok.js": 'tag({ icon: "info" }, "rests on one document"), tag({ kind: "attention" }, "very short: is this the whole text?")'}
    assert [b.split(":")[0] for b in calm_cautions_in_amber(slips)] == ["m.js", "r.js"]


# The moved note's way back never repeats a button of the card's own row (docs/DESIGN.md 4.26). Changed on purpose in
# 0.17.0: after "Not about this" then another judgement, the note offered Back to “Not about this” beside the row's own
# "Not about this". The function is run in Node with a stand-in for GRADE_TEXT.
def _note_way_back_cases() -> dict:
    import json
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    js = VIEW_JS["result.js"]
    m = re.search(r"export function noteWayBack\([\s\S]*?\n}\n", js)
    assert m, "views/result.js has no noteWayBack(): the moved note's way back is decided inline"
    src = 'const GRADE_TEXT = { supports: "Supports", partially_supports: "Partly supports", refutes: "Contradicts" };\n'
    src += m.group(0).replace("export function", "function")
    src += """
const cases = {
  fromNotAbout: noteWayBack("not_relevant", "refutes", "ai"),
  fromNotAboutTakeBack: noteWayBack("not_relevant", null, "ai"),
  fromNotAboutReadByYou: noteWayBack("not_relevant", "refutes", "you"),
  fromSupports: noteWayBack("supports", "refutes", "ai"),
  fromAI: noteWayBack(null, "refutes", "ai"),
};
console.log(JSON.stringify(cases));
"""
    out = subprocess.run([node, "-e", src], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_the_moved_note_never_repeats_a_row_button():
    c = _note_way_back_cases()
    # the row of an excerpt the AI read has its own "Not about this": the note offers none
    assert c["fromNotAbout"] is None and c["fromNotAboutTakeBack"] is None
    # an excerpt only you read has no "Not about this" in its row: the note is its one way back there
    assert c["fromNotAboutReadByYou"] == "Back to “Not about this”"
    # another earlier judgement of yours is not in the row: the note names it
    assert c["fromSupports"] == "Back to “Supports”"
    # your earlier judgement was not your own: the row's Take back is the way back
    assert c["fromAI"] is None


# A tab's count (docs/DESIGN.md 4.5, 5.5): a drawer tab may carry one count tag in words; a page's view tabs and
# Settings' tabs carry none. The guide says so in 4.5, where tabs() is described, and no page passes a count to tabs.
def test_the_guide_and_tabs_agree_on_counts():
    guide = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    s45 = guide[guide.index("### 4.5 View tabs"):guide.index("### 4.6 Choices")]
    assert "No counts in tabs." not in s45, "4.5 forbids every count in tabs, but 5.5 and tabs() give a drawer tab one"
    assert "count" in s45 and "drawer tab" in s45, "4.5 does not say which tabs may carry a count"
    assert "t.count" in (STATIC / "lib.js").read_text(encoding="utf-8"), "tabs() no longer draws a tab's count: 5.5 needs it"
    pages = {n: js for n, js in VIEW_JS.items() if n not in ("design.js",)}
    bad = [n for n, js in pages.items() for m in re.finditer(r"(?:viewTabs|tabs)\(\{[^)]*?count:", js)]
    assert not bad, "a page passes a count to its view tabs or Settings' tabs: " + ", ".join(bad)


# The Documents list keeps its titles readable (docs/DESIGN.md 4.20): a title takes the row's room before its marks, and
# a long file name breaks only after _ or -, never before its extension.
# Changed on purpose in 0.17.0: overflow-wrap: anywhere on .doc-file let the table narrow the title column to ~20
# characters at 1,280 px. Changed on purpose in 0.18.2: the table became a list of one-line rows that open (no columns),
# and the file name moved into a row's panel.
def test_the_documents_title_column_keeps_its_room():
    assert rule(".doc-file").get("overflow-wrap") != "anywhere", ".doc-file breaks anywhere"
    assert re.fullmatch(r"1 1 \d+(\.\d+)?em", rule(".doc-main .doc-title").get("flex", "")), "a title has no room of its own in em"
    js = VIEW_JS["sources.js"]
    assert 'h("div", { class: "doc-title", title: d.title && d.file ?' in js, "the Documents title has no doc-title class"
    assert ".split(/(?<=[_.-])/)" not in js, "a file name breaks after its dot, before its extension"
    # no column hides anything: the list is no table, and every fact is named in the row's panel
    assert "docs-table" not in js and 'h("dt", {}, "Who may read it with AI")' in js


# The quote's yellow is the quote's only (docs/DESIGN.md 2 step 4, 3.1, 4.23): its look lives in components.css § 4.23,
# and no page or shell rule paints with --mark or --mark-line. Changed on purpose in 0.17.0: the Bibliography's naming
# words (now foundWords(), soft teal) and the pending sentence's message (now a notice) were yellow page boxes.
def test_the_quote_yellow_is_only_the_quotes():
    bad = [f"{name}: {', '.join(sels)}" for name in ("views.css", "app.css")
           for media, sels, decls in css_blocks((STATIC / name).read_text(encoding="utf-8"))
           if any(re.search(r"var\(--mark(-line)?\)", v) for v in decls.values())]
    assert not bad, "the quote's yellow outside components.css § 4.23: " + "; ".join(bad)


# A tag is a fact and is never pressed, so it holds no link; a link is teal, never muted grey (docs/DESIGN.md 1, 4.2,
# 4.10). Changed on purpose in 0.17.0: Documents' Note column drew "read badly" as a link inside an amber tag, and two
# grey links.
def links_in_tags_or_muted(js: str) -> list[int]:
    bad = [m.start() for m in re.finditer(r'tag\(\{[^}]*\}\s*,\s*(?:link\(|h\("a")', js)]
    bad += [m.start() for m in re.finditer(r'h\("a", \{[^}]*\bclass: "[^"]*\bmuted\b', js)]
    bad += [m.start() for m in re.finditer(r'link\(\{[^}]*\bclass: "[^"]*\bmuted\b', js)]
    return [js.count("\n", 0, i) + 1 for i in bad]


def test_no_link_inside_a_tag_and_no_muted_link():
    bad = [f"{n}:{line}" for n, js in VIEW_JS.items() for line in links_in_tags_or_muted(js)]
    assert not bad, "a link inside a tag, or a grey link: " + ", ".join(bad)
    slips = ['tag({ kind: "attention" }, link({ href }, "x"))', 'h("a", { class: "it muted small", href }, "x")',
             'link({ href, class: "muted" }, "x")', 'tag({ kind: "attention" }, "x"), " ", link({ href }, "Look")']
    assert [bool(links_in_tags_or_muted(j)) for j in slips] == [True, True, True, False]


# A field in a row of small buttons is small too (docs/DESIGN.md 4.8): the open code's foot in the codebook editor
# (Up, Down, Split, Remove, Merge into…) has one height.
def test_the_codebook_merge_select_is_small():
    m = re.search(r"const mergeSel = select\(\{([^}]*)\}", VIEW_JS["codebooks.js"])
    assert m and "sm: true" in m.group(1), "the codebook editor's Merge into… is a full-height select among small buttons"


# Every entry of the guide has the parts its head promises (docs/DESIGN.md 4, 5), so a builder with one question finds
# Not for where a misfit is prevented. A kinds table (its first column Kind, Field, Mark, State, Value or Piece) stands
# for Looks. Section 5's pieces each have one use, their place: they say Means, Looks and Lives in.
ENTRY_PARTS = {"4": ("Means", "Use", "Not for", "Looks", "Make it", "Lives in"), "5": ("Means", "Looks", "Lives in")}


def missing_entry_parts(guide: str) -> dict[str, list[str]]:
    out = {}
    parts = re.split(r"^### ([45])\.(\d+) .*$", guide, flags=re.M)
    for i in range(1, len(parts), 3):
        sec, body = parts[i], parts[i + 2].split("\n## ")[0]
        miss = [p for p in ENTRY_PARTS[sec] if f"**{p}:**" not in body and f"**{p}**" not in body]
        if "Looks" in miss and re.search(r"^\| (Kind|Field|Mark|State|Value|Piece) \|", body, re.M):
            miss.remove("Looks")
        if "Means" in miss and re.search(r"^\| [^|]+\| Means \|", body, re.M):
            miss.remove("Means")
        if miss:
            out[f"{sec}.{parts[i + 1]}"] = miss
    return out


def test_every_entry_has_its_parts():
    guide = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    bad = missing_entry_parts(guide)
    assert not bad, "entries without the parts the guide promises: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in bad.items())
    # and the check notices a part taken out
    assert missing_entry_parts(guide.replace("**Not for:** a message (a [notice]", "A message (a [notice]")) == {"4.11": ["Not for"]}


# The named exceptions are listed in the guide (docs/DESIGN.md 9.5) as in this test, so a reviewer can check them
# without reading Python: the guide's three tables and PAGE_BOXES, SOFT_TEAL_MEANS and DASHED name the same rules.
def test_the_guide_lists_the_named_exceptions():
    guide = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    s95 = guide[guide.index("### 9.5 Named exceptions"):guide.index("## 10 ")]
    tables = re.split(r"^\*\*", s95, flags=re.M)
    def named(title: str) -> set[str]:
        block = next(b for b in tables if b.startswith(title))
        return set(re.findall(r"^\| `([^`]+)` \|", block, re.M))
    for title, listed in (("Boxes a page still draws", PAGE_BOXES), ("Soft teal in a page's block", SOFT_TEAL_MEANS), ("Dashed edges", DASHED)):
        assert named(title) == set(listed), f"DESIGN 9.5 {title} and the test differ: {sorted(named(title) ^ set(listed))}"


# A field under its label (field()) is the standard size; sm is for a field in a row of controls (docs/DESIGN.md 4.8).
def small_fields_in_a_form(js: str) -> list[str]:
    ctl = r"(?:input|select|fieldInput|selectField|inputField)"
    bad = [m.group(0)[:60] for m in re.finditer(rf'field\("[^"]*", {ctl}\(\{{ sm: true', js)]
    for m in re.finditer(rf"const (\w+) = {ctl}\(\{{ sm: true", js):
        name = m.group(1)
        nxt = re.compile(rf"\b(?:const|let) {name} =").search(js, m.end())   # until the name is used again for another
        if re.search(rf'field\("[^"]*", {name}\b', js[m.end():nxt.start() if nxt else len(js)]):
            bad.append(name)
    return bad


def test_a_field_under_its_label_is_the_standard_size():
    bad = [f"{n}: {b}" for n, js in VIEW_JS.items() for b in small_fields_in_a_form(js)]
    assert not bad, "a small field under its label: " + ", ".join(bad)
    assert small_fields_in_a_form('const x = input({ sm: true });\nfield("Leave out", x, { help })') == ["x"]


def test_the_team_line_is_a_helper_the_guide_and_the_reference_name():
    """team-share piece B: the team line (lib.js teamLine()) is the project switch's second row, a button of the opens
    kind; the guide names it in 4.19 (the second door), 5.1 (its row) and 9.3 (the helpers), and #/design draws it."""
    assert re.search(r"export function teamLine\(\{ id, controls, onClick \}\)", LIB)
    line = LIB[LIB.index("export function teamLine("):LIB.index("export function setDrawerOpen(")]
    assert '"btn-opens team-line"' in line and '"aria-expanded": "false"' in line and '"aria-controls": controls' in line
    assert 'icon(kind === "attention" ? "alert-triangle" : "users", { size: 15 })' in line
    assert '"team-line-name" }, "Team"' in line and '"team-line-state"' in line and '"running-dot"' in line
    assert 'tag({ kind: "count", class: "tab-count" }, count)' in line
    assert "Opens the Team tab beside the page" in line
    s419 = GUIDE[GUIDE.index("### 4.19 The drawer"):GUIDE.index("### 4.20")]
    s51 = GUIDE[GUIDE.index("### 5.1 The sidebar"):GUIDE.index("### 5.2")]
    s93 = GUIDE[GUIDE.index("### 9.3 The helpers"):GUIDE.index("### 9.4")]
    assert "teamLine({ id, controls, onClick })" in s419 and "[team line](#51-the-sidebar)" in s419
    assert "| Team line |" in s51 and "The team line is not an entry" in s51
    assert "`teamLine()`" in s93
    assert "| My team on this project, and its state |" in GUIDE
    ref = VIEW_JS["design.js"]
    sample = ref[ref.index('sample("The team line'):ref.index('sample("Entries')]
    for state in ('words: "synced 15:44"', 'count: "3 new"', 'kind: "running", words: "syncing now…"', 'kind: "attention", words: "offline"'):
        assert state in sample, state
    # the sharing samples of 5.5: the maker's choice (built with choice(), as share.js shareChoice() builds it), and the
    # tag with the small buttons for rows and a colleague's item
    s55 = ref[ref.index('section("5.5"'):]
    assert 'sample("Sharing your own item: a choice' in s55 and 'sample("Sharing in a row, and a colleague\'s item' in s55
    share = ref[ref.index("const shareSample = "):ref.index("const navEntry = ")]
    assert "choice({" in share and '"Private"' in share and '"Shared with your team"' in share and '"share-where"' in share
