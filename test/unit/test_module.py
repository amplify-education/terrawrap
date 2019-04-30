"""Test Terraform module utilities"""
from unittest import TestCase

import os

from terrawrap.utils.module import get_module_usage_map


class TestModule(TestCase):
    """Test Terraform module utilities"""
    def setUp(self):
        self.prev_dir = os.getcwd()
        os.chdir(os.path.normpath(os.path.dirname(__file__) + '/../helpers/mock_directory'))

    def tearDown(self):
        os.chdir(self.prev_dir)

    def test_get_module_usage_map(self):
        """Test getting map of module usages"""
        actual = get_module_usage_map('config')

        self.assertEqual(actual, {
            'modules/module1': {
                'config/app1',
                'config/app2',
                'config/app3'
            }
        })
