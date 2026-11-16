"""Test version utils"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from terrawrap.utils.version import ONE_DAY_IN_SECONDS, cache_path, get_latest_version, version_check


class TestVersion(TestCase):
    """Test version utils"""

    def setUp(self) -> None:
        cache_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cache_dir)
        self.cache_file = Path(cache_dir) / "terrawrap" / "version.json"
        cache_path_patcher = patch("terrawrap.utils.version.cache_path", return_value=self.cache_file)
        cache_path_patcher.start()
        self.addCleanup(cache_path_patcher.stop)

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
    def test_get_latest_version_happy(self, mock_get):
        """VersionUtils get latest version returns stable and rc"""
        current_version = "1.0.0"
        mock_get.return_value.json.return_value = {"releases": {"1.0.0": [], "1.0.1": [], "1.0.2rc1": []}}

        # pylint:disable=C0103
        stable, rc = get_latest_version(current_version=current_version)

        self.assertEqual(stable, "1.0.1")
        self.assertEqual(rc, "1.0.2rc1")

    @patch("requests.get")
    def test_get_latest_version_no_rc(self, mock_get):
        """VersionUtils get latest version returns None for rc when no RCs exist"""
        current_version = "1.0.0"
        mock_get.return_value.json.return_value = {"releases": {"1.0.0": [], "1.0.1": []}}
        # pylint:disable=C0103
        stable, rc = get_latest_version(current_version=current_version)

        self.assertEqual(stable, "1.0.1")
        self.assertIsNone(rc)

    def _write_entry(self, **overrides):
        entry = {"current_version": "1.0.0", "checked_at": time.time(), "stable": "1.0.1", "rc": None}
        entry.update(overrides)
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(entry), encoding="utf-8")

    @patch("requests.get")
    def test_get_latest_version_served_from_cache(self, mock_get):
        """VersionUtils looks PyPI up once and serves the next call from the cache file"""
        mock_get.return_value.json.return_value = {"releases": {"1.0.0": [], "1.0.1": []}}

        self.assertEqual(get_latest_version(current_version="1.0.0"), ("1.0.1", None))
        self.assertEqual(get_latest_version(current_version="1.0.0"), ("1.0.1", None))

        self.assertEqual(mock_get.call_count, 1)
        entry = json.loads(self.cache_file.read_text(encoding="utf-8"))
        self.assertEqual(entry["current_version"], "1.0.0")
        self.assertEqual((entry["stable"], entry["rc"]), ("1.0.1", None))

    @patch("requests.get")
    def test_get_latest_version_ignores_unusable_entries(self, mock_get):
        """VersionUtils treats stale, other-version, and malformed entries as a miss"""
        mock_get.return_value.json.return_value = {"releases": {"1.0.0": [], "1.0.2": []}}
        unusable = {
            "expired": {"checked_at": time.time() - ONE_DAY_IN_SECONDS - 1},
            "future timestamp": {"checked_at": time.time() + ONE_DAY_IN_SECONDS},
            "other installed version": {"current_version": "0.9.0"},
            "non-string stable": {"stable": ["1.0.1"]},
            "non-string rc": {"rc": 1},
            "non-numeric timestamp": {"checked_at": "now"},
        }
        for case, overrides in unusable.items():
            with self.subTest(case):
                self._write_entry(**overrides)
                self.assertEqual(get_latest_version(current_version="1.0.0"), ("1.0.2", None))

        self.assertEqual(mock_get.call_count, len(unusable))

    @patch("requests.get")
    def test_get_latest_version_ignores_unparseable_file(self, mock_get):
        """VersionUtils treats a file that isn't a JSON object as a miss and replaces it"""
        mock_get.return_value.json.return_value = {"releases": {"1.0.0": [], "1.0.1": []}}
        self.cache_file.parent.mkdir(parents=True)
        for content in (b"\x80\x04not json", b"[1, 2]", b'{"stable": "1.0.1"}'):
            with self.subTest(content=content):
                self.cache_file.write_bytes(content)
                self.assertEqual(get_latest_version(current_version="1.0.0"), ("1.0.1", None))
                self.assertEqual(json.loads(self.cache_file.read_text(encoding="utf-8"))["stable"], "1.0.1")

    @patch("requests.get")
    def test_get_latest_version_without_writable_cache(self, mock_get):
        """VersionUtils still returns the lookup when the cache can't be written"""
        mock_get.return_value.json.return_value = {"releases": {"1.0.0": [], "1.0.1": []}}
        self.cache_file.parent.parent.chmod(0o500)
        self.addCleanup(self.cache_file.parent.parent.chmod, 0o700)

        self.assertEqual(get_latest_version(current_version="1.0.0"), ("1.0.1", None))
        self.assertFalse(self.cache_file.parent.exists())

    @patch("requests.get")
    @patch("terrawrap.utils.version.os.replace", side_effect=OSError)
    def test_get_latest_version_removes_temp_file_on_failed_write(self, _mock_replace, mock_get):
        """VersionUtils leaves no temp file behind when replacing the cache file fails"""
        mock_get.return_value.json.return_value = {"releases": {"1.0.0": [], "1.0.1": []}}

        self.assertEqual(get_latest_version(current_version="1.0.0"), ("1.0.1", None))
        self.assertEqual(os.listdir(self.cache_file.parent), [])

    @patch("requests.get")
    @patch(
        "terrawrap.utils.version.cache_path", side_effect=RuntimeError("Could not determine home directory.")
    )
    def test_get_latest_version_without_home_directory(self, _mock_cache_path, mock_get):
        """VersionUtils still returns the lookup when there is no home directory"""
        mock_get.return_value.json.return_value = {"releases": {"1.0.0": [], "1.0.1": []}}

        self.assertEqual(get_latest_version(current_version="1.0.0"), ("1.0.1", None))


class TestCachePath(TestCase):
    """Test the version-check cache location"""

    @patch.dict(os.environ, {"XDG_CACHE_HOME": "/xdg/cache"})
    def test_cache_path_honors_xdg_cache_home(self):
        """The cache file lives under XDG_CACHE_HOME when it is set"""
        self.assertEqual(cache_path(), Path("/xdg/cache/terrawrap/version.json"))

    @patch.dict(os.environ, {"XDG_CACHE_HOME": ""})
    @patch("terrawrap.utils.version.Path.home", return_value=Path("/home/someone"))
    def test_cache_path_defaults_to_home_cache(self, _mock_home):
        """The cache file lives under ~/.cache when XDG_CACHE_HOME is unset or empty"""
        self.assertEqual(cache_path(), Path("/home/someone/.cache/terrawrap/version.json"))
