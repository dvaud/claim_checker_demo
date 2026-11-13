"""0.18.0rc2 (M8): a local model that works without a terminal.

- `modeladvice.advise` suggests the models that fit THIS computer: one recommended, a smaller and quicker and a larger and
  more careful one beside it, only when they fit the memory and the disk with room to spare; made-up computers here;
- after Ollama is installed on Windows and the installer did not start it, ENLENS starts it itself and waits;
- Ollama on the computer but not running is started by the card by itself (once, not twice), then the model is offered;
- `GET /api/servers` gives the advice and the suggested models that fit; the page shows the choices.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import fake_servers
from enlens_claims import modeladvice, ollama_setup
from test_app import Api, api, home  # noqa: F401  (fixtures)

GB = 1 << 30
STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


def pc(memory=16, disk=200, system="windows", unified=False, gpu=None):
    return {"memory": memory * GB, "disk_free": disk * GB, "system": system, "unified": unified,
            "gpu": gpu * GB if gpu else None}


def names(ladder):
    return [o["name"] for o in ladder["options"]]


def test_a_16_gb_mac_gets_the_8b_model_with_a_smaller_and_a_larger_beside_it():
    a = modeladvice.advise(pc(16, system="mac", unified=True))
    chat = a["chat"]
    assert chat["pick"]["name"] == "qwen3:8b" and chat["pick"]["role"] == "recommended"
    assert chat["smaller"]["name"] == "qwen3:4b" and chat["larger"]["name"] == "qwen3:14b"
    assert names(chat) == ["qwen3:4b", "qwen3:8b", "qwen3:14b"]
    assert chat["pick"]["speed"] == "quick" and "own memory" in chat["pick"]["speed_text"]
    assert chat["larger"]["tight"] and "close other programs" in chat["larger"]["note"]   # it fits, but only just
    for o in chat["options"]:                                                           # plain words for each
        assert o["size"].startswith("about ") and o["good_for"] and o["speed_text"]
    assert "Apple silicon" in a["computer"]["words"] and "16 GB of memory" in a["computer"]["words"]
    assert "one large file kept on this computer" in a["what_is_a_model"]


def test_8_gb_gets_a_smaller_model_and_never_one_that_does_not_fit():
    chat = modeladvice.advise(pc(8))["chat"]
    assert chat["pick"]["name"] == "qwen3:4b" and chat["larger"] is None
    assert "qwen3:8b" not in names(chat) and "qwen3:14b" not in names(chat)
    assert chat["pick"]["speed"] in ("fair", "slow") and "processor" in chat["pick"]["speed_text"]   # no graphics card


def test_32_gb_gets_the_14b_model_with_the_8b_as_the_quicker_one():
    chat = modeladvice.advise(pc(32, system="mac", unified=True))["chat"]
    assert chat["pick"]["name"] == "qwen3:14b" and chat["smaller"]["name"] == "qwen3:8b" and chat["larger"] is None


def test_windows_with_and_without_a_graphics_card():
    plain = modeladvice.advise(pc(16))["chat"]
    carded = modeladvice.advise(pc(16, gpu=12))["chat"]
    assert plain["pick"]["name"] == "qwen3:8b" and plain["pick"]["speed"] == "slow"
    assert carded["pick"]["name"] == "qwen3:8b" and carded["pick"]["speed"] == "quick"
    assert "graphics card" in carded["pick"]["speed_text"]
    assert "graphics card with 12 GB" in modeladvice.advise(pc(16, gpu=12))["computer"]["words"]
    # a small card does not make a big model fit it, but the memory still decides
    small_card = modeladvice.advise(pc(8, gpu=4))["chat"]
    assert small_card["pick"]["name"] == "qwen3:4b"


def test_low_disk_space_steps_down_and_then_says_why():
    low = modeladvice.advise(pc(32, disk=7, system="mac", unified=True))["chat"]
    assert low["pick"]["name"] == "qwen3:4b" and "qwen3:8b" not in names(low)     # 5.2 GB + room needs more than 7 GB
    none = modeladvice.advise(pc(32, disk=3))["chat"]
    assert none["pick"] is None and none["options"] == [] and "free disk space" in none["reason"]
    tiny = modeladvice.advise(pc(2, disk=100))["chat"]
    assert tiny["pick"] is None and "too little" in tiny["reason"] and "Claude" in tiny["reason"]


def test_search_by_meaning_starts_with_the_small_model_and_offers_the_multilingual_one():
    emb = modeladvice.advise(pc(16))["embed"]
    assert emb["pick"]["name"] == "nomic-embed-text" and emb["larger"]["name"] == "bge-m3"
    assert "many languages" in emb["larger"]["good_for"]
    assert modeladvice.advise(pc(4, disk=50))["embed"]["pick"]["name"] == "nomic-embed-text"
    assert modeladvice.advise(pc(16, disk=2))["embed"]["pick"] is None             # not even 0.3 GB of room to spare


def test_a_computer_that_cannot_be_read_is_not_refused():
    a = modeladvice.advise({"memory": None, "disk_free": None, "system": "linux", "unified": False, "gpu": None})
    assert a["chat"]["pick"] is not None and a["computer"]["words"] == ""


def test_suggested_keeps_the_old_shape_and_falls_back(monkeypatch):
    sug = modeladvice.suggested(modeladvice.advise(pc(16)))
    assert sug == [{"name": "qwen3:8b", "use": "chat", "size": "about 5.2 GB"},
                   {"name": "nomic-embed-text", "use": "embed", "size": "about 0.3 GB"}]
    assert [m["use"] for m in modeladvice.suggested(modeladvice.advise(pc(2)))] == ["embed"]
    monkeypatch.setattr(modeladvice, "computer", lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
    from enlens_claims import llm
    assert modeladvice.suggested() == [dict(m) for m in llm.SUGGESTED_MODELS]


def test_the_app_reads_the_computer_cheaply_and_a_graphics_card_only_where_nvidia_smi_is(monkeypatch):
    monkeypatch.setattr(modeladvice.shutil, "which", lambda n: None)
    modeladvice._FACTS.clear()
    f = modeladvice.computer("/tmp")
    assert f["gpu"] is None and f["memory"] and f["system"] in ("mac", "windows", "linux")
    calls = []
    monkeypatch.setattr(modeladvice.shutil, "which", lambda n: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(modeladvice.subprocess, "run", lambda *a, **k: calls.append(a) or type("R", (), {"stdout": "8192\n12288\n"})())
    assert modeladvice._gpu_memory("windows") == 12288 * (1 << 20) and len(calls) == 1
    assert modeladvice._gpu_memory("mac") is None                                   # never probed on a Mac


# ---------------------------------------------------------------------------------------------- starting Ollama itself
def test_windows_install_starts_ollama_itself_when_the_installer_did_not(site_free, monkeypatch, tmp_path):
    started, state = [], {"up": False}
    monkeypatch.setattr(ollama_setup, "check_windows", lambda f: "")
    monkeypatch.setattr(ollama_setup, "_install_windows", lambda f: tmp_path / "ollama app.exe")
    monkeypatch.setattr(ollama_setup, "start", lambda name=None: started.append(name) or state.update(up=True) or {"started": True})
    monkeypatch.setattr(ollama_setup.time, "sleep", lambda s: None)
    clock = iter(range(0, 10_000, 8))
    monkeypatch.setattr(ollama_setup.time, "time", lambda: next(clock))
    r = ollama_setup.install(sys_name="windows", is_running=lambda: state["up"])
    assert started == ["windows"] and r["running"] is True and r["started_by_enlens"] is True


def test_windows_install_leaves_it_alone_when_the_installer_started_it(site_free, monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_setup, "check_windows", lambda f: "")
    monkeypatch.setattr(ollama_setup, "_install_windows", lambda f: tmp_path / "ollama app.exe")
    monkeypatch.setattr(ollama_setup, "start", lambda name=None: pytest.fail("a second copy was started"))
    r = ollama_setup.install(sys_name="windows", is_running=lambda: True)
    assert r == {"path": str(tmp_path / "ollama app.exe"), "running": True}


def test_start_once_does_not_start_twice_or_when_it_answers(monkeypatch, tmp_path):
    app = tmp_path / "Ollama.app"
    app.mkdir()
    monkeypatch.setattr(ollama_setup, "app_path", lambda s=None: app)
    started = []
    monkeypatch.setattr(ollama_setup, "start", lambda name=None: started.append(1) or {"started": True, "path": str(app), "serve": False})
    monkeypatch.setattr(ollama_setup, "answers", lambda url=None: bool(answering))
    ollama_setup._STARTED["at"] = 0.0
    answering = False
    assert ollama_setup.start_once()["started"] is True and len(started) == 1
    again = ollama_setup.start_once()                                  # the card is drawn again while it starts
    assert again == {"started": False, "running": False, "starting": True} and len(started) == 1
    answering = True
    assert ollama_setup.start_once() == {"started": False, "running": True}
    monkeypatch.setattr(ollama_setup, "app_path", lambda s=None: None)
    with pytest.raises(ValueError, match="not on this computer"):
        ollama_setup.start_once()


@pytest.fixture
def site_free(monkeypatch, tmp_path):
    """The download is not asked for: a stand-in file in the downloads folder is what `_download` hands back."""
    monkeypatch.setattr(ollama_setup, "_download", lambda url, dest, on_progress, should_stop: dest.write_bytes(b"MZ") or True)
    monkeypatch.setattr(ollama_setup, "app_path", lambda s=None: None)
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "enlens"))
    yield


# ---------------------------------------------------------------------------------------------- the API and the page
def test_the_servers_call_gives_the_advice_and_the_suggested_models(api, monkeypatch):
    monkeypatch.setattr(modeladvice, "computer", lambda *a, **k: pc(8))
    srv, url = fake_servers.start("ollama")
    try:
        api("PUT", "/api/settings", {"ollama_url": url})
        st, r = api("GET", "/api/servers")
        assert st == 200
        assert r["advice"]["chat"]["pick"]["name"] == "qwen3:4b"
        assert [m["name"] for m in r["suggested"]] == ["qwen3:4b", "nomic-embed-text"]
        assert r["advice"]["computer"]["words"].startswith("This computer has 8 GB")
    finally:
        srv.shutdown()


def test_the_start_call_starts_nothing_when_ollama_answers(api, monkeypatch, tmp_path):
    srv, url = fake_servers.start("ollama")
    try:
        api("PUT", "/api/settings", {"ollama_url": url})
        app = tmp_path / "Ollama.app"
        app.mkdir()
        monkeypatch.setattr(ollama_setup, "app_path", lambda s=None: app)
        monkeypatch.setattr(ollama_setup, "start", lambda name=None: pytest.fail("started although it answers"))
        st, r = api("POST", "/api/ollama/start", {})
        assert st == 200 and r == {"started": False, "running": True}
    finally:
        srv.shutdown()


def test_the_page_starts_ollama_by_itself_and_offers_the_choices():
    js = (STATIC / "views" / "local-model.js").read_text(encoding="utf-8")
    # installed but not answering: started by the card (not only by its button), once a minute at most
    assert "startByItself(area, btn0)" in js and "lastAutoStart" in js and "ENLENS is starting it" in js
    # after an install that did not answer: started again, nothing for the person to open
    assert "installed, but it did not answer yet" not in js and "Open it from" not in js
    # the choices: recommended, smaller and quicker, larger and more careful, from the advice
    assert "info.advice" in js and "Smaller and quicker" in js and "Larger and more careful" in js
    assert "advice.what_is_a_model" in js and "advice.computer.words" in js and "advice.chat.reason" in js
    assert "model-choices" in (STATIC / "views.css").read_text(encoding="utf-8")
