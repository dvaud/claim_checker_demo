"""What the endpoints of the web app share: the errors, the background jobs, the readers of query strings and
bodies, and the small helpers that write exports (split out of server.py in 0.16)."""
from __future__ import annotations

import csv
import io
import json
import re
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable

from .progress import Tracker
from .. import claimcheck, llm
from ..llm import BackendError

MAX_UPLOAD = 2 * 1024 ** 3   # bytes per file
MAX_JSON = 20 * 1024 ** 2    # bytes per JSON body (a batch of hypotheses, a codebook)


class ApiError(Exception):
    def __init__(self, status: int, message: str, kind: str = "request", extra: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.kind, self.extra = status, message, kind, extra or {}


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------------------------
class Job:
    def __init__(self, kind: str, title: str, project: str | None):
        self.id = uuid.uuid4().hex[:12]
        self.kind, self.title, self.project = kind, title, project
        self.state = "queued"
        self.created = time.time()
        self.started: float | None = None
        self.finished: float | None = None
        self.progress: Any = {}
        self.tracker: Tracker | None = None
        self.result: Any = None
        self.error: str | None = None
        self.error_kind: str | None = None
        self.scope: str | None = None   # 0.7: what a job is about within its project (a document id), to find it again
        self.queue = False              # 0.8: its tasks wait in the queue for Claude Code
        self.cancel = threading.Event()

    def view(self, full: bool = True) -> dict:
        end = self.finished or time.time()
        out = {"id": self.id, "kind": self.kind, "title": self.title, "project": self.project, "state": self.state,
               "created_at": self.created, "started_at": self.started, "finished_at": self.finished,
               "seconds": round(end - (self.started or end), 1), "error": self.error, "error_kind": self.error_kind,
               "scope": self.scope, "queue": self.queue}
        if full:
            out["progress"] = self.tracker.state() if self.tracker else self.progress
            out["result"] = self.result
        return out

    def waits_on_queue(self) -> bool:
        """0.12: its work waits in the queue for Claude Code right now (not its own steps on this computer)."""
        if not self.queue or self.state not in ("queued", "running"):
            return False
        if self.tracker is not None:
            return ((self.tracker.model or {}).get("phase")) == "queue"
        return isinstance(self.progress, dict) and bool(self.progress.get("queue"))


class Jobs:
    """Background work. Jobs that use the chat model run one at a time (a local model serves one request well);
    the others (adding sources, embeddings) run beside them."""

    KEEP = 50

    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.model_lock = threading.Lock()

    def start(self, kind: str, title: str, project: str | None, fn: Callable[[Job], Any], uses_model: bool,
              unique: bool = False) -> Job:
        """`unique`: when a job of this kind is already queued or running for the project, that one is returned and
        nothing starts (a second press of a button, or a second tab, must not do the same work twice)."""
        job = Job(kind, title, project)
        with self.lock:
            if unique:
                same = [j for j in self.jobs.values() if j.kind == kind and j.project == project
                        and j.state in ("queued", "running")]
                if same:
                    return same[0]
            self.jobs[job.id] = job
            done = [j for j in self.jobs.values() if j.state in ("done", "error", "cancelled")]
            for j in sorted(done, key=lambda j: j.created)[:-self.KEEP or None] if len(done) > self.KEEP else []:
                self.jobs.pop(j.id, None)

        def run():
            lock = self.model_lock if uses_model else None
            try:
                if lock:
                    while not lock.acquire(timeout=0.5):
                        if job.cancel.is_set():
                            raise Cancelled()
                try:
                    if job.cancel.is_set():
                        raise Cancelled()
                    job.state, job.started = "running", time.time()
                    job.result = fn(job)
                    job.state = "cancelled" if job.cancel.is_set() and job.result is None else "done"
                finally:
                    if lock:
                        lock.release()
            except Cancelled:
                job.state = "cancelled"
            except llm.MemoryShort as e:  # 0.13.11: in plain words, not as "the AI model is not answering"
                job.state, job.error, job.error_kind = "error", str(e), "memory"
            except BackendError as e:
                stopped = job.cancel.is_set() and str(e).startswith("Stopped")
                job.state, job.error, job.error_kind = ("cancelled", None, None) if stopped else ("error", str(e), "backend")
            except (ValueError, KeyError, FileNotFoundError) as e:
                job.state, job.error, job.error_kind = "error", (e.args[0] if isinstance(e, KeyError) and e.args
                                                                 else str(e)), "request"
            except Exception as e:  # pragma: no cover - a bug: keep the app running and show it
                traceback.print_exc()
                job.state, job.error, job.error_kind = "error", f"Unexpected problem: {e}", "internal"
            finally:
                job.finished = time.time()
                if job.tracker is not None:
                    job.tracker.finish()

        threading.Thread(target=run, daemon=True, name=f"job-{kind}-{job.id}").start()
        return job

    def all(self) -> list[Job]:
        with self.lock:
            return sorted(self.jobs.values(), key=lambda j: -j.created)

    def get(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise ApiError(404, "No such job (jobs are kept until the app is closed).")
        return job


def benchmark_table(res: dict) -> list[dict]:
    """Measures as rows, task kinds as columns, in words."""
    rows = [("Tasks run", "tasks", "n"), ("Failed to answer (errors)", "errors", "n"),
            ("Usable answers on the first try", "usable", "%"), ("Valid JSON", "valid_json", "%"),
            ("Answers with a quote not in the text", "quote_problems", "%"),
            ("Same status as the reference", "same_status", "%"),
            ("Grounded or not: agreement beyond chance (κ)", "grounded_kappa", "k"),
            ("Same grade per passage", "same_passage_grade", "%"),
            ("Has a claim or not: agreement beyond chance (κ)", "claims_kappa", "k"),
            ("Code present or not: agreement beyond chance (κ)", "codes_kappa", "k"),
            ("Passages with exactly the same codes", "same_codes", "%"),
            ("Overlap of SDG targets named", "target_overlap", "%"), ("Same direction on shared targets", "same_direction", "%"),
            ("Median seconds per task", "seconds_median", "n")]
    names = {"verify_set": "Checking claims", "extract": "Extracting claims", "split": "Splitting justifications",
             "label": "Labelling with codes"}
    out = []
    for label, key, fmt in rows:
        vals = {names.get(k, k): v.get(key) for k, v in res["kinds"].items()}
        if all(v is None for v in vals.values()):
            continue
        out.append({"measure": label, **{k: ("–" if v is None else f"{v:.0%}" if fmt == "%" else f"{v:.2f}" if fmt == "k"
                                              else f"{v:g}") for k, v in vals.items()}})
    return out


def _text_with_quote(path: Path, quote: str, name: str) -> bytes | None:
    """A text file as it is, in a page that marks the quote (found as quotes are: line breaks and typography do not
    matter) with the id "quote", so a link to …#quote scrolls to it. None when the quote is not in the file."""
    import html

    from ..ingest import decode_text
    from ..textutil import find_quote

    # 0.14.3: read as the document was read when it was added (a Windows-1250 file kept its accented letters there,
    # so its quotes are found here too)
    raw = decode_text(path.read_bytes(), html=path.suffix.lower() in (".html", ".htm"))
    # 0.14.3: a quote accepted earlier is placed, not checked again (the whole-word rule is for new answers; a long
    # quote cut at 2,000 characters may end inside a word)
    hit = find_quote(raw, quote[:2000], whole_words=False)
    if not hit:
        return None
    a, b = hit[0], hit[1]
    body = (html.escape(raw[:a]) + '<mark id="quote">' + html.escape(raw[a:b]) + "</mark>" + html.escape(raw[b:]))
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
            "content=\"width=device-width, initial-scale=1\"><meta name=\"color-scheme\" content=\"light dark\">"
            f"<title>{html.escape(name)}</title><style>"
            "body{margin:0;font:15px/1.55 ui-serif,Georgia,serif;background:#fbfaf6;color:#1d1d1b}"
            "header{position:sticky;top:0;padding:10px 16px;font:13px/1.4 system-ui,sans-serif;background:#efece3;"
            "border-bottom:1px solid #ddd8cc}"
            "pre{white-space:pre-wrap;word-wrap:break-word;font:inherit;margin:0;padding:16px;max-width:46rem}"
            "mark{background:#ffe08a;color:inherit;padding:1px 0;scroll-margin-top:30vh}"
            "@media (prefers-color-scheme: dark){body{background:#1b1c1a;color:#e8e6df}"
            "header{background:#262724;border-color:#3a3b37}mark{background:#7a6215}}"
            f"</style></head><body><header>{html.escape(name)} · the original file; the quote from ENLENS is "
            f"highlighted</header><pre>{body}</pre></body></html>").encode()


def _usable_embedder(ws, emb):
    """Use semantic search only when the project has vectors from this model."""
    if emb is None:
        return None
    # one row is enough (0.11.1: the full status, three counts over the embeddings, ran per check and per result page)
    return emb if ws.scalar("SELECT 1 FROM embeddings WHERE model=? LIMIT 1", (emb.model,)) else None


def _check_options(body: dict, s: dict) -> dict:
    def num(key, lo, hi):
        try:
            v = int(body.get(key) if body.get(key) is not None else s[key])
        except (TypeError, ValueError):
            raise ApiError(400, f"{key} must be a whole number.") from None
        return max(lo, min(v, hi))

    doc_ids = body.get("doc_ids") or None
    if doc_ids is not None and not (isinstance(doc_ids, list) and all(isinstance(d, str) for d in doc_ids)):
        raise ApiError(400, "doc_ids must be a list of document ids.")
    return {"k": num("k", 1, 20), "per_doc": num("per_doc", 1, 10),
            "expand": bool(body["expand"]) if "expand" in body else bool(s["expand"]),
            "decompose": bool(body["decompose"]) if "decompose" in body else bool(s["decompose"]),
            "doc_ids": doc_ids, "semantic": bool(body.get("semantic", True)),
            "second_pass": bool(body["second_pass"]) if "second_pass" in body else bool(s.get("second_pass"))}


def _list(q: dict, key: str) -> list[str] | None:
    """A list from a query parameter: repeated (?docs=a&docs=b) or comma-separated (?docs=a,b)."""
    v = q.get(key)
    if not v:
        return None
    items = [x.strip() for part in (v if isinstance(v, list) else [v]) for x in str(part).split(",") if x.strip()]
    return items or None


def _bool(q: dict, key: str) -> bool:
    return (_str(q, key) or "").lower() in ("1", "true", "yes", "on")


def _body_int(body: dict, key: str, default: int | None, lo: int, hi: int) -> int | None:
    """A whole number from a JSON body, in plain language when it is not one (0.11.1: Python's own message was
    shown). `default` when the key is absent or empty (None stays None)."""
    v = body.get(key)
    if v is None or v == "":
        return default
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ApiError(400, f"{key} must be a whole number.") from None
    return max(lo, min(v, hi))


def _int(q: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(_float(q, key, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(v, hi))


def _xlsx_with_provenance(ws, sheets: list[tuple[str, list[dict]]], task_ids=None, kinds=None) -> bytes:
    """An Excel file of these sheets with "How these results were made" at the end (models, digests, prompts, seeds)."""
    from ..runs import provenance_table

    buf = io.BytesIO()
    first_name, first_rows = sheets[0]
    claimcheck.write_xlsx(first_rows, buf, first_name,
                          extra=list(sheets[1:]) + [("How these results were made", provenance_table(ws, task_ids, kinds))])
    return buf.getvalue()


def _str(q: dict, key: str) -> str | None:
    v = q.get(key)
    return (v[0] if isinstance(v, list) else v) or None


def _float(q: dict, key: str, default: float) -> float:
    v = _str(q, key)
    try:
        return float(v) if v not in (None, "") else float(default)
    except ValueError:
        raise ApiError(400, f"{key} must be a number.") from None


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _cell(text: str):
    """A table cell for Excel: a number when it reads as one ("1.9", "34%" stays text), else the text."""
    t = (text or "").strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", t):
        try:
            return float(t) if "." in t else int(t)
        except ValueError:
            return t
    return t


def reading_report(ws, doc_id: str, raw: str | None, reader: int) -> dict:
    """0.15 (A5): how a document was read: the new reader's report, or what is known about an older reading."""
    try:
        rep = json.loads(raw) if raw else {}
    except ValueError:
        rep = {}
    if rep:
        from .. import reader as reader2

        rep["places"] = [reader2.warning_place(w) for w in rep.get("warnings") or []]  # 0.15.7: not stored
        return rep
    n = ws.query("SELECT n_pages, ocr_pages, scanned_pages FROM documents WHERE doc_id=?", (doc_id,))[0]
    sec = {r[0]: r[1] for r in ws.query("SELECT section, COUNT(*) FROM passages WHERE doc_id=? GROUP BY section",
                                        (doc_id,))}
    return {"reader": reader, "older": True, "pages": n["n_pages"], "ocr_pages": n["ocr_pages"] or 0,
            "scanned_pages": n["scanned_pages"] or 0, "passages": sum(sec.values()), "body_passages": sec.get("body", 0),
            "unreadable_passages": sec.get("unreadable", 0), "warnings": [], "quality": None}


_PDFIUM_LOCK = threading.Lock()  # pdfium may be used by one thread at a time


def page_images_available() -> bool:
    try:
        import PIL  # noqa: F401
        import pypdfium2  # noqa: F401
    except Exception:  # noqa: BLE001 - missing or broken: no pictures of pages
        return False
    return True


def render_page(path: Path, page: int, scale: float = 1.5) -> bytes | None:
    """One page of a PDF as PNG bytes (1-based page number), or None when there is no such page."""
    import pypdfium2 as pdfium

    with _PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            if not 1 <= page <= len(pdf):
                return None
            img = pdf[page - 1].render(scale=scale).to_pil()
            buf = io.BytesIO()
            img.save(buf, "PNG", optimize=True)
            return buf.getvalue()
        finally:
            pdf.close()


def _filename(stem: str, ext: str) -> str:
    """A readable file name: the words of the stem, without characters file systems refuse."""
    clean = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', " ", stem)
    return re.sub(r"\s+", " ", clean).strip(" .")[:120] + "." + ext


def _disposition(fname: str) -> str:
    from urllib.parse import quote

    ascii_name = fname.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"


def _installation() -> dict:
    """0.10: how this ENLENS was installed (installation.py), for Settings → Technical and the help text."""
    from .. import installation

    try:
        i = installation.info()  # one description of the installation (0.11.1: the app kept its own copy)
        return {"kind": i["kind"], "system": installation.system(), "line": i["install_line"],
                "releases": i["releases"], "updates": i["updates"]}
    except Exception:  # noqa: BLE001
        return {"kind": "pip", "system": installation.system(), "line": "", "releases": ""}


def _csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")
