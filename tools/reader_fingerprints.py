"""The fingerprint of every file of a folder as each named reader reads it (a developer's check, not part of the app).

A reader number is frozen: a change to the reader must leave what an existing reader number makes of every document
byte-identical. Run this before and after a change, on the same folder, and compare the two files it writes:

    PYTHONPATH=src python tools/reader_fingerprints.py FOLDER OUT.json --readers 3 4
    python tools/reader_fingerprints.py --compare BEFORE.json AFTER.json

The fingerprint is `measure.fingerprint` of `ingest.read_document(path, reader=n)`: the text, every passage's place,
page, section and block, and the page spans. Files are read in parallel processes.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


def _one(args: tuple[str, list[int]]) -> tuple[str, dict]:
    from enlens_claims import ingest, measure

    path, readers = args
    out: dict = {}
    for r in readers:
        t = time.perf_counter()
        try:
            doc = ingest.read_document(Path(path), reader=r)
            out[str(r)] = {"fp": measure.fingerprint(doc), "passages": len(doc.passages),
                           "seconds": round(time.perf_counter() - t, 2)}
        except Exception as e:  # noqa: BLE001 - a file a reader cannot read is a result too
            out[str(r)] = {"fp": f"error: {e!r}"[:200], "passages": 0, "seconds": round(time.perf_counter() - t, 2)}
    return Path(path).name, out


def run(folder: Path, out: Path, readers: list[int], workers: int) -> None:
    files = sorted(str(p) for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    got: dict = {}
    with ProcessPoolExecutor(workers) as pool:
        for name, fps in pool.map(_one, [(f, readers) for f in files]):
            got[name] = fps
            print(name, " ".join(f"r{r}={v['fp'][:10]}" for r, v in fps.items()), flush=True)
    out.write_text(json.dumps(got, indent=1, sort_keys=True), encoding="utf-8")


def compare(a: Path, b: Path) -> int:
    x, y = json.loads(a.read_text("utf-8")), json.loads(b.read_text("utf-8"))
    differ = 0
    for name in sorted(set(x) | set(y)):
        for r in sorted(set(x.get(name, {})) & set(y.get(name, {})) or {"(missing)"}):  # readers read both times
            fa = x.get(name, {}).get(r, {}).get("fp")
            fb = y.get(name, {}).get(r, {}).get("fp")
            if fa != fb:
                differ += 1
                print(f"{name} reader {r}: {fa} -> {fb}")
    print(f"{len(set(x) | set(y))} files, {differ} differ")
    return 1 if differ else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs=2, type=Path, help="FOLDER OUT.json, or with --compare BEFORE.json AFTER.json")
    ap.add_argument("--readers", type=int, nargs="+", default=[3])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--compare", action="store_true")
    a = ap.parse_args(argv)
    if a.compare:
        return compare(*a.paths)
    run(a.paths[0], a.paths[1], a.readers, a.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
