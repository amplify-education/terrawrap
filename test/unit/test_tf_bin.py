"""Tests for bin/tf's argument parsing, incl. --no-version-check"""

import importlib.machinery
import importlib.util
import os
from unittest import TestCase

_BIN_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "bin", "tf"))


def _load_tf_module():
    """Load bin/tf (no .py extension) as a module via SourceFileLoader."""
    loader = importlib.machinery.SourceFileLoader("tf_bin", _BIN_PATH)
    spec = importlib.util.spec_from_loader("tf_bin", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestShouldSkipVersionCheck(TestCase):
    """Test should_skip_version_check"""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_tf_module()

    def test_true_when_flag_is_first(self):
        """Detects --no-version-check as the leading flag"""
        self.assertTrue(self.mod.should_skip_version_check(["tf", "--no-version-check", "dir", "plan"]))

    def test_true_when_flag_follows_no_resolve_envvars(self):
        """Detects --no-version-check when combined with --no-resolve-envvars, in either order"""
        argv = ["tf", "--no-resolve-envvars", "--no-version-check", "dir", "plan"]
        self.assertTrue(self.mod.should_skip_version_check(argv))

    def test_false_when_flag_absent(self):
        """A normal invocation with no flags does not skip the version check"""
        self.assertFalse(self.mod.should_skip_version_check(["tf", "dir", "plan"]))


class TestProcessArguments(TestCase):
    """Test process_arguments strips leading optional flags in any combination"""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_tf_module()

    def test_no_flags(self):
        """Parses path/command/arguments with no optional flags present"""
        path, command, additional_arguments, resolve_envvars = self.mod.process_arguments(
            ["tf", "dir", "plan", "-lock=false"]
        )
        self.assertEqual(
            (path, command, additional_arguments, resolve_envvars), ("dir", "plan", ["-lock=false"], True)
        )

    def test_no_version_check_flag_alone(self):
        """--no-version-check is stripped and does not disable envvar resolution"""
        path, command, additional_arguments, resolve_envvars = self.mod.process_arguments(
            ["tf", "--no-version-check", "dir", "plan"]
        )
        self.assertEqual((path, command, additional_arguments, resolve_envvars), ("dir", "plan", [], True))

    def test_both_flags_together(self):
        """Both leading flags are stripped and resolve_envvars reflects --no-resolve-envvars"""
        path, command, additional_arguments, resolve_envvars = self.mod.process_arguments(
            ["tf", "--no-resolve-envvars", "--no-version-check", "dir", "init", "-upgrade"]
        )
        self.assertEqual(
            (path, command, additional_arguments, resolve_envvars), ("dir", "init", ["-upgrade"], False)
        )
