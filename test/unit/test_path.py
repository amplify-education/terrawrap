"""Test path utilities"""
import os
from unittest import TestCase
from unittest.mock import patch, MagicMock

from networkx import DiGraph

from terrawrap.utils.path import get_file_graph, calc_repo_path


class TestPath(TestCase):
    """Test path utilities"""

    def setUp(self):
        self.prev_dir = os.getcwd()
        os.chdir(
            os.path.normpath(os.path.dirname(__file__) + "/../helpers/mock_directory")
        )

    def tearDown(self):
        os.chdir(self.prev_dir)

    def test_get_file_graph(self):
        """test getting graph of symlinks for a directory"""
        actual = get_file_graph("config")

        expected = DiGraph()
        expected.add_nodes_from(
            [
                "config",
                "config/.tf_wrapper",
                "config/app1",
                "config/app1/app.auto.tfvars",
                "config/app1/test.tf",
                "config/app1/variables.tf",
                "config/app2",
                "config/app2/test.tf",
                "config/app3",
                "config/app4",
                "config/app4/.tf_wrapper",
                "config/app5",
                "config/app5/app.auto.tfvars",
                "config/global.auto.tfvars",
                "config/team",
                "config/team/app4",
                "config/team/app4/variables.tf",
                "config/team/team.auto.tfvars",
            ]
        )

        expected.add_edges_from(
            [
                ("config/.tf_wrapper", "config"),
                ("config/global.auto.tfvars", "config"),
                ("config/app1", "config/app3"),
                ("config/app5/app.auto.tfvars", "config/app5"),
                ("config/app2/test.tf", "config/app2"),
                ("config/app4/.tf_wrapper", "config/app4"),
                ("config/team/team.auto.tfvars", "config/team"),
                ("config/team/app4/variables.tf", "config/team/app4"),
                ("config/app1/test.tf", "config/app1"),
                ("config/app1/app.auto.tfvars", "config/app1"),
                ("config/app1/variables.tf", "config/app1"),
            ]
        )
        self.assertEqual(set(actual.nodes), set(expected.nodes))
        self.assertEqual(set(actual.edges), set(expected.edges))

    @patch("terrawrap.utils.path.subprocess.check_output")
    def test_calc_repo_path(self, check_output_mock: MagicMock):
        """test getting repo path based on repo remote"""
        check_output_mock.return_value = b"git@github.com:amplify-education/repo-1.git"
        result = calc_repo_path("path/config")
        self.assertEqual(result, "repo-1/config")

        check_output_mock.return_value = (
            b"https://github.com/amplify-education/repo-2.git"
        )
        result = calc_repo_path("path/config")
        self.assertEqual(result, "repo-2/config")

        check_output_mock.return_value = (
            b"Fetch URL: https://github.com/amplify-education/repo-3.git"
        )
        result = calc_repo_path("path/config")
        self.assertEqual(result, "repo-3/config")
