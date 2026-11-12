"""Frameworks: optional codebooks a hypothesis can be tagged with, such as the 169 SDG targets.

A framework is a list of codes with descriptions. When a hypothesis names a code, the model sees the code's text
next to the claim, and the history can be filtered by it. The SDG targets ship with the package (`sdg`); any
other codebook is a CSV file:

    code,description[,group][,group_name]
    H1,"Remote work lowers commuting emissions",transport,Transport

placed in ENLENS_HOME/frameworks/ (all projects) or in a project's frameworks/ folder (that project only), or
added in the app. An optional `<name>.json` next to it gives {"title": ..., "label": ...}. The columns may be
separated by commas or by semicolons (a spreadsheet in many European settings saves CSV with semicolons), and the
file may be UTF-8 or a Windows code page (see `decode`).
"""
from __future__ import annotations

import csv
import io
import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .retrieve import BM25
from .textutil import tokens

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


@dataclass(frozen=True)
class Code:
    code: str
    description: str
    group: str = ""
    group_name: str = ""
    # 0.16 (K1, codebooks.py): when to use the code and when not, the words it is matched by besides its description,
    # and example quotes from the documents (optional columns of the CSV)
    include: str = ""
    exclude: str = ""
    keywords: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()


@dataclass
class Framework:
    name: str
    title: str
    label: str                       # what one code is called, e.g. "SDG target"
    codes: dict[str, Code]
    source: str = "bundled"          # bundled | home | project
    lexicon: list[tuple[str, str]] = field(default_factory=list)
    directional: bool = False        # its codes are aims a text can help or hinder (the SDG targets): labels say which
    match_text: dict[str, str] = field(default_factory=dict)  # the text a code is matched by, when not its description
    ordered: bool = False            # 0.16: its codes keep the file's order (a codebook made in the editor)
    meta: dict = field(default_factory=dict)  # 0.16: the codebook's side file as read (codebooks.py)
    _index: tuple | None = None
    _lex: tuple | None = None

    def sorted_codes(self) -> list[Code]:
        if self.ordered:
            return list(self.codes.values())
        if self.name == "sdg":
            from .taxonomy import target_sort_key

            return sorted(self.codes.values(), key=lambda c: target_sort_key(c.code))
        return sorted(self.codes.values(), key=lambda c: _natural(c.code))

    def normalise(self, code: str | None) -> str | None:
        if not code:
            return None
        c = str(code).strip()
        if c in self.codes:
            return c
        if self.name == "sdg":
            from .taxonomy import normalise_target

            return normalise_target(c)
        if self.name == "sdg_goals":
            m = re.match(r"^(?:sdg|goal)?\s*(\d{1,2})(?:\s*\.\s*\w+)?\.?$", c.lower())
            return str(int(m.group(1))) if m and str(int(m.group(1))) in self.codes else None
        low = {k.lower(): k for k in self.codes}
        return low.get(c.lower())

    def code_text(self, code: str) -> str:
        """The words a code is matched by: its description and group name (or its own matching text)."""
        c = self.codes[code]
        if code in self.match_text:
            return self.match_text[code]
        # 0.16: a code's own words to match it by come after its description (none: the text of before)
        return f"{c.description} {c.group_name}" + (" " + " ".join(c.keywords) if c.keywords else "")

    def _bm(self) -> tuple:
        if self._index is None:
            cs = self.sorted_codes()
            toks = [tokens(self.code_text(c.code)) for c in cs]
            self._index = (cs, BM25(toks), {c.code: set(t) for c, t in zip(cs, toks)})
        return self._index

    def scores(self, text: str, toks: list[str] | None = None, lex_hits: set[str] | None = None) -> dict[str, float]:
        """BM25 score of every code that shares a word with the text, plus the lexicon's common phrasings (`lex_hits`
        when the caller matched them already)."""
        cs, bm, _sets = self._bm()
        scores = {cs[i].code: s for i, s in bm.sparse(tokens(text) if toks is None else toks).items()}
        top = max(scores.values(), default=0.0)
        hits = self.lexicon_hits(text) if lex_hits is None else lex_hits
        for code in hits:  # common phrasings the code texts do not use ("water stress", "jobs")
            scores[code] = scores.get(code, 0.0) + 10 + top
        return scores

    def lexicon_hits(self, text: str) -> set[str]:
        """Codes whose common phrasings occur in the text (one pass over the text for all of them)."""
        if not self.lexicon:
            return set()
        if self._lex is None:  # the patterns are lower case: matching lower-cased text is faster than re.I
            lex = [(re.compile(p.lower()), c) for p, c in self.lexicon if c in self.codes]
            self._lex = [(rx, c, needles(rx)) for rx, c in lex]
        low = text.lower()
        # 0.16: a pattern is tried only where one of the words its alternatives start with occurs (the same codes:
        # it cannot match without one), about three times quicker over a corpus
        return {c for rx, c, need in self._lex if (need is None or any(n in low for n in need)) and rx.search(low)}

    def code_stems(self, code: str) -> set[str]:
        return self._bm()[2].get(code, set())

    def suggest(self, text: str, n: int = 5) -> list[dict]:
        """Codes whose wording is closest to the text (keyword match, no model): a starting point only."""
        scores = self.scores(text)
        best = sorted((c for c in scores if scores[c] > 0), key=lambda c: (-scores[c], _natural(c)))[:n]
        return [{"code": c, "group": self.codes[c].group, "description": self.codes[c].description,
                 "score": round(scores[c], 2)} for c in best]

    def info(self, with_codes: bool = False) -> dict:
        out = {"name": self.name, "title": self.title, "label": self.label, "source": self.source, "codes": len(self.codes),
               "directional": self.directional, "groups": len({c.group for c in self.codes.values() if c.group})}
        if with_codes:
            out["items"] = [{"code": c.code, "description": c.description, "group": c.group, "group_name": c.group_name,
                             **({"include": c.include} if c.include else {}),
                             **({"exclude": c.exclude} if c.exclude else {}),
                             **({"keywords": list(c.keywords)} if c.keywords else {}),
                             **({"examples": list(c.examples)} if c.examples else {})}
                            for c in self.sorted_codes()]
        return out


def needles(rx: re.Pattern) -> tuple[str, ...] | None:
    """0.16: strings one of which a text must contain for the pattern to match anywhere in it: the letters each of its
    alternatives starts with (after `\\b` or `^`). None when that cannot be said (the pattern then always runs):
    an alternative that starts with anything but a letter, a pattern that ignores case (`(?i)`: "ſ" matches "s"),
    or a Python whose parser of patterns this does not know."""
    if rx.flags & re.IGNORECASE:
        return None
    try:
        try:
            from re import _constants as sc
            from re import _parser as sp
        except ImportError:  # Python 3.10
            import sre_constants as sc
            import sre_parse as sp
        return _starts(list(sp.parse(rx.pattern, rx.flags)), sc)
    except Exception:  # noqa: BLE001 - not known: always run the pattern
        return None


def _starts(items: list, sc) -> tuple[str, ...] | None:
    i = 0
    while i < len(items) and items[i][0] is sc.AT:  # \b, ^: no letter of the text
        i += 1
    if i < len(items) and items[i][0] is sc.BRANCH:  # a|b: one of each alternative's
        out: list[str] = []
        for alt in items[i][1][1]:
            got = _starts(list(alt), sc)
            if not got:
                return None
            out.extend(got)
        return tuple(out)
    if i < len(items) and items[i][0] is sc.SUBPATTERN:  # (…): what the group starts with
        _group, add, _del, sub = items[i][1]
        return None if add & sc.SRE_FLAG_IGNORECASE else _starts(list(sub), sc)
    lit = []
    while i < len(items) and items[i][0] is sc.LITERAL:
        lit.append(chr(items[i][1]))
        i += 1
    return ("".join(lit),) if lit else None


def _natural(code: str) -> list:
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", code)]


_LOCK = threading.Lock()
_CACHE: dict[tuple, Framework] = {}


def _sdg() -> Framework:
    key = ("bundled", "sdg")
    with _LOCK:
        if key not in _CACHE:
            from .llm import LEXICON
            from .taxonomy import targets

            codes = {t.code: Code(t.code, t.description, str(t.goal), t.goal_name) for t in targets().values()}
            _CACHE[key] = Framework("sdg", "UN Sustainable Development Goals (169 targets)", "SDG target", codes,
                                    "bundled", list(LEXICON), directional=True)
        return _CACHE[key]


def _sdg_goals() -> Framework:
    """The 17 goals, as a codebook of their own (faster profiles, more agreement; coarser). A goal is matched by
    its name and the texts of its targets."""
    key = ("bundled", "sdg_goals")
    with _LOCK:
        if key not in _CACHE:
            from .llm import LEXICON
            from .taxonomy import goal_names, targets

            names = goal_names()
            texts: dict[str, list[str]] = {}
            for t in targets().values():
                texts.setdefault(str(t.goal), []).append(t.description)
            codes = {str(g): Code(str(g), name, str(g), name) for g, name in sorted(names.items())}
            lex = [(pat, code.split(".")[0]) for pat, code in LEXICON]
            _CACHE[key] = Framework("sdg_goals", "UN Sustainable Development Goals (17 goals)", "SDG", codes, "bundled",
                                    lex, directional=True,
                                    match_text={g: f"{codes[g].description} " + " ".join(texts.get(g, [])) for g in codes})
        return _CACHE[key]


def decode(data: bytes) -> str:
    """The text of a CSV file: UTF-8 (with or without a byte order mark), else a Windows code page: Central European
    (Hungarian ő and ű are bytes that Western European pages read as õ and û) when those bytes occur, else Western."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1250" if re.search(rb"[\xf5\xd5]", data) else "cp1252", errors="replace")


def _delimiter(text: str) -> str:
    """, or ; or a tab: whichever the header line has most of (a comma wins a tie)."""
    head = next((ln for ln in text.splitlines() if ln.strip()), "")
    best = max((",", ";", "\t"), key=lambda d: (head.count(d), d == ","))
    return best if head.count(best) else ","


# 0.16: the optional columns of a codebook made in the editor (the CSV still opens in a spreadsheet)
EXTRA_COLUMNS = ("when_to_use", "when_not_to_use", "keywords", "examples")


def _split_list(value: str | None, sep: str) -> tuple[str, ...]:
    out = []
    for x in (value or "").split(sep):
        x = " ".join(x.split())
        if x and x not in out:
            out.append(x)
    return tuple(out)


def parse_csv(text: str, allow_empty: bool = False, extra: bool = False) -> dict[str, Code]:
    """Codes from CSV text (commas or semicolons). Raises ValueError naming the problem. `allow_empty`: a codebook with
    no codes yet (one just started in the editor) is not a problem. `extra`: read the editor's columns too
    (`EXTRA_COLUMNS`); a codebook not made in the editor keeps them out, so a CSV that happened to have a column of
    that name is read as before 0.16."""
    text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text), delimiter=_delimiter(text))
    rows = list(reader)
    if not rows:
        heads = {(c or "").strip().lower() for c in (reader.fieldnames or [])}
        if allow_empty and {"code", "description"} <= heads:
            return {}
        raise ValueError("The file has no rows. Columns: code, description (and optionally group, group_name).")
    cols = {c.strip().lower(): c for c in rows[0].keys() if c}
    if "code" not in cols or "description" not in cols:
        raise ValueError("The file needs the columns code and description (and optionally group, group_name).")
    out: dict[str, Code] = {}
    for i, r in enumerate(rows, start=2):
        code = (r.get(cols["code"]) or "").strip()
        desc = " ".join((r.get(cols["description"]) or "").split())
        if not code and not desc:
            continue
        if not code or not desc:
            raise ValueError(f"Row {i}: every row needs a code and a description.")
        if len(code) > 40:
            raise ValueError(f"Row {i}: the code {code[:40]!r}… is longer than 40 characters.")
        if code in out:
            raise ValueError(f"Row {i}: the code {code!r} appears twice.")
        def col(name: str) -> str:
            if name in EXTRA_COLUMNS and not extra:
                return ""
            return (r.get(cols[name]) or "") if name in cols else ""

        out[code] = Code(code, desc, col("group").strip(), col("group_name").strip(),
                         " ".join(col("when_to_use").split()), " ".join(col("when_not_to_use").split()),
                         _split_list(col("keywords"), ";"), _split_list(col("examples"), "\n"))
    if len(out) > 5000:
        raise ValueError("A framework can hold at most 5,000 codes.")
    return out


def _load_file(path: Path, source: str) -> Framework | None:
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    meta = {}
    side = path.with_suffix(".json")
    if side.exists():
        try:
            meta = json.loads(side.read_text(encoding="utf-8"))
            st2 = side.stat()
            key = (*key, st2.st_mtime_ns, st2.st_size)  # 0.16: a change of the side file alone is seen too
        except (json.JSONDecodeError, OSError):
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    try:
        codes = parse_csv(decode(path.read_bytes()), allow_empty=bool(meta.get("editor")), extra=bool(meta.get("editor")))
    except (ValueError, OSError):
        return None
    name = path.stem.lower()
    fw = Framework(name, str(meta.get("title") or name.replace("_", " ").replace("-", " ").capitalize()),
                   str(meta.get("label") or "code"), codes, source, directional=bool(meta.get("directional")),
                   ordered=bool(meta.get("ordered")), meta=meta)
    with _LOCK:
        # one entry per file: the earlier states of a codebook saved in the editor (each with its index) go, not
        # kept in memory for good
        for k in [k for k in _CACHE if k[0] == key[0] and k != key]:
            del _CACHE[k]
        _CACHE[key] = fw
    return fw


def _folders(ws=None) -> list[tuple[Path, str]]:
    from .home import home

    out = [(home() / "frameworks", "home")]
    if ws is not None:
        # 0.17: a quick look can use the codebooks of the project it was opened from, read-only (its own labels stay
        # in the quick look); a codebook of the quick look itself comes after and wins
        from .home import project_path, quicklook_origin

        try:
            origin = quicklook_origin(Path(ws.root).name)
        except OSError:
            origin = None
        if origin and project_path(origin).resolve() != Path(ws.root).resolve():
            out.append((project_path(origin) / "frameworks", "origin"))
        out.append((Path(ws.root) / "frameworks", "project"))
    return out


def available(ws=None) -> dict[str, Framework]:
    """All frameworks a project can use: the bundled SDG targets, then home-wide, then the project's own."""
    out = {"sdg": _sdg(), "sdg_goals": _sdg_goals()}
    for folder, source in _folders(ws):
        if folder.is_dir():
            for p in sorted(folder.glob("*.csv")):
                fw = _load_file(p, source)
                if fw and NAME_RE.match(fw.name):
                    out[fw.name] = fw
    return out


def problems(ws=None) -> list[dict]:
    """Codebook files in the folders that could not be used, each with the reason: [{file, source, error}]. They are
    otherwise skipped without a word (0.14.3)."""
    out = []
    for folder, source in _folders(ws):
        if not folder.is_dir():
            continue
        for p in sorted(folder.glob("*.csv")):
            try:
                if not NAME_RE.match(p.stem.lower()):
                    raise ValueError("The file name must be a short name of letters, digits, - or _ (up to 40).")
                parse_csv(decode(p.read_bytes()), allow_empty=_editor_made(p))
            except (ValueError, OSError) as e:
                out.append({"file": p.name, "source": source, "error": str(e)})
    return out


def _editor_made(path: Path) -> bool:
    try:
        return bool(json.loads(path.with_suffix(".json").read_text(encoding="utf-8")).get("editor"))
    except (OSError, ValueError, AttributeError):
        return False


def get(name: str | None, ws=None) -> Framework | None:
    if not name:
        return None
    fw = available(ws).get(name)
    if fw is None:
        raise ValueError(f"Unknown framework {name!r}. Available: {', '.join(available(ws))}.")
    return fw


BUNDLED = ("sdg", "sdg_goals")


def save(ws, name: str, csv_text: str, title: str | None = None, label: str | None = None,
         directional: bool = False) -> Framework:
    """Add (or replace) a project framework from CSV text. `directional`: its codes are aims a text can help or
    hinder, so a profile says which."""
    n = (name or "").strip().lower().replace(" ", "_")
    if not NAME_RE.match(n) or n in BUNDLED:
        raise ValueError("Give the framework a short name: letters, digits, - or _ (and not 'sdg' or 'sdg_goals').")
    parse_csv(csv_text)  # validate before writing
    folder = Path(ws.root) / "frameworks"
    folder.mkdir(exist_ok=True)
    (folder / f"{n}.csv").write_text(csv_text.lstrip("﻿"), encoding="utf-8")
    meta = {k: v for k, v in (("title", title), ("label", label), ("directional", bool(directional) or None)) if v}
    side = folder / f"{n}.json"
    if meta:
        side.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    elif side.exists():
        side.unlink()
    fw = _load_file(folder / f"{n}.csv", "project")
    assert fw is not None
    return fw


def delete(ws, name: str) -> None:
    if not NAME_RE.match(name or "") or name in BUNDLED:
        raise KeyError(name)  # never a path: the name comes from a URL
    folder = Path(ws.root) / "frameworks"
    p = folder / f"{name}.csv"
    if not p.exists():
        raise KeyError(name)
    p.unlink()
    side = folder / f"{name}.json"
    if side.exists():
        side.unlink()


def resolve(ws, framework: str | None, code: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    """(framework, code, description, label) for a hypothesis; raises ValueError for an unknown code."""
    if not code:
        return (framework or None), None, None, None
    fw = get(framework or "sdg", ws)
    assert fw is not None
    c = fw.normalise(code)
    if not c:
        raise ValueError(f"Unknown {fw.label} {code!r} in {fw.title}.")
    return fw.name, c, fw.codes[c].description, fw.label
