"""One owner, several collaborators (0.18, roadmap L2): the endpoints of Handler for who the owner is, the proposals
that wait for the owner, and the owner's answers (ownership.py). The Team tab's "Waiting for the owner" and the
Documents page use them.

`Handler` takes this class as a base, so the names in ROUTES resolve on it. A new reading the owner accepted is made in
each copy by a job in the project's queue (`start_moves`, lane `reader`: never beside other work on the project's
documents), started when the owner accepts it, when a round of the shared folder that brought the decision in ends
(`after_job`) and after a zip was brought in (`start_due`, api_checks.py)."""
from __future__ import annotations

import traceback

from .api_common import ONE_START, ApiError, Job
from .. import home, ownership

JOB = "new_reader"  # the kind of the Documents page's "read with the new reader" job: the same lane, one at a time


def _covered(app, name: str) -> set[str]:
    """The documents a move job of the project that waits or runs will read anyway."""
    return {d for j in app.jobs.all() if j.kind == JOB and j.project == name and j.state in ("queued", "running")
            for d in getattr(j, "owner_docs", ())}


def start_moves(app, name: str, docs: list[str], force: bool = False) -> Job | None:
    """Read these documents with the new reader in this copy, as the project now reads them (`ownership.move_now`),
    then what adding documents does (search by meaning, the glossary, the codes). A document that a move job of the
    project waiting or running covers already is left to it; one that reads as the project does by the time the job
    has its turn (moved meanwhile) is passed over."""
    from .. import embed
    from ..llm import BackendError

    ws = app.ws(name)
    docs = [d for d in dict.fromkeys(docs) if d not in _covered(app, name)]
    if not docs:
        return None
    titles = {r["doc_id"]: r["title"] or "" for r in ws.query("SELECT doc_id, title FROM documents")}

    def run(job: Job):
        moved, kept = [], []
        for i, doc in enumerate(docs):
            if job.cancel.is_set():
                break
            if not ownership.behind(ws, doc):  # moved (or removed) while the job waited its turn: nothing to do
                continue
            job.progress = {"done": i, "total": len(docs), "file": titles.get(doc, ""), "phase": "reading"}
            try:
                r = ownership.move_now(ws, doc, force=force)
            except Exception as e:  # noqa: BLE001 - one document's fault does not stop the others; nothing changed
                traceback.print_exc()
                r = {"doc": doc, "title": titles.get(doc, ""), "moved": False, "reason": f"It could not be read again ({e})."}
            (moved if r["moved"] else kept).append({"doc_id": doc, "title": r.get("title") or "",
                                                    "reason": r.get("reason"), "not_placed": r.get("not_placed", 0)})
        stats = {"moved": moved, "kept": kept, "stopped": job.cancel.is_set(), "owner": True}
        if moved:
            s = app.settings()
            emb = home.make_embedder(s)
            if emb is not None and not job.cancel.is_set():
                job.progress = {"done": 0, "total": 0, "file": "", "phase": "embedding"}
                try:
                    stats["semantic_index"] = embed.build(ws, emb, progress=lambda d, n: job.progress.update(
                        done=d, total=n), should_stop=job.cancel.is_set)
                except BackendError as e:
                    stats["semantic_index_error"] = str(e)
            if not job.cancel.is_set():
                app._after_adding(ws, job, stats, [m["doc_id"] for m in moved], s)
        return stats

    with ONE_START:  # the look for a job that covers them, then the start, as one step
        docs = [d for d in docs if d not in _covered(app, name)]
        if not docs:
            return None
        n = len(docs)
        job = app.jobs.start(JOB, f"Reading {n} {'document' if n == 1 else 'documents'} with the new reader, as the "
                                  "owner accepted", name, run, uses_model=False, background=not force)
        job.owner_docs = tuple(docs)
    return job


def start_due(app, name: str) -> Job | None:
    """The new readings the owner accepted that are due in this copy and can be made now (the file is here, no work
    on the document runs: `reread.check`), as one job in the project's queue. Called after a round of the shared
    folder, a zip brought in, and the owner's own acceptance."""
    from .. import reread

    ws = app.ws(name)
    due = [d for d in ownership.moves_due(ws) if reread.check(ws, d).get("ok")]
    return start_moves(app, name, due) if due else None


def after_job(app, job: Job) -> None:
    """When a round of the shared folder ends: the new readings the owner accepted that are due in this copy start
    (`start_due`)."""
    from ..sync import folder

    if job.project is None or job.kind != folder.JOB or job.state != "done":
        return
    try:
        start_due(app, job.project)
    except Exception:  # noqa: BLE001 - never the round's fault
        traceback.print_exc()


def _guard(fn, *args):
    try:
        return fn(*args)
    except NotImplementedError as e:  # roles (DESIGN-roles §7): a rule of another piece not built in this tree yet
        raise ApiError(501, f"Not built yet: {e}") from e
    except ownership.NotAllowed as e:
        raise ApiError(403, str(e)) from e
    except KeyError:
        raise ApiError(404, "No such proposal, person, question or document in this project.") from None
    except ValueError as e:
        raise ApiError(409, str(e)) from e


class OwnerApi:
    def _owner_view(self, name: str) -> dict:
        ws = self.app.ws(name)
        out = ownership.view(ws)
        job = next((j for j in self.app.jobs.all() if j.kind == JOB and j.project == name
                    and j.state in ("queued", "running")), None)
        out["job"] = job.view() if job else None
        return out

    def get_owner(self, name, q):
        """Who the owner is, the proposals and what waits to be applied here (`ownership.view`). What this copy's
        person changed since the last look is written down as proposals first (nothing else changes), so the Team tab
        shows a change as a proposal as soon as it is made. That look never waits for other work that holds the
        project's database (a document read again, a merge): it is then written at the next look or round."""
        ownership.settle(self.app.ws(name), apply=False, wait=False)
        return self._owner_view(name)

    def post_owner_claim(self, name, q):
        self._body()
        _guard(ownership.claim, self.app.ws(name))
        return self._owner_view(name)

    def post_owner_hand_over(self, name, q):
        """{"to": a colleague's person id, "why"?}: only the owner; the colleague must be one the project knows."""
        from .. import people

        body = self._body()
        to = body.get("to")
        if not isinstance(to, str) or not to:
            raise ApiError(400, "Say whom to hand the project over to: {\"to\": a colleague's id}.")
        if to == people.me():
            raise ApiError(400, "Choose a colleague to hand the project over to, not yourself.")
        _guard(ownership.hand_over, self.app.ws(name), to, str(body.get("why") or "") or None)
        return self._owner_view(name)

    def post_owner_take_over(self, name, q):
        body = self._body()
        _guard(ownership.take_over, self.app.ws(name), str(body.get("why") or "") or None)
        return self._owner_view(name)

    def put_owner_settings(self, name, q):
        """The owner's setting: {"accept_adds": bool}. Turned on, what waits is accepted now."""
        body = self._body()
        if not isinstance(body.get("accept_adds"), bool):
            raise ApiError(400, "Send {\"accept_adds\": true} or {\"accept_adds\": false}.")
        ws = self.app.ws(name)
        _guard(ownership.set_accept_adds, ws, body["accept_adds"])
        if body["accept_adds"]:
            ownership.settle(ws)  # what waits is accepted now
        return self._owner_view(name)

    def post_proposal_accept(self, name, pid, q):
        body = self._body()
        _guard(ownership.accept, self.app.ws(name), pid, str(body.get("reason") or "") or None)
        start_due(self.app, name)  # a new reading accepted: made here too, in the queue
        return self._owner_view(name)

    def post_proposal_decline(self, name, pid, q):
        body = self._body()
        _guard(ownership.decline, self.app.ws(name), pid, str(body.get("reason") or "") or None)
        return self._owner_view(name)

    def post_proposal_take_back(self, name, pid, q):
        self._body()
        _guard(ownership.take_back, self.app.ws(name), pid)
        return self._owner_view(name)

    def post_owner_apply(self, name, q):
        """Make a new reading the owner accepted in this copy now: {"doc", "force"?}. With `force`, results that find
        no place in the new reading are kept as records (the person's own word); without, the document moves only
        when every result finds its place."""
        body = self._body()
        ws = self.app.ws(name)
        doc = body.get("doc")
        if not isinstance(doc, str) or not doc:
            raise ApiError(400, "Say which document: {\"doc\": its id}.")
        if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,)):
            raise ApiError(404, "No such document.")
        if not ownership.behind(ws, doc):
            raise ApiError(409, "This document is read here as the project reads it already: there is nothing to do.")
        job = start_moves(self.app, name, [doc], force=bool(body.get("force")))
        if job is None:  # a move of it waits or runs already: that one
            job = next((j for j in self.app.jobs.all() if j.kind == JOB and j.project == name
                        and j.state in ("queued", "running") and doc in getattr(j, "owner_docs", ())), None)
        return {**self._owner_view(name), "job": job.view() if job else None}

    # -----------------------------------------------------------------------------------------
    # roles (DESIGN-roles §5, §7 P4): the Owner sets roles, this copy answers questions, offers and refused rows
    # -----------------------------------------------------------------------------------------
    def put_owner_role(self, name, person, q):
        """{"role": "co" | "member"} and/or {"same_as": a person id | null}: the Owner's copy only (403 otherwise)."""
        from .. import people

        body = self._body()
        if "role" not in body and "same_as" not in body:
            raise ApiError(400, "Send {\"role\": \"co\" | \"member\"} or {\"same_as\": a person id or null}.")
        if person == people.me():
            raise ApiError(400, "Your own role is the owner's: hand the project over to change it.")
        ws = self.app.ws(name)
        if "role" in body:
            if body["role"] not in ("co", "member"):
                raise ApiError(400, "A role is \"co\" (Co-owner) or \"member\" (Member).")
            _guard(ownership.set_role, ws, person, body["role"])
        if "same_as" in body:
            other = body["same_as"]
            if other is not None and (not isinstance(other, str) or not other or other == person):
                raise ApiError(400, "Say who else this person is: {\"same_as\": another person's id}, or null.")
            _guard(ownership.set_same_as, ws, person, other)
        return self._owner_view(name)

    def post_owner_question(self, name, qid, q):
        """{"answer": "follow" | "keep" | "later"}: follow the owner record a question is about, keep the one followed,
        or put the question off (*Not now*, 0.18.1: kept for the person in the project, so in every browser)."""
        body = self._body()
        answer = body.get("answer")
        if answer not in ("follow", "keep", "later"):
            raise ApiError(400, "Send {\"answer\": \"follow\"}, {\"answer\": \"keep\"} or {\"answer\": \"later\"}.")
        ws = self.app.ws(name)
        found = next((x for x in _guard(ownership.owner_questions, ws._conn()) if x.get("id") == qid), None)
        if found is None:
            raise ApiError(404, "This question is not asked any more.")
        if answer == "later":
            _guard(ownership.put_off, ws, qid)
            return self._owner_view(name)
        _guard(ownership.follow_owner if answer == "follow" else ownership.keep_owner, ws, found["seq"], found["by"])
        start_due(self.app, name)  # following another owner may make new readings due here
        return self._owner_view(name)

    def post_owner_loosening(self, name, q):
        """{"docs": [doc ids] | null (all offered), "allow": bool}: a looser AI setting a file offers here."""
        body = self._body()
        docs, allow = body.get("docs"), body.get("allow")
        if not isinstance(allow, bool):
            raise ApiError(400, "Send {\"allow\": true} or {\"allow\": false}, with \"docs\".")
        if docs is not None and (not isinstance(docs, list) or not docs or not all(isinstance(d, str) and d for d in docs)):
            raise ApiError(400, "Say which documents: {\"docs\": [their ids]}, or null for all that are offered.")
        _guard(ownership.answer_loosening, self.app.ws(name), docs, allow)
        return self._owner_view(name)

    def post_owner_restore(self, name, doc, q):
        """Bring back a document removed in the last 30 days (`removed.restore`). In a Member's copy it is then
        proposed to the owner again (the next look writes it down)."""
        from .. import removed

        ws = self.app.ws(name)
        title = next((r.get("title") for r in _guard(removed.listing, ws) if r.get("doc") == doc), None)
        if not _guard(removed.restore, ws, doc):
            raise ApiError(404, "There is nothing to restore of this document: its 30 days are over, or it is back.")
        ownership.settle(ws, apply=False, wait=False)
        out = self._owner_view(name)
        out["restored"] = {"doc": doc, "title": title, "proposed": not out.get("can_write", True)}
        return out

    def post_owner_clash(self, name, cid, q):
        """"Leave it so": write the part again as it is, knowing both changes, so the clash ends in every copy."""
        self._body()
        _guard(ownership.decide_again, self.app.ws(name), cid)
        return self._owner_view(name)

    def post_owner_take_back(self, name, q):
        """A file said this person handed the project over, and they did not: take it back (§4.10)."""
        self._body()
        _guard(ownership.take_project_back, self.app.ws(name))
        return self._owner_view(name)

    def post_owner_refused_dismiss(self, name, kind, key, q):
        self._body()
        _guard(ownership.dismiss_refused, self.app.ws(name), kind, key)
        return self._owner_view(name)

    # H8: a colleague's renames and merges of a codebook they did not make wait before they move this person's labels
    def get_codebook_offer(self, name, cb, q):
        return {"offer": _offer(self.app.ws(name), cb)}

    def post_codebook_follow(self, name, cb, q):
        """{"follow": bool}: Follow (move this person's labels as the colleague did) or Keep mine."""
        from .. import codebooks

        body = self._body()
        if not isinstance(body.get("follow"), bool):
            raise ApiError(400, "Send {\"follow\": true} or {\"follow\": false}.")
        ws = self.app.ws(name)
        if _offer(ws, cb) is None:
            raise ApiError(409, "Nothing of this codebook waits for your word any more.")
        _guard(codebooks.answer_offer, ws, cb, body["follow"])
        return {"codebook": codebooks.load(ws, cb), "offer": _offer(ws, cb)}


def _offer(ws, cb: str) -> dict | None:
    """The offer of codebook `cb` (`codebooks.offers`), or None; None too while that rule is not built in this tree."""
    from .. import codebooks

    try:
        return next((o for o in codebooks.offers(ws) if o.get("name") == cb), None)
    except NotImplementedError:
        return None
