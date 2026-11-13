"""The deep dive after 0.17.0: defects, slow places and doubled work found by reading and measuring the whole
program. Each test here failed before its fix."""
from __future__ import annotations

import threading
import time

from enlens_claims import home, people, reader3
from enlens_claims.gui import server


# ---- reading: a paragraph on one line no longer takes seconds ------------------------------------------------
def test_a_long_line_is_not_tried_as_an_entry_of_a_table_of_contents():
    line = ("The plant expects to double its output when the second electrolyser arrives next spring, and " * 60).strip()
    assert len(line) > 5000
    t0 = time.perf_counter()
    for _ in range(20):
        assert reader3._toc_entry(line) is None
    assert time.perf_counter() - t0 < 0.5  # 20 such lines took about 10 s


def test_the_look_at_a_lines_end_misses_no_entry_of_a_table_of_contents():
    import random

    lines = ["Introduction ........ 3", "1.2 Methods . . . . 17", "Chapter one | 5", "Preface\tix", "Results 104",
             "A title that ends in 2020", "No number here", "Appendix A....iv", "x", "12", "Summary  …  7",
             "Foreword __ xii", "The year was 1987.", "Contents", "3 Findings 45 ", "Anhang|12", "a.b..3", "Ünnep 4"]
    rnd = random.Random(3)
    alphabet = "ab iv x1 23 .·…_| \t,;:Z9é"
    lines += ["".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 16))) for _ in range(20000)]
    for raw in lines:
        s = raw.strip()
        full = reader3._TOC_LINE.match(s)
        assert not full or reader3._TOC_TAIL.search(s[-10:]), raw  # every line the rule takes passes the first look
        got = reader3._toc_entry(raw)
        if not full:
            assert got is None, raw


# ---- the app: an endpoint's own header takes the place of the default one -------------------------------------
class _Reply:
    command = "GET"

    def __init__(self):
        self.headers: list[tuple[str, str]] = []
        self.wfile = self
        self.body = b""

    def send_response(self, status):
        self.status = status

    def send_header(self, k, v):
        self.headers.append((k, v))

    def end_headers(self):
        pass

    def write(self, data):
        self.body += data


def test_a_picture_of_a_page_may_be_kept_by_the_browser():
    r = _Reply()
    server.Handler._send(r, 200, b"png", "image/png", {"Cache-Control": "private, max-age=3600"})
    assert [v for k, v in r.headers if k == "Cache-Control"] == ["private, max-age=3600"]  # was: no-store, then this
    plain = _Reply()
    server.Handler._send(plain, 200, b"{}", "application/json")
    assert [v for k, v in plain.headers if k == "Cache-Control"] == ["no-store"]
    assert len({k for k, _v in r.headers}) == len(r.headers)  # one header of each name


# ---- settings: read and written by several threads at once ----------------------------------------------------
def test_settings_read_while_they_are_written_are_never_the_defaults():
    home.update_settings({"your_name": "Anna", "themes_k": 17})
    me = people.me()
    stop = time.time() + 1.0
    wrong: list[dict] = []

    def reader():
        while time.time() < stop:
            s = home.load_settings()
            if s.get("your_name") != "Anna" or s.get("person_id") != me:
                wrong.append(s)
                return

    def writer(key, values):
        i = 0
        while time.time() < stop:
            home.update_settings({key: values[i % len(values)]})
            i += 1

    threads = [threading.Thread(target=reader) for _ in range(3)] + [
        threading.Thread(target=writer, args=("k", [5, 6, 7])),
        threading.Thread(target=writer, args=("per_doc", [1, 2, 3]))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    end = home.load_settings()
    assert not wrong, {k: wrong[0].get(k) for k in ("your_name", "person_id")}
    assert end["your_name"] == "Anna" and end["themes_k"] == 17 and people.me() == me  # (the id was made anew)
    assert not [p.name for p in home.home().iterdir() if p.name.endswith(".part")]


def test_a_new_installation_makes_one_person_id_however_many_ask_at_once():
    assert not (home.home() / "settings.json").exists()
    got: list[str] = []
    go = threading.Event()

    def ask():
        go.wait()
        got.append(people.me())

    threads = [threading.Thread(target=ask) for _ in range(12)]
    for t in threads:
        t.start()
    go.set()
    for t in threads:
        t.join()
    assert len(set(got)) == 1 and people.me() == got[0]


def test_settings_that_cannot_be_read_this_moment_are_never_written_over(monkeypatch):
    import pytest

    home.update_settings({"your_name": "Anna", "themes_k": 17})
    me = people.me()
    p = home.home() / "settings.json"
    before = p.read_text(encoding="utf-8")
    real = type(p).read_text

    def held(self, *a, **kw):  # as Windows does while a virus scanner holds the file
        if self.name == "settings.json":
            raise PermissionError(13, "The process cannot access the file")
        return real(self, *a, **kw)

    monkeypatch.setattr(type(p), "read_text", held)
    assert home.load_settings()["your_name"] == ""  # for showing only: the defaults stand in
    with pytest.raises(home.Unreadable):
        home.update_settings({"k": 5})  # was: the defaults and this one change, written back
    with pytest.raises(home.Unreadable):
        people.me()  # was: a new person id
    monkeypatch.setattr(type(p), "read_text", real)
    assert p.read_text(encoding="utf-8") == before and people.me() == me


def test_a_damaged_settings_file_gives_way_to_the_settings_from_before_the_last_change():
    home.update_settings({"your_name": "Anna"})
    me = people.me()
    home.update_settings({"themes_k": 17})  # (the copy from before this change holds the name and the id)
    p = home.home() / "settings.json"
    p.write_text("{ half a fi", encoding="utf-8")
    s = home.load_settings()
    assert s["your_name"] == "Anna" and s["person_id"] == me
    assert people.me() == me


def test_links_that_cannot_be_read_are_not_replaced_by_the_one_new_link(tmp_path, monkeypatch):
    import pytest

    from enlens_claims.store import Workspace

    for n in ("one", "two"):
        Workspace.create(tmp_path / n)
        home.link_existing(str(tmp_path / n), n)
    Workspace.create(tmp_path / "three")
    p = home.home() / "links.json"
    real = type(p).read_text

    def held(self, *a, **kw):
        if self.name == "links.json":
            raise PermissionError(13, "The process cannot access the file")
        return real(self, *a, **kw)

    monkeypatch.setattr(type(p), "read_text", held)
    with pytest.raises(OSError):
        home.link_existing(str(tmp_path / "three"), "three")  # was: links.json with this one link alone
    monkeypatch.setattr(type(p), "read_text", real)
    assert {"one", "two"} <= set(home.list_projects())


# ---- a document's original file: only the file that was read ---------------------------------------------------
def _doc_pointing_at(ws, target, sha1):
    with ws.connect() as cx:
        cx.execute("INSERT INTO documents(doc_id, path, sha1, title, kind, n_chars, text) VALUES "
                   "('dsecret0001', ?, ?, 'A report', 'text', 10, 'Some text.')", (str(target), sha1))


def test_a_file_outside_the_project_is_a_documents_original_only_with_its_checksum(tmp_path):
    import zipfile

    from enlens_claims import bundle
    from enlens_claims.ingest import _sha1
    from enlens_claims.sources import original_file
    from enlens_claims.store import Workspace

    secret = tmp_path / "elsewhere" / "credentials.json"
    secret.parent.mkdir()
    secret.write_text('{"anthropic_api_key": "sk-secret"}', encoding="utf-8")
    # as a project zip from someone else may say: any file of this computer, with no checksum, or a wrong one
    for n, sha in enumerate((None, "0" * 40)):
        ws = Workspace.create(tmp_path / f"p{n}")
        _doc_pointing_at(ws, secret, sha)
        for verify in (True, False):
            info = original_file(ws, "dsecret0001", verify=verify)
            assert not info["available"] and info["path"] is None, (sha, verify)
        out = tmp_path / f"out{n}.zip"
        bundle.export_project(ws, out)
        with zipfile.ZipFile(out) as zf:
            assert not [x for x in zf.namelist() if x.startswith("originals/")]  # was: the secret file, in the zip
            assert b"sk-secret" not in b"".join(zf.read(x) for x in zf.namelist() if not x.endswith(".sqlite"))
    # a document added from a folder elsewhere on this computer (its checksum recorded) keeps its original
    own = Workspace.create(tmp_path / "own")
    _doc_pointing_at(own, secret, _sha1(secret))
    assert original_file(own, "dsecret0001", verify=False)["available"]
    # and a file of another project of the same data folder is no more this project's than any other file
    other = Workspace.create(tmp_path / "p0-sibling")
    with other.connect() as cx:
        cx.execute("INSERT INTO documents(doc_id, path, sha1, title, kind, n_chars, text) VALUES "
                   "('dsecret0002', '../elsewhere/credentials.json', NULL, 'x', 'text', 1, 'x')")
    assert not original_file(other, "dsecret0002")["available"]


def test_a_path_on_another_computer_is_never_looked_at(tmp_path, monkeypatch):
    from pathlib import Path

    from enlens_claims.sources import original_file
    from enlens_claims.store import Workspace

    ws = Workspace.create(tmp_path / "p")
    touched: list[str] = []
    real = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda self: touched.append(str(self)) or real(self))
    for n, path in enumerate(("\\\\attacker\\share\\x.pdf", "//attacker/share/x.pdf")):
        with ws.connect() as cx:
            cx.execute("INSERT INTO documents(doc_id, path, sha1, title, kind, n_chars, text) VALUES (?,?,?,?,?,?,?)",
                       (f"dunc{n:07d}", path, "0" * 39 + str(n), "x", "pdf", 1, "x"))
        info = original_file(ws, f"dunc{n:07d}")
        assert not info["available"] and "another computer" in info["reason"]
    assert not [t for t in touched if "attacker" in t]


# ---- the server: a request whose length is no number ------------------------------------------------------------
def test_a_request_with_a_length_that_is_no_number_gets_an_answer():
    import socket
    import threading as th

    srv, app = server.make_server("127.0.0.1", 0)
    th.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        for length in ("abc", "-1"):
            with socket.create_connection(("127.0.0.1", app.port), timeout=5) as c:
                c.sendall(f"POST /api/quit HTTP/1.1\r\nHost: 127.0.0.1:{app.port}\r\nContent-Length: {length}\r\n"
                          "\r\n".encode())
                c.settimeout(5)
                got = b""
                while True:  # the answer, then the server hangs up: with "-1" it went on waiting for the client to
                    more = c.recv(4096)
                    if not more:
                        break
                    got += more
                assert got.startswith(b"HTTP/1.1 401")  # (no token)
    finally:
        srv.shutdown()
        srv.server_close()


# ---- a project zip from someone else: its rows, and nothing else its database may hold --------------------------
def _zip_with_database(tmp_path, change):
    """A project zip as `export_project` makes it, its database changed by `change(cx)` (as a sender may)."""
    import sqlite3
    import zipfile

    from enlens_claims import bundle
    from enlens_claims.store import Workspace

    ws = Workspace.create(tmp_path / "theirs")
    with ws.connect() as cx:
        cx.execute("INSERT INTO documents(doc_id, sha1, title, kind, n_chars, text, ai_access) VALUES "
                   "('d0000000001', 'a', 'A report', 'text', 10, 'Some text.', 'cloud')")
    first = tmp_path / "theirs.zip"
    bundle.export_project(ws, first)
    work = tmp_path / "unpacked"
    with zipfile.ZipFile(first) as zf:
        zf.extractall(work)
    cx = sqlite3.connect(work / "enlens.sqlite")
    change(cx)
    cx.commit()
    cx.close()
    out = tmp_path / "forged.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for f in sorted(work.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(work).as_posix())
    return out


def test_an_imported_project_brings_no_trigger_and_no_view(tmp_path):
    from enlens_claims import access, bundle

    def forge(cx):
        cx.execute("CREATE TRIGGER open_again AFTER UPDATE OF ai_access ON documents BEGIN "
                   "UPDATE documents SET ai_access='cloud' WHERE doc_id=NEW.doc_id AND NEW.ai_access != 'cloud'; END")
        cx.execute("CREATE TRIGGER forget AFTER INSERT ON ai_sent BEGIN DELETE FROM ai_sent; END")
        cx.execute("CREATE VIEW looks_like_a_table AS SELECT * FROM documents")

    ws = bundle.import_project(_zip_with_database(tmp_path, forge), tmp_path / "mine")
    assert not ws.query("SELECT name FROM sqlite_master WHERE type IN ('trigger', 'view')")
    access.set_documents(ws, ["d0000000001"], setting="local")
    assert ws.scalar("SELECT ai_access FROM documents WHERE doc_id='d0000000001'") == "local"  # was: cloud again


def test_an_imported_project_with_a_table_that_works_out_its_own_values_is_refused(tmp_path):
    import pytest

    from enlens_claims import bundle

    def forge(cx):
        cx.execute("CREATE TABLE extra(a TEXT, b TEXT GENERATED ALWAYS AS ('cloud') VIRTUAL)")

    with pytest.raises(ValueError, match="more than a project's rows"):
        bundle.import_project(_zip_with_database(tmp_path, forge), tmp_path / "mine")
    assert not (tmp_path / "mine").exists()


# ---- themes: an edit about a theme only one run has -----------------------------------------------------------
def test_a_merge_into_a_theme_only_another_run_has_hides_no_theme_here(loaded):
    from pathlib import Path

    from enlens_claims import ingest, themes

    ingest.ingest(loaded, [Path(__file__).resolve().parent.parent / "tools" / "demo_corpus"])
    a = themes.run(loaded, k=3, seed=1, mode="words")
    with loaded.connect() as cx:  # a second set made with the same settings and the same grouping: the same key
        key = cx.execute("SELECT run_key FROM theme_runs WHERE run_id=?", (a,)).fetchone()[0]
        cols = [r[1] for r in cx.execute("PRAGMA table_info(theme_runs)")]
        row = dict(zip(cols, cx.execute("SELECT * FROM theme_runs WHERE run_id=?", (a,)).fetchone()))
        row["run_id"] = b = "t-second"
        cx.execute(f"INSERT INTO theme_runs({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                   [row[c] for c in cols])
        for table in ("themes", "theme_members"):
            tc = [r[1] for r in cx.execute(f"PRAGMA table_info({table})")]
            for r in cx.execute(f"SELECT * FROM {table} WHERE run_id=?", (a,)).fetchall():
                d = dict(zip(tc, r))
                d["run_id"] = b
                cx.execute(f"INSERT INTO {table}({','.join(tc)}) VALUES ({','.join('?' * len(tc))})", [d[c] for c in tc])
        # in the first set: a theme found in place of a removed one (its id is that set's alone), and a theme
        # merged into it
        first = cx.execute("SELECT theme_id FROM themes WHERE run_id=? ORDER BY theme_id", (a,)).fetchone()[0]
        cx.execute("INSERT INTO themes(run_id, theme_id, name, terms_json, size, reps_json, name_source) VALUES "
                   "(?, 5347776, 'Found later', '[]', 0, '[]', 'terms')", (a,))
        cx.execute("INSERT INTO reviews(item_kind, item_id, field, proposed, decision, corrected, reviewer, decided_at) "
                   "VALUES ('theme', ?, 'merge', '', 'edit', '5347776', '', '2026-01-01T00:00:00+00:00')",
                   (f"{key}:{first}",))
    before = sum(t["size"] for t in themes.view(loaded, a)["themes"])
    second = themes.view(loaded, b)
    assert first in {t["theme_id"] for t in second["themes"]}  # was: gone, with its passages
    assert sum(t["size"] for t in second["themes"]) == before
    assert themes.theme_passages(loaded, b, first)["total"] > 0
    assert first not in {t["theme_id"] for t in themes.view(loaded, a)["themes"]}  # merged, in the set that has both


# ---- small ones ---------------------------------------------------------------------------------------------------
def test_two_projects_whose_names_differ_only_in_accents_keep_their_own_claude_code_log():
    from enlens_claims import claude_setup

    assert claude_setup._log_path("Előadás") != claude_setup._log_path("El ad s")  # both were El_ad_s.log
    assert claude_setup._log_path("Előadás") == claude_setup._log_path("Előadás")


def test_a_mark_on_a_page_the_pdf_does_not_have_is_left_unplaced(tmp_path):
    from enlens_claims import annotate, pdfmake

    fl = pdfmake.Flow()
    fl.paragraph("Electrolyser plants create local jobs mainly during construction.")
    pdf = tmp_path / "one.pdf"
    fl.write(pdf)
    here = annotate.Mark(0, 20, "Electrolyser plants create local jobs", "supports", "", "check", page=1)
    beyond = annotate.Mark(0, 20, "Electrolyser plants create local jobs", "supports", "", "check", page=7)
    annotate.place(pdf, [here, beyond])  # was: PdfiumError "Failed to load page" where page pictures can be made
    assert here.placed and not beyond.placed


# ---- the research log and the notes ------------------------------------------------------------------------------
def test_the_logs_downloads_hold_every_entry(ws):
    from enlens_claims import researchlog

    with ws.connect() as cx:
        for i in range(2105):
            researchlog.record(cx, "entry", f"Entry number {i}")
    assert len(researchlog.table(ws)) == 2105  # was: the 2,000 oldest
    assert researchlog.markdown(ws, "P").count("Entry number") == 2105
    assert len(researchlog.entries(ws, limit=5000)["entries"]) == 2000  # a page still asks for 2,000 at most


def test_a_search_of_the_log_and_the_notes_finds_a_capital_letter_with_an_accent(loaded):
    from enlens_claims import notes, researchlog

    researchlog.add(loaded, "Életminőség comes up in every interview")
    researchlog.add(loaded, "Nothing about that here")
    got = researchlog.entries(loaded, q="életminőség")
    assert got["total"] == 1 and "Életminőség" in got["entries"][0]["text"]
    assert researchlog.entries(loaded, q="INTERVIEW")["total"] == 1
    doc = loaded.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
    notes.add(loaded, doc, 0, 5, text="Ökowind is the operator")
    notes.add(loaded, doc, 6, 12, text="another thought")
    found = notes.search(loaded, q="ökowind operator")
    assert found["total"] == 1 and found["notes"][0]["text"].startswith("Ökowind")
    assert notes.search(loaded, q="ökowind missing")["total"] == 0
    assert notes.search(loaded)["total"] == 2
