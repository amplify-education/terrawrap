"""Tests for PipelineEntrys"""
from unittest import TestCase

from mock import patch

from terrawrap.models.pipeline_entry import PipelineEntry


class TestPipelineEntry(TestCase):
    """Tests for PipelineEntrys"""

    @patch('terrawrap.models.pipeline_entry.execute_command')
    def test_execute(self, exec_command):
        """Test executing a command successfully"""
        exec_command.side_effect = [(0, ['Success'])]

        entry = PipelineEntry('/var', [])
        exit_code, stdout = entry.execute('plan')

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, ['Success'])

    @patch('terrawrap.models.pipeline_entry.execute_command')
    def test_execute_fail(self, exec_command):
        """Test executing a command unsuccessfully"""
        exec_command.side_effect = [(1, ['Fail'])]

        entry = PipelineEntry('/var', [])
        exit_code, stdout = entry.execute('plan')

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, ['Fail'])
