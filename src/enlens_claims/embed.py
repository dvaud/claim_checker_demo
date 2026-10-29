"""Local embeddings for semantic search: a vector per passage, made by a model on this computer.

Embeddings are optional. When a project has them, a check ranks passages by keyword match (BM25) and by meaning
(cosine similarity of embeddings) and fuses the two rankings, so a source that says "repurposing" is found for a
claim that says "upgrading". Without them, search is keyword-only, as before.

Vectors are made by an embedding model served locally (Ollama: `ollama pull nomic-embed-text`; or any
OpenAI-compatible server such as LM Studio or llama.cpp), stored unit-length as float32 in the project's database
(table `embeddings`, one row per passage and model) and loaded once per corpus state. numpy is used when installed;
without it a pure-Python dot product is used (about half a second per query on 10,000 passages).
"""
from __future__ import annotations

import json
import math
import os
import threading
from array import array
from typing import Callable, Protocol, Sequence

from .llm import BackendError
from .store import Workspace

# Some embedding models are trained with a prefix that says whether a text is a query or a document.
_PREFIXES = [
    ("nomic-embed", "search_query: ", "search_document: "),
    ("mxbai-embed", "Represent this sentence for searching relevant passages: ", ""),
    ("snowflake-arctic-embed", "Represent this sentence for searching relevant passages: ", ""),
    ("e5", "query: ", "passage: "),
]


def prefixes(model: str) -> tuple[str, str]:
    m = model.lower()
    for key, q, d in _PREFIXES:
        if key in m:
            return q, d
    return "", ""


class Embedder(Protocol):
    model: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _post(opener, url: str, body: dict, timeout: float, headers: dict | None = None) -> dict:
    from urllib.error import HTTPError, URLError
    from urllib.request import Request

    req = Request(url, data=json.dumps(body).encode(), method="POST",
                  headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with opener(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "{}")
    except HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode()).get("error", "")
            if isinstance(detail, dict):
                detail = detail.get("message", "")
        except Exception:
            pass
        raise BackendError(f"The embedding server returned an error ({e.code}): {detail or e.reason}") from e
    except (URLError, ConnectionError, TimeoutError, OSError) as e:
        raise BackendError(f"Could not reach the embedding server at {url}.") from e


class OllamaEmbedder:
    """An embedding model in Ollama, for example nomic-embed-text, mxbai-embed-large or bge-m3 (multilingual)."""

    def __init__(self, model: str, base_url: str | None = None, timeout: float = 300, opener=None):
        url = (base_url or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url
        self.base_url = url[:-3] if url.endswith("/v1") else url
        self.model, self.timeout = model, timeout
        if opener is None:
            from urllib.request import urlopen as opener  # noqa: N813
        self.opener = opener

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            out = _post(self.opener, f"{self.base_url}/api/embed", {"model": self.model, "input": list(texts),
                                                                    "truncate": True}, self.timeout)
            vecs = out.get("embeddings") or []
        except BackendError as e:
            if "(404)" in str(e) and "model" in str(e).lower():
                raise BackendError(f"Ollama has no embedding model {self.model!r}. Install it with: "
                                   f"ollama pull {self.model}") from e
            raise
        if len(vecs) != len(texts):
            raise BackendError(f"{self.model} returned {len(vecs)} vectors for {len(texts)} texts.")
        return vecs


class OpenAIEmbedder:
    """An embedding model behind an OpenAI-compatible /v1/embeddings endpoint (LM Studio, llama.cpp, vLLM...)."""

    def __init__(self, model: str, base_url: str, api_key: str | None = None, timeout: float = 300, opener=None):
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
        self.model, self.timeout = model, timeout
        self.api_key = api_key or os.environ.get("ENLENS_LOCAL_KEY", "local")
        if opener is None:
            from urllib.request import urlopen as opener  # noqa: N813
        self.opener = opener

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        out = _post(self.opener, f"{self.base_url}/embeddings", {"model": self.model, "input": list(texts)},
                    self.timeout, {"Authorization": f"Bearer {self.api_key}"})
        data = sorted(out.get("data") or [], key=lambda d: d.get("index", 0))
        if len(data) != len(texts):
            raise BackendError(f"{self.model} returned {len(data)} vectors for {len(texts)} texts.")
        return [d["embedding"] for d in data]


def make_embedder(kind: str, model: str, base_url: str | None = None) -> Embedder:
    if not model:
        raise BackendError("Choose an embedding model first (for example: ollama pull nomic-embed-text).")
    if kind == "ollama":
        return OllamaEmbedder(model, base_url)
    if kind in ("openai", "local"):
        return OpenAIEmbedder(model, base_url or "http://localhost:1234/v1")
    raise BackendError(f"Unknown embedding server kind {kind!r}; use 'ollama' or 'openai'.")


# ---------------------------------------------------------------------------------------------
# vectors on disk and in memory
# ---------------------------------------------------------------------------------------------
def _unit(v: Sequence[float]) -> array:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return array("f", (x / n for x in v))


def status(ws: Workspace, model: str | None) -> dict:
    """How many readable passages have a vector from this model."""
    total = int(ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'") or 0)
    done = int(ws.scalar("SELECT COUNT(*) FROM embeddings e JOIN passages p ON p.passage_id=e.passage_id "
                         "WHERE e.model=? AND p.section='body'", (model or "",)) or 0) if model else 0
    models = [r[0] for r in ws.query("SELECT DISTINCT model FROM embeddings")]
    return {"model": model or "", "passages": total, "embedded": done, "complete": bool(model) and total > 0 and done >= total,
            "models": models}


def build(ws: Workspace, embedder: Embedder, batch: int = 32, progress: Callable[[int, int], None] | None = None,
          should_stop: Callable[[], bool] | None = None) -> dict:
    """Embed every readable passage that has no vector from this model yet. Safe to stop and resume."""
    todo = ws.query("SELECT p.passage_id, p.text, d.title FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
                    "WHERE p.section='body' AND p.passage_id NOT IN (SELECT passage_id FROM embeddings WHERE model=?) "
                    "ORDER BY p.passage_id", (embedder.model,))
    _q, dprefix = prefixes(embedder.model)
    done = 0
    for i in range(0, len(todo), batch):
        if should_stop and should_stop():
            break
        chunk = todo[i:i + batch]
        vecs = embedder.embed([dprefix + r["text"] for r in chunk])
        with ws.connect() as cx:
            cx.executemany("INSERT OR REPLACE INTO embeddings VALUES (?,?,?)",
                           [(embedder.model, r["passage_id"], _unit(v).tobytes()) for r, v in zip(chunk, vecs)])
        done += len(chunk)
        if progress:
            progress(done, len(todo))
    _VECTORS.pop((str(ws.db_path.resolve()), embedder.model), None)
    return {**status(ws, embedder.model), "added": done, "remaining": len(todo) - done}


class Vectors:
    """All vectors of one model in a project, as one matrix (numpy) or a list of float arrays."""

    def __init__(self, ids: list[str], blobs: list[bytes]):
        self.ids = ids
        self.pos = {pid: i for i, pid in enumerate(ids)}
        try:
            import numpy as np

            self.np = np
            self.matrix = (np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(len(ids), -1)
                           if ids else np.zeros((0, 0), dtype=np.float32))
            self.rows = None
        except ImportError:  # pure Python fallback
            self.np = None
            self.rows = [array("f", b) for b in blobs]

    def similarities(self, query: Sequence[float]) -> list[float]:
        q = _unit(query)
        if self.np is not None:
            if not self.ids:
                return []
            if self.matrix.shape[1] != len(q):
                raise BackendError("The query vector and the stored vectors have different sizes: the embedding model "
                                   "changed. Rebuild the semantic index.")
            return (self.matrix @ self.np.asarray(q, dtype=self.np.float32)).tolist()
        from operator import mul

        return [sum(map(mul, r, q)) for r in self.rows]


_VECTORS: dict[tuple, tuple[int, Vectors]] = {}
_VLOCK = threading.Lock()


def vectors(ws: Workspace, model: str) -> Vectors | None:
    """The project's vectors for this model (cached until the corpus or the vectors change), or None."""
    key = (str(ws.db_path.resolve()), model)
    stamp = hash((ws.corpus_version(), ws.scalar("SELECT COUNT(*) FROM embeddings WHERE model=?", (model,))))
    with _VLOCK:
        hit = _VECTORS.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    rows = ws.query("SELECT e.passage_id, e.vec FROM embeddings e JOIN passages p ON p.passage_id=e.passage_id "
                    "WHERE e.model=? AND p.section='body' ORDER BY e.passage_id", (model,))
    if not rows:
        return None
    vs = Vectors([r[0] for r in rows], [r[1] for r in rows])
    with _VLOCK:
        _VECTORS[key] = (stamp, vs)
        while len(_VECTORS) > 4:
            _VECTORS.pop(next(iter(_VECTORS)))
    return vs


def query_vector(embedder: Embedder, text: str) -> list[float]:
    qprefix, _d = prefixes(embedder.model)
    return embedder.embed([qprefix + text])[0]
