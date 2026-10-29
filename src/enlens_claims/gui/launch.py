"""`enlens-gui`: start the hypothesis checker in the browser.

    enlens-gui                     # opens http://127.0.0.1:8765
    enlens-gui --home D:/enlens    # keep projects and settings in another folder
    enlens-gui --port 8600 --headless
    enlens-gui --local-only        # no cloud option at all (for installers)
    enlens-gui --make-launcher     # put an ENLENS icon on the Desktop: double-click it, no terminal needed
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="enlens-gui", description="Start the ENLENS hypothesis checker in your browser.")
    ap.add_argument("--home", help="folder for projects and settings (default: ~/enlens, or ENLENS_HOME)")
    ap.add_argument("--port", type=int, default=8765, help="port (default 8765; the next free one is used if taken)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (default 127.0.0.1: this computer only). 0.0.0.0 exposes the app to "
                         "your network: open the link it prints, which carries the access token.")
    ap.add_argument("--headless", action="store_true", help="do not open a browser window")
    ap.add_argument("--local-only", action="store_true",
                    help="switch the cloud option off for good: nothing can be sent to a cloud model (for installers; "
                         "the same as ENLENS_LOCAL_ONLY=1 or a file named local_only in the data folder)")
    ap.add_argument("--make-launcher", action="store_true",
                    help="create an ENLENS icon (Desktop; macOS also ~/Applications, Windows also the Start menu, Linux "
                         "also the applications menu) that starts the app without a terminal. --home and --local-only "
                         "given here are built into the icon.")
    ap.add_argument("--launcher-dir", action="append", metavar="FOLDER",
                    help="with --make-launcher: put the icon in this folder instead (repeatable)")
    ap.add_argument("--launcher", action="store_true",
                    help="what the icon runs: open the app if it is already running, otherwise start it in the "
                         "background (output to logs/enlens.log in the data folder) and open it")
    ap.add_argument("--no-start-ollama", action="store_true",
                    help="with --launcher: do not start the Ollama app when it is not running")
    a = ap.parse_args(argv)
    if a.local_only:
        os.environ["ENLENS_LOCAL_ONLY"] = "1"
    if a.home:
        os.environ["ENLENS_HOME"] = str(Path(a.home).expanduser().resolve())
    if a.make_launcher:
        from .launcher import make_launcher

        made = make_launcher(a.home, a.local_only, [Path(f).expanduser() for f in a.launcher_dir or []] or None)
        print("ENLENS can now be started without the terminal: double-click")
        for m in made:
            print(f"  {m}")
        return 0
    if a.launcher:
        from .. import home
        from . import launcher

        live = launcher.running()
        if live:  # already running: just show it
            if not a.headless:
                import webbrowser

                webbrowser.open(live["url"])
            print(f"ENLENS is already running at {live['url']}.")
            return 0
        launcher.detach()
        launcher.log_to_file()
        if not a.no_start_ollama:
            started = launcher.start_ollama(home.load_settings())
            if started:
                print(f"Started {started} (the model service was not running).")
    from .server import serve

    return serve(a.host, a.port, open_browser=not a.headless, launcher=a.launcher)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
