"""Retractions and corrections (0.18.1, roadmap B5): the DOIs of the bibliography's works and of the documents,
looked up in Crossref, whose metadata carries Retraction Watch's retractions and the publishers' corrections and
expressions of concern as "updates" of the work. A plain lookup, no AI.

The first online lookup of works, so it keeps the rules of every online lookup:
- it runs only when the person asks (the button, `enlens retractions`), never by itself;
- it follows each document's AI setting: a work whose document is marked *No AI* is not looked up;
- it is off under local-only: nothing is sent;
- it sends DOIs and nothing else: a plain `User-Agent: ENLENS/<version>`, no email, no name, no project name.

Each answer is kept with its date in the table `retractions` (a DOI looked up and found clean is kept too, so the
page can say when it was last checked)."""
from __future__ import annotations

import json
import os
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

from . import __version__, access, home
from .store import Workspace, now
from .textutil import clean_doi

BASE_URL = "https://api.crossref.org"
BATCH = 20        # DOIs in one request (Crossref ORs a filter given several times)
MAX_DOIS = 2000   # a cap per lookup, so a huge library never becomes thousands of requests
PAUSE = 0.15      # seconds between two requests: politeness
ROWS = 1000
TIMEOUT = 25
SERIOUS = "retraction"  # what the page shows as serious; every other type is milder
_OPENER = build_opener(ProxyHandler({}))  # no proxy settings of the system leak into a lookup

TYPE_TEXT = {"retraction": "Retracted", "correction": "Corrected", "expression_of_concern": "Expression of concern",
             "erratum": "Corrected", "corrigendum": "Corrected", "addendum": "Addendum", "withdrawal": "Withdrawn",
             "removal": "Removed", "new_edition": "New edition", "new_version": "New version"}


class RetractionError(Exception):
    """A lookup that cannot be made or did not work; the message is for the person."""


def norm_doi(doi: str | None) -> str | None:
    d = clean_doi(doi)
    return d if d and d.startswith("10.") else None


def _kind(t: str) -> str:
    return str(t or "").strip().lower().replace("-", "_").replace(" ", "_")


def serious(notices: list[dict]) -> bool:
    return any(n.get("type") in (SERIOUS, "withdrawal", "removal") for n in notices)


def _date(parts) -> str | None:
    try:
        ymd = [int(x) for x in (parts or [[]])[0]]
    except (TypeError, ValueError, IndexError):
        return None
    if not ymd:
        return None
    return "-".join(f"{n:02d}" if i else f"{n:04d}" for i, n in enumerate(ymd[:3]))


# -------------------------------------------------------------------------------------------------------- which DOIs
def _dois(ws: Workspace) -> dict[str, dict]:
    """{doi: {"items": [item_key], "docs": [doc_id]}} for every work of the bibliography and every document with a DOI;
    a document linked (or confirmed) to a work is a document of the work's DOI too."""
    out: dict[str, dict] = {}

    def entry(d):
        return out.setdefault(d, {"items": [], "docs": []})

    for r in ws.query("SELECT item_key, doi FROM bib_items WHERE doi IS NOT NULL AND doi<>'' ORDER BY seq"):
        d = norm_doi(r["doi"])
        if d:
            entry(d)["items"].append(r["item_key"])
    for r in ws.query("SELECT l.doc_id, b.doi FROM bib_links l JOIN bib_items b ON b.item_key=l.item_key "
                      "WHERE l.status IN ('auto', 'confirmed') AND b.doi IS NOT NULL AND b.doi<>''"):
        d = norm_doi(r["doi"])
        if d and r["doc_id"] not in entry(d)["docs"]:
            entry(d)["docs"].append(r["doc_id"])
    for r in ws.query("SELECT doc_id, doi FROM documents WHERE doi IS NOT NULL AND doi<>''"):
        d = norm_doi(r["doi"])
        if d and r["doc_id"] not in entry(d)["docs"]:
            entry(d)["docs"].append(r["doc_id"])
    return out


def plan(ws: Workspace) -> dict:
    """What a lookup would ask: {"ask": [DOIs], "no_ai": [DOIs left out], "capped": bool}."""
    found = _dois(ws)
    doc_ids = sorted({d for e in found.values() for d in e["docs"]})
    level = access.levels(ws, doc_ids) if doc_ids else {}
    ask, no_ai = [], []
    for d, e in found.items():
        # one document of the work marked No AI is enough to keep the work out: the person said no machine goes near it
        (no_ai if any(level.get(x) == "none" for x in e["docs"]) else ask).append(d)
    return {"ask": ask[:MAX_DOIS], "no_ai": no_ai, "capped": len(ask) > MAX_DOIS}


# -------------------------------------------------------------------------------------------------------- the lookup
def _get(url: str) -> dict:
    req = Request(url, headers={"User-Agent": f"ENLENS/{__version__}", "Accept": "application/json"})
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except HTTPError as e:
        if e.code == 429:
            raise RetractionError("Crossref asked for fewer requests. Try again in a few minutes.") from None
        raise RetractionError(f"Crossref answered with an error ({e.code}). Try again later.") from None
    except (URLError, OSError, TimeoutError):
        raise RetractionError("Could not reach Crossref. Check the internet connection and try again.") from None
    except ValueError:
        raise RetractionError("Crossref sent an answer ENLENS could not read. Try again later.") from None


def _batch(base: str, dois: list[str], sleep: Callable[[float], None]) -> dict[str, list[dict]]:
    """Notices for one batch: {doi: [notice]}. The filter is repeated, once per DOI (Crossref ORs it); each notice
    says which work it updates, so a notice that updates a DOI outside the batch is ignored."""
    asked = set(dois)
    got: dict[str, list[dict]] = {}
    offset = 0
    while True:
        flt = ",".join(f"updates:{d}" for d in dois)
        url = f"{base}/works?filter={quote(flt, safe=':,/')}&rows={ROWS}&offset={offset}&select=DOI,update-to"
        msg = (_get(url).get("message") or {})
        items = msg.get("items") or []
        for it in items:
            for u in it.get("update-to") or []:
                target = norm_doi(u.get("DOI"))
                if target in asked:
                    notice = {"type": _kind(u.get("type") or u.get("label")), "doi": norm_doi(it.get("DOI")),
                              "date": _date((u.get("updated") or {}).get("date-parts")), "source": u.get("source")}
                    if notice not in got.setdefault(target, []):
                        got[target].append(notice)
        offset += len(items)
        if not items or offset >= int(msg.get("total-results") or 0) or offset >= 5 * ROWS:
            return got
        sleep(PAUSE)


def lookup(ws: Workspace, progress: Callable[..., None] | None = None, base_url: str | None = None,
           should_stop: Callable[[], bool] | None = None, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Ask Crossref about the DOIs. Returns {"looked_up", "no_ai", "notices" (how many works have one), "capped",
    "checked_at"}. Raises RetractionError under local-only, and when Crossref cannot be reached (what was answered
    before is kept)."""
    if home.local_only():
        raise RetractionError("Online lookups are off on this computer (local-only), so nothing was sent.")
    base = (base_url or os.environ.get("ENLENS_CROSSREF_URL") or BASE_URL).rstrip("/")
    p = plan(ws)
    ask, stamp = p["ask"], now()
    done = found = 0
    for i in range(0, len(ask), BATCH):
        if should_stop and should_stop():
            break
        chunk = ask[i:i + BATCH]
        if progress:
            progress(done=done, total=len(ask), phase="retractions")
        got = _batch(base, chunk, sleep)
        with ws.connect() as cx:
            cx.executemany("INSERT OR REPLACE INTO retractions(doi, checked_at, notices_json) VALUES (?,?,?)",
                           [(d, stamp, json.dumps(got.get(d, []), ensure_ascii=False)) for d in chunk])
        done += len(chunk)
        found += sum(1 for d in chunk if got.get(d))
        if i + BATCH < len(ask):
            sleep(PAUSE)
    if progress:
        progress(done=done, total=len(ask), phase="retractions")
    return {"looked_up": done, "no_ai": len(p["no_ai"]), "notices": found, "capped": p["capped"], "checked_at": stamp}


# -------------------------------------------------------------------------------------------------------- what is kept
def _kept(ws: Workspace) -> dict[str, dict]:
    out = {}
    for r in ws.query("SELECT doi, checked_at, notices_json FROM retractions"):
        try:
            notices = json.loads(r["notices_json"] or "[]")
        except json.JSONDecodeError:
            notices = []
        out[r["doi"]] = {"checked_at": r["checked_at"], "notices": notices}
    return out


def status(ws: Workspace) -> dict:
    """What the last lookups found, for the page, the claim card and the command line:
    {"local_only": bool, "checked_at": the latest lookup or None, "checked": DOIs kept, "affected": DOIs with a notice,
     "by_doi": {doi: {"checked_at", "notices": [{type, doi, date, source}]}} (only DOIs with a notice),
     "by_item": {item_key: [notices]}, "by_doc": {doc_id: [notices]}} (notices carry "work_doi" and "checked_at";
     only works and documents with at least one notice)."""
    kept = _kept(ws)
    found = _dois(ws)
    by_item: dict[str, list] = {}
    by_doc: dict[str, list] = {}
    for d, k in kept.items():
        if not k["notices"]:
            continue
        rows = [{**n, "work_doi": d, "checked_at": k["checked_at"]} for n in k["notices"]]
        for key in found.get(d, {}).get("items", []):
            by_item[key] = rows
        for doc in found.get(d, {}).get("docs", []):
            by_doc[doc] = rows
    stamps = [k["checked_at"] for k in kept.values() if k["checked_at"]]
    return {"local_only": home.local_only(), "checked_at": max(stamps) if stamps else None, "checked": len(kept),
            "affected": sum(1 for k in kept.values() if k["notices"]),
            "by_doi": {d: k for d, k in kept.items() if k["notices"]}, "by_item": by_item, "by_doc": by_doc}


def for_docs(ws: Workspace) -> dict[str, list[dict]]:
    """{doc_id: notices} for the claim card."""
    return status(ws)["by_doc"]


def for_items(ws: Workspace) -> dict[str, list[dict]]:
    """{item_key: notices} for the bibliography's works."""
    return status(ws)["by_item"]


def text(n: dict) -> str:
    """One notice in words: 'Retracted (2023-04-12)'."""
    t = TYPE_TEXT.get(n.get("type") or "") or (n.get("type") or "notice").replace("_", " ").capitalize()
    return f"{t} ({n['date']})" if n.get("date") else t
