"""File Download Utils"""

import os
import platform
from typing import Dict

import requests
from filelock import FileLock


def download_plugins(plugin_paths: Dict[str, str]):
    """
    Download a set of Terraform plugins to the user's home directory
    :param plugin_paths: A dictionary of plugin names and URLs where to download them
    """
    for name, path in plugin_paths.items():
        home = os.path.expanduser("~")
        file_path = os.path.join(home, '.terraform.d/plugins', name)
        system = platform.system()
        machine = platform.machine()
        path_with_platform = '%s/%s/%s' % (path, system, machine)

        lock_path = '%s.%s' % (file_path, 'lock')
        lock = FileLock(lock_path, timeout=600)
        # use a lock to prevent conflicts writing the file if running this command in parallel
        with lock:
            try:
                download_file(path_with_platform, file_path)
            except requests.HTTPError:
                print('Unable to get plugin from %s. Attempting %s instead' % (path_with_platform, path))
                download_file(path, file_path)


def download_file(url: str, file_path: str):
    """
    Download from a url and save it to a file

    :param url: URL of file to download
    :param file_path: Path where to save file
    """
    etag_path = '%s.%s' % (file_path, 'etag')

    # get the etag if it exists
    headers = {}
    if os.path.isfile(etag_path) and os.path.isfile(file_path):
        with(open(etag_path, 'r')) as etag_file:
            headers['If-None-Match'] = etag_file.read()

    # get the file. send etag header to avoid downloading file if we already have the same version
    print('Downloading %s' % url)
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    # save the file if etag matches
    if response.status_code == 200:
        with(open(file_path, 'wb')) as out_file:
            out_file.write(response.content)

        # write the etag to a file so we can use it in future requests
        etag = response.headers.get('etag')
        if etag:
            # AWS returns the etag surrounded by quotes
            # remove them if that happens
            if etag[0] == '"':
                etag = etag[1:-1]
            with(open(etag_path, 'w')) as etag_file:
                etag_file.write(etag)
