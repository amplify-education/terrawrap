"""Running `terraform init` ahead of, or in response to, a command that needs an initialized backend."""

import json
import os
import shutil
import sys
from functools import partial
from typing import Callable, Dict, List, Optional

import boto3

from terrawrap.exceptions import NotTerraformConfigDirectory
from terrawrap.models.wrapper_config import WrapperConfig
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

# Audited commands are initialized before running rather than after failing, so the doomed
# first attempt never reaches the audit API.
_PREFLIGHT_COMMANDS = ("apply", "destroy")


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


def prepare_init(path: str, command_env: Dict[str, str]):
    shutil.rmtree(os.path.join(path, ".terraform"), ignore_errors=True)
    # Respect whatever is set, but default to true if it isn't set
    command_env.setdefault("TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE", "true")


def backend_state_file(path: str, env: Dict[str, str]) -> str:
    """Where terraform records the initialized backend, honoring TF_DATA_DIR."""
    return os.path.join(path, env.get("TF_DATA_DIR", ".terraform"), "terraform.tfstate")


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


def is_backend_uninitialized(path: str, env: Dict[str, str]) -> bool:
    """True if `path` declares a backend but terraform has not recorded one."""
    try:
        has_backend = bool(parse_backend_config_for_dir(path))
    except NotTerraformConfigDirectory:
        return False
    except Exception as exception:  # pylint: disable=broad-exception-caught
        # Best effort: a backend type or HCL terrawrap can't parse must not break apply/destroy;
        # the retry after a failed attempt still initializes.
        print(
            f"WARNING: Could not check whether the backend in {path} is initialized ({exception!r}); "
            "skipping the pre-apply init.",
            file=sys.stderr,
        )
        return False
    return has_backend and not os.path.isfile(backend_state_file(path, env))


def calc_init_backend_arguments(
    path: str, variables: Dict[str, str], wrapper_config: WrapperConfig, upgrade: bool = True
) -> List[str]:
    """Backend arguments for `terraform init`; empty when the wrapper config doesn't manage the backend.

    `upgrade=False` drops `-upgrade`, so init keeps the providers pinned in `.terraform.lock.hcl`.
    """
    if not wrapper_config.configure_backend:
        return []

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
        ["terraform", "init"] + arguments,
        cwd=path,
        capture_stderr=True,
        print_command=True,
        retry=True,
        env=command_env,
    )
    return exit_code


def auto_init_backend(path: str, wrapper_config: WrapperConfig, additional_envvars: Dict[str, str]) -> int:
    """Initialize a never-initialized backend. Variables are always loaded, whatever command triggered
    this, because they select the backend's bucket and key."""
    print("Backend is not initialized; running `terraform init` first.")
    variables = parse_variable_files(variable_files=find_variable_files(path=path))
    arguments = calc_init_backend_arguments(path, variables, wrapper_config, upgrade=False)
    download_plugins(wrapper_config)
    return run_init(path, variables, arguments, additional_envvars)


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
    already done. Audited commands are initialized right away when the backend is uninitialized."""
    if disabled or not wrapper_config.auto_init or not is_auto_init_eligible(command, arguments):
        return None

    auto_init = partial(auto_init_backend, path, wrapper_config, additional_envvars)
    if command in _PREFLIGHT_COMMANDS and is_backend_uninitialized(
        path, {**os.environ, **additional_envvars}
    ):
        run_auto_init_or_exit(auto_init)
        return None

    return auto_init
