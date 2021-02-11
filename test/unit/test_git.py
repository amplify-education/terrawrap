"""Test git utilities"""
import os
from collections import namedtuple
from unittest import TestCase
from mock import patch

from terrawrap.utils.git_utils import get_git_changed_files

Change = namedtuple("Change", ['a_path', 'b_path', 'new_file', 'deleted_file'])


class TestGit(TestCase):
    """Test git utilities"""
    @patch('terrawrap.utils.git_utils.Repo')
    def test_get_git_changed_files(self, repo):
        """Test getting list of changed files in git"""
        repo.return_value.commit.return_value.diff.return_value = [
            Change('/foo', '/foo', False, False),
            Change(None, '/bar', True, False),
            Change('/baz', None, False, True)
        ]
        actual = get_git_changed_files(os.getcwd())

        self.assertEqual(actual, {'/bar', '/foo', '/baz'})
