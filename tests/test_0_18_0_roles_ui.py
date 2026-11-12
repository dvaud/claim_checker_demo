"""Roles (DESIGN-roles §5, §7 P4) in the page: the Team tab's "Waiting for your word", "Settled at the same time",
"Removed in the last 30 days", the roles in the people list, the move question, linking another person's folder and
the codebook page's offer. Built as mock-up B ("one inbox, first") with the blind review's six changes and three
rules (review-ui/REVIEW.md).

- what the page works out, run in Node (owner-state.js, move-state.js) on views that follow P1's contract
  (roles_views.py): the order of the cards, the tab's number, every card's words;
- the files: the review's changes and rules where they are drawn (owner.js, team.js, projects.js, codebooks.js, lib.js,
  views.css), only the guide's helpers and tokens; the new helper in the guide's §9.3.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from roles_views import views

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


OWNER, STATE, TEAM = _read("views/owner.js"), _read("views/owner-state.js"), _read("views/team.js")
PROJECTS, MOVE, CODEBOOKS, LIB = _read("views/projects.js"), _read("views/move-state.js"), _read("views/codebooks.js"), _read("lib.js")
VIEWS = _read("views.css")


def _fn(src: str, start: str) -> str:
    i = src.index(start)
    j = src.find("\n}\n", i)
    return src[i:j]


# ------------------------------------------------------------------ what the page works out (Node)
NODE = r"""
import * as O from "./owner-state.js";
import * as M from "./move-state.js";
const V = JSON.parse(process.argv[2]);
const out = {};
for (const [k, v] of Object.entries(V)) {
  const b = O.inbox(v);
  out[k] = { count: O.tabCount(v), heading: O.heading(v, b.cards), cards: b.cards,
    order: [...b.bothWays.map((p) => "both:" + p.id), ...b.questions.map((q) => "q:" + q.kind), ...b.refused.map((r) => "refused:" + r.kind),
      ...b.offers.map((g) => "offers:" + g.list.length), ...b.deciding.map((p) => "p:" + p.id)],
    mine: b.mine.map((p) => p.id), mineHeading: b.mine.length ? O.mineHeading(b.mine) : null, settled: b.settled.map((c) => c.id),
    role: O.roleSentence(v), nothing: O.nothingWaits(v) };
}
const own = V.busy, mem = V.member;
const b = O.inbox(own);
out.take = O.questionWords(b.questions[0], own);
out.takeOther = O.questionWords({ ...b.questions[0], list: [{ ...b.questions[0].list[0], now: mem.owner }] }, { ...own, is_owner: false });
// (a copy never asks about its own record: it follows it at once, ownership.pin_owner; so Carol's copy)
const noOwner = { ...mem, owner: null, questions: [
  { id: "f1", seq: 1, kind: "founder", owner: "panna", by: "panna" }, { id: "f2", seq: 1, kind: "founder", owner: "pben", by: "pben" }] };
out.founders = O.questionWords(O.questionCards(noOwner)[0], noOwner);
out.founder = O.questionWords({ kind: "founder", ids: ["f2"], list: [{ id: "f2", seq: 1, kind: "founder", owner: mem.people[2], by: mem.people[2], now: mem.owner }] }, mem);
out.founderMine = O.questionWords({ kind: "founder", ids: ["f2"], list: [{ id: "f2", seq: 1, kind: "founder", owner: own.people[2], by: own.people[2], now: own.owner }] }, own);
out.refused = O.refusedWords(own.refused[0], own);
out.refusedOwner = O.refusedWords({ kind: "ownership", key: "3:pcarol", via: own.people[3], owner: own.people[3] }, own);
out.offers = [0, 1, 2].map((n) => O.offerWords(b.offers[0], own, n));
out.offerOne = O.offerWords(O.inbox(mem).offers[0], mem, 0);
out.both = O.bothWaysWords(own.proposals[0], own);
out.settled = b.settled.map((c) => O.settledWords(c, own));
out.removed = own.removed.map((r) => O.removedLine(r, own));
out.removedMember = O.removedLine(mem.removed[0], mem);
out.restored = [O.restoredText("Jobs", false), O.restoredText("Jobs", true)];
out.same = [O.samePersonLine(own.people[1], own), O.samePersonLine(mem.people[1], mem)];
out.order = O.peopleInOrder([{ id: "a" }, { id: "b" }, { id: "c", same_as: "a" }]).map((x) => x.id);
out.roleDlg = [O.roleDialogWords("Ben Okafor", "co"), O.roleDialogWords("Ben Okafor", "member")];
out.sameTitle = O.samePersonTitle("Anna de Vries (laptop)");
out.cb = O.codebookOfferText({ name: "Energy", from: { id: "pben", name: "Ben Okafor" }, labels: 40,
  events: [{ op: "rename", from: "A", to: "Water use" }, { op: "merge", from: "C", to: "B" }] });
out.wait = [O.waitingFor(mem), O.waitingFor({ owner: mem.owner, people: [] })];
out.old = { role: O.roleOf({ is_owner: true }), write: O.canWrite({ is_owner: false }), set: O.canSetRoles({ is_owner: true }) };
out.move = { sum: M.moveSummary({ made: "2026-11-12T10:00:00Z", version: "0.17.1", person: { name: "Dávid" }, projects: [{}, {}, {}] }),
  name: M.secondName({ person: { name: "Dávid" } }),
  servers: M.foreignServers({ servers: [{ key: "ollama_url", url: "http://localhost:11434", here: true }, { key: "embed_url", url: "https://gpu.lab.example", here: false }] }).map((s) => s.key),
  moved: M.movedText({ moved: { projects: [{ name: "A", from: "A" }, { name: "B (2)", from: "B" }], settings: true } }),
  link: [M.linkCleanTitle({ other: { name: "Anna" } }), M.linkCleanTitle({ other: null })] };
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def node(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("Node is not installed")
    d = tmp_path_factory.mktemp("roles-node")
    (d / "package.json").write_text('{"type": "module"}')
    for f in ("owner-state.js", "team-state.js", "move-state.js"):
        (d / f).write_text(_read(f"views/{f}"), encoding="utf-8")
    (d / "run.mjs").write_text(NODE, encoding="utf-8")
    r = subprocess.run([shutil.which("node"), str(d / "run.mjs"), json.dumps(views())], capture_output=True, text=True,
                       env={**os.environ, "TZ": "Europe/Amsterdam"})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_what_waits_comes_first_most_serious_first(node):
    o, busy = node["owner"], node["busy"]
    # a proposal answered both ways, the take-over, the refused change, Ben's offers (one card), then the proposals
    assert o["order"] == ["both:qjobs", "q:takeover", "refused:canon", "offers:2"]
    assert busy["order"] == ["both:qjobs", "q:takeover", "refused:canon", "offers:2", "p:qmayor", "p:qplant"]
    assert o["heading"] == "Waiting for your word (4)" and busy["heading"] == "Waiting for your word (6)"
    assert o["count"] == 4 and busy["count"] == 6        # the tab counts the cards; settled rows are not counted
    assert o["settled"] == ["c-ai", "c-state", "c-read", "c-blocks"]   # parts only: an answered-both-ways is its card
    e = node["empty"]
    assert e["order"] == [] and e["count"] == 0 and e["heading"] == "Waiting for your word"
    assert e["nothing"] == "Nothing waits for your word. Proposals, looser AI settings and questions about the owner come here first."


def test_a_members_view(node):
    m = node["member"]
    assert m["order"] == ["offers:1"] and m["count"] == 1 and m["heading"] == "Waiting for your word (1)"
    assert m["mine"] == ["qjobs"] and m["mineHeading"] == "Your proposals (1)"
    assert m["settled"] == []                             # settled rows are for the Owner and the Co-owners
    assert m["role"] == "You are a Member: your changes to the documents are proposals to Anna and the Co-owners."
    assert node["owner"]["role"] is None                  # the Owner's own copy says nothing
    assert node["wait"] == ["Waiting for Anna de Vries or a Co-owner.", "Waiting for Anna de Vries."]
    assert node["old"] == {"role": "owner", "write": False, "set": True}   # a view of before the roles reads as before


def test_the_questions_words(node):
    t = node["take"]
    # the review's change 4: tag "A take-over", no pronoun; in the owner's own copy, "Here you are still the owner"
    assert t["title"] == "Ben took the project over" and t["tag"] == "A take-over"
    assert t["said"] == "Nothing was heard of the owner for 14 days."
    assert t["text"] == "Here you are still the owner. If you follow Ben, Ben decides about the documents from now on."
    assert [a["label"] for a in t["answers"]] == ["Follow Ben", "Not now"] and t["answers"][1]["answer"] is None
    assert node["takeOther"]["text"] == "You follow Anna. If you follow Ben, Ben decides about the documents from now on."
    f = node["founders"]
    assert f["text"] == "Two people say they are this project’s first owner. Which do you follow?"
    assert [a["label"] for a in f["answers"]] == ["Follow Anna", "Follow Ben"] and [a["id"] for a in f["answers"]] == ["f1", "f2"]
    one = node["founder"]
    assert one["text"] == "This file names another first owner: Ben. You follow Anna."
    assert [(a["label"], a["answer"]) for a in one["answers"]] == [("Follow Ben", "follow"), ("Keep Anna", "keep")]
    mine = node["founderMine"]   # in the owner's own copy
    assert mine["text"] == "This file names another first owner: Ben. Here you are the owner."
    assert [a["label"] for a in mine["answers"]] == ["Follow Ben", "Stay the owner"]
    assert node["refused"]["text"] == ("Eszter’s file held a change to “Works council minutes, May” in your name. It was not "
                                       "taken, and your own word was sent again.") and node["refused"]["takeBack"] is False
    assert node["refusedOwner"] == {"title": "A change in your name was refused", "takeBack": True,
                                    "text": "Carol’s file says you handed the project to Carol. You did not: nothing was changed here."}


def test_the_ai_card_starts_unticked_and_counts(node):
    # the review's change 1 and rule (b): nothing ticked, both buttons wait; once ticked they count what they do
    none, one, two = node["offers"]
    assert none["ready"] is False and none["allow"] == "Allow here" and none["keep"] == "Keep stricter here"
    assert (one["allow"], one["keep"]) == ("Allow here for 1 document", "Keep 1 stricter here") and one["ready"]
    assert (two["allow"], two["keep"]) == ("Allow here for 2 documents", "Keep 2 stricter here")
    assert two["title"] == "Ben lets more AI read 2 documents" and two["here"] == "Here:" and two["theirs"] == "Ben’s:"
    assert "of the first" not in two["ai"] and "of the second" not in two["ai"] and two["where"] == "cloud"
    # one document: no box, one sentence, the two answers as in A
    s = node["offerOne"]
    assert s["one"] and s["ready"] and (s["allow"], s["keep"]) == ("Allow here", "Keep it stricter here")
    assert s["text"] == "Anna (owner) lets Claude read “Interview with a plant manager”. Here it stays Only a local AI until you say."
    assert s["ai"] == "Once allowed, Claude may read its excerpts."


def test_settled_rows_removals_and_restores(node):
    assert node["both"] == {"who": "Ben accepted it and Anna (laptop) declined it, neither knowing the other’s answer.",
                            "result": "the document stays in the project"}
    ai, state, read, blocks = node["settled"]
    assert ai["text"] == "You and Ben changed who may read it with AI at the same time. The stricter holds: No AI."
    # the review's change 4: the removed-and-kept row says where to remove it (the last words a link)
    assert state["text"] == "Ben removed it while Anna (laptop) kept it. It stays in the project."
    assert state["remove"] == "To remove it, use its menu on " and state["where"] == "Documents"
    assert read["text"] == "You and Ben each read it again at the same time. The newer reader’s reading holds."
    assert blocks["text"] == ("You and Ben each changed which passages are read at the same time. Ben’s choices hold, "
                              "with yours on top where they differ.")
    assert node["removed"] == [
        "Removed by you on 12 November: “A newer version is in the project.” Can be restored until 12 December.",
        "Removed by Ben (Co-owner) on 9 November: “The same notes as visit 1.” Can be restored until 9 December.",
        "Removed by Ben (Co-owner) on 20 October: “Not a source.” Can be restored until 19 November."]
    assert node["removedMember"].startswith("Removed by Anna (owner) on 12 November")
    assert node["restored"] == ["“Jobs” is back in the project.", "“Jobs” is back in your copy, and proposed to the owner."]


def test_the_people_list_and_its_dialogs(node):
    # the review's change 5: in a Member's view the same-person line names the person
    assert node["same"] == ["Also you: the same person", "Also Anna de Vries: the same person"]
    assert node["order"] == ["a", "c", "b"]                          # one person's rows stand together
    co, member = node["roleDlg"]
    assert co == {"title": "Make Ben a Co-owner?", "ok": "Make Co-owner", "body": [
        "Ben’s changes to the documents will hold for everyone at once, and Ben can accept or decline proposals. Only you "
        "set roles and hand the project over."]}
    assert member["title"] == "Make Ben a Member again?" and member["body"][1] == (
        "Changes of Ben’s that have not reached you yet come as proposals too.")
    # the review's change 6
    assert node["sameTitle"] == "Is Anna de Vries (laptop) the same person as someone here?"
    assert "rows" not in _fn(STATE, "export const SAME_PERSON_BODY").split("\n")[0]
    assert node["cb"] == "Ben renamed A to Water use and merged C into B. Follow for your 40 labels?"


def test_the_move_question(node):
    m = node["move"]
    assert m["sum"] == "3 projects, made on 12 November with ENLENS 0.17.1, by Dávid."
    assert m["name"] == "Dávid (2)" and m["servers"] == ["embed_url"]
    assert m["moved"] == "2 projects brought in, with the settings. Renamed because the name was taken: B → B (2)."
    assert m["link"] == ["This folder is Anna’s project.", "This folder is another person’s project."]


# ------------------------------------------------------------------ the files
def test_the_reviews_changes_where_they_are_drawn():
    # (2) a folder problem that stops this copy is the first section; "Waiting for your word" comes before the folder
    sections = TEAM[TEAM.index("export const TEAM_SECTIONS"):TEAM.index("];", TEAM.index("export const TEAM_SECTIONS"))]
    assert sections.index('"setup"') < sections.index('"stop"') < sections.index('"state"')
    assert 'addTeamSection(OWNER_SECTION, { before: "state" });' in TEAM and 'addTeamSection(REMOVED_SECTION, { before: "people" });' in TEAM
    assert 'const STOPS = new Set(["other_computer", "unreachable"]);' in TEAM and "Use both computers…" in TEAM
    # (3) a clash card: both buttons small and standard, neither main; Accept still asks first (the same accept())
    card = _fn(LIB, "export function proposalCard(")
    assert 'o.even ? button({ sm: true, onClick: o.onAccept }, "Accept")' in card
    assert 'kind: o.even ? "standard" : "quiet"' in card
    assert "even: !!both" in OWNER and "onAccept: (e) => accept(ctx, p, e.currentTarget)" in OWNER
    # rule (c): the clash is said once, as an error notice in the card; no tag repeats it
    assert "Answered both ways" not in _fn(OWNER, "function questionCard(") and OWNER.count('"Answered both ways."') == 1
    assert 'waiting: p.clash ? CLASH_WAITING : waitingFor(v)' in OWNER
    # (1) and rule (b): no Allow all; the boxes start unticked (the ticked set starts empty), the buttons wait
    assert "Allow all" not in OWNER + STATE
    assert 'checked: sel.has(o.doc)' in OWNER and "allow.disabled = keep.disabled = !w.ready;" in OWNER and "TICK_FIRST" in OWNER
    # (5) Make owner… last, after a line; one control per row; the name's line and the second line (views.css)
    menu = _fn(OWNER, "export function ownerMarks(")
    assert menu.index('"Make a Co-owner…"') < menu.index('"Same person as…"') < menu.index('"sep"') < menu.index('"Make owner…"')
    assert 'grid-template-areas: "mark name more" "sub sub sub"' in VIEWS
    assert "needs a newer ENLENS to act as Co-owner" in STATE and "0.18 to act" not in STATE   # no number (the brief)
    # (6) the move dialog: the reason "moving" is not offered stands under the cards, not in the dimmed card
    dlg = _fn(PROJECTS, "export function moveDialog(")
    assert "foot:" not in dlg and 'h("p", { class: "move-why" }, NOT_FRESH)' in dlg
    assert "disabled: !peek.fresh" in dlg and 'id: "move-go", disabled: true' in dlg   # Bring in waits for a card
    assert 'api("POST", "/api/move", { token, mode' in dlg
    # linking another person's folder asks first (409 with the report), then links with clean
    assert "e.status !== 409 || !(e.data && e.data.report)" in PROJECTS and "{ ...body, clean: true }" in PROJECTS


def test_a_question_with_two_answers_is_a_card():
    # rule (a): the codebook's Follow / Keep mine is a decision card, Follow the main button, Keep mine quiet
    i = CODEBOOKS.index("async function drawOffer()")
    offer = CODEBOOKS[i:CODEBOOKS.index("\n  }\n", i)]
    assert "decisionCard({" in offer and "notice(" not in offer
    assert 'button({ kind: "main", sm: true, id: "cb-offer-follow"' in offer and 'button({ kind: "quiet", sm: true, id: "cb-offer-keep"' in offer
    for name in ("questionCard", "refusedCard", "offerCard"):
        assert "decisionCard({" in _fn(OWNER, f"function {name}(")


def test_the_new_helper_is_the_guides():
    fn = _fn(LIB, "export function decisionCard(")
    assert 'class: ["proposal", attrs.class]' in fn and 'tag({ kind: "attention" }, o.flag)' in fn
    guide = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    helpers = guide[guide.index("### 9.3 The helpers"):guide.index("### 9.4")]
    assert "`decisionCard({ what, flag, person, time, said, body, actions, ai })`" in helpers
    assert "decisionCard(" in _read("views/design.js")       # the live reference draws it


def test_no_inline_look_and_only_tokens():
    for name, js in (("owner.js", OWNER), ("owner-state.js", STATE), ("move-state.js", MOVE)):
        assert "style:" not in js and ".style." not in js and "innerHTML" not in js, name
    # the pieces' placement: tokens only (no colour of its own)
    block = VIEWS[VIEWS.index("/* roles (DESIGN-roles §5, mock-up B)"):VIEWS.index("/* ==== Quick look */")]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", block) and "rgb(" not in block
    assert not re.search(r"^import ", MOVE, flags=re.M)      # Node-safe
    assert not re.search(r"^import ", STATE.replace('import { whenText } from "./team-state.js";', ""), flags=re.M)


def test_every_endpoint_the_page_calls_is_a_route():
    from enlens_claims.gui import server

    paths = {"PUT": ["/api/projects/P/owner/roles/x"], "POST": [
        "/api/projects/P/owner/questions/x", "/api/projects/P/owner/loosening", "/api/projects/P/owner/removed/d/restore",
        "/api/projects/P/owner/clashes/c", "/api/projects/P/owner/take-back", "/api/projects/P/owner/refused/k/x/dismiss",
        "/api/projects/P/codebooks/C/follow"], "GET": ["/api/projects/P/codebooks/C/offer"]}
    for method, ps in paths.items():
        for p in ps:
            assert any(m == method and rx.match(p) for m, rx, _ in server.ROUTES), (method, p)
    for frag in ("/owner/roles/${person}`", "/owner/questions/${id}`", "/owner/loosening`", "/owner/removed/${doc}/restore`",
                 "/owner/clashes/${id}`", "/owner/take-back`", "/owner/refused/${kind}/${key}/dismiss`", "/codebooks/${cb}/offer`",
                 "/codebooks/${cb}/follow`"):
        assert frag in STATE, frag
