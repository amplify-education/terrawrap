"""Test version utils"""
import json
import os
import tempfile

from datetime import datetime, timedelta
from unittest import TestCase

from mock import patch, MagicMock, ANY

from terrawrap.utils.version import version_check, get_latest_version, get_cache, set_cache


class TestVersion(TestCase):
    """Test version utils"""

    @patch("terrawrap.utils.version.sleep", MagicMock())
    @patch("terrawrap.utils.version.get_latest_version")
    def test_version_check_older(self, mock_get_latest_version):
        """VersionUtils version check with older version"""
        current_version = "1.0.0"
        latest_version = "1.0.1"
        mock_get_latest_version.return_value = latest_version

        response = version_check(current_version=current_version)

        self.assertEqual(
            response,
            True,
        )

    @patch("terrawrap.utils.version.get_latest_version")
    def test_version_check_newer(self, mock_get_latest_version):
        """VersionUtils version check with newer version"""
        current_version = "1.0.1"
        latest_version = "1.0.0"
        mock_get_latest_version.return_value = latest_version

        response = version_check(current_version=current_version)

        self.assertEqual(
            response,
            False,
        )

    @patch("terrawrap.utils.version.get_latest_version")
    def test_version_check_equal(self, mock_get_latest_version):
        """VersionUtils version check with equal version"""
        current_version = "1.0.0"
        latest_version = "1.0.0"
        mock_get_latest_version.return_value = latest_version

        response = version_check(current_version=current_version)

        self.assertEqual(
            response,
            False,
        )

    @patch("terrawrap.utils.version.get_latest_version")
    def test_version_check_handles_exception(self, mock_get_latest_version):
        """VersionUtils version check swallows exception"""
        current_version = "1.0.0"
        mock_get_latest_version.side_effect = RuntimeError

        response = version_check(current_version=current_version)

        self.assertEqual(
            response,
            False,
        )

    @patch("requests.get")
    @patch("terrawrap.utils.version.get_cache")
    def test_get_latest_version_valid_cache(self, mock_get_cache, mock_requests_get):
        """VersionUtils get latest version with valid cache"""
        current_version = "1.0.0"
        latest_version = "1.0.0"
        mock_cache = {
            "timestamp": datetime.utcnow(),
            "latest_version": current_version,
            "current_version": latest_version,
        }
        mock_get_cache.return_value = mock_cache

        response = get_latest_version(current_version=current_version)

        self.assertEqual(
            response,
            latest_version,
        )
        mock_requests_get.assert_not_called()

    @patch("requests.get")
    @patch("terrawrap.utils.version.set_cache")
    @patch("terrawrap.utils.version.get_cache")
    def test_get_latest_version_old_cache(self, mock_get_cache, mock_set_cache, mock_requests_get):
        """VersionUtils get latest version with old cache"""
        current_version = "1.0.0"
        latest_version = "1.0.1"
        mock_cache = {
            "timestamp": datetime.utcnow() - timedelta(days=1),
            "latest_version": current_version,
            "current_version": current_version,
        }
        mock_get_cache.return_value = mock_cache
        mock_requests_get.return_value.json.return_value = {
            "info": {
                "version": latest_version
            }
        }

        response = get_latest_version(current_version=current_version)

        self.assertEqual(
            response,
            latest_version,
        )
        mock_set_cache.assert_called_once_with(
            cache_file_path=ANY,
            latest_version=latest_version,
            current_version=current_version,
        )

    def test_get_cache_no_file(self):
        """VersionUtils get cache with no file"""
        cache_file_path = os.path.join(os.path.dirname(__file__), "does_not_exist_cache")

        response = get_cache(cache_file_path=cache_file_path)

        self.assertEqual(
            response,
            {},
        )

    @patch("json.load")
    def test_get_cache_bad_file(self, mock_json_load):
        """VersionUtils get cache with malformed file"""
        cache_file_path = os.path.join(os.path.dirname(__file__), "invalid_json_cache")
        mock_json_load.side_effect = json.decoder.JSONDecodeError(
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        response = get_cache(cache_file_path=cache_file_path)

        self.assertEqual(
            response,
            {},
        )

    def test_get_cache_good_file(self):
        """VersionUtils get cache with good file"""
        cache_file_path = os.path.join(os.path.dirname(__file__), "valid_cache")
        current_version = "1.0.0"
        latest_version = "1.0.1"

        response = get_cache(cache_file_path=cache_file_path)

        self.assertEqual(
            response,
            {
                "timestamp": datetime(2019, 9, 17, 11, 53, 13, 31919),
                "latest_version": latest_version,
                "current_version": current_version,
            }
        )

    @patch("terrawrap.utils.version.datetime")
    @patch("json.dump")
    def test_set_cache(self, mock_dump, mock_datetime):
        """VersionUtils set cache"""
        # pylint: disable=unused-variable
        cache_file, cache_file_path = tempfile.mkstemp()
        current_version = "1.0.0"
        latest_version = "1.0.1"

        set_cache(
            cache_file_path=cache_file_path,
            latest_version=latest_version,
            current_version=current_version,
        )

        mock_dump.assert_called_once_with(
            {
                "timestamp": mock_datetime.utcnow.return_value.isoformat.return_value,
                "latest_version": latest_version,
                "current_version": current_version,
            },
            ANY
        )
