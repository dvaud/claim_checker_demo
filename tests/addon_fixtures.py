"""Fixtures for add-ons (0.13.5): `addon` turns on the stand-in add-on package (tests/fake_extension), `local_addon`
fills in gui/extensions.py as a fork would. Both leave ENLENS as it was afterwards."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FAKE = Path(__file__).with_name("fake_extension")


def _forget_open_projects():
    from enlens_claims import home

    home._OPEN.clear()


@pytest.fixture
def addon():
    """The stand-in add-on, found through its entry point like an installed package."""
    import importlib

    from enlens_claims import access, addons

    from enlens_claims import taskkinds

    hooks = list(access._FLOORS), list(access._HIDDEN)  # the add-on registers its own when imported
    kinds = dict(taskkinds._REG)
    sys.path.insert(0, str(FAKE))
    importlib.invalidate_caches()
    import enlens_fake_addon

    addons.load(refresh=True)
    assert "fake" in addons.names(), addons.errors()
    _forget_open_projects()  # opened again, a project gains the add-on's tables
    yield enlens_fake_addon
    sys.path.remove(str(FAKE))
    access._FLOORS[:], access._HIDDEN[:] = hooks
    taskkinds._REG.clear()
    taskkinds._REG.update(kinds)
    for name in [m for m in sys.modules if m == "enlens_fake_addon" or m.startswith("enlens_fake_addon.")]:
        del sys.modules[name]
    addons.load(refresh=True)
    _forget_open_projects()


@pytest.fixture
def local_addon():
    """gui/extensions.py as a fork fills it in: `local_addon.set(NAME=value, ...)` defines names in it (and reloads
    the add-ons); they are taken away afterwards."""
    from enlens_claims import addons
    from enlens_claims.gui import extensions

    class Local:
        module = extensions

        def __init__(self):
            self.mp = pytest.MonkeyPatch()

        def set(self, **names):
            for k, v in names.items():
                self.mp.setattr(extensions, k, v, raising=False)
            addons.load(refresh=True)
            return extensions

    local = Local()
    yield local
    local.mp.undo()
    addons.load(refresh=True)
