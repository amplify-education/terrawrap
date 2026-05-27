"""Backward-compatibility regression tests modeled on production .tf_wrapper patterns.

Each TestCase mirrors a shape observed in amplify-education/terraform-config.
The intent is to lock in the contract for shapes that already exist
in deployed config, so future schema work doesn't silently break them.
"""
import os
import shutil
import tempfile
import textwrap
from unittest import TestCase
from unittest.mock import patch

from terrawrap.models.wrapper_config import (
    GCSBackendConfig,
    S3BackendConfig,
    SSMEnvVarConfig,
    TextEnvVarConfig,
    UnsetEnvVarConfig,
)
from terrawrap.utils.config import (
    find_wrapper_config_files,
    parse_wrapper_configs,
    resolve_envvars,
)


class _WrapperFixtureCase(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="terrawrap_compat_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, rel_path: str, body: str) -> str:
        abs_path = os.path.join(self.tmpdir, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(body).lstrip())
        return abs_path


class TestRootConfigWrapper(_WrapperFixtureCase):
    """Pattern: top-level config/.tf_wrapper with audit_api_url + a text envvar."""

    def test_root_config_parses(self):
        """audit_api_url is preserved and a scalar text envvar resolves verbatim."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              GITHUB_OWNER:
                source: text
                value: amplify-education
            audit_api_url: https://terraform-audit-api.devops.amplify.com
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertEqual(
            "https://terraform-audit-api.devops.amplify.com", config.audit_api_url
        )
        self.assertIsInstance(config.envvars["GITHUB_OWNER"], TextEnvVarConfig)
        self.assertEqual("amplify-education", config.envvars["GITHUB_OWNER"].value)


class TestAccountLevelInheritance(_WrapperFixtureCase):
    """Pattern: full chain root → aws → account, modeled on amplify-learning-dev."""

    def setUp(self):
        super().setUp()
        self._write(
            "config/.tf_wrapper",
            """
            envvars:
              GITHUB_OWNER:
                source: text
                value: amplify-education
            audit_api_url: https://terraform-audit-api.devops.amplify.com
            """,
        )
        self._write(
            "config/aws/.tf_wrapper",
            """
            envvars:
              DATADOG_APP_KEY:
                source: ssm
                path: /account/app_auth/datadog/app_key
              DATADOG_API_KEY:
                source: ssm
                path: /account/app_auth/datadog/api_key
            """,
        )
        self._write(
            "config/aws/amplify-learning-dev/.tf_wrapper",
            """
            envvars:
              DATADOG_APP_KEY:
                source: ssm
                path: /account/app_auth/datadog/app_key
              DATADOG_API_KEY:
                source: ssm
                path: /account/app_auth/datadog/api_key
              GITEA_BASE_URL:
                source: text
                value: https://gitea-devops.devops.amplify.com/
              GITEA_TOKEN:
                source: ssm
                path: /account/app_auth/gitea/read_token
            backends:
              s3:
                region: us-east-1
                bucket: amplify-learning-dev-ue1-terraform
                dynamodb_table: terraform-locking
            depends_on:
              - config/aws/amplify-learning-dev/general/iam
            """,
        )

    def test_three_level_chain_merges_all_envvars(self):
        """A leaf entry inherits root + middle + own envvars; backends and depends_on pass through."""
        leaf = os.path.join(self.tmpdir, "config/aws/amplify-learning-dev")
        os.makedirs(leaf, exist_ok=True)

        files = find_wrapper_config_files(leaf)
        config = parse_wrapper_configs(files)

        self.assertEqual("amplify-education", config.envvars["GITHUB_OWNER"].value)
        self.assertIsInstance(config.envvars["DATADOG_APP_KEY"], SSMEnvVarConfig)
        self.assertEqual(
            ["/account/app_auth/datadog/app_key"],
            config.envvars["DATADOG_APP_KEY"].paths,
        )
        self.assertEqual(
            ["/account/app_auth/gitea/read_token"], config.envvars["GITEA_TOKEN"].paths
        )
        self.assertIsInstance(config.backends.s3, S3BackendConfig)
        self.assertEqual("us-east-1", config.backends.s3.region)
        self.assertEqual(
            "amplify-learning-dev-ue1-terraform", config.backends.s3.bucket
        )
        self.assertEqual("terraform-locking", config.backends.s3.dynamodb_table)


class TestSourceText(_WrapperFixtureCase):
    """Pattern: source: text with both string and integer values (e.g. GITHUB_APP_ID)."""

    def test_integer_value_resolves_to_string(self):
        """YAML integer in `value` field survives parse and is stringified at resolve time."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              GITHUB_APP_ID:
                source: text
                value: 166070
            """,
        )

        config = parse_wrapper_configs([wrapper])
        resolved = resolve_envvars(config.envvars)

        self.assertEqual(166070, config.envvars["GITHUB_APP_ID"].value)
        self.assertEqual("166070", resolved["GITHUB_APP_ID"])

    def test_string_value_unchanged(self):
        """A string-typed `value` is returned verbatim."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              FOO:
                source: text
                value: bar
            """,
        )

        resolved = resolve_envvars(parse_wrapper_configs([wrapper]).envvars)

        self.assertEqual("bar", resolved["FOO"])


class TestSourceUnset(_WrapperFixtureCase):
    """Pattern: source: unset (e.g. GITHUB_TOKEN at config/github/)."""

    def test_unset_resolves_to_none(self):
        """An unset envvar resolves to None so execute_command can drop it from the subprocess env."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              GITHUB_TOKEN:
                source: unset
            """,
        )

        config = parse_wrapper_configs([wrapper])
        resolved = resolve_envvars(config.envvars)

        self.assertIsInstance(config.envvars["GITHUB_TOKEN"], UnsetEnvVarConfig)
        self.assertIsNone(resolved["GITHUB_TOKEN"])


class TestSSMSinglePathString(_WrapperFixtureCase):
    """Pattern: source: ssm with a scalar string path — the historic schema, still valid."""

    @patch("terrawrap.utils.config.resolve_ssm_paths")
    def test_scalar_path_normalized_to_list(self, mock_resolve):
        """A YAML scalar `path` normalizes to a single-element list before SSM resolution."""
        mock_resolve.return_value = "secret"
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              DATADOG_APP_KEY:
                source: ssm
                path: /account/app_auth/datadog/app_key
            """,
        )

        resolved = resolve_envvars(parse_wrapper_configs([wrapper]).envvars)

        self.assertEqual("secret", resolved["DATADOG_APP_KEY"])
        mock_resolve.assert_called_once_with(["/account/app_auth/datadog/app_key"])


class TestSSMMultiPathList(_WrapperFixtureCase):
    """Pattern: source: ssm with a YAML list `path` — the multi-path fallback schema."""

    @patch("terrawrap.utils.config.resolve_ssm_paths")
    def test_list_path_passed_to_resolver(self, mock_resolve):
        """A YAML list `path` is forwarded verbatim as a list to resolve_ssm_paths."""
        mock_resolve.return_value = "secret"
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              DATADOG_APP_KEY:
                source: ssm
                path:
                  - /primary/app_auth/datadog/app_key
                  - /fallback/app_auth/datadog/app_key
            """,
        )

        resolved = resolve_envvars(parse_wrapper_configs([wrapper]).envvars)

        self.assertEqual("secret", resolved["DATADOG_APP_KEY"])
        mock_resolve.assert_called_once_with(
            ["/primary/app_auth/datadog/app_key", "/fallback/app_auth/datadog/app_key"]
        )


class TestS3BackendDynamoLocking(_WrapperFixtureCase):
    """Pattern: backends.s3 with region + bucket + dynamodb_table (legacy locking)."""

    def test_s3_with_dynamodb_table(self):
        """The dynamodb_table form preserves all three fields."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            backends:
              s3:
                region: us-west-2
                bucket: amplify-devops-uw2-terraform
                dynamodb_table: terraform-locking
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertEqual("us-west-2", config.backends.s3.region)
        self.assertEqual("amplify-devops-uw2-terraform", config.backends.s3.bucket)
        self.assertEqual("terraform-locking", config.backends.s3.dynamodb_table)
        self.assertIsNone(config.backends.s3.use_lockfile)


class TestS3BackendNativeLockfile(_WrapperFixtureCase):
    """Pattern: backends.s3 with use_lockfile (newer S3-native state locking)."""

    def test_s3_with_use_lockfile(self):
        """use_lockfile is preserved and dynamodb_table is None when not set."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            backends:
              s3:
                region: us-west-2
                bucket: amplify-interviews-uw2-terraform
                use_lockfile: true
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertEqual("amplify-interviews-uw2-terraform", config.backends.s3.bucket)
        self.assertIs(True, config.backends.s3.use_lockfile)
        self.assertIsNone(config.backends.s3.dynamodb_table)


class TestGCSBackend(_WrapperFixtureCase):
    """Pattern: backends.gcs (config/gcp/.tf_wrapper)."""

    def test_gcs_backend(self):
        """A gcs backend with just a bucket survives parse."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            backends:
              gcs:
                bucket: amplify-devops-ue1-terraform-state
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertIsInstance(config.backends.gcs, GCSBackendConfig)
        self.assertEqual(
            "amplify-devops-ue1-terraform-state", config.backends.gcs.bucket
        )
        self.assertIsNone(config.backends.s3)


class TestApplyAutomaticallyFlag(_WrapperFixtureCase):
    """Pattern: apply_automatically: False (e.g. sandbox-templates)."""

    def test_apply_auto_false_preserved(self):
        """A False value disables apply_automatically; default is True."""
        with_false = self._write(
            "with_false/.tf_wrapper",
            "apply_automatically: False\n",
        )
        without = self._write("without/.tf_wrapper", "depends_on: []\n")

        self.assertFalse(parse_wrapper_configs([with_false]).apply_automatically)
        self.assertTrue(parse_wrapper_configs([without]).apply_automatically)


class TestPlanCheckBackendCheckFlags(_WrapperFixtureCase):
    """Pattern: plan_check: False + backend_check: False at leaf level (cloudwatch_regional)."""

    def test_three_false_flags_disable_checks(self):
        """All three boolean flags can be turned off together at a single leaf."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            apply_automatically: False
            plan_check: False
            backend_check: False
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertFalse(config.apply_automatically)
        self.assertFalse(config.plan_check)
        self.assertFalse(config.backend_check)


class TestDependsOnEmpty(_WrapperFixtureCase):
    """Pattern: depends_on: [] (the canonical leaf — required by graph_apply)."""

    def test_empty_list_parses_as_empty_list(self):
        """`depends_on: []` parses to [] (not None) so graph_apply recognizes it as a configured leaf."""
        wrapper = self._write("config/.tf_wrapper", "depends_on: []\n")

        config = parse_wrapper_configs([wrapper])

        self.assertEqual([], config.depends_on)


class TestDependsOnRepoRelative(_WrapperFixtureCase):
    """Pattern: depends_on entry starting with 'config/' (most common)."""

    def test_repo_relative_dep_verbatim(self):
        """The dep string passes through verbatim; resolution to a directory is done elsewhere."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            depends_on:
              - config/aws/amplify-learning-dev/general/iam
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertEqual(
            ["config/aws/amplify-learning-dev/general/iam"], config.depends_on
        )


class TestDependsOnFileRelative(_WrapperFixtureCase):
    """Pattern: depends_on entry like '../route53' (file-directory relative)."""

    def test_file_relative_dep_verbatim(self):
        """A '..'-prefixed dep stays as written; consumers resolve it relative to the file's dir."""
        wrapper = self._write(
            "config/aws/amplify-learning-prod/general/acm/.tf_wrapper",
            """
            depends_on:
              - ../route53
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertEqual(["../route53"], config.depends_on)


class TestComments(_WrapperFixtureCase):
    """Pattern: YAML comments interspersed with config keys (e.g. dbtcloud README)."""

    def test_comments_do_not_block_parse(self):
        """Comments in the YAML body are ignored by the parser."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            # Where do we find the dbt Cloud account id?
            envvars:
              DBT_CLOUD_ACCOUNT_ID:
                # 1Password: Axiom / dbt Cloud / terraform service token
                source: text
                value: 122795
            apply_automatically: False
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertEqual(122795, config.envvars["DBT_CLOUD_ACCOUNT_ID"].value)
        self.assertFalse(config.apply_automatically)


class TestEnvvarMix(_WrapperFixtureCase):
    """Pattern: all four envvar shapes coexisting (config/github/.tf_wrapper)."""

    def test_text_ssm_unset_int_coexist(self):
        """A single .tf_wrapper can declare text + ssm + unset envvars side by side."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              GITHUB_APP_ID:
                source: text
                value: 166070
              GITHUB_APP_PEM_FILE:
                source: ssm
                path: /account/app_auth/github/terraform_pem_file
              GITHUB_TOKEN:
                source: unset
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertIsInstance(config.envvars["GITHUB_APP_ID"], TextEnvVarConfig)
        self.assertIsInstance(config.envvars["GITHUB_APP_PEM_FILE"], SSMEnvVarConfig)
        self.assertIsInstance(config.envvars["GITHUB_TOKEN"], UnsetEnvVarConfig)
        self.assertEqual(
            ["/account/app_auth/github/terraform_pem_file"],
            config.envvars["GITHUB_APP_PEM_FILE"].paths,
        )


class TestSSMPathsKey(_WrapperFixtureCase):
    """Pattern: source: ssm with the plural ``paths`` YAML key."""

    def test_paths_only_parses_as_list(self):
        """A ``paths`` list deserializes to SSMEnvVarConfig.paths directly."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                paths:
                  - /a/b
                  - /c/d
            """,
        )

        config = parse_wrapper_configs([wrapper])

        envvar = config.envvars["MY_VAR"]
        self.assertIsInstance(envvar, SSMEnvVarConfig)
        self.assertEqual(["/a/b", "/c/d"], envvar.paths)

    def test_both_path_and_paths_prepends_path(self):
        """When both ``path`` and ``paths`` are present, ``path`` is prepended."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path: /primary
                paths:
                  - /secondary/a
                  - /secondary/b
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertEqual(
            ["/primary", "/secondary/a", "/secondary/b"],
            config.envvars["MY_VAR"].paths,
        )

    def test_deprecated_path_returns_first(self):
        """The deprecated .path property returns paths[0] for backward compatibility."""
        envvar = SSMEnvVarConfig(["/first", "/second"])

        self.assertEqual("/first", envvar.path)

    def test_path_list_fully_prepended(self):
        """When ``path`` is itself a list and ``paths`` is also given, all of path's entries prepend."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path:
                  - /primary/a
                  - /primary/b
                paths:
                  - /secondary
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertEqual(
            ["/primary/a", "/primary/b", "/secondary"],
            config.envvars["MY_VAR"].paths,
        )

    def test_child_paths_replaces_parent_paths(self):
        """A child ``paths`` list fully replaces the parent's — no list-union bleed."""
        parent = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                paths:
                  - /parent/a
                  - /parent/b
            """,
        )
        child = self._write(
            "config/leaf/.tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                paths:
                  - /child/x
            """,
        )

        config = parse_wrapper_configs([parent, child])

        self.assertEqual(["/child/x"], config.envvars["MY_VAR"].paths)


class TestSSMEnvVarConfigConstructorValidation(TestCase):
    """SSMEnvVarConfig rejects an empty paths list at construction time."""

    def test_empty_paths_raises_value_error(self):
        """Directly constructing SSMEnvVarConfig([]) raises ValueError."""
        with self.assertRaises(ValueError):
            SSMEnvVarConfig([])


class TestBackendsAndEnvvarsAndDependsCombined(_WrapperFixtureCase):
    """Pattern: snowflake-style file with backends + envvars + depends_on all populated."""

    def test_all_three_top_level_keys_coexist(self):
        """envvars, backends, and depends_on can be set together without interference."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              SNOWFLAKE_USER:
                source: ssm
                path: /account/app_auth/snowflake/amplify_prod_data_export/terraform_user/username
            backends:
              s3:
                region: us-west-2
                bucket: amplify-devops-uw2-terraform
                dynamodb_table: terraform-locking
            depends_on:
              - config/snowflake/amplify_prod_data_export_providers
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertIsInstance(config.envvars["SNOWFLAKE_USER"], SSMEnvVarConfig)
        self.assertEqual("amplify-devops-uw2-terraform", config.backends.s3.bucket)
        self.assertEqual(
            ["config/snowflake/amplify_prod_data_export_providers"], config.depends_on
        )
