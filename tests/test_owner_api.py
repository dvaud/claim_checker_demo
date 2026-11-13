"""0.18.0 (roadmap L2): the endpoints of one owner and several collaborators (gui/api_owner.py and the `# 0.18 (L2)`
routes of gui/server.py), over HTTP, as the Team tab and the Documents page use them (plan §7, §9.1 item 11).

Each person has their own app (their own server in their own ENLENS folder, with their copy of the project linked
in), so what one copy answers is what that person would see. The work between the copies goes through the shared
folder (owner_helpers.sync) or a zip, as in tests/test_owner.py.

- the view: every field the plan names, for the owner and for a collaborator; a project never exchanged; one with no
  owner;
- who may do what: only the owner answers proposals, turns the setting and hands the project over; only the
  proposer takes a proposal back; take-over and claim only when allowed; each refusal in words, with its code (403,
  404, 409, 400);
- `documents[].proposal` in the Documents listing, `proposed` in `PUT documents/ai-access`;
- a new reading the owner accepted: made in the owner's copy at once (a job in the reader lane), in a colleague's copy
  after the round of the shared folder that brought it (`after_job`) or the zip, and `POST owner/apply` when a copy
  waits for its person.
"""
from __future__ import annotations

import threading
import time
import urllib.parse
from pathlib import Path

import pytest

from enlens_claims import ingest, ownership, reread
from enlens_claims.sync import folder
from owner_helpers import add_doc, follow, has, join, level, move, reader_of, sync
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_app import Api, home  # noqa: F401  (fixture)

NAME = "Közös projekt"  # a project name with accents and a space, as a researcher names one
URL = urllib.parse.quote(NAME)
VIEW = {"owner", "me", "is_owner", "since", "how", "can_claim", "can_take_over", "accept_adds", "people", "proposals",
        "waiting", "to_apply", "documents", "job",
        # roles (DESIGN-roles §7 P1, builder P1): the role, questions, offers, removals, clashes, refused rows, notices
        "role", "can_write", "can_set_roles", "questions", "offers", "removed", "clashes", "refused", "notices",
        "later"}  # 0.18.1: questions put off with Not now, kept per person
PROPOSAL = {"id", "kind", "severity", "doc", "title", "what", "by", "at", "state", "note", "reason", "decided_by",
            "decided_at", "auto", "mine", "can_decide", "can_take_back", "here", "conflicts", "detail",
            "clash"}  # roles (builder P1): who accepted and who declined, when answered both ways
DETAIL = {"add": {"sha1", "text_fp", "reader", "ai_access", "state_n", "again"},
          "reread": {"from_fp", "from_reader", "to_fp", "to_reader"},
          "blocks": {"digest", "blocks_n", "left_out", "restored", "undone", "bounds"},
          "remove": {"removed_at", "state_n"},
          "loosen": {"from", "to", "ai_n"}}


class Served:
    """One person's app with their copy of the project in it. Calls are made as that person (their ENLENS folder)."""

    def __init__(self, p: Person, api: Api, app, srv):
        self.p, self.api, self.app, self.srv = p, api, app, srv

    def __call__(self, method: str, path: str = "", body: dict | None = None, raw: bytes | None = None,
                 base: str | None = None):
        with self.p:
            return self.api(method, (base if base is not None else f"/api/projects/{URL}") + path, body, raw=raw)

    def owner(self) -> dict:
        st, v = self("GET", "/owner")
        assert st == 200, v
        return v

    def jobs(self, kind: str | None = None) -> list:
        return [j for j in self.app.jobs.all() if kind is None or j.kind == kind]

    def idle(self, timeout: float = 60) -> None:
        """Every job of this app has ended (so nothing runs as this person while the test acts as another). 2026-11-12:
        and so has each job's thread: a job shows as done before its `ended` listeners run, and one of them may start
        the next job (the new reading after a round); under load that gap let this return before it was queued."""
        t0 = time.time()

        def busy() -> bool:
            jobs = self.app.jobs.all()
            names = {f"job-{j.kind}-{j.id}" for j in jobs}
            return (any(j.state in ("queued", "running") for j in jobs)
                    or any(t.name in names and t.is_alive() for t in threading.enumerate()))

        while busy():
            assert time.time() - t0 < timeout, [j.view(False) for j in self.app.jobs.all()]
            time.sleep(0.05)


@pytest.fixture
def serve():
    from enlens_claims import home
    from enlens_claims.gui.server import make_server

    started = []

    def start(p: Person) -> Served:
        with p:
            assert home.link_existing(str(p.ws.root), NAME) == NAME
            srv, app = make_server("127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        s = Served(p, Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token), app, srv)
        started.append(s)
        return s

    yield start
    for s in started:
        s.idle()
        s.srv.shutdown()
        s.srv.server_close()


@pytest.fixture
def shared_dir(tmp_path) -> Path:
    d = tmp_path / "Dávid" / "OneDrive - Közös egyetem" / "Csapat mappa"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def team(anna_and_ben, shared_dir, tmp_path, monkeypatch):
    """Anna (the maker, so the owner), Ben and Carol, all in the shared folder, after two rounds."""
    anna, ben = anna_and_ben
    for p in (anna, ben):
        with p:
            folder.set_folder(p.ws, str(shared_dir))
    carol = Person(tmp_path, "Carol", monkeypatch)
    join(carol, anna, tmp_path, shared_dir)
    sync(anna, ben, carol)
    return anna, ben, carol


def _waiting(s: Served, kind: str | None = None) -> list[dict]:
    return [x for x in s.owner()["proposals"] if x["state"] == "waiting" and (kind is None or x["kind"] == kind)]


def _words(body: dict) -> str:
    """A refusal is a sentence for a researcher: no Python names, no ids in brackets."""
    msg = body.get("error") or ""
    assert msg and msg[0].isupper() and msg.rstrip().endswith((".", ")")), body
    assert not any(w in msg for w in ("Error", "Traceback", "KeyError", "None", "NotAllowed")), msg
    return msg


# ---- the view --------------------------------------------------------------------------------------------------
def test_the_view_has_every_field_for_the_owner_and_for_a_collaborator(team, serve):
    anna, ben, carol = team
    a, b = serve(anna), serve(ben)
    va, vb = a.owner(), b.owner()
    assert set(va) == VIEW and set(vb) == VIEW
    assert va["owner"] == {"id": anna.id, "name": "you", "me": True} and va["is_owner"] and va["how"] == "made"
    assert vb["owner"] == {"id": anna.id, "name": "Anna", "me": False} and not vb["is_owner"]
    assert va["me"] == anna.id and vb["me"] == ben.id and va["since"] and va["since"] == vb["since"]
    assert va["accept_adds"] is True and not va["can_claim"] and not vb["can_claim"] and vb["can_take_over"] is None
    for v in (va, vb):
        assert v["proposals"] == [] and v["waiting"] == 0 and v["to_apply"] == [] and v["documents"] == {}
        assert v["job"] is None
        assert {x["id"] for x in v["people"]} == {anna.id, ben.id, carol.id}
        assert all(set(x) == {"id", "name", "me", "owner", "role", "same_as", "needs_update"}  # (+ roles, builder P1)
                   for x in v["people"])
        assert [x["id"] for x in v["people"] if x["owner"]] == [anna.id]
        assert [x["id"] for x in v["people"] if x["me"]] == [v["me"]] and v["people"][0]["me"]
    # the project's documents carry no proposal
    st, docs = b("GET", "/documents")
    assert st == 200 and docs["documents"] and all(d["proposal"] is None for d in docs["documents"])


def test_a_project_never_exchanged_is_its_makers_and_nothing_is_written(home, tmp_path):  # noqa: F811
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        api = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
        assert api("POST", "/api/projects", {"name": "Solo"})[0] == 200
        st, v = api("GET", "/api/projects/Solo/owner")
        assert st == 200 and set(v) == VIEW and v["is_owner"] and v["owner"]["me"] and v["how"] == "made"
        assert v["since"] is None and not v["can_claim"] and v["people"][0]["owner"]
        assert app.ws("Solo").query("SELECT 1 FROM ownership") == []   # written when it first leaves the computer
        st, err = api("POST", "/api/projects/Solo/owner/claim", {})
        assert st == 403 and "owner" in _words(err)                     # its maker is its owner already
        st, err = api("GET", "/api/projects/Nothing/owner")
        assert st == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_project_exchanged_before_has_no_owner_until_someone_claims_it(team, serve):
    anna, ben, carol = team
    for p in team:  # as a project exchanged with 0.17: no record of an owner, nothing decided
        with p:
            with p.ws.connect() as cx:
                # (and nothing pinned: since the review's C1 a pinned record that vanishes makes its place a question)
                for t in ("ownership", "proposals", "decisions", "canon", "canon_seen", "owner_pins"):
                    cx.execute(f"DELETE FROM {t}")
    b = serve(ben)
    v = b.owner()
    assert v["owner"] is None and v["can_claim"] and not v["is_owner"] and v["how"] is None
    assert not any(x["owner"] for x in v["people"])
    st, err = b("POST", "/owner/hand-over", {"to": anna.id})
    assert st == 403 and _words(err)
    st, err = b("POST", "/owner/take-over", {})
    assert st == 403 and "become" in _words(err).lower()
    st, v = b("POST", "/owner/claim", {})
    assert st == 200 and set(v) == VIEW and v["is_owner"] and v["how"] == "claim" and not v["can_claim"]
    assert v["owner"] == {"id": ben.id, "name": "you", "me": True}
    st, err = b("POST", "/owner/claim", {})
    assert st == 403 and "already" in _words(err)
    sync(ben, anna, carol)
    assert serve(anna).owner()["owner"]["id"] == ben.id


# ---- a proposal, as each copy shows it ---------------------------------------------------------------------------
def test_a_proposal_has_every_field_and_the_documents_listing_says_so(team, serve, tmp_path):
    anna, ben, carol = team
    a, b, c = serve(anna), serve(ben), serve(carol)
    st, v = a("PUT", "/owner/settings", {"accept_adds": False})
    assert st == 200 and set(v) == VIEW and v["accept_adds"] is False
    doc = add_doc(ben, tmp_path, "desalination")
    vb = b.owner()
    (p,) = vb["proposals"]
    assert set(p) == PROPOSAL and set(p["detail"]) == DETAIL["add"]
    assert p["kind"] == "add" and p["severity"] == "low" and p["state"] == "waiting" and p["doc"] == doc
    assert p["by"] == {"id": ben.id, "name": "you", "me": True} and p["mine"] and p["can_take_back"]
    assert not p["can_decide"] and p["here"] and p["conflicts"] == [] and p["decided_by"] is None
    assert p["what"].startswith("adding “") and p["title"] and p["at"]
    assert vb["waiting"] == 1 and vb["documents"][doc]["state"] == "proposed" and vb["documents"][doc]["text"]
    st, docs = b("GET", "/documents")
    mark = {d["doc_id"]: d["proposal"] for d in docs["documents"]}
    assert mark[doc] == vb["documents"][doc] and sum(1 for m in mark.values() if m) == 1
    sync(ben, carol, anna)
    va, vc = a.owner(), c.owner()
    (pa,) = va["proposals"]
    assert pa["can_decide"] and not pa["mine"] and not pa["can_take_back"] and va["waiting"] == 1
    assert pa["by"] == {"id": ben.id, "name": "Ben", "me": False}
    (pc,) = vc["proposals"]
    assert not pc["can_decide"] and not pc["can_take_back"] and vc["waiting"] == 0   # Carol only sees it
    assert vc["documents"][doc]["state"] == "proposed" and "Ben" in vc["documents"][doc]["text"]
    st, docs = c("GET", "/documents")
    assert {d["doc_id"]: d["proposal"] for d in docs["documents"]}[doc]["state"] == "proposed"


def test_every_kind_of_proposal_has_its_detail(team, serve, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs", reader=1, ai="local")
    gone = add_doc(anna, tmp_path, "grid")
    sync(anna, ben, carol)
    from owner_helpers import leave_out

    move(ben, doc)
    leave_out(ben, doc, 1)
    with ben:
        ben.ws.remove_document(gone)
    b = serve(ben)
    st, r = b("PUT", "/documents/ai-access", {"doc_ids": [doc], "ai_access": "cloud"})
    assert st == 200 and r["proposed"] == [doc]
    assert {d["doc_id"]: d["ai_access"] for d in r["documents"]}[doc] == "local"   # the listing: unchanged
    add_doc(ben, tmp_path, "desalination")
    got = {x["kind"]: x for x in b.owner()["proposals"]}
    assert set(got) == set(DETAIL)
    for kind, x in got.items():
        assert set(x["detail"]) == DETAIL[kind], kind
        assert x["severity"] == ownership.SEVERITY[kind] and x["state"] == "waiting"
    assert got["loosen"]["detail"]["from"] == "local" and got["loosen"]["detail"]["to"] == "cloud"
    assert got["reread"]["detail"]["to_reader"] == ingest.READER and got["remove"]["here"] is False
    assert got["blocks"]["detail"]["left_out"] == 1
    # the documents of this copy say what waits for the owner
    st, docs = b("GET", "/documents")
    mark = {d["doc_id"]: d["proposal"] for d in docs["documents"]}
    assert mark[doc]["state"] == "waiting" and "Waiting for the owner" in mark[doc]["text"]


# ---- who may answer ----------------------------------------------------------------------------------------------
def test_only_the_owner_answers_and_only_the_proposer_takes_back(team, serve, tmp_path):
    anna, ben, carol = team
    a, b = serve(anna), serve(ben)
    assert a("PUT", "/owner/settings", {"accept_adds": False})[0] == 200
    kept = add_doc(ben, tmp_path, "desalination")
    other = add_doc(ben, tmp_path, "grid")
    sync(ben, anna)
    ids = {x["doc"]: x["id"] for x in _waiting(a)}
    st, err = b("POST", f"/owner/proposals/{ids[kept]}/accept", {})
    assert st == 403 and "Only the owner" in _words(err)
    st, err = b("POST", f"/owner/proposals/{ids[kept]}/decline", {"reason": "no"})
    assert st == 403 and "Only the owner" in _words(err)
    st, err = a("POST", f"/owner/proposals/{ids[kept]}/take-back", {})
    assert st == 403 and "Only who made" in _words(err)
    for verb in ("accept", "decline", "take-back"):
        st, err = a("POST", f"/owner/proposals/q0000000000000000/{verb}", {})
        assert st == 404 and _words(err)
    st, v = a("POST", f"/owner/proposals/{ids[kept]}/accept", {"reason": "Fits the question"})
    assert st == 200 and set(v) == VIEW
    done = {x["id"]: x for x in v["proposals"]}[ids[kept]]
    assert done["state"] == "accepted" and done["reason"] == "Fits the question" and not done["auto"]
    assert done["decided_by"]["id"] == anna.id and done["decided_at"] and not done["can_decide"]
    st, err = a("POST", f"/owner/proposals/{ids[kept]}/decline", {})
    assert st == 409 and "no longer waits" in _words(err)
    st, v = a("POST", f"/owner/proposals/{ids[other]}/decline", {"reason": "A modelling study"})
    assert st == 200 and {x["id"]: x for x in v["proposals"]}[ids[other]]["state"] == "declined"
    assert v["waiting"] == 0 and not has(anna, other)
    sync(anna, ben)
    st, err = b("POST", f"/owner/proposals/{ids[other]}/take-back", {})
    assert st == 409 and "no longer waits" in _words(err)
    vb = b.owner()
    assert vb["documents"][other]["state"] == "declined" and "declined" in vb["documents"][other]["text"]
    st, bad = a("POST", f"/owner/proposals/{ids[kept]}/accept", raw=b"[1, 2]")
    assert st == 400


def test_the_proposer_takes_a_proposal_back(team, serve, tmp_path):
    anna, ben, carol = team
    a, b = serve(anna), serve(ben)
    assert a("PUT", "/owner/settings", {"accept_adds": False})[0] == 200
    doc = add_doc(ben, tmp_path, "grid")
    (p,) = _waiting(b)
    st, v = b("POST", f"/owner/proposals/{p['id']}/take-back", {})
    assert st == 200 and set(v) == VIEW
    (x,) = v["proposals"]
    assert x["state"] == "taken_back" and not x["can_take_back"] and v["waiting"] == 0
    assert v["documents"][doc]["state"] == "declined" and has(ben, doc)    # in his copy only
    with ben:
        assert ben.ws.scalar("SELECT kind FROM research_log ORDER BY rowid DESC LIMIT 1") == "proposal-taken-back"


def test_the_owners_setting_is_the_owners_and_turning_it_on_accepts_what_waits(team, serve, tmp_path):
    anna, ben, carol = team
    a, b = serve(anna), serve(ben)
    st, err = b("PUT", "/owner/settings", {"accept_adds": False})
    assert st == 403 and "Only the owner" in _words(err)
    for bad in ({}, {"accept_adds": "yes"}, {"accept_adds": 1}):
        st, err = a("PUT", "/owner/settings", bad)
        assert st == 400 and _words(err)
    assert a("PUT", "/owner/settings", {"accept_adds": False})[1]["accept_adds"] is False
    doc = add_doc(ben, tmp_path, "desalination")
    sync(ben, anna)
    assert a.owner()["waiting"] == 1
    st, v = a("PUT", "/owner/settings", {"accept_adds": True})
    assert st == 200 and v["accept_adds"] is True and v["waiting"] == 0
    (x,) = v["proposals"]
    assert x["state"] == "accepted" and x["auto"] and x["doc"] == doc


# ---- who the owner is ----------------------------------------------------------------------------------------------
def test_hand_over_and_take_over(team, serve, shared_dir):
    import shutil

    anna, ben, carol = team
    a, b, c = serve(anna), serve(ben), serve(carol)
    st, err = b("POST", "/owner/hand-over", {"to": carol.id})
    assert st == 403 and "Only the owner" in _words(err)
    st, err = a("POST", "/owner/hand-over", {})
    assert st == 400 and _words(err)
    st, err = a("POST", "/owner/hand-over", {"to": "p" + "0" * 16})
    assert st == 404 and _words(err)
    st, err = a("POST", "/owner/hand-over", {"to": anna.id})
    assert st == 400 and _words(err)
    st, v = a("POST", "/owner/hand-over", {"to": ben.id, "why": "On leave"})
    assert st == 200 and set(v) == VIEW and v["owner"]["id"] == ben.id and v["how"] == "handover"
    assert not v["is_owner"] and v["can_take_over"] is None
    sync(anna, ben, carol)
    vb = b.owner()
    assert vb["is_owner"] and vb["how"] == "handover" and vb["accept_adds"] is True
    st, err = c("POST", "/owner/take-over", {})
    assert st == 403 and "hand the project over" in _words(err)
    st, err = b("POST", "/owner/take-over", {})
    assert st == 403 and "already" in _words(err)
    shutil.rmtree(shared_dir / folder.team_name(ben.ws) / ben.id)   # Ben leaves the shared folder
    vc = c.owner()
    assert vc["can_take_over"] and vc["can_take_over"].endswith(".")
    st, v = c("POST", "/owner/take-over", {"why": "Ben left"})
    assert st == 200 and v["is_owner"] and v["how"] == "takeover" and v["owner"]["id"] == carol.id
    # roles (DESIGN-roles §4.1, §6.6): a take-over is never followed unasked; the other copies answer *Follow*
    sync(carol, anna, rounds=1)
    va = a.owner()
    assert va["owner"]["id"] == ben.id
    assert [(q["kind"], q["owner"], q["now"]) for q in va["questions"]] == [("takeover", carol.id, ben.id)]
    assert va["waiting"] >= 1
    follow(anna)
    va = a.owner()
    assert va["owner"]["id"] == carol.id and va["how"] == "takeover" and not va["questions"]


def test_the_owners_setting_holds_for_one_time_as_the_owner(team, serve):
    """Plan §12.8: the setting is the owner's own and starts at the default for a new owner, and again for an owner
    who has the project back."""
    anna, ben, carol = team
    a, b = serve(anna), serve(ben)
    assert a("PUT", "/owner/settings", {"accept_adds": False})[1]["accept_adds"] is False
    assert a("POST", "/owner/hand-over", {"to": ben.id})[0] == 200
    sync(anna, ben)
    assert b.owner()["accept_adds"] is True
    assert b("PUT", "/owner/settings", {"accept_adds": False})[1]["accept_adds"] is False
    st, err = a("PUT", "/owner/settings", {"accept_adds": True})
    assert st == 403 and _words(err)
    assert b("POST", "/owner/hand-over", {"to": anna.id})[0] == 200
    sync(ben, anna)
    va = a.owner()
    assert va["is_owner"] and va["accept_adds"] is True     # her earlier "off" was for her earlier time as the owner


# ---- a new reading the owner accepted ------------------------------------------------------------------------------
def test_an_accepted_new_reading_is_made_by_a_job_in_the_owners_copy(team, serve, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs", reader=1)
    sync(anna, ben)
    move(ben, doc)
    sync(ben, anna)
    a = serve(anna)
    (p,) = _waiting(a, "reread")
    st, v = a("POST", f"/owner/proposals/{p['id']}/accept", {})
    assert st == 200
    jobs = a.jobs("new_reader")
    assert len(jobs) == 1 and jobs[0].lane == "reader" and jobs[0].project == NAME
    assert v["job"] is None or v["job"]["id"] == jobs[0].id
    a.idle()
    assert jobs[0].state == "done" and [m["doc_id"] for m in jobs[0].result["moved"]] == [doc]
    assert reader_of(anna, doc) == ingest.READER and a.owner()["job"] is None


def test_after_a_round_the_due_new_reading_starts_as_a_job(team, serve, tmp_path):
    """`after_job`: when a round of the shared folder that brought the owner's decision in ends, the new readings due
    in this copy start as one job of the project's queue (reader lane, started by the app)."""
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs", reader=1)
    sync(anna, ben, carol)
    move(ben, doc)
    sync(ben, anna)
    from owner_helpers import accept, proposals

    accept(anna, proposals(anna, state="waiting")[0]["id"])
    sync(anna)
    c = serve(carol)
    st, r = c("POST", "/shared-folder/sync", {})
    assert st == 200
    c.idle()
    rounds = c.jobs(folder.JOB)
    assert rounds[0].state == "done" and rounds[0].result["moves_due"] == [doc]
    moves = c.jobs("new_reader")
    assert len(moves) == 1 and moves[0].background and moves[0].lane == "reader" and moves[0].state == "done"
    assert reader_of(carol, doc) == ingest.READER and not c.owner()["to_apply"]
    # a second round has nothing more to move
    c("POST", "/shared-folder/sync", {})
    c.idle()
    assert len(c.jobs("new_reader")) == 1


def test_a_copy_that_would_lose_places_waits_and_moves_when_its_person_says(team, serve, tmp_path, monkeypatch):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs", reader=1)
    sync(anna, ben, carol)
    move(ben, doc)
    sync(ben, anna)
    from owner_helpers import accept, proposals

    accept(anna, proposals(anna, state="waiting")[0]["id"])
    sync(anna)
    real = reread.move

    def losing(ws, doc_id, person_id=None, ocr=None, should_stop=None, keep_all=False):
        if keep_all:  # as if one of Carol's results would find no place in the new reading
            raise reread.WouldLose({"not_placed": [{"kind": "verification"}]})
        return real(ws, doc_id, person_id, ocr, should_stop, keep_all)

    monkeypatch.setattr(reread, "move", losing)
    c = serve(carol)
    c("POST", "/shared-folder/sync", {})
    c.idle()
    assert reader_of(carol, doc) == 1
    v = c.owner()
    (row,) = v["to_apply"]
    assert set(row) == {"doc", "title", "kind", "note", "can_force"} and row["doc"] == doc and row["kind"] == "reread"
    assert row["can_force"] and "1 of your results" in row["note"]
    c("POST", "/shared-folder/sync", {})   # it is not tried again by itself: it waits for its person
    c.idle()
    assert len(c.jobs("new_reader")) == 1 and reader_of(carol, doc) == 1
    st, err = c("POST", "/owner/apply", {"doc": "d" + "0" * 15})
    assert st == 404 and _words(err)
    st, err = c("POST", "/owner/apply", {})
    assert st in (400, 404) and _words(err)
    st, r = c("POST", "/owner/apply", {"doc": doc, "force": True})
    assert st == 200 and set(r) == VIEW and r["job"] and r["job"]["kind"] == "new_reader"
    assert r["job"]["background"] is False
    c.idle()
    assert reader_of(carol, doc) == ingest.READER and c.owner()["to_apply"] == []
    st, err = c("POST", "/owner/apply", {"doc": doc})   # nothing left to make here
    assert st == 409 and _words(err)


def test_a_zip_brought_in_follows_the_owner_and_starts_the_due_moves(anna_and_ben, serve, tmp_path):
    """Zips only, no shared folder: Ben's proposal reaches Anna in his file, her answer reaches him in hers; the new
    reading the owner made is made in his copy by a job of the queue once her zip came in."""
    from owner_helpers import leave_out

    anna, ben = anna_and_ben
    doc = add_doc(anna, tmp_path, "jobs", reader=1)
    other = add_doc(anna, tmp_path, "desalination")
    ben.bring_in(anna.send())
    assert has(ben, doc) and reader_of(ben, doc) == 1
    leave_out(ben, other, 1)
    a, b = serve(anna), serve(ben)
    st, r = a("POST", "/bring-in", raw=ben.send().read_bytes())
    assert st == 200 and [x["kind"] for x in r["report"]["proposals"]["new"]] == ["blocks"]
    assert r["report"]["owner"]["owner"] == anna.id and r["report"]["owner"]["moves"] == []
    assert any("proposal" in line for line in r["report"]["lines"])
    (p,) = _waiting(a, "blocks")
    assert a("POST", f"/owner/proposals/{p['id']}/accept", {})[0] == 200
    move(anna, doc)                                       # the owner's own new reading: the project's at once
    a.idle()
    st, r = b("POST", "/bring-in", raw=anna.send().read_bytes())
    assert st == 200 and r["report"]["proposals"]["decided"] == 1 and r["report"]["owner"]["moves"] == [doc]
    moves = b.jobs("new_reader")
    assert len(moves) == 1 and moves[0].background
    b.idle()
    assert reader_of(ben, doc) == ingest.READER and moves[0].state == "done"
    assert b.owner()["proposals"][0]["state"] == "accepted" and not b.owner()["to_apply"]


def test_a_move_waiting_its_turn_is_not_started_twice(team, serve, tmp_path):
    """Two rounds (or a round and a zip) that end while the move they start still waits its turn start one job."""
    from enlens_claims.gui import api_owner

    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs", reader=1)
    sync(anna, carol)
    move(anna, doc)
    sync(anna, rounds=1)
    with carol:  # a round of hers, without the move it makes due
        assert folder.sync_now(carol.ws)["moves_due"] == [doc]
        assert ownership.moves_due(carol.ws) == [doc] and ownership.behind(carol.ws, doc)
    c = serve(carol)
    release = threading.Event()
    with carol:
        busy = c.app.jobs.start("ingest", "Adding sources", NAME, lambda job: release.wait(30), uses_model=False)
        first = api_owner.start_due(c.app, NAME)
        assert first is not None and first.state == "queued" and first.owner_docs == (doc,)
        assert api_owner.start_due(c.app, NAME) is None              # covered by the one that waits
        st, r = c("POST", "/owner/apply", {"doc": doc})
        assert st == 200 and r["job"]["id"] == first.id and c.owner()["job"]["id"] == first.id
    release.set()
    c.idle()
    assert busy.state == "done" and first.state == "done" and len(c.jobs("new_reader")) == 1
    assert reader_of(carol, doc) == ingest.READER


# ---- the weak spots of the plan (§10.2, §10.3) ---------------------------------------------------------------------
def test_the_documents_listing_does_not_look_at_the_shared_folder(team, serve, monkeypatch):
    """§10.2: the Documents page's marks come without a look at the shared folder (a network drive that is not there
    must not hold the page up); the Team tab's view still says whether the owner has left."""
    anna, ben, carol = team
    b = serve(ben)

    def no_look(*a, **kw):
        raise AssertionError("the shared folder was looked at")

    monkeypatch.setattr(ownership, "owner_left", no_look)
    st, docs = b("GET", "/documents")
    assert st == 200 and all("proposal" in d for d in docs["documents"])
    st, err = b("GET", "/owner")
    assert st == 500                                   # (the Team tab's view does look)


def test_the_owners_view_does_not_wait_for_other_work_on_the_database(team, serve, tmp_path):
    """§10.3: `GET owner` writes what this person changed as proposals first, but never waits for other work that
    holds the project's database (a document read again, a merge): it shows what stands, and writes at the next look."""
    import sqlite3

    anna, ben, carol = team
    b = serve(ben)
    b.owner()
    doc = add_doc(ben, tmp_path, "grid")
    other = sqlite3.connect(ben.ws.db_path, isolation_level=None, timeout=1)
    other.execute("BEGIN IMMEDIATE")                   # as a long move or merge holds it
    try:
        t0 = time.time()
        v = b.owner()
        assert time.time() - t0 < 5 and v["proposals"] == []
        st, docs = b("GET", "/documents")
        assert st == 200 and {d["doc_id"] for d in docs["documents"]} >= {doc}
    finally:
        other.execute("ROLLBACK")
        other.close()
    (p,) = b.owner()["proposals"]
    assert p["doc"] == doc and p["kind"] == "add"
