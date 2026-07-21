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
