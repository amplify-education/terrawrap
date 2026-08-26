"""Unit tests for terraform variable utilities"""

import os
from unittest import TestCase

from networkx import DiGraph, is_isomorphic

from terrawrap.utils.tf_variables import (
    Variable,
    get_auto_var_usage_graph,
    get_auto_vars,
    get_nondefault_variables_for_file,
    get_source_for_variable,
)


class TestTerraformVariables(TestCase):
    """Unit tests for terraform variable utilities"""

    def setUp(self):
        self.prev_dir = os.getcwd()
        os.chdir(os.path.normpath(os.path.dirname(__file__) + "/../helpers/mock_directory"))

    def tearDown(self):
        os.chdir(self.prev_dir)

    def test_get_auto_vars(self):
        """test getting dict of tfvars files and their variables"""
        actual = get_auto_vars("config")
        self.assertEqual(
            actual,
            {
                "config/global.auto.tfvars": {
                    Variable("foo", "bar"),
                    Variable("dog", "cat"),
                },
                "config/app1/app.auto.tfvars": {
                    Variable("bar", "bye"),
                    Variable("baz", "bat"),
                },
                "config/app3/app.auto.tfvars": {
                    Variable("bar", "bye"),
                    Variable("baz", "bat"),
                },
                "config/team/team.auto.tfvars": {
                    Variable("foo", "cat"),
                },
                "config/app5/app.auto.tfvars": {
                    Variable("foo", ((("key", "value"),),)),
                },
                "config/area/area.auto.tfvars": {
                    Variable("region_setting", "us-west-2"),
                },
            },
        )

    def test_get_variables_for_file(self):
        """test getting list of variables declared in a tf file"""
        actual = get_nondefault_variables_for_file("config/app1/variables.tf")

        self.assertEqual(actual, {"foo", "bar"})

    def test_nondefault_excludes_falsy_default(self):
        """A declared `default = false` (or 0, "", []) is still a default and must be excluded."""
        actual = get_nondefault_variables_for_file("config/area/svc/variables.tf")

        self.assertEqual(actual, set())

    def test_get_source_for_variable(self):
        """test getting the source of a auto var"""
        actual = get_source_for_variable(
            "config/team/app4",
            "foo",
            {
                "config/team/team.auto.tfvars": {Variable("foo", "cat")},
                "config/global.auto.tfvars": {Variable("foo", "bar")},
            },
        )

        self.assertEqual(actual, "config/team/team.auto.tfvars")

    def test_get_auto_var_usages(self):
        """test getting graph of all auto var usages"""
        actual = get_auto_var_usage_graph("config")

        expected = DiGraph()
        expected.add_node("config/global.auto.tfvars")
        expected.add_node("config/app3/app.auto.tfvars")
        expected.add_node("config/team/team.auto.tfvars")
        expected.add_node("config/app1/app.auto.tfvars")
        expected.add_node("config/area/area.auto.tfvars")
        expected.add_node("config/app1")
        expected.add_node("config/app3")
        expected.add_node("config/team/app4")
        expected.add_node("config/area/svc")

        expected.add_edge("config/global.auto.tfvars", "config/app1")
        expected.add_edge("config/global.auto.tfvars", "config/app3")
        expected.add_edge("config/app3/app.auto.tfvars", "config/app3")
        expected.add_edge("config/team/team.auto.tfvars", "config/team/app4")
        expected.add_edge("config/app1/app.auto.tfvars", "config/app1")
        expected.add_edge("config/area/area.auto.tfvars", "config/area/svc")

        self.assertTrue(is_isomorphic(actual, expected))

    def test_auto_var_usages_tracks_override(self):
        """Upstream auto.tfvars overrides a downstream variable's default, so the edge must be present."""
        actual = get_auto_var_usage_graph("config")

        self.assertTrue(actual.has_edge("config/area/area.auto.tfvars", "config/area/svc"))
