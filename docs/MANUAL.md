# ENLENS claims: usage manual

ENLENS claims turns a set of source documents into **impact claims**: statements that an activity in a value chain
affects a UN SDG target, in a direction, in a segment of the chain, at a place and time, under a condition. Every
claim carries the exact words from the source that support it, with page and character positions. The claims are
then compared with an expert Value Chain Assessment (VCA) and summarised into a report.

The first application is the green hydrogen VCA by Peyerl and van der Zwaan (2024, *Discover Sustainability* 5:199).
The pipeline asks five questions of the literature:

1. Does the cited literature support the VCA's judgements? (Each justification is split into claims and checked.)
2. Which SDG targets does green hydrogen affect, in which direction and in which segment?
3. Where do synergies and trade-offs between targets appear?
4. When do the effects occur, and where do they land (producer or importer, which countries)?
5. Under which conditions do effects change, and which policy levers are named?

It also measures how well evidence extracted from the sources rebuilds the VCA's own labels, so you can judge
whether the method is good enough to extend the VCA to other value chains.

For checking single claims there is a **claim checker** with a graphical interface (section 3): type a claim, add
sources, and see which passages support it, with the quote highlighted. It works with the Claude API or with a model
running on your own computer through Ollama.

---

## 1. Install

Python 3.10 or newer.

```bash
pip install -e .                 # core: pydantic, pypdf, openpyxl
pip install -e '.[anthropic]'    # to call the Claude API
pip install -e '.[gui]'          # the claim checker: Streamlit and the Claude API client
pip install -e '.[dev]'          # pytest
```

Check the install with the tests (about 3 seconds, no network):

```bash
pytest
```

The command is `enlens` (or `python -m enlens_claims`). Every command takes `--ws FOLDER`, the workspace; the
default is `./workspace`.

---

## 2. Concepts

| Term | Meaning |
| --- | --- |
| Workspace | A folder with `config.json`, `enlens.sqlite` and subfolders `tasks/`, `results/`, `report/`. Everything about a run lives here. |
| Document | One source file (PDF, HTML, TXT or MD). Its text is stored once; every offset in the system points into it. |
| Passage | A run of whole sentences (up to about 1,100 characters) inside a document, with its page. Passages are the unit the model reads. Passages in the reference list are marked and skipped. |
| VCA target | One row of the VCA table: the cell for each segment (direct or indirect, positive or negative), the time horizon, the justification and the cited references. |
| VCA claim | One atomic statement split out of a justification, with its quote from the justification. |
| Impact claim | What the model extracts from a passage: activity, segment, SDG targets with direction and direct/indirect influence, place, countries, side (producer or importer), horizon, condition, policy lever, confidence, and evidence quotes. |
| Task | One model call waiting to be answered: `split` (justification to VCA claims), `extract` (passage to impact claims), `verify_set` (which of up to six passages from the cited sources support a VCA claim, fully or partly?), `verify` (does one passage support one claim? used for second checks of extracted claims), and for the claim checker `expand` (search terms for a claim) and `check` (grade passages against a typed claim). |
| Status of a claim | `auto` (accepted automatically), `needs_review`, `accepted`, `changed`, `rejected`. |

### Vocabularies

- Segments: `production`, `transportation`, `end_use`, plus `whole_chain` and `unclear`.
- Direction: `positive` (helps progress on the target), `negative` (hinders it), `mixed`, `no_effect`.
- Influence: `direct`, `indirect`, `unclear` (VCA definitions).
- Horizon: `short_term` (to 2030), `medium_long_term` (after 2030), `not_stated`.
- Interaction scores between targets: Nilsson et al. (2016) scale from −3 (cancelling) to +3 (indivisible).
- Targets: all 169 SDG targets, including lettered ones such as `7.b` and SDG 17 (`src/enlens_claims/data/sdg_targets.csv`).

---

## 3. The claim checker (graphical interface)

Type a claim, add sources, and see which passages support it, partly support it or contradict it, with the quote
highlighted in the passage.

### Start it

```bash
pip install -e '.[gui]'
enlens-gui                 # opens http://localhost:8501 in your browser
```

Options: `--home FOLDER` (where projects, history and settings live; default `~/enlens`), `--port 8600`, `--headless`
(do not open a browser). The app listens on this computer only. Stop it with Ctrl+C in the terminal.

### First use

1. **Settings → Model service.** Choose one:
   - **Claude API.** Paste an API key from console.anthropic.com and press *Test connection*. The key is kept for the
     session, or saved on this computer (readable by your user only) if you tick *Remember*. An `ANTHROPIC_API_KEY`
     environment variable is picked up too. The model is `claude-opus-5-5` unless you change it.
   - **Ollama.** Install Ollama (ollama.com), download a model (`ollama pull <model>`), then pick it from the list and
     press *Test connection*. It reports the model's size and the context it was trained for. Keep the context length at
     16,384 or more: Ollama's own default is much smaller and cuts long prompts without warning. See section 7 for
     choosing a model.
   - **Offline demo.** Grades by word overlap, without a model. For trying the app only.
2. **Sidebar → New project.** One project per set of sources.
3. **Sources.** Upload a zip, or PDF, HTML, text or Markdown files, and press *Add*. A `manifest.csv` inside the zip
   (columns `file`, `reference`, `doi`) names the work each file is. The *Check* column flags documents with an
   unreadable text layer and very short files (often a landing page instead of the report). Files already in the
   project are skipped.
4. **Check a claim.** Write the claim as one sentence. Optionally choose the SDG target it is about; targets marked ★
   are suggested from the claim's wording. Press *Check claim*.

### What a check does

1. The model writes search terms for the claim (synonyms, technical words, the opposite phrasing). One short call;
   switch it off under *Options*.
2. The passages that match the claim and its terms best are picked: 8 by default, at most 2 from one document first,
   so one long report cannot fill every slot.
3. The model reads them together and grades each one that bears on the claim: *supports*, *partly supports* (a
   necessary part of the claim is stated; one inference remains) or *refutes*, with a quote and a confidence. Every
   quote is checked against the passage; an answer that fails is retried with the problems listed, up to three times.

The result shows a status, the model's one-line summary, the evidence with the quote highlighted, the passages read
that held nothing relevant, and the search terms. Download it as CSV or JSON.

| Status | Meaning |
| --- | --- |
| Stated by a source | At least one passage states the claim (grade *supports* at or above the confidence threshold). |
| Partly stated by a source | No passage states it all, but one states a necessary part. |
| Contradicted by a source | A passage states the opposite, and none supports it. |
| Nothing found in the passages read | No passage read bears on the claim. This is not proof that no source says it: read more passages, restrict the documents, or reword the claim. |

*Options* on the check page: passages to read (4 to 12), at most per document, search terms on or off, the confidence
from which grades count, and a list to check against chosen documents only.

**History** lists every check in the project with its status. Select a row to see its evidence, delete it, or download
all checks as one CSV.

**The pilot's sources.** *Sources → Use an existing workspace as a project* links a workspace folder without copying it.
Give it the `pilot` folder from this package to check claims against the 38 pilot documents.

**Cost and time.** With the Claude API one check is two calls of a few thousand tokens. With Ollama it depends on the
model and the computer, from seconds to several minutes.

**Privacy.** With the Claude API the claim and the passages read are sent to Anthropic. With Ollama nothing leaves the
computer. Projects, history and settings stay in the home folder.

The same check from the command line:

```bash
enlens --ws myproject check "Green hydrogen production increases water stress in arid regions." --target 6.4
enlens --ws myproject check "..." --backend ollama --model qwen3:8b
```

---

## 4. Quick start with the offline baseline

The `baseline` backend is a keyword heuristic with the same output format as the models. It needs no key and no
network, so it is the fastest way to see the whole pipeline work. Its results are a floor, not findings.

```bash
enlens --ws demo init
enlens --ws demo load-vca path/to/43621_2024_374_MOESM1_ESM.xlsx
enlens --ws demo ingest path/to/sources.zip          # folders and zips are searched
enlens --ws demo match-sources
enlens --ws demo screen
enlens --ws demo make-tasks split
enlens --ws demo run split --backend baseline
enlens --ws demo make-tasks verify-vca
enlens --ws demo run verify_set --backend baseline
enlens --ws demo make-tasks extract
enlens --ws demo run extract --backend baseline
enlens --ws demo report                               # demo/report/report.html
```

---

## 5. The full workflow

### Step 1. Load the VCA

```bash
enlens --ws pilot init
enlens --ws pilot load-vca 43621_2024_374_MOESM1_ESM.xlsx
```

The loader reads sheet "(T3) SDGs & Targets - Analyses". The influence cells in that sheet are empty; the sign is the
cell colour (red negative, green positive, bold colour direct, light colour indirect). The command prints totals.
For the published workbook they must read 169 targets, 61 justified, 30 direct, 119 indirect, 86 positive,
63 negative, 47 short term and 14 medium to long term, as in the paper. If they do not, the colours were not read
correctly; see Troubleshooting.

### Step 2. Add sources

```bash
enlens --ws pilot ingest uploads/sources.zip more_reports/
enlens --ws pilot match-sources
enlens --ws pilot coverage
```

- Any file names work. Files are matched to the VCA references by DOI (from the file name, metadata or first pages)
  or by the words of the reference (title, organisation, year).
- `coverage` lists, for each justified target, how many of its cited sources are available. Targets with none are
  reported as "source missing" everywhere, never as unsupported, and are left out of the agreement scores.
- A `manifest.csv` next to the files (columns `file`, `reference`, `doi`; more columns are ignored) says exactly
  which reference each file is. Several rows may point at one file when the same work is cited in different ways;
  every row is linked. Manifest links take precedence over DOI and title matching.
- The VCA's reference lists contain a few errors (cut-off or wrong DOIs, the same work cited twice). The loader
  applies `src/enlens_claims/data/reference_fixes.csv` (actions `doi` and `same_as`) and then merges references
  whose title words overlap strongly. `load-vca` reports how many were fixed and merged. Add rows to that file when
  you find more.
- Duplicate files (same bytes) are skipped. Scanned PDFs without a text layer come out empty; run OCR first.
- Notes that travel with a corpus (`problems.txt`, `README.md`, `notes.txt`) are not ingested. When a manifest is
  present, `ingest` lists files it does not mention under `not_in_manifest`, so you can see what was added unlinked.
- `--exclude PATTERN` leaves out files by name, for example a download that turned out to be the wrong document:
  `enlens --ws pilot ingest enlens_text.zip --exclude 'A_18_*'`. Repeat it for several patterns.
- Text layers without a character map come out as `(cid:53)` codes or as shifted letters and control characters
  (`5HQHZDEOH DQG` for `Renewable and`). Such passages get section `unreadable` and are never sent to a model.
  `ingest` lists documents that are mostly unreadable, and they do not count as available sources in `coverage`.
  Get another copy of the file (the publisher's version often has a proper text layer) or run OCR.
- `coverage` and the report's Sources table flag very short documents: a web landing page or an event agenda saved
  instead of the report itself still matches the reference, but holds no evidence.

**Large PDF folders.** `tools/pdf_to_text.py` turns a folder of PDFs into small text files, one form-feed character
between pages, so page numbers survive. It copies HTML files and `manifest.csv` and writes `enlens_text.zip` next
to the folder, which `ingest` reads like the PDFs. It needs only `pypdf`:

```bash
pip install pypdf
python3 tools/pdf_to_text.py path/to/sources path/to/manifest.csv
```

**Adding sources later.** Ingest the new files into the same workspace, then run `match-sources`, `screen` and the
`make-tasks` commands again. Task ids are fixed by their content, so only new work is created: passages that now rank
among the top N for a target, and VCA claims whose best passages changed (they get a further task for the new set;
earlier answers are kept and counted together). Nothing already answered is asked again.

**Starting over with another copy of the corpus.** `enlens --ws pilot reset-corpus --yes` removes documents and
everything derived from them (passages, claims, verifications and their tasks) but keeps the VCA and its split
claims, so the split does not have to be paid for again.

### Step 3. Screen passages

```bash
enlens --ws pilot screen
```

A transparent heuristic marks passages that mention hydrogen (or its derivatives) and impact terms, and score
against the SDG target texts. Only screened passages go to extraction unless you pass `--all-passages`. This step
stands in for a fast decision model; see section 7 for replacing it. Lower `thresholds.screen_min_score` in
`config.json` (default 2.0) to let more passages through.

### Step 4. Create model tasks

```bash
enlens --ws pilot make-tasks split                    # 61 justifications to VCA claims
enlens --ws pilot make-tasks extract --per-target 6   # the 6 best passages for each of the 169 targets
```

Extracting every screened passage of a large corpus is expensive (the pilot corpus has 7,600). `--per-target N`
ranks passages against each SDG target's text and keeps the top N per target, so every target, not only the VCA's,
gets the same chance. Only passages that name hydrogen or a derivative (or whose preceding passage does, which the
task shows as context) are ranked; without that rule, general energy passages crowd out the value chain. Pass
`--any-passage` to drop it, or leave out `--per-target` to extract every screened passage.

After the split tasks have answers:

```bash
enlens --ws pilot make-tasks verify-vca --k 6    # one task per VCA claim, with its 6 best passages from cited sources
```

Each `verify_set` task shows one VCA claim and up to `--k` passages (default `thresholds.verify_top_k`), at most
`--per-doc` (default 2) from one document before the rest are filled by score, so one long report cannot crowd out
the others. The model grades only the passages that bear on the claim: `supports`, `partially_supports` (a
necessary part of the claim is stated and one inference remains: the mechanism without its effect on the target,
the converse case, or the same effect for another segment or for renewables in general) or `refutes`. Passages it
leaves out count as not enough information.

`--pairwise` makes the older design instead: one `verify` task per claim and passage, with three verdicts. In the
pilot, 72 of 75 pairwise checks found no support, often because the passage stated part of the claim; set-wise
checks with a partial grade read the same text and say more.

Other options: `--model` records a different model on the tasks; `--limit N` creates only N tasks (useful for a
trial); `--beyond-cited` searches all documents, not only those the VCA cites.

Second opinions with another model:

```bash
enlens --ws pilot make-tasks audit-vca --sample 0.1 --model claude-fable-5-1      # 10% of answered VCA checks
enlens --ws pilot make-tasks verify-claims --sample 0.1 --model claude-fable-5-1  # 10% of extracted claims
```

Audit answers to VCA checks are stored apart (`subject_kind` `vca_claim_audit`) and never change a claim's status;
`evaluate` and the report compare them with the first answers.

### Step 5. Answer the tasks

Three ways, which can be mixed per task kind:

**a) Claude API**

```bash
export ANTHROPIC_API_KEY=...
enlens --ws pilot run split
enlens --ws pilot run extract
enlens --ws pilot run verify_set
```

**b) A model in Ollama** (text stays on your machine):

```bash
ollama pull qwen3:8b                                        # once
enlens backend-check --backend ollama --model qwen3:8b      # is it running, is the model there?
enlens --ws pilot run verify_set --backend ollama --model qwen3:8b
```

The context length is set on every request (`--num-ctx`, default 16,384), and the answer is forced into the task's
JSON format. `--think off` switches off the reasoning of thinking models, which is faster. Other OpenAI-compatible
servers (llama.cpp, LM Studio, vLLM) work with `--backend local --url http://localhost:8080/v1`; set the context length
on the server, because that endpoint cannot pass it.

Local models are cheaper and private but weaker. Test them before trusting them (section 7).

**c) File queue** (any worker, including Claude in a chat or an agent):

```bash
enlens --ws pilot export-tasks extract --batch-size 25
# the worker reads tasks/extract/SYSTEM.md and WORKER_GUIDE.md, answers each line of tasks/extract/batch_*.jsonl,
# and writes results/extract/batch_*.jsonl lines: {"task_id": ..., "model": ..., "output": {...}}
enlens --ws pilot check-results pilot/results/extract/batch_0001.jsonl   # the worker checks its own file
enlens --ws pilot import-results pilot/results/extract
enlens --ws pilot requeue extract       # put exported tasks that got no answer back in the queue
```

`check-results` applies every check the import applies (schema, quotes, passage numbers) without storing anything,
and lists the problems per line, so a worker can fix its file before handing it back. The worker guide asks workers
to judge every task themselves and use code only to write and check JSON.

Running several workers at once (the pilot ran up to 15 Claude agents in parallel): give each worker its own batch
file, its own results file and its own folder for helper scripts. In the pilot, two workers that shared a scratch
folder overwrote each other's helper scripts and one wrote lines into the other's results file. Before importing,
check that every results file holds exactly the task ids of its batch.

Whatever the route, every answer is validated before it is stored:

- The JSON must match the schema; loose spellings ("end-use", "SDG 6.4") are normalised.
- Every quote must be found in the text the model was given. Matching ignores case, typographic quotes and dashes,
  ligatures and whitespace (PDF text often splits words), but nothing else: a paraphrase or an added number fails.
- A claim whose main quote is not found is dropped. A task with no usable answer is retried, with the problems
  listed in the next prompt, up to three attempts.
- Claims with confidence below `thresholds.accept_confidence` (default 0.8) get status `needs_review`.

Check progress at any time:

```bash
enlens --ws pilot status
```

### Step 6. Review

```bash
enlens --ws pilot review-export queue.csv --audit 0.05
```

The CSV holds claims that need review, a random 5% audit sample of auto-accepted claims, and VCA claims found
unsupported or contradicted. Fill in `decision` with `accept`, `change` or `reject`. For `change`, give any of:

- `corrected_targets`: `6.4:negative:direct; 2.4:negative:indirect`
- `corrected_segment`: one of the segment values
- `corrected_horizon`: one of the horizon values

```bash
enlens --ws pilot review-import queue.csv --reviewer "initials"
enlens --ws pilot gold-export gold.jsonl
```

Rows with an invalid correction are reported and change nothing. Reviewed items do not reappear in later queues.
`gold.jsonl` is the growing gold set: use it to compare prompts, models and thresholds.

### Step 7. Evaluate and report

```bash
enlens --ws pilot evaluate             # metrics as JSON
enlens --ws pilot report               # pilot/report/report.html plus CSVs
enlens --ws pilot report --strict      # only auto-accepted and reviewed claims
```

---

## 6. Reading the report

The report has one section per question. Every number traces to `claims.csv`, which holds each claim with its quote,
source and page.

**1. Does the cited literature support the VCA's judgements?** Status per VCA claim:

| Status | Meaning |
| --- | --- |
| supported | At least one passage from a cited source states the effect (grade supports, confidence at least `support_confidence`, default 0.6). |
| partially_supported | No passage states the whole effect, but one states a necessary part of it, so one inference step remains. |
| contradicted | A passage states the opposite and none supports it, fully or partly. |
| unsupported | Sources were available and checked, but no passage states the effect. The judgement may rest on reasoning beyond the sources, or retrieval missed the passage. |
| source_missing | None of the cited sources was provided, or the ones provided are unreadable. |
| not_checked | Verification tasks have not been answered yet. |

A second table shows the same statuses at other confidence thresholds. Partial grades usually carry lower
confidence than full support, so the share of partially supported claims depends strongly on the threshold; read
the whole table rather than one row.

**Do the VCA's texts and colours agree?** Each VCA claim with a clear direction is compared with the colour of the
VCA's own cell for its segment. Claims that point the other way are listed for the authors. Many are mitigations
inside the justification of a negative cell ("local manufacturing reduces the risk"), some are real mismatches.

**Can the method rebuild the VCA labels?** Claims extracted independently are aggregated per target and segment and
compared with the VCA:

- *Target has an effect*: over all 169 targets, so the targets the VCA leaves empty are the negatives. Precision
  (share of targets the evidence marks that the VCA also marks), recall (share of VCA targets the evidence finds),
  F1 and Cohen's κ (agreement beyond chance).
- *Cell*: the same per target × segment, within the justified targets that have a source available.
- *Sign*, *direct or indirect*, *time horizon*: agreement where both mark something.

Low recall with high precision usually means the sources were incomplete or the screen was too strict. Disagreement
on sign is the most informative: read those claims in `claims.csv`.

**2. Effects.** One row per target, one column per segment: sign and the number of documents. The sign is positive or
negative when one side has at least twice the documents of the other, otherwise mixed.

**3. Synergies and trade-offs.** *Stated* interactions are those a passage states, scored on the Nilsson scale.
*Inferred* pairs come from one document linking the same activity, segment and place to two targets: synergy (both
helped), trade-off (one helped, one hindered), shared pressure (both hindered). Inferred pairs are candidates for
expert scoring, not findings. The report lists only pairs found in two or more documents, because one long
document (in the pilot, a paper that maps hydrogen to many SDGs) can link dozens of targets; all pairs are in
`interactions.csv`.

**4–6. Timing, geography, conditions.** Claims by horizon and direction; countries named and whether effects land
with producers or importers; the conditions and policy levers that change an effect.

**7. Gaps.** Target and segment cells the VCA leaves empty but two or more documents mark, and targets with no sources.

**Sources.** Every document with its pages, passages, number of claims and the VCA targets that cite it, with checks
for unreadable or very short files.

**Method notes.** How the evidence was produced, and the agreement between the first answers and the second-model
audits.

---

## 7. Models and configuration

`config.json` in the workspace:

```json
{
  "models": {"screen": "heuristic", "split": "claude-fable-5-1", "extract": "claude-opus-5-5", "verify": "claude-opus-5-5"},
  "thresholds": {"screen_min_score": 2.0, "accept_confidence": 0.8, "support_confidence": 0.6, "verify_top_k": 6},
  "passages": {"max_chars": 1100, "min_chars": 200}
}
```

Suggested split, following Anthropic's guidance that Opus 5.5 is the default and Fable 5.1 is for work where Opus
falls short: Opus 5.5 for the high-volume extraction and verification; Fable 5.1 for the 61 justification splits,
for resolving conflicts, and for a second check on a sample (`make-tasks verify-claims --sample 0.1 --model
claude-fable-5-1`), which measures whether the more expensive model changes outcomes. A cheaper model (Haiku 5.5)
or a dedicated classifier can replace the screen once it is benchmarked on reviewed passages.

Every stored result records the model and the prompt version (`extract-v1`, `split-v2`, `verify-v1`,
`verify-set-v1`). When you change
a prompt in `prompts.py`, bump its version so old and new results stay distinguishable, then queue the affected tasks
again with `enlens refresh KIND` (add `--model` to switch model at the same time). Earlier answers stay in the
`results` table.

### Choosing and testing a local model

What this pipeline asks of a model is harder than chat: quotes copied word for word, a 10,000-token extraction prompt
(it lists all 169 targets), fine judgement between "partly supports" and "same topic", and answers in a fixed JSON
format. Ollama enforces the format, so even small models give valid JSON; the rest depends on the model.

Rough guide by memory (October 2026; check Ollama's library for current models): about 16 GB runs models of 8 to
12 billion parameters, 32 GB runs 27 to 32 billion, 64 GB or more runs the largest. Larger models judge better and are
slower. If memory allows, an 8-bit version copies quotes more reliably than the usual 4-bit one.

Test a model on your own computer before using it:

```bash
enlens --ws pilot benchmark --backend ollama --model qwen3:8b --sample 30
```

or *Settings → Test a model* in the claim checker. It runs the model on tasks the pilot already answered with Claude
Opus 5.5 and reports, per task kind: the share of usable answers, of answers with a quote not in the text, agreement
with the reference (same status, and Cohen's κ beyond chance), and seconds per task. Nothing is stored. The verdict
line uses rules of thumb: at least 90% usable and κ 0.6 is "good enough to use, with review"; at least 75% and κ 0.4
is "usable for a first pass". Agreement with Opus is not correctness, but a model that disagrees with it often will
also disagree with your reviewers.

Confidences are the model's own estimates. They are not calibrated until you compare them with reviewer decisions:
after a few hundred reviews, check what share of claims at each confidence level were accepted, and set
`accept_confidence` from that.

---

## 8. Database tables

| Table | Holds |
| --- | --- |
| documents, pages, passages | Source text, page spans, passages with `section` (body, references, reference_like, unreadable) and screen score |
| vca_targets, vca_refs, doc_refs | Gold labels, cited references, and which document matched which reference (method doi or title) |
| tasks, results | Every task, its payload and status; every answer with model, prompt version, validity and errors |
| claims, claim_targets, evidence | Extracted claims, their targets with direction and influence, and quotes with offsets and page |
| interactions | Stated interactions (with quote) and inferred candidate pairs |
| vca_claims, verifications | Split justifications; one row per checked passage with its grade and quote. `subject_kind` is `vca_claim`, `vca_claim_audit` (second opinion) or `claim` (second check of an extracted claim) |
| reviews | Reviewer decisions and corrections |
| user_claims | Claims typed into the claim checker, with their search terms, the model's summary and the options used; their grades are in `verifications` with `subject_kind` `user_claim` |

Open it with any SQLite tool. Offsets in `evidence` and `verifications` index into `documents.text`.

---

## 9. Using it for other value chains or policy documents

- **Another value chain**: you need the screen terms (`H2_RE` in `retrieve.py`), the segment definitions (`prompts.py`)
  and, for evaluation, an expert table in the same layout, or reviewed claims as gold.
- **Policy documents**: ingest them like any source. Policy levers and conditions are extracted from them as from papers.
  For a policy layer, run `make-tasks extract --docs <ids>` on those documents only and read section 6 of the report.
- **The Netherlands angle**: no VCA justification mentions the Netherlands; Dutch and EU policy documents and national
  studies have to be added as sources first.

---

## 10. Limits

- Claims are model output until reviewed. The quote check proves the quoted words exist; it does not prove the fields
  follow from them.
- The corpus is what you provide. Paywalled sources you cannot or will not process leave targets as "source missing".
- Text comes from the PDF text layer. Tables and figures are read as text, which is often garbled; scanned pages need OCR.
- The screen is a heuristic. Measure its recall on reviewed passages before relying on it for a new topic.
- Inferred interactions are co-occurrence within a document, not causal statements.
- Verification reads only the top `--k` passages per claim. In the pilot, a manual search of the full cited documents
  for 10 claims with no graded passage found partial support for 2 and a weak contradiction for 1; the other 7 had
  nothing anywhere in their sources. Retrieval misses some evidence, mostly where the source uses other words
  ("repurposing" for "upgrading").
- Model confidences in the pilot were low (extraction mean 0.46), so with the default `accept_confidence` of 0.8
  every claim went to review. Calibrate the threshold against reviewer decisions before using the auto status.

## 11. Copyright and privacy

Processing a document with an outside model service sends its text to that service. For paywalled literature, check
with your library whether your licences allow text and data mining with such a service, or use the local backend so
the text stays on your machine.

## 12. Troubleshooting

| Problem | Fix |
| --- | --- |
| `load-vca` totals differ from the paper | The workbook layout or colours changed. Check `_fill_sign` in `vca.py`; theme colour 9 is read as green. |
| A document did not match its reference | Put the DOI in the file name (`10.1016_j.ijhydene.2022.11.024.pdf`), or check `doc_refs` and add it by SQL. |
| Many quotes fail | Look at `results.errors_json`. Usually the model tidied PDF text; the retry prompt tells it to copy exactly. |
| Tasks stuck as `exported` | `enlens requeue KIND`. |
| `Set ANTHROPIC_API_KEY` | Export the key, or use the file queue or the local backend. |
| Empty document | No text layer (scanned). Run OCR, for example `ocrmypdf in.pdf out.pdf`, then ingest again. |
| A document is listed under `mostly_unreadable` | The PDF's fonts have no character map. Get another copy (often the publisher's) or OCR it, `reset-corpus` or ingest the new copy, and run `match-sources` again. |
| A source is flagged "very short" | It is probably a landing page or an agenda, not the cited work. Replace it, or leave it out with `--exclude`. |
| The claim checker says it cannot reach Ollama | Start the Ollama app (or `ollama serve`) and check the address in Settings (default `http://localhost:11434`). |
| "Ollama has no model ..." | Download it: `ollama pull <model>`, then pick it again in Settings. |
| Test connection warns about Ollama's cloud | The model runs on Ollama's servers, which do not support the JSON format the app needs, and the text leaves your computer. Pick a model downloaded with `ollama pull`. |
| "This task needs about N tokens of context" | Raise the context length in Settings or with `--num-ctx`. 16,384 covers every task. |
| A check with Ollama takes very long | The model is too large for the computer's memory, or it is thinking at length: try a smaller model or set reasoning to off. |
| "The Claude API rejected the key" | Copy the key again from console.anthropic.com; check it has credit. |
| Two workers' answers ended up in one results file | Give each worker its own scratch folder. Move the stray lines to the right file; `import-results` accepts any order. |
