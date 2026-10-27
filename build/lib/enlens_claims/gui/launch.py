"""`enlens-gui`: start the claim checker in the browser.

    enlens-gui                     # opens http://localhost:8501
    enlens-gui --home D:/enlens    # keep projects and settings in another folder
    enlens-gui --port 8600
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="enlens-gui", description="Start the ENLENS claim checker in your browser.")
    ap.add_argument("--home", help="folder for projects and settings (default: ~/enlens, or ENLENS_HOME)")
    ap.add_argument("--port", type=int, default=8501)
    ap.add_argument("--headless", action="store_true", help="do not open a browser window")
    a = ap.parse_args(argv)
    try:
        from streamlit.web import cli as stcli
    except ImportError:
        print("The interface needs Streamlit: pip install 'enlens-claims[gui]'", file=sys.stderr)
        return 1
    if a.home:
        os.environ["ENLENS_HOME"] = str(Path(a.home).expanduser().resolve())
    app = Path(__file__).with_name("app.py")
    sys.argv = ["streamlit", "run", str(app),
                "--server.port", str(a.port),
                "--server.address", "localhost",          # reachable from this computer only
                "--server.maxUploadSize", "2048",         # MB; zips of reports are large
                "--server.headless", "true" if a.headless else "false",
                "--browser.gatherUsageStats", "false",
                "--client.toolbarMode", "minimal",
                "--theme.primaryColor", "#2563eb"]
    return stcli.main()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
