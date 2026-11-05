"""A stand-in for the Zotero desktop app's local API (Zotero 7 or later: http://127.0.0.1:23119/api/), for the tests
and `tools/dev_server.py --zotero`. It serves a small library from memory, the way Zotero's documentation describes
the local API: `/api/users/0/...` and `/api/groups/<id>/...`, collections, top-level items (`/items/top`), children,
attachments (`?itemType=attachment`), `limit`/`start`, and `/items/<key>/file/view/url` (the file's file:// URL as plain
text). 0.13.9: the quick search (`q`: title, creators, year), `sort=title`, and `?itemKey=K1,K2` on `/items`, which, as
Zotero 10 does, also returns the children of the works asked for. `mode`: "ready", "api_off" (403 on /api/, the box in Zotero's settings not ticked), "old" (404 on /api/, as a
Zotero 6 would answer).
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class Library:
    def __init__(self, name: str):
        self.name = name
        self.collections: list[dict] = []
        self.items: list[dict] = []

    def collection(self, key: str, name: str, parent: str | None = None) -> str:
        self.collections.append({"key": key, "version": 1, "meta": {"numCollections": 0, "numItems": 0},
                                 "data": {"key": key, "name": name, "parentCollection": parent or False}})
        return key

    def item(self, key: str, title: str, *, type_: str = "journalArticle", creators=(), date: str = "",
             collections=(), **fields) -> str:
        cr = []
        for c in creators:
            cr.append({"creatorType": "author", "name": c} if isinstance(c, str) else
                      {"creatorType": "author", "lastName": c[0], "firstName": c[1] if len(c) > 1 else ""})
        data = {"key": key, "itemType": type_, "title": title, "creators": cr, "date": date,
                "collections": list(collections), **fields}
        self.items.append({"key": key, "version": 1, "meta": {"creatorSummary": "", "parsedDate": date[:4]},
                           "data": data})
        return key

    def attachment(self, key: str, parent: str | None, path: Path | None, title: str = "Full Text PDF",
                   content_type: str = "application/pdf", link_mode: str = "imported_file") -> str:
        data = {"key": key, "itemType": "attachment", "title": title, "linkMode": link_mode,
                "contentType": content_type, "filename": path.name if path else ""}
        if parent:
            data["parentItem"] = parent
        self.items.append({"key": key, "version": 1, "meta": {}, "data": data, "_path": str(path) if path else None})
        return key


class FakeZotero:
    def __init__(self):
        self.mode = "ready"
        self.libraries: dict[str, Library] = {"user": Library("My Library")}
        self.groups: dict[str, str] = {}     # group id -> name
        self.requests: list[str] = []
        self.server: ThreadingHTTPServer | None = None

    @property
    def user(self) -> Library:
        return self.libraries["user"]

    def group(self, gid: int, name: str) -> Library:
        self.groups[str(gid)] = name
        lib = self.libraries[f"group-{gid}"] = Library(name)
        return lib

    # -- the answers -----------------------------------------------------------------------
    def answer(self, path: str, q: dict) -> tuple[int, object, str]:
        if path == "/connector/ping":
            return 200, "Zotero is running", "text/plain"
        if not path.startswith("/api/"):
            return 404, "No endpoint found", "text/plain"
        if self.mode == "api_off":
            return 403, "Local API is not enabled", "text/plain"
        if self.mode == "old":
            return 404, "No endpoint found", "text/plain"
        m = re.match(r"^/api/(users/0|groups/(\d+))(/.*)$", path)
        if not m:
            return 400, "Bad user ID", "text/plain"
        lib = self.libraries.get("user" if m.group(1) == "users/0" else f"group-{m.group(2)}")
        if lib is None:
            return 404, "Not found", "text/plain"
        rest = m.group(3)
        top = [i for i in lib.items if not i["data"].get("parentItem")]
        if rest == "/groups":
            return 200, [{"id": int(g), "version": 1, "data": {"id": int(g), "name": n}} for g, n in self.groups.items()], ""
        if rest == "/collections":
            cols = []
            for c in lib.collections:
                n = sum(1 for i in top if c["key"] in i["data"].get("collections", []))
                cols.append({**c, "meta": {**c["meta"], "numItems": n}})
            return 200, self._page(cols, q), ""
        if rest == "/items/top":
            return 200, self._page([self._view(lib, i) for i in self._search(top, q)], q), ""
        if rest == "/items":
            items = lib.items
            if q.get("itemKey"):
                keys = set(q["itemKey"][0].split(","))
                items = [i for i in items if i["key"] in keys or i["data"].get("parentItem") in keys]
            if (q.get("itemType") or [""])[0] == "attachment":
                items = [i for i in items if i["data"]["itemType"] == "attachment"]
            return 200, self._page([self._view(lib, i) for i in items], q), ""
        mm = re.match(r"^/collections/([A-Z0-9]+)/items/top$", rest)
        if mm:
            return 200, self._page([self._view(lib, i) for i in self._search(top, q)
                                    if mm.group(1) in i["data"].get("collections", [])], q), ""
        mm = re.match(r"^/items/([A-Z0-9]+)/children$", rest)
        if mm:
            return 200, self._page([self._view(lib, i) for i in lib.items if i["data"].get("parentItem") == mm.group(1)],
                                   q), ""
        mm = re.match(r"^/items/([A-Z0-9]+)/file/view/url$", rest)
        if mm:
            it = next((i for i in lib.items if i["key"] == mm.group(1)), None)
            if not it or not it.get("_path"):
                return 404, "Not found", "text/plain"
            return 200, Path(it["_path"]).as_uri(), "text/plain"
        return 404, "No endpoint found", "text/plain"

    @staticmethod
    def _search(rows: list, q: dict) -> list:
        words = (q.get("q") or [""])[0].lower().split()
        if words:
            def text(i):
                d = i["data"]
                names = " ".join(c.get("name") or f'{c.get("lastName", "")} {c.get("firstName", "")}'
                                 for c in d.get("creators", []))
                return f'{d.get("title", "")} {names} {d.get("date", "")}'.lower()

            rows = [i for i in rows if all(w in text(i) for w in words)]
        if (q.get("sort") or [""])[0] == "title":
            rows = sorted(rows, key=lambda i: (i["data"].get("title") or "").lower(),
                          reverse=(q.get("direction") or [""])[0] == "desc")
        return rows

    @staticmethod
    def _view(lib: Library, it: dict) -> dict:
        out = {k: v for k, v in it.items() if not k.startswith("_")}
        n = sum(1 for i in lib.items if i["data"].get("parentItem") == it["key"])
        out["meta"] = {**it.get("meta", {}), "numChildren": n}
        out["library"] = {"type": "user", "id": 0, "name": lib.name}
        return out

    @staticmethod
    def _page(rows: list, q: dict) -> list:
        start = int((q.get("start") or ["0"])[0])
        limit = q.get("limit")
        return rows[start:start + int(limit[0])] if limit else rows[start:]

    # -- the server ------------------------------------------------------------------------
    def start(self) -> str:
        fake = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                u = urlparse(self.path)
                fake.requests.append(u.path)
                status, body, ctype = fake.answer(u.path, parse_qs(u.query))
                data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype or "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()


def demo_library(storage: Path, same_as: Path | None = None, make_pdf=None) -> FakeZotero:
    """The remote-work demo corpus as a researcher's Zotero would hold it (tools/dev_server.py --zotero): a
    collection with a subcollection; one work whose PDF is the very file in the project (linked by its checksum),
    three that are in the project without metadata (proposed by their title), one with a PDF in Zotero that is not in
    the project yet, and works still to find."""
    import shutil

    z = FakeZotero()
    lib = z.user
    rw = lib.collection("RWCOLL01", "Remote work")
    wb = lib.collection("WELLBE02", "Wellbeing", parent=rw)
    lib.collection("OTHER003", "Teaching")
    if same_as and same_as.exists():
        p = storage / "ATTPANEL" / same_as.name
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(same_as, p)
        lib.item("PANELST1", "Working from home and wellbeing: evidence from the Lowland Household Panel, 2019-2024",
                 creators=[("Verhoeven", "M."), ("Okafor", "A.")], date="2025", collections=[wb],
                 publicationTitle="Journal of Work and Society", DOI="10.5555/jws.2025.014")
        lib.attachment("ATTPANEL", "PANELST1", p)
    lib.item("HYBRIDR1", "Does hybrid work change productivity? A review of 27 studies",
             creators=[("Lindqvist", "C.")], date="2025", collections=[rw], type_="report",
             institution="Centre for Labour Studies")
    lib.item("COMMUTE1", "Commuting less, emitting less? A survey of 4,000 workers in the Rivermouth region",
             creators=["Rivermouth Mobility Institute"], date="2024", collections=[rw], type_="report")
    lib.item("YOUNGEM1", "“You never really meet anyone”: young employees on remote work",
             creators=[("Adeyemi", "T."), ("Brandt", "L.")], date="2024", collections=[wb], type_="report",
             institution="University of Easthaven")
    if make_pdf is not None:
        p = storage / "ATTFOURD" / "four_day_week_trial.pdf"
        p.parent.mkdir(parents=True, exist_ok=True)
        make_pdf(p, ["A four-day week in the public sector: results of a one-year trial\nS. Haugen, 2024\n\n"
                     "Summary. Sixty teams of a regional administration worked four days a week for a year at the same "
                     "pay. Sick leave fell by 18 percent, and staff reported less stress and better sleep. Service "
                     "levels were kept in most teams; two teams with front-desk work needed extra staff.",
                     "Results. Productivity per hour rose in 41 of 60 teams. Commuting fell by one day a week, which "
                     "cut the teams' commuting emissions by about a fifth."],
                 title="A four-day week in the public sector: results of a one-year trial")
        lib.item("FOURDAY1", "A four-day week in the public sector: results of a one-year trial",
                 creators=[("Haugen", "S.")], date="2024", collections=[rw], publicationTitle="Public Administration "
                 "Review", DOI="10.5555/par.2024.077")
        lib.attachment("ATTFOURD", "FOURDAY1", p)
    lib.item("OFFICEL1", "The office as a social place: why employees return", creators=[("Moreau", "J.")],
             date="2023", collections=[rw], publicationTitle="Organization Studies", DOI="10.5555/os.2023.212")
    lib.item("COWORK01", "Coworking spaces in small towns", creators=[("Peters", "R."), ("Ng", "K."), ("Silva", "D.")],
             date="2022", collections=[rw], type_="bookSection", bookTitle="Work After the Pandemic",
             url="https://example.org/coworking")
    lib.item("LONELY01", "Loneliness among young workers: a cohort study", creators=[("Okafor", "A.")], date="2023",
             collections=[wb], publicationTitle="Social Science & Medicine", DOI="10.5555/ssm.2023.0091")
    lib.item("SURVEY24", "Northbridge staff survey 2024", creators=["Municipality of Northbridge"], date="2024",
             collections=[rw], type_="report", extra="Annual staff survey")
    lib.item("TEACHNG1", "Teaching online after 2020", creators=[("Kim", "H.")], date="2021", collections=["OTHER003"])
    return z
