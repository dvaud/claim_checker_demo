"""Release helper for the GitHub Actions workflow (.github/workflows/release.yml), also usable by hand (0.10).

    python tools/release.py check [v0.10.0]     # the tag, pyproject.toml, __init__.py and CHANGELOG.md agree
    python tools/release.py notes [0.10.0]      # the CHANGELOG entry of that version (the release notes)
    python tools/release.py assets dist         # next to the wheel in dist/: install.sh and install.ps1 with the
                                                # version filled in, and SHA256SUMS of every file

Exit code 1 with a plain message when something does not agree, so the workflow stops before building.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ("install.sh", "install.ps1")


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


def changelog_versions(root: Path = ROOT) -> list[str]:
    return re.findall(r"^## (\d+\.\d+\.\d+)\b", (root / "CHANGELOG.md").read_text("utf-8"), re.M)


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
    if tag and not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        problems.append(f"the tag {tag} is not of the form v1.2.3")
    if problems:
        raise ReleaseError("; ".join(problems))
    return v


def notes(version: str | None = None, root: Path = ROOT) -> str:
    """The CHANGELOG entry of `version` (without its heading line), with how to install on top."""
    version = version or pyproject_version(root)
    text = (root / "CHANGELOG.md").read_text("utf-8")
    m = re.search(rf"^## {re.escape(version)}\b[^\n]*\n(.*?)(?=^## \d|\Z)", text, re.M | re.S)
    if not m:
        raise ReleaseError(f"CHANGELOG.md has no entry for {version}")
    repo = "dvaud/claim_checker_demo"
    head = (f"**Install or update** (your projects stay where they are):\n\n"
            f"| System | Paste this |\n| --- | --- |\n"
            f"| macOS, Linux (Terminal) | `curl -fsSL https://github.com/{repo}/releases/latest/download/install.sh \\| sh` |\n"
            f"| Windows (PowerShell) | `powershell -ExecutionPolicy Bypass -c \"irm https://github.com/{repo}/releases/latest/download/install.ps1 \\| iex\"` |\n\n"
            "A git copy updates with `enlens update`. `SHA256SUMS` lists the checksum of every file.\n\n---\n\n")
    return head + m.group(1).strip() + "\n"


def assets(dist: Path, root: Path = ROOT) -> list[Path]:
    """Write the install scripts with the version filled in next to the wheel, and SHA256SUMS of every file."""
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
    files = sorted(p for p in dist.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in files]
    (dist / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return files + [dist / "SHA256SUMS"]


def main(argv: list[str]) -> int:
    try:
        if not argv or argv[0] not in ("check", "notes", "assets"):
            print(__doc__)
            return 2
        if argv[0] == "check":
            print(check(argv[1] if len(argv) > 1 and argv[1] else None))
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
