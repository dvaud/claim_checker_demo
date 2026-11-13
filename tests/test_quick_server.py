"""2026-11-12: ENLENS's server starts without looking up this computer's full name. Python's own server_bind asks for
it (socket.getfqdn), which took 35 s (70 s in network mode) on GitHub's Mac runners: in every test that started ENLENS
there, and at every start of ENLENS on a Mac whose name the network does not answer for."""
from __future__ import annotations

import socket

from test_app import home  # noqa: F401  (fixture)


def test_the_server_starts_without_looking_up_this_computer_s_name(home, monkeypatch):  # noqa: F811
    from enlens_claims.gui.server import make_server

    def no_lookup(*a, **k):
        raise AssertionError("the server looked up this computer's name")

    monkeypatch.setattr(socket, "getfqdn", no_lookup)
    monkeypatch.setattr(socket, "gethostbyaddr", no_lookup)
    for host in ("127.0.0.1", "0.0.0.0"):   # on this computer only, and in network mode
        srv, app = make_server(host, 0)
        try:
            assert srv.server_port == app.port > 0 and srv.server_name == host
        finally:
            srv.server_close()


def test_every_test_server_starts_without_the_lookup_too():
    """2026-11-13: two stand-in servers written later (test_ollama_install, test_local_servers) used Python's own again, and each
    test with one waited 35 s on GitHub's Mac. A stand-in server is a QuickServer (or made from one)."""
    import re
    from pathlib import Path

    here = Path(__file__).parent
    found = []
    for f in sorted(here.rglob("*.py")) + sorted((here.parent / "src").rglob("*.py")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"\b(Threading)?HTTPServer\s*[()]", code) and "class QuickServer(" not in code:
                found.append(f"{f.name}:{n}: {line.strip()}")
    assert not found, "start these with QuickServer (enlens_claims.gui.server):\n" + "\n".join(found)
