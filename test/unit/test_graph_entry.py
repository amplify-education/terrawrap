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
        self.assertEqual(stdout, ["Success", "\n", "Resources: 0 added, 0 changed, 0 destroyed"])
        self.assertEqual(changes_detected, False)

    @patch("terrawrap.models.graph_entry.execute_command")
    def test_audit_api_url_only_to_init(self, exec_command):
        """audit_api_url goes to init but NOT to the operation call.
        The tf wrapper (bin/tf) handles audit reporting for apply/destroy;
        reporting at this level too would create duplicate tfaudit records
        (AT-14812)."""
        exec_command.side_effect = [
            (0, ["Success"]),
            (0, ["Success"]),
        ]

        entry = GraphEntry("/var", [])
        entry.execute("apply")

        self.assertEqual(exec_command.call_count, 2)

        init_call_kwargs = exec_command.call_args_list[0][1]
        operation_call_kwargs = exec_command.call_args_list[1][1]

        self.assertIn("audit_api_url", init_call_kwargs)
        self.assertNotIn("audit_api_url", operation_call_kwargs)

    @patch("terrawrap.models.graph_entry.execute_command")
    def test_execute_audit_api_url_value(self, exec_command):
        """audit_api_url is only passed to init, not to the operation call."""
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
        self.assertNotIn("audit_api_url", operation_call_kwargs)
