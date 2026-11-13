"""Roles: the independent review of the build (REVIEW-roles.md, 2026-11-12), its proofs kept as tests.

Each test says what the design promises; each failed on the reviewed build (branch `roles`, 4cf175a). C1 a record
held here is never replaced by a file's; C2 an event said to be this person's own is proven from this copy; H1 an
accept allows only the event it made; H2 numbers at the top of the range; H3 a removal note in this copy's own name;
M1 a former owner's late row; M2 a demotion decides no proposal answered both ways; L1 a document back from the
archive is as strict as the project; L2 a file never takes back this person's own judgement.
The reviewer's three files, as one; their first test (the scratch copy) is left out.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enlens_claims import claimcheck, ownership
from enlens_claims.sync import folder
from owner_helpers import accept, add_doc, decline, has, level, proposals, set_level, set_role, sync, view
from roles_helpers import doc_of, make_crew
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_privacy_and_sync import _claim, _excerpts
from test_owner import shared_dir, team  # noqa: F401  (fixtures)
from test_owner_more import NOTE


def _forge_canon(p: Person, doc: str, by: str, n: int = 10 ** 6, bump=(), ev_by: str | None = None, **change) -> None:
    """A row of the documents in `by`'s name (copied from the row that counts now), written with any SQLite tool."""
    with p:
        with p.ws.connect() as cx:
            cur = cx.execute("SELECT * FROM canon WHERE doc=? ORDER BY owner_seq DESC, n DESC LIMIT 1", (doc,))
            cols = [c[0] for c in cur.description]
            r = dict(zip(cols, cur.fetchone()))
            r.update(n=n, by=by, **change)
            for part in bump:
                r[f"{part}_n"] = n
                r[f"{part}_by"] = ev_by
            if "ai_access" in change:
                last = [n, change["ai_access"]] + ([ev_by] if ev_by else [])
                r["ai_hist_json"] = json.dumps(json.loads(r["ai_hist_json"] or "[]") + [last])
            cx.execute(f"INSERT OR REPLACE INTO canon({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       [r[c] for c in cols])


# ---- 1: the owner changes without a question ---------------------------------------------------------------------
def test_a_forged_first_record_in_the_owners_name_changes_the_owner_nowhere_unasked(team):
    anna, ben, carol = team
    assert view(ben)["owner"]["id"] == anna.id
    x = "p000000000001"                       # any id that sorts before Anna's (the attacker picks their own)
    assert x < anna.id
    with carol:
        with carol.ws.connect() as cx:        # the record that says Anna made the project, now naming X
            cx.execute("UPDATE ownership SET owner=? WHERE seq=1 AND by=?", (x, anna.id))
    sync(carol, ben, anna)
    v = view(ben)
    assert v["owner"]["id"] == anna.id, f"Ben now follows {v['owner']['id']} with questions {v['questions']}"


# ---- 2: an AI setting becomes looser without this person's click -------------------------------------------------
def test_an_event_said_to_be_this_persons_own_loosens_nothing_here(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="local")
    sync(anna, ben, carol)
    assert level(ben, doc) == "local"
    # as the H3 proof, but the AI event of the forged row names Ben as its maker
    _forge_canon(carol, doc, anna.id, bump=("ai",), ev_by=ben.id, ai_access="cloud")
    sync(carol, ben)
    assert level(ben, doc) == "local", "Ben's copy lets Claude read it, and Ben never clicked"


def test_an_old_accepted_proposal_does_not_allow_a_later_loosening(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="local")
    sync(anna, ben, carol)
    set_level(ben, doc, "cloud")                                   # Ben asks; held, proposed
    sync(ben, anna)
    (p,) = proposals(anna, state="waiting", kind="loosen")
    accept(anna, p["id"])
    sync(anna, ben, carol)
    assert level(ben, doc) == "cloud"
    set_level(anna, doc, "none")                                   # later the owner closes it: holds at once
    sync(anna, ben, carol)
    assert level(ben, doc) == level(carol, doc) == "none"
    _forge_canon(carol, doc, anna.id, bump=("ai",), ai_access="cloud")   # a file says the owner opened it again
    sync(carol, ben)
    assert level(ben, doc) == "none", "set without a click: Ben's proposal answered an earlier setting"
    assert [(o["doc"], o["to"]) for o in view(ben)["offers"]] == [(doc, "cloud")]


def test_a_forged_row_naming_an_old_accept_in_via_allows_nothing(team, tmp_path):
    """Follow-up to H1: `via` lives in a row's `hist_json`, which its writer controls. A forged row in the owner's name
    that names Ben's old accepted proposal as the accept that made its looser setting is only an offer: each accept
    sets a level without a click once, the first time this copy follows its own event."""
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="local")
    sync(anna, ben, carol)
    set_level(ben, doc, "cloud")                                   # Ben asks; held, proposed
    sync(ben, anna)
    (p,) = proposals(anna, state="waiting", kind="loosen")
    accept(anna, p["id"])
    sync(anna, ben, carol)
    assert level(ben, doc) == "cloud"
    set_level(anna, doc, "none")                                   # later the owner closes it: holds at once
    sync(anna, ben, carol)
    assert level(ben, doc) == level(carol, doc) == "none"
    with carol:                                                    # the accept's "via" entry, copied into a forged row
        cx = carol.ws._conn()
        dn = cx.execute("SELECT n FROM decisions WHERE proposal=? AND by=?", (p["id"], anna.id)).fetchone()[0]
        r = cx.execute("SELECT ai_n, ai_by, hist_json FROM canon WHERE doc=? AND by=?", (doc, anna.id)).fetchone()
        hist = json.loads(r[2] or "{}")
        hist.setdefault("via", {})["ai"] = {"p": p["id"], "d": [anna.id, dn], "was": "none", "was_n": r[0],
                                            "was_by": r[1]}
    _forge_canon(carol, doc, anna.id, bump=("ai",), ev_by=anna.id, ai_access="cloud", hist_json=json.dumps(hist))
    sync(carol, ben)
    assert level(ben, doc) == "none", "set without a click: the forged row named Ben's old accept"
    assert [(o["doc"], o["to"]) for o in view(ben)["offers"]] == [(doc, "cloud")]


# ---- 3: a number at the top of the range ------------------------------------------------------------------------
def test_a_members_row_with_the_highest_number_does_not_stop_the_project(team, tmp_path):
    anna, ben, carol = team
    with carol:                                 # a Member's own row (it counts for nothing), numbered 2**53
        with carol.ws.connect() as cx:
            cur = cx.execute("SELECT * FROM canon LIMIT 1")
            cols = [c[0] for c in cur.description]
            r = dict(zip(cols, cur.fetchone()))
            r.update(by=carol.id, n=2 ** 53)
            cx.execute(f"INSERT OR REPLACE INTO canon({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       [r[c] for c in cols])
    sync(carol, anna, ben)
    doc = add_doc(anna, tmp_path, "interview")  # the owner adds a document
    sync(anna, ben, carol)
    for p in (anna, ben):
        with p:
            k = ownership.canon(p.ws._conn()).get(doc)
        assert k is not None and k["state"] == "in", f"{p.name}: the owner's new document is not the project's"


# ---- 4: a note "you removed it" in this copy's own name --------------------------------------------------------
def test_a_removal_note_in_the_owners_name_removes_nothing_from_the_project(team, tmp_path):
    anna, ben, carol = team
    set_role(anna, ben, "co")
    sync(anna, ben, carol)
    doc = add_doc(ben, tmp_path, "interview")   # a Co-owner adds a document: the project's at once
    sync(ben, carol)                            # Carol has it; Anna has not been here since
    assert has(carol, doc)
    with carol:
        carol.ws.remove_document(doc, why="x")
        with carol.ws.connect() as cx:          # the note of the removal, in Anna's name
            cx.execute("UPDATE sync_removed SET person_id=? WHERE kind='document' AND key=?", (anna.id, doc))
        f = carol.send()
    anna.bring_in(f)
    sync(anna, ben, carol)
    with ben:
        k = ownership.canon(ben.ws._conn()).get(doc)
    assert k is not None and k["state"] == "in", f"the project removed it, by {k and k['state_by'] == anna.id and 'Anna'}"
    assert has(ben, doc)


# ---- second batch -------------------------------------------------------------------------------------------------
@pytest.fixture
def shared(tmp_path) -> Path:
    d = tmp_path / "Dávid" / "Közös mappa"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def crew(tmp_path, monkeypatch, shared):
    anna, ben, carol, dana = make_crew(tmp_path, monkeypatch, shared, co=("Ben",))
    with anna:
        ownership.set_accept_adds(anna.ws, False)
    sync(anna, ben, carol, dana)
    return anna, ben, carol, dana


# ---- 1b: the real owner loses the project in their own copy ----------------------------------------------------------
def test_a_forged_hand_over_record_does_not_take_the_project_from_the_owner_in_their_own_copy(team):
    anna, ben, carol = team
    with anna:
        ownership.hand_over(anna.ws, ben.id, "Ben leads it now")
    sync(anna, ben, carol)
    assert view(ben)["is_owner"] and view(carol)["owner"]["id"] == ben.id
    x = "p000000000001"
    assert x < ben.id
    with carol:
        with carol.ws.connect() as cx:        # Anna's hand-over to Ben, now naming X
            cx.execute("UPDATE ownership SET owner=? WHERE seq=2 AND by=?", (x, anna.id))
    sync(carol, ben, anna, rounds=3)
    v = view(ben)
    assert v["is_owner"], f"Ben's own copy follows {v['owner']['id']}; questions {v['questions']}; refused {v['refused']}"


# ---- a demotion decides a proposal answered both ways ------------------------------------------------------------
def test_a_demotion_does_not_decide_a_proposal_answered_both_ways(crew):
    anna, ben, carol, dana = crew
    doc = doc_of(carol, "Grid")
    with carol:
        carol.ws.remove_document(doc)
    sync(carol, anna, ben, dana)
    (p,) = [q for q in proposals(anna, state="waiting") if q["by"]["id"] == carol.id]
    accept(anna, p["id"])
    decline(ben, p["id"], "Not for this project")
    sync(anna, ben, carol, dana, rounds=2)
    q = next(x for x in view(dana)["proposals"] if x["id"] == p["id"])
    assert q["state"] == "waiting" and q["note"] == "answered both ways"
    assert has(anna, doc) and has(dana, doc)
    set_role(anna, ben, "member")             # nothing is said about the proposal
    sync(anna, ben, carol, dana, rounds=2)
    q = next(x for x in view(dana)["proposals"] if x["id"] == p["id"])
    assert has(dana, doc) and has(anna, doc), f"the document left: the proposal is now {q['state']}"


# ---- a stricter setting made while the document was away ---------------------------------------------------------
def test_a_document_that_comes_back_from_the_archive_is_as_strict_as_the_project(crew):
    anna, ben, carol, dana = crew
    doc = doc_of(anna, "Grid")
    assert level(dana, doc) == "cloud"
    with anna:
        anna.ws.remove_document(doc)          # the owner removes it: it leaves every copy, archived there
    sync(anna, ben, dana)
    assert not has(dana, doc)
    with anna:                                # the project has it again, and now nobody's AI may read it
        with anna.ws.connect() as cx:
            ctx = ownership._Ctx(anna.ws, cx, anna.id)
            ctx.put(doc, ("state", "ai"), state="in", ai_access="none")
            cx.execute("DELETE FROM sync_removed WHERE kind='document' AND key=?", (doc,))
    with anna:
        folder.sync_now(anna.ws)
    with dana:
        folder.sync_now(dana.ws)              # one round: the document is back from Dana's archive
    assert has(dana, doc)
    assert level(dana, doc) == "none", "back at the level it had when it was removed"


# ---- a judgement taken back in this person's name ----------------------------------------------------------------
def test_a_file_does_not_take_back_this_persons_own_judgement(anna_and_ben):
    anna, ben = anna_and_ben
    with ben:
        cid = _claim(ben.ws, anna.hid)
        pid = _excerpts(ben.ws, anna.hid)[0]["passage_id"]
        claimcheck.set_judgement(ben.ws, cid, pid, "supports", note="Ben's own reasoning, two paragraphs of it")
    with anna:
        with anna.ws.connect() as cx:
            cx.execute("INSERT OR REPLACE INTO judgements(claim_id, passage_id, person_id, verdict, note, at) VALUES "
                       "(?,?,?,NULL,NULL,'2999-01-02T00:00:00+00:00')", (cid, pid, ben.id))
    ben.bring_in(anna.send())
    with ben:
        assert ben.ws.query("SELECT verdict, note FROM judgements WHERE passage_id=? AND person_id=?",
                            (pid, ben.id))[0][:] == ("supports", "Ben's own reasoning, two paragraphs of it")


# ---- third batch --------------------------------------------------------------------------------------------------
# the builders' own H3 proof (test_roles_proofs.py), with the forged row numbered 2**53 instead of 10**6
def test_a_forged_removal_numbered_at_the_top_is_still_answered_by_the_owner(team, tmp_path, monkeypatch):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs")
    sync(anna, ben, carol)
    with carol:
        with carol.ws.connect() as cx:
            cur = cx.execute("SELECT * FROM canon WHERE doc=? ORDER BY owner_seq DESC, n DESC LIMIT 1", (doc,))
            cols = [c[0] for c in cur.description]
            r = dict(zip(cols, cur.fetchone()))
            assert r["by"] == anna.id
            r.update(n=2 ** 53, state="removed", state_n=2 ** 53)
            cx.execute(f"INSERT OR REPLACE INTO canon({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       [r[c] for c in cols])
    sync(carol, ben)
    # changed from the review's `assert not has(ben, doc)`: by the brief's rule for H2, a row numbered more than 2**32
    # above every number Ben's copy holds is not taken at all, so the forged removal never reaches him
    assert has(ben, doc)
    sync(anna, ben, carol, rounds=3)          # Anna answers with her own row
    with anna:
        n = anna.ws._conn().execute("SELECT n FROM canon WHERE doc=? AND by=?", (doc, anna.id)).fetchone()[0]
    with ben:
        k = ownership.canon(ben.ws._conn()).get(doc)
    assert has(ben, doc), f"Anna's answer is numbered {n} (2**53 + {n - 2 ** 53}); Ben's copy says {k and k['state']}"


# a former owner's late row, for a document only a Co-owner's row counts for
def test_a_former_owners_late_row_does_not_count_for_a_co_owners_document(tmp_path, monkeypatch, shared):
    anna, ben, carol, dana = make_crew(tmp_path, monkeypatch, shared)      # Ben and Carol are Co-owners
    doc = add_doc(carol, tmp_path, "note", text=NOTE)
    sync(carol, anna, ben, dana)
    with anna:
        ownership.hand_over(anna.ws, ben.id, "Ben leads it now")
    sync(anna, ben, carol, dana, rounds=2)                                 # Ben writes the project again as his
    assert view(dana)["owner"]["id"] == ben.id
    with anna:                                # Anna's row of place 1, written late: it removes Carol's document
        with anna.ws.connect() as cx:
            cur = cx.execute("SELECT * FROM canon WHERE doc=? AND by=?", (doc, carol.id))
            cols = [c[0] for c in cur.description]
            r = dict(zip(cols, cur.fetchone()))
            hist = json.loads(r["hist_json"] or "{}")
            hist["state"] = (hist.get("state") or []) + [[r["state_n"], r["state_by"] or carol.id]]
            r.update(by=anna.id, owner_seq=1, grant=None, n=r["n"] + 1, state="removed", state_n=r["n"] + 1,
                     state_by=anna.id, hist_json=json.dumps(hist))
            cx.execute(f"INSERT OR REPLACE INTO canon({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       [r[c] for c in cols])
    sync(anna, ben, carol, dana)
    with dana:
        k = ownership.canon(dana.ws._conn()).get(doc)
    assert k["state"] == "in" and has(dana, doc), "the former owner's row counts: the document left Dana's copy"
