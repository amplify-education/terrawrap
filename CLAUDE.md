# terrawrap

Python CLI wrapper around Terraform. `bin/` scripts (`tf`, `plan_check`,
`graph_apply`, …) are thin entrypoints; the testable logic lives in
`terrawrap/utils/` and `terrawrap/models/`, unit-tested under `test/unit/`. Put
new logic there, not in the `bin/` scripts.

## Version bumps require a CHANGELOG entry

Any PR that changes `terrawrap/`, `test/`, `bin/`, `setup.*`, or `*.pip` **must**
bump `__version__` in `terrawrap/version.py` — `bin/versionCheck.sh` fails the PR
build otherwise (semver: fix → patch, feature → minor).

**Always pair the version bump with a matching `CHANGELOG.md` entry** under a new
`## [<version>] - <YYYY-MM-DD>` heading, using the
[Keep a Changelog](http://keepachangelog.com/en/1.0.0/) sections
(Added / Changed / Fixed / Removed). `versionCheck.sh` does **not** check the
changelog, so it is easy to bump the version and forget the entry — don't. Set
the heading version to the value you just wrote into `version.py`.

## Tests

- `tox` runs unit tests on py310–py314. **Minimum supported is 3.10**, so do not
  use Python 3.11+ APIs in tests (e.g. `unittest.TestCase.enterContext`). Use
  `unittest.TestCase` with `@patch` decorators, or `tempfile.mkdtemp()` +
  `self.addCleanup(shutil.rmtree, ...)`.
- A single-interpreter `pytest` pass is not enough — run `tox` (all envs) before
  declaring done.
- pre-commit runs black (pinned `22.8.0`), mypy, and pylint (scoped to
  `terrawrap/` and `test/` — `bin/` scripts are not linted).

## Local Dev Env

A local pyenv env for this repo can drift behind `origin/main`'s
`requirements.txt` (a new pinned dependency isn't installed until you
re-`pip install`) — a pytest collection `ImportError` on an unrelated-looking
module is often this, not a real regression.

In a worktree checked out off a newer `origin/main` than the editable
install's target, run pytest with `PYTHONPATH=$(pwd)` so the worktree's copy
of `terrawrap` shadows the stale editable install pointing at the main
checkout.
