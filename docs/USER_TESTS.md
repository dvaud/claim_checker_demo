# First-time user tests of the app (0.5.1 to 0.7.0)

The aim: a social scientist without computational background, using ENLENS for the first time on a computer someone
else set up, should find it obvious what to do and what is happening, without a tutorial.

## How the tests were run

A sub-agent played the researcher. It used the app only through a browser at 1366×800, decided each step from
screenshots, and did not read code, HTML or the API. Each test started from a fresh install made with
`python tools/dev_server.py --fresh-user`: the AI already configured, no project yet, and six documents on remote
work waiting in a folder (`tools/demo_corpus/`: two PDFs, three text files, one saved web page).

The AI in the test setup is a word-overlap stand-in, so many of its judgements were wrong on purpose. The testers
were asked to judge the interface, including whether it let them notice and correct a wrong judgement.

The goals were the same in every round: add documents to a new project; check a hypothesis; explain the answer to a
colleague (which documents, where in them); review the AI's judgements like a co-coder's (rounds 2–5); check a
two-part hypothesis; make the app look harder; check three hypotheses at once; export for a co-author who uses
Excel; make the counting stricter and set it back; look around Settings.

## Results

| Round | Tester | Obvious what to do | Obvious what is happening / what it means | Main findings fixed afterwards |
| --- | --- | --- | --- | --- |
| 1 | Sociologist | 8/10 | 4/10 | Headline, counts and AI summary contradicted each other; no way to overrule the AI; strictness in four places; model names ("fake-model") on working screens; CSV export with programmer columns; no locations for text files |
| 2 | Sociologist | 8/10 | 6/10 | How parts combine; verdicts worded too strongly; no review step; strictness felt like "reliable"; cloud option next to local ones; Excel without a summary |
| 3 | Public-administration researcher | 8/10 | 5/10 | Intensive review exposed bugs: counts out of step with the cards, "Agree" overwriting a correction, folds collapsing; locations not checkable in the app; "Back to normal" did not save |
| 4 | Public-administration researcher | 8/10 | 6/10 | A comment typed before judging was lost; cards jumping; batch button disabled without a reason; "not about" excerpts outside the review queue |
| 5 | Labour sociologist | 8/10 | 6/10 | Unreviewed answers looked final; could not point to the sentence meant; part-level wording; tooltips invisible on touch |

The fixes after round 5 (provisional answers, *Mark the sentence you mean*, wording for split hypotheses, popovers,
returning to the excerpt from the document view) were checked with scripted browser flows, not with a sixth tester.

## What testers found clear throughout

The two-step start; *What happens when you check*; the live progress with Stop; highlighted quotes verified against
the document, with *Show more of the document*; *What to do next*; recoding with Undo and the agreement figure; the
split-hypothesis rule; the Results list; the Excel export; the honest note that the AI's certainty is its own
estimate; the private / local indicator.

## What remains

- Every tester said they would use ENLENS as a first-pass co-coder whose judgements they check, not cite its answers
  unreviewed. The app now supports and encourages that review.
- *Settings → Advanced* stays technical (it is labelled for IT staff). The cloud option alarmed testers even behind
  a confirmation; installers can remove it with `enlens-gui --local-only`.
- Suggestions not yet built: preview and edit the split into parts and the AI's extra search words before a check;
  flag excerpts about another group than the hypothesis names.


## 0.6.0: the new features (rounds 6 and 7)

Same method: a sub-agent played the researcher, using the app only through a browser at 1366×800 and deciding each
step from screenshots, on a fresh install made with `python tools/dev_server.py --fresh-user` (the AI configured, no
project, the six demo documents waiting, plus a seventh "from a colleague" to add later). The stand-in AI now also
flags excerpts about fully remote workers for hypotheses about hybrid work, follows words such as "not" or "only" in
a person's hint when it reads an excerpt again, and offers a second, more cautious model ("llama3.1:8b").

Round 6 had ten goals: add documents; check a two-part hypothesis after *Look before checking* (remove a search word,
add one); explain the answer with locations and open the original there; review like a co-coder and ask the AI to
read one excerpt again with a reason; find an excerpt about another group; get a second model's opinion; add the
colleague's report and bring the result up to date; check three hypotheses and see which documents decide which
answers; see how often you agreed with the AI; send everything to a co-author (Excel and the whole project) and
quit. Round 7, after the fixes, took seven goals on the parts that had caused trouble, with a different tester.

| Round | Tester | Obvious what to do | Obvious what is happening / what it means | Main findings fixed afterwards |
| --- | --- | --- | --- | --- |
| 6 | Labour sociologist | 7/10 | 7/10 | Cards jumped after a judgement or a re-read; saving only a comment counted as agreeing with the AI; *Open the original* did not go to the place; a re-read gave no reason; *Next to review* did not go to disagreements first; the second-model box moved; the preview did not follow a changed option; sentences split at initials |
| 7 | Public-administration researcher | 7/10 | 8/10 | Marking a sentence before judging recorded agreement; *Next to review* returned to a card left undecided; the second model was compared only with the first AI, not with the person; a radio button lost its state (one group shared by the same excerpt in two parts); a re-read's reason was not kept as a comment; no overview of all excerpts (now a *Table* view) |

The fixes after round 7 were checked with scripted browser flows, not with an eighth tester.

What both testers found clear: *Look before checking* with editable parts and search words; the labels saying who
judged what ("AI only, not reviewed", "your judgement", "AI said: …", "your comment (not a judgement)"); exact
locations ("page 1, paragraph 4") and quotes verified against the document; Undo after every action; the re-read
history with the AI's reason and the hint given; *Read the new documents*, which keeps reviews; the evidence map
("the best screen in the app"), which let the first tester catch a wrong answer resting on one document; the Excel
download with its *Map* sheet; *Quit ENLENS*.

What remains:

- Both would use ENLENS as a first-pass coder whose work they check. The second warned that a re-read with a hint
  can simply echo the person's view; the app now says so next to every re-read.
- The second model is named by its technical name (with a plain hint about its size); model choice is still the
  part of the app that needs whoever installed it.
- Headless test browsers cannot show PDFs, so *Open the original* for PDFs (opening at the page) was checked by its
  link only; on a real browser it opens the PDF viewer at the page.


## 0.7.0: exploring the documents (round 8)

Same method, on a fresh install with the six remote-work documents (`tools/dev_server.py --fresh-user`). Both
testers were told they had used the Cross-Doc SDG Explorer before. That was a premise of the simulation only: Cross-Doc
was never finished and has no users, so no one can repeat their Cross-Doc work in ENLENS, and no release waits for
that (0.8). Ten goals each, run at the same time:

- **Labour sociologist:** add the documents; every line about "commuting" into Excel; which SDG targets the
  wellbeing paper touches, where and why; correct a code; let the AI read the codes and say what changed; the
  concept "remote work" and its wordings; themes (rename one, documents per theme); a check with a highlighted PDF;
  what "They…" refers to; a quick look at one document, then not keep it.
- **Public-administration researcher:** goals per document into Excel; a phrase search, a near search, words around
  "hybrid"; key terms, codes and search in one document; themes named by the AI and merged; which model, version and
  settings made the codes and whether they repeat; change the default themes and codebook; a check and what its
  quotes' "it" means; an own codebook; an export for FlexiConc / Cross-Doc.

| Round | Tester | Obvious what to do | Obvious what is happening / what it means |
| --- | --- | --- | --- |
| 8 | Labour sociologist | 6/10 | 6/10 (the result page alone 9/10) |
| 8 | Public-administration researcher | 7/10 | 5/10 |

Fixed before release:

- Search: words the stemmer keeps apart ("commuters" for "commuting") were silently left out; they are now listed
  under the count to add with one click. *Words nearby* showed a ratio that looked like a count; it now shows the
  count, ranks by count or by typicality, and has a window of 2 to 10 words. *All the words* says that the line is at
  the rarest word. An empty box under *Words nearby*; a "Not found" hint suggesting the mode already chosen; the
  "No AI is used" line next to search by meaning; an empty provenance sheet with check headers in the Excel file.
- What a *passage* is is said where counts of passages appear (Search, Profile).
- Themes: the default of 20 failed on a small project; a small project now gets about three passages a theme, and 2
  themes are allowed. After a merge the page jumped and the set still showed the old number of themes.
- Profile: the box still said "provisional" after the AI had read everything; after the AI pass nothing said what
  changed (it now says how many keyword codes were confirmed, not confirmed, and added); *Count by* forgot the choice
  and showed *Group* for a codebook without groups; the Excel columns of the grid had codes without names.
- Codes in a document: *Change* only changed how a code applies; it is now *Change how it applies*, with *Wrong code?
  Choose another instead*.
- Concepts: accepting a single-word wording ("home") renamed the concept; a concept is now named by its most
  frequent wording of two words or more. Proposed wordings could not be refused and came back; *Not the same* now
  keeps them away.
- References: "0 stretches" with no reason when a name does not occur; "No references found yet" after the whole
  document was read.
- Reproducibility: the exact version showed "not recorded" (the stand-in server did not report a digest, as Ollama
  does; the wording now says "not reported by the model server" when a server does not). The repeatable-answers test
  says what it asked and the exact version, and points to where each result's settings are.
- Settings: the profile codebook and the number of themes moved from *Advanced (for IT staff)* to a new *Exploring
  the documents* section; the codebook list no longer cuts the name; the built-in 17-goals codebook had a Delete
  button; examples from the hydrogen pilot in placeholders and help texts; "a SDG".
- Quick look: no way to discard it (now *Discard now* in the banner, back to the project it came from); after a
  project was removed the app had no project selected; dates in another format; a toast with a system path.
- FlexiConc export was only on the command line; it is now on the Projects page.

What both found clear: the start (new project, adding documents); the result page; labels saying who made them and
how sure the AI is; Undo; matched words highlighted in the text; the document page with its side panels; renaming
themes and the theme × document grid; the merge dialog; the Excel provenance sheet; the highlighted PDF.

What remains:

- The references and the names of themes and concepts depend on the model; with the stand-in model they were thin.
  Whether a local model does well enough is for the acceptance measures (CHANGELOG, *Not measured yet*).
- A link proposed by the AI and removed with *Not right* has no Undo; theme numbers keep gaps after a merge (numbers
  are kept so that references to them stay valid).
- The fixes were checked with scripted browser flows and the automated tests, not with a ninth tester.

## 0.8.0: Claude Code on your own plan (not tested with people yet)

The roadmap asks for two or three real researchers, each on their own Claude plan, to set up the plugin with only the
guide, run a profile and two checks through Claude Code, review the results, and stop and continue a run. The bar
stays 7/10 on "It is obvious what to do" and "It is obvious what is happening". That test comes after the runs on the
pilot (docs/MODEL_CHOICE.md), so the testers meet the final defaults. Before release, a developer also installs the
plugin in a real, signed-in Claude Code, runs `/enlens-run Demo`, stops it, continues it, and checks in a transcript
which model each helper ran on.

The interface was checked in a browser with the fake Claude Code (`tools/dev_server.py --claude-code` and
`--claude-code-paused`). It covered the waiting states of a check and of the profile labels, the queue panel,
Results with a waiting check, Settings (Claude Code, the plugin, AI model per task), and *Ask a stronger model* on a
result.

