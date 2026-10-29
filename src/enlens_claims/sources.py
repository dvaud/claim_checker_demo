"""Match ingested documents to the references cited in the VCA justifications."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .store import Workspace
from .textutil import STOPWORDS, find_dois, normalise
from .vca import _title_words

_GENERIC = STOPWORDS | {
    "green", "hydrogen", "energy", "review", "analysis", "journal", "international", "research", "study",
    "sustainable", "development", "renewable", "report", "available", "online", "accessed", "paris", "vol",
    "https", "http", "www", "doi", "org", "and", "the", "for", "2019", "2020", "2021", "2022", "2023", "2024",
}


def _ref_words(reference: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", normalise(reference))
    return {w for w in words if len(w) > 3 and w not in _GENERIC and not w.isdigit()}


def declared_refs(value: str | None) -> list[str]:
    """documents.declared_ref holds a JSON list of reference strings (older workspaces: one plain string)."""
    if not value:
        return []
    try:
        v = json.loads(value)
        return [str(x) for x in v] if isinstance(v, list) else [str(v)]
    except json.JSONDecodeError:
        return [value]


def match(ws: Workspace, min_title_score: float = 0.6) -> dict[str, int]:
    from .vca import ref_key

    refs = ws.query("SELECT ref_key, reference, doi, alias_of FROM vca_refs")
    canon = {r["ref_key"]: (r["alias_of"] or r["ref_key"]) for r in refs}
    docs = ws.query("SELECT doc_id, path, title, doi, declared_ref, substr(text, 1, 6000) AS head FROM documents")
    pairs: dict[tuple[str, str], tuple[str, float]] = {}
    by_text = {normalise(r["reference"])[:120]: r["ref_key"] for r in refs}
    unknown_declared = []

    def add(doc_id: str, key: str, method: str, score: float) -> None:
        k = canon.get(key, key)
        if (doc_id, k) not in pairs:
            pairs[(doc_id, k)] = (method, score)

    ref_words = {r["ref_key"]: _title_words(r["reference"]) for r in refs}

    def closest(text: str) -> str | None:
        w = _title_words(text)
        best, score = None, 0.0
        for k, rw in ref_words.items():
            if not w or not rw:
                continue
            j = len(w & rw) / len(w | rw)
            if j > score:
                best, score = k, j
        return best if score >= 0.6 else None

    for d in docs:  # a manifest names the references directly
        if d["declared_ref"] and d["doi"] and f"doi:{d['doi']}" in canon:
            add(d["doc_id"], f"doi:{d['doi']}", "manifest", 1.0)
        for dr in declared_refs(d["declared_ref"]):
            k = ref_key(dr)[0]
            k = k if k in canon else (by_text.get(normalise(dr)[:120]) or closest(dr))
            if k:
                add(d["doc_id"], k, "manifest", 1.0)
            else:
                unknown_declared.append(dr[:80])
    for d in docs:
        head_dois = set(find_dois(d["head"] or ""))
        if d["doi"]:
            head_dois.add(d["doi"])
        for r in refs:
            if r["doi"] and r["doi"] in head_dois:
                add(d["doc_id"], r["ref_key"], "doi", 1.0)
    matched = {k[1] for k in pairs}
    # wording match for references still without a document
    for r in refs:
        if canon[r["ref_key"]] in matched:
            continue
        words = _ref_words(r["reference"])
        if len(words) < 3:
            continue
        best: tuple[str, float] | None = None
        for d in docs:
            if d["declared_ref"]:
                continue  # the manifest already says what this document is
            hay = set(re.findall(r"[a-z0-9]+", normalise(f"{d['path']} {d['title']} {d['head']}")))
            score = len(words & hay) / len(words)
            if best is None or score > best[1]:
                best = (d["doc_id"], score)
        if best and best[1] >= min_title_score:
            add(best[0], r["ref_key"], "title", round(best[1], 3))
            matched.add(canon[r["ref_key"]])
    with ws.connect() as cx:
        # links added by hand (method 'manual', see the manual's troubleshooting) survive a new match
        cx.execute("DELETE FROM doc_refs WHERE method IS NULL OR method != 'manual'")
        cx.executemany("INSERT OR IGNORE INTO doc_refs VALUES (?,?,?,?)", [(d, k, m, s) for (d, k), (m, s) in pairs.items()])
    found = {k[1] for k in pairs}
    out = {"references": sum(1 for r in refs if not r["alias_of"]), "matched_references": len(found),
           "documents_matched": len({k[0] for k in pairs}),
           "by_manifest": sum(1 for v in pairs.values() if v[0] == "manifest"),
           "by_doi": sum(1 for v in pairs.values() if v[0] == "doi"),
           "by_title": sum(1 for v in pairs.values() if v[0] == "title")}
    if unknown_declared:
        out["manifest_references_not_in_vca"] = unknown_declared[:20]
    return out


# a document whose text layer is mostly unreadable is linked but does not count as an available source
UNREADABLE_DOCS = ("SELECT doc_id FROM passages GROUP BY doc_id "
                   "HAVING AVG(section = 'unreadable') > 0.5")


def unreadable_docs(ws: Workspace) -> set[str]:
    return {r[0] for r in ws.query(UNREADABLE_DOCS)}


def docs_for_target(ws: Workspace, target: str) -> list[str]:
    rows = ws.query(
        "SELECT DISTINCT dr.doc_id FROM doc_refs dr JOIN vca_refs r ON r.ref_key = dr.ref_key "
        f"WHERE r.alias_of IS NULL AND r.targets_json LIKE ? AND dr.doc_id NOT IN ({UNREADABLE_DOCS})",
        (f'%"{target}"%',))
    return [r[0] for r in rows]


def coverage(ws: Workspace) -> list[dict]:
    """Per justified target: how many distinct cited works are available as readable documents."""
    out = []
    for t in ws.query("SELECT target FROM vca_targets WHERE justification != '' ORDER BY goal"):
        code = t[0]
        refs = ws.query("SELECT ref_key FROM vca_refs WHERE alias_of IS NULL AND targets_json LIKE ?", (f'%"{code}"%',))
        linked = ws.query(
            "SELECT DISTINCT dr.ref_key, dr.doc_id IN (" + UNREADABLE_DOCS + ") AS bad FROM doc_refs dr "
            "JOIN vca_refs r ON r.ref_key=dr.ref_key WHERE r.alias_of IS NULL AND r.targets_json LIKE ?", (f'%"{code}"%',))
        have = {r[0] for r in linked if not r[1]}
        row = {"target": code, "cited": len(refs), "available": len(have)}
        bad = {r[0] for r in linked if r[1]} - have
        if bad:
            row["unreadable"] = len(bad)
        out.append(row)
    return out


def document_overview(ws: Workspace) -> list[dict]:
    """One row per document with the checks a reader needs before trusting it as a source."""
    bad = unreadable_docs(ws)
    claims = {r[0]: r[1] for r in ws.query("SELECT doc_id, COUNT(DISTINCT claim_id) FROM claims GROUP BY doc_id")}
    out = []
    for d in ws.query("SELECT d.doc_id, d.title, d.kind, d.n_pages, d.n_chars, d.path, d.added_at, d.ocr_pages, "
                      "d.scanned_pages, (SELECT COUNT(*) FROM passages p WHERE p.doc_id=d.doc_id AND p.section='body') AS body "
                      "FROM documents d ORDER BY d.title"):
        flags = []
        ocr, scanned = d["ocr_pages"] or 0, d["scanned_pages"] or 0
        scan = ""
        if ocr:
            scan = "Scanned: text recognised (OCR)" + (f" on {ocr} of {d['n_pages']} pages" if d["n_pages"] and
                                                       ocr < d["n_pages"] else "")
        if scanned > ocr:
            scan = (scan + "; " if scan else "") + (f"Scanned: no text on {scanned - ocr} of {d['n_pages']} pages. "
                                                    "Ask IT to install Tesseract to read it.")
        if d["doc_id"] in bad:
            flags.append("the text could not be read (perhaps a scanned or protected PDF)")
        if d["n_chars"] < 1000:  # a saved landing page or an agenda instead of the report itself
            flags.append("very short: is this the whole document?")
        out.append({"doc_id": d["doc_id"], "title": d["title"] or "", "kind": d["kind"], "pages": d["n_pages"],
                    "chars": d["n_chars"],
                    "passages": d["body"], "claims": claims.get(d["doc_id"], 0), "file": re.sub(r".*[/\\]", "", d["path"] or ""),
                    "added": (d["added_at"] or "")[:16].replace("T", " "), "added_at": d["added_at"] or "",
                    "check": "; ".join(flags), "scanned": scan, "ocr_pages": ocr, "scanned_pages": scanned})
    return out


_SHA1S: dict[tuple, str] = {}  # checksums of original files, by (path, modified, size)


def original_file(ws: Workspace, doc_id: str, verify: bool = True) -> dict:
    """Where the file a document was read from is now: only the path recorded when it was added is used, resolved
    against the project folder when it was recorded relative to it (linked, moved or imported projects).

    Returns {"doc_id", "kind", "title", "recorded", "name", "path" | None, "available", "inside", "reason"};
    `inside` says the file is in the project folder. With `verify`, a file whose checksum differs from the one
    recorded (up to 300 MB) is reported as changed, not available.
    """
    from .ingest import _sha1

    row = ws.query("SELECT path, sha1, kind, title FROM documents WHERE doc_id=?", (doc_id,))
    if not row:
        raise KeyError(doc_id)
    recorded, sha1, kind, title = row[0]["path"] or "", row[0]["sha1"], row[0]["kind"], row[0]["title"]
    out = {"doc_id": doc_id, "kind": kind, "title": title, "recorded": recorded,
           "name": re.sub(r".*[/\\]", "", recorded), "path": None, "available": False, "inside": False, "reason": ""}
    if not recorded:
        out["reason"] = "No file was recorded for this document."
        return out
    p = Path(recorded)
    cands = [p] if p.is_absolute() else [ws.root / p, ws.root.parent / p, Path.cwd() / p]
    parts = Path(recorded.replace("\\", "/")).parts
    for mark in ("uploads", "inputs", "originals"):  # a project that was moved or imported keeps its own copies
        if mark in parts:
            cands.append(ws.root.joinpath(*parts[len(parts) - 1 - parts[::-1].index(mark):]))
    root = ws.root.resolve()
    for c in cands:
        try:
            c = c.resolve()
        except OSError:
            continue
        if not c.is_file():
            continue
        if not p.is_absolute() and not (c.is_relative_to(root) or c.is_relative_to(root.parent)):
            continue
        st = c.stat()
        key = (str(c), st.st_mtime_ns, st.st_size)
        if verify and key not in _SHA1S and st.st_size <= 300 * 1024 ** 2:
            _SHA1S[key] = _sha1(c)
        if verify and sha1 and key in _SHA1S and _SHA1S[key] != sha1:
            out["reason"] = f"The file at {c} has changed since it was added; the text the app read is shown here."
            return out
        out.update(path=str(c), available=True, inside=c.is_relative_to(root))
        return out
    out["reason"] = f"The original file is no longer at {recorded}; the text the app read is shown here."
    return out
