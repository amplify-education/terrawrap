"""Contains functions for checking the latest version of this package"""
import sys
import tempfile
import os
from time import sleep
from typing import Optional, Tuple

import requests
from packaging import version
from diskcache import Cache


ONE_DAY_IN_SECONDS = 60 * 60 * 24
cache = Cache(os.path.join(tempfile.gettempdir(), "terrawrap_version_cache"))


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

        if latest_rc and version.parse(latest_rc) > current:
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
        )
    return False


# We supply current_version so that the cache is invalidated when you install a new version of Terrawrap.
# pylint: disable=unused-argument
@cache.memoize(expire=ONE_DAY_IN_SECONDS)
def get_latest_version(current_version: str) -> Tuple[str, Optional[str]]:
    """
    Get the latest stable and RC versions of Terrawrap from PyPI.
    Caches this lookup for one day locally.
    :param current_version: The current version of Terrawrap (used for cache invalidation).
    :return: Tuple of (latest stable version, latest RC version or None).
    """
    response = requests.get(
        "https://pypi.python.org/pypi/terrawrap/json", timeout=5
    ).json()
    all_versions = [version.parse(v) for v in response["releases"]]
    stable_versions = [v for v in all_versions if not v.is_prerelease]
    rc_versions = [v for v in all_versions if v.is_prerelease]
    latest_stable = str(max(stable_versions))
    latest_rc = str(max(rc_versions)) if rc_versions else None
    return latest_stable, latest_rc
