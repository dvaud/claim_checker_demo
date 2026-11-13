"""Release helper for the GitHub Actions workflow (.github/workflows/release.yml), also usable by hand (0.10).

    python tools/release.py check [v0.10.0]     # the tag and the top entry of CHANGELOG.md agree (0.18.1: the version
                                                # itself comes from the tag, built into the package by setuptools-scm)
    python tools/release.py prerelease v0.15.0rc1   # "true" for a release candidate (0.15), else "false"
    python tools/release.py notes [0.10.0]      # the CHANGELOG entry of that version (the release notes)
    python tools/release.py assets dist [--expect 0.18.1]   # next to the wheel in dist/: install.sh and install.ps1 with the
                                                # version filled in, the same as files to double-click
                                                # (Install-ENLENS-Windows.cmd, Install-ENLENS-macOS.zip; 0.14.5),
                                                # and SHA256SUMS of every file
    python tools/release.py fragments 0.18.1 "a title"   # 0.18.1: join changes/*.md into a new CHANGELOG entry
                                                # and delete them (--dry-run prints the entry and changes nothing)
    python tools/release.py fragments --check   # fails while changes/ still holds fragments (the release workflow)
    python tools/release.py prepare 0.18.1 "a title" [--go]   # 0.18.1 (J1.5): the release pull request: a branch
                                                # release/0.18.1 with the fragments joined, README's New in and the
                                                # app's What's new written from the entry, and `gh pr create`.
                                                # Without --go it is a dry run: it prints the steps and the entry
    python tools/release.py sync-notes [0.18.1]   # rewrite README's New in and whats-new.md from the changelog entry
    python tools/release.py sync-notes --check   # fails when they do not match the newest entry (a test runs it too)

Exit code 1 with a plain message when something does not agree, so the workflow stops before building.
"""
from __future__ import annotations

import hashlib
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ("install.sh", "install.ps1")
# 0.14.5: the install as files to double-click, for whoever would rather not open Terminal or PowerShell
WINDOWS_FILE = "Install-ENLENS-Windows.cmd"  # install/Install-ENLENS-Windows.cmd with install.ps1 below it
MAC_FILE = "Install-ENLENS-macOS.zip"        # holds install.sh as MAC_COMMAND, which Terminal runs on a double-click
MAC_COMMAND = "Install ENLENS.command"


class ReleaseError(Exception):
    pass


# 0.15: a version is X.Y.Z, or X.Y.ZrcN for a release candidate of X.Y.Z (published as a GitHub pre-release)
VERSION = r"\d+\.\d+\.\d+(?:rc\d+)?"


def changelog_versions(root: Path = ROOT) -> list[str]:
    return re.findall(rf"^## ({VERSION})(?![\w.])", (root / "CHANGELOG.md").read_text("utf-8"), re.M)


def is_prerelease(version: str) -> bool:
    """0.15: a release candidate (v0.15.0rc1) is published as a GitHub pre-release: the install line and the
    app's Update take the latest full release, so only someone who asks for it gets it."""
    return bool(re.fullmatch(r"v?\d+\.\d+\.\d+rc\d+", version.strip()))


def release_version(root: Path = ROOT) -> str:
    """0.18.1 (J1.3): the version being released is the top entry of CHANGELOG.md. It stands in no source file: the
    package's version is made from the git tag when it is built (setuptools-scm)."""
    versions = changelog_versions(root)
    if not versions:
        raise ReleaseError("CHANGELOG.md has no entry for any version")
    return versions[0]


def check(tag: str | None = None, root: Path = ROOT) -> str:
    """The version, when the tag (if given) and the top CHANGELOG entry agree. Returns the top entry's version."""
    v = release_version(root)
    problems = []
    if tag and tag.lstrip("v") != v:
        problems.append(f"the tag is {tag}, but the top entry of CHANGELOG.md is {v}")
    if tag and not re.fullmatch(rf"v{VERSION}", tag):
        problems.append(f"the tag {tag} is not of the form v1.2.3 (or v1.2.3rc1 for a release candidate)")
    if problems:
        raise ReleaseError("; ".join(problems))
    return v


def notes(version: str | None = None, root: Path = ROOT) -> str:
    """The CHANGELOG entry of `version` (without its heading line), with how to install on top."""
    version = version or release_version(root)
    text = (root / "CHANGELOG.md").read_text("utf-8")
    m = re.search(rf"^## {re.escape(version)}(?![\w.])[^\n]*\n(.*?)(?=^## \d|\Z)", text, re.M | re.S)
    if not m:
        raise ReleaseError(f"CHANGELOG.md has no entry for {version}")
    repo = "dvaud/claim_checker_demo"
    files = f"https://github.com/{repo}/releases/download/v{version}"
    # 0.15: a release candidate's lines name its own files: "latest" is the latest full release
    lines = files if is_prerelease(version) else f"https://github.com/{repo}/releases/latest/download"
    final = re.sub(r"rc\d+$", "", version)
    head = (f"**This is a release candidate** of ENLENS {final}, to try before it becomes the release. The install "
            f"line on the ENLENS page and *Update* in the app keep giving the latest full release; the lines below "
            f"install this one. When {final} itself is out, *Update* offers it.\n\n"
            if is_prerelease(version) else "")
    head += (f"**Install or update** (your projects stay where they are):\n\n"
            f"| System | Paste this |\n| --- | --- |\n"
            f"| macOS, Linux (Terminal) | `curl -fsSL {lines}/install.sh \\| sh` |\n"
            f"| Windows (PowerShell) | `powershell -ExecutionPolicy Bypass -c \"irm {lines}/install.ps1 \\| iex\"` |\n\n"
            "**Or download a file and double-click it** (it does the same as the line):\n\n"
            f"- **Windows:** [{WINDOWS_FILE}]({files}/{WINDOWS_FILE}). If the browser warns about the file, keep it; "
            "if Windows says it protected your PC, click *More info*, then *Run anyway*. Quit ENLENS before updating.\n"
            f"- **macOS:** [{MAC_FILE}]({files}/{MAC_FILE}). Open it and double-click *{MAC_COMMAND}*. The first "
            "time, macOS says it could not verify the file: click *Done*, open *System Settings → Privacy & "
            f"Security*, click *Open Anyway* next to *{MAC_COMMAND}* and confirm.\n\n"
            "A git copy updates with `enlens update`. `SHA256SUMS` lists the checksum of every file.\n\n---\n\n")
    return head + m.group(1).strip() + "\n"


def assets(dist: Path, root: Path = ROOT, expect: str | None = None) -> list[Path]:
    """Write the install scripts with the version filled in next to the wheel, the same as files to double-click,
    and SHA256SUMS of every file. 0.18.1: the version is the wheel's own (made from the tag when it was built); with
    `expect` (the tag's version) a wheel of another version stops the release. Without it (a test build by hand, which
    on a commit after a tag is 0.18.0.post3) whatever single wheel is there sets the version."""
    dist.mkdir(parents=True, exist_ok=True)
    wheels = sorted(dist.glob("enlens_claims-*.whl"))
    if expect:
        v = expect.lstrip("v")
        if [w.name for w in wheels] != [f"enlens_claims-{v}-py3-none-any.whl"]:
            raise ReleaseError(f"dist/ should hold exactly enlens_claims-{v}-py3-none-any.whl, not "
                               f"{[w.name for w in wheels]} (the package's version is made from the tag: build at the tag)")
    else:
        m = re.fullmatch(r"enlens_claims-(.+)-py3-none-any\.whl", wheels[0].name) if len(wheels) == 1 else None
        if not m:
            raise ReleaseError(f"dist/ should hold exactly one enlens_claims-<version>-py3-none-any.whl, not {[w.name for w in wheels]}")
        v = m.group(1)
    for name in SCRIPTS:
        src = (root / "install" / name).read_text("utf-8")
        if "@ENLENS_VERSION@" not in src:
            raise ReleaseError(f"install/{name} has no @ENLENS_VERSION@ to fill in")
        out = dist / name
        out.write_bytes(src.replace("@ENLENS_VERSION@", v).encode("utf-8"))
    double_click_files(dist, v, root)
    # (`uv build` leaves a .gitignore in its output folder: not a file of the release)
    files = sorted(p for p in dist.iterdir() if p.is_file() and p.name != "SHA256SUMS" and not p.name.startswith("."))
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in files]
    (dist / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return files + [dist / "SHA256SUMS"]


def double_click_files(dist: Path, v: str, root: Path = ROOT) -> list[Path]:
    """0.14.5: the install scripts already in `dist` as files to double-click.

    - Windows: cmd runs the head (install/Install-ENLENS-Windows.cmd) up to its `exit /b`; the head has PowerShell
      read the whole file, in which the head is one comment, `<# … #>`, and install.ps1 follows. One file, nothing
      else downloaded, and the release's Windows machine can try it before the release exists.
    - macOS: install.sh as "Install ENLENS.command" (Terminal runs a .command on a double-click), in a zip, which
      keeps its "may run" mark: a browser drops it from a bare download. Gatekeeper still asks once, since the file
      is not signed by an Apple developer.
    """
    head = (root / "install" / WINDOWS_FILE).read_text("utf-8").replace("@ENLENS_VERSION@", v)
    lines = head.rstrip("\n").split("\n")
    if not lines[0].startswith("<# :") or "#>" in "\n".join(lines[:-1]) or not lines[-1].endswith("#>"):
        raise ReleaseError(f"install/{WINDOWS_FILE} must start with '<# :' and hold '#>' only at the end of its last line")
    text = "\n".join(lines) + "\n" + (dist / "install.ps1").read_text("utf-8")
    if not text.isascii():
        raise ReleaseError(f"{WINDOWS_FILE} must be plain ASCII: cmd reads it in the console's code page")
    (dist / WINDOWS_FILE).write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii"))
    entry = zipfile.ZipInfo(MAC_COMMAND, date_time=time.localtime()[:6])
    entry.create_system = 3                    # Unix, so that the mode below is read
    entry.external_attr = 0o100755 << 16       # a file anyone may run
    entry.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(dist / MAC_FILE, "w") as z:
        z.writestr(entry, (dist / "install.sh").read_bytes())
    return [dist / WINDOWS_FILE, dist / MAC_FILE]


# 0.18.1 (roadmap J1.4): changelog fragments. Each change adds a small file, changes/<topic>.md, instead of editing
# CHANGELOG.md, so two branches never edit the same lines of it. A fragment is made of "### <Section>" headings, each
# followed by its text; the release joins them into one new entry and deletes them. Sections of the same name (in any
# case) from several fragments become one; FIRST come first, LAST last, any other in the order they first appear.
CHANGES = "changes"
FIRST = ("New", "Changes that can alter your results")
LAST = ("Fixed", "Privacy", "For developers", "Tests", "Not yet done")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def fragment_files(root: Path = ROOT) -> list[Path]:
    folder = root / CHANGES
    return sorted(p for p in folder.glob("*.md") if p.name != "README.md") if folder.is_dir() else []


def _join(a: str, b: str) -> str:
    # two lists run on as one list; anything else is a paragraph of its own
    return a + ("\n" if a.lstrip().startswith("- ") and b.lstrip().startswith("- ") else "\n\n") + b


def fragments_entry(version: str, title: str, root: Path = ROOT, month: str | None = None) -> str:
    """The new CHANGELOG entry made from changes/*.md (not written)."""
    files = fragment_files(root)
    if not files:
        raise ReleaseError(f"{CHANGES}/ holds no fragments")
    if not re.fullmatch(VERSION, version):
        raise ReleaseError(f"{version} is not of the form 1.2.3 (or 1.2.3rc1)")
    if version in changelog_versions(root):
        raise ReleaseError(f"CHANGELOG.md already has an entry for {version}")
    if not title.strip():
        raise ReleaseError("the entry needs a title")
    names: dict[str, str] = {}     # lower case -> the name as first written
    parts: dict[str, list[str]] = {}
    for f in files:
        current, lines = None, []

        def keep():
            text = "\n".join(lines).strip()
            if current is not None and text:
                parts.setdefault(current, []).append(text)

        for line in f.read_text("utf-8").splitlines():
            m = re.match(r"^###\s+(.+?)\s*$", line)
            if m:
                keep()
                name = m.group(1)
                canon = next((c for c in FIRST + LAST if c.lower() == name.lower()), name)
                current, lines = names.setdefault(canon.lower(), canon).lower(), []
            elif line.startswith("#"):
                raise ReleaseError(f"{CHANGES}/{f.name}: only '### Section' headings belong in a fragment: {line!r}")
            elif current is None and line.strip():
                raise ReleaseError(f"{CHANGES}/{f.name}: text before its first '### Section' heading")
            else:
                lines.append(line)
        keep()
    if not parts:
        raise ReleaseError(f"the fragments in {CHANGES}/ are empty")
    first = [c.lower() for c in FIRST if c.lower() in parts]
    last = [c.lower() for c in LAST if c.lower() in parts]
    middle = [k for k in parts if k not in first and k not in last]
    month = month or f"{MONTHS[time.localtime().tm_mon - 1]} {time.localtime().tm_year}"
    out = f"## {version} ({month}): {title.strip()}\n"
    for key in first + middle + last:
        body = parts[key][0]
        for more in parts[key][1:]:
            body = _join(body, more)
        out += f"\n### {names[key]}\n\n{body}\n"
    return out


def join_fragments(version: str, title: str, root: Path = ROOT, month: str | None = None) -> str:
    """Write the entry at the top of CHANGELOG.md and delete the fragments. Returns the entry."""
    entry = fragments_entry(version, title, root, month)
    path = root / "CHANGELOG.md"
    text = path.read_text("utf-8")
    m = re.search(r"^## ", text, re.M)
    at = m.start() if m else len(text)
    path.write_text(text[:at] + entry + "\n" + text[at:], encoding="utf-8")
    for f in fragment_files(root):
        f.unlink()
    return entry


def no_fragments_left(root: Path = ROOT) -> None:
    files = fragment_files(root)
    if files:
        raise ReleaseError(f"{CHANGES}/ still holds {len(files)} fragment(s) ({', '.join(f.name for f in files)}): "
                           f'run `python tools/release.py fragments <version> "<title>"` first')


# 0.18.1 (roadmap J1.5, J2.5): the release pull request. `prepare` does all the typing of a release: it joins the
# fragments into the changelog, writes the README's *New in* and the app's *What's new* from that entry (so the three
# never drift apart), commits them on a branch release/X.Y.Z and opens a pull request. Merging the pull request tags
# the merge commit (.github/workflows/tag-release.yml), and the tag starts release.yml.
README = "README.md"
WHATS_NEW = Path("src") / "enlens_claims" / "gui" / "static" / "whats-new.md"
NEW_IN_START = "<!-- new-in:start (written by `python tools/release.py prepare`: change the changelog entry, not this) -->"
NEW_IN_END = "<!-- new-in:end -->"
README_POINTS = 5     # the README's New in: three to five bullets (docs/DEVELOPING.md, The README)
WHATS_NEW_POINTS = 6  # What's new: a few, each extremely short
NO_SUBTITLE = "What changed since the last release."


def entry_text(version: str, root: Path = ROOT) -> str:
    """The changelog entry of `version`, heading line included."""
    text = (root / "CHANGELOG.md").read_text("utf-8")
    m = re.search(rf"^## {re.escape(version)}(?![\w.])[^\n]*\n.*?(?=^## \d|\Z)", text, re.M | re.S)
    if not m:
        raise ReleaseError(f"CHANGELOG.md has no entry for {version}")
    return m.group(0)


def entry_parts(entry: str) -> tuple[str, str, list[tuple[str, str]]]:
    """(title, opening paragraph, [(section name, body)]) of an entry. Only the `###` sections count: a candidate's
    own `####` parts stay inside their section."""
    head, _, rest = entry.partition("\n")
    m = re.match(r"^## \S+(?: \([^)]*\))?:\s*(.+?)\s*$", head)
    if not m:
        raise ReleaseError(f"the entry's heading is not '## X.Y.Z (Month Year): Title': {head!r}")
    pieces = re.split(r"^###[ \t]+(.+?)[ \t]*$", rest, flags=re.M)
    sections = [(pieces[i].strip(), pieces[i + 1]) for i in range(1, len(pieces) - 1, 2)]
    return m.group(1), pieces[0].strip(), sections


def _bullets(body: str) -> list[str]:
    """The top-level `- **Headline** …` bullets of a section, each as one line of text."""
    out: list[str] = []
    open_bullet = False
    for line in body.splitlines():
        if line.startswith("- **"):
            out.append(line[2:].strip())
            open_bullet = True
        elif open_bullet and line.startswith("  ") and line.strip():
            out[-1] += " " + line.strip()
        else:
            open_bullet = open_bullet and bool(line.strip()) and line.startswith(" ")
    return out


def _balanced(text: str) -> bool:
    return text.count("(") == text.count(")") and text.count("*") % 2 == 0


def _first_sentence(text: str, limit: int = 200) -> str:
    """The first sentence of `text` (a short one such as "(roadmap N1)." takes the next with it), cut at a clause
    when it is longer than `limit`: never inside a bracket or an italic."""
    text = re.sub(r"\s+", " ", text).strip()
    sentence, rest = "", text
    while rest and len(sentence) < 30:
        m = re.search(r"(?<=[.!?])\s+(?=[A-Z*(“\"])", rest)
        piece, rest = (rest[:m.start()], rest[m.end():]) if m else (rest, "")
        sentence = f"{sentence} {piece}".strip()
    if len(sentence) > limit:
        cuts = [m.start() for m in re.finditer(r"[,;:]\s", sentence[:limit]) if _balanced(sentence[:m.start()])]
        if cuts and cuts[-1] > limit // 2:
            sentence = sentence[:cuts[-1]] + "."
        else:
            sentence = sentence[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return sentence


def _headline(bullet: str) -> tuple[str, str]:
    """('Headline', the text after it) of a `**Headline.** text` bullet."""
    m = re.match(r"\*\*(.+?)\*\*(.*)$", bullet, re.S)
    return (m.group(1).strip(), m.group(2).strip()) if m else (bullet.strip(), "")


def entry_bullets(entry: str) -> list[str]:
    """The bullets that say what is new: those of the sections *New…* and *Changes that can alter your results*; when
    there are none, of the other sections that are not about the code or the tests; when there are none, *Fixed*."""
    _, _, sections = entry_parts(entry)
    skip = tuple(n.lower() for n in LAST if n != "Fixed")
    new = [b for n, body in sections if re.match(r"(new\b|changes that can alter)", n, re.I) for b in _bullets(body)]
    other = [b for n, body in sections if not re.match(r"(new\b|changes that can alter|from the|defect|fixed)", n, re.I)
             and n.lower() not in skip for b in _bullets(body)]
    fixed = [b for n, body in sections if re.match(r"(fixed|defect)", n, re.I) for b in _bullets(body)]
    return new or other or fixed


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def readme_new_in(version: str, root: Path = ROOT) -> str:
    """The README's *New in* section (between its markers) for `version`, written from its changelog entry."""
    title, _, _ = entry_parts(entry_text(version, root))
    lines = []
    for bullet in entry_bullets(entry_text(version, root))[:README_POINTS]:
        head, rest = _headline(bullet)
        sentence = _first_sentence(rest)
        joiner = "" if sentence[:1] in ",;:)" else " "
        line = f"- **{head}**{joiner}{sentence}".rstrip()
        verdict = re.search(r"\b(can|cannot) change results", bullet, re.I)
        if verdict and verdict.group(0).lower() not in line.lower():
            line += ("" if line.endswith((".", "…")) else ".") + f" {_capital(verdict.group(0).lower())}."
        lines.append(line)
    if not lines:
        raise ReleaseError(f"the entry of {version} has no bullets to write the README's New in from")
    return (f"{NEW_IN_START}\n## New in {version}: {title}\n\n" + "\n".join(lines) + f"\n{NEW_IN_END}")


def whats_new_text(version: str, root: Path = ROOT) -> str:
    """The app's *What's new* note (gui/static/whats-new.md) for `version`: `# X.Y.Z: Title`, `*subtitle*`, and a few
    extremely short points, the headlines of the entry's bullets."""
    entry = entry_text(version, root)
    title, intro, _ = entry_parts(entry)
    sub = _first_sentence(intro, 120).replace("*", "") if intro else ""
    if sub.endswith("…"):      # cut in the middle of a thought: no subtitle is better than half of one
        sub = ""
    points = []
    for bullet in entry_bullets(entry)[:WHATS_NEW_POINTS]:
        head = _headline(bullet)[0].replace("**", "").replace("*", "")
        points.append("- " + (head.rstrip(".") if len(head) > 3 else head))
    if not points:
        raise ReleaseError(f"the entry of {version} has no bullets to write What's new from")
    return f"# {version}: {_capital(title)}\n*{sub or NO_SUBTITLE}*\n" + "\n".join(points) + "\n"


def write_readme_new_in(version: str, root: Path = ROOT) -> bool:
    """Replace what stands between the README's markers. True when the README changed."""
    path = root / README
    text = path.read_text("utf-8")
    m = re.search(rf"{re.escape(NEW_IN_START.split(' (')[0])}[^\n]*\n.*?{re.escape(NEW_IN_END)}", text, re.S)
    if not m:
        raise ReleaseError(f"{README} has no {NEW_IN_START.split(' (')[0]} … {NEW_IN_END} to write New in into")
    new = text[:m.start()] + readme_new_in(version, root) + text[m.end():]
    path.write_text(new, encoding="utf-8")
    return new != text


def sync_notes(version: str | None = None, root: Path = ROOT, check_only: bool = False) -> list[str]:
    """Write (or with `check_only`, only compare) the README's *New in* and *What's new* from the changelog entry of
    `version` (default: the newest). Returns the files that differ / were changed."""
    version = version or release_version(root)
    changed = []
    readme = root / README
    text = readme.read_text("utf-8")
    m = re.search(rf"{re.escape(NEW_IN_START.split(' (')[0])}[^\n]*\n.*?{re.escape(NEW_IN_END)}", text, re.S)
    if not m:
        raise ReleaseError(f"{README} has no {NEW_IN_START.split(' (')[0]} … {NEW_IN_END} to write New in into")
    if m.group(0) != readme_new_in(version, root):
        changed.append(README)
        if not check_only:
            write_readme_new_in(version, root)
    note = root / WHATS_NEW
    wanted = whats_new_text(version, root)
    # a check compares the version only: the note is written by hand once in a while, and a person may edit it
    current = note.read_text("utf-8").splitlines()[0] if note.exists() else ""
    differs = (current != wanted.splitlines()[0]) if check_only else (not note.exists() or note.read_text("utf-8") != wanted)
    if differs:
        changed.append(str(WHATS_NEW).replace("\\", "/"))
        if not check_only:
            note.write_text(wanted, encoding="utf-8")
    return changed


def _run(cmd: list[str], root: Path) -> str:
    import subprocess

    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise ReleaseError(f"`{' '.join(cmd)}` failed: {(r.stderr or r.stdout).strip()[-1500:]}")
    return r.stdout.strip()


def pull_request_body(version: str, title: str, root: Path = ROOT) -> str:
    return (f"The release of ENLENS {version}: {title}.\n\n"
            "Written by `python tools/release.py prepare`: the changes/ fragments joined into the new CHANGELOG entry, "
            "and the README's *New in* and the app's *What's new* written from that entry.\n\n"
            "Before merging, read the entry, write its opening paragraph (and, if it changed, run "
            "`python tools/release.py sync-notes` to rewrite *New in* and *What's new* from it), and wait for the "
            "Tests run to be green. Merging tags the merge commit `v" + version + "` and starts the release workflow, "
            "which drafts the GitHub Release for you to publish.\n")


def prepare(version: str, title: str, root: Path = ROOT, dry_run: bool = True, run=_run) -> list[str]:
    """The release pull request (J1.5). Dry run: nothing is written and nothing is run; the steps are returned. For
    real: a clean working tree is required; a branch release/<version> gets one commit, is pushed, and `gh pr create`
    opens the pull request against main. `run(cmd, root)` runs a command (the tests pass a recorder)."""
    if not re.fullmatch(VERSION, version):
        raise ReleaseError(f"{version} is not of the form 1.2.3 (or 1.2.3rc1)")
    entry = fragments_entry(version, title, root)       # refuses without fragments, a twice-used version, no title
    branch = f"release/{version}"
    steps = [f"git switch -c {branch}",
             f"join the fragments of {CHANGES}/ into CHANGELOG.md ({len(fragment_files(root))} files)",
             f"write {README}'s New in and {WHATS_NEW} from the entry",
             f"git add CHANGELOG.md {README} {WHATS_NEW} {CHANGES}",
             f'git commit -m "ENLENS {version}: {title}"',
             f"git push -u origin {branch}",
             f'gh pr create --base main --head {branch} --title "ENLENS {version}" --body-file <the text below>']
    if dry_run:
        return steps + ["", entry.rstrip("\n")]
    if run(["git", "status", "--porcelain", "--untracked-files=no"], root):
        raise ReleaseError("the working tree has changes: commit or stash them before preparing a release")
    # what is released is main as GitHub has it: not a feature branch's commits, nor another session's fragments
    # that are not committed yet (the shared clone)
    run(["git", "fetch", "--quiet", "origin", "main"], root)
    here, there = (run(["git", "rev-parse", ref], root).strip() for ref in ("HEAD", "origin/main"))
    if here != there:
        raise ReleaseError("prepare a release from main as it is on GitHub: switch to main and pull first "
                           f"(HEAD is {here[:10]}, origin/main is {there[:10]})")
    loose = run(["git", "status", "--porcelain", "--untracked-files=all", "--", CHANGES], root)
    if loose.strip():
        raise ReleaseError(f"{CHANGES}/ has files that are not committed (another session's work?):\n{loose.strip()}\n"
                           "commit them on main first, or move them away")
    run(["git", "switch", "-c", branch], root)
    join_fragments(version, title, root)
    sync_notes(version, root)
    run(["git", "add", "CHANGELOG.md", README, str(WHATS_NEW).replace("\\", "/"), CHANGES], root)
    run(["git", "commit", "-m", f"ENLENS {version}: {title}"], root)
    run(["git", "push", "-u", "origin", branch], root)
    run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", f"ENLENS {version}",
         "--body", pull_request_body(version, title, root)], root)
    return steps


def main(argv: list[str]) -> int:
    try:
        if not argv or argv[0] not in ("check", "notes", "assets", "prerelease", "fragments", "prepare", "sync-notes"):
            print(__doc__)
            return 2
        if argv[0] == "fragments":
            args = [a for a in argv[1:] if not a.startswith("--")]
            if "--check" in argv:
                no_fragments_left()
                print(f"{CHANGES}/ holds no fragments")
            elif len(args) != 2:
                print(__doc__)
                return 2
            elif "--dry-run" in argv:
                print(fragments_entry(args[0], args[1]), end="")
            else:
                print(join_fragments(args[0], args[1]), end="")
        elif argv[0] == "prepare":
            args = [a for a in argv[1:] if not a.startswith("--")]
            if len(args) != 2:
                print(__doc__)
                return 2
            # a dry run is the default for a person who forgot the flag's meaning: only --go does it for real
            for line in prepare(args[0], args[1], dry_run="--go" not in argv):
                print(line)
            if "--go" not in argv:
                print("\n(a dry run: nothing was changed. Add --go to make the branch and the pull request.)")
        elif argv[0] == "sync-notes":
            args = [a for a in argv[1:] if not a.startswith("--")]
            changed = sync_notes(args[0] if args else None, check_only="--check" in argv)
            if "--check" in argv and changed:
                raise ReleaseError(f"{', '.join(changed)} do not match the newest entry of CHANGELOG.md: run "
                                   "`python tools/release.py sync-notes`")
            print("written: " + ", ".join(changed) if changed and "--check" not in argv else "README.md and whats-new.md match")
        elif argv[0] == "check":
            print(check(argv[1] if len(argv) > 1 and argv[1] else None))
        elif argv[0] == "prerelease":
            print("true" if is_prerelease(argv[1] if len(argv) > 1 else release_version()) else "false")
        elif argv[0] == "notes":
            print(notes(argv[1] if len(argv) > 1 else None), end="")
        else:
            rest = [a for a in argv[1:]]
            expect = rest[rest.index("--expect") + 1] if "--expect" in rest and rest.index("--expect") + 1 < len(rest) else None
            if expect:
                rest = [a for a in rest if a not in ("--expect", expect)]
            for p in assets(Path(rest[0] if rest else "dist"), expect=expect):
                print(p)
    except ReleaseError as e:
        print(f"Release problem: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
