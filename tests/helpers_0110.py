"""0.11 test fixtures: a project whose documents have each AI setting, and models that record what they were sent.

- `Cloud`: a stand-in for Claude (named like the Claude API backend), answering with the fake model's canned answers
  and recording every system prompt, user prompt and payload it is given;
- `Local`: the same for a model server on this computer;
- `mixed_project`: three documents about green hydrogen and water. The one marked "Only a local AI" carries the
  marker LOCALMARK in every sentence, the one marked "No AI" NONEMARK (in its title too); the third Claude may read.
"""
from __future__ import annotations

import json
from pathlib import Path

import fake_servers

LOCAL_MARK = "Zqxlocalmark"
NONE_MARK = "Zqxnonemark"
MARKS = (LOCAL_MARK.lower(), NONE_MARK.lower())


def _doc(title: str, mark: str | None, title_mark: str | None = None) -> str:
    m = f" {mark}" if mark else ""
    tm = f" {title_mark}" if title_mark else m
    sents = [
        f"Green hydrogen production can increase water stress in arid regions{m}.",
        f"Electrolysis needs large amounts of fresh water for every kilogram of hydrogen{m}.",
        f"Export hubs in Morocco could compete with farming for groundwater{m}.",
        f"Desalinated seawater reduces the pressure on freshwater in coastal plants{m}.",
        f"Hydrogen projects can create local jobs in construction and operation of electrolysers{m}.",
        f"Training programmes are needed so that local workers benefit from hydrogen projects{m}.",
        f"The plant uses renewable electricity from solar and wind farms nearby{m}.",
        f"It exports ammonia by ship to European ports every month{m}.",
    ]
    paras = []
    for i in range(4):  # several passages per document
        paras.append(" ".join(sents[(i * 2 + j) % len(sents)] for j in range(6)))
    return f"{title}{tm}\n\n" + "\n\n".join(paras) + "\n"


def write_corpus(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "open_report.txt").write_text(_doc("Open report on hydrogen and water", None))
    # the title of a document marked "Only a local AI" is shown (only "No AI" titles are hidden): its own marker
    (folder / "licensed_study.txt").write_text(_doc("Licensed study on hydrogen and water", LOCAL_MARK, "Licensedtitle"))
    (folder / "interviews.txt").write_text(_doc("Interview transcripts on hydrogen and water", NONE_MARK))
    return folder


def mixed_project(ws, folder: Path) -> dict[str, str]:
    """Ingest the three documents and give them their settings. Returns {"cloud"|"local"|"none": doc_id}."""
    from enlens_claims import access, ingest

    write_corpus(folder)
    ingest.ingest(ws, [folder], ai_access="cloud")
    ids = {}
    for r in ws.query("SELECT doc_id, path FROM documents"):
        name = Path(r["path"]).name
        ids[{"open_report.txt": "cloud", "licensed_study.txt": "local", "interviews.txt": "none"}[name]] = r["doc_id"]
    access.set_documents(ws, [ids["local"]], "local")
    access.set_documents(ws, [ids["none"]], "none")
    return ids


class Recorder:
    name = "recorder"

    def __init__(self):
        self.sent: list[str] = []
        self.kinds: list[str] = []

    def complete(self, kind, system, user, model, payload=None):
        self.sent.append("\n".join([system, user, json.dumps(payload or {}, ensure_ascii=False)]))
        self.kinds.append(kind)
        try:
            out = fake_servers._answer(system, user, model=model)
        except (IndexError, KeyError, ValueError):
            out = {}
        return json.dumps(out)

    def text(self) -> str:
        return "\n".join(self.sent).lower()

    def leaked(self, marks=MARKS) -> list[str]:
        t = self.text()
        return [m for m in marks if m in t]


class Cloud(Recorder):
    """Claude, as far as ENLENS can tell (the Claude API backend's name)."""
    name = "anthropic"


class Local(Recorder):
    """A model server on this computer."""
    name = "ollama"
    base_url = "http://localhost:11434"


def use_local_model(monkeypatch, local: Local | None) -> None:
    """Make `local` the local model for restricted documents (None: no local model is chosen)."""
    from enlens_claims import home

    if local is None:
        monkeypatch.setattr(home, "restricted_choice", lambda s: {})
        monkeypatch.setattr(home, "make_restricted_backend", lambda s: None)
    else:
        monkeypatch.setattr(home, "restricted_choice", lambda s: {"server": "ollama", "model": "local-model",
                                                                   "same_as_main": False, "url": local.base_url})
        monkeypatch.setattr(home, "make_restricted_backend", lambda s: (local, "local-model"))
