"""What a merge did, in words, and what the Projects page shows of the work brought in (0.18: split out of sync.py)."""
from __future__ import annotations

import json
import sqlite3

from .. import people
from ..store import Workspace

def _n(k: int, one: str, many: str | None = None) -> str:
    return f"{k} {one if k == 1 else (many or one + 's')}"


def _title(t: str | None, n: int = 80) -> str:
    """A document's title in a sentence: in quotes, cut short with "…"; its own straight double quotes become single
    ones, so a title that starts with a quotation does not read ""You never …" (the Team tab, 0.18)."""
    from ..researchlog import quoted

    parts = (t or "a document").split('"')
    s = "".join(p + ("‘" if i % 2 == 0 else "’") for i, p in enumerate(parts[:-1])) + parts[-1]
    return quoted(s, n)


def summary(r: dict) -> list[str]:
    """The report as a few plain sentences, most important first."""
    who = r["from"]["name"] or "your colleague"
    d, c, t, cb = r["documents"], r["checks"], r["themes"], r["codebooks"]
    out = counting_lines(r)  # K3 (DEC-1): what changed what counts in an answer, first
    came = [x for x in (_n(len(d["new"]), "new document") if d["new"] else "",
                        _n(c["new"], "new result") if c["new"] else "",
                        _n(c["updated"], "result", "results") + " brought up to date" if c["updated"] else "",
                        _n(t["new"], "new theme run") if t["new"] else "",
                        _n(len(cb["new"]), "codebook") if cb["new"] else "") if x]
    if came:
        out.append(f"From {who}: " + ", ".join(came) + ".")
    if r["judgements"]:
        out.append(f"{_n(r['judgements'], 'judgement')} of excerpts came in, each under the name of who made it. "
                   "Yours still count where you judged an excerpt yourself.")
    extra = [x for x in (_n(r.get("log") or 0, "research log entry", "research log entries") if r.get("log") else "",
                         _n(r.get("notes") or 0, "note") if r.get("notes") else "") if x]
    if extra:  # 0.16
        one = (r.get("log") or 0) + (r.get("notes") or 0) == 1
        out.append(f"{' and '.join(extra)} of {who}'s came in or {'was' if one else 'were'} brought up to date, under "
                   "their name.")
    both = [x for x in (_n(len(c["clash"]), "result") if c["clash"] else "",
                        _n(len(t["clash"]), "set of themes", "sets of themes") if t["clash"] else "",
                        _n(len(cb["clash"]), "codebook") if cb["clash"] else "") if x]
    for m in cb.get("merged") or []:  # 0.18: a codebook both changed, merged code by code
        parts = [x for x in (_n(len(m["theirs"]), "code") + " brought up to date" if m["theirs"] else "",
                             _n(len(m["added"]), "new code") if m["added"] else "",
                             _n(len(m["removed"]), "code") + " removed as in their copy" if m["removed"] else "") if x]
        line = f"The codebook “{m['name']}”, which you both changed, was merged code by code"
        line += (": " + ", ".join(parts) + "." if parts else ".")
        if m["clash"]:
            line += (f" {_n(len(m['clash']), 'code')} you both changed ({', '.join(m['clash'][:3])}"
                     f"{' and more' if len(m['clash']) > 3 else ''}) kept your version, with {who}'s beside it in the "
                     "codebook editor.")
        if m["kept_removed"]:
            line += f" {_n(len(m['kept_removed']), 'code')} you removed stayed removed; {who}'s later version is kept."
        out.append(line)
    if both:
        out.append(f"Sync clash: {' and '.join(both)} you both changed. {who}'s version came in beside yours, marked "
                   "“sync clash”: nothing was replaced.")
    for x in d.get("other_reading") or []:  # 0.18 (readings.py)
        if x.get("failed"):
            continue  # it came in as a document of its own (the line below says so)
        kept = (f" {_n(x['not_placed'], 'result')} found no place in your reading and {'is' if x['not_placed'] == 1 else 'are'} "
                "kept as records." if x["not_placed"] else "")
        out.append(f"“{x['title']}”: {who} has it in another reading (read by another reader). Their results were "
                   f"placed on your reading of it, so it stays one document.{kept}")
    pr = r.get("proposals") or {}  # 0.18 L2 (ownership.py)
    if pr.get("owner"):
        out.append("The project's owner changed: see the Team tab.")
    if pr.get("new"):
        names = ", ".join(_title(x.get("title"), 60) for x in pr["new"][:3]) + \
            (" and more" if len(pr["new"]) > 3 else "")
        out.append(f"{_n(len(pr['new']), 'proposal')} to the owner came in, about {names}: see “Waiting for the "
                   "owner” in the Team tab.")
    if pr.get("decided"):
        out.append(f"The owner's answer to {_n(pr['decided'], 'proposal')} came in.")
    not_here = d.get("not_here") or []  # 0.18 (the shared folder)
    if not_here:
        names = ", ".join(f"“{x['title']}”" for x in not_here[:3]) + (" and more" if len(not_here) > 3 else "")
        out.append(f"{_n(len(not_here), 'document')} of {who}'s {'is' if len(not_here) == 1 else 'are'} not in the "
                   f"shared folder ({names}): {who} keeps documents that only a local AI or no AI may read out of it. "
                   "Add the file yourself to see what was found in it in place; until then excerpts from it are kept "
                   "as records.")
    for x in d["clash"]:
        out.append(f"“{x['title']}” is a file you both added, but the two computers read it into different text. "
                   f"{who}'s reading came in as a document of its own, marked “sync clash”, with what was made from it.")
    for a in r["ai_access"]:
        if a["why"] == "theirs":
            out.append(f"“{a['title']}” is now kept from Claude ({_label(a['now'])}), as in {who}'s copy."
                       + (f" Claude had read {_n(a['claude_read_here'], 'excerpt')} of it here before." if a.get("claude_read_here") else ""))
        elif a["why"] == "yours" and a.get("claude_read_there"):
            out.append(f"{who}'s copy let Claude read “{a['title']}” ({_n(a['claude_read_there'], 'excerpt')}); in yours it "
                       f"stays {_label(a['now']).lower()}. What Claude made of it there came in with the rest.")
        elif a["why"] == "yours":
            out.append(f"“{a['title']}” came in as {_label(a['now']).lower()}, as you keep that file.")
        else:
            out.append(f"“{a['title']}” came in as {_label(a['now']).lower()}, the setting for new documents here.")
    if c["running"]:
        out.append(f"{_n(len(c['running']), 'check')} still running in {who}'s copy did not come in yet: bring in a later "
                   "file when it is done.")
    running_here = [x for x in (_n(len(c.get("running_here") or []), "result"),
                                _n(len(t.get("running_here") or []), "set of themes", "sets of themes"))
                    if not x.startswith("0 ")]
    if running_here:
        out.append(f"Still running in your copy, so kept as it is for now: {' and '.join(running_here)} that {who} "
                   f"changed too. When the run is done, bring in {who}'s file again: {who}'s version then comes in "
                   "beside yours.")
    nw = d.get("not_wanted") or []  # 0.18 L2 (ownership.not_wanted)
    if nw:
        names = ", ".join(f"“{x}”" for x in nw[:3]) + (" and more" if len(nw) > 3 else "")
        out.append(f"{_n(len(nw), 'document')} of {who}'s did not come in ({names}): the owner removed "
                   f"{'it' if len(nw) == 1 else 'them'} from the project or did not accept {'it' if len(nw) == 1 else 'them'}.")
    if d["removed_here"] or c["removed_here"]:
        out.append(f"{_n(len(d['removed_here']) + len(c['removed_here']), 'thing')} you removed earlier did not come back.")
    # 0.18 L2: in a project with an owner, a colleague's removal is said as what it is (`removals` of owner_merge.py)
    rm = d.get("removals") or {}
    said = {t for ts in rm.values() for t in ts}
    there = [x for x in d["removed_there"] if x not in said]
    if there or c["removed_there"]:
        names = ", ".join(f"“{x}”" for x in (there + c["removed_there"])[:3])
        out.append(f"{who} removed {names}{' and more' if len(there) + len(c['removed_there']) > 3 else ''} "
                   "from their copy. It stays in yours: remove it here too if you agree.")

    def _names(ts: list[str]) -> str:
        return ", ".join(_title(x) for x in ts[:3]) + (" and more" if len(ts) > 3 else "")

    if rm.get("proposed"):
        ts = rm["proposed"]
        out.append(f"{who} proposes removing {_names(ts)} from the project: "
                   f"{'it waits' if len(ts) == 1 else 'they wait'} for the owner. Until then {'it stays' if len(ts) == 1 else 'they stay'} in your copy.")
    if rm.get("owner"):
        ts = rm["owner"]
        out.append(f"The owner removed {_names(ts)} from the project: {'it leaves' if len(ts) == 1 else 'they leave'} "
                   "your copy too (checks keep what they read of it).")
    if rm.get("declined"):
        out.append(f"{_names(rm['declined'])} {'stays' if len(rm['declined']) == 1 else 'stay'} in your copy only: the "
                   "owner did not accept your proposal to add it.")
    if rm.get("taken_back"):
        out.append(f"{_names(rm['taken_back'])} {'stays' if len(rm['taken_back']) == 1 else 'stay'} in your copy only: "
                   "you took your proposal to add it back.")
    sh = r.get("shares") or {}  # 0.18 (sharing.py)
    if sh.get("withdrawn"):
        names = ", ".join(f"“{x}”" for x in sh["withdrawn"][:3]) + (" and more" if len(sh["withdrawn"]) > 3 else "")
        out.append(f"No longer shared by its owner: {names}. It stays in your copy, marked as withdrawn, and is not "
                   "passed on.")
    if sh.get("withheld"):
        out.append(f"{_n(len(sh['withheld']), 'item')} in {who}'s file had been taken back by the person who shared "
                   "it, so it did not come in.")
    # roles (DESIGN-roles §4.8, §4.9): rows of a third person, and a codebook's changes that wait
    if r.get("via"):
        out.append(f"{_n(r['via'], 'row')} of other people came in through {who}'s file, not from their own: each is "
                   f"shown under its author's name, via {who}, until their own file brings it.")
    if r.get("held_back"):
        out.append(f"{_n(r['held_back'], 'removal')} of other people's notes, log entries or reviews came through "
                   f"{who}'s file, not from their own, and {'was' if r['held_back'] == 1 else 'were'} held back: "
                   "nothing was removed.")
    if cb.get("skipped_events"):
        out.append(f"{_n(cb['skipped_events'], 'rename or merge', 'renames or merges')} of codes in {who}'s file did "
                   "not fit the codebook's list of changes and moved no label.")
    for name in cb.get("offered") or []:
        out.append(f"{who} renamed or merged codes of the codebook “{name}”. Your labels keep their codes until you "
                   "choose Follow or Keep mine on the codebook's page.")
    if r["bibliography"] == "kept_yours":
        out.append(f"{who}'s bibliography comes from another Zotero collection or file: yours was kept.")
    if r["labels_kept_yours"]:
        out.append(f"Where you both had the AI label a document, your labels were kept "
                   f"({_n(r['labels_kept_yours'], 'document and codebook', 'documents and codebooks')}).")
    if not out:
        out.append(f"Nothing new: this copy already has everything in {who}'s file.")
    return out


# ---- K3 (the audit's DEC-1): a colleague's change of what counts in an answer ---------------------------------------
# Worked out in the receiving copy, from what the merge changed: a check whose version from the colleague counts the
# non-scientific documents where the one it replaces here did not (or the other way round), and a document whose
# Non-scientific mark the project's word sets or takes away here (`ownership.settle`, after the merge). Nothing of it is
# stored but the report's own lines; a change this copy has already adds none.
def counting_lines(r: dict) -> list[str]:
    """The lines of the report about what counts in an answer: one per check whose exception a colleague changed
    (`checks.counting`), one per document whose mark came in applied (`documents.marks`)."""
    who = r["from"]["name"] or "your colleague"
    out = []
    for x in (r.get("checks") or {}).get("counting") or []:
        by = x.get("by") or who
        check = _title(x["text"])
        line = (f"{by} set the check {check} to count the non-scientific documents"
                + (f" (the reason given: {_title(x['why'], 120)})" if x.get("why") else "")
                if x["on"] else f"{by} set the check {check} to no longer count the non-scientific documents")
        if x.get("beside"):
            line += (f". You both changed the check, so {by}'s version came in beside yours, marked “sync clash”, and "
                     "yours stays as it was")
            its = "That version's answer here"
        else:
            its = "Its answer here"
        if x["now_text"] == x["other_text"]:
            line += f". This does not change the answer here: {x['now_text']} either way."
        else:
            line += (f". {its} is now {x['now_text']}; " + ("without them" if x["on"] else "counting them")
                     + f" it would be {x['other_text']}.")
        out.append(line)
    for m in (r.get("documents") or {}).get("marks") or []:
        by = m.get("by") or "The owner"
        line = (f"{by} marked {_title(m['title'])} as non-scientific: no judgement of it counts in an answer here "
                "now, except in checks set to count them." if m["on"] else
                f"{by} counted {_title(m['title'])} as scientific again: its judgements count in answers here now.")
        ch = m.get("changed") or []
        if not ch:
            line += " It changes no answer here."
        elif len(ch) <= 3:
            parts = [f"{_title(a['text'], 60)} (now {a['now_text']})" for a in ch]
            line += (f" It changed the answer of {_n(len(ch), 'check')} here: "
                     + (parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]) + ".")
        else:
            line += f" It changed the answers of {_n(len(ch), 'check')} here."
        out.append(line)
    return out


def counting_change(was: dict | None, unit: dict) -> dict | None:
    """{"on", "why", "at", "text"} when a check's incoming version (`unit`, as fingerprints.py reads it) counts the
    non-scientific documents and the version it replaces here (`was`) does not, or the other way round; None when both
    count them alike (a new reason alone changes no answer)."""
    from ..nonscientific import COUNT_AT, _options, setting

    def opts(u: dict | None) -> dict:
        h = (u or {}).get("hypotheses") or [{}]
        return _options(h[0].get("options_json"))

    new, old = opts(unit), opts(was)
    on, why = setting(new)
    if on == setting(old)[0]:
        return None
    text = (unit.get("hypotheses") or [{}])[0].get("text") or ""
    return {"on": on, "why": why, "at": new.get(COUNT_AT), "text": text}


def counting_said(ws: Workspace, changes: list[dict], sender: dict) -> list[dict]:
    """The checks of `changes` (`counting_change`, with "hyp_id" here and "beside") with who changed them and their
    answers here now and the other way: [{"hyp_id", "text", "on", "why", "by", "beside", "now", "now_text", "other",
    "other_text"}]. Who: the person of the research log's entry of that change (it carries the setting's time), else the
    sender. A change of this person's own coming back says nothing."""
    from ..nonscientific import answers_either_way

    names, me = people.names(ws), people.me()
    here = {r[0] for r in ws.query("SELECT hyp_id FROM hypotheses")}
    out = []
    for x in changes:
        if x["hyp_id"] not in here:
            continue
        pid = None
        if x.get("at"):
            rows = ws.query("SELECT person_id FROM research_log WHERE kind='check-setting' AND at=? LIMIT 1",
                            (x["at"],))
            pid = rows[0][0] if rows else None
        if pid == me or (pid is None and sender.get("id") == me):
            continue
        by = names.get(pid) if pid else None
        out.append({"hyp_id": x["hyp_id"], "text": x["text"], "on": x["on"], "why": x["why"],
                    "by": by or sender.get("name") or None,
                    "beside": x["beside"] if x.get("beside") in here else None,
                    **{k: v for k, v in answers_either_way(ws, x["hyp_id"]).items() if k != "counts"}})
    return out


def canon_blocks(cx: sqlite3.Connection) -> dict[tuple[str, str], str | None]:
    """{(doc, writer): blocks_json} of the project's word on the documents (ownership.py's `canon`), to compare after a
    merge."""
    try:
        return {(r[0], r[1]): r[2] for r in cx.execute("SELECT doc, by, blocks_json FROM canon")}
    except sqlite3.OperationalError:
        return {}


def marks_due(cx: sqlite3.Connection, before: dict, new_docs: set[str]) -> list[dict]:
    """The documents held here before the merge whose Non-scientific mark the project's word, as the merge changed it,
    gives otherwise than this copy has it now: [{"doc_id", "on", "by"}]. `ownership.settle` applies it after the merge
    (or not, when this person's own choice stays on top: `tell_marks` then says nothing)."""
    from ..docrole import nonscientific_from_choices

    try:
        rows = cx.execute("SELECT c.doc, c.by, c.blocks_json, c.blocks_by, d.nonscientific FROM canon c "
                          "JOIN documents d ON d.doc_id=c.doc").fetchall()
    except sqlite3.OperationalError:
        return []
    due: dict[str, dict] = {}
    for doc, by, blocks, blocks_by, marked in rows:
        if doc in new_docs or before.get((doc, by), "") == blocks or blocks is None:
            continue
        try:
            choices = json.loads(blocks)
        except ValueError:
            continue
        on = isinstance(choices, dict) and nonscientific_from_choices(choices)
        if on != bool(marked):
            due[doc] = {"doc_id": doc, "on": on, "by": blocks_by or by}
    return list(due.values())


def marks_before(ws: Workspace, report: dict | None) -> dict | None:
    """Before `ownership.settle` applies the marks a merge brought (`documents.marks_due`): the answers of the checks
    that read those documents, as they are now. None when there are none (nothing more to do)."""
    from ..docrole import _answers, _checks_reading, is_nonscientific

    due = ((report or {}).get("documents") or {}).get("marks_due")
    if not due:
        return None
    checks = {m["doc_id"]: _checks_reading(ws, m["doc_id"]) for m in due}
    return {"checks": checks, "marked": {d: is_nonscientific(ws, d) for d in checks},
            "answers": _answers(ws, sorted({h for hs in checks.values() for h in hs}))}


def tell_marks(ws: Workspace, report: dict, before: dict | None, told: set[str] | None = None) -> None:
    """After `ownership.settle`: the marks it applied of those the merge brought (`marks_before`) go into the report,
    with the answers each changed here, and the report kept in `sync_log` (`log_id`) is brought up to date. `told`:
    the documents a report of the same round said already (two colleagues' work can bring the same word); those said
    here are added to it."""
    from ..docrole import _answers, _text, is_nonscientific

    if before is None:
        return
    told = set() if told is None else told
    d = report["documents"]
    due = d.pop("marks_due", None) or []
    names, me = people.names(ws), people.me()
    after = _answers(ws, list(before["answers"]))
    marks = []
    for m in due:
        doc = m["doc_id"]
        now = is_nonscientific(ws, doc)
        if now == before["marked"].get(doc) or now != m["on"] or m.get("by") == me or doc in told:
            continue
        told.add(doc)
        b, a = before["answers"], after
        changed = [{"hyp_id": h, "text": a[h]["text"], "now_text": _text(a[h])} for h in before["checks"].get(doc, [])
                   if h in b and h in a and (b[h]["status"], _text(b[h])) != (a[h]["status"], _text(a[h]))]
        title = ws.scalar("SELECT title FROM documents WHERE doc_id=?", (doc,))
        marks.append({"doc_id": doc, "title": title, "on": now, "by": names.get(m.get("by")) or None,
                      "changed": changed})
    if marks:
        d["marks"] = marks
    report["lines"] = summary(report)
    if report.get("log_id"):  # the row as it was kept, with these two parts brought up to date
        with ws.connect() as cx:
            row = cx.execute("SELECT report_json FROM sync_log WHERE log_id=?", (report["log_id"],)).fetchone()
            kept = json.loads(row[0]) if row else None
            if isinstance(kept, dict):
                kept["documents"], kept["lines"] = d, report["lines"]
                cx.execute("UPDATE sync_log SET report_json=? WHERE log_id=?",
                           (json.dumps(kept, ensure_ascii=False), report["log_id"]))


def _label(level: str) -> str:
    from ..access import LABEL

    return LABEL.get(level, level)


def history(ws: Workspace, limit: int = 10) -> list[dict]:
    """The colleagues' work brought in, newest first: [{"at", "from", "lines"}]."""
    out = []
    for r in ws.query("SELECT at, report_json FROM sync_log ORDER BY log_id DESC LIMIT ?", (limit,)):
        rep = json.loads(r["report_json"])
        out.append({"at": r["at"], "from": rep.get("from"), "lines": rep.get("lines") or summary(rep)})
    return out


def overview(ws: Workspace) -> dict:
    """For the Projects page: who works on this project, the latest work brought in, and the open sync clashes."""
    who = people.names(ws)
    copies = [{"kind": kind, "key": k, "of_key": v["of"], "name": v["name"], "at": v["at"]}
              for kind in ("check", "document", "themes", "codebook") for k, v in copies_of(ws, kind).items()]
    copies.sort(key=lambda c: c["at"] or "", reverse=True)
    return {"uid": ws.meta("project_uid"), "people": [{"id": k, "name": v} for k, v in who.items()
                                                     if v != "you" and k != people.UNKNOWN],
            "history": history(ws, 5), "clashes": copies, "agreement": people.agreement(ws)}


_ORIGINALS = {"check": "SELECT hyp_id FROM hypotheses", "themes": "SELECT run_id FROM theme_runs",
              "document": "SELECT doc_id FROM documents"}


def copies_of(ws: Workspace, kind: str, settled: bool = False) -> dict[str, dict]:
    """{key: {"of", "name", "at"}} of the sync-clash copies of one kind (check, themes, document, codebook) whose
    other version is still here. A copy whose other version you removed is settled: it is simply yours now (`settled`
    lists those too)."""
    who = people.names(ws)
    here = {r[0] for r in ws.query(_ORIGINALS[kind])} if kind in _ORIGINALS else None
    return {r["key"]: {"of": r["of_key"], "name": who.get(r["person_id"], "a colleague"), "at": r["at"]}
            for r in ws.query("SELECT key, of_key, person_id, at FROM sync_copies WHERE kind=?", (kind,))
            if settled or here is None or (r["of_key"] in here and r["key"] in here)}
