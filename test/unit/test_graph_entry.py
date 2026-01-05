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

    @patch("terrawrap.models.graph_entry.execute_command")
    def test_execute_passes_audit_api_url(self, exec_command):
        """Test that audit_api_url is passed to execute_command calls"""
        exec_command.side_effect = [
            (0, ["Success"]),
            (0, ["Success"]),
        ]

        entry = GraphEntry("/var", [])
        entry.execute("apply")

        self.assertEqual(exec_command.call_count, 2)

        for call_args in exec_command.call_args_list:
            self.assertIn("audit_api_url", call_args[1])

    @patch("terrawrap.models.graph_entry.execute_command")
    def test_execute_audit_api_url_value(self, exec_command):
        """Test that the correct audit_api_url value is passed"""
        exec_command.side_effect = [
            (0, ["Success"]),
            (0, ["Success"]),
        ]

        entry = GraphEntry("/var", [])
        entry.execute("plan")

        self.assertEqual(exec_command.call_count, 2)
        init_call_kwargs = exec_command.call_args_list[0][1]
        operation_call_kwargs = exec_command.call_args_list[1][1]

        self.assertIn("audit_api_url", init_call_kwargs)
        self.assertIn("audit_api_url", operation_call_kwargs)
