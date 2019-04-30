"""Test path utilities"""
from unittest import TestCase

import os

from terrawrap.utils.path import get_symlinks, get_directories_for_paths


class TestPath(TestCase):
    """Test path utilities"""
    def setUp(self):
        self.prev_dir = os.getcwd()
        os.chdir(os.path.normpath(os.path.dirname(__file__) + '/../helpers/mock_directory'))

    def tearDown(self):
        os.chdir(self.prev_dir)

    def test_get_symlinks(self):
        """test getting map of symlinks for a directory"""
        actual = get_symlinks('config')
        self.assertEqual(actual, {
            'config/app1': {'config/app3'}
        })

    def test_get_directories_for_paths(self):
        """test get directories for a list of paths"""

        actual = get_directories_for_paths([
            'config/app1',
            'config/app1/test.tf',
            'config/app2/test.tf'
        ])
        self.assertEqual(actual, [
            'config/app1',
            'config/app1',
            'config/app2'
        ])
