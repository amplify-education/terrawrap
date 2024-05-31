"""Tests for GraphEntries"""
from unittest import TestCase
from unittest.mock import patch

from terrawrap.models.graph_entry import GraphEntry


class TestGraphEntry(TestCase):
    """Tests for GraphEntries"""

    @patch("terrawrap.models.graph_entry.execute_command")
    def test_execute(self, exec_command):
        """Test executing a command successfully"""
        exec_command.side_effect = [
            (0, ["Success"]),
            (0, ["Success"]),
        ]

        entry = GraphEntry("/var", [])
        exit_code, stdout, changes_detected = entry.execute("plan")

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, ["Success", "\n", "Success"])
        self.assertEqual(changes_detected, True)

    @patch("terrawrap.models.graph_entry.execute_command")
    def test_execute_fail(self, exec_command):
        """Test executing a command unsuccessfully"""
        exec_command.side_effect = [(1, ["Fail"])]

        entry = GraphEntry("/var", [])
        exit_code, stdout, changes_detected = entry.execute("plan")

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, ["Fail"])
        self.assertEqual(changes_detected, True)

    @patch("terrawrap.models.graph_entry.execute_command")
    def test_execute_apply_changes(self, exec_command):
        """Test executing apply with changes"""
        exec_command.side_effect = [
            (0, ["Success"]),
            (0, ["Success"]),
        ]

        entry = GraphEntry("/var", [])
        exit_code, stdout, changes_detected = entry.execute("apply")

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, ["Success", "\n", "Success"])
        self.assertEqual(changes_detected, True)

    @patch("terrawrap.models.graph_entry.execute_command")
    def test_execute_apply_no_changes(self, exec_command):
        """Test executing apply with no changes"""
        exec_command.side_effect = [
            (0, ["Success"]),
            (0, ["Resources: 0 added, 0 changed, 0 destroyed"]),
        ]

        entry = GraphEntry("/var", [])
        exit_code, stdout, changes_detected = entry.execute("apply")

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            stdout, ["Success", "\n", "Resources: 0 added, 0 changed, 0 destroyed"]
        )
        self.assertEqual(changes_detected, False)
