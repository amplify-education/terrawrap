"""Test git utilities"""
import os
from unittest import TestCase

from mock import patch, ANY

from terrawrap.utils.cli import execute_command, MAX_RETRIES, Status, _post_audit_info


class TestCli(TestCase):
    """Test cli utilities"""

    def setUp(self):
        self.popen_patcher = patch('subprocess.Popen')
        self.mock_popen = self.popen_patcher.start()
        self.mock_process = self.mock_popen.return_value

        self.jitter_patcher = patch('terrawrap.utils.cli.Jitter')
        self.mock_jitter = self.jitter_patcher.start()
        self.mock_jitter.return_value.backoff.return_value = 3

    def tearDown(self):
        self.popen_patcher.stop()
        self.jitter_patcher.stop()

    def test_execute_command(self):
        """Test executing a command successfully"""
        self.mock_process.poll.return_value = 0
        exit_code, stdout = execute_command(['echo', '1 '])

        self.assertEqual(self.mock_popen.call_count, 1)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, [])

    @patch('terrawrap.utils.cli._get_retriable_errors')
    @patch('io.open')
    def test_execute_command_retry(self, mock_open, mock_network_error):
        """Test retrying execution because of network errors"""
        self.mock_process.poll.side_effect = [1, 1, 1, 0]
        mock_network_error.side_effect = [["Throttling"], []]
        mock_stdout_read = mock_open.return_value
        mock_stdout_read.readline.return_value = b''

        exit_code, stdout = execute_command(['echo', '1'], retry=True)

        self.assertEqual(self.mock_popen.call_count, 2)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, [])

    @patch('terrawrap.utils.cli._get_retriable_errors')
    @patch('io.open')
    def test_execute_command_max_retry(self, mock_open, mock_network_error):
        """Test retrying execution because of network errors up to 5 times"""
        self.mock_process.poll.return_value = 255
        mock_network_error.side_effect = [
            ["Throttling"],
            ["unexpected EOF"],
            ["Throttling"],
            ["unexpected EOF"],
            ["Throttling"],
            ["unexpected EOF"]
        ]
        mock_stdout_read = mock_open.return_value
        mock_stdout_read.readline.return_value = b''

        exit_code, stdout = execute_command(['echo', '1'], retry=True)

        self.assertEqual(self.mock_popen.call_count, MAX_RETRIES)
        self.assertEqual(exit_code, 255)
        self.assertEqual(stdout, [])

    @patch('requests.post')
    def test_post_audit_info_statuses(self, mock_post):
        """Test Audit API helper function for each possible status"""
        statuses = {
            Status.IN_PROGRESS: None,
            Status.FAILED: 2,
            Status.SUCCESS: 0
        }

        fake_url = 'foo.bar'
        os.chdir(os.path.normpath(os.path.dirname(__file__) + '/../helpers'))

        for status, exit_code in statuses.items():
            _post_audit_info(
                audit_api_url=fake_url,
                path=os.path.join(os.getcwd(), 'mock_directory/config/.tf_wrapper'),
                start_time=12345,
                exit_code=exit_code
            )

            mock_post.assert_called_with(
                url='foo.bar/audit_info',
                auth=ANY,
                json={
                    'directory': '/test/helpers/mock_directory/config/.tf_wrapper',
                    'start_time': 12345,
                    'status': status,
                    'output': ''
                },
                timeout=30,
            )
