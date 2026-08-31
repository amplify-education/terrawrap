"""Validate and (optionally) repair .tf_wrapper files.

The schema check loads each file through :func:`parse_wrapper_configs` and
surfaces deserialization errors with their file path. The repair step ports
``scripts/check_tf_wrapper.sh`` from terraform-config: it prunes dead
``depends_on`` entries and back-fills ``depends_on: []`` on referenced
targets that lack one (graph_apply requires the array to exist).

The completeness check catches a class of bug where ``graph_wrapper_dependencies``
recurses into every ``depends_on`` target and aborts the whole apply if that
target's own ``.tf_wrapper`` doesn't declare ``depends_on`` (missing file or
missing key). ``--fix`` resolves it in advance; without ``--fix`` it's
reported as a validation error.
"""

import logging
import os
from typing import Dict, List, Optional, Set, Tuple

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
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]
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

    Tries ``dep`` relative to the directory that contains ``tf_wrapper_path``
    first, since ``../sibling``-style entries are meant to be file-local; if
    the result is not an existing directory, falls back to resolving relative
    to ``repo_root`` for ``config/foo``-style entries. Checking file-local
    first avoids the case where a repo-root-relative resolution of a
    ``../``-prefixed entry coincidentally lands on an unrelated directory
    that happens to exist (e.g. a same-named sibling checkout outside the
    repo).

    Note: this order is the mirror of ``create_wrapper_config_obj``, which tries
    ``os.getcwd()``-relative first and falls back to the file-local directory.
    The two only disagree when both candidates happen to be existing
    directories — the case this order flip exists to get right, since that's
    exactly the coincidental-sibling-checkout scenario described above.
    """
    abs_dep = get_absolute_path(dep, os.path.dirname(tf_wrapper_path))
    if not os.path.isdir(abs_dep):
        abs_dep = get_absolute_path(dep, repo_root)
    return abs_dep


def _prune_dead_deps(tf_path: str, data, repo_root: str, referenced_targets: Set[str]) -> bool:
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


def _target_status(target_wrapper: str) -> str:
    """Classify a depends_on target's .tf_wrapper for the completeness check.

    :return: one of ``"missing"`` (no file), ``"malformed"`` (file exists but
        isn't a YAML mapping — indistinguishable from "missing" via
        ``_load_yaml`` alone, so checked separately), ``"no_depends_on"``
        (mapping without the key), or ``"ok"``.
    """
    if not os.path.isfile(target_wrapper):
        return "missing"
    data = _load_yaml(target_wrapper)
    if data is None:
        return "malformed"
    if data.get("depends_on") is None:
        return "no_depends_on"
    return "ok"


def _is_within(path: str, root: str) -> bool:
    """True if ``path`` is ``root`` or a descendant of it, comparing realpaths."""
    real_path = os.path.realpath(path)
    real_root = os.path.realpath(root)
    return real_path == real_root or real_path.startswith(real_root + os.sep)


def _backfill_missing_depends_on(target_dir: str, repo_root: str) -> Optional[str]:
    """Add ``depends_on: []`` to a referenced target that lacks the key.

    Creates ``target_dir/.tf_wrapper`` from scratch when it doesn't exist at
    all (see the module docstring for the class of bug this closes). Refuses
    to create a file outside ``repo_root``: ``_resolve_dep``
    can resolve a ``depends_on`` entry (e.g. one with enough ``../`` segments,
    or one that coincidentally matches a same-named directory elsewhere) to a
    path outside the repo, and creating a file there would be a write outside
    the checkout that a CI dirty-tree check would never catch. A malformed
    (non-mapping) existing file is left untouched — rewriting content we can't
    parse risks destroying it — and reported by :func:`validate_depends_on`.
    Returns the rewritten/created file path if a change was made, else None.
    """
    target_wrapper = os.path.join(target_dir, TF_WRAP_FILE)
    status = _target_status(target_wrapper)
    if status in ("ok", "malformed"):
        return None
    if status == "missing":
        if not _is_within(target_dir, repo_root):
            logger.warning(
                "refusing to create %s: target resolves outside repo_root %s",
                target_wrapper,
                repo_root,
            )
            return None
        data = {}
    else:  # no_depends_on
        data = _load_yaml(target_wrapper)
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
        backfilled = _backfill_missing_depends_on(target_dir, repo_root)
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
            logger.warning("skipping %s: expected a mapping, got %s", path, type(loaded).__name__)
        return None
    return loaded


def _dump_yaml(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        _yaml.dump(data, handle)


def validate_depends_on(tf_wrapper_paths: List[str], repo_root: str) -> List[str]:
    """Check that every depends_on target declares depends_on in its own .tf_wrapper.

    Errors are deduplicated per target directory (one fix location) rather than
    per referencing file, naming one referrer for context.

    :return: sorted list of human-readable error messages.
    """
    # target_dir -> error message naming one referencing .tf_wrapper for context
    violations: Dict[str, str] = {}
    for tf_path in tf_wrapper_paths:
        data = _load_yaml(tf_path)
        if data is None:
            continue
        deps = data.get("depends_on")
        if not deps or not isinstance(deps, list):
            continue
        for dep in deps:
            target_dir = _resolve_dep(dep, tf_path, repo_root)
            if not os.path.isdir(target_dir) or target_dir in violations:
                continue
            target_wrapper = os.path.join(target_dir, TF_WRAP_FILE)
            status = _target_status(target_wrapper)
            if status == "ok":
                continue
            if status == "missing":
                violations[target_dir] = (
                    f"{tf_path}: depends_on target '{dep}' has no {target_wrapper}; "
                    f"create it with `depends_on: []` (or run --fix)"
                )
            elif status == "malformed":
                violations[target_dir] = (
                    f"{tf_path}: depends_on target '{dep}' — {target_wrapper} "
                    f"isn't a valid YAML mapping; add `depends_on: []` to it"
                )
            else:  # no_depends_on
                violations[target_dir] = (
                    f"{tf_path}: depends_on target '{dep}' — {target_wrapper} "
                    f"doesn't declare a `depends_on` key; add `depends_on: []` (or run --fix)"
                )
    return sorted(violations.values())


def validate_and_fix(root: str, fix: bool) -> Tuple[List[str], List[str]]:
    """High-level entry point used by ``bin/tf_validate``.

    :return: (schema errors, files changed)
    """
    tf_wrappers = find_tf_wrappers(root)
    changed: List[str] = []
    if fix:
        changed = fix_depends_on(tf_wrappers, root)
    errors = validate_schema(tf_wrappers)
    errors.extend(validate_depends_on(tf_wrappers, root))
    return errors, changed
