"""Looking around: the endpoints of Handler for search, collocates, profiles, terms and concepts, themes,
references, the annotated documents and FlexiConc, and the frameworks (codebooks).

Split out of server.py in 0.16: `Handler` takes this class as a base, so the names in ROUTES
still resolve on it."""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import unquote

from .api_common import ApiError, XLSX, _bool, _csv, _disposition, _filename, _float, _int, _list, _str, _xlsx_with_provenance
from .. import frameworks, home, sync


class ExploreApi:
    def get_frameworks(self, name, q):
        ws = self.app.ws(name)
        return {"frameworks": [fw.info() for fw in frameworks.available(ws).values()], "problems": frameworks.problems(ws)}

    def post_framework(self, name, q):
        body = self._body()
        fw = frameworks.save(self.app.ws(name), str(body.get("name") or ""), str(body.get("csv") or ""),
                             body.get("title") or None, body.get("label") or None, bool(body.get("directional")))
        return {"framework": fw.info()}

    def get_framework(self, name, fw_name, q):
        fw = frameworks.get(fw_name, self.app.ws(name))
        return {"framework": fw.info(with_codes=True)}

    def delete_framework(self, name, fw_name, q):
        if fw_name in frameworks.BUNDLED:
            raise ApiError(400, "The SDG codebooks ship with the app and cannot be removed.")
        frameworks.delete(self.app.ws(name), fw_name)
        return {"deleted": fw_name}

    def post_quicklook(self, q):
        """One document (raw body, ?name=file name) becomes a temporary project; returns the project and its job."""
        import tempfile

        raw = _str(q, "name") or unquote(self.headers.get("X-Filename") or "") or "document.pdf"
        fname = re.split(r"[/\\]", raw)[-1] or "document.pdf"
        if not re.search(r"\.(pdf|docx|html?|txt|md)$", fname, re.I):
            raise ApiError(400, "A quick look reads one PDF, Word (.docx), web page (HTML), text or Markdown file.")
        n = self._body_size()
        with tempfile.TemporaryDirectory(prefix="enlens-quick-") as tmp:
            path = Path(tmp) / "upload"
            self._save_body(path, n)
            name, job = self.app.start_quicklook(fname, path)
        return {"project": self.app.project_summary(name), "job": job.view()}

    def post_keep(self, name, q):
        self._body()
        self.app.ws(name)
        return {"kept": home.keep_project(name), "project": self.app.project_summary(name)}

    def _search_args(self, q) -> dict:
        return {"mode": _str(q, "mode") or "any", "docs": _list(q, "docs"), "exact": _bool(q, "exact"),
                "near": _int(q, "near", 5, 1, 50), "all_sections": _bool(q, "all"), "code": _str(q, "code")}

    def get_search(self, name, q):
        from .. import concordance

        ws = self.app.ws(name)
        text = _str(q, "q") or ""
        if (_str(q, "mode") or "") == "meaning":
            emb = self.app._embedder_for(ws)
            if emb is None:
                raise ApiError(400, "Search by meaning is not set up for this project (Settings → Advanced).")
            return concordance.meaning(ws, text, emb, k=_int(q, "limit", 20, 1, 100), docs=_list(q, "docs"))
        return concordance.search(ws, text, sort=_str(q, "sort") or "doc", offset=_int(q, "offset", 0, 0, 10 ** 7),
                                  limit=_int(q, "limit", 200, 1, 1000), width=_int(q, "width", 60, 20, 300),
                                  **self._search_args(q))

    def get_search_export(self, name, fmt, q):
        from .. import concordance

        ws = self.app.ws(name)
        text = _str(q, "q") or ""
        res = concordance.search(ws, text, sort=_str(q, "sort") or "doc", offset=0, limit=None, **self._search_args(q))
        rows = concordance.table(res)
        stem = _filename(f"ENLENS search - {text[:40]}", fmt)
        if fmt == "xlsx":
            col = concordance.collocates(ws, text, **{k: v for k, v in self._search_args(q).items()})
            body = _xlsx_with_provenance(ws, [("Lines", rows), ("Per document", [
                {"Document": d["title"], "Hits": d["hits"], "Passages": d["passages"]} for d in res["per_doc"]]),
                ("Words around it", [{"Word": w["word"], "Near the hits": w["count"], "In the corpus": w["corpus"],
                                      "PMI": w["pmi"]} for w in col["words"]])], task_ids=[])
            return self._send(200, body, XLSX, {"Content-Disposition": _disposition(stem)})
        return self._send(200, _csv(rows), "text/csv; charset=utf-8", {"Content-Disposition": _disposition(stem)})

    def get_collocates(self, name, q):
        from .. import concordance

        order = _str(q, "order") or "typical"
        if order not in ("typical", "often"):
            raise ApiError(400, "order must be typical or often.")
        return concordance.collocates(self.app.ws(name), _str(q, "q") or "", window=_int(q, "window", 5, 1, 15),
                                      order=order, **self._search_args(q))

    def _fw(self, ws, q) -> str:
        fw = _str(q, "framework") or self.app.settings().get("profile_framework") or "sdg"
        frameworks.get(fw, ws)
        return fw

    def get_profile(self, name, q):
        from .. import profile

        from .. import codebooks

        ws = self.app.ws(name)
        fw = self._fw(ws, q)
        level = _str(q, "level") or "code"
        if level not in ("code", "group"):
            raise ApiError(400, "level must be code or group.")
        codebooks.follow(ws, fw)  # 0.16: labels follow the codebook's renames and merges
        out = {"framework": fw, "pass1": profile.pass1_status(ws, fw), "frameworks": [f.info() for f in
                                                                                      frameworks.available(ws).values()],
               # 0.16: codes taken out whose labels wait, and codes the AI labelled with an earlier wording
               "removed_codes": [{"code": r["code"], "labels": r["labels"]} for r in codebooks.removed_codes(ws, fw)],
               "stale_codes": codebooks.stale(ws, fw)}
        if out["pass1"]["done"]:
            docs = _list(q, "docs")
            # 0.16: the labels that count are worked out once for the grid and the counts when both are of every
            # document (they were worked out twice on each visit of the page)
            labs = profile.effective(ws, fw, light=True) if not docs else None
            out["grid"] = profile.grid(ws, fw, docs, level, labs=labs)
            out["stats"] = profile.stats(ws, fw, labs=labs)
            out["read_by_model"] = int(ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='label' AND status='done' AND "
                                                 "substr(task_id, 1, ?) = ?", (len(f"label:{fw}:"), f"label:{fw}:")) or 0)
        return out

    def get_profile_plan(self, name, q):
        return self.app.label_plan(name, q)

    def post_profile_keywords(self, name, q):
        return {"job": self.app.start_keyword_pass(name, self._body()).view()}

    def post_profile_label(self, name, q):
        return {"job": self.app.start_labels(name, self._body()).view()}

    def post_profile_compare(self, name, q):
        return {"job": self.app.start_label_compare(name, self._body()).view()}

    def get_profile_calibration(self, name, q):
        from .. import profile

        ws = self.app.ws(name)
        return profile.calibration(ws, _str(q, "framework"))

    def get_profile_export(self, name, q):
        from .. import profile
        from ..terms import key_terms_table

        ws = self.app.ws(name)
        fw = self._fw(ws, q)
        level = _str(q, "level") or "code"
        g = profile.grid(ws, fw, _list(q, "docs"), level if level in ("code", "group") else "code")
        sheets = [("Documents by code", profile.grid_table(g)), ("Labels", profile.labels_table(ws, fw, _list(q, "docs"))),
                  ("Key terms per document", key_terms_table(ws))]
        body = _xlsx_with_provenance(ws, sheets, kinds=("label",))
        fname = _filename(f"ENLENS profile - {name} - {fw} - {time.strftime('%Y-%m-%d')}", "xlsx")
        return self._send(200, body, XLSX, {"Content-Disposition": _disposition(fname)})

    def get_document_profile(self, name, doc_id, q):
        from .. import profile

        from .. import codebooks

        ws = self.app.ws(name)
        fw = self._fw(ws, q)
        codebooks.follow(ws, fw)  # 0.16: labels follow the codebook's renames and merges
        return profile.doc_profile(ws, fw, doc_id)

    def post_label(self, name, q):
        from .. import profile

        body = self._body()
        ws = self.app.ws(name)
        lid = profile.add_label(ws, str(body.get("framework") or "sdg"), str(body.get("passage_id") or ""),
                                str(body.get("code") or ""), body.get("quote") or None,
                                str(body.get("relevance") or "main"), str(body.get("direction") or "not_stated"),
                                body.get("note"))
        return {"label_id": lid}

    def put_label(self, name, label_id, q):
        from .. import profile

        body = self._body()
        profile.set_label(self.app.ws(name), label_id, str(body.get("decision") or ""), body.get("relevance") or None,
                          body.get("direction") or None, body.get("note"))
        return {"saved": True}

    def get_terms(self, name, q):
        from .. import terms

        return terms.glossary(self.app.ws(name), _str(q, "q"), _int(q, "offset", 0, 0, 10 ** 7),
                              _int(q, "limit", 100, 1, 500), _str(q, "sort") or "docs")

    def post_terms_build(self, name, q):
        self._body()
        return {"job": self.app.start_terms(name).view()}

    def get_concept_lookup(self, name, q):
        from .. import terms

        ws = self.app.ws(name)
        text = _str(q, "name") or ""
        tid = terms.find_term(ws, text) if text.strip() else None
        if not tid:
            raise ApiError(404, f"No term of the glossary matches {text!r}.")
        return {"term_id": tid}

    def get_concept(self, name, term, q):
        from .. import terms

        return terms.card(self.app.ws(name), term, _int(q, "offset", 0, 0, 10 ** 7), _int(q, "limit", 50, 1, 500),
                          with_references=_bool(q, "refs"))

    def put_concept_link(self, name, q):
        from .. import terms

        body = self._body()
        terms.set_link(self.app.ws(name), str(body.get("a") or ""), str(body.get("b") or ""),
                       str(body.get("decision") or ""), body.get("relation") or None, note=body.get("note"))
        return {"saved": True}

    def post_concepts_judge(self, name, q):
        return {"job": self.app.start_judge_links(name, self._body()).view()}

    def post_concept_wordings(self, name, term, q):
        self._body()
        return {"job": self.app.start_wordings(name, term).view()}

    def get_document_terms(self, name, doc_id, q):
        from .. import terms

        ws = self.app.ws(name)
        return {**terms.key_term_spans(ws, doc_id, _int(q, "n", 15, 1, 50)), "status": terms.status(ws)}

    def get_passage_terms(self, name, passage_id, q):
        from .. import terms

        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM passages WHERE passage_id=?", (passage_id,)):
            raise ApiError(404, "No such passage.")
        return {"terms": terms.key_terms(ws, passage_id=passage_id, n=_int(q, "n", 5, 1, 20))}

    def get_themes(self, name, q):
        from .. import themes

        ws = self.app.ws(name)
        s = self.app.settings()
        emb = home.make_embedder(s)
        try:
            mode, why = themes.choose_mode(ws, "auto", getattr(emb, "model", None))
        except ValueError as e:
            mode, why = "words", str(e)
        runs = themes.runs(ws)
        clash = sync.copies_of(ws, "themes")  # 0.14: a colleague's version of a run you both changed
        for r in runs:
            r["clash"] = clash.get(r["run_id"])
        return {"runs": runs, "auto_mode": mode, "auto_why": why, "k": s.get("themes_k") or 20}

    def post_themes(self, name, q):
        return {"job": self.app.start_themes(name, self._body()).view()}

    def get_theme_run(self, name, run_id, q):
        from .. import themes

        ws = self.app.ws(name)
        fw = _str(q, "framework")
        if fw:
            frameworks.get(fw, ws)
        return themes.view(ws, run_id, fw)

    def delete_theme_run(self, name, run_id, q):
        from .. import themes

        why = _str(q, "why") or self._body().get("why")  # 0.16: the reason, for the research log
        themes.delete_run(self.app.ws(name), run_id, why=str(why or "") or None)
        return {"deleted": run_id}

    def get_themes_export(self, name, run_id, q):
        from .. import themes

        ws = self.app.ws(name)
        fw = _str(q, "framework")
        sheets = themes.tables(ws, run_id, fw)
        body = _xlsx_with_provenance(ws, sheets, task_ids=[r[0] for r in ws.query(
            "SELECT task_id FROM tasks WHERE kind='theme' AND substr(task_id, 1, ?) = ?", (len(f"theme:{run_id}:"),
                                                                                         f"theme:{run_id}:"))])
        fname = _filename(f"ENLENS themes - {name} - {time.strftime('%Y-%m-%d')}", "xlsx")
        return self._send(200, body, XLSX, {"Content-Disposition": _disposition(fname)})

    def put_theme_edit(self, name, run_id, q):
        from .. import themes

        body = self._body()
        tid = body.get("theme_id")
        themes.edit(self.app.ws(name), run_id, str(body.get("what") or ""), int(tid) if tid is not None else None,
                    body.get("value"), body.get("passage_id") or None, reason=str(body.get("why") or "") or None)
        return {"saved": True}

    def post_theme_names(self, name, run_id, q):
        self._body()
        return {"job": self.app.start_theme_names(name, run_id).view()}

    def post_new_theme(self, name, run_id, q):
        return {"job": self.app.start_new_theme(name, run_id, self._body()).view()}

    def get_theme(self, name, run_id, theme_id, q):
        from .. import themes

        try:
            tid = int(theme_id)
        except ValueError:
            raise ApiError(404, "No such theme.") from None
        return themes.theme_passages(self.app.ws(name), run_id, tid, _int(q, "offset", 0, 0, 10 ** 7),
                                     _int(q, "limit", 50, 1, 200))

    def get_references(self, name, doc_id, q):
        from .. import references

        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)):
            raise ApiError(404, "No such document.")
        if _str(q, "start") is not None:
            ch = references.chain_at(ws, doc_id, _int(q, "start", 0, 0, 10 ** 9), _int(q, "end", 0, 0, 10 ** 9))
            return {"chain": ch}
        return {"chains": references.chains(ws, doc_id), "status": references.status(ws, doc_id)}

    def post_references(self, name, doc_id, q):
        return {"job": self.app.start_resolve(name, doc_id, self._body()).view()}

    def _layers(self, q) -> tuple[str, ...]:
        from ..annotate import LAYERS

        got = tuple(_list(q, "layers") or ["judgements"])
        bad = [x for x in got if x not in LAYERS]
        if bad:
            raise ApiError(400, f"Unknown layer {bad[0]!r}: use {', '.join(LAYERS)}.")
        return got

    def get_annotated(self, name, doc_id, q):
        from .. import annotate

        ws = self.app.ws(name)
        hyp = _list(q, "hyp")
        r = annotate.annotate_document(ws, doc_id, hyp, self._layers(q), _str(q, "framework") or
                                       self.app.settings().get("profile_framework") or "sdg", _str(q, "concept"),
                                       threshold=_float(q, "threshold", self.app.settings()["threshold"]))
        disp = _disposition(r["name"])
        extra = {"Content-Disposition": disp, "X-Enlens-Placed": f"{r['placed']}/{r['marks']}"}
        if r["content_type"].startswith("text/html"):
            extra["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
        return self._send(200, r["body"], r["content_type"], extra)

    def get_flexiconc(self, name, q):
        """The project in the FlexiConc layout of the Cross-Doc SDG Explorer (one SQLite file)."""
        import tempfile

        from .. import flexiconc_export

        ws = self.app.ws(name)
        with tempfile.TemporaryDirectory(prefix="enlens-fc-") as tmp:
            out = Path(tmp) / "flexiconc.sqlite"
            emb = self.app.settings().get("embed_model") if self.app.settings().get("embed_backend") != "off" else None
            flexiconc_export.export(ws, out, framework=_str(q, "framework") or self.app.settings().get("profile_framework")
                                    or "sdg", embed_model=emb or None, embeddings=bool(emb))
            # streamed from the file (0.11.1): with embeddings the export of a large project is hundreds of MB
            self._stream(out, "application/vnd.sqlite3",
                         {"Content-Disposition": _disposition(_filename(f"{name} - FlexiConc", "sqlite"))})

    def get_annotated_zip(self, name, hyp_id, q):
        from .. import annotate

        ws = self.app.ws(name)
        body, summary = annotate.annotate_hypothesis_zip(ws, hyp_id, self._layers(q),
                                                         threshold=_float(q, "threshold", self.app.settings()["threshold"]))
        text = ws.scalar("SELECT text FROM hypotheses WHERE hyp_id=?", (hyp_id,)) or hyp_id
        fname = _filename(f"ENLENS highlighted - {text[:60]}", "zip")
        return self._send(200, body, "application/zip", {"Content-Disposition": _disposition(fname),
                                                         "X-Enlens-Placed": f"{summary['placed']}/{summary['marks']}"})
