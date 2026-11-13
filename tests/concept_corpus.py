"""0.18.1 (D3, D4): a small made-up corpus for the tests of paths between concepts and concepts over time. Solar
panels are mentioned with grid storage, grid storage with battery prices, and solar panels never with battery prices,
so the path from one to the other runs through grid storage. Filler passages mention none of them."""
from __future__ import annotations

from pathlib import Path

A = ("Rooftop solar panels in the region now feed grid storage at noon. Operators said grid storage absorbs what "
     "solar panels make when demand is low, and gives it back in the evening, so fewer plants run at night.")
B = ("Grid storage became cheaper as battery prices fell. The operators planned more grid storage once battery "
     "prices dropped below the level of the tender, and two new sites were opened in the north.")
F = ("The municipal council met in the town hall to discuss the budget for roads, schools and the library. Members "
     "asked for more parking near the station and for longer opening hours at the swimming pool in summer.")


def write(folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    files = {   # (the glossary keeps terms that two documents or more use)
        "solar": "Solar report\n\n" + "\n\n".join([A, F, A.replace("noon", "midday"), F.replace("roads", "bridges")]),
        "solar2": "Solar survey\n\n" + "\n\n".join([A.replace("region", "valley"), F.replace("summer", "spring"),
                                                      A.replace("Rooftop", "New")]),
        "storage": "Storage review\n\n" + "\n\n".join([B, F.replace("budget", "plan"), B.replace("north", "south")]),
        "storage2": "Storage outlook\n\n" + "\n\n".join([B.replace("tender", "auction"), F, B.replace("two", "three")]),
        "filler": "Council minutes\n\n" + "\n\n".join([F.replace("library", "museum"), F.replace("station", "port"),
                                                       F.replace("summer", "winter")]),
    }
    out = {}
    for k, text in files.items():
        p = folder / f"{k}.txt"
        p.write_text(text + "\n", encoding="utf-8")
        out[k] = p
    return out
