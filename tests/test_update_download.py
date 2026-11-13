"""0.17.0: *Update* downloads the new version by a second route when GitHub's download links are busy.

On 2026-11-09 the update from 0.15.6 to 0.15.7 stopped with "Something went wrong inside the app" and
"Unexpected problem: HTTP Error 504: Gateway Time-out". GitHub's download links (github.com/…/releases/download/…)
answered 504 for everyone, any project's, while the API's own route to the same file (…/releases/assets/<id>, asked
for the file itself) worked. The download was the one step of the update with no plain message: GitHub's error went
up to the server as an unexpected problem. Now each file is fetched from the download link, else from the API's
route, twice over a few seconds apart, and a download that cannot be had says so in plain words, with nothing
installed.
"""
from __future__ import annotations

import hashlib
import io
import json
from urllib.error import HTTPError, URLError

import pytest

from test_setup_and_moving import NEXT, Runs
from test_update_button import served  # noqa: F401  (fixture)
from test_app import home  # noqa: F401  (fixture)

LATEST = "https://api.github.com/repos/dvaud/claim_checker_demo/releases/latest"
WHEEL = f"enlens_claims-{NEXT}-py3-none-any.whl"
DL = f"https://github.com/dvaud/claim_checker_demo/releases/download/v{NEXT}/"
API = "https://api.github.com/repos/dvaud/claim_checker_demo/releases/assets/"


def _gateway(url):
    return HTTPError(url, 504, "Gateway Time-out", {}, io.BytesIO(b"<html>504</html>"))


def _github(busy=("download",), wheel=b"PK fake wheel"):
    """A GitHub whose routes in `busy` ("download", "api") answer 504; the latest release has both routes per file."""
    digest = hashlib.sha256(wheel).hexdigest()
    asked = []
    files = {WHEEL: (wheel, 1), "SHA256SUMS": (f"{digest}  {WHEEL}\n".encode(), 2)}
    pages = {LATEST: json.dumps({
        "tag_name": f"v{NEXT}", "html_url": f"https://github.com/x/releases/tag/v{NEXT}", "body": "notes",
        "assets": [{"name": n, "browser_download_url": DL + n, "url": f"{API}{i}"} for n, (_, i) in files.items()],
    }).encode()}
    for n, (body, i) in files.items():
        pages[DL + n] = body
        pages[f"{API}{i}"] = body

    def fetch(url):
        asked.append(url)
        if ("download" in busy and url.startswith(DL)) or ("api" in busy and url.startswith(API)):
            raise _gateway(url)
        return pages[url]

    return fetch, asked


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    from enlens_claims import update

    monkeypatch.setattr(update, "find_uv", lambda: "/bin/uv")
    monkeypatch.setattr(update, "DOWNLOAD_PAUSE", 0)


def test_the_latest_release_names_both_routes_to_each_file():
    from enlens_claims import update

    fetch, _ = _github()
    rel = update.latest_release(fetch=fetch, channel="stable")
    assert rel["wheel_url"] == DL + WHEEL and rel["wheel_api"] == f"{API}1"
    assert rel["sums_url"] == DL + "SHA256SUMS" and rel["sums_api"] == f"{API}2"


def test_busy_download_links_fall_back_to_the_api_route(tmp_path):
    from enlens_claims import update

    fetch, asked = _github(busy=("download",))
    runs = Runs()
    r = update.update_release(fetch=fetch, run=runs, workdir=tmp_path, windows=False)
    assert r["updated"] and r["version"] == NEXT
    assert asked == [LATEST, DL + WHEEL, f"{API}1", DL + "SHA256SUMS", f"{API}2"]
    assert (tmp_path / WHEEL).read_bytes() == b"PK fake wheel" and runs.calls[0][:3] == ["/bin/uv", "tool", "install"]


def test_the_download_link_comes_first_when_it_works(tmp_path):
    from enlens_claims import update

    fetch, asked = _github(busy=())
    assert update.update_release(fetch=fetch, run=Runs(), workdir=tmp_path, windows=False)["updated"]
    assert asked == [LATEST, DL + WHEEL, DL + "SHA256SUMS"]  # the API's route is not asked: its limit is kept


def test_a_download_that_cannot_be_had_says_so_and_installs_nothing(tmp_path):
    from enlens_claims import update

    fetch, asked = _github(busy=("download", "api"))
    runs = Runs()
    with pytest.raises(update.UpdateError) as e:
        update.update_release(fetch=fetch, run=runs, workdir=tmp_path, windows=False)
    msg = str(e.value)
    assert f"ENLENS {NEXT} could not be downloaded from GitHub (HTTP 504 Gateway Time-out)" in msg
    assert "Nothing was changed" in msg and "try again in a few minutes" in msg
    assert runs.calls == []
    assert asked == [LATEST] + [DL + WHEEL, f"{API}1"] * update.DOWNLOAD_ROUNDS  # each route, each round
    assert update.DOWNLOAD_ROUNDS == 2


def test_offline_during_the_download_is_said_plainly_too(tmp_path):
    from enlens_claims import update

    fetch, _ = _github(busy=())

    def cut(url):
        if url == LATEST:
            return fetch(url)
        raise URLError("nodename nor servname provided, or not known")

    with pytest.raises(update.UpdateError, match=r"could not be downloaded from GitHub \(URLError: .*Are you online"):
        update.update_release(fetch=cut, run=Runs(), workdir=tmp_path, windows=False)


def test_windows_falls_back_too_and_leaves_nothing_when_it_fails(monkeypatch, home):  # noqa: F811
    from enlens_claims import update

    jobs = []
    fetch, _ = _github(busy=("download",))
    r = update.update_release(fetch=fetch, windows=True, restart=["app"], start=jobs.append)
    assert r["handover"] and len(jobs) == 1
    fetch, _ = _github(busy=("download", "api"))
    with pytest.raises(update.UpdateError, match="could not be downloaded"):
        update.update_release(fetch=fetch, windows=True, restart=["app"], start=jobs.append)
    assert len(jobs) == 1 and not any(update.updates_folder().iterdir())


def test_the_api_route_is_asked_for_the_file_itself(monkeypatch):
    import urllib.request

    from enlens_claims import update

    sent = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=0):
        sent.append((req.full_url, req.get_header("Accept"), timeout))
        return Answer(b"file")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert update._fetch(f"{API}1") == b"file" and update._fetch(LATEST) == b"file"
    assert sent == [(f"{API}1", "application/octet-stream", 60), (LATEST, "application/vnd.github+json", 60)]


def test_the_button_shows_the_plain_message_not_an_unexpected_problem(served, monkeypatch, tmp_path):  # noqa: F811
    from enlens_claims import update

    a, _, restarts = served
    fetch, _ = _github(busy=("download", "api"))
    monkeypatch.setattr(update, "update", lambda **kw: update.update_release(
        fetch=fetch, run=Runs(), workdir=tmp_path, windows=False))
    st, r = a("POST", "/api/update", {})
    assert st == 409 and r.get("kind") != "internal" and "Unexpected problem" not in r["error"]
    assert "HTTP 504 Gateway Time-out" in r["error"] and "Nothing was changed" in r["error"]
    assert restarts == []
    assert a("POST", "/api/update", {})[0] == 409  # it can be tried again: the lock was let go
