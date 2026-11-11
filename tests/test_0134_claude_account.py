"""0.13.4: which account Claude Code is signed in to.

Claude Code says it itself (`claude auth status`: the address, the organisation, the plan). ENLENS keeps those three
in the set-up status and shows them where the researcher looks for them: the card that opens on the sidebar's
"Claude, on your plan" line, Settings → AI's checklist and `enlens claude-setup`. The login itself stays with Claude
Code, and the address is not spread into the app's other answers. The stand-in tests/fake_claude_cli.py plays
Claude Code (FAKE_CLAUDE_EMAIL, FAKE_CLAUDE_ORG and FAKE_CLAUDE_PLAN set what it reports).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from test_app import Api, api, home  # noqa: F401  (fixtures)
from _static import assert_sheet_after

FAKE = str(Path(__file__).with_name("fake_claude_cli.py"))
STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setenv("ENLENS_CLAUDE", FAKE)
    for env in ("FAKE_CLAUDE_EMAIL", "FAKE_CLAUDE_ORG", "FAKE_CLAUDE_PLAN", "FAKE_CLAUDE_LOGGED_OUT"):
        monkeypatch.delenv(env, raising=False)
    from enlens_claims import claude_setup

    claude_setup._STATUS.update(at=0.0, value=None)
    return claude_setup


def _claude_saying(tmp_path, monkeypatch, auth) -> None:
    """A stand-in whose `auth status` prints exactly `auth` (another Claude Code version, odd values)."""
    p = tmp_path / "claude_says.py"
    p.write_text("import json, sys\n"
                 "if sys.argv[1:] == ['--version']: print('2.1.400 (Claude Code)')\n"
                 f"elif sys.argv[1:3] == ['auth', 'status']: print(json.dumps({auth!r}))\n"
                 "elif sys.argv[1:3] == ['plugin', 'list']: print('[]')\n", encoding="utf-8")
    monkeypatch.setenv("ENLENS_CLAUDE", str(p))
    from enlens_claims import claude_setup

    claude_setup._STATUS.update(at=0.0, value=None)


def test_the_status_names_the_account(home, fake_claude, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FAKE_CLAUDE_EMAIL", "r.searcher@uva.nl")
    monkeypatch.setenv("FAKE_CLAUDE_ORG", "University of Amsterdam")
    monkeypatch.setenv("FAKE_CLAUDE_PLAN", "team")
    st = fake_claude.status(refresh=True)
    assert st["signed_in"] is True and st["email"] == "r.searcher@uva.nl"
    assert st["org_name"] == "University of Amsterdam" and st["plan"] == "team" and st["auth_method"] == "claude.ai"
    assert st["account"] == "commercial"
    assert fake_claude.account_words(st) == "r.searcher@uva.nl, Team plan (University of Amsterdam)"


def test_a_personal_plan_is_not_named_after_its_organisation(home, fake_claude, monkeypatch):  # noqa: F811
    # on Pro and Max the organisation is Claude's own "…'s Organization": saying it adds nothing
    monkeypatch.setenv("FAKE_CLAUDE_ORG", "researcher@example.org's Organization")
    monkeypatch.setenv("FAKE_CLAUDE_PLAN", "max")
    st = fake_claude.status(refresh=True)
    assert st["org_name"] == "researcher@example.org's Organization"
    assert fake_claude.account_words(st) == "researcher@example.org, Max plan"


def test_signed_out_names_no_account(home, fake_claude, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_OUT", "1")
    st = fake_claude.status(refresh=True)
    assert st["signed_in"] is False and st["email"] == "" and st["org_name"] == "" and st["auth_method"] == ""
    assert fake_claude.account_words(st) == ""


def test_what_claude_code_says_is_made_safe_to_show(home, tmp_path, monkeypatch):  # noqa: F811
    from enlens_claims import claude_setup

    # an older Claude Code that names no account: signed in, nothing more to say
    _claude_saying(tmp_path, monkeypatch, {"loggedIn": True, "authMethod": "claude.ai"})
    st = claude_setup.status(refresh=True)
    assert st["signed_in"] is True and st["email"] == "" and claude_setup.account_words(st) == ""
    # the plan alone, or an API account of the Claude Console
    _claude_saying(tmp_path, monkeypatch, {"loggedIn": True, "subscriptionType": "pro"})
    assert claude_setup.account_words(claude_setup.status(refresh=True)) == "Pro plan"
    _claude_saying(tmp_path, monkeypatch, {"loggedIn": True, "authMethod": "console", "email": "lab@example.org"})
    assert claude_setup.account_words(claude_setup.status(refresh=True)) == "lab@example.org, a Claude Console account"
    # odd values: no line breaks or control characters, no runaway length, nothing but text
    _claude_saying(tmp_path, monkeypatch, {"loggedIn": True, "email": "a@b.nl\n\x1b[31mred" + "x" * 500,
                                           "orgName": 42, "authMethod": ["claude.ai"]})
    st = claude_setup.status(refresh=True)
    assert st["email"].startswith("a@b.nl [31mred") and len(st["email"]) == 200
    assert not re.search(r"[\x00-\x1f]", st["email"]) and st["org_name"] == "" and st["auth_method"] == ""
    # an account Claude Code reports while signed out is not shown
    _claude_saying(tmp_path, monkeypatch, {"loggedIn": False, "email": "old@example.org"})
    st = claude_setup.status(refresh=True)
    assert st["signed_in"] is False and st["email"] == ""


def test_local_only_asks_claude_code_nothing(home, fake_claude, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    st = fake_claude.status(refresh=True)
    assert st["found"] is False and st["email"] == "" and st["signed_in"] is None


def test_the_page_reads_the_account_from_the_set_up_status_only(api, fake_claude, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FAKE_CLAUDE_EMAIL", "r.searcher@uva.nl")
    monkeypatch.setenv("FAKE_CLAUDE_PLAN", "enterprise")
    monkeypatch.setenv("FAKE_CLAUDE_ORG", "UvA")
    st, info = api("GET", "/api/claude-setup?refresh=1")
    assert st == 200
    assert {k: info["status"][k] for k in ("email", "org_name", "plan")} == {"email": "r.searcher@uva.nl",
                                                                            "org_name": "UvA", "plan": "enterprise"}
    # the address is not copied into the app's other answers
    assert "r.searcher@uva.nl" not in json.dumps(api("GET", "/api/state")[1])
    api("POST", "/api/projects", {"name": "P"})
    st, q = api("GET", "/api/projects/P/queue")
    assert st == 200 and set(q["claude"]) == {"found", "signed_in", "installed", "ready"}


def test_claude_setup_on_the_command_line_says_the_account(home, fake_claude, monkeypatch, capsys):  # noqa: F811
    from enlens_claims import cli

    monkeypatch.setenv("FAKE_CLAUDE_EMAIL", "r.searcher@uva.nl")
    monkeypatch.setenv("FAKE_CLAUDE_PLAN", "team")
    monkeypatch.setenv("FAKE_CLAUDE_ORG", "UvA")
    assert cli.main(["claude-setup", "--no-check"]) == 0
    assert "Claude Code is signed in as r.searcher@uva.nl, Team plan (UvA)." in capsys.readouterr().out


def test_the_sidebar_card_and_the_settings_checklist():
    app = (STATIC / "app.js").read_text()
    lib = (STATIC / "lib.js").read_text()
    settings = (STATIC / "views" / "settings.js").read_text()
    overview = (STATIC / "views" / "overview.js").read_text()
    # the sidebar line opens a card (it had the browser's tooltip, which could not name the account)
    body = app[app.index("function renderPrivacy()"):app.index("function sidebarScrollInit()")]
    assert "title:" not in body and '"aria-describedby": "privacy-card"' in body and 'role: "tooltip"' in body
    assert "Signed in to Claude Code as" in body and "Escape" in body
    assert "mouseenter" in body and "claudeStatus()" in body
    # one shared answer, asked again after a minute; Settings hands on what it reads fresh
    for name in ("claudeStatus", "claudeSeenNow", "rememberClaude", "claudeAccount"):
        assert f"export function {name}(" in lib, name
    assert "rememberClaude(info.status" in settings and "rememberClaude(r.status" in settings
    assert "/api/claude-setup" not in overview   # 0.17.0: the Overview AI box is gone; the sidebar line asks
    # Settings → AI: "Signed in with your Claude plan" names the account
    assert "accountText(st)" in settings and '"Pro, Max, Team or Enterprise"' in settings


def test_the_card_stylesheet():
    # 0.17.0: reads the cascade (tests/_static.py), so it holds when the design guide moves the rules
    from _static import SITE, all_css, css_blocks, index_html, MARKER, rule

    assert index_html().split(MARKER, 1)[1].count('rel="stylesheet"') == 1 and SITE in index_html().split(MARKER, 1)[1]
    mine = [d for _m, sels, d in css_blocks(all_css()) if any(".privacy-" in s for s in sels)]
    assert len(mine) > 5
    # light and dark both work: the colour tokens of tokens.css only
    assert not any(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", v) for d in mine for v in d.values())
    css = all_css()
    assert rule(".privacy-wrap:hover .privacy-card")["visibility"] == "visible"
    assert rule(".privacy-wrap:focus-within .privacy-card")["opacity"] == "1"
    assert rule(".privacy-wrap.privacy-quiet .privacy-card")["visibility"] == "hidden"
    assert rule(".privacy-card", media="(hover: none)")["display"] == "none"
    assert rule(".privacy-account strong")["overflow-wrap"] == "anywhere"


def test_the_stand_in_reports_an_account(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path))
    for env in ("FAKE_CLAUDE_EMAIL", "FAKE_CLAUDE_ORG", "FAKE_CLAUDE_PLAN", "FAKE_CLAUDE_LOGGED_OUT"):
        monkeypatch.delenv(env, raising=False)
    out = json.loads(subprocess.run([sys.executable, FAKE, "auth", "status"], capture_output=True, text=True).stdout)
    assert out == {"loggedIn": True, "authMethod": "claude.ai", "email": "researcher@example.org"}
