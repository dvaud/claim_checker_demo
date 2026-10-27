"""Model backends.

- AnthropicBackend calls the Claude API (needs ANTHROPIC_API_KEY and the `anthropic` package).
- OllamaBackend calls a model served by Ollama, so text never leaves the machine.
- LocalBackend calls any other OpenAI-compatible server (llama.cpp, LM Studio, vLLM).
- BaselineBackend is a keyword heuristic with the same output format. It runs offline, drives the tests,
  and gives a floor that any model has to beat on the gold set.
- The file queue (tasks export / tasks import) lets any outside worker answer tasks, including Claude in a chat.
"""
from __future__ import annotations

import json
import os
import re
from typing import Protocol

from .textutil import content_words, overlap, split_sentences


class Backend(Protocol):
    name: str

    def complete(self, kind: str, system: str, user: str, model: str, payload: dict) -> str: ...


class BackendError(RuntimeError):
    """A problem the user can fix (server not running, model missing, key wrong, context too small)."""


def estimate_tokens(text: str) -> int:
    """Rough upper estimate. English runs about 4 characters a token; PDF text and numbers need more tokens."""
    return int(len(text) / 3.0) + 1


class AnthropicBackend:
    """The Claude API. The system prompt is cached, so repeated tasks of one kind pay for it once."""

    name = "anthropic"

    def __init__(self, api_key: str | None = None, max_tokens: int = 8000, client=None, base_url: str | None = None,
                 timeout: float = 600):
        if client is None:
            try:
                import anthropic
            except ImportError as e:  # pragma: no cover - depends on the environment
                raise BackendError("Install the API extra: pip install 'enlens-claims[anthropic]'") from e
            key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise BackendError("No Claude API key. Enter one in Settings or set ANTHROPIC_API_KEY.")
            kw = {"api_key": key, "timeout": timeout}
            if base_url:
                kw["base_url"] = base_url
            client = anthropic.Anthropic(**kw)
        self.client = client
        self.max_tokens = max_tokens

    def complete(self, kind: str, system: str, user: str, model: str, payload: dict) -> str:
        try:
            msg = self.client.messages.create(
                model=model,
                max_tokens=self.max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:  # the SDK's error classes vary by version; keep the message
            raise BackendError(_anthropic_message(e, model)) from e
        return "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")

    def check(self, model: str | None = None) -> dict:
        """Cheap connection test: list models (no tokens used). Says whether `model` is available."""
        try:
            page = self.client.models.list(limit=100)
            ids = [m.id for m in getattr(page, "data", page)]
        except Exception as e:
            raise BackendError(_anthropic_message(e, model or "")) from e
        out = {"ok": True, "models": ids}
        if model:
            out["model_available"] = model in ids
        return out


def _anthropic_message(e: Exception, model: str) -> str:
    text = str(e)
    status = getattr(e, "status_code", None)
    if status == 401 or "authentication" in text.lower():
        return "The Claude API rejected the key. Check it in Settings."
    if status == 404 or "not_found" in text.lower():
        return f"The Claude API does not know the model {model!r}. Check the model name in Settings."
    if status == 429:
        return "The Claude API is rate-limiting this key. Wait a minute and try again."
    if "connect" in text.lower():
        return "Could not reach the Claude API. Check the internet connection."
    return f"Claude API error: {text[:300]}"


class OllamaBackend:
    """A model served by Ollama on this computer (or another one you trust), through Ollama's own API.

    - The context length is set on every request (`num_ctx`). Ollama otherwise uses a small default and cuts longer
      prompts without warning; the extraction prompt alone is about 10,000 tokens.
    - The answer is constrained to the task's JSON schema (`format`), so even small models return valid JSON.
      Every answer is still validated and quote-checked like any other.
    - One context length for all tasks: changing it between requests makes Ollama reload the model.
    """

    name = "ollama"

    def __init__(self, base_url: str | None = None, num_ctx: int = 16384, think: bool | None = None,
                 keep_alive: str = "15m", timeout: int = 1800, reserve: int = 2048, opener=None):
        url = (base_url or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url
        self.base_url = url[:-3] if url.endswith("/v1") else url
        self.num_ctx = int(num_ctx)
        self.think = think
        self.keep_alive = keep_alive
        self.timeout = timeout
        self.reserve = reserve
        self._caps: dict[str, list[str] | None] = {}
        if opener is None:
            from urllib.request import urlopen as opener  # noqa: N813
        self.opener = opener

    def _can_think(self, model: str) -> bool | None:
        """Whether the model reports the thinking capability (None when Ollama does not say)."""
        if model not in self._caps:
            try:
                self._caps[model] = self.model_info(model).get("capabilities") or None
            except BackendError:
                self._caps[model] = None
        caps = self._caps[model]
        return None if caps is None else "thinking" in caps

    # -- plumbing -------------------------------------------------------------------------------
    def _call(self, path: str, body: dict | None = None, timeout: int | None = None) -> dict:
        from urllib.error import HTTPError, URLError
        from urllib.request import Request

        data = json.dumps(body).encode() if body is not None else None
        req = Request(f"{self.base_url}{path}", data=data, method="POST" if body is not None else "GET",
                      headers={"Content-Type": "application/json"})
        try:
            with self.opener(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode() or "{}")
        except HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode()).get("error", "")
            except Exception:
                pass
            if e.code == 404 and body and body.get("model"):
                raise BackendError(f"Ollama has no model {body['model']!r}. Install it with: ollama pull {body['model']}") from e
            raise BackendError(f"Ollama returned an error ({e.code}): {detail or e.reason}") from e
        except (URLError, ConnectionError, TimeoutError) as e:
            reason = getattr(e, "reason", e)
            if "timed out" in str(reason).lower():
                raise BackendError(f"Ollama did not answer within {timeout or self.timeout} seconds. "
                                   "The model may be too large for this computer.") from e
            raise BackendError(f"Could not reach Ollama at {self.base_url}. Start the Ollama app, or run `ollama serve`.") from e

    # -- tasks ----------------------------------------------------------------------------------
    def complete(self, kind: str, system: str, user: str, model: str, payload: dict) -> str:
        from .schema import output_schema

        need = estimate_tokens(system) + estimate_tokens(user) + self.reserve
        if need > self.num_ctx:
            raise BackendError(f"This task needs about {need:,} tokens of context, but the context length is "
                               f"{self.num_ctx:,}. Raise it in Settings (16,384 covers every task).")
        body = {"model": model, "stream": False, "format": output_schema(kind), "keep_alive": self.keep_alive,
                "options": {"temperature": 0, "num_ctx": self.num_ctx},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.think is not None and self._can_think(model) is not False:
            body["think"] = self.think  # sent only to models that can think; others may reject the field
        data = self._call("/api/chat", body)
        evaluated = int(data.get("prompt_eval_count") or 0)
        if evaluated and evaluated >= self.num_ctx - 16:
            raise BackendError(f"Ollama filled the whole context ({evaluated:,} tokens), so the prompt was probably cut. "
                               "Raise the context length in Settings.")
        return (data.get("message") or {}).get("content", "")

    # -- information ----------------------------------------------------------------------------
    def version(self) -> str:
        return self._call("/api/version", timeout=10).get("version", "")

    def models(self) -> list[str]:
        return sorted(m.get("name") or m.get("model", "") for m in self._call("/api/tags", timeout=10).get("models", []))

    def _remote(self, model: str) -> bool:
        for m in self._call("/api/tags", timeout=10).get("models", []):
            if model in (m.get("name"), m.get("model")) and m.get("remote_host"):
                return True
        return False

    def model_info(self, model: str) -> dict:
        """Size, quantisation and the longest context the model was trained for, where Ollama reports them."""
        d = self._call("/api/show", {"model": model}, timeout=30)
        det = d.get("details") or {}
        trained = next((v for k, v in (d.get("model_info") or {}).items() if k.endswith(".context_length")), None)
        return {"parameters": det.get("parameter_size"), "quantization": det.get("quantization_level"),
                "family": det.get("family"), "trained_context": trained,
                "capabilities": d.get("capabilities") or []}

    def check(self, model: str | None = None) -> dict:
        out: dict = {"ok": True, "version": self.version(), "models": self.models()}
        if model:
            out["model_available"] = model in out["models"] or f"{model}:latest" in out["models"]
            if out["model_available"]:
                info = self.model_info(model)
                out["model"] = info
                if self._remote(model):
                    out["warning"] = (f"{model} runs on Ollama's cloud, not on this computer. Ollama's cloud does not "
                                      "support the JSON format this app needs, and the text leaves the computer. "
                                      "Choose a local model.")
                    return out
                if info.get("trained_context") and info["trained_context"] < self.num_ctx:
                    out["warning"] = (f"{model} was trained for {info['trained_context']:,} tokens of context, less than "
                                      f"the {self.num_ctx:,} set here; long prompts may be read poorly.")
        return out


class LocalBackend:
    """Any OpenAI-compatible chat endpoint (llama.cpp server, LM Studio, vLLM).

    The context length has to be set on the server: this endpoint has no way to pass it. For Ollama use
    OllamaBackend instead, which sets it on every request.
    """

    name = "local"

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: int = 600, opener=None):
        self.base_url = (base_url or os.environ.get("ENLENS_LOCAL_URL") or "http://localhost:8080/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("ENLENS_LOCAL_KEY", "local")
        self.timeout = timeout
        if opener is None:
            from urllib.request import urlopen as opener  # noqa: N813
        self.opener = opener

    def complete(self, kind: str, system: str, user: str, model: str, payload: dict) -> str:
        from urllib.request import Request

        body = json.dumps({"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
        req = Request(f"{self.base_url}/chat/completions", data=body, method="POST",
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
        with self.opener(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------------------------
# keyword baseline
# ---------------------------------------------------------------------------------------------
LEXICON: list[tuple[str, str]] = [
    (r"groundwater|fresh ?water|water (stress|scarcity|use|demand|consumption|withdrawal)|desalinat", "6.4"),
    (r"drinking water|sanitation", "6.1"),
    (r"\bjobs?\b|employment|unemploy|workforce|decent work|working conditions|labou?r", "8.5"),
    (r"economic growth|\bgdp\b", "8.1"),
    (r"poverty|\bpoor\b", "1.1"),
    (r"emission|decarboni[sz]|greenhouse|climate change|co2", "13.2"),
    (r"renewable", "7.2"),
    (r"energy access|access to (electricity|energy)|electrification", "7.1"),
    (r"energy efficiency", "7.3"),
    (r"fertili[sz]er|food|agricultur|farming|crop", "2.4"),
    (r"air pollution|health", "3.9"),
    (r"gender|women", "5.5"),
    (r"inequalit|disparit", "10.1"),
    (r"land use|land degradation|desertif", "15.3"),
    (r"biodiversity|habitat", "15.5"),
    (r"marine|ocean|brine", "14.1"),
    (r"infrastructure|pipeline|port\b|ports\b", "9.1"),
    (r"industriali[sz]|industrial", "9.2"),
    (r"innovation|research and development|r&d", "9.5"),
    (r"waste|recycl", "12.5"),
    (r"natural resources|raw material|critical mineral", "12.2"),
    (r"corruption|bribery", "16.5"),
    (r"conflict|violence|geopolitic", "16.1"),
    (r"technology transfer", "17.7"),
    (r"foreign (direct )?investment|financ", "17.3"),
    (r"\bexports?\b|\btrade\b", "17.11"),
]
NEG = re.compile(r"\b(increas\w* (the )?(water )?(stress|scarcity|risk|pressure|emission|cost|conflict|inequalit)|compet\w*|threat\w*|"
                 r"worsen\w*|risk\w*|displac\w*|harm\w*|pollut\w*|scarcit\w*|depend\w* on import|negative|hinder\w*|"
                 r"limit\w*|exacerbat\w*|undermin\w*|red flag)", re.I)
POS = re.compile(r"\b(reduc\w* (the )?(ghg |co2 |greenhouse gas )?emission|creat\w* (new )?jobs|improv\w*|opportunit\w*|"
                 r"benefit\w*|enhanc\w*|boost\w*|support\w*|enabl\w*|decarboni[sz]\w*|positive|green flag|access to)", re.I)
H2 = re.compile(r"hydrogen|\bh2\b|electroly|ammonia|fuel cell|e-?fuel", re.I)


def _segment(s: str) -> str:
    if re.search(r"pipeline|shipping|transport|storage|port\b|ports\b|carrier", s, re.I):
        return "transportation"
    if re.search(r"fuel cell|steel|fertili|industr|mobility|end[- ]use|vehicle|refiner", s, re.I):
        return "end_use"
    if re.search(r"electroly|production|plant|renewable electricity|water (use|demand|consumption)", s, re.I):
        return "production"
    return "whole_chain"


def _direction(s: str) -> str:
    n, p = bool(NEG.search(s)), bool(POS.search(s))
    if n and p:
        return "mixed"
    if n:
        return "negative"
    return "positive" if p else ""


def _horizon(s: str) -> str:
    if re.search(r"\b(2035|2040|2045|2050|2060|long[- ]term|medium[- ]term)\b", s, re.I):
        return "medium_long_term"
    if re.search(r"\b(2025|2030|short[- ]term|near[- ]term|currently|today)\b", s, re.I):
        return "short_term"
    return "not_stated"


class BaselineBackend:
    name = "baseline"

    def complete(self, kind: str, system: str, user: str, model: str, payload: dict) -> str:
        if kind == "extract":
            return json.dumps(self._extract(payload["text"]))
        if kind == "split":
            return json.dumps(self._split(payload["justification"]))
        if kind == "verify":
            return json.dumps(self._verify(payload["claim"], payload["text"]))
        if kind == "verify_set":
            ev = []
            for i, p in enumerate(payload["passages"], 1):
                v = self._verify(payload["claim"], p["text"])
                if v["verdict"] == "supports":
                    ev.append({"passage": i, "verdict": "supports", "confidence": v["confidence"], "quote": v["quote"]})
            return json.dumps({"evidence": ev, "rationale": "word overlap"})
        if kind == "check":
            ev = []
            for i, p in enumerate(payload["passages"], 1):
                v = self._verify(payload["claim"], p["text"], partial=0.2)
                if v["verdict"] != "not_enough_info":
                    ev.append({"passage": i, "verdict": v["verdict"], "confidence": v["confidence"], "quote": v["quote"]})
            return json.dumps({"evidence": ev, "rationale": "Offline demo: graded by word overlap, not by reading."})
        if kind == "expand":
            words = sorted(content_words(payload["claim"]))
            return json.dumps({"terms": words[:20] or [payload["claim"][:60]]})
        raise ValueError(kind)

    def check(self, model: str | None = None) -> dict:
        return {"ok": True, "models": ["baseline"], "model_available": True}

    def _extract(self, text: str) -> dict:
        claims = []
        for a, b in split_sentences(text):
            s = text[a:b]
            if not H2.search(s):
                continue
            d = _direction(s)
            if not d:
                continue
            tg = [code for pat, code in LEXICON if re.search(pat, s, re.I)]
            if not tg:
                continue
            claims.append({
                "claim": s[:300], "activity": "green hydrogen", "segment": _segment(s),
                "targets": [{"target": c, "direction": d, "influence": "unclear"} for c in dict.fromkeys(tg)][:3],
                "horizon": _horizon(s), "confidence": 0.5, "evidence": [{"field": "claim", "quote": s}],
            })
        return {"claims": claims, "interactions": []}

    def _split(self, text: str) -> dict:
        out = []
        for a, b in split_sentences(text):
            s = text[a:b]
            if len(s) < 15:
                continue
            out.append({"text": s, "quote": s, "segment": _segment(s), "direction": _direction(s) or "mixed",
                        "horizon": _horizon(s)})
        if not out:
            out = [{"text": text[:300] or "empty", "quote": text[:300], "direction": "mixed"}]
        return {"claims": out}

    def _verify(self, claim: str, passage: str, partial: float | None = None) -> dict:
        cw = content_words(claim)
        best, best_s = 0.0, None
        for a, b in split_sentences(passage):
            s = passage[a:b]
            ov = overlap(cw, content_words(s))
            if ov > best:
                best, best_s = ov, s
        if best >= 0.35 and best_s:
            return {"verdict": "supports", "confidence": round(min(0.95, best + 0.2), 2), "quote": best_s,
                    "rationale": "word overlap"}
        if partial is not None and best >= partial and best_s:
            return {"verdict": "partially_supports", "confidence": round(best + 0.2, 2), "quote": best_s,
                    "rationale": "some word overlap"}
        return {"verdict": "not_enough_info", "confidence": 0.6, "quote": None, "rationale": "low word overlap"}


def get_backend(name: str, **kw) -> Backend:
    if name == "anthropic":
        return AnthropicBackend(**kw)
    if name == "ollama":
        return OllamaBackend(**kw)
    if name == "local":
        return LocalBackend(**kw)
    if name == "baseline":
        return BaselineBackend()
    raise ValueError(f"unknown backend {name!r}; use 'anthropic', 'ollama', 'local' or 'baseline', or the file queue "
                     "(export-tasks / import-results)")
