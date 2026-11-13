### New

- **A result made by an earlier ENLENS says so on its own page.** A check, a set of themes and the Codes page now
  name the earlier version behind them in the line under their title ("Made with ENLENS 0.17.2", or "12 labels made
  with ENLENS 0.16.1" for a codebook's labels), with what that means in its tooltip. Results made by this version
  show nothing new. The Overview kept its summary of every result. Cannot change results.

### For developers

- `runs.made_with_one(app_version)` and `runs.labels_made_with(ws, framework)`; `made_with` in the answers of
  `GET …/hypotheses/<id>`, `GET …/themes/<run>` and `GET …/profile`; `lib.js` `madeWithFact(m)` for a page head's
  facts. Tests: `tests/test_version_on_each_result.py`.
