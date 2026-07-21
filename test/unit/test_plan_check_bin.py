"""Tests for bin/plan_check's nested `tf` subprocess invocations"""

import importlib.machinery
import importlib.util
import os
from unittest import TestCase
from unittest.mock import patch

_BIN_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "bin", "plan_check"))


def _load_plan_check_module():
    """Load bin/plan_check (no .py extension) as a module via SourceFileLoader."""
    loader = importlib.machinery.SourceFileLoader("plan_check_bin", _BIN_PATH)
    spec = importlib.util.spec_from_loader("plan_check_bin", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestInitAndPlanDirectoryNoVersionCheck(TestCase):
    """init_and_plan_directory's nested `tf` calls skip the per-invocation version check"""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_plan_check_module()

    def test_init_and_plan_calls_pass_no_version_check(self):
        """Both the init and plan subprocess calls include --no-version-check

        plan_check makes one nested `tf` call per directory for init, plan, and
        (when writing plan output) show; each independently re-runs the PyPI
        staleness check unless told not to, polluting captured stdout with a
        nag banner that has obscured real terraform show failures in CI.
        """
        with patch.object(self.mod, "execute_command") as mock_execute:
            mock_execute.side_effect = [
                (0, ["init ok\n"]),
                (self.mod.PlanExitCode.SUCCESS_NO_DIFF.value, ["plan ok\n"]),
            ]
            result = self.mod.init_and_plan_directory(
                directory="/tmp/does-not-exist",
                skip_iam=True,
                print_diff=False,
                with_colors=False,
                additional_envvars={},
            )

        self.assertEqual(result, self.mod.WrapperExitCode.SUCCESS)
        self.assertEqual(mock_execute.call_count, 2)
        for call in mock_execute.call_args_list:
            command_args = call.args[0]
            self.assertIn("--no-version-check", command_args)
