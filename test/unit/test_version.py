"""Test version utils"""

import os
import pickle
import shutil
import sqlite3
import tempfile
from unittest import TestCase
from unittest.mock import MagicMock, patch

from terrawrap.utils.version import cache, get_latest_version, version_check


class TestVersion(TestCase):
    """Test version utils"""

    def setUp(self) -> None:
        cache.clear()

    @patch("terrawrap.utils.version.sleep", MagicMock())
    @patch("terrawrap.utils.version.get_latest_version")
    def test_version_check_older(self, mock_get_latest_version):
        """VersionUtils version check with older version"""
        current_version = "1.0.0"
        mock_get_latest_version.return_value = ("1.0.1", None)

        response = version_check(current_version=current_version)

        self.assertTrue(response)

    @patch("terrawrap.utils.version.get_latest_version")
    def test_version_check_newer(self, mock_get_latest_version):
        """VersionUtils version check with newer version"""
        current_version = "1.0.1"
        mock_get_latest_version.return_value = ("1.0.0", None)

        response = version_check(current_version=current_version)

        self.assertFalse(response)

    @patch("terrawrap.utils.version.get_latest_version")
    def test_version_check_equal(self, mock_get_latest_version):
        """VersionUtils version check with equal version"""
        current_version = "1.0.0"
        mock_get_latest_version.return_value = ("1.0.0", None)

        response = version_check(current_version=current_version)

        self.assertFalse(response)

    @patch("terrawrap.utils.version.get_latest_version")
    def test_version_check_rc_available(self, mock_get_latest_version):
        """VersionUtils version check prints RC notice when RC is newer"""
        current_version = "1.0.0"
        mock_get_latest_version.return_value = ("1.0.0", "1.0.1rc1")

        response = version_check(current_version=current_version)

        self.assertFalse(response)

    @patch("terrawrap.utils.version.sleep", MagicMock())
    @patch("terrawrap.utils.version.get_latest_version")
    def test_version_check_stale_with_rc(self, mock_get_latest_version):
        """VersionUtils version check returns stale and shows RC when both apply"""
        current_version = "1.0.0"
        mock_get_latest_version.return_value = ("1.0.1", "1.0.2rc1")

        response = version_check(current_version=current_version)

        self.assertTrue(response)

    @patch("terrawrap.utils.version.sleep", MagicMock())
    @patch("terrawrap.utils.version.get_latest_version")
    def test_version_check_rc_older_than_stable(self, mock_get_latest_version):
        """RC alert is suppressed when an equal-or-newer stable already exists"""
        current_version = "1.0.0"
        # An RC for 1.1.0 exists, but 1.1.0 stable has already shipped — don't
        # suggest opting into the older RC.
        mock_get_latest_version.return_value = ("1.1.0", "1.1.0rc2")

        with patch("sys.stderr") as mock_stderr:
            response = version_check(current_version=current_version)

        self.assertTrue(response)
        printed = "".join(call.args[0] for call in mock_stderr.write.call_args_list if call.args)
        self.assertNotIn("release candidate", printed)

    @patch("terrawrap.utils.version.get_latest_version")
    def test_version_check_rc_on_matching_stable(self, mock_get_latest_version):
        """No RC alert when current version is the published release of that RC"""
        current_version = "0.11.0"
        mock_get_latest_version.return_value = ("0.11.0", "0.11.0rc2")

        with patch("sys.stderr") as mock_stderr:
            response = version_check(current_version=current_version)

        self.assertFalse(response)
        printed = "".join(call.args[0] for call in mock_stderr.write.call_args_list if call.args)
        self.assertNotIn("release candidate", printed)

    @patch("terrawrap.utils.version.get_latest_version")
    def test_version_check_handles_exception(self, mock_get_latest_version):
        """VersionUtils version check swallows exception"""
        current_version = "1.0.0"
        mock_get_latest_version.side_effect = RuntimeError

        response = version_check(current_version=current_version)

        self.assertFalse(response)

    @patch("requests.get")
    @patch("terrawrap.utils.version.Cache", MagicMock())
    def test_get_latest_version_happy(self, mock_get):
        """VersionUtils get latest version returns stable and rc"""
        current_version = "1.0.0"
        mock_get.return_value.json.return_value = {"releases": {"1.0.0": [], "1.0.1": [], "1.0.2rc1": []}}

        # pylint:disable=C0103
        stable, rc = get_latest_version(current_version=current_version)

        self.assertEqual(stable, "1.0.1")
        self.assertEqual(rc, "1.0.2rc1")

    @patch("requests.get")
    @patch("terrawrap.utils.version.Cache", MagicMock())
    def test_get_latest_version_no_rc(self, mock_get):
        """VersionUtils get latest version returns None for rc when no RCs exist"""
        current_version = "1.0.0"
        mock_get.return_value.json.return_value = {"releases": {"1.0.0": [], "1.0.1": []}}
        # pylint:disable=C0103
        stable, rc = get_latest_version(current_version=current_version)

        self.assertEqual(stable, "1.0.1")
        self.assertIsNone(rc)

    @patch("requests.get")
    def test_get_latest_version_cache_refuses_pickled_entries(self, mock_get):
        """VersionUtils treats a cache entry rewritten to hold a pickle as a miss"""
        mock_get.return_value.json.return_value = {"releases": {"1.0.0": [], "1.0.1": []}}
        marker_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, marker_dir)
        self.addCleanup(cache.clear)
        marker = os.path.join(marker_dir, "marker")

        self.assertEqual(get_latest_version(current_version="1.0.0"), ("1.0.1", None))
        self.assertEqual(get_latest_version(current_version="1.0.0"), ("1.0.1", None))
        self.assertEqual(mock_get.call_count, 1)

        connection = sqlite3.connect(os.path.join(cache.directory, "cache.db"))
        connection.execute(
            "UPDATE Cache SET mode = 4, value = ?",
            (pickle.dumps(_Planted(marker), protocol=2),),
        )
        connection.commit()
        connection.close()

        self.assertEqual(get_latest_version(current_version="1.0.0"), ("1.0.1", None))
        self.assertEqual(mock_get.call_count, 2)
        self.assertFalse(os.path.exists(marker))


def _write_marker(path):
    with open(path, "w", encoding="utf-8") as marker:
        marker.write("ran")
    return ("9.9.9", None)


class _Planted:
    def __init__(self, path):
        self.path = path

    def __reduce__(self):
        return (_write_marker, (self.path,))
