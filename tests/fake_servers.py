"""Small stand-ins for an Ollama server and the Claude API, for tests and for trying the GUI offline.

They speak the same HTTP as the real services for the calls enlens makes, and answer from simple rules:
search terms are the claim's words, and a check grades the first passage as supporting with a short quote from it.
Run `python tests/fake_servers.py` to start a fake Ollama on port 11435.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FAKE_MODEL = "fake-model:latest"
# misbehaving models, for testing the guards: reasons until the output cap, writes blank space, never starts
THINKER, LOOPER, SLOW = "fake-thinker:latest", "fake-loop:latest", "fake-slow:latest"
FAKE_EMBED = "fake-embed:latest"   # an embedding model: hashed bag of words, 64 dimensions
SECOND = "fake-second:latest"      # a second opinion: grades like fake-model, but sees support as only partial
MODELS = (FAKE_MODEL, THINKER, LOOPER, SLOW, FAKE_EMBED, SECOND)


def fake_vector(text: str, dims: int = 64) -> list[float]:
    import hashlib

    v = [0.0] * dims
    for w in re.findall(r"[a-z]{4,}", text.lower()):
        v[int(hashlib.md5(w[:6].encode()).hexdigest(), 16) % dims] += 1.0
    return v if any(v) else [1.0] + [0.0] * (dims - 1)


def _varied_check(user: str) -> dict:
    """A spread of grades for trying the interface: support, partial support, contradiction, or nothing."""
    import hashlib

    claim = user.split("\n", 1)[1].split("\n\nP1 |", 1)[0] if "\n" in user else user
    blocks = re.findall(r"^P(\d+) \| [^\n]*\n(.+?)(?=\n\nP\d+ \||\Z)", user, re.S | re.M)
    h = int(hashlib.md5(claim.encode()).hexdigest(), 16)
    if h % 5 == 0 or not blocks:
        return {"evidence": [], "rationale": "None of the passages bears on the claim (fake server)."}
    grades = [("supports", 0.82), ("partially_supports", 0.66), ("refutes", 0.71 if h % 3 == 0 else 0.45)]
    ev = []
    for (n, text), (verdict, conf) in zip(blocks, grades):
        words = text.split()
        ev.append({"passage": int(n), "verdict": verdict, "confidence": conf, "quote": " ".join(words[2:12])})
    return {"evidence": ev, "rationale": "Passage 1 states it; passage 2 states the mechanism only (fake server)."}


_STOP = set("that this with from have were been their they them which when where while into than then also more most "
            "some such only very about after before other these those there would could should does will".split())
_UP = re.compile(r"\b(increas\w*|ris\w*|rose|higher|more|improv\w*|rais\w*|grow\w*|grew|better|gain\w*)\b", re.I)
_DOWN = re.compile(r"\b(reduc\w*|decreas\w*|fall\w*|fell|lower\w*|less|fewer|cut\w*|declin\w*|wors\w*|lost)\b", re.I)
_NEG = re.compile(r"\b(not|no|never|nor|neither|without)\b", re.I)


def _words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z]{4,}", text.lower()):
        if w in _STOP:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if w.endswith(suf) and len(w) - len(suf) >= 4:
                w = w[: -len(suf)]
                break
        out.add(w)
    return out


def _polarity(text: str) -> int:
    p = (1 if _UP.search(text) else 0) - (1 if _DOWN.search(text) else 0)
    return -p if _NEG.search(text) else p


def _overlap_check(user: str) -> dict:
    """Grades by shared words and the direction words of each sentence: a crude stand-in for reading, but its grades
    follow the text, so the interface can be tried with sensible results."""
    claim = user.split("\n", 1)[1].split("\n\nP1 |", 1)[0] if "\n" in user else user
    cw = _words(claim)
    cpol = _polarity(claim)
    heads = dict(re.findall(r"^P(\d+) \| ([^\n]*)\n", user, re.M))
    blocks = re.findall(r"^P(\d+) \| [^\n]*\n(.+?)(?=\n\nP\d+ \||\Z)", user, re.S | re.M)
    # words of the claim found in most excerpts ("work", "home") say little: a sentence must share a rarer one
    df = {w: sum(1 for _n, t in blocks if w in _words(t)) for w in cw}
    rare = {w for w in cw if len(blocks) < 3 or df[w] <= len(blocks) / 2} or cw
    ev = []
    for n, text in blocks:
        best, best_s = 0.0, ""
        for sent in re.split(r"(?<=[.!?])\s+", text):
            sw = _words(sent)
            title = sent.strip()[:30] in heads.get(n, "")
            if title or sent.strip().endswith("?") or not (sw & rare):  # a question or a title states nothing
                continue
            ov = len(cw & sw) / max(1, len(cw))
            if ov > best:
                best, best_s = ov, sent.strip()
        if not best_s or best < 0.28:
            continue
        spol = _polarity(best_s)
        short = len(best_s.split()) < 9   # a heading or fragment: graded, but without much certainty
        cap = 0.58 if short else 0.92
        # check-v3: an excerpt about another group than the claim names (fully remote for a claim about hybrid work)
        scope = ("about fully remote workers, not hybrid" if "hybrid" in claim.lower()
                 and re.search(r"fully (remote|from home)", best_s, re.I) else None)
        if cpol and spol and cpol != spol and best >= 0.4:
            ev.append({"passage": int(n), "verdict": "refutes", "confidence": round(min(cap, 0.5 + best / 2), 2), "quote": best_s,
                       "scope_note": scope})
        elif best >= 0.45 and not scope:
            ev.append({"passage": int(n), "verdict": "supports", "confidence": round(min(cap, 0.5 + best / 2), 2), "quote": best_s,
                       "scope_note": None})
        else:
            ev.append({"passage": int(n), "verdict": "partially_supports", "confidence": round(min(cap, 0.42 + best / 2), 2),
                       "quote": best_s, "scope_note": scope})
    # check-v4: a quote that opens with "It" or "They" says what it refers to (the subject of the sentence before)
    texts = dict(blocks)
    for e in ev:
        if re.match(r"(It|Its|They|Their)\b", e["quote"]):
            before = texts.get(str(e["passage"]), "").split(e["quote"])[0]
            prev = [x for x in re.split(r"(?<=[.!?])\s+", before.strip()) if x]
            m = re.match(r"([A-Z][a-z]+(?: [a-z]{3,})?)", prev[-1]) if prev else None
            if m:
                e["refers_to"] = m.group(1)
    if not ev:
        return {"evidence": [], "rationale": "None of the excerpts is about this claim."}
    kinds = {e["verdict"] for e in ev}
    if "supports" in kinds and "refutes" in kinds:
        why = "Some excerpts state the claim and others state the opposite."
    elif "supports" in kinds:
        why = "At least one excerpt states the claim directly."
    elif "refutes" in kinds:
        why = "The relevant excerpts point the other way."
    else:
        why = "The excerpts state parts of the claim, but none states it all."
    return {"evidence": ev, "rationale": why}


def _split_hypothesis(text: str) -> list[str]:
    parts = [p.strip(" .") for p in re.split(r",? and |; |, but ", text) if len(p.strip(" .")) >= 10]
    if len(parts) < 2:
        return [text]
    words = parts[0].split()
    verb = next((i for i, w in enumerate(words) if i and re.fullmatch(r"[a-z]+(s|ed)", w) and w not in ("hours", "years")), None)
    subject = " ".join(words[:verb]) if verb else ""
    out = []
    for p in parts:
        if subject and p[0].islower() and re.match(r"[a-z]+(s|ed)\b", p):
            p = f"{subject} {p}"
        out.append(p[0].upper() + p[1:] + ".")
    return out


# other wordings the varied fake offers for the demo corpus's topics, as a model would
_RELATED = {"commut": ["commute", "travel to work", "car trips"], "emission": ["CO2", "carbon"],
            "remote": ["telework", "home working"], "home": ["telework"], "wellbe": ["well-being", "life satisfaction"],
            "lonel": ["isolation", "lonely"], "sick": ["absence", "sickness"], "productivity": ["output", "performance"],
            "hybrid": ["part-time remote"], "public": ["municipal", "citizens"], "service": ["waiting times"],
            "young": ["younger workers", "under 30"], "traffic": ["congestion", "rush hour"]}


def _second_view(out: dict) -> dict:
    """fake-second: where fake-model sees support, it sees partial support (a model that is more cautious)."""
    for e in out.get("evidence", []):
        if e["verdict"] == "supports":
            e["verdict"], e["confidence"] = "partially_supports", round(max(0.5, e["confidence"] - 0.1), 2)
    return out


_BEFORE = re.compile(r"BEFORE P(\d+) \(for refers_to only[^\n]*\n.*?(?=P\1 \| )", re.S)


def _answer(system: str, user: str, varied: bool = False, model: str = "") -> dict:
    user = _BEFORE.sub("", user)  # check-v4 shows the text before an excerpt (for refers_to only): never graded
    out = _answer1(system, user, varied)
    return _second_view(out) if model == SECOND and system.startswith("You check whether") else out


# kinds ("label", "link", "theme", "resolve") whose first answer carries a quote that is not in the text, to prove
# the retry path; the answer to a retry (the prompt lists the problems) is right
WRONG_FIRST: set = set()


def _first_words(text: str, n: int = 8) -> str:
    return " ".join(text.split()[:n])


def _blocks(user: str) -> list[tuple[str, str]]:
    return re.findall(r"^P(\d+)(?: \|[^\n]*| \(page [^)]*\))?\n(.+?)(?=\n\nP\d+[ \n(|]|\Z)", user, re.S | re.M)


def _answer_07(system: str, user: str) -> dict | None:
    """Canned answers for the task kinds of 0.7: codebook labels, links between terms, theme names, references."""
    retry = "YOUR PREVIOUS ANSWER HAD THESE PROBLEMS" in user
    user = user.split("\n\nYOUR PREVIOUS ANSWER HAD THESE PROBLEMS", 1)[0]
    if system.startswith("You label a passage"):
        kind = "label"
        cands = re.findall(r"^([0-9A-Za-z][\w.-]*): (.+)$", user.split("CANDIDATE CODES:\n", 1)[1].split("\n\n", 1)[0], re.M) \
            if "CANDIDATE CODES:\n" in user else []
        passage = user.split("PASSAGE:\n", 1)[1] if "PASSAGE:\n" in user else ""
        pw = _words(passage)
        labels = [{"code": c, "relevance": "main" if i == 0 else "mentioned", "direction": "hinders" if i == 0 else "not_stated",
                   "confidence": 0.8 if i == 0 else 0.6, "quote": _first_words(passage), "reason": "fake: shares words"}
                  for i, (c, d) in enumerate([(c, d) for c, d in cands if _words(d) & pw][:2])]
        out = {"labels": labels, "note": None}
        if kind in WRONG_FIRST and not retry and labels:
            out["labels"][0]["quote"] = "words that are not in the passage at all"
        return out
    if system.startswith("You judge how terms"):
        terms = re.findall(r"^TERM (\d+): (.+)$", user, re.M)
        snips = {n: re.findall(rf"^  passage {n}\.\d+ \([^)]*\): (.+)$", user, re.M) for n, _l in terms}
        a, b = terms[0][0], terms[1][0]
        la, lb = terms[0][1].lower(), terms[1][1].lower()
        rel = "same" if (la in lb or lb in la) else "related"
        out = {"relations": [{"a": int(a), "b": int(b), "relation": rel, "confidence": 0.75,
                              "quote_a": _first_words(snips[a][0], 6), "quote_b": _first_words(snips[b][0], 6)}]}
        if "link" in WRONG_FIRST and not retry:
            out["relations"][0]["quote_a"] = "a quote nobody wrote"
        return out
    if system.startswith("You name a theme"):
        terms = (re.search(r"^KEY TERMS: (.*)$", user, re.M) or [None, ""])[1].split(", ")
        ps = _blocks(user)
        name = " ".join(" and ".join(t for t in terms[:2] if t).split()[:6]) or "a theme"
        out = {"name": name, "name_quote": {"passage": 1, "quote": _first_words(ps[0][1])},
               "description": f"The passages discuss {', '.join(terms[:3])}.",
               "description_quote": {"passage": int(ps[-1][0]), "quote": _first_words(ps[-1][1])}}
        if "theme" in WRONG_FIRST and not retry:
            out["name_quote"]["quote"] = "not a quote from any passage"
        return out
    if system.startswith("You find chains of references"):
        chains = []
        for n, text in _blocks(user):
            sents = re.split(r"(?<=[.!?])\s+", text.strip())
            subject = None
            mentions = []
            for snt in sents:
                m = re.match(r"(Green hydrogen|Hydrogen projects|Export hubs|The plant|Hydrogen production)\b", snt) \
                    or re.match(r"((?!It\b|They\b|Their\b|Its\b|This\b|These\b|The\b|In\b|A\b)[A-Z][a-z]+ [a-z]{4,})\b", snt)
                if m and subject is None:
                    subject = m.group(1)
                    mentions.append({"passage": int(n), "span": _first_words(snt, 6), "mention": subject, "named": True})
                elif subject and re.match(r"(It|Its|They|Their)\b", snt):
                    w = snt.split()[0]
                    mentions.append({"passage": int(n), "span": _first_words(snt, 5), "mention": w, "named": False})
            if subject and len(mentions) >= 2:
                chains.append({"name": subject, "mentions": mentions})
        out = {"chains": chains}
        if "resolve" in WRONG_FIRST and not retry and chains:
            out["chains"][0]["mentions"][0]["span"] = "a span that is nowhere"
        return out
    return None


def _answer1(system: str, user: str, varied: bool = False) -> dict:
    new = _answer_07(system, user)
    if new is not None:
        return new
    if system.startswith("You prepare a search") and varied:
        claim = user.split("\n", 1)[1].split("\n\nIt is part of this hypothesis", 1)[0] if "\n" in user else user
        low = claim.lower()
        extra = [t for key, alts in _RELATED.items() if key in low for t in alts]
        own = [w for w in dict.fromkeys(re.findall(r"[a-z]{4,}", low)) if w not in _STOP]
        return {"terms": (extra + own)[:12] or ["claim"]}
    if system.startswith("You prepare a search"):
        claim = user.split("\n", 1)[1] if "\n" in user else user
        return {"terms": sorted({w.lower() for w in re.findall(r"[A-Za-z]{5,}", claim)})[:10] or ["claim"]}
    if system.startswith("You check whether") and varied:
        user = re.sub(r"\n\nThis passage is read again on request\..*\Z", "", user, flags=re.S)
        m = re.search(r"\n\nA reader noted[^:]*: (.*)\Z", user, re.S)
        out = _overlap_check(user[:m.start()] if m else user)
        if m and out["evidence"]:  # asked to read again with a person's comment: a stand-in for reconsidering
            note = m.group(1).lower()
            for e in out["evidence"]:
                if re.search(r"opposite|contradict|refut|\bnot\b|n't", note):
                    e["verdict"] = "refutes"
                elif re.search(r"part|only|some", note):
                    e["verdict"] = "partially_supports"
                e["confidence"] = round(max(0.5, e["confidence"] - 0.12), 2)
            v = {"refutes": "contradicts", "partially_supports": "only partly supports", "supports": "supports"}
            out["rationale"] = (f"Taking the reader's note into account, the passage {v[out['evidence'][0]['verdict']]} the "
                                "claim (fake server: it follows words in the note such as 'not' or 'only').")
        return out
    if system.startswith("You check whether"):
        m = re.search(r"^P1 \| [^\n]*\n(.+?)(?:\n\nP2 \||\Z)", user, re.S | re.M)
        if not m:
            return {"evidence": [], "rationale": "nothing shown"}
        words = m.group(1).split()
        return {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.8, "quote": " ".join(words[:8])}],
                "rationale": "The first passage states it (fake server)."}
    if system.startswith("You extract"):
        return {"claims": [], "interactions": [], "note": None}
    if system.startswith("You split a hypothesis"):
        text = user.split("\n", 1)[1] if "\n" in user else user
        return {"parts": [{"text": p, "role": "component"} for p in _split_hypothesis(text.strip())], "note": None}
    return {}


class _Ollama(BaseHTTPRequestHandler):
    server_version = "fake-ollama"

    def log_message(self, *a):  # keep test output quiet
        pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        aliases = getattr(self.server, "aliases", None)
        if self.path == "/api/version":
            return self._send(200, {"version": "0.12.6" if aliases else "0.40.5-fake"})
        if self.path == "/api/tags":
            return self._send(200, {"models": [{"name": m, "model": m, "modified_at": self.server.modified.get(m, ""),
                                                "digest": hashlib.sha256(m.encode()).hexdigest()}
                                               for m in (aliases or MODELS)]})
        if self.path == "/api/ps":  # models in memory, most recently used first
            return self._send(200, {"models": [{"name": m, "model": m, "expires_at": f"2026-10-28T12:{59 - i:02d}:00Z"}
                                               for i, m in enumerate(self.server.loaded)]})
        return self._send(404, {"error": "not found"})

    def _load(self, name: str) -> None:
        """Keep track of what a real Ollama would hold in memory (chat models; embedding models are small)."""
        if name in self.server.loaded:
            self.server.loaded.remove(name)
        self.server.loaded.insert(0, name)
        chat = [m for m in self.server.loaded if "embed" not in m]
        self.server.peak_loaded = max(self.server.peak_loaded, len(chat))

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.requests.append((self.path, req))
        model = req.get("model", "")
        aliases = getattr(self.server, "aliases", None)
        if aliases:  # the dev server's realistic names (a fresh install as a user would have it)
            model = aliases.get(model) or aliases.get(f"{model}:latest") or "?"
        if model not in MODELS and f"{model}:latest" not in MODELS:
            return self._send(404, {"error": f"model '{model}' not found"})
        if self.path == "/api/generate" and req.get("keep_alive") in (0, "0", "0s"):  # unload
            self.server.unloads.append(req.get("model"))
            if req.get("model") in self.server.loaded:
                self.server.loaded.remove(req.get("model"))
            return self._send(200, {"model": req.get("model"), "done": True, "done_reason": "unload", "response": ""})
        if self.path == "/api/embed":
            inputs = req.get("input")
            inputs = [inputs] if isinstance(inputs, str) else list(inputs or [])
            return self._send(200, {"model": model, "embeddings": [fake_vector(t) for t in inputs]})
        if self.path == "/api/show":
            thinks = self.server.thinking or model == THINKER
            return self._send(200, {"details": {"parameter_size": "8B", "quantization_level": "Q4_K_M", "family": "fake"},
                                    "model_info": {"fake.context_length": self.server.trained_context},
                                    "capabilities": ["completion"] + (["thinking"] if thinks else [])})
        if self.path == "/api/chat":
            self._load(req.get("model", ""))
            self.server.contexts.append(int((req.get("options") or {}).get("num_ctx") or 0))
            msgs = req.get("messages") or []
            system = next((m["content"] for m in msgs if m["role"] == "system"), "")
            user = next((m["content"] for m in msgs if m["role"] == "user"), "")
            opts = req.get("options") or {}
            num_ctx = int(opts.get("num_ctx") or 4096)
            cap = int(opts.get("num_predict") or 10_000)
            tokens = (len(system) + len(user)) // 4
            answer = json.dumps(_answer(system, user, getattr(self.server, "varied", False), model))
            if not req.get("stream", True):
                return self._send(200, {"model": model, "done": True, "message": {"role": "assistant", "content": answer},
                                        "prompt_eval_count": min(tokens, num_ctx), "eval_count": 50})
            return self._stream(model, answer, min(tokens, num_ctx), cap, req.get("think"))
        return self._send(404, {"error": "not found"})

    def _stream(self, model, answer, prompt_tokens, cap, think):
        """Newline-delimited JSON chunks, like Ollama with "stream": true."""
        import time

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

        def send(obj):
            self.wfile.write((json.dumps(obj) + "\n").encode())
            self.wfile.flush()

        def msg(**kw):
            return {"model": model, "done": False, "message": {"role": "assistant", "content": "", **kw}}

        try:
            if model == SLOW:
                time.sleep(self.server.slow_seconds)
            n, reason = 0, "stop"
            if model == THINKER and think is not False:
                for n in range(1, cap + 1):
                    send(msg(thinking="hmm "))
                reason = "length"
            elif model == LOOPER:
                send(msg(content='{"terms": ['))
                for n in range(2, cap + 1):
                    send(msg(content="\n "))
                    time.sleep(0.002)  # slow enough that a client which gives up is noticed (not all buffered)
                reason = "length"
            else:
                for i in range(0, len(answer), 8):
                    send(msg(content=answer[i:i + 8]))
                    n += 1
                    if self.server.delay:
                        time.sleep(self.server.delay)
            send({"model": model, "done": True, "done_reason": reason, "message": {"role": "assistant", "content": ""},
                  "prompt_eval_count": prompt_tokens, "eval_count": n, "load_duration": 2_000_000_000,
                  "prompt_eval_duration": 1_500_000_000, "eval_duration": 3_000_000_000})
        except (BrokenPipeError, ConnectionResetError):  # the client stopped reading, as it should when it gives up
            self.server.disconnects += 1


class _Anthropic(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self) -> bool:
        # the SDK sends the key as x-api-key (older versions) or as a bearer token (2.x)
        if self.headers.get("x-api-key") == "good-key" or self.headers.get("Authorization") == "Bearer good-key":
            return True
        self._send(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
        return False

    def do_GET(self):
        if not self._authorised():
            return
        if self.path.startswith("/v1/models"):
            data = [{"id": "claude-opus-5-5", "type": "model", "display_name": "Claude Opus 5.5",
                     "created_at": "2026-01-01T00:00:00Z"}]
            return self._send(200, {"data": data, "has_more": False, "first_id": data[0]["id"], "last_id": data[0]["id"]})
        return self._send(404, {"type": "error", "error": {"type": "not_found_error", "message": "not found"}})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if not self._authorised():
            return
        self.server.requests.append((self.path, req))
        if self.path.startswith("/v1/messages"):
            system = "".join(b.get("text", "") for b in req.get("system") or []) if isinstance(req.get("system"), list) else req.get("system", "")
            user = req["messages"][0]["content"]
            text = json.dumps(_answer(system, user if isinstance(user, str) else ""))
            return self._send(200, {"id": "msg_fake", "type": "message", "role": "assistant", "model": req.get("model"),
                                    "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
                                    "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 10}})
        return self._send(404, {"type": "error", "error": {"type": "not_found_error", "message": "not found"}})


def start(kind: str = "ollama", port: int = 0, trained_context: int = 32768):
    """Start a fake server in a background thread; returns (server, base_url). Call server.shutdown() to stop."""
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Ollama if kind == "ollama" else _Anthropic)
    srv.requests = []
    srv.trained_context = trained_context
    srv.thinking = False
    srv.delay = 0.0          # seconds between streamed chunks
    srv.slow_seconds = 5     # how long fake-slow waits before its first chunk
    srv.disconnects = 0
    srv.varied = False       # True: a spread of grades (for trying the interface)
    srv.aliases = None       # {listed name: fake model}: the names a real install would show
    srv.loaded = []          # model names in memory (as /api/ps lists them), most recently used first
    srv.peak_loaded = 0      # the most chat models held in memory at once
    srv.unloads = []         # models unloaded (keep_alive 0)
    srv.modified = {}        # {model name: ISO time it was pulled}
    srv.contexts = []        # num_ctx of every chat request
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":  # pragma: no cover
    import sys

    import os

    s, url = start("ollama", int(sys.argv[1]) if len(sys.argv) > 1 else 11435)
    s.delay = float(os.environ.get("FAKE_DELAY", "0"))
    print(f"fake Ollama at {url} with model {FAKE_MODEL}; Ctrl+C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        s.shutdown()
