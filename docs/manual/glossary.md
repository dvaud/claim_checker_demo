[Manual](../MANUAL.md) › Glossary

# Words used in ENLENS

The app speaks plain language; the command line, the API and the code use technical names. Both are listed here.

| In the app | Technical name | Meaning |
| --- | --- | --- |
| **Project** | Project, workspace | A folder with `config.json` and `enlens.sqlite`. The app keeps its projects in `~/enlens/projects` (or `ENLENS_HOME`); the command line works on any folder given with `--ws`. Both use the same format. |
| **Document** | Document | One source file (PDF, Word .docx, HTML, TXT or MD; zips are opened). Its text is stored once, and every place in it points into that text. Its paragraphs and headings are kept, so a quote can be cited as "paragraph 6 of 8" (text and web pages) or "page 2, paragraph 3" (PDFs). Scanned pages can be read by text recognition (OCR). |
| **Theory document** | Document role `theory` | A document marked as the framework the research is read through (0.18.1). It is still read, searched and noted, but left out of themes, codebook labels, the excerpts a check reads and key terms. You mark it; ENLENS never guesses ([Theory documents](explore.md#theory-documents)). In the code, never *framework*: that word means a codebook. |
| **Excerpt**, **passage** | Passage | A paragraph of a document (long ones cut, short ones put together; up to about 1,100 characters, some 180 words). Excerpts are what the AI reads. Reference lists, page furniture and unreadable text are left out ([How documents are read](reading.md)). |
| **Hypothesis** | Hypothesis | What you check. Checked as written, or split into 2 to 5 *parts* that must all hold, each checked on its own. |
| **Part** | Claim | One statement that is checked: the hypothesis itself, or one of its parts. |
| **Judgement** | Grade, verdict | What the AI says about one excerpt: *supports*, *partly supports* (an important part is stated; something remains to be inferred), *contradicts* (`refutes`), or *not about this hypothesis*. With a quote and a certainty. |
| **Your judgement** | User verdict | Your own judgement of an excerpt. It replaces the AI's in the answer and the counts, always counts, and is kept next to the AI's. Agreeing with the AI is a review; choosing another judgement is a change. You can point to the sentence you mean. |
| **Answer** | Status | What the documents say about the whole hypothesis: *supported*, *partly supported*, *mixed evidence* (`contested`), *contradicted*, and the rest ([The answers](check.md#the-answers)). |
| **AI certainty** | Confidence | The AI's own estimate (0–100%) of how sure it is: high (≥ 80%), medium (≥ 60%), low. Not a check of whether it is right. |
| **Strictness** | Threshold | How sure the AI must be for a judgement to count (default 60%). Weaker judgements stay visible, marked *Not counted*. It applies to every result, old and new. |
| **Search** (in a check) | Round | One set of excerpts read for a part. *Read more excerpts* and *Search with other words* add searches. |
| **Search by meaning** | Semantic index | Optional: a vector per excerpt from a local embedding model, so excerpts are found by meaning as well as by shared words. |
| **About another group** | Scope note | The AI's note that an excerpt is about another group, setting, place or period than the hypothesis names ("about fully remote workers, not hybrid"). Such an excerpt supports the hypothesis at most partly. |
| **Second opinion** | Model for second opinions | Another model that reads the same excerpts on its own, to show where it differs. Its judgements never change an answer. |
| **Stronger model** | Model routing (*Steps up to*) | The model a check steps up to: it reads the excerpts again and its judgements replace the first ones; the answer shows what it was at first. |
| **The auditor** | Auditor | The model for second opinions and hard cases on Claude: Opus, or Fable when switched on. |
| **Codebook** | Framework | An optional list of codes (like codes in NVivo or Atlas.ti). The 169 SDG targets ship with ENLENS; make your own ([Make your own codebook](codebooks.md)). The AI sees each code's text. |
| **Code**, **label** | Code, label | One entry of a codebook; a label says that a passage addresses it. |
| **Words it is matched by** | Keywords | The words of a code, besides its definition, that the keyword pass looks for ([Make your own codebook](codebooks.md)). |
| **Removed codes** | Removed codes | Codes taken out of a codebook. The labels made with them wait, are not counted, and count again when the code is brought back ([What happens to labels](codebooks.md#what-happens-to-labels)). |
| **Highlight**, **note** | Note | Words of a document that you marked, with your own words about them (none, for a plain highlight) and one of four colours. A note can be used as evidence in a check ([Notes, the research log and earlier versions](notes-and-log.md#highlights-and-notes)). |
| **Research log** | Research log | The dated record of what was decided in a project: entries ENLENS writes by itself, and your own ([The research log](notes-and-log.md#the-research-log)). |
| **Version**, **History** | Version | The state of a set of themes, your judgements in a check, or a codebook, kept before each change, to compare with now and restore. Each copy of a project keeps its own ([Earlier versions](notes-and-log.md#earlier-versions)). |
| **Reader** | Reader | The part of ENLENS that turns a file into text and passages. Every document records which reader read it. |
| **Who may read with AI** | `ai_access` | A document's setting: *Claude may read it* (`cloud`), *Only a local AI* (`local`), *No AI* (`none`) ([Privacy](privacy.md#who-may-read-each-document-with-ai)). |
| **Sync clash** | Sync clash | Two versions of the same thing, after you and a colleague both changed it; both are kept ([Work together](together.md#a-sync-clash)). |
| **The queue** | Task queue | The AI work ENLENS has prepared for Claude Code, answered by helpers ([Claude Code](claude-code.md)). |
