"""What every part of the sync shares (0.18: split out of sync.py): the names of the tables and columns it treats
alike, how a document is named by its content (`text_fp`), and small helpers to read rows."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Any, Iterable

from ..store import Workspace

FORMAT = "enlens-project"
_TOKEN = re.compile(r"[A-Za-z0-9_\-]+")
DOC_ID = re.compile(r"[A-Za-z0-9_]{1,64}(-[0-9a-f]{6})?")  # a document id ("d1a2b3c4d5e", a copy "…-0f1e2d"): never a path
UNFINISHED = ("pending", "retry")
# a document's reading: its text is in `documents`, the rest in these tables (one row set per document)
READING_TABLES = ("pages", "paragraphs", "headings", "passages", "blocks", "doc_tables")
_TEXT_COLS = {"text"}  # never rewritten (documents', passages' and hypotheses' own words)
# the tables of a copy that are never merged: derived again from the documents, or about this copy only
LOCAL_ONLY = {"meta", "embeddings", "code_vectors", "terms", "term_mentions", "concepts", "concept_terms", "task_claims",
              "sync_log", "sqlite_sequence",
              "versions",  # 0.16: earlier versions of themes and checks are this copy's history (history.py)
              "sync_written", "sync_folder_read", "sync_folder_docs",  # 0.18: this copy's record of the shared folder
              "canon_seen",  # 0.18 L2: how far this copy has followed the owner's decisions (ownership.py)
              "sync_changes",  # what changed since the shared folder's last round (changes.py)
              # roles (DESIGN-roles §3.2): the owner records this copy follows, documents removed here by a colleague's
              # word (restorable for 30 days), rows relayed by a third person, the state last taken from whom, and rows
              # a file brought under this copy's own id
              "owner_pins", "removed_docs", "sync_via", "sync_from", "sync_refused",
              "concept_link_sentences",  # 0.18.1 (D2): made again with each copy's glossary, from its own readings
              # 0.18.1 (H4): answers this copy keeps so as not to ask again; raw AI answers with their quotes, also of
              # documents a colleague's setting may keep from them: never sent (each copy keeps its own)
              "ai_cache"}
# merged by their own rules (merge.py); every other table (the SDG pack's, an add-on's) is merged row by row, keeping yours
OWN_RULES = {"documents", "pages", "paragraphs", "headings", "passages", "blocks", "doc_tables", "labels", "mentions", "tasks", "results",
             "ai_sent", "hypotheses", "user_claims", "second_opinions", "judgements", "people", "theme_runs", "themes",
             "theme_members", "reviews", "concept_links", "bib_items", "bib_links", "sync_seen", "sync_copies",
             "sync_removed", "verifications",
             "research_log", "notes",  # 0.16: merged entry by entry and note by note (researchlog.merge, notes.merge)
             "shares",  # 0.18: what each person shares, by its owner's word (sharing.receive, share_merge.py)
             # 0.18 L2 (ownership.py, sync/owner_merge.py): who the owner is, proposals, decisions and the documents as
             # accepted; a person's Leave out / Restore no longer travels row by row (it is a proposal)
             "ownership", "proposals", "decisions", "canon", "block_choices",
             "roles"}  # roles (DESIGN-roles §3.1): the Owner's word on who is a Co-owner (ownership.py, owner_merge.py)
# the columns that hold ids of documents, passages, tasks, checks, runs (rewritten when an id changes in a merge)
ID_COLS = {"doc_id", "passage_id", "task_id", "claim_id", "subject_id", "ver_id", "hyp_id", "run_id", "item_id",
           "label_id", "window", "payload_json", "options_json", "parts_json", "key", "of_key", "origin_id"}



def _sha(*parts: Any) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p if isinstance(p, bytes) else str(p).encode("utf-8")))
        h.update(b"\0")
    return h.hexdigest()


def base_id(doc_id: str) -> str:
    """The document id of a file, without the mark of a sync-clash copy ("d1a2b3c4d5e-0f1e2d" -> "d1a2b3c4d5e")."""
    return doc_id.split("-", 1)[0]


def text_fp(text: str | None) -> str:
    """The fingerprint of a document's text (16 hex digits)."""
    return _sha(text or "")[:16]


def text_fps(db: sqlite3.Connection | Workspace, again: bool = False) -> dict[str, str]:
    """{doc_id: fingerprint of its text}, computed once per document and kept (`documents.text_fp`); `again` works
    every one out anew (a colleague's file: what it says about itself is not trusted)."""
    cx = db._conn() if isinstance(db, Workspace) else db
    out = {}
    missing = []
    for doc_id, fp in cx.execute("SELECT doc_id, text_fp FROM documents").fetchall():
        if fp and not again:
            out[doc_id] = fp
        else:
            missing.append(doc_id)
    for doc_id in missing:
        (text,) = cx.execute("SELECT text FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        out[doc_id] = text_fp(text)
        cx.execute("UPDATE documents SET text_fp=? WHERE doc_id=?", (out[doc_id], doc_id))
    return out


def _tokens(s: str, mp: dict[str, str]) -> str:
    return _TOKEN.sub(lambda m: mp.get(m.group(0), m.group(0)), s) if mp and s else s


def _rows(cx: sqlite3.Connection, sql: str, args: Iterable = ()) -> list[dict]:
    cur = cx.execute(sql, tuple(args))
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _cols(cx: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in cx.execute(f"PRAGMA table_info({table})")]


def _pk(cx: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in sorted(cx.execute(f"PRAGMA table_info({table})"), key=lambda r: r[5]) if r[5]]

