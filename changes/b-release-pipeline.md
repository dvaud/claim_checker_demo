### Releases

- **One version number, from the release tag, and a release made by merging a pull request.** Nothing is typed in three places any more: the version of ENLENS is made from the tag of its release, and `enlens update` in a git copy installs it again when a new release comes. A release now starts with one command, which joins the changes, writes the README's *New in* and the app's *What's new* from them and opens a pull request; merging it tags the release. Every release file carries a signed note of which workflow and commit built it (`gh attestation verify`), the packages the tests install are pinned in a lock file, Dependabot proposes updates, every GitHub Action is pinned by its commit, and the install line of each published release is tried again on Linux, macOS and Windows, then every Monday. Cannot change results.

### For developers

- `pyproject.toml` has `dynamic = ["version"]` and `[tool.setuptools_scm]` (`post-release` versions, no local part, `0.0.0` without git); `enlens_claims.__version__` reads the package's metadata, then `git describe`, then `0.0.0`; `update.version_in` reads a git copy's newest release tag; `server._installed_version` reads the metadata afresh.
- `tools/release.py`: `check` compares the tag and the changelog's top entry, `assets --expect vX.Y.Z` the wheel's version, `prepare X.Y.Z "title" [--go]` (a dry run unless `--go`), `sync-notes [--check]`. `.github/workflows/tag-release.yml`, `published-install.yml`, `dependabot.yml`, `uv.lock` (with a `ci` extra), `actions/attest-build-provenance` in `release.yml`. `docs/DEVELOPING.md` has the steps.
- The README's *New in* stands between `<!-- new-in:start -->` and `<!-- new-in:end -->` and is written by `release.py`.

### Tests

- `tests/test_release_pipeline.py`, `tests/test_release_prepare.py`, `tests/test_doc_links.py`: the version flow, the workflows' shape (with PyYAML), pinned actions, the lock, links between documents, a manual section for every feature, and *New in* matching the changelog.

### Not yet done

- None of the new workflows has run on GitHub: the first runs are the merge of the first release pull request, the release it tags, and the weekly published-install run. The build's own requirements (`setuptools-scm`) are not in the lock file.
