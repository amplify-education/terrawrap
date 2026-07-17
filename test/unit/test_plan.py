"""Tests for plan output processing helpers"""

from unittest import TestCase

from terrawrap.utils.plan import extract_show_json


class TestExtractShowJson(TestCase):
    """Test extract_show_json"""

    def test_strips_command_echo_prefix(self):
        """Returns the JSON when only the tf-wrapper command echo precedes it"""
        stdout = [
            "Executing: terraform show -json /tmp/tfplan/foo/tfplan.binary\n",
            '{"format_version":"1.2","resource_changes":[]}\n',
        ]
        self.assertEqual(
            extract_show_json(stdout),
            '{"format_version":"1.2","resource_changes":[]}\n',
        )

    def test_strips_stderr_noise_before_json(self):
        """Strips stderr-merged noise (warnings) interleaved before the JSON

        Regression: terraform stderr (lockfile/deprecation warnings) gets
        merged into stdout by execute_command(capture_stderr=True); the old
        stdout[1:] slice only stripped the command echo, leaving warning
        lines as a non-JSON prefix that broke downstream `opa exec` parsing.
        """
        stdout = [
            "Executing: terraform show -json /tmp/tfplan/foo/tfplan.binary\n",
            "Warning: lock file mismatch\n",
            "  on backend.tf line 5: deprecated argument\n",
            '{"format_version":"1.2","resource_changes":[]}\n',
        ]
        self.assertEqual(
            extract_show_json(stdout),
            '{"format_version":"1.2","resource_changes":[]}\n',
        )

    def test_returns_json_when_no_preamble(self):
        """Returns the JSON unchanged when stdout has no preamble lines"""
        self.assertEqual(extract_show_json(['{"a":1}\n']), '{"a":1}\n')

    def test_raises_when_no_json_present(self):
        """Raises RuntimeError if there is no JSON line in stdout"""
        with self.assertRaises(RuntimeError):
            extract_show_json(["Executing: terraform show -json\n", "Error: no plan\n"])
