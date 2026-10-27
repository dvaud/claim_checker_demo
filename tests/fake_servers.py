"""Small stand-ins for an Ollama server and the Claude API, for tests and for trying the GUI offline.

They speak the same HTTP as the real services for the calls enlens makes, and answer from simple rules:
search terms are the claim's words, and a check grades the first passage as supporting with a short quote from it.
Run `python tests/fake_servers.py` to start a fake Ollama on port 11435.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FAKE_MODEL = "fake-model:latest"


def _answer(system: str, user: str) -> dict:
    if system.startswith("You prepare a search"):
        claim = user.split("\n", 1)[1] if "\n" in user else user
        return {"terms": sorted({w.lower() for w in re.findall(r"[A-Za-z]{5,}", claim)})[:10] or ["claim"]}
    if system.startswith("You check whether"):
        m = re.search(r"^P1 \| [^\n]*\n(.+?)(?:\n\nP2 \||\Z)", user, re.S | re.M)
        if not m:
            return {"evidence": [], "rationale": "nothing shown"}
        words = m.group(1).split()
        return {"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.8, "quote": " ".join(words[:8])}],
                "rationale": "The first passage states it (fake server)."}
    if system.startswith("You extract"):
        return {"claims": [], "interactions": [], "note": None}
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
        if self.path == "/api/version":
            return self._send(200, {"version": "0.40.5-fake"})
        if self.path == "/api/tags":
            return self._send(200, {"models": [{"name": FAKE_MODEL, "model": FAKE_MODEL}]})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.requests.append((self.path, req))
        model = req.get("model", "")
        if model not in (FAKE_MODEL, FAKE_MODEL.split(":")[0]):
            return self._send(404, {"error": f"model '{model}' not found"})
        if self.path == "/api/show":
            return self._send(200, {"details": {"parameter_size": "8B", "quantization_level": "Q4_K_M", "family": "fake"},
                                    "model_info": {"fake.context_length": self.server.trained_context},
                                    "capabilities": ["completion"] + (["thinking"] if self.server.thinking else [])})
        if self.path == "/api/chat":
            msgs = req.get("messages") or []
            system = next((m["content"] for m in msgs if m["role"] == "system"), "")
            user = next((m["content"] for m in msgs if m["role"] == "user"), "")
            num_ctx = int((req.get("options") or {}).get("num_ctx") or 4096)
            tokens = (len(system) + len(user)) // 4
            return self._send(200, {"model": model, "done": True,
                                    "message": {"role": "assistant", "content": json.dumps(_answer(system, user))},
                                    "prompt_eval_count": min(tokens, num_ctx), "eval_count": 50})
        return self._send(404, {"error": "not found"})


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
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":  # pragma: no cover
    import sys

    s, url = start("ollama", int(sys.argv[1]) if len(sys.argv) > 1 else 11435)
    print(f"fake Ollama at {url} with model {FAKE_MODEL}; Ctrl+C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        s.shutdown()
