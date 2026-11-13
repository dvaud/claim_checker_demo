# ENLENS: rules for agents working in this repository

This repository is usually developed on a 16 GB MacBook that overheats, with 3–5 GB of memory free, by several Claude
sessions and subagents at once. On 2026-11-12 three subagents plus the main agent each ran the test suite with
`-n 4`: about 1 GB was left, test runs were killed (exit 137) and the T3 app restarted twice, cancelling every
background agent. These rules keep that from happening again. docs/DEVELOPING.md (*Tests*) explains the tools.

## Tests

- **CI runs the whole suite**, on Linux (one job with every optional extra), macOS and Windows, on every push to `main`
  (`.github/workflows/tests.yml`). Locally, run only the tests of what you changed: the test files you touched, or
  `--testmon` to rerun the tests that touch the code you changed.
- **One test run at a time on this computer.** A hook (`~/.claude/hooks/one-test-run.sh`) refuses a second one. To wait
  for the running one, run `bash ~/.claude/hooks/wait-for-tests.sh`, then start yours. Never get around the hook
  (splitting the word "pytest", aliases, wrappers): it guards the machine, not a formality.
- **Subagents: at most `-n 2`, on their own test files only.** The whole suite runs once, alone, after branches are
  merged (`python -m pytest -q -rs -n 4 --durations=15`), and before a release, if at all.
- A run of the whole suite leaves out tests marked `heavy`; CI runs them. Name the file, or set `ENLENS_ALL_TESTS=1`,
  to run them here. Random runs (`random`) use 2 seeds here.
- Leave pytest's cache on (do not pass `-p no:cacheprovider`): `--lf` and `--ff` need it, and each git copy has its own.
- Python: `/Users/rdavid/claim_checker_demo/.venv/bin/python` (every extra installed). In a worktree, run pytest from
  the worktree: its `pyproject.toml` puts that worktree's `src` first.
- A new test should write little: a test not marked `heavy` that writes more than 200 MB warns
  (`WriteBudgetWarning`, `tools/writemeter.py`). Use the shared `loaded` fixture and small projects rather than many
  fresh ones.

## Agents and processes

- **At most two implementing subagents at once.** Others may plan, read or review, which uses little memory. At most
  four subagents in all.
- **No `( … &)`, `nohup` or `disown`.** Use Claude Code's own background runs, and stop every process you started (dev
  servers, test runs, watchers, loops) before your turn ends; check with `pgrep -fl dev_server` and
  `pgrep -fl pytest`. `tools/dev_server.py` stops by itself after 60 minutes and when the Claude Code that started it
  ends, but stop it yourself anyway.
- **Keep output short.** Send test and server output to a file and show only its `tail`. Thread logs of 6–7 MB slow
  the T3 app down.
- **Never load a large local model** (Ollama, LM Studio) to test: probe `/api/ps` and `/api/tags`, or use the dev
  server's stand-ins.
- **Several sessions share this clone.** Work in your own worktree (`.claude/worktrees/<name>`), commit only your own
  paths, and check `git status` before committing. Remove your worktree when its branch is merged
  (`git worktree remove <path>`, then `git worktree prune`).
