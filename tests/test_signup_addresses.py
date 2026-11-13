"""0.18.0rc3: the storage space's set-up gives each sign-up address to copy, not a link.

A link opens the default browser, where Backblaze's robot check ("Not so fast!") can ask again for ever (seen in Zen,
a Firefox fork with strict tracking protection). The dialog shows the address with a Copy button, says what to do
about the robot check, and names the Application Keys page instead of linking to it (a link would open the default
browser again, where the person may not be signed in).
"""
from __future__ import annotations

import re
from pathlib import Path

from enlens_claims.gui.api_space import LINKS

STATIC = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static"
JS = (STATIC / "views" / "team-space.js").read_text(encoding="utf-8")
MANUAL_FILE = Path(__file__).resolve().parents[1] / "docs" / "manual" / "storage-space.md"
MANUAL = " ".join(MANUAL_FILE.read_text(encoding="utf-8").split())   # the manual's lines wrap at 120 columns


def _setup_dialog():
    start = JS.index("export async function setupDialog")
    return JS[start:JS.index("\n}\n", start)]


def test_both_sign_up_addresses_are_given_to_copy():
    js = _setup_dialog()
    assert 'typeAddress(L.b2_signup' in js and 'typeAddress(L.r2_signup' in js
    assert "copyLine" in JS and '"link")' in JS          # the copy line, with a link icon rather than a terminal's
    # the addresses typed when the links are missing are the ones the app serves
    assert LINKS["b2_signup"] in js and LINKS["r2_signup"] in js


def test_no_sign_up_page_or_key_page_opens_as_a_link():
    js = _setup_dialog()
    assert not re.search(r"outLink\(L\.(b2_signup|b2_keys|r2_signup)", js)
    assert "Application Keys" in js and "in that browser" in js


def test_the_robot_check_is_explained_in_the_dialog_and_the_manual():
    js = _setup_dialog()
    assert "keeps asking whether you are a robot" in js and "Safari, Chrome or Edge" in js
    assert "Not so fast!" in MANUAL and "Copy" in MANUAL and "Safari, Chrome or Edge" in MANUAL


def test_copy_line_keeps_its_terminal_icon_by_default():
    lib = (STATIC / "lib.js").read_text(encoding="utf-8")
    assert 'export function copyLine(text, label = "Copy", where = "Claude Code", lead = "terminal")' in lib
    assert "icon(lead, { size: 13 })" in lib
