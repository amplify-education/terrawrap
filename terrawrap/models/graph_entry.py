"""Module for containing Graph Entries"""
from abc import ABC, abstractmethod

import os
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

        # We're using --no-resolve-envvars here because we've already resolved the environment variables in
        # the constructor. We are then passing in those environment variables explicitly in the
        # execute_command call below.
        base_args = ["tf", "--no-resolve-envvars", self.abs_path]
        init_args = base_args + ["init"] + self.variables
        operation_args = base_args + [operation] + self.variables

        init_exit_code, init_stdout = execute_command(
            init_args,
            print_output=False,
            capture_stderr=True,
            env=command_env,
        )
        if init_exit_code != 0:
            self.state = "Failed"
            return init_exit_code, init_stdout, True

        shell = False
        if operation in ["apply", "destroy"]:
            operation_args = ["yes", "yes", "|"] + operation_args
            shell = True

        operation_exit_code, operation_stdout = execute_command(
            " ".join(operation_args) if shell else operation_args,
            print_output=False,
            capture_stderr=True,
            env=command_env,
            shell=shell,
        )

        if operation_exit_code == 0:
            self.state = "Success"
        else:
            self.state = "Failed"

        changes_detected = True
        if any("Resources: 0 added, 0 changed, 0 destroyed" in line for line in operation_stdout):
            changes_detected = False

        print("\nFinished executing %s %s ..." % (self.abs_path, operation))
        return (
            operation_exit_code,
            init_stdout + ["\n"] + operation_stdout,
            changes_detected,
        )
