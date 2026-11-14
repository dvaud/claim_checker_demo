"""A codebook brought in from NVivo, ATLAS.ti or MAXQDA (roadmap K1 "In and out", with G5): a REFI-QDA codebook
(`.qdc`, *Codebook Exchange* 1.0), or the `<CodeBook>` of a REFI-QDA project (`.qdpx`). No AI (Level 0).

    enlens --ws X import-qdc FILE [NAME] [--title T] [--codebook TITLE]

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
  columns (the first paragraph is always the definition, even when it opens with one of these labels); a group written as "<group> <group name>" with the group name as its description gets both back; a code
  that is only a number (an SDG target, "6.4") written with the start of its definition gets its number back. The
  code ids (side file `ids`) are new: a codebook brought in is a new codebook, not the one it was exported from. A
  `.qdc` does not carry an example's document and page (only its words), the codebook's label or its direction
  setting, so those come back empty. Keywords were joined with ", " by ENLENS 0.18.7 and with "; " since (a keyword
  may hold a comma): a later ENLENS file splits them only at semicolons, and in the versions after 0.18.7 a single
  keyword that holds a comma ends with ";" so that the file says so itself, whatever version it names. These readings (numbers, groups, the
  hypotheses' codes, the "(codebook)" wrapper) apply only to files whose origin is ENLENS.
- **Sets of codes become groups** only when they can stand for them (ATLAS.ti keeps its code groups as sets over
  flat codes): no code has codes under it and no code is in two sets. Otherwise they are left out and counted.
- **Left out**: colours (counted), Sets otherwise, memos (NoteRef), a non-codable code's own description when it has
  codes under it (a group, or a step in the tree, has only a name; the summary counts these), and, in a `.qdpx`,
  everything but the codebook, and the codes ENLENS writes for its hypotheses ("Hypotheses (ENLENS)"). A `.qdpx`
  ENLENS wrote holds each codebook under a "<title> (codebook)" code: when there is only one, its contents are the
  codebook and its title the codebook's title; with several, the person chooses one (`codebook`, else
  SeveralCodebooks names them).

The file is read with the standard library's XML reader, so no new dependency: a DOCTYPE or an ENTITY is refused,
by a first look at the text and by the parser itself, whatever the encoding (no entity expansion, no outside file); a
`.qdc` may be at most 20 MB, a `.qdpx` at most 5,000 members, and only its `project.qde` is read, at most 64 MB once
unpacked (a zip bomb stops there). Only the codebook is kept in memory, and the reader stops past 10,000 codes,
before the tree is built.
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
MAX_CODES = 5000          # a codebook holds at most this many codes
MAX_READ = 2 * MAX_CODES  # the reader stops past this many codes (headings and hypotheses count too), before the tree
MAX_DESC = 100_000        # characters of a description read (a definition keeps DEF_MAX)
NAME_LONG = 1000          # characters of a name read (NAME_MAX are kept, the rest opens the definition)
NAME_MAX = 40
DEF_MAX = 4000   # codebooks._clean_state keeps this many characters of a definition
GROUP_MAX = 60
HYPOTHESES = "Hypotheses (ENLENS)"
_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.S)
_DANGER = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.I)
_LABELS = (("When to use it:", "include"), ("When not to use it:", "exclude"), ("Keywords:", "keywords"),
           ("Example:", "example"))
_HTML = re.compile(r"<\s{0,20}(?:/\s{0,20})?(p|br|div|span|b|i|em|strong|ul|ol|li|font)\b[^<>]{0,2000}>", re.I)
_DOCTYPE = "The file declares a DOCTYPE or an ENTITY, which a REFI-QDA codebook never needs: it was not read."
SEP = " › "


@dataclass
class Node:
    name: str
    description: str = ""
    codable: bool = True
    children: list["Node"] = field(default_factory=list)
    guid: str = ""


# ---------------------------------------------------------------------------------------------
# reading the file safely
# ---------------------------------------------------------------------------------------------
def _text_of(data: bytes) -> str:
    """The XML as text: UTF-16 or UTF-32 by its byte order mark or, without one, by where its zero bytes fall (an XML
    file starts with "<" or a space), else UTF-8, else the encoding its declaration names. Raises ValueError."""
    for bom, enc in ((b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"), (b"\xef\xbb\xbf", "utf-8-sig"),
                     (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if data.startswith(bom):
            return _no_nul(data.decode(enc, "replace"))
    h = data[:4]
    if len(h) == 4 and 0 in h:
        enc = ("utf-32-be" if h[:3] == b"\0\0\0" else "utf-32-le" if h[1:] == b"\0\0\0" else
               "utf-16-be" if h[0] == 0 and h[2] == 0 else "utf-16-le" if h[1] == 0 and h[3] == 0 else "")
        if enc:
            return _no_nul(data.decode(enc, "replace"))
    try:
        return _no_nul(data.decode("utf-8"))
    except UnicodeDecodeError:
        pass
    m = re.match(rb"\s*<\?xml[^>]{0,200}encoding=[\"']([A-Za-z0-9._-]+)[\"']", data)
    try:
        return _no_nul(data.decode(m.group(1).decode("ascii") if m else "cp1252"))
    except (LookupError, UnicodeDecodeError):
        raise ValueError("The file is not text ENLENS can read (not UTF-8 or UTF-16).") from None


def _no_nul(text: str) -> str:
    if "\x00" in text:   # never in XML: bytes read in the wrong encoding, or not text at all
        raise ValueError("The file is not text ENLENS can read (it holds zero bytes, which no XML file has).")
    return text


@dataclass
class _Read:
    """What the reader keeps of a file: the codebook's top codes, and what lies around them."""
    roots: list[Node] = field(default_factory=list)
    origin: str = ""          # the <CodeBook>'s origin, else the <Project>'s
    title: str = ""           # the <Project>'s name
    sets: list[tuple[str, list[str]]] = field(default_factory=list)   # (name, member code guids) of the code sets
    colours: int = 0          # codes with a colour
    found: bool = False       # a <CodeBook> was met


class _Reader:
    """The XML parser's target: keeps the codes of the first `<CodeBook>` as Nodes and the few things around it
    (the project's name and origin, the sets of codes), and nothing else of a project (its sources and codings pass
    by). It refuses a DOCTYPE however the file is encoded (the parser calls `doctype` before reading any declaration
    in it), nesting past the limits and more codes than a codebook can hold, as they come, before the tree is built."""

    def __init__(self):
        self.out = _Read()
        self.depth = 0
        self.book = 0              # the depth of the <CodeBook>, while inside it
        self.path: list[tuple[str, bool]] = []   # the open elements inside the codebook: (local name, a code?)
        self.codes: list[Node] = []
        self.count = 0
        self.desc: list[str] | None = None   # the text of the <Description> being read, directly under a code
        self.desc_len = 0
        self.desc_at = 0
        self.set: tuple[str, list[str]] | None = None

    def doctype(self, *_a):
        raise ValueError(_DOCTYPE)

    def start(self, tag, attrib):
        local = tag.rsplit("}", 1)[-1]
        self.depth += 1
        if self.depth > 4 * MAX_DEPTH:
            raise ValueError("The file nests its elements too deeply to be a codebook.")
        if self.depth == 1 and local == "Project":
            self.out.title = " ".join((attrib.get("name") or "")[:200].split())
            self.out.origin = (attrib.get("origin") or "")[:200]
        if local == "Set":
            self.set = (" ".join((attrib.get("name") or "")[:NAME_LONG].split()), [])
        elif local == "MemberCode" and self.set is not None:
            self.set[1].append(attrib.get("targetGUID") or "")
        if not self.book:
            if local == "CodeBook" and not self.out.found:
                self.out.found, self.book = True, self.depth
                if attrib.get("origin"):
                    self.out.origin = attrib["origin"][:200]
            return
        parent, parent_code = self.path[-1] if self.path else ("CodeBook", False)
        is_code = local == "Code" and (parent_code or (parent == "Codes" and len(self.path) == 1))
        self.path.append((local, is_code))
        if is_code:
            if len(self.codes) > MAX_DEPTH:
                raise ValueError(f"The codes are nested more than {MAX_DEPTH} levels deep.")
            self.count += 1
            if self.count > MAX_READ:
                raise ValueError(f"The file holds more than {MAX_READ:,} codes: a codebook can hold at most "
                                 f"{MAX_CODES:,} codes.")
            n = Node(" ".join((attrib.get("name") or "")[:NAME_LONG].split()) or "Unnamed code", "",
                     (attrib.get("isCodable") or "true").strip().lower() not in ("false", "0"),
                     guid=attrib.get("guid") or "")
            if (attrib.get("color") or "").strip():
                self.out.colours += 1
            (self.codes[-1].children if self.codes else self.out.roots).append(n)
            self.codes.append(n)
        elif local == "Description" and parent_code and self.desc is None:
            self.desc, self.desc_len, self.desc_at = [], 0, len(self.path)

    def data(self, text):
        if self.desc is not None and self.desc_len < MAX_DESC:
            self.desc.append(text[:MAX_DESC - self.desc_len])
            self.desc_len += len(text)

    def end(self, tag):
        local = tag.rsplit("}", 1)[-1]
        self.depth -= 1
        if local == "Set" and self.set is not None:
            if any(self.set[1]):   # a set of codes (not of documents)
                self.out.sets.append(self.set)
            self.set = None
        if not self.book:
            return
        if self.depth < self.book:
            self.book = 0
            return
        if self.desc is not None and len(self.path) == self.desc_at:
            self.codes[-1].description = _clean_desc("".join(self.desc))
            self.desc = None
        if self.path.pop()[1]:
            self.codes.pop()

    def close(self):
        return self.out


def _read(data: bytes) -> _Read:
    """The codebook of a `.qdc` or a `project.qde`, read without DOCTYPE or entities. Raises ValueError."""
    text = _DECL.sub("", _text_of(data), count=1)
    if _DANGER.search(text):
        raise ValueError(_DOCTYPE)
    reader = _Reader()
    parser = ET.XMLParser(target=reader)
    try:
        for i in range(0, len(text), 1 << 16):
            parser.feed(text[i:i + (1 << 16)])
        out = parser.close()
    except ET.ParseError as e:
        raise ValueError(f"The file is not well-formed XML ({e}).") from None
    if not out.found:
        raise ValueError("The file holds no codebook (no <CodeBook> element). Export the codebook from NVivo, "
                         "ATLAS.ti or MAXQDA as a REFI-QDA codebook (.qdc).")
    return out


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


# ---------------------------------------------------------------------------------------------
# the tree
# ---------------------------------------------------------------------------------------------
def _clean_desc(s: str) -> str:
    """A description as plain text: paragraphs kept (blank lines), HTML (some programs write it) taken off. Every
    pattern stops at the next "<" or after a bounded run, so a hostile description costs time in step with its length."""
    s = (s or "")[:MAX_DESC]
    if _HTML.search(s):
        s = re.sub(r"<\s{0,20}(?:br|/\s{0,20}(?:p|div|li))\b[^<>]{0,2000}>", "\n\n", s, flags=re.I)
        s = html.unescape(re.sub(r"<[^<>]{1,2000}>", "", s))
    paras = [" ".join(p.split()) for p in re.split(r"\n[ \t\r\f\v]*\n", s.replace("\r\n", "\n").replace("\r", "\n"))]
    return "\n\n".join(p for p in paras if p)


def read_tree(data: bytes | Path) -> tuple[list[Node], dict]:
    """The top codes of a `.qdc` or a `.qdpx` (bytes, or a path), and what else was found: {origin, title, sets
    (how many sets of codes), set_members [(name, [code guid, ...])], colours (codes with a colour), zip}."""
    is_zip = (data[:4] == b"PK\x03\x04") if isinstance(data, bytes) else zipfile.is_zipfile(data)
    if is_zip:
        raw = _qde_of_zip(data)
    else:
        raw = data if isinstance(data, bytes) else Path(data).read_bytes()[:MAX_QDC + 1]
        if len(raw) > MAX_QDC:
            raise ValueError(f"The codebook file is larger than {MAX_QDC // 1024 ** 2} MB: it was not read.")
    got = _read(raw)
    return got.roots, {"origin": got.origin, "title": got.title, "sets": len(got.sets), "set_members": got.sets,
                       "colours": got.colours, "zip": is_zip}


# ---------------------------------------------------------------------------------------------
# the tree as ENLENS codes and groups
# ---------------------------------------------------------------------------------------------
def _comma_keywords(origin: str) -> bool:
    """Whether "Keywords:" may be split at commas: ENLENS 0.18.7 joined keywords with ", "; later versions with "; "
    (a keyword may hold a comma), so their keywords split only at semicolons. Other programs: either. After 0.18.7 a
    single keyword that holds a comma ends with ";", so the file itself says how to read it (_split_desc): the version
    matters only for a file without one."""
    m = re.match(r"ENLENS (\d+)\.(\d+)\.(\d+)", origin or "")
    return not m or tuple(int(x) for x in m.groups()) <= (0, 18, 7)


def _split_desc(desc: str, comma: bool = True) -> dict:
    """A description's definition, and the when-to-use, when-not, keywords and examples paragraphs ENLENS writes.
    The first paragraph is always the definition (ENLENS writes it first), even when it opens with one of the labels
    ("Example: the classic case…"): only the paragraphs after it are read for them."""
    out = {"description": [], "include": "", "exclude": "", "keywords": [], "examples": []}
    for i, p in enumerate(desc.split("\n\n")):
        for label, key in (_LABELS if i else ()):
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
    if len(name) > 90:   # ENLENS writes a group's name in at most 90 characters
        return None
    for i, ch in enumerate(name):
        if ch == " " and qdpx._short(f"{name[:i]} {desc}", 90) == name:
            return name[:i], desc
    return None


class _Unique:
    """Names unique without regard to case, each at most `size` characters: the second "Name" becomes "Name (2)". A
    counter per name, so a thousand codes of one name cost a thousand lookups, not half a million."""

    def __init__(self, size: int):
        self.size = size
        self.used: set[str] = set()
        self.next: dict[str, int] = {}
        self.renamed: list[tuple[str, str]] = []

    def take(self, name: str) -> str:
        base = _cut(name, self.size)
        out = base
        if out.lower() in self.used:
            n = self.next.get(base.lower(), 1)
            while out.lower() in self.used:
                n += 1
                tail = f" ({n})"
                out = _cut(name, self.size - len(tail)).rstrip("…").rstrip() + tail
            self.next[base.lower()] = n
        self.used.add(out.lower())
        if out != base:
            self.renamed.append((name, out))
        return out


class SeveralCodebooks(ValueError):
    """A file ENLENS wrote holds several codebooks and none was chosen: `extra` names them (the app offers a choice)."""

    def __init__(self, titles: list[str]):
        super().__init__(f"The file holds {len(titles)} codebooks: " + ", ".join(f"“{t}”" for t in titles)
                         + ". Choose the one to bring in.")
        self.titles = titles
        self.extra = {"codebooks": titles}


def _one_codebook(roots: list[Node], codebook: str) -> tuple[list[Node], str] | None:
    """The codes and title of one "<title> (codebook)" wrapper ENLENS wrote (export-qdpx writes every codebook in use
    so), or None when the file has no wrappers. `codebook`: the title chosen; with several wrappers and none chosen,
    SeveralCodebooks."""
    wrappers = [r for r in roots if r.name.endswith(" (codebook)") and r.children]
    titles = [w.name[:-len(" (codebook)")] for w in wrappers]
    if codebook:
        for w, t in zip(wrappers, titles):
            if t == codebook or t.casefold() == codebook.strip().casefold():
                return w.children, t
        if wrappers:
            raise ValueError(f"The file holds no codebook called “{codebook}”. It holds: "
                             + ", ".join(f"“{t}”" for t in titles) + ".")
        return None
    if len(wrappers) > 1:
        raise SeveralCodebooks(titles)
    if len(roots) == 1 and wrappers:
        return wrappers[0].children, titles[0]
    return None


def _sets_as_groups(roots: list[Node], sets: list) -> dict[str, str] | None:
    """{code guid: set name} when the sets can stand for groups (ATLAS.ti keeps its code groups as sets over flat
    codes): no code has codes under it, and no code is in more than one set. Otherwise None."""
    if not sets or any(r.children for r in roots):
        return None
    guids = {r.guid for r in roots if r.guid}
    of: dict[str, str] = {}
    for name, members in sets:
        for g in set(members):
            if g in of:
                return None
            if g in guids:
                of[g] = name or "Set"
    return of or None


def to_state(roots: list[Node], info: dict | None = None, codebook: str = "") -> dict:
    """The tree as the editor's state ({title, groups, codes}) with a summary of what was done ({...,"notes": [...]}).
    `codebook`: in a file ENLENS wrote with several codebooks, the title of the one to bring in."""
    info = info or {}
    title = info.get("title") or ""
    origin = str(info.get("origin") or "")
    ours = origin.startswith("ENLENS")   # readings that only ENLENS's own export calls for
    comma = _comma_keywords(origin)
    hyp = [r for r in roots if ours and r.name == HYPOTHESES]
    roots = [r for r in roots if not (ours and r.name == HYPOTHESES)]
    one = _one_codebook(roots, codebook) if ours else None
    if one:
        roots, title = one
    names = _Unique(NAME_MAX)
    gnames = _Unique(GROUP_MAX)
    groups: list[dict] = []
    codes: list[dict] = []
    s = {"codes": 0, "groups": 0, "folded": 0, "parents_as_codes": 0, "headings": 0, "not_codable": 0,
         "no_description": 0, "cut": 0, "group_descriptions": 0, "long": 0, "sets_as_groups": 0}

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

    def new_group(key: str, gname: str) -> str:
        if len(key) > GROUP_MAX:
            gname = gname or key[:120]
        key = gnames.take(key)
        groups.append({"group": key, "group_name": gname})
        s["groups"] += 1
        return key

    def walk(n: Node, group: str, path: list[str]) -> None:
        """`n` lies `len(path)` levels under the top (path: the names above it, from the top)."""
        if n.children:
            if n.codable and n.description:
                add(n, group, path)
                s["parents_as_codes"] += 1
            else:
                s["headings"] += 1
                if n.description:   # a heading that cannot be coded: its description has no place
                    s["group_descriptions"] += 1
            for c in n.children:
                walk(c, group, path + [n.name])
        elif n.codable:
            add(n, group, path)
        else:
            s["not_codable"] += 1

    by_set = None if ours else _sets_as_groups(roots, info.get("set_members") or [])
    set_keys: dict[str, str] = {}
    for r in roots:
        if by_set and r.guid in by_set and r.codable:
            sname = by_set[r.guid]
            if sname not in set_keys:
                set_keys[sname] = new_group(sname, "")
            walk(r, set_keys[sname], [sname])
            continue
        if not r.children:
            walk(r, "", [])
            continue
        mine = _enlens_group(r.name, r.description) if ours else None
        key, gname = mine or (r.name, "")
        key = new_group(key, gname)
        if mine is None and r.description and not r.codable:
            s["group_descriptions"] += 1
        if r.codable and r.description and mine is None:
            add(r, key, [])
            s["parents_as_codes"] += 1
        for c in r.children:
            walk(c, key, [r.name])
    if not codes:
        raise ValueError("The file holds no codes ENLENS can use (none that can be coded).")
    if len(codes) > MAX_CODES:
        raise ValueError(f"A codebook can hold at most {MAX_CODES:,} codes.")
    s["sets_as_groups"] = len(set_keys)
    s.update(sets=max(0, int(info.get("sets") or 0) - len(set_keys)), colours=int(info.get("colours") or 0),
             renamed=[{"from": a, "to": b} for a, b in names.renamed], hypotheses_left_out=bool(hyp), origin=origin)
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
        out.append(f"{_pl(s['headings'], 'heading')} (a code with codes under it that has no description or cannot be "
                   "coded) became a group or a step in the tree, not a code.")
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
        one = s["group_descriptions"] == 1
        out.append(f"{_pl(s['group_descriptions'], 'description')} of a group or a heading {'was' if one else 'were'} "
                   "left out: a group, or a step in the tree, has only a name.")
    if s["sets_as_groups"]:
        out.append(f"{_pl(s['sets_as_groups'], 'set')} of codes became {'a group' if s['sets_as_groups'] == 1 else 'groups'}"
                   " (no code had codes under it, and none was in two sets).")
    if s["sets"]:
        out.append(f"{_pl(s['sets'], 'set')} left out: ENLENS has no sets.")
    if s["colours"]:
        out.append(f"{_pl(s['colours'], 'code')} had a colour: ENLENS keeps none.")
    if s["hypotheses_left_out"]:
        out.append("The hypotheses ENLENS wrote as codes were left out.")
    return out


# ---------------------------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------------------------
def from_source(source: dict) -> dict:
    """The state for `codebooks.create` from the New codebook dialog's source: {"file": base64 of the file,
    "filename"} or {"qdc": the XML as text}, and "codebook": the title of the codebook to bring in, when a file
    ENLENS wrote holds several (SeveralCodebooks names them)."""
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
    return to_state(roots, info, str(source.get("codebook") or ""))


def from_path(path: str | Path, codebook: str = "") -> dict:
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"No such file: {p}")
    if zipfile.is_zipfile(p):
        roots, info = read_tree(p)
    else:
        if p.stat().st_size > MAX_QDC:
            raise ValueError(f"The codebook file is larger than {MAX_QDC // 1024 ** 2} MB: it was not read.")
        roots, info = read_tree(p.read_bytes())
    return to_state(roots, info, codebook)
