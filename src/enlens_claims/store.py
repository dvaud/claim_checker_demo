"""Workspace on disk: a folder with config.json and one SQLite database."""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

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
CREATE TABLE IF NOT EXISTS term_mentions(term_id TEXT, passage_id TEXT, doc_id TEXT, start INT, end INT);
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
"""

# Indexes on columns that older workspaces gain only through MIGRATIONS, so they are created afterwards.
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
CREATE INDEX IF NOT EXISTS ix_labels_passage ON labels(passage_id);
CREATE INDEX IF NOT EXISTS ix_labels_doc ON labels(framework, doc_id);
CREATE INDEX IF NOT EXISTS ix_labels_code ON labels(framework, code);
CREATE INDEX IF NOT EXISTS ix_term_mentions_term ON term_mentions(term_id);
CREATE INDEX IF NOT EXISTS ix_term_mentions_passage ON term_mentions(passage_id);
CREATE INDEX IF NOT EXISTS ix_term_mentions_doc ON term_mentions(doc_id, term_id);
CREATE INDEX IF NOT EXISTS ix_concept_terms_term ON concept_terms(term_id);
CREATE INDEX IF NOT EXISTS ix_theme_members_theme ON theme_members(run_id, theme_id);
CREATE INDEX IF NOT EXISTS ix_mentions_chain ON mentions(doc_id, chain_id);
CREATE INDEX IF NOT EXISTS ix_reviews_item ON reviews(item_kind, item_id);
CREATE INDEX IF NOT EXISTS ix_tasks_queued ON tasks(queued, kind, status);
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
              ("hypotheses", "queue", "TEXT"), ("user_claims", "stage", "TEXT")]


def _migrate(cx: sqlite3.Connection) -> None:
    """Add columns introduced after a workspace was created, and give checks from 0.4 a hypothesis record."""
    for table, col, typ in MIGRATIONS:
        cols = {r[1] for r in cx.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            cx.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    # a 0.4 claim check is a hypothesis with one part (the claim itself); its target was an SDG target
    cx.execute("INSERT OR IGNORE INTO hypotheses(hyp_id, text, framework, code, options_json, decomposed, rationale, model, "
               "created_at) SELECT claim_id, text, CASE WHEN COALESCE(target, '') != '' THEN 'sdg' END, NULLIF(target, ''), "
               "options_json, 0, rationale, model, created_at FROM user_claims WHERE hyp_id IS NULL")
    cx.execute("UPDATE user_claims SET hyp_id=claim_id, part=0, "
               "framework=CASE WHEN COALESCE(target, '') != '' THEN 'sdg' END WHERE hyp_id IS NULL")


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


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
            cx.executescript(SCHEMA)
            _migrate(cx)
            cx.executescript(INDEXES)
            cx.commit()
        finally:
            cx.close()

    def _conn(self) -> sqlite3.Connection:
        cx = getattr(self._local, "cx", None)
        if cx is None:
            cx = sqlite3.connect(self.db_path, timeout=60, isolation_level=None)  # transactions are ours, see connect()
            cx.row_factory = sqlite3.Row
            cx.execute("PRAGMA synchronous=NORMAL")  # safe with WAL; much faster commits
            self._local.cx, self._local.depth = cx, 0
        return cx

    def close(self) -> None:
        """Close this thread's connection (it is reopened on the next use)."""
        cx = getattr(self._local, "cx", None)
        if cx is not None:
            cx.close()
            self._local.cx = None

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
            for t in ("documents", "pages", "paragraphs", "headings", "passages", "embeddings", "doc_refs", "claims",
                      "claim_targets", "evidence", "interactions", "verifications", "labels", "terms", "term_mentions",
                      "concepts", "concept_terms", "theme_runs", "themes", "theme_members", "mentions"):
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

    def remove_document(self, doc_id: str) -> dict[str, int]:
        """Remove one document and what the pipeline derived from it.

        Hypothesis checks keep their grades: they are a record of what was read (each check stores the passage
        text and title it showed), so a past verdict does not change when a source is removed later.
        """
        out: dict[str, int] = {}
        with self.connect() as cx:
            if not cx.execute("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)).fetchone():
                raise KeyError(doc_id)
            pids = [r[0] for r in cx.execute("SELECT passage_id FROM passages WHERE doc_id=?", (doc_id,))]
            claim_ids = [r[0] for r in cx.execute("SELECT claim_id FROM claims WHERE doc_id=?", (doc_id,))]
            for cid in claim_ids:
                cx.execute("DELETE FROM claim_targets WHERE claim_id=?", (cid,))
                cx.execute("DELETE FROM evidence WHERE claim_id=?", (cid,))
            out["claims"] = cx.execute("DELETE FROM claims WHERE doc_id=?", (doc_id,)).rowcount
            out["interactions"] = cx.execute("DELETE FROM interactions WHERE doc_id=? AND kind='stated'", (doc_id,)).rowcount
            out["verifications"] = cx.execute("DELETE FROM verifications WHERE doc_id=? AND subject_kind != 'user_claim'",
                                              (doc_id,)).rowcount
            for pid in pids:
                cx.execute("DELETE FROM embeddings WHERE passage_id=?", (pid,))
                cx.execute("DELETE FROM results WHERE task_id=?", (f"extract:{pid}",))
                cx.execute("DELETE FROM tasks WHERE task_id=?", (f"extract:{pid}",))
                cx.execute("DELETE FROM theme_members WHERE passage_id=?", (pid,))
                # model labels of this passage: their tasks are 'label:<framework>:<passage_id>'
                tail = f":{pid}"   # compared exactly ('_' in an id is a wildcard for LIKE)
                for tbl in ("results", "tasks"):
                    cx.execute(f"DELETE FROM {tbl} WHERE kind='label' AND substr(task_id, -?) = ?", (len(tail), tail))
            # 0.7: what was derived from the document (the term index is rebuilt when the corpus version changes)
            out["labels"] = cx.execute("DELETE FROM labels WHERE doc_id=?", (doc_id,)).rowcount
            out["mentions"] = cx.execute("DELETE FROM mentions WHERE doc_id=?", (doc_id,)).rowcount
            cx.execute("DELETE FROM term_mentions WHERE doc_id=?", (doc_id,))
            head = f"resolve:{doc_id}:"
            for tbl in ("results", "tasks"):
                cx.execute(f"DELETE FROM {tbl} WHERE kind='resolve' AND substr(task_id, 1, ?) = ?", (len(head), head))
            out["passages"] = cx.execute("DELETE FROM passages WHERE doc_id=?", (doc_id,)).rowcount
            cx.execute("DELETE FROM pages WHERE doc_id=?", (doc_id,))
            cx.execute("DELETE FROM paragraphs WHERE doc_id=?", (doc_id,))
            cx.execute("DELETE FROM headings WHERE doc_id=?", (doc_id,))
            cx.execute("DELETE FROM doc_refs WHERE doc_id=?", (doc_id,))
            out["documents"] = cx.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,)).rowcount
            self.bump_corpus(cx)
        return out

    def counts(self) -> dict[str, int]:
        tables = ["documents", "passages", "embeddings", "vca_targets", "vca_refs", "doc_refs", "tasks", "results",
                  "hypotheses", "user_claims", "claims", "claim_targets", "evidence", "interactions", "vca_claims",
                  "verifications", "reviews", "labels", "terms", "term_mentions", "concept_links", "theme_runs",
                  "mentions"]
        return {t: int(self.scalar(f"SELECT COUNT(*) FROM {t}") or 0) for t in tables}
