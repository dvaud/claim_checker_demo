"""0.18.1: the new tables that are this copy's own never reach a colleague.

- `ai_cache` (H4): answers this copy keeps so as not to ask the AI again. Raw AI answers with their quotes, also of
  documents marked Only a local AI or No AI, which a colleague's copy may not be allowed to hold.
- `concept_link_sentences` (D2): the sentences of links found in the text, quoted from this copy's readings; each copy
  makes them again with its own glossary.

Neither travels in a zip for a colleague (`scope="shared"`) nor through the shared folder (`ProjectRows.tables`). The
whole-project zip, for moving your own project, keeps everything.
"""
from __future__ import annotations

import sqlite3
import zipfile

from enlens_claims import bundle, sharing
from enlens_claims.sync.common import LOCAL_ONLY

OWN = ("ai_cache", "concept_link_sentences")


def _fill(ws) -> None:
    pid, doc = ws.query("SELECT passage_id, doc_id FROM passages LIMIT 1")[0]
    with ws.connect() as cx:
        cx.execute("INSERT OR REPLACE INTO ai_cache(key, kind, prompt_version, model, raw_json, at) VALUES "
                   "('k1', 'label', 'v1', 'qwen3:8b', '{\"quote\": \"words of a local-only document\"}', '2026-11-13')")
        cx.execute("INSERT OR REPLACE INTO concept_link_sentences(a, b, passage_id, doc_id, page, start, end, quote) VALUES "
                   "('water', 'electrolysis', ?, ?, 1, 0, 10, 'water such as electrolysis')", (pid, doc))


def _count(db_bytes: bytes, tmp_path, table: str) -> int:
    path = tmp_path / "got.sqlite"
    path.write_bytes(db_bytes)
    cx = sqlite3.connect(path)
    try:
        return cx.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        cx.close()


def test_a_zip_for_a_colleague_leaves_them_out_and_a_whole_project_zip_keeps_them(loaded, tmp_path):
    _fill(loaded)
    shared, whole = tmp_path / "shared.zip", tmp_path / "whole.zip"
    bundle.export_project(loaded, shared, scope="shared")
    bundle.export_project(loaded, whole, scope="all")
    for table in OWN:
        with zipfile.ZipFile(shared) as zf:
            assert _count(zf.read("enlens.sqlite"), tmp_path, table) == 0, table
        with zipfile.ZipFile(whole) as zf:
            assert _count(zf.read("enlens.sqlite"), tmp_path, table) == 1, table


def test_the_shared_folder_never_writes_them(loaded):
    _fill(loaded)
    assert set(OWN) <= LOCAL_ONLY and set(OWN) <= set(sharing._LOCAL_TABLES)
    with loaded.connect() as cx:
        names = {t for t, _where, _cols in sharing.ProjectRows(cx, loaded.root).tables()}
    assert not names & set(OWN)
    assert "retractions" in names  # what Crossref says of a DOI is public, and saves a colleague the lookup


def test_remove_everything_and_removing_a_document_take_them_too(loaded):
    _fill(loaded)
    doc = loaded.query("SELECT doc_id FROM concept_link_sentences")[0]["doc_id"]
    loaded.remove_document(doc)
    assert not loaded.scalar("SELECT COUNT(*) FROM concept_link_sentences WHERE doc_id=?", (doc,))
    _fill(loaded)
    loaded.reset_corpus()
    for table in OWN:
        assert not loaded.scalar(f"SELECT COUNT(*) FROM {table}"), table


def test_a_colleagues_project_comes_in_without_them_and_your_own_keeps_them(loaded):
    """What `bundle.import_project` and linking a colleague's folder do with a project another person made: their
    kept answers would answer here as this copy's own."""
    from enlens_claims import home

    _fill(loaded)
    bundle._forget_folder(loaded, home.load_settings().get("person_id") or "me")  # a project you moved yourself
    me = home.load_settings().get("person_id")
    if me:
        assert all(loaded.scalar(f"SELECT COUNT(*) FROM {t}") == 1 for t in OWN)
    bundle._forget_folder(loaded, "a-colleague")
    for table in OWN:
        assert not loaded.scalar(f"SELECT COUNT(*) FROM {table}"), table
