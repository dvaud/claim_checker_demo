"""Time shared-folder rounds on a large project (S5/S14 of the deep dive after 0.17.0).

    python tools/bench_folder_rounds.py build <dir> [--docs 1000] [--checks 100] [--rows 200000]
    python tools/bench_folder_rounds.py time <dir>

`build` makes a synthetic project in <dir>/template: <docs> documents of about a hundred passages each (written as
text files and added the usual way), <checks> shared checks of three parts with thirty excerpts, tasks and answers
each, and about <rows> rows that are the project's (labels with the bundled SDG codebook, the ledger of what was sent
to Claude, reference chains), then one round into a shared folder (the snapshot). `time` copies the template and times,
in plain wall-clock and CPU seconds: idle rounds, a round after one small change (a judgement of one excerpt; one
label with the bundled codebook, among the project's rows), and an idle round after each. Nothing here loads a model.
"""
from __future__ import annotations

import os
import random
import shutil
import sys
import time
from pathlib import Path

WORDS = ("hydrogen electrolyser grid storage solar wind policy subsidy jobs region market price carbon emission "
         "industry steel ammonia transport pipeline water desalination capacity investment cost demand supply export "
         "import local community training skills research innovation risk safety standard certificate auction tender "
         "network port island village farm biomass battery efficiency output plant").split()


def _text(rng: random.Random, paragraphs: int) -> str:
    return "\n\n".join(" ".join(rng.choice(WORDS) for _ in range(rng.randint(60, 110))).capitalize() + "."
                       for _ in range(paragraphs))


def build(root: Path, docs: int, checks: int, rows: int) -> None:
    rng = random.Random(7)
    tpl = root / "template"
    if tpl.exists():
        shutil.rmtree(tpl)
    (tpl / "txt").mkdir(parents=True)
    (tpl / "team").mkdir()
    os.environ["ENLENS_HOME"] = str(tpl / "home")
    os.environ["ENLENS_CLAUDE"] = "/nonexistent"
    for i in range(docs):
        (tpl / "txt" / f"doc{i:05d}.txt").write_text(_text(rng, 100), encoding="utf-8")
    from enlens_claims import home, ingest, sharing
    from enlens_claims.sync import folder

    home.update_settings({"your_name": "Anna"})
    t = time.perf_counter()
    ws = home.create_project("Big")
    ingest.ingest(ws, [tpl / "txt"])
    print(f"added {docs} documents in {time.perf_counter() - t:.0f} s", flush=True)
    with ws.connect() as cx:
        pids = [r[0] for r in cx.execute("SELECT passage_id FROM passages ORDER BY passage_id")]
        doc_of = {p: p.split(":", 1)[0] for p in pids}
        at = "2026-11-12T10:00:00+00:00"
        for h in range(checks):
            hid = f"h{h:04d}"
            cx.execute("INSERT INTO hypotheses(hyp_id, text, framework, created_at, decomposed) VALUES (?,?,?,?,1)",
                       (hid, f"Hypothesis {h}: " + " ".join(rng.sample(WORDS, 8)), "", at))
            cx.execute("INSERT INTO tasks(task_id, kind, status, payload_json, created_at) VALUES (?,?,?,?,?)",
                       (f"decompose:{hid}", "decompose", "done", "{}", at))
            for c in range(3):
                cid = f"c{h:04d}{c}"
                cx.execute("INSERT INTO user_claims(claim_id, text, hyp_id, part, created_at) VALUES (?,?,?,?,?)",
                           (cid, " ".join(rng.sample(WORDS, 6)), hid, c, at))
                for p in rng.sample(pids, 30):
                    tid = f"check:{cid}:{p}"
                    cx.execute("INSERT INTO verifications(ver_id, subject_kind, subject_id, passage_id, doc_id, verdict, "
                               "confidence, quote, model) VALUES (?,?,?,?,?,?,?,?,?)",
                               (f"v{cid}{p}", "user_claim", cid, p, doc_of[p], rng.choice(["supports", "neutral"]),
                                0.8, " ".join(rng.sample(WORDS, 5)), "claude"))
                    cx.execute("INSERT INTO tasks(task_id, kind, status, payload_json, created_at) VALUES (?,?,?,?,?)",
                               (tid, "check", "done", '{"passage_id": "%s"}' % p, at))
                    cx.execute("INSERT INTO results(task_id, attempt, kind, raw_json, valid, received_at) VALUES "
                               "(?,?,?,?,?,?)", (tid, 1, "check", '{"verdict": "supports"}', 1, at))
        # the project's rows: labels with the bundled codebook, the ledger, reference chains
        n_labels, n_sent = rows // 2, rows // 4
        cx.executemany("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, relevance, source, quote, "
                       "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       [(f"l{i:07d}", p, doc_of[p], "sdg", f"{rng.randint(1, 17)}.{rng.randint(1, 9)}", "high",
                         "model", " ".join(rng.sample(WORDS, 4)), at) for i, p in
                        enumerate(rng.choice(pids) for _ in range(n_labels))])
        cx.executemany("INSERT INTO ai_sent(passage_id, doc_id, route, task_id, sent_at, feature) VALUES "
                       "(?,?,?,?,?,?)", [(p, doc_of[p], "claude-code", None, f"{at}{i}", "label") for i, p in
                                         enumerate(rng.choice(pids) for _ in range(n_sent))])
        cx.executemany("INSERT INTO mentions(doc_id, chain_id, start, end, text, is_named, source, passage_id, window) "
                       "VALUES (?,?,?,?,?,?,?,?,?)",
                       [(doc_of[p], i % 50, i, i + 5, "the plant", 0, "model", p, f"resolve:{p}#{i}") for i, p in
                        enumerate(rng.choice(pids) for _ in range(rows - n_labels - n_sent))])
    sharing.share(ws, [{"kind": "check", "key": f"h{h:04d}"} for h in range(checks)])
    folder.set_folder(ws, str(tpl / "team"))
    t = time.perf_counter()
    out = folder.sync_now(ws)
    print(f"first round (the snapshot) in {time.perf_counter() - t:.0f} s: bundle {out['wrote'].get('seq')}, "
          f"{out['wrote'].get('rows')} rows", flush=True)
    ws.close()


def _timed(label: str, fn) -> dict:
    w, c = time.perf_counter(), time.process_time()
    out = fn()
    w, c = time.perf_counter() - w, time.process_time() - c
    print(f"{label:<34} wall {w:6.2f} s   cpu {c:6.2f} s   bundle {out['wrote'].get('seq')}", flush=True)
    return out


def run(root: Path) -> None:
    tpl, work = root / "template", root / "work"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(tpl, work, symlinks=True)
    os.environ["ENLENS_HOME"] = str(work / "home")
    os.environ["ENLENS_CLAUDE"] = "/nonexistent"
    from enlens_claims import home, people
    from enlens_claims.sync import folder

    ws = home.open_project("Big")
    folder.set_folder(ws, str(work / "team"))
    _timed("idle round", lambda: folder.sync_now(ws))
    _timed("idle round again", lambda: folder.sync_now(ws))
    me = people.me()
    with ws.connect() as cx:
        cid, pid = cx.execute("SELECT subject_id, passage_id FROM verifications WHERE subject_kind='user_claim' "
                              "LIMIT 1").fetchone()
        cx.execute("INSERT INTO judgements(claim_id, passage_id, person_id, verdict, at) VALUES (?,?,?,?,?)",
                   (cid, pid, me, "supports", "2026-11-12T11:00:00+00:00"))
    _timed("round after one judgement", lambda: folder.sync_now(ws))
    _timed("idle round after it", lambda: folder.sync_now(ws))
    with ws.connect() as cx:
        pid, doc = cx.execute("SELECT passage_id, doc_id FROM passages LIMIT 1").fetchone()
        cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, relevance, source, created_at) "
                   "VALUES ('lnew', ?, ?, 'sdg', '6.4', 'high', 'person', '2026-11-12T11:00:00+00:00')", (pid, doc))
    _timed("round after one SDG label", lambda: folder.sync_now(ws))
    _timed("idle round after it", lambda: folder.sync_now(ws))
    ws.close()


if __name__ == "__main__":
    cmd, where = sys.argv[1], Path(sys.argv[2])
    if cmd == "build":
        args = dict(zip(sys.argv[3::2], sys.argv[4::2]))
        build(where, int(args.get("--docs", 1000)), int(args.get("--checks", 100)), int(args.get("--rows", 200000)))
    else:
        run(where)
