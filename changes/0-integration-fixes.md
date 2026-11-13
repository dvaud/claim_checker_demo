### Fixed

- **An answer from the Claude API no longer says it was made at temperature 0.** ENLENS sends the Claude API no
  temperature (nor a seed), but recorded *temperature 0* with each of its answers in *How these results were made*.
  It now records none, as for Claude Code. Answers made before keep their record. Cannot change results.

### For developers

- `docs/METHODS.md` (how a check, labels, concepts and themes work, with references, for a methods section) and
  `docs/PRIVACY.md` (what leaves the computer, when and to whom, for an ethics application or a data protection
  assessment), linked from the README, the manual's hub and its privacy page (roadmap J4.4).
- The test files are named by topic, not by version (roadmap J1.11): 170 files renamed once.
