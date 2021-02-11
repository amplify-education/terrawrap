"""Unit tests for terraform variable utilities"""
from unittest import TestCase

import os

from networkx import DiGraph, is_isomorphic

from terrawrap.utils.tf_variables import (
    get_auto_vars,
    get_nondefault_variables_for_file,
    get_source_for_variable,
    get_auto_var_usage_graph,
    Variable,
)


class TestTerraformVariables(TestCase):
    """Unit tests for terraform variable utilities"""
    def setUp(self):
        self.prev_dir = os.getcwd()
        os.chdir(os.path.normpath(os.path.dirname(__file__) + '/../helpers/mock_directory'))

    def tearDown(self):
        os.chdir(self.prev_dir)

    def test_get_auto_vars(self):
        """test getting dict of tfvars files and their variables"""
        actual = get_auto_vars('config')
        self.assertEqual(actual, {
            'config/global.auto.tfvars': {
                Variable('foo', 'bar'),
                Variable('dog', 'cat'),
            },
            'config/app1/app.auto.tfvars': {
                Variable('bar', 'bye'),
                Variable('baz', 'bat'),
            },
            'config/app3/app.auto.tfvars': {
                Variable('bar', 'bye'),
                Variable('baz', 'bat'),
            },
            'config/team/team.auto.tfvars': {
                Variable('foo', 'cat'),
            },
            'config/app5/app.auto.tfvars': {
                Variable('foo', ((('key', 'value'),),)),
            },
        })

    def test_get_variables_for_file(self):
        """test getting list of variables declared in a tf file"""
        actual = get_nondefault_variables_for_file('config/app1/variables.tf')

        self.assertEqual(actual, {'foo', 'bar'})

    def test_get_source_for_variable(self):
        """test getting the source of a auto var"""
        actual = get_source_for_variable('config/team/app4', 'foo', {
            'config/team/team.auto.tfvars': {Variable('foo', 'cat')},
            'config/global.auto.tfvars': {Variable('foo', 'bar')}
        })

        self.assertEqual(actual, 'config/team/team.auto.tfvars')

    def test_get_auto_var_usages(self):
        """test getting dict of all auto var usages"""
        actual = get_auto_var_usage_graph('config')

        expected = DiGraph()
        expected.add_node('config/global.auto.tfvars')
        expected.add_node('config/app3/app.auto.tfvars')
        expected.add_node('config/team/team.auto.tfvars')
        expected.add_node('config/app1/app.auto.tfvars')
        expected.add_node('config/app1')
        expected.add_node('config/app3')
        expected.add_node('config/team/app4')

        expected.add_edge('config/global.auto.tfvars', 'config/app1')
        expected.add_edge('config/global.auto.tfvars', 'config/app3')
        expected.add_edge('config/app3/app.auto.tfvars', 'config/app3')
        expected.add_edge('config/team/team.auto.tfvars', 'config/team/app4')
        expected.add_edge('config/app1/app.auto.tfvars', 'config/app1')

        self.assertTrue(is_isomorphic(actual, expected))
