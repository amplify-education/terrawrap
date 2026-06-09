"""Test plan_check directory selection utilities"""
import os
import shutil
import tempfile
from unittest import TestCase
from unittest.mock import patch

from networkx import DiGraph

from terrawrap.utils.plan_check import get_modified_subdirectories

MODULE = "terrawrap.utils.plan_check"


@patch(f"{MODULE}.get_auto_var_usage_graph", return_value=DiGraph())
@patch(f"{MODULE}.get_module_usage_graph", return_value=DiGraph())
@patch(f"{MODULE}.get_git_root")
@patch(f"{MODULE}.get_git_changed_files")
class TestGetModifiedSubdirectories(TestCase):
    """Test selecting which directories to plan from a set of git-changed files"""

    def setUp(self):
        """Build a throwaway terraform tree with one surviving .tf file"""
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.leaf_dir = os.path.join(self.root, "config", "team", "app")
        os.makedirs(self.leaf_dir)
        with open(
            os.path.join(self.leaf_dir, "main.tf"), "w", encoding="utf-8"
        ) as handle:
            handle.write('resource "null_resource" "noop" {}\n')

    def test_modified_file_plans_dir(self, mock_changed, mock_root, _mod, _var):
        """A modified .tf file plans its containing directory"""
        mock_root.return_value = self.root
        mock_changed.return_value = {os.path.join(self.leaf_dir, "main.tf")}
        regular, _ = get_modified_subdirectories(self.root)
        self.assertIn(self.leaf_dir, regular)

    def test_deleted_file_plans_dir(self, mock_changed, mock_root, _mod, _var):
        """Deleting the only changed file still plans the directory it lived in"""
        mock_root.return_value = self.root
        mock_changed.return_value = {os.path.join(self.leaf_dir, "ecr.tf")}
        regular, _ = get_modified_subdirectories(self.root)
        self.assertIn(self.leaf_dir, regular)

    def test_deleted_dir_not_planned(self, mock_changed, mock_root, _mod, _var):
        """A change under a directory that no longer exists is not planned"""
        mock_root.return_value = self.root
        mock_changed.return_value = {
            os.path.join(self.root, "config", "team", "gone", "ecr.tf")
        }
        regular, symlinked = get_modified_subdirectories(self.root)
        self.assertEqual(regular, [])
        self.assertEqual(symlinked, [])
