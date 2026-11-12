"""Tests for bin/tf's argument parsing, incl. --no-version-check"""

import importlib.machinery
import importlib.util
import os
from unittest import TestCase
from unittest.mock import Mock, patch

from terrawrap.models.wrapper_config import WrapperConfig
from test.helpers.backend_errors import CHANGED_CONFIG_ERROR, INITIAL_CONFIG_ERROR

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
        self.assertEqual(result, ("dir", "plan", ["-lock=false"], True, False, False))

    def test_no_version_check_flag_alone(self):
        """--no-version-check is stripped, reported, and does not disable envvar resolution"""
        result = self.mod.process_arguments(["tf", "--no-version-check", "dir", "plan"])
        self.assertEqual(result, ("dir", "plan", [], True, True, False))

    def test_no_resolve_envvars_flag_alone(self):
        """--no-resolve-envvars is stripped and reported without affecting the version check"""
        result = self.mod.process_arguments(["tf", "--no-resolve-envvars", "dir", "plan"])
        self.assertEqual(result, ("dir", "plan", [], False, False, False))

    def test_both_flags_together(self):
        """Both leading flags are stripped and both booleans reflect the flags passed"""
        result = self.mod.process_arguments(
            ["tf", "--no-resolve-envvars", "--no-version-check", "dir", "init", "-upgrade"]
        )
        self.assertEqual(result, ("dir", "init", ["-upgrade"], False, True, False))

    def test_no_auto_init_flag_alone(self):
        """--no-auto-init is stripped and reported without affecting the other flags"""
        result = self.mod.process_arguments(["tf", "--no-auto-init", "dir", "apply"])
        self.assertEqual(result, ("dir", "apply", [], True, False, True))

    def test_all_flags_together(self):
        result = self.mod.process_arguments(
            ["tf", "--no-auto-init", "--no-resolve-envvars", "--no-version-check", "dir", "plan"]
        )
        self.assertEqual(result, ("dir", "plan", [], False, True, True))


class TestExecTfCommandConsole(TestCase):
    """`console` bypasses execute_command's capture-to-file path entirely,
    since terraform's own line editor only echoes typed input when it detects
    stdout is a real terminal."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_tf_module()

    def test_console_runs_with_inherited_stdio_and_skips_execute_command(self):
        """console execs terraform directly (no stdout/stdin redirection) and
        never goes through the capture-to-file path used by other commands.
        Variables reach terraform only via TF_VAR_* env (console never gets
        `-var` arguments appended), so `env` must still carry them through the
        bypass."""
        with (
            patch.object(self.mod, "execute_command") as mock_execute_command,
            patch.object(self.mod.subprocess, "run") as mock_run,
        ):
            mock_run.return_value.returncode = 0

            with self.assertRaises(SystemExit) as raised:
                self.mod.exec_tf_command(
                    command="console",
                    path="/some/path",
                    variables={"foo": "bar"},
                    arguments=[],
                    additional_envvars={"EXTRA_ENVVAR": "baz"},
                    audit_api_url=None,
                )

        self.assertEqual(raised.exception.code, 0)
        mock_execute_command.assert_not_called()
        mock_run.assert_called_once()
        called_args, called_kwargs = mock_run.call_args
        self.assertEqual(called_args[0], ["terraform", "console"])
        self.assertEqual(called_kwargs["cwd"], "/some/path")
        self.assertEqual(called_kwargs["env"]["TF_VAR_foo"], "bar")
        self.assertEqual(called_kwargs["env"]["EXTRA_ENVVAR"], "baz")
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


class TestExecTfCommandAutoInit(TestCase):
    """exec_tf_command runs auto_init once on a never-initialized backend, then retries the command."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_tf_module()

    def _exec(self, auto_init, command="apply"):
        return self.mod.exec_tf_command(
            command=command,
            path="/some/path",
            variables={},
            arguments=[],
            additional_envvars={},
            audit_api_url=None,
            auto_init=auto_init,
        )

    def test_retries_command_after_successful_auto_init(self):
        auto_init = Mock(return_value=0)
        with patch.object(self.mod, "execute_command") as mock_execute:
            mock_execute.side_effect = [(1, INITIAL_CONFIG_ERROR), (0, ["ok"])]
            with self.assertRaises(SystemExit) as raised:
                self._exec(auto_init)

        self.assertEqual(raised.exception.code, 0)
        auto_init.assert_called_once_with()
        self.assertEqual(mock_execute.call_count, 2)
        self.assertEqual(mock_execute.call_args_list[1].args[0], ["terraform", "apply"])

    def test_auto_init_runs_at_most_once(self):
        """A persistent init-required error after init fails instead of looping"""
        auto_init = Mock(return_value=0)
        with patch.object(self.mod, "execute_command") as mock_execute:
            mock_execute.return_value = (1, INITIAL_CONFIG_ERROR)
            with self.assertRaises(SystemExit) as raised:
                self._exec(auto_init)

        self.assertEqual(raised.exception.code, 1)
        auto_init.assert_called_once_with()
        self.assertEqual(mock_execute.call_count, 2)

    def test_failed_auto_init_exits_with_its_code_without_retrying(self):
        auto_init = Mock(return_value=3)
        with patch.object(self.mod, "execute_command") as mock_execute:
            mock_execute.return_value = (1, INITIAL_CONFIG_ERROR)
            with self.assertRaises(SystemExit) as raised:
                self._exec(auto_init)

        self.assertEqual(raised.exception.code, 3)
        self.assertEqual(mock_execute.call_count, 1)

    def test_changed_backend_config_does_not_auto_init(self):
        auto_init = Mock(return_value=0)
        with patch.object(self.mod, "execute_command") as mock_execute:
            mock_execute.return_value = (1, CHANGED_CONFIG_ERROR)
            with self.assertRaises(SystemExit) as raised:
                self._exec(auto_init)

        self.assertEqual(raised.exception.code, 1)
        auto_init.assert_not_called()

    def test_disabled_auto_init_preserves_failure(self):
        with patch.object(self.mod, "execute_command") as mock_execute:
            mock_execute.return_value = (1, INITIAL_CONFIG_ERROR)
            with self.assertRaises(SystemExit) as raised:
                self._exec(None)

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(mock_execute.call_count, 1)


class TestHandlerAutoInit(TestCase):
    """handler() hands the resolved auto-init callable to exec_tf_command"""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_tf_module()

    def test_passes_resolved_callable_and_flag(self):
        wrapper_config = WrapperConfig()
        resolved = Mock()
        with (
            patch.object(self.mod.sys, "argv", ["tf", "--no-auto-init", "dir", "plan"]),
            patch.object(self.mod, "version_check"),
            patch.object(self.mod, "get_absolute_path", return_value="/abs"),
            patch.object(self.mod.os.path, "isdir", return_value=True),
            patch.object(self.mod, "find_wrapper_config_files", return_value=[]),
            patch.object(self.mod, "parse_wrapper_configs", return_value=wrapper_config),
            patch.object(self.mod, "find_variable_files", return_value=[]),
            patch.object(self.mod, "parse_variable_files", return_value={}),
            patch.object(self.mod, "resolve_auto_init", return_value=resolved) as mock_resolve,
            patch.object(self.mod, "exec_tf_command") as mock_exec,
        ):
            self.mod.handler()

        mock_resolve.assert_called_once_with("plan", [], "/abs", wrapper_config, {}, True)
        self.assertIs(mock_exec.call_args.kwargs["auto_init"], resolved)


class TestHandlerInit(TestCase):
    """`tf <dir> init` prepends the backend arguments and downloads plugins"""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_tf_module()

    def test_init_passes_backend_arguments_and_downloads_plugins(self):
        wrapper_config = WrapperConfig()
        with (
            patch.object(self.mod.sys, "argv", ["tf", "--no-version-check", "dir", "init", "-input=false"]),
            patch.object(self.mod, "get_absolute_path", return_value="/abs"),
            patch.object(self.mod.os.path, "isdir", return_value=True),
            patch.object(self.mod, "find_wrapper_config_files", return_value=[]),
            patch.object(self.mod, "parse_wrapper_configs", return_value=wrapper_config),
            patch.object(self.mod, "find_variable_files", return_value=[]),
            patch.object(self.mod, "parse_variable_files", return_value={"v": "1"}),
            patch.object(
                self.mod, "calc_init_backend_arguments", return_value=["-reconfigure", "-upgrade"]
            ) as mock_args,
            patch.object(self.mod, "download_plugins") as mock_plugins,
            patch.object(self.mod, "resolve_auto_init", return_value=None),
            patch.object(self.mod, "exec_tf_command") as mock_exec,
        ):
            self.mod.handler()

        mock_args.assert_called_once_with("/abs", {"v": "1"}, wrapper_config)
        mock_plugins.assert_called_once_with(wrapper_config)
        self.assertEqual(
            mock_exec.call_args.kwargs["arguments"], ["-reconfigure", "-upgrade", "-input=false"]
        )
