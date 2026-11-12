"""Run the app against fake local servers, for developing and testing the interface without real models.

    python tools/dev_server.py [--port 8765] [--home /tmp/enlens-dev] [--pilot path/to/pilot] [--delay 0.05]

- starts a fake Ollama (chat model `fake-model:latest`, embedding model `fake-embed:latest`; with `--fresh-user` or
  `--corpus social` it lists them as `qwen3:8b` and `nomic-embed-text:latest`, as a real install would) on a free port,
- creates a data folder with a project "Demo" (three small sources, a semantic index, a few checks),
- optionally links a real workspace (for example the pilot) as a second project,
- starts the app with its API token printed, so the API can be called with curl as well;
- with `--claude-code` (0.8): Settings name Claude Code, and a fake Claude Code session answers the queue every few
  seconds (tests/fake_claude_code.py), as if the researcher had typed /enlens-run; `--claude-code-paused` leaves the
  queue unanswered, to see the waiting and paused states (0.14.3: both find the stand-in `claude` program, and no
  mode of the dev server ever finds the real one: it would read the developer's Claude account into the settings and
  *Start Claude Code* would run on their plan);
- with `--claude-cli` (0.9): Claude Code chosen, and a stand-in `claude` program (tests/fake_claude_cli.py) that the
  app finds, adds the plugin to, and starts with "Start Claude Code" (each run waits 2 s per round, so the progress
  can be watched). Add `--empty` to see the first-run screens as a new user of 0.9 does.
- with `--claude-install` (0.10): Claude Code chosen but not on the computer yet, and signed out: "Set up Claude"
  runs a stand-in installer (tests/fake_claude_installer.py, 3 s), opens a stand-in sign-in that signs in after 6 s,
  and adds the plugin. Combine with `--empty` for a new user's first screen.
- with `--zotero` (0.13): a stand-in Zotero answering like the Zotero app's local API, with a library for the
  remote-work demo corpus (use it with `--corpus social` or `--fresh-user`): one work whose PDF is the very file in
  the project, three found by their title, one with a PDF to add, works still to find. `--zotero api_off` is a Zotero
  whose box "Allow other applications…" is not ticked, `--zotero old` a Zotero 6, `--zotero closed` no Zotero open.
- with `--update` (0.13.1): "Update ENLENS" in the sidebar finds a stand-in newer release (nothing is fetched or
  installed: the install takes 2 s) and restarts the app in this process, with a new token, so the page's wait and
  reload can be watched. `--update commits` is a git copy with 3 new commits, `--update on-disk` a newer version
  installed while this one ran (the banner with *Restart now*), `--update none` an ENLENS that is up to date, and
  `--update fails` an install that fails. `--update windows` (0.15.4) is the hand-over of Windows: the app quits and
  comes back 6 s later (the install), `--update windows-fails` the same with an install that did not finish (the
  note that says why).
- with `--ollama` (0.13.7): a model on this computer chosen, but no model yet. `--ollama empty` is an Ollama with no
  model (its *Download* takes 12 s, then the model answers), `--ollama later` an Ollama that starts 15 s after the
  app (the page notices it by itself), `--ollama none` no Ollama at all. Other servers on this computer (LM Studio…)
  are not looked for. Combine with `--empty` for a new user's first screen. 0.15.6: `--ollama install` is no Ollama on
  the computer: *Install Ollama* shows the real size of Ollama's download for this computer (asked of ollama.com), then
  a stand-in install (nothing is downloaded or installed: 12 s of download, 2 s each to check and install), after which
  the stand-in Ollama answers; `--ollama stopped` is an Ollama installed but not running (*Start Ollama*, 3 s).
- with `--low-memory` (0.13.11): the computer has 2.7 GB free and every local model needs 8.1 GB, so the local model
  for documents marked Only a local AI is not started (use it with `--mixed --claude-code`): see the note on the
  progress, the excerpts that wait, and *Read them now* → *Start it anyway*.
- 0.18: as `enlens-gui` does, the app looks in each project's shared folder by itself every couple of minutes (the
  poller, gui/poller.py), so the Team tab's rounds by themselves can be tried: choose a shared folder for a project
  (two dev servers with their own `--home` and one folder make two colleagues). None of the projects made here has
  one, so until then it only looks. `--no-poller` leaves it off (*Sync now* still works).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]


def social_documents(folder: Path, make_pdf) -> Path:
    """The remote-work demo corpus as a user would have it: two PDFs (with pages), text files and a saved web page."""
    src = ROOT / "tools" / "demo_corpus"
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("panel_study_wellbeing.txt", "hybrid_productivity_review.txt"):
        text = (src / name).read_text(encoding="utf-8")
        paras = [p for p in text.split("\n\n") if p.strip()]
        half = (len(paras) + 1) // 2
        title = paras[0].split("\n")[0]
        make_pdf(folder / name.replace(".txt", ".pdf"), ["\n\n".join(paras[:half]), "\n\n".join(paras[half:])], title=title)
    for name in ("commuting_emissions_report.txt", "young_employees_interviews.txt", "municipal_policy_brief.txt",
                 "news_article_traffic.html"):
        (folder / name).write_text((src / name).read_text(encoding="utf-8"), encoding="utf-8")
    return folder


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--home", default=None)
    ap.add_argument("--pilot", default=None, help="a workspace folder to link as a project")
    ap.add_argument("--delay", type=float, default=0.03, help="seconds between streamed chunks of the fake model")
    ap.add_argument("--empty", action="store_true", help="no demo project: see the first-run screens")
    ap.add_argument("--fresh-user", action="store_true",
                    help="as set up for a new user: model configured, no project yet, and a folder of documents "
                         "(tools/demo_corpus) ready to add")
    ap.add_argument("--corpus", choices=["hydrogen", "social"], default="hydrogen",
                    help="documents of the seeded Demo project (social: the remote-work demo corpus)")
    ap.add_argument("--claude-code", action="store_true", help="0.8: Claude Code answers (a fake session, every 3 s)")
    ap.add_argument("--claude-code-paused", action="store_true", help="0.8: Claude Code chosen, but nothing answers")
    ap.add_argument("--claude-cli", action="store_true",
                    help="0.9: Claude Code chosen, with a stand-in claude program the app sets up and starts")
    ap.add_argument("--no-tesseract", action="store_true", help="0.10: act as if Tesseract were not installed")
    ap.add_argument("--claude-install", action="store_true",
                    help="0.10: Claude Code not installed yet and signed out: Set up Claude installs it (stand-ins)")
    ap.add_argument("--mixed", action="store_true",
                    help="0.11: the Demo project's documents have each AI setting (one Claude may read, one only a local "
                         "AI, one no AI), Claude Code is the AI and the fake local model reads the restricted one")
    ap.add_argument("--zotero", nargs="?", const="ready", choices=["ready", "api_off", "old", "closed"],
                    help="0.13: a stand-in Zotero (its local API) with a library for the remote-work demo corpus")
    ap.add_argument("--update", nargs="?", const="release",
                    choices=["release", "commits", "on-disk", "none", "fails", "windows", "windows-fails"],
                    help="0.13.1: Update ENLENS finds a stand-in newer version and restarts the app in this process")
    ap.add_argument("--ollama", nargs="?", const="empty", choices=["empty", "later", "none", "install", "stopped"],
                    help="0.13.7: a model on this computer chosen, but no model yet (empty), Ollama later, or none; "
                         "0.15.6: Ollama not on the computer (install, a stand-in install) or not running (stopped)")
    ap.add_argument("--reading", action="store_true",
                    help="0.15: a project 'Reading' with PDFs of known text (columns, running heads, line numbers, front and "
                         "back matter, a table, footnotes) read by the new reader, and one read by the old reader with a check "
                         "on it, to try the reading view and Read with the new reader")
    ap.add_argument("--low-memory", action="store_true",
                    help="0.13.11: too little memory free for the local model (2.7 GB free, 8.1 GB needed)")
    ap.add_argument("--no-poller", action="store_true",
                    help="0.18: do not look in the projects' shared folders by themselves (Sync now still works)")
    a = ap.parse_args()
    home_dir = Path(a.home or tempfile.mkdtemp(prefix="enlens-dev-"))
    os.environ["ENLENS_HOME"] = str(home_dir)
    # 0.14.3: the real Claude Code is never found, in any mode: the app would read the developer's own signed-in account
    # and plan into the dev settings, and *Start Claude Code* would start a real run on their plan. By default nothing
    # answers as `claude`; the Claude Code modes below put the stand-in in its place.
    os.environ["ENLENS_CLAUDE"] = str(home_dir / "no-claude-here")

    import fake_servers
    from helpers import PAPER_A_PAGES, REPORT_B_TEXT, UNRELATED_HTML, make_pdf

    from enlens_claims import claimcheck, embed, home, ingest
    from enlens_claims.gui.server import App, make_server
    from enlens_claims.llm import OllamaBackend

    if a.low_memory:  # 0.13.11: the memory figures of the user test that all but froze a 16 GB Mac
        from enlens_claims import llm

        llm.free_memory = lambda: int(2.7 * (1 << 30))
        OllamaBackend.memory_need = lambda self, model: int(8.1 * (1 << 30))
    fake, fake_url = fake_servers.start("ollama")
    fake.delay = 0.0  # seeding runs at full speed; the delay applies to checks made in the app
    fake.varied = True
    chat_model, embed_model = fake_servers.FAKE_MODEL, fake_servers.FAKE_EMBED
    if a.fresh_user or a.corpus == "social":  # the names a real install would show, so a test user sees no "fake"
        chat_model, embed_model = "qwen3:8b", "nomic-embed-text:latest"
        fake.aliases = {chat_model: fake_servers.FAKE_MODEL, embed_model: fake_servers.FAKE_EMBED,
                        "llama3.1:8b": fake_servers.SECOND}  # a second model, for "Ask a second AI model"
    home.update_settings({"backend": "ollama", "ollama_url": fake_url, "ollama_model": chat_model,
                          "embed_backend": "ollama", "embed_model": embed_model})
    if a.fresh_user:
        docs = social_documents(home_dir / "My documents" / "Remote work literature", make_pdf)
        print(f"documents ready to add: {docs}")
    elif not a.empty and "Demo" not in home.list_projects():
        if a.corpus == "social":
            corpus = social_documents(home_dir / "demo_sources", make_pdf)
        else:
            corpus = home_dir / "demo_sources"
            corpus.mkdir(exist_ok=True)
            make_pdf(corpus / "paper_a.pdf", PAPER_A_PAGES, title="Water footprint of electrolytic hydrogen in arid export regions")
            (corpus / "irena_jobs_report.txt").write_text(REPORT_B_TEXT)
            (corpus / "birds.html").write_text(UNRELATED_HTML)
        ws = home.create_project("Demo")
        ingest.ingest(ws, [corpus], ai_access="cloud")
        emb = home.make_embedder(home.load_settings())
        embed.build(ws, emb)
        be = OllamaBackend(base_url=fake_url)
        if a.mixed:  # 0.11: one document per AI setting; "Claude" (the fake model under Claude's name) reads the rest
            from enlens_claims import access

            docs = [r[0] for r in ws.query("SELECT doc_id FROM documents ORDER BY title")]
            access.set_documents(ws, docs[:1], "local", note="publisher licence")
            access.set_documents(ws, docs[1:2], "none", note="contains interview data")
            home.update_settings({"allow_claude_code": True, "backend": "claude_code", "restricted_server": "ollama",
                                  "restricted_model": chat_model})

            class FakeClaude(OllamaBackend):
                name = "anthropic"

            be = FakeClaude(base_url=fake_url)
        checks = ([("Working from home reduces commuting emissions.", False),
                   ("Hybrid work improves wellbeing and increases loneliness among young employees.", True),
                   ("Remote work lowers the quality of public services.", False)] if a.corpus == "social" else
                  [("Green hydrogen production can increase water stress in arid regions.", False),
                   ("Hydrogen export hubs create local jobs and reduce emissions in importing countries.", True),
                   ("Swallows migrate north in autumn.", False)])
        for text, dec in checks:
            claimcheck.check_hypothesis(ws, text, be, chat_model, decompose=dec, embedder=emb)
        home.update_settings({"project": "Demo"})
    if a.reading and "Reading" not in home.list_projects():
        from enlens_claims import measure

        folder = home_dir / "reading_sources"
        folder.mkdir(exist_ok=True)
        cases = measure.make_known_texts(folder)
        ws = home.create_project("Reading")
        old = [c.path for c in cases if c.name.startswith("d_")]
        reader_now = ingest.READER
        ingest.READER = 1  # one document as ENLENS 0.14 read it, to move to the new reader
        try:
            ingest.ingest(ws, old, ai_access="cloud")
        finally:
            ingest.READER = reader_now
        ingest.ingest(ws, [c.path for c in cases if c.path not in old], ai_access="cloud")
        emb = home.make_embedder(home.load_settings())
        embed.build(ws, emb)
        claimcheck.check_hypothesis(ws, "Coastal residents overestimate how fast their cliffs retreat.",
                                    OllamaBackend(base_url=fake_url), chat_model, embedder=emb)
        home.update_settings({"project": "Reading"})
    if a.pilot:
        try:
            home.link_existing(a.pilot, "Pilot")
        except ValueError as e:
            print(e)
    fake.delay = a.delay
    if a.ollama:  # 0.13.7: a model on this computer, with no model yet (only these stand-ins are looked for)
        from enlens_claims import llm

        llm.OPENAI_PORTS = ()
        fake.aliases = {"qwen3:8b": fake_servers.FAKE_MODEL, "nomic-embed-text:latest": fake_servers.FAKE_EMBED}
        fake.installed, fake.pull_seconds = [], 12.0
        dead = "http://127.0.0.1:9"   # nothing answers there: "no Ollama yet"
        home.update_settings({"backend": "auto", "ollama_url": fake_url if a.ollama == "empty" else dead,
                              "ollama_model": "", "embed_backend": "off", "embed_model": ""})
        if a.ollama == "later":  # the stand-in "starts": the address in Settings points at it after 15 s
            def start_later():
                time.sleep(15)
                home.update_settings({"ollama_url": fake_url})
                print(f"stand-in Ollama now answers at {fake_url}, with no model")
            threading.Thread(target=start_later, daemon=True).start()
    if a.ollama in ("install", "stopped"):   # 0.15.6: the real Ollama of this computer is never found, started or replaced
        from enlens_claims import ollama_setup

        there = {"installed": a.ollama == "stopped"}
        fake_app = home_dir / "Ollama.app"
        ollama_setup.app_path = lambda sys_name=None: fake_app if there["installed"] else None

        def fake_start(sys_name=None):
            def later():
                time.sleep(3)
                home.update_settings({"ollama_url": fake_url})
                print(f"stand-in Ollama started: it answers at {fake_url}, with no model")
            threading.Thread(target=later, daemon=True).start()
            return {"started": True, "path": str(fake_app), "serve": False}

        def fake_download(url, dest, on_progress, should_stop):   # nothing is fetched: 12 s at the real size
            total = ollama_setup.download_size()["bytes"]
            for i in range(61):
                if should_stop():
                    return False
                on_progress({"step": "download", "done": total * i // 60, "total": total})
                time.sleep(0.2)
            return True

        def fake_install(app):
            time.sleep(2)
            there["installed"] = True
            return fake_app

        ollama_setup.start = fake_start
        ollama_setup._download = fake_download
        ollama_setup._unpack_mac = lambda zip_path, work: work
        ollama_setup.check_mac = ollama_setup.check_windows = lambda path: time.sleep(2) or ""
        ollama_setup._install_mac = ollama_setup._install_windows = fake_install
    if a.no_tesseract:
        ingest.find_tesseract = lambda: ""
        ingest._OCR_STATUS[:] = [0.0, None]
    if a.claude_code or a.claude_code_paused:
        os.environ["ENLENS_CLAUDE"] = str(ROOT / "tests" / "fake_claude_cli.py")  # the stand-in, never the real one
        os.environ.setdefault("FAKE_CLAUDE_DELAY", "2")
        home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
        from enlens_claims import claude_setup

        claude_setup.write_plugin()
    if a.claude_cli:
        os.environ["ENLENS_CLAUDE"] = str(ROOT / "tests" / "fake_claude_cli.py")
        os.environ.setdefault("FAKE_CLAUDE_DELAY", "2")
        home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    if a.claude_install:
        import subprocess

        from enlens_claims import claude_setup

        os.environ["ENLENS_CLAUDE"] = str(home_dir / "claude-code" / "claude.py")
        os.environ["ENLENS_CLAUDE_INSTALLER"] = str(ROOT / "tests" / "fake_claude_installer.py")
        os.environ.setdefault("FAKE_INSTALLER_DELAY", "3")
        os.environ["FAKE_CLAUDE_LOGGED_OUT"] = "1"
        home.update_settings({"allow_claude_code": True, "backend": "claude_code"})

        def sign_in_later(script):  # the "window": the stand-in signs in after a few seconds
            def run():
                time.sleep(6)
                subprocess.run([sys.executable, os.environ["ENLENS_CLAUDE"]], capture_output=True)
            threading.Thread(target=run, daemon=True).start()
            return "Terminal (stand-in)"

        claude_setup._open_window = sign_in_later
    if a.claude_code:
        import fake_claude_code

        def session():
            while True:
                time.sleep(3)
                for name in home.list_projects():
                    try:
                        fake_claude_code.run(name, tools=fake_claude_code.DirectTools(), wrong_first=False)
                    except Exception as e:  # noqa: BLE001 - keep the session going
                        print(f"fake Claude Code: {e}", file=sys.stderr)

        threading.Thread(target=session, daemon=True).start()
    if a.zotero:
        import socket

        import fake_zotero

        panel = next((p for p in (home_dir / "demo_sources" / "panel_study_wellbeing.pdf",
                                  home_dir / "My documents" / "Remote work literature" / "panel_study_wellbeing.pdf")
                      if p.exists()), None)
        z = fake_zotero.demo_library(home_dir / "Zotero" / "storage", same_as=panel, make_pdf=make_pdf)
        z.mode = a.zotero if a.zotero in ("api_off", "old") else "ready"
        url = z.start()
        if a.zotero == "closed":  # a port nothing answers on
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        os.environ["ENLENS_ZOTERO_URL"] = url
        print(f"stand-in Zotero: {url} ({a.zotero})")
    if a.update:
        stand_in_update(a.update)
    port = a.port
    token = None  # 0.17.2: a restart keeps the token, as the real one does (the open tab keeps it)
    try:
        while True:
            srv, app = make_server("127.0.0.1", port, App(token=token))
            token = app.token
            app.stop = lambda: threading.Thread(target=srv.shutdown, daemon=True).start()  # "Quit ENLENS" works too
            app.launcher = a.fresh_user  # a new user starts it from the ENLENS icon
            again = threading.Event()
            drop = None
            if a.update:  # 0.13.1: "Update ENLENS" restarts the app in this process
                app.restart = lambda: (again.set(), app.stop())
                drop = track_connections(srv)
            port = srv.server_address[1]
            # 0.17.2: the page carries no token: open the link
            print(f"data folder: {home_dir}\nfake Ollama: {fake_url}\napp: http://127.0.0.1:{port}/\n"
                  f"token: {app.token}\nlink: http://127.0.0.1:{port}/#token={app.token}", flush=True)
            if not a.no_poller:
                app.poller.start()  # 0.18 (L3): as serve() does (each app of a restart has its own)
            try:
                srv.serve_forever(poll_interval=0.3)
            except KeyboardInterrupt:
                break
            finally:
                app.poller.stop()  # no round starts once this app stops
                srv.server_close()
            if HANDOVER["pending"]:  # 0.15.4: the app quit for the Windows hand-over: "install", then come back
                HANDOVER["pending"] = False
                drop()
                time.sleep(6)
                if a.update == "windows-fails":
                    from enlens_claims import update as _upd

                    _upd.updates_folder().mkdir(parents=True, exist_ok=True)
                    _upd.result_path().write_text(json.dumps({"ok": False, "hint": "in_use",
                                                              "version": HANDOVER["version"]}), encoding="utf-8")
                print("started again after the stand-in hand-over", flush=True)
                continue
            if not again.is_set():
                break
            drop()
            time.sleep(1.5)  # as a real restart takes a moment
            print("restarted (stand-in update)", flush=True)
    finally:
        fake.shutdown()
    return 0


def track_connections(srv):
    """0.13.1: a function that closes the server's open connections. A real restart replaces the process, which
    closes them; here the old app's threads would go on answering the page's kept-alive connection with its old
    token, and the page would never see the restarted app."""
    import socket
    import weakref

    conns = weakref.WeakSet()
    process = srv.process_request

    def track(request, client_address):
        conns.add(request)
        process(request, client_address)

    def drop():
        for c in list(conns):
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    srv.process_request = track
    return drop


HANDOVER = {"pending": False, "version": ""}  # 0.15.4: --update windows: the app quit for the hand-over


def stand_in_update(mode: str) -> None:
    """0.13.1: `--update`: what update.update() would say, without GitHub, git or uv."""
    from enlens_claims import __version__, update
    from enlens_claims.gui import server

    # a release candidate (0.17.0rc4) is followed by the next candidate (0.17.0rc5), a release by the next patch
    import re as _re
    m = _re.match(r"^(.*?)(\d+)$", __version__)
    newer = f"{m.group(1)}{int(m.group(2)) + 1}" if m else __version__ + ".1"
    if mode == "on-disk":
        server._installed_version = lambda: newer
        return

    def fake(check_only: bool = False, **_kw) -> dict:
        if mode == "none":
            return {"updated": False, "version": __version__, "message": f"ENLENS {__version__} is up to date."}
        if check_only:
            return {"updated": False, "version": __version__, "waiting": 3 if mode == "commits" else newer,
                    "message": "A newer ENLENS is waiting."}
        time.sleep(2)
        if mode == "fails":
            raise update.UpdateError("Could not ask GitHub for the newest ENLENS (URLError: timed out). Are you online?")
        if mode.startswith("windows"):
            HANDOVER.update(pending=True, version=newer)
            return {"updated": True, "from": __version__, "version": newer, "route": "release", "handover": True,
                    "message": "handed over"}
        return {"updated": True, "from": __version__, "version": newer, "message": f"ENLENS updated to {newer}."}

    update.update = fake


if __name__ == "__main__":
    sys.exit(main())
