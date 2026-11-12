"""0.18.0 (roadmap L2): one owner, several collaborators, in the page (views/owner.js, views/owner-state.js, the block
"Working together" of views.css, marked lines in views/team.js and views/sources.js).

- the files and how they are wired: its look in 0.17.0's stylesheets (the components, placed in views.css), the
  section added before the people
  with its own data and number, the Owner mark and Make owner… in the people list, the Documents page's chip, toast
  and removal question; only today's components and tokens; keyboard and screen reader;
- the words of the plan (§8) in the files;
- what the page works out, run in Node when it is installed (owner-state.js): which proposals show where, the heading,
  the tab's number, a card's lines by kind, an answer in words, the Documents page's chip and toast;
- the app's answers have the fields the page reads (GET …/owner, `documents[].proposal`, `proposed`).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from _static import defined_tokens, release_sheets
from test_app import api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


OWNER = _read("views/owner.js")
STATE = _read("views/owner-state.js")
TEAM = _read("views/team.js")
SOURCES = _read("views/sources.js")
VIEWS = _read("views.css")
# 0.17.0 (design guide): owner.css is folded into views.css's block "Working together"
CSS = VIEWS[VIEWS.index("/* ==== Working together */"):VIEWS.index("/* ==== Quick look */")]
INDEX = _read("index.html")


def _no_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _marked(src: str, mark: str = "0.18 L2") -> list[str]:
    return [ln for ln in src.splitlines() if mark in ln]


# ------------------------------------------------------------------ files and wiring
def test_the_owner_has_its_rules_in_the_views_stylesheet():
    # 0.17.0 (design guide): no stylesheet of its own; its pieces are placed in views.css's block "Working together"
    sheets = release_sheets()
    assert "/static/owner.css" not in sheets and "owner.css" not in INDEX and not (STATIC / "owner.css").exists()
    css = _no_comments(CSS)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and "rgb(" not in css and "hsl(" not in css  # tokens only
    assert set(re.findall(r"var\((--[a-z0-9-]+)", css)) <= defined_tokens()
    owner = [sel for sel in re.findall(r"\.([a-z][\w-]*)", css) if sel.startswith("owner-")]
    # 0.17.0: the reason is asked in a dialog (owner-dlg-field), no longer in a field inside the card (owner-reason);
    # the card's own line under its head is owner-line
    assert {"owner-cards", "owner-line", "owner-dlg-field", "owner-setting"} <= set(owner)
    for sel in re.findall(r"\.(owner-[\w-]*)[^{]*\{", css):   # its own names; the components it holds it only places
        assert sel.startswith("owner-"), sel


def test_the_section_comes_before_the_people_with_its_own_data_and_number():
    assert 'import { OWNER_SECTION, ownerMarks, ownerPerson } from "./owner.js";   // 0.18 L2' in TEAM
    assert 'addTeamSection(OWNER_SECTION, { before: "people" });' in TEAM
    # TEAM_SECTIONS is filled before the section is added (the call comes after the list and the function)
    assert TEAM.index("export const TEAM_SECTIONS") < TEAM.index("addTeamSection(OWNER_SECTION")
    # a section reads its own answer with the tab's refresh, and a failed read keeps what was there
    assert "const loads = TEAM_SECTIONS.filter((s) => s.load);" in TEAM
    assert "Promise.all(loads.map((s) => s.load(project).catch(keep(ctx.data[s.key]))))" in TEAM
    assert "loads.forEach((s, i) => { ctx.data[s.key] = extra[i]; });" in TEAM
    assert "poller, seenAt(), ctx.data]);" in TEAM                     # its answer counts as a change to draw
    assert "+ sectionCount(ctx)" in TEAM                                  # the tab's number adds what waits
    assert TEAM.count("data: {}") == 2                                    # another project: nothing of the last one
    # the section: its key, its data, its number; drawn as team.js draws a section, with a heading it can focus
    assert 'key: "owner",' in OWNER and "load: (project) => api(\"GET\", OWNER_API.view(P(project)))," in OWNER
    assert "count: (ctx) => tabCount(" in OWNER
    assert 'class: `team-section team-sec-${key}`, "aria-labelledby": id, dataset: { key }' in OWNER
    assert 'h("h3", { class: "team-h", id, tabindex: "-1" }, title)' in OWNER
    assert 'ctx.focusHeading("owner")' in OWNER
    # owner.js never imports team.js (team.js imports it: no cycle)
    assert "team.js" not in "".join(re.findall(r"^import .*$", OWNER, flags=re.M))


def test_the_people_list_shows_the_owner_and_the_hand_over():
    # 0.17.0 (design guide): each person a list row; the Owner a role on the person mark, Make owner… at the row's end
    marked = _marked(TEAM)
    assert any('listRow({ person: ownerPerson(ctx, me, "you")' in ln for ln in marked)
    assert any('listRow({ person: ownerPerson(ctx, x, x.name)' in ln for ln in marked)
    assert "actions: [ownerMarks(ctx, me)].filter(Boolean)" in TEAM and "actions: [ownerMarks(ctx, x)].filter(Boolean)" in TEAM
    fn = OWNER[OWNER.index("export function ownerPerson"):OWNER.index("// the Documents page (sources.js)")]
    assert 'role: owner ? "Owner" : null' in fn and "v.owner.id === person.id" in fn
    assert "v.is_owner &&" in fn and '"Make owner…"' in fn and '"aria-label": `Make ${name} the owner…`' in fn
    assert "Hand this project over to ${name}?" in fn
    assert "They will decide about its documents from now on; proposals that wait become theirs to answer. You stay in the team." in fn
    assert 'api("POST", OWNER_API.handOver(P(ctx.project))' in OWNER and "{ to: to.id, why }" in OWNER


def test_the_documents_page_in_marked_lines():
    marked = "\n".join(_marked(SOURCES))
    assert 'import { proposalChip, proposedToast, removalNote } from "./owner.js";' in marked
    assert "proposalChip(d.proposal)," in marked
    assert "proposedToast(res, project, ids);" in marked                   # in patchDocs: the select and the dialog
    assert "if (!(res.proposed || []).length) toast(" in marked             # its own words only when not proposed
    assert "const proposal = await removalNote(project, d);" in marked
    assert "proposal) });" in SOURCES and 'toast(proposal ? "Removed from your copy.' in marked
    chip = OWNER[OWNER.index("export function proposalChip"):OWNER.index("// who the owner is, for the Documents page")]
    assert 'class: "visually-hidden" }, c.text' in chip and '"aria-hidden": c.text ? "true" : null' in chip  # said once
    note = OWNER[OWNER.index("export async function removalNote"):]
    assert 'doc.proposal.state !== "waiting"' in note and "v.is_owner" in note


def test_no_inline_look_and_no_link_drawn_as_a_button():
    for name, js in (("owner.js", OWNER), ("owner-state.js", STATE), ("team.js L2", "\n".join(_marked(TEAM))),
                     ("sources.js L2", "\n".join(_marked(SOURCES)))):
        assert "style:" not in js and ".style." not in js, name
        assert not re.search(r'h\("a", \{[^}]*class: "[^"]*btn', js), name
        assert "innerHTML" not in js, name
    # 0.17.0 (design guide): only the components' helpers (buttons, tags, cards, notices), never their classes by hand
    # 0.17.0: a proposal is the guide's proposalCard() (lib.js: a small card, the severity tag in its head, Accept main
    # and Decline… quiet), where 0.18 made it of card(), listRow() and severityTag() at the mark "0.17.0: proposalCard()"
    for made in ('button({ kind: "quiet", sm: true', 'button({ sm: true',
                 'personMark([name || "a colleague"], { role: owner ? "Owner" : null })', "proposalCardBox({ id: `owner-card-${p.id}`",
                 'notice({ kind: "attention", role: "note", class: "owner-notice" }', 'notice({ kind: "info", role: "note", class: "owner-notice" }',
                 "severity: p.severity,", 'side: p.can_decide ? "owner" : "proposer"'):
        assert made in OWNER, made
    lib = _read("lib.js")
    card = lib[lib.index("export function proposalCard("):]
    card = card[:card.index("\n}\n")]
    assert 'button({ kind: "main", sm: true, onClick: o.onAccept }, "Accept")' in card
    assert 'button({ kind: "quiet", sm: true, onClick: o.onDecline }, "Decline…")' in card
    assert "o.severity ? severityTag(o.severity) : null" in card
    assert not re.search(r'class: [`"](btn|chip|card|notice)(?![\w-])', OWNER)


# ------------------------------------------------------------------ the words of the plan (§8)
def test_the_words_of_the_plan():
    words = OWNER + STATE
    for w in (
        "Waiting for the owner", "Waiting for you", "Nothing waits for the owner.", "Nothing waits for you.",
        "This project has no owner yet. An owner decides which documents the project holds, how they are read and who "
        "may read them with AI. Until someone is, everything works as before.", "Become the owner",
        'low: "Low", medium: "Medium", high: "High"', "It is in every copy for now. Declined, it stays in ",
        "Accepted, every copy reads it again and moves its results with it.", "Where the text starts or ends was changed.",
        "Accepted, it leaves every copy; checks keep what they read of it.", "you accept", "nothing changes anywhere.",
        "other proposal for this document waits too.", "Accept", "Decline", "Reason (optional)",
        "Remove “${shortTitle(p.title, 70)}” from every copy of the project?", "Take back", "Take this proposal back?",
        "Your copy stays as it is.", "Accepted by ", " at once", "Declined: ", "Taken back.", "No longer needed: ",
        "The project now reads “", "with the new reader.", "Move it anyway", "Results that find no place are kept as records.",
        "Accept documents collaborators add, at once",
        "Off: each added document waits for your click. Removing a document and letting more AI read one always wait for you.",
        "You can take the project over.", "Take over", "Owner: ", "In your copy only", "a looser setting is the owner’s to decide. Proposed to ",
        "; until then nothing changes.", "In your copy it goes now; for the project it is a proposal to the owner.",
        "Mark as seen", "Answered (",
    ):
        assert w in words, w


def test_the_endpoints_are_those_of_the_plan():
    for path in ("/api/projects/${p}/owner`", "/owner/claim`", "/owner/hand-over`", "/owner/take-over`", "/owner/settings`",
                 "/owner/apply`", "/owner/proposals/${id}/accept`", "/owner/proposals/${id}/decline`",
                 "/owner/proposals/${id}/take-back`"):
        assert path in STATE, path
    assert 'api("PUT", OWNER_API.settings(P(ctx.project)), { accept_adds: want })' in OWNER
    assert 'api("POST", OWNER_API.apply(P(ctx.project)), { doc: row.doc, force: true })' in OWNER
    assert "OWNER_API.accept(P(ctx.project), P(p.id)), why ? { reason: why } : {}" in OWNER
    assert "OWNER_API.decline(P(ctx.project), P(p.id)), why ? { reason: why } : {}" in OWNER
    assert 'api("POST", OWNER_API.takeBack(P(ctx.project), P(p.id)), {})' in OWNER
    assert 'api("POST", OWNER_API.claim(P(ctx.project)), {})' in OWNER and "OWNER_API.takeOver(P(ctx.project))" in OWNER
    # a refusal (only the owner, no such proposal, it no longer waits) reads the tab again
    assert "e.status === 403 || e.status === 404 || e.status === 409" in OWNER
    assert not re.search(r"^import ", STATE.replace('import { whenText } from "./team-state.js";', ""), flags=re.M)


def test_keyboard_and_screen_reader():
    # the severity is a word, said with what it is; the decline's reason is a labelled field; Enter and Escape work.
    # 0.17.0 (DESIGN.md 5.5): Decline… opens a dialog that asks for the optional reason (reasonDialog), where 0.18 opened
    # a field inside the card; Escape is the dialog's (lib.js dialog(): its cancel), Enter in the field presses its button
    lib = _read("lib.js")
    sev = lib[lib.index("export function severityTag("):]
    assert 'title: `Severity: ${words.toLowerCase()}`' in sev[:sev.index("\n}\n")] and 'title: "Severity: high"' in sev
    # a screen reader hears "Severity: Low", not "Low" alone (the title is not reliably read)
    assert 'h("span", { class: "visually-hidden" }, "Severity: ")' in sev[:sev.index("\n}\n")]
    # field() (lib.js) labels the field and points it at its help line (`${id}-help`)
    assert 'field("Reason (optional)", reason, { help,' in OWNER and 'id: "owner-dlg-reason"' in OWNER
    assert 'h("label", { for: id, class: "field-label" }, label)' in lib and 'control.setAttribute("aria-describedby", id + "-help")' in lib
    dlg = lib[lib.index("export function dialog("):]
    assert 'e.key === "Enter"' in OWNER and 'dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(null); });' in dlg  # Escape
    assert 'const ok = await reasonDialog({ title: "Decline this proposal?", confirmText: "Decline", help: reasonHelp(p),' in OWNER
    assert "sees it with your answer, and it is kept in the research log." in OWNER   # the help says where the reason goes
    # stable ids, so the panel finds the focus again after a redraw (a card's buttons: an answer reads the tab again and
    # the focus goes to the section's heading, ctx.focusHeading("owner"))
    for i in ("owner-card-${p.id}", "owner-dlg-reason", "owner-dlg-ok",
              "owner-claim", "owner-take-over", "owner-accept-adds", "owner-seen", "owner-make-${person.id}"):
        assert i in OWNER, i
    assert 'role: "status"' in OWNER          # the new-reader job's line
    assert "gone.has(job.id)" in OWNER and "gone.add(job.id)" in OWNER   # a job that is no more is not followed again
    # the proposer's Take back only where they may (a third colleague sees the wait only), and it asks first
    assert "onTakeBack: p.can_take_back ? (e) => takeBack(ctx, p, e.currentTarget) : null" in OWNER
    # Take back shows whenever it is given, also beside Accept and Decline… for an owner whose own proposal still waits
    assert 'const takeBack = o.onTakeBack ? [button({ kind: "quiet", sm: true, onClick: o.onTakeBack }, "Take back")] : [];' in lib
    assert '"Decline…"), ...takeBack]' in lib
    assert 'd.querySelector("summary").id = "owner-answered"' in OWNER and 'ctx.open.has("owner-answered")' in OWNER


# ------------------------------------------------------------------ what the page works out (Node)
NODE = r"""
import * as O from "./owner-state.js";
const NOW = new Date(Date.parse("2026-11-11T10:00:00Z"));
const ben = { id: "pben", name: "Ben Okafor", me: false }, me = { id: "pme", name: "you", me: true };
const anna = { id: "panna", name: "Anna de Vries", me: false };
const P = (o) => ({ id: "q" + Math.random().toString(16).slice(2, 10), kind: "add", severity: "low", doc: "d1", title: "Annual report 2024",
  what: "adding “Annual report 2024”", by: ben, at: "2026-11-11T09:00:00Z", state: "waiting", note: null, reason: null,
  decided_by: null, decided_at: null, auto: false, mine: false, can_decide: false, can_take_back: false, here: true,
  conflicts: [], detail: {}, ...o });
const owner = { owner: me, is_owner: true, waiting: 2, since: "2026-11-10T09:00:00Z", proposals: [], to_apply: [] };
const collab = { owner: anna, is_owner: false, waiting: 1, since: "2026-11-10T09:00:00Z", proposals: [], to_apply: [] };
const out = {};
out.shown = [O.sectionShown(null, true), O.sectionShown({ proposals: [], to_apply: [] }, false), O.sectionShown({ proposals: [], to_apply: [] }, true),
  O.sectionShown({ since: "x", proposals: [], to_apply: [] }, false), O.sectionShown({ can_claim: true, proposals: [], to_apply: [] }, false)];
const declined = P({ id: "qdec", state: "declined", mine: true, by: me, reason: "Not ours", decided_by: anna, decided_at: "2026-11-11T09:30:00Z" });
const list = [P({ id: "qw1" }), declined, P({ id: "qacc", state: "accepted", decided_by: me, decided_at: "2026-11-11T09:10:00Z", auto: true }),
  P({ id: "qtb", state: "taken_back" }), P({ id: "qw2", by: me, mine: true })];
for (let i = 0; i < 12; i++) list.push(P({ id: "qold" + i, state: "moot", note: "The owner removed this document from the project." }));
const v = { ...collab, proposals: list };
const s = O.splitProposals(v);
out.split = { cards: s.cards.map((p) => p.id), declined: s.declined.map((p) => p.id), answered: s.answered.length, total: s.answeredTotal };
out.splitSeen = O.splitProposals(v, new Set(["qdec"])).declined.length;
out.count = [O.tabCount({ ...owner, proposals: list }), O.tabCount(v), O.tabCount(v, new Set(["qdec"])), O.tabCount(null)];
out.heading = [O.heading(owner, 2), O.heading(collab, 0), O.heading({ can_claim: true }), O.nothingWaits(owner), O.nothingWaits(collab)];
out.who = [O.proposer(P({})), O.proposer(P({ by: me }))];
out.parts = [O.whatParts("removing “Annual report 2024” from the project"), O.whatParts("something without a title")];
out.lines = {
  add: O.kindLine(P({}), owner), addMine: O.kindLine(P({ by: me }), collab),
  reread: O.kindLine(P({ kind: "reread", detail: { from_reader: 1, to_reader: 3 } }), owner),
  blocks: O.kindLine(P({ kind: "blocks", detail: { left_out: 2, restored: 1, undone: 0, bounds: 1 } }), owner),
  blocksOne: O.blocksLine({ left_out: 0, restored: 1, undone: 0, bounds: 0 }), blocksUndone: O.blocksLine({ undone: 2 }),
  blocksNone: O.blocksLine({}),
  remove: O.kindLine(P({ kind: "remove" }), owner),
  loosenOwner: O.kindLine(P({ kind: "loosen", detail: { from: "none", to: "cloud" } }), owner),
  loosenOther: O.kindLine(P({ kind: "loosen", detail: { from: "local", to: "cloud" } }), collab),
};
out.answered = [O.answeredLine(P({ state: "accepted", decided_by: anna, decided_at: "2026-11-11T09:59:00Z" }), NOW),
  O.answeredLine(P({ state: "accepted", decided_by: me, decided_at: "2026-11-11T09:59:00Z", auto: true }), NOW),
  O.answeredLine(P({ state: "accepted", note: "The owner added it too." }), NOW),
  O.answeredLine(P({ state: "declined", reason: "Out of scope", decided_at: "2026-11-11T09:59:00Z" }), NOW),
  O.answeredLine(P({ state: "declined" }), NOW), O.answeredLine(P({ state: "taken_back" }), NOW),
  O.answeredLine(P({ state: "replaced" }), NOW), O.answeredLine(P({ state: "moot", note: "Gone since." }), NOW)];
out.declined = [O.declinedLine(declined, collab), O.declinedLine(P({ kind: "loosen", state: "declined" }), collab)];
out.misc = { wait: [O.waitingFor(collab), O.waitingFor(owner), O.waitingFor({ owner: null })], conflicts: [O.conflictsText(1), O.conflictsText(3)],
  apply: O.applyText({ title: "Grid effects", note: "2 of your results on it would not find their place in the new reading." }),
  owner: [O.ownerName(collab), O.ownerName(owner), O.ownerName(null)] };
out.chips = [O.docChip({ state: "proposed", text: "Added by Ben Okafor: waiting for the owner." }), O.docChip({ state: "declined", text: "In your copy only: the owner declined it." }),
  O.docChip({ state: "waiting", text: "x" }), O.docChip(null)];
out.toast = [O.proposedText(1, "Anna de Vries"), O.proposedText(3, "the owner", 2)];
out.loosen = [O.loosenConfirm(P({ kind: "loosen", detail: { from: "local", to: "cloud" } }), true),
  O.loosenConfirm(P({ kind: "loosen", detail: { from: "none", to: "cloud" } }), false),
  O.loosenConfirm(P({ kind: "loosen", detail: { from: "none", to: "local" } }), true)];
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def node_out(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("Node is not installed")
    d = tmp_path_factory.mktemp("owner-node")
    (d / "package.json").write_text('{"type": "module"}')
    (d / "owner-state.js").write_text(STATE, encoding="utf-8")
    (d / "team-state.js").write_text(_read("views/team-state.js"), encoding="utf-8")
    (d / "run.mjs").write_text(NODE, encoding="utf-8")
    r = subprocess.run([shutil.which("node"), str(d / "run.mjs")], capture_output=True, text=True,
                       env={**os.environ, "TZ": "Europe/Amsterdam"})  # the times are read in Dutch local time
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_when_the_section_shows_and_what_goes_where(node_out):
    # a project never exchanged, with no shared folder, has nothing to say; with a folder, an owner on record, or no
    # owner (it could have one) it shows
    assert node_out["shown"] == [False, False, True, True, True]
    s = node_out["split"]
    assert s["cards"] == ["qw1", "qw2"]                         # all that wait, newest first as the app sends them
    assert s["declined"] == ["qdec"]                            # this person's own declined one, first, until seen
    assert s["answered"] == 10 and s["total"] == 14             # the latest ten in the fold
    assert node_out["splitSeen"] == 0
    # the tab's number: what waits for the owner's answer; for a collaborator, their declined ones not seen yet
    assert node_out["count"] == [2, 1, 0, 0]
    assert node_out["heading"] == ["Waiting for you (2)", "Waiting for the owner", "No owner yet", "Nothing waits for you.",
                                   "Nothing waits for the owner."]


def test_a_cards_words(node_out):
    assert node_out["who"] == [{"who": "Ben Okafor", "verb": "proposes"}, {"who": "You", "verb": "propose"}]
    assert node_out["parts"] == [{"before": "removing ", "title": "Annual report 2024", "after": " from the project"},
                                 {"before": "something without a title", "title": None, "after": ""}]
    ln = node_out["lines"]
    assert ln["add"] == "It is in every copy for now. Declined, it stays in Ben Okafor’s copy only."
    assert ln["addMine"] == "It is in every copy for now. Declined, it stays in your copy only."
    assert ln["reread"] == "Reader 1 to 3. Accepted, every copy reads it again and moves its results with it."
    assert ln["blocks"] == "2 passages left out, 1 restored. Where the text starts or ends was changed."
    assert ln["blocksOne"] == "1 passage restored." and ln["blocksUndone"] == "2 passages back as the reader reads them."
    assert ln["blocksNone"] == "Which passages are read was changed."
    assert ln["remove"] == "Accepted, it leaves every copy; checks keep what they read of it."
    assert ln["loosenOwner"] == "Now: No AI. Proposed: Claude may read it. Until you accept, nothing changes anywhere."
    assert ln["loosenOther"] == "Now: Only a local AI. Proposed: Claude may read it. Until the owner accepts, nothing changes anywhere."


def test_an_answer_in_words(node_out):
    a = node_out["answered"]
    assert a[0] == {"text": "Accepted by Anna de Vries", "when": "Today 10:59"}
    assert a[1] == {"text": "Accepted by you at once", "when": "Today 10:59"}
    assert a[2] == {"text": "No longer needed: The owner added it too.", "when": ""}
    assert a[3] == {"text": "Declined: Out of scope", "when": "Today 10:59"}
    assert [x["text"] for x in a[4:]] == ["Declined.", "Taken back.", "Replaced by a later proposal.", "No longer needed: Gone since."]
    d = node_out["declined"]
    assert d[0] == {"head": "Anna de Vries declined your proposal", "reason": "Declined: Not ours", "after": "The document stays in your copy only."}
    assert d[1]["head"] == "Anna de Vries declined your proposal" and d[1]["after"] == "Nothing changed anywhere."
    m = node_out["misc"]
    assert m["wait"] == ["Waiting for Anna de Vries.", "Waiting for you.", "Waiting for the owner."]
    assert m["conflicts"] == ["1 other proposal for this document waits too.", "3 other proposals for this document wait too."]
    assert m["apply"] == ("The project now reads “Grid effects” with the new reader. 2 of your results on it would not find "
                          "their place in the new reading.")
    assert m["owner"] == ["Anna de Vries", "you", "the owner"]


def test_the_documents_pages_chip_and_toast(node_out):
    c = node_out["chips"]
    assert c[0] == {"label": "Waiting for the owner", "text": "Added by Ben Okafor: waiting for the owner.", "kind": "waiting"}
    assert c[1] == {"label": "In your copy only", "text": "In your copy only: the owner declined it.", "kind": "declined"}
    assert c[2]["label"] == "Waiting for the owner" and c[3] is None
    assert node_out["toast"] == [
        "1 document: a looser setting is the owner’s to decide. Proposed to Anna de Vries; until then nothing changes.",
        "2 documents changed. 3 documents: a looser setting is the owner’s to decide. Proposed to the owner; until then nothing changes."]


# ------------------------------------------------------------------ the app's answers have what the page reads
def test_the_answers_have_the_fields_the_page_reads(api, home, tmp_path):  # noqa: F811
    from enlens_claims import ingest

    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    f = tmp_path / "Annual report 2024.txt"
    f.write_text("Annual report 2024\n\n" + "The plant hired forty people from the region in its first year. " * 12 + "\n\n"
                 + "Most of them were technicians trained at the local college, and a few came from the capital. " * 12 + "\n",
                 encoding="utf-8")
    ingest.ingest(home.open_project("Demo"), [f])
    st, v = api("GET", "/api/projects/Demo/owner")
    assert st == 200
    assert {"owner", "me", "is_owner", "since", "how", "can_claim", "can_take_over", "accept_adds", "people", "proposals",
            "waiting", "to_apply", "documents", "job"} <= set(v)
    # a project never exchanged is its maker's, from nothing; the setting is on by default
    assert v["is_owner"] is True and v["owner"]["me"] is True and v["how"] == "made" and v["accept_adds"] is True
    assert v["since"] is None and v["can_claim"] is False and v["proposals"] == [] and v["job"] is None
    assert {"id", "name", "me", "owner"} <= set(v["people"][0]) and v["people"][0]["owner"] is True
    st, r = api("GET", "/api/projects/Demo/documents")
    assert st == 200 and r["documents"] and all("proposal" in d and d["proposal"] is None for d in r["documents"])
    doc = r["documents"][0]["doc_id"]
    st, r = api("PUT", "/api/projects/Demo/documents/ai-access", {"doc_ids": [doc], "ai_access": "none"})
    assert st == 200 and r["proposed"] == [] and "documents" in r      # the owner's own change: never a proposal
    st, r = api("PUT", "/api/projects/Demo/owner/settings", {"accept_adds": False})
    assert st == 200 and r["accept_adds"] is False and r["is_owner"] is True
    st, r = api("POST", "/api/projects/Demo/owner/proposals/qnosuchproposal/accept", {})
    assert st == 404


def test_accepting_a_looser_setting_says_when_its_words_go_into_the_shared_folder(node_out):
    # stage-4 review: with the keep-out switch in force, a document let out to Claude is written into the shared folder
    on, off, still_kept = node_out["loosen"]
    assert on == ("Every copy then has it as “Claude may read it”. The shared folder keeps out only documents marked "
                  "Only a local AI or No AI, so its text and file will then go into the shared folder too.")
    assert off == "Every copy then has it as “Claude may read it”."
    assert still_kept == "Every copy then has it as “Only a local AI”."


def test_the_owners_accept_asks_first_for_a_looser_setting():
    js = (STATIC / "views" / "owner.js").read_text(encoding="utf-8")
    assert 'p.kind === "loosen"' in js and "loosenConfirm(p, inForce)" in js and "keep_out.in_force" in js
