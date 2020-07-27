[![Codacy Badge](https://api.codacy.com/project/badge/Grade/e8bf52c80edf4070a18d8725b1f5f166)](https://app.codacy.com/app/amplify-education/terrawrap?utm_source=github.com&utm_medium=referral&utm_content=amplify-education/terrawrap&utm_campaign=Badge_Grade_Settings)
[![Codacy Badge](https://api.codacy.com/project/badge/Coverage/ceeb459250dd429f9ca5a497c0e45051)](https://www.codacy.com/app/amplify-education/terrawrap?utm_source=github.com&utm_medium=referral&utm_content=amplify-education/terrawrap&utm_campaign=Badge_Coverage)
[![Build Status](https://travis-ci.org/amplify-education/terrawrap.svg?branch=master)](https://travis-ci.org/amplify-education/terrawrap)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://raw.githubusercontent.com/amplify-education/terrawrap/master/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/terrawrap.svg)](https://pypi.org/project/terrawrap/)
[![Python Versions](https://img.shields.io/pypi/pyversions/terrawrap.svg)](https://pypi.python.org/pypi/terrawrap)
[![Downloads](https://img.shields.io/badge/dynamic/json.svg?label=downloads&url=https%3A%2F%2Fpypistats.org%2Fapi%2Fpackages%2Fterrawrap%2Frecent&query=data.last_month&colorB=brightgreen&suffix=%2FMonth)](https://pypistats.org/packages/terrawrap)

# Terrawrap

Set of Python-based CLI tools for working with Terraform configurations in bulk

## About Amplify

Amplify builds innovative and compelling digital educational products that empower teachers and students across the 
country. We have a long history as the leading innovator in K-12 education - and have been described as the best tech 
company in education and the best education company in tech. While others try to shrink the learning experience into  
the technology, we use technology to expand what is possible in real classrooms with real students and teachers.

Learn more at <https://www.amplify.com>

## Table of Contents

-   [Features](#features)

-   [Goals](#goals)

-   [Getting Started](#getting-started)
    -   [Prerequisites](#prerequisites)
    -   [Installing](#installing)
    -   [Building From Source](#building-from-source)
    -   [Running Tests](#running-tests)

-   [Configuration](#configuration)
    -   [.tf_wrapper](#tf_wrapper)
    -   [Plugins](#plugins)
    -   [Autovars](#autovars)
    -   [Backend Configuration](#backend-configuration)

-   [Commands](#commands)
    -   [tf](#tf)
    -   [plan_check](#plan_check)
    -   [graph_apply](https://github.com/amplify-education/terrawrap/wiki/graph_apply)

## Features

1.  `auto.tfvars` inheritance. Terrawrap makes it easier to share variables between Terraform directories through
    inheritance of `auto.tfvars` files.

2.  Remote backend generation. Terrawrap makes it easier to work with remote state backends by
    generating configuration for them.

3.  Repository level plan/apply. Terrawrap provides commands for running plan/apply recursively on a entire
    repository at once.

4.  Repository level dependency visualization. Terrawrap provides commands for displaying the order of applies in 
    human readable output.

5.  Automatically download third-party Terraform plugins

## Goals

1.  Make Terraform DRY for large organizations. A Terraform best practices is to break up Terraform configs
    into many small state files. This leads to an explosion in boilerplate code when using Terraform in large
    organizations with 100s of state files. Terrawrap reduces some boilerplate code by providing `auto.tfvars`
    inheritance and generating backend configurations.

2.  Make Terraform code easier to manage. Terraform only runs commands on a single directory at a time. This makes
    working with hundreds of terraform directories/state files hard. Terrawrap provides utilities for running
    commands against an entire repository at once instead of one directory at a time.

3.  All Terraform code should be valid Terraform. Any Terraform code used with Terrawrap should be runnable with
    Terraform by itself without the wrapper. Terrawrap does not provide any new syntax.

4.  Terrawrap is not a code generator. Generated code is harder to
    read and understand. Code generators tend to lead to leaky abstractions that can be more trouble than they are
    worth. However, Terrawrap does generate remote backend configs as a workaround to Terraform's lack of support for
    variables in backend configs (See <https://github.com/hashicorp/terraform/issues/13022>). We expect this to be
    the only instance of code generation in Terrawrap.

## Getting Started

### Prerequisites

Terrawrap requires Python 3.6.0 or higher to run.

### Installing

This package can be installed using `pip`

```sh
pip3 install terrawrap
```

You should now be able to use the `tf` command.

## Building From Source

For development, `tox>=2.9.1` is recommended.

### Running Tests

Terrawrap uses `tox`. You will need to install tox with `pip install tox`.
Running `tox` will automatically execute linters as well as the unit tests.

You can also run them individually with the `-e` argument.

For example, `tox -e py37-unit` will run the unit tests for python 3.7

To see all the available options, run `tox -l`.

## Configuration

### .tf_wrapper

Terrawrap can be configured via a `.tf_wrapper` file. The wrapper will walk the provided configuration
path and look for `.tf_wrapper` files. The files are merged in the order that they are discovered. Consider 
the below example:

```text
foo
├── bar
│   └── .tf_wrapper
└── .tf_wrapper
```

If there are conflicting configurations between those two `.tf_wrapper` files, the `.tf_wrapper` file in
`foo/bar` will win.

The following options are supported in `.tf_wrapper`:

```yaml
configure_backend: True # If true, automatically configure Terraform backends.
backend_check: True # If true, require this directory to have a terraform backend configured

envvars:
  <NAME_OF_ENVVAR>:
    source: # The source of the envvar. One of `['ssm', 'text']`.
    path: # If the source of the envvar is `ssm`, the SSM Parameter Store path to lookup the value of the environment variable from.
    value: # if the source of the envvar is `text`, the string value to set as the environment variable.

plugins:
    <NAME_OF_PLUGIN>: <plugin url>
```

### Plugins

Terrawrap supports automatically downloading provider plugins by configuring the `.tf_wrapper` file as specified above.
This is a temporary workaround until Terraform 0.13 is released with built-in support for automatically 
downloading plugins and plugin registries are available for hosting private plugins. 

Terrawrap will first try to download platform specific versions of plugins by downloading them from 
`<plugin url>/<system type>/<architecture type>`. If Terrawrap is unable to download from the platform specific URL 
then it will try to download directly from the given plugin url directly instead.

For example, the following config on a Mac

```yaml
plugins:
    foo: http://example.com/foo
```

Terrawap will first try to download from `http://example.com/foo/Darwin/x86_64`. 
If that request fails then Terrawrap will try `http://example.com/foo` instead.

### Autovars

Terrawrap automatically adds `-var-file` arguments to any terraform command by scanning for `*.auto.tfvars` 
files in the directory structure.

For example, the following command `tf config/foo/bar apply` with the following directory structure:

```text
config
├── foo
|   └── bar
|   │  ├── baz.tf
|   │  └── bar.auto.tfvars
|   └── foo.auto.tfvars
└── config.auto.tfvars
```

will generate the following command:

```bash
terraform apply -var-file config/config.auto.tfvars \
    -var-file config/foo/foo.auto.tfvars \
    -var-file config/foo/bar/bar.auto.tfvars
```

### Backend Configuration

Terrawrap supports automatically configuring backends by injecting the appropriate `-backend-config`
args when running `init`

For example, the Terrawrap command `tf config/foo/bar init` will generate a Terraform command like below if using
an AWS S3 remote state backend

```bash
terraform init -reconfigure \
    -backend-config=dynamodb_table=<lock table name> \
    -backend-config=encrypt=true \
    -backend-config=key=config/foo/bar.tfstate \
    -backend-config=region=<region name> \
    -backend-config=bucket=<state bucket name> \
    -backend-config=skip_region_validation=true \
    -backend-config=skip_credentials_validation=true
```

Terrawrap configures the backend by looking for `.tf_wrapper` files in the directory structure. 
Either `s3` or `gcs` are supported. See the relevant Terraform documentation for the options available
for each type of backend: 
<https://www.terraform.io/docs/backends/types/s3.html#configuration-variables>
<https://www.terraform.io/docs/backends/types/gcs.html#configuration-variables>

#### S3 Backend
```yml
backends:
    s3:
        region:
        role_arn:
        bucket:
        dynamodb_table:
```

| Option Name    | Required | Purpose                                                                              |
| -------------- | -------- | ------------------------------------------------------------------------------------ |
| bucket         | Yes      | Name of S3 Bucket                                                                    |
| region         | Yes      | AWS Region that S3 state bucket and DynamoDB lock table are located in               |
| dynamodb_table | No       | DynamoDB table to use for state locking. Locking is disable if lock_table is not set |
| role_arn       | No       | AWS role to assume when reading/writing to S3 bucket and lock table                  |

The S3 state file key name is generated from the directory name being used to run the terraform command. 
For example, `tf config/foo/bar init` uses a state file with the key `config/foo/bar.tfstate` in S3

#### GCS Backend
```yml
backends:
    gcs:
        bucket:
```
| Option Name    | Required | Purpose                                                                              |
| -------------- | -------- | ------------------------------------------------------------------------------------ |
| bucket         | Yes      | Name of GCS Bucket                                                                   |

## Commands

### tf

`tf <directory> <terraform command>` runs a terraform command for a given directory that contains `*.tf` files. 
Terrawrap automatically includes autovars as described above when running the given command. Any Terraform
command is supported 

### plan_check

`plan_check <directory>` runs `terraform plan` recursively for all child directories starting at the given directory.
`plan_check` uses `git` to identify which files have changed compared with the `master` branch. It will then run `plan`
on any directory that contains `tf` files with the following criteria

1.  A directory that has files that changed
2.  A directory that is symlinked to a directory that has files changed
3.  A directory with symlinked files that are linked to files that changed
4.  A directory that that uses a Terraform module whose source changed
5.  A directory with Terraform files that refer to an autovar file that changed

### backend_check

`backend_check [directory]` verifies that all directories under the given directory that contain `.tf` files
also have Terraform Backends defined.
