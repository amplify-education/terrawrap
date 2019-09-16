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
        exit_code, stdout, changes_detected = entry.execute('plan')

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, ['Success', '\n'])
        self.assertEqual(changes_detected, False)

    @patch('terrawrap.models.pipeline_entry.execute_command')
    def test_execute_fail(self, exec_command):
        """Test executing a command unsuccessfully"""
        exec_command.side_effect = [(1, ['Fail'])]

        entry = PipelineEntry('/var', [])
        exit_code, stdout, changes_detected = entry.execute('plan')

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, ['Fail'])
        self.assertEqual(changes_detected, True)

    @patch('terrawrap.models.pipeline_entry.execute_command')
    def test_execute_apply_changes(self, exec_command):
        """Test executing apply with changes"""
        exec_command.side_effect = [
            (0, ['Success']),
            (2, ['Something changed']),
            (0, ['Success']),
        ]

        entry = PipelineEntry('/var', [])
        exit_code, stdout, changes_detected = entry.execute('apply')

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, ['Success', '\n', 'Something changed', '\n', 'Success'])
        self.assertEqual(changes_detected, True)

    @patch('terrawrap.models.pipeline_entry.execute_command')
    def test_execute_apply_no_changes(self, exec_command):
        """Test executing apply with no changes"""
        exec_command.side_effect = [
            (0, ['Success']),
            (0, ['Nothing changed']),
        ]

        entry = PipelineEntry('/var', [])
        exit_code, stdout, changes_detected = entry.execute('apply')

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, ['Success', '\n', 'Nothing changed'])
        self.assertEqual(changes_detected, False)
