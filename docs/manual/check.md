[Manual](../MANUAL.md) › Check a hypothesis

# Check a hypothesis

> **In short**
> - In *Hypotheses*, write one sentence that could be true or false (or several, one per line) and press *Check*
>   (<kbd>Ctrl</kbd>+<kbd>Enter</kbd>).
> - ENLENS finds the excerpts that bear on it, the AI judges each with a quote, and every quote is checked against
>   the source.
> - The answer counts only judgements the AI is sure enough about, and always yours.

## Writing the hypothesis

*Hypotheses* (under **Check** in the sidebar, marked *Uses the AI*) has one box for what you want to test, with the
answers listed under it and an *Evidence map* tab ([Read and review a result](review.md#the-list-of-answers)). By the
*Check* button, *Claude, on your plan, reads the excerpts it needs* says which AI reads your text.

The box takes one hypothesis, or several ([below](#checking-many-at-once)). One sentence that could be true or false: *Remote work lowers commuting emissions in large cities*, *Green hydrogen
production increases water stress in arid regions*. When it contains "and", "but" or a semicolon, the app offers to
**check each part separately**. [How a check reaches its answer](how-a-check-works.md) explains the steps.

*More options*:

- let the AI think of other words your documents might use;
- tag the hypothesis with a code of a codebook (an SDG target, or a code of your own);
- limit the check to some documents.

**Look before checking** shows first how the hypothesis will be checked: the parts the AI would split it into (with
*Check each part separately*) and the extra words it would search for. Change, remove or add a part; remove search
words that do not fit and add words your documents use; then *Check*. The result records that you set them.

## What a check does

The hypothesis is split into parts if you asked (and the AI can), the AI may think of other words, the best excerpts
are found by their words and by meaning, the AI judges each with a quote and a certainty, and every quote is checked
against the source. The six steps, with the checks a quote must pass:
[What a check does](how-a-check-works.md#what-a-check-does).

**While it runs**, the page shows each step as it finishes: the parts, the other words searched for, how many
excerpts from how many documents, the AI reading them. *Technical details* shows what the model does second by
second. Remarks about the round appear under the steps (excerpts of restricted documents read on this computer, or
waiting for you). *Stop* ends the check and leaves nothing behind; with a model on this computer it also stops the
model. You can use the rest of the app meanwhile.

With Claude Code as the AI, the check may wait for you to press *Start Claude Code*
([Claude Code](claude-code.md#start-claude-code)).

## How sure the AI must be

Each judgement comes with the AI's **certainty**, and counts only when it reaches the **strictness** (60% by default).
Change it in [*Settings → Checking*](settings.md#the-five-tabs). **Your own judgement always counts.** What the two
mean: [How sure the AI must be](how-a-check-works.md#how-sure-the-ai-must-be).

## The answers

The answer under the box is one of nine: *Supported by your documents*, *Partly supported*, *Mixed evidence*,
*Contradicted by your documents*, and the grey ones, *Only uncertain evidence*, *No evidence found*, *Nothing in your
documents matched*, *Not finished yet* and *The check did not work*. What each means, and what to do about each:
[The answers](how-a-check-works.md#the-answers).

> [!TIP]
> *No evidence found* is about the excerpts read, not about your documents. Under the evidence, *Read more excerpts*
> and *Search with other words* look further: documents often say "telework" where you wrote "remote work".

### A hypothesis checked in parts

The parts must all hold: one contradicted part contradicts the whole, and every part supported supports it. The app
says which part decides. The full rules: [A hypothesis checked in
parts](how-a-check-works.md#a-hypothesis-checked-in-parts). *Who says what*, the documents behind an answer by side:
[Who says what](how-a-check-works.md#who-says-what).

## Checking many at once

The same box checks a list of hypotheses one after the other. Write them one per line, or load a spreadsheet or CSV
with a column `hypothesis` (or `claim`, `text`, `statement`) and optional `framework` and `code` columns. The button
counts what it will check (*Check 3*). *Look before checking* is for one hypothesis at a time. A hypothesis that
cannot be checked is listed and the next one is checked; a problem with the AI stops the set and keeps what was
done. Each answer then appears in the list under the box.

---

Next: [Read and review a result →](review.md)
