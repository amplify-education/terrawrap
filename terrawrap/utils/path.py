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


def get_symlink_graph(directory: str) -> DiGraph:
    """
    Recursively walk a directory and return a graph of all symlinks
    :param directory:
    :return: graph of symlink source and paths that link to that source
    """
    graph = DiGraph()
    for current_dir, _, files in os.walk(directory, followlinks=True):
        if '.terraform' in current_dir:
            continue

        # create edges in graph for all directories which are symlinks
        if os.path.islink(current_dir):
            link_source = os.path.join(os.path.dirname(current_dir), os.readlink(current_dir))
            link_source_norm = os.path.normpath(link_source)
            target_path_norm = os.path.normpath(current_dir)

            if link_source_norm not in graph.nodes:
                graph.add_node(link_source_norm)

            if target_path_norm not in graph.nodes:
                graph.add_node(target_path_norm)

            # Create a edge in the graph from symlink source to symlink target
            graph.add_edge(link_source_norm, target_path_norm)

        # also create a edge for every file which is a symlink
        for file in files:
            if os.path.islink(file):
                link_source = os.path.join(os.path.dirname(file), os.readlink(file))
                link_source_norm = os.path.normpath(link_source)
                target_path_norm = os.path.normpath(file)

                if link_source_norm not in graph.nodes:
                    graph.add_node(link_source_norm)

                if target_path_norm not in graph.nodes:
                    graph.add_node(target_path_norm)

                # first create an edge from symlink file to symlink destination
                # this is important in cases when a auto.tfvars file is symlinked
                graph.add_edge(link_source_norm, target_path_norm)

                # also create a edge from symlink file to the directory of the destination
                # For example a directory could have a shared script or other file which is a symlink
                # If the source of that file changes then we need to run plan/apply on every directory
                # which includes a link to that file
                graph.add_edge(link_source_norm, os.path.normpath(current_dir))

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
