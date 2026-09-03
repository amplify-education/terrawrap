"""Test git utilities"""

import os
from logging import Logger
from unittest import TestCase
from unittest.mock import ANY, call, patch

from requests.exceptions import HTTPError

from terrawrap.utils.cli import (
    MAX_RETRIES,
    Status,
    _get_retriable_errors,
    _post_audit_info,
    _post_log_chunk,
    execute_command,
)

MOCK_ERROR = HTTPError()


class TestCli(TestCase):
    """Test cli utilities"""

    def setUp(self):
        self.popen_patcher = patch("subprocess.Popen")
        self.mock_popen = self.popen_patcher.start()
        self.mock_process = self.mock_popen.return_value

        self.jitter_patcher = patch("terrawrap.utils.cli.Jitter")
        self.mock_jitter = self.jitter_patcher.start()
        self.mock_jitter.return_value.backoff.return_value = 3

    def tearDown(self):
        self.popen_patcher.stop()
        self.jitter_patcher.stop()

    def test_execute_command(self):
        """Test executing a command successfully"""
        self.mock_process.poll.return_value = 0
        exit_code, stdout = execute_command(["echo", "1 "])

        self.assertEqual(self.mock_popen.call_count, 1)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, [])

    def _run_with_stdout_bytes(self, payload: bytes, *, poll_results=(0,)):
        """Feed `payload` into the temp file terrawrap streams from, as if a
        subprocess had written it, then run execute_command against it.
        `poll_results` is returned from successive process.poll() calls (the
        last value repeats once exhausted), letting a test simulate the
        process still running for a while before it exits.
        Returns (exit_code, stdout, printed_text)."""

        def fake_popen(_args, *_pargs, **kwargs):
            os.write(kwargs["stdout"], payload)
            return self.mock_process

        def poll_side_effect(_results=list(poll_results)):
            return _results.pop(0) if len(_results) > 1 else _results[0]

        self.mock_popen.side_effect = fake_popen
        self.mock_process.poll.side_effect = poll_side_effect

        with patch("builtins.print") as mock_print:
            exit_code, stdout = execute_command(["echo"])

        printed_chunks = [print_call.args[0] for print_call in mock_print.call_args_list]
        return exit_code, stdout, printed_chunks

    def test_execute_command_decodes_multibyte_utf8_split_across_reads(self):
        """Terraform's box-drawing characters (e.g. U+2502) are multi-byte UTF-8
        sequences. Reading/decoding one raw byte at a time used to mangle each
        byte into its own U+FFFD replacement character; the incremental decoder
        must reassemble the full character instead."""
        payload = "│ lock info\n".encode("utf-8")

        _, stdout, printed_chunks = self._run_with_stdout_bytes(payload)
        printed = "".join(printed_chunks)

        self.assertEqual(printed, "│ lock info\n")
        self.assertNotIn("�", printed)
        self.assertEqual(stdout, ["│ lock info\n"])
        # The 3-byte "│" sequence collapses into a single decoded character
        # rather than 3 separate (mangled) print calls.
        self.assertEqual(printed_chunks[0], "│")

    def test_execute_command_flushes_prompt_without_trailing_newline(self):
        """A terraform prompt (e.g. `Enter a value:`) has no trailing newline
        and still must reach the user immediately, not be withheld waiting for
        a newline or process exit - otherwise interactive `apply` runs would
        appear to hang while actually waiting on stdin."""
        prompt = b"Enter a value: "

        # poll() reports "still running" for the first couple of checks after
        # the prompt bytes are read, so the read loop can't rely on process
        # exit to flush output - it must print as soon as each character is
        # decodable, not buffer until EOF.
        _, _, printed_chunks = self._run_with_stdout_bytes(prompt, poll_results=(None, None, 0))

        self.assertEqual("".join(printed_chunks), "Enter a value: ")
        # Each ASCII byte is printed as its own chunk as soon as it's decoded,
        # proving output isn't batched/withheld until the process exits.
        self.assertEqual(len(printed_chunks), len(prompt))

    def test_execute_command_replaces_truncated_multibyte_sequence_at_eof(self):
        """A multi-byte sequence truncated by process exit (e.g. output cut off
        mid-character) is replaced, not left buffered forever - proving the
        incremental decoder's final flush can't hang the read loop."""
        truncated = b"\xe2\x94"  # first two of three bytes of U+2502

        exit_code, stdout, printed_chunks = self._run_with_stdout_bytes(truncated)

        self.assertEqual(exit_code, 0)
        self.assertEqual("".join(printed_chunks), "�")
        self.assertEqual(stdout, ["�"])

    @patch("terrawrap.utils.cli._get_retriable_errors")
    @patch("io.open")
    def test_execute_command_retry(self, mock_open, mock_network_error):
        """Test retrying execution because of network errors"""
        self.mock_process.poll.side_effect = [1, 1, 1, 0]
        mock_network_error.side_effect = [["Throttling"], []]
        mock_stdout_read = mock_open.return_value
        mock_stdout_read.readline.return_value = b""

        exit_code, stdout = execute_command(["echo", "1"], retry=True)

        self.assertEqual(self.mock_popen.call_count, 2)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, [])

    @patch("terrawrap.utils.cli._get_retriable_errors")
    @patch("io.open")
    def test_execute_command_max_retry(self, mock_open, mock_network_error):
        """Test retrying execution because of network errors up to 5 times"""
        self.mock_process.poll.return_value = 255
        mock_network_error.side_effect = [
            ["Throttling"],
            ["unexpected EOF"],
            ["Throttling"],
            ["unexpected EOF"],
            ["Throttling"],
            ["unexpected EOF"],
        ]
        mock_stdout_read = mock_open.return_value
        mock_stdout_read.readline.return_value = b""

        exit_code, stdout = execute_command(["echo", "1"], retry=True)

        self.assertEqual(self.mock_popen.call_count, MAX_RETRIES)
        self.assertEqual(exit_code, 255)
        self.assertEqual(stdout, [])

    def test_get_retriable_errors_504(self):
        """Lines carrying a known transient signature (e.g. a 504 Gateway
        Timeout from the backend API) are retriable; unrelated lines are not."""
        lines = [
            "Error: error updating monitor: 504 Gateway Timeout\n",
            "Error: invalid resource address\n",
        ]

        self.assertEqual(
            _get_retriable_errors(lines),
            ["Error: error updating monitor: 504 Gateway Timeout\n"],
        )

    @patch.object(Logger, "error")
    @patch("terrawrap.utils.cli._post_audit_info")
    def test_execute_command_silent_error(self, mock_audit_info, mock_logger):
        """Test silent error execution because of network errors"""
        self.mock_process.poll.return_value = 255
        mock_audit_info_api = "MOCK_AUDIT_INFO_API"
        mock_error = MOCK_ERROR
        mock_audit_info.side_effect = mock_error

        expected_calls = [
            call("An error occurred while connecting to audit API: %s", mock_error),
            call("An error occurred while connecting to audit API: %s", mock_error),
        ]

        exit_code, stdout = execute_command(
            ["apply", "1"], audit_api_url=mock_audit_info_api, cwd=os.getcwd()
        )
        self.assertEqual(exit_code, 255)
        self.assertEqual(stdout, [])

        mock_logger.assert_has_calls(expected_calls)

    @patch("terrawrap.utils.cli._post_audit_info")
    def test_execute_command_multiple_audit_urls(self, mock_audit_info):
        """A list of audit API URLs posts the initial and update audit info to every URL."""
        self.mock_process.poll.return_value = 0
        urls = ["https://audit-a.example.com", "https://audit-b.example.com"]

        exit_code, _ = execute_command(["apply", "1"], audit_api_url=urls, cwd=os.getcwd())

        self.assertEqual(exit_code, 0)
        posted_urls = [c.kwargs["audit_api_url"] for c in mock_audit_info.call_args_list]
        # Initial 'in progress' post to each URL, then the status update to each URL.
        self.assertEqual(urls + urls, posted_urls)
        for update_call in mock_audit_info.call_args_list[2:]:
            self.assertTrue(update_call.kwargs["update"])

    @patch.object(Logger, "error")
    @patch("terrawrap.utils.cli._post_audit_info")
    def test_execute_command_multi_url_one_fails(self, mock_audit_info, mock_logger):
        """A failing audit URL is logged and does not block posting to the remaining URLs."""
        self.mock_process.poll.return_value = 0
        urls = ["https://audit-a.example.com", "https://audit-b.example.com"]
        mock_audit_info.side_effect = [MOCK_ERROR, None, MOCK_ERROR, None]

        exit_code, _ = execute_command(["apply", "1"], audit_api_url=urls, cwd=os.getcwd())

        self.assertEqual(exit_code, 0)
        posted_urls = [c.kwargs["audit_api_url"] for c in mock_audit_info.call_args_list]
        self.assertEqual(urls + urls, posted_urls)
        mock_logger.assert_has_calls(
            [
                call("An error occurred while connecting to audit API: %s", MOCK_ERROR),
                call("An error occurred while connecting to audit API: %s", MOCK_ERROR),
            ]
        )

    @patch("terrawrap.utils.cli.BotoAWSRequestsAuth")
    @patch("requests.post")
    def test_post_audit_info_statuses(self, mock_post, _):
        """Test Audit API helper function for each possible status"""
        statuses = {Status.IN_PROGRESS: None, Status.FAILED: 2, Status.SUCCESS: 0}

        fake_url = "https://foo.bar"
        os.chdir(os.path.normpath(os.path.dirname(__file__) + "/../helpers"))

        for status, exit_code in statuses.items():
            _post_audit_info(
                audit_api_url=fake_url,
                path=os.path.join(os.getcwd(), "mock_directory/config/.tf_wrapper"),
                start_time=12345,
                exit_code=exit_code,
            )

            mock_post.assert_called_with(
                url="https://foo.bar/audit_info",
                auth=ANY,
                json={
                    "directory": "/test/helpers/mock_directory/config/.tf_wrapper",
                    "start_time": 12345,
                    "status": status,
                    "output": "",
                    "git_hash": ANY,
                    # ANY: build_id is read from CODEBUILD_BUILD_ID, which is None
                    # locally but set when this suite runs inside CodeBuild.
                    "build_id": ANY,
                },
                timeout=30,
            )

    @patch.dict(os.environ, {"CODEBUILD_BUILD_ID": "terraform-apply:abc-123"})
    @patch("terrawrap.utils.cli.BotoAWSRequestsAuth")
    @patch("requests.post")
    def test_post_audit_info_echoes_build_id(self, mock_post, _):
        """The audit payload echoes CODEBUILD_BUILD_ID so the API can correlate
        the apply back to its UI-triggered PENDING placeholder."""
        os.chdir(os.path.normpath(os.path.dirname(__file__) + "/../helpers"))

        _post_audit_info(
            audit_api_url="https://foo.bar",
            path=os.path.join(os.getcwd(), "mock_directory/config/.tf_wrapper"),
            start_time=12345,
            exit_code=0,
        )

        self.assertEqual(mock_post.call_args.kwargs["json"]["build_id"], "terraform-apply:abc-123")

    @patch.dict(os.environ)
    @patch("terrawrap.utils.cli.BotoAWSRequestsAuth")
    @patch("requests.post")
    def test_post_audit_info_build_id_empty(self, mock_post, _):
        """Outside CodeBuild (e.g. a pipeline ECS apply) build_id is "" — never
        None, since the API deserializes build_id as a required str and rejects
        null."""
        os.environ.pop("CODEBUILD_BUILD_ID", None)
        os.chdir(os.path.normpath(os.path.dirname(__file__) + "/../helpers"))

        _post_audit_info(
            audit_api_url="https://foo.bar",
            path=os.path.join(os.getcwd(), "mock_directory/config/.tf_wrapper"),
            start_time=12345,
            exit_code=0,
        )

        self.assertEqual(mock_post.call_args.kwargs["json"]["build_id"], "")

    @patch("terrawrap.utils.cli.BotoAWSRequestsAuth")
    @patch("requests.post")
    def test_post_audit_info_signs_for_url_host(self, _, mock_auth):
        """SigV4 host must come from the audit_api_url, not a hardcoded value."""
        os.chdir(os.path.normpath(os.path.dirname(__file__) + "/../helpers"))

        _post_audit_info(
            audit_api_url="https://terraform-audit-api.devops-testing.amplify.com",
            path=os.path.join(os.getcwd(), "mock_directory/config/.tf_wrapper"),
            start_time=12345,
            exit_code=0,
        )

        mock_auth.assert_called_with(
            aws_host="terraform-audit-api.devops-testing.amplify.com",
            aws_region="us-west-2",
            aws_service="execute-api",
        )


class TestPostLogChunk(TestCase):
    """Test the log-chunk POST helper"""

    @patch("terrawrap.utils.cli.BotoAWSRequestsAuth")
    @patch("requests.post")
    def test_post_log_chunk_payload(self, mock_post, _):
        """Posts directory/start_time/sequence/content to the log_chunk endpoint"""
        os.chdir(os.path.normpath(os.path.dirname(__file__) + "/../helpers"))

        _post_log_chunk(
            audit_api_url="https://foo.bar",
            path=os.path.join(os.getcwd(), "mock_directory/config/.tf_wrapper"),
            start_time=12345,
            sequence=2,
            content="hello\n",
        )

        mock_post.assert_called_once_with(
            url="https://foo.bar/log_chunk",
            auth=ANY,
            json={
                "directory": "/test/helpers/mock_directory/config/.tf_wrapper",
                "start_time": 12345,
                "sequence": 2,
                "content": "hello\n",
            },
            timeout=10,
        )

    @patch("terrawrap.utils.cli.BotoAWSRequestsAuth")
    @patch("requests.post")
    def test_post_log_chunk_signs_for_url_host(self, _, mock_auth):
        """SigV4 host must come from the audit_api_url, not a hardcoded value."""
        os.chdir(os.path.normpath(os.path.dirname(__file__) + "/../helpers"))

        _post_log_chunk(
            audit_api_url="https://terraform-audit-api.devops-testing.amplify.com",
            path=os.path.join(os.getcwd(), "mock_directory/config/.tf_wrapper"),
            start_time=12345,
            sequence=0,
            content="x",
        )

        mock_auth.assert_called_with(
            aws_host="terraform-audit-api.devops-testing.amplify.com",
            aws_region="us-west-2",
            aws_service="execute-api",
        )

    @patch("terrawrap.utils.cli.BotoAWSRequestsAuth")
    @patch("requests.post")
    def test_post_log_chunk_raises_on_http_error(self, mock_post, _):
        """A non-2xx response raises, so the caller decides how to handle it."""
        mock_post.return_value.raise_for_status.side_effect = MOCK_ERROR
        os.chdir(os.path.normpath(os.path.dirname(__file__) + "/../helpers"))

        with self.assertRaises(HTTPError):
            _post_log_chunk(
                audit_api_url="https://foo.bar",
                path=os.path.join(os.getcwd(), "mock_directory/config/.tf_wrapper"),
                start_time=12345,
                sequence=0,
                content="x",
            )


class TestChunkStreaming(TestCase):
    """Test that execute_command streams log chunks via on_chunk during apply/destroy.

    Runs a real short-lived subprocess (no Popen mock) so the byte-by-byte
    read/flush logic in _execute_command is exercised end to end.
    """

    def setUp(self):
        self.audit_info_patcher = patch("terrawrap.utils.cli._post_audit_info")
        self.audit_info_patcher.start()

    def tearDown(self):
        self.audit_info_patcher.stop()

    @patch("terrawrap.utils.cli._post_log_chunk")
    def test_streams_chunks_when_applying(self, mock_post_chunk):
        """Output is flushed once at the CHUNK_LINE_COUNT threshold and once more at EOF"""
        code = "\n".join(f"print({i})" for i in range(15))
        exit_code, _ = execute_command(
            ["python3", "-c", code, "apply"],
            audit_api_url="https://foo.bar",
            cwd=os.getcwd(),
            print_output=False,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_post_chunk.call_count, 2)
        sequences = [c.kwargs["sequence"] for c in mock_post_chunk.call_args_list]
        self.assertEqual(sequences, [0, 1])

        first_chunk, second_chunk = (c.kwargs["content"] for c in mock_post_chunk.call_args_list)
        self.assertEqual(first_chunk.count("\n"), 10)
        self.assertEqual(second_chunk, "10\n11\n12\n13\n14\n")

    @patch("terrawrap.utils.cli._post_log_chunk")
    def test_no_streaming_without_audit_api_url(self, mock_post_chunk):
        """No audit_api_url means no chunk streaming, even for an apply command"""
        execute_command(
            ["python3", "-c", "print('x')", "apply"],
            cwd=os.getcwd(),
            print_output=False,
        )

        mock_post_chunk.assert_not_called()

    @patch("terrawrap.utils.cli._post_log_chunk")
    def test_no_streaming_for_non_apply_commands(self, mock_post_chunk):
        """Streaming only triggers for apply/destroy commands"""
        execute_command(
            ["python3", "-c", "print('x')"],
            audit_api_url="https://foo.bar",
            cwd=os.getcwd(),
            print_output=False,
        )

        mock_post_chunk.assert_not_called()

    @patch("terrawrap.utils.cli._post_log_chunk")
    def test_chunk_post_failure_swallowed(self, mock_post_chunk):
        """A log-chunk POST failure is swallowed by design — this is opt-in telemetry
        riding alongside the real apply, so any failure here (network, git, auth) must
        never take down the apply itself. Raising a generic Exception (not just a
        requests error) proves the broad except in _chunk_callback is intentional."""
        mock_post_chunk.side_effect = Exception("boom")

        exit_code, _ = execute_command(
            ["python3", "-c", "print('x')", "apply"],
            audit_api_url="https://foo.bar",
            cwd=os.getcwd(),
            print_output=False,
        )

        self.assertEqual(exit_code, 0)
