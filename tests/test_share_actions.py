"""0.18.0 (roadmap L1): Share / Unshare on each item's own page, its state as a small tag, and whose it is
(views/share.js, and the item pages: a check, a set of themes, a codebook, notes, research log entries, links
between terms), and the two downloads (what you shared, or the whole project). Since the sharing choice (SPEC 3.1),
an item's maker has a choice on its page, Private | Shared with your team, and a line that says where it goes.

- static checks of the pages, as the other UI tests here do;
- the person mark's initials and an item's address, in Node when it is installed;
- through the API: the answers the share bar reads, sharing a check that needs its codebook (the page says so), a
  colleague's item refused, Unshare.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_app import api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static"


def _js(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


SHARE = _js("views/share.js")


# ------------------------------------------------------------------ the helper
def test_the_tag_says_private_shared_or_withdrawn_by_someone():
    assert 'private: "Private", shared: "Shared", withdrawn: "Withdrawn"' in SHARE
    assert "`Withdrawn by ${item.by}`" in SHARE
    assert 'role: "group", "aria-label": "Sharing with your team"' in SHARE        # the bar on an item's page
    assert "your colleagues get it with your work, through the team's storage space or shared folder, or in the file" \
           " “Send what you shared (.zip)”" in SHARE                                # SHARING_HELP names both ways and the file
    assert "only ${item.owner.name} can share it or take it back" in SHARE          # a colleague's item says whose
    assert "maker not known" in SHARE                                               # made before 0.18


def test_only_the_owner_gets_the_button_and_it_names_the_item():
    fn = SHARE[SHARE.index("export function shareButton"):]
    fn = fn[:fn.index("\n}\n")]
    assert "if (!item.can_change) return null;" in fn
    assert '"aria-label": `${label}: ${KIND_WORDS[item.kind] || "item"} “${name}”`' in fn
    assert '"Unshare"' in fn and '"Share again"' in fn and '"Share"' in fn
    # the focus goes back to the item's new button once the page is drawn again (a stable id per place)
    assert "const id = shareId(item, opts.idPrefix);" in fn and "if (onChanged) await onChanged(r);" in fn
    assert "document.getElementById(id)" in fn


def test_sharing_says_what_came_with_it_and_unsharing_asks_first():
    share = SHARE[SHARE.index("export async function shareItem"):SHARE.index("export async function unshareItem")]
    assert "r.also" in share and "is shared with it, so colleagues can read its codes" in share
    assert "r.cannot" in share and "is a colleague’s and not shared by them" in share
    unshare = SHARE[SHARE.index("export async function unshareItem"):SHARE.index("export function shareButton")]
    assert "askWhy(" in unshare and "marked as withdrawn by you" in unshare and "why: ok.why" in unshare
    assert 'api("POST", `/api/projects/${P(App.project)}/sharing/unshare`' in unshare


def test_the_whole_project_asks_first_and_warns_about_0_17():
    fn = SHARE[SHARE.index("export async function confirmWholeProject"):SHARE.index("export async function downloadProject")]
    assert "ENLENS 0.17.0rc5 or earlier sees all your private work" in fn and "Send what you shared instead" in fn
    zb = SHARE[SHARE.index("export function zipButton"):]
    assert 'if (scope === "shared") { downloadProject(project, "shared"); return; }' in zb
    assert "await confirmWholeProject(project)" in zb
    assert '"Send what you shared (.zip)"' in SHARE and '"Download the whole project (.zip)"' in SHARE


# ------------------------------------------------------------------ the sharing choice (SPEC 3.1)
def _fn(name: str) -> str:
    fn = SHARE[SHARE.index(f"export function {name}("):]
    return fn[:fn.index("\n}\n")]


def test_the_maker_has_a_choice_of_two_named_values():
    fn = _fn("shareChoice")
    assert "choice({ label: `Who sees this ${KIND_WORDS[item.kind] || \"item\"}`" in fn
    assert 'class: "share-choice"' in fn and "id," in fn and "sm:" not in fn            # the normal size
    # an arrow key must not share an item by itself: two pressed-state buttons, not a radio group (SPEC 3.7)
    assert "filter: true" in fn
    assert '[icon("house", { size: 13 }), "Private"]' in fn
    assert '[icon("users", { size: 13 }), opts.team ? "Shared with your team" : "Shared"]' in fn
    assert '"Only you see it"' in fn and '"Your team gets it with your work"' in fn and '"Colleagues get it with your work"' in fn
    # sharing, or taking back after the dialog; cancelled or failed: the choice is set back and the focus stays on it
    assert 'v === "shared" ? await shareItem(item) : await unshareItem(item)' in fn
    assert 'if (v === "private") c.set(now);' in fn                                     # the choice stays until the answer
    assert "if (!r) {\n        c.set(now);" in fn and "b.disabled = false" in fn and "back.focus()" in fn
    assert "if (onChanged) await onChanged(r);" in fn and "document.getElementById(id)" in fn
    assert 'again.querySelector(\'[aria-pressed="true"]\')' in fn
    assert re.search(r"^import \{[^}]*\bchoice, icon, link\b[^}]*\} from \"\.\./lib\.js\";", SHARE, flags=re.M)


def test_the_bar_draws_the_choice_for_the_maker_only():
    fn = _fn("shareBar")
    mine = fn[fn.index("if (!item.can_change) {"):]
    theirs, maker = mine[:mine.index("} else {")], mine[mine.index("} else {"):]
    assert "shareChoice" not in theirs and "shareTag(item), ownerMark(item)" in theirs
    assert "only ${item.owner.name} can share it or take it back" in theirs
    # after a change the brief is read again: sharing moves the next round closer
    assert "shareChoice(item, async () => { forgetBrief(App.project); await load(); if (opts.onChange) opts.onChange(); }," in maker
    assert "{ team: !!(brief && brief.team) }" in maker
    assert 'item.state === "withdrawn" ? shareTag(item) : null' in maker
    assert "!item.mine && !item.owner ? ownerMark(item) : null" in maker                # "maker not known"
    assert "help, shareWhere(item, brief)" in maker
    assert "shareButton(" not in fn                                                     # no small button on the item's page
    # the item and the team's brief read together; a brief that fails leaves the bar drawn
    assert "await Promise.all([api(\"GET\", `/api/projects/${P(project)}/sharing/${kind}/${P(key)}`)," in fn
    assert "teamBrief(project).catch(() => null)" in fn
    assert 'import { teamBrief, forgetBrief, whenPhrase, inText, ms } from "./team-state.js";' in SHARE


def test_the_line_says_where_a_shared_item_goes():
    fn = _fn("shareWhere")
    assert "Taken back: colleagues keep what they had, marked as withdrawn." in fn
    assert "No team yet: it goes to colleagues in the file “Send what you shared (.zip)”. " in fn
    assert 'link({ href: "#/team" }, "Set up a team")' in fn
    assert "`Sent to your team ${whenPhrase(brief.sentAt)}.`" in fn
    assert '`Goes to ${brief.names} at the next round${brief.nextAt ? ", " + inText(brief.nextAt) : ""}.`' in fn
    assert 'link({ kind: "jump", class: "share-see"' in fn and '"See what you shared"' in fn
    assert 'new CustomEvent("enlens-drawer", { detail: { tab: "team", section: "shared" } })' in fn
    css = (STATIC / "views.css").read_text(encoding="utf-8")
    block = css[css.index("/* ==== Working together */"):]
    assert ".share-bar .share-where { flex: 1 1 100%; margin: 0; color: var(--text-2); font-size: var(--fs-small); }" in block


def test_lists_and_the_team_tab_keep_the_small_buttons():
    assert "shareButton(item, onChanged, { link: true })" in _fn("shareInline")
    team = _js("views/team.js")
    assert "shareButton(it, () => ctx.refresh({ force: true }), { link: true, idPrefix: \"team\" })" in team


SHARE_WHERE_NODE = r"""
import { shareWhere, shareChoice } from "./views/share.js";
const NOW = Date.now();
const iso = (s) => new Date(NOW + s * 1000).toISOString();
const text = (n) => n === null || n === undefined ? null : typeof n === "string" ? n
  : Array.isArray(n) ? n.map(text).join("") : n.link ? `[${text(n.c)}${n.link.href ? " -> " + n.link.href : ""}]` : text(n.c);
const team = { team: true, names: "Ben and Chloé", nextAt: iso(120), sentAt: iso(-3600) };
let seen = null;
window.addEventListener = () => {};
window.dispatchEvent = (e) => { seen = e.detail; };
const shared = { kind: "check", key: "h1", state: "shared", at: iso(-60) };
const line = shareWhere(shared, team);
line.c[2].link.onClick();
const pick = shareChoice({ kind: "themes", key: "r 1", state: "withdrawn" }, null, { team: true });
console.log(JSON.stringify({
  waits: text(line), sent: text(shareWhere({ ...shared, at: iso(-7200) }, { ...team, sentAt: iso(-60) })),
  noNext: text(shareWhere(shared, { ...team, nextAt: null })),
  noTeam: text(shareWhere(shared, null)), noTeam2: text(shareWhere(shared, { team: false })),
  withdrawn: text(shareWhere({ ...shared, state: "withdrawn" }, team)), private: shareWhere({ ...shared, state: "private" }, team),
  detail: seen, cls: line.attrs.class,
  pick: { label: pick.label, value: pick.value, id: pick.id, filter: pick.filter, sm: pick.sm || false,
    words: pick.options.map((o) => [o[0], text(o[1])]) },
  noTeamWords: shareChoice({ kind: "check", key: "h1", state: "shared" }, null, {}).options.map((o) => text(o[1])),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_the_line_and_the_choice_in_node(tmp_path):
    (tmp_path / "views").mkdir()
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "views" / "share.js").write_text(SHARE, encoding="utf-8")
    (tmp_path / "views" / "versions.js").write_text("export const askWhy = () => null;")
    (tmp_path / "views" / "team-state.js").write_text(_js("views/team-state.js"), encoding="utf-8")
    # a lib.js whose h() and link() make plain objects, and whose choice() gives back what it was asked for
    (tmp_path / "lib.js").write_text(
        "const n = () => {}; globalThis.window = globalThis.window || {};"
        " globalThis.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = o.detail; } };"
        " export const App = {}, api = n, icon = () => '', replace = n, toast = n, showError = n, P = (x) => x,"
        " shortTitle = (x) => x, helpMark = n, download = n, dialog = n, button = n, downloadButton = n, notice = n,"
        " tag = n, personMark = n, shareState = n;"
        " export const h = (t, attrs, ...c) => ({ t, attrs, c });"
        " export const link = (o, ...c) => ({ link: o, c });"
        " export const choice = (o) => ({ ...o, set: n });", encoding="utf-8")
    (tmp_path / "run.mjs").write_text(SHARE_WHERE_NODE, encoding="utf-8")
    r = subprocess.run([shutil.which("node"), str(tmp_path / "run.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["waits"] == "Goes to Ben and Chloé at the next round, in about 2 min. [See what you shared]"
    assert got["sent"].startswith("Sent to your team today at ") and got["sent"].endswith(". [See what you shared]")
    assert got["noNext"] == "Goes to Ben and Chloé at the next round. [See what you shared]"
    assert got["noTeam"] == got["noTeam2"] == ("No team yet: it goes to colleagues in the file “Send what you shared (.zip)”. "
                                               "[Set up a team -> #/team]")
    assert got["withdrawn"] == "Taken back: colleagues keep what they had, marked as withdrawn."
    assert got["private"] is None and got["cls"] == "share-where"
    assert got["detail"] == {"tab": "team", "section": "shared"}
    assert got["pick"] == {"label": "Who sees this set of themes", "value": "private", "id": "share-themes-r_1", "filter": True,
                           "sm": False, "words": [["private", "Private"], ["shared", "Shared with your team"]]}
    assert got["noTeamWords"] == ["Private", "Shared"]


# ------------------------------------------------------------------ the item pages
def test_each_item_page_has_its_share_state():
    result, themes, codebooks = _js("views/result.js"), _js("views/themes.js"), _js("views/codebooks.js")
    # 0.17.0 (design guide 4.14): the check's share state is in its page head, pageHead({ …, meta: sharing }), not a row
    # after the head as before
    assert 'const sharing = shareBar("check", hypId);' in result and "meta: sharing }));" in result
    assert 'const sharing = shareBar("themes", runId);' in themes and "}), sharing);" in themes
    assert 'cb.where === "bundled" ? null : shareBar("codebook", cb.name)' in codebooks and "}), sharing);" in codebooks
    notes, log, concepts = _js("views/notes.js"), _js("views/log.js"), _js("views/concepts.js")
    assert 'sharingOf("note")' in notes and "share: data.shares && data.shares.get(n.note_id)" in notes
    assert 'sharingOf("log")' in log and 'e.kind === "entry" && shares.get(e.entry_id)' in log
    assert 'sharingOf("link")' in concepts and '[lk.a, lk.b].sort().join("|")' in concepts


def test_a_colleagues_judgement_note_and_entry_show_whose():
    result, notes, log = _js("views/result.js"), _js("views/notes.js"), _js("views/log.js")
    # 0.17.0's person mark (lib.js personMark(people)): the person icon and initials, the full name its tooltip
    assert result.count("who ? personMark([who])") == 2
    # a colleague's note and log entry: the mark stands alone (nothing else there names them), so it shows the name
    # (DESIGN.md 5.5, personMark(…, { name: "short" })); before, the initials only
    assert 'n.mine ? null : personMark([n.who], { name: "short" })' in notes
    assert 'e.mine ? null : personMark([e.who], { name: "short" })' in log and "entryWho(e)" in log
    # a shared item's maker shows the name too: "By Anna"
    assert 'personMark([item.owner.name], { name: "short", prefix: "By" })' in SHARE


def test_the_download_places_say_which_zip_they_give():
    projects, result = _js("views/projects.js"), _js("views/result.js")
    assert "Download as a zip" not in projects
    assert 'zipButton(p.name, "shared", { text: "Send what you shared" })' in projects
    assert 'zipButton(p.name, "all", { text: "Download the whole project"' in projects
    # the storage space or shared folder is set up on the Team page (#/team); Join a team… is in the project menu
    assert 'link({ href: "#/team" }, "Team page")' in projects and "Join a team… in the project menu" in projects
    assert 'zipButton(project, "shared", { text: "What you shared (.zip)"' in result
    assert 'zipButton(project, "all", { text: "Whole project (.zip)"' in result
    assert "Everything, to share or move." not in result


# ------------------------------------------------------------------ Node: initials and addresses
NODE = r"""
import { itemHref } from "./views/share.js";
import { initials } from "./initials.js";
console.log(JSON.stringify({
  ini: ["Anna de Vries", "Ben Okafor", "Chloé Martin", "anna", "a colleague", "you", "  ", "Jean-Luc Picard", "李 小龙", "Dr. Ngozi Okonjo-Iweala"].map(initials),
  href: [{ kind: "check", key: "h1" }, { kind: "themes", key: "r 1" }, { kind: "codebook", key: "My book" }, { kind: "note", key: "n1" },
         { kind: "log", key: "e1" }, { kind: "link", key: "t1|t2" }, { kind: "check", key: "h2", here: false }].map(itemHref),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_initials_and_addresses_in_node(tmp_path):
    (tmp_path / "views").mkdir()
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "views" / "share.js").write_text(SHARE, encoding="utf-8")
    (tmp_path / "views" / "versions.js").write_text("export const askWhy = () => null;")
    (tmp_path / "views" / "team-state.js").write_text(_js("views/team-state.js"), encoding="utf-8")
    (tmp_path / "lib.js").write_text("const n = () => {}; export const App = {}, api = n, h = n, icon = n, replace = n, toast = n,"
                                     " showError = n, P = (x) => x, shortTitle = (x) => x, helpMark = n, download = n, dialog = n,"
                                     " button = n, downloadButton = n, notice = n, tag = n, personMark = n, shareState = n,"
                                     " choice = n, link = n;")
    # 0.17.0 (design guide): the person mark is lib.js personMark(), which takes 0.18's initials: the function, as it is
    lib = _js("lib.js")
    fn = lib[lib.index("export function initials(name)"):]
    (tmp_path / "initials.js").write_text(fn[:fn.index("\n}\n") + 3], encoding="utf-8")
    (tmp_path / "run.mjs").write_text(NODE, encoding="utf-8")
    got = json.loads(subprocess.run([shutil.which("node"), str(tmp_path / "run.mjs")], capture_output=True, text=True, check=True).stdout)
    assert got["ini"] == ["AV", "BO", "CM", "A", "", "", "", "JP", "李小", "DO"]
    assert got["href"] == ["#/h/h1", "#/themes/r%201", "#/codebooks/My%20book", "#/notes", "#/log", "#/concepts/t1", None]


# ------------------------------------------------------------------ through the API, as the page uses it
def test_share_and_unshare_as_the_page_does(api, tmp_path, monkeypatch):  # noqa: F811
    import os

    from enlens_claims import bundle, claimcheck, codebooks, home as home_mod, ingest, people, sharing
    from enlens_claims.llm import BaselineBackend

    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    home_mod.update_settings({"your_name": "Anna"})
    ws = home_mod.open_project("Demo")
    ingest.ingest(ws, [Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"])
    codebooks.create(ws, "mine", title="Mine")
    hid = claimcheck.check_hypothesis(ws, "Remote work reduces commuting emissions.", BaselineBackend(), "baseline", k=2)
    with ws.connect() as cx:
        cx.execute("UPDATE hypotheses SET framework='mine', code='a' WHERE hyp_id=?", (hid,))

    # the bar reads one item: private, yours, the button there
    st, r = api("GET", f"/api/projects/Demo/sharing/check/{hid}")
    it = r["item"]
    assert st == 200 and it["state"] == "private" and it["mine"] is True and it["can_change"] is True and it["here"] is True
    assert {"title", "owner", "by", "at", "needs"} <= set(it) and it["needs"] == [{"kind": "codebook", "key": "mine"}]
    assert api("GET", "/api/projects/Demo/sharing/check/h-nothing")[0] == 404             # the bar stays hidden
    assert api("GET", "/api/projects/Demo/sharing/codebook/sdg")[0] == 404                 # a bundled codebook is no item

    # Share: the check, and its codebook with it (the toast says so)
    st, r = api("POST", "/api/projects/Demo/sharing/share", {"items": [{"kind": "check", "key": hid}]})
    assert st == 200 and [x["key"] for x in r["shared"]] == [hid] and [(x["kind"], x["key"]) for x in r["also"]] == [("codebook", "mine")]
    st, r = api("GET", "/api/projects/Demo/sharing?kind=codebook")
    assert {i["key"]: i["state"] for i in r["items"]} == {"mine": "shared"}

    # Unshare, with the why the dialog asks for: withdrawn by you
    st, r = api("POST", "/api/projects/Demo/sharing/unshare", {"items": [{"kind": "check", "key": hid}], "why": "not ready"})
    assert st == 200 and [x["key"] for x in r["withdrawn"]] == [hid]
    st, r = api("GET", f"/api/projects/Demo/sharing/check/{hid}")
    assert r["item"]["state"] == "withdrawn" and r["item"]["by"] == "you"
    st, r = api("GET", "/api/projects/Demo/log?group=together")
    assert any(e["kind"] == "unshared" and e["why"] == "not ready" for e in r["entries"])

    # a colleague's check: whose it is, no button, and the server refuses all the same
    zip_path = tmp_path / "demo.zip"
    bundle.export_project(ws, zip_path)
    me_home = os.environ["ENLENS_HOME"]
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home-ben"))
    try:
        home_mod.update_settings({"your_name": "Ben"})
        ben_id = people.me()
        ben = bundle.import_project(zip_path, tmp_path / "ben-project")
        hb = claimcheck.check_hypothesis(ben, "Cycling lanes cut car trips.", BaselineBackend(), "baseline", k=2)
        sharing.share(ben, [{"kind": "check", "key": hb}])
        back = tmp_path / "ben.zip"
        bundle.export_project(ben, back, scope="shared")
    finally:
        monkeypatch.setenv("ENLENS_HOME", me_home)
    st, r = api("POST", "/api/projects/Demo/bring-in", raw=back.read_bytes(), headers={"Content-Type": "application/octet-stream"})
    assert st == 200, r
    st, r = api("GET", f"/api/projects/Demo/sharing/check/{hb}")
    it = r["item"]
    assert it["state"] == "shared" and it["mine"] is False and it["can_change"] is False
    assert it["owner"] == {"id": ben_id, "name": "Ben"}
    st, r = api("POST", "/api/projects/Demo/sharing/unshare", {"items": [{"kind": "check", "key": hb}]})
    assert st == 403 and "Ben" in r["error"]
