"""Add-ons: what an app built on ENLENS adds, in files of its own (0.13.5). See docs/EXTENDING.md.

An add-on is a Python module. It comes from one of two places, and ENLENS reads both:

- a **fork** fills in `enlens_claims/gui/extensions.py`, which ENLENS ships holding only a docstring;
- a **separate package** names its module under the entry point group `enlens.extensions`, in its pyproject.toml:

      [project.entry-points."enlens.extensions"]
      margin = "margin_addon"

ENLENS reads only the names an add-on defines and uses its own default for every other one, so ENLENS alone (no
add-on) behaves exactly as before. The names (each one optional):

- `BRAND`: a dict over `static/brand.json` (name, tagline, welcome_title, welcome_text, description, logo).
- `STATIC`: a folder of the add-on's page files, served at `/static/addons/<add-on>/`. Its `site.css`, when there
  is one, is added to `/static/site.css` after the installation's own.

ENLENS's standing rules apply to anything an add-on adds: `home.local_only()`, the per-document AI settings and the
quote check are checked by ENLENS, never by the add-on.

An add-on that fails to load is left out (ENLENS still starts) and its error is kept in `errors()`.
"""
from __future__ import annotations

import importlib
import json
import sys
import traceback
from importlib import metadata
from pathlib import Path
from types import ModuleType

GROUP = "enlens.extensions"
LOCAL = "enlens_claims.gui.extensions"
STATIC = Path(__file__).with_name("gui") / "static"
BRAND_FILE = STATIC / "brand.json"
BRAND_KEYS = ("name", "tagline", "welcome_title", "welcome_text", "description", "logo")

_loaded: list[tuple[str, ModuleType]] | None = None
_errors: list[dict] = []


def _entry_points() -> list:
    try:
        return sorted(metadata.entry_points(group=GROUP), key=lambda ep: ep.name)
    except Exception:  # a broken installed package must not stop ENLENS
        return []


def load(refresh: bool = False) -> list[tuple[str, ModuleType]]:
    """The add-ons, as (name, module): the fork's gui/extensions.py first, then each package's, by name."""
    global _loaded
    if _loaded is not None and not refresh:
        return _loaded
    out: list[tuple[str, ModuleType]] = []
    _errors.clear()
    try:
        out.append(("local", importlib.import_module(LOCAL)))
    except Exception as e:  # noqa: BLE001: a fork's broken file is reported, not fatal
        _errors.append({"addon": "local", "error": f"{type(e).__name__}: {e}"})
        traceback.print_exc()
    for ep in _entry_points():
        try:
            mod = ep.load()
        except Exception as e:  # noqa: BLE001
            _errors.append({"addon": ep.name, "error": f"{type(e).__name__}: {e}"})
            print(f"ENLENS: the add-on {ep.name} could not be loaded: {e}", file=sys.stderr)
            continue
        out.append((ep.name, mod))
    _loaded = out
    return out


def errors() -> list[dict]:
    load()
    return list(_errors)


def names() -> list[str]:
    """The add-ons in use, apart from an empty local layer."""
    return [n for n, m in load() if n != "local" or defines(m)]


def defines(mod: ModuleType) -> bool:
    """Whether a module defines anything an add-on can (an empty gui/extensions.py does not)."""
    return any(not k.startswith("_") and k.isupper() or k in HOOKS for k in vars(mod))


HOOKS = ("state", "overview")  # functions an add-on may define (more in later versions)


def values(attr: str) -> list:
    """Every add-on's `attr`, in load order (add-ons that do not define it are skipped)."""
    return [getattr(m, attr) for _n, m in load() if getattr(m, attr, None) is not None]


# -------------------------------------------------------------------------------------------------- branding
def brand() -> dict:
    """The app's name and words: static/brand.json, then each add-on's BRAND over it. Only known keys, as text."""
    try:
        out = json.loads(BRAND_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        out = {}
    out = {k: str(out[k]) for k in BRAND_KEYS if isinstance(out.get(k), str) and out[k].strip()}
    for b in values("BRAND"):
        if isinstance(b, dict):
            out.update({k: str(v) for k, v in b.items() if k in BRAND_KEYS and isinstance(v, str) and v.strip()})
    out.setdefault("name", "ENLENS")
    out.setdefault("logo", "/static/logo.svg")
    return out


# -------------------------------------------------------------------------------------------------- page files
def static_dirs() -> dict[str, Path]:
    """Each add-on's folder of page files, by add-on name (a fork keeps its files in static/ itself)."""
    out = {}
    for n, m in load():
        d = getattr(m, "STATIC", None)
        if d and n != "local" and Path(d).is_dir():
            out[n] = Path(d)
    return out


def static_file(rel: str) -> Path | None:
    """The add-on file served at /static/addons/<add-on>/<path>, or None. Never outside the add-on's folder."""
    name, _, rest = rel.partition("/")
    base = static_dirs().get(name)
    if not base or not rest:
        return None
    target = (base / rest).resolve()
    return target if target.is_relative_to(base.resolve()) and target.is_file() else None


def site_css() -> bytes:
    """/static/site.css: the installation's own (static/site.css), then each add-on's site.css."""
    parts = [(STATIC / "site.css").read_bytes()] if (STATIC / "site.css").is_file() else []
    for n, d in static_dirs().items():
        f = d / "site.css"
        if f.is_file():
            parts.append(f"\n/* add-on: {n} */\n".encode() + f.read_bytes())
    return b"".join(parts)
