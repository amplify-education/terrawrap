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

    def execute(self, operation: str, debug: bool = False) -> Tuple[int, List[str]]:
        """
        Function for executing this pipeline entry.
        :param operation: The Terraform operation to execute. IE: apply, plan
        :param debug: True if Terraform debug info should be printed.
        :return: A tuple of the exit code and output of the command.
        """
        command_env = os.environ.copy()
        command_env.update(self.envvars)

        if debug:
            command_env["TF_LOG"] = "DEBUG"

        # We're using --no-resolve-envvars here because we've already resolved the environment variables in
        # the constructor. We are then passing in those environment variables explicitly in the
        # execute_command call below.
        args = ["tf", "--no-resolve-envvars", self.path, operation] + self.variables

        # pylint: disable=unused-variable
        plan_file, plan_file_name = tempfile.mkstemp(
            suffix="plan.tfplan"
        )

        if operation in ["apply", "destroy"]:
            plan_exit_code, plan_stdout = execute_command(
                [
                    "tf",
                    "--no-resolve-envvars",
                    self.path,
                    "plan",
                    "-out=%s" % plan_file_name
                ] + self.variables,
                print_output=False,
                capture_stderr=True,
                env=command_env
            )
            args += ["-auto-approve", plan_file_name]
        else:
            plan_exit_code = 0
            plan_stdout = []

        if plan_exit_code != 0:
            return plan_exit_code, plan_stdout

        operation_exit_code, operation_stdout = execute_command(
            args,
            print_output=False,
            capture_stderr=True,
            env=command_env
        )

        return operation_exit_code, plan_stdout + operation_stdout
