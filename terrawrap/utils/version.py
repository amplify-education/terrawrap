"""Contains functions for checking the latest version of this package"""
import sys
import tempfile
import os
from time import sleep

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
        latest_version = get_latest_version(current_version=current_version)
        if version.parse(latest_version) <= version.parse(current_version):
            return False

        print(
            "WARNING: Your version of Terrawrap is stale!",
            f"You have version '{current_version}' but the latest is '{latest_version}'",
            "Please upgrade as soon as possible!\n pip install --upgrade terrawrap \n",
            sep="\n",
            file=sys.stderr,
        )
        sleep(1)
        return True
    except Exception as exp:
        print(
            f"WARNING: Encountered some error while checking for latest version of Terrawrap: {repr(exp)}",
        )
    return False


# We supply current_version so that the cache is invalidated when you install a new version of Terrawrap.
# pylint: disable=unused-argument
@cache.memoize(expire=ONE_DAY_IN_SECONDS)
def get_latest_version(current_version: str) -> str:
    """
    Get the latest version of Terrawrap from Pypi. Caches this lookup for one day locally.
    :param current_version: The current version of Terrawrap.
    :return: The latest version of Terrawrap, potentially delayed by one day.
    """
    response = requests.get("https://pypi.python.org/pypi/terrawrap/json", timeout=5).json()
    return response["info"]["version"]
