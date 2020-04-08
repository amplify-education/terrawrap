"""Module for containing Pipeline Entries"""
import logging
import os
import tempfile
from typing import List, Tuple

from terrawrap.utils.cli import execute_command
from terrawrap.utils.config import find_wrapper_config_files, parse_wrapper_configs, resolve_envvars
from terrawrap.utils.path import get_absolute_path

logger = logging.getLogger(__name__)


class PipelineEntry:
    """Class representing a Pipeline Entry"""

    def __init__(self, path: str, variables: List[str]):
        """
        :param path: The path to the Terraform configuration files to execute.
        :param variables: Any additional variables to set alongside the Terraform command.
        """
        self.path = get_absolute_path(path=path)
        wrapper_config_files = find_wrapper_config_files(self.path)
        wrapper_config = parse_wrapper_configs(wrapper_config_files)
        self.envvars = resolve_envvars(wrapper_config.envvars)
        self.variables = variables

    # pylint: disable=too-many-locals
    def execute(self, operation: str, debug: bool = False) -> Tuple[int, List[str], bool]:
        """
        Function for executing this pipeline entry.
        :param operation: The Terraform operation to execute. IE: apply, plan
        :param debug: True if Terraform debug info should be printed.
        :return: A tuple of the exit code, output of the command, and whether changes were detected.
        """
        command_env = os.environ.copy()
        command_env.update(self.envvars)

        if debug:
            command_env["TF_LOG"] = "DEBUG"

        # pylint: disable=unused-variable
        plan_file, plan_file_name = tempfile.mkstemp(
            suffix=".tfplan"
        )

        # We're using --no-resolve-envvars here because we've already resolved the environment variables in
        # the constructor. We are then passing in those environment variables explicitly in the
        # execute_command call below.
        base_args = [
            "tf",
            "--no-resolve-envvars",
            self.path
        ]
        init_args = base_args + ["init"] + self.variables
        plan_args = base_args + [
            "plan",
            "-detailed-exitcode",
            "-out=%s" % plan_file_name
        ] + self.variables
        operation_args = base_args + [operation] + self.variables

        if operation in ["apply", "destroy"]:
            operation_args += ["-auto-approve"]

        init_exit_code, output = execute_command(
            init_args,
            print_output=False,
            capture_stderr=True,
            env=command_env,
        )

        if init_exit_code != 0:
            return init_exit_code, output, True

        # We need to plan first before we apply so we can actually see a plan... Thanks Hashicorp
        if operation in ["apply"]:
            plan_exit_code, plan_stdout = execute_command(
                plan_args,
                print_output=False,
                capture_stderr=True,
                env=command_env
            )

            output += ["\n"] + plan_stdout

            if plan_exit_code != 2:
                return (
                    plan_exit_code,
                    output,
                    False,
                )

            operation_args += [plan_file_name]

        if operation in ["plan"]:
            operation_args += ["--detailed-exitcode"]

        operation_exit_code, operation_stdout = execute_command(
            operation_args,
            print_output=False,
            capture_stderr=True,
            env=command_env
        )

        output += ["\n"] + operation_stdout

        changes_detected = True
        if operation in ["plan"]:
            if operation_exit_code == 2:
                # Set exit code to 0 so the command doesn't fail out
                operation_exit_code = 0
            elif operation_exit_code != 2:
                changes_detected = False

        return (
            operation_exit_code,
            output,
            changes_detected,
        )
