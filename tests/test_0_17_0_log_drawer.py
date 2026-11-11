"""0.17.0: the research log drawer (views/logdrawer.js), the panel beside every page.

- the JS: the export, the page-to-filter mapping (also run in Node when it is installed), the subject in the POST body,
  the fallback line;
- the API: an entry written with a subject comes back from the subject filter, and from no other.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_app import Api, api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static"
JS = (STATIC / "views" / "logdrawer.js").read_text(encoding="utf-8")
_NAV_CSS = (STATIC / "navigation.css").read_text(encoding="utf-8")
CSS = _NAV_CSS[_NAV_CSS.index("/* ==== the research log drawer"):]  # the drawer's rules, merged into navigation.css


def test_the_module_keeps_its_exports_and_reuses_the_log_page():
    assert re.search(r"export function initLogDrawer\(", JS)
    assert re.search(r"export function pageContext\(", JS)
    assert 'import { subjectHref } from "./log.js"' in JS
    assert "initLogDrawer" in (STATIC / "app.js").read_text(encoding="utf-8")


def test_the_mapping_is_written_for_every_page_kind():
    for needle in ('"check"', '"document"', '"themes"', '"codebook"', "documents", "checks", "codebooks"):
        assert needle in JS
    for route in ("sources", "notes", "bibliography", "hypotheses", "check", "batch", "history", "map", "profile", "codebooks"):
        assert re.search(rf"\b{route}: \"", JS), route


def test_the_post_carries_the_subject_and_the_words_match_the_brief():
    assert re.search(r'api\("POST", `/api/projects/\$\{P\(App\.project\)\}/log`, payload\)', JS)
    assert "payload.subject_kind = ctx.subject_kind" in JS and "payload.subject_id = ctx.subject_id" in JS
    assert "Nothing is kept with this page; showing all" in JS
    assert "A decision and why…" in JS and "Add to the log" in JS and "The whole research log" in JS
    assert "on the Overview" in JS and "Kept with: " in JS and "This page" in JS


def test_button_drawer_and_layout_are_wired():
    assert '"aria-expanded"' in JS and '"aria-label": "Research log"' in JS and 'h("aside"' in JS
    assert "Escape" in JS and "session(" in JS and "hashchange" in JS and "App.onChange" in JS
    assert "metaKey || e.ctrlKey" in JS
    # the drawer is a column beside the page (reserving its width) from 1000px, floats over it from 861px to 999px
    assert re.search(r"@media \(min-width: 1000px\) \{\s*body\.logdrawer-open \.shell \{ grid-template-columns:", CSS)
    assert "(min-width: 861px) and (max-width: 999px)" in CSS and "(max-width: 999px)" in JS
    assert "1200px" in CSS and "860px" in CSS and "72vh" in CSS and "position: fixed" in CSS
    # only the app's colour tokens, only logdrawer- class names
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", CSS)
    for sel in re.findall(r"\.([a-z][\w-]*)", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)):
        assert sel.startswith("logdrawer") or sel in {"main", "shell", "topbar-project", "icon-btn", "btn", "link-btn"} or sel[0].isdigit(), sel


def test_no_rule_styles_the_body_class_alone():
    """`logdrawer-open` is the class the open drawer puts on <body>. A rule for the bare class once also hit an entry's
    "Open" link (`.logdrawer-open { display: inline-block; margin-top: 3px }`), which made the whole page shrink-to-fit
    and 3px lower whenever the drawer was open: the page ran under the panel and its button was cut off. The entry's
    link has its own class, and the body class is used only after `body.`."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    assert not re.search(r"(?<!body)\.logdrawer-open\b", css)
    assert 'class: "logdrawer-open"' not in JS and 'class: "logdrawer-entry-link"' in JS
    assert re.search(r"\.logdrawer-entry-link \{", css)


NODE_CASES = {
    "#/h/abc": {"subject_kind": "check", "subject_id": "abc"},
    "#/doc/d1": {"subject_kind": "document", "subject_id": "d1"},
    "#/themes/run7": {"subject_kind": "themes", "subject_id": "run7"},
    "#/themes/run7/t3": {"subject_kind": "themes", "subject_id": "run7"},
    "#/codebooks/My%20book": {"subject_kind": "codebook", "subject_id": "My book"},
    "#/sources": {"group": "documents"}, "#/notes": {"group": "documents"}, "#/bibliography": {"group": "documents"},
    "#/hypotheses": {"group": "checks"}, "#/check": {"group": "checks"}, "#/batch": {"group": "checks"},
    "#/history": {"group": "checks"}, "#/map": {"group": "checks"},
    "#/themes": {"group": "themes"}, "#/profile": {"group": "codebooks"}, "#/codebooks": {"group": "codebooks"},
    "#/overview": None, "#/search": None, "#/concepts": None, "#/settings": None, "": None, "#/": None,
}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_page_context_in_node(tmp_path):
    (tmp_path / "views").mkdir()
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "views" / "logdrawer.js").write_text(JS)
    (tmp_path / "views" / "log.js").write_text("export const subjectHref = () => null;")
    (tmp_path / "lib.js").write_text("const n = () => {}; export const App = {}, api = n, h = n, icon = n, clear = n, session = n,"
                                     " fmt = {}, toast = n, showError = n, P = (x) => x;")
    (tmp_path / "run.mjs").write_text(
        'import { pageContext, whenText } from "./views/logdrawer.js";\n'
        f"const cases = {json.dumps(list(NODE_CASES))};\n"
        "const out = {}; for (const c of cases) { const r = pageContext(c); out[c] = r && (({ label, ...rest }) => rest)(r); }\n"
        "const lbl = [pageContext('#/h/x').label, pageContext('#/doc/x').label, pageContext('#/themes/r').label,"
        " pageContext('#/codebooks/Mine').label, pageContext('#/sources').label];\n"
        "const now = new Date(2026, 10, 9, 18, 0);\n"
        "const when = [whenText(new Date(2026, 10, 9, 9, 5).toISOString(), now), whenText(new Date(2026, 10, 8, 17, 26).toISOString(), now)];\n"
        "console.log(JSON.stringify({ out, lbl, when }));\n")
    got = json.loads(subprocess.run(["node", str(tmp_path / "run.mjs")], capture_output=True, text=True, check=True).stdout)
    assert got["out"] == NODE_CASES
    assert got["lbl"] == ["this hypothesis", "this document", "these themes", "Mine", "the project"]
    assert got["when"] == ["Today 09:05", "Yesterday 17:26"]


def test_an_entry_written_with_a_subject_comes_back_from_the_subject_filter(api):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    base = "/api/projects/Demo/log"
    st, r = api("POST", base, {"text": "Narrowed the wording.", "subject_kind": "check", "subject_id": "h123"})
    assert st == 200 and r["entry"]["subject_kind"] == "check" and r["entry"]["subject_id"] == "h123"
    assert api("POST", base, {"text": "Another hypothesis.", "subject_kind": "check", "subject_id": "h999"})[0] == 200
    assert api("POST", base, {"text": "About the project.", "subject_kind": None, "subject_id": None})[0] == 200
    st, r = api("GET", f"{base}?subject_kind=check&subject_id=h123")
    assert st == 200 and [e["text"] for e in r["entries"]] == ["Narrowed the wording."]
    st, r = api("GET", f"{base}?group=entries")
    assert r["total"] == 3
    st, r = api("GET", f"{base}?subject_kind=check&subject_id=nothing-here")
    assert r["entries"] == []
