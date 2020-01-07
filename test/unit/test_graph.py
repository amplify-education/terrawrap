"""Test terraform config utilities"""
from unittest import TestCase

import networkx

from terrawrap.utils.graph import (
    find_source_nodes,
    has_cycle,
    successors,
    generate_dependencies,
    visualize,
)

ROLE_ARN = 'arn:aws:iam::1234567890:role/test_role'
BUCKET = 'us-west-2--mclass--terraform--test'
REGION = 'us-west-2'
LOCK_TABLE = 'terraform-locking'


class TestConfig(TestCase):
    """Test terraform config utilities"""

    def setUp(self):
        """Sets up a directed graph to test utility functions"""
        self.graph = networkx.DiGraph()
        self.graph.add_nodes_from(["1", "2", "3", "4", "5", "6"])
        self.graph.add_edges_from([("1", "2"), ("1", "4"), ("1", "6"), ("3", "5"), ("3", "6")])

    def test_find_source_nodes(self):
        """Tests we can find source nodes for a given graph"""
        actual_sources = find_source_nodes(self.graph)
        expected_sources = ["1", "3"]
        self.assertEqual(actual_sources, expected_sources)

    def has_no_cycle(self):
        """ Tests a graph has no cycle"""
        cycle = has_cycle(self.graph)
        self.assertFalse(cycle)

    def test_has_source_cycle(self):
        """ Tests we can detect a source cycle in a graph"""
        self.graph.add_edges_from([("5", "1"), ("4", "3")])
        self.assertTrue(has_cycle(self.graph))

    def test_has_non_source_cycle(self):
        """ Tests we can find a non source cycle"""
        self.graph.add_edges_from([("6", "4"), ("4", "6")])
        self.assertTrue(has_cycle(self.graph))

    def test_successors(self):
        """ Tests we can find a nodes successors"""
        actual_successors = successors(0, "1", self.graph)
        expected_successors = (0, "1", ["2", "4", "6"])
        self.assertEqual(actual_successors, expected_successors)

    def test_generate_dependencies(self):
        """ Tests we can generates a list of dependencies for a graph using source nodes"""
        sources = find_source_nodes(self.graph)
        actual_dependencies = generate_dependencies(sources, self.graph)
        expected_dependencies = [
            [(1, "1", ["2", "4", "6"]), (2, "2", []), (2, "4", []), (2, "6", [])],
            [(1, "3", ["5", "6"]), (2, "5", []), (2, "6", [])]
        ]
        self.assertEqual(actual_dependencies, expected_dependencies)

    def test_visualizer(self):
        """ Tests we can print given a list of dependencies"""
        sources = find_source_nodes(self.graph)
        dependencies = generate_dependencies(sources, self.graph)
        visualize(dependencies)
