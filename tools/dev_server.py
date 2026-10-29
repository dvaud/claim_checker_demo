"""Run the app against fake local servers, for developing and testing the interface without real models.

    python tools/dev_server.py [--port 8765] [--home /tmp/enlens-dev] [--pilot path/to/pilot] [--delay 0.05]

- starts a fake Ollama (chat model `fake-model:latest`, embedding model `fake-embed:latest`; with `--fresh-user` or
  `--corpus social` it lists them as `qwen3:8b` and `nomic-embed-text:latest`, as a real install would) on a free port,
- creates a data folder with a project "Demo" (three small sources, a semantic index, a few checks),
- optionally links a real workspace (for example the pilot) as a second project,
- starts the app with its API token printed, so the API can be called with curl as well;
- with `--claude-code` (0.8): Settings name Claude Code, and a fake Claude Code session answers the queue every few
  seconds (tests/fake_claude_code.py), as if the researcher had typed /enlens-run; `--claude-code-paused` leaves the
  queue unanswered, to see the waiting and paused states.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
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
    a = ap.parse_args()
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
        ingest.ingest(ws, [corpus])
        emb = home.make_embedder(home.load_settings())
        embed.build(ws, emb)
        be = OllamaBackend(base_url=fake_url)
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
    if a.claude_code or a.claude_code_paused:
        home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
        from enlens_claims import claude_setup

        claude_setup.write_plugin()
    if a.claude_code:
        import time

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
    srv, app = make_server("127.0.0.1", a.port)
    app.stop = lambda: threading.Thread(target=srv.shutdown, daemon=True).start()  # "Quit ENLENS" works here too
    app.launcher = a.fresh_user  # a new user starts it from the ENLENS icon
    print(f"data folder: {home_dir}\nfake Ollama: {fake_url}\napp: http://127.0.0.1:{srv.server_address[1]}/\n"
          f"token: {app.token}", flush=True)
    try:
        srv.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        fake.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
