"""Reviewer queue as a spreadsheet: export what needs a person, import their decisions as labels."""
from __future__ import annotations

import csv
import json
import random
import re
from pathlib import Path
from typing import Any

from .analysis import vca_support
from .store import Workspace, now
from .taxonomy import CLAIM_SEGMENTS, DIRECTIONS, HORIZONS, INFLUENCES, normalise_target

COLUMNS = ["item_kind", "item_id", "reason", "text", "targets", "segment", "horizon", "place", "condition",
           "quote", "source", "page", "decision", "corrected_targets", "corrected_segment", "corrected_horizon",
           "reviewer", "note"]
DECISIONS = ("accept", "change", "reject")


def _targets_str(ws: Workspace, claim_id: str) -> str:
    return "; ".join(f"{r['target']}:{r['direction']}:{r['influence']}"
                     for r in ws.query("SELECT * FROM claim_targets WHERE claim_id=? ORDER BY target", (claim_id,)))


def export(ws: Workspace, path: str | Path, audit_fraction: float = 0.05, seed: int = 0,
           include_vca: bool = True) -> dict[str, int]:
    rng = random.Random(seed)
    reviewed = {r[0] for r in ws.query("SELECT DISTINCT item_id FROM reviews WHERE field != 'superseded'")}
    rows = []
    claims = ws.query("SELECT c.*, d.title, p.page FROM claims c JOIN documents d ON d.doc_id=c.doc_id "
                      "JOIN passages p ON p.passage_id=c.passage_id WHERE c.status IN ('needs_review','auto') ORDER BY c.claim_id")
    n_review = n_audit = 0
    for c in claims:
        if c["claim_id"] in reviewed:
            continue
        if c["status"] == "needs_review":
            reason = c["status_reason"] or "needs review"
            n_review += 1
        elif rng.random() < audit_fraction:
            reason = "random audit sample"
            n_audit += 1
        else:
            continue
        ev = ws.query("SELECT quote FROM evidence WHERE claim_id=? AND field='claim' LIMIT 1", (c["claim_id"],))
        rows.append({"item_kind": "claim", "item_id": c["claim_id"], "reason": reason, "text": c["claim"],
                     "targets": _targets_str(ws, c["claim_id"]), "segment": c["segment"], "horizon": c["horizon"],
                     "place": c["place_text"] or "", "condition": c["condition"] or c["policy_lever"] or "",
                     "quote": ev[0][0] if ev else "", "source": c["title"], "page": c["page"]})
    n_vca = 0
    if include_vca:
        for v in vca_support(ws):
            if v["status"] not in ("contradicted", "unsupported") or v["vca_claim_id"] in reviewed:
                continue
            q = (v["refute"] or v["support"] or [{}])[0]
            rows.append({"item_kind": "vca_claim", "item_id": v["vca_claim_id"], "reason": f"VCA claim {v['status']}",
                         "text": v["text"], "targets": v["target"], "segment": v["segment"], "horizon": v["horizon"],
                         "quote": q.get("quote", ""), "source": q.get("title", ""), "page": q.get("page", "")})
            n_vca += 1
    with open(path, "w", newline="", encoding="utf-8") as f:
        write_csv(f, [{k: r.get(k, "") for k in COLUMNS} for r in rows], COLUMNS)
    return {"rows": len(rows), "needs_review": n_review, "audit": n_audit, "vca_claims": n_vca}


def _parse_targets(s: str) -> list[tuple[str, str, str]]:
    out = []
    for part in [p.strip() for p in (s or "").split(";") if p.strip()]:
        bits = [b.strip() for b in part.split(":")]
        code = normalise_target(bits[0])
        if not code:
            raise ValueError(f"unknown target in {part!r}")
        direction = bits[1].lower() if len(bits) > 1 and bits[1] else "positive"
        influence = bits[2].lower() if len(bits) > 2 and bits[2] else "unclear"
        if direction not in DIRECTIONS:
            raise ValueError(f"bad direction in {part!r}; use one of {', '.join(DIRECTIONS)}")
        if influence not in INFLUENCES:
            raise ValueError(f"bad influence in {part!r}; use one of {', '.join(INFLUENCES)}")
        out.append((code, direction, influence))
    return out


# ---------------------------------------------------------------------------------------------
# Spreadsheets ENLENS writes (CSV and Excel). Their text comes from documents (a table read from a PDF), bibliography
# files and colleagues (a hypothesis, a note, a name, a quote), and a spreadsheet runs text that looks like a formula:
# "=HYPERLINK(...)" in a cell sends the cells beside it away when clicked, "=WEBSERVICE(...)" without a click. Every
# CSV goes through `write_csv` (its cells through `csv_cell`), every Excel row through `append_row`.
# ---------------------------------------------------------------------------------------------
_PLAIN_NUMBER = re.compile(r"[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?%?")


def csv_cell(value: Any) -> Any:
    """A cell for a CSV file, as text a spreadsheet shows and does not run. The program that opens a CSV decides what
    a cell is, so text it could take for a formula gets a leading apostrophe ("'=1+1"): text that starts with "=",
    "@", a tab or a carriage return, and text that starts with "+" or "-" unless it is a plain number (an optional
    sign, digits with an optional decimal part or thousands separators, an optional "%": "-5", "+1,200.5", "-3%"),
    the sign is followed by a space ("- a list item") or it is the sign alone ("-"): quotes are compared by their
    text, so those stay as written. Numbers (int, float) and anything that is not text are never changed."""
    if not isinstance(value, str) or not value:
        return value
    first = value[0]
    if first in "=@\t\r":
        return "'" + value
    if first in "+-":
        if len(value) == 1 or value[1] == " " or _PLAIN_NUMBER.fullmatch(value):
            return value
        return "'" + value
    return value


def write_csv(out, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    """Rows as CSV into an open text file (or a StringIO), with a header row: the keys of the first row unless
    `fieldnames` names them (then the header is written even with no rows); nothing at all for no rows and no
    `fieldnames`. Every cell, the header's too, goes through `csv_cell`."""
    if fieldnames is None:
        if not rows:
            return
        fieldnames = list(rows[0])
    csv.writer(out).writerow([csv_cell(h) for h in fieldnames])
    w = csv.DictWriter(out, fieldnames=fieldnames)
    w.writerows({k: csv_cell(v) for k, v in r.items()} for r in rows)


def append_row(sheet, values: list) -> None:
    """Append a row to an Excel sheet (openpyxl) with every text cell written as text. openpyxl writes text that
    starts with "=" as a formula (and "#N/A" as an error), which Excel runs; set as text it shows as written, with
    no apostrophe added. Numbers and dates stay what they are."""
    sheet.append(values)
    r = sheet.max_row
    for j, v in enumerate(values, 1):
        if isinstance(v, str):
            sheet.cell(row=r, column=j).data_type = "s"


def read_csv_rows(path: str | Path) -> list[dict]:
    """Rows of a CSV file as saved by a spreadsheet: UTF-8 with or without a byte-order mark, else Windows-1252."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    import io

    return [{(k or "").strip(): v for k, v in r.items()} for r in csv.DictReader(io.StringIO(text, newline=""))]


def import_decisions(ws: Workspace, path: str | Path, reviewer: str = "") -> dict[str, int]:
    stats = {"rows": 0, "applied": 0, "skipped": 0, "errors": 0}
    errors = []
    rows = read_csv_rows(path)
    with ws.connect() as cx:
        for i, r in enumerate(rows, start=2):
            stats["rows"] += 1
            d = (r.get("decision") or "").strip().lower()
            if d not in DECISIONS:
                stats["skipped"] += 1
                continue
            who = r.get("reviewer") or reviewer
            try:
                corrected = {}
                if r["item_kind"] == "claim":
                    cid = r["item_id"]
                    if d == "accept":
                        cx.execute("UPDATE claims SET status='accepted', status_reason='reviewer accepted' WHERE claim_id=?", (cid,))
                    elif d == "reject":
                        cx.execute("UPDATE claims SET status='rejected', status_reason='reviewer rejected' WHERE claim_id=?", (cid,))
                    else:
                        # validate every correction before changing anything
                        tg = _parse_targets(r["corrected_targets"]) if r.get("corrected_targets") else None
                        fields = {}
                        for fld, allowed in (("segment", CLAIM_SEGMENTS), ("horizon", HORIZONS)):
                            v = (r.get(f"corrected_{fld}") or "").strip()
                            if v and v not in allowed:
                                raise ValueError(f"corrected_{fld} must be one of {', '.join(allowed)}")
                            if v:
                                fields[fld] = v
                        if tg is None and not fields:
                            raise ValueError("decision 'change' needs at least one corrected_* value")
                        if tg is not None:
                            cx.execute("DELETE FROM claim_targets WHERE claim_id=?", (cid,))
                            cx.executemany("INSERT INTO claim_targets VALUES (?,?,?,?)", [(cid, *x) for x in tg])
                            corrected["targets"] = r["corrected_targets"]
                        for fld, v in fields.items():
                            cx.execute(f"UPDATE claims SET {fld}=? WHERE claim_id=?", (v, cid))
                            corrected[fld] = v
                        cx.execute("UPDATE claims SET status='changed', status_reason='reviewer corrected' WHERE claim_id=?", (cid,))
                cx.execute("INSERT INTO reviews(item_kind, item_id, field, proposed, decision, corrected, reviewer, note, decided_at) "
                           "VALUES (?,?,?,?,?,?,?,?,?)",
                           (r["item_kind"], r["item_id"], "all", json.dumps({"targets": r.get("targets"), "segment": r.get("segment"),
                                                                              "horizon": r.get("horizon")}),
                            d, json.dumps(corrected), who, r.get("note", ""), now()))
                stats["applied"] += 1
            except (ValueError, KeyError) as e:
                stats["errors"] += 1
                errors.append(f"row {i}: {e}")
    if errors:
        stats["error_messages"] = errors[:20]  # type: ignore[assignment]
    return stats


def export_gold(ws: Workspace, path: str | Path) -> int:
    """Reviewed claims with their passage, as JSON lines: the start of a gold set for testing prompts and models."""
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for r in ws.query("SELECT rv.*, c.claim, c.segment, c.horizon, c.passage_id, p.text AS passage FROM reviews rv "
                          "JOIN claims c ON c.claim_id=rv.item_id JOIN passages p ON p.passage_id=c.passage_id "
                          "WHERE rv.item_kind='claim' AND rv.field != 'superseded' ORDER BY rv.review_id"):
            rec = dict(r)
            rec["targets"] = _targets_str(ws, r["item_id"])
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n
