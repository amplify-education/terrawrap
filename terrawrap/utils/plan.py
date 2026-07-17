"""Helpers for processing terraform plan output."""

from typing import List


def extract_show_json(stdout_lines: List[str]) -> str:
    """
    Extract the JSON output of `terraform show -json` from a captured stdout
    stream that may contain non-JSON noise (the `tf` wrapper's command echo,
    deprecation warnings, lockfile notices, etc.) interleaved before the JSON.

    `terraform show -json` emits the plan as a single JSON object, so we locate
    the first line whose first non-whitespace character is `{` and treat
    everything from there onward as the JSON document.

    :param stdout_lines: Lines captured from the command's stdout, each
        retaining its trailing newline as returned by `readlines()`.
    :return: The JSON content as a single string.
    :raises RuntimeError: If no JSON line is found.
    """
    for i, line in enumerate(stdout_lines):
        if line.lstrip().startswith("{"):
            return "".join(stdout_lines[i:])
    raise RuntimeError(
        f"no JSON object found in `terraform show -json` output: {''.join(stdout_lines[-50:])}"
    )
