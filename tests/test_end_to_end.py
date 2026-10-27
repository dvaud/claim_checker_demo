import csv
import json

from enlens_claims import analysis, review
from enlens_claims.cli import main


def test_cli_pipeline_with_baseline(tmp_path, corpus, vca_xlsx, capsys):
    ws = str(tmp_path / "w")
    run = lambda *a: main(["--ws", ws, *a])  # noqa: E731
    assert run("init") == 0
    run("load-vca", str(vca_xlsx))
    run("ingest", str(corpus))
    run("match-sources")
    run("screen")
    run("make-tasks", "split")
    run("run", "split", "--backend", "baseline")
    run("make-tasks", "verify-vca", "--k", "3")
    run("run", "verify_set", "--backend", "baseline")
    run("make-tasks", "extract")
    run("run", "extract", "--backend", "baseline")
    capsys.readouterr()
    run("evaluate")
    metrics = json.loads(capsys.readouterr().out)
    assert metrics["vca_claims"].get("source_missing", 0) >= 1      # 1.1's paper was not provided
    assert metrics["targets_scored"] == 2                            # 6.4 and 8.5 have sources
    assert metrics["target_presence_all_targets"]["tp"] >= 1
    run("report")
    html = (tmp_path / "w" / "report" / "report.html").read_text()
    for heading in ("Does the cited literature support", "Which SDG targets", "synergies and trade-offs",
                    "When do the effects occur", "Where do the effects land", "conditions", "Gaps and new candidates"):
        assert heading in html
    for f in ("effects.csv", "claims.csv", "vca_claims.csv", "interactions.csv", "metrics.json"):
        assert (tmp_path / "w" / "report" / f).exists()
    claims = list(csv.DictReader(open(tmp_path / "w" / "report" / "claims.csv")))
    assert any(r["target"] == "6.4" and r["direction"] == "negative" for r in claims)
    assert all(r["quote"] for r in claims)


def test_inferred_interactions_and_review_roundtrip(loaded, tmp_path):
    from enlens_claims import tasks
    from enlens_claims.llm import BaselineBackend
    from enlens_claims.retrieve import screen

    screen(loaded)
    tasks.make_extract(loaded)
    tasks.run(loaded, "extract", BaselineBackend())
    n = analysis.infer_interactions(loaded)
    inter = analysis.interaction_table(loaded)
    assert n == len([1 for _ in loaded.query("SELECT * FROM interactions WHERE kind LIKE 'inferred%'")])
    assert all(i["relation"] in ("synergy", "trade_off", "shared_pressure") for i in inter)

    path = tmp_path / "queue.csv"
    stats = review.export(loaded, path, audit_fraction=1.0)
    rows = list(csv.DictReader(open(path)))
    assert stats["rows"] == len(rows) and rows
    claim_rows = [r for r in rows if r["item_kind"] == "claim"]
    claim_rows[0]["decision"] = "reject"
    if len(claim_rows) > 1:
        claim_rows[1]["decision"] = "change"
        claim_rows[1]["corrected_targets"] = "6.4:negative:direct"
        claim_rows[1]["corrected_horizon"] = "short_term"
    bad = dict(claim_rows[0], decision="change", corrected_segment="pipeline", item_id=claim_rows[0]["item_id"])
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=review.COLUMNS)
        w.writeheader()
        for r in claim_rows + [bad]:
            w.writerow(r)
    res = review.import_decisions(loaded, path, reviewer="tester")
    assert res["errors"] == 1 and "corrected_segment" in res["error_messages"][0]
    assert loaded.scalar("SELECT status FROM claims WHERE claim_id=?", (claim_rows[0]["item_id"],)) == "rejected"
    if len(claim_rows) > 1:
        cid = claim_rows[1]["item_id"]
        assert loaded.scalar("SELECT status FROM claims WHERE claim_id=?", (cid,)) == "changed"
        assert [tuple(r) for r in loaded.query("SELECT target, direction, influence FROM claim_targets WHERE claim_id=?", (cid,))] == [("6.4", "negative", "direct")]
    assert review.export_gold(loaded, tmp_path / "gold.jsonl") == res["applied"]
    # reviewed items do not come back in the next queue
    again = review.export(loaded, tmp_path / "queue2.csv", audit_fraction=1.0)
    ids = {r["item_id"] for r in csv.DictReader(open(tmp_path / "queue2.csv"))}
    assert claim_rows[0]["item_id"] not in ids and again["rows"] == len(ids)


def test_label_recovery_counts_cells(loaded):
    from enlens_claims import tasks

    # one perfect claim for 6.4 production negative, one wrong-sign claim for 8.5
    t = [r for r in loaded.query("SELECT * FROM passages WHERE text LIKE '%water stress%'")][0]
    with loaded.connect() as cx:
        cx.execute("INSERT INTO claims(claim_id, doc_id, passage_id, claim, segment, countries_json, horizon, side, status) "
                   "VALUES ('c1', ?, ?, 'x', 'production', '[]', 'short_term', 'producer', 'auto')", (t["doc_id"], t["passage_id"]))
        cx.execute("INSERT INTO claim_targets VALUES ('c1', '6.4', 'negative', 'direct')")
        cx.execute("INSERT INTO claims(claim_id, doc_id, passage_id, claim, segment, countries_json, horizon, side, status) "
                   "VALUES ('c2', ?, ?, 'y', 'production', '[]', 'not_stated', 'producer', 'auto')", (t["doc_id"], t["passage_id"]))
        cx.execute("INSERT INTO claim_targets VALUES ('c2', '8.5', 'negative', 'indirect')")
    rec = analysis.label_recovery(loaded)
    assert rec["targets_scored"] == 2
    assert rec["target_presence"]["tp"] == 2 and rec["target_presence"]["fp"] == 0
    assert rec["cell_sign"] == {"n": 2, "agree": 1, "accuracy": 0.5}
    assert rec["cell_influence"] == {"n": 2, "agree": 2, "accuracy": 1.0}
    assert rec["horizon"] == {"n": 1, "agree": 1, "accuracy": 1.0}
