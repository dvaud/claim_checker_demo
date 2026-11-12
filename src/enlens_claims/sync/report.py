"""What a merge did, in words, and what the Projects page shows of the work brought in (0.18: split out of sync.py)."""
from __future__ import annotations

import json

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
    out = []
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
    if r["bibliography"] == "kept_yours":
        out.append(f"{who}'s bibliography comes from another Zotero collection or file: yours was kept.")
    if r["labels_kept_yours"]:
        out.append(f"Where you both had the AI label a document, your labels were kept "
                   f"({_n(r['labels_kept_yours'], 'document and codebook', 'documents and codebooks')}).")
    if not out:
        out.append(f"Nothing new: this copy already has everything in {who}'s file.")
    return out


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
