"""A codebook brought in from NVivo, ATLAS.ti or MAXQDA (roadmap K1 "In and out", with G5): a REFI-QDA codebook
(`.qdc`, *Codebook Exchange* 1.0), or the `<CodeBook>` of a REFI-QDA project (`.qdpx`). No AI (Level 0).

    enlens --ws X import-qdc FILE [NAME] [--title T]

The codes become an ordinary codebook made in the editor (`codebooks.create`, start "qdc"): a CSV file and its side
file, so it still opens in a spreadsheet, and sync, the research log and History treat it as any other. What maps to
what, and the choices made:

- **A code at the top with codes under it is a group** (its name the group's). Its codes are the group's codes.
- **Deeper levels are folded into the top group** (ENLENS's groups have one level; NVivo allows any depth): a code
  three or more levels down is a code of its top group, and its place in the tree is kept at the end of its
  definition: "(In the tree: Emotions › Positive › Joy.)".
- **A code with codes under it is also a code itself only when it has a description** (a definition of its own): one
  without is a heading, kept as the group's name or in its codes' place in the tree. This holds for every level.
- **A code that cannot be coded** (`isCodable="false"`) with nothing under it is left out; one with codes under it is
  a group (or, deeper, a step of the tree).
- **A code without a description** gets its place in the tree as its definition ("Emotions › Joy"), or its name when
  it stands at the top: ENLENS needs a definition, and the summary asks for a real one.
- **Names** longer than 40 characters (ENLENS's limit) are cut at a word, and the whole name opens the definition. Two
  codes of the same name (in different branches, say) are told apart: the second becomes "Name (2)".
- **ENLENS's own export comes back** (as far as a `.qdc` carries it): a code's description holds its definition, then "When to use it:",
  "When not to use it:", "Keywords:" and "Example: “…”" paragraphs (qdpx._code_description), which go back to their
  columns; a group written as "<group> <group name>" with the group name as its description gets both back; a code
  that is only a number (an SDG target, "6.4") written with the start of its definition gets its number back. The
  code ids (side file `ids`) are new: a codebook brought in is a new codebook, not the one it was exported from. A
  `.qdc` does not carry an example's document and page (only its words), the codebook's label or its direction
  setting, so those come back empty. Keywords were joined with ", " by ENLENS 0.18.7 and with "; " since (a keyword
  may hold a comma): a later ENLENS file splits them only at semicolons. These readings (numbers, groups, the
  hypotheses' codes, the "(codebook)" wrapper) apply only to files whose origin is ENLENS.
- **Left out**: colours, Sets (ENLENS has no sets: the summary counts them), memos (NoteRef), a non-codable top
  code's own description (a group has only a name; the summary counts these), and, in a `.qdpx`, everything but the
  codebook, and the codes ENLENS writes for its hypotheses ("Hypotheses (ENLENS)"). A `.qdpx` ENLENS wrote holds each
  codebook under a "<title> (codebook)" code: when there is only one, its contents are the codebook and its title the
  codebook's title.

The file is read with the standard library's XML reader, so no new dependency: a DOCTYPE or an ENTITY is refused
before it is parsed (no entity expansion, no outside file), a `.qdc` may be at most 20 MB, a `.qdpx` at most 5,000
members, and only its `project.qde` is read, at most 64 MB once unpacked (a zip bomb stops there).
"""
from __future__ import annotations

import base64
import binascii
import html
import io
import re
import zipfile
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from . import qdpx

MAX_QDC = 20 * 1024 ** 2
MAX_QDE = 64 * 1024 ** 2
MAX_MEMBERS = 5000
MAX_DEPTH = 64
NAME_MAX = 40
DEF_MAX = 4000   # codebooks._clean_state keeps this many characters of a definition
GROUP_MAX = 60
HYPOTHESES = "Hypotheses (ENLENS)"
_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.S)
_DANGER = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.I)
_LABELS = (("When to use it:", "include"), ("When not to use it:", "exclude"), ("Keywords:", "keywords"),
           ("Example:", "example"))
_HTML = re.compile(r"<\s*/?\s*(p|br|div|span|b|i|em|strong|ul|ol|li|font)\b[^>]*>", re.I)
SEP = " › "


@dataclass
class Node:
    name: str
    description: str = ""
    codable: bool = True
    children: list["Node"] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------
# reading the file safely
# ---------------------------------------------------------------------------------------------
def _text_of(data: bytes) -> str:
    """The XML as text: UTF-16 or UTF-32 by its byte order mark, else UTF-8, else the encoding its declaration names."""
    for bom, enc in ((b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"), (b"\xef\xbb\xbf", "utf-8-sig"),
                     (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if data.startswith(bom):
            return data.decode(enc)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    m = re.match(rb"\s*<\?xml[^>]*encoding=[\"']([A-Za-z0-9._-]+)[\"']", data)
    try:
        return data.decode(m.group(1).decode("ascii") if m else "cp1252")
    except (LookupError, UnicodeDecodeError):
        raise ValueError("The file is not text ENLENS can read (not UTF-8 or UTF-16).") from None


def _safe_root(data: bytes) -> ET.Element:
    """The XML's `<CodeBook>` element, read without DOCTYPE or entities. Raises ValueError."""
    text = _DECL.sub("", _text_of(data), count=1)
    if _DANGER.search(text):
        raise ValueError("The file declares a DOCTYPE or an ENTITY, which a REFI-QDA codebook never needs: it was not "
                         "read.")
    parser = ET.XMLPullParser(events=("start", "end"))
    book = None
    depth = 0
    in_book = 0
    stack: list[ET.Element] = []   # the open elements outside the codebook (their parents, to drop finished ones)
    try:
        for i in range(0, len(text), 1 << 16):   # small pieces: the events of one piece wait in memory
            parser.feed(text[i:i + (1 << 16)])
            for ev, el in parser.read_events():
                local = el.tag.rsplit("}", 1)[-1]
                if ev == "start":
                    depth += 1
                    if depth > 4 * MAX_DEPTH:
                        raise ValueError("The file nests its elements too deeply to be a codebook.")
                    if in_book:
                        in_book += 1
                    elif local == "CodeBook" and book is None:
                        book, in_book = el, 1
                    else:
                        stack.append(el)
                else:
                    depth -= 1
                    if in_book:
                        in_book -= 1
                    else:
                        if stack and stack[-1] is el:
                            stack.pop()
                        # the rest of a project (its sources, codings) is not kept in memory: a finished element
                        # leaves its parent, not only its contents (a cleared element still costs an object)
                        el.clear()
                        if stack:
                            del stack[-1][:]
        parser.close()
    except ET.ParseError as e:
        raise ValueError(f"The file is not well-formed XML ({e}).") from None
    if book is None:
        raise ValueError("The file holds no codebook (no <CodeBook> element). Export the codebook from NVivo, "
                         "ATLAS.ti or MAXQDA as a REFI-QDA codebook (.qdc).")
    return book


def _qde_of_zip(data: bytes | Path) -> bytes:
    """`project.qde` of a `.qdpx`, read no further than MAX_QDE (a zip bomb stops there)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data) if isinstance(data, bytes) else data)
    except (zipfile.BadZipFile, OSError):
        raise ValueError("The file is not a REFI-QDA project (.qdpx): it is not a zip file.") from None
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ValueError(f"The project file holds more than {MAX_MEMBERS:,} files: it was not read.")
        qdes = [i for i in infos if i.filename.lower().endswith(".qde") and not i.is_dir()]
        qde = next((i for i in qdes if i.filename.lower() == "project.qde"), None) or \
            next((i for i in qdes if "/" not in i.filename), None) or (qdes[0] if len(qdes) == 1 else None)
        if qde is None:
            raise ValueError("The project file (.qdpx) holds no project.qde.")
        if qde.file_size > MAX_QDE:
            raise ValueError(_too_big())
        try:
            with zf.open(qde) as f:
                out = f.read(MAX_QDE + 1)
        except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, zlib.error, OSError,
                EOFError):
            # a damaged member, a compression the standard library lacks, a password
            raise ValueError("The project file (.qdpx) is damaged or locked with a password, or packed in a way "
                             "ENLENS cannot unpack. Export only the codebook (.qdc) and bring that in.") from None
        if len(out) > MAX_QDE:
            raise ValueError(_too_big())
        return out


def _too_big() -> str:
    return (f"The project inside the file is larger than {MAX_QDE // 1024 ** 2} MB once unpacked. Export only the "
            "codebook (.qdc) from NVivo, ATLAS.ti or MAXQDA and bring that in.")


def _project_attr(data: bytes, attr: str) -> str:
    """An attribute of the `<Project>` element (its name, the program that wrote it), from the file's first bytes."""
    m = re.search(rb"<(?:\w+:)?Project\b[^>]*\b" + attr.encode() + rb"=\"([^\"]{1,200})\"", data[:4096])
    return html.unescape(m.group(1).decode("utf-8", "replace")) if m else ""


# ---------------------------------------------------------------------------------------------
# the tree
# ---------------------------------------------------------------------------------------------
def _local(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _clean_desc(s: str) -> str:
    """A description as plain text: paragraphs kept (blank lines), HTML (some programs write it) taken off."""
    s = s or ""
    if _HTML.search(s):
        s = re.sub(r"<\s*(br|/p|/div|/li)\b[^>]*>", "\n\n", s, flags=re.I)
        s = html.unescape(re.sub(r"<[^>]+>", "", s))
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n|\r\n\s*\r\n", s.replace("\r\n", "\n"))]
    return "\n\n".join(p for p in paras if p)


def _node(el: ET.Element, depth: int = 0) -> Node:
    if depth > MAX_DEPTH:
        raise ValueError(f"The codes are nested more than {MAX_DEPTH} levels deep.")
    desc = next((c for c in el if _local(c) == "Description"), None)
    return Node(" ".join((el.get("name") or "").split()) or "Unnamed code",
                _clean_desc(desc.text if desc is not None else ""),
                (el.get("isCodable") or "true").strip().lower() not in ("false", "0"),
                [_node(c, depth + 1) for c in el if _local(c) == "Code"])


def read_tree(data: bytes | Path) -> tuple[list[Node], dict]:
    """The top codes of a `.qdc` or a `.qdpx` (bytes, or a path), and what else was found: {origin, title, sets, zip}."""
    is_zip = (data[:4] == b"PK\x03\x04") if isinstance(data, bytes) else zipfile.is_zipfile(data)
    title = origin = ""
    if is_zip:
        raw = _qde_of_zip(data)
        title, origin = _project_attr(raw, "name"), _project_attr(raw, "origin")
    else:
        raw = data if isinstance(data, bytes) else Path(data).read_bytes()[:MAX_QDC + 1]
        if len(raw) > MAX_QDC:
            raise ValueError(f"The codebook file is larger than {MAX_QDC // 1024 ** 2} MB: it was not read.")
    book = _safe_root(raw)
    codes = next((c for c in book if _local(c) == "Codes"), None)
    roots = [_node(c) for c in (codes if codes is not None else []) if _local(c) == "Code"]
    sets = sum(1 for e in book.iter() if _local(e) == "Set")
    return roots, {"origin": book.get("origin") or origin, "title": title, "sets": sets, "zip": is_zip}


# ---------------------------------------------------------------------------------------------
# the tree as ENLENS codes and groups
# ---------------------------------------------------------------------------------------------
def _comma_keywords(origin: str) -> bool:
    """Whether "Keywords:" may be split at commas: ENLENS 0.18.7 joined keywords with ", "; later versions with "; "
    (a keyword may hold a comma), so their keywords split only at semicolons. Other programs: either."""
    m = re.match(r"ENLENS (\d+)\.(\d+)\.(\d+)", origin or "")
    return not m or tuple(int(x) for x in m.groups()) <= (0, 18, 7)


def _split_desc(desc: str, comma: bool = True) -> dict:
    """A description's definition, and the when-to-use, when-not, keywords and examples paragraphs ENLENS writes."""
    out = {"description": [], "include": "", "exclude": "", "keywords": [], "examples": []}
    for p in desc.split("\n\n"):
        for label, key in _LABELS:
            if p.startswith(label):
                v = p[len(label):].strip()
                if key == "keywords":
                    out["keywords"] += [k.strip() for k in v.split(";" if ";" in v or not comma else ",") if k.strip()]
                elif key == "example":
                    out["examples"].append(v[1:-1].strip() if v[:1] in "“\"" and v[-1:] in "”\"" else v)
                else:
                    out[key] = (out[key] + " " + v).strip()
                break
        else:
            out["description"].append(p)
    out["description"] = " ".join(out["description"]).strip()
    return out


def _cut(s: str, n: int) -> str:
    """`s` in at most `n` characters, cut before a word where it can be."""
    if len(s) <= n:
        return s
    head = s[:n - 1]
    sp = head.rfind(" ")
    return (head[:sp] if sp > n // 2 else head).rstrip(" ,;:-") + "…"


def _enlens_code(name: str, definition: str) -> str | None:
    """The code a name ENLENS wrote stands for, when ENLENS put the start of the definition after a number."""
    tok = name.split(" ", 1)[0]
    if tok != name and qdpx._NUMERIC.match(tok) and qdpx._code_name(tok, definition) == name:
        return tok
    return None


def _enlens_group(name: str, desc: str) -> tuple[str, str] | None:
    """(group, group name) of a group ENLENS wrote as "<group> <group name>" with the group name as its description."""
    if not desc or "\n" in desc:
        return None
    if name == desc:
        return name, desc
    for i, ch in enumerate(name):
        if ch == " " and qdpx._short(f"{name[:i]} {desc}", 90) == name:
            return name[:i], desc
    return None


class _Names:
    """Code names unique (as the editor counts them: without regard to case), each at most 40 characters."""

    def __init__(self):
        self.used: set[str] = set()
        self.renamed: list[tuple[str, str]] = []

    def take(self, name: str) -> str:
        base = _cut(name, NAME_MAX)
        out, n = base, 1
        while out.lower() in self.used:
            n += 1
            tail = f" ({n})"
            out = _cut(name, NAME_MAX - len(tail)).rstrip("…").rstrip() + tail
        self.used.add(out.lower())
        if out != base:
            self.renamed.append((name, out))
        return out


def to_state(roots: list[Node], info: dict | None = None) -> dict:
    """The tree as the editor's state ({title, groups, codes}) with a summary of what was done ({...,"notes": [...]})."""
    info = info or {}
    title = info.get("title") or ""
    origin = str(info.get("origin") or "")
    ours = origin.startswith("ENLENS")   # readings that only ENLENS's own export calls for
    comma = _comma_keywords(origin)
    hyp = [r for r in roots if ours and r.name == HYPOTHESES]
    roots = [r for r in roots if not (ours and r.name == HYPOTHESES)]
    wrappers = [r for r in roots if r.name.endswith(" (codebook)") and r.children]
    if len(roots) == 1 and wrappers and ours:
        title = roots[0].name[:-len(" (codebook)")]
        roots = roots[0].children
    names = _Names()
    gkeys: set[str] = set()
    groups: list[dict] = []
    codes: list[dict] = []
    s = {"codes": 0, "groups": 0, "folded": 0, "parents_as_codes": 0, "headings": 0, "not_codable": 0,
         "no_description": 0, "cut": 0, "group_descriptions": 0, "long": 0}

    def add(n: Node, group: str, path: list[str]) -> None:
        d = _split_desc(n.description, comma)
        code = (_enlens_code(n.name, d["description"]) if ours else None) or n.name
        definition = d["description"]
        tail = ""
        if not definition:
            s["no_description"] += 1
            definition = SEP.join(path + [n.name]) if path else n.name
        elif len(path) >= 2:
            tail = f" (In the tree: {SEP.join(path + [n.name])}.)"
        name = names.take(code or "Code")
        if len(code) > NAME_MAX:
            s["cut"] += 1
            definition = f"{code}: {definition}" if definition != code else code
        if len(definition) + len(tail) > DEF_MAX:   # the editor keeps 4,000 characters: cut here, keep the tree
            s["long"] += 1
            definition = _cut(definition, max(200, DEF_MAX - len(tail)))
        definition = (definition + tail)[:DEF_MAX]
        if len(path) >= 2:
            s["folded"] += 1
        codes.append({"code": name, "description": definition, "group": group, "include": d["include"],
                      "exclude": d["exclude"], "keywords": d["keywords"], "examples": d["examples"]})
        s["codes"] += 1

    def walk(n: Node, group: str, path: list[str]) -> None:
        """`n` lies `len(path)` levels under the top (path: the names above it, from the top)."""
        if n.children:
            if n.codable and n.description:
                add(n, group, path)
                s["parents_as_codes"] += 1
            else:
                s["headings"] += 1
            for c in n.children:
                walk(c, group, path + [n.name])
        elif n.codable:
            add(n, group, path)
        else:
            s["not_codable"] += 1

    for r in roots:
        if not r.children:
            walk(r, "", [])
            continue
        mine = _enlens_group(r.name, r.description) if ours else None
        key, gname = mine or (r.name, "")
        if len(key) > GROUP_MAX:
            key, gname = _cut(key, GROUP_MAX), gname or key[:120]
        base, n = key, 1
        while key.lower() in gkeys:
            n += 1
            key = f"{_cut(base, GROUP_MAX - 5).rstrip('…')} ({n})"
        gkeys.add(key.lower())
        groups.append({"group": key, "group_name": gname})
        s["groups"] += 1
        if mine is None and r.description and not (r.codable and r.description):
            s["group_descriptions"] += 1
        if r.codable and r.description and mine is None:
            add(r, key, [])
            s["parents_as_codes"] += 1
        for c in r.children:
            walk(c, key, [r.name])
    if not codes:
        raise ValueError("The file holds no codes ENLENS can use (none that can be coded).")
    if len(codes) > 5000:
        raise ValueError("A codebook can hold at most 5,000 codes.")
    s.update(sets=int(info.get("sets") or 0), renamed=[{"from": a, "to": b} for a, b in names.renamed],
             hypotheses_left_out=bool(hyp), origin=origin)
    s["notes"] = _notes(s)
    return {"title": title, "groups": groups, "codes": codes, "summary": s}


def _pl(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def _notes(s: dict) -> list[str]:
    out = [f"{_pl(s['codes'], 'code')}" + (f" in {_pl(s['groups'], 'group')}" if s["groups"] else "") + " brought in."]
    if s["folded"]:
        out.append(f"{_pl(s['folded'], 'code')} stood three or more levels down: each is now a code of its top group, "
                   "with its place in the tree at the end of its definition.")
    if s["parents_as_codes"]:
        one = s["parents_as_codes"] == 1
        out.append(f"{_pl(s['parents_as_codes'], 'code')} with codes under {'it' if one else 'them'} had a description, "
                   f"so {'it is' if one else 'each is'} a code too.")
    if s["headings"]:
        out.append(f"{_pl(s['headings'], 'heading')} (a code with codes under it and no description) became a group "
                   "or a step in the tree, not a code.")
    if s["no_description"]:
        out.append(f"{_pl(s['no_description'], 'code')} had no description: {'its' if s['no_description'] == 1 else 'their'} "
                   "place in the tree (or name) stands in for it. Give each a definition in the editor.")
    if s["cut"]:
        out.append(f"{_pl(s['cut'], 'name')} longer than 40 characters {'was' if s['cut'] == 1 else 'were'} cut; the "
                   "whole name opens the definition.")
    if s["long"]:
        out.append(f"{_pl(s['long'], 'definition')} longer than {DEF_MAX:,} characters {'was' if s['long'] == 1 else 'were'} "
                   "shortened (a codebook keeps that many); its place in the tree stays at the end.")
    if s["renamed"]:
        out.append(f"{_pl(len(s['renamed']), 'code')} shared a name with another and got a number: "
                   + ", ".join(f"“{r['to']}”" for r in s["renamed"][:5]) + ("…" if len(s["renamed"]) > 5 else "") + ".")
    if s["not_codable"]:
        out.append(f"{_pl(s['not_codable'], 'code')} that cannot be coded, with nothing under {'it' if s['not_codable'] == 1 else 'them'}, "
                   f"{'was' if s['not_codable'] == 1 else 'were'} left out.")
    if s["group_descriptions"]:
        out.append(f"{_pl(s['group_descriptions'], 'group description')} {'was' if s['group_descriptions'] == 1 else 'were'} "
                   "left out: a group has only a name.")
    if s["sets"]:
        out.append(f"{_pl(s['sets'], 'set')} left out: ENLENS has no sets.")
    if s["hypotheses_left_out"]:
        out.append("The hypotheses ENLENS wrote as codes were left out.")
    return out


# ---------------------------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------------------------
def from_source(source: dict) -> dict:
    """The state for `codebooks.create` from the New codebook dialog's source: {"file": base64 of the file,
    "filename"} or {"qdc": the XML as text}."""
    if source.get("file"):
        b64 = str(source.get("file"))
        if len(b64) > (MAX_QDC * 4) // 3 + 8:
            raise ValueError(f"The file is larger than {MAX_QDC // 1024 ** 2} MB. Export only the codebook (.qdc) "
                             "and bring that in.")
        try:
            data = base64.b64decode(b64, validate=False)
        except (binascii.Error, ValueError):
            raise ValueError("The file could not be read (it did not arrive whole).") from None
    elif source.get("qdc"):
        data = str(source.get("qdc")).encode("utf-8")
    else:
        raise ValueError("Choose a .qdc or .qdpx file.")
    roots, info = read_tree(data)
    return to_state(roots, info)


def from_path(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"No such file: {p}")
    if zipfile.is_zipfile(p):
        roots, info = read_tree(p)
    else:
        if p.stat().st_size > MAX_QDC:
            raise ValueError(f"The codebook file is larger than {MAX_QDC // 1024 ** 2} MB: it was not read.")
        roots, info = read_tree(p.read_bytes())
    return to_state(roots, info)
