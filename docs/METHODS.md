# Methods

How ENLENS reads documents, finds passages, checks a hypothesis, labels passages with codes, builds a glossary and
finds themes, with the published methods it uses, written so that a researcher can describe their use of ENLENS in a
methods section. Each statement names the module of `src/enlens_claims/` or the manual page it can be checked
against. What leaves the computer, and when, is in [PRIVACY.md](PRIVACY.md).

## What ENLENS is for

ENLENS checks hypotheses against a researcher's own documents and helps explore them. Every judgement of a passage
carries a quote that is checked against the source text. Each project is a folder on the researcher's computer with
one SQLite database.

Its rule is "as little AI as possible" ([ROADMAP.md](ROADMAP.md#the-rule-as-little-ai-as-possible)): each feature is
built at the lowest level that does the job.

| Level | What it means | In ENLENS |
| --- | --- | --- |
| 0 · No AI | Rules, statistics, text matching, layout | Reading documents, search, keyword codes, the glossary, themes, agreement figures |
| 1 · Local program | A program on this computer, no language model | Tesseract for scanned pages, an embedding model for search by meaning |
| 2 · Local model | A language model on this computer | Any AI task; the only AI for documents marked *Only a local AI* |
| 3 · Claude | Anthropic's models | Judging excerpts, labels, theme names, concept links and the other AI tasks |

The AI part of a feature is optional: the rest works without it, and every AI answer is quoted, checked against the
text and can be overruled by a person.

## Reading documents

ENLENS reads PDF, Word, web pages, Markdown and plain text (`ingest.SUPPORTED`). The reader is numbered, and each
document records the one that read it (`ingest.READER`; reader 5 since ENLENS 0.18.1). A new reader reads only
documents added after an update; earlier documents keep their text, and every quote in them keeps its place, until a
person moves them to the new reader ([Read with the new reader](manual/reading.md#read-with-the-new-reader)).

The reader uses rules, no model (`reader.py`, `reader3.py`, `reader4.py`, `reader5.py`). It takes each line of a PDF
with its position and font (pdfminer), or recognises scanned pages with Tesseract at 200 dpi when it is installed
(`ingest.OCR_DPI`). It sets aside running heads, page numbers and line numbers by position and repetition, finds
columns and the reading order, groups lines into blocks, and gives each block a kind: title, heading, abstract, body,
caption, table, footnote, front or back matter, references, figure, furniture, contents or index (`reader.KINDS`).
Tables are found from aligned columns and ruled lines, figures are blocks of their own, and text is repaired
(ligatures, soft hyphens, words broken across lines). Body text, headings, the abstract and captions become
**passages**, the units every feature reads (`reader.INCLUDED`): short paragraphs are joined up to about 200
characters and long ones are cut between sentences at about 1,100 (`reader.make_passages`). Everything else stays in
the text but out of the passages. A person can see every block and *Leave out* or *Restore* it
([What the reader does](manual/reading.md#what-the-reader-does)).

The same file gives the same text on every computer with the same reader. `enlens measure` tests this and reports
reading quality against documents of known text
([Measuring how well ENLENS reads](manual/reading.md#measuring-how-well-enlens-reads)).

## Search and retrieval

**Words.** Text is folded (Unicode NFKC, typographic quotes and dashes unified, lower case) and split into words of
any script. Common words are removed (English, and the most frequent function words of Dutch, German, French,
Spanish and Portuguese), and a light English suffix stripper merges "increase", "increases" and "increased"
(`textutil.tokens`, `textutil.stem`). The glossary uses fuller lists of common words for 58 languages
(`stopwords.py`, from stopwords-iso).

**Ranking.** Passages are ranked with Okapi BM25 (Robertson and Zaragoza, 2009), k1 = 1.5 and b = 0.75, with an
inverse document frequency of log(1 + (N − n + 0.5) / (n + 0.5)) (`retrieve.BM25`). In a check, the hypothesis's own
words count twice and the extra search words once (`search.rank_passages`).

**Search by meaning (optional).** With an embedding model on the computer, each passage gets a vector and similarity
is the cosine (`embed.py`). The keyword and meaning rankings, 200 deep each, are merged by reciprocal rank fusion with
k = 60 (Cormack, Clarke and Büttcher, 2009; `search.RRF_K`). Each excerpt records whether keywords, meaning or both
found it.

**The excerpts of a check.** By default a check reads the best 8 excerpts, at most 2 from one document first, so one
long report cannot fill every place (`home.py` defaults `k` and `per_doc`). A second sorting by wording, without a
model, is off by default (`search.rerank`).

**The concordance** (*Search*) lists every place words occur, in four modes: any, all, phrase, near
(`concordance.py`). *Words that often appear nearby* ranks the words within a window (5 each side by default) by
pointwise mutual information, log2 of observed over expected frequency (Church and Hanks, 1990;
`concordance.collocates`).

## Checking a hypothesis

The code is in `claimcheck.py`, `verdicts.py`, `check_results.py`, `judgements.py` and `assessment.py`; the manual
pages are [Check a hypothesis](manual/check.md#what-a-check-does) and [Read and review a result](manual/review.md).

1. **Parts (optional, off by default).** A model splits a compound hypothesis into the claims that must all hold.
2. **Search words (optional, on by default).** A model writes other words a source might use: synonyms, technical
   terms and words for the opposite. With *Look before checking*, the person sees and edits the parts and words
   first, and the result records whether they did.
3. **Excerpts** are chosen as in [Search and retrieval](#search-and-retrieval).
4. **Grading.** A model reads the excerpts with the claim (prompt `check-v5`, `prompts.py`). For each excerpt that
   bears on the claim it gives a grade (*supports*, *partly supports* or *contradicts*), the shortest quote that shows
   it, and its own probability that the grade is right: the *certainty*. It is told to leave out excerpts that are
   only on the same topic and to use no outside knowledge. An excerpt about another group, place or period than the
   claim's is graded at most *partly supports* (`tasks.capped`). The 300 characters before an excerpt are shown only
   to resolve words such as "it" (`references.CONTEXT_CHARS`).
5. **The quote check.** Each quote is found in its excerpt after normalising typography, spacing and case, as whole
   words ("legal" is not found in "illegal"); a second pass allows only for spaces a PDF put inside words
   (`textutil.find_quote`). It must have at least three words or 15 characters and at most 600 characters. An answer
   that fails goes back to the model with its problems listed; after three failed attempts the check *did not work*
   (`tasks.MAX_ATTEMPTS`).
6. **Stepping up.** An answer whose lowest certainty is under 0.6, or a task rejected twice, goes once to a stronger
   model, whose judgements replace the first; both are kept (`routing.STEP_UP_BELOW`, `tasks.step_up`).
7. **People's judgements.** A person's judgement replaces the AI's in the answer and always counts
   (`verdicts.effective`); the AI's stays beside it in the downloads. In a shared project, the person's own judgement
   counts first, then the latest colleague's ([Each person's judgements](manual/together.md#each-persons-judgements)).
8. **Strictness.** An AI judgement counts only when its certainty is at least the strictness, 0.6 by default; weaker
   ones stay visible as *Not counted* ([How sure the AI must be](manual/check.md#how-sure-the-ai-must-be)). After 20
   of a person's judgements, ENLENS suggests the lowest strictness from which the person agreed with at least 80% of
   the AI's judgements (`check_exports.calibration`).

**One claim's answer** comes from the judgements that count (`verdicts.claim_status`): support and contradiction
together give *Mixed evidence*; otherwise support gives *Supported*, partial support *Partly supported* and
contradiction *Contradicted*. Judgements all below the strictness give *Only uncertain evidence*; none about the
claim gives *No evidence found*. Excerpts of documents no AI may read wait for the person and count once judged.

**A hypothesis in parts** (`verdicts.aggregate`): a part contradicted makes the whole contradicted; otherwise a part
with mixed evidence makes it mixed; every part supported makes it supported; some parts (partly) supported make it
partly supported. A part not known yet (failed or waiting) makes the whole at most *Partly supported*
([A hypothesis checked in parts](manual/check.md#a-hypothesis-checked-in-parts)).

**Who says what.** A document is on the supporting side if one of its counted excerpts supports, partly supporting if
none does, and contradicting if one contradicts; it can be on both sides. The *lean*, from −1 to +1, summarises the
excerpts read, a partial grade counting half (`verdicts.balance`). It is not a measure of truth.

**The assessment in words** is made by fixed rules, never by an AI (`assessment.py`): it quotes up to two of the
strongest excerpts per side, warns when one document carries most of the support (more than half of three or more
excerpts) or all of it comes from one year or one kind of document, lists what is not counted, and names the
person's judgement that changed the answer. Excerpts of documents kept from Claude are counted, never quoted
([The assessment in words](manual/review.md#the-assessment-in-words)).

**Second opinions** are a separate reading by another model, shown for comparison; they never change the answer
([Ask another AI model](manual/review.md#ask-another-ai-model)).

## Codes and labels

A codebook is a list of codes with descriptions: the 169 SDG targets come with ENLENS, and a researcher can make their
own as a CSV file, with optional columns for when to use a code, when not to, keywords and example quotes
(`frameworks.py`, `codebooks.py`; [Make your own codebook](manual/codebooks.md)). Labelling has two passes
(`profile.py`; [Codes](manual/explore.md#codes)):

1. **Keywords and meaning, no model.** Each code's text is indexed with BM25. A code is a candidate for a passage
   that has at least 20% of the code's words, weighted by inverse document frequency; at 60% it counts on keywords
   alone (`profile.KEYWORD_FLOOR`, `profile.PROVISIONAL`). The SDG codebook adds a lexicon of common phrasings. With
   embeddings, a code is also a candidate when a passage is more than two standard deviations closer to it than the
   code's mean over the corpus, and among the passage's five closest codes. Up to 8 candidates per passage go on.
2. **The AI pass (optional).** A model reads each passage, with the text before it, and its candidates (prompt
   `label-v1`). It says which codes apply, as the main topic or a mention, in which direction where the codebook has
   one, with a checked quote and a reason.

A person's decisions and own labels always win. When a codebook changes, labels follow renames and merges, and those
the AI made with an earlier wording are marked, so only those passages need labelling again (`codebooks.py`).

**Agreement** is measured with Cohen's kappa (Cohen, 1960): between two people who judged the same excerpts, once they
share 10 (`people.KAPPA_MIN`); when a sample is labelled again by another model (`profile.compare_sample`); between
routes (below); and in the acceptance measures against a person's reference sheets (`acceptance.py`).

## The glossary and concepts

The glossary is built without a model (`terms.py`; [Concepts](manual/explore.md#concepts)).

- **Candidates** are runs of one to four words that cross no punctuation and neither start nor end with a common word
  of the passage's language or a number. A candidate must occur at least 3 times in at least 2 documents.
- **Ranking** is by C-value (Frantzi, Ananiadou and Mima, 2000), which favours a whole term ("proton exchange
  membrane") over its nested parts: log2 of the word count plus one (so one-word terms can score), times the term's
  frequency less the mean frequency of the longer kept terms that contain it. The best 6,000 become terms.
- **Abbreviations** defined in the text are found by the Schwartz–Hearst rule (Schwartz and Hearst, 2003).
- **Possibly the same:** with an embedding model, terms that are each other's nearest neighbour at a cosine of at
  least 0.85 are proposed to the person.
- **Links found in the text** (English only) come from lexico-syntactic patterns of the kind Hearst (1992) described:
  "X such as Y", "Y and other X", "X, also called Y", "X leads to Y", "X instead of Y" (`textrelations.py`).
- **Concepts** are sets of terms joined by "same" links from a person, the abbreviation rule or the AI (optional). Every
  proposed link waits for a person.
- **Key terms** of a document are its terms ranked by TF-IDF with sublinear term frequency, (1 + ln tf) × idf (Salton
  and Buckley, 1988; `terms.key_terms`).
- **Paths between two concepts** run through accepted links and co-occurrence weighted by pointwise mutual information:
  a step costs 1 / (1 + PMI), and only concepts that share at least two passages with PMI above zero are joined
  (`conceptpaths.py`). The shortest path is found with Dijkstra's algorithm (1959) and the next ones with Yen's
  method (1971).

## Themes

Themes group passages by what they discuss, before any hypothesis (`themes.py`; [Themes](manual/explore.md#themes)).
The clustering is spherical k-means (cosine similarity; Dhillon and Modha, 2001) with a k-means++ start (Arthur and
Vassilvitskii, 2007) drawn from a fixed seed (0 by default), on the passages' embeddings when the project has them,
otherwise on TF-IDF vectors over the glossary's terms. k is 20 by default, at most 60 and at most a third of the
passages; exact repeats are left out first. Each theme is named without AI by its key terms (class-based TF-IDF)
and shown with the three passages nearest its centre. A model can add a name of at most six words and a one-sentence
description, each with a checked quote. A person can rename, merge, move or remove themes; the same passages,
settings and seed give the same themes.

## Theory documents

A researcher can mark a document as **theory**: the framework the research is read through, not evidence about the
field (`docrole.py`; [Theory documents](manual/explore.md#theory-documents)). ENLENS never marks one by itself. A
theory document is still read, searched and noted, but left out of the excerpts a check reads (unless a check is
limited to it by hand), codebook labels, themes, key terms, the glossary's counts, links found in the text and concept
paths. A codebook can start from a theory document, each code's definition quoted from it with its page and its
examples taken only from evidence documents (`theorycodes.py`).

## The AI's part and reproducibility

**Models per task.** Each kind of AI task has its own prompt with a version, an answer schema and a default model
(`taskkinds.py`, `prompts.py`). On Claude with a Pro plan: labels and concept links on Haiku; search words, parts,
theme names and references on Sonnet; judging excerpts on Sonnet, stepping up to Opus (or Fable when switched on);
second opinions on Opus. Other plans shift these, and a model chosen per task comes first (`routing.py`;
[The model of each kind of task](manual/models.md#the-model-of-each-kind-of-task)).

**Routes.** The same tasks can be answered by Claude Code on the researcher's plan, the Claude API, Claude in a chat
(the connector) or a model server on the computer (`routing.ROUTE_NAMES`). With Claude Code and a local model both
set, the *AI mix* gives some kinds of task to the local model first; its answer goes up to Claude when it is unsure
(under 0.6), fails the quote check three times, or judges an excerpt as contradicting (`routing.MIX_LOCAL_ROWS`,
`routing.judging_changes`; [The mix of local and Claude](manual/models.md#the-mix-of-local-and-claude)).

**What each answer records** (`tasks.ingest_result`): the model and, where the server gives it, its digest (the exact
weights); the prompt version; the seed and the settings that matter; the route and, for Claude Code, the helper;
whether a stronger model answered; the raw answer, whether it was accepted and why not; and the ENLENS version. Each
check, label and theme run records the ENLENS version too, and each document its reader (`runs.py`). Every Excel
download ends with *How these results were made* ([What every answer records](manual/models.md#what-every-answer-records)).

**Seeds.** Requests to a local model server use temperature 0 and a fixed seed, 42 by default (`llm.DEFAULT_SEED`);
*Settings → Technical → Repeatable results* tests whether the server gives the same answer twice. Claude takes no
seed: through Claude Code or the Claude API the same question may give a different answer. The acceptance runs
(`enlens acceptance queue … --again`) measure how much two readings differ.

**Kept answers.** An accepted answer is kept under a SHA-256 key of the kind of task, the prompt version, the model
and the whole prompt (`tasks.cache_key`). The same question asked again is answered from it, after its quotes are
checked against the new text. Unsure answers, second opinions, readings asked for again and tasks forced onto a
model are never kept or reused (`tasks.NO_CACHE_KINDS`, `tasks._unsure`).

**Agreement between routes.** The local model and Claude answer the same sample of tasks (10 to 100), and their
decisions are compared: the grade of each excerpt, whether each code applies, the relation of each pair of terms. The
result is the share of identical decisions and Cohen's kappa; from 0.8 the local model counts as good for that kind,
from 0.6 as fair (`benchmark.kappa`; [Agreement between routes](manual/models.md#agreement-between-routes)).

**The validation report.** `enlens measure` reports on reading documents, with no AI: documents of known text,
determinism, quotes that still find their place, and timings (`measure.py`). Each release carries it as
`validation-report.md`.

**Across versions.** ENLENS never redoes work by itself: results made by an earlier version stay as they were made
([Results across versions](manual/models.md#results-across-versions)).

## Limits

- **Certainty is the model's own estimate**, not a calibrated probability. The calibration in *Settings → Checking*
  shows how often the researcher agreed with the AI at each level.
- ***No evidence found* is about the excerpts read** (8 by default), not about the documents, which may use other
  words. *Read more excerpts* and *Search with other words* look further.
- **The quote check proves that the words are there**, not that the grade is right. The person's review checks the
  grade.
- **The default models are not yet validated** on a filled-in reference set ([MODEL_CHOICE.md](MODEL_CHOICE.md)).
- **Agreement is not correctness**: kappa compares two readers, neither of them a gold standard.
- **Claude's answers are not repeatable** the way a seeded local model's are.
- **The stemmer is English.** It strips English endings from words in every language, so forms in other languages may
  be merged wrongly or not at all. A multilingual embedding model (`bge-m3`) can bridge languages.
- **Reading has limits**: text inside pictures is not read, and scanned pages get no tables or figures.
- **Disagreement is left to the researcher**: ENLENS does not judge whether two excerpts that disagree concern another
  place, group or period, or how strong each source is.

## For a methods section

Adapt the paragraph below. Fill in the version, the routes and models used (from *How these results were made* in
the Excel download) and your own review procedure.

> Documents were analysed with ENLENS version [X.Y.Z], a local application that checks hypotheses against a document
> collection with verified quotations. Documents were converted to text by ENLENS's rule-based reader (reader [N]) and
> split into passages of up to about 1,100 characters. For each hypothesis, passages were retrieved with Okapi BM25
> (k1 = 1.5, b = 0.75; Robertson and Zaragoza, 2009) [, fused with embedding-based retrieval by reciprocal rank fusion
> (Cormack et al., 2009)], taking the best [8] with at most two per document. A language model ([model, route]) graded
> each passage as supporting, partly supporting or contradicting the hypothesis, with a quotation and a self-reported
> certainty; every quotation was verified automatically against the source text. Grades with a certainty below [0.6]
> were not counted. [All / A sample of N] grades were reviewed by [the author / two coders], whose judgements replaced
> the model's. Verdicts followed fixed rules (a hypothesis with any necessary part contradicted is contradicted).
> [Agreement between coders was measured with Cohen's kappa (Cohen, 1960).] Prompts, model versions and all raw model
> answers are kept with the project.

## References

- Arthur, D., and Vassilvitskii, S. (2007). k-means++: the advantages of careful seeding. *Proceedings of the 18th
  Annual ACM-SIAM Symposium on Discrete Algorithms*, 1027–1035.
- Church, K. W., and Hanks, P. (1990). Word association norms, mutual information, and lexicography. *Computational
  Linguistics*, 16(1), 22–29.
- Cohen, J. (1960). A coefficient of agreement for nominal scales. *Educational and Psychological Measurement*, 20(1),
  37–46.
- Cormack, G. V., Clarke, C. L. A., and Büttcher, S. (2009). Reciprocal rank fusion outperforms Condorcet and
  individual rank learning methods. *Proceedings of the 32nd International ACM SIGIR Conference*, 758–759.
- Dhillon, I. S., and Modha, D. S. (2001). Concept decompositions for large sparse text data using clustering.
  *Machine Learning*, 42(1–2), 143–175.
- Dijkstra, E. W. (1959). A note on two problems in connexion with graphs. *Numerische Mathematik*, 1, 269–271.
- Frantzi, K., Ananiadou, S., and Mima, H. (2000). Automatic recognition of multi-word terms: the C-value/NC-value
  method. *International Journal on Digital Libraries*, 3(2), 115–130.
- Hearst, M. A. (1992). Automatic acquisition of hyponyms from large text corpora. *Proceedings of COLING 1992*,
  539–545.
- Robertson, S., and Zaragoza, H. (2009). The probabilistic relevance framework: BM25 and beyond. *Foundations and
  Trends in Information Retrieval*, 3(4), 333–389.
- Salton, G., and Buckley, C. (1988). Term-weighting approaches in automatic text retrieval. *Information Processing
  and Management*, 24(5), 513–523.
- Schwartz, A. S., and Hearst, M. A. (2003). A simple algorithm for identifying abbreviation definitions in biomedical
  text. *Pacific Symposium on Biocomputing*, 8, 451–462.
- Yen, J. Y. (1971). Finding the k shortest loopless paths in a network. *Management Science*, 17(11), 712–716.

The optional SDG pack has methods of its own, including the interaction scores of Nilsson, Griggs and Visbeck (2016):
see [The SDG pack](manual/sdg-pack.md).
