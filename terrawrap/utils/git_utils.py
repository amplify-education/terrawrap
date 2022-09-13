"""Utility functions for working with Git"""
from typing import Set

import os
from git import Repo


def get_git_changed_files(path) -> Set[str]:
    """
    Compare HEAD of the current branch with master and return list of paths that changed
    Assumes this script is running from a git directory
    :return: List of paths that changed
    """
    repo = Repo(path, search_parent_directories=True)
    changed_files = set()
    for change in repo.commit('origin/master').diff(None):
        if not change.new_file:
            changed_files.add(os.path.abspath(change.a_path))
        if not change.deleted_file:
            changed_files.add(os.path.abspath(change.b_path))

    return changed_files


def get_git_root(path):
    """Get the git root directory for a given path"""
    git_repo = Repo(path, search_parent_directories=True)
    git_root = git_repo.git.rev_parse("--show-toplevel")
    return git_root


def get_git_hash(path):
    """Get the git hash for tf apply run changes"""
    repo = Repo(path, search_parent_directories=True)
    sha = repo.head.object.hexsha
    return sha
