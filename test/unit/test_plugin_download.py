"""Tests for file downloading utilities"""
from unittest import TestCase
from unittest.mock import patch, mock_open, MagicMock, call

import requests_mock
from botocore.exceptions import ClientError

from terrawrap.utils.plugin_download import FileDownloadFailed, PluginDownload


class TestPluginDownload(TestCase):
    """Tests for file downloading utilities"""

    def setUp(self) -> None:
        self.s3_client = MagicMock()
        self.plugin_download = PluginDownload(self.s3_client)

    @requests_mock.Mocker()
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.isfile", MagicMock(return_value=False))
    @patch("os.stat", MagicMock())
    @patch("os.chmod", MagicMock())
    def test_file_download(self, mock_requests, open_mock):
        """Test downloading a file"""
        mock_requests.register_uri("GET", "http://example.com", content=b"fake content")

        self.plugin_download._download_file("http://example.com", "/tmp/plugins/foo")

        file_write_call = call(b"fake content")

        open_mock.return_value.write.assert_has_calls([file_write_call])

    @requests_mock.Mocker()
    @patch("builtins.open", new_callable=mock_open, read_data="1234")
    @patch("os.path.isfile", MagicMock(return_value=True))
    @patch("os.stat", MagicMock())
    @patch("os.chmod", MagicMock())
    def test_file_download_with_etag(self, mock_requests, open_mock):
        """Test downloading a file and saving it's etag"""
        mock_requests.register_uri(
            "GET",
            "http://example.com",
            headers={"Etag": "fake_etag"},
            content=b"fake content",
        )

        self.plugin_download._download_file("http://example.com", "/tmp/plugins/foo")

        etag_write_call = call("fake_etag")
        file_write_call = call(b"fake content")

        open_mock.return_value.write.assert_has_calls(
            [file_write_call, etag_write_call]
        )

    @requests_mock.Mocker()
    @patch("builtins.open", new_callable=mock_open, read_data="fake_etag")
    @patch("os.path.isfile", MagicMock(return_value=True))
    def test_file_download_cached(self, mock_requests, open_mock):
        """Test downloading a file and saving it's etag"""
        mock_requests.register_uri("GET", "http://example.com", status_code=304)

        self.plugin_download._download_file("http://example.com", "/tmp/plugins/foo")

        # assert we don't write anything if response returns a 304
        # 304 response means we sent a matching Etag and therefore should use the cached version of the file
        open_mock.return_value.write.assert_has_calls([])

    @patch("os.path.expanduser", MagicMock(return_value="/home/fake_user"))
    @patch("os.makedirs", MagicMock())
    @patch("terrawrap.utils.plugin_download.FileLock", MagicMock())
    @patch("platform.system", MagicMock(return_value="FakeLinux"))
    @patch("platform.machine", MagicMock(return_value="x86_42"))
    def test_download_plugins(self):
        """Test downloading plugins"""
        with patch.object(self.plugin_download, "_download_file") as download_file_mock:
            self.plugin_download.download_plugins({"foo": "http://example.com"})

            download_file_mock.assert_called_with(
                "http://example.com/FakeLinux/x86_42",
                "/home/fake_user/.terraform.d/plugins/foo",
            )

    @patch("os.path.expanduser", MagicMock(return_value="/home/fake_user"))
    @patch("os.makedirs", MagicMock())
    @patch("terrawrap.utils.plugin_download.FileLock", MagicMock())
    @patch("platform.system", MagicMock(return_value="FakeLinux"))
    @patch("platform.machine", MagicMock(return_value="x86_42"))
    def test_download_plugins_platform_missing(self):
        """Test downloading plugins and falling back to non-platform specific files"""
        with patch.object(self.plugin_download, "_download_file") as download_file_mock:

            def _download_mock_side_effect(url, _):
                if url != "http://example.com":
                    raise FileDownloadFailed()

            download_file_mock.side_effect = _download_mock_side_effect

            self.plugin_download.download_plugins({"foo": "http://example.com"})

            platform_specific_call = call(
                "http://example.com/FakeLinux/x86_42",
                "/home/fake_user/.terraform.d/plugins/foo",
            )
            generic_call = call(
                "http://example.com", "/home/fake_user/.terraform.d/plugins/foo"
            )

            download_file_mock.assert_has_calls([platform_specific_call, generic_call])

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.isfile", MagicMock(return_value=False))
    @patch("os.stat", MagicMock())
    @patch("os.chmod", MagicMock())
    def test_download_from_s3(self, open_mock):
        """Test downloading a file from S3"""
        mock_content = MagicMock()
        mock_content.read.return_value = b"fake content"

        self.s3_client.get_object.return_value = {
            "Body": mock_content,
            "ETag": "fake_etag",
        }

        self.plugin_download._download_file("s3://test/bar", "/tmp/plugins/foo")

        etag_write_call = call("fake_etag")
        file_write_call = call(b"fake content")

        open_mock.return_value.write.assert_has_calls(
            [file_write_call, etag_write_call]
        )

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.isfile", MagicMock(return_value=False))
    def test_download_from_s3_cached(self, open_mock):
        """Test downloading a file from s3 that is cached"""
        self.s3_client.get_object.side_effect = ClientError(
            {"Error": {"Code": "304"}}, ""
        )

        self.plugin_download._download_file("s3://test/bar", "/tmp/plugins/foo")

        open_mock.return_value.write.assert_has_calls([])
