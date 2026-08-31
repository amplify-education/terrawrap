"""Tests for the .tf_wrapper validator and depends_on fixer."""

import contextlib
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile
import textwrap
from unittest import TestCase
from unittest.mock import patch

import yaml

from terrawrap.utils.validator import (
    find_tf_wrappers,
    fix_depends_on,
    validate_and_fix,
    validate_depends_on,
    validate_schema,
)

_BIN_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "bin", "tf_validate"))


def _load_tf_validate_module():
    """Load bin/tf_validate (no .py extension) as a module via SourceFileLoader."""
    loader = importlib.machinery.SourceFileLoader("tf_validate_bin", _BIN_PATH)
    spec = importlib.util.spec_from_loader("tf_validate_bin", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestValidateSchema(TestCase):
    """Schema validation surfaces deserialization errors with their file path."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="terrawrap_validate_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name: str, body: str) -> str:
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(body).lstrip())
        return path

    def test_valid_file_produces_no_errors(self):
        """A well-formed .tf_wrapper passes validation."""
        path = self._write(
            ".tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path: /a/b
            """,
        )

        errors = validate_schema([path])

        self.assertEqual([], errors)

    def test_invalid_source_is_reported(self):
        """An unknown envvar source produces a single error tagged with the file path."""
        path = self._write(
            ".tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: not_a_source
                value: x
            """,
        )

        errors = validate_schema([path])

        self.assertEqual(1, len(errors))
        self.assertIn(path, errors[0])

    def test_invalid_path_type_is_reported(self):
        """A numeric `path` is rejected with a precise error."""
        path = self._write(
            ".tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path: 42
            """,
        )

        errors = validate_schema([path])

        self.assertEqual(1, len(errors))
        self.assertIn(path, errors[0])

    def test_empty_path_list_is_reported(self):
        """An empty list for `path` is rejected."""
        path = self._write(
            ".tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path: []
            """,
        )

        errors = validate_schema([path])

        self.assertEqual(1, len(errors))
        self.assertIn(path, errors[0])

    def test_mixed_type_path_list_is_reported(self):
        """A list mixing strings and non-strings for `path` is rejected."""
        path = self._write(
            ".tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path:
                  - /a
                  - 42
            """,
        )

        errors = validate_schema([path])

        self.assertEqual(1, len(errors))
        self.assertIn(path, errors[0])

    def test_malformed_yaml_is_reported(self):
        """A .tf_wrapper with invalid YAML produces an error entry instead of crashing."""
        path = self._write(".tf_wrapper", "key: :\n  bad indentation\n")

        errors = validate_schema([path])

        self.assertEqual(1, len(errors))
        self.assertIn(path, errors[0])


class TestFixDependsOn(TestCase):
    """fix_depends_on prunes dead entries and back-fills missing arrays on referenced targets."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="terrawrap_fix_")
        self.config_dir = os.path.join(self.tmpdir, "config")
        os.makedirs(self.config_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_dir(self, rel: str) -> str:
        path = os.path.join(self.config_dir, rel)
        os.makedirs(path, exist_ok=True)
        return path

    def _write_wrapper(self, rel: str, body: str) -> str:
        directory = self._make_dir(rel)
        path = os.path.join(directory, ".tf_wrapper")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(body).lstrip())
        return path

    def _read_yaml(self, path: str):
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def test_dead_dependency_is_pruned(self):
        """A depends_on entry pointing at a missing directory is removed."""
        self._make_dir("real_dep")
        consumer = self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/real_dep
              - config/ghost_dep
            """,
        )

        fix_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        self.assertEqual(["config/real_dep"], self._read_yaml(consumer)["depends_on"])

    def test_referenced_target_gets_empty_array(self):
        """A target referenced as a depends_on gains depends_on: [] if it lacks one."""
        target_dir = self._make_dir("target")
        target_wrapper = os.path.join(target_dir, ".tf_wrapper")
        with open(target_wrapper, "w", encoding="utf-8") as handle:
            handle.write("backend_check: true\n")
        self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/target
            """,
        )

        fix_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        self.assertEqual([], self._read_yaml(target_wrapper)["depends_on"])

    def test_already_correct_files_are_unchanged(self):
        """fix is idempotent: rerunning on a clean tree returns no changes."""
        self._make_dir("real_dep")
        self._write_wrapper("real_dep", "depends_on: []\n")
        self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/real_dep
            """,
        )

        first_run = fix_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)
        second_run = fix_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        self.assertEqual([], first_run)
        self.assertEqual([], second_run)

    def test_relative_dep_resolves_file_local(self):
        """A depends_on entry not starting with 'config' resolves relative to the file's directory."""
        self._make_dir("foo")
        self._make_dir("foo/sibling")
        self._write_wrapper(
            "foo/consumer",
            """
            depends_on:
              - ../sibling
            """,
        )

        fix_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        consumer_yaml = self._read_yaml(os.path.join(self.config_dir, "foo/consumer/.tf_wrapper"))
        self.assertEqual(["../sibling"], consumer_yaml["depends_on"])

    def test_relative_dep_prefers_file_local_over_coincidental_repo_root_match(self):
        """A '../x' entry resolves against the file's own directory even when repo_root/x also exists.

        Regression guard: resolving repo-root-relative first could silently pick an unrelated
        directory that happens to share a name with the intended sibling.
        """
        self._make_dir("foo")
        self._make_dir("foo/sibling")
        self._make_dir("sibling")  # coincidental repo-root/sibling — must NOT be the resolved target
        self._write_wrapper(
            "foo/consumer",
            """
            depends_on:
              - ../sibling
            """,
        )

        fix_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        correct_target = os.path.join(self.config_dir, "foo/sibling", ".tf_wrapper")
        wrong_target = os.path.join(self.config_dir, "sibling", ".tf_wrapper")
        self.assertTrue(os.path.isfile(correct_target))
        self.assertFalse(os.path.isfile(wrong_target))

    def test_missing_target_wrapper_is_created(self):
        """A depends_on target with no .tf_wrapper at all gets one created with depends_on: [].

        Regression guard: a target directory with no .tf_wrapper broke graph_apply for the
        whole tree (see the validator module docstring).
        """
        target_dir = self._make_dir("target")
        self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/target
            """,
        )

        changed = fix_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        target_wrapper = os.path.join(target_dir, ".tf_wrapper")
        self.assertIn(os.path.realpath(target_wrapper), [os.path.realpath(p) for p in changed])
        self.assertEqual([], self._read_yaml(target_wrapper)["depends_on"])

    def test_missing_target_outside_repo_root_is_not_created(self):
        """--fix refuses to create a .tf_wrapper for a target that resolves outside repo_root.

        Regression guard: a depends_on entry with enough '../' segments (or one that
        coincidentally matches a directory elsewhere) must never cause a write outside the repo.
        """
        outside_dir = tempfile.mkdtemp(prefix="terrawrap_outside_")
        self.addCleanup(shutil.rmtree, outside_dir, ignore_errors=True)
        self._write_wrapper(
            "consumer",
            f"""
            depends_on:
              - {outside_dir}
            """,
        )

        changed = fix_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        self.assertEqual([], changed)
        self.assertFalse(os.path.isfile(os.path.join(outside_dir, ".tf_wrapper")))

    def test_malformed_target_wrapper_is_left_untouched(self):
        """--fix does not rewrite a target .tf_wrapper that isn't a valid YAML mapping."""
        target_wrapper = self._write_wrapper("target", "# just a comment\n")
        self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/target
            """,
        )

        changed = fix_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        self.assertEqual([], changed)
        with open(target_wrapper, encoding="utf-8") as handle:
            self.assertEqual("# just a comment\n", handle.read())

    def test_comments_are_preserved_after_rewrite(self):
        """YAML comments in a .tf_wrapper survive a --fix rewrite (ruamel round-trip)."""
        self._make_dir("real_dep")
        consumer_dir = self._make_dir("consumer")
        consumer = os.path.join(consumer_dir, ".tf_wrapper")
        with open(consumer, "w", encoding="utf-8") as handle:
            handle.write("# important: managed by team-X\ndepends_on:\n  - config/missing\n")

        fix_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        with open(consumer, encoding="utf-8") as handle:
            raw = handle.read()
        self.assertIn("# important: managed by team-X", raw)
        self.assertEqual([], self._read_yaml(consumer)["depends_on"])


class TestValidateDependsOn(TestCase):
    """validate_depends_on flags depends_on targets that don't declare depends_on themselves."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="terrawrap_depcheck_")
        self.config_dir = os.path.join(self.tmpdir, "config")
        os.makedirs(self.config_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_dir(self, rel: str) -> str:
        path = os.path.join(self.config_dir, rel)
        os.makedirs(path, exist_ok=True)
        return path

    def _write_wrapper(self, rel: str, body: str) -> str:
        directory = self._make_dir(rel)
        path = os.path.join(directory, ".tf_wrapper")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(body).lstrip())
        return path

    def test_target_missing_wrapper_is_an_error(self):
        """A depends_on target with no .tf_wrapper at all is reported."""
        self._make_dir("target")
        self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/target
            """,
        )

        errors = validate_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        self.assertEqual(1, len(errors))
        self.assertIn("config/target", errors[0])

    def test_target_without_depends_on_key_is_an_error(self):
        """A depends_on target whose .tf_wrapper doesn't declare depends_on is reported."""
        self._write_wrapper("target", "backend_check: true\n")
        self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/target
            """,
        )

        errors = validate_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        self.assertEqual(1, len(errors))
        self.assertIn("depends_on", errors[0])

    def test_malformed_target_wrapper_is_an_error(self):
        """A depends_on target whose .tf_wrapper exists but isn't a valid YAML mapping is reported.

        Regression guard: previously indistinguishable from "missing file" via _load_yaml's
        overloaded None return, so this case was silently skipped by both branches.
        """
        self._write_wrapper("target", "# just a comment\n")
        self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/target
            """,
        )

        errors = validate_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        self.assertEqual(1, len(errors))
        self.assertIn("valid YAML mapping", errors[0])

    def test_compliant_target_produces_no_error(self):
        """A target that declares depends_on (even empty) passes."""
        self._write_wrapper("target", "depends_on: []\n")
        self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/target
            """,
        )

        errors = validate_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        self.assertEqual([], errors)

    def test_dead_dependency_is_not_reported(self):
        """A depends_on entry that doesn't resolve to any directory is out of scope for this check."""
        self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/ghost
            """,
        )

        errors = validate_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        self.assertEqual([], errors)

    def test_broken_target_referenced_twice_reports_once(self):
        """Multiple referrers to the same broken target produce a single deduplicated error."""
        self._make_dir("target")
        self._write_wrapper(
            "consumer_a",
            """
            depends_on:
              - config/target
            """,
        )
        self._write_wrapper(
            "consumer_b",
            """
            depends_on:
              - config/target
            """,
        )

        errors = validate_depends_on(find_tf_wrappers(self.tmpdir), self.tmpdir)

        self.assertEqual(1, len(errors))


class TestValidateAndFix(TestCase):
    """validate_and_fix orchestrates fix then validate, returning (errors, changed)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="terrawrap_vaf_")
        self.config_dir = os.path.join(self.tmpdir, "config")
        os.makedirs(self.config_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_dir(self, rel: str) -> str:
        path = os.path.join(self.config_dir, rel)
        os.makedirs(path, exist_ok=True)
        return path

    def _write_wrapper(self, rel: str, body: str) -> str:
        directory = self._make_dir(rel)
        path = os.path.join(directory, ".tf_wrapper")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(body).lstrip())
        return path

    def test_no_fix_skips_repair_and_validates(self):
        """fix=False returns empty changed list and still validates schema."""
        self._write_wrapper("a", "backend_check: true\n")

        errors, changed = validate_and_fix(self.tmpdir, fix=False)

        self.assertEqual([], errors)
        self.assertEqual([], changed)

    def test_fix_true_runs_repair_and_validate(self):
        """fix=True prunes dead deps and then validates — both phases run."""
        self._make_dir("real_dep")
        consumer = self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/real_dep
              - config/ghost_dep
            """,
        )

        errors, changed = validate_and_fix(self.tmpdir, fix=True)

        self.assertEqual([], errors)
        self.assertIn(consumer, changed)

    def test_fix_false_does_not_rewrite_files(self):
        """Without fix=True, broken depends_on entries are not pruned."""
        self._make_dir("real_dep")
        consumer = self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/ghost_dep
            """,
        )
        with open(consumer, encoding="utf-8") as handle:
            before = handle.read()

        validate_and_fix(self.tmpdir, fix=False)

        with open(consumer, encoding="utf-8") as handle:
            after = handle.read()
        self.assertEqual(before, after)

    def test_missing_target_wrapper_is_an_error_without_fix(self):
        """A depends_on target with no .tf_wrapper surfaces as an error when fix=False."""
        self._make_dir("target")
        self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/target
            """,
        )

        errors, changed = validate_and_fix(self.tmpdir, fix=False)

        self.assertEqual([], changed)
        self.assertEqual(1, len(errors))
        self.assertIn("config/target", errors[0])

    def test_fix_true_resolves_the_missing_target_wrapper_case(self):
        """--fix creates the missing target .tf_wrapper, leaving no depends_on errors behind."""
        self._make_dir("target")
        self._write_wrapper(
            "consumer",
            """
            depends_on:
              - config/target
            """,
        )

        errors, changed = validate_and_fix(self.tmpdir, fix=True)

        self.assertEqual([], errors)
        self.assertEqual(1, len(changed))


class TestTfValidateMain(TestCase):
    """bin/tf_validate main() exit-code contract."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="terrawrap_main_")
        # Keep the module object so patch.object can replace the locally-bound
        # validate_and_fix name (imported via 'from X import Y').
        self._mod = _load_tf_validate_module()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, argv, stub_return=None):
        """Invoke main() with argv; optionally stub the module-local validate_and_fix.

        Catching SystemExit is intentional — main() signals its exit code via sys.exit
        and this helper extracts that code for test assertions.
        """
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", ["tf_validate"] + argv))
            if stub_return is not None:
                stack.enter_context(patch.object(self._mod, "validate_and_fix", return_value=stub_return))
            try:
                self._mod.main()
                return 0
            except SystemExit as exc:  # NOSONAR — testing the CLI's exit-code contract
                return exc.code

    def test_exit_0_when_no_errors_and_no_changes(self):
        """Clean tree with --fix exits 0."""
        code = self._run(["--path", self.tmpdir, "--fix"], stub_return=([], []))
        self.assertEqual(0, code)

    def test_exit_1_on_schema_errors(self):
        """Schema errors cause exit 1 even without --fix."""
        code = self._run(["--path", self.tmpdir], stub_return=(["some error"], []))
        self.assertEqual(1, code)

    def test_exit_1_when_fix_rewrites_files(self):
        """--fix exits 1 when files were modified so CI dirty-tree checks fire."""
        code = self._run(
            ["--path", self.tmpdir, "--fix"],
            stub_return=([], ["/some/path/.tf_wrapper"]),
        )
        self.assertEqual(1, code)

    def test_exit_2_for_non_directory(self):
        """A non-existent --path exits 2."""
        code = self._run(["--path", "/no/such/dir/xyz"])
        self.assertEqual(2, code)
