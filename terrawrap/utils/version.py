"""Contains functions for checking the latest version of this package"""

import contextlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from time import sleep
from typing import Optional, Tuple

import requests
from packaging import version

ONE_DAY_IN_SECONDS = 60 * 60 * 24


def cache_path() -> Path:
    """
    Path of the version-check cache file, under the user's own cache directory so
    no other account can plant an entry.
    """
    cache_home = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(cache_home) / "terrawrap" / "version.json"


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
    Caches this lookup for one day locally, keyed on the installed version so that
    upgrading Terrawrap invalidates it.
    :param current_version: The current version of Terrawrap.
    :return: Tuple of (latest stable version, latest RC version or None).
    """
    cached = _read_cache(current_version)
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


def _read_cache(current_version: str) -> Optional[Tuple[str, Optional[str]]]:
    """Return the cached lookup, or None when it is missing, stale, or malformed."""
    try:
        with open(cache_path(), encoding="utf-8") as cache_file:
            entry = json.load(cache_file)
        stable = entry["stable"]
        rc = entry["rc"]
        checked_at = entry["checked_at"]
        cached_version = entry["current_version"]
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        return None

    if (
        cached_version != current_version
        or not isinstance(stable, str)
        or not (rc is None or isinstance(rc, str))
        or not isinstance(checked_at, (int, float))
        or not 0 <= time.time() - checked_at < ONE_DAY_IN_SECONDS
    ):
        return None
    return stable, rc


def _write_cache(current_version: str, stable: str, rc: Optional[str]) -> None:
    """Store the lookup; a cache that can't be written just means a PyPI lookup next run."""
    entry = {"current_version": current_version, "checked_at": time.time(), "stable": stable, "rc": rc}
    tmp_name = None
    try:
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as tmp_file:
            tmp_name = tmp_file.name
            json.dump(entry, tmp_file)
        os.replace(tmp_name, path)
    except (OSError, RuntimeError):
        if tmp_name:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
