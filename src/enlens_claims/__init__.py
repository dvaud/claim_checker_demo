"""ENLENS: check hypotheses against your own documents, locally. Every verdict comes with exact, checked quotes.

The SDG / value chain assessment pipeline of the green hydrogen pilot is included as an optional pack
(`enlens load-vca`, `make-tasks`, `report`, ...).
"""


def _version() -> str:
    """The version, from the installed package's metadata (0.18.1, roadmap J1.3). It is made from the git tag when the
    package is built (setuptools-scm, see pyproject.toml), so it stands in no source file. A copy run straight from
    the sources, without an install, asks git for its newest release tag; with neither, "0.0.0" (an unknown version
    is older than every release, so the app offers an update rather than hiding one)."""
    try:
        from importlib import metadata

        return metadata.version("enlens-claims")
    except Exception:  # noqa: BLE001 - PackageNotFoundError, or metadata that cannot be read
        pass
    try:
        import subprocess
        from pathlib import Path

        from .procs import no_window  # a module of its own with no imports of the package: safe to load here

        root = Path(__file__).resolve().parent.parent.parent
        if (root / ".git").exists():
            out = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"], cwd=root,
                                 capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL,
                                 **no_window())
            if out.returncode == 0 and out.stdout.strip().lstrip("v"):
                return out.stdout.strip().lstrip("v")
    except Exception:  # noqa: BLE001 - no git, no repository, a timeout
        pass
    return "0.0.0"


__version__ = _version()
