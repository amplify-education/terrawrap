"""Module for containing convenience functions around path manipulation"""
import os
from collections import defaultdict
from typing import Dict, Set, Iterable, List


def get_absolute_path(path: str, root_dir: str = None) -> str:
    """
    Convenience function for determining the full path to a file or directory.
    A RuntimeError will be raised if the given path does not appear to point to either a file or a directory.
    :param path: The path. Can be either relative from the cwd or an absolute path.
    :param root_dir: The root directory to use instead of the cwd.
    :return: An absolute path for the given path.
    """
    if os.path.isabs(path):
        path = os.path.abspath(path)
    else:
        path = os.path.abspath(os.path.join(root_dir or os.getcwd(), path))

    return path


def get_symlinks(directory: str) -> Dict[str, Set[str]]:
    """
    Recursively walk a directory and return a dict of all symlinks
    :param directory:
    :return: dict of symlink source to set of paths that link to that source
    """
    links: Dict[str, Set[str]] = defaultdict(set)
    # pylint: disable=unused-variable
    for current_dir, dirs, files in os.walk(directory, followlinks=True):
        if '.terraform' in current_dir:
            continue

        if os.path.islink(current_dir):
            link_source = os.path.join(os.path.dirname(current_dir), os.readlink(current_dir))
            links[os.path.normpath(link_source)].add(os.path.normpath(current_dir))

    return dict(links)


def get_directories_for_paths(paths: Iterable[str]) -> List[str]:
    """
    For a list of paths check if each one is a directory or a file. If its a file then return
    the directory for the file otherwise return the path itself
    :param paths:
    :return:
    """
    # get set of symlinks that point to directories
    directories = [path for path in paths if os.path.isdir(path)]

    # get set of symlinks that point to files
    files = [path for path in paths if not os.path.isdir(path)]

    # get the directory for each file and add it to the list of directories
    directories.extend([os.path.dirname(file) for file in files])

    return directories
