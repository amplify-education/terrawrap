# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

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
