"""Your record of the work (0.16): the endpoints of Handler for the research log (F4), notes and highlights (F2),
earlier versions to compare and restore (F5), and your own codebooks (K1).

`Handler` takes this class as a base, so the names in ROUTES resolve on it."""
from __future__ import annotations

import re

from .api_common import ApiError, XLSX, _bool, _disposition, _int, _str, _xlsx_with_provenance
from .. import codebooks, history, notes, researchlog


def _project_title(ws) -> str:
    return ws.root.name


class RecordApi:
    # -- the research log ------------------------------------------------------------------------
    def get_log(self, name, q):
        ws = self.app.ws(name)
        return researchlog.entries(ws, _str(q, "group"), _str(q, "q"), _str(q, "subject_kind"), _str(q, "subject_id"),
                                   _int(q, "offset", 0, 0, 10 ** 7), _int(q, "limit", 200, 1, 2000))

    def post_log(self, name, q):
        body = self._body()
        return {"entry": researchlog.add(self.app.ws(name), str(body.get("text") or ""), body.get("subject_kind") or None,
                                         body.get("subject_id") or None, body.get("title") or None)}

    def put_log(self, name, entry_id, q):
        body = self._body()
        text = body.get("text")
        why = body.get("why")
        return {"entry": researchlog.update(self.app.ws(name), entry_id, None if text is None else str(text),
                                            None if why is None else str(why))}

    def delete_log(self, name, entry_id, q):
        researchlog.remove(self.app.ws(name), entry_id)
        return {"deleted": entry_id}

    def get_log_export(self, name, fmt, q):
        ws = self.app.ws(name)
        base = f"research-log-{_safe(ws.root.name)}"
        if fmt == "md":
            body = researchlog.markdown(ws, _project_title(ws)).encode("utf-8")
            self._send(200, body, "text/markdown; charset=utf-8", {"Content-Disposition": _disposition(base + ".md")})
        else:
            body = _xlsx_with_provenance(ws, [("Research log", researchlog.table(ws))], task_ids=[])
            self._send(200, body, XLSX, {"Content-Disposition": _disposition(base + ".xlsx")})

    # -- notes and highlights -------------------------------------------------------------------
    def get_notes(self, name, q):
        return notes.search(self.app.ws(name), _str(q, "q"), _str(q, "doc"), _str(q, "colour"), _bool(q, "mine"),
                            _int(q, "offset", 0, 0, 10 ** 7), _int(q, "limit", 200, 1, 5000))

    def get_document_notes(self, name, doc_id, q):
        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)):
            raise ApiError(404, "No such document.")
        return {"notes": notes.for_document(ws, doc_id), "colours": list(notes.COLOURS)}

    def post_note(self, name, q):
        body = self._body()
        try:
            start, end = int(body.get("start")), int(body.get("end"))
        except (TypeError, ValueError):
            raise ApiError(400, "Select the words to note in the text.") from None
        return {"note": notes.add(self.app.ws(name), str(body.get("doc_id") or ""), start, end,
                                  body.get("quote") if isinstance(body.get("quote"), str) else None,
                                  str(body.get("text") or ""), str(body.get("colour") or "yellow"))}

    def put_note_item(self, name, note_id, q):
        body = self._body()
        text, colour = body.get("text"), body.get("colour")
        return {"note": notes.update(self.app.ws(name), note_id, None if text is None else str(text),
                                     None if colour is None else str(colour))}

    def delete_note_item(self, name, note_id, q):
        notes.remove(self.app.ws(name), note_id)
        return {"deleted": note_id}

    def post_note_evidence(self, name, note_id, q):
        body = self._body()
        return notes.use_as_evidence(self.app.ws(name), note_id, str(body.get("claim_id") or ""),
                                     str(body.get("verdict") or ""), body.get("comment") or None)

    def get_notes_export(self, name, fmt, q):
        ws = self.app.ws(name)
        base = f"notes-{_safe(ws.root.name)}"
        if fmt == "md":
            body = notes.markdown(ws, _project_title(ws)).encode("utf-8")
            self._send(200, body, "text/markdown; charset=utf-8", {"Content-Disposition": _disposition(base + ".md")})
        else:
            body = _xlsx_with_provenance(ws, [("Notes", notes.table(ws))], task_ids=[])
            self._send(200, body, XLSX, {"Content-Disposition": _disposition(base + ".xlsx")})

    # -- earlier versions -----------------------------------------------------------------------
    def get_versions(self, name, kind, key, q):
        ws = self.app.ws(name)
        if kind == "codebook":
            codebooks.follow(ws, key)
        return history.versions(ws, kind, key)

    def get_version(self, name, kind, key, version_id, q):
        return history.compare(self.app.ws(name), kind, key, version_id)

    def post_restore(self, name, kind, key, version_id, q):
        self._body()
        return history.restore(self.app.ws(name), kind, key, version_id)

    # -- codebooks ------------------------------------------------------------------------------
    def get_codebooks(self, name, q):
        return codebooks.list_all(self.app.ws(name))

    def post_codebook(self, name, q):
        body = self._body()
        source = body.get("source") if isinstance(body.get("source"), dict) else {}
        return {"codebook": codebooks.create(self.app.ws(name), str(body.get("name") or ""),
                                             str(body.get("title") or ""), str(body.get("where") or "project"),
                                             str(body.get("start") or "fresh"), source,
                                             str(body.get("label") or "code"))}

    def get_codebook_sources(self, name, q):
        return {"runs": codebooks.theme_sources(self.app.ws(name), _bool(q, "all"))}

    def post_codebook_example(self, name, q):
        body = self._body()
        got = codebooks.find_example(self.app.ws(name), str(body.get("quote") or ""), body.get("doc_id") or None)
        if not got:
            raise ApiError(400, "These words are not in this project's documents. Copy an example from a document, "
                                "word for word (at least a few words).")
        return {"example": got}

    def get_codebook(self, name, cb, q):
        return {"codebook": codebooks.load(self.app.ws(name), cb)}

    def put_codebook(self, name, cb, q):
        body = self._body()
        state = body.get("codebook")
        if not isinstance(state, dict):
            raise ApiError(400, "Send the codebook as {\"codebook\": {...}}.")
        merges = body.get("merges") if isinstance(body.get("merges"), list) else []
        return codebooks.save(self.app.ws(name), cb, state, merges, str(body.get("why") or "") or None)

    def post_codebook_clash(self, name, cb, uid, q):
        """0.18: keep your version of a code you and a colleague both changed, or theirs (sync/codebook_merge.py)."""
        body = self._body()
        return {"codebook": codebooks.settle_clash(self.app.ws(name), cb, uid, str(body.get("keep") or ""),
                                                   str(body.get("why") or "") or None)}

    def delete_codebook(self, name, cb, q):
        why = _str(q, "why") or self._body().get("why")
        codebooks.remove(self.app.ws(name), cb, str(why or "") or None)
        return {"deleted": cb}

    def post_codebook_move(self, name, cb, q):
        return {"codebook": codebooks.move(self.app.ws(name), cb, str(self._body().get("to") or ""))}

    def post_codebook_copy_here(self, name, cb, q):
        self._body()
        return {"codebook": codebooks.copy_here(self.app.ws(name), cb)}

    def post_codebook_try(self, name, cb, q):
        body = self._body()
        ws = self.app.ws(name)
        state = body.get("codebook") if isinstance(body.get("codebook"), dict) else codebooks.state_of(ws, cb)

        def run(job):
            job.progress = {"done": 0, "total": 0}
            return codebooks.try_codes(ws, state, progress=lambda d, n: job.progress.update(done=d, total=n))

        job = self.app.jobs.start("codebook-try", f"Trying the codebook ({cb})", name, run, uses_model=False)
        job.scope = cb
        return {"job": job.view()}

    def post_codebook_relabel(self, name, cb, q):
        body = self._body()
        ws = self.app.ws(name)
        code = str(body.get("code") or "")
        pids = codebooks.relabel_passages(ws, cb, code)
        if not pids:
            raise ApiError(409, "No passage of this code was labelled with its earlier wording.")
        return {"passages": len(pids),
                "job": self.app.start_labels(name, {"framework": cb, "passage_ids": pids}).view()}

    def get_codebook_csv(self, name, cb, q):
        fname, body = codebooks.csv_of(self.app.ws(name), cb)
        self._send(200, body, "text/csv; charset=utf-8", {"Content-Disposition": _disposition(fname)})


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")[:60] or "project"

