# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [0.6.15] - 2020-12-15

### Changed

-   update `jsons` package to version >=1.0.0,<1.2.0

## [0.6.14] - 2020-12-15

### Changed

-   revert `jsons` package to version 0.10.2

## [0.6.13] - 2020-12-15

### Changed

-   update `jsons` package to version 1.3.0

## [0.6.12] - 2020-12-10

### Changed

-   Add `tf_wrapper` config check for the `connect_symlinks` in `graph_apply`

## [0.6.11] - 2020-11-02

### Changed

-   Bump `python-hcl2` version

## [0.6.10] - 2020-10-30

### Changed

-   Fix report error on parsing module

## [0.6.9] - 2020-10-28

### Changed

-   Update plan_check to print IAM and error directories

## [0.6.8] - 2020-10-10

### Changed

-   Fix retry another throttle error

## [0.6.7] - 2020-7-9

### Changed

-   Catch no cycle error for visualize

## [0.6.6] - 2020-06-11

### Changed

-   Make downloaded plugins executable

## [0.6.5] - 2020-06-11

### Changed

-   Create plugin directory if it doesn't exist before downloading plugins

## [0.6.4] - 2020-06-09

### Changed

-   Fix error handling in graph apply

## [0.6.3] - 2020-06-09

### Changed

-   Fix bug when parsing S3 URLs while downloading plugins

## [0.6.2] - 2020-06-08

### Added

-   Added support for downloading plugins from platform specific URLs. 
    For example on Mac, Terrawrap will try downloading from `<plugin_url>/Darwin/x86_64` first and fallback to 
    downloading from `<plugin url>`. See README for more details.
    
-   Added support for downloading from plugins from S3 using the AWS SDK

## [0.6.1] - 2020-06-08

### Changed

-   Changed `backend_check` to ignore directories that don't contain `.tf` files

## [0.6.0] - 2020-06-05

### Added

-   Added support for a new `plugins` config option in `.tf_wrapper` to automatically download third party 
    plugins when running `init`. See the README for info.
