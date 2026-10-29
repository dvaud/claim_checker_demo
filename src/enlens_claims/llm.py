"""Model backends. Local first: Ollama and OpenAI-compatible local servers keep every text on this computer.

- OllamaBackend calls a model served by Ollama, so text never leaves the machine.
- LocalBackend calls any other OpenAI-compatible server (LM Studio, llama.cpp, Jan, vLLM), also local.
- detect_local() finds which of these servers are running and which models they offer.
- AnthropicBackend calls the Claude API (cloud: needs a key and the `anthropic` package; opt-in in the app).
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


class _BudgetReached(Exception):
    """A model reached its reasoning budget before starting its answer (handled inside OllamaBackend)."""

    def __init__(self, thinking: str):
        super().__init__("reasoning budget reached")
        self.thinking = thinking


JUDGING = frozenset({"check", "reread", "second"})   # the task kinds where reasoning can help: judging excerpts


def estimate_tokens(text: str) -> int:
    """Rough upper estimate. English runs about 4 characters a token; PDF text and numbers need more tokens."""
    return int(len(text) / 3.5) + 1


# Longest answer each task kind needs, in tokens. A reasoning model gets THINK_ALLOWANCE on top for its reasoning.
# Without a cap a model that loops (endless blank space in the JSON, or reasoning that never ends) runs until the
# context is full, which on a laptop takes longer than any timeout.
OUTPUT_CAP = {"expand": 400, "decompose": 800, "check": 1500, "verify_set": 1500, "verify": 600, "split": 1500,
              "extract": 3000, "reread": 600, "second": 1500, "label": 1500, "link": 700, "theme": 500, "resolve": 2500}
DEFAULT_SEED = 42   # sent with every request (0.7): with temperature 0 the same input gives the same answer
THINK_ALLOWANCE = 4096

# Context lengths "auto" chooses from. The model's working memory (the KV cache) grows with the context length:
# for qwen3:8b about 1.2 GB at 8,192 tokens and 2.4 GB at 16,384, so the smallest length that fits is used.
CONTEXT_TIERS = (8192, 12288, 16384, 32768)
CONTEXT_MARGIN = 512   # tokens kept free on top of the estimate (chat template, rounding)


def fit_context(tokens: int) -> int:
    """The smallest context length of CONTEXT_TIERS that holds `tokens` (the largest tier when none does)."""
    for n in CONTEXT_TIERS:
        if tokens + CONTEXT_MARGIN <= n:
            return n
    return CONTEXT_TIERS[-1]


def is_chat_model(name: str) -> bool:
    """False for embedding and reranking models, which cannot answer tasks."""
    return not re.search(r"embed|bge-|e5-|minilm|rerank", name or "", re.I)


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
                 keep_alive: str = "15m", timeout: int = 1800, reserve: int = 2048, opener=None,
                 stall_timeout: int = 600, think_kinds: frozenset | set | None = None, think_budget: int = 0,
                 seed: int | None = DEFAULT_SEED):
        url = (base_url or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url
        self.base_url = url[:-3] if url.endswith("/v1") else url
        self.num_ctx = int(num_ctx)
        self.think = think
        self.think_kinds = frozenset(think_kinds) if think_kinds is not None else None  # reason for these kinds only
        self.think_budget = int(think_budget or 0)  # reasoning tokens before the model is asked to answer (0: none)
        self.keep_alive = keep_alive
        self.timeout = timeout
        self.reserve = reserve
        self.stall_timeout = stall_timeout   # longest silence: loading the model and reading a long prompt included
        self.progress = None                 # optional callable(info) while an answer streams in
        self.should_stop = None              # optional callable() -> bool, checked every second: True stops the call
        self._caps: dict[str, list[str] | None] = {}
        self.seed = seed
        self._digests: dict[str, str] = {}
        if opener is None:
            from urllib.request import urlopen as opener  # noqa: N813
        self.opener = opener

    def digest(self, model: str) -> str | None:
        """The digest Ollama reports for the model (/api/tags): the exact weights, whatever the tag points to."""
        if model not in self._digests:
            try:
                for m in self._call("/api/tags", timeout=10).get("models", []):
                    name = m.get("name") or m.get("model")
                    if name and m.get("digest"):
                        self._digests[name] = m["digest"]
            except BackendError:
                return None
        return self._digests.get(model) or self._digests.get(f"{model}:latest")

    def _can_think(self, model: str) -> bool | None:
        """Whether the model reports the thinking capability (None when Ollama does not say)."""
        if model not in self._caps:
            try:
                self._caps[model] = self.model_info(model).get("capabilities") or None
            except BackendError:
                return None  # not cached: Ollama may just be starting
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
    def _think_for(self, kind: str) -> bool | None:
        """Reasoning for this task kind: on/off, or None for the model's default. With `think_kinds`, reasoning is on
        for those kinds only (judging excerpts) and off for the rest (splitting a hypothesis, search words)."""
        if self.think_kinds is not None:
            return kind in self.think_kinds
        return self.think

    def complete(self, kind: str, system: str, user: str, model: str, payload: dict) -> str:
        """Stream the answer, so a stuck model is noticed early and progress can be shown while it works.

        The answer is read in a background thread; this thread wakes every second to report progress (through
        `self.progress`, if set) and to enforce the limits. Stopping early closes the connection, which makes Ollama
        stop generating.

        With a reasoning budget (`think_budget` tokens), a model that is still reasoning when it reaches the budget
        is stopped and asked again, without reasoning, to answer at once; its reasoning so far goes along as notes.
        A task with reasoning then takes a bounded time, and the answer is not lost to the output cap.
        """
        import time

        from .schema import output_schema

        can_think = self._can_think(model)
        want = self._think_for(kind)
        thinks = want is True or (want is None and can_think is True)
        budget = int(self.think_budget or 0) if thinks else 0
        allowance = (budget + 64 if budget else THINK_ALLOWANCE) if thinks else 0
        answer_cap = OUTPUT_CAP.get(kind, 2000)
        cap = answer_cap + allowance
        prompt_tokens = estimate_tokens(system) + estimate_tokens(user)
        need = prompt_tokens + cap + budget  # a forced answer carries the reasoning so far as notes
        if need > self.num_ctx:
            hint = " or switch reasoning off" if thinks else ""
            raise BackendError(f"This task needs about {need:,} tokens of context, but the context length is "
                               f"{self.num_ctx:,}. Raise it in Settings{hint}.")
        body = {"model": model, "stream": True, "format": output_schema(kind), "keep_alive": self.keep_alive,
                "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": cap,
                            **({"seed": int(self.seed)} if self.seed is not None else {})},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if want is not None and can_think is not False:
            body["think"] = want  # sent only to models that can think; others may reject the field
        info = {"task": kind, "model": model, "phase": "waiting", "prompt_tokens": prompt_tokens, "thinking_tokens": 0,
                "answer_tokens": 0, "seconds": 0.0, "first_token_after": None, "rate": None, "tail": "", "cap": cap,
                "thinks": thinks, "budget": budget or None, "budget_reached": False}
        t0 = time.time()
        try:
            content, final = self._stream(body, model, info, t0, budget)
        except _BudgetReached as b:
            info["budget_reached"] = True
            info["phase"] = "writing"
            notes = b.thinking[-6 * budget:].strip()
            forced = {**body, "options": {**body["options"], "num_predict": answer_cap},
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user + "\n\nYOUR REASONING SO FAR (notes for yourself; "
                                    "quote only from the passages above, never from these notes):\n" + notes +
                                    "\n\nStop reasoning now and give your answer in the required format."}]}
            if can_think is not False:
                forced["think"] = False
            cap = answer_cap
            content, final = self._stream(forced, model, info, t0, 0)

        text = "".join(content)
        ns = 1e9
        stats = {"load_seconds": (final.get("load_duration") or 0) / ns,
                 "prompt_tokens": final.get("prompt_eval_count"), "prompt_seconds": (final.get("prompt_eval_duration") or 0) / ns,
                 "output_tokens": final.get("eval_count"), "output_seconds": (final.get("eval_duration") or 0) / ns,
                 "total_seconds": time.time() - t0, "thinking_tokens": info["thinking_tokens"],
                 "budget_reached": info["budget_reached"]}
        self.last_stats = stats
        info.update(phase="done", stats=stats)
        self._report(info, t0, force=True)
        evaluated = int(final.get("prompt_eval_count") or 0)
        if evaluated and evaluated >= self.num_ctx - 16:
            raise BackendError(f"Ollama filled the whole context ({evaluated:,} tokens), so the prompt was probably cut. "
                               "Raise the context length in Settings.")
        if final.get("done_reason") == "length":
            if not text.strip():
                raise BackendError(f"{model} used its whole allowance of {cap:,} tokens on reasoning without answering. "
                                   "Give reasoning a budget, or switch it off, in Settings, or choose another model.")
            raise BackendError(f"{model}'s answer was cut off at {cap:,} tokens, far longer than this task needs; the "
                               "model is probably repeating itself. Try again or choose another model.")
        return text

    def _report(self, info: dict, t0: float, force: bool = False) -> None:
        import time

        if not force and time.time() - info.get("_last_report", 0.0) < 1.0:
            return
        info["_last_report"] = time.time()
        info["seconds"] = time.time() - t0
        made = info["thinking_tokens"] + info["answer_tokens"]
        if made and info["first_token_after"] is not None:
            spent = info["seconds"] - info["first_token_after"]
            info["rate"] = made / spent if spent > 0.5 else None
        if self.progress:
            try:
                self.progress({k: v for k, v in info.items() if not k.startswith("_")})
            except Exception:
                pass  # a display problem must never stop the model

    def _stream(self, body: dict, model: str, info: dict, t0: float, budget: int) -> tuple[list[str], dict]:
        """One streamed request: the answer's pieces and Ollama's final chunk. Raises _BudgetReached when the model
        has reasoned for `budget` tokens without starting its answer."""
        import queue
        import threading
        import time
        from urllib.error import HTTPError
        from urllib.request import Request

        req = Request(f"{self.base_url}/api/chat", data=json.dumps(body).encode(), method="POST",
                      headers={"Content-Type": "application/json"})
        q: queue.Queue = queue.Queue()
        held: dict = {}

        def reader():
            try:
                with self.opener(req, timeout=self.stall_timeout) as resp:
                    held["resp"] = resp
                    for line in resp:
                        q.put(("line", line))
                q.put(("end", None))
            except Exception as e:  # handed to the waiting thread, which turns it into a readable message
                q.put(("error", e))

        def stop():
            try:
                if held.get("resp") is not None:
                    held["resp"].close()
            except Exception:
                pass

        slow = (f"{model} was still answering after {self.timeout} seconds. It is too slow on this computer for this "
                "task: give reasoning a budget or switch it off in Settings, or choose a smaller model.")
        content: list[str] = []
        thinking: list[str] = []
        thought = 0
        final: dict = {}
        last = time.time()
        threading.Thread(target=reader, daemon=True).start()
        try:
            while True:
                if self.should_stop and self.should_stop():
                    raise BackendError("Stopped.")
                try:
                    what, val = q.get(timeout=1.0)
                except queue.Empty:
                    self._report(info, t0)
                    if time.time() - last > self.stall_timeout:
                        said = "before starting its answer" if info["phase"] == "waiting" else "in the middle of its answer"
                        raise BackendError(f"{model} sent nothing for {self.stall_timeout} seconds {said}. The computer may "
                                           "be short of memory (check Activity Monitor), or the model is too large for it.")
                    if time.time() - t0 > self.timeout:
                        raise BackendError(slow)
                    continue
                if what == "error":
                    raise val
                if what == "end":
                    break
                last = time.time()
                if not val.strip():
                    continue
                chunk = json.loads(val)
                if chunk.get("error"):
                    raise BackendError(f"Ollama stopped with an error: {chunk['error']}")
                if info["first_token_after"] is None:
                    info["first_token_after"] = time.time() - t0
                msg = chunk.get("message") or {}
                if msg.get("thinking"):
                    info["thinking_tokens"] += 1
                    thought += 1
                    info["phase"] = "thinking"
                    thinking.append(msg["thinking"])
                    info["tail"] = "".join(thinking[-80:])[-400:]
                    if budget and thought >= budget and not content:
                        raise _BudgetReached("".join(thinking))
                if msg.get("content"):
                    content.append(msg["content"])
                    info["answer_tokens"] += 1
                    info["phase"] = "writing"
                    info["tail"] = "".join(content)[-400:]
                if info["answer_tokens"] > 50 and len("".join(content[-60:]).strip()) == 0:
                    raise BackendError(f"{model} got stuck writing blank space instead of an answer (a known problem of "
                                       "some models with fixed-format answers). Try again, switch reasoning off, or "
                                       "choose another model.")
                if time.time() - t0 > self.timeout:
                    raise BackendError(slow)
                self._report(info, t0)
                if chunk.get("done"):
                    final = chunk
                    break
        except HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode()).get("error", "")
            except Exception:
                pass
            if e.code == 404:
                raise BackendError(f"Ollama has no model {model!r}. Install it with: ollama pull {model}") from e
            raise BackendError(f"Ollama returned an error ({e.code}): {detail or e.reason}") from e
        except (BackendError, _BudgetReached):
            raise
        except (TimeoutError, OSError) as e:
            if "timed out" in str(e).lower() or isinstance(e, TimeoutError):
                said = "before starting its answer" if info["phase"] == "waiting" else "in the middle of its answer"
                raise BackendError(f"{model} sent nothing for {self.stall_timeout} seconds {said}. The computer may be "
                                   "short of memory (check Activity Monitor), or the model is too large for it.") from e
            raise BackendError(f"Could not reach Ollama at {self.base_url}. Start the Ollama app, or run `ollama serve`.") from e
        finally:
            stop()
        return content, final

    # -- information ----------------------------------------------------------------------------
    def version(self) -> str:
        return self._call("/api/version", timeout=10).get("version", "")

    def models(self) -> list[str]:
        return sorted(m.get("name") or m.get("model", "") for m in self._call("/api/tags", timeout=10).get("models", []))

    def loaded(self, timeout: float = 10) -> list[str]:
        """Models Ollama holds in memory right now (`/api/ps`), most recently used first."""
        rows = self._call("/api/ps", timeout=timeout).get("models", []) or []
        rows = sorted(rows, key=lambda m: str(m.get("expires_at") or ""), reverse=True)
        return [m.get("name") or m.get("model", "") for m in rows if m.get("name") or m.get("model")]

    def inventory(self, timeout: float = 10) -> dict:
        """The models this server offers (`models`), the ones in memory now (`loaded`) and when each was pulled
        (`modified`, ISO times), for choosing a default model without loading anything extra."""
        tags = [m for m in self._call("/api/tags", timeout=timeout).get("models", []) if not m.get("remote_host")]
        names = sorted(m.get("name") or m.get("model", "") for m in tags)
        try:
            loaded = self.loaded(timeout)
        except BackendError:
            loaded = []
        return {"models": names, "loaded": [m for m in loaded if m in names],
                "modified": {(m.get("name") or m.get("model", "")): str(m.get("modified_at") or "") for m in tags}}

    def unload(self, model: str) -> bool:
        """Free the memory a model holds (Ollama unloads it at once with keep_alive 0). False if Ollama refused."""
        try:
            self._call("/api/generate", {"model": model, "keep_alive": 0}, timeout=60)
            return True
        except BackendError:
            return False

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
    """Any OpenAI-compatible chat endpoint on this computer: LM Studio, llama.cpp's server, Jan, vLLM, LocalAI.

    - The answer is constrained to the task's JSON schema (`response_format` json_schema). Servers that do not
      accept that get json_object, then no format; the first that works is remembered.
    - The answer is streamed, so progress can be shown, a stuck model is noticed and a check can be stopped.
      Servers that ignore `stream` and send one JSON body work too.
    - The context length has to be set on the server: this endpoint has no way to pass it. For Ollama use
      OllamaBackend instead, which sets it on every request.
    """

    name = "local"
    FORMATS = ("json_schema", "json_object", "none")

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: int = 1800, opener=None,
                 stall_timeout: int = 600, stream: bool = True, seed: int | None = DEFAULT_SEED):
        url = (base_url or os.environ.get("ENLENS_LOCAL_URL") or "http://localhost:8080/v1").rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url
        self.base_url = url if url.endswith("/v1") else url + "/v1"
        self.api_key = api_key or os.environ.get("ENLENS_LOCAL_KEY", "local")
        self.timeout = timeout
        self.stall_timeout = stall_timeout
        self.stream = stream
        self.progress = None      # optional callable(info) while an answer streams in
        self.should_stop = None   # optional callable() -> bool
        self._format = "json_schema"
        self.seed = seed
        if opener is None:
            from urllib.request import urlopen as opener  # noqa: N813
        self.opener = opener

    def _request(self, path: str, body: dict | None = None):
        from urllib.request import Request

        return Request(f"{self.base_url}{path}", data=json.dumps(body).encode() if body is not None else None,
                       method="POST" if body is not None else "GET",
                       headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})

    def _error(self, e: Exception, model: str = "") -> BackendError:
        from urllib.error import HTTPError

        if isinstance(e, BackendError):
            return e
        if isinstance(e, HTTPError):
            detail = ""
            try:
                d = json.loads(e.read().decode())
                detail = d.get("error", "") if isinstance(d, dict) else ""
                if isinstance(detail, dict):
                    detail = detail.get("message", "")
            except Exception:
                pass
            if e.code == 404 and model and ("model" in str(detail).lower() or not detail):
                return BackendError(f"The local server at {self.base_url} has no model {model!r}. Load it first "
                                    "(in LM Studio: load the model; with llama.cpp: start the server with it).")
            if e.code in (401, 403):
                return BackendError(f"The local server at {self.base_url} refused the request ({e.code}). "
                                    "Set its API key in ENLENS_LOCAL_KEY.")
            return BackendError(f"The local server returned an error ({e.code}): {str(detail)[:300] or e.reason}")
        if "timed out" in str(e).lower() or isinstance(e, TimeoutError):
            return BackendError(f"{model or 'The model'} sent nothing for {self.stall_timeout} seconds. The computer may be "
                                "short of memory, or the model is too large for it.")
        return BackendError(f"Could not reach the local server at {self.base_url}. Start it (LM Studio: Developer > "
                            "Start server; llama.cpp: llama-server), or check the address in Settings.")

    def complete(self, kind: str, system: str, user: str, model: str, payload: dict) -> str:
        from urllib.error import HTTPError

        from .schema import output_schema

        cap = OUTPUT_CAP.get(kind, 2000) + THINK_ALLOWANCE
        base = {"model": model, "temperature": 0, "max_tokens": cap, "stream": self.stream,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.seed is not None:  # llama.cpp, vLLM and LM Studio take a seed; a server that does not ignores it
            base["seed"] = int(self.seed)
        order = list(self.FORMATS[self.FORMATS.index(self._format):])
        last: Exception | None = None
        for fmt in order:
            body = dict(base)
            if fmt == "json_schema":
                body["response_format"] = {"type": "json_schema",
                                           "json_schema": {"name": kind, "schema": output_schema(kind), "strict": False}}
            elif fmt == "json_object":
                body["response_format"] = {"type": "json_object"}
            try:
                text = self._run(kind, model, body, estimate_tokens(system) + estimate_tokens(user), cap)
                self._format = fmt
                return text
            except HTTPError as e:
                last = e
                try:
                    detail = e.read().decode()
                except Exception:
                    detail = ""
                e.read = lambda d=detail.encode(): d  # keep the body readable for _error
                if e.code in (400, 422, 500) and ("response_format" in detail or "json" in detail.lower()
                                                  or "schema" in detail.lower() or "grammar" in detail.lower()):
                    continue  # this server does not take this answer format: try the next one
                raise self._error(e, model) from e
            except Exception as e:
                raise self._error(e, model) from e
        raise self._error(last or RuntimeError("no answer"), model)

    def _run(self, kind: str, model: str, body: dict, prompt_tokens: int, cap: int) -> str:
        import queue
        import threading
        import time

        req = self._request("/chat/completions", body)
        q: queue.Queue = queue.Queue()
        held: dict = {}

        def reader():
            try:
                with self.opener(req, timeout=self.stall_timeout) as resp:
                    held["resp"] = resp
                    if hasattr(resp, "__iter__") and not hasattr(resp, "_fake_whole"):
                        for line in resp:
                            q.put(("line", line))
                    else:
                        q.put(("line", resp.read()))
                q.put(("end", None))
            except Exception as e:
                q.put(("error", e))

        info = {"task": kind, "model": model, "phase": "waiting", "prompt_tokens": prompt_tokens, "thinking_tokens": 0,
                "answer_tokens": 0, "seconds": 0.0, "first_token_after": None, "rate": None, "tail": "", "cap": cap,
                "thinks": False}
        content: list[str] = []
        whole: list[bytes] = []
        finish = None
        t0 = last = time.time()
        last_report = [0.0]

        def report(force: bool = False):
            if not self.progress or (not force and time.time() - last_report[0] < 1.0):
                return
            last_report[0] = time.time()
            info["seconds"] = time.time() - t0
            made = info["thinking_tokens"] + info["answer_tokens"]
            if made and info["first_token_after"] is not None:
                spent = info["seconds"] - info["first_token_after"]
                info["rate"] = made / spent if spent > 0.5 else None
            try:
                self.progress(dict(info))
            except Exception:
                pass

        threading.Thread(target=reader, daemon=True).start()
        try:
            while True:
                if self.should_stop and self.should_stop():
                    raise BackendError("Stopped.")
                try:
                    what, val = q.get(timeout=1.0)
                except queue.Empty:
                    report()
                    if time.time() - last > self.stall_timeout:
                        raise BackendError(f"{model} sent nothing for {self.stall_timeout} seconds.")
                    if time.time() - t0 > self.timeout:
                        raise BackendError(f"{model} was still answering after {self.timeout} seconds. It is too slow "
                                           "on this computer for this task: choose a smaller model.")
                    continue
                if what == "error":
                    raise val
                if what == "end":
                    break
                last = time.time()
                line = val.decode("utf-8", errors="replace") if isinstance(val, bytes) else str(val)
                stripped = line.strip()
                if not stripped.startswith("data:"):
                    whole.append(val if isinstance(val, bytes) else line.encode())
                    continue
                data = stripped[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    err = chunk["error"]
                    raise BackendError(f"The local server stopped with an error: {err.get('message') if isinstance(err, dict) else err}")
                ch = (chunk.get("choices") or [{}])[0]
                delta = ch.get("delta") or {}
                if info["first_token_after"] is None and (delta.get("content") or delta.get("reasoning_content")
                                                          or delta.get("reasoning")):
                    info["first_token_after"] = time.time() - t0
                if delta.get("reasoning_content") or delta.get("reasoning"):
                    info["thinking_tokens"] += 1
                    info["phase"] = "thinking"
                    info["thinks"] = True
                if delta.get("content"):
                    content.append(delta["content"])
                    info["answer_tokens"] += 1
                    info["phase"] = "writing"
                    info["tail"] = "".join(content[-60:])[-400:]
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
                if info["answer_tokens"] > 50 and len("".join(content[-60:]).strip()) == 0:
                    raise BackendError(f"{model} got stuck writing blank space instead of an answer. Try again or "
                                       "choose another model.")
                report()
        finally:
            try:
                if held.get("resp") is not None:
                    held["resp"].close()
            except Exception:
                pass
        if whole and not content:  # the server ignored "stream" and sent one JSON body
            try:
                data = json.loads(b"".join(whole).decode("utf-8", errors="replace"))
            except json.JSONDecodeError as e:
                raise BackendError("The local server sent an answer that is not JSON.") from e
            if isinstance(data, dict) and data.get("error"):
                err = data["error"]
                raise BackendError(f"The local server returned an error: {err.get('message') if isinstance(err, dict) else err}")
            ch = (data.get("choices") or [{}])[0]
            content = [((ch.get("message") or {}).get("content") or "")]
            finish = ch.get("finish_reason")
        info.update(phase="done", stats={"total_seconds": time.time() - t0, "output_tokens": info["answer_tokens"]})
        report(force=True)
        text = "".join(content)
        if finish == "length":
            raise BackendError(f"{model}'s answer was cut off at {cap:,} tokens; the model is probably repeating "
                               "itself or reasoning at length. Try again or choose another model.")
        return text

    # -- information ----------------------------------------------------------------------------
    def models(self) -> list[str]:
        try:
            with self.opener(self._request("/models"), timeout=10) as resp:
                data = json.loads(resp.read().decode() or "{}")
        except Exception as e:
            raise self._error(e) from e
        return sorted(str(m.get("id")) for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id"))

    def loaded(self, timeout: float = 3) -> list[str]:
        """Models the server holds in memory now. Only LM Studio says so (its `/api/v0/models`, `state: loaded`);
        for other servers this is empty."""
        from urllib.request import Request

        root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        try:
            req = Request(f"{root}/api/v0/models", method="GET", headers={"Authorization": f"Bearer {self.api_key}"})
            with self.opener(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode() or "{}")
        except Exception:
            return []
        return [str(m["id"]) for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")
                and m.get("state") == "loaded" and m.get("type", "llm") in ("llm", "vlm")]

    def inventory(self, timeout: float = 10) -> dict:
        return {"models": self.models(), "loaded": self.loaded(min(timeout, 3)), "modified": {}}

    def digest(self, model: str) -> str | None:
        """OpenAI-compatible servers report no digest: the model file the server lists (LM Studio's path) or the
        model's name is recorded instead."""
        from urllib.request import Request

        root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        try:
            req = Request(f"{root}/api/v0/models/{model}", method="GET", headers={"Authorization": f"Bearer {self.api_key}"})
            with self.opener(req, timeout=3) as resp:
                data = json.loads(resp.read().decode() or "{}")
            path = data.get("path") or data.get("id")
            if path:
                return f"file:{path}"
        except Exception:
            pass
        return f"name:{model}"

    def unload(self, model: str) -> bool:
        """OpenAI-compatible servers have no standard way to unload a model (LM Studio unloads idle models itself,
        after its own time-to-live): nothing is done."""
        return False

    def check(self, model: str | None = None) -> dict:
        out: dict = {"ok": True, "url": self.base_url, "models": self.models()}
        if model:
            out["model_available"] = model in out["models"]
        return out


# ---------------------------------------------------------------------------------------------
# finding local servers
# ---------------------------------------------------------------------------------------------
# Default addresses of local model servers: LM Studio, llama.cpp, Jan, vLLM, KoboldCpp.
OPENAI_PORTS = ("http://localhost:1234/v1", "http://localhost:8080/v1", "http://localhost:1337/v1",
                "http://localhost:8000/v1", "http://localhost:5001/v1")
_DETECTED: dict = {}


def detect_local(ollama_url: str | None = None, extra: list[str] | None = None, timeout: float = 0.6,
                 cache_seconds: float = 10.0) -> list[dict]:
    """Local model servers that answer right now, with their models: [{"kind", "url", "models", "version"?}].

    Probes Ollama and the usual ports of OpenAI-compatible servers in parallel; only this computer is asked
    (plus any address given). Results are cached for a few seconds.
    """
    import threading
    import time

    ollama = (ollama_url or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    if not ollama.startswith("http"):
        ollama = "http://" + ollama
    cands = [u.rstrip("/") for u in [*(extra or []), *OPENAI_PORTS] if u]
    cands = list(dict.fromkeys(u if u.endswith("/v1") else u + "/v1" for u in cands))
    key = (ollama, tuple(cands))
    hit = _DETECTED.get(key)
    if hit and time.time() - hit[0] < cache_seconds:
        return [dict(x) for x in hit[1]]
    found: dict[int, dict] = {}

    def probe_ollama():
        try:
            be = OllamaBackend(base_url=ollama, timeout=timeout)
            version = be._call("/api/version", timeout=timeout).get("version", "")
            inv = be.inventory(timeout=max(timeout, 2))
            found[0] = {"kind": "ollama", "url": be.base_url, "version": version, **inv}
        except Exception:
            pass

    def probe_openai(i: int, url: str):
        if url.rstrip("/").removesuffix("/v1") == ollama.removesuffix("/v1"):
            return  # Ollama's own OpenAI endpoint: already listed as Ollama
        try:
            lb = LocalBackend(base_url=url, timeout=2)
            models = lb._probe(timeout)
            found[i] = {"kind": "openai", "url": url, "models": models, "loaded": lb.loaded(timeout), "modified": {}}
        except Exception:
            pass

    threads = [threading.Thread(target=probe_ollama, daemon=True)]
    threads += [threading.Thread(target=probe_openai, args=(i + 1, u), daemon=True) for i, u in enumerate(cands)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout + 2.5)
    out = [found[i] for i in sorted(found)]
    _DETECTED[key] = (time.time(), out)
    return [dict(x) for x in out]


def _probe(self: LocalBackend, timeout: float) -> list[str]:
    with self.opener(self._request("/models"), timeout=timeout) as resp:
        data = json.loads(resp.read().decode() or "{}")
    return sorted(str(m.get("id")) for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id"))


LocalBackend._probe = _probe  # type: ignore[attr-defined]
OpenAICompatibleBackend = LocalBackend


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
        if kind in ("check", "reread", "second"):
            ev = []
            for i, p in enumerate(payload["passages"], 1):
                v = self._verify(payload["claim"], p["text"], partial=0.2)
                if v["verdict"] != "not_enough_info":
                    ev.append({"passage": i, "verdict": v["verdict"], "confidence": v["confidence"], "quote": v["quote"]})
            return json.dumps({"evidence": ev, "rationale": "Offline demo: graded by word overlap, not by reading."})
        if kind == "expand":
            words = sorted(content_words(payload["claim"]))
            return json.dumps({"terms": words[:20] or [payload["claim"][:60]]})
        if kind == "decompose":
            return json.dumps(self._decompose(payload["hypothesis"]))
        if kind == "label":
            return json.dumps(self._label(payload))
        if kind == "link":
            return json.dumps(self._link(payload))
        if kind == "theme":
            return json.dumps(self._theme(payload))
        if kind == "resolve":
            return json.dumps({"chains": []})  # the demo finds no references (it cannot read)
        raise ValueError(kind)

    def _label(self, payload: dict) -> dict:
        """The candidate codes whose description shares the most words with a sentence of the passage."""
        text = payload["text"]
        out = []
        for c in payload.get("candidates") or []:
            cw = content_words(c["description"])
            best, best_s = 0.0, None
            for a, b in split_sentences(text):
                ov = overlap(cw, content_words(text[a:b]))
                if ov > best:
                    best, best_s = ov, text[a:b]
            if best >= 0.15 and best_s:
                out.append({"code": c["code"], "relevance": "main" if best >= 0.3 else "mentioned",
                            "direction": "not_stated", "confidence": round(min(0.9, 0.4 + best), 2), "quote": best_s,
                            "reason": "Offline demo: shares words with the code's text."})
        return {"labels": out, "note": "Offline demo: labelled by word overlap, not by reading."}

    def _link(self, payload: dict) -> dict:
        t = payload["terms"]
        a, b = t[0], t[1]
        sa = set(a["label"].lower().split()) & set(b["label"].lower().split())
        qa = " ".join(a["snippets"][0]["text"].split()[:8]) if a["snippets"] else a["label"]
        qb = " ".join(b["snippets"][0]["text"].split()[:8]) if b["snippets"] else b["label"]
        return {"relations": [{"a": 1, "b": 2, "relation": "related" if sa else "different", "confidence": 0.5,
                               "quote_a": qa, "quote_b": qb}]}

    def _theme(self, payload: dict) -> dict:
        terms = payload.get("terms") or ["theme"]
        p = payload["passages"]
        q1 = " ".join(p[0]["text"].split()[:8])
        q2 = " ".join(p[-1]["text"].split()[:8])
        name = " and ".join(terms[:2]) if len(" and ".join(terms[:2]).split()) <= 6 else terms[0]
        return {"name": " ".join(name.split()[:6]), "name_quote": {"passage": 1, "quote": q1},
                "description": f"Passages about {', '.join(terms[:3])} (offline demo, from the key terms).",
                "description_quote": {"passage": len(p), "quote": q2}}

    def _decompose(self, text: str) -> dict:
        """Split at sentence ends, semicolons and ', and' / 'because' / 'which': a demo, not an analysis."""
        parts = []
        for a, b in split_sentences(text):
            for piece in re.split(r";|,\s+and\s+|\s+because\s+|,\s+which\s+|\s+and therefore\s+", text[a:b]):
                piece = piece.strip(" ,.")
                if len(piece) >= 10:
                    parts.append({"text": piece[0].upper() + piece[1:] + ".", "role": "component"})
        return {"parts": parts[:5] or [{"text": text, "role": "component"}], "note": "Offline demo: split at punctuation."}

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


class ClaudeCodeBackend:
    """Claude Code on the researcher's own plan (0.8): nothing is asked from here. The app's runs prepare tasks and
    wait for them in the queue (`taskqueue.wait_for`), which Claude Code answers through the connector
    (`/enlens-run` in Claude Code, typed by the researcher or started by the app's "Start Claude Code", 0.9). ENLENS
    never handles its login."""

    name = "claude_code"

    def __init__(self, router=None):
        self.router = router
        self.should_stop = None   # callable() -> bool: stop waiting
        self.progress = None      # callable(info): what waits in the queue

    def complete(self, kind: str, system: str, user: str, model: str, payload: dict) -> str:
        raise BackendError("Claude Code answers through the task queue; type /enlens-run in Claude Code.")

    def check(self, model: str | None = None) -> dict:
        return {"ok": True, "models": ["haiku", "sonnet", "opus", "fable"], "model_available": True}

    def digest(self, model: str) -> str | None:
        return None  # Claude Code reports no digest: the model is recorded as set for the helper


def provenance(backend, model: str) -> dict:
    """What exactly answers: {"digest", "seed", "settings": {backend, num_ctx, think, think_budget, temperature}}."""
    name = getattr(backend, "name", "") or ""
    digest = None
    if hasattr(backend, "digest"):
        try:
            digest = backend.digest(model)
        except Exception:
            digest = None
    elif name in ("anthropic", "baseline"):
        digest = f"name:{model}"
    if name == "claude_code":
        digest = None
    from .routing import ROUTE_NAMES

    settings = {"backend": name, "temperature": 0, "route": ROUTE_NAMES.get(name, name)}
    if name == "claude_code":
        settings.pop("temperature")  # Claude Code sets no temperature and no seed
    if getattr(backend, "num_ctx", None):
        settings["num_ctx"] = int(backend.num_ctx)
    if name == "ollama":
        settings["think"] = ("judging" if getattr(backend, "think_kinds", None) else
                             {True: "on", False: "off", None: "default"}[getattr(backend, "think", None)])
        settings["think_budget"] = int(getattr(backend, "think_budget", 0) or 0)
    return {"digest": digest, "seed": getattr(backend, "seed", None), "settings": settings}


def repeatable(backend, model: str) -> dict:
    """Ask the same short question twice: the same answer twice means this server is repeatable with a fixed seed
    and temperature 0 ("repeatable"); otherwise "not guaranteed". Two short model calls."""
    from .prompts import system_prompt, user_prompt

    name = getattr(backend, "name", "")
    if name == "baseline":
        return {"repeatable": True, "seed": False, "note": "The offline demo has no model: it always answers the same."}
    if name == "anthropic":
        return {"repeatable": False, "seed": False, "note": "The Claude API takes no seed: answers are not guaranteed "
                                                            "to be the same twice, even at temperature 0."}
    if name == "claude_code":
        return {"repeatable": False, "seed": False,
                "note": "Claude Code takes no seed and no temperature: answers are not guaranteed to be the same "
                        "twice. Measure how much two readings differ with the acceptance runs (--again), or compare "
                        "a sample of labels."}
    payload = {"claim": "Green hydrogen production can increase water stress in arid regions."}
    a = backend.complete("expand", system_prompt("expand"), user_prompt("expand", payload), model, payload)
    b = backend.complete("expand", system_prompt("expand"), user_prompt("expand", payload), model, payload)
    same = a.strip() == b.strip()
    try:
        dig = backend.digest(model) if hasattr(backend, "digest") else None
    except Exception:  # noqa: BLE001 - the test's answer does not depend on it
        dig = None
    return {"repeatable": same, "seed": getattr(backend, "seed", None) is not None, "digest": dig,
            "note": ("The same question gave the same answer twice." if same else
                     "The same question gave two different answers: this server does not guarantee repeatable answers "
                     "(it may ignore the seed, or run its arithmetic in a different order each time).")}


def get_backend(name: str, **kw) -> Backend:
    """A backend by name. 'auto' picks the first local server that is running (Ollama first)."""
    if name == "auto":
        found = detect_local(ollama_url=kw.get("base_url"))
        if not found:
            raise BackendError("No local model server is running. Start Ollama (ollama.com) or LM Studio (lmstudio.ai), "
                               "or choose a backend with --backend.")
        srv = found[0]
        if srv["kind"] == "ollama":
            return OllamaBackend(**{**kw, "base_url": srv["url"]})
        return LocalBackend(base_url=srv["url"])
    if name == "anthropic":
        return AnthropicBackend(**kw)
    if name == "ollama":
        return OllamaBackend(**kw)
    if name == "local":
        return LocalBackend(**kw)
    if name == "baseline":
        return BaselineBackend()
    if name == "claude_code":
        return ClaudeCodeBackend()
    raise ValueError(f"unknown backend {name!r}; use 'auto', 'ollama', 'local', 'anthropic', 'claude_code' or "
                     "'baseline', or the file queue (export-tasks / import-results)")
