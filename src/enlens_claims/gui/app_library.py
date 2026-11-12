"""The bibliography, search, profiles and concepts of the app (App's 0.13 and 0.7 sections).

Split out of server.py in 0.16: `App` takes this class as a base; the public methods are the same."""
from __future__ import annotations

import json
import traceback

from .api_common import ONE_START, ApiError, Job, _usable_embedder
from .. import bibliography, embed, frameworks, home
from ..llm import BackendError
from ..store import now as _now


class LibraryMixin:
    # -- 0.13: the bibliography (Zotero, or an exported file) -----------------------------------------------------
    def start_bibliography(self, name: str, body: dict) -> Job:
        ws = self.ws(name)
        z, f = body.get("zotero"), body.get("file")
        if body.get("update"):
            src = ws.meta("bibliography") or {}
            if src.get("kind") != "zotero":
                raise ApiError(400, "Only a bibliography read from Zotero can be updated: for a file, add the newer "
                                    "file instead.")
            z = {"library": src.get("library"), "collection": src.get("collection"),
                 "subcollections": src.get("subcollections", True), "items": src.get("items")}

        def progress(job: Job):
            return lambda **kw: setattr(job, "progress", kw)

        if isinstance(f, dict):
            fname = str(f.get("name") or "bibliography")[:200]
            fmt, works = bibliography.parse_file(fname, str(f.get("text") or ""))
            if not works:
                raise ApiError(400, f"No works were found in {fname}.")

            def run(job: Job):
                return bibliography.save(ws, works, {"kind": "file", "name": fname, "format": fmt},
                                         progress=progress(job))
        elif isinstance(z, dict):
            library = str(z.get("library") or "user")
            collection = str(z["collection"]) if z.get("collection") else None
            if not bibliography.LIBRARY_RE.match(library) or (collection and not bibliography.KEY_RE.match(collection)):
                raise ApiError(400, "Choose a library and a collection of your Zotero.")
            items = z.get("items")  # 0.13.9: the works chosen one by one (their Zotero keys)
            if items is not None and (not isinstance(items, list) or not 0 < len(items) <= bibliography.MAX_CHOSEN
                                      or not all(isinstance(k, str) and bibliography.KEY_RE.match(k) for k in items)):
                raise ApiError(400, f"Choose between 1 and {bibliography.MAX_CHOSEN} works of your Zotero.")

            def run(job: Job):
                works, src = bibliography.pull_zotero(library, collection, bool(z.get("subcollections", True)),
                                                      progress=progress(job), should_stop=job.cancel.is_set,
                                                      items=items)
                if job.cancel.is_set():
                    return None
                libs = {x["id"]: x["name"] for x in bibliography.zotero_status().get("libraries") or []}
                src["library_name"] = libs.get(library) or ("My Library" if library == "user" else "Group library")
                return bibliography.save(ws, works, src, progress=progress(job))
        else:
            raise ApiError(400, "Choose a Zotero collection or an exported file.")
        return self.jobs.start("bibliography", "Bringing in the bibliography", name, run, uses_model=False)

    def start_bibliography_files(self, name: str, body: dict) -> Job:
        """Add the files the bibliography has (Zotero's PDFs) for works without a document: read where they are."""
        ws = self.ws(name)
        keys = body.get("item_keys")
        paths = bibliography.files_to_add(ws, [str(k) for k in keys] if isinstance(keys, list) else None)
        if not paths:
            raise ApiError(400, "There is no file to add: every work with a file in Zotero has its document already.")
        return self.start_ingest(name, {"ai_access": body.get("ai_access"), "ai_note": body.get("ai_note")}, paths,
                                 "Adding Zotero's files")

    def _after_adding(self, ws, job: Job, stats: dict, new_docs: list[str], s: dict) -> None:
        """After documents are added (0.7): the glossary (F3) is rebuilt and the codebook's keyword pass (F2) reads
        the new documents. Neither uses the chat model; a problem with either is reported, not fatal."""
        from .. import profile, terms

        emb = _usable_embedder(ws, home.make_embedder(s))
        job.progress = {"done": 0, "total": 0, "file": "", "phase": "glossary"}
        try:
            stats["glossary"] = terms.build(ws, progress=lambda d, n: job.progress.update(done=d, total=n),
                                            should_stop=job.cancel.is_set, embedder=emb)
        except BackendError as e:
            stats["glossary_error"] = str(e)
        if job.cancel.is_set():
            return
        job.progress = {"done": 0, "total": 0, "file": "", "phase": "codes"}
        fw = s.get("profile_framework") or "sdg"
        try:
            frameworks.get(fw, ws)
            stats["codes"] = profile.keyword_pass(ws, fw, emb, doc_ids=new_docs if profile.pass1_status(ws, fw)["done"]
                                                  else None, progress=lambda d, n: job.progress.update(done=d, total=n))
        except (ValueError, BackendError) as e:
            stats["codes_error"] = str(e)

    def start_new_reader(self, name: str, doc_id: str, person: str) -> Job:
        """0.15 (A0): a document moved to the new reader, then what adding a document does: its search by meaning, the
        glossary and the codebook's keyword pass. The move itself is one transaction (reread.move)."""
        from .. import reread

        ws = self.ws(name)
        s = self.settings()
        title = ws.scalar("SELECT title FROM documents WHERE doc_id=?", (doc_id,)) or "a document"

        def run(job: Job):
            job.progress = {"done": 0, "total": 0, "file": title, "phase": "reading"}
            if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)):  # removed while the move waited
                raise ValueError("This document was removed while its move waited its turn: nothing was moved.")
            # said in words for a researcher, and nothing changed, when it cannot be done now (0.18: a ValueError, so
            # the job's error is these words, also after the move waited its turn and something changed meanwhile)
            report = reread.move(ws, doc_id, person)
            stats = {"report": report}
            emb = home.make_embedder(s)
            if emb is not None and not job.cancel.is_set():
                job.progress = {"done": 0, "total": 0, "file": "", "phase": "embedding"}
                try:
                    stats["semantic_index"] = embed.build(ws, emb, progress=lambda d, n: job.progress.update(done=d, total=n),
                                                          should_stop=job.cancel.is_set)
                except BackendError as e:
                    stats["semantic_index_error"] = str(e)
            if not job.cancel.is_set():
                self._after_adding(ws, job, stats, [doc_id], s)
            return stats

        with ONE_START:  # 0.18 (M6): this document's move waits or runs already: that one, not a second
            same = [j for j in self.jobs.all() if j.kind == "reread" and j.lane == "reader" and j.project == name
                    and j.scope == doc_id and j.state in ("queued", "running")]
            if same:
                return same[0]
            return self.jobs.start("reread", f"Reading “{title[:60]}” with the new reader", name, run,
                                   uses_model=False, lane="reader", scope=doc_id)  # it runs alone in its project

    def start_new_reader_preview(self, name: str, doc_ids: list[str]) -> Job:
        """0.18 (M7): the dry run before moving several documents: each is read again by the current reader (nothing is
        stored) and the job says, per document, how many results would find no place and which. Counts first, so the
        person knows beforehand how many documents move cleanly; the `not_placed` lists feed one combined review."""
        from .. import reread

        ws = self.ws(name)
        titles = {r["doc_id"]: r["title"] or "" for r in ws.query("SELECT doc_id, title FROM documents")}

        def run(job: Job):
            docs = []
            for i, doc_id in enumerate(doc_ids):
                if job.cancel.is_set():
                    break
                title = titles.get(doc_id, "")
                job.progress = {"done": i, "total": len(doc_ids), "file": title, "phase": "checking"}
                entry = {"doc_id": doc_id, "title": title, "ok": True, "reason": None, "results": 0, "no_place": 0,
                         "not_placed": [], "left_out": 0}
                try:
                    rep = reread.preview(ws, doc_id, should_stop=job.cancel.is_set)
                except Exception as e:  # noqa: BLE001 - one document's fault does not stop the others
                    traceback.print_exc()
                    rep = {"ok": False, "reason": f"It could not be read again ({e}). Nothing was changed."}
                if not rep.get("ok"):
                    entry.update(ok=False, reason=rep.get("reason") or "It cannot be read again now.")
                else:
                    lost = rep.get("not_placed") or []
                    placed = sum(c.get("moved", 0) for k, c in (rep.get("counts") or {}).items() if k != "theme_member")
                    entry.update(results=placed + len(lost), no_place=len(lost), left_out=len(rep.get("left_out") or []),
                                 not_placed=[{k: x.get(k) for k in ("kind_text", "what", "quote", "page", "where",
                                                                    "left_out_kind", "why")} for x in lost])
                docs.append(entry)
            job.progress = {"done": len(docs), "total": len(doc_ids), "file": "", "phase": "checking"}
            clean = [d for d in docs if d["ok"] and not d["no_place"]]
            losing = [d for d in docs if d["ok"] and d["no_place"]]
            return {"documents": docs, "stopped": job.cancel.is_set(),
                    "summary": {"documents": len(docs), "clean": len(clean), "would_lose": len(losing),
                                "cannot": len([d for d in docs if not d["ok"]]),
                                "results_without_place": sum(d["no_place"] for d in losing)}}

        n = len(doc_ids)
        return self.jobs.start("new_reader_preview", f"Checking {n} {'document' if n == 1 else 'documents'} for the new reader",
                               name, run, uses_model=False)

    def start_new_reader_many(self, name: str, doc_ids: list[str], person: str, keep_unplaced: bool = False) -> Job:
        """0.15.7: several documents moved to the new reader in one job, from the Documents page, each all or nothing
        (reread.move). A document where any result would find no place is left as it is (`keep_all`), and so is one
        that cannot be read again now; both are listed with the reason, to be moved from their own page after its
        preview. Then, once for all of them, what adding documents does (search by meaning, glossary, codes)."""
        from .. import reread

        ws = self.ws(name)
        s = self.settings()
        titles = {r["doc_id"]: r["title"] or "" for r in ws.query("SELECT doc_id, title FROM documents")}

        def run(job: Job):
            moved, kept = [], []
            for i, doc_id in enumerate(doc_ids):
                if job.cancel.is_set():
                    break
                title = titles.get(doc_id, "")
                job.progress = {"done": i, "total": len(doc_ids), "file": title, "phase": "reading"}
                try:
                    r = reread.move(ws, doc_id, person, keep_all=not keep_unplaced)
                except reread.WouldLose as e:
                    kept.append({"doc_id": doc_id, "title": title, "reason": str(e),
                                 "not_placed": len(e.report.get("not_placed") or [])})
                    continue
                except ValueError as e:  # it cannot be read again now: in words for a researcher
                    kept.append({"doc_id": doc_id, "title": title, "reason": str(e), "cannot": True})
                    continue
                except Exception as e:  # noqa: BLE001 - one document's fault does not stop the others; nothing changed
                    traceback.print_exc()
                    kept.append({"doc_id": doc_id, "title": title, "reason": f"It could not be read again ({e}). "
                                 "Nothing was changed.", "cannot": True})
                    continue
                moved.append({"doc_id": doc_id, "title": title,
                              "results": sum(c.get("moved", 0) for c in (r.get("counts") or {}).values()),
                              "left_out": len(r.get("left_out") or []), "no_place": len(r.get("not_placed") or [])})
            job.progress = {"done": len(moved) + len(kept), "total": len(doc_ids), "file": "", "phase": "reading"}
            stats = {"moved": moved, "kept": kept, "stopped": job.cancel.is_set(),
                     "summary": {"moved": len(moved), "left_as_they_were": len(kept),
                                 "results_moved": sum(m["results"] for m in moved),
                                 "results_without_place": sum(m["no_place"] for m in moved),
                                 "moved_anyway": bool(keep_unplaced)}}
            if moved:  # the moves are kept even when the job is stopped: each was complete on its own
                emb = home.make_embedder(s)
                if emb is not None and not job.cancel.is_set():
                    job.progress = {"done": 0, "total": 0, "file": "", "phase": "embedding"}
                    try:
                        stats["semantic_index"] = embed.build(ws, emb, progress=lambda d, n: job.progress.update(
                            done=d, total=n), should_stop=job.cancel.is_set)
                    except BackendError as e:
                        stats["semantic_index_error"] = str(e)
                if not job.cancel.is_set():
                    self._after_adding(ws, job, stats, [m["doc_id"] for m in moved], s)
            return stats

        n = len(doc_ids)
        return self.jobs.start("new_reader", f"Reading {n} {'document' if n == 1 else 'documents'} with the new reader",
                               name, run, uses_model=False)

    def set_reading_checked(self, name: str, doc_id: str, checked: bool) -> dict:
        """0.15.7: the person looked at what a document's reading report asks them to check and found the reading good
        enough (or takes that back). Kept in the reading report itself, so a new reading of the document asks again."""
        from .. import people

        ws = self.ws(name)
        with ws.connect() as cx:
            row = cx.execute("SELECT reading_json FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
            if row is None:
                raise ApiError(404, "No such document.")
            try:
                rep = json.loads(row[0]) if row[0] else {}
            except ValueError:
                rep = {}
            if not rep:
                raise ApiError(409, "This document has no reading report to mark: it was read before 0.15.")
            if checked:
                rep["checked"] = {"by": people.me(), "name": people.my_name(), "at": _now()}
            else:
                rep.pop("checked", None)
            cx.execute("UPDATE documents SET reading_json=? WHERE doc_id=?", (json.dumps(rep, ensure_ascii=False), doc_id))
        return {"checked": rep.get("checked")}

    def start_index(self, name: str) -> Job:
        ws = self.ws(name)
        emb = home.make_embedder(self.settings())
        if emb is None:
            raise ApiError(400, "Choose a model for search by meaning first (Settings → Documents, where Ollama can download nomic-embed-text).")

        def run(job: Job):
            job.progress = {"done": 0, "total": 0}
            return embed.build(ws, emb, progress=lambda d, n: job.progress.update(done=d, total=n),
                               should_stop=job.cancel.is_set)

        return self.jobs.start("index", f"Semantic index with {emb.model}", name, run, uses_model=False,
                               unique=True)  # 0.17: a second press attaches to the running job


    # -- 0.7: search, profiles, concepts, themes, references, highlights, quick look -----------------
    def _embedder_for(self, ws):
        s = self.settings()
        if s.get("embed_backend") == "off":
            return None
        try:
            return _usable_embedder(ws, home.make_embedder(s))
        except BackendError:
            return None

    MODEL_JOB_KINDS = {"label": ("label",), "link": ("link",), "wordings": ("expand",), "theme-names": ("theme",),
                       "resolve": ("resolve",)}  # the task kinds Stop withdraws from the queue; others: none

    def start_queued_job(self, kind: str, title: str, name: str, fn, steps=("grade",),
                         withdraw: tuple[str, ...] | None = None) -> Job:
        """A job that uses the chat model: progress as done/total, the model's own progress, Stop. By queue (0.8)
        the progress also says what waits for Claude Code, and the job is "not running" while nothing answers.

        `fn(job, backend, model, progress)` does the work; `progress(done, total)` updates the bar. Stop takes the
        tasks of the kinds in `withdraw` that wait in the queue back out (0.13.6: public; `_model_job` before)."""
        be, model = self.backend()  # one context length for every kind: Ollama never reloads the model

        def run(job: Job):
            job.progress = {"done": 0, "total": 0}
            self._wire(job, be)
            if hasattr(be, "progress"):
                be.progress = lambda info: job.progress.update(queue=info) if info.get("phase") == "queue" else \
                    job.progress.update(model=info)
            return fn(job, be, model, lambda d, n: job.progress.update(done=d, total=n))

        return self.start_job(kind, title, name, run,
                              withdraw=self.MODEL_JOB_KINDS.get(kind, ()) if withdraw is None else tuple(withdraw),
                              ws=self._ws_or_none(name))

    _model_job = start_queued_job  # the name before 0.13.6

    def _ws_or_none(self, name: str | None):
        try:
            return self.ws(name) if name else None
        except ApiError:
            return None
