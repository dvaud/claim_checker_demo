"""Run the app against fake local servers, for developing and testing the interface without real models.

    python tools/dev_server.py [--port 8765] [--home /tmp/enlens-dev] [--pilot path/to/pilot] [--delay 0.05]

- starts a fake Ollama (chat model `fake-model:latest`, embedding model `fake-embed:latest`; with `--fresh-user` or
  `--corpus social` it lists them as `qwen3:8b` and `nomic-embed-text:latest`, as a real install would) on a free port,
- creates a data folder with a project "Demo" (three small sources, a semantic index, a few checks),
- optionally links a real workspace (for example the pilot) as a second project,
- starts the app with its API token printed, so the API can be called with curl as well;
- with `--claude-code` (0.8): Settings name Claude Code, and a fake Claude Code session answers the queue every few
  seconds (tests/fake_claude_code.py), as if the researcher had typed /enlens-run; `--claude-code-paused` leaves the
  queue unanswered, to see the waiting and paused states;
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
  `--update fails` an install that fails.
- with `--ollama` (0.13.7): a model on this computer chosen, but no model yet. `--ollama empty` is an Ollama with no
  model (its *Download* takes 12 s, then the model answers), `--ollama later` an Ollama that starts 15 s after the
  app (the page notices it by itself), `--ollama none` no Ollama at all. Other servers on this computer (LM Studio…)
  are not looked for. Combine with `--empty` for a new user's first screen.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]


# 0.13.7: a researcher's draft citing the remote-work demo's works (some say it, some only partly, some not; one work
# has no document in the project yet, one is not in the bibliography), for --citations
CITING_DRAFT = """Chapter 2. Remote work and wellbeing

Since the pandemic, many employers let staff work from home part of the week. Employees who work from home at least two days a week report higher life satisfaction than those at the office every day (Verhoeven & Okafor, 2025). The difference is largest for parents of young children (Verhoeven & Okafor, 2025).

The environmental gains are often overstated. Remote work cuts commuting emissions by more than half (Rivermouth Mobility Institute, 2024), and a four-day week cuts them by about a fifth (Haugen, 2024).

Productivity is a more contested question. Lindqvist (2025) found that hybrid work lowers productivity overall. Young employees who work remotely feel lonely and miss learning from colleagues (Adeyemi & Brandt, 2024; Okafor, 2023). Employers respond by bringing staff back to the office (Moreau, 2023).

Older employees, by contrast, report no change in their wellbeing (Smith, 2019).
"""


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
    ap.add_argument("--citations", action="store_true",
                    help="0.13.7: the remote-work demo with its Zotero library brought in and a draft whose citations "
                         "wait to be checked (implies --corpus social --zotero)")
    ap.add_argument("--zotero", nargs="?", const="ready", choices=["ready", "api_off", "old", "closed"],
                    help="0.13: a stand-in Zotero (its local API) with a library for the remote-work demo corpus")
    ap.add_argument("--update", nargs="?", const="release", choices=["release", "commits", "on-disk", "none", "fails"],
                    help="0.13.1: Update ENLENS finds a stand-in newer version and restarts the app in this process")
    ap.add_argument("--ollama", nargs="?", const="empty", choices=["empty", "later", "none"],
                    help="0.13.7: a model on this computer chosen, but no model yet (empty), Ollama later, or none")
    a = ap.parse_args()
    if a.citations:
        a.corpus, a.zotero = "social", a.zotero or "ready"
    home_dir = Path(a.home or tempfile.mkdtemp(prefix="enlens-dev-"))
    os.environ["ENLENS_HOME"] = str(home_dir)

    import fake_servers
    from helpers import PAPER_A_PAGES, REPORT_B_TEXT, UNRELATED_HTML, make_pdf

    from enlens_claims import claimcheck, embed, home, ingest
    from enlens_claims.gui.server import make_server
    from enlens_claims.llm import OllamaBackend

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
    if a.no_tesseract:
        ingest.find_tesseract = lambda: ""
        ingest._OCR_STATUS[:] = [0.0, None]
    if a.claude_code or a.claude_code_paused:
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
        if a.citations and "Demo" in home.list_projects():
            from enlens_claims import bibliography, citations

            ws = home.open_project("Demo")
            works, src = bibliography.pull_zotero("user", "RWCOLL01", True)
            src["library_name"] = "My Library"
            bibliography.save(ws, works, src)
            bibliography.confirm_all(ws)
            citations.add_text(ws, CITING_DRAFT, title="Chapter 2: remote work and wellbeing (draft)")
            print("citations: the Zotero library is in the Demo project, with a draft to check")
    if a.update:
        stand_in_update(a.update)
    port = a.port
    try:
        while True:
            srv, app = make_server("127.0.0.1", port)
            app.stop = lambda: threading.Thread(target=srv.shutdown, daemon=True).start()  # "Quit ENLENS" works too
            app.launcher = a.fresh_user  # a new user starts it from the ENLENS icon
            again = threading.Event()
            drop = None
            if a.update:  # 0.13.1: "Update ENLENS" restarts the app in this process, with a new token
                app.restart = lambda: (again.set(), app.stop())
                drop = track_connections(srv)
            port = srv.server_address[1]
            print(f"data folder: {home_dir}\nfake Ollama: {fake_url}\napp: http://127.0.0.1:{port}/\n"
                  f"token: {app.token}", flush=True)
            try:
                srv.serve_forever(poll_interval=0.3)
            except KeyboardInterrupt:
                break
            finally:
                srv.server_close()
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


def stand_in_update(mode: str) -> None:
    """0.13.1: `--update`: what update.update() would say, without GitHub, git or uv."""
    from enlens_claims import __version__, update
    from enlens_claims.gui import server

    nums = [int(x) for x in __version__.split(".")]
    newer = ".".join(map(str, nums[:-1] + [nums[-1] + 1]))
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
        return {"updated": True, "from": __version__, "version": newer, "message": f"ENLENS updated to {newer}."}

    update.update = fake


if __name__ == "__main__":
    sys.exit(main())
