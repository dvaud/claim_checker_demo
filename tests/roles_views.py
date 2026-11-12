"""Views of GET …/owner that follow the roles contract (DESIGN-roles §7, P1's `view()` fields), for the page's tests
(`test_0_18_0_roles_ui.py`) and its screenshots, while P1's rules are built beside them. The people and documents are
those of the mock-ups (Anna the Owner, her laptop and Ben Co-owners, Carol, Eszter and Tomás Members)."""
from __future__ import annotations

import copy

ANNA, LAPTOP, BEN, CAROL, ESZTER, TOMAS = "panna", "plaptop", "pben", "pcarol", "peszter", "ptomas"
NAMES = {ANNA: "Anna de Vries", LAPTOP: "Anna de Vries (laptop)", BEN: "Ben Okafor", CAROL: "Carol Smit",
         ESZTER: "Eszter Kovács", TOMAS: "Tomás Ruiz"}
ROLES = {ANNA: "owner", LAPTOP: "co", BEN: "co", CAROL: "member", ESZTER: "member", TOMAS: "member"}


def person(pid: str, me: str) -> dict:
    return {"id": pid, "name": NAMES[pid], "me": pid == me}


def _people(me: str, old_ben: bool = False) -> list[dict]:
    out = []
    for pid in (ANNA, LAPTOP, BEN, CAROL, ESZTER, TOMAS):
        out.append({**person(pid, me), "owner": pid == ANNA, "role": ROLES[pid],
                    "same_as": ANNA if pid == LAPTOP else None, "needs_update": old_ben and pid == BEN})
    return out


def _proposal(me: str, pid: str, kind: str, title: str, what: str, by: str, at: str, *, can_decide: bool,
              clash: dict | None = None, severity: str | None = None, reason: str | None = None) -> dict:
    return {"id": pid, "kind": kind, "severity": severity or {"add": "low", "remove": "high", "loosen": "high"}[kind],
            "doc": "d-" + pid, "title": title, "what": what, "by": person(by, me), "at": at, "state": "waiting",
            "note": None, "reason": reason, "decided_by": None, "decided_at": None, "auto": False, "mine": by == me,
            "can_decide": can_decide, "can_take_back": by == me, "here": True, "conflicts": [], "detail": {},
            "clash": clash}


def owner_view(busy: bool = False, empty: bool = False) -> dict:
    """Anna's copy (the Owner): a proposal answered both ways, a take-over, a refused change, Ben's two looser AI
    settings, (busy:) two proposals; four things settled at the same time; three removals."""
    me = ANNA
    v = {"owner": person(ANNA, me), "me": me, "is_owner": True, "since": "2026-11-01T09:00:00Z", "how": "made",
         "can_claim": False, "can_take_over": None, "accept_adds": True, "people": _people(me, old_ben=busy),
         "proposals": [], "waiting": 0, "to_apply": [], "documents": {}, "job": None,
         "role": "owner", "can_write": True, "can_set_roles": True, "questions": [], "offers": [], "removed": [],
         "clashes": [], "refused": [], "notices": []}
    if empty:
        return v
    clash = {"accepted": [person(BEN, me)], "declined": [person(LAPTOP, me)]}
    v["proposals"] = [_proposal(me, "qjobs", "remove", "Jobs in the coal regions", "removing “Jobs in the coal regions” from the project",
                                CAROL, "2026-11-11T09:00:00Z", can_decide=True, clash=clash, reason="It is a blog post, not a source.")]
    if busy:
        v["proposals"] += [
            _proposal(me, "qmayor", "add", "Interview with a mayor", "adding “Interview with a mayor”", TOMAS,
                      "2026-11-12T09:31:00Z", can_decide=True, reason="The second interview of Lusatia."),
            _proposal(me, "qplant", "loosen", "Interview with a plant manager", "letting Claude read “Interview with a plant manager”",
                      ESZTER, "2026-11-09T12:00:00Z", can_decide=True)]
        v["proposals"][-1]["detail"] = {"from": "local", "to": "cloud"}
    v["questions"] = [{"id": "qtake", "seq": 2, "kind": "takeover", "owner": person(BEN, me), "by": person(BEN, me),
                       "why": "Nothing was heard of the owner for 14 days.", "now": person(ANNA, me), "at": "2026-11-12T07:55:00Z"}]
    v["refused"] = [{"kind": "canon", "key": "dminutes", "via": person(ESZTER, me), "title": "Works council minutes, May",
                     "at": "2026-11-10T15:00:00Z"}]
    v["offers"] = [{"doc": "dplant", "title": "Interview with a plant manager", "from": "local", "to": "cloud", "by": person(BEN, me)},
                   {"doc": "dgrid", "title": "Grid operator annual report 2024", "from": "none", "to": "local", "by": person(BEN, me)}]
    v["clashes"] = [
        {"id": "c-ai", "kind": "part", "doc": "dminutes", "title": "Works council minutes, May", "part": "ai",
         "events": [[7, ANNA, "none"], [4, BEN, "cloud"]], "counts": [7, ANNA], "people": [person(ANNA, me), person(BEN, me)]},
        {"id": "c-state", "kind": "part", "doc": "dstats", "title": "Regional employment statistics 2023", "part": "state",
         "events": [[5, BEN, "removed"], [3, LAPTOP, "in"]], "counts": [3, LAPTOP], "people": [person(BEN, me), person(LAPTOP, me)]},
        {"id": "c-read", "kind": "part", "doc": "dgrid", "title": "Grid operator annual report 2024", "part": "read",
         "events": [[8, ANNA, 3], [6, BEN, 2]], "counts": [8, ANNA], "people": [person(ANNA, me), person(BEN, me)]},
        {"id": "c-blocks", "kind": "part", "doc": "dunion", "title": "Interview with a union representative", "part": "blocks",
         "events": [[9, ANNA, None], [9, BEN, None]], "counts": [9, BEN], "people": [person(ANNA, me), person(BEN, me)]},
        {"id": "c-ans", "kind": "answer", "doc": "d-qjobs", "title": "Jobs in the coal regions", "proposal": "qjobs",
         "accepted": [BEN], "declined": [LAPTOP]}]
    v["removed"] = [
        {"doc": "dcoal", "title": "Coal phase-out timeline (draft)", "at": "2026-11-12T10:00:00Z", "by": person(ANNA, me),
         "why": "A newer version is in the project.", "cause": "removed", "until": "2026-12-12T10:00:00Z"},
        {"doc": "dfield", "title": "Field notes, Lusatia visit 2", "at": "2026-11-09T10:00:00Z", "by": person(BEN, me),
         "why": "The same notes as visit 1.", "cause": "removed", "until": "2026-12-09T10:00:00Z"},
        {"doc": "dpress", "title": "Press release, 3 October", "at": "2026-10-20T10:00:00Z", "by": person(BEN, me),
         "why": "Not a source.", "cause": "removed", "until": "2026-11-19T10:00:00Z"}]
    v["waiting"] = 4 + (2 if busy else 0)
    return v


def member_view() -> dict:
    """Carol's copy (a Member): Anna's looser setting for one document, her own proposal answered both ways, a role
    notice, three removals."""
    me = CAROL
    v = owner_view()
    for key in ("questions", "refused", "clashes"):
        v[key] = []
    v.update(me=me, is_owner=False, owner=person(ANNA, me), role="member", can_write=False, can_set_roles=False,
             people=_people(me), accept_adds=False,
             offers=[{"doc": "dplant", "title": "Interview with a plant manager", "from": "local", "to": "cloud", "by": person(ANNA, me)}],
             notices=[{"kind": "role", "text": "Anna made Ben a Co-owner."}])
    v["proposals"] = [_proposal(me, "qjobs", "remove", "Jobs in the coal regions", "removing “Jobs in the coal regions” from the project",
                                CAROL, "2026-11-11T09:00:00Z", can_decide=False,
                                clash={"accepted": [person(BEN, me)], "declined": [person(LAPTOP, me)]},
                                reason="It is a blog post, not a source.")]
    for r in v["removed"]:
        r["by"] = person(r["by"]["id"], me)
    v["waiting"] = 1
    return v


def views() -> dict[str, dict]:
    return {"owner": owner_view(), "busy": owner_view(busy=True), "empty": owner_view(empty=True), "member": member_view()}


def copy_of(name: str) -> dict:
    return copy.deepcopy(views()[name])
