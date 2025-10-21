"""Test git utilities"""
import errno
import os
from logging import Logger
from unittest import TestCase
from unittest.mock import patch, ANY, call, mock_open, MagicMock
from requests.exceptions import HTTPError

from terrawrap.utils.cli import execute_command, MAX_RETRIES, Status, _post_audit_info, _execute_command


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

    @patch("terrawrap.utils.cli.BotoAWSRequestsAuth")
    @patch("requests.post")
    def test_post_audit_info_statuses(self, mock_post, _):
        """Test Audit API helper function for each possible status"""
        statuses = {Status.IN_PROGRESS: None, Status.FAILED: 2, Status.SUCCESS: 0}

        fake_url = "foo.bar"
        os.chdir(os.path.normpath(os.path.dirname(__file__) + "/../helpers"))

        for status, exit_code in statuses.items():
            _post_audit_info(
                audit_api_url=fake_url,
                path=os.path.join(os.getcwd(), "mock_directory/config/.tf_wrapper"),
                start_time=12345,
                exit_code=exit_code,
            )

            mock_post.assert_called_with(
                url="foo.bar/audit_info",
                auth=ANY,
                json={
                    "directory": "/test/helpers/mock_directory/config/.tf_wrapper",
                    "start_time": 12345,
                    "status": status,
                    "output": "",
                    "git_hash": ANY,
                },
                timeout=30,
            )

    @patch("tempfile.mkstemp")
    @patch.object(Logger, "warning")
    def test_execute_command_memory_error(self, mock_logger, mock_mkstemp):
        """Test handling of OSError errno 12 (Cannot allocate memory) during command execution"""
        # Setup mock file objects
        mock_stdout_fd = 3
        mock_stdout_path = "/tmp/mock_stdout"
        mock_mkstemp.return_value = (mock_stdout_fd, mock_stdout_path)
        
        # Create mock file object that raises OSError ENOMEM on first read, then succeeds
        mock_file = MagicMock()
        memory_error = OSError()
        memory_error.errno = errno.ENOMEM  # Cannot allocate memory
        
        # Configure read to fail first, then succeed
        mock_file.read.side_effect = [
            memory_error,  # First read fails with memory error
            b"test output",  # Second read succeeds with reduced buffer
            b"",  # Third read returns empty (process finished)
            b"",  # Additional reads for final output collection
            b"",  # More reads to handle any additional calls
        ] + [b""] * 10  # Ensure we have enough empty responses
        
        # Mock process
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # Process finished successfully
        
        with patch("builtins.open", mock_open()) as mock_file_open:
            mock_file_open.return_value.__enter__.return_value = mock_file
            
            with patch("subprocess.Popen", return_value=mock_process):
                # Test that the function handles memory error gracefully
                exit_code, stdout = _execute_command(
                    ["test", "command"],
                    print_output=False,
                    capture_stderr=True,
                    print_command=False
                )
                
                # Verify the function completed successfully
                self.assertEqual(exit_code, 0)
                self.assertIsInstance(stdout, list)
                
                # Verify that warning was logged about memory allocation issue
                mock_logger.assert_called_with(
                    "Memory allocation issue while reading output, reducing buffer size"
                )
                
                # Verify that read was called multiple times (initial failure, then retry)
                self.assertTrue(mock_file.read.call_count >= 2)

    @patch("tempfile.mkstemp")
    @patch.object(Logger, "warning")
    def test_execute_command_memory_error_final_read(self, mock_logger, mock_mkstemp):
        """Test handling of OSError errno 12 during final output reading"""
        # Setup mock file objects
        mock_stdout_fd = 3
        mock_stdout_path = "/tmp/mock_stdout"
        mock_mkstemp.return_value = (mock_stdout_fd, mock_stdout_path)
        
        # Create mock file object that works for live reading but fails on final read
        mock_file = MagicMock()
        memory_error = OSError()
        memory_error.errno = errno.ENOMEM  # Cannot allocate memory
        
        # Setup side effects: normal read during live output, then memory error on seek+read
        mock_file.read.side_effect = [b"", memory_error]  # Empty for live, error for final
        mock_process = MagicMock()
        mock_process.poll.return_value = 0
        
        with patch("builtins.open", mock_open()) as mock_file_open:
            mock_file_open.return_value.__enter__.return_value = mock_file
            
            with patch("subprocess.Popen", return_value=mock_process):
                # Test that the function handles memory error gracefully during final read
                exit_code, stdout = _execute_command(
                    ["test", "command"],
                    print_output=False,
                    capture_stderr=True,
                    print_command=False
                )
                
                # Verify the function completed successfully
                self.assertEqual(exit_code, 0)
                
                # Verify that warning was logged about memory allocation issue during final read
                mock_logger.assert_called_with(
                    "Memory allocation issue while reading final output, truncating"
                )
                
                # Verify that stdout contains the truncation message
                self.assertIn("...[Output truncated due to memory constraints]...\n", stdout)
