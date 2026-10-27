"""Workspace on disk: a folder with config.json and one SQLite database."""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS user_claims(
  claim_id TEXT PRIMARY KEY, text TEXT, target TEXT, terms_json TEXT, rationale TEXT, options_json TEXT,
  model TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS documents(
  doc_id TEXT PRIMARY KEY, path TEXT, sha1 TEXT UNIQUE, title TEXT, doi TEXT, kind TEXT,
  n_pages INT, n_chars INT, text TEXT, added_at TEXT, declared_ref TEXT);
CREATE TABLE IF NOT EXISTS pages(doc_id TEXT, page INT, start INT, end INT, PRIMARY KEY(doc_id, page));
CREATE TABLE IF NOT EXISTS passages(
  passage_id TEXT PRIMARY KEY, doc_id TEXT, seq INT, page INT, start INT, end INT, text TEXT,
  section TEXT, screen_score REAL DEFAULT 0, screened INT DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_passages_doc ON passages(doc_id, seq);

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

CREATE TABLE IF NOT EXISTS reviews(
  review_id INTEGER PRIMARY KEY AUTOINCREMENT, item_kind TEXT, item_id TEXT, field TEXT,
  proposed TEXT, decision TEXT, corrected TEXT, reviewer TEXT, note TEXT, decided_at TEXT);
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


MIGRATIONS = [("documents", "declared_ref", "TEXT"), ("vca_refs", "alias_of", "TEXT"), ("vca_refs", "note", "TEXT")]


def _migrate(cx: sqlite3.Connection) -> None:
    """Add columns introduced after a workspace was created."""
    for table, col, typ in MIGRATIONS:
        cols = {r[1] for r in cx.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            cx.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.db_path = self.root / "enlens.sqlite"
        self.config_path = self.root / "config.json"

    # ---- lifecycle -------------------------------------------------------------------------
    @classmethod
    def create(cls, root: str | Path) -> "Workspace":
        ws = cls(root)
        ws.root.mkdir(parents=True, exist_ok=True)
        for sub in ("tasks", "results", "exports", "report"):
            (ws.root / sub).mkdir(exist_ok=True)
        if not ws.config_path.exists():
            ws.config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        with ws.connect() as cx:
            cx.executescript(SCHEMA)
        return ws

    @classmethod
    def open(cls, root: str | Path) -> "Workspace":
        ws = cls(root)
        if not ws.db_path.exists():
            raise FileNotFoundError(f"No workspace at {ws.root}. Run `enlens init {ws.root}` first.")
        with ws.connect() as cx:
            cx.executescript(SCHEMA)  # idempotent: adds tables introduced by newer versions
            _migrate(cx)
        return ws

    @property
    def config(self) -> dict[str, Any]:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        if self.config_path.exists():
            user = json.loads(self.config_path.read_text())
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        return cfg

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        cx = sqlite3.connect(self.db_path, timeout=60)
        cx.row_factory = sqlite3.Row
        cx.execute("PRAGMA journal_mode=WAL")  # readers do not block on a long write
        try:
            yield cx
            cx.commit()
        finally:
            cx.close()

    # ---- small helpers ---------------------------------------------------------------------
    def query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.connect() as cx:
            return list(cx.execute(sql, args))

    def scalar(self, sql: str, args: tuple = ()) -> Any:
        rows = self.query(sql, args)
        return rows[0][0] if rows else None

    def reset_corpus(self) -> dict[str, int]:
        """Remove documents and everything derived from them. The VCA and the split justifications stay."""
        out = {}
        with self.connect() as cx:
            for t in ("documents", "pages", "passages", "doc_refs", "claims", "claim_targets", "evidence",
                      "interactions", "verifications"):
                out[t] = cx.execute(f"DELETE FROM {t}").rowcount
            out["results"] = cx.execute("DELETE FROM results WHERE kind IN ('extract','verify','verify_set','expand','check')").rowcount
            out["tasks"] = cx.execute("DELETE FROM tasks WHERE kind IN ('extract','verify','verify_set','expand','check')").rowcount
            out["user_claims"] = cx.execute("DELETE FROM user_claims").rowcount
            out["reviews"] = cx.execute("DELETE FROM reviews WHERE item_kind='claim'").rowcount
        return out

    def counts(self) -> dict[str, int]:
        tables = ["documents", "passages", "vca_targets", "vca_refs", "doc_refs", "tasks", "results", "user_claims",
                  "claims", "claim_targets", "evidence", "interactions", "vca_claims", "verifications", "reviews"]
        return {t: int(self.scalar(f"SELECT COUNT(*) FROM {t}") or 0) for t in tables}
