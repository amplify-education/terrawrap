"""Tests for file downloading utilities"""
from unittest import TestCase
from unittest.mock import patch, mock_open, MagicMock, call

import requests_mock
from requests import HTTPError

from terrawrap.utils.file_download import download_file, download_plugins


class TestFileDownload(TestCase):
    """Tests for file downloading utilities"""
    @requests_mock.Mocker()
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.path.isfile', MagicMock(return_value=True))
    def test_file_download(self, mock_requests, open_mock):
        """Test downloading a file"""
        mock_requests.register_uri('GET', 'http://example.com', content=b'fake content')

        download_file('http://example.com', '/tmp/plugins/foo')

        file_write_call = call(b'fake content')

        open_mock.return_value.write.assert_has_calls([file_write_call])

    @requests_mock.Mocker()
    @patch('builtins.open', new_callable=mock_open, read_data='1234')
    @patch('os.path.isfile', MagicMock(return_value=True))
    def test_file_download_with_etag(self, mock_requests, open_mock):
        """Test downloading a file and saving it's etag"""
        mock_requests.register_uri(
            'GET',
            'http://example.com',
            headers={'Etag': 'fake_etag'},
            content=b'fake content'
        )

        download_file('http://example.com', '/tmp/plugins/foo')

        etag_write_call = call('fake_etag')
        file_write_call = call(b'fake content')

        open_mock.return_value.write.assert_has_calls([file_write_call, etag_write_call])

    @requests_mock.Mocker()
    @patch('builtins.open', new_callable=mock_open, read_data='fake_etag')
    @patch('os.path.isfile', MagicMock(return_value=True))
    def test_file_download_cached(self, mock_requests, open_mock):
        """Test downloading a file and saving it's etag"""
        mock_requests.register_uri(
            'GET',
            'http://example.com',
            status_code=304
        )

        download_file('http://example.com', '/tmp/plugins/foo')

        # assert we don't write anything if response returns a 304
        # 304 response means we sent a matching Etag and therefore should use the cached version of the file
        open_mock.return_value.write.assert_has_calls([])

    @patch('terrawrap.utils.file_download.download_file')
    @patch('os.path.expanduser', MagicMock(return_value='/home/fake_user'))
    @patch('terrawrap.utils.file_download.FileLock', MagicMock())
    @patch('platform.system', MagicMock(return_value='FakeLinux'))
    @patch('platform.machine', MagicMock(return_value='x86_42'))
    def test_download_plugins(self, download_file_mock):
        """Test downloading plugins"""
        download_plugins({
            'foo': 'example.com'
        })

        download_file_mock.assert_called_with(
            'example.com/FakeLinux/x86_42',
            '/home/fake_user/.terraform.d/plugins/foo'
        )

    @patch('terrawrap.utils.file_download.download_file')
    @patch('os.path.expanduser', MagicMock(return_value='/home/fake_user'))
    @patch('terrawrap.utils.file_download.FileLock', MagicMock())
    @patch('platform.system', MagicMock(return_value='FakeLinux'))
    @patch('platform.machine', MagicMock(return_value='x86_42'))
    def test_download_plugins_platform_missing(self, download_file_mock):
        """Test downloading plugins and falling back to non-platform specific files"""
        def _download_mock_side_effect(url, _):
            if url != 'example.com':
                raise HTTPError()

        download_file_mock.side_effect = _download_mock_side_effect

        download_plugins({
            'foo': 'example.com'
        })

        platform_specific_call = call(
            'example.com/FakeLinux/x86_42',
            '/home/fake_user/.terraform.d/plugins/foo'
        )
        generic_call = call(
            'example.com',
            '/home/fake_user/.terraform.d/plugins/foo'
        )

        download_file_mock.assert_has_calls([platform_specific_call, generic_call])
