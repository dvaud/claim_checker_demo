"""Draw the icon files that ship with ENLENS (0.10.2), from the logo as `launcher.draw_icon` draws it.

    python tools/make_icons.py        # needs Pillow; writes src/enlens_claims/gui/icons/ENLENS.icns and ENLENS.ico

The files are committed, so making the ENLENS icon never needs Pillow. Run this again only when the logo changes.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from enlens_claims.gui.launcher import ICONS, draw_icon  # noqa: E402


def main() -> int:
    big = draw_icon(1024)
    if big is None:
        print("Pillow is needed to draw the icons: pip install pillow", file=sys.stderr)
        return 1
    ICONS.mkdir(parents=True, exist_ok=True)
    big.save(ICONS / "ENLENS.icns")  # 16 to 512 points, each at 1x and 2x (1024 pixels)
    draw_icon(256).save(ICONS / "ENLENS.ico", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
    for p in sorted(ICONS.iterdir()):
        print(f"{p.relative_to(ROOT)}  {p.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
