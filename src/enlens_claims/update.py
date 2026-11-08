"""Updating ENLENS in place (0.8.2): `enlens update`.

ENLENS installed once from a git copy (`git clone …`, a venv, `pip install -e .`) never needs a new folder or a new
venv for a new version: the editable install runs the code in the git copy, so fetching the new version is enough.
`enlens update` does that safely:

1. finds the git copy this ENLENS runs from (it refuses a copy installed from a zip or from PyPI, and says why);
2. stops if files of the copy were changed by hand (so an update never overwrites them);
3. fetches and moves forward only (`git merge --ff-only`): nothing is merged or rewritten;
4. runs `pip install -e .` again only when `pyproject.toml` changed (new dependencies or commands), with the extras
   already installed (connector, fast, ocr, …) and, from 0.15.1, the layout reader (pdfminer), into the same Python;
5. refreshes the Claude Code plugin in the data folder if `enlens claude-setup` wrote one;
6. says to restart the app if it is running (the browser is told not to cache the page, so a restart is all).

The data folder (ENLENS_HOME, default ~/enlens) is never touched: projects, settings and history stay where they are.
`enlens update --check` only says whether a newer version is waiting.

0.10: ENLENS installed with the one-line install (installation.py, kind "script") updates from GitHub Releases
instead (`update_release`): it asks for the latest release, downloads its wheel, checks it against the release's
SHA256SUMS, installs it with `uv tool install` into the same place (so the icon and the plugin keep working), and runs
`enlens post-install` from the new version. On Windows the running `enlens` program cannot replace itself, so there
it says to run the install line again.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .procs import no_window

Runner = Callable[[list[str], Path], subprocess.CompletedProcess]


class UpdateError(Exception):
    """An update that cannot go ahead; the message says what to do."""


def source_root() -> Path | None:
    """The git copy this ENLENS runs from (src/enlens_claims/ → the folder with pyproject.toml), or None."""
    root = Path(__file__).resolve().parent.parent.parent
    if (root / "pyproject.toml").is_file() and (root / ".git").exists():
        return root
    return None


GIT_TIMEOUT = 90  # seconds a git command may take (0.14.3)


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a command. 0.14.3: it never reads from the terminal (stdin is closed), and a git command never asks for a
    password or a passphrase (a remote that wants credentials fails instead of waiting for ever) and gives up after
    GIT_TIMEOUT seconds: the app looks every two minutes, and one stuck look held up every later one. 0.15.3: without
    a window on Windows (procs)."""
    env, timeout = None, None
    if cmd and cmd[0] == "git":
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
        timeout = GIT_TIMEOUT
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, errors="replace",
                              stdin=subprocess.DEVNULL, env=env, timeout=timeout, **no_window())
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"{' '.join(cmd[:2])} took longer than {timeout} s and was "
                                                          "stopped (is the network or the remote not answering?)")


# 0.14.3: written (inside .git, so the copy stays "unchanged") before the requirements are installed after a merge,
# removed when the install worked: a failed install is finished by the next `enlens update`, which would otherwise
# find nothing to merge and say "up to date".
def _pending_path(root: Path) -> Path:
    return root / ".git" / "enlens-reinstall-pending"


def _pending(root: Path) -> list[str] | None:
    """The extras to install when an earlier update failed in its install step; None when nothing is pending."""
    try:
        data = json.loads(_pending_path(root).read_text("utf-8"))
        return [str(x) for x in data.get("extras") or []]
    except OSError:
        return None
    except (ValueError, AttributeError):
        return []


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


def _extras_in(text: str) -> dict[str, list[str]]:
    """The `[project.optional-dependencies]` table of a pyproject: tomllib when there is one (Python 3.11+), else
    read line by line (0.11.1: on 3.10 without tomli every extra was dropped on a reinstall)."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover - 3.10
        tomllib = None
    if tomllib is not None:
        try:
            return tomllib.loads(text).get("project", {}).get("optional-dependencies", {})
        except ValueError:
            return {}
    out: dict[str, list[str]] = {}
    inside = False
    name, buf = None, ""
    for line in text.splitlines():
        bare = line.split("#", 1)[0].strip()
        if bare.startswith("["):
            inside = bare == "[project.optional-dependencies]"
            continue
        if not inside or not bare:
            continue
        if name is None:
            if "=" not in bare:
                continue
            name, buf = bare.split("=", 1)[0].strip(), bare.split("=", 1)[1]
        else:
            buf += " " + bare
        if "]" in buf:
            out[name] = re.findall(r'"([^"]*)"', buf)
            name, buf = None, ""
    return out


def installed_extras(pyproject: Path) -> list[str]:
    """The optional dependency groups whose packages are all installed in this Python (to keep them on reinstall)."""
    from importlib import metadata

    try:
        extras = _extras_in(pyproject.read_text("utf-8"))
    except OSError:
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
           python: str | None = None, quick: bool = False) -> dict:
    """Bring this ENLENS up to date, the way it was installed (see the module's notes). Returns what happened.
    `quick` (0.13.6, the app's check every two minutes): a one-line install learns the newest version from GitHub's
    release page, which GitHub's limit of 60 API requests an hour does not count."""
    if root is None and source_root() is None:
        from . import installation

        k = installation.kind()
        if k == "script":
            if quick and check_only:
                return update_release(check_only=True, run=run, peek=_peek)
            return update_release(check_only=check_only, run=run)
        if k == "package":
            raise UpdateError("This ENLENS came as a download for this system: download the newest one from "
                              f"https://github.com/{installation.REPO}/releases and install it over this one (your "
                              "projects stay where they are).")
    return update_git(check_only=check_only, root=root, run=run, python=python)


def update_git(check_only: bool = False, root: Path | None = None, run: Runner = _run,
               python: str | None = None) -> dict:
    """Bring the git copy up to date (see the module's notes). Returns what happened, for printing."""
    root = root or source_root()
    if root is None:
        from .installation import install_line

        raise UpdateError("This ENLENS was installed with pip, so it cannot update itself. Install it once with the "
                          f"one-line install ({install_line()}), or from a git copy (see docs/DEVELOPING.md); after "
                          "that `enlens update` is all a new version needs.")
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
    except UpdateError as e:
        if _git(run, root, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD":  # detached: no branch to set upstream on
            raise UpdateError("This git copy is not on a branch (a detached HEAD), so it cannot follow GitHub. In it, "
                              f"run `git checkout main` (in {root}), then `enlens update` again.") from e
        raise UpdateError("This git copy follows no branch on GitHub. In it, run "
                          "`git branch --set-upstream-to=origin/main` (or the branch you use), then try again.") from e
    _git(run, root, "fetch", "--quiet")
    before = version_in(root)
    waiting = int(_git(run, root, "rev-list", "--count", f"HEAD..{upstream}") or 0)
    pending = _pending(root)
    if not waiting and pending is None:
        return {"updated": False, "version": before, "message": f"ENLENS {before} is up to date."}
    if check_only:
        if not waiting:  # merged earlier, but its requirements are not installed yet
            return {"updated": False, "version": before, "waiting": 1,
                    "message": "ENLENS was fetched, but its requirements are not installed yet. Run `enlens update`."}
        return {"updated": False, "version": before, "waiting": waiting,
                "message": f"A newer ENLENS is waiting ({waiting} change{'s' if waiting != 1 else ''}). Run `enlens update`."}
    py = root / "pyproject.toml"
    if waiting:
        ahead = int(_git(run, root, "rev-list", "--count", f"{upstream}..HEAD") or 0)
        if ahead:
            raise UpdateError(f"This copy has {ahead} commit(s) of its own that are not on GitHub, so it cannot simply move "
                              f"forward. Push them first (`git push` in {root}) or ask for help.")
        deps_before = _digest(py)
        extras = installed_extras(py)  # before the merge (0.11.1): an extra whose packages grew must stay installed
        _git(run, root, "merge", "--ff-only", "--quiet", upstream)
        if _digest(py) != deps_before:
            # 0.15.1: and the layout reader (pdfminer), which the one-line install has always brought: without it
            # PDFs are read from their text alone (a git copy installed with `pip install -e .` lacked it)
            layout = {"pdfminer"} if "pdfminer" in _extras_in(py.read_text("utf-8")) else set()
            pending = sorted(set(pending or []) | set(extras) | layout)
            try:
                _pending_path(root).write_text(json.dumps({"extras": pending}), encoding="utf-8")
            except OSError:
                pass
    after = version_in(root)
    out: dict = {"updated": True, "from": before, "version": after, "reinstalled": False}
    if pending is not None:
        extras = pending
        target = f"{root}[{','.join(extras)}]" if extras else str(root)
        r = run([python or sys.executable, "-m", "pip", "install", "--quiet", "-e", target], root)
        if r.returncode != 0:
            raise UpdateError(f"ENLENS {after} was fetched, but installing its new requirements failed:\n"
                              f"{(r.stderr or r.stdout or '').strip()[-2000:]}\nRun `enlens update` again when online.")
        try:
            _pending_path(root).unlink()
        except OSError:
            pass
        out["reinstalled"] = True
        out["extras"] = extras
    out["plugin"] = _refresh_plugin()
    out["running"] = _app_running()
    notes = [f"ENLENS updated from {before} to {after}." if before != after else
             f"ENLENS {after}: the requirements of the last update are installed now."]
    if out["reinstalled"]:
        notes.append("Its requirements changed and were installed into the same Python (no new venv).")
    if out["plugin"] == "updated":
        notes.append("The Claude Code plugin was refreshed.")
    elif out["plugin"]:
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
        path = claude_setup.find_claude()
        if path:  # 0.14.3: Claude Code keeps its own copy of a plugin: have it take the new files
            claude_setup.refresh_in_claude_code(path)
            return "updated"
        return True
    except Exception:  # noqa: BLE001 - the update itself succeeded; the plugin can be set up again by hand
        return False


def _app_running() -> bool:
    try:
        from .gui import launcher

        return launcher.running() is not None
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------------------------
# 0.10: the one-line install updates from GitHub Releases
# ---------------------------------------------------------------------------------------------
Fetch = Callable[[str], bytes]


def _fetch(url: str) -> bytes:
    from urllib.request import Request, urlopen

    req = Request(url, headers={"User-Agent": "enlens-update", "Accept": "application/vnd.github+json"})
    with urlopen(req, timeout=60) as r:
        return r.read()


# 0.15: a pre-release (development, alpha, beta, release candidate) comes before the release it leads to
_STAGES = {"dev": 0, "a": 1, "alpha": 1, "b": 2, "beta": 2, "c": 3, "rc": 3}
_RELEASE = 9


def version_tuple(v: str) -> tuple[int, ...]:
    """What orders versions: four numbers, then the stage and its number. 'v0.10.1' -> (0, 10, 1, 0, 9, 0);
    0.15: a release candidate comes after every earlier release and before its own, '0.15.0rc1' ->
    (0, 15, 0, 0, 3, 1) (before, it counted as 0.15.0, so a copy of it never heard of 0.15.0 itself). Other words after
    the numbers are ignored ('0.15.0candidate' is 0.15.0). () for no version."""
    m = re.match(r"v?(\d+(?:\.\d+)*)(?:[-_.]?(dev|alpha|beta|rc|a|b|c)[-_.]?(\d*)(?![A-Za-z]))?", v.strip(), re.I)
    if not m:
        return ()
    nums = [int(x) for x in m.group(1).split(".")][:4]
    stage = _STAGES[m.group(2).lower()] if m.group(2) else _RELEASE
    return (*nums, *[0] * (4 - len(nums)), stage, int(m.group(3) or 0) if m.group(2) else 0)


def semver(v: str) -> str:
    """0.15: a version as semantic versioning writes it, for files read by other programs (the Claude Code
    plugin): '0.15.0rc1' -> '0.15.0-rc.1'; a release stays as it is."""
    return re.sub(r"^(\d+\.\d+\.\d+)[-_.]?(rc|a|b)[-_.]?(\d+)$", r"\1-\2.\3", v)


# 0.13.6: 0.14.0, 0.15.0 and 0.15.1 were numbered higher than their changes called for (they changed nothing for
# people using ENLENS), so they were withdrawn and their changes are part of 0.13.6. A copy of one of them that is
# still running is older than any later ENLENS, whatever its number says. 0.14.0 is a release again (shared
# projects), so it left the list. 0.15: a withdrawn number counts as older only while this version is below it
# (gui/launcher.is_older), so 0.15.0 and 0.15.1 can be released for real without leaving the list first. 0.15.0 is
# a release (the new reader), and so is 0.15.1 (reader 3): both left the list, which is empty now.
WITHDRAWN: frozenset[str] = frozenset()


def is_candidate(v: str) -> bool:
    """0.15: whether a version is a pre-release (a release candidate, beta, alpha or development version)."""
    t = version_tuple(v)
    return bool(t) and t[4] != _RELEASE


def update_channel() -> str:
    """0.15: "stable" (the default) or "early" (also release candidates), from the settings (Settings → Technical)."""
    try:
        from . import home

        c = str(home.load_settings().get("update_channel") or "stable")
    except Exception:  # noqa: BLE001 - unreadable settings: the cautious channel
        return "stable"
    return c if c in ("stable", "early") else "stable"


def highest_release(releases: list) -> dict:
    """0.15: of GitHub's list of releases (newest first, drafts included when the person may see them), the published
    one with the highest version, a pre-release too. {} when there is none."""
    best: dict = {}
    for r in releases if isinstance(releases, list) else []:
        if not isinstance(r, dict) or r.get("draft") or not version_tuple(str(r.get("tag_name") or "")):
            continue
        if not best or version_tuple(str(r["tag_name"])) > version_tuple(str(best["tag_name"])):
            best = r
    return best


def latest_release(fetch: Fetch = _fetch, repo: str | None = None, channel: str | None = None) -> dict:
    """The latest published release: {"version", "tag", "wheel_url", "wheel", "sums_url", "notes", "url"}.
    0.15: on the "early" channel (default from the settings) the highest version of all published releases,
    a pre-release too; on "stable" GitHub's *latest*, which is never a pre-release."""
    from .installation import REPO

    early = (channel or update_channel()) == "early"
    url = f"https://api.github.com/repos/{repo or REPO}/releases" + ("?per_page=30" if early else "/latest")
    try:
        data = json.loads(fetch(url).decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - offline, rate limited, no release yet: say it plainly
        raise UpdateError(f"Could not ask GitHub for the newest ENLENS ({type(e).__name__}: {e}). Are you online?") from e
    if early:
        data = highest_release(data)
    assets = {a.get("name", ""): a.get("browser_download_url", "") for a in data.get("assets") or []}
    wheel = next((n for n in assets if n.startswith("enlens_claims-") and n.endswith(".whl")), "")
    tag = str(data.get("tag_name") or "")
    return {"version": tag.lstrip("v"), "tag": tag, "wheel": wheel, "wheel_url": assets.get(wheel, ""),
            "sums_url": assets.get("SHA256SUMS", ""), "notes": str(data.get("body") or ""),
            "url": str(data.get("html_url") or "")}


def _peek(url: str) -> str:
    """Where `url` sends the browser (its redirect), without following it."""
    from urllib.error import HTTPError
    from urllib.request import HTTPRedirectHandler, Request, build_opener

    class _Stay(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003 - urllib's own signature
            return None  # urllib then raises HTTPError with the 302 and its Location

    req = Request(url, method="HEAD", headers={"User-Agent": "enlens-update"})
    try:
        with build_opener(_Stay).open(req, timeout=20) as r:
            return r.headers.get("Location") or ""
    except HTTPError as e:
        if 300 <= e.code < 400:
            return e.headers.get("Location") or ""
        raise


Peek = Callable[[str], str]


def latest_version(peek: Peek = _peek, repo: str | None = None, channel: str | None = None) -> str:
    """0.13.6: the newest release's version, from where github.com/…/releases/latest redirects to
    (…/releases/tag/v0.13.6). A web page, not the API: GitHub's limit of 60 API requests an hour for each address
    does not count it, so the app can ask every two minutes on every computer in an office. "" when it cannot tell.
    0.15: "" on the "early" channel: that page never shows a pre-release, so the API list is asked instead."""
    from .installation import REPO

    if (channel or update_channel()) == "early":
        return ""
    try:
        where = peek(f"https://github.com/{repo or REPO}/releases/latest")
    except Exception as e:  # noqa: BLE001 - offline, GitHub down: say it plainly
        raise UpdateError(f"Could not ask GitHub for the newest ENLENS ({type(e).__name__}: {e}). Are you online?") from e
    m = re.search(r"/releases/tag/([^/?#]+)", where or "")
    return m.group(1).lstrip("v") if m else ""


def find_uv() -> str:
    found = shutil.which("uv")
    if found:
        return found
    h = Path.home()
    for c in (h / ".local" / "bin" / "uv", h / ".local" / "bin" / "uv.exe", h / ".cargo" / "bin" / "uv",
              Path("/opt/homebrew/bin/uv"), Path("/usr/local/bin/uv")):
        if c.exists():
            return str(c)
    return ""


def update_release(check_only: bool = False, run: Runner = _run, fetch: Fetch = _fetch, workdir: Path | None = None,
                   windows: bool | None = None, peek: Peek | None = None, channel: str | None = None) -> dict:
    """Install the newest GitHub Release over a one-line install (see the module's notes). With `peek` (0.13.6), a
    check reads the newest version from the release page (`latest_version`), and asks the API only when the page does
    not say. 0.15: `channel` ("stable" or "early", default from the settings) says whether a release candidate counts."""
    import tempfile

    from . import __version__, installation

    have = __version__
    channel = channel or update_channel()
    seen = latest_version(peek, channel=channel) if check_only and peek is not None else ""
    rel = {"version": seen} if seen else latest_release(fetch, channel=channel)
    if not rel["version"] or version_tuple(rel["version"]) <= version_tuple(have):
        return {"updated": False, "version": have, "message": f"ENLENS {have} is up to date."}
    if check_only:
        return {"updated": False, "version": have, "waiting": rel["version"],
                "message": f"ENLENS {rel['version']} is ready to install (you have {have}). Run `enlens update`."}
    if windows if windows is not None else os.name == "nt":
        raise UpdateError(f"ENLENS {rel['version']} is ready. On Windows, quit ENLENS (Quit ENLENS in the app), then "
                          f"download this file and double-click it:\n  {installation.double_click_file('windows')}\n"
                          f"or run the install line again in PowerShell:\n  {installation.install_line('windows')}")
    if not rel["wheel_url"] or not rel["sums_url"]:
        raise UpdateError(f"The release {rel['tag']} has no ENLENS package or no checksums: see {rel['url']}.")
    uv = find_uv()
    if not uv:
        raise UpdateError("uv, which installed ENLENS, was not found. Run the install line again:\n  "
                          + installation.install_line())
    tmp = Path(workdir or tempfile.mkdtemp(prefix="enlens-update-"))
    try:
        wheel = tmp / rel["wheel"]
        wheel.write_bytes(fetch(rel["wheel_url"]))
        sums = fetch(rel["sums_url"]).decode("utf-8", errors="replace")
        want = next((line.split()[0].lower() for line in sums.splitlines()
                     if len(line.split()) == 2 and line.split()[1].lstrip("*") == rel["wheel"]), "")
        got = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if not want or want != got:
            raise UpdateError(f"The downloaded {rel['wheel']} does not match the release's checksum, so it was not "
                              "installed. Try again later.")
        spec = f"enlens-claims[{','.join(installation.EXTRAS)}] @ {wheel.resolve().as_uri()}"
        # uv's own Python, as the install line chose (0.11.1): never a system Python 3.12 that may go away
        os.environ.setdefault("UV_PYTHON_PREFERENCE", "only-managed")
        r = run([uv, "tool", "install", "--force", "--quiet", "--python", "3.12", spec], tmp)
        if r.returncode != 0:
            raise UpdateError(f"Installing ENLENS {rel['version']} failed:\n{(r.stderr or r.stdout or '').strip()[-2000:]}")
        # the new version finishes the job: the marker, the plugin (the icon points at the same Python)
        post = run([sys.executable, "-m", "enlens_claims.cli", "post-install", "--by", "script", "--no-icon"], tmp)
        if post.returncode != 0:  # 0.11.1: a failed marker or plugin repair was reported as a successful update
            raise UpdateError(f"ENLENS {rel['version']} was installed, but finishing the update failed:\n"
                              f"{(post.stderr or post.stdout or '').strip()[-2000:]}\nRun `enlens post-install` to try "
                              "that part again.")
    finally:
        if workdir is None:
            shutil.rmtree(tmp, ignore_errors=True)
    out = {"updated": True, "from": have, "version": rel["version"], "route": "release",
           "post_install": (post.stdout or "").strip(), "running": _app_running()}
    notes = [f"ENLENS updated from {have} to {rel['version']}."]
    notes.append("ENLENS is running: choose Quit ENLENS in the app and open it again." if out["running"]
                 else "Open ENLENS as usual.")
    out["message"] = " ".join(notes)
    return out
