"""What the endpoints of the web app share: the errors, the background jobs, the readers of query strings and
bodies, and the small helpers that write exports (split out of server.py in 0.16)."""
from __future__ import annotations

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
        # 0.18 (M6): its turn in its project (see Jobs and LANES)
        self.lane: str | None = None    # what it changes in the project, if more than its own results
        self.serial: str | None = None  # jobs with the same serial run one after the other
        self.order = (0.0, 0)           # its place in the project's queue (lower: earlier)
        self.admitted = False           # it has had its turn in the project (it runs, or waits only for the model)
        self.blocker: Job | None = None  # the job it waits for, while it waits for its turn
        self.background = False         # started by the app itself (the shared folder's poller), not the person

    def view(self, full: bool = True) -> dict:
        end = self.finished or time.time()
        out = {"id": self.id, "kind": self.kind, "title": self.title, "project": self.project, "state": self.state,
               "created_at": self.created, "started_at": self.started, "finished_at": self.finished,
               "seconds": round(end - (self.started or end), 1), "error": self.error, "error_kind": self.error_kind,
               "scope": self.scope, "queue": self.queue, "waiting_for": self.waiting_for(),
               "background": self.background}
        if full:
            out["progress"] = self.tracker.state() if self.tracker else self.progress
            out["result"] = self.result
        return out

    def waiting_for(self) -> dict | None:
        """0.18 (M6): the job of the same project this one waits for, in words, while it waits for its turn."""
        b = self.blocker
        if b is None or self.admitted or self.state != "queued":
            return None
        return {"id": b.id, "kind": b.kind, "title": b.title, "message": f"Queued: starts when “{b.title}” has finished"}

    def waits_on_queue(self) -> bool:
        """0.12: its work waits in the queue for Claude Code right now (not its own steps on this computer)."""
        if not self.queue or self.state not in ("queued", "running"):
            return False
        if self.tracker is not None:
            return ((self.tracker.model or {}).get("phase")) == "queue"
        return isinstance(self.progress, dict) and bool(self.progress.get("queue"))


# 0.18 (M6): jobs wait their turn. Jobs of one project that change the same things do not run at the same time: the
# later one waits in the project's queue (state "queued", `waiting_for` says for which job) and starts when its turn
# comes, first come first served; it can be cancelled while it waits. A job's lane says what it changes besides its own results; a job in no
# lane (a check, labels, themes, the glossary, a codebook tried out …) reads the documents and writes its own results,
# so such jobs run beside each other (and the chat model still serves one at a time: `model_lock`).
#   reader  the new reader: it replaces a document's passages and moves every result on them, in one step. A job that
#           holds passage ids from before would write its results onto passages that are gone, so it runs alone in
#           its project: it waits until no other job of the project runs, and while it runs every other job waits
#           for it. While it waits, it and the jobs waiting behind it hold back only search by meaning and other
#           moves (WAITING_HOLDS): the rest of the project's work goes on, so a move waiting behind a check that waits
#           for Claude Code never stalls the whole project (it takes the first moment nothing else runs).
#   corpus  adding documents: new documents and passages, their vectors for search by meaning, the glossary and codes.
#   index   setting up search by meaning: vectors for every passage without one (adding documents makes them too, so
#           the two would prepare the same passages twice).
#   sync    a round of the shared folder: it brings colleagues' documents and work in (a merge); never while documents
#           are being added or read again, and never two at once. It runs beside checks, as a colleague's zip does.
LANES: dict[str, set[str]] = {
    "corpus": {"corpus", "index", "sync"},
    "index": {"corpus", "index"},
    "sync": {"corpus", "sync"},
}
ALONE = "reader"
WAITING_HOLDS = {ALONE, "index"}  # a move still waiting, and what waits behind it, hold back only jobs of these lanes
ONE_START = threading.Lock()  # a look for the same job already there, then the start of a new one, as one step
LANE_OF_KIND = {"ingest": "corpus", "new_reader": "reader", "index": "index", "folder-sync": "sync"}
# (one document read with the new reader is a job of kind "reread", as reading one excerpt again is: its start names
# the lane.) The project's jobs in the second lanes that still wait move behind a new job of the first: search by
# meaning after the new reader, so no passage is prepared twice.
BEHIND = {ALONE: {"index"}}


def conflicts(a: Job, b: Job) -> bool:
    """0.18 (M6): whether two jobs may not run at the same time: the same project, and lanes that clash (or the same
    `serial`, such as new themes for one set of themes, which would take the same passages)."""
    if a.project is None or a.project != b.project:
        return False
    if a.serial is not None and a.serial == b.serial:
        return True
    if a.lane == ALONE or b.lane == ALONE:
        return True
    return a.lane is not None and b.lane is not None and b.lane in LANES.get(a.lane, ())


class Jobs:
    """Background work. Jobs that use the chat model run one at a time (a local model serves one request well);
    the others (adding sources, embeddings) run beside them. 0.18 (M6): jobs of one project that change the same
    things wait their turn (LANES), first come first served, except that search by meaning still waiting moves behind
    the new reader (BEHIND), and a move still waiting holds back little (WAITING_HOLDS)."""

    KEEP = 50
    WAKE = 0.25  # seconds: how often a job that waits for its turn looks again (it is also woken when a job ends)

    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.turns = threading.Condition(self.lock)  # 0.18: woken whenever a job ends or is cancelled
        self.model_lock = threading.Lock()
        self.ended: list[Callable[[Job], Any]] = []   # 0.18: called with every job that ends (the poller listens)
        self._seq = 0

    def start(self, kind: str, title: str, project: str | None, fn: Callable[[Job], Any], uses_model: bool,
              unique: bool = False, lane: str | None = None, serial: str | None = None, background: bool = False,
              if_free: bool = False, scope: str | None = None) -> Job | None:
        """`unique`: when a job of this kind is already queued or running for the project, that one is returned and
        nothing starts (a second press of a button, or a second tab, must not do the same work twice).

        0.18 (M6): `lane` (default: by kind, LANE_OF_KIND) and `serial` say which jobs of the project this one may not
        run beside (see LANES); it waits for them in the queue. `background`: started by the app, not the person.
        `if_free`: start only when it would not have to wait; None (nothing started) otherwise."""
        job = Job(kind, title, project)
        job.lane = lane if lane is not None else LANE_OF_KIND.get(kind)
        job.serial, job.background, job.scope = serial, background, scope
        with self.lock:
            if unique:
                same = [j for j in self.jobs.values() if j.kind == kind and j.project == project
                        and j.state in ("queued", "running")]
                if same:
                    return same[0]
            self._seq += 1
            job.order = (float(self._seq), self._seq)
            behind = BEHIND.get(job.lane or "")
            moved = {}
            if behind and project is not None:  # the jobs that still wait and go after it now come after it
                for j in self.jobs.values():
                    if j.project == project and j.lane in behind and j.state == "queued" and not j.admitted:
                        moved[j] = j.order
                        j.order = (job.order[0] + 0.5, j.order[1])
            job.blocker = self._blocker(job)
            if if_free and job.blocker is not None:
                for j, order in moved.items():  # nothing started: they keep their places
                    j.order = order
                return None
            self.jobs[job.id] = job
            done = [j for j in self.jobs.values() if j.state in ("done", "error", "cancelled")]
            for j in sorted(done, key=lambda j: j.created)[:-self.KEEP or None] if len(done) > self.KEEP else []:
                self.jobs.pop(j.id, None)

        def run():
            lock = self.model_lock if uses_model else None
            try:
                self._wait_turn(job)
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
                with self.turns:  # 0.18: the jobs that wait for this one look again now
                    self.turns.notify_all()
                for listener in list(self.ended):
                    try:
                        listener(job)
                    except Exception:  # noqa: BLE001 - a listener never stops the job's thread from ending well
                        traceback.print_exc()

        threading.Thread(target=run, daemon=True, name=f"job-{kind}-{job.id}").start()
        return job

    # -- 0.18 (M6): the project's queue --------------------------------------------------------------------------
    def _blocker(self, job: Job) -> Job | None:
        """The job `job` waits for (call with the lock held), among the jobs of its project it may not run beside: the
        one just ahead of it in the queue that still waits (it finishes last, so "starts when … has finished" holds),
        else one that has had its turn (the one longest at it)."""
        if job.project is None:
            return None
        parked = set() if job.lane in WAITING_HOLDS else self._parked(job.project)
        running = ahead = None
        for o in self.jobs.values():
            if o is job or o.project != job.project or o.state not in ("queued", "running") or not conflicts(job, o):
                continue
            if o.admitted:
                if running is None or o.order < running.order:
                    running = o
            elif o.order < job.order and not o.cancel.is_set() and o.id not in parked:
                if ahead is None or o.order > ahead.order:
                    ahead = o
        return ahead or running

    def _parked(self, project: str) -> set[str]:
        """The jobs of the project that wait behind a move to the new reader still waiting (the move itself, and the
        moves and search by meaning waiting behind it, directly or through each other): they hold back only jobs of
        their own lanes (WAITING_HOLDS), so a move that waits long never stalls the rest of the project. Call with
        the lock held."""
        waiting = sorted((o for o in self.jobs.values() if o.project == project and o.state == "queued"
                          and not o.admitted and not o.cancel.is_set()), key=lambda o: o.order)
        parked: set[str] = set()
        for i, o in enumerate(waiting):
            if o.lane == ALONE or (o.lane in WAITING_HOLDS and any(p.id in parked and conflicts(o, p)
                                                                   for p in waiting[:i])):
                parked.add(o.id)
        return parked

    def _wait_turn(self, job: Job) -> None:
        """Wait until it is the job's turn in its project (raises Cancelled when it is cancelled meanwhile)."""
        with self.turns:
            while True:
                if job.cancel.is_set():
                    job.blocker = None
                    raise Cancelled()
                job.blocker = self._blocker(job)
                if job.blocker is None:
                    job.admitted = True
                    return
                self.turns.wait(self.WAKE)

    def cancel(self, job: Job) -> None:
        """Stop a job; one that waits for its turn leaves the queue at once (and the jobs behind it move up)."""
        job.cancel.set()
        with self.turns:
            self.turns.notify_all()

    def holder(self, project: str, kind: str, lane: str | None = None) -> Job | None:
        """0.18: the job a new job of `kind` (and `lane`) in `project` would wait for now, if any (the poller asks)."""
        probe = Job(kind, "", project)
        probe.lane = lane if lane is not None else LANE_OF_KIND.get(kind)
        with self.lock:
            probe.order = (float(self._seq + 1), self._seq + 1)
            return self._blocker(probe)

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
    from ..review import write_csv

    buf = io.StringIO()
    write_csv(buf, rows)  # text a spreadsheet would run as a formula is written as text (review.csv_cell)
    return buf.getvalue().encode("utf-8-sig")
