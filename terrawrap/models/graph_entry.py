"""Module for containing Graph Entries"""
from abc import ABC, abstractmethod

import os
import tempfile
from typing import List, Tuple

from terrawrap.utils.cli import execute_command
from terrawrap.utils.config import (
    find_wrapper_config_files,
    parse_wrapper_configs,
    resolve_envvars,
)
from terrawrap.utils.path import get_absolute_path


class Entry(ABC):
    """Abstract Graph Entry class"""
    path = ""
    state = ""

    @abstractmethod
    def execute(self, operation: str, debug: bool = False) -> Tuple[int, List[str], bool]:
        """Execute a graph entry"""
        return 0, [], False


class NoOpGraphEntry(Entry):
    """NoOp Graph Entry class. Use this for graph entries that should not be executed"""
    def __init__(self, path: str, variables: List[str]):
        self.path = path
        self.variables = variables
        self.state = "no-op"

    def execute(self, operation: str, debug: bool = False) -> Tuple[int, List[str], bool]:
        print("Skipping execute for %s %s ..." % (self.path, operation))
        return 0, [], False


class GraphEntry(Entry):
    """Class representing a Graph Entry"""

    def __init__(self, path: str, variables: List[str]):
        """
        :param path: The path to the Terraform configuration files to execute.
        :param variables: Any additional variables to set alongside the Terraform command.
        """
        self.path = path
        self.abs_path = get_absolute_path(path=path)
        wrapper_config_files = find_wrapper_config_files(self.abs_path)
        wrapper_config = parse_wrapper_configs(wrapper_config_files)
        self.envvars = resolve_envvars(wrapper_config.envvars)
        self.variables = variables
        self.state = "Pending"

    # pylint: disable=too-many-locals
    def execute(self, operation: str, debug: bool = False) -> Tuple[int, List[str], bool]:
        """
        Function for executing this Graph Entry.
        :param operation: The Terraform operation to execute. IE: apply, plan
        :param debug: True if Terraform debug info should be printed.
        :return: A tuple of the exit code, output of the command, and whether changes were detected.
        """
        print("Executing %s %s ..." % (self.abs_path, operation))
        self.state = "Executing"
        command_env = os.environ.copy()
        command_env.update(self.envvars)

        if debug:
            command_env["TF_LOG"] = "DEBUG"

        # pylint: disable=unused-variable
        plan_file, plan_file_name = tempfile.mkstemp(suffix=".tfplan")

        # We're using --no-resolve-envvars here because we've already resolved the environment variables in
        # the constructor. We are then passing in those environment variables explicitly in the
        # execute_command call below.
        base_args = ["tf", "--no-resolve-envvars", self.abs_path]
        init_args = base_args + ["init"] + self.variables
        plan_args = (
            base_args +
            ["plan", "-detailed-exitcode", "-out=%s" % plan_file_name] +
            self.variables
        )
        operation_args = base_args + [operation] + self.variables

        if operation in ["apply", "destroy"]:
            operation_args += ["-auto-approve"]

        init_exit_code, init_stdout = execute_command(
            init_args, print_output=False, capture_stderr=True, env=command_env
        )
        if init_exit_code != 0:
            self.state = "Failed"
            return init_exit_code, init_stdout, True
        if operation in ["apply"]:
            plan_exit_code, plan_stdout = execute_command(
                plan_args, print_output=False, capture_stderr=True, env=command_env
            )
            operation_args += [plan_file_name]
        else:
            plan_exit_code = 0
            plan_stdout = []

        changes_detected = plan_exit_code != 0
        if plan_exit_code in (0, 2):
            self.state = "Success"
        else:
            self.state = "Failed"

        if plan_exit_code != 2:
            return (
                plan_exit_code,
                init_stdout + ["\n"] + plan_stdout,
                changes_detected,
            )

        operation_exit_code, operation_stdout = execute_command(
            operation_args, print_output=False, capture_stderr=True, env=command_env
        )

        if operation_exit_code == 0:
            self.state = "Success"

        else:
            self.state = "Failed"

        print("\nFinished executing %s %s ..." % (self.abs_path, operation))
        return (
            operation_exit_code,
            init_stdout + ["\n"] + plan_stdout + ["\n"] + operation_stdout,
            changes_detected,
        )
