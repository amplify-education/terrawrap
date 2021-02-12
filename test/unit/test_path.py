"""Test path utilities"""
from unittest import TestCase

import os

from networkx import DiGraph, is_isomorphic

from terrawrap.utils.path import get_symlink_graph


class TestPath(TestCase):
    """Test path utilities"""
    def setUp(self):
        self.prev_dir = os.getcwd()
        os.chdir(os.path.normpath(os.path.dirname(__file__) + '/../helpers/mock_directory'))

    def tearDown(self):
        os.chdir(self.prev_dir)

    def test_get_symlinks(self):
        """test getting graph of symlinks for a directory"""
        actual = get_symlink_graph('config')

        expected = DiGraph()
        expected.add_node('config/app1')
        expected.add_node('config/app3')

        expected.add_edge('config/app1', 'config/app3')

        self.assertTrue(is_isomorphic(actual, expected))
