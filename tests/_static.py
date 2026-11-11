"""Shared checks of the page's stylesheets (0.13.5).

index.html links ENLENS's stylesheets, then the marker `<!-- release stylesheets end -->`, then `site.css` (the
installation's own look) last. Since 0.17.0 they are four: tokens.css, app.css, components.css (one section per
component of docs/DESIGN.md) and views.css; a release adds no sheet of its own. A test that checks a rule reads the
cascade (all_css(), rule() below), never a sheet by name.
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


# ---- 0.17.0: the cascade, not the files -------------------------------------------------------------------------------
# A rule moves between ENLENS's sheets when the design guide (docs/DESIGN.md) folds a component into its one section; a
# test that checks a rule exists reads the cascade (every sheet above the marker, in link order), never a sheet by name.

def all_css(index: str | None = None) -> str:
    """ENLENS's stylesheets (not site.css), in index.html's link order, joined."""
    return "\n".join((STATIC / href.removeprefix("/static/")).read_text(encoding="utf-8")
                     for href in release_sheets(index))


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def css_blocks(css: str):
    """Every style rule of `css` as (media, selectors, declarations): media is the enclosing @media/@supports prelude
    ("" at the top level; nested ones joined with " && "), selectors the selector list split at its top-level commas
    (whitespace normalised), declarations the rule's body as {property: value} in order. @keyframes are skipped."""
    css = _strip_comments(css)
    out = []

    def block(i: int, media: str) -> int:
        n = len(css)
        while i < n:
            while i < n and css[i] in " \t\r\n":
                i += 1
            if i >= n:
                return i
            if css[i] == "}":
                return i + 1
            j = i
            while j < n and css[j] not in "{;":
                j += 1
            prelude = " ".join(css[i:j].split())
            if j >= n:
                return n
            if css[j] == ";":
                i = j + 1
                continue
            if prelude.startswith(("@media", "@supports")):
                i = block(j + 1, f"{media} && {prelude}" if media else prelude)
                continue
            depth, k = 1, j + 1
            while depth and k < n:
                depth += {"{": 1, "}": -1}.get(css[k], 0)
                k += 1
            if not prelude.startswith("@"):
                decls = {}
                for d in css[j + 1:k - 1].split(";"):
                    if ":" in d:
                        p, v = d.split(":", 1)
                        decls[p.strip()] = " ".join(v.split())
                sels = [" ".join(s.split()) for s in re.split(r",(?![^()]*\))", prelude)]
                out.append((media, sels, decls))
            i = k
        return i

    block(0, "")
    return out


def rule(selector: str, media: str | None = None, css: str | None = None) -> dict:
    """The declarations the cascade gives `selector`, merged property by property in link order (the later sheet wins).

    It matches the selector's text, not the browser's cascade: a rule counts when its selector list holds exactly
    `selector` (whitespace normalised), so rule(".btn") does not see `.result .btn`, and no specificity is computed.
    Rules inside an @media block count only when `media` names that block's query word for word
    (rule(".status-area", media="(max-height: 759px)")); media=None reads the top level only."""
    css = all_css() if css is None else css
    want = " ".join(selector.split())
    m = None if media is None else (media if media.startswith("@") else f"@media {media}")
    merged: dict = {}
    for med, sels, decls in css_blocks(css):
        if (med or None) == m and want in sels:
            merged.update(decls)
    return merged


def defined_tokens_all() -> set[str]:
    """Every custom property any ENLENS sheet defines (tokens.css holds them; the guard tests keep it so)."""
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", all_css()))


# ---- 0.17.0: a script as code only ------------------------------------------------------------------------------------
# A check that reads names and braces in a script must not be misled by a word inside a comment, a string or a regular
# expression. js_code() blanks those out, character for character, so positions and line numbers stay the script's own.

_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_AFTER_WORDS = {"return", "typeof", "case", "in", "of", "delete", "void", "throw", "new", "else", "do"}


def js_code(js: str) -> str:
    """`js` with its comments, strings, template text and regular expressions blanked (same length, newlines kept).
    The quotes stay, and so do the braces of a template's `${…}` and the code inside them, so the braces of the result
    balance exactly when the script's do."""
    out = list(js)
    n = len(js)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    def template_text(i: int) -> int:
        """From inside a template: blank its text up to its closing backtick or the next `${`; the index after it."""
        j = i
        while j < n:
            if js[j] == "\\":
                j += 2
            elif js[j] == "`":
                blank(i, j)
                return j + 1
            elif js.startswith("${", j):
                blank(i, j + 1)          # the "$" goes, the "{" stays
                interp.append(0)
                return j + 2
            else:
                j += 1
        blank(i, n)
        return n

    interp: list[int] = []   # for each `${` still open: the braces opened inside it
    i, last, word = 0, "", ""
    while i < n:
        c = js[i]
        if c in " \t\r\n":
            i += 1
        elif js.startswith("//", i):
            j = js.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif js.startswith("/*", i):
            j = js.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and js[j] != c and js[j] != "\n":
                j += 2 if js[j] == "\\" else 1
            blank(i + 1, j)
            i, last, word = min(j + 1, n), c, ""
        elif c == "`":
            i, last, word = template_text(i + 1), "`", ""
        elif c == "/" and (not last or last in _REGEX_AFTER or word in _REGEX_AFTER_WORDS):
            j, in_class = i + 1, False
            while j < n and js[j] != "\n" and (in_class or js[j] != "/"):
                if js[j] == "\\":
                    j += 1
                elif js[j] == "[":
                    in_class = True
                elif js[j] == "]":
                    in_class = False
                j += 1
            if j < n and js[j] == "/":      # a regular expression; otherwise a division sign after all
                blank(i + 1, j)
                j += 1
                while j < n and js[j].isalpha():
                    j += 1
                i, last, word = j, ")", ""
            else:
                i, last, word = i + 1, "/", ""
        elif c == "}" and interp and interp[-1] == 0:
            interp.pop()                    # the end of a `${…}`: the template's text goes on
            i, last, word = template_text(i + 1), "`", ""
        else:
            if interp and c in "{}":
                interp[-1] += 1 if c == "{" else -1
            if c.isalnum() or c in "_$":
                j = i
                while j < n and (js[j].isalnum() or js[j] in "_$"):
                    j += 1
                i, last, word = j, js[j - 1], js[i:j]
            else:
                i, last, word = i + 1, c, ""
    return "".join(out)
