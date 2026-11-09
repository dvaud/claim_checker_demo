"""Projects, documents and the reading view: the endpoints of Handler for the documents of a project
(0.11 per-document AI settings, 0.15 the reading view, page images and tables, uploads).

Split out of server.py in 0.16: `Handler` takes this class as a base, so the names in ROUTES
still resolve on it."""
from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote

from .api_common import ApiError, MAX_UPLOAD, XLSX, _cell, _csv, _disposition, _filename, _float, _str, _text_with_quote, page_images_available, render_page
from .. import access, claimcheck, home, ingest


class DocumentsApi:
    def get_projects(self, q):
        return {"projects": [self.app.project_summary(n) for n in home.list_projects()]}

    def post_project(self, q):
        body = self._body()
        ws = home.create_project(str(body.get("name") or ""))
        home.update_settings({"project": ws.root.name})
        return {"project": self.app.project_summary(ws.root.name)}

    def post_link(self, q):
        body = self._body()
        name = home.link_existing(str(body.get("path") or ""), body.get("name") or None)
        home.update_settings({"project": name})
        return {"project": self.app.project_summary(name)}

    def get_project(self, name, q):
        return self.app.project(name)

    def delete_project(self, name, q):
        body = self._body()
        if body.get("confirm") != name:
            raise ApiError(400, "Confirm by sending the project's name as 'confirm'.")
        if name not in home.list_projects():
            raise ApiError(404, f"No project called {name!r}.")
        try:
            return {"result": home.remove_project(name)}
        except home.FolderInUse as e:  # 0.15.7 (Windows): said in words, not "something went wrong"
            raise ApiError(409, str(e)) from None

    def get_documents(self, name, q):
        return self.app.documents(name)

    def put_documents_access(self, name, q):
        body = self._body()
        ws = self.app.ws(name)
        ids = body.get("doc_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids):
            raise ApiError(400, "doc_ids must be a list of document ids.")
        kw = {}
        if "ai_access" in body:
            kw["setting"] = body.get("ai_access") or None
        if "note" in body:
            kw["note"] = body.get("note")
        if "budget" in body:
            kw["budget"] = body.get("budget")
        if not kw:
            raise ApiError(400, "Give ai_access, note or budget.")
        r = access.set_documents(ws, ids, **kw)
        return {**r, **self.app.documents(name)}

    def put_project_access(self, name, q):
        body = self._body()
        ws = self.app.ws(name)
        if body.get("default"):
            access.set_default(ws, body["default"])
        if body.get("dismiss_banner"):
            access.dismiss_banner(ws)
        return {"ai_access": access.project_info(ws)}

    def get_document_sent(self, name, doc_id, q):
        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)):
            raise ApiError(404, "No such document.")
        return access.document_ledger(ws, doc_id)

    def get_ai_sent_csv(self, name, q):
        rows = [{"Sent at": r["sent_at"], "Route": r["route"], "Feature": r["feature"], "Document": r["title"],
                 "Document id": r["doc_id"], "Passage id": r["passage_id"], "Page": r["page"] if r["page"] else "",
                 "Task": r["task_id"]} for r in access.ledger(self.app.ws(name))]
        if not rows:
            rows = [{"Sent at": "", "Route": "", "Feature": "", "Document": "Nothing has been sent to Claude from this "
                     "project.", "Document id": "", "Passage id": "", "Page": "", "Task": ""}]
        stem = _filename(f"ENLENS sent to Claude - {name} - {time.strftime('%Y-%m-%d')}", "csv")
        return self._send(200, _csv(rows), "text/csv; charset=utf-8", {"Content-Disposition": _disposition(stem)})

    def delete_documents(self, name, q):
        body = self._body()
        if body.get("confirm") is not True:
            raise ApiError(400, "Confirm with {\"confirm\": true}: this removes every document and every check.")
        ws = self.app.ws(name)
        pipeline = {"extracted claims": ws.scalar("SELECT COUNT(*) FROM claims"),
                    "VCA verifications": ws.scalar("SELECT COUNT(*) FROM verifications WHERE subject_kind != 'user_claim'"),
                    "pipeline tasks": ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind IN ('extract','verify','verify_set')")}
        held = ", ".join(f"{n:,} {what}" for what, n in pipeline.items() if n)
        if held:
            raise ApiError(409, f"This project also holds results of the SDG pipeline ({held}); removing all documents "
                                f"would delete them too. Remove documents one by one, or run `enlens --ws \"{ws.root}\" "
                                "reset-corpus --yes` if that is what you want.")
        removed = ws.reset_corpus()
        from .. import researchlog  # 0.16

        with ws.connect() as cx:
            researchlog.record(cx, "document-removed", f"Removed every document ({removed.get('documents', 0)}) and "
                                                       f"every check ({removed.get('hypotheses', 0)}).")
        return {"removed": removed}

    def get_document(self, name, doc_id, q):
        return self.app.document(name, doc_id, int(_float(q, "offset", 0)), int(_float(q, "limit", 50)),
                                 _str(q, "view") or "")

    def get_document_file(self, name, doc_id, q):
        """The original file of a document, for reading it as it looks (a PDF opens at #page=N in the browser)."""
        ws = self.app.ws(name)
        info = self.app.original(ws, doc_id)
        if _str(q, "check"):
            return {k: info[k] for k in ("doc_id", "kind", "name", "available", "reason")}
        if not info["available"]:  # say so plainly, and show the text the app read
            text = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc_id,)) or ""
            body = f"{info['reason']}\n\n{info['title'] or ''}\n\n{text}".encode()
            return self._send(200, body, "text/plain; charset=utf-8",
                              {"Content-Security-Policy": "default-src 'none'; sandbox"})
        path = Path(info["path"])
        ext = path.suffix.lower()
        disp = _disposition(info["name"] or path.name).replace("attachment;", "inline;", 1)
        if ext == ".pdf":
            return self._stream(path, "application/pdf", {"Content-Disposition": disp})
        if ext == ".docx":  # 0.8: a Word file opens in Word (or whatever the computer opens it with)
            return self._stream(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                {"Content-Disposition": disp.replace("inline;", "attachment;", 1)})
        if ext in (".html", ".htm"):  # no scripts, no internet, and a unique origin that cannot reach this app
            csp = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
            return self._stream(path, "text/html; charset=utf-8", {"Content-Security-Policy": csp,
                                                                     "Content-Disposition": disp})
        quote = _str(q, "quote")
        if quote and path.stat().st_size <= 20 * 1024 ** 2:  # a text file, with the quote marked: link to …#quote
            page = _text_with_quote(path, quote, info["name"] or path.name)
            if page is not None:
                return self._send(200, page, "text/html; charset=utf-8", {
                    "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'"})
        return self._stream(path, "text/plain; charset=utf-8", {"Content-Security-Policy": "default-src 'none'; sandbox",
                                                                "Content-Disposition": disp})

    def delete_document(self, name, doc_id, q):
        why = _str(q, "why") or self._body().get("why")  # 0.16: the reason, for the research log
        return {"removed": self.app.ws(name).remove_document(doc_id, why=str(why or "") or None)}

    def put_block(self, name, doc_id, n, q):
        body = self._body()
        if not isinstance(body.get("included"), bool):
            raise ApiError(400, "included must be true or false.")
        try:
            num = int(n)
        except ValueError:
            raise ApiError(404, "No such block in this document.") from None
        if "alike" in body and not isinstance(body["alike"], bool):
            raise ApiError(400, "alike must be true or false.")
        return self.app.set_block(name, doc_id, num, body["included"], bool(body.get("alike")))

    def put_bounds(self, name, doc_id, q):
        """0.15.1: {"side": "start"|"end", "block": n|null}: where the text starts or ends (null: no longer)."""
        body = self._body()
        side, n = body.get("side"), body.get("block")
        if n is not None and (isinstance(n, bool) or not isinstance(n, int)):
            raise ApiError(400, "block must be a block number or null.")
        return self.app.set_bound(name, doc_id, side, n)

    def get_reread(self, name, doc_id, q):
        """0.15 (A0): what *Read with the new reader* would do to this document, without doing it."""
        from .. import reread

        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)):
            raise ApiError(404, "No such document.")
        return reread.preview(ws, doc_id)  # {"ok": False, "reason"} when it cannot be done now

    def post_reread_document(self, name, doc_id, q):
        """0.15 (A0): read the document with the new reader and move its results with it (all or nothing)."""
        from .. import people, reread

        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)):
            raise ApiError(404, "No such document.")
        ok = reread.check(ws, doc_id)
        if not ok.get("ok"):
            raise ApiError(409, ok.get("reason") or "This document cannot be read again now.")
        busy = [j for j in self.app.jobs.jobs.values() if j.project == name and j.state in ("queued", "running")]
        if busy:
            raise ApiError(409, f"Wait until “{busy[0].title}” has finished in this project, then read the document "
                                "with the new reader.")
        return {"job": self.app.start_new_reader(name, doc_id, people.me()).view()}

    def post_new_reader_many(self, name, q):
        """0.15.7: read several documents with the new reader at once (the Documents page): `doc_ids`, or every
        document an earlier reader read. Each moves only when all its results find their place."""
        from .. import people

        ws = self.app.ws(name)
        body = self._body()
        older = [r["doc_id"] for r in ws.query("SELECT doc_id FROM documents WHERE COALESCE(reader, 1) < ? "
                                               "ORDER BY title", (ingest.READER,))]
        ids = body.get("doc_ids")
        if ids is not None:
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                raise ApiError(400, "doc_ids must be a list of document ids.")
            ids = [i for i in older if i in set(ids)]
        else:
            ids = older
        if not ids:
            raise ApiError(409, "Every document here was read by the current reader already: there is nothing to do.")
        busy = [j for j in self.app.jobs.jobs.values() if j.project == name and j.state in ("queued", "running")]
        if busy:
            raise ApiError(409, f"Wait until “{busy[0].title}” has finished in this project, then read the documents "
                                "with the new reader.")
        return {"job": self.app.start_new_reader_many(name, ids, people.me()).view()}

    def put_reading_checked(self, name, doc_id, q):
        """0.15.7: mark a document's reading as checked by the person (`checked`: true), or take that back."""
        body = self._body()
        if not isinstance(body.get("checked"), bool):
            raise ApiError(400, "checked must be true or false.")
        return self.app.set_reading_checked(name, doc_id, body["checked"])

    def get_page_image(self, name, doc_id, n, q):
        """The page of the original PDF as a picture (pypdfium2, from the OCR extra), to set beside the text."""
        ws = self.app.ws(name)
        info = self.app.original(ws, doc_id)
        if not info["available"] or (info.get("kind") or "") != "pdf":
            raise ApiError(404, info.get("reason") or "The original PDF is not available.")
        if not page_images_available():
            raise ApiError(404, "Pictures of pages need the OCR extra (pypdfium2), which is not installed.")
        try:
            page = int(n)
        except ValueError:
            raise ApiError(404, "No such page.") from None
        png = render_page(Path(info["path"]), page, min(3.0, max(0.5, _float(q, "scale", 1.5))))
        if png is None:
            raise ApiError(404, "No such page.")
        return self._send(200, png, "image/png", {"Cache-Control": "private, max-age=3600"})

    def get_table_export(self, name, doc_id, n, q):
        """A table found in a document, for Excel: its caption, then its rows of cells."""
        ws = self.app.ws(name)
        try:
            n = int(n)
        except ValueError:
            raise ApiError(404, "No such table in this document.") from None
        row = ws.query("SELECT t.caption, t.rows_json, t.page, d.title FROM doc_tables t JOIN documents d "
                       "ON d.doc_id=t.doc_id WHERE t.doc_id=? AND t.n=?", (doc_id, n))
        if not row:
            raise ApiError(404, "No such table in this document.")
        r = row[0]
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        sh = wb.active
        sh.title = f"Table {n}"[:31]
        sh.append([r["caption"] or f"Table {n}"])
        sh["A1"].font = Font(bold=True)
        sh.append([f"From: {r['title'] or ''}" + (f", page {r['page']}" if r["page"] else "")
                   + ". Read by ENLENS from the PDF: check the numbers against the original."])
        sh.append([])
        for cells in json.loads(r["rows_json"] or "[]"):
            sh.append([_cell(c) for c in cells])
        buf = io.BytesIO()
        wb.save(buf)
        fname = _filename(f"{(r['title'] or 'Document')[:60]} - table {n}", "xlsx")
        return self._send(200, buf.getvalue(), XLSX, {"Content-Disposition": _disposition(fname)})

    def _body_size(self) -> int:
        """The size of a raw upload, refused above MAX_UPLOAD (the connection is closed: the body is not read)."""
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            self.close_connection = True
            raise ApiError(413, "Files larger than 2 GB are not accepted.")
        return n

    def _save_body(self, target: Path, n: int, allow_empty: bool = False) -> None:
        """Stream the raw request body of `n` bytes into `target` (one copy of this for the three uploads, 0.11.1)."""
        self._consumed = True
        left = n
        with open(target, "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left or (not n and not allow_empty):
            target.unlink(missing_ok=True)
            raise ApiError(400, "The upload was cut off.")

    def post_upload(self, name, q):
        ws = self.app.ws(name)
        raw = _str(q, "name") or unquote(self.headers.get("X-Filename") or "") or "upload"  # each decoded once
        fname = re.split(r"[/\\]", raw)[-1]
        fname = re.sub(r'[\x00-\x1f<>:"|?*]', "_", fname).strip(" .") or "upload"
        if fname.startswith("."):
            fname = "_" + fname
        n = self._body_size()
        folder = home.upload_folder(ws, _str(q, "batch"))
        target = folder / fname
        if not target.resolve().is_relative_to(folder.resolve()):
            raise ApiError(400, "That file name is not accepted.")
        self._save_body(target, n, allow_empty=True)
        return {"batch": folder.name, "name": fname, "size": n}

    def post_ingest(self, name, q):
        return {"job": self.app.start_ingest(name, self._body()).view()}

    def post_index(self, name, q):
        return {"job": self.app.start_index(name).view()}

    def get_passage(self, name, passage_id, q):
        around = max(0, min(int(_float(q, "around", 1)), 5))
        return claimcheck.neighbours(self.app.ws(name), passage_id, around, around)
