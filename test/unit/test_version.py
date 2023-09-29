"""Test version utils"""
from unittest import TestCase

from mock import patch, MagicMock

from terrawrap.utils.version import version_check, get_latest_version, cache


class TestVersion(TestCase):
    """Test version utils"""

    def setUp(self) -> None:
        cache.clear()

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
    @patch("terrawrap.utils.version.Cache", MagicMock())
    def test_get_latest_version_happy(self, mock_get):
        """VersionUtils get latest version happy path"""
        current_version = "1.0.0"
        latest_version = "1.0.1"
        mock_get.return_value.json.return_value = {"info": {"version": latest_version}}

        response = get_latest_version(current_version=current_version)

        self.assertEqual(
            response,
            latest_version,
        )
