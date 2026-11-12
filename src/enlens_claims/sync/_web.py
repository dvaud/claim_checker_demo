"""Plain HTTP for the online-storage clients (`storage.py`, `b2.py`, `r2.py`): the standard library only.

`send` makes one request and hands back the answer whatever its status; a network failure is a `NetError` with a
reason in words. `send_retrying` tries again, with a short back-off, after a cut connection, a 429 or a 5xx.
Redirects are never followed (a signed request must not travel on), and nothing here ever puts a key in a message.
"""
from __future__ import annotations

import http.client
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlsplit

BACKOFF = (0.5, 1.0, 2.0)          # seconds before the 2nd, 3rd and 4th try
sleep = time.sleep                  # tests replace it
ERROR_BODY_CAP = 64 * 1024          # an error page is read up to this much
_LOOPBACK = ("127.0.0.1", "localhost", "::1")


class NetError(Exception):
    """No answer came: `reason` says why in a few words; `retryable` is true for a cut connection."""

    def __init__(self, reason: str, retryable: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


@dataclass
class Reply:
    status: int
    headers: dict = field(default_factory=dict)   # names in lower case
    body: bytes = b""
    too_big: bool = False                         # more than `read_cap` bytes came (body is then cut short)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # noqa: D401
        return None


def _opener(url: str):
    handlers: list = [_NoRedirect()]
    if (urlsplit(url).hostname or "") in _LOOPBACK:
        handlers.append(urllib.request.ProxyHandler({}))   # this computer is never behind the proxy
    return urllib.request.build_opener(*handlers)


def _reason(e: BaseException) -> tuple[str, bool]:
    if isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError):
        inner = e.reason
        if isinstance(inner, BaseException):
            return _reason(inner)
        return (str(inner) or "no connection"), False
    if isinstance(e, socket.gaierror):
        return "the address was not found, so there may be no internet connection", False
    if isinstance(e, ConnectionRefusedError):
        return "the connection was refused", False
    if isinstance(e, TimeoutError):
        return "there was no answer in time", False
    if isinstance(e, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
        return "the connection was cut", True
    if isinstance(e, (http.client.HTTPException, EOFError)):
        return "the connection was cut", True
    if isinstance(e, ssl.SSLError):
        return "the secure connection could not be made", False
    if isinstance(e, OSError):
        return (e.strerror or "no connection"), False
    return "no connection", False


def send(method: str, url: str, headers: dict | None = None, body: bytes | None = None, timeout: float = 60.0,
         read_cap: int | None = None) -> Reply:
    """One request. With `read_cap`, a successful answer longer than that (by its Content-Length, or by reading) is
    flagged `too_big` and not read whole."""
    req = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))
    try:
        try:
            resp = _opener(url).open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            resp = e
        with resp:
            status = getattr(resp, "status", None) or resp.code
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            if status >= 300:
                return Reply(status, hdrs, resp.read(ERROR_BODY_CAP))
            if read_cap is None:
                return Reply(status, hdrs, resp.read())
            try:
                declared = int(hdrs.get("content-length", "-1"))
            except ValueError:
                declared = -1
            if declared > read_cap:
                return Reply(status, hdrs, b"", True)
            data = resp.read(read_cap + 1)
            if len(data) > read_cap:
                return Reply(status, hdrs, b"", True)
            return Reply(status, hdrs, data)
    except NetError:
        raise
    except Exception as e:  # noqa: BLE001 - every network failure is reported in words
        reason, retry = _reason(e)
        raise NetError(reason, retry) from e


def is_maintenance(r: Reply) -> bool:
    return r.status == 503 and b"maintenance" in r.body.lower()


def send_retrying(build, timeout: float = 60.0, read_cap: int | None = None) -> Reply:
    """`build()` returns `(method, url, headers, body)` afresh for each try (a signature carries the time).
    A cut connection, a 429 and a 5xx (but not a maintenance page) are tried again after 0.5, 1 and 2 seconds; the last
    answer comes back, or the last NetError is raised."""
    tries = 1 + len(BACKOFF)
    for i in range(tries):
        last = i == tries - 1
        method, url, headers, body = build()
        try:
            r = send(method, url, headers, body, timeout, read_cap)
        except NetError as e:
            if e.retryable and not last:
                sleep(BACKOFF[i])
                continue
            raise
        if (r.status == 429 or r.status >= 500) and not is_maintenance(r) and not last:
            sleep(BACKOFF[i])
            continue
        return r
    raise AssertionError("unreachable")
