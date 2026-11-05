"""0.13.6: the page's extension points (registry.js, static/extensions.js, docs/EXTENDING.md).

The stand-in add-on's page module (tests/fake_extension/enlens_fake_addon/static/extensions.js) adds a page, a sidebar
entry with its AI mark, an Overview section and card, a job kind, a welcome card and a result's link back to its
origin. The registry and the module run in Node, as the 0.13.2 tests do; the server lists the module for the page.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_app import api, home  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"
FAKE_PAGE = Path(__file__).with_name("fake_extension") / "enlens_fake_addon" / "static" / "extensions.js"
NODE = shutil.which("node")

STUB = """
globalThis.document = { querySelector: () => null, addEventListener() {}, documentElement: { dataset: {} } };
globalThis.window = globalThis; globalThis.location = { hash: "" };
globalThis.sessionStorage = { getItem: () => null, setItem() {} }; globalThis.localStorage = globalThis.sessionStorage;
"""


def _node(body: str, tmp_path: Path):
    f = tmp_path / "t.mjs"
    f.write_text(STUB + f"""
const reg = await import({json.dumps((STATIC / "registry.js").as_uri())});
const {{ FEATURES, SECTIONS }} = await import({json.dumps((STATIC / "features.js").as_uri())});
const local = (await import({json.dumps((STATIC / "extensions.js").as_uri())})).default;
const fake = (await import({json.dumps(FAKE_PAGE.as_uri())})).default;
const out = {{}};
{body}
console.log(JSON.stringify(out));
""")
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_enlens_alone_keeps_its_overview_and_jobs(tmp_path):
    out = _node("""
out.local = reg.applyExtensions(local, { FEATURES, SECTIONS });
out.sections = reg.overviewSections(FEATURES, SECTIONS);
out.rows = [
  reg.jobRow({ id: "j1", kind: "check", title: "Water use rises" }),
  reg.jobRow({ id: "j2", kind: "second-opinion", title: "Second opinion from opus on 3 hypotheses" }),
  reg.jobRow({ id: "j3", kind: "ingest", title: "Adding sources" }),
  reg.jobRow({ id: "j4", kind: "prepare", title: "Water" }),
  reg.jobRow({ id: "j5", kind: "nobody-knows", title: "Something an add-on runs" }),
];
out.batch = [reg.originLink({ batch_id: "b1" }), reg.originLink({ origin: "batch", origin_id: "b2", batch_id: "b2" }),
             reg.originLink({}), reg.originLink({ origin: "unknown", origin_id: "x" })];
""", tmp_path)
    assert out["local"] == {"sections": [], "features": [], "routes": 0, "jobKinds": [], "welcome": 0, "origins": []}
    # the Overview as 0.13.5 drew it: explore (four cards and "Read one document"), then check (compact); 0.13.7 adds
    # Check citations before Results
    assert [(s["key"], s["features"], s["compact"]) for s in out["sections"]] == [
        ("explore", ["search", "profile", "concepts", "themes", "sources"], False),
        ("check", ["check", "batch", "citations", "history"], True)]
    assert out["sections"][0]["sub"] == "Start here: no hypothesis needed."
    check, second, ingest, prepare, unknown = out["rows"]
    assert check == {"href": "#/check?job=j1", "icon": "flask", "text": "Water use rises", "tooltip": "Water use rises"}
    assert second["text"] == "Second opinion (3 hypotheses)" and second["href"] == "#/history?job=j2"
    assert ingest == {"href": "#/sources", "icon": "upload", "text": "Adding documents", "tooltip": None}
    assert prepare["text"] == "Look before checking (Water)" and prepare["href"] == "#/check"
    assert unknown["text"] == "Something an add-on runs" and unknown["icon"] == "circle"
    b_old, b_new, none, unknown_origin = out["batch"]
    assert b_old == {"eyebrow": None, "meta": "part of a set", "href": "#/history?batch=b1"} == {**b_new, "href": "#/history?batch=b1"}
    assert none is None and unknown_origin is None


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_stand_in_page_module(tmp_path):
    out = _node("""
out.added = reg.applyExtensions(fake, { FEATURES, SECTIONS });
out.again = reg.applyExtensions(fake, { FEATURES, SECTIONS });   // twice: nothing new, nothing replaced
out.sections = reg.overviewSections(FEATURES, SECTIONS).map((s) => [s.key, s.features, s.title, s.sub]);
out.check = FEATURES.check.title;
out.notes = { ...FEATURES.notes, state: FEATURES.notes.state({ fake_notes: 4 }) };
out.route = reg.PAGE_ROUTES.map(([rx, nav]) => [rx.source, nav, rx.test("/fake/notes")]);
out.job = reg.jobRow({ id: "j9", kind: "fake-labels", title: "Stand-in labels" });
out.welcome = reg.WELCOME_CARDS;
out.origin = reg.originLink({ origin: "fake-note", origin_id: "n 1" });
reg.JOB_KINDS["per-note"] = { icon: "tag", text: "A note's job", link: (j) => `#/fake/notes/${j.scope}`, withJob: true };
out.scoped = reg.jobRow({ id: "j8", kind: "per-note", scope: "n2" });
""", tmp_path)
    assert out["added"]["sections"] == ["notes"] and out["added"]["features"] == ["notes"]
    assert out["added"]["routes"] == 1 and out["added"]["jobKinds"] == ["fake-labels"]
    assert out["added"]["welcome"] == 1 and out["added"]["origins"] == ["fake-note"]
    assert out["again"]["features"] == [] and out["again"]["sections"] == []
    assert out["check"] == "Check a hypothesis"  # ENLENS's own entry is never replaced
    # the Overview gains the add-on's section, after ENLENS's, with its card and its own state line
    assert out["sections"][-1] == ["notes", ["notes"], "Your notes", "What you wrote down in the field."]
    assert [s[0] for s in out["sections"]] == ["explore", "check", "notes"]
    assert out["notes"]["state"] == [True, "4 notes"] and out["notes"]["nav"] is True and out["notes"]["ai"] == "optional"
    assert out["route"][0][1:] == ["notes", True]
    assert out["job"] == {"href": "#/fake/notes?job=j9", "icon": "tag", "text": "Stand-in labels", "tooltip": None}
    assert out["welcome"][0]["title"] == "Bring your field notes"
    assert out["scoped"]["href"] == "#/fake/notes/n2?job=j8"  # a link made from the job
    assert out["origin"] == {"eyebrow": "Back to the note", "meta": "from a note", "href": "#/fake/notes?note=n%201"}


def test_the_server_lists_an_addons_page_module(api, addon):  # noqa: F811
    st, s = api("GET", "/api/state")
    assert s["addon_pages"] == ["/static/addons/fake/extensions.js"]
    st, js = api("GET", "/static/addons/fake/extensions.js", token=False)
    assert st == 200 and b"export default" in js


def test_enlens_alone_lists_none(api):  # noqa: F811
    assert api("GET", "/api/state")[1]["addon_pages"] == []
    st, js = api("GET", "/static/extensions.js", token=False)
    assert st == 200 and b"export default {};" in js


def test_the_page_reads_the_registry():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'import localExtensions from "./extensions.js";' in app
    assert "applyExtensions(localExtensions, into)" in app and "await import(url)" in app
    assert "...ROUTES, ...PAGE_ROUTES" in app and "jobRow(j)" in app and "function addonNav()" in app
    for gone in ("const linkFor", "const kindIcon", "const kindText", "const withJob"):  # moved to registry.js
        assert gone not in app, gone
    assert "overviewSections(FEATURES, SECTIONS)" in (STATIC / "views" / "overview.js").read_text(encoding="utf-8")
    assert "originLink(r)" in (STATIC / "views" / "result.js").read_text(encoding="utf-8")
    assert "WELCOME_CARDS" in (STATIC / "views" / "setup.js").read_text(encoding="utf-8")
    local = (STATIC / "extensions.js").read_text(encoding="utf-8")
    assert "never edit" in local and "export default {};" in local
    ext = (ROOT / "docs" / "EXTENDING.md").read_text(encoding="utf-8")
    for name in ("static/extensions.js", "applyExtensions", "jobKinds", "origins", "welcome", "PAGE_ROUTES"):
        assert name in ext, name
