"""Module for containing convenience functions around path manipulation"""
import os
import re
import subprocess
from collections import defaultdict
from typing import Dict, Set

from networkx import DiGraph

GIT_REPO_REGEX = r"URL.*/([\w-]*)(?:\.git)?"


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


def get_file_graph(directory: str) -> DiGraph:
    """
    Recursively walk a directory and return a graph of all files and symlinks
    :param directory:
    :return: graph of file names to parent directories and symlink destinations
    """
    graph = DiGraph()
    for current_dir, dirs, files in os.walk(directory):
        if '.terraform' in current_dir or '.git' in current_dir:
            continue

        if current_dir not in graph.nodes:
            graph.add_node(current_dir)

        # for every file in a dir, create a node and an edge pointing to the parent dir
        # also create an edge for symlinks to symlink source
        for path in files:
            norm_path = os.path.normpath(os.path.join(current_dir, path))
            if norm_path not in graph.nodes:
                graph.add_node(norm_path)

            graph.add_edge(norm_path, current_dir)

            if os.path.islink(norm_path):
                link_source = os.path.normpath(os.path.join(current_dir, os.readlink(norm_path)))

                if link_source not in graph.nodes:
                    graph.add_node(link_source)

                graph.add_edge(link_source, norm_path)

        # handle dirs the same way as files but don't create a node/edge for them unless they are a symlink
        for path in dirs:
            norm_path = os.path.normpath(os.path.join(current_dir, path))
            if os.path.islink(norm_path):
                link_source = os.path.normpath(os.path.join(current_dir, os.readlink(norm_path)))

                if link_source not in graph.nodes:
                    graph.add_node(link_source)

                graph.add_edge(link_source, norm_path)
    return graph


def calc_repo_path(path: str) -> str:
    """
    Convenience function for taking an absolute path to a TF directory and returning the path to that
    directory relative to the repo.
    :param path: The absolute path to a TF directory.
    :return: New path to the TF directory
    """
    byte_output = subprocess.check_output(["git", "remote", "show", "origin", "-n"], cwd=path)
    output = byte_output.decode("utf-8", errors="replace")
    match = re.search(GIT_REPO_REGEX, output)
    if match:
        repo_name = match.group(1)
    else:
        raise RuntimeError("Could not determine git repo name, are we in a git repo?")

    return '%s/%s' % (repo_name, path[path.index("/config") + 1:])
