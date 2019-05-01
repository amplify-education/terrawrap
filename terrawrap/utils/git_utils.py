"""Utility functions for working with Git"""
from typing import Set

import os
from git import Repo


def get_git_changed_files() -> Set[str]:
    """
    Compare HEAD of the current branch with master and return list of paths that changed
    Assumes this script is running from a git directory
    :return: List of paths that changed
    """
    repo = Repo()
    changed_files = set()
    for change in repo.commit('origin/master').diff(None):
        if not change.new_file:
            changed_files.add(os.path.abspath(change.a_path))
        if not change.deleted_file:
            changed_files.add(os.path.abspath(change.b_path))

    return changed_files
