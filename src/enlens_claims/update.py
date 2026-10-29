"""Updating ENLENS in place (0.8.2): `enlens update`.

ENLENS installed once from a git copy (`git clone …`, a venv, `pip install -e .`) never needs a new folder or a new
venv for a new version: the editable install runs the code in the git copy, so fetching the new version is enough.
`enlens update` does that safely:

1. finds the git copy this ENLENS runs from (it refuses a copy installed from a zip or from PyPI, and says why);
2. stops if files of the copy were changed by hand (so an update never overwrites them);
3. fetches and moves forward only (`git merge --ff-only`): nothing is merged or rewritten;
4. runs `pip install -e .` again only when `pyproject.toml` changed (new dependencies or commands), with the extras
   already installed (connector, fast, ocr, …), into the same Python;
5. refreshes the Claude Code plugin in the data folder if `enlens claude-setup` wrote one;
6. says to restart the app if it is running (the browser is told not to cache the page, so a restart is all).

The data folder (ENLENS_HOME, default ~/enlens) is never touched: projects, settings and history stay where they are.
`enlens update --check` only says whether a newer version is waiting.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

Runner = Callable[[list[str], Path], subprocess.CompletedProcess]


class UpdateError(Exception):
    """An update that cannot go ahead; the message says what to do."""


def source_root() -> Path | None:
    """The git copy this ENLENS runs from (src/enlens_claims/ → the folder with pyproject.toml), or None."""
    root = Path(__file__).resolve().parent.parent.parent
    if (root / "pyproject.toml").is_file() and (root / ".git").exists():
        return root
    return None


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def _git(run: Runner, root: Path, *args: str) -> str:
    r = run(["git", *args], root)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        raise UpdateError(f"git {' '.join(args)} failed: {msg}")
    return (r.stdout or "").rstrip()  # rstrip: porcelain lines start with a space


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def version_in(root: Path) -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (root / "src" / "enlens_claims" / "__init__.py").read_text("utf-8"))
    return m.group(1) if m else "?"


def installed_extras(pyproject: Path) -> list[str]:
    """The optional dependency groups whose packages are all installed in this Python (to keep them on reinstall)."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover - 3.10
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return []
    from importlib import metadata

    try:
        extras = tomllib.loads(pyproject.read_text("utf-8")).get("project", {}).get("optional-dependencies", {})
    except (OSError, ValueError):
        return []
    keep = []
    for name, reqs in extras.items():
        if not reqs:
            continue
        dists = [re.split(r"[<>=!~\[; ]", r.strip(), maxsplit=1)[0] for r in reqs]
        try:
            for d in dists:
                metadata.version(d)
        except metadata.PackageNotFoundError:
            continue
        keep.append(name)
    return sorted(keep)


def update(check_only: bool = False, root: Path | None = None, run: Runner = _run,
           python: str | None = None) -> dict:
    """Bring the git copy up to date (see the module's notes). Returns what happened, for printing."""
    root = root or source_root()
    if root is None:
        raise UpdateError("This ENLENS was not installed from a git copy, so it cannot update itself. Install it once "
                          "from GitHub (git clone, then pip install -e . in a venv; see the README, 'Updating'); "
                          "after that `enlens update` is all a new version needs.")
    if shutil.which("git") is None and run is _run:
        raise UpdateError("git is not installed on this computer (macOS: run `xcode-select --install`).")
    changed = _git(run, root, "status", "--porcelain", "--untracked-files=no")
    if changed:
        files = [line[3:] for line in changed.splitlines()]
        raise UpdateError("These files of ENLENS were changed on this computer, so the update stops rather than "
                          f"overwrite them: {', '.join(files)}. Keep the changes with `git stash` (in {root}) or "
                          "undo them with `git checkout -- .`, then run `enlens update` again.")
    try:
        upstream = _git(run, root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    except UpdateError:
        raise UpdateError("This git copy follows no branch on GitHub. In it, run "
                          "`git branch --set-upstream-to=origin/main` (or the branch you use), then try again.")
    _git(run, root, "fetch", "--quiet")
    before = version_in(root)
    waiting = int(_git(run, root, "rev-list", "--count", f"HEAD..{upstream}") or 0)
    if not waiting:
        return {"updated": False, "version": before, "message": f"ENLENS {before} is up to date."}
    if check_only:
        return {"updated": False, "version": before, "waiting": waiting,
                "message": f"A newer ENLENS is waiting ({waiting} change{'s' if waiting != 1 else ''}). Run `enlens update`."}
    ahead = int(_git(run, root, "rev-list", "--count", f"{upstream}..HEAD") or 0)
    if ahead:
        raise UpdateError(f"This copy has {ahead} commit(s) of its own that are not on GitHub, so it cannot simply move "
                          f"forward. Push them first (`git push` in {root}) or ask for help.")
    py = root / "pyproject.toml"
    deps_before = _digest(py)
    _git(run, root, "merge", "--ff-only", "--quiet", upstream)
    after = version_in(root)
    out: dict = {"updated": True, "from": before, "version": after, "reinstalled": False}
    if _digest(py) != deps_before:
        extras = installed_extras(py)
        target = f"{root}[{','.join(extras)}]" if extras else str(root)
        r = run([python or sys.executable, "-m", "pip", "install", "--quiet", "-e", target], root)
        if r.returncode != 0:
            raise UpdateError(f"ENLENS {after} was fetched, but installing its new requirements failed:\n"
                              f"{(r.stderr or r.stdout or '').strip()[-2000:]}\nRun `enlens update` again when online.")
        out["reinstalled"] = True
        out["extras"] = extras
    out["plugin"] = _refresh_plugin()
    out["running"] = _app_running()
    notes = [f"ENLENS updated from {before} to {after}."]
    if out["reinstalled"]:
        notes.append("Its requirements changed and were installed into the same Python (no new venv).")
    if out["plugin"]:
        notes.append("The Claude Code plugin was refreshed; in Claude Code run `/plugin marketplace update enlens`.")
    notes.append("ENLENS is running: choose Quit ENLENS in the app and open it again." if out["running"]
                 else "Open ENLENS as usual.")
    out["message"] = " ".join(notes)
    return out


def _refresh_plugin() -> bool:
    try:
        from . import claude_setup
        from . import home

        if home.local_only() or not claude_setup.folder().exists():
            return False
        claude_setup.write_plugin()
        return True
    except Exception:  # noqa: BLE001 - the update itself succeeded; the plugin can be set up again by hand
        return False


def _app_running() -> bool:
    try:
        from .gui import launcher

        return launcher.running() is not None
    except Exception:  # noqa: BLE001
        return False
