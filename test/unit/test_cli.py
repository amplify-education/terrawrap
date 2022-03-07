"""Test git utilities"""
from unittest import TestCase
from mock import patch

import requests_mock
import getpass

from terrawrap.utils.cli import execute_command, MAX_RETRIES


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

    @patch('getpass.getuser')
    def test_set_audit_api_url(self, mock_getuser_func):
        mock_getuser_func.return_value = 'mockuser'
        expected_body = '{"directory": "test", "status": "FAILED", "run_by": "mockuser", "output": []}'

        with requests_mock.Mocker() as mocker:
            mocker.register_uri(requests_mock.ANY, requests_mock.ANY, text='test message')
            execute_command(['test', '0'], audit_api_url='http://test.com')

            assert mocker.called_once
            assert mocker.last_request.body.decode('utf-8') == expected_body
