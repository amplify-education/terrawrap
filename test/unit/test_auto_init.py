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
    find_uninitialized_backend,
    is_auto_init_eligible,
    is_backend_init_error,
    prepare_init,
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


class TestFindUninitializedBackend(TestCase):
    def setUp(self):
        self.path = tempfile.mkdtemp(prefix="71564ffd-")
        self.addCleanup(shutil.rmtree, self.path, ignore_errors=True)

    def _write_backend(self):
        with open(os.path.join(self.path, "backend.tf"), "w", encoding="utf-8") as backend_file:
            backend_file.write('terraform {\n  backend "s3" {}\n}\n')

    def test_backend_without_dot_terraform_is_uninitialized(self):
        self._write_backend()
        self.assertIsNotNone(find_uninitialized_backend(self.path, {}))

    def test_backend_with_backend_state_is_initialized(self):
        self._write_backend()
        os.makedirs(os.path.join(self.path, ".terraform"))
        with open(os.path.join(self.path, ".terraform", "terraform.tfstate"), "w", encoding="utf-8") as state:
            state.write("{}")
        self.assertIsNone(find_uninitialized_backend(self.path, {}))

    def test_initialized_backend_skips_hcl_parsing(self):
        """Parsing takes up to ~1s in large directories, so an initialized backend must not pay for it"""
        os.makedirs(os.path.join(self.path, ".terraform"))
        with open(os.path.join(self.path, ".terraform", "terraform.tfstate"), "w", encoding="utf-8") as state:
            state.write("{}")
        with patch("terrawrap.utils.auto_init.parse_backend_config_for_dir") as parse_backend:
            self.assertIsNone(find_uninitialized_backend(self.path, {}))
        parse_backend.assert_not_called()

    def test_tf_data_dir_is_honored(self):
        self._write_backend()
        os.makedirs(os.path.join(self.path, "custom-data"))
        with open(
            os.path.join(self.path, "custom-data", "terraform.tfstate"), "w", encoding="utf-8"
        ) as state:
            state.write("{}")
        self.assertIsNone(find_uninitialized_backend(self.path, {"TF_DATA_DIR": "custom-data"}))
        self.assertIsNotNone(find_uninitialized_backend(self.path, {}))

    def test_unsupported_backend_type_is_not_uninitialized(self):
        """A backend type terrawrap can't parse must not make apply/destroy crash"""
        with open(os.path.join(self.path, "backend.tf"), "w", encoding="utf-8") as backend_file:
            backend_file.write('terraform {\n  backend "local" {\n    path = "a.tfstate"\n  }\n}\n')
        self.assertIsNone(find_uninitialized_backend(self.path, {}))

    def test_unparseable_config_is_not_uninitialized(self):
        """Any parse failure must not break apply/destroy, but the skipped pre-flight is reported"""
        stderr = io.StringIO()
        with (
            patch(
                "terrawrap.utils.auto_init.parse_backend_config_for_dir", side_effect=ValueError("bad hcl")
            ),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertIsNone(find_uninitialized_backend(self.path, {}))
        self.assertIn(self.path, stderr.getvalue())
        self.assertIn("bad hcl", stderr.getvalue())

    def test_unexpected_parser_bug_propagates(self):
        """Only the parser's own failures are downgraded to a warning; a bug must not be hidden"""
        with patch("terrawrap.utils.auto_init.parse_backend_config_for_dir", side_effect=TypeError("bug")):
            with self.assertRaises(TypeError):
                find_uninitialized_backend(self.path, {})

    def test_no_backend_block_is_not_uninitialized(self):
        """Directories without a backend block never hit the backend-init error"""
        self.assertIsNone(find_uninitialized_backend(self.path, {}))


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

    @patch("terrawrap.utils.config.calc_repo_path", return_value="repo/dir")
    def test_real_backend_config_flag_is_dropped_by_upgrade_false(self, _repo_path):
        """The filter must match the literal calc_backend_config emits, not a hand-written stand-in"""
        path = tempfile.mkdtemp(prefix="3f1c9a7e-")
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        with open(os.path.join(path, "backend.tf"), "w", encoding="utf-8") as backend_file:
            backend_file.write('terraform {\n  backend "s3" {}\n}\n')

        with_upgrade = calc_init_backend_arguments(path, {}, WrapperConfig())
        without_upgrade = calc_init_backend_arguments(path, {}, WrapperConfig(), upgrade=False)

        self.assertIn("-upgrade", with_upgrade)
        self.assertNotIn("-upgrade", without_upgrade)
        self.assertEqual([a for a in with_upgrade if a != "-upgrade"], without_upgrade)

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
        init_args.assert_called_once_with(
            "/abs", {"v": "1"}, wrapper_config, upgrade=False, existing_backend_config=None
        )
        plugins.assert_called_once_with(wrapper_config)
        rmtree.assert_called_once()
        called = execute.call_args
        self.assertEqual(called.args[0], ["terraform", "init", "-input=false", "-reconfigure"])
        self.assertEqual(called.kwargs["cwd"], "/abs")
        self.assertEqual(called.kwargs["env"]["TF_VAR_v"], "1")
        self.assertEqual(called.kwargs["env"]["EXTRA"], "x")
        self.assertEqual(called.kwargs["env"]["TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE"], "true")

    @patch("terrawrap.utils.auto_init.shutil.rmtree")
    @patch("terrawrap.utils.auto_init.download_plugins")
    @patch("terrawrap.utils.auto_init.calc_init_backend_arguments", return_value=[])
    @patch("terrawrap.utils.auto_init.parse_variable_files", return_value={})
    @patch("terrawrap.utils.auto_init.find_variable_files", return_value=[])
    @patch("terrawrap.utils.auto_init.execute_command")
    def test_keeps_stdout_clean_for_machine_readable_output(self, execute, *_):
        """`tf <dir> output -json` must see only its own output on stdout after a first-run init"""

        def noisy_init(*_args, **_kwargs):
            print("Executing: terraform init")
            print("Terraform has been successfully initialized!")
            return 0, []

        execute.side_effect = noisy_init
        stdout, stderr = io.StringIO(), io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            auto_init_backend("/abs", WrapperConfig(), {})

        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Backend is not initialized", stderr.getvalue())
        self.assertIn("successfully initialized", stderr.getvalue())

    @patch("terrawrap.utils.auto_init.shutil.rmtree")
    @patch("terrawrap.utils.auto_init.download_plugins")
    @patch("terrawrap.utils.auto_init.parse_variable_files", return_value={})
    @patch("terrawrap.utils.auto_init.find_variable_files", return_value=[])
    @patch("terrawrap.utils.auto_init.execute_command", return_value=(4, []))
    def test_failed_init_returns_its_exit_code_and_says_the_command_did_not_run(self, execute, *_):
        stderr = io.StringIO()

        with (
            contextlib.redirect_stderr(stderr),
            patch("terrawrap.utils.auto_init.calc_init_backend_arguments", return_value=[]),
        ):
            exit_code = auto_init_backend("/abs", WrapperConfig(), {})

        self.assertEqual(exit_code, 4)
        self.assertIn("exit code 4", stderr.getvalue())
        self.assertIn("--no-auto-init", stderr.getvalue())
        execute.assert_called_once()

    @patch("terrawrap.utils.auto_init.download_plugins")
    @patch("terrawrap.utils.auto_init.parse_variable_files", return_value={})
    @patch("terrawrap.utils.auto_init.find_variable_files", return_value=[])
    @patch("terrawrap.utils.auto_init.execute_command")
    @patch("terrawrap.utils.auto_init.parse_backend_config_for_dir", side_effect=ValueError("bad hcl"))
    def test_unreadable_backend_config_fails_with_guidance_instead_of_a_traceback(self, _parse, execute, *_):
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            exit_code = auto_init_backend("/abs", WrapperConfig(), {})

        self.assertEqual(exit_code, 1)
        self.assertIn("bad hcl", stderr.getvalue())
        self.assertIn("--no-auto-init", stderr.getvalue())
        execute.assert_not_called()

    @patch("terrawrap.utils.auto_init.shutil.rmtree")
    @patch("terrawrap.utils.auto_init.download_plugins")
    @patch("terrawrap.utils.auto_init.parse_variable_files", return_value={})
    @patch("terrawrap.utils.auto_init.find_variable_files", return_value=[])
    @patch("terrawrap.utils.auto_init.execute_command", return_value=(0, []))
    @patch("terrawrap.utils.auto_init.parse_backend_config_for_dir")
    @patch("terrawrap.utils.auto_init.calc_backend_config", return_value=["-reconfigure"])
    def test_reuses_an_already_parsed_backend_config(self, _calc, parse_backend, *_):
        """The pre-flight already parsed the HCL; parsing it again costs up to ~1s in large directories"""
        auto_init_backend("/abs", WrapperConfig(), {}, backend_config={"s3": {}})

        parse_backend.assert_not_called()


class TestPrepareInit(TestCase):
    def setUp(self):
        self.path = tempfile.mkdtemp(prefix="9b2d41c0-")
        self.addCleanup(shutil.rmtree, self.path, ignore_errors=True)

    def _touch(self, *parts):
        file_path = os.path.join(self.path, *parts)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as touched:
            touched.write("x")
        return file_path

    def test_removes_default_data_dir(self):
        data_file = self._touch(".terraform", "terraform.tfstate")

        prepare_init(self.path, {})

        self.assertFalse(os.path.exists(data_file))

    def test_removes_the_data_dir_named_by_tf_data_dir_and_leaves_dot_terraform(self):
        custom = self._touch("custom-data", "terraform.tfstate")
        default = self._touch(".terraform", "keep")

        prepare_init(self.path, {"TF_DATA_DIR": "custom-data"})

        self.assertFalse(os.path.exists(custom))
        self.assertTrue(os.path.exists(default))

    def test_never_removes_the_configuration_directory(self):
        """TF_DATA_DIR=. (or a parent) would otherwise delete the configuration being initialized"""
        config_file = self._touch("main.tf")

        prepare_init(self.path, {"TF_DATA_DIR": "."})
        prepare_init(self.path, {"TF_DATA_DIR": ".."})

        self.assertTrue(os.path.exists(config_file))

    def test_never_removes_a_directory_outside_the_configuration_directory(self):
        """TF_DATA_DIR can come from a checked-in .tf_wrapper, so it must not name arbitrary directories"""
        outside = tempfile.mkdtemp(prefix="c41e7d02-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        victim = os.path.join(outside, "precious")
        with open(victim, "w", encoding="utf-8") as precious:
            precious.write("x")
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            prepare_init(self.path, {"TF_DATA_DIR": outside})

        self.assertTrue(os.path.exists(victim))
        self.assertIn("Not clearing TF_DATA_DIR", stderr.getvalue())

    def test_does_not_follow_a_symlinked_data_dir(self):
        outside = tempfile.mkdtemp(prefix="c41e7d02-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        victim = os.path.join(outside, "precious")
        with open(victim, "w", encoding="utf-8") as precious:
            precious.write("x")
        os.symlink(outside, os.path.join(self.path, ".terraform"))

        prepare_init(self.path, {})

        self.assertTrue(os.path.exists(victim))


@patch("terrawrap.utils.auto_init.auto_init_backend", return_value=0)
class TestResolveAutoInit(TestCase):
    def _resolve(self, command, wrapper_config=None, uninitialized=True, disabled=False):
        found = object() if uninitialized else None
        with patch("terrawrap.utils.auto_init.find_uninitialized_backend", return_value=found):
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

    def test_backend_reading_commands_init_up_front_when_uninitialized(self, auto_init_backend_mock):
        """output/show/state/plan... read the backend, so their failed first attempt must never print"""
        for command in ("plan", "output", "show", "state", "workspace", "refresh", "taint"):
            with self.subTest(command=command):
                auto_init_backend_mock.reset_mock()
                self.assertIsNone(self._resolve(command))
                auto_init_backend_mock.assert_called_once()

    def test_up_front_init_receives_the_parsed_backend_config(self, auto_init_backend_mock):
        self._resolve("output")
        self.assertIsNotNone(auto_init_backend_mock.call_args.kwargs["backend_config"])

    def test_backend_free_commands_are_not_initialized_up_front(self, auto_init_backend_mock):
        """fmt/validate/version/get/test run without a backend; initializing for them would be a surprise"""
        for command in ("fmt", "validate", "version", "get", "test"):
            with self.subTest(command=command):
                self.assertIsNotNone(self._resolve(command))
                auto_init_backend_mock.assert_not_called()

    def test_callable_runs_auto_init_backend(self, auto_init_backend_mock):
        self._resolve("validate")()
        auto_init_backend_mock.assert_called_once_with("/abs", ANY, {})

    def test_disabled_by_flag(self, auto_init_backend_mock):
        self.assertIsNone(self._resolve("apply", disabled=True))
        auto_init_backend_mock.assert_not_called()

    def test_disabled_by_wrapper_config(self, auto_init_backend_mock):
        self.assertIsNone(self._resolve("apply", wrapper_config=WrapperConfig(auto_init=False)))
        auto_init_backend_mock.assert_not_called()

    def test_init_is_never_auto_initialized(self, auto_init_backend_mock):
        self.assertIsNone(self._resolve("init"))
        auto_init_backend_mock.assert_not_called()


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

    def test_apply_honors_process_environment_tf_data_dir(self, auto_init_backend_mock):
        """An exported TF_DATA_DIR relocates the state file; ignoring it would re-init every apply"""
        self._write_backend()
        os.makedirs(os.path.join(self.path, "custom-data"))
        with open(
            os.path.join(self.path, "custom-data", "terraform.tfstate"), "w", encoding="utf-8"
        ) as state:
            state.write("{}")

        with patch.dict(os.environ, {"TF_DATA_DIR": "custom-data"}):
            self.assertIsNotNone(resolve_auto_init("apply", [], self.path, WrapperConfig(), {}, False))

        auto_init_backend_mock.assert_not_called()

    def test_wrapper_envvars_override_process_tf_data_dir(self, auto_init_backend_mock):
        self._write_backend()
        os.makedirs(os.path.join(self.path, "custom-data"))
        with open(
            os.path.join(self.path, "custom-data", "terraform.tfstate"), "w", encoding="utf-8"
        ) as state:
            state.write("{}")

        with patch.dict(os.environ, {"TF_DATA_DIR": "elsewhere"}):
            self.assertIsNotNone(
                resolve_auto_init(
                    "apply", [], self.path, WrapperConfig(), {"TF_DATA_DIR": "custom-data"}, False
                )
            )

        auto_init_backend_mock.assert_not_called()
