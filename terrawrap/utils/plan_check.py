"""Utility functions for determining which directories plan_check should run against"""

import os
from typing import List, Tuple

from networkx import compose_all, descendants

from terrawrap.utils.config import find_wrapper_config_files, parse_wrapper_configs
from terrawrap.utils.git_utils import get_git_changed_files, get_git_root
from terrawrap.utils.module import get_module_usage_graph
from terrawrap.utils.path import get_file_graph
from terrawrap.utils.tf_variables import get_auto_var_usage_graph


def get_modified_subdirectories(plan_path: str) -> Tuple[List[str], List[str]]:
    """
    Use Git to find which directories have changed and return a list of them
    A changed directory is a directory that has files that changed, or has symlinks to files that
    changed, or uses a module that changed
    :param plan_path: root to search for changed subdirectories from
    :return: A list of "regular" directories and directories that are symlinks which have changed
    """
    changed_files = get_git_changed_files(plan_path)
    root = get_git_root(plan_path)

    module_usage_graph = get_module_usage_graph(root)
    file_graph = get_file_graph(root)
    auto_vars_usage_graph = get_auto_var_usage_graph(root)

    graph = compose_all([module_usage_graph, file_graph, auto_vars_usage_graph])

    directories_to_check = set()
    for path in changed_files:
        if path in graph.nodes:
            affected_directories = descendants(graph, path)
        else:
            # A deleted file is gone from disk, so the filesystem-derived graph never
            # holds a node for it. Fall back to its parent directory so that removing a
            # resource still plans the directory it was removed from. should_run_plan_for
            # below drops the directory if the deletion also removed the directory itself.
            affected_directories = {os.path.dirname(path)}

        # filter out directories that we shouldn't run plan for
        affected_directories = [
            affected_dir
            for affected_dir in affected_directories
            if should_run_plan_for(affected_dir, plan_path)
        ]

        if affected_directories:
            directories_to_check.update(affected_directories)

    # group directories into regular and symlink paths so downstream code can treat them differently
    regular_directories = [directory for directory in directories_to_check if not os.path.islink(directory)]

    symlinked_directories = [directory for directory in directories_to_check if os.path.islink(directory)]

    return regular_directories, symlinked_directories


def should_run_plan_for(directory: str, plan_path: str) -> bool:
    """
    Return True if we are allowed to run plan for a given directory
    :param directory: The directory to check if we should run plan there
    :param plan_path: The root used for plan_check. All directories outside of this dir shouldn't run plan
    """

    # We don't want to run plan if the directory doesn't exist anymore (it could have been deleted)
    # Or if there are no TF files in it
    # Or if plan has been disabled for that dir in .tf_wrapper
    # Or if the directory is outside of the path arg used to run this command
    return (
        os.path.commonpath([plan_path, directory]) == plan_path
        and os.path.exists(directory)
        and os.path.isdir(directory)
        and is_plan_check_enabled(directory)
        and any(file.endswith(".tf") for file in os.listdir(directory))
    )


def is_plan_check_enabled(directory: str) -> bool:
    """Return True if plan check is enabled based on .tf_wrapper config"""
    wrapper_config_files = find_wrapper_config_files(path=os.path.abspath(directory))
    wrapper_config = parse_wrapper_configs(wrapper_config_files=wrapper_config_files)

    return wrapper_config.plan_check
