"""Contains functions for checking the latest version of this package"""

import contextlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from time import sleep, time
from typing import Any, Dict, Optional, Tuple

import requests
from packaging import version

logger = logging.getLogger(__name__)

ONE_DAY_IN_SECONDS = 60 * 60 * 24


def cache_path() -> Path:
    """
    Path of the version-check cache file, under the user's own cache directory so
    no other account can plant an entry. A relative XDG_CACHE_HOME is ignored, as the
    XDG Base Directory spec requires.
    """
    xdg_cache_home = Path(os.environ.get("XDG_CACHE_HOME", ""))
    cache_home = xdg_cache_home if xdg_cache_home.is_absolute() else Path.home() / ".cache"
    return cache_home / "terrawrap" / "version.json"


def version_check(current_version: str) -> bool:
    """
    Print a warning message if a stale version of Terrawrap is detected.
    :param current_version: The currently installed version of Terrawrap.
    :return: True if the version of Terrawrap is stale.
    """
    try:
        latest_stable, latest_rc = get_latest_version(current_version=current_version)
        current = version.parse(current_version)
        is_stale = False

        if version.parse(latest_stable) > current:
            print(
                "WARNING: Your version of Terrawrap is stale!",
                f"You have version '{current_version}' but the latest is '{latest_stable}'",
                "Please upgrade as soon as possible!\n pip install --upgrade terrawrap \n",
                sep="\n",
                file=sys.stderr,
            )
            is_stale = True

        if (
            latest_rc
            and version.parse(latest_rc) > current
            and version.parse(latest_rc) > version.parse(latest_stable)
        ):
            print(
                f"NOTE: A release candidate {latest_rc} is available for testing. It may contain bugs.",
                f"\nTo opt in, run: pip install terrawrap=={latest_rc}\n",
                sep="",
                file=sys.stderr,
            )

        if is_stale:
            sleep(1)

        return is_stale
    except Exception as exp:
        print(
            f"WARNING: Encountered some error while checking for latest version of Terrawrap: {repr(exp)}",
            file=sys.stderr,
        )
    return False


def get_latest_version(current_version: str) -> Tuple[str, Optional[str]]:
    """
    Get the latest stable and RC versions of Terrawrap from PyPI.
    Caches this lookup for one day locally, separately for each installed version.
    :param current_version: The current version of Terrawrap.
    :return: Tuple of (latest stable version, latest RC version or None).
    """
    cached = _usable_lookup(_load_entries().get(current_version))
    if cached is not None:
        return cached

    response = requests.get("https://pypi.python.org/pypi/terrawrap/json", timeout=5).json()
    all_versions = [version.parse(v) for v in response["releases"]]
    stable_versions = [v for v in all_versions if not v.is_prerelease]
    rc_versions = [v for v in all_versions if v.is_prerelease]
    latest_stable = str(max(stable_versions))
    latest_rc = str(max(rc_versions)) if rc_versions else None

    _write_cache(current_version, latest_stable, latest_rc)
    return latest_stable, latest_rc


def _load_entries() -> Dict[str, Any]:
    """Return the cache file's entries keyed by installed version, or {} when it can't be read."""
    try:
        with open(cache_path(), encoding="utf-8") as cache_file:
            entries = json.load(cache_file)
    except (OSError, RuntimeError, ValueError):
        return {}
    return entries if isinstance(entries, dict) else {}


def _usable_lookup(entry: Any) -> Optional[Tuple[str, Optional[str]]]:
    """Return an entry's (stable, rc) when it is fresh and both are valid versions, else None."""
    if not isinstance(entry, dict):
        return None
    stable, rc, checked_at = entry.get("stable"), entry.get("rc"), entry.get("checked_at")
    if (
        not isinstance(stable, str)
        or not (rc is None or isinstance(rc, str))
        or not isinstance(checked_at, (int, float))
        or not 0 <= time() - checked_at < ONE_DAY_IN_SECONDS
    ):
        return None
    try:
        version.parse(stable)
        if rc is not None:
            version.parse(rc)
    except version.InvalidVersion:
        return None
    return stable, rc


def _write_cache(current_version: str, stable: str, rc: Optional[str]) -> None:
    """
    Store the lookup under the installed version, dropping entries that are no longer
    usable. A cache that can't be written just means a PyPI lookup next run.
    """
    entries = {key: entry for key, entry in _load_entries().items() if _usable_lookup(entry) is not None}
    entries[current_version] = {"checked_at": time(), "stable": stable, "rc": rc}
    tmp_name = None
    try:
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as tmp_file:
            tmp_name = tmp_file.name
            json.dump(entries, tmp_file)
        os.replace(tmp_name, path)
    except (OSError, RuntimeError) as exc:
        logger.debug("Could not write the version-check cache: %r", exc)
        if tmp_name:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
