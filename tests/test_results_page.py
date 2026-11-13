"""0.12: work that waits for Claude Code with nothing answering it is "not running" (the sidebar says so, in its own
colour, instead of "1 task running"), and the result page is calmer: the answer with who says what, one caution and
one next step; the evidence with each excerpt's quote in its context and one row of actions (with a one-click
"Not about this"); the other AI models; notes and downloads; Delete at the page's foot."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import fake_claude_code as fcc
from test_queue import _project
from test_app import CLAIM, api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


def _job(api, job_id):
    return next(j for j in api("GET", "/api/jobs")[1]["jobs"] if j["id"] == job_id)


def _until(fn, seconds=15.0):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    return fn()


# ---------------------------------------------------------------------------------------------
# the sidebar: on hold, not running
# ---------------------------------------------------------------------------------------------
def test_a_check_waiting_for_claude_code_is_on_hold_until_something_answers(api, corpus):  # noqa: F811
    from enlens_claims import home as core
    from enlens_claims import taskqueue

    _project(api, corpus)
    jid = api("POST", "/api/projects/P/checks", {"text": CLAIM, "k": 3})[1]["job"]["id"]
    try:
        # the check waits in the queue and nothing answers it: on hold, in the jobs list and in the app's state
        assert _until(lambda: _job(api, jid)["on_hold"]), _job(api, jid)
        assert _job(api, jid)["state"] == "running" and _job(api, jid)["queue"] is True
        assert [j["on_hold"] for j in api("GET", "/api/state")[1]["jobs"] if j["id"] == jid] == [True]
        ws = core.open_project("P")
        assert taskqueue.answering(ws) is False
        # a Claude Code typed elsewhere takes a batch: it is running
        claim = taskqueue.next_tasks(ws, n=1)
        assert claim["claim"]
        assert taskqueue.answering(ws) is True and _job(api, jid)["on_hold"] is False
        # given back unanswered: on hold again
        taskqueue.release(ws, claim["claim"])
        assert _job(api, jid)["on_hold"] is True
        # answered by a session (the fake /enlens-run): its answer is recent, so the check counts as running while
        # it waits for the next stage
        fcc.FakeClaudeCode(fcc.DirectTools(), wrong_first=False).run("P")
        assert taskqueue.answering(ws) is True
        j = _job(api, jid)
        assert j["state"] in ("running", "done") and j["on_hold"] is False
    finally:
        api("POST", f"/api/jobs/{jid}/cancel")
        api.wait(jid)
    # finished work, and work that never waits for Claude Code (adding documents), is never on hold
    assert not any(j["on_hold"] for j in api("GET", "/api/jobs")[1]["jobs"])


def test_an_old_answer_does_not_count_as_answering(api, corpus):  # noqa: F811
    from enlens_claims import home as core
    from enlens_claims import taskqueue

    _project(api, corpus)
    jid = api("POST", "/api/projects/P/checks", {"text": CLAIM, "k": 3})[1]["job"]["id"]
    try:
        assert _until(lambda: _job(api, jid)["on_hold"])
        fcc.FakeClaudeCode(fcc.DirectTools(), wrong_first=False).run("P")
        ws = core.open_project("P")
        assert taskqueue.answering(ws) is True
        # the same answers, three minutes old: a session that has gone
        with ws.connect() as cx:
            cx.execute("UPDATE results SET received_at=? WHERE route='Claude Code'",
                       (time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 180)),))
        assert taskqueue.answering(ws) is False
    finally:
        api("POST", f"/api/jobs/{jid}/cancel")
        api.wait(jid)


def test_the_sidebar_says_not_running_in_its_own_colour():
    # 0.17.0: the jobs and queue panels became one status area of a fixed size (app.js drawStatus); the rule stays
    app = (STATIC / "app.js").read_text()
    draw = app[app.index("async function drawStatus()"):app.index("// 0.14.2: the theme is a small icon beside Settings")]
    # on hold and running are told apart, with their own class, words and mark
    assert "const hold = active.filter((j) => j.on_hold);" in draw and "const going = active.filter((j) => !j.on_hold);" in draw
    assert 'kind: "stalled"' in draw and '"Not running"' in draw and 'icon: "pause"' in draw
    # 0.17.0 (design guide): "2 tasks waiting" fits the status area beside Start ("2 tasks wait for Clau…" was cut);
    # the tooltip says for whom
    assert "sub: `${tasksWord(n)} waiting`," in draw and "wait\"} for Claude Code. Start it" in draw
    # the pulsing dot is only for work that runs
    assert 'w.kind === "running" ? h("span", { class: "running-dot"' in draw
    # it offers to start Claude Code for the current project's work on hold, in one button
    assert "startClaudeNow(App.project)" in draw and '"Start"' in draw
    from _static import all_css, rule  # 0.17.0: reads the cascade, so it holds when the rule moves

    stalled = rule(".work-box.work-stalled")
    # 0.17.0 (design guide): "needs you" is the attention token (its value is --warn's)
    assert "var(--attention-soft)" in stalled.values() and ".work-box.work-stalled .running-dot" not in all_css()  # no pulse for work on hold


# ---------------------------------------------------------------------------------------------
# the result page
# ---------------------------------------------------------------------------------------------
def test_the_result_page_reads_in_one_order():
    js = (STATIC / "views" / "result.js").read_text()
    draw = js[js.index("  function draw(r) {"):js.index("    // keep the person's place after a save")]
    order = ["answerCard(r, parts, single, allPassages)", "evidenceHead(r, allPassages, single)", "partView(part, r, single)",
             "modelsCard(r, allPassages)", "noteCard(r)", "downloadsCard(r, parts)", '"Delete this result"']
    normal = draw[draw.index("} else {"):]
    at = [normal.index(x) for x in order]
    assert at == sorted(at), at
    # who says what is inside the answer card, not a card of its own between the answer and the evidence
    card = js[js.index("  function answerCard("):js.index("  function whatsNewText(")]
    assert "whoSaysWhat(parts[0])" in card and "followUpsCard" not in js
    # one caution at most, in the same paragraph as the next step; no prefix that reads as a history
    # 0.17.0 (design guide, changed on purpose): the one caution is a notice, attention or info (docs/DESIGN.md 3.3, 4.12)
    assert "The AI's first reading:" not in js and card.count('class: "answer-caution"') == 1
    # 0.14.3: the one caution paragraph may also name the excerpts that wait for your judgement (baseCaution + forYouLine)
    assert "const baseCaution = r.incomplete ?" in card and "const caution = [baseCaution, forYouLine]" in card and 'text && caution ? notice({ kind: r.incomplete || unchecked || forYou ? "attention" : "info", class: "answer-caution" }, h("p", {}, text))' in card
    # strictness is said once, beside what counts, explained behind its help mark (which says where to try another)
    assert "function strictnessLine(" not in js
    head = js[js.index("  function evidenceHead("):js.index("  // One compact row per excerpt read")]
    assert 'id: "strictness"' in head and '"Try another strictness on this page"' in head and "your judgement overrides the AI's" in head
    # one count: the excerpts about the hypothesis (those the AI found not about it do not make it less reviewed),
    # and a caution whenever AI judgements that count are unchecked, however many
    assert "const relevantLeft = allPassages.filter((p) => !p.reviewed && (p.ai_verdict || p.waiting_for_you)).length;" in card
    # 0.14: "reviewed by you" (alone), or "by you and Anna" in a shared project
    assert 'relevantLeft === 0 ? `reviewed by ${byPeople}`' in card and 'people[0] || "you"' in card
    assert "`It rests on ${aiJ(unchecked)} you have not reviewed.`" in card
    # Delete is at the page's foot, not under the downloads' technical details
    downloads = js[js.index("  function downloadsCard("):js.index("  async function deleteHyp(")]
    assert "deleteHyp" not in downloads
    # a check waiting for Claude Code: the answer card is the queue notice; no empty sections under it, Delete stays
    waiting = draw[draw.index('if (r.status === "waiting" && !onlyLocal) {'):draw.index("} else {")]
    assert "queueNotice(" in waiting and "modelsCard" not in waiting and "downloadsCard" not in waiting
    assert "{ foldType: true }" in waiting and "deleteHyp(r)" in waiting and "techCard(r, parts)" in waiting
    lib = (STATIC / "lib.js").read_text()
    assert "opts.foldType && q.can_start ?" in lib and "foldType: opts.foldType" in lib


def test_an_excerpt_card_is_compact_and_can_be_dismissed():
    js = (STATIC / "views" / "result.js").read_text()
    judge = js[js.index("  function judgeControl("):js.index("  function moreRow(")]
    # dismissing is a person's judgement "Not about this": recorded like any other, with Undo
    assert 'put("not_relevant", undefined,' in judge and '"Not about this")' in judge
    assert 'p.user_verdict !== "not_relevant"' in judge and 'p.read_by !== "you"' in judge
    # an agreement is a state on the card, not a filled button; agreeing with an uncounted judgement says it counts
    assert '"You agree with the AI")' not in judge
    # an agreement can be taken back from the card itself, the same way as a different judgement: one label, saved at
    # once with Undo (no confirmation for one and not the other)
    assert judge.count('}, "Take back"));') == 3 and "confirmDialog" not in judge
    # the other judgements are buttons (arrowing through radios saved at every key press)
    # 0.17.0 (design guide, changed on purpose): they are a choice in its filter form (choice({ filter: true })): the
    # one in force shows as chosen, and the arrow keys only move between them (nothing is saved until one is picked)
    assert 'type: "radio"' not in judge and "choice({ filter: true, label: \"Your judgement (saved when you pick one)\"" in judge
    # the first slot reads the same on every card ("Agree"); its title says when agreeing makes a judgement count
    assert '"Agree"),' in judge and "(it does not count now)" in judge
    # an uncounted judgement says so on the card; what agreeing does is in its tooltip and the strictness help
    card = js[js.index("  function evidenceCard("):js.index("  // Where a card is on the screen now")]
    assert 'class: "ev-fact ev-uncounted-fact"' in card and "it counts once you judge it yourself" in card
    # the counted excerpts first in each list, the uncounted after them
    assert "const byCount = [...judged.filter((x) => x.counted || x.user_verdict)" in js
    # the radio "Not about this" is left out where the button does it
    assert '!(canDismiss && val === "not_relevant")' in judge
    card = js[js.index("  function evidenceCard("):js.index("  // Where a card is on the screen now")]
    # the quote in its context; "more…" at the end of the excerpt (0.18.2; it was the "In context" button) is the one way
    # to more of the text (the whole excerpt, and on into the document), never part of a selected sentence; the actions
    # in one row that never moves: the judge and More panels open under it
    assert "excerptWindow(p.text, hsI, heI, brI, { after:" in card and '"Show the whole excerpt"' not in card and "function contextView" not in js
    assert '}, whole ? "less" : "more…");' in card and '"Open the whole document at this place"' in card
    assert 'link({ kind: "jump", class: "more-link",' in card and '"In context")' not in card and "ctx-toggle" not in js
    from _static import rule
    assert rule(".ev .more-link").get("user-select") == "none"
    assert "judgeControl(p, part, passageEl, extras)" in card and 'panelToggle(`tech:${p.passage_id}`, "Details", morePanel, false)' in card
    # four actions in the row; reading again is under Details, the original file with the whole excerpt (more…);
    # one panel open at a time
    # 0.17.0 (design guide): reading again sends the excerpt to the AI, so it carries the AI mark (withAI())
    # 0.17.0 (design guide 4.4): the reread button's panel says where the excerpt goes, under the button
    assert "rereadBtn ? h(\"div\", { class: \"ev-more-actions\" }, withAI(rereadBtn), readsLine(\"this excerpt again, with your comment\")) : null," in card and '"the original file"' in card
    assert "if (other !== btn) other.click();" in js
    assert 'wrap.append(judgePanel, ...(extras.panels || []));' in judge
    assert "Sentence highlighted by the AI" not in js  # the section head says it once
    from _static import all_css, css_blocks, rule  # 0.17.0: reads the cascade, so it holds when the rules move

    # no new faces: only the font tokens of tokens.css, in every rule of the result page
    assert rule(".result .part-card")
    fonts = [d["font-family"] for _m, sels, d in css_blocks(all_css()) if "font-family" in d
             and any(s.startswith(".result ") for s in sels)]
    assert fonts and all(f.strip().startswith("var(--font-") for f in fonts), fonts


NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_excerpt_window_keeps_the_quote_and_a_sentence_either_side(tmp_path):
    js = (STATIC / "views" / "result.js").read_text()
    src = re.search(r"export function excerptWindow\(.*?\n}\n", js, re.S).group(0).replace("export ", "")
    text = ("Intro one is here. Intro two follows on. The sentence before the quote. THE QUOTE IS THIS SENTENCE. "
            "The sentence after the quote. Then more words that go on for a while. " + "Filler sentence. " * 30 + "Method. ")
    q0 = text.index("THE QUOTE")
    q1 = q0 + len("THE QUOTE IS THIS SENTENCE.")
    short = "A short excerpt. THE QUOTE IS THIS SENTENCE."
    heading = "A short excerpt. THE QUOTE IS THIS SENTENCE. 4. Heterogeneity."
    m0 = text.index("Method.")
    script = src + f"""
const t = {json.dumps(text)};
const out = {{
  win: excerptWindow(t, {q0}, {q1}, null),
  none: excerptWindow({json.dumps(short)}, 17, 44, null),
  heading: excerptWindow({json.dumps(heading)}, 17, 44, null),
  noquote: excerptWindow(t, null, null, null),
  last: excerptWindow(t, {m0 - len("Filler sentence. ")}, {m0 - 1}, null),
  phone: excerptWindow(t, {q0}, {q1}, null, {{ after: 0 }}),
}};
console.log(JSON.stringify(out));"""
    f = tmp_path / "w.js"
    f.write_text(script)
    out = json.loads(subprocess.run([NODE, str(f)], capture_output=True, text=True, check=True).stdout)
    a, b = out["win"]
    shown = text[a:b]
    assert shown.startswith("The sentence before the quote.") and "THE QUOTE IS THIS SENTENCE." in shown
    assert shown.rstrip().endswith("The sentence after the quote.")
    assert out["none"] is None  # a short excerpt is shown whole
    assert heading[slice(*out["heading"])].rstrip() == short  # ... but not the next section's heading after the quote
    assert text[slice(*out["noquote"])].startswith("Intro one is here. Intro two follows on.")
    # the line after the quote is a heading ("Method."): left out of the window
    assert "Method." not in text[slice(*out["last"])]
    # on a phone: the sentence before and the quote, not the sentence after
    phone = text[slice(*out["phone"])]
    assert phone.startswith("The sentence before the quote.") and phone.rstrip().endswith("THE QUOTE IS THIS SENTENCE.")


def test_a_dummy_subject_is_not_a_reference_to_check():
    from enlens_claims.references import opens_with_pronoun

    # "There is…", "It is unclear whether…", "It seems…" refer to nothing: no "check what it refers to"
    for q in ("There is no evidence that hybrid work reduces productivity overall.", "It is unclear whether rents rose.",
              "It seems that commuting fell.", "It is not clear how the savings were measured.", "There were fewer trips."):
        assert not opens_with_pronoun(q), q
    # a pronoun that stands for something still asks for it
    for q in ("It is cheaper than storing hydrogen in tanks.", "They found lower emissions.", "This reduces costs.",
              "It was likely to fail.", "There, the plant closed in 2019."):
        assert opens_with_pronoun(q), q


def test_the_page_names_documents_and_reaches_the_cards_from_the_table():
    js = (STATIC / "views" / "result.js").read_text()
    # a document on two sides: its title on each, the second time with "also for" (or partly for, against)
    # one row per document, each side it is on with its judgement mark and where (a document on both sides once)
    who = js[js.index("  function whoSaysWhat(part) {"):js.index('  // "page 1, paragraph 5"')]
    assert "The same document" not in js and 'h("ul", { class: "who who-list"' in who and 'class: `who-dot who-${sd}`' in who
    # a split hypothesis says which way each part's documents lean
    assert "function sidesText(b)" in js and '`${docsOf(k)} ${w}`' in js
    # ... and a document with excerpts on two sides counts once ("3 documents for, 1 of them also against")
    assert 'bits.reduce((t, [k]) => t + k, 0) <= n' in js and "of them also ${w}" in js and "in all)" in js
    # the caution of a split hypothesis counts only the parts that decide the answer
    assert "decidingParts(parts).flatMap((x) => x.passages || []).filter((p) => p.counted && !p.reviewed)" in js
    # "Next to review" from the table view goes back to the cards first (it used to say "Everything is reviewed.")
    nxt = js[js.index("  function nextToReview("):js.index("  const jumpTo")]
    assert 'if (evidenceView === "table") { evidenceView = "cards"' in nxt
    # the model list for a second opinion is asked once per page, not on every redraw
    assert "(serversOnce = serversOnce || api(\"GET\", \"/api/servers\"))" in js
