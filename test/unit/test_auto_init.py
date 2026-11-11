"""Tests for terrawrap.utils.auto_init"""

import contextlib
import io
import os
import shutil
import tempfile
from unittest import TestCase
from unittest.mock import ANY, patch

from terrawrap.models.wrapper_config import WrapperConfig
from terrawrap.utils.auto_init import (
    auto_init_backend,
    calc_init_backend_arguments,
    is_auto_init_eligible,
    is_backend_init_error,
    is_backend_uninitialized,
    resolve_auto_init,
)
from test.helpers.backend_errors import CHANGED_CONFIG_ERROR, INITIAL_CONFIG_ERROR

WRAPPED_REASON_ERROR = [
    'Error: Backend initialization required, please run "terraform init"\n',
    "Reason: Initial configuration of the\n",
    'requested backend "s3"\n',
]


class TestIsBackendInitError(TestCase):
    def setUp(self):
        self.path = tempfile.mkdtemp(prefix="71564ffd-")
        self.addCleanup(shutil.rmtree, self.path, ignore_errors=True)

    def _write_backend_state(self, data_dir=".terraform"):
        os.makedirs(os.path.join(self.path, data_dir), exist_ok=True)
        with open(os.path.join(self.path, data_dir, "terraform.tfstate"), "w", encoding="utf-8") as state:
            state.write("{}")

    def test_initial_configuration_matches(self):
        """The initial-configuration error from a fresh checkout triggers auto-init"""
        self.assertTrue(is_backend_init_error(INITIAL_CONFIG_ERROR, self.path, {}))

    def test_reason_wrapped_across_lines_matches(self):
        """Terraform hard-wraps diagnostics, so matching ignores line breaks"""
        self.assertTrue(is_backend_init_error(WRAPPED_REASON_ERROR, self.path, {}))

    def test_changed_backend_config_does_not_match(self):
        """-reconfigure on a changed backend could orphan state, so it must not auto-init"""
        self.assertFalse(is_backend_init_error(CHANGED_CONFIG_ERROR, self.path, {}))

    def test_unrelated_output_does_not_match(self):
        self.assertFalse(is_backend_init_error(["Error: Invalid provider configuration\n"], self.path, {}))

    def test_quoted_message_with_initialized_backend_does_not_match(self):
        """Output that merely quotes the message must not wipe an initialized .terraform"""
        self._write_backend_state()
        self.assertFalse(is_backend_init_error(INITIAL_CONFIG_ERROR, self.path, {}))

    def test_tf_data_dir_is_honored(self):
        self._write_backend_state(data_dir="custom-data")
        self.assertFalse(
            is_backend_init_error(INITIAL_CONFIG_ERROR, self.path, {"TF_DATA_DIR": "custom-data"})
        )
        self.assertTrue(is_backend_init_error(INITIAL_CONFIG_ERROR, self.path, {}))


class TestIsAutoInitEligible(TestCase):
    def test_state_backed_commands_are_eligible(self):
        for command in ("plan", "apply", "destroy", "refresh", "state", "output", "show"):
            with self.subTest(command=command):
                self.assertTrue(is_auto_init_eligible(command, []))

    def test_init_console_import_are_excluded(self):
        for command in ("init", "console", "import"):
            with self.subTest(command=command):
                self.assertFalse(is_auto_init_eligible(command, []))

    def test_help_is_excluded(self):
        self.assertFalse(is_auto_init_eligible("apply", ["-help"]))


class TestIsBackendUninitialized(TestCase):
    def setUp(self):
        self.path = tempfile.mkdtemp(prefix="71564ffd-")
        self.addCleanup(shutil.rmtree, self.path, ignore_errors=True)

    def _write_backend(self):
        with open(os.path.join(self.path, "backend.tf"), "w", encoding="utf-8") as backend_file:
            backend_file.write('terraform {\n  backend "s3" {}\n}\n')

    def test_backend_without_dot_terraform_is_uninitialized(self):
        self._write_backend()
        self.assertTrue(is_backend_uninitialized(self.path, {}))

    def test_backend_with_backend_state_is_initialized(self):
        self._write_backend()
        os.makedirs(os.path.join(self.path, ".terraform"))
        with open(os.path.join(self.path, ".terraform", "terraform.tfstate"), "w", encoding="utf-8") as state:
            state.write("{}")
        self.assertFalse(is_backend_uninitialized(self.path, {}))

    def test_tf_data_dir_is_honored(self):
        self._write_backend()
        os.makedirs(os.path.join(self.path, "custom-data"))
        with open(
            os.path.join(self.path, "custom-data", "terraform.tfstate"), "w", encoding="utf-8"
        ) as state:
            state.write("{}")
        self.assertFalse(is_backend_uninitialized(self.path, {"TF_DATA_DIR": "custom-data"}))
        self.assertTrue(is_backend_uninitialized(self.path, {}))

    def test_unsupported_backend_type_is_not_uninitialized(self):
        """A backend type terrawrap can't parse must not make apply/destroy crash"""
        with open(os.path.join(self.path, "backend.tf"), "w", encoding="utf-8") as backend_file:
            backend_file.write('terraform {\n  backend "local" {\n    path = "a.tfstate"\n  }\n}\n')
        self.assertFalse(is_backend_uninitialized(self.path, {}))

    def test_unparseable_config_is_not_uninitialized(self):
        """Any parse failure must not break apply/destroy, but the skipped pre-flight is reported"""
        stderr = io.StringIO()
        with (
            patch(
                "terrawrap.utils.auto_init.parse_backend_config_for_dir", side_effect=ValueError("bad hcl")
            ),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertFalse(is_backend_uninitialized(self.path, {}))
        self.assertIn(self.path, stderr.getvalue())
        self.assertIn("bad hcl", stderr.getvalue())

    def test_no_backend_block_is_not_uninitialized(self):
        """Directories without a backend block never hit the backend-init error"""
        self.assertFalse(is_backend_uninitialized(self.path, {}))


class TestCalcInitBackendArguments(TestCase):
    @patch("terrawrap.utils.auto_init.calc_backend_config")
    @patch("terrawrap.utils.auto_init.parse_backend_config_for_dir")
    def test_returns_backend_config_when_configured(self, parse_backend, calc_backend):
        parse_backend.return_value = {"s3": {}}
        calc_backend.return_value = ["-reconfigure", "-upgrade", "-backend-config=key=value"]
        wrapper_config = WrapperConfig()

        result = calc_init_backend_arguments("/dir", {"a": "b"}, wrapper_config)

        self.assertEqual(result, ["-reconfigure", "-upgrade", "-backend-config=key=value"])
        calc_backend.assert_called_once_with(
            path="/dir",
            variables={"a": "b"},
            wrapper_config=wrapper_config,
            existing_backend_config={"s3": {}},
        )

    @patch("terrawrap.utils.auto_init.calc_backend_config")
    @patch("terrawrap.utils.auto_init.parse_backend_config_for_dir")
    def test_upgrade_false_drops_upgrade_flag(self, parse_backend, calc_backend):
        """Auto-init keeps providers pinned to the lock file by omitting -upgrade"""
        parse_backend.return_value = {"s3": {}}
        calc_backend.return_value = ["-reconfigure", "-upgrade", "-backend-config=key=value"]

        result = calc_init_backend_arguments("/dir", {}, WrapperConfig(), upgrade=False)

        self.assertEqual(result, ["-reconfigure", "-backend-config=key=value"])

    @patch("terrawrap.utils.auto_init.parse_backend_config_for_dir")
    def test_returns_empty_when_configure_backend_disabled(self, parse_backend):
        self.assertEqual(calc_init_backend_arguments("/dir", {}, WrapperConfig(configure_backend=False)), [])
        parse_backend.assert_not_called()

    @patch("terrawrap.utils.auto_init.parse_backend_config_for_dir")
    def test_returns_empty_without_backend_block(self, parse_backend):
        parse_backend.return_value = None
        self.assertEqual(calc_init_backend_arguments("/dir", {}, WrapperConfig()), [])


class TestAutoInitBackend(TestCase):
    @patch("terrawrap.utils.auto_init.shutil.rmtree")
    @patch("terrawrap.utils.auto_init.download_plugins")
    @patch("terrawrap.utils.auto_init.execute_command", return_value=(0, []))
    @patch("terrawrap.utils.auto_init.calc_init_backend_arguments", return_value=["-reconfigure"])
    @patch("terrawrap.utils.auto_init.parse_variable_files", return_value={"v": "1"})
    @patch("terrawrap.utils.auto_init.find_variable_files", return_value=["vars.tfvars"])
    def test_loads_variables_and_runs_init_like_explicit_init(
        self, find_vars, parse_vars, init_args, execute, plugins, rmtree
    ):
        """Variables select the backend bucket/key, so they load regardless of the triggering command"""
        wrapper_config = WrapperConfig()

        exit_code = auto_init_backend("/abs", wrapper_config, {"EXTRA": "x"})

        self.assertEqual(exit_code, 0)
        find_vars.assert_called_once_with(path="/abs")
        parse_vars.assert_called_once_with(variable_files=["vars.tfvars"])
        init_args.assert_called_once_with("/abs", {"v": "1"}, wrapper_config, upgrade=False)
        plugins.assert_called_once_with(wrapper_config)
        rmtree.assert_called_once()
        called = execute.call_args
        self.assertEqual(called.args[0], ["terraform", "init", "-reconfigure"])
        self.assertEqual(called.kwargs["cwd"], "/abs")
        self.assertEqual(called.kwargs["env"]["TF_VAR_v"], "1")
        self.assertEqual(called.kwargs["env"]["EXTRA"], "x")
        self.assertEqual(called.kwargs["env"]["TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE"], "true")


@patch("terrawrap.utils.auto_init.auto_init_backend", return_value=0)
class TestResolveAutoInit(TestCase):
    def _resolve(self, command, wrapper_config=None, uninitialized=True, disabled=False):
        with patch("terrawrap.utils.auto_init.is_backend_uninitialized", return_value=uninitialized):
            return resolve_auto_init(command, [], "/abs", wrapper_config or WrapperConfig(), {}, disabled)

    def test_apply_inits_up_front_when_uninitialized(self, auto_init_backend_mock):
        self.assertIsNone(self._resolve("apply"))
        auto_init_backend_mock.assert_called_once()

    def test_destroy_inits_up_front_when_uninitialized(self, auto_init_backend_mock):
        self.assertIsNone(self._resolve("destroy"))
        auto_init_backend_mock.assert_called_once()

    def test_failed_up_front_init_exits(self, auto_init_backend_mock):
        auto_init_backend_mock.return_value = 4
        with self.assertRaises(SystemExit) as raised:
            self._resolve("apply")
        self.assertEqual(raised.exception.code, 4)

    def test_apply_returns_callable_when_already_initialized(self, auto_init_backend_mock):
        self.assertIsNotNone(self._resolve("apply", uninitialized=False))
        auto_init_backend_mock.assert_not_called()

    def test_other_commands_return_callable_without_initializing(self, auto_init_backend_mock):
        self.assertIsNotNone(self._resolve("plan"))
        auto_init_backend_mock.assert_not_called()

    def test_callable_runs_auto_init_backend(self, auto_init_backend_mock):
        self._resolve("plan")()
        auto_init_backend_mock.assert_called_once_with("/abs", unittest_any(), {})

    def test_disabled_by_flag(self, auto_init_backend_mock):
        self.assertIsNone(self._resolve("apply", disabled=True))
        auto_init_backend_mock.assert_not_called()

    def test_disabled_by_wrapper_config(self, auto_init_backend_mock):
        self.assertIsNone(self._resolve("apply", wrapper_config=WrapperConfig(auto_init=False)))
        auto_init_backend_mock.assert_not_called()

    def test_init_is_never_auto_initialized(self, auto_init_backend_mock):
        self.assertIsNone(self._resolve("init"))
        auto_init_backend_mock.assert_not_called()


def unittest_any():
    return ANY


@patch("terrawrap.utils.auto_init.auto_init_backend", return_value=0)
class TestResolveAutoInitDetection(TestCase):
    """resolve_auto_init with the real backend detector against a directory on disk"""

    def setUp(self):
        self.path = tempfile.mkdtemp(prefix="71564ffd-")
        self.addCleanup(shutil.rmtree, self.path, ignore_errors=True)

    def _write_backend(self):
        with open(os.path.join(self.path, "backend.tf"), "w", encoding="utf-8") as backend_file:
            backend_file.write('terraform {\n  backend "s3" {}\n}\n')

    def test_apply_with_uninitialized_backend_inits_up_front(self, auto_init_backend_mock):
        self._write_backend()

        self.assertIsNone(resolve_auto_init("apply", [], self.path, WrapperConfig(), {}, False))

        auto_init_backend_mock.assert_called_once()

    def test_apply_with_initialized_backend_does_not_init(self, auto_init_backend_mock):
        self._write_backend()
        os.makedirs(os.path.join(self.path, ".terraform"))
        with open(os.path.join(self.path, ".terraform", "terraform.tfstate"), "w", encoding="utf-8") as state:
            state.write("{}")

        self.assertIsNotNone(resolve_auto_init("apply", [], self.path, WrapperConfig(), {}, False))

        auto_init_backend_mock.assert_not_called()

    def test_apply_without_backend_block_does_not_init(self, auto_init_backend_mock):
        self.assertIsNotNone(resolve_auto_init("apply", [], self.path, WrapperConfig(), {}, False))

        auto_init_backend_mock.assert_not_called()
