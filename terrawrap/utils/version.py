"""Contains functions for checking the latest version of this package"""
import sys
import tempfile
import os
import json
from typing import Dict, Any
from datetime import datetime
from time import sleep

import requests
from packaging import version


def version_check(current_version: str):
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
            "WARNING: Your version of Terrawrap is stale! You have version '%s' but the latest is '%s'" % (
                current_version,
                latest_version,
            ),
            "Please upgrade as soon as possible!\n",
            sep="\n",
            file=sys.stderr,
        )
        sleep(5)
        return True
    except Exception as exp:
        print(
            "WARNING: Encountered some error while checking for latest version of Terrawrap: %s" % repr(exp),
        )
    return False


def get_latest_version(current_version: str) -> str:
    """
    Get the latest version of Terrawrap from Pypi. Caches this lookup for one day locally.
    :param current_version: The current version of Terrawrap.
    :return: The latest version of Terrawrap, potentially delayed by one day.
    """
    cache_file_path = os.path.join(tempfile.gettempdir(), "terrawrap_version_cache")
    cached_data = get_cache(cache_file_path=cache_file_path)

    current_version_changed = current_version != cached_data.get("current_version")
    cache_outdated = (datetime.utcnow() - cached_data.get("timestamp", datetime.utcnow())).days > 0

    if not cached_data or current_version_changed or cache_outdated:
        response = requests.get("https://pypi.python.org/pypi/terrawrap/json").json()
        latest_version = response["info"]["version"]
        set_cache(
            cache_file_path=cache_file_path,
            latest_version=latest_version,
            current_version=current_version,
        )
        return latest_version

    return cached_data["latest_version"]


def get_cache(cache_file_path: str) -> Dict[str, Any]:
    """
    Get the cached data for Terrawrap.
    :param cache_file_path: The path to the cache file.
    :return: The cached data, or an empty dictionary if no cache was found.
    """
    if not os.path.exists(cache_file_path):
        return {}

    try:
        with open(cache_file_path, "r") as cache_file:
            data = json.load(cache_file)
            # It's unclear why mypy thinks fromisoformat isn't a thing, but it does, and it is.
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])  # type: ignore
            return data
    except json.decoder.JSONDecodeError:
        return {}


def set_cache(cache_file_path: str, latest_version: str, current_version: str):
    """
    Set the cached data for Terrawrap.
    :param cache_file_path: The path to the cache file.
    :param latest_version: The latest version of Terrawrap.
    :param current_version: The current version of Terrawrap.
    """
    with open(cache_file_path, "w") as cache_file:
        json.dump(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "latest_version": latest_version,
                "current_version": current_version,
            },
            cache_file,
        )
