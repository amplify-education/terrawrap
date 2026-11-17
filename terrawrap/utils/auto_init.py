"""Running `terraform init` ahead of, or in response to, a command that needs an initialized backend."""

import contextlib
import json
import os
import shutil
import sys
from functools import partial
from typing import Callable, Dict, List, Optional

import boto3
from jsons.exceptions import JsonsError
from lark.exceptions import LarkError

from terrawrap.exceptions import NotTerraformConfigDirectory
from terrawrap.models.wrapper_config import BackendsConfig, WrapperConfig
from terrawrap.utils.cli import execute_command
from terrawrap.utils.config import (
    calc_backend_config,
    find_variable_files,
    parse_backend_config_for_dir,
    parse_variable_files,
)
from terrawrap.utils.plugin_download import PluginDownload

# Only a never-initialized backend is safe to auto-init: `-reconfigure` on a changed backend
# discards the old backend config without copying state.
_INIT_REQUIRED = "Backend initialization required"
_INITIAL_CONFIGURATION_REASON = "Initial configuration of the requested backend"

_COMMANDS_WITHOUT_AUTO_INIT = ("init", "console", "import")

# Commands that need an initialized backend are initialized before running rather than after failing, so
# the doomed first attempt never reaches the audit API or pollutes stdout (`output -json`). Commands outside
# this list (fmt, validate, version, get, test) run without a backend and are never initialized up front.
_PREFLIGHT_COMMANDS = (
    "apply",
    "destroy",
    "force-unlock",
    "graph",
    "output",
    "plan",
    "providers",
    "refresh",
    "show",
    "state",
    "taint",
    "untaint",
    "workspace",
)

# What the HCL/backend parser raises on input it can't handle; anything else is a bug and propagates.
_BACKEND_PARSE_ERRORS = (OSError, ValueError, LarkError, JsonsError)


def has_help_flag(arguments: List[str]) -> bool:
    return any("-help" in argument for argument in arguments)


def convert_variables_to_envvars(variables: Dict[str, str]) -> Dict[str, str]:
    envvars = {}

    for key, value in variables.items():
        new_key = "TF_VAR_%s" % key
        if not isinstance(value, str):
            envvars[new_key] = json.dumps(value)
        else:
            envvars[new_key] = value

    return envvars


def build_command_env(variables: Dict[str, str], additional_envvars: Dict[str, str]) -> Dict[str, str]:
    command_env = os.environ.copy()
    command_env.update(convert_variables_to_envvars(variables=variables))
    command_env.update(additional_envvars)
    return command_env


def terraform_data_dir(path: str, env: Dict[str, str]) -> str:
    return os.path.join(path, env.get("TF_DATA_DIR", ".terraform"))


def prepare_init(path: str, command_env: Dict[str, str]):
    data_dir = os.path.abspath(terraform_data_dir(path, command_env))
    config_dir = os.path.abspath(path)
    # TF_DATA_DIR can come from a checked-in .tf_wrapper, so only a directory strictly inside the config
    # directory is ever deleted, and only if no component below the config directory is a symlink.
    inside = data_dir != config_dir and os.path.commonpath([data_dir, config_dir]) == config_dir
    if inside and os.path.realpath(data_dir) == os.path.join(
        os.path.realpath(config_dir), os.path.relpath(data_dir, config_dir)
    ):
        shutil.rmtree(data_dir, ignore_errors=True)
    elif os.path.lexists(data_dir) and data_dir != os.path.join(config_dir, ".terraform"):
        print(
            f"WARNING: Not clearing TF_DATA_DIR {data_dir}; it is not a directory inside {config_dir}.",
            file=sys.stderr,
        )
    # Respect whatever is set, but default to true if it isn't set
    command_env.setdefault("TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE", "true")


def backend_state_file(path: str, env: Dict[str, str]) -> str:
    """Where terraform records the initialized backend, honoring TF_DATA_DIR."""
    return os.path.join(terraform_data_dir(path, env), "terraform.tfstate")


def is_backend_init_error(output: List[str], path: str, env: Dict[str, str]) -> bool:
    """True if terraform output reports a backend that has never been initialized.

    Terraform prints this reason only when the backend state file is missing, so requiring that too keeps
    unrelated output that merely quotes the message from triggering a destructive init.
    """
    # Terraform hard-wraps its diagnostics, so compare with whitespace collapsed.
    text = " ".join("".join(output).split())
    return (
        _INIT_REQUIRED in text
        and _INITIAL_CONFIGURATION_REASON in text
        and not os.path.isfile(backend_state_file(path, env))
    )


def is_auto_init_eligible(command: str, arguments: List[str]) -> bool:
    """True if `command` can be preceded by an automatic init."""
    return command not in _COMMANDS_WITHOUT_AUTO_INIT and not has_help_flag(arguments)


def find_uninitialized_backend(path: str, env: Dict[str, str]) -> Optional[BackendsConfig]:
    """The backend config of `path` if it declares a backend terraform has not recorded as initialized."""
    # Parsing HCL takes up to ~1s in large directories, so only pay for it when the backend is missing.
    if os.path.isfile(backend_state_file(path, env)):
        return None

    try:
        return parse_backend_config_for_dir(path) or None
    except NotTerraformConfigDirectory:
        return None
    except _BACKEND_PARSE_ERRORS as exception:
        # A backend type or HCL terrawrap can't parse must not break the command; the retry after a failed
        # attempt still initializes.
        print(
            f"WARNING: Could not check whether the backend in {path} is initialized ({exception!r}); "
            "skipping the pre-command init.",
            file=sys.stderr,
        )
        return None


def calc_init_backend_arguments(
    path: str,
    variables: Dict[str, str],
    wrapper_config: WrapperConfig,
    upgrade: bool = True,
    existing_backend_config: Optional[BackendsConfig] = None,
) -> List[str]:
    """Backend arguments for `terraform init`; empty when the wrapper config doesn't manage the backend.

    `upgrade=False` drops `-upgrade`, so init keeps the providers pinned in `.terraform.lock.hcl`.
    """
    if not wrapper_config.configure_backend:
        return []

    if existing_backend_config is None:
        existing_backend_config = parse_backend_config_for_dir(path)
    if not existing_backend_config:
        return []

    arguments = calc_backend_config(
        path=path,
        variables=variables,
        wrapper_config=wrapper_config,
        existing_backend_config=existing_backend_config,
    )
    return arguments if upgrade else [argument for argument in arguments if argument != "-upgrade"]


def download_plugins(wrapper_config: WrapperConfig):
    PluginDownload(boto3.client("s3")).download_plugins(wrapper_config.plugins)


def run_init(
    path: str, variables: Dict[str, str], arguments: List[str], additional_envvars: Dict[str, str]
) -> int:
    """Run `terraform init` with the same preparation as `tf <path> init`."""
    command_env = build_command_env(variables, additional_envvars)
    prepare_init(path, command_env)
    exit_code, _ = execute_command(
        # -input=false: a partially configured backend must fail here, not wait on stdin in CI.
        ["terraform", "init", "-input=false"] + arguments,
        cwd=path,
        capture_stderr=True,
        print_command=True,
        retry=True,
        env=command_env,
    )
    return exit_code


def auto_init_backend(
    path: str,
    wrapper_config: WrapperConfig,
    additional_envvars: Dict[str, str],
    backend_config: Optional[BackendsConfig] = None,
) -> int:
    """Initialize a never-initialized backend. Variables are always loaded, whatever command triggered
    this, because they select the backend's bucket and key. `backend_config` is the already-parsed backend
    block, when the caller has it."""
    # Init output goes to stderr so the requested command's stdout (e.g. `output -json`) stays parseable.
    with contextlib.redirect_stdout(sys.stderr):
        print("Backend is not initialized; running `terraform init` first.")
        variables = parse_variable_files(variable_files=find_variable_files(path=path))
        try:
            arguments = calc_init_backend_arguments(
                path, variables, wrapper_config, upgrade=False, existing_backend_config=backend_config
            )
        except _BACKEND_PARSE_ERRORS as exception:
            print(
                f"ERROR: Could not read the backend configuration in {path} ({exception!r}), so "
                "`terraform init` was not run. Run `terraform init` there yourself, or pass --no-auto-init.",
                file=sys.stderr,
            )
            return 1
        download_plugins(wrapper_config)
        exit_code = run_init(path, variables, arguments, additional_envvars)

    if exit_code != 0:
        print(
            f"ERROR: Automatic `terraform init` failed with exit code {exit_code}; the requested command was "
            "not run. Fix the error above, or pass --no-auto-init to skip the init.",
            file=sys.stderr,
        )
    return exit_code


def run_auto_init_or_exit(auto_init: Callable[[], int]):
    """Run `auto_init`, exiting with its exit code if it fails."""
    exit_code = auto_init()
    if exit_code != 0:
        sys.exit(exit_code)


def resolve_auto_init(
    command: str,
    arguments: List[str],
    path: str,
    wrapper_config: WrapperConfig,
    additional_envvars: Dict[str, str],
    disabled: bool,
) -> Optional[Callable[[], int]]:
    """Return the callable that initializes the backend for `command`, or None if auto-init is off or
    already done. Commands that need a backend are initialized right away when it is uninitialized."""
    if disabled or not wrapper_config.auto_init or not is_auto_init_eligible(command, arguments):
        return None

    auto_init = partial(auto_init_backend, path, wrapper_config, additional_envvars)
    if command in _PREFLIGHT_COMMANDS:
        backend_config = find_uninitialized_backend(path, {**os.environ, **additional_envvars})
        if backend_config is not None:
            run_auto_init_or_exit(partial(auto_init, backend_config=backend_config))
            return None

    return auto_init
