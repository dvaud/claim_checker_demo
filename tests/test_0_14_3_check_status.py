"""0.14.3: a check's status, its Excel rows and its quotes say what really happened.

- A round whose main part failed is failed: the part of excerpts no AI may read (born done) no longer hides it.
- Excerpts that wait for the person's own judgement count towards no status until judged: a check of No-AI documents
  is "Waiting for your judgement", not "No evidence found"; Excel says nobody has judged them.
- A comment of yours does not set a colleague's verdict aside; "you reviewed / changed" counts your judgements only.
- A quote is found as whole words only, the spacing pass does not join words the quote keeps apart, and a
  judgement's quote has a few words at least.
- A local model's answer it could not finish is a rejected attempt (asked again), not a connection error that
  deletes the check and stops Check several.
- The stronger model gets its own three tries; a rejected stronger answer stays with the helper's claim to be fixed.
- Excel names every model a check used; the evidence map agrees with the Results list; the prompt version recorded
  is the one the model was given.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers_0110 import Cloud, Local, mixed_project, use_local_model

import fake_servers
from enlens_claims import access, claimcheck, home, people, routing, taskqueue, tasks
from enlens_claims.llm import AnswerError, OllamaBackend
from enlens_claims.textutil import find_quote, find_selection, grade_quote_problem

HYP = "Green hydrogen production can increase water stress in arid regions."


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Mixed")
    return ws, mixed_project(ws, tmp_path / "corpus")


def _first_words(payload: dict, n: int = 6) -> str:
    return " ".join(payload["passages"][0]["text"].split()[:n])


class BadQuotes(Cloud):
    """Claude whose judging answers never pass the quote check."""

    def complete(self, kind, system, user, model, payload=None):
        if kind == "check":
            self.kinds.append(kind)
            return json.dumps({"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.9,
                                             "quote": "not in the text at all xyz"}]})
        return super().complete(kind, system, user, model, payload)


class NothingFound(Cloud):
    """Claude that finds none of the excerpts about the hypothesis."""

    def complete(self, kind, system, user, model, payload=None):
        if kind == "check":
            self.kinds.append(kind)
            return json.dumps({"evidence": [], "rationale": "None is about it."})
        return super().complete(kind, system, user, model, payload)


# ---------------------------------------------------------------------------------------------
# 1. a failed main part is not hidden by the part no AI may read
# ---------------------------------------------------------------------------------------------
def test_a_failed_main_part_fails_the_round(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)  # the local document's excerpts wait for the person too
    hid = claimcheck.check_hypothesis(ws, HYP, BadQuotes(), "claude-opus", k=12, per_doc=4, expand=False)
    sts = {t["task_id"].rsplit(":", 1)[-1] if t["task_id"].endswith(":person") else "main": t["status"]
           for t in ws.query("SELECT task_id, status FROM tasks WHERE kind='check'")}
    assert sts == {"person": "done", "main": "failed"}
    res = claimcheck.hypothesis_result(ws, hid)
    part = res["parts"][0]
    # before 0.14.3: status "unsupported", round_status "done", no errors, not incomplete
    assert res["status"] == "failed" and part["round_status"] == "failed"
    assert part["errors"] and "quote not found" in part["errors"][0]
    assert res["incomplete"] is True
    assert [h["status"] for h in claimcheck.history(ws) if h["hyp_id"] == hid] == ["failed"]
    assert [x["status"] for x in claimcheck.evidence_map(ws)["hypotheses"]] == ["failed"]


def test_a_failed_main_part_fails_the_round_whatever_the_local_model_read(mixed, monkeypatch):
    ws, ids = mixed
    local = Local()
    use_local_model(monkeypatch, local)
    hid = claimcheck.check_hypothesis(ws, HYP, BadQuotes(), "claude-opus", k=12, per_doc=4, expand=False)
    res = claimcheck.hypothesis_result(ws, hid)
    part = res["parts"][0]
    readers = {p["read_by"]: p["status"] for p in part["rounds_info"][0]["parts"]}
    assert readers["local"] == "done" and readers["you"] == "done"
    assert part["status"] == "failed" and part["round_status"] == "failed"
    # the local model's judgements of that failed search count nowhere (before 0.14.3 the answer rested on them)
    local = [x for x in part["passages"] if x["read_by"] == "local"]
    assert any(x["ai_verdict"] for x in local) and all(x["round_failed"] and not x["counted"] for x in local)
    assert res["balance"]["docs_counted"] == 0 and part["balance"]["docs_counted"] == 0
    assert res["who"] == [] and part["who"] == []
    row = [h for h in claimcheck.history(ws) if h["hyp_id"] == hid][0]
    assert (row["supports"], row["partly"], row["refutes"], row["docs_supporting"]) == (0, 0, 0, 0)
    assert claimcheck.evidence_map(ws)["cells"][hid] == {}
    xl = [r for r in claimcheck.export_table(ws) if r["Document"].startswith("Licensed")]
    assert xl and all(r["Judged by"] == "nobody: the check did not work" for r in xl)
    assert any(r["AI's own judgement"].endswith("(not counted: the check did not work)") for r in xl)
    # your own judgement in a check whose every search failed does not count either: it did not work
    x = local[0]
    claimcheck.set_judgement(ws, part["claim_id"], x["passage_id"], "supports")
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["status"] == "failed" and res["balance"]["docs_counted"] == 0


class FailSecondRound(Cloud):
    """Claude whose first search is answered and whose further searches fail."""

    def __init__(self):
        super().__init__()
        self.rounds = 0

    def complete(self, kind, system, user, model, payload=None):
        if kind == "check":
            self.rounds += 1
            if self.rounds > 1:
                return json.dumps({"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.9,
                                                 "quote": "not in the text at all xyz"}]})
        return super().complete(kind, system, user, model, payload)


def test_a_failed_further_search_counts_nowhere_but_your_judgement_does(mixed, monkeypatch):
    ws, ids = mixed
    local = Local()
    use_local_model(monkeypatch, local)
    be = FailSecondRound()
    hid = claimcheck.check_hypothesis(ws, HYP, be, "claude-opus", k=3, per_doc=1, expand=False)
    before = claimcheck.hypothesis_result(ws, hid)
    r = claimcheck.continue_check(ws, hid, be, "claude-opus", k=6, readers=None)
    assert r["passages"] and r.get("ok") is False
    part = claimcheck.result(ws, hid)
    assert [rd["status"] for rd in part["rounds_info"]] == ["done", "failed"]
    second = [x for x in part["passages"] if x["round"] == 2]
    assert second and all(x["round_failed"] and not x["counted"] for x in second)
    # the answer rests on the first search only
    assert part["status"] == before["parts"][0]["status"]
    assert part["balance"] == before["parts"][0]["balance"]
    # a person's own judgement of an excerpt of the failed search counts (another search was answered)
    x = second[0]
    claimcheck.set_judgement(ws, hid, x["passage_id"], "refutes")
    got = next(y for y in claimcheck.result(ws, hid)["passages"] if y["passage_id"] == x["passage_id"])
    assert got["counted"] and claimcheck.hypothesis_result(ws, hid)["balance"]["docs_refuting"] >= 1


def test_round_status_rules():
    def t(tid, status, model="m"):
        return {"task_id": tid, "status": status, "model": model}

    rs = claimcheck._round_status
    person = t("check:u1:person", "done", claimcheck.PERSON)
    assert rs([t("check:u1", "failed"), person]) == "failed"
    assert rs([t("check:u1", "done"), person]) == "done"
    assert rs([t("check:u1", "pending"), person]) == "pending"
    # a local part that failed beside an answered main part is shown on its own (local_failed), as in 0.11.1
    assert rs([t("check:u1", "done"), t("check:u1:local", "failed")]) == "done"
    assert rs([t("check:u1", "failed"), t("check:u1:local", "done")]) == "failed"
    # no main part: the local part decides; only excerpts for the person: nothing left for a model
    assert rs([t("check:u1:local", "failed"), person]) == "failed"
    assert rs([t("check:u1:local", "done"), person]) == "done"
    assert rs([person]) == "done"


# ---------------------------------------------------------------------------------------------
# 2 and 3. excerpts waiting for the person's own judgement, in the status and in Excel
# ---------------------------------------------------------------------------------------------
def test_a_check_of_documents_no_ai_may_read_waits_for_you(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    access.set_documents(ws, list(ids.values()), "none")
    cloud = Cloud()
    hid = claimcheck.check_hypothesis(ws, HYP, cloud, "claude-opus", k=6, per_doc=2, expand=False)
    assert cloud.kinds == []  # no model read anything
    res = claimcheck.hypothesis_result(ws, hid)
    # before 0.14.3: "unsupported" (No evidence found), whose help says the excerpts were read
    assert res["status"] == "not_checked" and res["status_text"] == claimcheck.WAITING_YOU
    assert res["parts"][0]["status_text"] == claimcheck.WAITING_YOU
    assert res["waiting_for_you"] == 6 and res["incomplete"] is False
    row = [h for h in claimcheck.history(ws) if h["hyp_id"] == hid][0]
    assert (row["status"], row["status_text"]) == ("not_checked", claimcheck.WAITING_YOU)
    assert claimcheck.evidence_map(ws)["hypotheses"][0]["status_text"] == claimcheck.WAITING_YOU
    # Excel: nobody has judged these excerpts, and no AI read them
    rows = claimcheck.export_table(ws)
    assert {r["Answer"] for r in rows} == {claimcheck.WAITING_YOU}
    assert {(r["Judgement"], r["Judged by"], r["AI's own judgement"]) for r in rows} == {
        ("Not judged yet", "nobody yet", "Not read by an AI: kept for your own judgement")}
    assert claimcheck.summary_table(ws)[0]["Answer"] == claimcheck.WAITING_YOU
    # your judgement counts at once
    part = res["parts"][0]
    p = part["passages"][0]
    claimcheck.set_judgement(ws, part["claim_id"], p["passage_id"], "supports")
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["status"] == "supported" and res["status_text"] == claimcheck.STATUS_TEXT["supported"]
    row = next(r for r in claimcheck.export_table(ws) if r["Judgement"] == "Supports")
    assert row["Judged by"] == "you" and row["AI's own judgement"] == "Not read by an AI: kept for your own judgement"
    # a person's "not about it" is a reading: with only that, nothing was found
    for x in part["passages"]:
        claimcheck.set_judgement(ws, part["claim_id"], x["passage_id"], "not_relevant")
    assert claimcheck.hypothesis_result(ws, hid)["status"] == "unsupported"


def test_excerpts_waiting_for_you_do_not_count_as_not_about_it(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    hid = claimcheck.check_hypothesis(ws, HYP, NothingFound(), "claude-opus", k=12, per_doc=4, expand=False)
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["waiting_for_you"] > 0
    # the AI read its excerpts and found nothing: that is still "No evidence found" (for the excerpts it read)
    assert res["status"] == "unsupported" and res["status_text"] == claimcheck.STATUS_TEXT["unsupported"]


def test_claim_status_leaves_out_excerpts_waiting_for_you():
    def v(verdict, conf, model="m", user=None):
        return claimcheck.effective({"verdict": verdict, "confidence": conf, "model": model, "user_verdict": user,
                                     "doc_id": "d"})

    waiting = v("not_enough_info", None, claimcheck.PERSON)
    assert claimcheck.claim_status([waiting, waiting], 0.6) == "not_checked"
    assert claimcheck.claim_status([v("supports", 0.9), waiting], 0.6) == "supported"
    assert claimcheck.claim_status([v("not_enough_info", None), waiting], 0.6) == "unsupported"
    assert claimcheck.claim_status([v("not_enough_info", None, claimcheck.PERSON, "refutes"), waiting], 0.6) == \
        "contradicted"
    # a part not known yet keeps a split hypothesis at most partly supported (as for a failed part, see 12)
    assert claimcheck.aggregate(["supported", "not_checked"]) == "partially_supported"


def test_excel_says_when_the_ai_answer_could_not_be_used(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    claimcheck.check_hypothesis(ws, HYP, BadQuotes(), "claude-opus", k=12, per_doc=4, expand=False)
    rows = claimcheck.export_table(ws)
    claude_rows = [r for r in rows if r["AI's own judgement"] == "Not read: the AI's answer could not be used"]
    assert claude_rows and all(r["Judged by"] == "nobody: the check did not work" and
                               r["Judgement"] == "Not counted: the check did not work" for r in claude_rows)
    assert not any(r["Judged by"] == "the AI" for r in rows)  # before 0.14.3: every row said the AI judged it
    assert {r["Counted in the answer"] for r in rows} == {"no"}


def test_excel_says_when_an_excerpt_waits_for_the_local_model(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, Local())
    r = claimcheck.open_check(ws, HYP, terms=["water"], k=12, per_doc=4)  # a chat check: the local part waits
    claimcheck.submit_grades(ws, r["check_id"], [{"passage": 1, "verdict": "supports", "confidence": 0.9,
                                                  "quote": " ".join(r["passages"][0]["text"].split()[:6])}], "One.")
    rows = claimcheck.export_table(ws)
    local = [x for x in rows if x["AI's own judgement"] == "Not read yet: it waits for your local model"]
    assert local and all(x["Judged by"] == "nobody yet" for x in local)
    assert any(x["Judged by"] == "the AI" for x in rows)


# ---------------------------------------------------------------------------------------------
# 4 and 11. a comment does not hide a colleague's verdict; "you" counts your own judgements
# ---------------------------------------------------------------------------------------------
def test_a_comment_of_yours_does_not_hide_a_colleagues_verdict(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    access.set_documents(ws, [ids["local"], ids["none"]], "cloud")
    hid = claimcheck.check_hypothesis(ws, HYP, Cloud(), "claude-opus", k=6, per_doc=2, expand=False)
    part = claimcheck.hypothesis_result(ws, hid)["parts"][0]
    x = next(p for p in part["passages"] if p["ai_verdict"] in ("supports", "partially_supports"))
    cid, pid = part["claim_id"], x["passage_id"]
    with ws.connect() as cx:
        cx.execute("INSERT INTO people(person_id, name, seen_at) VALUES ('p0000000000aa', 'Anna', '2026')")
        people.record(cx, cid, pid, "p0000000000aa", "refutes", "Anna's reason", None)
        people.refresh(cx, [cid])

    def item():
        return next(y for y in claimcheck.result(ws, cid)["passages"] if y["passage_id"] == pid)

    assert (item()["verdict"], item()["judged_by"], item()["my_verdict"]) == ("refutes", "Anna", None)
    claimcheck.set_judgement(ws, cid, pid, None, note="Check the year of this study")
    got = item()
    # before 0.14.3: "supports" (the AI's), judged_by you, user_verdict None
    assert (got["verdict"], got["user_verdict"], got["judged_by"]) == ("refutes", "refutes", "Anna")
    assert got["user_note"] == "Check the year of this study"  # your own comment, yours to edit
    assert got["my_verdict"] is None  # what the page sends with your comment: Anna's verdict is not yours
    assert any(o["mine"] and o["verdict"] is None for o in got["others"])
    # editing your comment as the page does (your own verdict: none) keeps Anna's verdict hers
    claimcheck.set_judgement(ws, cid, pid, got["my_verdict"], note="Check the year: 2019")
    assert ws.query("SELECT verdict FROM judgements WHERE claim_id=? AND passage_id=? AND person_id=?",
                    (cid, pid, people.me()))[0][0] is None
    assert (item()["verdict"], item()["judged_by"], item()["user_note"]) == ("refutes", "Anna", "Check the year: 2019")
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["status"] in ("contested", "contradicted")
    # every "you" count is of your own judgements, not Anna's: Excel, the result and the Results list alike
    assert res["reviewed"] == 0 and res["corrected"] == 0 and res["to_review"] == res["excerpts_read"]
    assert res["to_review_relevant"] == sum(1 for p in res["parts"][0]["passages"] if p["ai_verdict"])
    summary = claimcheck.summary_table(ws)[0]
    assert (summary["Judgements you reviewed"], summary["Judgements you changed"]) == (0, 0)
    row = [h for h in claimcheck.history(ws) if h["hyp_id"] == hid][0]
    assert (row["corrected"], row["reviewed"], row["to_review"]) == (0, 0, res["excerpts_read"])
    # your own verdict wins over Anna's, and keeps your comment
    claimcheck.set_judgement(ws, cid, pid, "partially_supports", note="Check the year of this study")
    got = item()
    assert (got["verdict"], got["judged_by"], got["user_note"]) == ("partially_supports", "you",
                                                                    "Check the year of this study")
    assert got["my_verdict"] == "partially_supports"
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["reviewed"] == 1 and res["corrected"] == int(x["ai_verdict"] != "partially_supports")
    row = [h for h in claimcheck.history(ws) if h["hyp_id"] == hid][0]
    assert (row["reviewed"], row["to_review"]) == (1, res["excerpts_read"] - 1)
    # taking back your comment and verdict: Anna's counts again
    claimcheck.set_judgement(ws, cid, pid, None)
    assert (item()["verdict"], item()["judged_by"]) == ("refutes", "Anna")


def test_the_result_page_saves_your_comment_with_your_own_verdict():
    js = (Path(__file__).parent.parent / "src" / "enlens_claims" / "gui" / "static" / "views" / "result.js").read_text(
        encoding="utf-8")
    assert "put(p.my_verdict || null, note.value.trim()," in js        # the comment field
    assert "{ verdict: p.my_verdict || null, note: hint }" in js         # the hint of "Ask the AI to read this again"
    assert "const prev = { verdict: p.my_verdict || null," in js        # Undo
    assert "put(current || null, note.value.trim()" not in js and "{ verdict: p.user_verdict || null, note: hint }" not in js


def test_a_selection_that_cuts_a_word_can_be_labelled(mixed, monkeypatch):
    from enlens_claims import profile

    ws, ids = mixed
    pid, text = next((r["passage_id"], r["text"]) for r in ws.query("SELECT passage_id, text FROM passages WHERE "
                                                                     "doc_id=? AND section='body'", (ids["cloud"],)))
    i = text.index("hydrogen")
    sel = text[i + 2:i + 20]  # "drogen …": a mouse selection that starts inside a word
    lid = profile.add_label(ws, "sdg", pid, "6.4", quote=sel)  # before: "The quote must be text from this passage."
    q = ws.scalar("SELECT quote FROM labels WHERE label_id=?", (lid,))
    assert q.startswith("hydrogen") and find_quote(text, q)


def test_the_original_file_view_places_quotes_accepted_before(tmp_path):
    from enlens_claims.gui import server

    f = tmp_path / "notes.txt"
    f.write_text("Another study found no link between hydrogen and water. " + "Long text " * 300, encoding="utf-8")
    assert server._text_with_quote(f, "nother study found", "notes") is not None  # a quote stored before 0.14.3
    long_quote = "Another study found no link between hydrogen and water. " + "Long text " * 250
    assert len(long_quote) > 2000 and server._text_with_quote(f, long_quote, "notes") is not None  # cut mid-word


# ---------------------------------------------------------------------------------------------
# 5. quotes: whole words, no joined words, a judgement's quote long enough
# ---------------------------------------------------------------------------------------------
def test_a_quote_is_found_as_whole_words_only():
    assert find_quote("Another study found no link.", "not") is None
    assert find_quote("It is illegal to export hydrogen from the zone.", "legal to export hydrogen") is None
    assert find_quote("The effect is nowhere near as strong.", "the effect is now here") is None
    assert find_quote("Unsustainable practices remain common.", "sustainable practices remain common") is None
    assert find_quote("Costs fell by 2.5 percent last year.", "5 percent last year") is None
    # whole words, with the PDF quirks real documents have
    hit = find_quote("It is legal to export hydrogen.", "legal to export hydrogen")
    assert hit and hit[2] == "exact"
    hay = "cooking projects44. This study assesses the emissions"
    assert find_quote(hay, "clean cooking projects") is None and find_quote(hay, "cooking projects")
    assert find_quote("rRenewables fared better than coal.", "Renewables fared better")  # a bullet glued to a word
    assert find_quote("new jobs by 2050expected addition", "new jobs by 2050")             # a figure glued to a word
    assert find_quote("supply by 2030.106 But these jobs", "supply by 2030")                 # a footnote after a stop
    hit = find_quote("Twenty plants wi ll produce 650 tons of hydrogen daily.", "will produce 650 tons")
    assert hit and hit[2] == "spacing"                                                        # PDF split a word
    hit = find_quote("Freshwater is an issue in water -stressed areas.", "issue in water-stressed areas")
    assert hit and hit[2] == "spacing"
    # accented letters are letters; scripts written without spaces have an edge between any two characters
    assert find_quote("A vízhiány nő a száraz régiókban.", "víz nő a száraz") is None
    assert find_quote("A vízhiány nő a száraz régiókban.", "vízhiány nő a száraz")
    assert find_quote("绿色氢气生产会增加干旱地区的水资源压力。", "增加干旱地区的水资源压力")
    assert find_quote("グリーン水素の生産は水ストレスを高める。", "水ストレスを高める")
    # the looser search (to place quotes stored before), and a person's selection widened to whole words
    assert find_quote("Another study found no link.", "nother study", whole_words=False)
    hay = "Another study found no link."
    a, b, _k = find_selection(hay, "nother study fo")
    assert hay[a:b] == "Another study found"
    hay = "The café opened. 绿色氢气生产会增加压力"
    a, b, _k = find_selection(hay, "The caf")  # a combining accent stays with its letter
    assert hay[a:b] == "The café"
    a, b, _k = find_selection(hay, "氢气生产")  # no widening in a script written without spaces
    assert hay[a:b] == "氢气生产"


def test_a_quote_may_not_end_inside_a_number():
    assert find_quote("Emissions rose by 2,500 tonnes a year.", "Emissions rose by 2") is None
    assert find_quote("Costs fell by 1.5 million euros.", "Costs fell by 1") is None
    assert find_quote("Costs fell by 1.5 million euros.", "Costs fell by 1.") is None
    assert find_quote("Costs fell by 1.5 million euros.", "5 million euros") is None
    assert find_quote("The IRA offers support to 2032,12 with the majority", "The IRA offers support to 2032") is None
    # a footnote number after a year and a full stop (PDF text) is not part of the number
    assert find_quote("jobs worldwide by 2030.106 But these jobs", "jobs worldwide by 2030")
    assert find_quote("jobs worldwide by 2030.106 But these jobs", "jobs worldwide by 2030.")
    assert find_quote("Costs fell by 1.5 million euros.", "Costs fell by 1.5 million")


def test_the_instructions_ask_for_three_whole_words():
    from enlens_claims import mcp_server, prompts

    for kind in ("check", "reread", "second", "verify_set", "verify"):
        assert "at least three whole words" in prompts.system_prompt(kind), kind
    assert (prompts.VERSIONS["check"], prompts.VERSIONS["reread"], prompts.VERSIONS["second"]) == ("check-v5",) * 3
    assert (prompts.VERSIONS["verify"], prompts.VERSIONS["verify_set"]) == ("verify-v2", "verify-set-v2")
    assert "at least three whole words" in claimcheck.chat_rules()  # what a Claude chat is given with the excerpts
    assert "at least three whole words" in mcp_server.INSTRUCTIONS
    assert "at least three whole words" in mcp_server.Grade.model_fields["quote"].description


def test_a_judgements_quote_needs_a_few_words():
    assert grade_quote_problem("not") and grade_quote_problem("no effect")
    assert grade_quote_problem("no significant effect") is None    # three words
    assert grade_quote_problem("water-intensive") is None            # 15 characters
    assert grade_quote_problem("水资源压力") is None and grade_quote_problem("压力")  # a character is about a word


def test_a_short_or_partial_quote_is_sent_back(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    access.set_documents(ws, list(ids.values()), "cloud")
    cid = claimcheck.open_check(ws, HYP, terms=["water"], k=4, per_doc=2)["check_id"]
    shown = json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (f"check:{cid}",)))["passages"][0]
    words = shown["text"].split()
    one = next(w for w in words if w.isalpha() and 3 <= len(w) < 15)
    short = claimcheck.submit_grades(ws, cid, [{"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": one}])
    assert not short["accepted"] and "too short" in short["problems"][0]
    i = next(i for i, w in enumerate(words) if i >= 3 and w.isalpha() and len(w) >= 6)
    cut = " ".join(words[:i] + [words[i][:3]])  # ends inside a word
    partial = claimcheck.submit_grades(ws, cid, [{"passage": 1, "verdict": "supports", "confidence": 0.9,
                                                  "quote": cut}])
    assert not partial["accepted"] and "part of a word" in partial["problems"][0]
    ok = claimcheck.submit_grades(ws, cid, [{"passage": 1, "verdict": "supports", "confidence": 0.9,
                                             "quote": " ".join(words[:i + 1])}])
    assert ok["accepted"]
    # your own sentence is a selection in the excerpt: one that cuts a word is widened to the whole word
    claimcheck.set_judgement(ws, cid, shown["passage_id"], "supports", quote=cut)
    got = next(x for x in claimcheck.result(ws, cid)["passages"] if x["passage_id"] == shown["passage_id"])
    assert got["quote_by"] == "you" and got["quote"].split() == words[:i + 1]
    assert find_quote(shown["text"], got["quote"])  # found again as whole words (highlights, the original file)


# ---------------------------------------------------------------------------------------------
# 6. a local model's answer it could not finish is a rejected attempt
# ---------------------------------------------------------------------------------------------
class CutOffOnce(Local):
    """A local model whose first judging answer is cut off at the length limit."""

    def __init__(self):
        super().__init__()
        self.cut = 1

    def complete(self, kind, system, user, model, payload=None):
        if kind == "check" and self.cut:
            self.cut -= 1
            self.kinds.append(kind)
            raise AnswerError(f"{model}'s answer was cut off at 2,600 tokens; the model is probably repeating itself.",
                              '{"evidence": [{"passage": 1, "verdict": "supp')
        self.sent.append(user)
        return super().complete(kind, system, user, model, payload)


def test_an_answer_cut_off_is_asked_again(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    local = CutOffOnce()
    hid = claimcheck.check_hypothesis(ws, HYP, local, "qwen", k=6, per_doc=2, expand=False)
    tid = f"check:{hid}"
    got = ws.query("SELECT attempt, valid, errors_json, raw_json FROM results WHERE task_id=? ORDER BY attempt", (tid,))
    assert [r["valid"] for r in got] == [0, 1]
    assert "cut off" in json.loads(got[0]["errors_json"])[0] and got[0]["raw_json"].startswith('{"evidence"')
    assert "YOUR PREVIOUS ANSWER HAD THESE PROBLEMS" in local.sent[-1] and "cut off" in local.sent[-1]
    assert claimcheck.hypothesis_result(ws, hid)["status"] in ("supported", "partially_supported", "contested")


def test_settings_problems_are_still_said_at_once(mixed, monkeypatch):
    from enlens_claims.llm import BackendError

    srv, url = fake_servers.start("ollama")
    try:
        # reasoning that uses up the whole allowance: a setting to change, not a try to repeat
        with pytest.raises(BackendError) as e:
            OllamaBackend(base_url=url).complete("expand", "You prepare a search", "CLAIM:\nx", fake_servers.THINKER, {})
        assert "on reasoning without answering" in str(e.value) and not isinstance(e.value, AnswerError)
    finally:
        srv.shutdown()
    # a full context: the prompt was cut; raise the context length
    be = OllamaBackend(base_url="http://127.0.0.1:9", think=False)
    monkeypatch.setattr(be, "check_memory", lambda m: None)
    monkeypatch.setattr(be, "_can_think", lambda m: False)
    monkeypatch.setattr(be, "_stream", lambda body, model, info, t0, budget: (
        ['{"terms": ["a"]}'], {"prompt_eval_count": be.num_ctx, "done_reason": "stop"}))
    with pytest.raises(BackendError) as e:
        be.complete("expand", "You prepare a search", "CLAIM:\nx", "m", {})
    assert "filled the whole context" in str(e.value) and not isinstance(e.value, AnswerError)
    # and a check stopped by one leaves nothing behind, as before
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    with pytest.raises(BackendError):
        claimcheck.check_hypothesis(ws, HYP, be, "m", k=3, per_doc=1)
    assert claimcheck.history(ws) == []


def test_a_model_stuck_writing_blank_space_keeps_the_check_and_the_batch_going(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    access.set_documents(ws, list(ids.values()), "cloud")
    srv, url = fake_servers.start("ollama")
    try:
        be = OllamaBackend(base_url=url, think=False)
        # before 0.14.3 this raised "got stuck writing blank space" and deleted the hypothesis
        hid = claimcheck.check_hypothesis(ws, HYP, be, fake_servers.LOOPER, k=3, per_doc=2, expand=False)
        res = claimcheck.hypothesis_result(ws, hid)
        assert res["status"] == "failed" and "blank space" in res["parts"][0]["errors"][0]
        assert ws.scalar("SELECT attempts FROM tasks WHERE task_id=?", (f"check:{hid}",)) == tasks.MAX_ATTEMPTS
        # Check several goes on to the next hypothesis (it stopped at the first before)
        out = claimcheck.check_batch(ws, [{"text": HYP}, {"text": "Electrolysis needs large amounts of fresh water."}],
                                     be, fake_servers.LOOPER, k=3, per_doc=2, expand=False)
        assert out["stopped"] is None and len(out["checked"]) == 2
    finally:
        srv.shutdown()


# ---------------------------------------------------------------------------------------------
# 7 and 8. the stronger model's tries
# ---------------------------------------------------------------------------------------------
class Seq(Cloud):
    """The Claude API: a bad answer, an unsure good one (which steps up), then the stronger model's bad answers."""
    router = routing.Router(route="anthropic")

    def __init__(self, good_from: int = 99):
        super().__init__()
        self.n, self.good_from, self.calls = 0, good_from, []

    def complete(self, kind, system, user, model, payload=None):
        if kind != "check":
            return super().complete(kind, system, user, model, payload)
        self.n += 1
        self.calls.append(model)
        good = {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.4 if self.n == 2 else 0.9,
                              "quote": _first_words(payload)}]}
        bad = {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": "zzz not there at all"}]}
        return json.dumps(good if self.n == 2 or self.n >= self.good_from else bad)


def test_the_stronger_model_gets_its_own_three_tries(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    access.set_documents(ws, list(ids.values()), "cloud")
    be = Seq()
    steps = []
    hid = claimcheck.check_hypothesis(ws, HYP, be, "claude-sonnet-5-5", k=3, expand=False,
                                      progress=lambda s, m, i=None: steps.append((s, m)))
    # two tries of the first model, then three of the stronger one (before 0.14.3: two, and "again" stayed set)
    assert be.calls == ["claude-sonnet-5-5"] * 2 + ["claude-opus-5-5"] * 3
    t = ws.query("SELECT status, step, again FROM tasks WHERE task_id=?", (f"check:{hid}",))[0]
    assert (t["status"], t["step"], t["again"]) == ("done", 1, 0)
    info = claimcheck.hypothesis_result(ws, hid)["parts"][0]["rounds_info"][0]
    assert info["stronger_waiting"] is False
    done = [m for s, m in steps if s == "grade_done"][0]
    assert "could not be used" not in done  # the first model's accepted answer counts


def test_the_stronger_models_third_try_can_still_count(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    access.set_documents(ws, list(ids.values()), "cloud")
    be = Seq(good_from=5)
    hid = claimcheck.check_hypothesis(ws, HYP, be, "claude-sonnet-5-5", k=3, expand=False)
    assert be.calls[-1] == "claude-opus-5-5" and len(be.calls) == 5
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["stronger"]["models"] == ["claude-opus-5-5"]
    assert "judging again as the stronger model" in claimcheck.models_text(res)


class BadTwiceThenGood(Seq):
    """Two rejected answers: the third and last try goes to the stronger model, and it is accepted."""

    def complete(self, kind, system, user, model, payload=None):
        if kind != "check":
            return super().complete(kind, system, user, model, payload)
        self.n += 1
        self.calls.append(model)
        q = _first_words(payload) if self.n >= 3 else "zzz not there at all"
        return json.dumps({"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": q}]})


def test_a_stronger_models_last_try_is_not_reading_again(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    access.set_documents(ws, list(ids.values()), "cloud")
    be = BadTwiceThenGood()
    hid = claimcheck.check_hypothesis(ws, HYP, be, "claude-sonnet-5-5", k=3, expand=False)
    assert be.calls == ["claude-sonnet-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["models_used"] == [{"model": "claude-opus-5-5", "roles": ["judging the excerpts"]}]
    assert "again" not in claimcheck.models_text(res)


def test_a_rejected_stronger_answer_stays_with_the_claim(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    access.set_documents(ws, list(ids.values()), "cloud")
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    hid = claimcheck.queue_check(ws, HYP, routing.from_settings(home.load_settings()), k=3, expand=False)
    got = taskqueue.next_tasks(ws, "check")
    t = got["tasks"][0]
    payload = json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (t["task_id"],)))
    unsure = {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.4, "quote": _first_words(payload)}]}
    r = taskqueue.submit(ws, got["claim"], [{"task_id": t["task_id"], "answer": unsure}])
    assert r["results"][0].get("read_again_by")
    got2 = taskqueue.next_tasks(ws, "check")
    monkeypatch.setitem(tasks.prompts.VERSIONS, "check", "check-v5-later")  # instructions changed meanwhile
    bad = {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": "words not in the passage"}]}
    r = taskqueue.submit(ws, got2["claim"], [{"task_id": t["task_id"], "answer": bad}])
    # before 0.14.3 the claim was released here, so the fix below was refused ("claim lapsed")
    assert r["open"] == [t["task_id"]] and r["results"][0]["attempts_left"] == 2
    # the first answer is still the one in force, with the version of its instructions
    assert ws.scalar("SELECT prompt_version FROM tasks WHERE task_id=?", (t["task_id"],)) == "check-v5"
    sure = {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.95, "quote": _first_words(payload)}]}
    r = taskqueue.submit(ws, got2["claim"], [{"task_id": t["task_id"], "answer": sure}])
    assert r["results"][0]["stored"] and r["open"] == []
    row = ws.query("SELECT again, claimed_by, prompt_version FROM tasks WHERE task_id=?", (t["task_id"],))[0]
    assert (row["again"], row["claimed_by"], row["prompt_version"]) == (0, None, "check-v5-later")
    assert claimcheck.hypothesis_result(ws, hid)["status"] == "supported"


def test_three_rejected_stronger_answers_give_the_task_back_with_the_first_answer(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    access.set_documents(ws, list(ids.values()), "cloud")
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    hid = claimcheck.queue_check(ws, HYP, routing.from_settings(home.load_settings()), k=3, expand=False)
    got = taskqueue.next_tasks(ws, "check")
    tid = got["tasks"][0]["task_id"]
    payload = json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (tid,)))
    unsure = {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.4, "quote": _first_words(payload)}]}
    taskqueue.submit(ws, got["claim"], [{"task_id": tid, "answer": unsure}])
    got2 = taskqueue.next_tasks(ws, "check")
    bad = {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": "words not in the passage"}]}
    for left in (2, 1, 0):
        r = taskqueue.submit(ws, got2["claim"], [{"task_id": tid, "answer": bad}])
        assert r["results"][0]["attempts_left"] == left
    assert r["open"] == []  # given up: released
    row = ws.query("SELECT status, again, claimed_by FROM tasks WHERE task_id=?", (tid,))[0]
    assert (row["status"], row["again"], row["claimed_by"]) == ("done", 0, None)
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["status"] in ("uncertain", "supported") and not res["parts"][0]["rounds_info"][0]["stronger_waiting"]


# ---------------------------------------------------------------------------------------------
# 9. every model a check used, for a methods section
# ---------------------------------------------------------------------------------------------
def test_excel_names_every_model_the_check_used(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, Local())
    hid = claimcheck.check_hypothesis(ws, HYP, Cloud(), "claude-opus", k=12, per_doc=4, expand=True)
    res = claimcheck.hypothesis_result(ws, hid)
    used = {m["model"]: m["roles"] for m in res["models_used"]}
    assert set(used) == {"claude-opus", "local-model"}
    assert "judging the excerpts" in used["claude-opus"] and "search words" in used["claude-opus"]
    assert used["local-model"] == ["judging the excerpts of documents marked Only a local AI"]
    col = claimcheck.summary_table(ws)[0]["AI model used (for a methods section)"]
    assert "claude-opus (" in col and "local-model (judging the excerpts of documents marked Only a local AI)" in col


def test_the_model_answering_by_queue_is_named_not_the_one_set_at_the_start(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    access.set_documents(ws, list(ids.values()), "cloud")
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    hid = claimcheck.queue_check(ws, HYP, routing.from_settings(home.load_settings()), k=3, expand=False)
    got = taskqueue.next_tasks(ws, "check")
    t = got["tasks"][0]
    payload = json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (t["task_id"],)))
    unsure = {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.4, "quote": _first_words(payload)}]}
    taskqueue.submit(ws, got["claim"], [{"task_id": t["task_id"], "answer": unsure}])
    got2 = taskqueue.next_tasks(ws, "check")
    sure = {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.95, "quote": _first_words(payload)}]}
    taskqueue.submit(ws, got2["claim"], [{"task_id": t["task_id"], "answer": sure}])
    res = claimcheck.hypothesis_result(ws, hid)
    col = claimcheck.summary_table(ws)[0]["AI model used (for a methods section)"]
    # before 0.14.3 the column said only the model chosen when the check started (res["model"])
    assert got["model"] in col and got2["model"] in col and got2["model"] != got["model"]
    assert res["model"] == got["model"]


# ---------------------------------------------------------------------------------------------
# 10. the evidence map agrees with the Results list
# ---------------------------------------------------------------------------------------------
def test_a_document_does_not_decide_an_answer_not_given_yet(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, Local())
    r = claimcheck.open_check(ws, HYP, terms=["water"], k=12, per_doc=4)
    claimcheck.submit_grades(ws, r["check_id"], [{"passage": 1, "verdict": "supports", "confidence": 0.9,
                                                  "quote": " ".join(r["passages"][0]["text"].split()[:6])}], "One.")
    assert claimcheck.hypothesis_result(ws, r["check_id"])["status"] == "waiting"  # the local part waits
    m = claimcheck.evidence_map(ws)
    assert m["hypotheses"][0]["status"] == "waiting"
    assert [d["decides"] for d in m["documents"]] == [0] * len(m["documents"])  # before 0.14.3: 1


# ---------------------------------------------------------------------------------------------
# 12. a failed part keeps a split hypothesis cautious, as the manual now says
# ---------------------------------------------------------------------------------------------
def test_a_failed_part_keeps_a_split_hypothesis_at_most_partly_supported():
    assert claimcheck.aggregate(["supported", "failed"]) == "partially_supported"
    assert claimcheck.aggregate(["contradicted", "failed"]) == "contradicted"
    assert claimcheck.aggregate(["failed", "failed"]) == "failed"
    manual = (Path(__file__).parent.parent / "docs" / "MANUAL.md").read_text(encoding="utf-8")
    assert "Parts whose check failed are left out" not in manual
    assert "is then at most partly supported" in manual


# ---------------------------------------------------------------------------------------------
# 13. the prompt version recorded is the one the model was given
# ---------------------------------------------------------------------------------------------
def test_the_prompt_version_is_the_one_the_model_was_given(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    access.set_documents(ws, list(ids.values()), "cloud")
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    hid = claimcheck.queue_check(ws, HYP, routing.from_settings(home.load_settings()), k=3, expand=False)
    tid = f"check:{hid}"
    assert ws.scalar("SELECT prompt_version FROM tasks WHERE task_id=?", (tid,)) == "check-v5"
    monkeypatch.setitem(tasks.prompts.VERSIONS, "check", "check-v5-updated")  # ENLENS updated while it waited
    got = taskqueue.next_tasks(ws, "check")
    assert got["prompt_version"] == "check-v5-updated"
    payload = json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (tid,)))
    sure = {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.95, "quote": _first_words(payload)}]}
    taskqueue.submit(ws, got["claim"], [{"task_id": tid, "answer": sure}])
    assert ws.scalar("SELECT prompt_version FROM results WHERE task_id=?", (tid,)) == "check-v5-updated"
    assert ws.scalar("SELECT prompt_version FROM tasks WHERE task_id=?", (tid,)) == "check-v5-updated"
    assert {r[0] for r in ws.query("SELECT prompt_version FROM verifications WHERE subject_id=?", (hid,))} == \
        {"check-v5-updated"}


def test_the_file_queue_records_the_instructions_written_with_the_task(loaded, monkeypatch):
    tasks.make_split(loaded, model="m")
    monkeypatch.setitem(tasks.prompts.VERSIONS, "split", "split-exported")
    tasks.export(loaded, "split")
    assert (loaded.root / "tasks" / "split" / "SYSTEM.md").exists()
    monkeypatch.setitem(tasks.prompts.VERSIONS, "split", "split-newer")  # updated before the answers came back
    good = {"claims": [{"text": "Electrolysis needs large amounts of fresh water.",
                        "quote": "Electrolysis needs large amounts of fresh water", "direction": "negative"}]}
    assert tasks.ingest_result(loaded, "split:6.4", good)[0]
    assert loaded.scalar("SELECT prompt_version FROM results WHERE task_id='split:6.4'") == "split-exported"


# ---------------------------------------------------------------------------------------------
# lead's follow-ups after merging the slices
# ---------------------------------------------------------------------------------------------
def test_the_connector_says_a_check_waits_for_your_judgement(mixed, monkeypatch):
    from enlens_claims import mcp_server

    ws, ids = mixed
    use_local_model(monkeypatch, None)
    access.set_documents(ws, list(ids.values()), "none")
    hid = claimcheck.check_hypothesis(ws, HYP, Cloud(), "claude-opus", k=6, per_doc=2, expand=False)
    cid = claimcheck.hypothesis_result(ws, hid)["parts"][0]["claim_id"]
    # before: "Not finished yet", while the app said "Waiting for your judgement"
    assert mcp_server._summary(ws, cid)["status_text"] == claimcheck.WAITING_YOU


def test_the_original_file_view_reads_the_file_as_it_was_added(tmp_path):
    from enlens_claims.gui import server

    f = tmp_path / "jegyzet.txt"
    text = ("Az elektrolízissel előállított hidrogén vízhiányt okozhat a száraz régiókban. A vízhiány súlyos gond, "
            "és a hidrogéntermelés növeli. Ezért a tervezőknek előre kell számolniuk a vízigénnyel.")
    f.write_bytes(text.encode("cp1250"))  # a few sentences, as a document has (one short line is ambiguous)
    # before: read as UTF-8, every accented letter became "�" and the quote was not found
    assert server._text_with_quote(f, "előállított hidrogén vízhiányt okozhat", "jegyzet") is not None
