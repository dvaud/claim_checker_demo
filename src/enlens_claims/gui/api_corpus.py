"""0.18.1 part A (documents, theory documents, concepts and team copies): the endpoints of Handler that
part adds, kept out of server.py so the two parts of 0.18.1, built side by side, never edit the same lines.


`Handler` takes this class as a base, so the names in ROUTES resolve on it. server.py adds ROUTES after its own
(the first pattern that matches wins), DOWNLOADS to the routes that may take the token as ?token=, and NOT_A_CHANGE to
the changes after which the shared folder's poller does not bring a round forward."""
from __future__ import annotations

from .api_common import ApiError, _str

P = r"([^/]+)"  # one path segment, as in server.py

# (method, pattern without ^ and $, handler name), e.g. ("GET", rf"/api/projects/{P}/…", "get_…")
ROUTES: list[tuple[str, str, str]] = [
    # K2 part 1: a document's role (theory or evidence; docrole.py)
    ("GET", rf"/api/projects/{P}/document-roles", "get_document_roles"),
    ("GET", rf"/api/projects/{P}/documents/{P}/role", "get_document_role"),
    ("PUT", rf"/api/projects/{P}/documents/{P}/role", "put_document_role"),
    # K2 part 2: a codebook from a theory document (theorycodes.py)
    ("GET", rf"/api/projects/{P}/codebook-theory", "get_codebook_theory_docs"),
    ("GET", rf"/api/projects/{P}/codebook-theory/{P}", "get_codebook_theory"),
    # D3 and D4: paths between two concepts, a concept over time and across groups (conceptpaths.py)
    ("GET", rf"/api/projects/{P}/concept-paths", "get_concept_paths"),
    ("GET", rf"/api/projects/{P}/concept-time/{P}", "get_concept_time"),
    ("POST", rf"/api/projects/{P}/concept-groups/{P}", "post_concept_groups"),
    # A7 (reader 5): a figure's picture, drawn from the original PDF when it is shown, never stored
    ("GET", rf"/api/projects/{P}/documents/{P}/figures/{P}\.png", "get_figure_image"),
]
DOWNLOADS: set[str] = {"get_figure_image"}  # A7: in an <img>, as get_page_image is
NOT_A_CHANGE: set[str] = set()


class CorpusApi:
    # ---- K2 part 1: a document's role ---------------------------------------------------------------------------
    def get_document_roles(self, name, q):
        """{"roles": {doc id: "theory"}}: the documents with a role other than evidence, for the Documents list."""
        ws = self.app.ws(name)
        return {"roles": {r[0]: r[1] for r in ws.query("SELECT doc_id, role FROM documents WHERE role IS NOT NULL")}}

    def get_document_role(self, name, doc_id, q):
        """{"doc_id", "role" (null: evidence), "impact": what was made with it in (docrole.impact)}."""
        from .. import docrole

        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)):
            raise ApiError(404, "No such document in this project.")
        return {"doc_id": doc_id, "role": docrole.role_of(ws, doc_id), "impact": docrole.impact(ws, doc_id)}

    def put_document_role(self, name, doc_id, q):
        """{"role": "theory" | null, "why"?}: mark a document as theory, or as evidence again. Under an owner, a
        Member's mark is a proposal (the Team tab's next look writes it), as *Leave out* is."""
        from .. import docrole

        body = self._body()
        role = body.get("role")
        if role is not None and role not in docrole.ROLES:
            raise ApiError(400, "A document's role is \"theory\", or null (evidence).")
        why = body.get("why")
        try:
            return docrole.set_role(self.app.ws(name), doc_id, role, str(why).strip() or None if why else None)
        except KeyError:
            raise ApiError(404, "No such document in this project.") from None

    # ---- K2 part 2: a codebook from a theory document -------------------------------------------------------------
    def get_codebook_theory_docs(self, name, q):
        """{"documents": [{"doc_id", "title", "theory"}]}: the documents a codebook can start from, theory first."""
        ws = self.app.ws(name)
        rows = ws.query("SELECT doc_id, title, role FROM documents ORDER BY role IS NULL, title")
        return {"documents": [{"doc_id": r["doc_id"], "title": r["title"], "theory": r["role"] == "theory"} for r in rows]}

    # ---- D3 and D4 -----------------------------------------------------------------------------------------------
    def get_concept_paths(self, name, q):
        """?from=<term id>&to=<term id>[&k=3]: the shortest chains between two concepts (conceptpaths.paths)."""
        from .. import conceptpaths

        a, b = _str(q, "from"), _str(q, "to")
        if not a or not b:
            raise ApiError(400, "Say both concepts: ?from=<term id>&to=<term id>.")
        try:
            k = max(1, min(5, int(_str(q, "k") or 3)))
        except ValueError:
            k = 3
        try:
            return conceptpaths.paths(self.app.ws(name), a, b, k)
        except KeyError:
            raise ApiError(404, "No such term in the glossary: make the glossary again.") from None

    def get_concept_time(self, name, term, q):
        """A concept by publication year (conceptpaths.over_time)."""
        from .. import conceptpaths

        try:
            return conceptpaths.over_time(self.app.ws(name), term)
        except KeyError:
            raise ApiError(404, "No such term in the glossary: make the glossary again.") from None

    def post_concept_groups(self, name, term, q):
        """{"groups": {name: [doc ids]}}: a concept in sets of documents picked on the page, not stored."""
        from .. import conceptpaths

        groups = self._body().get("groups")
        if not isinstance(groups, dict) or not all(isinstance(v, list) for v in groups.values()):
            raise ApiError(400, "Send {\"groups\": {name: [document ids]}}.")
        try:
            return conceptpaths.compare_groups(self.app.ws(name), term, {str(k): [str(x) for x in v]
                                                                         for k, v in groups.items()})
        except KeyError:
            raise ApiError(404, "No such term in the glossary: make the glossary again.") from None
        except ValueError as e:
            raise ApiError(400, str(e)) from None

    def get_codebook_theory(self, name, doc_id, q):
        """The candidate concepts of a document, as draft codes with their quoted definitions and the evidence's
        suggested examples (theorycodes.candidates)."""
        from .. import theorycodes

        try:
            return theorycodes.candidates(self.app.ws(name), doc_id)
        except KeyError:
            raise ApiError(404, "No such document in this project.") from None

    # ---- A7 (reader 5): a figure's picture ------------------------------------------------------------------------
    def get_figure_image(self, name, doc_id, n, q):
        """The picture of a block that has a box on its page (a figure; also a table found from its rules): the crop of
        the original PDF's page the reader found (`blocks.x0..y1`, points from the top left), as a PNG. It is drawn
        from the original when asked for, as the *Page* panel's picture is, and nothing of it is stored or sent to an
        AI. `?scale=` (0.5 to 3, default 2)."""
        from pathlib import Path

        from .api_common import _float, page_images_available

        ws = self.app.ws(name)
        try:
            n = int(n)
        except ValueError:
            raise ApiError(404, "No such block in this document.") from None
        rows = ws.query("SELECT page, kind, x0, y0, x1, y1 FROM blocks WHERE doc_id=? AND n=?", (doc_id, n))
        if not rows:
            raise ApiError(404, "No such block in this document.")
        b = rows[0]
        if b["page"] is None or b["x0"] is None or b["kind"] not in ("figure", "table"):
            raise ApiError(404, "This block has no place on a page to draw.")
        info = self.app.original(ws, doc_id)
        if not info["available"] or (info.get("kind") or "") != "pdf":
            raise ApiError(404, info.get("reason") or "The original PDF is not available.")
        if not page_images_available():
            raise ApiError(404, "Pictures of pages need the OCR extra (pypdfium2), which is not installed.")
        png = _render_crop(Path(info["path"]), int(b["page"]), (b["x0"], b["y0"], b["x1"], b["y1"]),
                           min(3.0, max(0.5, _float(q, "scale", 2.0))))
        if png is None:
            raise ApiError(404, "No such page.")
        return self._send(200, png, "image/png", {"Cache-Control": "private, max-age=3600"})


def _render_crop(path, page: int, box: tuple[float, float, float, float], scale: float) -> bytes | None:
    """The box (points from the top left of the page, with a margin of a few points) of a PDF page (1-based) as PNG
    bytes, or None when there is no such page. The whole page is drawn at `scale` and the box cut from it."""
    import io

    import pypdfium2 as pdfium

    from .api_common import _PDFIUM_LOCK

    with _PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            if not 1 <= page <= len(pdf):
                return None
            pg = pdf[page - 1]
            width, height = pg.get_size()
            img = pg.render(scale=scale).to_pil()
        finally:
            pdf.close()
    pad = 4.0
    sx, sy = img.width / max(width, 1.0), img.height / max(height, 1.0)
    left, top = max(0.0, box[0] - pad) * sx, max(0.0, box[1] - pad) * sy
    right, bottom = min(width, box[2] + pad) * sx, min(height, box[3] + pad) * sy
    if right - left < 2 or bottom - top < 2:
        return None
    buf = io.BytesIO()
    img.crop((int(left), int(top), int(right) + 1, int(bottom) + 1)).save(buf, "PNG", optimize=True)
    return buf.getvalue()
