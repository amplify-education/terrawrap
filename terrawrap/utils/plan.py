"""Helpers for processing terraform plan output."""

import os
import sys
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from terrawrap.utils.cli import execute_command


class PlanExitCode(Enum):
    """Exit codes produced by `terraform plan -detailed-exitcode`, reused for `show`."""

    SUCCESS_NO_DIFF = 0
    FAILURE = 1
    SUCCESS_WITH_DIFF = 2


def extract_show_json(stdout_lines: List[str], exit_code: Optional[int] = None) -> str:
    """
    Extract the JSON output of `terraform show -json` from a captured stdout
    stream that may contain non-JSON noise (the `tf` wrapper's command echo,
    deprecation warnings, lockfile notices, etc.) interleaved before the JSON.

    `terraform show -json` emits the plan as a single JSON object, so we locate
    the first line whose first non-whitespace character is `{` and treat
    everything from there onward as the JSON document.

    :param stdout_lines: Lines captured from the command's stdout, each
        retaining its trailing newline as returned by `readlines()`.
    :param exit_code: The command's exit code, included in the error message
        when raised so a caller can tell "exited 0 but wrote nothing" apart
        from a non-FAILURE exit code that still produced no JSON.
    :return: The JSON content as a single string.
    :raises RuntimeError: If no JSON line is found.
    """
    for i, line in enumerate(stdout_lines):
        if line.lstrip().startswith("{"):
            return "".join(stdout_lines[i:])

    code_note = f" (exit code {exit_code})" if exit_code is not None else ""
    captured = "".join(stdout_lines[-50:]).strip()
    body = captured if captured else "<no output captured>"
    raise RuntimeError(f"no JSON object found in `terraform show -json` output{code_note}: {body}")


def convert_plan_to_json(
    plan_binary_file: Path,
    source_directory: Path,
    additional_envvars: Dict[str, Optional[str]],
    wrapper_script: str,
) -> Path:
    """
    Converts binary terraform plan to json. Saves it in the same directory.

    Retries the `terraform show -json` conversion once if the first attempt exits
    without the FAILURE code but still produces no JSON — an intermittent failure
    mode observed under high --parallel-jobs concurrency (see CHANGELOG) that a
    same-input retry reliably clears.

    :param plan_binary_file: File with a plan saved in a binary format
    :param source_directory: Directory with source terraform files
    :param additional_envvars: A dictionary representing additional environment variables to supply
    :param wrapper_script: Path to the `tf` wrapper executable to invoke `show -json` through
    :return: Path object pointing to a json plan file
    """
    command_env: Dict[str, Optional[str]] = dict(os.environ)
    command_env.update(additional_envvars)

    show_command = [
        wrapper_script,
        "--no-version-check",
        str(source_directory),
        "show",
        "-json",
        str(plan_binary_file),
    ]

    def run_show() -> Tuple[List[str], int]:
        exit_code, stdout = execute_command(show_command, print_output=False, env=command_env)
        if exit_code == PlanExitCode.FAILURE.value:
            raise RuntimeError(f"'terraform show' failed for {plan_binary_file}:\n{''.join(stdout)}")
        return stdout, exit_code

    stdout, exit_code = run_show()
    try:
        show_json = extract_show_json(stdout, exit_code=exit_code)
    except RuntimeError as exception:
        print(
            f"Warning: retrying 'terraform show -json' for {plan_binary_file} "
            f"after an empty conversion attempt: {exception}",
            file=sys.stderr,
        )
        stdout, exit_code = run_show()
        show_json = extract_show_json(stdout, exit_code=exit_code)

    plan_json_file = plan_binary_file.parent / "tfplan.json"
    with plan_json_file.open("w") as plan_json_stream:
        plan_json_stream.write(show_json)

    return plan_json_file
