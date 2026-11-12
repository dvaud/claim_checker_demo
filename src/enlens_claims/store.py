"""Workspace on disk: a folder with config.json and one SQLite database."""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import threading
import weakref
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# 0.17.2: the glossary's places. A passage id names its document (`passage_range`), so a document's places are a range
# of passage ids and `doc_id` stays empty. It is kept, with the table's name and the order of its columns, for an
# ENLENS before 0.17.2 that opens this file: it makes its indexes on `doc_id` (store.INDEXES of then) and writes its
# glossary here, and it never sends this table to a colleague nor reads it as the project's rows (its sync.LOCAL_ONLY).
PLACES_TABLE = ("CREATE TABLE IF NOT EXISTS term_mentions(term_id TEXT NOT NULL, passage_id TEXT NOT NULL, doc_id TEXT, "
                "start INT NOT NULL, end INT NOT NULL, PRIMARY KEY(term_id, passage_id, start, end)) WITHOUT ROWID;")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS hypotheses(
  hyp_id TEXT PRIMARY KEY, text TEXT, framework TEXT, code TEXT, options_json TEXT, decomposed INT DEFAULT 0,
  rationale TEXT, model TEXT, created_at TEXT, batch_id TEXT, note TEXT, parts_json TEXT);
CREATE TABLE IF NOT EXISTS user_claims(
  claim_id TEXT PRIMARY KEY, text TEXT, target TEXT, terms_json TEXT, rationale TEXT, options_json TEXT,
  model TEXT, created_at TEXT, hyp_id TEXT, part INT DEFAULT 0, role TEXT, framework TEXT);

CREATE TABLE IF NOT EXISTS documents(
  doc_id TEXT PRIMARY KEY, path TEXT, sha1 TEXT UNIQUE, title TEXT, doi TEXT, kind TEXT,
  n_pages INT, n_chars INT, text TEXT, added_at TEXT, declared_ref TEXT);
CREATE TABLE IF NOT EXISTS pages(doc_id TEXT, page INT, start INT, end INT, PRIMARY KEY(doc_id, page));
CREATE TABLE IF NOT EXISTS paragraphs(doc_id TEXT, n INT, start INT, PRIMARY KEY(doc_id, n));
CREATE TABLE IF NOT EXISTS headings(doc_id TEXT, start INT, end INT, text TEXT, PRIMARY KEY(doc_id, start));
CREATE TABLE IF NOT EXISTS passages(
  passage_id TEXT PRIMARY KEY, doc_id TEXT, seq INT, page INT, start INT, end INT, text TEXT,
  section TEXT, screen_score REAL DEFAULT 0, screened INT DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_passages_doc ON passages(doc_id, seq);
CREATE TABLE IF NOT EXISTS embeddings(model TEXT, passage_id TEXT, vec BLOB, PRIMARY KEY(model, passage_id));

CREATE TABLE IF NOT EXISTS vca_targets(
  target TEXT PRIMARY KEY, goal INT, description TEXT,
  production TEXT, transportation TEXT, end_use TEXT,
  horizon TEXT, interdependence TEXT, justification TEXT, references_text TEXT);
CREATE TABLE IF NOT EXISTS vca_refs(ref_key TEXT PRIMARY KEY, reference TEXT, doi TEXT, kind TEXT, targets_json TEXT,
  alias_of TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS doc_refs(doc_id TEXT, ref_key TEXT, method TEXT, score REAL, PRIMARY KEY(doc_id, ref_key));

CREATE TABLE IF NOT EXISTS tasks(
  task_id TEXT PRIMARY KEY, kind TEXT, model TEXT, prompt_version TEXT, payload_json TEXT,
  status TEXT, attempts INT DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS results(
  task_id TEXT, attempt INT, kind TEXT, model TEXT, prompt_version TEXT, raw_json TEXT,
  valid INT, errors_json TEXT, received_at TEXT, PRIMARY KEY(task_id, attempt));

CREATE TABLE IF NOT EXISTS claims(
  claim_id TEXT PRIMARY KEY, task_id TEXT, doc_id TEXT, passage_id TEXT, claim TEXT, activity TEXT,
  segment TEXT, place_text TEXT, countries_json TEXT, scale TEXT, side TEXT, horizon TEXT,
  condition TEXT, policy_lever TEXT, confidence REAL, model TEXT, prompt_version TEXT, status TEXT,
  status_reason TEXT);
CREATE TABLE IF NOT EXISTS claim_targets(
  claim_id TEXT, target TEXT, direction TEXT, influence TEXT, PRIMARY KEY(claim_id, target));
CREATE TABLE IF NOT EXISTS evidence(
  claim_id TEXT, field TEXT, quote TEXT, doc_id TEXT, start INT, end INT, page INT, match TEXT);
CREATE TABLE IF NOT EXISTS interactions(
  inter_id TEXT PRIMARY KEY, claim_id TEXT, doc_id TEXT, from_target TEXT, to_target TEXT,
  score INT, quote TEXT, start INT, end INT, page INT, kind TEXT);

CREATE TABLE IF NOT EXISTS vca_claims(
  vca_claim_id TEXT PRIMARY KEY, target TEXT, seq INT, text TEXT, quote TEXT, segment TEXT,
  direction TEXT, place TEXT, horizon TEXT, condition TEXT, model TEXT, prompt_version TEXT);
CREATE TABLE IF NOT EXISTS verifications(
  ver_id TEXT PRIMARY KEY, subject_kind TEXT, subject_id TEXT, passage_id TEXT, doc_id TEXT,
  verdict TEXT, confidence REAL, quote TEXT, start INT, end INT, page INT, model TEXT, prompt_version TEXT);

CREATE TABLE IF NOT EXISTS second_opinions(
  subject_id TEXT, passage_id TEXT, model TEXT, verdict TEXT, confidence REAL, quote TEXT, start INT, end INT,
  scope_note TEXT, at TEXT, PRIMARY KEY(subject_id, passage_id, model));

CREATE TABLE IF NOT EXISTS reviews(
  review_id INTEGER PRIMARY KEY AUTOINCREMENT, item_kind TEXT, item_id TEXT, field TEXT,
  proposed TEXT, decision TEXT, corrected TEXT, reviewer TEXT, note TEXT, decided_at TEXT);

-- 0.7: codebook profiles (F2). One row per passage, code and source: the keyword-and-meaning pass ('keywords',
-- 'meaning' or 'both'), the model pass ('model') or a person ('person'). A person's verdict on a row is a review
-- (item_kind 'label').
CREATE TABLE IF NOT EXISTS labels(
  label_id TEXT PRIMARY KEY, passage_id TEXT, doc_id TEXT, framework TEXT, code TEXT, relevance TEXT, direction TEXT,
  confidence REAL, quote TEXT, start INT, end INT, page INT, source TEXT, model TEXT, prompt_version TEXT,
  reason TEXT, matched_json TEXT, score REAL, similarity REAL, task_id TEXT, created_at TEXT);
-- the vector of each code's text, per embedding model and framework (never mixed with passage vectors)
CREATE TABLE IF NOT EXISTS code_vectors(model TEXT, framework TEXT, code TEXT, text_hash TEXT, vec BLOB,
  PRIMARY KEY(model, framework, code));

-- 0.7: the term index (F3, F6): a glossary of the corpus, rebuilt when the documents change
CREATE TABLE IF NOT EXISTS terms(term_id TEXT PRIMARY KEY, label TEXT, stems TEXT, n_words INT, df INT, tf INT,
  passages INT, cvalue REAL);
-- every place a term occurs: its passage and the document offsets of its words. 0.17.2: WITHOUT ROWID (the rows are
-- their own key, kept once) with one index in passage order, where the table had a rowid, the document of each place
-- and three indexes (70 % of a project's file); see PLACES_TABLE.
{PLACES_TABLE}
-- concepts: terms joined by 'same' links (a person, the model, the abbreviation rule); links may name terms that
-- are not in the index any more (they come back when the term does)
CREATE TABLE IF NOT EXISTS concepts(concept_id TEXT PRIMARY KEY, label TEXT);
CREATE TABLE IF NOT EXISTS concept_terms(concept_id TEXT, term_id TEXT, source TEXT, PRIMARY KEY(concept_id, term_id));
CREATE TABLE IF NOT EXISTS concept_links(a TEXT, b TEXT, relation TEXT, source TEXT, confidence REAL, quote_a TEXT,
  quote_b TEXT, model TEXT, created_at TEXT, PRIMARY KEY(a, b, source));

-- 0.7: themes (F4)
CREATE TABLE IF NOT EXISTS theme_runs(run_id TEXT PRIMARY KEY, mode TEXT, k INT, seed INT, embed_model TEXT,
  chat_model TEXT, created_at TEXT, passages INT, run_key TEXT, settings_json TEXT, corpus_version INT);
CREATE TABLE IF NOT EXISTS themes(run_id TEXT, theme_id INT, name TEXT, description TEXT, terms_json TEXT, size INT,
  reps_json TEXT, name_source TEXT, quotes_json TEXT, model TEXT, PRIMARY KEY(run_id, theme_id));
CREATE TABLE IF NOT EXISTS theme_members(run_id TEXT, theme_id INT, passage_id TEXT, similarity REAL,
  PRIMARY KEY(run_id, passage_id));

-- 0.7: references within a document (F5): chains of mentions, each mention quote-checked and placed by offset
-- one row per mention as one window of passages reported it (`window`: task id # chain); chains are joined across
-- overlapping windows and numbered per document (`chain_id`)
CREATE TABLE IF NOT EXISTS mentions(doc_id TEXT, chain_id INT, start INT, end INT, text TEXT, is_named INT,
  source TEXT, model TEXT, passage_id TEXT, window TEXT, PRIMARY KEY(doc_id, start, end, window));

-- 0.7: what produced a run of model judgements (model, digest, prompt, seed, settings), to warn when it changes
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, kind TEXT, scope TEXT, model TEXT, digest TEXT,
  prompt_version TEXT, seed INT, settings_json TEXT, started_at TEXT, finished_at TEXT, tasks INT);

-- 0.8: batches of queued tasks handed out to a helper (Claude Code through the connector): who took them and when.
-- A claim not answered within queue.CLAIM_MINUTES lapses and its tasks return to the queue.
CREATE TABLE IF NOT EXISTS task_claims(claim_id TEXT PRIMARY KEY, kind TEXT, model TEXT, helper TEXT, route TEXT,
  taken_by TEXT, task_ids_json TEXT, claimed_at TEXT, expires_at TEXT, finished_at TEXT, stored INT DEFAULT 0,
  problems INT DEFAULT 0);

-- 0.11: every passage sent to a cloud model (Claude Code, the Claude API, a Claude chat through the connector), at the
-- moment it left: one row per passage per sending (and per passage shown before it as context)
CREATE TABLE IF NOT EXISTS ai_sent(passage_id TEXT, doc_id TEXT, route TEXT, task_id TEXT, sent_at TEXT, feature TEXT);
CREATE INDEX IF NOT EXISTS ix_ai_sent_doc ON ai_sent(doc_id, passage_id);

-- 0.13: the project's bibliography (a Zotero library or collection, or an exported file; see bibliography.py): its
-- works, and which document each work is. status: 'auto' (the same file or DOI), 'probable' (the title, an author or
-- the year on the first pages; a person confirms it), 'confirmed' or 'rejected' (a person's word, kept across matches)
CREATE TABLE IF NOT EXISTS bib_items(item_key TEXT PRIMARY KEY, item_type TEXT, title TEXT, creators_json TEXT,
  year TEXT, doi TEXT, url TEXT, container TEXT, isbn TEXT, link TEXT, files_json TEXT, seq INT);
CREATE TABLE IF NOT EXISTS bib_links(item_key TEXT, doc_id TEXT, status TEXT, method TEXT, score REAL,
  evidence_json TEXT, decided_at TEXT, PRIMARY KEY(item_key, doc_id));
CREATE INDEX IF NOT EXISTS ix_bib_links_doc ON bib_links(doc_id);

-- 0.14: shared projects (people.py, sync.py). The people whose work is in the project; each person's own judgement of
-- an excerpt (the one in force is copied to verifications.user_*, see people.refresh)
CREATE TABLE IF NOT EXISTS people(person_id TEXT PRIMARY KEY, name TEXT, seen_at TEXT);
CREATE TABLE IF NOT EXISTS judgements(claim_id TEXT, passage_id TEXT, person_id TEXT, verdict TEXT, note TEXT, at TEXT,
  quote TEXT, start INT, end INT, PRIMARY KEY(claim_id, passage_id, person_id));
-- every state of a check, a theme run or a codebook that was sent or brought in (its fingerprint): what tells a newer
-- version from one changed on both sides
CREATE TABLE IF NOT EXISTS sync_seen(kind TEXT, key TEXT, fp TEXT, PRIMARY KEY(kind, key, fp));
-- a colleague's version of something both of you changed (a "sync clash"), kept beside yours: of_key is yours
CREATE TABLE IF NOT EXISTS sync_copies(kind TEXT, key TEXT, of_key TEXT, person_id TEXT, at TEXT,
  PRIMARY KEY(kind, key));
-- what was removed from this copy (a document, a check, a theme run), so a colleague's work does not bring it back
CREATE TABLE IF NOT EXISTS sync_removed(kind TEXT, key TEXT, title TEXT, at TEXT, person_id TEXT, fp TEXT,
  PRIMARY KEY(kind, key));
-- each colleague's work brought in: who, when, and what it changed
CREATE TABLE IF NOT EXISTS sync_log(log_id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, person_id TEXT,
  report_json TEXT);

-- 0.15 (reader 2, see reader.py): each document's blocks in reading order (a paragraph, a heading, a caption, a table,
-- a running head...), with what kind each is, whether features read it (included) and its box on the page in points
-- from the top left (NULL: read without boxes); a table's rows and cells; and a person's corrections (Restore, Leave
-- out), kept by the block's text so they hold when the document is read again
CREATE TABLE IF NOT EXISTS blocks(doc_id TEXT, n INT, page INT, start INT, end INT, kind TEXT, included INT,
  x0 REAL, y0 REAL, x1 REAL, y1 REAL, PRIMARY KEY(doc_id, n));
CREATE TABLE IF NOT EXISTS doc_tables(doc_id TEXT, n INT, block INT, page INT, start INT, end INT, caption TEXT,
  rows_json TEXT, PRIMARY KEY(doc_id, n));
CREATE TABLE IF NOT EXISTS block_choices(doc_id TEXT, fp TEXT, included INT, kind TEXT, person_id TEXT, at TEXT,
  PRIMARY KEY(doc_id, fp));

-- 0.16 (roadmap F4, researchlog.py): the research log, a dated record of what was decided: written by the app as it
-- happens (kind: what happened, subject: what about, title: its name then) and a person's own entries (kind 'entry');
-- `why` is a person's reason, `version_id` the state before the change (history.py)
CREATE TABLE IF NOT EXISTS research_log(entry_id TEXT PRIMARY KEY, at TEXT, person_id TEXT, kind TEXT,
  subject_kind TEXT, subject_id TEXT, title TEXT, text TEXT, why TEXT, version_id TEXT, data_json TEXT,
  edited_at TEXT, app_version TEXT);
CREATE INDEX IF NOT EXISTS ix_research_log_at ON research_log(at);
CREATE INDEX IF NOT EXISTS ix_research_log_subject ON research_log(subject_kind, subject_id);
-- 0.16 (F2, notes.py): a person's notes and highlights on exact words of a document (document offsets, the words as
-- `quote`, the note as `text`: empty for a highlight)
CREATE TABLE IF NOT EXISTS notes(note_id TEXT PRIMARY KEY, doc_id TEXT, start INT, end INT, quote TEXT, page INT,
  text TEXT, colour TEXT, person_id TEXT, created_at TEXT, edited_at TEXT);
CREATE INDEX IF NOT EXISTS ix_notes_doc ON notes(doc_id, start);
-- 0.16 (F5, history.py): the state of a set of themes or of a check before a person changed it, to compare and
-- restore (codebooks keep theirs beside their file)
CREATE TABLE IF NOT EXISTS versions(version_id TEXT PRIMARY KEY, kind TEXT, key TEXT, at TEXT, person_id TEXT,
  label TEXT, data_json TEXT);
CREATE INDEX IF NOT EXISTS ix_versions_key ON versions(kind, key, at);
-- 0.18 (L1, sharing.py): what is shared. One row per item (kind: check, themes, codebook, note, log, link; key: its id,
-- the same in every copy): private, shared or withdrawn, who made it (`owner`, NULL: not known, made before 0.18), who
-- set the state and when. No row: made in this copy by its person, and private
CREATE TABLE IF NOT EXISTS shares(kind TEXT, key TEXT, state TEXT, owner TEXT, by TEXT, at TEXT, title TEXT,
  PRIMARY KEY(kind, key));
-- 0.18 (the shared folder, sync/folder.py): this copy's own record of the folder, never exchanged. What it wrote there
-- (kind: an item's kind and key with its fingerprint; "doc": a document's stub; "reading", "file": a reading or an
-- original file there; "row": one of the project's rows; "head": the folder written to and the last bundle's number;
-- "words": a document whose words may be in what was written, taken out again if it is later kept out of the folder
-- (its fp: who may read it with AI and its checksum as last written, as JSON, so this holds once the document is
-- removed here);
-- "content": an item written whole, "<kind>/<key>", taken out again if it is later taken back; "keep": a colleague's
-- switch as last read; "seen": a colleague whose subfolder this copy has seen there (an owner whose subfolder was
-- never seen has not left); a "reading" or "file" seen in a colleague's subfolder has that colleague's id as its fp),
-- with the bundle that carried it; how far it has brought in each colleague's bundles; and what the folder says of each
-- document (the latest stub heard), so a check that read a document this copy does not hold is still compared by
-- content (sync.fingerprints._canon), and the document's file can be fetched once it arrives
CREATE TABLE IF NOT EXISTS sync_written(kind TEXT, key TEXT, fp TEXT, seq INT, at TEXT, PRIMARY KEY(kind, key));
CREATE TABLE IF NOT EXISTS sync_folder_read(person_id TEXT PRIMARY KEY, seq INT, at TEXT, epoch TEXT);
CREATE TABLE IF NOT EXISTS sync_folder_docs(doc_id TEXT PRIMARY KEY, text_fp TEXT, sha1 TEXT, title TEXT, reading TEXT,
  file TEXT, name TEXT, kept_out INT, person_id TEXT, at TEXT, ai_access TEXT, ai_by TEXT);
-- 0.18 (L2, ownership.py): one owner and several collaborators. `ownership`: who the owner is, as a chain of records
-- (seq 1: the maker or whoever first claimed it; then each hand-over or take-over, `after` the owner before it).
-- `proposals`: a collaborator's change to the documents (kind: add, remove, reread, blocks, loosen), written by
-- their copy. `decisions`: the owner's word on a proposal. `canon`: the documents as the owner accepted them, one row
-- per document and writer (state in/removed, its reading, who may read it with AI, which blocks are left out), each
-- part with the number (`*_n`) of the owner's change that last set it. These four travel (their own merge rules).
-- `canon_seen`: this copy's own record of how far it has followed `canon`, never merged.
CREATE TABLE IF NOT EXISTS ownership(seq INT, owner TEXT, by TEXT, at TEXT, kind TEXT, after TEXT, why TEXT,
  PRIMARY KEY(seq, by));
CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, kind TEXT, doc TEXT, title TEXT, by TEXT, at TEXT,
  detail_json TEXT, taken_back_at TEXT);
CREATE TABLE IF NOT EXISTS decisions(proposal TEXT, by TEXT, owner_seq INT, verdict TEXT, reason TEXT, at TEXT,
  auto INT, PRIMARY KEY(proposal, by));
CREATE TABLE IF NOT EXISTS canon(doc TEXT, by TEXT, owner_seq INT, n INT, state TEXT, state_n INT, sha1 TEXT, title TEXT,
  text_fp TEXT, reader INT, read_n INT, ai_access TEXT, ai_n INT, ai_hist_json TEXT, blocks_json TEXT, blocks_n INT,
  at TEXT, PRIMARY KEY(doc, by));
CREATE TABLE IF NOT EXISTS canon_seen(doc TEXT PRIMARY KEY, state_n INT, read_n INT, ai_n INT, ai_level TEXT,
  blocks_n INT, blocks_json TEXT, gone INT, came_from TEXT, read_tried INT, read_note TEXT, read_from TEXT);
"""
SCHEMA = SCHEMA.replace("{PLACES_TABLE}", PLACES_TABLE)

# Indexes on columns that older workspaces gain only through MIGRATIONS, so they are created afterwards.
# 0.11.1: the label lookups per passage (`WHERE framework=? AND passage_id=?`) and per task were planned over the
# framework index alone (a project has no statistics), hundreds of times slower on a large project; the index on
# (passage_id, framework) answers them directly, and the old single-column one is dropped.
# The task queue asks every few seconds what waits and what a claim holds: ix_tasks_waiting holds only the tasks that
# wait (its WHERE is taskqueue.WAITING word for word: SQLite uses a partial index only for a query that repeats its
# condition), ix_tasks_claimed only the tasks a claim holds. Both stay small however many tasks were answered.
# ix_results_route: taskqueue._last_answer (every queue status poll) asks for the newest answer of a route, which
# otherwise reads the text of every answer ever given (about 0.1 s for 200,000 answers).
INDEXES = """
CREATE INDEX IF NOT EXISTS ix_ver_subject ON verifications(subject_kind, subject_id);
CREATE INDEX IF NOT EXISTS ix_ver_passage ON verifications(passage_id);
CREATE INDEX IF NOT EXISTS ix_tasks_kind_status ON tasks(kind, status);
CREATE INDEX IF NOT EXISTS ix_claims_task ON claims(task_id);
CREATE INDEX IF NOT EXISTS ix_claims_doc ON claims(doc_id);
CREATE INDEX IF NOT EXISTS ix_evidence_claim ON evidence(claim_id);
CREATE INDEX IF NOT EXISTS ix_interactions_claim ON interactions(claim_id);
CREATE INDEX IF NOT EXISTS ix_user_claims_hyp ON user_claims(hyp_id, part);
CREATE INDEX IF NOT EXISTS ix_hypotheses_created ON hypotheses(created_at);
CREATE INDEX IF NOT EXISTS ix_second_subject ON second_opinions(subject_id);
DROP INDEX IF EXISTS ix_labels_passage;
CREATE INDEX IF NOT EXISTS ix_labels_passage_fw ON labels(passage_id, framework);
CREATE INDEX IF NOT EXISTS ix_labels_task ON labels(task_id);
CREATE INDEX IF NOT EXISTS ix_labels_doc ON labels(framework, doc_id);
CREATE INDEX IF NOT EXISTS ix_labels_code ON labels(framework, code);
DROP INDEX IF EXISTS ix_term_mentions_term;
DROP INDEX IF EXISTS ix_term_mentions_passage;
DROP INDEX IF EXISTS ix_term_mentions_doc;
CREATE INDEX IF NOT EXISTS ix_term_mentions_at ON term_mentions(passage_id, start, end, term_id);
CREATE INDEX IF NOT EXISTS ix_concept_terms_term ON concept_terms(term_id);
CREATE INDEX IF NOT EXISTS ix_theme_members_theme ON theme_members(run_id, theme_id);
CREATE INDEX IF NOT EXISTS ix_mentions_chain ON mentions(doc_id, chain_id);
CREATE INDEX IF NOT EXISTS ix_reviews_item ON reviews(item_kind, item_id);
CREATE INDEX IF NOT EXISTS ix_tasks_queued ON tasks(queued, kind, status);
CREATE INDEX IF NOT EXISTS ix_tasks_waiting ON tasks(kind, queued_at) WHERE COALESCE(queued, 0)=1 AND
  COALESCE(access, 'cloud')='cloud' AND (status IN ('pending', 'retry') OR (status='done' AND again=1));
CREATE INDEX IF NOT EXISTS ix_tasks_claimed ON tasks(claimed_by) WHERE claimed_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_results_route ON results(route, received_at);
"""

DEFAULT_CONFIG: dict[str, Any] = {
    "models": {
        "screen": "heuristic",
        "split": "claude-fable-5-1",
        "extract": "claude-opus-5-5",
        "verify": "claude-opus-5-5",
    },
    "thresholds": {
        "screen_min_score": 2.0,
        "accept_confidence": 0.8,
        "support_confidence": 0.6,
        "verify_top_k": 6,
    },
    "passages": {"max_chars": 1100, "min_chars": 200},
}


MIGRATIONS = [("documents", "declared_ref", "TEXT"), ("vca_refs", "alias_of", "TEXT"), ("vca_refs", "note", "TEXT"),
              ("user_claims", "hyp_id", "TEXT"), ("user_claims", "part", "INT DEFAULT 0"), ("user_claims", "role", "TEXT"),
              ("user_claims", "framework", "TEXT"), ("hypotheses", "parts_json", "TEXT"),
              # a person's own judgement of an excerpt, which overrides the AI's (see claimcheck.set_judgement)
              ("verifications", "user_verdict", "TEXT"), ("verifications", "user_note", "TEXT"),
              ("verifications", "user_at", "TEXT"),
              # the sentence a person points to for their judgement (document offsets), shown instead of the AI's quote
              ("verifications", "user_quote", "TEXT"), ("verifications", "user_start", "INT"),
              ("verifications", "user_end", "INT"),
              # 0.6: the page of a paragraph (NULL for documents without pages), and scanned PDF pages
              ("paragraphs", "page", "INT"), ("documents", "ocr_pages", "INT"), ("documents", "scanned_pages", "INT"),
              # 0.6: the AI's note that an excerpt is about another group (check-v3), and its earlier judgements
              # of an excerpt it was asked to read again (a JSON list, oldest first)
              ("verifications", "scope_note", "TEXT"), ("verifications", "ai_history_json", "TEXT"),
              # 0.6: when the documents added after a check were last read for it ("Read the new documents")
              ("hypotheses", "docs_checked_at", "TEXT"),
              # 0.6: the latest time the AI read an excerpt again: the person's hint and the AI's reason (JSON)
              ("verifications", "reread_json", "TEXT"),
              # 0.7 (check-v4): the named form a quote refers to ("it" = "the planned plant"), quoted from the
              # excerpt or from the passage before it (refers_where: 'excerpt' | 'before'); document offsets
              ("verifications", "refers_to", "TEXT"), ("verifications", "refers_start", "INT"),
              ("verifications", "refers_end", "INT"), ("verifications", "refers_where", "TEXT"),
              # 0.7: exactly what produced an answer: the model's digest (or file name), the seed and the settings
              ("results", "digest", "TEXT"), ("results", "seed", "INT"), ("results", "settings_json", "TEXT"),
              # 0.8 (G1): a task handed to the queue for an AI outside this program (Claude Code), when, and the claim
              # that holds it now (a batch handed out: who took it and when; it lapses after queue.CLAIM_MINUTES)
              ("tasks", "queued", "INT DEFAULT 0"), ("tasks", "queued_at", "TEXT"), ("tasks", "claimed_by", "TEXT"),
              ("tasks", "claimed_at", "TEXT"),
              # 0.8 (G3): 1 once the task went up to the next model (it does so once at most), and a model the task
              # must keep (an acceptance run per model): routing then leaves it alone
              ("tasks", "step", "INT DEFAULT 0"), ("tasks", "forced_model", "TEXT"),
              # 0.8 (G3): an answered task waiting to be read again by the stronger model (its answer counts meanwhile)
              ("tasks", "again", "INT DEFAULT 0"),
              # 0.8.1: the role a task is routed as when it is not its kind: "audit" for a second-model audit of the
              # SDG pack's answers (audit-vca, verify-claims), routed like a second opinion (NULL: its kind)
              ("tasks", "role", "TEXT"),
              # 0.8 (G5): how an answer was produced: the route (Claude Code, the Claude API, a local server, the file
              # queue), the helper agent, whether it came from the stronger model, and when its batch was claimed
              ("results", "route", "TEXT"), ("results", "helper", "TEXT"), ("results", "step", "INT DEFAULT 0"),
              ("results", "claimed_at", "TEXT"),
              # 0.8 (G1): a check by queue: where each hypothesis and each part stand (NULL: an ordinary check)
              ("hypotheses", "queue", "TEXT"), ("user_claims", "stage", "TEXT"),
              # 0.11: who may read a document with AI ('cloud', 'local', 'none'; NULL: the project's default), why
              # (a person's note, it changes nothing), and an optional cap on the share Claude may read (percent)
              ("documents", "ai_access", "TEXT"), ("documents", "ai_note", "TEXT"), ("documents", "ai_budget", "REAL"),
              # 0.11: the most restricted setting of the documents a task's text comes from (see access.py)
              ("tasks", "access", "TEXT"),
              # 0.13.3: the title read from the file, kept while the title of the work it is linked to in the
              # bibliography replaces it (NULL: the document has its own title; see bibliography._sync_titles)
              ("documents", "file_title", "TEXT"),
              # 0.13.6: where a hypothesis comes from: "batch" (Check several) or an add-on's own kind, and the id of
              # what it comes from there (NULL: typed by a person, or made before 0.13.6)
              ("hypotheses", "origin", "TEXT"), ("hypotheses", "origin_id", "TEXT"),
              # a theme a person removed as not relevant, and when (NULL: shown); a theme found in place of
              # a removed one (that theme's id; NULL: found by the run); a passage such a theme took from another
              # theme (the theme it was in before; NULL: where the run put it)
              ("themes", "removed_at", "TEXT"), ("themes", "replaces", "INT"), ("theme_members", "found_in", "INT"),
              # 0.14: whose judgement of an excerpt is in force (people.py), and who made a review (NULL: made before
              # 0.14, in this copy)
              ("verifications", "user_by", "TEXT"), ("reviews", "person_id", "TEXT"),
              # 0.14: a fingerprint of a document's text (sync.py: the same file read into other text is another copy)
              ("documents", "text_fp", "TEXT"),
              # 0.15 (roadmap J4.2): which reader read a document's text (ingest.READER; documents read before 0.15
              # get 1, the only reader there was) and the ENLENS version that read it; the ENLENS version behind every
              # AI answer, run, label, theme run and check (NULL: made before 0.15). Never part of a sync
              # fingerprint: it says how a result was made, not what it is
              ("documents", "reader", "INT"), ("documents", "app_version", "TEXT"), ("results", "app_version", "TEXT"),
              ("runs", "app_version", "TEXT"), ("labels", "app_version", "TEXT"), ("theme_runs", "app_version", "TEXT"),
              ("hypotheses", "app_version", "TEXT"),
              # 0.15 (reader 2): the kind of block a passage was made from (reader.KINDS; NULL: read by reader 1), and
              # the document's reading report (what the reader did, and how well it read; reader.finish_report)
              ("passages", "block", "TEXT"), ("documents", "reading_json", "TEXT"),
              # 0.15 (Read with the new reader, reread.py): the fingerprints of the texts a document had before it was
              # read again (a JSON list, oldest first; sync.text_fp), so a colleague's copy of an earlier reading can
              # be known as the same document later; and the share of it Claude had read in passages that have no
              # place in the new reading (0 to 1): their ledger rows name no passage now, and it still counts toward
              # what Claude has read of it (access.shares)
              ("documents", "old_fps", "TEXT"), ("documents", "sent_share", "REAL"),
              # 0.16 (K1, codebooks.py): the code a label had before its code was merged into another, so restoring
              # the codebook from before the merge gives it back (NULL: never merged)
              ("labels", "merged_from", "TEXT"),
              # 0.18 (sync/folder.py): which start of a colleague's bundles (their epoch) this copy has read up to
              ("sync_folder_read", "epoch", "TEXT"),
              # 0.18: who may read a document with AI as the folder said (the strictest heard), so a document a colleague
              # keeps out of the folder is as strict here from the moment its file is added (sync/folder.py hold_settings)
              ("sync_folder_docs", "ai_access", "TEXT"), ("sync_folder_docs", "ai_by", "TEXT"),
              # 0.18 L2: whose new reading a copy made from their zip holds (ownership.adopt)
              ("canon_seen", "read_from", "TEXT")]


def _add_columns(cx: sqlite3.Connection, migrations) -> None:
    """Add the columns (table, column, type) a table does not have yet; each only once."""
    for table, col, typ in migrations:
        cols = {r[1] for r in cx.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            cx.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def _migrate(cx: sqlite3.Connection) -> None:
    """Add columns introduced after a workspace was created, and give checks from 0.4 a hypothesis record."""
    _add_columns(cx, MIGRATIONS)
    # 0.15: a document without a reader was read before readers were counted, so by the first one (also one that
    # comes in from a colleague's older ENLENS)
    cx.execute("UPDATE documents SET reader=1 WHERE reader IS NULL")
    # a 0.4 claim check is a hypothesis with one part (the claim itself); its target was an SDG target
    cx.execute("INSERT OR IGNORE INTO hypotheses(hyp_id, text, framework, code, options_json, decomposed, rationale, model, "
               "created_at) SELECT claim_id, text, CASE WHEN COALESCE(target, '') != '' THEN 'sdg' END, NULLIF(target, ''), "
               "options_json, 0, rationale, model, created_at FROM user_claims WHERE hyp_id IS NULL")
    cx.execute("UPDATE user_claims SET hyp_id=claim_id, part=0, "
               "framework=CASE WHEN COALESCE(target, '') != '' THEN 'sdg' END WHERE hyp_id IS NULL")


# 0.17.2: the glossary's state as a build notes it. The corpus version it was made from has a new name: an ENLENS before
# 0.17.2 reads `terms_corpus_version`, finds none and says its glossary is not made, rather than showing one whose places
# it cannot read (it reads them by `doc_id`); and when it makes its own, its note tells this version so
GLOSSARY_META = ("glossary_corpus_version", "terms_corpus_version", "terms_built_at", "terms_build_id")


def passage_range(doc_id: str) -> tuple[str, str]:
    """The ids of a document's passages, as a range [low, high) to compare passage ids with. A passage id is
    f"{doc_id}:{seq:04d}" and a document id has no colon (ingest: "d" and hex digits; a colleague's: sync.common.DOC_ID;
    the ids of answers kept from an earlier reading, "<doc>:r1-0005", never name a passage row), so exactly the
    passages of this document have ids that start with its id and a colon; ';' is the character after ':'."""
    return f"{doc_id}:", f"{doc_id};"


# a passage id's document, in SQL (see `passage_range`): the part before the colon
DOC_OF = "substr({0}, 1, instr({0}, ':') - 1)"


def _drop_old_places(cx: sqlite3.Connection) -> bool:
    """0.17.2: the glossary's places in their new shape (PLACES_TABLE). A table of the old shape (with a rowid) is
    derived, so it is dropped rather than copied, and the glossary is made again, as for a project whose glossary was
    never made ("No glossary yet", Make the glossary). A glossary an ENLENS before 0.17.2 made in this file (its note
    `terms_corpus_version`: the project of an earlier version, or such an ENLENS that opened the file since) is
    dropped too: its terms are not this version's places. Indexes such an ENLENS made go in store.INDEXES. Returns
    whether anything was dropped."""
    row = cx.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='term_mentions'").fetchone()
    old_shape = row is not None and "WITHOUT ROWID" not in (row[0] or "").upper()
    if old_shape:
        cx.execute("DROP TABLE term_mentions")  # its indexes go with it
        cx.execute(PLACES_TABLE)
    old_build = cx.execute("SELECT 1 FROM meta WHERE key='terms_corpus_version'").fetchone() is not None
    if old_build:
        cx.execute("DELETE FROM term_mentions")
        cx.execute("DELETE FROM terms")
        cx.execute(f"DELETE FROM meta WHERE key IN ({','.join('?' * len(GLOSSARY_META))})", GLOSSARY_META)
    return old_shape or old_build


# 0.17.2: the file is made smaller (VACUUM) after the old places were dropped only when that frees at least this much and
# this share of it; less is left as free pages, which SQLite fills before the file grows
VACUUM_MIN_FREE = 32 * 1024 * 1024
VACUUM_MIN_SHARE = 0.25
VACUUM_WAIT_MS = 2000   # how long it waits for another connection to let go of the file before it leaves it as it is


def _vacuum_after_drop(cx: sqlite3.Connection, folder: Path) -> bool:
    """Once, right after the old places were dropped: then the copy VACUUM makes holds only what is left (here 94 MB of a
    460 MB file, under a second), where later it would hold the glossary again too. It needs free disk space for that
    copy and for the write-ahead log, which holds it once more, so it is done only when twice that is free; and only
    when no other program is writing to the file (it waits VACUUM_WAIT_MS for one; readers do not stop it). Otherwise
    the freed pages stay in the file and the next glossary is written into them. Returns whether it ran."""
    import shutil

    size = cx.execute("PRAGMA page_size").fetchone()[0]
    pages, free = cx.execute("PRAGMA page_count").fetchone()[0], cx.execute("PRAGMA freelist_count").fetchone()[0]
    if free * size < VACUUM_MIN_FREE or free < VACUUM_MIN_SHARE * pages:
        return False
    try:
        if shutil.disk_usage(folder).free < 2 * (pages - free) * size + VACUUM_MIN_FREE:
            return False
    except OSError:
        return False
    cx.execute(f"PRAGMA busy_timeout={int(VACUUM_WAIT_MS)}")
    try:
        cx.execute("VACUUM")
        cx.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # the log held the whole new copy: give the space back
    except sqlite3.OperationalError:   # another connection reads or writes the file: left as it is
        return False
    return True


def _setup_addons(cx: sqlite3.Connection) -> None:
    """0.13.6: each add-on's tables, columns and indexes, after ENLENS's own and in the add-ons' order, the same
    idempotent way (docs/EXTENDING.md)."""
    from .addons import database

    for db in database():
        if db["schema"]:
            cx.executescript(db["schema"])
        _add_columns(cx, db["migrations"])
        if db["indexes"]:
            cx.executescript(db["indexes"])


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


class _Cx(sqlite3.Connection):
    """0.15.7: a connection a workspace can keep track of (a plain sqlite3.Connection cannot be weakly referenced)."""


class Workspace:
    """One project folder. Connections are kept per thread and reused; `connect()` is one transaction.

    Nested `connect()` blocks become savepoints, so an inner block that fails undoes only its own writes.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.db_path = self.root / "enlens.sqlite"
        self.config_path = self.root / "config.json"
        self._local = threading.local()
        self._config_cache: tuple[tuple, dict] | None = None
        # 0.15.7: every connection opened to this project, in any thread, so `close_all` can close them before the
        # folder is moved or removed. A thread's connection is not closed when the thread ends (a connection holds
        # a reference to itself, so only the garbage collector frees it), and on Windows an open database file cannot
        # be moved or deleted: removing a project, a quick look or a scratch copy failed there.
        self._all: weakref.WeakSet = weakref.WeakSet()
        self._all_lock = threading.Lock()
        self._gen = 0

    # ---- lifecycle -------------------------------------------------------------------------
    @classmethod
    def create(cls, root: str | Path) -> "Workspace":
        ws = cls(root)
        ws.root.mkdir(parents=True, exist_ok=True)
        for sub in ("tasks", "results", "exports", "report"):
            (ws.root / sub).mkdir(exist_ok=True)
        if not ws.config_path.exists():
            ws.config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        ws._setup()
        return ws

    @classmethod
    def open(cls, root: str | Path) -> "Workspace":
        ws = cls(root)
        if not ws.db_path.exists():
            raise FileNotFoundError(f"No workspace at {ws.root}. Run `enlens --ws {ws.root} init` first.")
        ws._setup()  # idempotent: adds tables, columns and indexes introduced by newer versions
        return ws

    def _setup(self) -> None:
        cx = sqlite3.connect(self.db_path, timeout=60)
        try:
            cx.execute("PRAGMA journal_mode=WAL")  # readers do not block on a long write; persistent per file
            # each statement of the schema below is a transaction of its own: with the default FULL each one is
            # flushed to disk (about a second per new project on Windows, and a round of the shared folder makes
            # one to three scratch projects); NORMAL, as every connection of `_conn`, is safe with WAL
            cx.execute("PRAGMA synchronous=NORMAL")
            doc_cols = {r[1] for r in cx.execute("PRAGMA table_info(documents)")}
            before_011 = bool(doc_cols) and "ai_access" not in doc_cols  # a project made before 0.11, opened now
            before_018 = not cx.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shares'").fetchone()
            cx.executescript(SCHEMA)
            _migrate(cx)
            dropped = _drop_old_places(cx)
            cx.executescript(INDEXES)
            _setup_addons(cx)
            if before_018:  # 0.18 (L1): a project exchanged before counts as shared; one never sent starts private
                from .sharing import upgrade

                upgrade(cx, self.root)
            cx.commit()
            if dropped:
                _vacuum_after_drop(cx, self.root)
        finally:
            cx.close()
        if before_011:
            from .access import upgrade

            upgrade(self)

    def _conn(self) -> sqlite3.Connection:
        cx = getattr(self._local, "cx", None)
        if cx is not None and getattr(self._local, "gen", 0) != self._gen:
            cx = None  # 0.15.7: closed by close_all; a new one if this thread goes on using the project
        if cx is None:
            # transactions are ours, see connect(); check_same_thread=False only lets close_all close it from another
            # thread: each connection is still used by the thread that opened it alone
            cx = sqlite3.connect(self.db_path, timeout=60, isolation_level=None, factory=_Cx, check_same_thread=False)
            cx.row_factory = sqlite3.Row
            cx.execute("PRAGMA synchronous=NORMAL")  # safe with WAL; much faster commits
            # a project may have come from someone else: nothing its database's own definitions name (in a default, an
            # index, a check) may call functions that reach outside the database
            cx.execute("PRAGMA trusted_schema=OFF")
            self._local.cx, self._local.depth, self._local.gen = cx, 0, self._gen
            with self._all_lock:
                self._all.add(cx)
        return cx

    def close(self) -> None:
        """Close this thread's connection (it is reopened on the next use)."""
        cx = getattr(self._local, "cx", None)
        if cx is not None:
            cx.close()
            self._local.cx = None

    def close_all(self) -> None:
        """0.15.7: close every connection to this project, in every thread, before its folder is moved or removed (on
        Windows an open database file cannot be). A thread that uses the project afterwards opens a new one."""
        with self._all_lock:
            cxs = list(self._all)
            self._gen += 1
        for cx in cxs:
            try:
                cx.close()
            except sqlite3.Error:
                pass

    @property
    def config(self) -> dict[str, Any]:
        try:
            st = self.config_path.stat()
            stamp: tuple = (st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = ()
        if self._config_cache and self._config_cache[0] == stamp:
            return json.loads(json.dumps(self._config_cache[1]))
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        if stamp:
            user = json.loads(self.config_path.read_text())
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        self._config_cache = (stamp, cfg)
        return json.loads(json.dumps(cfg))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        cx = self._conn()
        depth = self._local.depth
        # IMMEDIATE: take the write lock at the start, waiting for other writers (timeout 60 s). A deferred BEGIN that
        # reads first and writes later fails at once with "database is locked" when another job wrote in between.
        cx.execute("BEGIN IMMEDIATE" if depth == 0 else f"SAVEPOINT sp{depth}")
        self._local.depth = depth + 1
        try:
            yield cx
        except BaseException:
            self._local.depth = depth
            if depth == 0:
                cx.execute("ROLLBACK")
            else:
                cx.execute(f"ROLLBACK TO sp{depth}")
                cx.execute(f"RELEASE sp{depth}")
            raise
        self._local.depth = depth
        cx.execute("COMMIT" if depth == 0 else f"RELEASE sp{depth}")

    # ---- small helpers ---------------------------------------------------------------------
    def query(self, sql: str, args: tuple | list = ()) -> list[sqlite3.Row]:
        return self._conn().execute(sql, tuple(args)).fetchall()

    def scalar(self, sql: str, args: tuple | list = ()) -> Any:
        row = self._conn().execute(sql, tuple(args)).fetchone()
        return row[0] if row else None

    def meta(self, key: str, default: Any = None) -> Any:
        v = self.scalar("SELECT value FROM meta WHERE key=?", (key,))
        try:
            return json.loads(v) if v is not None else default
        except json.JSONDecodeError:
            return default

    def set_meta(self, key: str, value: Any, cx: sqlite3.Connection | None = None) -> None:
        sql, args = "INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value))
        if cx is not None:
            cx.execute(sql, args)
        else:
            with self.connect() as c:
                c.execute(sql, args)

    def project_uid(self, cx: sqlite3.Connection | None = None) -> str:
        """0.14: what makes two copies of a project the same project (made once; it travels with the project zip)."""
        uid = self.meta("project_uid")
        if not uid:
            import uuid

            uid = uuid.uuid4().hex
            self.set_meta("project_uid", uid, cx)
        return uid

    def removed(self, cx: sqlite3.Connection, kind: str, key: str, title: str | None) -> None:
        """0.14: note that a document, a check or a theme run was removed here, so a colleague's work does not bring it
        back (adding the same file again takes the note away). A document's note keeps the fingerprint of its text,
        so the checks that read it are still compared by content (sync.py)."""
        from .people import me

        fp = None
        if kind == "document":
            from .sync import text_fp

            row = cx.execute("SELECT text FROM documents WHERE doc_id=?", (key,)).fetchone()
            fp = text_fp(row[0]) if row else None
        cx.execute("INSERT OR REPLACE INTO sync_removed(kind, key, title, at, person_id, fp) VALUES (?,?,?,?,?,?)",
                   (kind, key, title, now(), me(), fp))

    def corpus_version(self) -> int:
        """Changes whenever documents are added or removed; search indexes are rebuilt when it does."""
        return int(self.meta("corpus_version", 0) or 0)

    def bump_corpus(self, cx: sqlite3.Connection) -> None:
        row = cx.execute("SELECT value FROM meta WHERE key='corpus_version'").fetchone()
        cx.execute("INSERT OR REPLACE INTO meta VALUES ('corpus_version', ?)", (json.dumps(int(json.loads(row[0]) if row else 0) + 1),))

    def reset_corpus(self) -> dict[str, int]:
        """Remove documents and everything derived from them. The VCA and the split justifications stay."""
        out = {}
        with self.connect() as cx:
            for kind, sql in (("document", "SELECT doc_id, title FROM documents"), ("check", "SELECT hyp_id, text FROM hypotheses"),
                              ("themes", "SELECT run_id, NULL FROM theme_runs")):
                for key, title in cx.execute(sql).fetchall():
                    self.removed(cx, kind, key, title)
            for t in ("documents", "pages", "paragraphs", "headings", "passages", "embeddings", "doc_refs", "claims",
                      "claim_targets", "evidence", "interactions", "verifications", "labels", "terms", "term_mentions",
                      "concepts", "concept_terms", "theme_runs", "themes", "theme_members", "mentions", "bib_links",
                      "blocks", "doc_tables", "block_choices"):
                out[t] = cx.execute(f"DELETE FROM {t}").rowcount
            kinds = ("('extract','verify','verify_set','expand','check','decompose','reread','second','label','link',"
                     "'theme','resolve')")
            out["results"] = cx.execute(f"DELETE FROM results WHERE kind IN {kinds}").rowcount
            out["tasks"] = cx.execute(f"DELETE FROM tasks WHERE kind IN {kinds}").rowcount
            out["user_claims"] = cx.execute("DELETE FROM user_claims").rowcount
            out["second_opinions"] = cx.execute("DELETE FROM second_opinions").rowcount
            out["hypotheses"] = cx.execute("DELETE FROM hypotheses").rowcount
            out["reviews"] = cx.execute("DELETE FROM reviews WHERE item_kind IN ('claim', 'label', 'theme', "
                                        "'theme_member')").rowcount
            self.bump_corpus(cx)
        return out

    def remove_document(self, doc_id: str, why: str | None = None) -> dict[str, int]:
        """Remove one document and what the pipeline derived from it.

        Hypothesis checks keep their grades: they are a record of what was read (each check stores the passage
        text and title it showed), so a past verdict does not change when a source is removed later. 0.16: the
        research log says so (`why`: the person's reason), and a person's notes on it stay (notes.py lists them).
        """
        out: dict[str, int] = {}
        with self.connect() as cx:
            row = cx.execute("SELECT title FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
            if not row:
                raise KeyError(doc_id)
            self.removed(cx, "document", doc_id, row[0])
            from . import researchlog

            researchlog.record(cx, "document-removed", f"Removed the document {researchlog.quoted(row[0])}.",
                               "document", doc_id, row[0], why=why)
            cx.execute("DELETE FROM sync_copies WHERE kind='document' AND key=?", (doc_id,))
            pids = [r[0] for r in cx.execute("SELECT passage_id FROM passages WHERE doc_id=?", (doc_id,))]
            claim_ids = [r[0] for r in cx.execute("SELECT claim_id FROM claims WHERE doc_id=?", (doc_id,))]
            for cid in claim_ids:
                cx.execute("DELETE FROM claim_targets WHERE claim_id=?", (cid,))
                cx.execute("DELETE FROM evidence WHERE claim_id=?", (cid,))
            out["claims"] = cx.execute("DELETE FROM claims WHERE doc_id=?", (doc_id,)).rowcount
            out["interactions"] = cx.execute("DELETE FROM interactions WHERE doc_id=? AND kind='stated'", (doc_id,)).rowcount
            out["verifications"] = cx.execute("DELETE FROM verifications WHERE doc_id=? AND subject_kind != 'user_claim'",
                                              (doc_id,)).rowcount
            # one statement per table rather than four per passage (0.11.1: a document of a few hundred passages in a
            # project with many tasks held the database for seconds)
            own = "(SELECT passage_id FROM passages WHERE doc_id=?)"
            cx.execute(f"DELETE FROM embeddings WHERE passage_id IN {own}", (doc_id,))
            cx.execute(f"DELETE FROM theme_members WHERE passage_id IN {own}", (doc_id,))
            for tbl in ("results", "tasks"):
                cx.execute(f"DELETE FROM {tbl} WHERE task_id IN (SELECT 'extract:' || passage_id FROM passages "
                           "WHERE doc_id=?)", (doc_id,))
                # model labels of its passages: their tasks are 'label:<framework>:<passage_id>'; the passage ids of
                # one document share a length (seq is padded), so the tail of the task id is compared exactly
                for n in sorted({len(pid) for pid in pids}):
                    cx.execute(f"DELETE FROM {tbl} WHERE kind='label' AND substr(task_id, -?) IN {own}", (n, doc_id))
            # 0.7: what was derived from the document (the term index is rebuilt when the corpus version changes)
            out["labels"] = cx.execute("DELETE FROM labels WHERE doc_id=?", (doc_id,)).rowcount
            out["mentions"] = cx.execute("DELETE FROM mentions WHERE doc_id=?", (doc_id,)).rowcount
            cx.execute("DELETE FROM term_mentions WHERE passage_id >= ? AND passage_id < ?", passage_range(doc_id))
            for tbl in ("blocks", "doc_tables", "block_choices"):  # 0.15
                cx.execute(f"DELETE FROM {tbl} WHERE doc_id=?", (doc_id,))
            # 0.15: answers kept as records when the document moved to the new reader name passages that no longer
            # exist ("<doc>:r1-0005", reread.tombstone); they go with the document
            for tbl in ("results", "tasks"):
                cx.execute(f"DELETE FROM {tbl} WHERE instr(task_id, ?) > 0 AND task_id GLOB ?",
                           (f"{doc_id}:r", f"*{doc_id}:r[0-9]*-[0-9]*"))
            head = f"resolve:{doc_id}:"
            for tbl in ("results", "tasks"):
                cx.execute(f"DELETE FROM {tbl} WHERE kind='resolve' AND substr(task_id, 1, ?) = ?", (len(head), head))
            out["passages"] = cx.execute("DELETE FROM passages WHERE doc_id=?", (doc_id,)).rowcount
            cx.execute("DELETE FROM pages WHERE doc_id=?", (doc_id,))
            cx.execute("DELETE FROM paragraphs WHERE doc_id=?", (doc_id,))
            cx.execute("DELETE FROM headings WHERE doc_id=?", (doc_id,))
            cx.execute("DELETE FROM doc_refs WHERE doc_id=?", (doc_id,))
            cx.execute("DELETE FROM bib_links WHERE doc_id=?", (doc_id,))  # 0.13: its work goes back to "to find"
            out["documents"] = cx.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,)).rowcount
            # 0.11.1: tasks not answered yet that still hold its passages (a check, a theme name, a concept link) are
            # relabelled now, so none of them is handed to Claude Code after the document is gone
            from .access import relabel

            relabel(cx)
            self.bump_corpus(cx)
        return out

    def counts(self) -> dict[str, int]:
        tables = ["documents", "passages", "embeddings", "vca_targets", "vca_refs", "doc_refs", "tasks", "results",
                  "hypotheses", "user_claims", "claims", "claim_targets", "evidence", "interactions", "vca_claims",
                  "verifications", "reviews", "labels", "terms", "term_mentions", "concept_links", "theme_runs",
                  "mentions"]
        return {t: int(self.scalar(f"SELECT COUNT(*) FROM {t}") or 0) for t in tables}
