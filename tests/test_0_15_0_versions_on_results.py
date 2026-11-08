"""0.15 (roadmap J4.2 and the reader's number): results you can trust across versions.

- each document records the reader that read its text (ingest.READER) and the ENLENS version; a document read before
  0.15 gets reader 1, the only one there was (also one that comes in from a colleague's older ENLENS);
- every AI answer, run, codebook label, theme run and check records the ENLENS version that made it;
- labels, runs and theme runs are written by column name, so a column added later (here, or by an add-on) does not
  break the writes;
- the version is never part of a sync fingerprint: a colleague on an older ENLENS (no such column) sees no clash;
- "How these results were made" names the version behind each answer and the reader behind the documents;
- the Overview says which results an earlier version made, and nothing when every result is from this one.
"""
from __future__ import annotations

from pathlib import Path

from test_app import api, home  # noqa: F401  (fixtures)

from enlens_claims import __version__, claimcheck, ingest, profile, runs, sources, sync, themes
from enlens_claims.store import Workspace

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
DEMO = Path(__file__).resolve().parent.parent / "tools" / "demo_corpus"


def test_a_document_records_its_reader_and_version(loaded):
    rows = loaded.query("SELECT reader, app_version FROM documents")
    assert rows and all(r["reader"] == ingest.READER and r["app_version"] == __version__ for r in rows)
    one = loaded.query("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")[0]["doc_id"]
    docs = {d["doc_id"]: d for d in sources.document_overview(loaded)}
    assert docs[one]["reader"] == ingest.READER and docs[one]["app_version"] == __version__


def test_a_document_read_before_0_15_was_read_by_reader_1(loaded):
    with loaded.connect() as cx:
        cx.execute("UPDATE documents SET reader=NULL, app_version=NULL")
    ws = Workspace.open(loaded.root)  # opening a project fills in what an older version could not say
    assert {r[0] for r in ws.query("SELECT reader FROM documents")} == {1}
    assert {r[0] for r in ws.query("SELECT app_version FROM documents")} == {None}


def test_answers_runs_labels_theme_runs_and_checks_record_the_version(loaded):
    ingest.ingest(loaded, [DEMO])  # enough passages for themes
    import fake_servers

    from enlens_claims.llm import OllamaBackend

    srv, url = fake_servers.start("ollama")
    try:
        be, model = OllamaBackend(base_url=url, seed=42), fake_servers.FAKE_MODEL
        profile.keyword_pass(loaded, "sdg")
        profile.run_labels(loaded, "sdg", be, model, limit=2)
    finally:
        srv.shutdown()
    pid = loaded.query("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")[0]["passage_id"]
    profile.add_label(loaded, "sdg", pid, "6.4")
    run = themes.run(loaded, k=3, seed=0, mode="words")
    hid = claimcheck.create_hypothesis(loaded, "Electrolysis needs water")
    for sql in ("SELECT app_version FROM results", "SELECT app_version FROM runs",
                "SELECT app_version FROM labels WHERE source='model'", "SELECT app_version FROM labels WHERE source='person'",
                "SELECT app_version FROM labels WHERE source IN ('keywords','meaning','both')"):
        got = {r[0] for r in loaded.query(sql)}
        assert got == {__version__}, (sql, got)
    assert loaded.scalar("SELECT app_version FROM theme_runs WHERE run_id=?", (run,)) == __version__
    assert loaded.scalar("SELECT app_version FROM hypotheses WHERE hyp_id=?", (hid,)) == __version__


def test_labels_and_runs_are_written_by_column_name(loaded):
    """A column added after these were written (an add-on's, or the next version's) does not break them."""
    ingest.ingest(loaded, [DEMO])  # enough passages for themes
    with loaded.connect() as cx:
        for t in ("labels", "runs", "theme_runs"):
            cx.execute(f"ALTER TABLE {t} ADD COLUMN later_col TEXT")
    pid = loaded.query("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")[0]["passage_id"]
    profile.add_label(loaded, "sdg", pid, "6.4")
    profile.keyword_pass(loaded, "sdg")
    themes.run(loaded, k=3, seed=0, mode="words")

    class NoBackend:
        router = None

    runs.start(loaded, "label", "sdg", NoBackend(), "some-model", 0)
    assert loaded.scalar("SELECT COUNT(*) FROM runs WHERE app_version=?", (__version__,)) == 1


def test_the_version_is_not_part_of_a_sync_fingerprint(loaded):
    hid = claimcheck.create_hypothesis(loaded, "Electrolysis needs water")
    cx = loaded._conn()
    fps = sync._fingerprints(cx)
    unit = sync._check_unit(cx, hid)
    canon = sync._canon(cx)
    mine = fps(unit, canon)
    unit["hypotheses"] = [{k: v for k, v in r.items() if k != "app_version"} for r in unit["hypotheses"]]
    assert fps(unit, canon) == mine  # the same check from a colleague's older ENLENS, which has no such column
    unit["hypotheses"] = [{**r, "app_version": "9.9.9"} for r in unit["hypotheses"]]
    assert fps(unit, canon) == mine


def test_how_these_results_were_made_names_the_version_and_the_reader(loaded):
    import fake_servers

    from enlens_claims.llm import OllamaBackend

    srv, url = fake_servers.start("ollama")
    try:
        profile.keyword_pass(loaded, "sdg")
        profile.run_labels(loaded, "sdg", OllamaBackend(base_url=url, seed=42), fake_servers.FAKE_MODEL, limit=1)
    finally:
        srv.shutdown()
    with loaded.connect() as cx:  # one answer made before versions were recorded
        cx.execute("UPDATE results SET app_version=NULL WHERE rowid=(SELECT MIN(rowid) FROM results)")
    rows = runs.provenance_table(loaded, kinds=("label",))
    versions = {r.get("ENLENS version") for r in rows if "ENLENS version" in r}
    assert versions == {__version__, f"before {runs.RECORDED_SINCE}"} or versions == {f"before {runs.RECORDED_SINCE}"}
    n_docs = loaded.scalar("SELECT COUNT(*) FROM documents")
    assert rows[-1]["Step"].startswith(f"Reading this project's documents: {n_docs} documents by reader {ingest.READER} (ENLENS {__version__})")
    none = runs.provenance_table(loaded, task_ids=[])
    assert none[0]["Step"].startswith("No AI model") and none[-1]["Step"].startswith("Reading this project's documents")


def test_made_with_says_what_an_earlier_version_made(loaded):
    claimcheck.create_hypothesis(loaded, "Electrolysis needs water")
    m = runs.made_with(loaded)
    assert m["version"] == __version__ and m["reader"] == ingest.READER and not m["older"]
    assert [r["what"] for r in m["results"]] == ["checks"]
    with loaded.connect() as cx:  # a check from before 0.15, and one from an earlier version that said its number
        cx.execute("INSERT INTO hypotheses(hyp_id, text, created_at) VALUES ('h-old', 'Old', '2026-11-01')")
        cx.execute("INSERT INTO hypotheses(hyp_id, text, created_at, app_version) VALUES ('h-older', 'Older', '2026-11-02', "
                   "'0.0.1')")
    m = runs.made_with(loaded)
    older = sorted((r["label"], r["n"]) for r in m["results"] if r["older"])
    assert m["older"] and older == [("0.0.1", 1), (f"before {runs.RECORDED_SINCE}", 1)]
    assert not any(d["older"] for d in m["documents"])
    with loaded.connect() as cx:  # a document an earlier reader read (once there is a second reader)
        cx.execute("UPDATE documents SET reader=0 WHERE rowid=(SELECT MIN(rowid) FROM documents)")
    assert sum(d["n"] for d in runs.made_with(loaded)["documents"] if d["older"]) == 1


def test_the_overview_says_which_results_an_earlier_version_made(api):
    st, _ = api("POST", "/api/projects", {"name": "v"})
    assert st in (200, 201)
    st, o = api("GET", "/api/projects/v/overview")
    assert st == 200 and o["made_with"]["version"] == __version__ and o["made_with"]["older"] is False
    js = (STATIC / "views" / "overview.js").read_text()
    assert "madeWith(o.made_with)" in js and "Made with an earlier version of ENLENS" in js
    assert ".ov-made-with" in (STATIC / "v09.css").read_text()
