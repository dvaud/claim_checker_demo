"""A pytest plugin (a developer's check, not part of the app): the fingerprint of every document the tests read, by
each frozen reader, to show that a change to the reader leaves the frozen readers byte-identical.

    FP_OUT=/tmp/fp-before PYTHONPATH=<old src>:tools python -m pytest -p reader_fingerprints_pytest tests ...
    FP_OUT=/tmp/fp-after  PYTHONPATH=<new src>:tools python -m pytest -p reader_fingerprints_pytest tests ...
    python tools/reader_fingerprints_pytest.py /tmp/fp-before /tmp/fp-after

Every time a test makes a Document (`reader.build_document`), the same raw file is also read by the readers in
FP_READERS (default "2 3") and their fingerprints are written, keyed by the file's checksum and the reading's
lengths, to a file per process in FP_OUT. Comparing two runs lists the documents read otherwise.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path


def pytest_configure(config):
    out = os.environ.get("FP_OUT")
    if not out:
        return
    from enlens_claims import measure, reader

    readers = [int(r) for r in os.environ.get("FP_READERS", "2 3").split()]
    real = reader.build_document
    sink = Path(out) / f"{os.getpid()}.jsonl"
    sink.parent.mkdir(parents=True, exist_ok=True)
    busy = []

    def build_document(raw, max_chars=1100, min_chars=200, version=reader.READER):
        if not busy and getattr(raw, "sha1", None):
            busy.append(1)
            try:
                rec = {"sha1": raw.sha1, "kind": raw.kind, "max": max_chars, "min": min_chars}
                for r in readers:
                    try:
                        rec[str(r)] = measure.fingerprint(real(copy.deepcopy(raw), max_chars, min_chars, r))
                    except Exception as e:  # noqa: BLE001
                        rec[str(r)] = f"error: {type(e).__name__}"
                with sink.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
            finally:
                busy.clear()
        return real(raw, max_chars, min_chars, version)

    reader.build_document = build_document


def _load(folder: Path) -> dict:
    got: dict = {}
    for f in folder.glob("*.jsonl"):
        for line in f.read_text("utf-8").splitlines():
            rec = json.loads(line)
            key = (rec.pop("sha1"), rec.pop("kind"), rec.pop("max"), rec.pop("min"))
            got.setdefault(key, set()).add(json.dumps(rec, sort_keys=True))
    return got


def compare(a: Path, b: Path) -> int:
    x, y = _load(a), _load(b)
    both = set(x) & set(y)
    differ = [k for k in sorted(both) if x[k] != y[k]]
    for k in differ:
        print(k, sorted(x[k]), "->", sorted(y[k]))
    print(f"{len(x)} readings before, {len(y)} after, {len(both)} in both, {len(differ)} differ")
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(compare(Path(sys.argv[1]), Path(sys.argv[2])))
