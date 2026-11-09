[Manual](../MANUAL.md) › A model on your own computer

# A model on your own computer

> **In short**
> - No Claude plan, or documents that must stay on your computer? A model served on your own computer keeps every
>   word on it.
> - Choose *A model on this computer*: ENLENS installs Ollama and then downloads a model, each with one button.
> - Local models are private and free but weaker: test one before you trust it.

## Getting one

Choose *A model on this computer* (on the first screen or in *Settings → AI*). Without a model server, the step
offers **Ollama**, a free program that runs AI models on your computer:

- *Install Ollama* first says how big the download is on your computer (in November 2026 about **1.7 GB on Windows**
  and **230 MB on a Mac**) and how much free disk space it needs (about four times that), before anything is
  downloaded. Then ENLENS downloads Ollama's own installer from ollama.com, checks that it is signed by Ollama, installs
  it (Windows: in your user folder, no administrator rights; Mac: in *Applications*) and starts it, with a progress
  bar and *Stop*. On Linux, Ollama's installer asks for your password, so ENLENS opens a terminal window running it.
- Ollama already on the computer but not running: *Start Ollama*.
- Rather do it yourself? *Download Ollama's installer* gets the file itself (ollama.com's own download page now leads
  with a line to type in a terminal).

Then ENLENS downloads a model with one button: *Download qwen3:8b* (about 5 GB), and if you like *nomic-embed-text*
for search by meaning ([First steps](first-steps.md#1-the-ai)). None of your documents are sent. **LM Studio**, **llama.cpp**, **Jan** and **vLLM** work too, as
OpenAI-compatible servers: in [LM Studio](https://lmstudio.ai), *Developer → Start server* with a model loaded.

In a terminal instead:

```bash
ollama pull qwen3:8b             # a local chat model
ollama pull nomic-embed-text     # optional: search by meaning (English)
ollama pull bge-m3               # or this one for many languages: an English hypothesis also finds Dutch or French passages
```

Two other ways to use a local model:

- **Only for some documents**: mark them *Only a local AI*, and choose the model in *Settings → AI → Local model for
  restricted documents* ([Privacy](privacy.md#who-may-read-each-document-with-ai)).
- **For everything, for good**: start ENLENS with `--local-only` ([Settings](settings.md#for-whoever-installs-enlens)).

When no local model is chosen, or the chosen one is not installed, ENLENS uses one the model server already holds in
memory (so nothing extra is loaded), else the most recently downloaded one, and the test says which.

## Choosing and tuning

What ENLENS asks of a model is harder than chat: quotes copied word for word, fine judgement between "partly supports"
and "same topic", and answers in a fixed JSON format. Ollama and the OpenAI-compatible servers are given the answer's
JSON schema, so even small models give valid JSON; the rest depends on the model.

| Topic | What to know |
| --- | --- |
| **Size** | A rough guide by memory (October 2026; check your server's library for current models): about 16 GB runs models of 8 to 12 billion parameters, 32 GB runs 27 to 32 billion, 64 GB or more runs the largest. Larger models judge better and are slower. If memory allows, an 8-bit version copies quotes more reliably than a 4-bit one. |
| **Context** | ENLENS sets the context length on every Ollama request (Ollama's own default is much smaller and cuts long prompts without warning). Automatic by default: the smallest of 8,192, 12,288, 16,384 and 32,768 tokens that holds the largest task your settings can produce (8 excerpts without reasoning: 8,192). It stays the same between requests, because Ollama reloads the model when it changes. The model's working memory grows with it (for qwen3:8b about 1.2 GB at 8,192 tokens, 2.4 GB at 16,384). *Settings → Technical* shows the length in use and takes a fixed number instead. With LM Studio or llama.cpp, set it when loading the model: 16,384 covers every task of the app. |
| **Memory** | ENLENS loads no model of its own and makes one model call at a time. On Ollama, a second opinion unloads the main model first and unloads itself when done, so two models are never in memory together. LM Studio and other OpenAI-compatible servers have no standard way to unload a model, so their own setting decides (LM Studio can keep only one model loaded). Restricted documents and memory: see [Privacy](privacy.md#the-local-model-and-your-computers-memory). |
| **Reasoning** | For models that reason before answering (Qwen 3 and 3.5, for example), *Settings → AI → Reasoning* (Ollama) has four choices: *Off* (the fastest), *Only when judging excerpts* (where reasoning can help; not for search words or splitting a hypothesis), *On for every step*, and *Model's default*. |
| **Reasoning budget** | Default 1,500 tokens. A model still reasoning at the budget is stopped and asked to answer at once from its notes. At 20 tokens a second that is at most about 75 seconds of reasoning per judgement; with *Only when judging excerpts*, a check takes a minute or two per part instead of half an hour. Reasoning text a server puts before the answer is ignored. |
| **Embeddings** | `nomic-embed-text` (fast, English), `mxbai-embed-large`, or `bge-m3` (many languages). Building the index embeds every passage once (minutes for ten thousand passages); after that a search costs one short call. With numpy installed the comparison is instant; without it, about half a second per search on ten thousand passages. Choose the model in *Settings → Documents*. |

> [!TIP]
> Whether reasoning judges better depends on the model. Compare with
> `enlens --ws pilot benchmark --model … --think off` and `--think judging` before relying on it.

**Cost and time.** With a local model a check costs nothing but time: from seconds to several minutes per call,
depending on the model and the computer.

## Test a model before trusting it

*Settings → Technical → Test a model*, or:

```bash
enlens --ws pilot benchmark --backend ollama --model qwen3:8b --sample 30
```

It runs the model on tasks the pilot already answered with Claude Opus 5.5 and reports, per kind of task: the share of
usable answers, the share with a quote not in the text, agreement with the reference (the same status, and Cohen's κ
beyond chance), and seconds per task. Nothing is stored.

| Verdict | Rule of thumb |
| --- | --- |
| Good enough to use, with review | at least 90% usable and κ 0.6 |
| Usable for a first pass | at least 75% usable and κ 0.4 |

Agreement with Opus is not correctness, but a model that often disagrees with it will also often disagree with your
reviewers.

**Certainties are the model's own estimates.** They mean little until you compare them with your own judgement:
*Settings → Checking* shows how often you agreed with the AI at each certainty, from the excerpts you judged, and after
20 judgements suggests the lowest strictness from which you agreed at least 80% of the time.

**Repeatable results.** ENLENS sends a seed (42 by default) and temperature 0 with every request. *Settings → Technical
→ Repeatable results* tests whether your server gives the same answer twice (`enlens backend-check --repeatable` on
the command line).

---

Next: [Which model does what →](models.md)
