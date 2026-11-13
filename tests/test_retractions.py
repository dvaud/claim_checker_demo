"""0.18.1 (B5): retractions and corrections, looked up in Crossref when asked. The tests use a stand-in Crossref
(a QuickServer on this computer) and never touch the network."""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import pytest

from enlens_claims import __version__, access, bibliography, retractions
from enlens_claims.store import Workspace
from test_app import api, home  # noqa: F401  (fixtures)

RETRACTED = "10.1234/retracted.1"
CORRECTED = "10.1234/corrected.2"
CLEAN = "10.1234/clean.3"
HIDDEN = "10.1234/hidden.4"   # its document is marked No AI


class Crossref:
    """The part of Crossref's API ENLENS uses: /works?filter=updates:<doi>,updates:<doi>."""

    def __init__(self):
        from enlens_claims.gui.server import QuickServer

        outer = self
        self.requests: list[tuple[str, dict]] = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                flt = parse_qs(urlparse(self.path).query).get("filter", [""])[0]
                asked = {p.split(":", 1)[1] for p in flt.split(",") if p.startswith("updates:")}
                items = [{"DOI": "10.9999/notice-r", "update-to": [
                    {"DOI": RETRACTED.upper(), "type": "retraction", "source": "retraction-watch",
                     "updated": {"date-parts": [[2024, 3, 9]]}}]},
                    {"DOI": "10.9999/notice-c", "update-to": [
                        {"DOI": CORRECTED, "type": "correction", "source": "publisher",
                         "updated": {"date-parts": [[2023, 11]]}}]},
                    {"DOI": "10.9999/notice-h", "update-to": [
                        {"DOI": HIDDEN, "type": "retraction", "source": "publisher", "updated": {"date-parts": [[2022, 1, 1]]}}]}]
                items = [i for i in items if any(u["DOI"].lower() in asked for u in i["update-to"])]
                body = json.dumps({"status": "ok", "message": {"total-results": len(items), "items": items}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = QuickServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def crossref():
    c = Crossref()
    yield c
    c.stop()


@pytest.fixture
def ws(tmp_path, home):  # noqa: F811
    from enlens_claims import home as core

    ws = core.create_project("R")
    works = [("w1", RETRACTED, "A retracted study"), ("w2", CORRECTED, "A corrected study"), ("w3", CLEAN, "A sound study"),
             ("w4", HIDDEN, "A study read only by hand"), ("w5", None, "A work with no DOI")]
    with ws.connect() as cx:
        for i, (key, doi, title) in enumerate(works):
            cx.execute("INSERT INTO bib_items(item_key, item_type, title, creators_json, year, doi, files_json, seq) "
                       "VALUES (?,?,?,?,?,?,?,?)", (key, "journalArticle", title, "[]", "2020", doi, "[]", i))
        for doc_id, title, doi in [("d1", "The retracted study", None), ("d4", "The hidden study", HIDDEN)]:
            cx.execute("INSERT INTO documents(doc_id, path, sha1, title, doi, kind, n_pages, n_chars, text, added_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?)", (doc_id, f"{doc_id}.txt", doc_id, title, doi, "txt", 1, 1, "x", "2026-01-01"))
        cx.execute("INSERT INTO bib_links(item_key, doc_id, status, method) VALUES ('w1', 'd1', 'confirmed', 'person')")
    ws.set_meta("bibliography", {"kind": "file", "name": "x.bib", "pulled_at": "2026-01-01T00:00:00+00:00"})
    access.set_documents(ws, ["d4"], "none")
    return ws


def test_a_retraction_and_a_correction_are_found_and_shown(ws, crossref):
    out = retractions.lookup(ws, base_url=crossref.url, sleep=lambda s: None)
    assert out["looked_up"] == 3 and out["no_ai"] == 1 and out["notices"] == 2   # the No AI work and the DOI-less one are out
    v = bibliography.view(ws)
    notices = {w["key"]: w["notices"] for w in (v["to_find"] + [r["work"] for r in v["linked"]])}
    assert [n["type"] for n in notices["w1"]] == ["retraction"] and notices["w1"][0]["date"] == "2024-03-09"
    assert notices["w1"][0]["source"] == "retraction-watch" and notices["w1"][0]["doi"] == "10.9999/notice-r"
    assert [n["type"] for n in notices["w2"]] == ["correction"] and notices["w2"][0]["date"] == "2023-11"
    assert notices["w3"] == [] and notices["w5"] == []
    assert v["retractions"]["affected"] == 2 and v["retractions"]["checked_at"]
    # the claim card: the document linked to the retracted work
    by_doc = retractions.for_docs(ws)
    assert list(by_doc) == ["d1"] and by_doc["d1"][0]["type"] == "retraction"
    assert retractions.serious(by_doc["d1"]) and not retractions.serious(retractions.for_items(ws)["w2"])
    assert retractions.text(by_doc["d1"][0]) == "Retracted (2024-03-09)"


def test_a_no_ai_document_is_never_sent(ws, crossref):
    retractions.lookup(ws, base_url=crossref.url, sleep=lambda s: None)
    sent = " ".join(p for p, _h in crossref.requests).lower()
    assert HIDDEN not in sent and RETRACTED in sent and CLEAN in sent
    assert retractions.plan(ws)["no_ai"] == [HIDDEN]
    assert HIDDEN not in retractions.status(ws)["by_doi"]
    # a work without a document is looked up; marking the document back lets its work in
    access.set_documents(ws, ["d4"], "cloud")
    assert HIDDEN in retractions.plan(ws)["ask"]


def test_local_only_sends_nothing(ws, crossref, monkeypatch):
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    with pytest.raises(retractions.RetractionError, match="local-only"):
        retractions.lookup(ws, base_url=crossref.url)
    assert crossref.requests == [] and retractions.status(ws)["local_only"] is True


def test_the_request_carries_only_dois_and_the_plain_user_agent(ws, crossref, monkeypatch):
    monkeypatch.setenv("ENLENS_CROSSREF_URL", crossref.url)
    retractions.lookup(ws, sleep=lambda s: None)   # the address from the environment
    assert crossref.requests
    for path, headers in crossref.requests:
        assert headers["user-agent"] == f"ENLENS/{__version__}"
        flat = (path + json.dumps(headers)).lower()
        assert "mailto" not in flat and "@" not in flat and "authorization" not in headers and "cookie" not in headers
        assert set(parse_qs(urlparse(path).query)) <= {"filter", "rows", "offset", "select"}


def test_results_are_kept_with_their_date_and_read_again(ws, crossref):
    assert retractions.status(ws)["checked_at"] is None
    out = retractions.lookup(ws, base_url=crossref.url, sleep=lambda s: None)
    again = Workspace.open(ws.root)   # a fresh reading of the project's database
    s = retractions.status(again)
    assert s["checked_at"] == out["checked_at"] and s["checked"] == 3 and s["affected"] == 2
    assert s["by_doi"][RETRACTED]["checked_at"] == out["checked_at"]
    assert [n["work_doi"] for n in s["by_item"]["w1"]] == [RETRACTED]
    # the clean DOI is kept too (with no notice), so the page can say it was checked
    assert again.scalar("SELECT notices_json FROM retractions WHERE doi=?", (CLEAN,)) == "[]"


def test_an_unreachable_server_is_a_clear_error(ws):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{s.getsockname()[1]}"
    with pytest.raises(retractions.RetractionError, match="Could not reach Crossref"):
        retractions.lookup(ws, base_url=dead)
    assert retractions.status(ws)["checked_at"] is None


def test_the_routes(api, ws, crossref, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ENLENS_CROSSREF_URL", crossref.url)
    st, r = api("GET", "/api/projects/R/retractions")
    assert st == 200 and r["checked_at"] is None and r["plan"] == {"ask": 3, "no_ai": 1}
    st, r = api("POST", "/api/projects/R/retractions/check", {})
    assert st == 200 and r["job"]["kind"] == "retractions"
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done" and job["result"]["notices"] == 2, job
    st, r = api("GET", "/api/projects/R/retractions")
    assert r["affected"] == 2 and list(r["by_doc"]) == ["d1"] and r["by_doc"]["d1"][0]["type"] == "retraction"
    st, b = api("GET", "/api/projects/R/bibliography")
    assert st == 200 and b["retractions"]["affected"] == 2
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    st, r = api("POST", "/api/projects/R/retractions/check", {})
    assert st == 400 and "local-only" in r["error"]


def test_the_command_line_shows_and_checks(ws, crossref, monkeypatch, capsys):
    from enlens_claims import cli

    monkeypatch.setenv("ENLENS_CROSSREF_URL", crossref.url)
    assert cli.main(["retractions", str(ws.root), "--check"]) == 0
    out = capsys.readouterr().out
    assert '"affected": 2' in out
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    assert cli.main(["retractions", str(ws.root), "--check"]) == 1
