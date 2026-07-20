# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## \[0.10.28\] - 2026-07-18

### Changed

- Removed the vestigial `mypy` pin and moved `types-*` packages from `test-requirements.txt`
  into the `mirrors-mypy` hook's `additional_dependencies`, where the pinned mypy the hook
  actually runs can see them.

## \[0.10.26\] - 2026-07-16

### Changed

- Replaced pylint, isort, and black with `ruff` (lint + format) in pre-commit. Reformatting to
  ruff's 110-column line length reflowed docstrings, print strings, and CLI usage text across
  `terrawrap/`, `test/`, and `bin/`; behavior is unchanged. (AT-14951)

## \[0.10.25\] - 2026-06-17

### Fixed

- `version_check` exception handler now emits its warning to `stderr` instead of
  `stdout`. When the PyPI version lookup fails (network timeout, unreachable host),
  the bare `print()` was writing to stdout and could corrupt the output of
  subsequent `terraform show -json` calls, producing `no JSON object found` parse
  failures in the plan-check pipeline. (PR #230)

## \[0.10.24\] - 2026-06-09

### Fixed

- `plan_check --modified-only` now runs a plan for a directory whose only change
  is a file deletion. A deleted file is absent from the filesystem-derived
  dependency graph, so the changed path was silently skipped and the directory
  was never planned. It now falls back to the deleted file's parent directory,
  still gated by `should_run_plan_for` (a directory removed entirely stays
  excluded). (PR #229)

## \[0.10.23\] - 2026-06-08

### Fixed

- `tf` now retries commands that fail with `504 Gateway Timeout`, alongside the
  existing retryable conditions. (PR #228)

## \[0.10.22\] - 2026-05-26

### Added

- `.tf_wrapper` SSM envvars now accept `path` as either a string (existing) or a
  list of strings, plus a new `paths` alias that takes a list. When a list is
  provided, each path is tried in order. A path that raises
  `AccessDeniedException` or `ParameterNotFound` is silently skipped; other
  errors propagate. If every path is skipped, terrawrap exits with an error
  message listing the attempted paths and the caller's IAM identity (from
  `sts:GetCallerIdentity`).
- `tf_validate` CLI: schema-checks every `.tf_wrapper` under a given path. The
  `--fix` flag also prunes dead `depends_on` entries and back-fills
  `depends_on: []` on referenced targets — replacing the legacy
  `scripts/check_tf_wrapper.sh` in `terraform-config`. Uses `ruamel.yaml` so
  YAML comments survive a round-trip. Exits 1 when `--fix` rewrites files so
  CI dirty-tree checks fire.

### Changed

- SSM envvar resolution no longer uses `ssm-cache`; replaced with a small
  in-tree resolver that uses `boto3` directly. This lets terrawrap distinguish
  `AccessDeniedException` from `ParameterNotFound`, which `ssm-cache`
  collapses into a single `InvalidParameterError`.
- The new in-tree SSM resolver caches values for the lifetime of the process
  (no TTL eviction), where the previous `ssm-cache` library used a 10-minute
  `max_age`. Long-running terrawrap consumers should restart the process to
  pick up rotated SSM values; one-shot CLI invocations are unaffected.
- `SSMEnvVarConfig.path` is now a read-only property aliasing `paths[0]` for
  backward compatibility; new code should read `.paths` for the full list.
- Wrapper-config merging now treats the SSM `path`/`paths` fields with
  child-wins replacement semantics, not list-extension. The previous behavior
  would crash if parent and child declared `path` with mismatched types, and
  would silently union path lists across the inheritance chain.

### Removed

- `ssm-cache` is no longer a dependency.
- `SSM_ENVVAR_CACHE` module global in `terrawrap.utils.config` is removed.

## \[0.10.21\] - 2026-05-26

### Fixed

- `tf audit` now derives the SigV4 signing host (`aws_host`) from `audit_api_url`
  instead of a hard-coded value, so audit requests sign correctly when the audit
  endpoint differs per environment. (PR #224)

## \[0.10.20\] - 2026-05-18

### Fixed

- `plan_check` now detects directories whose `auto.tfvars` default value is
  overridden upstream (PR #219). Missing dependency edge previously caused
  `plan` to be skipped on affected dirs.

## \[0.10.19\] - 2026-05-14

### Fixed

- Stop double-recording `tf audit` records from the `GraphEntry` apply path.
  `GraphEntry.execute()` no longer forwards `audit_api_url` to the inner
  `execute_command()` call — `bin/tf` already reports apply/destroy to the
  audit API, so reporting at the outer level produced two rows per apply
  (~50% of all `tfaudit` rows). (AT-14812, PR #216)

## \[0.10.18\] - 2026-05-14

### Changed

- Suppress the RC upgrade prompt when the latest stable already matches or
  exceeds the latest RC on PyPI — users on 0.10.x and 0.11.x were being
  nudged into 0.11.0rc2 after 0.11.0 had shipped. RC notice now only fires
  when `latest_rc > latest_stable`. (PR #217)
- Rename the CI `rc/` branch pattern in `test-build-publish.yml` to the more
  general `release/`, supporting long-lived release branches. (PR #214)

## \[0.10.17\] - 2026-05-04

### Fixed

- `convert_plan_to_json` now tolerates stderr lines interleaved with the
  `tf show -json` stdout. Previously it stripped exactly one prefix line
  (`stdout[1:]`) on the assumption that only the wrapper's command echo
  preceded the JSON; because `_execute_command` runs with
  `capture_stderr=True`, terraform stderr (lockfile warnings, deprecation
  notices, etc.) was being merged into stdout and corrupting `tfplan.json`.
  (PR #213)

## \[0.10.16\] - 2026-05-01

### Fixed

- Compress terraform output larger than 5 MB (gzip + base64) into an
  `output_compressed` field before posting to the audit API. Snowflake apply
  output (~12.7 MB) was silently failing API Gateway with HTTP 413 because
  the response was never checked. Also adds `raise_for_status()` so future
  oversized payloads surface as errors instead of false successes. (PR #212)

## \[0.10.15\] - 2026-03-11

### Changed

- Update RC install prompt wording and fix `test-build-publish.yml`. (PR #208)

## \[0.10.14\] - 2026-03-10

### Changed

- Make `version_check` and the publish job RC-aware. (PR #205)

## \[0.10.13\] - 2026-02-24

### Changed

- Upgrade `packaging` to v26. (PR #204)

## \[0.10.12\] - 2026-02-20

### Changed

- Upgrade `packaging` to v24. (PR #203)

## \[0.10.11\] - 2026-01-30

### Changed

- Upgrade `mypy` version. (PR #201)

## \[0.10.9\] - 2026-01-05

### Added

- Pass `audit_api_url` through to `graph_entry`. (PR #200)

## \[0.10.8\] - 2025-07-23

### Fixed

- Surface and handle errors raised by `_post_audit_info` instead of letting
  them break the apply path. (AT-13689, PR #198)

## \[0.10.7\] - 2025-03-20

### Added

- `use_lockfile` support in `.tf_wrapper`. (AT-13020, PR #197)

## \[0.10.6\] - 2025-03-17

### Changed

- `tf_move` no longer attempts to move files that are untracked by git. (PR #196)

## \[0.10.5\] - 2025-03-17

### Changed

- `tf_move` no longer deletes the original state file in S3. (PR #195)

## \[0.10.4\] - 2025-03-17

### Added

- `tf_move` CLI for relocating terraform state between directories.
  (AT-12986, PR #194)

## \[0.10.3\] - 2024-11-04

### Added

- Support newer Python versions. (PR #192)

## \[0.10.2\] - 2024-08-30

### Changed

- Always pass `-upgrade` on `init`. (PR #191)

## \[0.10.1\] - 2024-08-30

### Changed

- Ignore extra-args handling when running `--help`. (PR #190)

## \[0.10.0\] - 2024-05-31

### Changed

- Update Python version and packages. (PR #188)

## \[0.9.35\] - 2024-03-06

### Changed

- Update `MANIFEST.in`. (PR #186)

## \[0.9.34\] - 2024-03-04

### Changed

- Rename the Python dependency file to the standard `requirements.txt`.
  (AT-10041, PR #180)

## \[0.9.33\] - 2024-01-16

### Fixed

- Match additional state-push error strings during retry. (PR #176)

## \[0.9.32\] - 2024-01-14

### Fixed

- Add support for re-pushing state when the original push fails. (PR #175)

## \[0.9.31\] - 2023-10-23

### Fixed

- Fix `GIT_REPO_REGEX` and `calc_repo_path` in `utils/path.py`. (PR #172)

## \[0.9.30\] - 2023-10-04

### Changed

- Default to ignoring Terraform lock files. (AT-10360, PR #169)

## \[0.9.29\] - 2023-09-29

### Changed

- Bump a number of dependencies. (PR #168)

## \[0.9.28\] - 2023-09-29

### Changed

- Stop deleting Terraform provider lock files automatically. (AT-10360, PR #167)

## \[0.9.27\] - 2023-09-01

### Fixed

- Catch an additional retriable error in the retry loop. (PR #166)

## \[0.9.26\] - 2023-08-31

### Changed

- Upgrade `PyYAML`. (PR #165)

## \[0.9.25\] - 2023-04-28

### Added

- TF Audit support for `tf destroy` applies. (AT-9247, PR #163)

## \[0.9.24\] - 2023-04-27

### Changed

- Apply `python-black` formatting and add the pre-commit check. (AT-9375, PR #164)

## \[0.9.23\] - 2023-03-24

### Fixed

- Extend the lock-create-time regex to handle microsecond precision. (PR #162)

## \[0.9.22\] - 2023-03-16

### Fixed

- Make the lock-create-time regex resilient to additional format variations.
  (PR #161)

## \[0.9.21\] - 2023-01-17

### Removed

- Remove duplicate TF Audit calls from `graph_entry`; the inner `bin/tf`
  invocation already records the apply. (AT-7866, PR #160)

## \[0.9.20\] - 2022-09-23

### Changed

- Change `--modified-only` behavior of `plan_check` command. `--modified-only` will now compare with `merge-base`
  using `git merge-base` command instead of directly comparing against the master branch

## \[0.9.19\] - 2022-09-21

### Changed

- Bump required version for jsons package because the old failed with python >= 3.8

## \[0.8.8\] - 2021-04-20

### Changed

- Fix parsing of the wrap file config

## \[0.8.7\] - 2021-03-31

### Changed

- Add parallel jobs option to the `plan_check`

## \[0.8.6\] - 2021-03-29

### Changed

- Improvements to `backend_check`

## \[0.8.5\] - 2021-03-29

### Changed

- Update `jsons` package to version `>=1.0.0,<1.3.0`

## \[0.8.4\] - 2021-03-26

### Changed

- Updated plan check to ignore git directory

## \[0.8.3\] - 2021-02-23

### Changed

- Update `PyYAML` package to version >=5.3.1,\<6

## \[0.8.2\] - 2021-02-19

### Changed

- Check that a path is a directory before attempting to run `plan` when running `plan_check`

## \[0.8.1\] - 2021-02-16

### Changed

- Terraform provider version lock files are not automatically deleted

## \[0.8.0\] - 2021-02-11

### Changed

- Refactored `plan_check` when using `--modified-only` to build a graph when scanning for directories that
  were changed or affected by a change (such as symlinks, module changes, auto.tfvars, etc). This fixes a
  number of edge cases where `plan_check` missed directories that should have had `plan` run.

## \[0.7.0\] - 2021-01-29

### Changed

- Fixed a bug in `graph_apply` when there are symlinks to directories above the directory being applied

## \[0.6.15\] - 2020-12-15

### Changed

- update `jsons` package to version >=1.0.0,\<1.2.0

## \[0.6.14\] - 2020-12-15

### Changed

- revert `jsons` package to version 0.10.2

## \[0.6.13\] - 2020-12-15

### Changed

- update `jsons` package to version 1.3.0

## \[0.6.12\] - 2020-12-10

### Changed

- Add `tf_wrapper` config check for the `connect_symlinks` in `graph_apply`

## \[0.6.11\] - 2020-11-02

### Changed

- Bump `python-hcl2` version

## \[0.6.10\] - 2020-10-30

### Changed

- Fix report error on parsing module

## \[0.6.9\] - 2020-10-28

### Changed

- Update plan_check to print IAM and error directories

## \[0.6.8\] - 2020-10-10

### Changed

- Fix retry another throttle error

## \[0.6.7\] - 2020-7-9

### Changed

- Catch no cycle error for visualize

## \[0.6.6\] - 2020-06-11

### Changed

- Make downloaded plugins executable

## \[0.6.5\] - 2020-06-11

### Changed

- Create plugin directory if it doesn't exist before downloading plugins

## \[0.6.4\] - 2020-06-09

### Changed

- Fix error handling in graph apply

## \[0.6.3\] - 2020-06-09

### Changed

- Fix bug when parsing S3 URLs while downloading plugins

## \[0.6.2\] - 2020-06-08

### Added

- Added support for downloading plugins from platform specific URLs.
  For example on Mac, Terrawrap will try downloading from `<plugin_url>/Darwin/x86_64` first and fallback to
  downloading from `<plugin url>`. See README for more details.

- Added support for downloading from plugins from S3 using the AWS SDK

## \[0.6.1\] - 2020-06-08

### Changed

- Changed `backend_check` to ignore directories that don't contain `.tf` files

## \[0.6.0\] - 2020-06-05

### Added

- Added support for a new `plugins` config option in `.tf_wrapper` to automatically download third party
  plugins when running `init`. See the README for info.
