"""Export a project in the Cross-Doc SDG Explorer's "FlexiConc" SQLite layout (F8), for anyone who still opens these
databases with FlexiConc tools.

    enlens --ws PROJECT export-flexiconc out.sqlite

Tables, as CrossDoc's `flexiconc_adapter` creates them:
- documents(doc_id, uri, created_at, text_length, full_text): every document with its full text;
- sentences(doc_id, sentence_id, start, end, text, label, confidence, consensus, token_analysis_json,
  span_analysis_json): the sentences of each document (`textutil.split_sentences`). `label` is the code of the
  label (F2) whose quote falls in the sentence: for the SDG codebooks the goal number, as CrossDoc stored it; the full
  code, its text, relevance, direction, quote and reason are in token_analysis_json; `consensus` says who labelled it
  ("model", "person", "keywords+meaning", "keywords", "meaning"). span_analysis_json holds the key terms (F6) in the
  sentence, in CrossDoc's span format (text, start_char, end_char, importance);
- chains(doc_id, chain_id, representative, mentions_json): the reference chains (F5);
- clusters(doc_id, cluster_id, members_json): the themes (F4) of the latest (or a chosen) run, per document: the
  sentences of the theme's passages in that document;
- embeddings(doc_id, sentence_id, model, dim, vector): each sentence gets the vector of the passage that holds it
  (float32 bytes);
- indices(doc_id, kind, payload): created empty. CrossDoc's tries and co-occurrence payloads are not exported,
  because nothing in ENLENS reads them.
"""
from __future__ import annotations

import bisect
import json
import sqlite3
from pathlib import Path

from .store import Workspace
from .textutil import split_sentences

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
    doc_id      TEXT PRIMARY KEY,
    uri         TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    text_length INTEGER,
    full_text   TEXT
);
CREATE TABLE IF NOT EXISTS sentences(
    doc_id TEXT,
    sentence_id INTEGER,
    start INTEGER,
    end   INTEGER,
    text  TEXT,
    label INTEGER,
    confidence REAL,
    consensus TEXT,
    token_analysis_json TEXT,
    span_analysis_json  TEXT,
    PRIMARY KEY(doc_id, sentence_id)
);
CREATE INDEX IF NOT EXISTS idx_sent_doc ON sentences(doc_id);
CREATE TABLE IF NOT EXISTS chains(
    doc_id TEXT,
    chain_id INTEGER,
    representative TEXT,
    mentions_json  TEXT,
    PRIMARY KEY(doc_id, chain_id)
);
CREATE TABLE IF NOT EXISTS clusters(
    doc_id TEXT,
    cluster_id INTEGER,
    members_json TEXT,
    PRIMARY KEY(doc_id, cluster_id)
);
CREATE TABLE IF NOT EXISTS embeddings(
    doc_id TEXT,
    sentence_id INTEGER,
    model TEXT,
    dim INTEGER,
    vector BLOB,
    PRIMARY KEY(doc_id, sentence_id, model)
);
CREATE TABLE IF NOT EXISTS indices(
    doc_id  TEXT,
    kind    TEXT,
    payload BLOB,
    PRIMARY KEY(doc_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_indices_kind ON indices(kind);
"""

_RANK = {"person": 0, "model": 1, "both": 2, "keywords": 3, "meaning": 4}
_CONSENSUS = {"person": "person", "model": "model", "both": "keywords+meaning", "keywords": "keywords",
              "meaning": "meaning"}


def _label_value(framework: str, code: str):
    if framework == "sdg":
        try:
            return int(code.split(".")[0])
        except ValueError:
            return None
    if framework == "sdg_goals":
        return int(code) if code.isdigit() else None
    return None


def export(ws: Workspace, out: str | Path, framework: str = "sdg", embed_model: str | None = None,
           theme_run: str | None = None, embeddings: bool = True) -> dict:
    """Write the project to `out` (a new SQLite file). Returns the counts written."""
    from . import frameworks, profile
    from .references import chains as doc_chains

    out = Path(out)
    if out.exists():
        raise ValueError(f"{out} exists already: choose a new file name.")
    fw = frameworks.get(framework, ws)
    labs = profile.effective(ws, framework)
    by_doc_labels: dict[str, list[dict]] = {}
    for r in labs:
        by_doc_labels.setdefault(r["doc_id"], []).append(r)
    passages: dict[str, list] = {}
    prange: dict[str, tuple[int, int]] = {}
    for r in ws.query("SELECT passage_id, doc_id, start, end FROM passages ORDER BY doc_id, start"):
        passages.setdefault(r["doc_id"], []).append(dict(r))
        prange[r["passage_id"]] = (r["start"] or 0, r["end"] or 0)
    run_id = theme_run
    if run_id is None:
        r = ws.query("SELECT run_id FROM theme_runs ORDER BY created_at DESC, rowid DESC LIMIT 1")
        run_id = r[0][0] if r else None
    theme_of: dict[str, tuple[int, float]] = {}
    names: dict[int, str] = {}
    if run_id:
        from .themes import view

        v = view(ws, run_id)
        names = {t["theme_id"]: t["name"] for t in v["themes"]}
        rk = ws.scalar("SELECT run_key FROM theme_runs WHERE run_id=?", (run_id,))
        from .themes import _edits, _final

        ed = _edits(ws, rk)
        for m in ws.query("SELECT passage_id, theme_id, similarity FROM theme_members WHERE run_id=?", (run_id,)):
            moved = ed["moves"].get(m["passage_id"])
            theme_of[m["passage_id"]] = (_final(ed["merges"], moved or m["theme_id"]), m["similarity"])
    vecs = None
    if embeddings:
        from . import embed

        model = embed_model or ws.scalar("SELECT model FROM embeddings GROUP BY model ORDER BY COUNT(*) DESC LIMIT 1")
        vecs = (model, embed.vectors(ws, model)) if model else None
        if vecs and vecs[1] is None:
            vecs = None
    terms_by_doc: dict[str, list] = {}
    from .terms import key_terms

    stats = {"documents": 0, "sentences": 0, "labelled_sentences": 0, "chains": 0, "clusters": 0, "embeddings": 0}
    cx = sqlite3.connect(out)
    try:
        cx.executescript(SCHEMA)
        for d in ws.query("SELECT doc_id, path, added_at, n_chars, text FROM documents ORDER BY doc_id"):
            doc_id, text = d["doc_id"], d["text"] or ""
            cx.execute("INSERT INTO documents VALUES (?,?,?,?,?)", (doc_id, d["path"], d["added_at"], len(text), text))
            stats["documents"] += 1
            sents = split_sentences(text)
            starts = [a for a, _b in sents]

            def sid_at(off: int) -> int:
                return max(0, bisect.bisect_right(starts, off) - 1)

            # labels: each labelled sentence gets the label of highest rank (person, model, then the passes)
            best: dict[int, dict] = {}
            for r in by_doc_labels.get(doc_id, []):
                if r["start"] is not None:
                    sid = sid_at(r["start"])
                else:  # a keyword label: the sentence of its passage with most of its matched words
                    matched = [w.lower() for w in json.loads(r["matched_json"] or "[]")]
                    p0, p1 = prange.get(r["passage_id"], (0, 0))
                    cands = [i for i, (a, _b) in enumerate(sents) if p0 <= a < p1]
                    if not cands or not matched:
                        continue
                    sid = max(cands, key=lambda i: (sum(w in text[sents[i][0]:sents[i][1]].lower() for w in matched), -i))
                cur = best.get(sid)
                if cur is None or (_RANK[r["source"]], -(r["confidence"] or 0)) < (_RANK[cur["source"]], -(cur["confidence"] or 0)):
                    best[sid] = r
            kt = terms_by_doc.get(doc_id)
            if kt is None:
                kt = {k["term_id"]: k["score"] for k in key_terms(ws, doc_id=doc_id, n=30)} if ws.scalar(
                    "SELECT 1 FROM terms LIMIT 1") else {}
            spans: dict[int, list] = {}
            if kt:
                q = ",".join("?" * len(kt))
                for m in ws.query(f"SELECT term_id, start, end FROM term_mentions WHERE doc_id=? AND term_id IN ({q})",
                                  (doc_id, *kt)):
                    spans.setdefault(sid_at(m["start"]), []).append(
                        {"text": text[m["start"]:m["end"]], "start_char": m["start"], "end_char": m["end"],
                         "importance": kt[m["term_id"]]})
            ps = passages.get(doc_id, [])
            pst = [p["start"] for p in ps]
            rows, erows = [], []
            for i, (a, b) in enumerate(sents):
                lb = best.get(i)
                tok = {}
                if lb:
                    tok = {"framework": fw.name, "code": lb["code"],
                           "description": fw.codes[lb["code"]].description if lb["code"] in fw.codes else "",
                           "relevance": lb["relevance"], "direction": lb["direction"], "quote": lb["quote"],
                           "reason": lb["reason"], "source": lb["source"]}
                    stats["labelled_sentences"] += 1
                rows.append((doc_id, i, a, b, text[a:b], _label_value(fw.name, lb["code"]) if lb else None,
                             lb["confidence"] if lb else None, _CONSENSUS.get(lb["source"]) if lb else None,
                             json.dumps(tok, ensure_ascii=False), json.dumps(spans.get(i, []), ensure_ascii=False)))
                if vecs:
                    j = bisect.bisect_right(pst, a) - 1
                    if 0 <= j < len(ps) and a < ps[j]["end"]:
                        pos = vecs[1].pos.get(ps[j]["passage_id"])
                        if pos is not None:
                            blob = _vec_bytes(vecs[1], pos)
                            erows.append((doc_id, i, vecs[0], len(blob) // 4, blob))
            cx.executemany("INSERT INTO sentences VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            cx.executemany("INSERT INTO embeddings VALUES (?,?,?,?,?)", erows)
            stats["sentences"] += len(rows)
            stats["embeddings"] += len(erows)
            for ch in doc_chains(ws, doc_id):
                ms = [{"text": m["text"], "start_char": m["start"], "end_char": m["end"],
                       "sentence_id": sid_at(m["start"]), "named": m["is_named"]} for m in ch["mentions"]]
                cx.execute("INSERT INTO chains VALUES (?,?,?,?)", (doc_id, ch["chain_id"], ch["name"],
                                                                   json.dumps(ms, ensure_ascii=False)))
                stats["chains"] += 1
            if theme_of:
                members: dict[int, list] = {}
                for p in ps:
                    t = theme_of.get(p["passage_id"])
                    if not t:
                        continue
                    for i, (a, b) in enumerate(sents):
                        if p["start"] <= a < p["end"]:
                            members.setdefault(t[0], []).append({"sentence_id": i, "text": text[a:b], "start": a, "end": b,
                                                                 "similarity": round(t[1], 4), "theme": names.get(t[0], "")})
                for tid, ms in sorted(members.items()):
                    cx.execute("INSERT INTO clusters VALUES (?,?,?)", (doc_id, tid, json.dumps(ms, ensure_ascii=False)))
                    stats["clusters"] += 1
        cx.commit()
    except BaseException:
        cx.close()
        out.unlink(missing_ok=True)
        raise
    cx.close()
    return {**stats, "file": str(out), "framework": fw.name, "theme_run": run_id,
            "embedding_model": vecs[0] if vecs else None}


def _vec_bytes(vs, pos: int) -> bytes:
    if vs.np is not None:
        return vs.matrix[pos].astype("float32").tobytes()
    return vs.rows[pos].tobytes()


def read_document(path: str | Path, doc_id: str) -> dict:
    """Read one document back the way CrossDoc's `load_production_from_flexiconc` does (for tests and checks)."""
    cx = sqlite3.connect(path)
    try:
        uri, full_text = cx.execute("SELECT uri, full_text FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        sents = [{"sentence_id": r[0], "doc_start": r[1], "doc_end": r[2], "sentence_text": r[3],
                  "classification": {"label": r[4], "confidence": r[5], "consensus": r[6]}
                  if r[4] is not None or r[5] is not None or r[6] is not None else {},
                  "token_analysis": json.loads(r[7]) if r[7] else {}, "span_analysis": json.loads(r[8]) if r[8] else []}
                 for r in cx.execute("SELECT sentence_id, start, end, text, label, confidence, consensus, "
                                     "token_analysis_json, span_analysis_json FROM sentences WHERE doc_id=? "
                                     "ORDER BY sentence_id", (doc_id,))]
        chains = [{"chain_id": r[0], "representative": r[1], "mentions": json.loads(r[2] or "[]")}
                  for r in cx.execute("SELECT chain_id, representative, mentions_json FROM chains WHERE doc_id=? "
                                      "ORDER BY chain_id", (doc_id,))]
        clusters = [json.loads(r[0] or "[]") for r in cx.execute("SELECT members_json FROM clusters WHERE doc_id=? "
                                                                 "ORDER BY cluster_id", (doc_id,))]
    finally:
        cx.close()
    return {"doc_id": doc_id, "uri": uri, "full_text": full_text, "sentence_analyses": sents,
            "coreference_analysis": {"chains": chains}, "cluster_analysis": {"clusters": clusters}}
