"""Roles (DESIGN-roles §7 P4): the routes of the Team tab's new pieces (gui/api_owner.py, gui/server.py).

- each route exists, checks what it is sent, and hands the right arguments to the rule it calls (the rules are
  monkeypatched here, so these tests hold whatever P1, P2 and P3 build behind them);
- a refusal of a rule is the page's status: NotAllowed 403, KeyError 404, ValueError 409, a rule not built yet 501;
- end to end, against the real rules: marked `needs_p1` / `needs_p2` / `needs_p3`, skipped while the rule they need
  is still a stub of S0 (they switch on by themselves once it is built).
"""
from __future__ import annotations

import pytest

from enlens_claims import codebooks, ownership, people, removed
from enlens_claims.gui import server
from test_app import api, home  # noqa: F401  (fixtures)


def _stub(fn, *args) -> bool:
    """True while `fn` is still the S0 stub (it raises NotImplementedError at once)."""
    try:
        fn(*args)
    except NotImplementedError:
        return True
    except Exception:  # noqa: BLE001 - built: it failed on the dummy arguments, as it may
        return False
    return False


needs_p1 = pytest.mark.skipif(_stub(ownership.owner_questions, None), reason="waits for P1: ownership's roles rules are stubs")
needs_p2 = pytest.mark.skipif(_stub(codebooks.offers, None), reason="waits for P2: codebooks.offers is a stub")
needs_p3 = pytest.mark.skipif(_stub(removed.listing, None), reason="waits for P3: removed.py is a stub")

ROUTES = [
    ("PUT", "/api/projects/Demo/owner/roles/pben", "put_owner_role"),
    ("POST", "/api/projects/Demo/owner/questions/q1", "post_owner_question"),
    ("POST", "/api/projects/Demo/owner/loosening", "post_owner_loosening"),
    ("POST", "/api/projects/Demo/owner/removed/d1/restore", "post_owner_restore"),
    ("POST", "/api/projects/Demo/owner/clashes/c1", "post_owner_clash"),
    ("POST", "/api/projects/Demo/owner/take-back", "post_owner_take_back"),
    ("POST", "/api/projects/Demo/owner/refused/canon/d1/dismiss", "post_owner_refused_dismiss"),
    ("GET", "/api/projects/Demo/codebooks/Energy/offer", "get_codebook_offer"),
    ("POST", "/api/projects/Demo/codebooks/Energy/follow", "post_codebook_follow"),
]


def test_every_route_of_the_design_is_there_and_answers_on_its_handler():
    for method, path, name in ROUTES:
        hits = [n for m, rx, n in server.ROUTES if m == method and rx.match(path)]
        assert hits and hits[0] == name, (method, path, hits)
        assert callable(getattr(server.Handler, name)), name
    # the proposal's own take-back is still the proposal's (not the project's)
    hit = [n for m, rx, n in server.ROUTES if m == "POST" and rx.match("/api/projects/Demo/owner/proposals/q1/take-back")]
    assert hit[0] == "post_proposal_take_back"


@pytest.fixture
def demo(api):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    return api


@pytest.fixture
def calls(monkeypatch):
    """The rules the routes call, replaced: each call is kept; ownership.view gives a small view."""
    seen: list[tuple] = []

    def rec(name, result=None):
        def f(*a):
            seen.append((name, a[1:]))   # the first is the project's Workspace
            return result if result is not None else {}
        return f

    for n in ("set_role", "set_same_as", "follow_owner", "keep_owner", "answer_loosening", "decide_again",
              "take_project_back", "dismiss_refused"):
        monkeypatch.setattr(ownership, n, rec(n))
    monkeypatch.setattr(ownership, "owner_questions", lambda cx: [{"id": "q1", "seq": 2, "kind": "takeover", "owner": "pben",
                                                                    "by": "pben", "why": None, "now": "panna"}])
    monkeypatch.setattr(ownership, "view", lambda ws, light=False: {"role": "member", "can_write": False})
    monkeypatch.setattr(ownership, "settle", lambda *a, **k: None)
    return seen


def test_roles_and_the_same_person(demo, calls):
    st, v = demo("PUT", "/api/projects/Demo/owner/roles/pben", {"role": "co"})
    assert st == 200 and v["role"] == "member" and "job" in v
    st, _ = demo("PUT", "/api/projects/Demo/owner/roles/pben", {"same_as": "panna"})
    assert st == 200
    st, _ = demo("PUT", "/api/projects/Demo/owner/roles/pben", {"same_as": None})
    assert st == 200
    assert [c[0] for c in calls] == ["set_role", "set_same_as", "set_same_as"]
    assert calls[0][1] == ("pben", "co") and calls[1][1] == ("pben", "panna") and calls[2][1] == ("pben", None)
    # what is not a role, nothing to set, oneself, or the same as oneself: refused before any rule runs
    for body in ({"role": "owner"}, {"role": "boss"}, {}, {"same_as": "pben"}, {"same_as": 3}):
        assert demo("PUT", "/api/projects/Demo/owner/roles/pben", body)[0] == 400, body
    assert demo("PUT", f"/api/projects/Demo/owner/roles/{people.me()}", {"role": "co"})[0] == 400
    assert len(calls) == 3


def test_questions_are_answered_by_their_id(demo, calls):
    assert demo("POST", "/api/projects/Demo/owner/questions/q1", {"answer": "follow"})[0] == 200
    assert demo("POST", "/api/projects/Demo/owner/questions/q1", {"answer": "keep"})[0] == 200
    assert calls == [("follow_owner", (2, "pben")), ("keep_owner", (2, "pben"))]
    assert demo("POST", "/api/projects/Demo/owner/questions/q1", {"answer": "later"})[0] == 400
    assert demo("POST", "/api/projects/Demo/owner/questions/qgone", {"answer": "follow"})[0] == 404   # not asked any more


def test_looser_ai_settings_are_answered_for_the_documents_ticked(demo, calls):
    assert demo("POST", "/api/projects/Demo/owner/loosening", {"docs": ["d1", "d2"], "allow": True})[0] == 200
    assert demo("POST", "/api/projects/Demo/owner/loosening", {"docs": None, "allow": False})[0] == 200
    assert calls == [("answer_loosening", (["d1", "d2"], True)), ("answer_loosening", (None, False))]
    # the review's change 1: a batch that loosens names its documents; nothing ticked is no request
    for body in ({"docs": [], "allow": True}, {"docs": ["d1"]}, {"docs": "d1", "allow": True}, {"docs": [3], "allow": True}):
        assert demo("POST", "/api/projects/Demo/owner/loosening", body)[0] == 400, body


def test_leave_it_so_take_back_and_dismiss(demo, calls):
    assert demo("POST", "/api/projects/Demo/owner/clashes/c1", {})[0] == 200
    assert demo("POST", "/api/projects/Demo/owner/take-back", {})[0] == 200
    assert demo("POST", "/api/projects/Demo/owner/refused/canon/d1/dismiss", {})[0] == 200
    assert calls == [("decide_again", ("c1",)), ("take_project_back", ()), ("dismiss_refused", ("canon", "d1"))]


def test_a_rules_refusal_is_the_pages_status(demo, monkeypatch, calls):
    def refuse(exc):
        def f(*a):
            raise exc
        return f

    for exc, status in ((ownership.NotAllowed("Only the owner sets roles."), 403), (KeyError("pnobody"), 404),
                        (ValueError("no longer so"), 409), (NotImplementedError("P1"), 501)):
        monkeypatch.setattr(ownership, "set_role", refuse(exc))
        st, body = demo("PUT", "/api/projects/Demo/owner/roles/pben", {"role": "co"})
        assert st == status, (exc, body)
        if status == 403:
            assert body["error"] == "Only the owner sets roles."


def test_restore_says_whether_it_was_proposed(demo, monkeypatch, calls):
    monkeypatch.setattr(removed, "listing", lambda ws: [{"doc": "d1", "title": "Jobs", "at": "2026-11-12T10:00:00Z",
                                                         "by": "panna", "why": "", "cause": "removed", "until": "2026-12-12"}])
    monkeypatch.setattr(removed, "restore", lambda ws, doc: doc == "d1")
    st, v = demo("POST", "/api/projects/Demo/owner/removed/d1/restore", {})
    assert st == 200 and v["restored"] == {"doc": "d1", "title": "Jobs", "proposed": True}   # a Member's copy (the view)
    monkeypatch.setattr(ownership, "view", lambda ws, light=False: {"role": "co", "can_write": True})
    st, v = demo("POST", "/api/projects/Demo/owner/removed/d1/restore", {})
    assert st == 200 and v["restored"]["proposed"] is False
    assert demo("POST", "/api/projects/Demo/owner/removed/d9/restore", {})[0] == 404   # its 30 days are over


def test_a_codebooks_offer_and_its_answer(demo, monkeypatch):
    # before P2: no offer, and Follow has nothing to answer
    monkeypatch.setattr(codebooks, "offers", lambda ws: (_ for _ in ()).throw(NotImplementedError("P2")))
    st, r = demo("GET", "/api/projects/Demo/codebooks/Energy/offer")
    assert st == 200 and r == {"offer": None}
    offer = {"name": "Energy", "from": "pben", "events": [{"op": "rename", "from": "A", "to": "Water use"}], "labels": 40}
    left = [offer]
    answered = []
    monkeypatch.setattr(codebooks, "offers", lambda ws: list(left))
    monkeypatch.setattr(codebooks, "answer_offer", lambda ws, name, follow: (answered.append((name, follow)), left.clear()))
    monkeypatch.setattr(codebooks, "load", lambda ws, name: {"name": name})
    assert demo("GET", "/api/projects/Demo/codebooks/Energy/offer")[1] == {"offer": offer}
    assert demo("GET", "/api/projects/Demo/codebooks/Other/offer")[1] == {"offer": None}
    assert demo("POST", "/api/projects/Demo/codebooks/Energy/follow", {"follow": "yes"})[0] == 400
    st, r = demo("POST", "/api/projects/Demo/codebooks/Energy/follow", {"follow": True})
    assert st == 200 and r == {"codebook": {"name": "Energy"}, "offer": None} and answered == [("Energy", True)]
    assert demo("POST", "/api/projects/Demo/codebooks/Energy/follow", {"follow": False})[0] == 409   # nothing waits now


# ------------------------------------------------------------------ end to end, against the real rules
@needs_p1
def test_the_view_has_every_field_the_page_reads(demo):
    st, v = demo("GET", "/api/projects/Demo/owner")
    assert st == 200
    assert {"role", "can_write", "can_set_roles", "questions", "offers", "removed", "clashes", "refused", "notices"} <= set(v)
    assert v["role"] == "owner" and v["can_write"] is True and v["can_set_roles"] is True
    for p in v["people"]:
        assert {"role", "same_as", "needs_update"} <= set(p)


@needs_p1
def test_only_the_owners_copy_sets_roles(demo):
    st, v = demo("GET", "/api/projects/Demo/owner")
    assert v["can_set_roles"] is True
    # a person the project does not know: 404
    assert demo("PUT", "/api/projects/Demo/owner/roles/pnobody00000000", {"role": "co"})[0] == 404


@needs_p3
def test_restore_without_an_archive_is_404(demo):
    assert demo("POST", "/api/projects/Demo/owner/removed/dnothing/restore", {})[0] == 404


@needs_p2
def test_a_codebook_with_no_colleague_has_no_offer(demo):
    st, r = demo("GET", "/api/projects/Demo/codebooks/Nothing/offer")
    assert st == 200 and r == {"offer": None}
