#!/usr/bin/env python3
"""Make a folder of open-access papers with their true text, for `enlens measure --folder DIR`.

A developer tool. It is never run by the tests and needs the network. For each arXiv paper in PAPERS it downloads the
PDF (https://arxiv.org/pdf/<id>) and the LaTeX source (https://arxiv.org/e-print/<id>), turns the main .tex file
into plain text and writes `<id>.pdf` and `<id>.txt` (a slash in an old-style id becomes an underscore).

THE TEXT IS APPROXIMATE. The de-TeX below is rough: it drops the preamble, comments, mathematics, figures, tables,
code, citations, cross-references and the bibliography, and keeps the title, the section titles and the words of the
paragraphs. Macros defined by the authors, text inside unusual environments and symbols in the PDF that the source
writes differently (a ligature, an accent made by a command) will differ from what the PDF shows, so the figures
this folder gives carry a little noise (a point or two). What they are good for is the comparison between readers
on the same files, not an absolute score.

    python tools/arxiv_truth.py OUTPUT_FOLDER [--only ID ...] [--pause SECONDS]

Papers (all open access on arXiv, well known, with plain LaTeX); add more ids to the list for other fields.
"""
from __future__ import annotations

import argparse
import gzip
import io
import re
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

PAPERS = [
    "1706.03762",  # Attention Is All You Need
    "1502.03167",  # Batch Normalization
    "1512.03385",  # Deep Residual Learning for Image Recognition
    "1810.04805",  # BERT
    "1409.0473",   # Neural Machine Translation by Jointly Learning to Align and Translate
    "1301.3781",   # Efficient Estimation of Word Representations in Vector Space
    "1406.2661",   # Generative Adversarial Networks
    "1312.6114",   # Auto-Encoding Variational Bayes
    "1503.02531",  # Distilling the Knowledge in a Neural Network
    "1409.1556",   # Very Deep Convolutional Networks for Large-Scale Image Recognition
]
MIN_WORDS = 500    # less than this and the source is not the text of the paper
USER_AGENT = "ENLENS-measure (research tool; contact: the ENLENS developers)"

# environments whose content is not running text
_DROP_ENVS = ("figure", "table", "equation", "align", "eqnarray", "gather", "multline", "displaymath", "math",
              "tabular", "tabularx", "algorithm", "algorithmic", "lstlisting", "verbatim", "thebibliography",
              "minipage", "wrapfigure", "tikzpicture", "subfigure", "split", "array", "flalign", "tabbing",
              "comment", "CCSXML", "IEEEkeywords", "keywords")
# commands whose braces hold nothing to read
_DROP_CMDS = ("cite", "citep", "citet", "citealp", "citeauthor", "citeyear", "ref", "eqref", "autoref", "cref",
              "Cref", "pageref", "label", "footnote", "thanks", "vspace", "hspace", "vskip", "hskip", "includegraphics",
              "bibliography", "bibliographystyle", "input", "include", "usepackage", "url", "texttt", "index",
              "setlength", "caption", "footnotetext", "footnotemark", "newcommand", "renewcommand", "def",
              "DeclareMathOperator", "mathbf", "mathcal", "mathrm", "mathbb", "mbox", "color", "textcolor")


def fetch(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310  fixed arxiv.org addresses
        return r.read()


def source_files(blob: bytes) -> dict[str, str]:
    """The .tex files of an e-print (a gzipped tar, or one gzipped file), by name."""
    data = blob
    try:
        data = gzip.decompress(blob)
    except OSError:
        pass
    out: dict[str, str] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            for m in tf.getmembers():
                if m.isfile() and m.name.lower().endswith(".tex"):
                    out[m.name] = tf.extractfile(m).read().decode("utf-8", errors="replace")
        if out:
            return out
    except tarfile.TarError:
        pass
    out["main.tex"] = data.decode("utf-8", errors="replace")
    return out


def main_tex(files: dict[str, str]) -> str:
    """The text of the main file with its \\input and \\include files put in place."""
    mains = [n for n, t in files.items() if r"\begin{document}" in t]
    if not mains:
        raise ValueError("no main .tex file (no \\begin{document})")
    name = max(mains, key=lambda n: len(files[n]))
    by_base = {Path(n).stem: t for n, t in files.items()}

    def put(text: str, depth: int = 0) -> str:
        if depth > 6:
            return text
        text = strip_comments(text)

        def sub(m):
            ref = Path(m.group(2).strip()).stem
            return put(by_base.get(ref, ""), depth + 1)

        return re.sub(r"\\(input|include)\s*\{([^}]*)\}", sub, text)

    return put(files[name])


def strip_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", text)


def _braced(text: str, start: int) -> tuple[str, int]:
    """The text of the {group} that opens at `start`, and the position after it."""
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "\\":
            continue
        if c == "{" and text[i - 1:i] != "\\":
            depth += 1
        elif c == "}" and text[i - 1:i] != "\\":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
    return text[start + 1:], len(text)


def _drop_command(text: str, name: str) -> str:
    """Remove \\name[...]{...} (every braced argument that follows directly)."""
    pat = re.compile(r"\\" + name + r"\*?(?![A-Za-z])\s*(\[[^\]]*\])*")
    out, pos = [], 0
    while True:
        m = pat.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        out.append(text[pos:m.start()])
        i = m.end()
        while text[i:i + 1] == "{":
            _g, i = _braced(text, i)
            if name not in ("newcommand", "renewcommand", "DeclareMathOperator"):
                break
        pos = i
    return "".join(out)


def detex(tex: str) -> str:
    """A rough plain text of a LaTeX document: its title, section titles and paragraphs. See the module's note: it is
    approximate."""
    tex = strip_comments(tex)
    title = ""
    m = re.search(r"\\title\s*(\[[^\]]*\])?\s*\{", tex)
    if m:
        t, _e = _braced(tex, m.end() - 1)
        t = _drop_command(t, "thanks")
        t = re.sub(r"\\\\|\\and", " ", t)
        title = _plain(t)
        if not 3 < len(title) < 300:
            title = ""
    if r"\begin{document}" in tex:
        tex = tex.split(r"\begin{document}", 1)[1]
    for end in (r"\begin{thebibliography}", r"\bibliography{", r"\end{document}", r"\appendix"):
        tex = tex.split(end, 1)[0]
    for env in _DROP_ENVS:
        tex = re.sub(r"\\begin\{" + re.escape(env) + r"\*?\}.*?\\end\{" + re.escape(env) + r"\*?\}", " ", tex,
                     flags=re.S)
    tex = re.sub(r"\$\$.*?\$\$", " ", tex, flags=re.S)
    tex = re.sub(r"\\\[.*?\\\]", " ", tex, flags=re.S)
    tex = re.sub(r"\\\(.*?\\\)", " ", tex, flags=re.S)
    tex = re.sub(r"(?<!\\)\$.*?(?<!\\)\$", " ", tex, flags=re.S)
    for name in _DROP_CMDS:
        tex = _drop_command(tex, name)
    # section titles on lines of their own
    tex = re.sub(r"\\(?:sub)*(?:section|paragraph)\*?\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", r"\n\n\1\n\n", tex)
    tex = re.sub(r"\\begin\{abstract\}|\\end\{abstract\}", "\n\n", tex)
    tex = re.sub(r"\\item\b", "\n\n", tex)
    return "\n\n".join(x for x in [title, "\n".join(_plain(p) for p in re.split(r"\n\s*\n", tex) if _plain(p))] if x) + "\n"


def _plain(s: str) -> str:
    """The words of a piece of LaTeX: commands removed, their braces' text kept, accents and quotes simplified."""
    s = re.sub(r"\\(?:begin|end)\s*\{[^}]*\}", " ", s)
    s = re.sub(r"\\(?:textbf|textit|emph|textsc|textrm|textsf|underline|mathit)\s*\{", "{", s)
    s = re.sub(r"\\href\s*\{[^}]*\}", "", s)
    s = re.sub(r"\\['`^\"~=.]\{?([A-Za-z])\}?", r"\1", s)
    s = s.replace("``", '"').replace("''", '"').replace("~", " ").replace("---", " - ").replace("--", "-")
    s = re.sub(r"\\[,;:! ]", " ", s)
    s = re.sub(r"\\(?:&|%|_|#|\$)", lambda m: m.group(0)[1], s)
    s = re.sub(r"\\[A-Za-z]+\*?(\[[^\]]*\])?", " ", s)
    s = s.replace("{", "").replace("}", "").replace("\\", " ")
    return re.sub(r"\s+", " ", s).strip()


def make(out: Path, ids: list[str], pause: float = 3.0) -> int:
    out.mkdir(parents=True, exist_ok=True)
    done = 0
    for n, pid in enumerate(ids):
        stem = pid.replace("/", "_")
        if (out / f"{stem}.pdf").exists() and (out / f"{stem}.txt").exists():
            print(f"{pid}: already there", file=sys.stderr)
            continue
        if n:
            time.sleep(pause)
        try:
            pdf = fetch(f"https://arxiv.org/pdf/{pid}")
            time.sleep(pause)
            text = detex(main_tex(source_files(fetch(f"https://arxiv.org/e-print/{pid}"))))
        except Exception as e:  # noqa: BLE001  one paper that fails does not stop the others
            print(f"{pid}: skipped ({type(e).__name__}: {e})", file=sys.stderr)
            continue
        if len(text.split()) < MIN_WORDS:   # some sources are only a wrapper around the PDF
            print(f"{pid}: skipped (the source gives only {len(text.split())} words of text)", file=sys.stderr)
            continue
        (out / f"{stem}.pdf").write_bytes(pdf)
        (out / f"{stem}.txt").write_text(text, encoding="utf-8")
        print(f"{pid}: {len(text.split())} words of truth", file=sys.stderr)
        done += 1
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", help="folder to write <id>.pdf and <id>.txt into")
    ap.add_argument("--only", nargs="+", help="only these arXiv ids")
    ap.add_argument("--pause", type=float, default=3.0, help="seconds between requests (default 3)")
    a = ap.parse_args(argv)
    n = make(Path(a.out), a.only or PAPERS, a.pause)
    print(f"{n} paper(s) written to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
