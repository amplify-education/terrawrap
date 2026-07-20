"""Tests for plan output processing helpers"""

from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from terrawrap.utils.plan import PlanExitCode, convert_plan_to_json, extract_show_json

MODULE = "terrawrap.utils.plan"


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

    def test_error_includes_exit_code_when_provided(self):
        """The raised message names the exit code, not just the noise around it

        Regression: a bare "no JSON object found ... output: <noise>" message
        can't distinguish "terraform show exited 0 but wrote nothing" from a
        real failure that happened to exit non-zero without the FAILURE code.
        """
        with self.assertRaisesRegex(RuntimeError, r"exit code 0"):
            extract_show_json(["Executing: terraform show -json\n"], exit_code=0)

    def test_error_notes_empty_output_when_nothing_captured(self):
        """An empty/whitespace-only capture is reported explicitly, not as a blank suffix"""
        with self.assertRaisesRegex(RuntimeError, r"<no output captured>"):
            extract_show_json([], exit_code=0)


@patch(f"{MODULE}.execute_command")
class TestConvertPlanToJson(TestCase):
    """Test convert_plan_to_json"""

    def setUp(self):
        self.plan_binary_file = Path("/tmp/tfplan/foo/tfplan.binary")
        self.source_directory = Path("/repo/config/foo")

    def _write_target(self):
        """convert_plan_to_json writes tfplan.json next to the binary; avoid touching disk"""
        return patch(f"{MODULE}.Path.open")

    @patch.dict(f"{MODULE}.os.environ", {}, clear=True)
    def test_writes_json_on_first_attempt(self, mock_execute):
        """Writes the plan JSON and returns its path when show succeeds on the first try"""
        mock_execute.return_value = (
            PlanExitCode.SUCCESS_WITH_DIFF.value,
            ["Executing: terraform show -json\n", '{"a":1}\n'],
        )
        with self._write_target() as mock_open:
            result = convert_plan_to_json(
                self.plan_binary_file, self.source_directory, {}, wrapper_script="/opt/bin/tf"
            )
            mock_open.return_value.__enter__.return_value.write.assert_called_once_with('{"a":1}\n')

        self.assertEqual(result, self.plan_binary_file.parent / "tfplan.json")
        mock_execute.assert_called_once_with(
            [
                "/opt/bin/tf",
                "--no-version-check",
                str(self.source_directory),
                "show",
                "-json",
                str(self.plan_binary_file),
            ],
            print_output=False,
            env={},
        )

    def test_retries_once_when_first_attempt_has_no_json(self, mock_execute):
        """A single empty/noise-only attempt is retried and recovers transparently

        Regression: amplify-education/terraform-config CI observed `terraform show
        -json` intermittently returning only terrawrap's own noise (no JSON) under
        --parallel-jobs=16, hitting a different directory on different runs. That's
        the transient failure this retry is meant to absorb.
        """
        mock_execute.side_effect = [
            (PlanExitCode.SUCCESS_WITH_DIFF.value, ["WARNING: Your version of Terrawrap is stale!\n"]),
            (PlanExitCode.SUCCESS_WITH_DIFF.value, ['{"a":1}\n']),
        ]
        with self._write_target():
            convert_plan_to_json(
                self.plan_binary_file, self.source_directory, {}, wrapper_script="/opt/bin/tf"
            )

        self.assertEqual(mock_execute.call_count, 2)

    def test_raises_after_second_attempt_still_has_no_json(self, mock_execute):
        """Gives up after one retry rather than looping forever on a persistent failure"""
        mock_execute.return_value = (
            PlanExitCode.SUCCESS_WITH_DIFF.value,
            ["WARNING: Your version of Terrawrap is stale!\n"],
        )
        with self.assertRaisesRegex(RuntimeError, r"no JSON object found"):
            convert_plan_to_json(
                self.plan_binary_file, self.source_directory, {}, wrapper_script="/opt/bin/tf"
            )

        self.assertEqual(mock_execute.call_count, 2)

    def test_does_not_retry_on_terraform_show_failure(self, mock_execute):
        """A genuine 'terraform show' failure (exit code FAILURE) is not treated as the
        flaky empty-output case and is not retried"""
        mock_execute.return_value = (PlanExitCode.FAILURE.value, ["Error: failed to read plan file\n"])
        with self.assertRaisesRegex(RuntimeError, r"'terraform show' failed"):
            convert_plan_to_json(
                self.plan_binary_file, self.source_directory, {}, wrapper_script="/opt/bin/tf"
            )

        mock_execute.assert_called_once()
