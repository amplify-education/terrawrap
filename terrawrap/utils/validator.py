"""Validate and (optionally) repair .tf_wrapper files.

The schema check loads each file through :func:`parse_wrapper_configs` and
surfaces deserialization errors with their file path. The repair step ports
``scripts/check_tf_wrapper.sh`` from terraform-config: it prunes dead
``depends_on`` entries and back-fills ``depends_on: []`` on referenced
targets that lack one (graph_apply requires the array to exist).
"""
import logging
import os
from typing import List, Optional, Set, Tuple

import yaml
from jsons import DeserializationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from terrawrap.utils.config import TF_WRAP_FILE, parse_wrapper_configs
from terrawrap.utils.path import get_absolute_path

_SKIP_DIRS = frozenset({"node_modules", "__pycache__"})
_yaml = YAML(typ="rt")  # round-trip: preserves comments and key order
_yaml.default_flow_style = False
logger = logging.getLogger(__name__)


def find_tf_wrappers(root: str) -> List[str]:
    """Walk ``root`` for every ``.tf_wrapper``, pruning hidden and build dirs."""
    matches = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS
        ]
        for name in files:
            if name == TF_WRAP_FILE:
                matches.append(os.path.join(dirpath, name))
    return sorted(matches)


def validate_schema(tf_wrapper_paths: List[str]) -> List[str]:
    """Return a list of human-readable error messages — one per failing file."""
    errors = []
    for path in tf_wrapper_paths:
        try:
            parse_wrapper_configs([path])
        except (
            DeserializationError,
            ValueError,
            TypeError,
            KeyError,
            yaml.YAMLError,
        ) as exc:
            errors.append(f"{path}: {exc}")
    return errors


def _resolve_dep(dep: str, tf_wrapper_path: str, repo_root: str) -> str:
    """Resolve a depends_on entry to an absolute path.

    Tries ``dep`` relative to ``repo_root`` first; if the result is not an
    existing directory, falls back to resolving relative to the directory that
    contains ``tf_wrapper_path``. Handles both ``config/foo`` and ``../sibling``
    forms without a special-case prefix check.

    Note: this differs from ``create_wrapper_config_obj``, which resolves against
    ``os.getcwd()`` rather than ``repo_root`` — the results only agree when
    ``cwd == repo_root``.
    """
    abs_dep = get_absolute_path(dep, repo_root)
    if not os.path.isdir(abs_dep):
        abs_dep = get_absolute_path(dep, os.path.dirname(tf_wrapper_path))
    return abs_dep


def _prune_dead_deps(
    tf_path: str, data, repo_root: str, referenced_targets: Set[str]
) -> bool:
    """Drop ``depends_on`` entries that don't resolve to a directory.

    Mutates ``data`` in place and records every kept target in ``referenced_targets``.
    Returns True when the file was modified.
    """
    deps = data.get("depends_on")
    if not deps:
        return False
    if not isinstance(deps, list):
        logger.warning(
            "skipping %s: depends_on must be a list, got %s",
            tf_path,
            type(deps).__name__,
        )
        return False
    kept = []
    for dep in deps:
        dep_path = _resolve_dep(dep, tf_path, repo_root)
        if os.path.isdir(dep_path):
            kept.append(dep)
            referenced_targets.add(os.path.realpath(dep_path))
    if kept == deps:
        return False
    data["depends_on"] = kept
    return True


def _backfill_missing_depends_on(target_dir: str) -> Optional[str]:
    """Add ``depends_on: []`` to a referenced target that lacks the key.

    Returns the rewritten file path if a change was made, else None.
    """
    target_wrapper = os.path.join(target_dir, TF_WRAP_FILE)
    data = _load_yaml(target_wrapper)
    if data is None or data.get("depends_on") is not None:
        return None
    data["depends_on"] = []
    _dump_yaml(target_wrapper, data)
    return target_wrapper


def fix_depends_on(tf_wrapper_paths: List[str], repo_root: str) -> List[str]:
    """Prune dead ``depends_on`` entries and back-fill empty arrays on targets.

    :param tf_wrapper_paths: every .tf_wrapper file to consider.
    :param repo_root: directory used to resolve ``config/...``-style deps.
    :return: sorted list of files that were rewritten.
    """
    changed: Set[str] = set()
    referenced_targets: Set[str] = set()

    for tf_path in tf_wrapper_paths:
        data = _load_yaml(tf_path)
        if data is None:
            continue
        if _prune_dead_deps(tf_path, data, repo_root, referenced_targets):
            _dump_yaml(tf_path, data)
            changed.add(tf_path)

    for target_dir in referenced_targets:
        backfilled = _backfill_missing_depends_on(target_dir)
        if backfilled is not None:
            changed.add(backfilled)

    return sorted(changed)


def _load_yaml(path: str):
    """Load a YAML file using round-trip mode to preserve comments.

    :return: parsed mapping, or None if the file is missing, malformed, or not a dict.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = _yaml.load(handle)
    except FileNotFoundError:
        return None
    except YAMLError as exc:
        logger.warning("skipping %s: YAML parse error: %s", path, exc)
        return None
    if not isinstance(loaded, dict):
        if loaded is not None:
            logger.warning(
                "skipping %s: expected a mapping, got %s", path, type(loaded).__name__
            )
        return None
    return loaded


def _dump_yaml(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        _yaml.dump(data, handle)


def validate_and_fix(root: str, fix: bool) -> Tuple[List[str], List[str]]:
    """High-level entry point used by ``bin/tf_validate``.

    :return: (schema errors, files changed)
    """
    tf_wrappers = find_tf_wrappers(root)
    changed: List[str] = []
    if fix:
        changed = fix_depends_on(tf_wrappers, root)
    errors = validate_schema(tf_wrappers)
    return errors, changed
