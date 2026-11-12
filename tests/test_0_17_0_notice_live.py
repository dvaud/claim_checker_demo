"""0.17.0: a notice drawn with the page is read with the page; one that comes of what you just did is announced
(docs/DESIGN.md 4.12, 8).

lib.js builds the DOM, so Node runs it here with the stand-in document of tests/_fakedom.py.
"""
from __future__ import annotations

import re

import pytest

from _fakedom import NODE, STATIC, run

VIEW_JS = {p.name: p.read_text(encoding="utf-8") for p in sorted((STATIC / "views").glob("*.js"))}

PROBE = r"""
const { notice, noticeList } = await import(LIB);
const r = (o) => { const n = notice(o, "x"); return { role: n.getAttribute("role"), live: n.getAttribute("live") }; };
const list = noticeList([{ kind: "error", text: "A round failed." }, { kind: "attention", text: "Needs a newer ENLENS." }, { kind: "error", text: "Now.", live: "alert" }]);
const listRoles = [];
(function walk(n) { for (const c of n.children || []) { if ((c.getAttribute("class") || "").split(" ").includes("notice")) listRoles.push(c.getAttribute("role")); walk(c); } })(list);
console.log(JSON.stringify({
  attention: r({ kind: "attention" }), error: r({ kind: "error" }), info: r({ kind: "info" }), done: r({ kind: "done" }),
  attentionStatus: r({ kind: "attention", live: "status" }), doneStatus: r({ kind: "done", live: "status" }),
  errorQuiet: r({ kind: "error", live: false }), ownRole: r({ kind: "attention", role: "note" }), listRoles,
}));
"""


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_a_notice_is_live_only_when_it_comes_of_an_action(tmp_path):
    p = run(PROBE, tmp_path)
    # drawn with the page: no live role, so a screen reader does not interrupt on every page it opens
    assert p["attention"]["role"] is None and p["info"]["role"] is None and p["done"]["role"] is None
    # an error is still an alert; live says otherwise where it must
    assert p["error"]["role"] == "alert" and p["errorQuiet"]["role"] is None
    # what came of an action: a status, whatever its kind
    assert p["attentionStatus"]["role"] == "status" and p["doneStatus"]["role"] == "status"
    # live is an option, never an attribute; a role given by the page wins
    assert all(v["live"] is None for k, v in p.items() if k != "listRoles")
    assert p["ownRole"]["role"] == "note"
    # a list of problems stands in its place: no row is an alert unless its live says so
    assert p["listRoles"] == [None, None, "alert"]


# A notice that lands in a container already marked aria-live is read by the container: it takes no live of its own,
# and an error there says live: false, or a screen reader may read it twice. Changed on purpose in 0.17.0: this replaces
# a test that pinned how many notices each page marked live: "status", which failed on any honest edit and caught no
# missing case. The notices of a few functions land in a live container through a list or a helper; they are named here.
LANDS_IN_LIVE = {"settings.js": ["testResult", "plainTestResult"], "sources.js": ["ingestSummary"]}


def live_containers(js: str) -> set[str]:
    return set(re.findall(r'const (\w+) = h\("\w+", \{[^}]*"aria-live"', js))


def statement(js: str, start: int) -> str:
    """From start to the end of its statement: the first line that ends with a semicolon."""
    end = re.compile(r";[ \t]*(//[^\n]*)?\n").search(js, start)
    return js[start:end.end() if end else len(js)]


def function_body(js: str, name: str) -> str:
    m = re.search(rf"^([ \t]*)(?:export )?function {name}\(", js, re.M)
    assert m, f"no function {name}()"
    return js[m.start():js.index(f"\n{m.group(1)}}}\n", m.start())]


def doubled_notices(name: str, js: str) -> list[str]:
    """Each notice that lands in a live container and announces itself too."""
    bad = []
    def check(text: str, at: int, where: str) -> None:
        for m in re.finditer(r"notice\(\{([^}]*)\}", text):
            o = m.group(1)
            line = js.count("\n", 0, at + m.start()) + 1
            if re.search(r'\blive: "', o):
                bad.append(f"{name}:{line} {where}: live in a live container")
            elif 'kind: "error"' in o and "live: false" not in o:
                bad.append(f"{name}:{line} {where}: an error (an alert) in a live container")
    for box in live_containers(js):
        for m in re.finditer(rf"replace\({box}, ", js):
            check(statement(js, m.start()), m.start(), f"replace({box}, …)")
    for fn in LANDS_IN_LIVE.get(name, []):
        body = function_body(js, fn)
        check(body, js.index(body), f"{fn}()")
    return bad


def test_no_live_notice_inside_a_live_container():
    bad = [b for name, js in VIEW_JS.items() for b in doubled_notices(name, js)]
    assert not bad, "\n".join(bad)


def test_the_live_container_guard_catches_what_it_claims():
    slips = {
        "a.js": 'const out = h("div", { "aria-live": "polite" });\nreplace(out, notice({ kind: "done", live: "status" }, h("p", {}, "x")));\n',
        "b.js": 'const area = h("div", { class: "x", "aria-live": "polite" });\nreplace(area, ok\n  ? notice({ kind: "done" }, "a")\n  : notice({ kind: "info", live: "status" }, "b"));\n',
        "c.js": 'const out = h("div", { "aria-live": "polite" });\ntry { } catch (e) { replace(out, notice({ kind: "error" }, h("p", {}, e.message))); }\n',
        "ok.js": 'const box = h("div", {});\nreplace(box, notice({ kind: "done", live: "status" }, "x"));\n'
                 'const out = h("div", { "aria-live": "polite" });\nreplace(out, notice({ kind: "error", live: false }, "y"));\n',
    }
    assert [n for n, js in slips.items() if doubled_notices(n, js)] == ["a.js", "b.js", "c.js"]
