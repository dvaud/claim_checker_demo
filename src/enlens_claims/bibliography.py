"""0.13: a project's bibliography: the works of a Zotero library or collection (or of a file exported from a reference
manager), matched with the project's documents.

Zotero is read through its local API: Zotero 7 or later, running on this computer, answers at
http://127.0.0.1:23119/api/ once "Allow other applications on this computer to communicate with Zotero" is ticked
(Zotero: Settings → Advanced). Nothing goes over the internet and no Zotero account or key is needed. A file exported
from Zotero, Mendeley, EndNote and others (BibTeX, RIS, CSL JSON, Zotero's CSV) works without the app.

A work and a document are linked by themselves when they are the same file (a file Zotero keeps for the work and the
document have the same checksum) or have the same DOI. A work whose title, and an author or the year, are found on the
first pages of a document is a *probable* link that a person confirms. A person's decisions (the same work, not the
same, linked by hand) survive every new match and every update of the bibliography.

0.13.3: a document linked to a work is called by the work's title everywhere (a PDF's own title is often a file name,
a journal's running head or nothing at all). The title read from the file is kept and comes back when the link goes.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener, url2pathname

from .store import Workspace, now
from .textutil import STOPWORDS, clean_doi, fast_normalise, find_dois

ZOTERO = "http://127.0.0.1:23119"
HEAD_CHARS = 8000          # the first pages of a document, where its title, authors and year are printed
FRONT_CHARS = 1500         # its title page
READABLE = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}   # files ENLENS can add (ingest.SUPPORTED)
MAX_HASH = 300 * 1024 ** 2  # files larger than this are not compared by checksum
SKIP_TYPES = {"note", "annotation"}
LIBRARY_RE = re.compile(r"^(user|group-\d{1,12})$")
KEY_RE = re.compile(r"^[A-Za-z0-9]{1,32}$")
MAX_CHOSEN = 500           # 0.13.9: works chosen one by one (more than this: a collection is the better way)
FORMATS = {"bibtex": "BibTeX", "ris": "RIS", "csl": "CSL JSON", "csv": "Zotero CSV"}


class ZoteroError(ValueError):
    """`kind`: not_running (no Zotero on this computer answers), api_off (Zotero answers but does not let other
    programs read it), too_old (a Zotero without the local API), failed (anything else)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# ------------------------------------------------------------------------------------------
# reading Zotero (its local API)
# ------------------------------------------------------------------------------------------
def zotero_url() -> str:
    return (os.environ.get("ENLENS_ZOTERO_URL") or ZOTERO).rstrip("/")


_OPENER = build_opener(ProxyHandler({}))  # this computer only: never through a proxy


def _get(path: str, params: dict | None = None, timeout: float = 20, text: bool = False):
    url = zotero_url() + path + ("?" + urlencode(params) if params else "")
    req = Request(url, headers={"Accept": "text/plain" if text else "application/json", "Zotero-API-Version": "3",
                                "User-Agent": "ENLENS"})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            body = r.read()
    except HTTPError as e:
        if e.code == 403:
            raise ZoteroError("api_off", "Zotero does not let other programs read it yet.") from None
        if e.code in (404, 501) and path.startswith("/api/users/0/collections"):
            raise ZoteroError("too_old", "This Zotero cannot be read directly (Zotero 7 or later can).") from None
        raise ZoteroError("failed", f"Zotero answered {e.code} to {path}.") from None
    except (URLError, OSError, TimeoutError) as e:
        raise ZoteroError("not_running", f"Zotero is not open on this computer ({e}).") from None
    if text:
        return body.decode("utf-8", "replace")
    try:
        return json.loads(body or b"null")
    except json.JSONDecodeError:
        raise ZoteroError("failed", f"Zotero's answer to {path} could not be read.") from None


def _all(path: str, params: dict | None = None, page: int = 100) -> list:
    """Every object of a list, a page at a time (the local API also answers without paging; pages keep each answer
    small)."""
    out: list = []
    start = 0
    while True:
        got = _get(path, {**(params or {}), "limit": page, "start": start})
        if not isinstance(got, list):
            raise ZoteroError("failed", f"Zotero's answer to {path} is not a list.")
        out.extend(got)
        if len(got) < page:
            return out
        start += page


def _prefix(library: str) -> str:
    if not LIBRARY_RE.match(library or ""):
        raise ValueError("Unknown Zotero library.")
    return "/api/users/0" if library == "user" else f"/api/groups/{library[6:]}"


def zotero_status() -> dict:
    """Whether Zotero can be read here, and its libraries (My Library and the groups)."""
    try:
        _get("/api/users/0/collections", {"limit": 1}, timeout=4)
    except ZoteroError as e:
        if e.kind == "not_running":
            return {"state": "not_running", "url": zotero_url()}
        return {"state": e.kind, "url": zotero_url(), "detail": str(e)}
    libs = [{"id": "user", "name": "My Library"}]
    try:
        for g in _get("/api/users/0/groups", timeout=6) or []:
            data = g.get("data") or g
            gid = g.get("id") or data.get("id")
            if gid is not None and re.fullmatch(r"\d{1,12}", str(gid)):
                libs.append({"id": f"group-{gid}", "name": str(data.get("name") or f"Group {gid}")})
    except ZoteroError:
        pass  # groups are optional: My Library is enough
    return {"state": "ready", "url": zotero_url(), "libraries": libs}


def zotero_collections(library: str) -> list[dict]:
    """The collections of a library in tree order, each with its depth and the number of works directly in it."""
    rows = []
    for c in _all(_prefix(library) + "/collections"):
        data = c.get("data") or {}
        key = c.get("key") or data.get("key")
        if not key:
            continue
        rows.append({"key": key, "name": str(data.get("name") or key), "parent": data.get("parentCollection") or None,
                     "items": int((c.get("meta") or {}).get("numItems") or 0)})
    kids: dict[str | None, list[dict]] = defaultdict(list)
    keys = {r["key"] for r in rows}
    for r in rows:
        kids[r["parent"] if r["parent"] in keys else None].append(r)
    out: list[dict] = []

    def walk(parent, depth):
        for r in sorted(kids.get(parent, []), key=lambda x: x["name"].lower()):
            out.append({**r, "depth": depth})
            if depth < 30:
                walk(r["key"], depth + 1)

    walk(None, 0)
    return out


def zotero_works(library: str, collection: str | None = None, q: str = "", limit: int = 100) -> dict:
    """0.13.9: the works of a library or of one collection (not its subcollections), by title, to choose from one by
    one. `q` is Zotero's own quick search (title, creators, year). `more`: there are more than `limit`."""
    prefix = _prefix(library)
    if collection is not None and not KEY_RE.match(collection):
        raise ValueError("Unknown Zotero collection.")
    limit = max(1, min(int(limit), 200))
    params = {"limit": limit + 1, "start": 0, "sort": "title", "direction": "asc"}
    if q.strip():
        params["q"] = q.strip()[:200]
    got = _get(prefix + (f"/collections/{collection}/items/top" if collection else "/items/top"), params)
    if not isinstance(got, list):
        raise ZoteroError("failed", "Zotero's list of works could not be read.")
    out = []
    for it in got[:limit]:
        d = it.get("data") or {}
        if d.get("parentItem") or d.get("itemType") in SKIP_TYPES:
            continue
        w = from_zotero(it, library, [])
        if w["title"] and KEY_RE.match(w["key"].rsplit(":", 1)[-1]):
            out.append({"key": w["key"].rsplit(":", 1)[-1], "title": w["title"], "cite": cite(w["creators"], w["year"]),
                        "type": type_text(w["type"])})
    return {"works": out, "more": len(got) > limit}


def _file_path(prefix: str, key: str) -> str | None:
    """Where Zotero keeps an attachment's file (stored or linked), or None."""
    try:
        u = _get(f"{prefix}/items/{key}/file/view/url", text=True, timeout=8).strip()
    except ZoteroError:
        return None
    if not u.startswith("file:"):
        return None
    p = urlparse(u)
    path = url2pathname(p.path if not p.netloc else f"//{p.netloc}{p.path}")
    return path or None


def pull_zotero(library: str, collection: str | None = None, subcollections: bool = True, progress=None,
                should_stop=None, items: list[str] | None = None) -> tuple[list[dict], dict]:
    """The works of a library, or of a collection (with its subcollections), or (0.13.9) the works chosen one by one
    (`items`, their Zotero keys), with the files Zotero keeps for them."""
    prefix = _prefix(library)
    if collection is not None and not KEY_RE.match(collection):
        raise ValueError("Unknown Zotero collection.")
    chosen = list(dict.fromkeys(str(k) for k in items or []))
    if items is not None and (not chosen or len(chosen) > MAX_CHOSEN or not all(KEY_RE.match(k) for k in chosen)):
        raise ValueError(f"Choose between 1 and {MAX_CHOSEN} works of your Zotero.")
    say = progress or (lambda **kw: None)
    say(phase="works", done=0, total=0)
    source = {"kind": "zotero", "library": library, "collection": collection, "subcollections": bool(subcollections)}
    items = {}  # the works, by their Zotero key
    if chosen:
        source.update(collection=None, subcollections=False)
        for i in range(0, len(chosen), 50):  # Zotero answers up to 50 keys at a time
            batch = chosen[i:i + 50]
            # Zotero 10's local API also returns the children of the works asked for: only the works themselves count
            for it in _all(f"{prefix}/items", {"itemKey": ",".join(batch)}):
                if it.get("key") in batch and not (it.get("data") or {}).get("parentItem"):
                    items.setdefault(it["key"], it)
            say(phase="works", done=len(items), total=len(chosen))
        if not items:
            raise ZoteroError("failed", "The works you chose are not in Zotero any more.")
        items = {k: items[k] for k in chosen if k in items}  # in the order they were chosen
        source["items"] = list(items)  # a work deleted from Zotero is left out of the next update too
    elif collection:
        cols = zotero_collections(library)
        names = {c["key"]: c["name"] for c in cols}
        if collection not in names:
            raise ZoteroError("failed", "That collection is not in Zotero any more.")
        source["collection_name"] = names[collection]
        keys = [collection]
        if subcollections:
            kids = defaultdict(list)
            for c in cols:
                kids[c["parent"]].append(c["key"])
            i = 0
            while i < len(keys):
                keys.extend(k for k in kids.get(keys[i], []) if k not in keys)
                i += 1
        for k in keys:
            for it in _all(f"{prefix}/collections/{k}/items/top"):
                items.setdefault(it.get("key"), it)
            say(phase="works", done=len(items), total=0)
            if should_stop and should_stop():
                break
    else:
        for it in _all(f"{prefix}/items/top"):
            items.setdefault(it.get("key"), it)
        say(phase="works", done=len(items), total=0)
    items = {k: v for k, v in items.items() if k and ((v.get("data") or {}).get("itemType") not in SKIP_TYPES)}
    # the files: a work's attachments, or the work itself when it is a file kept on its own
    atts: dict[str, list[dict]] = defaultdict(list)
    if collection or chosen:
        with_kids = [k for k, v in items.items() if int((v.get("meta") or {}).get("numChildren") or 0) > 0]
        for i, k in enumerate(with_kids):
            if should_stop and should_stop():
                break
            for ch in _all(f"{prefix}/items/{k}/children"):
                if (ch.get("data") or {}).get("itemType") == "attachment":
                    atts[k].append(ch)
            say(phase="attachments", done=i + 1, total=len(with_kids))
    else:
        for a in _all(f"{prefix}/items", {"itemType": "attachment"}):
            parent = (a.get("data") or {}).get("parentItem")
            if parent and parent in items and (a.get("data") or {}).get("itemType") == "attachment":
                atts[parent].append(a)
    for k, v in items.items():
        if (v.get("data") or {}).get("itemType") == "attachment":
            atts[k].append(v)
    wanted = [(k, a) for k, lst in atts.items() for a in lst if _readable_attachment(a.get("data") or {})]
    paths: dict[str, list[dict]] = defaultdict(list)
    for i, (k, a) in enumerate(wanted):
        if should_stop and should_stop():
            break
        p = _file_path(prefix, a.get("key") or (a.get("data") or {}).get("key") or "")
        if p:
            paths[k].append({"path": p, "name": Path(p).name, "type": (a.get("data") or {}).get("contentType") or ""})
        say(phase="files", done=i + 1, total=len(wanted))
    works = [from_zotero(v, library, paths.get(k, [])) for k, v in items.items()]
    return [w for w in works if w["title"]], source


def _readable_attachment(data: dict) -> bool:
    if data.get("linkMode") == "linked_url":
        return False
    name = str(data.get("filename") or data.get("path") or data.get("title") or "")
    ctype = str(data.get("contentType") or "")
    return (Path(name).suffix.lower() in READABLE or ctype in ("application/pdf", "text/html", "text/plain",
            "text/markdown", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))


# ------------------------------------------------------------------------------------------
# one work, from each kind of source
# ------------------------------------------------------------------------------------------
_YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d|21\d\d)\b")


def _year(*vals) -> str | None:
    for v in vals:
        m = _YEAR.search(str(v or ""))
        if m:
            return m.group(1)
    return None


def _doi_from(*vals) -> str | None:
    for v in vals:
        if not v:
            continue
        s = str(v)
        m = re.search(r"(?im)^\s*doi\s*:\s*(\S+)", s)
        d = clean_doi(m.group(1)) if m else None
        if d and d.startswith("10."):
            return d
        found = find_dois(s)
        if found:
            return found[0]
    return None


def _work(key, type_, title, creators, year, doi, url, container, isbn, link, files) -> dict:
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    return {"key": key, "type": str(type_ or "").strip() or None, "title": title[:600],
            "creators": [c for c in creators if c.get("last") or c.get("name")][:60],
            "year": year, "doi": clean_doi(doi) if doi else None, "url": (str(url).strip() or None) if url else None,
            "container": (re.sub(r"\s+", " ", str(container)).strip()[:300] or None) if container else None,
            "isbn": (str(isbn).strip()[:60] or None) if isbn else None, "link": link, "files": files or []}


def _zotero_link(library: str, key: str) -> str:
    return (f"zotero://select/library/items/{key}" if library == "user"
            else f"zotero://select/groups/{library[6:]}/items/{key}")


def from_zotero(item: dict, library: str, files: list[dict]) -> dict:
    d = item.get("data") or {}
    key = item.get("key") or d.get("key") or ""
    creators = []
    for c in d.get("creators") or []:
        if c.get("name"):
            creators.append({"name": str(c["name"]).strip(), "role": c.get("creatorType")})
        elif c.get("lastName") or c.get("firstName"):
            creators.append({"last": str(c.get("lastName") or c.get("firstName")).strip(),
                             "first": str(c.get("firstName") or "").strip() if c.get("lastName") else "",
                             "role": c.get("creatorType")})
    creators.sort(key=lambda c: 0 if c.get("role") in (None, "author", "programmer", "artist", "director",
                                                         "presenter", "inventor", "interviewee") else 1)
    title = d.get("title") or d.get("caseName") or d.get("nameOfAct") or d.get("subject") or ""
    container = next((d.get(k) for k in ("publicationTitle", "bookTitle", "proceedingsTitle", "websiteTitle",
                                          "blogTitle", "institution", "university", "publisher") if d.get(k)), None)
    return _work(f"zotero:{library}:{key}", d.get("itemType"), title, creators,
                 _year((item.get("meta") or {}).get("parsedDate"), d.get("date")),
                 _doi_from(d.get("DOI"), d.get("extra"))
                 or (_doi_from(d.get("url")) if "doi.org" in str(d.get("url") or "") else None),
                 d.get("url"), container, d.get("ISBN"), _zotero_link(library, key), files)


def _hash_key(title: str, year: str | None, creators: list[dict]) -> str:
    first = (creators[0].get("last") or creators[0].get("name") or "") if creators else ""
    raw = f"{_fold(title)}|{year or ''}|{_fold(first)}"
    return "work:" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def _person(name: str, comma_only: bool = False) -> dict:
    """'Last, First', 'First Last' or '{Organisation}'. `comma_only`: a name without a comma is an organisation (RIS
    and Zotero's CSV write every person as 'Last, First')."""
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return {}
    if name.startswith("{") and name.endswith("}"):
        return {"name": name[1:-1].strip()}
    if "," in name:
        last, first = name.split(",", 1)
        return {"last": last.strip(), "first": first.strip()}
    parts = name.split(" ")
    if comma_only:
        return {"name": name}
    if len(parts) == 1:
        return {"last": parts[0], "first": ""}
    return {"last": parts[-1], "first": " ".join(parts[:-1])}


# -- CSL JSON (Zotero: Export → CSL JSON; most reference managers) --------------------------
def parse_csl(text: str) -> list[dict]:
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("items") or [data]
    out = []
    for o in data if isinstance(data, list) else []:
        if not isinstance(o, dict):
            continue
        creators = []
        for role in ("author", "editor", "translator"):
            for a in o.get(role) or []:
                if not isinstance(a, dict):
                    continue
                if a.get("literal"):
                    creators.append({"name": str(a["literal"]), "role": role})
                elif a.get("family") or a.get("given"):
                    creators.append({"last": str(a.get("family") or a.get("given")),
                                     "first": str(a.get("given") or "") if a.get("family") else "", "role": role})
        issued = o.get("issued") or {}
        parts = issued.get("date-parts") if isinstance(issued, dict) else None
        year = _year(parts[0][0] if parts and parts[0] else None, issued.get("raw") if isinstance(issued, dict) else
                     None, issued.get("literal") if isinstance(issued, dict) else None, issued if isinstance(issued, str)
                     else None)
        title = o.get("title") or ""
        oid = str(o.get("id") or "")
        m = re.search(r"zotero\.org/(users|groups)/(?:local/)?([^/]+)/items/([A-Z0-9]{8})\b", oid)
        if m:
            lib = "user" if m.group(1) == "users" else f"group-{m.group(2)}"
            key, link = f"zotero:{lib}:{m.group(3)}", _zotero_link(lib, m.group(3))
        else:
            key, link = (f"csl:{oid[:120]}" if oid else _hash_key(title, year, creators)), None
        out.append(_work(key, o.get("type"), title, creators, year, _doi_from(o.get("DOI"), o.get("note")),
                         o.get("URL"), o.get("container-title") or o.get("publisher"), o.get("ISBN"), link, []))
    return out


# -- RIS ---------------------------------------------------------------------------------------
def parse_ris(text: str) -> list[dict]:
    out, rec = [], None
    for line in text.lstrip("\ufeff").splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])  -(?: (.*))?$", line.rstrip())
        if not m:
            if rec is not None and rec.get("_last") and line.strip():  # a value continued on the next line
                rec[rec["_last"]][-1] += " " + line.strip()
            continue
        tag, val = m.group(1), (m.group(2) or "").strip()
        if tag == "TY":
            rec = {"TY": [val]}
            continue
        if rec is None:
            continue
        if tag == "ER":
            out.append(_ris_work(rec))
            rec = None
            continue
        rec.setdefault(tag, []).append(val)
        rec["_last"] = tag
    if rec is not None:
        out.append(_ris_work(rec))
    return [w for w in out if w]


def _ris_work(r: dict) -> dict:
    g = lambda *tags: next((r[t][0] for t in tags if r.get(t) and r[t][0]), None)  # noqa: E731
    creators = ([_person(a, True) for t in ("AU", "A1") for a in r.get(t, [])]
                or [_person(a, True) for a in r.get("A2", [])])
    creators = [c for c in creators if c]
    title = g("TI", "T1", "CT", "BT") or ""
    year = _year(g("PY"), g("Y1"), g("DA"))
    urls = r.get("UR", [])
    files = []
    for t in ("L1", "L4"):
        for v in r.get(t, []):
            p = _local_path(v)
            if p:
                files.append({"path": p, "name": Path(p).name, "type": ""})
    rid = g("ID")
    key = f"ris:{rid[:120]}" if rid else _hash_key(title, year, creators)
    container = next((r[t][0] for t in ("T2", "JO", "JF", "JA", "PB") if r.get(t) and r[t][0] and r[t][0] != title),
                     None)
    return _work(key, g("TY"), title, creators, year, _doi_from(g("DO"), " ".join(urls), g("N1")),
                 next((u for u in urls if "doi.org" not in u), urls[0] if urls else None), container, g("SN"), None,
                 files)


def _local_path(v: str) -> str | None:
    v = (v or "").strip()
    if v.startswith("file:"):
        p = urlparse(v)
        return url2pathname(p.path) or None
    if re.match(r"^(/|[A-Za-z]:[\\/]|\\\\)", v):
        return v
    return None  # internal-pdf://…, relative paths and links cannot be found from here


# -- BibTeX / BibLaTeX -----------------------------------------------------------------------
_ACCENTS = {'"': "\u0308", "'": "\u0301", "`": "\u0300", "^": "\u0302", "~": "\u0303", "=": "\u0304", ".": "\u0307",
            "u": "\u0306", "v": "\u030c", "H": "\u030b", "c": "\u0327", "k": "\u0328", "r": "\u030a"}
_LETTERS = {"ss": "ß", "o": "ø", "O": "Ø", "aa": "å", "AA": "Å", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ", "l": "ł",
            "L": "Ł", "i": "ı", "j": "ȷ", "textendash": "–", "textemdash": "—", "&": "&", "%": "%", "$": "$", "_": "_",
            "#": "#"}


def tex(s: str) -> str:
    """BibTeX's LaTeX to plain text: accents, special letters, dashes and quotes; other commands and braces go."""
    s = re.sub(r"\\([\"'`^~=.])\s*\{?\s*\\?([A-Za-z])\s*\}?", lambda m: m.group(2) + _ACCENTS[m.group(1)], s)
    s = re.sub(r"\\([uvHckr])\s*\{\s*\\?([A-Za-z])\s*\}", lambda m: m.group(2) + _ACCENTS[m.group(1)], s)
    s = re.sub(r"\\([uvHckr]) ([A-Za-z])", lambda m: m.group(2) + _ACCENTS[m.group(1)], s)
    s = re.sub(r"\\(ss|aa|AA|ae|AE|oe|OE|textendash|textemdash|[oOlLij])(?![A-Za-z])\s*",
               lambda m: _LETTERS[m.group(1)], s)
    s = re.sub(r"\\([&%$_#])", lambda m: m.group(1), s)
    s = s.replace("---", "—").replace("--", "–").replace("``", "“").replace("''", "”").replace("~", " ")
    s = re.sub(r"\\[A-Za-z]+\*?\s*", "", s)
    s = s.replace("{", "").replace("}", "")
    s = unicodedata.normalize("NFC", s.replace("ı\u0301", "í").replace("ı\u0308", "ï").replace("ı\u0300", "ì")
                              .replace("ı\u0302", "î"))
    return re.sub(r"\s+", " ", s).strip()


def _bib_value(text: str, i: int) -> tuple[str, int]:
    """One field value from position i: {…}, "…", a number or a @string name, joined with #. Returns (raw, end)."""
    parts = []
    n = len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        c = text[i]
        if c == "{" or c == '"':
            close = "}" if c == "{" else '"'
            depth, j = 0, i + 1
            while j < n:
                ch = text[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}" and (depth > 0 or close != "}"):
                    depth -= 1
                elif ch == close and depth == 0:
                    break
                j += 1
            parts.append(text[i + 1:j])
            i = j + 1
        else:
            m = re.compile(r"[^\s,#}]+").match(text, i)
            parts.append(m.group(0) if m else "")
            i = m.end() if m else i + 1
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i < n and text[i] == "#":
            i += 1
            continue
        break
    return "".join(parts), i


def parse_bibtex(text: str) -> list[dict]:
    out = []
    i, n = 0, len(text)
    head = re.compile(r"@\s*([A-Za-z]+)\s*([{(])")
    while True:
        m = head.search(text, i)
        if not m:
            break
        etype, open_ch = m.group(1).lower(), m.group(2)
        close_ch = "}" if open_ch == "{" else ")"
        j, depth = m.end(), 1
        while j < n and depth:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ")" and close_ch == ")" and depth == 1:
                depth = 0
            j += 1
        body = text[m.end():j - 1]
        i = j
        # an unbalanced brace would swallow the entries after it: an entry ends where a line starts the next one
        nxt = re.compile(r"\n\s*@\s*[A-Za-z]+\s*[{(]").search(text, m.end(), j)
        if nxt:
            body, i = text[m.end():nxt.start()], nxt.start()
        if etype in ("comment", "preamble", "string"):
            continue
        citekey, _, rest = body.partition(",")
        fields: dict[str, str] = {}
        k = 0
        fm = re.compile(r"\s*([A-Za-z][\w:.+-]*)\s*=\s*")
        while k < len(rest):
            f = fm.match(rest, k)
            if not f:
                nxt = rest.find(",", k + 1)
                if nxt < 0:
                    break
                k = nxt + 1
                continue
            raw, k = _bib_value(rest, f.end())
            fields[f.group(1).lower()] = raw
            while k < len(rest) and rest[k] in " \t\r\n,":
                k += 1
        out.append(_bib_work(etype, citekey.strip(), fields))
    return out


def _split_names(raw: str) -> list[str]:
    names, depth, cur = [], 0, ""
    for tok in re.split(r"(\{|\}|\s+and\s+)", raw):
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth -= 1
        if tok and re.fullmatch(r"\s+and\s+", tok) and depth == 0:
            names.append(cur)
            cur = ""
        else:
            cur += tok or ""
    names.append(cur)
    return [x.strip() for x in names if x.strip()]


def _bib_work(etype: str, citekey: str, f: dict) -> dict:
    creators = []
    for role in ("author", "editor"):
        for nm in _split_names(f.get(role, "")):
            org = nm.startswith("{") and nm.endswith("}") and nm.count("{") == 1
            p = _person(("{" + tex(nm) + "}") if org else tex(nm))
            if p:
                creators.append({**p, "role": role})
        if creators:
            break
    title = tex(f.get("title", ""))
    year = _year(f.get("year"), f.get("date"))
    files = []
    for part in re.split(r"(?<!\\);", f.get("file", "")):
        bits = [b.replace("\\:", ":").replace("\\\\", "\\") for b in re.split(r"(?<!\\):", part)]
        # "description:path:type" (a Windows path's own colon is escaped, or rejoined here)
        cand = (":".join(bits[1:-1]) if len(bits) >= 3 else bits[-1] if bits else "").strip()
        p = _local_path(cand)
        if p:
            files.append({"path": p, "name": Path(p).name, "type": bits[-1] if len(bits) >= 3 else ""})
    key = f"bib:{citekey[:120]}" if citekey else _hash_key(title, year, creators)
    container = tex(f.get("journal") or f.get("journaltitle") or f.get("booktitle") or f.get("institution")
                    or f.get("school") or f.get("publisher") or f.get("organization") or "") or None
    return _work(key, etype, title, creators, year, _doi_from(f.get("doi"), f.get("url"), f.get("note")),
                 tex(f.get("url", "")) or None, container, f.get("isbn"), None, files)


# -- Zotero's CSV export ---------------------------------------------------------------------
def parse_zotero_csv(text: str) -> list[dict]:
    out = []
    for r in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        title = (r.get("Title") or "").strip()
        creators = [p for a in (r.get("Author") or "").split(";") if (p := _person(a, True))]
        if not creators:
            creators = [p for a in (r.get("Editor") or "").split(";") if (p := _person(a, True))]
        year = _year(r.get("Publication Year"), r.get("Date"))
        zkey = (r.get("Key") or "").strip()
        files = []
        for p in (r.get("File Attachments") or "").split(";"):
            lp = _local_path(p.strip())
            if lp:
                files.append({"path": lp, "name": Path(lp).name, "type": ""})
        key = f"zotero:user:{zkey}" if KEY_RE.match(zkey) else _hash_key(title, year, creators)
        out.append(_work(key, r.get("Item Type"), title, creators, year,
                         _doi_from(r.get("DOI"), r.get("Extra")), r.get("Url"),
                         r.get("Publication Title") or r.get("Publisher"), r.get("ISBN"),
                         _zotero_link("user", zkey) if KEY_RE.match(zkey) else None, files))
    return out


def sniff(name: str, text: str) -> str | None:
    ext = Path(name or "").suffix.lower()
    t = text.lstrip("\ufeff \t\r\n")
    if ext in (".bib", ".bibtex", ".biblatex"):
        return "bibtex"
    if ext == ".ris" or re.match(r"TY  - ", t):
        return "ris"
    if ext in (".json", ".csljson") or t[:1] in ("[", "{"):
        return "csl"
    first = t.split("\n", 1)[0]
    if ext == ".csv" or ("Item Type" in first and "Title" in first):
        return "csv"
    if re.search(r"@\s*[A-Za-z]+\s*\{", t):
        return "bibtex"
    if re.search(r"(?m)^TY  - ", t):
        return "ris"
    return None


def parse_file(name: str, text: str) -> tuple[str, list[dict]]:
    """The works of an exported file; (format, works). Raises ValueError for a file that is none of the formats."""
    fmt = sniff(name, text)
    if fmt is None:
        raise ValueError("This file is not a bibliography ENLENS can read. Export it from Zotero (or another reference "
                         "manager) as BibTeX, RIS, CSL JSON or CSV.")
    try:
        works = {"bibtex": parse_bibtex, "ris": parse_ris, "csl": parse_csl, "csv": parse_zotero_csv}[fmt](text)
    except (json.JSONDecodeError, csv.Error) as e:
        raise ValueError(f"The {FORMATS[fmt]} file could not be read: {e}") from None
    return fmt, [w for w in works if w and w["title"]]


# ------------------------------------------------------------------------------------------
# storing a bibliography
# ------------------------------------------------------------------------------------------
def has(ws: Workspace) -> bool:
    return bool(ws.scalar("SELECT 1 FROM bib_items LIMIT 1"))


def _hash_files(works: list[dict], old: dict[str, dict], progress=None) -> None:
    """The checksum of each file a work has (the same as a document's when it is the same file). A file that did not
    change since the last time keeps its checksum."""
    from .ingest import _sha1

    todo = [f for w in works for f in w["files"]]
    for i, f in enumerate(todo):
        try:
            st = os.stat(f["path"])
        except OSError:
            f["exists"] = False
            continue
        f["exists"] = True
        f["size"], f["mtime"] = st.st_size, st.st_mtime_ns
        prev = old.get(f["path"])
        if prev and prev.get("size") == f["size"] and prev.get("mtime") == f["mtime"] and prev.get("sha1"):
            f["sha1"] = prev["sha1"]
        elif st.st_size <= MAX_HASH:
            try:
                f["sha1"] = _sha1(Path(f["path"]))
            except OSError:
                pass
        if progress:
            progress(phase="checksums", done=i + 1, total=len(todo))


def save(ws: Workspace, works: list[dict], source: dict, progress=None) -> dict:
    """Make `works` the project's bibliography (replacing the one before), then match it with the documents.

    A person's decisions are kept: for the same work (by its key, else its DOI, else its title and year)."""
    old_files = {}
    for r in ws.query("SELECT files_json FROM bib_items"):
        for f in json.loads(r["files_json"] or "[]"):
            old_files[f.get("path")] = f
    _hash_files(works, old_files, progress)
    seen: set[str] = set()
    uniq = []
    for w in works:
        if w["key"] in seen:
            continue
        seen.add(w["key"])
        uniq.append(w)
    old = {r["item_key"]: (r["doi"], _fold(r["title"] or ""), r["year"]) for r in
           ws.query("SELECT item_key, doi, title, year FROM bib_items")}
    by_doi = {w["doi"]: w["key"] for w in uniq if w["doi"]}
    by_ty = {(_fold(w["title"]), w["year"]): w["key"] for w in uniq}
    with ws.connect() as cx:
        cx.execute("DELETE FROM bib_items")
        cx.executemany("INSERT INTO bib_items(item_key, item_type, title, creators_json, year, doi, url, container, "
                       "isbn, link, files_json, seq) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       [(w["key"], w["type"], w["title"], json.dumps(w["creators"], ensure_ascii=False), w["year"],
                         w["doi"], w["url"], w["container"], w["isbn"], w["link"],
                         json.dumps(w["files"], ensure_ascii=False), i) for i, w in enumerate(uniq)])
        # a person's decisions about works whose key changed (another source for the same library) follow the work
        for r in cx.execute("SELECT item_key, doc_id, status, method, score, evidence_json, decided_at FROM bib_links "
                            "WHERE status IN ('confirmed', 'rejected')").fetchall():
            if r[0] in seen:
                continue
            doi, title, year = old.get(r[0], (None, None, None))
            new = (by_doi.get(doi) if doi else None) or by_ty.get((title, year))
            if new:
                cx.execute("INSERT OR IGNORE INTO bib_links VALUES (?,?,?,?,?,?,?)", (new, *r[1:]))
        cx.execute("DELETE FROM bib_links WHERE item_key NOT IN (SELECT item_key FROM bib_items) "
                   "OR doc_id NOT IN (SELECT doc_id FROM documents)")
        ws.set_meta("bibliography", {**source, "pulled_at": now(), "works": len(uniq)}, cx)
    if progress:
        progress(phase="matching", done=0, total=0)
    return match(ws)


def remove(ws: Workspace) -> dict:
    with ws.connect() as cx:
        n = cx.execute("DELETE FROM bib_items").rowcount
        cx.execute("DELETE FROM bib_links")
        cx.execute("DELETE FROM meta WHERE key='bibliography'")
        _sync_titles(cx)  # 0.13.3: every document gets its own title back
    return {"removed": n}


# ------------------------------------------------------------------------------------------
# matching works and documents
# ------------------------------------------------------------------------------------------
def _fold(s: str) -> str:
    """Lower case, typography unified, accents taken off: 'Müller' and 'Muller' are the same word here."""
    t = unicodedata.normalize("NFKD", fast_normalise(s or ""))
    return "".join(c for c in t if not unicodedata.combining(c))


def _tokens(s: str) -> list[str]:
    return re.findall(r"[^\W_]+", _fold(s))


def _sig(tokens: list[str]) -> set[str]:
    return {t for t in tokens if (len(t) > 2 or t.isdigit()) and t not in STOPWORDS}


def _surnames(creators: list[dict]) -> list[list[str]]:
    out = []
    for c in creators[:3]:
        toks = _tokens(c.get("last") or c.get("name") or "")
        toks = [t for t in toks if len(t) > 1 and t not in STOPWORDS] if c.get("name") else [t for t in toks if len(t) > 1]
        if toks:
            out.append(toks)
    return out


def _title_variants(title: str) -> list[list[str]]:
    """The whole title and, for 'Main: subtitle', the main title (a document may print the subtitle apart)."""
    whole = _tokens(title)
    out = [whole]
    main = re.split(r"\s*[:?!]\s+|\s+[-–—]\s+", title, maxsplit=1)[0]
    mt = _tokens(main)
    if mt != whole and len(_sig(mt)) >= 3:
        out.append(mt)
    return out


def match(ws: Workspace) -> dict:
    """Link the works of the bibliography with the documents. Links found by checksum or DOI are made at once; a
    work whose title and an author or the year are on a document's first pages is proposed (probable). A person's
    decisions are never overruled, and a document or work already linked gets no proposal."""
    items = [dict(r) for r in ws.query("SELECT item_key, title, creators_json, year, doi, files_json FROM bib_items")]
    # the title read from the file (a document linked before is called by its work's title; that must not match)
    docs = [dict(r) for r in ws.query("SELECT doc_id, path, sha1, COALESCE(file_title, title) AS title, doi, "
                                      f"substr(text, 1, {HEAD_CHARS}) AS head FROM documents")]
    decided = {(r["item_key"], r["doc_id"]): r["status"] for r in
               ws.query("SELECT item_key, doc_id, status FROM bib_links WHERE status IN ('confirmed', 'rejected')")}
    linked_items = {k for (k, _d), s in decided.items() if s == "confirmed"}
    linked_docs = {d for (_k, d), s in decided.items() if s == "confirmed"}
    auto: dict[tuple[str, str], str] = {}
    by_sha = {d["sha1"]: d["doc_id"] for d in docs if d["sha1"] and "~" not in d["sha1"]}  # 0.14: not another reading
    by_doi: dict[str, list[str]] = defaultdict(list)
    for d in docs:
        if d["doi"]:
            by_doi[clean_doi(d["doi"])].append(d["doc_id"])
    for it in items:
        for f in json.loads(it["files_json"] or "[]"):
            doc = by_sha.get(f.get("sha1") or "")
            if doc and (it["item_key"], doc) not in decided:
                auto[(it["item_key"], doc)] = "file"
        if it["doi"]:
            for doc in by_doi.get(it["doi"], []):
                if (it["item_key"], doc) not in decided:
                    auto.setdefault((it["item_key"], doc), "doi")
    linked_items |= {k for k, _d in auto}
    linked_docs |= {d for _k, d in auto}

    # probable links: the title on the first pages, with an author or the year
    info = {}
    index: dict[str, set[str]] = defaultdict(set)
    for d in docs:
        if d["doc_id"] in linked_docs:
            continue
        name = re.sub(r".*[/\\]", "", d["path"] or "")
        head = d["head"] or ""
        toks = _tokens(f"{d['title'] or ''} . {name} . {head}")
        front = _tokens(f"{d['title'] or ''} . {name} . {head[:FRONT_CHARS]}")
        top = set(_tokens(f"{d['title'] or ''} {name} {head[:600]}"))
        info[d["doc_id"]] = (set(toks), " " + " ".join(toks) + " ", front, " " + " ".join(front) + " ", top, d, toks)
        for t in set(toks):
            index[t].add(d["doc_id"])
    pairs: list[tuple[str, str, float, dict]] = []
    for it in items:
        if it["item_key"] in linked_items:
            continue
        variants = _title_variants(it["title"] or "")
        sig = _sig(variants[0])
        if not sig:
            continue
        need = max(1, int(0.6 * len(sig) + 0.999))
        hits = Counter(doc for t in sig for doc in index.get(t, ()))
        creators = json.loads(it["creators_json"] or "[]")
        surnames = _surnames(creators)
        for doc_id, n in hits.items():
            if n < need or (it["item_key"], doc_id) in decided:
                continue
            words, joined, front, front_joined, top, d, toks = info[doc_id]
            t, how = _title_found(variants, sig, joined, front, front_joined)
            if not t:
                continue
            author = next((" ".join(s) for s in surnames if all(x in words for x in s)), None)
            year = it["year"] if it["year"] and it["year"] in words else None
            ok = (how == "whole" and author and year) if len(sig) < 3 else bool(author or year)
            if not ok:   # a short title ("Hydrogen") says little on its own: it needs both
                continue
            score = 0.5 * t + (0.25 if author else 0) + (0.2 if year else 0) + (0.05 if year and year in top else 0)
            ev = {"title": how, "author": author, "year": year}
            ev.update(_where(d, it["title"]))
            ev["_dist"] = _year_distance(toks, variants[0], year)
            pairs.append((it["item_key"], doc_id, round(score, 3), ev))
    # editions: works with the same title (a yearly report) proposed for one document keep the one whose year stands
    # closest after the title ("Hydrogen market report 2024" is not the 2023 edition it mentions)
    nearest: dict[tuple[str, str], int] = {}
    titles = {it["item_key"]: _fold(it["title"] or "") for it in items}
    for k, doc, _s, ev in pairs:
        g = (doc, titles[k])
        nearest[g] = min(nearest.get(g, 10 ** 9), ev["_dist"])
    pairs = [(k, doc, s, ev) for k, doc, s, ev in pairs if ev["_dist"] <= nearest[(doc, titles[k])]]
    for _k, _d, _s, ev in pairs:
        ev.pop("_dist", None)
    best_doc: dict[str, float] = {}
    best_item: dict[str, float] = {}
    for k, doc, s, _ev in pairs:
        best_doc[doc] = max(best_doc.get(doc, 0), s)
        best_item[k] = max(best_item.get(k, 0), s)
    # the best proposal for each document and each work (near ties both stay, for the person to choose: the same
    # title in two editions without the year near the title)
    probable = [(k, doc, s, ev) for k, doc, s, ev in pairs if s >= best_doc[doc] - 0.04 and s >= best_item[k] - 0.04]
    with ws.connect() as cx:
        cx.execute("DELETE FROM bib_links WHERE status IN ('auto', 'probable')")
        cx.executemany("INSERT OR IGNORE INTO bib_links(item_key, doc_id, status, method, score) VALUES (?,?,?,?,1.0)",
                       [(k, d, "auto", m) for (k, d), m in auto.items()])
        cx.executemany("INSERT OR IGNORE INTO bib_links(item_key, doc_id, status, method, score, evidence_json) "
                       "VALUES (?,?,?,?,?,?)",
                       [(k, d, "probable", "title", s, json.dumps(ev, ensure_ascii=False)) for k, d, s, ev in probable])
        _sync_titles(cx)
    return counts(ws)


def _sync_titles(cx) -> int:
    """0.13.3: a document linked to a work (the same file, the same DOI, or a person's word) takes the work's title;
    the title read from the file goes to `file_title` and comes back when no work is linked any more. A document
    linked to several works takes the first one's (the order of the bibliography, as `doc_citations`). Returns how
    many titles changed; the keyword index (search.passage_index) is rebuilt when any did."""
    want: dict[str, str] = {}
    for doc_id, title in cx.execute("SELECT l.doc_id, b.title FROM bib_links l JOIN bib_items b ON "
                                    "b.item_key=l.item_key WHERE l.status IN ('auto', 'confirmed') ORDER BY b.seq"):
        if title and title.strip():
            want.setdefault(doc_id, title.strip())
    changed = 0
    for doc_id, title, own in cx.execute("SELECT doc_id, title, file_title FROM documents").fetchall():
        new = want.get(doc_id)
        if new is not None and new != title:
            cx.execute("UPDATE documents SET title=?, file_title=? WHERE doc_id=?",
                       (new, (title or "") if own is None else own, doc_id))
        elif new is None and own is not None:
            cx.execute("UPDATE documents SET title=?, file_title=NULL WHERE doc_id=?", (own or None, doc_id))
        else:
            continue
        changed += 1
    if changed:
        row = cx.execute("SELECT value FROM meta WHERE key='titles_version'").fetchone()
        cx.execute("INSERT OR REPLACE INTO meta VALUES ('titles_version', ?)",
                   (json.dumps(int(json.loads(row[0]) if row else 0) + 1),))
    return changed


def _year_distance(toks: list[str], title: list[str], year: str | None) -> int:
    """How many words after the title (where it first stands) the year comes; very large without the year."""
    if not year:
        return 10 ** 6
    n = len(title)
    start = next((i for i in range(len(toks) - n + 1) if toks[i:i + n] == title), 0) if n else 0
    after = next((j - start for j in range(start, len(toks)) if toks[j] == year), None)
    if after is not None:
        return after
    before = next((start - j for j in range(start - 1, -1, -1) if toks[j] == year), None)
    return 10 ** 5 + (before or 0)


def _title_found(variants: list[list[str]], sig: set[str], joined: str, front: list[str],
                 front_joined: str) -> tuple[float, str]:
    """How well a work's title is found on a document: (weight, how). The whole title (or the main title before a
    colon) as a phrase, best on the title page; else nearly all its words close together on the title page (a PDF's
    text often breaks a title over lines or around a header). Words spread over the first pages are not enough: a
    document that cites the work names them too."""
    for i, v in enumerate(variants):
        if v and f" {' '.join(v)} " in front_joined:
            return (1.0 if i == 0 else 0.9), ("whole" if i == 0 else "main")
    for i, v in enumerate(variants):
        if v and f" {' '.join(v)} " in joined:
            return (0.8 if i == 0 else 0.7), ("whole" if i == 0 else "main")
    if len(sig) < 4:
        return 0.0, ""
    width = 2 * len(variants[0]) + 6
    best = 0
    for i in range(max(1, len(front) - width + 1)):
        best = max(best, len(sig & set(front[i:i + width])))
        if best == len(sig):
            break
    cov = best / len(sig)
    return (round(0.7 * cov, 3), "words") if cov >= 0.85 else (0.0, "")


def _where(d: dict, title: str) -> dict:
    """Where on the document the title stands: a short excerpt and its page, for the person to judge."""
    head = d["head"] or ""
    toks = re.findall(r"[^\W_]+", title)
    m = None
    if len(toks) >= 2:
        rx = re.compile(r"[\W_]+".join(re.escape(t) for t in toks[:40]), re.I)
        m = rx.search(head)
    if m is None:
        sig = [t for t in toks if len(t) > 3 and t.lower() not in STOPWORDS]
        m = re.search(re.escape(sig[0]), head, re.I) if sig else None
    if m is None:
        return {"excerpt": re.sub(r"\s+", " ", head[:220]).strip(), "start": 0, "end": 0}
    a = max(0, m.start() - 90)
    b = min(len(head), m.end() + 110)
    pre = re.sub(r"\s+", " ", head[a:m.start()])
    mid = re.sub(r"\s+", " ", head[m.start():m.end()])
    post = re.sub(r"\s+", " ", head[m.end():b])
    return {"excerpt": ("…" if a else "") + pre + mid + post + ("…" if b < len(head) else ""),
            "start": len(("…" if a else "") + pre), "end": len(("…" if a else "") + pre + mid), "offset": m.start()}


def counts(ws: Workspace) -> dict:
    meta = ws.meta("bibliography") or {}
    works = int(ws.scalar("SELECT COUNT(*) FROM bib_items") or 0)
    linked = {r[0] for r in ws.query("SELECT DISTINCT item_key FROM bib_links WHERE status IN ('auto', 'confirmed')")}
    prob = {r[0] for r in ws.query("SELECT DISTINCT item_key FROM bib_links WHERE status='probable'")}
    docs_linked = int(ws.scalar("SELECT COUNT(DISTINCT doc_id) FROM bib_links WHERE status IN ('auto', 'confirmed', "
                                "'probable')") or 0)
    ndocs = int(ws.scalar("SELECT COUNT(*) FROM documents") or 0)
    return {"works": works, "linked": len(linked), "confirm": int(ws.scalar(
        "SELECT COUNT(*) FROM bib_links WHERE status='probable'") or 0),
            "to_find": works - len(linked | prob), "not_in": ndocs - docs_linked, "source": meta or None}


def decide(ws: Workspace, item_key: str, doc_id: str, decision: str) -> None:
    """A person's word on a work and a document: 'same' (linked), 'different' (never proposed again; an automatic
    link is undone), 'clear' (back to what the matching finds)."""
    if decision not in ("same", "different", "clear"):
        raise ValueError("decision must be same, different or clear.")
    if not ws.scalar("SELECT 1 FROM bib_items WHERE item_key=?", (item_key,)):
        raise KeyError("No such work in the bibliography.")
    if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)):
        raise KeyError("No such document.")
    with ws.connect() as cx:
        old = cx.execute("SELECT method, evidence_json FROM bib_links WHERE item_key=? AND doc_id=?",
                         (item_key, doc_id)).fetchone()
        cx.execute("DELETE FROM bib_links WHERE item_key=? AND doc_id=?", (item_key, doc_id))
        if decision != "clear":
            # how the link was found stays (the same file, DOI, title); "person" for one a person made by hand
            cx.execute("INSERT INTO bib_links(item_key, doc_id, status, method, score, evidence_json, decided_at) "
                       "VALUES (?,?,?,?,?,?,?)", (item_key, doc_id, "confirmed" if decision == "same" else "rejected",
                                                  (old[0] if old and old[0] else "person"), 1.0,
                                                  old[1] if old else None, now()))
    match(ws)


def confirm_all(ws: Workspace) -> int:
    rows = ws.query("SELECT item_key, doc_id FROM bib_links WHERE status='probable'")
    with ws.connect() as cx:
        cx.execute("UPDATE bib_links SET status='confirmed', decided_at=? WHERE status='probable'", (now(),))
    match(ws)
    return len(rows)


# ------------------------------------------------------------------------------------------
# what the page shows
# ------------------------------------------------------------------------------------------
TYPE_TEXT = {
    "journalArticle": "Journal article", "article-journal": "Journal article", "article": "Journal article",
    "JOUR": "Journal article", "JFULL": "Journal article", "EJOUR": "Journal article",
    "book": "Book", "BOOK": "Book", "EBOOK": "Book", "bookSection": "Book chapter", "chapter": "Book chapter",
    "incollection": "Book chapter", "inbook": "Book chapter", "CHAP": "Book chapter", "ECHAP": "Book chapter",
    "report": "Report", "techreport": "Report", "RPRT": "Report", "thesis": "Thesis", "phdthesis": "Thesis",
    "mastersthesis": "Thesis", "THES": "Thesis", "conferencePaper": "Conference paper", "paper-conference":
    "Conference paper", "inproceedings": "Conference paper", "CONF": "Conference paper", "CPAPER": "Conference paper",
    "webpage": "Web page", "online": "Web page", "ELEC": "Web page", "blogPost": "Web page", "post-weblog": "Web page",
    "newspaperArticle": "News article", "article-newspaper": "News article", "NEWS": "News article",
    "magazineArticle": "Magazine article", "article-magazine": "Magazine article", "MGZN": "Magazine article",
    "preprint": "Preprint", "document": "Document", "misc": "Document", "GEN": "Document", "statute": "Law",
    "case": "Court case", "dataset": "Data set", "DATA": "Data set", "attachment": "File", "manuscript": "Manuscript",
    "presentation": "Presentation", "interview": "Interview", "encyclopediaArticle": "Encyclopedia entry",
    "entry-encyclopedia": "Encyclopedia entry", "patent": "Patent", "PAT": "Patent", "standard": "Standard",
}


def cite(creators: list[dict], year: str | None) -> str:
    """'Verhoeven and Okafor (2025)', 'Lindqvist et al. (2025)': the authors, else whoever is named."""
    who_ = [c for c in creators if c.get("role") in (None, "author")] or creators
    names = [n for c in who_ if (n := c.get("last") or c.get("name"))]
    who = ("" if not names else names[0] if len(names) == 1 else f"{names[0]} and {names[1]}" if len(names) == 2
           else f"{names[0]} et al.")
    return f"{who} ({year})" if who and year else who or (f"({year})" if year else "")


def _full_names(creators: list[dict]) -> str:
    return "; ".join((f"{c['last']}, {c['first']}" if c.get("first") else c.get("last")) if c.get("last")
                     else c.get("name", "") for c in creators)


def type_text(item_type: str | None) -> str | None:
    """'Journal article' for journalArticle, article-journal, JOUR…; else the type's own name in words."""
    return TYPE_TEXT.get(item_type or "") or (re.sub(r"(?<=[a-z])(?=[A-Z])|[_-]", " ", item_type or "").strip().lower()
                                               .capitalize() or None)


def _work_view(r) -> dict:
    creators = json.loads(r["creators_json"] or "[]")
    files = json.loads(r["files_json"] or "[]")
    return {"key": r["item_key"], "title": r["title"], "cite": cite(creators, r["year"]), "authors": _full_names(creators),
            "year": r["year"], "type": type_text(r["item_type"]),
            "container": r["container"], "doi": r["doi"], "url": r["url"], "link": r["link"],
            "file": next((f["name"] for f in files if f.get("exists") and Path(f["path"]).suffix.lower() in READABLE),
                         None)}


def view(ws: Workspace) -> dict:
    meta = ws.meta("bibliography")
    if not meta:
        return {"bibliography": None}
    works = {r["item_key"]: _work_view(r) for r in ws.query("SELECT * FROM bib_items ORDER BY seq")}
    docs = {r["doc_id"]: {"doc_id": r["doc_id"], "title": r["title"], "file": re.sub(r".*[/\\]", "", r["path"] or ""),
                          "kind": r["kind"], "pages": r["n_pages"], "added_at": r["added_at"],
                          "file_title": file_title(r)}
            for r in ws.query("SELECT doc_id, title, file_title, path, kind, n_pages, added_at FROM documents "
                              "ORDER BY title")}
    links = [dict(r) for r in ws.query("SELECT item_key, doc_id, status, method, score, evidence_json, decided_at "
                                       "FROM bib_links")]
    linked, confirm, seen_items, seen_docs = [], [], set(), set()
    for ln in links:
        w, d = works.get(ln["item_key"]), docs.get(ln["doc_id"])
        if not w or not d or ln["status"] == "rejected":
            continue
        row = {"work": w, "doc": d, "status": ln["status"], "method": ln["method"], "score": ln["score"]}
        if ln["status"] == "probable":
            ev = row["evidence"] = json.loads(ln["evidence_json"] or "{}")
            if ev.get("offset") is not None:  # the page the title stands on (documents with pages)
                ev["page"] = ws.scalar("SELECT page FROM pages WHERE doc_id=? AND start<=? ORDER BY start DESC LIMIT 1",
                                       (ln["doc_id"], ev["offset"]))
            confirm.append(row)
        else:
            linked.append(row)
        seen_items.add(ln["item_key"])
        seen_docs.add(ln["doc_id"])
    linked.sort(key=lambda r: (r["work"]["title"] or "").lower())
    confirm.sort(key=lambda r: (-(r["score"] or 0), (r["work"]["title"] or "").lower()))
    to_find = [w for k, w in works.items() if k not in seen_items]
    not_in = [d for k, d in docs.items() if k not in seen_docs]
    return {"bibliography": {**meta, "format_text": FORMATS.get(meta.get("format") or "", "")},
            "counts": {"works": len(works), "linked": len({r["work"]["key"] for r in linked}), "confirm": len(confirm),
                       "to_find": len(to_find), "not_in": len(not_in),
                       "files": sum(1 for w in to_find if w["file"])},
            "linked": linked, "confirm": confirm, "to_find": to_find, "not_in": not_in}


def file_title(r) -> str | None:
    """The title read from the file of a document that took its work's title, to show next to it: None when it has
    its own, or when the two have the same words (only case, accents, quote marks or dashes differ)."""
    own = r["file_title"]
    return own if own and _tokens(own) != _tokens(r["title"] or "") else None


def files_to_add(ws: Workspace, keys: list[str] | None = None) -> list[Path]:
    """The files Zotero (or the exported file) has for works without a document yet, that ENLENS can read."""
    have = {r[0] for r in ws.query("SELECT DISTINCT item_key FROM bib_links WHERE status IN ('auto', 'confirmed', "
                                   "'probable')")}
    known = {r[0] for r in ws.query("SELECT sha1 FROM documents")}
    out, seen = [], set()
    for r in ws.query("SELECT item_key, files_json FROM bib_items ORDER BY seq"):
        if r["item_key"] in have or (keys is not None and r["item_key"] not in keys):
            continue
        for f in json.loads(r["files_json"] or "[]"):
            p = Path(f.get("path") or "")
            if (p.suffix.lower() in READABLE and f.get("sha1") not in known and str(p) not in seen
                    and p.is_file()):
                seen.add(str(p))
                out.append(p)
                break  # one file per work: the first readable one (Zotero lists the main file first)
    return out


def new_links(ws: Workspace, doc_ids: set[str]) -> dict:
    """What the matching made of documents just added: how many are linked to a work, how many wait for a person."""
    rows = ws.query("SELECT doc_id, status FROM bib_links WHERE status IN ('auto', 'confirmed', 'probable')")
    linked = {r["doc_id"] for r in rows if r["doc_id"] in doc_ids and r["status"] != "probable"}
    prob = {r["doc_id"] for r in rows if r["doc_id"] in doc_ids and r["status"] == "probable"} - linked
    return {"linked": len(linked), "confirm": len(prob)}


def doc_citations(ws: Workspace) -> dict[str, dict]:
    """The work each document is (linked or confirmed), for the Documents list and the document viewer."""
    out: dict[str, dict] = {}
    for r in ws.query("SELECT l.doc_id, l.status, b.* FROM bib_links l JOIN bib_items b ON b.item_key=l.item_key "
                      "WHERE l.status IN ('auto', 'confirmed') ORDER BY b.seq"):
        if r["doc_id"] in out:
            continue
        w = _work_view(r)
        out[r["doc_id"]] = {"cite": w["cite"], "title": w["title"], "doi": w["doi"], "link": w["link"],
                            "url": w["url"], "type": w["type"], "container": w["container"]}
    return out


def to_find_rows(ws: Workspace) -> list[dict]:
    v = view(ws)
    rows = []
    for w in v.get("to_find") or []:
        rows.append({"Title": w["title"], "Authors": w["authors"], "Year": w["year"] or "", "Type": w["type"] or "",
                     "Published in": w["container"] or "", "DOI": w["doi"] or "",
                     "DOI link": f"https://doi.org/{w['doi']}" if w["doi"] else "", "Web address": w["url"] or "",
                     "Open in Zotero": w["link"] or "", "File in Zotero": w["file"] or ""})
    return rows
