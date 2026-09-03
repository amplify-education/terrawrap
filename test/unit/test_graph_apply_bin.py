"""Tests for bin/graph_apply's handling of a manual (apply_automatically: false) dependency"""

import importlib.machinery
import importlib.util
import io
import os
from unittest import TestCase
from unittest.mock import patch

from terrawrap.exceptions import ManualDependencyError

_BIN_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "bin", "graph_apply"))


def _load_graph_apply_module():
    """Load bin/graph_apply (no .py extension) as a module via SourceFileLoader."""
    loader = importlib.machinery.SourceFileLoader("graph_apply_bin", _BIN_PATH)
    spec = importlib.util.spec_from_loader("graph_apply_bin", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestManualDependencyError(TestCase):
    """A ManualDependencyError from walk_and_graph_directory is a clean exit(1), not a traceback"""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_graph_apply_module()

    def test_prints_to_stderr_and_exits(self):
        """The exception message reaches stderr and the process exits 1, without a traceback"""
        docopt_args = {
            "--operation": "plan",
            "--debug": False,
            "--print-only-changes": False,
            "--parallel-jobs": "4",
            "--path": os.getcwd(),
        }
        stderr = io.StringIO()
        with (
            patch.object(self.mod, "version_check"),
            patch.object(self.mod, "docopt", return_value=docopt_args),
            patch.object(
                self.mod,
                "walk_and_graph_directory",
                side_effect=ManualDependencyError("Cannot depend on manual_target"),
            ),
            patch("sys.stderr", stderr),
        ):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.main()

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Cannot depend on manual_target", stderr.getvalue())
