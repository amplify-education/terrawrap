"""File Download Utils"""

import os
import platform
import stat
from typing import Dict, Tuple, Optional
from urllib.parse import urlparse

import boto3
import requests
from botocore.exceptions import ClientError
from filelock import FileLock


class FileDownloadFailed(RuntimeError):
    """Error raised when failing to download a file"""


class PluginDownload:
    """Utility for downloading plugins"""

    def __init__(self, s3_client):
        self.s3_client = s3_client or boto3.client('s3')

    def download_plugins(self, plugin_paths: Dict[str, str]):
        """
        Download a set of Terraform plugins to the user's home directory
        :param plugin_paths: A dictionary of plugin names and URLs where to download them
        """
        for name, path in plugin_paths.items():
            home = os.path.expanduser("~")
            plugin_directory = os.path.join(home, '.terraform.d/plugins')
            os.makedirs(plugin_directory, exist_ok=True)

            file_path = os.path.join(plugin_directory, name)

            system = platform.system()
            machine = platform.machine()
            path_with_platform = '%s/%s/%s' % (path, system, machine)

            lock_path = '%s.%s' % (file_path, 'lock')
            lock = FileLock(lock_path, timeout=600)
            # use a lock to prevent conflicts writing the file if running this command in parallel
            with lock:
                try:
                    self._download_file(path_with_platform, file_path)
                except FileDownloadFailed:
                    print('Unable to get plugin from %s. Attempting %s instead' % (path_with_platform, path))
                    self._download_file(path, file_path)

    def _download_file(self, url: str, file_path: str):
        """
        Download from a url and save it to a file

        :param url: URL of file to download
        :param file_path: Path where to save file
        """
        # get the etag from the etag file if it exists
        etag = None
        etag_path = '%s.%s' % (file_path, 'etag')
        if os.path.isfile(etag_path) and os.path.isfile(file_path):
            with(open(etag_path, 'r')) as etag_file:
                etag = etag_file.read()

        download_info = self._get_file_content(url, etag)

        if download_info:
            content = download_info[0]
            etag = download_info[1]

            with(open(file_path, 'wb')) as out_file:
                out_file.write(content)

            mode = os.stat(file_path)
            os.chmod(file_path, mode.st_mode | stat.S_IEXEC)

            if etag:
                # AWS returns the etag surrounded by quotes
                # remove them if that happens
                if etag[0] == '"':
                    etag = etag[1:-1]
                with(open(etag_path, 'w')) as etag_file:
                    etag_file.write(etag)

    def _get_file_content(self, url: str, etag: Optional[str]) -> Optional[Tuple[bytes, Optional[str]]]:
        """
        Download a file from either S3 or HTTP

        :param url: URL where to download the file from
        :param etag: etag value to use for caching
        :return: File content and the file's etag. Will return None if the file is already cached
        """
        print('Downloading %s' % url)

        parsed_url = urlparse(url)

        if parsed_url.scheme in ('http', 'https'):
            return self._get_http_content(url, etag)

        if parsed_url.scheme == 's3':
            return self._get_s3_content(url, etag)

        raise RuntimeError('Invalid file download scheme. URL must start with one of (http, https, s3')

    def _get_http_content(self, url: str, etag: Optional[str]) -> Optional[Tuple[bytes, Optional[str]]]:
        """Download a file over HTTP/HTTPS"""
        headers = {}

        # get the file. send etag header to avoid downloading file if we already have the same version
        if etag:
            headers['If-None-Match'] = etag

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()

            if response.status_code == 304:
                return None

            return response.content, response.headers.get('etag')
        except requests.HTTPError as exception:
            raise FileDownloadFailed() from exception

    def _get_s3_content(self, url: str, etag: Optional[str]) -> Optional[Tuple[bytes, Optional[str]]]:
        """Download a file from S3 using the AWS SDK"""
        parsed_url = urlparse(url)

        args = {
            'Bucket': parsed_url.hostname,
            'Key': parsed_url.path[1:]  # remove leading slash in path
        }

        if etag:
            args['IfNoneMatch'] = etag

        try:
            response = self.s3_client.get_object(**args)
            return response['Body'].read(), response['ETag']
        except ClientError as ex:
            if ex.response['Error']['Code'] == '304':
                return None
            if ex.response['Error']['Code'] == 'NoSuchKey':
                raise FileDownloadFailed() from ex
            raise ex
