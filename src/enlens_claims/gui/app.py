"""ENLENS claim checker: a local web interface. Start it with `enlens-gui`.

Pages: Check a claim · Sources · History · Settings. All data stays in ENLENS_HOME (see core.py); text is sent
only to the model service chosen in Settings (the Claude API, or Ollama on this computer).
"""
from __future__ import annotations

import csv
import html
import io
import json
import time
from pathlib import Path

import streamlit as st

from enlens_claims import benchmark as bench
from enlens_claims import claimcheck, ingest
from enlens_claims.gui import core
from enlens_claims.llm import BackendError
from enlens_claims.sources import document_overview
from enlens_claims.taxonomy import target_sort_key, targets

st.set_page_config(page_title="ENLENS claim checker", page_icon="🔎", layout="wide")

CSS = """
<style>
.badge{display:inline-block;padding:.15rem .6rem;border-radius:999px;font-size:.85rem;font-weight:600;
       border:1px solid currentColor;margin-right:.4rem;white-space:nowrap}
.b-supports,.b-supported{color:#1a7f37;background:rgba(46,160,67,.12)}
.b-partially_supports,.b-partially_supported{color:#9a6700;background:rgba(212,167,44,.15)}
.b-refutes,.b-contradicted{color:#cf222e;background:rgba(207,34,46,.10)}
.b-unsupported,.b-no_passages,.b-not_checked,.b-none{color:#57606a;background:rgba(110,119,129,.12)}
.b-failed{color:#cf222e;background:rgba(207,34,46,.10)}
.passage{font-size:.93rem;line-height:1.55}
.passage mark{background:rgba(255,196,0,.38);color:inherit;padding:0 .1rem;border-radius:2px}
.muted{opacity:.7;font-size:.88rem}
.claimtext{font-size:1.15rem;font-weight:600;margin:.3rem 0 .2rem 0}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

GRADE_TEXT = {"supports": "Supports", "partially_supports": "Partly supports", "refutes": "Refutes"}


# ---------------------------------------------------------------------------------------------
# shared state
# ---------------------------------------------------------------------------------------------
def settings() -> dict:
    if "settings" not in st.session_state:
        st.session_state.settings = core.load_settings()
    return st.session_state.settings


def save(**changes) -> None:
    s = settings()
    s.update(changes)
    core.save_settings(s)


def api_key() -> str:
    return st.session_state.get("api_key") or core.env_key() or core.stored_key()


def workspace():
    name = settings().get("project")
    if not name or name not in core.list_projects():
        return None
    try:
        return core.open_project(name)
    except Exception as e:  # a damaged or moved project should not break every page
        st.error(f"Could not open project {name!r}: {e}")
        return None


def badge(kind: str, text: str | None = None) -> str:
    return f"<span class='badge b-{html.escape(kind)}'>{html.escape(text or kind)}</span>"


def highlighted(text: str, start: int | None, end: int | None) -> str:
    if start is None or end is None or not (0 <= start < end <= len(text)):
        return html.escape(text)
    return html.escape(text[:start]) + "<mark>" + html.escape(text[start:end]) + "</mark>" + html.escape(text[end:])


def to_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def local_time(iso: str) -> str:
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return (iso or "")[:16].replace("T", " ")


def target_label(code: str) -> str:
    t = targets().get(code)
    return f"{code} · {t.description[:110]}{'…' if len(t.description) > 110 else ''}" if t else code


# ---------------------------------------------------------------------------------------------
# sidebar: project picker and the model in use
# ---------------------------------------------------------------------------------------------
def sidebar() -> None:
    s = settings()
    with st.sidebar:
        st.markdown("### ENLENS claim checker")
        projects = core.list_projects()
        if projects:
            current = s.get("project") if s.get("project") in projects else projects[0]
            choice = st.selectbox("Project", projects, index=projects.index(current), key="project_pick")
            if choice != s.get("project"):
                save(project=choice)
                st.session_state.pop("last_claim", None)
        with st.expander("New project", expanded=not projects):
            with st.form("new_project", clear_on_submit=True, border=False):
                name = st.text_input("Name", placeholder="e.g. Green hydrogen Morocco")
                if st.form_submit_button("Create"):
                    try:
                        ws = core.create_project(name)
                        save(project=ws.root.name)
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
        st.divider()
        st.caption("Model")
        st.markdown(f"**{html.escape(core.backend_label(s))}**", unsafe_allow_html=True)
        if s["backend"] == "anthropic" and not api_key():
            st.warning("No Claude API key yet. Add one in Settings.", icon="🔑")
        st.caption(f"Data folder: `{core.home()}`")


# ---------------------------------------------------------------------------------------------
# result view (check page and history)
# ---------------------------------------------------------------------------------------------
def show_result(ws, claim_id: str, threshold: float, allow_delete: bool = False) -> None:
    try:
        r = claimcheck.result(ws, claim_id, threshold)
    except KeyError:
        st.info("This check no longer exists.")
        return
    head = badge(r["status"], claimcheck.STATUS_TEXT.get(r["status"], r["status"]))
    st.markdown(head + f"<div class='claimtext'>{html.escape(r['claim'])}</div>", unsafe_allow_html=True)
    meta = []
    if r.get("target"):
        meta.append(f"SDG target {r['target']}: {r.get('target_description', '')[:120]}")
    meta.append(f"checked {local_time(r['created_at'])} with {r['model'] or r['options'].get('model', '?')}")
    meta.append(f"grades counted from confidence {threshold:g}")
    st.markdown(f"<div class='muted'>{html.escape(' · '.join(meta))}</div>", unsafe_allow_html=True)
    if r["status_any"] != r["status"]:
        st.caption(f"Counting every grade, whatever its confidence: {claimcheck.STATUS_TEXT.get(r['status_any'], r['status_any']).lower()}.")
    if r["status"] == "failed":
        st.error("The model's answers did not pass the checks three times:\n\n- " + "\n- ".join(r["errors"][:5] or ["no details"]))
    if r["status"] == "no_passages":
        st.warning("No passage in the documents shares words with this claim. Try other wording, or add sources.")
    if r.get("rationale"):
        st.markdown(f"> {html.escape(r['rationale'])}")

    graded = [p for p in r["passages"] if p["verdict"]]
    rest = [p for p in r["passages"] if not p["verdict"]]
    if graded:
        st.markdown(f"#### Evidence ({len(graded)} of {len(r['passages'])} passages)")
    for p in graded:
        low = p["confidence"] is not None and p["confidence"] < threshold
        with st.container(border=True):
            label = GRADE_TEXT.get(p["verdict"], p["verdict"])
            conf = f"confidence {p['confidence']:.2f}" + (" (below the threshold)" if low else "")
            src = html.escape(p["title"] or "untitled") + (f", page {p['page']}" if p["page"] else "")
            st.markdown(f"{badge(p['verdict'], label)}<span class='muted'>{conf}</span><br><b>{src}</b>",
                        unsafe_allow_html=True)
            st.markdown(f"<div class='passage'>{highlighted(p['text'], p['quote_start'], p['quote_end'])}</div>",
                        unsafe_allow_html=True)
    if rest:
        with st.expander(f"Also read, nothing relevant found ({len(rest)})"):
            for p in rest:
                st.markdown(f"**{html.escape(p['title'] or 'untitled')}**" + (f", page {p['page']}" if p["page"] else ""))
                st.markdown(f"<div class='passage muted'>{html.escape(p['text'])}</div>", unsafe_allow_html=True)
    if r["terms"]:
        st.caption("Search terms used: " + ", ".join(r["terms"]))

    c1, c2, c3 = st.columns([1, 1, 4])
    rows = [{"claim": r["claim"], "status": r["status"], "verdict": p["verdict"] or "", "confidence": p["confidence"] or "",
             "quote": p["quote"] or "", "source": p["title"], "page": p["page"] or ""} for p in r["passages"]]
    c1.download_button("Download CSV", to_csv(rows), file_name=f"check_{claim_id}.csv", mime="text/csv",
                       key=f"csv_{claim_id}")
    c2.download_button("Download JSON", json.dumps(r, indent=2, ensure_ascii=False).encode(), file_name=f"check_{claim_id}.json",
                       mime="application/json", key=f"json_{claim_id}")
    if allow_delete and c3.button("Delete this check", key=f"del_{claim_id}"):
        claimcheck.delete_claim(ws, claim_id)
        st.rerun()


# ---------------------------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------------------------
def page_check() -> None:
    st.title("Check a claim")
    ws = workspace()
    if ws is None:
        st.info("Create a project in the sidebar, then add sources on the Sources page.")
        return
    n_docs = ws.scalar("SELECT COUNT(*) FROM documents") or 0
    if not ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'"):
        st.info("This project has no readable documents yet.")
        st.page_link(PAGES["sources"], label="Add sources", icon="📄")
        return
    s = settings()
    st.caption(f"Project **{s['project']}** · {n_docs} documents. The claim is checked against the passages that match it "
               "best, and a model grades each one. Every quote is checked against the source text.")

    claim = st.text_area("Claim", key="claim_text", height=90,
                         placeholder="e.g. Green hydrogen production increases water stress in arid regions.")
    suggested = [x["code"] for x in claimcheck.suggest_targets(claim)] if len(claim.strip()) >= 15 else []
    others = [c for c in sorted(targets(), key=target_sort_key) if c not in suggested]
    options = [""] + suggested + others
    target = st.selectbox("SDG target (optional)", options, key="claim_target",
                          format_func=lambda c: "No specific target" if not c else
                          ("★ " if c in suggested else "") + target_label(c),
                          help="Starred targets are suggested from the claim's wording. The model sees the target's text.")

    with st.expander("Options"):
        c1, c2 = st.columns(2)
        k = c1.slider("Passages to read", 4, 12, int(s["k"]),
                      help="More passages find more evidence but cost more and take longer.")
        per_doc = c2.slider("At most this many from one document first", 1, 4, int(s["per_doc"]),
                            help="Keeps one long report from filling every slot.")
        expand = c1.toggle("Let the model add search terms", value=bool(s["expand"]),
                           help="One extra short model call. Finds passages that use other words than the claim.")
        threshold = c2.slider("Count grades from confidence", 0.0, 1.0, float(s["threshold"]), 0.05,
                              help="Grades below this confidence are shown but do not decide the status.")
        docs = document_overview(ws)
        chosen = st.multiselect("Only these documents", [d["doc_id"] for d in docs],
                                format_func=lambda d: next(x["title"] for x in docs if x["doc_id"] == d)[:90],
                                placeholder="All documents")
        if (k, per_doc, expand, threshold) != (s["k"], s["per_doc"], s["expand"], s["threshold"]):
            save(k=k, per_doc=per_doc, expand=expand, threshold=threshold)

    if st.button("Check claim", type="primary", disabled=len(claim.strip()) < 10):
        try:
            backend, model = core.make_backend(s, api_key())
        except BackendError as e:
            st.error(str(e))
            st.page_link(PAGES["settings"], label="Open Settings", icon="⚙️")
            return
        t0 = time.time()
        with st.status("Checking the claim…", expanded=True) as status:
            def step(_kind, msg):
                status.update(label=msg + "…")
                status.write(msg)
            try:
                cid = claimcheck.check_claim(ws, claim, backend, model, target=target or None, k=k, per_doc=per_doc,
                                             expand=expand, doc_ids=chosen or None, progress=step)
            except (BackendError, ValueError) as e:
                status.update(label="Stopped", state="error")
                st.error(str(e))
                return
            status.update(label=f"Done in {time.time() - t0:.0f} seconds", state="complete", expanded=False)
        st.session_state.last_claim = cid

    if st.session_state.get("last_claim"):
        st.divider()
        show_result(ws, st.session_state.last_claim, float(settings()["threshold"]))


def page_sources() -> None:
    st.title("Sources")
    ws = workspace()
    if ws is None:
        st.info("Create a project in the sidebar first.")
        return
    st.caption(f"Project **{settings()['project']}** · folder `{ws.root}`")

    files = st.file_uploader("Add sources: a zip, or PDF, HTML, text or Markdown files", accept_multiple_files=True,
                             type=["zip", "pdf", "html", "htm", "txt", "md"], key=f"up_{st.session_state.get('up_n', 0)}")
    with st.expander("Upload options"):
        st.markdown("A `manifest.csv` inside the zip (columns `file`, `reference`, `doi`) names the work each file is. "
                    "PDFs keep their page numbers. Scanned PDFs without a text layer need OCR first.")
        exclude = st.text_input("Leave out files whose name matches", placeholder="e.g. A_18_*  (several: separate with spaces)")
    if files and st.button(f"Add {len(files)} file{'s' if len(files) > 1 else ''} to the project", type="primary"):
        folder = core.save_uploads(ws, [(f.name, f.getvalue()) for f in files])
        bar = st.progress(0.0, text="Reading files…")
        stats = ingest.ingest(ws, [folder], exclude=exclude.split() or None,
                              progress=lambda i, n, name: bar.progress(i / max(n, 1), text=f"Reading {name} ({i + 1} of {n})"))
        bar.progress(1.0, text="Done")
        msg = f"Added {stats['added']} documents ({stats['passages']:,} passages)."
        if stats["duplicates"]:
            msg += f" {stats['duplicates']} were already in the project."
        st.success(msg)
        if stats.get("empty"):
            st.warning(f"{stats['empty']} files had no text (scanned PDFs need OCR).")
        if stats.get("mostly_unreadable"):
            st.warning("Mostly unreadable text layer: " + ", ".join(stats["mostly_unreadable"]) +
                       ". Find another copy (often the publisher's) or run OCR.")
        if stats.get("not_in_manifest"):
            st.info("Not named in the manifest: " + ", ".join(stats["not_in_manifest"][:10]))
        st.session_state.up_n = st.session_state.get("up_n", 0) + 1

    docs = document_overview(ws)
    st.subheader(f"Documents ({len(docs)})")
    if not docs:
        st.caption("None yet.")
    else:
        st.dataframe([{"Title": d["title"], "Kind": d["kind"], "Pages": d["pages"], "Passages": d["passages"],
                       "Check": d["check"], "File": d["file"], "Added": d["added"]} for d in docs],
                     hide_index=True,
                     column_config={"Title": st.column_config.TextColumn(width="large"),
                                    "Check": st.column_config.TextColumn(width="medium",
                                                                         help="Unreadable or very short files hold no usable evidence")})
    with st.expander("Remove all documents"):
        st.markdown("Removes every document and every check made against them. Settings and other projects stay.")
        if st.checkbox("Yes, remove them", key="confirm_reset") and st.button("Remove all documents"):
            ws.reset_corpus()
            st.session_state.pop("last_claim", None)
            st.rerun()

    with st.expander("Use an existing workspace as a project"):
        st.markdown("For example the pilot folder from the zip (`pilot`). It is linked, not copied.")
        path = st.text_input("Folder path", key="link_path")
        if st.button("Link folder") and path:
            try:
                save(project=core.link_existing(path))
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def page_history() -> None:
    st.title("History")
    ws = workspace()
    if ws is None:
        st.info("Create a project in the sidebar first.")
        return
    thr = float(settings()["threshold"])
    rows = claimcheck.history(ws, thr)
    if not rows:
        st.caption("No checks in this project yet.")
        return
    table = [{"Checked": local_time(r["created_at"]), "Claim": r["claim"], "Target": r["target"],
              "Status": claimcheck.STATUS_TEXT.get(r["status"], r["status"]), "Supports": r["supports"],
              "Partly": r["partly"], "Refutes": r["refutes"], "Model": r["model"]} for r in rows]
    ev = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row",
                      column_config={"Claim": st.column_config.TextColumn(width="large")})
    st.download_button("Download all checks as CSV", to_csv(claimcheck.export_rows(ws, thr)), file_name="checks.csv",
                       mime="text/csv")
    picked = ev.selection.rows if ev and ev.selection else []
    if picked:
        st.divider()
        show_result(ws, rows[picked[0]]["claim_id"], thr, allow_delete=True)
    else:
        st.caption("Select a row to see its evidence.")


def page_settings() -> None:
    st.title("Settings")
    s = settings()
    labels = {"anthropic": "Claude API (Anthropic)", "ollama": "Ollama, on this computer", "baseline": "Offline demo (no model)"}
    backend = st.radio("Model service", list(labels), format_func=labels.get, index=list(labels).index(s["backend"]),
                       horizontal=True)
    if backend != s["backend"]:
        save(backend=backend)

    if backend == "anthropic":
        st.markdown("Text of the passages read is sent to Anthropic's API. Usage is billed to the key's account.")
        have = "environment variable ANTHROPIC_API_KEY" if core.env_key() else ("saved on this computer" if core.stored_key() else "")
        if have:
            st.success(f"A key is set ({have}).")
        key = st.text_input("API key", type="password", placeholder="sk-ant-…", help="From console.anthropic.com")
        remember = st.checkbox("Remember the key on this computer", value=bool(core.stored_key()),
                               help=f"Saved in {core.home() / 'credentials.json'}, readable by your user only.")
        if key:
            st.session_state.api_key = key
            if remember:
                core.remember_key(key)
        if not remember and core.stored_key():
            core.forget_key()
        model = st.text_input("Model", value=s["anthropic_model"], help="For example claude-opus-5-5")
        if model != s["anthropic_model"]:
            save(anthropic_model=model.strip())
        if st.button("Test connection"):
            try:
                be, m = core.make_backend(settings(), api_key())
                info = be.check(m)
                if info.get("model_available"):
                    st.success(f"Connected. {m} is available.")
                else:
                    st.warning(f"Connected, but {m} is not in this key's model list: " + ", ".join(info["models"][:12]))
            except BackendError as e:
                st.error(str(e))

    elif backend == "ollama":
        st.markdown("Text stays on this computer. Install Ollama from ollama.com, then pull a model, for example "
                    "`ollama pull qwen3:8b`. Larger models judge better but need more memory and time.")
        url = st.text_input("Ollama address", value=s["ollama_url"])
        if url != s["ollama_url"]:
            save(ollama_url=url.strip())
        try:
            from enlens_claims.llm import OllamaBackend

            installed = OllamaBackend(base_url=url, timeout=5).models()
        except BackendError as e:
            installed = []
            st.warning(str(e))
        if installed:
            cur = s["ollama_model"] if s["ollama_model"] in installed else installed[0]
            model = st.selectbox("Model", installed, index=installed.index(cur))
        else:
            model = st.text_input("Model", value=s["ollama_model"], placeholder="e.g. qwen3:8b")
        if model and model != s["ollama_model"]:
            save(ollama_model=model)
        c1, c2 = st.columns(2)
        ctx = c1.number_input("Context length (tokens)", 4096, 131072, int(s["num_ctx"]), 4096,
                              help="16,384 covers every task. Ollama's own default is much smaller and silently cuts "
                                   "long prompts. Larger values use more memory.")
        think = c2.selectbox("Reasoning (thinking models only)", ["default", "off", "on"],
                             index=["default", "off", "on"].index(s["think"]),
                             help="For models that reason before answering. Off is faster. Some models (gpt-oss) "
                                  "cannot switch it off; leave those at default. Ignored for models that do not think.")
        if (int(ctx), think) != (int(s["num_ctx"]), s["think"]):
            save(num_ctx=int(ctx), think=think)
        if st.button("Test connection"):
            try:
                be, m = core.make_backend(settings())
                info = be.check(m)
                if not info.get("model_available"):
                    st.warning(f"Ollama {info['version']} is running, but {m} is not installed. Run: ollama pull {m}")
                else:
                    md = info.get("model", {})
                    st.success(f"Ollama {info['version']} is running. {m}: {md.get('parameters') or '?'} parameters, "
                               f"{md.get('quantization') or '?'}, trained for {md.get('trained_context') or '?'} tokens of context.")
                    if info.get("warning"):
                        st.warning(info["warning"])
            except BackendError as e:
                st.error(str(e))
    else:
        st.info("The demo grades passages by word overlap. It shows how the app works; its results are not findings.")

    st.divider()
    st.subheader("Test a model before trusting it")
    st.markdown("Runs the chosen model on tasks from a workspace that another model already answered (the pilot was "
                "answered by Claude Opus 5.5), and compares the answers. Nothing is stored. This measures agreement "
                "with the reference, not correctness.")
    ref = st.text_input("Reference workspace folder", value=s.get("benchmark_reference") or "",
                        placeholder="e.g. /path/to/enlens-claims-0.3/pilot")
    c1, c2 = st.columns(2)
    n = c1.slider("Tasks per kind", 5, 50, 10, 5)
    kinds = c2.multiselect("Tasks", ["verify_set", "extract"], default=["verify_set"],
                           format_func={"verify_set": "Checking claims", "extract": "Extracting claims"}.get)
    if s["backend"] == "anthropic":
        st.caption(f"With the Claude API this uses tokens: {n * len(kinds)} model calls.")
    if st.button("Run test", disabled=not (ref and kinds)):
        if ref != s.get("benchmark_reference"):
            save(benchmark_reference=ref)
        try:
            from enlens_claims.store import Workspace

            rws = Workspace.open(Path(ref).expanduser())
            be, m = core.make_backend(settings(), api_key())
        except (FileNotFoundError, BackendError) as e:
            st.error(str(e))
            return
        bar = st.progress(0.0, text="Starting…")
        try:
            res = bench.run(rws, be, m, kinds=tuple(kinds), sample=n,
                            progress=lambda i, total, tid: bar.progress((i - 1) / total, text=f"Task {i} of {total}"))
        except (ValueError, BackendError) as e:
            st.error(str(e))
            return
        bar.progress(1.0, text="Done")
        for line in bench.verdict(res):
            st.markdown(f"- {line}")
        st.dataframe(benchmark_table(res), hide_index=True)
        st.download_button("Download the full result", json.dumps(res, indent=2).encode(),
                           file_name=f"benchmark_{m.replace(':', '_')}.json", mime="application/json")


def benchmark_table(res: dict) -> list[dict]:
    """Measures as rows, task kinds as columns, in words."""
    rows = [("Tasks run", "tasks", "n"), ("Failed to answer (errors)", "errors", "n"),
            ("Usable answers on the first try", "usable", "%"), ("Valid JSON", "valid_json", "%"),
            ("Answers with a quote not in the text", "quote_problems", "%"),
            ("Same status as the reference", "same_status", "%"),
            ("Grounded or not: agreement beyond chance (κ)", "grounded_kappa", "k"),
            ("Same grade per passage", "same_passage_grade", "%"),
            ("Has a claim or not: agreement beyond chance (κ)", "claims_kappa", "k"),
            ("Overlap of SDG targets named", "target_overlap", "%"), ("Same direction on shared targets", "same_direction", "%"),
            ("Median seconds per task", "seconds_median", "n")]
    names = {"verify_set": "Checking claims", "extract": "Extracting claims"}
    out = []
    for label, key, fmt in rows:
        vals = {names.get(k, k): v.get(key) for k, v in res["kinds"].items()}
        if all(v is None for v in vals.values()):
            continue
        out.append({"Measure": label, **{k: ("–" if v is None else f"{v:.0%}" if fmt == "%" else f"{v:.2f}" if fmt == "k"
                                              else f"{v:g}") for k, v in vals.items()}})
    return out


PAGES = {
    "check": st.Page(page_check, title="Check a claim", icon="🔎", default=True),
    "sources": st.Page(page_sources, title="Sources", icon="📄", url_path="sources"),
    "history": st.Page(page_history, title="History", icon="🕘", url_path="history"),
    "settings": st.Page(page_settings, title="Settings", icon="⚙️", url_path="settings"),
}

sidebar()
st.navigation(list(PAGES.values())).run()
