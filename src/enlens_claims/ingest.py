"""Read PDFs, HTML and text into documents and passages with page and character offsets.

All offsets point into the stored document text: one cleaned string per document, pages joined by a
blank line. Quotes, evidence and highlights are resolved against that string.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from .store import Workspace, now
from .textutil import find_dois, split_sentences

SUPPORTED = {".pdf", ".html", ".htm", ".txt", ".md"}
REF_HEADING = re.compile(
    r"(?:^|\s)(References|REFERENCES|Bibliography|BIBLIOGRAPHY|Literature [Cc]ited|Works [Cc]ited|Reference [Ll]ist)"
    r"\s*:?\s+(?=\[?\(?\d|[A-Z][A-Za-z'\-]+,?\s+[A-Z]|[A-Z]{2,})"
)


@dataclass
class RawDoc:
    path: Path
    kind: str
    pages: list[str]
    meta_title: str | None = None
    sha1: str = ""
    paginated: bool = True  # False for text without page breaks: passages then carry no page number


@dataclass
class Passage:
    seq: int
    start: int
    end: int
    page: int | None
    section: str


@dataclass
class Document:
    doc_id: str
    raw: RawDoc
    text: str
    page_spans: list[tuple[int, int]]
    title: str
    doi: str | None
    passages: list[Passage] = field(default_factory=list)


# ------------------------------------------------------------------------------------------
# reading
# ------------------------------------------------------------------------------------------
class _TextOnly(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "table", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "noscript"):
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "noscript") and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
        elif not self.skip:
            self.parts.append(data)


def read_file(path: Path) -> RawDoc:
    data = path.read_bytes()
    sha1 = hashlib.sha1(data).hexdigest()
    ext = path.suffix.lower()
    if ext == ".pdf":
        pages, title = _read_pdf(path)
        return RawDoc(path, "pdf", pages, title, sha1)
    if ext in (".html", ".htm"):
        p = _TextOnly()
        p.feed(data.decode("utf-8", errors="replace"))
        return RawDoc(path, "html", ["".join(p.parts)], (p.title or "").strip() or None, sha1, paginated=False)
    text = data.decode("utf-8", errors="replace")
    if ext == ".md":
        text = strip_markdown(text)
    pages = text.split("\f") if "\f" in text else [text]
    return RawDoc(path, "text", pages, None, sha1, paginated="\f" in text)


def strip_markdown(text: str) -> str:
    """Remove markdown table rules, cell bars and heading marks so table text reads as plain words."""
    lines = []
    for ln in text.split("\n"):
        if re.fullmatch(r"[\s|:\-]*\|[\s|:\-]*", ln) and "-" in ln:
            continue  # table separator row
        ln = re.sub(r"^\s{0,3}#{1,6}\s+", "", ln)
        ln = re.sub(r"\s*\|\s*", " ", ln)
        lines.append(ln)
    return "\n".join(lines)


def _read_pdf(path: Path) -> tuple[list[str], str | None]:
    pages: list[str] = []
    title = None
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        try:
            meta = reader.metadata
            title = (meta.title if meta else None) or None
        except Exception:
            title = None
        for pg in reader.pages:
            try:
                pages.append(pg.extract_text() or "")
            except Exception:
                pages.append("")
    except Exception:
        pages = []
    if sum(len(p.strip()) for p in pages) < 200:
        try:  # optional fallback
            from pdfminer.high_level import extract_text

            alt = extract_text(str(path)) or ""
            if len(alt.strip()) > sum(len(p.strip()) for p in pages):
                pages = alt.split("\f")
        except Exception:
            pass
    if title and (len(title) < 8 or re.search(r"microsoft|untitled|\.docx?$|\.pdf$", title, re.I)):
        title = None
    return pages, title


# ------------------------------------------------------------------------------------------
# cleaning and segmentation
# ------------------------------------------------------------------------------------------
def clean_page(text: str) -> str:
    t = text.replace("\r", "\n")
    t = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", t)  # hyphenation at line ends
    t = re.sub(r"[ \t\f\v]+", " ", t)
    t = re.sub(r"\s*\n\s*", " ", t)  # line breaks inside a page become spaces
    return t.strip()


def assemble(pages: list[str]) -> tuple[str, list[tuple[int, int]]]:
    text_parts: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    for i, p in enumerate(pages):
        c = clean_page(p)
        if i:
            text_parts.append("\n\n")
            pos += 2
        spans.append((pos, pos + len(c)))
        text_parts.append(c)
        pos += len(c)
    return "".join(text_parts), spans


def page_of(offset: int, spans: list[tuple[int, int]]) -> int:
    """1-based page number for a document offset (the blank line after a page counts as that page)."""
    for i, (_s, e) in enumerate(spans):
        if offset < e + 2:
            return i + 1
    return max(1, len(spans))


def references_start(text: str) -> int | None:
    """Offset where the reference list begins, if a heading is found in the last 60% of the text."""
    floor = int(len(text) * 0.4)
    best = None
    for m in REF_HEADING.finditer(text):
        if m.start(1) >= floor:
            best = m.start(1)
            break
    return best


def reference_like(s: str) -> bool:
    """True for passages that read like bibliography entries rather than prose."""
    years = len(re.findall(r"\b(19|20)\d{2}[a-z]?\b", s))
    dois = len(re.findall(r"10\.\d{4,9}/", s))
    etal = len(re.findall(r"\bet al\.?", s))
    vols = len(re.findall(r"\b\d+\s*\(\d+\)\s*[:,]\s*\d+", s)) + len(re.findall(r"\bpp?\.\s*\d+", s))
    words = max(1, len(s.split()))
    return dois >= 2 or (years + etal + vols) / words > 0.08


CID_RE = re.compile(r"\(cid:\d+\)")
_WORD_RE = re.compile(r"[^\W\d_]{2,}")
# function words of the languages the corpus may contain; prose has many, glyph-code garble has none
_FUNCTION_WORDS = frozenset(
    "the of and to in for is on that by with as are from be this or an at which it can will not has have was "
    "de la le les et des du en el los las y que con por para del una un se al lo es da do dos das em os ao "
    "der die das und von mit den dem ist im zu het een van voor op te zijn niet".split())


def unreadable(s: str) -> bool:
    """True when a PDF text layer has no usable character map.

    Two forms occur: '(cid:53)(cid:72)...' codes, and fonts whose glyph codes come out as shifted
    letters and control characters ('5HQHZDEOH DQG ...' for 'Renewable and ...').
    """
    n = max(1, len(s))
    if len(CID_RE.findall(s)) * 8 > 0.2 * n:
        return True
    ctrl = sum(1 for c in s if (ord(c) < 32 and c not in "\n\t") or c == "�" or 0xE000 <= ord(c) <= 0xF8FF)
    if ctrl > 0.05 * n:
        return True
    words = _WORD_RE.findall(s.lower())
    numbers = len(re.findall(r"(?<![^\s(])\d[\d.,%]*(?![^\s),;:])", s))  # tables and charts are mostly numbers
    return (len(words) >= 30 and numbers < 0.1 * len(words)
            and sum(w in _FUNCTION_WORDS for w in words) < 0.02 * len(words))


def make_passages(text: str, spans: list[tuple[int, int]], max_chars: int = 1100, min_chars: int = 200) -> list[Passage]:
    ref_at = references_start(text)
    sents: list[tuple[int, int]] = []
    for s, e in spans:
        for a, b in split_sentences(text[s:e], offset=s):
            # break very long "sentences" (tables, run-on extraction) at whitespace
            while b - a > max_chars:
                cut = text.rfind(" ", a + min_chars, a + max_chars)
                cut = cut if cut > a else a + max_chars
                sents.append((a, cut))
                a = cut + 1
            if b > a:
                sents.append((a, b))
    out: list[Passage] = []
    cur: list[tuple[int, int]] = []

    def flush():
        if not cur:
            return
        a, b = cur[0][0], cur[-1][1]
        pg = page_of(a, spans)
        if ref_at is not None and a >= ref_at:
            section = "references"
        elif unreadable(text[a:b]):
            section = "unreadable"
        elif reference_like(text[a:b]):
            section = "reference_like"
        else:
            section = "body"
        out.append(Passage(len(out), a, b, pg, section))
        cur.clear()

    for a, b in sents:
        crosses_refs = ref_at is not None and cur and cur[0][0] < ref_at <= a
        new_page = cur and page_of(a, spans) != page_of(cur[0][0], spans)
        if cur and ((b - cur[0][0] > max_chars) or crosses_refs or (new_page and cur[-1][1] - cur[0][0] >= min_chars)):
            flush()
        cur.append((a, b))
    flush()
    return out


def guess_title(raw: RawDoc, text: str) -> str:
    if raw.meta_title:
        return re.sub(r"\s+", " ", raw.meta_title).strip()[:300]
    head = text[:400]
    first = re.split(r"(?<=[.!?])\s", head)[0]
    return (first or raw.path.stem)[:200]


def guess_doi(raw: RawDoc, text: str, spans: list[tuple[int, int]]) -> str | None:
    """The paper's own DOI: from the file name, else the most frequent DOI before the references."""
    stem = raw.path.stem.replace("_", "/").replace("%2F", "/")
    from_name = find_dois(stem)
    if from_name:
        return from_name[0]
    cut = references_start(text) or len(text)
    counts: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for s, e in spans[:4]:
        for d in find_dois(text[s:min(e, cut)]):
            counts[d] += 1
            first_seen.setdefault(d, s)
    if not counts:
        return None
    return sorted(counts, key=lambda d: (-counts[d], first_seen[d]))[0]


def build_document(raw: RawDoc, max_chars: int = 1100, min_chars: int = 200) -> Document:
    text, spans = assemble(raw.pages)
    doc = Document("d" + raw.sha1[:10], raw, text, spans, guess_title(raw, text), guess_doi(raw, text, spans))
    doc.passages = make_passages(text, spans, max_chars, min_chars)
    if not raw.paginated:
        for p in doc.passages:
            p.page = None
    return doc


# ------------------------------------------------------------------------------------------
# input discovery
# ------------------------------------------------------------------------------------------
def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> list[Path]:
    out = []
    root = dest.resolve()
    for info in zf.infolist():
        name = info.filename
        if info.is_dir() or name.startswith("__MACOSX") or Path(name).name.startswith("._"):
            continue
        target = (dest / name).resolve()
        if not str(target).startswith(str(root)):
            continue  # zip-slip guard
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        out.append(target)
    return out


def read_manifests(files: list[Path]) -> dict[str, dict]:
    """manifest.csv files (columns file, reference, doi) say which references each file is.

    Several rows may point at the same file (one work cited in several ways). Keyed by file name.
    """
    import csv

    out: dict[str, dict] = {}
    for m in files:
        if m.name.lower() != "manifest.csv":
            continue
        with open(m, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                names = set()
                for col in ("file", "markdown_file", "text_file"):
                    pth = Path((row.get(col) or "").strip())
                    if pth.name:
                        names |= {pth.name, "stem:" + pth.stem}  # a converted copy (.txt) keeps the stem
                for name in filter(None, names):
                    e = out.setdefault(name, {"references": [], "doi": ""})
                    ref = (row.get("reference") or "").strip()
                    if ref and ref not in e["references"]:
                        e["references"].append(ref)
                    if (row.get("doi") or "").strip() and not e["doi"]:
                        e["doi"] = row["doi"].strip()
    return out


# notes that travel with a corpus but are not sources
NOT_SOURCES = {"problems.txt", "readme.txt", "readme.md", "license.txt", "notes.txt", "worker_guide.md", "system.md"}


def discover(inputs: list[str | Path], unpack_dir: Path, manifests: list[Path] | None = None) -> list[Path]:
    files: list[Path] = []
    queue = [Path(p) for p in inputs]
    depth: dict[Path, int] = {}
    while queue:
        p = queue.pop(0)
        if p.is_dir():
            queue.extend(sorted(x for x in p.rglob("*") if x.is_file()))
        elif p.suffix.lower() == ".zip" and zipfile.is_zipfile(p):
            if depth.get(p, 0) > 2:
                continue
            dest = unpack_dir / re.sub(r"[^A-Za-z0-9._-]", "_", p.stem)
            with zipfile.ZipFile(p) as zf:
                for x in _safe_extract(zf, dest):
                    depth[x] = depth.get(p, 0) + 1
                    queue.append(x)
        elif p.suffix.lower() in SUPPORTED and p.is_file() and p.name.lower() not in NOT_SOURCES:
            files.append(p)
        elif p.name.lower() == "manifest.csv" and manifests is not None:
            manifests.append(p)
    return files


def ingest(ws: Workspace, inputs: list[str | Path], exclude: list[str] | None = None,
           progress=None) -> dict[str, int]:
    """Add documents. `exclude` holds file-name patterns (e.g. 'A_18_*') to leave out, such as a wrong download.

    `progress(done, total, file_name)` is called before each file is read (for a progress bar).
    """
    from fnmatch import fnmatch

    from .textutil import clean_doi

    cfg = ws.config["passages"]
    manifest_files: list[Path] = []
    files = discover(inputs, ws.root / "inputs", manifest_files)
    skipped = [f for f in files if any(fnmatch(f.name, pat) for pat in exclude or [])]
    files = [f for f in files if f not in skipped]
    declared = read_manifests(manifest_files)
    stats = {"files": len(files), "added": 0, "duplicates": 0, "empty": 0, "passages": 0, "declared": 0}
    if exclude:
        stats["excluded"] = [f.name for f in skipped]
    with ws.connect() as cx:
        known = {r[0] for r in cx.execute("SELECT sha1 FROM documents")}
        for i, f in enumerate(files):
            if progress:
                progress(i, len(files), f.name)
            raw = read_file(f)
            if raw.sha1 in known:
                stats["duplicates"] += 1
                continue
            doc = build_document(raw, cfg["max_chars"], cfg["min_chars"])
            if len(doc.text.strip()) < 100:
                stats["empty"] += 1
                continue
            known.add(raw.sha1)
            dec = declared.get(f.name) or declared.get("stem:" + f.stem) or {}
            if dec:
                stats["declared"] += 1
                doc.doi = clean_doi(dec.get("doi")) or doc.doi
                if dec["references"]:
                    doc.title = re.sub(r"https?://\S+", "", dec["references"][0]).strip(" ,.")[:250]
            elif declared:
                stats.setdefault("not_in_manifest", []).append(f.name)
            cx.execute("INSERT INTO documents(doc_id, path, sha1, title, doi, kind, n_pages, n_chars, text, added_at, "
                       "declared_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (doc.doc_id, str(f), raw.sha1, doc.title, doc.doi, raw.kind,
                        len(doc.page_spans) if raw.paginated else None,
                        len(doc.text), doc.text, now(), json.dumps(dec["references"], ensure_ascii=False) if dec else None))
            if raw.paginated:
                cx.executemany("INSERT INTO pages VALUES (?,?,?,?)",
                               [(doc.doc_id, i + 1, s, e) for i, (s, e) in enumerate(doc.page_spans)])
            cx.executemany(
                "INSERT INTO passages(passage_id, doc_id, seq, page, start, end, text, section) VALUES (?,?,?,?,?,?,?,?)",
                [(f"{doc.doc_id}:{p.seq:04d}", doc.doc_id, p.seq, p.page, p.start, p.end, doc.text[p.start:p.end], p.section)
                 for p in doc.passages])
            stats["added"] += 1
            stats["passages"] += len(doc.passages)
            bad = sum(1 for p in doc.passages if p.section == "unreadable")
            if bad > 0.3 * max(1, len(doc.passages)):
                stats.setdefault("mostly_unreadable", []).append(f.name)
    return stats


def doc_text(ws: Workspace, doc_id: str) -> str:
    return ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc_id,)) or ""

