"""Does the hypothesis checker's second sorting pass (search.rerank) bring more excerpts from the cited sources into
the top k? Measured on a workspace with VCA claims and cited references (the pilot), without any model:

    python tools/eval_second_pass.py pilot

The workspace is copied to a temporary folder first (opening it would add 0.6's columns to the original).
For each VCA claim whose target has readable cited sources, the claim's text is searched over all documents with
and without the second pass, and the excerpts from cited sources among the top k are counted.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(folder: str) -> dict:
    from enlens_claims.search import rank_passages
    from enlens_claims.sources import docs_for_target
    from enlens_claims.store import Workspace

    tmp = Path(tempfile.mkdtemp(prefix="enlens-eval-"))
    for name in ("enlens.sqlite", "config.json"):
        if (Path(folder) / name).exists():
            shutil.copy2(Path(folder) / name, tmp / name)
    ws = Workspace.open(tmp)
    claims = [(vc["text"], set(docs_for_target(ws, vc["target"])))
              for vc in ws.query("SELECT target, text FROM vca_claims ORDER BY target, seq")]
    claims = [c for c in claims if c[1]]
    out = {"claims": len(claims)}
    for k in (6, 8):
        res = {}
        for label, second in (("without", False), ("with", True)):
            cited = first = 0
            for text, docs in claims:
                got = rank_passages(ws, text, [], k=k, per_doc=2, second_pass=second)
                cited += sum(p["doc_id"] in docs for p in got)
                first += int(bool(got) and got[0]["doc_id"] in docs)
            res[label] = {"cited_in_top_k": cited, "first_excerpt_cited": first}
        out[f"k={k}"] = res
    shutil.rmtree(tmp, ignore_errors=True)
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "pilot")), indent=1))
