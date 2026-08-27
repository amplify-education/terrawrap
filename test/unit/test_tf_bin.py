"""Tests for bin/tf's argument parsing, incl. --no-version-check"""

import importlib.machinery
import importlib.util
import os
from unittest import TestCase
from unittest.mock import patch

_BIN_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "bin", "tf"))


def _load_tf_module():
    """Load bin/tf (no .py extension) as a module via SourceFileLoader."""
    loader = importlib.machinery.SourceFileLoader("tf_bin", _BIN_PATH)
    spec = importlib.util.spec_from_loader("tf_bin", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestProcessArguments(TestCase):
    """process_arguments strips leading optional flags, in any combination, in one pass"""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_tf_module()

    def test_no_flags(self):
        """Parses path/command/arguments with no optional flags present"""
        result = self.mod.process_arguments(["tf", "dir", "plan", "-lock=false"])
        self.assertEqual(result, ("dir", "plan", ["-lock=false"], True, False))

    def test_no_version_check_flag_alone(self):
        """--no-version-check is stripped, reported, and does not disable envvar resolution"""
        result = self.mod.process_arguments(["tf", "--no-version-check", "dir", "plan"])
        self.assertEqual(result, ("dir", "plan", [], True, True))

    def test_no_resolve_envvars_flag_alone(self):
        """--no-resolve-envvars is stripped and reported without affecting the version check"""
        result = self.mod.process_arguments(["tf", "--no-resolve-envvars", "dir", "plan"])
        self.assertEqual(result, ("dir", "plan", [], False, False))

    def test_both_flags_together(self):
        """Both leading flags are stripped and both booleans reflect the flags passed"""
        result = self.mod.process_arguments(
            ["tf", "--no-resolve-envvars", "--no-version-check", "dir", "init", "-upgrade"]
        )
        self.assertEqual(result, ("dir", "init", ["-upgrade"], False, True))


class TestExecTfCommandConsole(TestCase):
    """`console` bypasses execute_command's capture-to-file path entirely,
    since terraform's own line editor only echoes typed input when it detects
    stdout is a real terminal."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_tf_module()

    def test_console_runs_with_inherited_stdio_and_skips_execute_command(self):
        """console execs terraform directly (no stdout/stdin redirection) and
        never goes through the capture-to-file path used by other commands."""
        with (
            patch.object(self.mod, "execute_command") as mock_execute_command,
            patch.object(self.mod.subprocess, "run") as mock_run,
        ):
            mock_run.return_value.returncode = 0

            with self.assertRaises(SystemExit) as raised:
                self.mod.exec_tf_command(
                    command="console",
                    path="/some/path",
                    variables={},
                    arguments=["-var", "foo=bar"],
                    additional_envvars={},
                    audit_api_url=None,
                )

        self.assertEqual(raised.exception.code, 0)
        mock_execute_command.assert_not_called()
        mock_run.assert_called_once()
        called_args, called_kwargs = mock_run.call_args
        self.assertEqual(called_args[0], ["terraform", "console", "-var", "foo=bar"])
        self.assertEqual(called_kwargs["cwd"], "/some/path")
        self.assertNotIn("stdout", called_kwargs)
        self.assertNotIn("stdin", called_kwargs)

    def test_console_exits_with_terraform_return_code(self):
        """A non-zero console exit code (e.g. Ctrl-D vs. a crash) propagates."""
        with patch.object(self.mod, "execute_command"), patch.object(self.mod.subprocess, "run") as mock_run:
            mock_run.return_value.returncode = 1

            with self.assertRaises(SystemExit) as raised:
                self.mod.exec_tf_command(
                    command="console",
                    path="/some/path",
                    variables={},
                    arguments=[],
                    additional_envvars={},
                    audit_api_url=None,
                )

        self.assertEqual(raised.exception.code, 1)
