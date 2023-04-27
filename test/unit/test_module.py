"""Test Terraform module utilities"""
from unittest import TestCase

import os

from networkx import DiGraph, is_isomorphic

from terrawrap.utils.module import get_module_usage_graph


class TestModule(TestCase):
    """Test Terraform module utilities"""

    def setUp(self):
        self.prev_dir = os.getcwd()
        os.chdir(
            os.path.normpath(os.path.dirname(__file__) + "/../helpers/mock_directory")
        )

    def tearDown(self):
        os.chdir(self.prev_dir)

    def test_get_module_usage_graph(self):
        """Test getting graph of module usages"""
        actual = get_module_usage_graph("config")

        expected = DiGraph()
        expected.add_node("modules/module1")
        expected.add_node("config/app1")
        expected.add_node("config/app2")
        expected.add_node("config/app3")

        expected.add_edge("modules/module1", "config/app1")
        expected.add_edge("modules/module1", "config/app2")
        expected.add_edge("modules/module1", "config/app3")

        self.assertTrue(is_isomorphic(actual, expected))
