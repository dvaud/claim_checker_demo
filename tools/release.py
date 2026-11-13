"""Release helper for the GitHub Actions workflow (.github/workflows/release.yml), also usable by hand (0.10).

    python tools/release.py check [v0.10.0]     # the tag, pyproject.toml, __init__.py and CHANGELOG.md agree
    python tools/release.py prerelease v0.15.0rc1   # "true" for a release candidate (0.15), else "false"
    python tools/release.py notes [0.10.0]      # the CHANGELOG entry of that version (the release notes)
    python tools/release.py assets dist         # next to the wheel in dist/: install.sh and install.ps1 with the
                                                # version filled in, the same as files to double-click
                                                # (Install-ENLENS-Windows.cmd, Install-ENLENS-macOS.zip; 0.14.5),
                                                # and SHA256SUMS of every file
    python tools/release.py fragments 0.18.1 "a title"   # 0.18.1: join changes/*.md into a new CHANGELOG entry
                                                # and delete them (--dry-run prints the entry and changes nothing)
    python tools/release.py fragments --check   # fails while changes/ still holds fragments (the release workflow)

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


def pyproject_version(root: Path = ROOT) -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (root / "pyproject.toml").read_text("utf-8"), re.M)
    if not m:
        raise ReleaseError("pyproject.toml has no version")
    return m.group(1)


def package_version(root: Path = ROOT) -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (root / "src" / "enlens_claims" / "__init__.py").read_text("utf-8"))
    if not m:
        raise ReleaseError("src/enlens_claims/__init__.py has no __version__")
    return m.group(1)


# 0.15: a version is X.Y.Z, or X.Y.ZrcN for a release candidate of X.Y.Z (published as a GitHub pre-release)
VERSION = r"\d+\.\d+\.\d+(?:rc\d+)?"


def changelog_versions(root: Path = ROOT) -> list[str]:
    return re.findall(rf"^## ({VERSION})(?![\w.])", (root / "CHANGELOG.md").read_text("utf-8"), re.M)


def is_prerelease(version: str) -> bool:
    """0.15: a release candidate (v0.15.0rc1) is published as a GitHub pre-release: the install line and the
    app's Update take the latest full release, so only someone who asks for it gets it."""
    return bool(re.fullmatch(r"v?\d+\.\d+\.\d+rc\d+", version.strip()))


def check(tag: str | None = None, root: Path = ROOT) -> str:
    """The version, when the tag (if given), pyproject.toml, __init__.py and the top CHANGELOG entry agree."""
    v = pyproject_version(root)
    problems = []
    if package_version(root) != v:
        problems.append(f"__init__.py says {package_version(root)}, pyproject.toml {v}")
    top = (changelog_versions(root) or ["(none)"])[0]
    if top != v:
        problems.append(f"the top entry of CHANGELOG.md is {top}, pyproject.toml says {v}")
    if tag and tag.lstrip("v") != v:
        problems.append(f"the tag is {tag}, pyproject.toml says {v}")
    if tag and not re.fullmatch(rf"v{VERSION}", tag):
        problems.append(f"the tag {tag} is not of the form v1.2.3 (or v1.2.3rc1 for a release candidate)")
    if problems:
        raise ReleaseError("; ".join(problems))
    return v


def notes(version: str | None = None, root: Path = ROOT) -> str:
    """The CHANGELOG entry of `version` (without its heading line), with how to install on top."""
    version = version or pyproject_version(root)
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


def assets(dist: Path, root: Path = ROOT) -> list[Path]:
    """Write the install scripts with the version filled in next to the wheel, the same as files to double-click,
    and SHA256SUMS of every file."""
    v = pyproject_version(root)
    dist.mkdir(parents=True, exist_ok=True)
    wheels = sorted(dist.glob("enlens_claims-*.whl"))
    if [w.name for w in wheels] != [f"enlens_claims-{v}-py3-none-any.whl"]:
        raise ReleaseError(f"dist/ should hold exactly enlens_claims-{v}-py3-none-any.whl, not {[w.name for w in wheels]}")
    for name in SCRIPTS:
        src = (root / "install" / name).read_text("utf-8")
        if "@ENLENS_VERSION@" not in src:
            raise ReleaseError(f"install/{name} has no @ENLENS_VERSION@ to fill in")
        out = dist / name
        out.write_bytes(src.replace("@ENLENS_VERSION@", v).encode("utf-8"))
    double_click_files(dist, v, root)
    files = sorted(p for p in dist.iterdir() if p.is_file() and p.name != "SHA256SUMS")
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


def main(argv: list[str]) -> int:
    try:
        if not argv or argv[0] not in ("check", "notes", "assets", "prerelease", "fragments"):
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
        elif argv[0] == "check":
            print(check(argv[1] if len(argv) > 1 and argv[1] else None))
        elif argv[0] == "prerelease":
            print("true" if is_prerelease(argv[1] if len(argv) > 1 else pyproject_version()) else "false")
        elif argv[0] == "notes":
            print(notes(argv[1] if len(argv) > 1 else None), end="")
        else:
            for p in assets(Path(argv[1] if len(argv) > 1 else "dist")):
                print(p)
    except ReleaseError as e:
        print(f"Release problem: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
