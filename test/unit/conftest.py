"""Fixtures shared by every unit test"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_version_cache(tmp_path, monkeypatch):
    """Point the version-check cache at a per-test directory instead of the user's real cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
