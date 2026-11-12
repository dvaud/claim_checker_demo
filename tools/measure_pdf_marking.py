"""How long placing a few marks on a large PDF takes, and the peak memory (a developer's measurement, not the app).

    PYTHONPATH=src python tools/measure_pdf_marking.py make BIG.pdf --pages 1000
    PYTHONPATH=src python tools/measure_pdf_marking.py place BIG.pdf

`place` runs `annotate.place` once for three marks (on pages 10, the middle one and the last but one, each by its
page) and prints the wall-clock seconds and the process's peak resident memory. Run each measurement in a fresh
process.
"""
from __future__ import annotations

import argparse
import random
import resource
import sys
import time
from pathlib import Path

WORDS = ("water hydrogen plant river farm city supply demand electrolyser desalination operator region export "
         "grid solar wind storage price policy").split()


def page_text(n: int) -> str:
    rnd = random.Random(n)
    lines = [f"Page {n} marker sentence for page {n} of the long report."]
    lines += [" ".join(rnd.choice(WORDS) for _ in range(14)) + "." for _ in range(45)]
    return "\n".join(lines)


def make(path: Path, pages: int) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
    from helpers import make_pdf

    make_pdf(path, [page_text(i) for i in range(1, pages + 1)])


def place(path: Path) -> None:
    from pypdf import PdfReader

    from enlens_claims import annotate

    n = len(PdfReader(str(path)).pages)
    marks = [annotate.Mark(0, 0, f"marker sentence for page {p} of", "supports", "", "judgements", page=p)
             for p in (10, n // 2, n - 1)]
    t = time.perf_counter()
    info = annotate.place(path, marks)
    secs = time.perf_counter() - t
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss / 1024 ** 2 if sys.platform == "darwin" else rss / 1024
    print(f"pages {info['pages']}  placed {sum(m.placed for m in marks)}/{len(marks)} "
          f"({', '.join(f'p{m.page} {m.method}' for m in marks)})  {secs:.1f} s  peak RSS {rss_mb:.0f} MB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["make", "place"])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--pages", type=int, default=1000)
    a = ap.parse_args()
    make(a.pdf, a.pages) if a.what == "make" else place(a.pdf)


if __name__ == "__main__":
    main()
