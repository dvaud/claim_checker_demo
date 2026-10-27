#!/usr/bin/env python3
"""Turn a folder of PDFs into small text files the ENLENS pipeline reads exactly as it reads the PDFs.

Each PDF becomes <name>.txt with one form-feed character between pages, so page numbers survive.
HTML files and manifest.csv are copied as they are. The result is zipped for upload.

Usage:
    pip install pypdf
    python3 pdf_to_text.py path/to/sources path/to/manifest.csv
The zip is written next to the sources folder as enlens_text.zip.
"""
from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path


def pdf_pages(path: Path) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # a damaged page should not stop the whole file
            pages.append("")
    return pages


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    src = Path(argv[0]).expanduser().resolve()
    manifest = Path(argv[1]).expanduser().resolve() if len(argv) > 1 else None
    if not src.is_dir():
        print(f"Not a folder: {src}")
        return 2
    out = src.parent / "enlens_text"
    if out.exists():
        shutil.rmtree(out)
    (out / "sources").mkdir(parents=True)
    problems = []
    n = 0
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        if f.suffix.lower() == ".pdf":
            try:
                pages = pdf_pages(f)
            except Exception as e:
                problems.append(f"{f.name}: could not be read ({e})")
                continue
            text = "\f".join(pages)
            (out / "sources" / (f.stem + ".txt")).write_text(text, encoding="utf-8")
            n += 1
            empty = sum(1 for p in pages if len(p.strip()) < 30)
            cid = len(re.findall(r"\(cid:\d+\)", text))
            if empty > len(pages) / 2:
                problems.append(f"{f.name}: {empty} of {len(pages)} pages have no text layer (scanned?)")
            if cid > 200:
                problems.append(f"{f.name}: text layer uses unreadable glyph codes ({cid} found)")
        elif f.suffix.lower() in (".html", ".htm", ".txt", ".md"):
            shutil.copy2(f, out / "sources" / f.name)
            n += 1
    if manifest and manifest.exists():
        shutil.copy2(manifest, out / "manifest.csv")
    zpath = src.parent / "enlens_text.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(out))
    print(f"{n} files converted. Upload this file: {zpath} ({zpath.stat().st_size / 1e6:.1f} MB)")
    for p in problems:
        print("  check:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
