"""Make the screenshots of the user manual (docs/images/manual/*.png) from the app running against fake models.

    <python with playwright> tools/manual_screenshots.py [--only NAME ...] [--server-python PATH] [--out docs/images/manual]

Playwright is not a dependency of ENLENS and is not in the project's virtual environment. Run this script with a Python
that has it (for example the one of `uv tool install playwright`, with Chromium installed), and let the dev server run in
the project's own environment:

    ~/.local/share/uv/tools/playwright/bin/python -I tools/manual_screenshots.py

- for each shot it starts tools/dev_server.py with the options the shot needs (a server is reused by the following shots
  when the options are the same), on a free port, with a data folder of its own in a temporary folder; nothing of the
  real ENLENS data is touched, and no real model or Claude Code is ever started,
- opens the page in Chromium (light theme, 1280 x 860, twice the pixels so text stays sharp), brings it to the state
  the manual shows (navigates, clicks, types, waits for the content), and saves a PNG of the part that matters,
- result.png carries small numbered badges, put on the page just before the picture is taken (`badge()`); the script
  prints which badge went where, and the manual's text must follow that order,
- when Pillow is available (in this Python, or in the server's) the PNGs are reduced to a palette of at most 256 colours
  so each stays small (aim: under 250 KB),
- the dev servers are always stopped at the end (terminate, then kill), even when a shot fails; the browser console's
  errors are printed per shot.

Run it whenever a screen shown in the manual changes, then look at every picture (they are the manual's evidence).
To add a shot: add a line to SHOTS and a function `shot_<name>(page)` (the name with `-` as `_`) that brings the page to
its state and returns what to photograph (a locator or None for the whole window).

--only NAME ... makes just those shots (names as in the list, without .png).
"""
from __future__ import annotations

import argparse
import atexit
import io
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV_SERVER = ROOT / "tools" / "dev_server.py"

# name (file name without .png) | dev_server.py options | what it shows
SHOTS = [
    ("first-use", ("--empty", "--claude-install"), "the welcome screen of a new user, with the AI step's checklist and Set up Claude"),
    ("result", ("--corpus", "social", "--claude-code"), "top of a finished check: the answer, who says what, Next to review, start of the evidence (numbered)"),
    ("excerpt-card", ("--corpus", "social", "--claude-code"), "one excerpt card with its judgement, quote and actions"),
    ("search", ("--corpus", "social", "--claude-code"), "Search: a word run, the count per document, concordance lines"),
    ("profile", ("--corpus", "social", "--claude-code"), "Profile: the grid of codes by document"),
    ("themes", ("--corpus", "social", "--claude-code"), "Themes: a set of themes"),
    ("map", ("--corpus", "social", "--claude-code"), "Results shown as a map"),
    ("settings-ai", ("--corpus", "social", "--claude-code"), "Settings, AI"),
    ("reading-view", ("--reading",), "a document in the reading view, with the Reading panel and Leave out on a hovered block"),
    ("bibliography", ("--corpus", "social", "--zotero"), "Bibliography after bringing in the stand-in Zotero library"),
    ("waiting", ("--corpus", "social", "--claude-code-paused"), "a check waiting for Claude Code: Start Claude Code and the speed choice"),
    ("documents", ("--mixed",), "Documents: each one a line that opens; who may read it with AI in its panel"),
]

VIEWPORT = {"width": 1280, "height": 860}
SIDEBAR = 264          # the sidebar's width: pictures of "the main part" start to its right
MAX_KB = 250


# --- the dev server ---------------------------------------------------------------------------------------------------

class DevServer:
    """One tools/dev_server.py process; `url` is the app's address once it is ready."""

    def __init__(self, python: str, options: tuple[str, ...]):
        self.options = options
        self.home = Path(tempfile.mkdtemp(prefix="enlens-manual-"))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        cmd = [python, str(DEV_SERVER), "--home", str(self.home), "--port", str(port), *options]
        self.lines: list[str] = []
        self.proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.url = self.token = ""
        ready = threading.Event()

        def drain():
            for line in self.proc.stdout:  # keeps the pipe empty so the server never blocks on it
                self.lines.append(line.rstrip())
                m = re.match(r"app: (http://\S+)", line)
                if m and not self.url:
                    self.url = m.group(1)
                t = re.match(r"token: (\S+)", line)  # printed after the address
                if t and not self.token:
                    self.token = t.group(1)
                    ready.set()
            ready.set()

        threading.Thread(target=drain, daemon=True).start()
        if not ready.wait(180) or not self.url:
            tail = "\n".join(self.lines[-15:])
            self.stop()
            raise RuntimeError(f"the dev server did not start ({' '.join(options)}):\n{tail}")

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)
        shutil.rmtree(self.home, ignore_errors=True)


class Servers:
    """Keeps the server of the current options; a shot with other options replaces it (one server at a time: memory)."""

    def __init__(self, python: str):
        self.python = python
        self.current: DevServer | None = None
        atexit.register(self.close)

    def get(self, options: tuple[str, ...]) -> DevServer:
        if self.current and self.current.options == options and self.current.proc.poll() is None:
            return self.current
        self.close()
        print(f"  dev server: {' '.join(options)}", flush=True)
        self.current = DevServer(self.python, options)
        return self.current

    def close(self) -> None:
        if self.current:
            self.current.stop()
            self.current = None


# --- helpers for the shots ----------------------------------------------------------------------------------------------

def badge(page, target, n: int, side: str = "left", note: str = "") -> None:
    """Put a numbered circle beside `target` (a selector or a Playwright locator): absolutely positioned on the page,
    in the free space to its left (or above-left for side="top"), so it never covers the text it points at."""
    loc = page.locator(target).first if isinstance(target, str) else target.first
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    if box is None:
        raise RuntimeError(f"badge {n}: target not visible")
    scroll = page.evaluate("[window.scrollX, window.scrollY]")
    size = 26
    x = box["x"] + scroll[0] - size - 8 if side == "left" else box["x"] + scroll[0] - 4
    y = box["y"] + scroll[1] + (2 if side == "left" else -size - 2)
    page.evaluate(
        """([x, y, n, size]) => {
            const b = document.createElement("div");
            b.className = "manual-badge";
            b.textContent = String(n);
            b.style.cssText = `position:absolute;left:${x}px;top:${y}px;width:${size}px;height:${size}px;border-radius:50%;
              background:#c2410c;color:#fff;font:700 15px/${size}px system-ui,sans-serif;text-align:center;z-index:99999;
              box-shadow:0 0 0 2px #fff,0 1px 4px rgba(0,0,0,.4);pointer-events:none`;
            document.body.appendChild(b);
        }""",
        [x, y, n, size],
    )
    print(f"  badge {n}: {note or (target if isinstance(target, str) else 'locator')}", flush=True)


def go(page, server: DevServer, route: str = "") -> None:
    page.goto(server.url + route)
    page.wait_for_selector("#view > *", timeout=30000)
    page.wait_for_timeout(600)


def settled(page, ms: int = 700) -> None:
    """No spinner left on the page, then a short pause for animations."""
    page.wait_for_function("!document.querySelector('#view .spinner, #view [aria-busy=true], #view .skeleton')", timeout=30000)
    page.wait_for_timeout(ms)


def main_area(page):
    return page.locator("main, #main, #view").first


def open_result(page, server: DevServer, text: str = "Working from home reduces commuting") -> None:
    go(page, server, "#/history")
    page.get_by_text(text).first.click()
    page.wait_for_selector("section.answer", timeout=30000)
    settled(page)


# --- the shots: each brings the page to its state and returns what to photograph --------------------------------------

def shot_first_use(page, server):
    go(page, server)
    page.get_by_role("button", name=re.compile("Set up Claude")).first.wait_for(timeout=30000)
    settled(page)
    return "window"


def shot_result(page, server):
    open_result(page, server)
    badge(page, "section.answer .answer-status", 1, note="the answer (Mixed evidence, judged by the AI)")
    badge(page, "section.answer .who", 2, note="who says what, one row per document")
    badge(page, "section.answer .next-review", 3, note="Next to review")
    badge(page, ".ev-section-head .ev-title-row", 4, note="the Evidence title and its Cards / Table switch")
    return ("area", 30, 760)


def shot_excerpt_card(page, server):
    open_result(page, server)
    return page.locator("article.ev").first


def shot_search(page, server):
    go(page, server, "#/search")
    page.fill("input[type=search]", "commuting")
    page.keyboard.press("Enter")
    page.wait_for_selector("text=places in", timeout=30000)
    settled(page)
    return ("area", 0, 860)


def shot_profile(page, server):
    go(page, server, "#/profile")
    if page.get_by_role("button", name=re.compile("Find the codes by keywords")).count():
        page.get_by_role("button", name=re.compile("Find the codes by keywords")).first.click()
    grid = page.locator("#view table.pf-grid").first
    grid.wait_for(timeout=60000)
    settled(page, 1200)
    return ("from", page.get_by_role("heading", name=re.compile("^Documents by")).first, 720)


def shot_themes(page, server):
    go(page, server, "#/themes")
    page.get_by_role("button", name="Find themes").first.click()
    page.wait_for_selector("text=Open a theme to read its passages", timeout=90000)
    settled(page, 1200)
    return ("area", 0, 860)


def shot_map(page, server):
    go(page, server, "#/map")
    settled(page, 1500)
    # one column per document: the grid scrolls sideways inside its box, so open the box to the grid's full width and
    # make the window wide enough for it, so that every column is in the picture
    width = page.evaluate("""() => {
        const w = document.querySelector('.map-wrap');
        const full = w.scrollWidth;
        w.style.cssText += `;overflow:visible;max-width:none;width:${full}px`;
        return full;
    }""")
    page.set_viewport_size({"width": SIDEBAR + width + 120, "height": VIEWPORT["height"]})
    page.wait_for_timeout(500)
    return ("area", 0, 740)


def shot_settings_ai(page, server):
    go(page, server, "#/settings/model")
    settled(page, 1000)
    return ("area", 0, 548)   # title, version, tabs and the four tiles; the set-up checklist below is left out


def shot_reading_view(page, server):
    # the first document read by the new reader (one that has the panel "How this document was read" without the
    # note about the old reader), with the pointer on a block of text so its Leave out button shows
    go(page, server, "#/sources")
    settled(page)
    hrefs = page.eval_on_selector_all("#view a[href^='#/doc/']", "els => [...new Set(els.map(e => e.getAttribute('href')))]")
    for href in hrefs:
        go(page, server, href)
        page.wait_for_selector("#view .passage-row", state="attached", timeout=30000)
        settled(page)
        if page.locator("#dv-read-h").count() and "Read by the reader of ENLENS before" not in page.inner_text("#view"):
            break
    page.locator("#view").get_by_role("button", name="Reading", exact=True).first.click()
    page.wait_for_selector("#dv-read-h", timeout=30000)
    settled(page)
    rows = page.locator("#view .passage-row:not(.dv-out)")
    rows.nth(min(3, rows.count() - 1)).hover()
    page.wait_for_timeout(400)
    return ("area", 0, 860)


def shot_bibliography(page, server):
    go(page, server, "#/bibliography")
    page.get_by_role("button", name="Bring in the bibliography").first.wait_for(timeout=30000)
    page.get_by_role("button", name="Bring in the bibliography").first.click()
    page.wait_for_selector("text=Please confirm", timeout=60000)
    settled(page, 1200)
    return ("area", 0, 860)


def shot_waiting(page, server):
    go(page, server, "#/check")
    page.fill("textarea#hyp", "Working from home reduces commuting emissions.")
    page.get_by_role("button", name="Check this hypothesis").click()
    page.locator("#view").get_by_role("button", name="Start Claude Code").first.wait_for(timeout=60000)
    settled(page, 1000)
    return ("from", page.get_by_role("heading", name=re.compile("^Checking")).first, 640)


def shot_documents(page, server):
    go(page, server, "#/sources")
    settled(page, 1000)
    # 0.18.3: a document is a line that opens; the picture shows one open, a document kept from Claude if there is one
    # (0.18.5: the list is grouped by who may read the documents; the first of the groups kept from Claude)
    page.evaluate("""() => { const items = [...document.querySelectorAll('.doc-item')];
      const it = document.querySelector('.doc-group[data-group="local"] .doc-item, .doc-group[data-group="none"] .doc-item') || items[0];
      if (it) it.querySelector('.doc-toggle').click(); }""")
    settled(page, 400)
    return ("from", page.get_by_role("heading", name=re.compile("documents? in this project$")).first, 640)


# --- taking and saving the picture -----------------------------------------------------------------------------------------

def take(page, what, path: Path) -> None:
    # the "what is new" note of the first start sits in a corner of every window: not part of the screens shown
    page.evaluate("document.querySelectorAll('.release-note, .update-popup').forEach((e) => e.remove())")
    page.evaluate("document.querySelectorAll('#toasts .toast').forEach((e) => e.remove())")
    if what == "window" or what is None:
        page.screenshot(path=str(path))
    elif isinstance(what, tuple) and what[0] == "area":   # the main part, from y to y + h (page coordinates)
        _, y, h = what
        page.screenshot(path=str(path), clip={"x": SIDEBAR, "y": y, "width": page.viewport_size["width"] - SIDEBAR, "height": h})
    elif isinstance(what, tuple) and what[0] == "from":    # the main part from an element downwards, h tall
        _, loc, h = what
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        top = page.evaluate("window.scrollY") + box["y"] - 24
        page.screenshot(path=str(path), full_page=True, clip={
            "x": SIDEBAR, "y": max(0, top), "width": page.viewport_size["width"] - SIDEBAR, "height": h})
    else:                                                   # a locator: its box with a little air
        what.scroll_into_view_if_needed()
        box = what.bounding_box()   # in the window's coordinates; a full-page clip takes the page's
        sx, sy = page.evaluate("[window.scrollX, window.scrollY]")
        pad = 8
        page.screenshot(path=str(path), full_page=True, clip={
            "x": max(0, sx + box["x"] - pad), "y": max(0, sy + box["y"] - pad), "width": box["width"] + 2 * pad, "height": box["height"] + 2 * pad})


QUANTISE = (
    "import sys\nfrom PIL import Image\np, n = sys.argv[1], int(sys.argv[2])\n"
    "im = Image.open(p).convert('RGB').quantize(colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)\n"
    "im.save(p, optimize=True)\n")


def quantise(path: Path, server_python: str) -> None:
    """Palette PNG: 256 colours, fewer when it is still over MAX_KB (text stays clean down to about 64)."""
    original = path.read_bytes()
    for n in (256, 128, 64):
        path.write_bytes(original)
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(original)).convert("RGB").quantize(
                colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
            im.save(path, optimize=True)
        except ImportError:   # no Pillow here: the server's Python has it
            r = subprocess.run([server_python, "-c", QUANTISE, str(path), str(n)], capture_output=True, text=True)
            if r.returncode:
                path.write_bytes(original)
                print("  (no Pillow: left as it is)")
                return
        if path.stat().st_size <= MAX_KB * 1024:
            return


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="+", metavar="NAME", help="make only these shots (names without .png)")
    default_py = ROOT / ".venv" / "bin" / "python"
    ap.add_argument("--server-python", default=str(default_py) if default_py.exists() else "python3",
                    help="the Python that runs tools/dev_server.py (default: the project's .venv)")
    ap.add_argument("--out", default=str(ROOT / "docs" / "images" / "manual"))
    a = ap.parse_args()
    names = [s[0] for s in SHOTS]
    if a.only and (bad := [n for n in a.only if n not in names]):
        ap.error(f"unknown shot(s) {bad}; known: {', '.join(names)}")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    chosen = [s for s in SHOTS if not a.only or s[0] in a.only]
    chosen.sort(key=lambda s: [x[1] for x in SHOTS].index(s[1]))   # shots with the same options come together

    from playwright.sync_api import sync_playwright

    servers = Servers(a.server_python)
    failed: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for name, options, _what in chosen:
                print(f"{name}", flush=True)
                ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2, color_scheme="light")
                ctx.add_init_script("try { localStorage.setItem('enlens.theme', 'light'); } catch (e) {}")
                page = ctx.new_page()
                errors: list[str] = []
                page.on("console", lambda m, e=errors: e.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda x, e=errors: e.append(str(x)))
                try:
                    server = servers.get(tuple(options))
                    # 0.17.2: the page carries no token: the tab holds it, as one opened from the app's link would
                    ctx.add_init_script(f"try {{ sessionStorage.setItem('enlens-token', {json.dumps(server.token)}); }} catch (e) {{}}")
                    what = globals()["shot_" + name.replace("-", "_")](page, server)
                    path = out / f"{name}.png"
                    take(page, what, path)
                    quantise(path, a.server_python)
                    size = path.stat().st_size
                    px = _png_size(path)
                    print(f"  saved {path.name}: {px[0]} x {px[1]} px, {size / 1024:.0f} KB", flush=True)
                except Exception as e:  # noqa: BLE001 - one failing shot must not stop the others
                    failed.append(name)
                    print(f"  FAILED {name}: {type(e).__name__}: {str(e)[:400]}", flush=True)
                finally:
                    for line in errors:
                        print(f"  console error: {line[:300]}", flush=True)
                    ctx.close()
            browser.close()
    finally:
        servers.close()
    if failed:
        print(f"not made: {', '.join(failed)}")
    return 1 if failed else 0


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:32]
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


if __name__ == "__main__":
    sys.exit(main())
