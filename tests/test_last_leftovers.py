"""Deep dive leftovers (E3): an index on the answers' route, and the reading view's word picking. (E2's leftovers are
in test_0_17_2_small_leftovers.py.)"""
from __future__ import annotations

import pytest

from enlens_claims import home as core
from enlens_claims import taskqueue
from test_app import home  # noqa: F401  (fixture)


@pytest.fixture
def ws(home):  # noqa: F811
    return core.create_project("Leftovers")


def test_the_newest_answer_of_a_route_is_found_by_its_index(ws):
    with ws.connect() as cx:
        for i, route in enumerate(["Claude Code", "Local", "Claude Code", None, "Claude API"]):
            cx.execute("INSERT INTO results(task_id, attempt, kind, model, valid, received_at, route) "
                       "VALUES (?,?,?,?,?,?,?)", (f"t{i}", 1, "check", "m", 1, f"2026-11-0{i + 1}T10:00:00Z", route))
    assert taskqueue._last_answer(ws) == "2026-11-03T10:00:00Z"
    plan = " | ".join(r[3] for r in ws.query("EXPLAIN QUERY PLAN SELECT MAX(received_at) FROM results "
                                             "WHERE route='Claude Code'"))
    assert "ix_results_route" in plan, plan


def test_a_project_made_before_the_index_gets_it_when_opened(ws):
    with ws.connect() as cx:
        cx.execute("DROP INDEX ix_results_route")
    assert not ws.scalar("SELECT 1 FROM sqlite_master WHERE name='ix_results_route'")
    again = core.open_project("Leftovers")
    assert again.scalar("SELECT 1 FROM sqlite_master WHERE name='ix_results_route'") == 1


# ---------------------------------------------------------------------------------------------
# an astral letter picks a word in the reading view
# ---------------------------------------------------------------------------------------------
PROBE = r"""
const { wordSpan } = await import(LIB);
// the picking as it was before: one UTF-16 unit at a time
const OLD = /[\p{L}\p{N}_'’-]/u;
function oldSpan(t, i) {
  if (!OLD.test(t[i] || "")) { if (i > 0 && OLD.test(t[i - 1])) i--; else return null; }
  let s = i, e = i + 1;
  while (s > 0 && OLD.test(t[s - 1])) s--;
  while (e < t.length && OLD.test(t[e])) e++;
  while (s < e && /['’-]/.test(t[s])) s++;
  while (e > s && /['’-]/.test(t[e - 1])) e--;
  return e > s ? [s, e] : null;
}
const word = (t, i) => { const r = wordSpan(t, i); return r && t.slice(r[0], r[1]); };
const out = { same: [] };
// every index of texts without astral letters: the same word as before
for (const t of ["The yield of it's rose. Don’t-stop, 3.5 km!", "  --x--  ", "naïve café", "a", "", "word 😀 word", "end."])
  for (let i = 0; i <= t.length; i++) if (JSON.stringify(wordSpan(t, i)) !== JSON.stringify(oldSpan(t, i))) out.same.push([t, i]);
const t = "Yield 𝑥 rose, a𝑥b and 𠀀𠀁 next to 😀.";
const at = (needle, k = 0) => t.indexOf(needle) + k;
out.alone = word(t, at("𝑥"));              // on the pair's first half
out.alone2 = word(t, at("𝑥", 1));          // on its second half
out.inside = word(t, at("a𝑥b", 1));        // a word with an astral letter in it
out.insideEnd = word(t, at("a𝑥b", 3));
out.cjk = word(t, at("𠀀𠀁", 2));
out.afterAstral = word(t, at("𝑥 rose") + 2);   // on the space after it: the word before
out.emoji = word("word😀 x", 4);          // an emoji is no letter: the word before it, as for any sign
out.emojiAfterSpace = word(t, at("😀"));
out.emojiOnly = word("😀 😀", 0);
out.rose = word(t, at("rose"));
console.log(JSON.stringify(out));
"""


def test_a_letter_outside_the_bmp_picks_its_word(tmp_path):
    from _fakedom import run

    out = run(PROBE, tmp_path)
    assert out["same"] == []            # nothing changes for text without such letters
    assert out["alone"] == "𝑥" and out["alone2"] == "𝑥"
    assert out["inside"] == "a𝑥b" and out["insideEnd"] == "a𝑥b"
    assert out["cjk"] == "𠀀𠀁"
    assert out["afterAstral"] == "𝑥"
    assert out["emoji"] == "word" and out["emojiAfterSpace"] is None
    assert out["emojiOnly"] is None and out["rose"] == "rose"
