"""Tests for Graph applyinhs"""
from unittest import TestCase

import os

from mock import patch, call
import networkx

from terrawrap.models.graph import ApplyGraph


class TestApplyGraph(TestCase):
    """Tests for executing commands on graphs"""
    def setUp(self):
        self.prev_dir = os.getcwd()
        os.chdir(os.path.normpath(os.path.dirname(__file__) + '/../helpers/mock_directory'))
        self.graph = networkx.DiGraph()
        self.graph.add_nodes_from(["foo/app1"])
        self.post_graph = ["bar/app2"]

    def tearDown(self):
        os.chdir(self.prev_dir)

    @patch('terrawrap.models.graph.GraphEntry')
    def test_execute(self, graph_entry_class):
        """Test that executing a graph will call init and then the command"""
        graph_entry_class.return_value.state = "Pending"
        graph_entry_class.return_value.path = "foo/app1"
        graph_entry_class.return_value.execute.return_value = (0, ['Success'], True)

        graph = ApplyGraph('plan', self.graph, [], "foo")

        graph.execute_graph()
        graph.execute_post_graph()

        self.assertEqual(
            graph_entry_class.return_value.execute.mock_calls,
            [call('plan', debug=False)]
        )

    @patch('terrawrap.models.graph.GraphEntry')
    def test_no_op(self, graph_entry_class):
        """Test that executing a graph can no-op if the prefix does not match"""
        graph_entry_class.return_value.state = "no-op"
        graph_entry_class.return_value.path = "foo/app1"
        graph_entry_class.return_value.execute.return_value = (0, ['Success'], True)

        graph = ApplyGraph('plan', self.graph, [], "bar")

        graph.execute_graph()
        graph.execute_post_graph()

        expected_not_applied = {'foo/app1'}
        self.assertEqual(
            graph_entry_class.return_value.execute.mock_calls,
            []
        )
        self.assertEqual(graph.not_applied, expected_not_applied)

    @patch('terrawrap.models.graph.GraphEntry')
    def test_post_graph(self, graph_entry_class):
        """Test that executing a post_graph list"""
        graph_entry_class.return_value.state = "no-op"
        graph_entry_class.return_value.path = "foo/app1"
        graph_entry_class.return_value.execute.return_value = (0, ['Success'], True)

        graph = ApplyGraph('plan', self.graph, self.post_graph, "bar")

        graph.execute_graph()
        graph.execute_post_graph()

        self.assertEqual(
            graph_entry_class.return_value.execute.mock_calls,
            []
        )
        self.assertEqual(
            graph.not_applied,
            {graph_entry_class.return_value.path}
        )
