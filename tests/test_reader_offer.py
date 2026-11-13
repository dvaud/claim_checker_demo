"""0.17.2: the Documents page offers reader 4 to a reader-3 document only when reader 4 can read it otherwise (a text
or Word file); a PDF or web page of reader 3 reads the same and is not offered it. Documents of earlier readers are
offered the new reader whatever their kind."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from _fakedom import NODE

SOURCES = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static" / "views" / "doc-shared.js"   # newReaderFor lives here since 0.18.4 (it was in sources.js)


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_reader_4_is_offered_only_where_it_can_change_the_reading(tmp_path):
    src = SOURCES.read_text(encoding="utf-8")
    m = re.search(r"^export function newReaderFor\(d, latest\) \{.*?^\}", src, re.S | re.M)
    assert m, "newReaderFor is gone from doc-shared.js"
    docs = [{"reader": r, "kind": k} for r in (1, 2, 3, 4) for k in ("pdf", "html", "text", "docx")]
    probe = tmp_path / "probe.mjs"
    probe.write_text(m.group(0) + f"\nconsole.log(JSON.stringify({json.dumps(docs)}.map((d) => newReaderFor(d, 4))));\n",
                     encoding="utf-8")
    r = subprocess.run([NODE, str(probe)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    offered = {(d["reader"], d["kind"]) for d, yes in zip(docs, json.loads(r.stdout)) if yes}
    assert offered == {(1, "pdf"), (1, "html"), (1, "text"), (1, "docx"),
                       (2, "pdf"), (2, "html"), (2, "text"), (2, "docx"),
                       (3, "text"), (3, "docx")}
