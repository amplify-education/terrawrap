"""Test path utilities"""
import os
from unittest import TestCase

from networkx import DiGraph

from terrawrap.utils.path import get_file_graph


class TestPath(TestCase):
    """Test path utilities"""

    def setUp(self):
        self.prev_dir = os.getcwd()
        os.chdir(os.path.normpath(os.path.dirname(__file__) + '/../helpers/mock_directory'))

    def tearDown(self):
        os.chdir(self.prev_dir)

    def test_get_file_graph(self):
        """test getting graph of symlinks for a directory"""
        actual = get_file_graph('config')

        expected = DiGraph()
        expected.add_nodes_from([
            'config',
            'config/.tf_wrapper',
            'config/app1',
            'config/app1/app.auto.tfvars',
            'config/app1/test.tf',
            'config/app1/variables.tf',
            'config/app2',
            'config/app2/test.tf',
            'config/app3',
            'config/app4',
            'config/app4/.tf_wrapper',
            'config/app5',
            'config/app5/app.auto.tfvars',
            'config/global.auto.tfvars',
            'config/team',
            'config/team/app4',
            'config/team/app4/variables.tf',
            'config/team/team.auto.tfvars',
        ])

        expected.add_edges_from([
            ('config/.tf_wrapper', 'config'),
            ('config/global.auto.tfvars', 'config'),
            ('config/app1', 'config/app3'),
            ('config/app5/app.auto.tfvars', 'config/app5'),
            ('config/app2/test.tf', 'config/app2'),
            ('config/app4/.tf_wrapper', 'config/app4'),
            ('config/team/team.auto.tfvars', 'config/team'),
            ('config/team/app4/variables.tf', 'config/team/app4'),
            ('config/app1/test.tf', 'config/app1'),
            ('config/app1/app.auto.tfvars', 'config/app1'),
            ('config/app1/variables.tf', 'config/app1')
        ])
        self.assertEqual(set(actual.nodes), set(expected.nodes))
        self.assertEqual(set(actual.edges), set(expected.edges))
