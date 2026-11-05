"""0.13.7: checking citations against the sources they cite.

A text (a draft pasted or read from a file, or one of the project's documents) is read for its citations: author-year
ones in brackets and in the sentence ("(Smith & Jones, 2020)", "Smith et al. (2020a) found…"), and numbered ones with
the text's numbered reference list. Each gets the claim in front of it and the sentences before it, and each cited
work is looked up in the bibliography (the work's documents linked to it). A work with a document gets a check of
its own, against that document only, with the claim's sentences given to the AI as context; its answer is "Source
accurate", or a notice (only partly supported, not found in the source, the source says otherwise…). The tests never
touch a real Claude, Zotero or the network: the model is a stand-in that records what it is sent.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from helpers_0110 import Cloud, Local, use_local_model

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"

DRAFT = """Remote work and wellbeing

Working from home spread quickly after 2020. Hybrid workers commute fewer hours a week (Verhoeven & Okafor, 2025). Commuting emissions fall by a third (Rivermouth Mobility Institute, 2024), while productivity doubles (Verhoeven & Okafor, 2025).
According to Lindqvist et al. (2025), loneliness rises among young employees. Mueller (2018) found that hybrid schedules reduce sick leave, but see Van der Berg (2022).
The figures were checked twice (Figure 3, 2020). Costs fell (Smith, 2019) and wages rose (Nowhere & Nobody, 2011).
"""


# ---------------------------------------------------------------------------------------------
# finding citations, their claims and their contexts (no project needed)
# ---------------------------------------------------------------------------------------------
def test_finding_author_year_citations():
    from enlens_claims.citations import find_citations

    found = find_citations(DRAFT)["citations"]
    by = {c["marker"]: c for c in found}
    assert [c["marker"] for c in found] == ["(Verhoeven & Okafor, 2025)", "(Rivermouth Mobility Institute, 2024)",
                        "(Verhoeven & Okafor, 2025)", "Lindqvist et al. (2025)", "Mueller (2018)",
                        "Van der Berg (2022)", "(Smith, 2019)", "(Nowhere & Nobody, 2011)"]
    # the claim in front of a citation, and the sentences before it as its context
    first = found[0]
    assert first["claim"] == "Hybrid workers commute fewer hours a week."
    assert first["before"] == "Working from home spread quickly after 2020."
    assert "(Verhoeven & Okafor, 2025)" in first["sentence"]
    # two citations in one sentence: each its own part of it
    assert found[1]["claim"] == "Commuting emissions fall by a third."
    assert found[2]["claim"] == "Productivity doubles."
    # in the sentence: what follows "According to X," or "X found that"
    assert by["Lindqvist et al. (2025)"]["claim"] == "Loneliness rises among young employees."
    assert by["Mueller (2018)"]["claim"] == "Hybrid schedules reduce sick leave."
    # "but see": cited for another view, left out of the checks unless the person puts it back
    assert by["Van der Berg (2022)"]["refs"][0]["signal"] == "contrast"
    # "(Figure 3, 2020)" is not a citation; a heading is not a sentence
    assert not any("Figure" in c["marker"] for c in found)
    assert all("Remote work and wellbeing" not in c["before"] for c in found)


def test_harder_citations():
    from enlens_claims.citations import find_citations

    text = ("Hybrid work is common in Europe (Smith 2019, 2020; Lee 2018). J. Smith (2021) showed that office use "
            "fell. Remote work raises output (e.g., Bloom et al. 2015, p. 4) but it lowers mentoring (OECD 2021; "
            "World Bank 2020). However, Kim (2017) found that pay gaps widen. The World Health Organization [WHO] "
            "(2019) warned about sedentary behaviour (see also WHO, 2021). Smith's (2020a) survey shows that "
            "emissions fell. Müller and de Vries (2016) argue that teams drift apart.")
    found = find_citations(text)["citations"]
    refs = [(r["author"], r["year"]) for c in found for r in c["refs"]]
    assert refs == [("Smith", "2019"), ("Smith", "2020"), ("Lee", "2018"), ("J. Smith", "2021"),
                    ("Bloom et al.", "2015"), ("OECD", "2021"), ("World Bank", "2020"), ("Kim", "2017"),
                    ("World Health Organization [WHO]", "2019"), ("WHO", "2021"), ("Smith's", "2020a"),
                    ("Müller and de Vries", "2016")]
    claims = {c["marker"]: c["claim"] for c in found}
    assert claims["J. Smith (2021)"] == "Office use fell."
    assert claims["(e.g., Bloom et al. 2015, p. 4)"] == "Remote work raises output."
    assert claims["(OECD 2021; World Bank 2020)"] == "It lowers mentoring."
    assert claims["Kim (2017)"] == "Pay gaps widen."
    # the author is the subject when no "that" follows; the abbreviation is left out of the claim
    assert claims["World Health Organization [WHO] (2019)"] == "World Health Organization warned about sedentary behaviour."
    assert claims["(see also WHO, 2021)"].endswith("warned about sedentary behaviour.")
    assert claims["Smith's (2020a)"] == "Emissions fell."
    assert claims["Müller and de Vries (2016)"] == "Teams drift apart."


def test_numbered_citations_need_the_reference_list():
    from enlens_claims.citations import find_citations

    body = "Productivity rose in the first year [1]. Later studies disagree [2, 4–5]. Others found no change.[3]\n\n"
    refs = ("References\n1. Bloom N, Liang J. Does working from home work? QJE 2015.\n2. Smith J. Routine tasks at "
            "home. 2019.\n3. Lee K. Creative work at home. 2021.\n4. Kim S. Pay gaps. 2017.\n5. Mueller A. Sick "
            "leave. 2018.\n")
    got = find_citations(body + refs)
    assert [(c["marker"], [r["number"] for r in c["refs"]]) for c in got["citations"]] == [
        ("[1]", [1]), ("[2, 4–5]", [2, 4, 5]), ("[3]", [3])]
    assert got["citations"][2]["claim"] == "Others found no change."  # a number after the full stop
    assert got["numeric_unread"] == 0
    # the reference list itself is never read as citations
    assert all(c["start"] < got["refs_start"] for c in got["citations"])
    # without the list: counted, so the page can say how many could not be read
    alone = find_citations(body + "And Smith (2019) agrees with this view.")
    assert alone["numeric_unread"] == 3 and [c["marker"] for c in alone["citations"]] == ["Smith (2019)"]


def test_an_authors_reference_list_is_not_read_as_citations():
    from enlens_claims.citations import find_citations

    text = ("Body text. Remote work lowers commuting (Smith, 2019). " * 3
            + "\n\nReferences\nSmith, J. (2019). Routine tasks at home. Journal of Work.\n"
              "Lee, K., & Kim, S. (2021). Creative work. Journal of Things.\n")
    got = find_citations(text)
    assert len(got["citations"]) == 3 and {c["marker"] for c in got["citations"]} == {"(Smith, 2019)"}


# ---------------------------------------------------------------------------------------------
# which work of the bibliography a citation names
# ---------------------------------------------------------------------------------------------
def _work(key, title, year, *authors, doi=None, org=False):
    from enlens_claims import bibliography as b

    creators = [{"name": a} if org else {"last": a.split()[-1], "first": " ".join(a.split()[:-1])} for a in authors]
    if not org:  # particles stay with the surname, as Zotero keeps them
        creators = [{"last": a, "first": ""} if " " in a and a.split()[0].islower() else c
                    for a, c in zip(authors, creators)]
    return b._work(key, "journalArticle", title, creators, year, doi, None, None, None, f"zotero://{key}", [])


LIBRARY = [
    _work("w-smith19", "Routine tasks at home", "2019", "John Smith"),
    _work("w-smith20a", "A survey of commuting", "2020", "John Smith"),
    _work("w-smith20b", "Better offices", "2020", "John Smith"),
    _work("w-smithjones", "Two of us", "2020", "John Smith", "Kate Jones"),
    _work("w-lee", "Creative work", "2021", "Ann Lee", "Bo Kim"),
    _work("w-lindq", "Loneliness at home", "2025", "Eva Lindqvist", "Per Holm", "Ola Berg"),
    _work("w-berg", "Sick leave in the Netherlands", "2022", "van der Berg"),
    _work("w-muller", "Teams that drift", "2016", "Jan Müller"),
    _work("w-who", "Physical activity", "2019", "World Health Organization", org=True),
    _work("w-mob", "Commuting less, emitting less?", "2024", "Rivermouth Mobility Institute", org=True,
          doi="10.5555/rmi.2024.12"),
]


@pytest.fixture
def library(ws):
    from enlens_claims import bibliography as b

    b.save(ws, LIBRARY, {"kind": "file", "name": "my.bib", "format": "bibtex"})
    return ws


def test_matching_citations_with_works(library):
    from enlens_claims.citations import BibIndex

    ix = BibIndex(library)
    m = ix.match
    assert m("Smith", "2019")["key"] == "w-smith19"
    # two works of one author in one year: 2020a and 2020b in the order of their titles; without a letter, ask
    assert m("Smith", "2020a")["key"] == "w-smith20a" and m("Smith", "2020b")["key"] == "w-smith20b"
    assert m("Smith", "2020")["state"] == "ambiguous" and set(m("Smith", "2020")["candidates"]) == {
        "w-smith20a", "w-smith20b"}
    assert m("Smith & Jones", "2020")["key"] == "w-smithjones"  # the second author decides
    assert m("Lee and Kim", "2021")["key"] == "w-lee"
    assert m("Lindqvist et al.", "2025")["key"] == "w-lindq"
    assert m("Van der Berg", "2022")["key"] == "w-berg" and m("Berg", "2022")["key"] == "w-berg"
    assert m("Muller", "2016")["key"] == "w-muller"  # accents aside
    assert m("J. Smith", "2019")["key"] == "w-smith19"
    assert m("World Health Organization [WHO]", "2019")["key"] == "w-who" and m("WHO", "2019")["key"] == "w-who"
    assert m("Rivermouth Mobility Institute", "2024")["key"] == "w-mob"
    assert m("Sweden, Lindqvist", "2025")["key"] == "w-lindq"  # a word before the author's name
    # another year: not taken, but offered (a wrong year in the draft is worth a look)
    wrong = m("Lindqvist et al.", "2024")
    assert wrong["state"] == "none" and wrong["candidates"] == ["w-lindq"]
    assert m("Nowhere & Nobody", "2011") == {"state": "none", "key": None, "candidates": []}
    # a numbered list's entry: by its DOI, else its title with the first author
    assert ix.match_entry("Rivermouth Mobility Institute. Report 12. doi:10.5555/rmi.2024.12")["key"] == "w-mob"
    assert ix.match_entry("Lee A, Kim B. Creative work. J Things 2021;3:1-9.")["key"] == "w-lee"


# ---------------------------------------------------------------------------------------------
# a project: documents, a bibliography, a draft
# ---------------------------------------------------------------------------------------------
SOURCES = {
    "panel.txt": ("Working from home and wellbeing: evidence from the Lowland Household Panel\nVerhoeven and Okafor, "
                  "2025\n\nHybrid workers commute on average 3.1 fewer hours a week than office workers. Their "
                  "productivity stayed the same in our panel. Life satisfaction rose slightly among hybrid workers."),
    "mobility.txt": ("Commuting less, emitting less? A survey of 4,000 workers in the Rivermouth region\nRivermouth "
                     "Mobility Institute, 2024\ndoi:10.5555/rmi.2024.12\n\nRemote work reduces commuting emissions, "
                     "but by less than often assumed: emissions from commuting fall by about a tenth."),
    "lonely.txt": ("Loneliness at home\nLindqvist, Holm and Berg, 2025\n\nLoneliness rises among young employees "
                   "who work from home most days. Older employees report no change."),
}
WORKS = [
    _work("w-panel", "Working from home and wellbeing: evidence from the Lowland Household Panel", "2025",
          "M. Verhoeven", "A. Okafor"),
    _work("w-mob", "Commuting less, emitting less? A survey of 4,000 workers in the Rivermouth region", "2024",
          "Rivermouth Mobility Institute", org=True, doi="10.5555/rmi.2024.12"),
    _work("w-lindq", "Loneliness at home", "2025", "Eva Lindqvist", "Per Holm", "Ola Berg"),
    _work("w-mueller", "Sick leave and hybrid schedules", "2018", "Anna Mueller"),  # no document in the project
    _work("w-smith", "Costs of offices", "2019", "John Smith"),
    _work("w-smith-b", "Costs of homes", "2019", "Jane Smith"),  # two Smiths, 2019: the person chooses
]


def _project(ws, folder: Path, ai_access: str = "cloud"):
    from enlens_claims import bibliography as b
    from enlens_claims import ingest

    folder.mkdir(parents=True, exist_ok=True)
    for name, text in SOURCES.items():
        (folder / name).write_text(text, encoding="utf-8")
    ingest.ingest(ws, [folder], ai_access=ai_access)
    b.save(ws, WORKS, {"kind": "file", "name": "my.bib", "format": "bibtex"})
    b.match(ws)
    b.confirm_all(ws)
    docs = {Path(r["path"]).name: r["doc_id"] for r in ws.query("SELECT doc_id, path FROM documents")}
    return docs


@pytest.fixture
def project(tmp_path, monkeypatch):
    from enlens_claims import home

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Drafts")
    return ws, _project(ws, tmp_path / "sources")


def _by_raw(v: dict) -> dict:
    out = {}
    for r in v["refs"]:
        out.setdefault(r["raw"], r)
    return out


def test_a_draft_and_the_state_of_each_citation(project):
    from enlens_claims import citations

    ws, docs = project
    tid = citations.add_text(ws, DRAFT, title="Chapter 2")
    v = citations.view(ws, tid)
    refs = _by_raw(v)
    assert v["text"]["title"] == "Chapter 2" and v["text"]["source"] == "paste" and v["text"]["level"] == "cloud"
    assert refs["Verhoeven & Okafor, 2025"]["state"] == "ready"
    assert refs["Verhoeven & Okafor, 2025"]["documents"] == [{"doc_id": docs["panel.txt"],
                                                             "title": refs["Verhoeven & Okafor, 2025"]["documents"][0]["title"]}]
    assert refs["Rivermouth Mobility Institute, 2024"]["state"] == "ready"
    assert refs["Lindqvist et al. (2025)"]["state"] == "ready"
    assert refs["Mueller (2018)"]["state"] == "no_document"  # in the bibliography, no document in the project
    assert refs["Smith, 2019"]["state"] == "ambiguous" and len(refs["Smith, 2019"]["candidates"]) == 2
    assert refs["Nowhere & Nobody, 2011"]["state"] == "no_work"
    assert refs["Van der Berg (2022)"]["state"] == "contrast"
    assert v["ready"] == 4 and v["citations"] == 8
    # a person says which Smith; a citation that is none can be left out, and put back
    citations.choose_work(ws, refs["Smith, 2019"]["ref_id"], "w-smith")
    citations.set_ignored(ws, refs["Nowhere & Nobody, 2011"]["ref_id"], True)
    refs = _by_raw(citations.view(ws, tid))
    assert refs["Smith, 2019"]["state"] == "no_document" and refs["Smith, 2019"]["how"] == "person"
    assert refs["Nowhere & Nobody, 2011"]["state"] == "ignored"
    citations.set_ignored(ws, refs["Nowhere & Nobody, 2011"]["ref_id"], False)
    assert _by_raw(citations.view(ws, tid))["Nowhere & Nobody, 2011"]["state"] == "no_work"
    # a draft with nothing to check is refused with a plain explanation
    with pytest.raises(citations.CitationError, match="No citations were found"):
        citations.add_text(ws, "A text without any citation in it at all, only plain sentences.")


def test_the_bibliography_changing_later(project, tmp_path):
    """A work added to the bibliography (or a document linked to a work) after the draft was added is used."""
    from enlens_claims import bibliography as b
    from enlens_claims import citations

    ws, _docs = project
    tid = citations.add_text(ws, DRAFT)
    assert _by_raw(citations.view(ws, tid))["Nowhere & Nobody, 2011"]["state"] == "no_work"
    b.save(ws, WORKS + [_work("w-nn", "Wages", "2011", "Al Nowhere", "Bo Nobody")],
           {"kind": "file", "name": "my.bib", "format": "bibtex"})
    assert _by_raw(citations.view(ws, tid))["Nowhere & Nobody, 2011"]["state"] == "no_document"


# ---------------------------------------------------------------------------------------------
# checking: one check per cited work, against its document only, with the claim's sentences as context
# ---------------------------------------------------------------------------------------------
class Reader(Cloud):
    """Claude, as far as ENLENS can tell: supports a claim when a passage has a sentence with all of its words,
    finds nothing otherwise. Records everything it is sent."""

    def complete(self, kind, system, user, model, payload=None):
        self.sent.append("\n".join([system, user, json.dumps(payload or {}, ensure_ascii=False)]))
        self.kinds.append(kind)
        if kind != "check":
            return json.dumps({"terms": []} if kind == "expand" else {})
        claim = set(re.findall(r"[a-z]{4,}", payload["claim"].lower()))
        ev = []
        for i, p in enumerate(payload["passages"], 1):
            for sent in re.split(r"(?<=[.!?])\s+", p["text"]):
                words = set(re.findall(r"[a-z]{4,}", sent.lower()))
                if claim and claim <= words:
                    ev.append({"passage": i, "verdict": "supports", "confidence": 0.9, "quote": sent.strip()})
                    break
        return json.dumps({"evidence": ev, "rationale": "stand-in"})


def test_checking_each_cited_work_against_its_document(project):
    from enlens_claims import citations, claimcheck

    ws, docs = project
    tid = citations.add_text(ws, DRAFT)
    items = citations.plan(ws, tid)
    assert len(items) == 4
    model = Reader()
    out = citations.check(ws, items, model, "claude-sonnet", k=8, per_doc=2)
    assert len(out["checked"]) == 4 and not out["errors"]
    v = citations.view(ws, tid)
    refs = _by_raw(v)
    hyb = refs["Verhoeven & Okafor, 2025"]
    assert hyb["state"] == "checked" and hyb["verdict"] == "accurate" and hyb["verdict_text"] == "Source accurate"
    assert "Hybrid workers commute" in hyb["quote"]["quote"] and hyb["quote"]["doc_id"] == docs["panel.txt"]
    # the source says something else ("a tenth", not "a third"): a notice
    assert refs["Rivermouth Mobility Institute, 2024"]["verdict"] == "not_found"
    prod = [r for r in v["refs"] if r["claim"] == "Productivity doubles."][0]
    assert prod["verdict"] == "not_found" and prod["verdict_text"] == "Not found in the source"
    assert refs["Lindqvist et al. (2025)"]["verdict"] == "accurate"
    assert v["notices"] == 2 and v["accurate"] == 2
    # each check read only the cited work's document, and was told the claim's sentences (not as evidence)
    for r in v["refs"]:
        if r["hyp_id"]:
            res = claimcheck.hypothesis_result(ws, r["hyp_id"])
            assert {p["doc_id"] for part in res["parts"] for p in part["passages"]} == {d["doc_id"] for d in r["documents"]}
            assert res["origin"] == "citation" and res["origin_id"] == r["ref_id"]
    prompts = [s for s, k in zip(model.sent, model.kinds) if k == "check"]
    hyb_prompt = [s for s in prompts if "CLAIM:\nHybrid workers commute fewer hours a week." in s][0]
    assert "THE CLAIM IN ITS TEXT" in hyb_prompt and "never grade or quote it" in hyb_prompt
    assert "Working from home spread quickly after 2020." in hyb_prompt  # the sentence before
    assert "(Verhoeven &amp; Okafor, 2025)" in hyb_prompt or "(Verhoeven & Okafor, 2025)" in hyb_prompt
    assert "Mobility" not in hyb_prompt.split("CLAIM IN ITS TEXT")[1].split("P1 |")[1]  # the other documents unread
    # checks of citations are on the Citations page, not among the hypotheses' results
    assert claimcheck.history(ws) == []
    assert len(claimcheck.history(ws, citations=True)) == 4
    # nothing is checked twice; a work chosen again replaces its check
    assert citations.plan(ws, tid) == []
    citations.choose_work(ws, hyb["ref_id"], "w-lindq")
    assert _by_raw(citations.view(ws, tid))["Verhoeven & Okafor, 2025"]["state"] == "ready"
    assert ws.scalar("SELECT COUNT(*) FROM hypotheses WHERE origin_id=?", (hyb["ref_id"],)) == 0


def test_a_persons_word_on_an_excerpt_changes_the_answer(project):
    from enlens_claims import citations, claimcheck

    ws, _docs = project
    tid = citations.add_text(ws, DRAFT)
    citations.check(ws, citations.plan(ws, tid), Reader(), "claude-sonnet", k=8, per_doc=2)
    hyb = _by_raw(citations.view(ws, tid))["Verhoeven & Okafor, 2025"]
    res = claimcheck.hypothesis_result(ws, hyb["hyp_id"])
    p = [x for x in res["parts"][0]["passages"] if x.get("verdict") == "supports"][0]
    claimcheck.set_judgement(ws, res["parts"][0]["claim_id"], p["passage_id"], "partially_supports")
    hyb = _by_raw(citations.view(ws, tid))["Verhoeven & Okafor, 2025"]
    assert hyb["verdict"] == "partly" and hyb["corrected"]


def test_removing_a_text_removes_its_checks(project):
    from enlens_claims import citations

    ws, _docs = project
    tid = citations.add_text(ws, DRAFT)
    citations.check(ws, citations.plan(ws, tid), Reader(), "claude-sonnet", k=8, per_doc=2)
    assert ws.scalar("SELECT COUNT(*) FROM hypotheses WHERE origin='citation'") == 4
    citations.remove_text(ws, tid)
    for t in ("cite_texts", "citations", "cite_refs"):
        assert ws.scalar(f"SELECT COUNT(*) FROM {t}") == 0
    assert ws.scalar("SELECT COUNT(*) FROM hypotheses") == 0
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='check'") == 0


# ---------------------------------------------------------------------------------------------
# privacy: the draft's own AI setting, a document's, local-only, the connector
# ---------------------------------------------------------------------------------------------
SECRET = "Zqxdraftmark"
PRIVATE_DRAFT = (f"Our unpublished finding {SECRET} is new. Hybrid workers commute fewer hours a week "
                 f"(Verhoeven & Okafor, 2025). Loneliness rises among young employees (Lindqvist et al., 2025).")


def test_a_draft_only_a_local_ai_may_read(project, monkeypatch):
    from enlens_claims import access, citations, claimcheck

    ws, _docs = project
    cloud, local = Reader(), Local()
    use_local_model(monkeypatch, local)
    tid = citations.add_text(ws, PRIVATE_DRAFT, ai_access="local")
    assert citations.view(ws, tid)["text"]["level"] == "local"
    out = citations.check(ws, citations.plan(ws, tid), cloud, "claude-sonnet", k=8, per_doc=2)
    assert len(out["checked"]) == 2
    assert not any(SECRET.lower() in s.lower() for s in cloud.sent)  # nothing of the draft reached Claude
    assert not any("Hybrid workers commute fewer" in s for s in cloud.sent)
    assert any(SECRET.lower() in s.lower() for s in local.sent)  # the local model read the excerpts
    for hid in out["checked"]:
        res = claimcheck.hypothesis_result(ws, hid)
        assert {p["read_by"] for p in res["parts"][0]["passages"]} == {"local"}
    # its checks are never shown to a Claude chat through the connector
    assert set(out["checked"]) <= access.hidden_hypotheses(ws)
    # every task about it is labelled as the draft is
    assert {r[0] for r in ws.query("SELECT access FROM tasks WHERE payload_json LIKE '%citing%'")} == {"local"}


def test_a_draft_no_ai_may_read_waits_for_the_person(project, monkeypatch):
    from enlens_claims import citations, claimcheck

    ws, _docs = project
    cloud, local = Reader(), Local()
    use_local_model(monkeypatch, local)
    tid = citations.add_text(ws, PRIVATE_DRAFT, ai_access="none")
    out = citations.check(ws, citations.plan(ws, tid), cloud, "claude-sonnet", k=8, per_doc=2)
    assert cloud.sent == [] and local.sent == []
    res = claimcheck.hypothesis_result(ws, out["checked"][0])
    assert res["waiting_for_you"] and {p["read_by"] for p in res["parts"][0]["passages"]} == {"you"}
    # the setting can be loosened later: the tasks not answered yet follow it
    citations.set_text(ws, tid, ai_access="cloud")
    assert citations.view(ws, tid)["text"]["level"] == "cloud"


def test_a_project_document_keeps_its_own_setting(project, monkeypatch):
    from enlens_claims import access, citations

    ws, docs = project
    cloud = Reader()
    use_local_model(monkeypatch, None)
    (Path(ws.root) / "draft.txt").write_text(PRIVATE_DRAFT, encoding="utf-8")
    from enlens_claims import ingest

    ingest.ingest(ws, [Path(ws.root) / "draft.txt"])
    did = ws.scalar("SELECT doc_id FROM documents WHERE path LIKE '%draft.txt'")
    access.set_documents(ws, [did], "local")
    tid = citations.add_text(ws, doc_id=did)
    v = citations.view(ws, tid)
    assert v["text"]["source"] == "document" and v["text"]["level"] == "local" and v["ready"] == 2
    with pytest.raises(citations.CitationError, match="keeps its own AI setting"):
        citations.set_text(ws, tid, ai_access="cloud")
    citations.check(ws, citations.plan(ws, tid), cloud, "claude-sonnet", k=8, per_doc=2)
    assert not any(SECRET.lower() in s.lower() for s in cloud.sent)
    # the document removed: its text and its citations go with it
    ws.remove_document(did)
    assert ws.scalar("SELECT COUNT(*) FROM cite_texts") == 0 and ws.scalar("SELECT COUNT(*) FROM cite_refs") == 0


def test_local_only_keeps_a_cloud_draft_here(project, monkeypatch):
    from enlens_claims import citations

    ws, _docs = project
    tid = citations.add_text(ws, PRIVATE_DRAFT, ai_access="cloud")
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    assert citations.view(ws, tid)["text"]["level"] == "local"


def test_by_queue_the_tasks_carry_the_context_and_respect_the_draft(project):
    from enlens_claims import citations, tasks

    ws, _docs = project
    tid = citations.add_text(ws, DRAFT)
    with tasks.queueing():
        hids, errors = citations.queue(ws, citations.plan(ws, tid), None, expand=False, k=8, per_doc=2)
    assert len(hids) == 4 and not errors
    rows = ws.query("SELECT payload_json, queued, access FROM tasks WHERE kind='check'")
    assert len(rows) == 4 and all(r["queued"] == 1 and r["access"] == "cloud" for r in rows)
    payloads = [json.loads(r["payload_json"]) for r in rows]
    assert all(p["claim_context"] and p["citing"]["text_id"] == tid and p["cited"] for p in payloads)
    # a draft marked local: nothing of it goes into the queue for Claude Code
    private = citations.add_text(ws, PRIVATE_DRAFT, ai_access="local")
    with tasks.queueing():
        hids, _ = citations.queue(ws, citations.plan(ws, private), None, expand=True, k=8, per_doc=2)
    mine = [r for r in ws.query("SELECT task_id, payload_json, queued, access FROM tasks")
            if json.loads(r["payload_json"]).get("citing", {}).get("text_id") == private]
    assert mine and all(r["queued"] == 0 and r["access"] != "cloud" for r in mine)
    assert not any(t.startswith("expand:") for t in (r["task_id"] for r in mine))  # no search words from Claude


# ---------------------------------------------------------------------------------------------
# through the app
# ---------------------------------------------------------------------------------------------
from test_app import Api, api, home  # noqa: E402,F401  (fixtures)


def _until(fn, seconds=20.0):
    import time

    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    return fn()


def test_citations_through_the_app(api, tmp_path):  # noqa: F811
    import fake_claude_code as fcc
    from enlens_claims import home as core

    ws = core.create_project("P")
    docs = _project(ws, tmp_path / "sources")
    st, r = api("GET", "/api/projects/P/citations")
    assert st == 200 and r["texts"] == [] and r["has_bibliography"] is True and r["ai_access"]["default"]
    # a pasted draft
    st, v = api("POST", "/api/projects/P/citations", {"text": DRAFT, "title": "Chapter 2", "ai_access": "cloud"})
    assert st == 200, v
    tid = v["text"]["text_id"]
    assert v["text"]["title"] == "Chapter 2" and v["ready"] == 4 and v["citations"] == 8
    assert {w["key"] for w in v["bibliography_works"]} >= {"w-panel", "w-smith"}
    # what a request gets wrong is said plainly
    st, r = api("POST", "/api/projects/P/citations", {"text": "No citation in this text, only plain words here."})
    assert st == 400 and "No citations were found" in r["error"]
    assert api("POST", "/api/projects/P/citations", {"text": DRAFT, "ai_access": "everyone"})[0] == 400
    assert api("POST", "/api/projects/P/citations", {"doc_id": "nope"})[0] == 404
    assert api("POST", "/api/projects/P/citations", {"upload": {"batch": "x", "name": "gone.txt"}})[0] == 400
    assert api("GET", "/api/projects/P/citations/nope")[0] == 404
    assert api("POST", "/api/projects/P/citations/nope/check", {})[0] == 404
    # a person's word: which Smith; not a citation, and back
    smith = [x for x in v["refs"] if x["raw"] == "Smith, 2019"][0]
    nn = [x for x in v["refs"] if x["raw"] == "Nowhere & Nobody, 2011"][0]
    st, v = api("PUT", f"/api/projects/P/citations/{tid}/refs/{smith['ref_id']}", {"item_key": "w-smith"})
    assert st == 200 and [x for x in v["refs"] if x["ref_id"] == smith["ref_id"]][0]["how"] == "person"
    assert api("PUT", f"/api/projects/P/citations/{tid}/refs/{smith['ref_id']}", {"item_key": "w-none"})[0] == 404
    assert api("PUT", f"/api/projects/P/citations/{tid}/refs/nope", {"ignored": True})[0] == 404
    st, v = api("PUT", f"/api/projects/P/citations/{tid}/refs/{nn['ref_id']}", {"ignored": True})
    assert [x for x in v["refs"] if x["ref_id"] == nn["ref_id"]][0]["state"] == "ignored"
    # the draft's AI setting, and a name
    st, v = api("PUT", f"/api/projects/P/citations/{tid}", {"ai_access": "local", "title": "Chapter 2, v2"})
    assert st == 200 and v["text"]["ai_access"] == "local" and v["text"]["title"] == "Chapter 2, v2"
    api("PUT", f"/api/projects/P/citations/{tid}", {"ai_access": "cloud"})
    # checking by queue (Claude Code is the AI of a new installation): the stand-in Claude Code reads them
    st, r = api("POST", f"/api/projects/P/citations/{tid}/check", {})
    assert st == 200, r
    jid = r["job"]["id"]
    assert r["job"]["kind"] == "citations" and r["job"]["scope"] == tid
    try:
        for _ in range(4):  # search words, then the excerpts
            _until(lambda: ws.scalar("SELECT COUNT(*) FROM tasks WHERE queued=1 AND status IN ('pending', 'retry')"), 10)
            fcc.FakeClaudeCode(fcc.DirectTools(), wrong_first=False).run("P")
            if api("GET", f"/api/jobs/{jid}")[1]["state"] not in ("queued", "running"):
                break
        done = api.wait(jid, timeout=30)
        assert done["state"] == "done", done
        assert len(done["result"]["checked"]) == 4 and done["result"]["text_id"] == tid
    finally:
        if api("GET", f"/api/jobs/{jid}")[1]["state"] in ("queued", "running"):
            api("POST", f"/api/jobs/{jid}/cancel")
            api.wait(jid)
    v = api("GET", f"/api/projects/P/citations/{tid}")[1]
    assert v["ready"] == 0 and v["accurate"] + v["notices"] == 4
    checked = [x for x in v["refs"] if x["state"] == "checked"]
    assert all(x["hyp_id"] and x["verdict_text"] for x in checked)
    # its checks open on the result page, with the sentence they stand for; they are not among the Results
    res = api("GET", f"/api/projects/P/hypotheses/{checked[0]['hyp_id']}")[1]
    assert res["origin"] == "citation" and res["options"]["citation"]["sentence"] == checked[0]["sentence"]
    assert api("GET", "/api/projects/P/hypotheses")[1]["hypotheses"] == []
    o = api("GET", "/api/projects/P/overview")[1]
    assert o["hypotheses"] == 0 and o["citations"] == {"texts": 1, "refs": 6, "checked": 4}  # two left out
    # nothing left to check: said plainly
    st, r = api("POST", f"/api/projects/P/citations/{tid}/check", {})
    assert st == 400 and "No citation is ready" in r["error"]
    # Excel
    st, body = api("GET", f"/api/projects/P/citations/{tid}/export.xlsx")
    assert st == 200 and body[:2] == b"PK"
    import io

    import openpyxl

    rows = list(openpyxl.load_workbook(io.BytesIO(body)).active.iter_rows(values_only=True))
    assert rows[0][:5] == ("#", "Page of your text", "Sentence", "Claim checked", "Citation") and len(rows) == 9
    # a file: sent to /uploads, read, and deleted again; it never becomes a document
    n_docs = ws.scalar("SELECT COUNT(*) FROM documents")
    st, up = api("POST", "/api/projects/P/uploads?batch=cite-t1&name=draft.txt", raw=PRIVATE_DRAFT.encode())
    assert st == 200
    st, v2 = api("POST", "/api/projects/P/citations", {"upload": {"batch": "cite-t1", "name": "draft.txt"},
                                                      "ai_access": "local"})
    assert st == 200, v2
    assert v2["text"]["source"] == "file" and v2["text"]["file_name"] == "draft.txt" and v2["text"]["level"] == "local"
    assert ws.scalar("SELECT COUNT(*) FROM documents") == n_docs and not (ws.root / "uploads" / "cite-t1").exists()
    # a document of the project
    st, v3 = api("POST", "/api/projects/P/citations", {"doc_id": docs["panel.txt"]})
    assert st == 400 and "No citations were found" in v3["error"]
    texts = api("GET", "/api/projects/P/citations")[1]["texts"]
    assert [t["text_id"] for t in texts] == [v2["text"]["text_id"], tid]
    # removing a text removes its checks
    assert api("DELETE", f"/api/projects/P/citations/{tid}", {})[0] == 200
    assert ws.scalar("SELECT COUNT(*) FROM hypotheses WHERE origin='citation'") == 0
    assert api("DELETE", f"/api/projects/P/citations/{tid}", {})[0] == 404


def test_checking_in_the_app_with_a_model_that_answers_at_once(api, tmp_path, monkeypatch):  # noqa: F811
    """Not by queue: the app reads each citation with the model of Settings, one after the other."""
    from enlens_claims import home as core
    from enlens_claims.gui import server

    ws = core.create_project("P")
    _project(ws, tmp_path / "sources")
    reader = Reader()
    monkeypatch.setattr(server.App, "queue_mode", lambda self: False)
    monkeypatch.setattr(server.App, "backend", lambda self, kinds=None, k=None: (reader, "claude-sonnet"))
    tid = api("POST", "/api/projects/P/citations", {"text": DRAFT})[1]["text"]["text_id"]
    jid = api("POST", f"/api/projects/P/citations/{tid}/check", {})[1]["job"]["id"]
    done = api.wait(jid, timeout=60)
    assert done["state"] == "done", done
    assert len(done["result"]["checked"]) == 4 and not done["result"]["errors"]
    v = api("GET", f"/api/projects/P/citations/{tid}")[1]
    assert v["accurate"] == 2 and v["notices"] == 2
    # one again, on request
    one = [x for x in v["refs"] if x["verdict"] == "not_found"][0]
    jid = api("POST", f"/api/projects/P/citations/{tid}/check", {"ref_ids": [one["ref_id"]], "again": True})[1]["job"]["id"]
    assert api.wait(jid)["result"]["checked"]
    assert ws.scalar("SELECT COUNT(*) FROM hypotheses WHERE origin_id=?", (one["ref_id"],)) == 1
    # a citation's own Excel file (from its result page) has its summary; the Results' Excel file leaves it out
    import io

    import openpyxl

    def summary_rows(path):
        st, body = api("GET", path)
        assert st == 200
        return list(openpyxl.load_workbook(io.BytesIO(body))["Summary"].iter_rows(values_only=True))[1:]

    hid = [x for x in v["refs"] if x["verdict"] == "accurate"][0]["hyp_id"]
    assert len(summary_rows(f"/api/projects/P/hypotheses/{hid}/export.xlsx")) == 1
    assert summary_rows("/api/projects/P/export.xlsx") == []


# ---------------------------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------------------------
def test_the_page_files():
    from helpers import api_docs

    features = (STATIC / "features.js").read_text(encoding="utf-8")
    assert 'citations: {  // 0.13.7' in features and 'href: "#/citations", ai: "uses"' in features
    assert features.index("citations: {") < features.index("history: {")  # before Results, after Check several
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'import { renderCitations } from "./views/citations.js";' in app and '"citations", renderCitations]' in app
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('data-route="batch"') < html.index('data-route="citations"') < html.index('data-route="history"')
    registry = (STATIC / "registry.js").read_text(encoding="utf-8")
    assert "citation: {" in registry and 'citations: { icon: "quote"' in registry
    view = (STATIC / "views" / "citations.js").read_text(encoding="utf-8")
    for s in ('"Find the citations"', "Who may read your text with AI?", "Source accurate", "To look at",
              "Cannot be checked yet", "Not a citation", "See the excerpts and judge them", "/uploads?batch="):
        assert s in view, s
    result = (STATIC / "views" / "result.js").read_text(encoding="utf-8")
    assert "function citedIn(c)" in result and 'r.origin === "citation"' in result
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    block = css[css.index("/* 0.13.7: Check citations"):]
    assert ".cite-card" in block and ".result-cited" in block
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(", block)  # colour tokens only: light and dark both work
    assert "v0137.css" not in html  # no stylesheet of its own: new rules go into app.css
    docs = api_docs()
    for route in ("GET /api/projects/<p>/citations", "POST /api/projects/<p>/citations",
                  "GET /api/projects/<p>/citations/<text>", "PUT /api/projects/<p>/citations/<text>",
                  "DELETE /api/projects/<p>/citations/<text>", "POST /api/projects/<p>/citations/<text>/check",
                  "PUT /api/projects/<p>/citations/<text>/refs/<ref>",
                  "GET /api/projects/<p>/citations/<text>/export.xlsx"):
        assert route in docs, route


def test_the_registry_links_back_in_node(tmp_path):
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("needs Node")
    f = tmp_path / "t.mjs"
    f.write_text(f"""
const r = await import({json.dumps((STATIC / "registry.js").as_uri())});
console.log(JSON.stringify([r.originLink({{ origin: "citation", origin_id: "tabc123-4-1" }}),
  r.jobRow({{ kind: "citations", id: "j1", scope: "tabc123", title: "3 citations" }})]));
""")
    out = json.loads(subprocess.run([node, str(f)], capture_output=True, text=True, timeout=60).stdout)
    assert out[0] == {"eyebrow": "Back to the citations", "meta": "a citation in your text",
                      "href": "#/citations/tabc123?ref=tabc123-4-1"}
    assert out[1]["href"] == "#/citations/tabc123?job=j1" and out[1]["text"] == "Checking citations (3 citations)"
