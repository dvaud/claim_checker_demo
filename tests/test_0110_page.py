"""0.11: the page files of per-document AI settings are there, linked and served."""
from pathlib import Path

from test_app import api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


def test_the_page_files():
    index = (STATIC / "index.html").read_text()
    assert '/static/v011.css' in index
    css = (STATIC / "v011.css").read_text()
    assert "#" not in css.split("*/", 1)[1].replace("#ai", "")  # colour tokens only, no fixed colours
    acc = (STATIC / "views" / "ai-access.js").read_text()
    for name in ("accessChoice", "accessSelect", "docAccessDialog", "accessAskCard", "accessBanner", "termsPanel",
                 "restrictedModelCard"):
        assert f"function {name}(" in acc
    assert "./ai-access.js" in (STATIC / "views" / "sources.js").read_text()
    assert "./ai-access.js" in (STATIC / "views" / "settings.js").read_text()
    result = (STATIC / "views" / "result.js").read_text()
    assert "read-local" in result and "Waiting for your judgement" in result


def test_served(api):  # noqa: F811
    for f in ("/static/v011.css", "/static/views/ai-access.js"):
        st, _ = api("GET", f, token=False)
        assert st == 200, f
    st, s = api("GET", "/api/state")
    assert st == 200 and "restricted" in s
