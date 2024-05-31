"""Tests for Graph applyinhs"""
from typing import List
from unittest import TestCase
from unittest.mock import patch, MagicMock, call

import os

import networkx

from terrawrap.models.graph import ApplyGraph


class TestApplyGraph(TestCase):
    """Tests for executing commands on graphs"""

    def setUp(self):
        self.prev_dir = os.getcwd()
        self.graph = networkx.DiGraph()
        self.graph.add_nodes_from(["foo/app1", "bar/app1"])
        self.post_graph = ["bar/app2"]

    @patch("terrawrap.models.graph.GraphEntry")
    def test_execute(self, graph_entry_class):
        """Test that executing a graph"""

        # pylint: disable=unused-argument
        def _get_graph_entry(path: str, variables: List[str]):
            entry = MagicMock()
            entry.state = "Success"
            entry.path = path
            entry.execute.return_value = (0, ["Success"], True)
            return entry

        graph_entry_class.side_effect = _get_graph_entry

        graph = ApplyGraph("plan", self.graph, self.post_graph, "bar")

        graph.execute_graph()
        graph.execute_post_graph()

        self.assertEqual(
            graph.graph_dict["bar/app1"].execute.mock_calls, [call("plan", debug=False)]
        )

        self.assertEqual(
            graph.graph_dict["bar/app2"].execute.mock_calls, [call("plan", debug=False)]
        )

        self.assertEqual(graph.not_applied, {"foo/app1"})
        self.assertEqual(graph.applied, {"bar/app1", "bar/app2"})
