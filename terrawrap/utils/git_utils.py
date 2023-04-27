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

    # Get the common ancestor commit between master and HEAD
    # See https://git-scm.com/docs/git-merge-base
    # then compare the current working directory with the common ancestor
    # We do it this way so that we don't get extra diffs in cases when master is ahead of our branch.
    # if we compared the current branch directly with master then we would see changes on master that
    # haven't been merged into our branch yet.
    merge_base = repo.merge_base("origin/master", "HEAD")
    if merge_base and merge_base[0] is not None:
        base_commit = merge_base[0]
    else:
        base_commit = repo.commit("origin/master")

    for change in base_commit.diff():
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
