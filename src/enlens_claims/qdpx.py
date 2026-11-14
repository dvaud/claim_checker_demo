"""A project for NVivo, ATLAS.ti and MAXQDA (0.18.7, roadmap G5): the REFI-QDA exchange formats. No AI (Level 0).

    enlens --ws X export-qdpx out.qdpx [--framework NAME]
    enlens --ws X export-qdc NAME out.qdc

**`.qdpx`** (REFI-QDA *Project Exchange* 1.0, namespace `urn:QDA-XML:project:1.0`) is a zip of `project.qde` (the
project as XML) and `sources/<guid>.txt`, the plain text of each document (UTF-8). **`.qdc`** (*Codebook Exchange*
1.0, `urn:QDA-XML:codebook:1.0`) is one codebook alone, as XML.

What goes in, and the choices made:

- **Documents** (`<TextSource>`): every document of the project, as the whole-project zip (bundle.py) takes them: a
  document no AI may read (*No AI*) is still the person's own and goes too, and so do theory documents and those
  marked Non-scientific (their role and mark are written in the source's description). A document removed from the
  project is gone from the database and so from the file. The text is the document's passages joined in order,
  without those of blocks left out (section `left_out`: running heads, page numbers, a cover, front matter, and every
  block a person left out), as they stay out of everything ENLENS reads; the reference list (section `references`)
  stays, as part of the document. Between two passages stands the white space the document had there, or a blank
  line where a left-out block stood. Offsets are characters (Unicode code points) into that text. A document without passages
  (not read yet) goes as its whole text.
- **Codes** (`<CodeBook>`): one parent code per codebook ("<title> (codebook)"), its groups as parent codes under it
  and its codes under them; a code's description holds its definition, when to use it and when not, its keywords and
  its example quotes. The codebooks are those with labels in the project and the project's own codebooks (or only
  the one asked for). Then a parent code *Hypotheses (ENLENS)*, one code per hypothesis checked (its words, answer
  and your notes in the description) and under each three codes, *Supports*, *Partly supports* and *Contradicts*.
  A code's GUID comes from its codebook and its stable id (codebooks.py), so the `.qdc` and the `.qdpx` of a codebook
  give its codes the same GUIDs, and two exports of the same project give the same GUIDs throughout (uuid5).
- **Codings** (`<PlainTextSelection>` with one `<Coding>`): the labels that count, as the Profile page counts them
  (`profile.effective`: a person's decision overrides the AI's, a rejected label is gone, the keyword pass's strong
  candidates count until the AI has read the passage), each on its quote when it has one, else on its whole passage;
  and the judgements of a check's excerpts that count in its answer (`counted`: at the strictness in Settings, or the
  project's on the command line; a person's always; a Non-scientific document's never), on the hypothesis's *Supports*, *Partly supports* or
  *Contradicts*, each on its quote, else on its whole excerpt. Excerpts judged not about the hypothesis, and labels
  of codes taken out of a codebook, do not go.
- **Who coded it** (`<Users>`): a label or a judgement the AI made is coded by "ENLENS AI (<model>)", one of the
  keyword pass by "ENLENS keyword pass (no AI)"; a person's own label, a label a person agreed with or changed, and a
  person's judgement are that person's (your name from Settings, else "ENLENS user"; a colleague by their name), so
  the researcher sees in NVivo whose decision each coding is. A label stores no person: the person of its last
  decision is taken (`reviews.person_id`), and a person's own label without one is this computer's person's. The
  judgement's person is the one whose judgement is in force (yours first, as `people.refresh` chooses).
- **Memos** (`<Notes>`): every note and highlight (F2) as a memo, tied by a `<NoteRef>` to a selection of its exact
  words (to the document itself when its words cannot be placed: they stood in a block left out, or are lost); your
  notes on a hypothesis as a memo on its code; and the research log (F4) as one memo of the project.

Everything is the person's own work, private items too (as the whole-project zip): the file is for their own
analysis in another program, not for a colleague. Nothing leaves the computer.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import uuid
import zipfile
import xml.etree.ElementTree as ET
from bisect import bisect_right
from pathlib import Path
from . import __version__
from .store import Workspace, now

NS = "urn:QDA-XML:project:1.0"
NS_CODEBOOK = "urn:QDA-XML:codebook:1.0"
# the namespace of every ENLENS GUID (uuid5): fixed, so the same item gets the same GUID in every export
_ROOT = uuid.UUID("6a1f3c52-9d0e-5b7a-8c41-e2d5f0a7b913")
VERDICT_CODES = (("supports", "Supports", "#2E7D32"), ("partially_supports", "Partly supports", "#F9A825"),
                 ("refutes", "Contradicts", "#C62828"))
KEYWORD_USER = "ENLENS keyword pass (no AI)"
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_NUMERIC = re.compile(r"^[\d.\-_ ]+[a-z]?$", re.I)


def guid(*parts: str) -> str:
    return str(uuid.uuid5(_ROOT, "\x1f".join(str(p) for p in parts)))


def _x(s: str | None) -> str:
    """Text as XML 1.0 can hold it (control characters it forbids become spaces)."""
    return _BAD_XML.sub(" ", s or "")


def _stamp(at: str | None) -> str | None:
    """An xsd:dateTime from ENLENS's ISO times ('…+00:00'), or None."""
    if not at:
        return None
    at = str(at).strip()
    return at if re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)?$", at) else None


def _el(parent: ET.Element | None, tag: str, attrs: dict | None = None, text: str | None = None) -> ET.Element:
    a = {k: _x(str(v)) for k, v in (attrs or {}).items() if v is not None}   # PDF text holds control characters
    e = ET.Element(tag, a) if parent is None else ET.SubElement(parent, tag, a)
    if text is not None:
        e.text = _x(text)
    return e


def _short(s: str, n: int = 80) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


# ---------------------------------------------------------------------------------------------
# a document's plain text: its passages joined, and where each document offset lands in it
# ---------------------------------------------------------------------------------------------
class SourceText:
    """The plain text of one document (its passages joined in order) and the map from document offsets to it."""

    def __init__(self, doc_text: str, passages: list[tuple[int, int]], whole: bool = False):
        doc_text = doc_text or ""
        segs: list[tuple[int, int, int]] = []    # (doc start, doc end, start in the joined text)
        parts: list[str] = []
        pos, prev_end = 0, None
        for s, e in sorted(passages):
            s, e = max(0, int(s)), min(len(doc_text), int(e))
            if prev_end is not None:
                s = max(s, prev_end)      # passages never overlap; if they did, the overlap is taken once
            if e <= s:
                continue
            if prev_end is not None:
                gap = doc_text[prev_end:s]
                sep = gap if not gap.strip() else "\n\n"   # a passage cut mid-word joins its neighbour again
                parts.append(sep)
                pos += len(sep)
            segs.append((s, e, pos))
            parts.append(doc_text[s:e])
            pos += e - s
            prev_end = e
        if whole and not segs and doc_text:          # not read into passages yet: the whole text
            segs, parts = [(0, len(doc_text), 0)], [doc_text]
        self.text = "".join(parts)
        self._segs = segs
        self._starts = [s for s, _e, _p in segs]

    def span(self, start: int | None, end: int | None) -> tuple[int, int] | None:
        """Document offsets [start, end) as offsets into the joined text, cut to the passages they fall in; None when
        nothing of the span is in a passage (it stood in a block left out)."""
        if start is None or end is None or end <= start or not self._segs:
            return None
        i = bisect_right(self._starts, start) - 1
        if i < 0 or start >= self._segs[i][1]:   # in a gap: from the next passage on
            i += 1
        if i >= len(self._segs) or self._segs[i][0] >= end:
            return None
        ds, de, p = self._segs[i]
        a = p + max(start, ds) - ds
        j = bisect_right(self._starts, end - 1) - 1
        ds2, de2, p2 = self._segs[j]
        b = p2 + min(end, de2) - ds2
        return (a, b) if b > a else None


# ---------------------------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------------------------
class _Users:
    def __init__(self, ws: Workspace):
        from . import people

        self.me = people.me()
        self.my_name = people.my_name() or "ENLENS user"
        self.names = {r["person_id"]: (r["name"] or "a colleague") for r in ws.query("SELECT person_id, name FROM people")}
        self.used: dict[str, str] = {}   # guid -> name

    def person(self, person_id: str | None) -> str:
        pid = person_id or self.me
        name = self.my_name if pid == self.me else self.names.get(pid) or "a colleague"
        g = guid("user", "person", pid)
        self.used[g] = name
        return g

    def ai(self, model: str | None) -> str:
        name = f"ENLENS AI ({model or 'model not recorded'})"
        g = guid("user", "ai", model or "")
        self.used[g] = name
        return g

    def keywords(self) -> str:
        g = guid("user", "keywords")
        self.used[g] = KEYWORD_USER
        return g


# ---------------------------------------------------------------------------------------------
# codes
# ---------------------------------------------------------------------------------------------
def _code_name(code: str, description: str) -> str:
    """A code's name as another program lists it: a code that is only a number (an SDG target, 6.4) takes the start
    of its definition along."""
    if _NUMERIC.match(code or "") and description:
        return _short(f"{code} {description}", 60)
    return code


def _code_description(c) -> str:
    lines = [c.description or ""]
    if c.include:
        lines.append(f"When to use it: {c.include}")
    if c.exclude:
        lines.append(f"When not to use it: {c.exclude}")
    if c.keywords:
        lines.append("Keywords: " + ", ".join(c.keywords))
    for ex in c.examples:
        lines.append(f"Example: “{ex}”")
    return "\n\n".join(x for x in lines if x).strip()


def code_guid(fw, code: str) -> str:
    ids = (fw.meta or {}).get("ids") or {}
    return guid("code", fw.name, ids.get(code) or code)


def _codebook_codes(parent: ET.Element, fw) -> int:
    """The codes of codebook `fw` under `parent`: its groups as parent codes (not codable), its codes under them.
    Returns how many codes were written."""
    n = 0
    groups: dict[str, ET.Element] = {}
    for c in fw.sorted_codes():
        at = parent
        if c.group:
            if c.group not in groups:
                gname = f"{c.group} {c.group_name}".strip() if c.group_name and c.group_name != c.group else c.group
                groups[c.group] = _el(parent, "Code", {"guid": guid("group", fw.name, c.group), "name": _short(gname, 90),
                                                       "isCodable": "false"})
                if c.group_name:
                    _el(groups[c.group], "Description", text=c.group_name)
                n += 1
            at = groups[c.group]
        e = _el(at, "Code", {"guid": code_guid(fw, c.code), "name": _code_name(c.code, c.description), "isCodable": "true"})
        desc = _code_description(c)
        if desc:
            _el(e, "Description", text=desc)
        n += 1
    return n


def codebook_xml(ws: Workspace, framework: str) -> bytes:
    """Codebook `framework` as a REFI-QDA codebook (`.qdc`)."""
    from . import frameworks

    fw = frameworks.get(framework, ws)
    root = _el(None, "CodeBook", {"xmlns": NS_CODEBOOK, "origin": f"ENLENS {__version__}"})
    codes = _el(root, "Codes")
    _codebook_codes(codes, fw)
    return _bytes(root)


def export_codebook(ws: Workspace, framework: str, out_path: str | Path) -> dict:
    """Write codebook `framework` to `out_path` as a `.qdc` file; returns {path, codes}."""
    from . import frameworks

    body = codebook_xml(ws, framework)
    Path(out_path).write_bytes(body)
    return {"path": str(out_path), "codes": len(frameworks.get(framework, ws).codes)}


def _bytes(root: ET.Element) -> bytes:
    ET.indent(root, space=" ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------------------------
# the project
# ---------------------------------------------------------------------------------------------
def _frameworks_to_export(ws: Workspace, framework: str | None) -> list:
    from . import frameworks

    avail = frameworks.available(ws)
    if framework:
        return [frameworks.get(framework, ws)]
    used = {r[0] for r in ws.query("SELECT DISTINCT framework FROM labels")}
    return [fw for name, fw in avail.items() if name in used or fw.source == "project"]


def _label_people(ws: Workspace) -> dict[str, str | None]:
    """{label_id: the person whose decision on it counts} (the last review, a colleague's before yours, as
    profile._decisions orders them)."""
    from .people import review_order

    order, oargs = review_order()
    out: dict[str, str | None] = {}
    for r in ws.query(f"SELECT item_id, person_id FROM reviews WHERE item_kind='label' {order}", oargs):
        out[r["item_id"]] = r["person_id"]
    return out


REL = {"main": "main topic", "mentioned": "mentioned"}
DIR = {"helps": "helps", "hinders": "hinders", "mixed": "mixed", "not_stated": "not stated"}
VERDICT_WORDS = {"supports": "Supports", "partially_supports": "Partly supports", "refutes": "Contradicts"}


class _Builder:
    def __init__(self, ws: Workspace, framework: str | None, threshold: float | None = None):
        self.ws = ws
        self.framework = framework
        self.threshold = threshold
        self.users = _Users(ws)
        self.puid = ws.project_uid()
        self.selections: dict[str, list[ET.Element]] = {}   # doc_id -> its selections (made before the sources)
        self.source_notes: dict[str, list[str]] = {}        # doc_id -> note GUIDs tied to the document itself
        self.notes: list[ET.Element] = []
        self.texts: dict[str, SourceText] = {}
        self.titles: dict[str, str] = {}
        self.docs: list[dict] = []
        self.summary = {"documents": 0, "codes": 0, "codings": 0, "labels": 0, "judgements": 0, "notes": 0,
                        "not_placed": 0}

    def g(self, *parts: str) -> str:
        return guid(self.puid, *parts)

    # -- documents
    def load_documents(self) -> None:
        spans: dict[str, list[tuple[int, int]]] = {}
        has: set[str] = set()
        for r in self.ws.query("SELECT doc_id, start, end, section FROM passages ORDER BY doc_id, seq"):
            has.add(r["doc_id"])
            # a passage of blocks left out (by the reader or by the person) keeps its text in ENLENS, unread
            if r["start"] is not None and r["end"] is not None and r["section"] != "left_out":
                spans.setdefault(r["doc_id"], []).append((r["start"], r["end"]))
        cols = {r[1] for r in self.ws.query("PRAGMA table_info(documents)")}
        extra = ", ".join(c for c in ("role", "nonscientific", "ai_access", "file_title") if c in cols)
        rows = self.ws.query(f"SELECT doc_id, title, path, doi, added_at, text{', ' + extra if extra else ''} "
                             "FROM documents")
        for r in sorted(rows, key=lambda r: ((r["title"] or "").lower(), r["doc_id"])):
            d = dict(r)
            self.texts[d["doc_id"]] = SourceText(d.get("text") or "", spans.get(d["doc_id"], []),
                                                 whole=d["doc_id"] not in has)
            self.titles[d["doc_id"]] = d["title"] or Path(d["path"] or "").name or d["doc_id"]
            d.pop("text", None)   # kept once, joined, in self.texts
            self.docs.append(d)

    def select(self, doc_id: str, key: tuple, start: int | None, end: int | None, user: str, at: str | None,
               code_guid_: str | None = None, description: str | None = None,
               note_guid: str | None = None) -> bool:
        """A selection of document offsets [start, end) of `doc_id`, coded with `code_guid_` and/or carrying a memo;
        False when its words are in no passage."""
        st = self.texts.get(doc_id)
        sp = st.span(start, end) if st else None
        if sp is None:
            return False
        attrs = {"guid": self.g("selection", *key), "name": _short(st.text[sp[0]:sp[1]], 60),
                 "startPosition": sp[0], "endPosition": sp[1], "creatingUser": user, "creationDateTime": _stamp(at)}
        sel = _el(None, "PlainTextSelection", attrs)
        if description:
            _el(sel, "Description", text=description)
        if code_guid_:
            c = _el(sel, "Coding", {"guid": self.g("coding", *key), "creatingUser": user,
                                    "creationDateTime": _stamp(at)})
            _el(c, "CodeRef", {"targetGUID": code_guid_})
            self.summary["codings"] += 1
        if note_guid:
            _el(sel, "NoteRef", {"targetGUID": note_guid})
        self.selections.setdefault(doc_id, []).append(sel)
        return True

    # -- codebooks and labels
    def codebooks(self, codes: ET.Element) -> None:
        from . import codebooks, profile

        who = _label_people(self.ws)
        for fw in _frameworks_to_export(self.ws, self.framework):
            try:
                codebooks.follow(self.ws, fw.name)   # labels follow the codebook's renames, as the Profile page does
            except Exception:  # noqa: BLE001 (a codebook that cannot be followed still exports as it is)
                pass
            top = _el(codes, "Code", {"guid": guid("codebook", fw.name), "name": f"{fw.title or fw.name} (codebook)",
                                      "isCodable": "false"})
            _el(top, "Description", text=f"ENLENS codebook “{fw.name}”: each code is called “{fw.label}”.")
            self.summary["codes"] += 1 + _codebook_codes(top, fw)
            for r in profile.effective(self.ws, fw.name):
                if r["doc_id"] not in self.texts or r["code"] not in fw.codes:
                    continue
                by_person = r["source"] == "person" or r.get("decision") in ("accept", "change")
                if by_person:
                    user = self.users.person(who.get(r["label_id"]))
                elif r["source"] == "model":
                    user = self.users.ai(r["model"])
                else:
                    user = self.users.keywords()
                lines = [f"Code: {r['code']}"]
                if r.get("relevance"):
                    lines.append(f"Relevance: {REL.get(r['relevance'], r['relevance'])}")
                if fw.directional and r.get("direction"):
                    lines.append(f"Direction: {DIR.get(r['direction'], r['direction'])}")
                src = {"model": f"the AI ({r['model'] or 'model not recorded'})", "person": "you",
                       "keywords": "keywords (no AI)", "meaning": "meaning (no AI)",
                       "both": "keywords and meaning agree (no AI)"}.get(r["source"], r["source"])
                lines.append(f"Labelled by: {src}" + (" (provisional: the AI has not read this passage yet)"
                                                       if r.get("provisional") else ""))
                if r.get("decision") in ("accept", "change"):
                    lines.append("Your decision: " + ("agreed" if r["decision"] == "accept" else "changed"))
                if r.get("reason") and r["source"] != "person":
                    lines.append(f"Reason: {r['reason']}")
                if r.get("person_note"):
                    lines.append(f"Your note: {r['person_note']}")
                start, end = (r["start"], r["end"]) if r.get("quote") and r.get("start") is not None else (None, None)
                if start is None:
                    p = self.ws.query("SELECT start, end FROM passages WHERE passage_id=?", (r["passage_id"],))
                    start, end = (p[0]["start"], p[0]["end"]) if p else (None, None)
                if self.select(r["doc_id"], ("label", r["label_id"]), start, end, user, r.get("created_at"),
                               code_guid(fw, r["code"]), "\n".join(lines)):
                    self.summary["labels"] += 1
                else:
                    self.summary["not_placed"] += 1

    # -- hypotheses and their judgements
    def hypotheses(self, codes: ET.Element) -> None:
        from .check_results import hypothesis_result
        from .claimcheck import history
        from .verdicts import GRADES

        hs = list(reversed(history(self.ws, self.threshold)))   # oldest first
        if not hs:
            return
        top = _el(codes, "Code", {"guid": self.g("hypotheses"), "name": "Hypotheses (ENLENS)", "isCodable": "false"})
        _el(top, "Description", text="Each hypothesis checked in ENLENS, with the excerpts whose judgement counts in "
                                     "its answer coded as Supports, Partly supports or Contradicts.")
        self.summary["codes"] += 1
        for h in hs:
            hid = h["hyp_id"]
            res = hypothesis_result(self.ws, hid, self.threshold)
            hc = _el(top, "Code", {"guid": self.g("hypothesis", hid), "name": _short(res["text"], 90),
                                   "isCodable": "false"})
            desc = [res["text"], f"Answer: {res.get('status_text') or res.get('status') or ''}",
                    f"Checked on {(res.get('created_at') or '')[:10]}"]
            _el(hc, "Description", text="\n\n".join(x for x in desc if x))
            if (res.get("note") or "").strip():   # CodeType: Description, NoteRef*, Code* (in this order)
                ng = self.g("hypothesis-note", hid)
                self._note(ng, f"Your notes on: {_short(res['text'], 60)}", res["note"], self.users.person(None),
                           res.get("created_at"))
                _el(hc, "NoteRef", {"targetGUID": ng})
            verdict_code = {}
            for v, word, colour in VERDICT_CODES:
                verdict_code[v] = self.g("hypothesis", hid, v)
                _el(hc, "Code", {"guid": verdict_code[v], "name": word, "isCodable": "true", "color": colour})
            self.summary["codes"] += 1 + len(VERDICT_CODES)
            n_parts = len(res["parts"])
            for part in res["parts"]:
                models = {r["passage_id"]: r["model"] for r in self.ws.query(
                    "SELECT passage_id, model FROM verifications WHERE subject_id=? ORDER BY rowid", (part["claim_id"],))}
                for x in part["passages"]:
                    if not x.get("counted") or x.get("verdict") not in GRADES or x["doc_id"] not in self.texts:
                        continue
                    if x.get("user_verdict"):
                        user = self.users.person(self._judge_of(part["claim_id"], x["passage_id"], x["user_verdict"]))
                        by = "you" if x.get("judged_by") in (None, "you") else x["judged_by"]
                    else:
                        model = models.get(x["passage_id"]) or part.get("model") or res.get("model")
                        user, by = self.users.ai(model), f"the AI ({model})"
                    if x.get("not_placed") or x.get("in_corpus") is False or x.get("doc_start") is None:
                        self.summary["not_placed"] += 1   # read before the document was read again: no place now
                        continue
                    base = x["doc_start"]
                    if x.get("quote") and x.get("quote_start") is not None and x.get("quote_end") is not None:
                        start, end = base + x["quote_start"], base + x["quote_end"]
                    else:
                        start, end = base, base + len(x.get("text") or "")
                    lines = [f"{VERDICT_WORDS[x['verdict']]}, judged by {by}"]
                    if x.get("certainty") and not x.get("user_verdict"):
                        lines[0] += f" (certainty {x['certainty']})"
                    if n_parts > 1:
                        lines.append(f"Part {part['part'] + 1} of {n_parts}: {part['claim']}")
                    if x.get("user_note"):
                        lines.append(f"Your comment: {x['user_note']}")
                    if self.select(x["doc_id"], ("judgement", part["claim_id"], x["passage_id"]), start, end, user,
                                   res.get("created_at"), verdict_code[x["verdict"]], "\n".join(lines)):
                        self.summary["judgements"] += 1
                    else:
                        self.summary["not_placed"] += 1

    def _judge_of(self, claim_id: str, passage_id: str, verdict: str) -> str | None:
        rows = self.ws.query("SELECT person_id FROM judgements WHERE claim_id=? AND passage_id=? AND verdict=?",
                             (claim_id, passage_id, verdict))
        ids = [r[0] for r in rows]
        return self.users.me if self.users.me in ids or not ids else ids[0]

    # -- memos
    def _note(self, g: str, name: str, text: str, user: str, at: str | None) -> None:
        n = _el(None, "Note", {"guid": g, "name": _short(name, 90), "creatingUser": user, "creationDateTime": _stamp(at)})
        _el(n, "PlainTextContent", text=text)
        self.notes.append(n)
        self.summary["notes"] += 1

    def doc_notes(self) -> None:
        from . import notes

        for d in self.docs:
            for nt in notes.for_document(self.ws, d["doc_id"]):
                g = self.g("note", nt["note_id"])
                body = (nt.get("text") or "").strip()
                quote = nt.get("quote") or ""
                name = _short(body, 60) if body else f"Highlight: {_short(quote, 50)}"
                content = (body + "\n\n" if body else "") + f"“{quote}” ({self.titles[d['doc_id']]})"
                user = self.users.person(nt.get("person_id"))
                self._note(g, name, content, user, nt.get("created_at"))
                placed = not nt.get("lost") and self.select(d["doc_id"], ("note", nt["note_id"]), nt["start"],
                                                            nt["end"], user, nt.get("created_at"), note_guid=g)
                if not placed:
                    self.source_notes.setdefault(d["doc_id"], []).append(g)

    def log_note(self) -> None:
        from . import researchlog

        if not self.ws.scalar("SELECT COUNT(*) FROM research_log"):
            return
        self._note(self.g("research-log"), "Research log (ENLENS)", researchlog.markdown(self.ws, self.ws.root.name),
                   self.users.person(None), now())

    # -- the XML
    def build(self) -> tuple[ET.Element, dict[str, str]]:
        """The project element and {file name in sources/: its text}."""
        self.load_documents()
        codes_holder = ET.Element("Codes")
        self.codebooks(codes_holder)
        self.hypotheses(codes_holder)
        self.doc_notes()
        self.log_note()
        me = self.users.person(None)
        root = _el(None, "Project", {"xmlns": NS, "name": self.ws.root.name, "origin": f"ENLENS {__version__}",
                                     "creatingUserGUID": me, "creationDateTime": now()})
        users = _el(root, "Users")
        for g, name in sorted(self.users.used.items(), key=lambda kv: kv[1].lower()):
            _el(users, "User", {"guid": g, "name": name})
        if len(codes_holder):
            cb = _el(root, "CodeBook")
            cb.append(codes_holder)
        files: dict[str, str] = {}
        if self.docs:
            sources = _el(root, "Sources")
            names: set[str] = set()
            for d in self.docs:
                did = d["doc_id"]
                g = self.g("source", did)
                name, i = self.titles[did], 2
                while name.lower() in names:
                    name, i = f"{self.titles[did]} ({i})", i + 1
                names.add(name.lower())
                src = _el(sources, "TextSource", {"guid": g, "name": name, "plainTextPath": f"internal://{g}.txt",
                                                  "creatingUser": me, "creationDateTime": _stamp(d.get("added_at"))})
                desc = [f"ENLENS document {did}"]
                if d.get("doi"):
                    desc.append(f"DOI: {d['doi']}")
                if d.get("role") == "theory":
                    desc.append("Theory document: the framework the research is read through, not evidence.")
                if d.get("nonscientific"):
                    desc.append("Non-scientific: read and judged, never counted in an answer.")
                if d.get("ai_access") == "none":
                    desc.append("No AI reads this document.")
                elif d.get("ai_access") == "local":
                    desc.append("Only a local AI reads this document.")
                _el(src, "Description", text="\n".join(desc))
                sels = sorted(self.selections.get(did, []),
                              key=lambda s: (int(s.get("startPosition")), int(s.get("endPosition")), s.get("guid")))
                for s in sels:
                    src.append(s)
                for ng in self.source_notes.get(did, []):
                    _el(src, "NoteRef", {"targetGUID": ng})
                files[f"{g}.txt"] = self.texts[did].text
                self.summary["documents"] += 1
        if self.notes:
            notes_el = _el(root, "Notes")
            for n in self.notes:
                notes_el.append(n)
        return root, files


def export_project(ws: Workspace, out_path: str | Path, framework: str | None = None,
                   threshold: float | None = None) -> dict:
    """Write the project to `out_path` as a REFI-QDA project (`.qdpx`): see the module's docstring for what goes in.
    `framework`: only that codebook (else every codebook with labels and the project's own); `threshold`: the
    strictness a judgement counts at (else the project's, as every check export). Returns what it holds:
    {path, documents, codes, codings, labels, judgements, notes, users, not_placed}."""
    b = _Builder(ws, framework, threshold)
    root, files = b.build()
    out = Path(out_path)
    tmp = Path(tempfile.mkdtemp(prefix="enlens-qdpx-"))
    try:
        part = tmp / "project.qdpx"
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.qde", _bytes(root))
            for name, text in sorted(files.items()):
                zf.writestr(f"sources/{name}", text.encode("utf-8"))
        shutil.move(str(part), str(out))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"path": str(out), **b.summary, "users": len(b.users.used)}


__all__ = ["export_project", "export_codebook", "codebook_xml", "SourceText", "guid", "NS", "NS_CODEBOOK"]
