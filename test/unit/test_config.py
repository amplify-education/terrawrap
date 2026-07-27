"""Test terraform config utilities"""

import os
import shutil
import tempfile
import textwrap
from unittest import TestCase
from unittest.mock import patch

import networkx

from terrawrap.exceptions import EnvVarResolutionError
from terrawrap.models.wrapper_config import (
    DEFAULT_COMMAND_TIMEOUT,
    BackendsConfig,
    CommandEnvVarConfig,
    S3BackendConfig,
    SSMEnvVarConfig,
    WrapperConfig,
    env_var_deserializer,
)
from terrawrap.utils.config import (
    calc_backend_config,
    find_wrapper_config_files,
    graph_wrapper_dependencies,
    parse_wrapper_configs,
    resolve_envvars,
    walk_and_graph_directory,
    walk_without_graph_directory,
)

ROLE_ARN = "arn:aws:iam::1234567890:role/test_role"
BUCKET = "us-west-2--mclass--terraform--test"
REGION = "us-west-2"
LOCK_TABLE = "terraform-locking"


class TestConfig(TestCase):
    """Test terraform config utilities"""

    def setUp(self):
        self.prev_dir = os.getcwd()
        os.chdir(os.path.normpath(os.path.dirname(__file__) + "/../helpers"))
        self.config_dict = {}

    def test_graph_wrapper_dependencies(self):
        """Test dependency graph for a single directory"""
        actual_graph = networkx.DiGraph()
        visited = []
        current_dir = os.path.join(
            os.getcwd(),
            "mock_graph_directory/config/account_level/regional_level_2/app2",
        )
        graph_wrapper_dependencies(current_dir, self.config_dict, actual_graph, visited)

        expected_graph = networkx.DiGraph()
        app3 = os.path.join(
            os.getcwd(),
            "mock_graph_directory/config/account_level/regional_level_2/app2",
        )
        app1 = os.path.join(
            os.getcwd(),
            "mock_graph_directory/config/account_level/regional_level_1/app1",
        )
        expected_graph.add_node(app3)
        expected_graph.add_node(app1)
        expected_graph.add_edge(app1, app3)

        self.assertTrue(networkx.is_isomorphic(actual_graph, expected_graph))

    def test_walk_and_graph_directory(self):
        """Test dependency graph for a recursive dependency"""
        starting_dir = os.path.join(os.getcwd(), "mock_graph_directory/config/account_level/regional_level_2")
        actual_graph, actual_post_graph = walk_and_graph_directory(starting_dir, self.config_dict)

        expected_graph = networkx.DiGraph()
        app1 = os.path.join(
            os.getcwd(),
            "mock_graph_directory/config/account_level/regional_level_1/app1",
        )
        app2 = os.path.join(
            os.getcwd(),
            "mock_graph_directory/config/account_level/regional_level_2/app2",
        )
        app4 = os.path.join(
            os.getcwd(),
            "mock_graph_directory/config/account_level/regional_level_2/app4",
        )
        app5 = os.path.join(
            os.getcwd(),
            "mock_graph_directory/config/account_level/regional_level_2/team/app5",
        )
        app9 = os.path.join(
            os.getcwd(),
            "mock_graph_directory/config/account_level/regional_level_2/team/app9",
        )
        expected_graph.add_nodes_from([app1, app2, app4, app5])
        expected_graph.add_edge(app4, app5)
        expected_graph.add_edge(app2, app4)
        expected_graph.add_edge(app1, app2)
        expected_post_graph = [
            os.path.join(
                os.getcwd(),
                "mock_graph_directory/config/account_level/regional_level_2/app7",
            )
        ]

        self.assertTrue(networkx.is_isomorphic(actual_graph, expected_graph))
        self.assertEqual(actual_post_graph, expected_post_graph)
        self.assertTrue(app9 not in actual_graph.nodes)
        self.assertTrue(app9 not in actual_post_graph)

    def test_walk_without_graph_directory(self):
        """Test will find and list all config dirs if no dependency information"""
        starting_dir = os.path.join(os.getcwd(), "mock_directory/config/")
        actual_post_graph = walk_without_graph_directory(starting_dir)

        app1 = os.path.join(os.getcwd(), "mock_directory/config/app1")
        app2 = os.path.join(os.getcwd(), "mock_directory/config/app2")
        area_svc = os.path.join(os.getcwd(), "mock_directory/config/area/svc")

        app_team_4 = os.path.join(os.getcwd(), "mock_directory/config/team/app4")

        expected_post_graph = [app1, app2, area_svc, app_team_4]

        expected_post_graph.sort()
        actual_post_graph.sort()

        self.assertEqual(actual_post_graph, expected_post_graph)

    def wont_apply_automatically_in_parrallel(self):
        """Test will not automatically apply if set with no dependency info"""
        starting_dir = os.path.join(os.getcwd(), "mock_graph_directory/config/account_level/regional_level_3")
        actual_post_graph = walk_without_graph_directory(starting_dir)

        app1 = os.path.join(starting_dir, "/app1")
        app3 = os.path.join(starting_dir, "/app3")
        app4 = os.path.join(starting_dir, "/app4")
        app7 = os.path.join(starting_dir, "/app7")

        expected_post_graph = [app1, app3, app4]

        expected_post_graph.sort()
        actual_post_graph.sort()

        self.assertEqual(actual_post_graph, expected_post_graph)
        self.assertTrue(app7 not in actual_post_graph)

    def test_calc_backend_config(self):
        """Test that correct backend config is generated"""
        actual_config = calc_backend_config(
            "mock_directory/config/app1",
            {
                "region": REGION,
                "account_short_name": "test",
            },
            WrapperConfig(),
            BackendsConfig(s3=S3BackendConfig(bucket=BUCKET, region=REGION)),
        )

        expected_config = [
            "-reconfigure",
            "-upgrade",
            (f"-backend-config=dynamodb_table={LOCK_TABLE}"),
            "-backend-config=encrypt=true",
            "-backend-config=key=terrawrap/config/app1.tfstate",
            (f"-backend-config=region={REGION}"),
            (f"-backend-config=bucket={BUCKET}"),
            "-backend-config=skip_region_validation=true",
            "-backend-config=skip_credentials_validation=true",
        ]

        self.assertEqual(expected_config, actual_config)

    def test_calc_backend_config_wrapper_config(self):
        """Test that correct backend config is generated from the tf wrapper config"""
        wrapper_config = WrapperConfig(
            backends=BackendsConfig(s3=S3BackendConfig(bucket=BUCKET, region=REGION))
        )

        actual_config = calc_backend_config(
            "mock_directory/config/app1",
            {},
            wrapper_config,
            BackendsConfig(s3=S3BackendConfig(bucket=BUCKET, region=REGION)),
        )

        expected_config = [
            "-reconfigure",
            "-upgrade",
            f"-backend-config=dynamodb_table={LOCK_TABLE}",
            "-backend-config=encrypt=true",
            "-backend-config=key=terrawrap/config/app1.tfstate",
            f"-backend-config=region={REGION}",
            f"-backend-config=bucket={BUCKET}",
            "-backend-config=skip_region_validation=true",
            "-backend-config=skip_credentials_validation=true",
        ]

        self.assertEqual(expected_config, actual_config)

    def test_calc_backend_config_with_role_arn(self):
        """Test that the correct role is used in backend config"""
        wrapper_config = WrapperConfig(
            backends=BackendsConfig(s3=S3BackendConfig(bucket=BUCKET, region=REGION, role_arn=ROLE_ARN))
        )

        actual_config = calc_backend_config(
            "mock_directory/config/app1",
            {},
            wrapper_config,
            BackendsConfig(s3=S3BackendConfig(bucket=BUCKET, region=REGION)),
        )

        expected_config = [
            "-reconfigure",
            "-upgrade",
            f"-backend-config=dynamodb_table={LOCK_TABLE}",
            "-backend-config=encrypt=true",
            "-backend-config=key=terrawrap/config/app1.tfstate",
            f"-backend-config=region={REGION}",
            f"-backend-config=bucket={BUCKET}",
            "-backend-config=skip_region_validation=true",
            "-backend-config=skip_credentials_validation=true",
            f"-backend-config=role_arn={ROLE_ARN}",
        ]

        self.assertEqual(expected_config, actual_config)

    def test_find_wrapper_configs(self):
        """Test find wrapper configs along a confir dir's path"""
        actual_config_files = find_wrapper_config_files(
            os.path.join(os.getcwd(), "mock_directory/config/app4")
        )
        expected_config_files = [
            os.path.join(os.getcwd(), "mock_directory/config/.tf_wrapper"),
            os.path.join(os.getcwd(), "mock_directory/config/app4/.tf_wrapper"),
        ]

        self.assertEqual(expected_config_files, actual_config_files)

    def test_parse_wrapper_config(self):
        """Test parse wrapper configs and merge correctly"""
        wrapper_config = parse_wrapper_configs(
            wrapper_config_files=[
                os.path.join(os.getcwd(), "mock_directory/config/.tf_wrapper"),
                os.path.join(os.getcwd(), "mock_directory/config/app4/.tf_wrapper"),
            ]
        )

        self.assertEqual("OVERWRITTEN_VALUE", wrapper_config.envvars["OVERWRITTEN_KEY"].value)
        self.assertEqual("HARDCODED_VALUE", wrapper_config.envvars["HARDCODED_KEY"].value)
        self.assertEqual(["FAKE_SSM_PATH"], wrapper_config.envvars["SSM_KEY"].paths)

    @patch("terrawrap.utils.config.resolve_ssm_paths")
    def test_resolve_envvars_from_wrapper_config(self, mock_resolve_ssm_paths):
        """Test envvars can be resolved correctly"""
        mock_resolve_ssm_paths.return_value = "SSM_VALUE"
        wrapper_config = parse_wrapper_configs(
            wrapper_config_files=[
                os.path.join(os.getcwd(), "mock_directory/config/.tf_wrapper"),
                os.path.join(os.getcwd(), "mock_directory/config/app4/.tf_wrapper"),
            ]
        )

        actual_envvars = resolve_envvars(wrapper_config.envvars)

        self.assertEqual("OVERWRITTEN_VALUE", actual_envvars["OVERWRITTEN_KEY"])
        self.assertEqual("HARDCODED_VALUE", actual_envvars["HARDCODED_KEY"])
        self.assertEqual("SSM_VALUE", actual_envvars["SSM_KEY"])
        self.assertEqual("10", actual_envvars["NOT_A_STRING"])
        self.assertEqual(None, actual_envvars["FORCE_UNSET"])
        mock_resolve_ssm_paths.assert_called_once_with(["FAKE_SSM_PATH"])


class TestPathMergeSemantics(TestCase):
    """Verify .tf_wrapper merge semantics for SSMEnvVarConfig.paths across the parent/child chain."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="terrawrap_paths_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, rel_path: str, body: str) -> str:
        abs_path = os.path.join(self.tmpdir, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(body).lstrip())
        return abs_path

    def test_string_path_normalized_to_list(self):
        """A scalar `path` in YAML deserializes to a single-element list."""
        parent = self._write(
            "parent/.tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path: /a/b/c
            """,
        )

        config = parse_wrapper_configs([parent])

        envvar = config.envvars["MY_VAR"]
        self.assertIsInstance(envvar, SSMEnvVarConfig)
        self.assertEqual(["/a/b/c"], envvar.paths)

    def test_child_list_replaces_parent_string(self):
        """Parent scalar `path` followed by child list — child wins, no type-mismatch crash."""
        parent = self._write(
            "parent/.tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path: /parent/path
            """,
        )
        child = self._write(
            "parent/child/.tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path:
                  - /child/path/a
                  - /child/path/b
            """,
        )

        config = parse_wrapper_configs([parent, child])

        self.assertEqual(["/child/path/a", "/child/path/b"], config.envvars["MY_VAR"].paths)

    def test_child_string_replaces_parent_list(self):
        """Parent list `path` followed by child scalar — child wins as a single-element list."""
        parent = self._write(
            "parent/.tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path:
                  - /parent/a
                  - /parent/b
            """,
        )
        child = self._write(
            "parent/child/.tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path: /child/path
            """,
        )

        config = parse_wrapper_configs([parent, child])

        self.assertEqual(["/child/path"], config.envvars["MY_VAR"].paths)

    def test_child_list_replaces_parent_list(self):
        """Two lists — child's list fully replaces parent's; no additive union."""
        parent = self._write(
            "parent/.tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path:
                  - /parent/a
            """,
        )
        child = self._write(
            "parent/child/.tf_wrapper",
            """
            envvars:
              MY_VAR:
                source: ssm
                path:
                  - /child/a
                  - /child/b
            """,
        )

        config = parse_wrapper_configs([parent, child])

        self.assertEqual(["/child/a", "/child/b"], config.envvars["MY_VAR"].paths)

    def test_unset_replaced_by_ssm_child(self):
        """A parent `unset` entry is fully replaced when a child declares the same var via SSM."""
        parent = self._write(
            "github/.tf_wrapper",
            """
            envvars:
              GITHUB_TOKEN:
                source: unset
            """,
        )
        child = self._write(
            "github/amplify-enterprise/.tf_wrapper",
            """
            envvars:
              GITHUB_TOKEN:
                source: ssm
                path: /account/app_auth/github/terraform_token
            """,
        )

        config = parse_wrapper_configs([parent, child])

        envvar = config.envvars["GITHUB_TOKEN"]
        self.assertIsInstance(envvar, SSMEnvVarConfig)
        self.assertEqual(["/account/app_auth/github/terraform_token"], envvar.paths)


class TestAuditApiUrlParsing(TestCase):
    """Verify audit_api_url accepts a scalar URL or a list of URLs."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="terrawrap_audit_url_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, rel_path: str, body: str) -> str:
        abs_path = os.path.join(self.tmpdir, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(body).lstrip())
        return abs_path

    def test_scalar_url(self):
        """A scalar audit_api_url deserializes as a single-element list."""
        parent = self._write(
            "parent/.tf_wrapper",
            """
            audit_api_url: https://audit.example.com
            """,
        )

        config = parse_wrapper_configs([parent])

        self.assertEqual(["https://audit.example.com"], config.audit_api_url)

    def test_list_of_urls(self):
        """A list audit_api_url deserializes as a list of strings."""
        parent = self._write(
            "parent/.tf_wrapper",
            """
            audit_api_url:
              - https://audit-a.example.com
              - https://audit-b.example.com
            """,
        )

        config = parse_wrapper_configs([parent])

        self.assertEqual(
            ["https://audit-a.example.com", "https://audit-b.example.com"],
            config.audit_api_url,
        )

    def test_child_list_replaces_parent_scalar(self):
        """A child list overrides a parent scalar without a type-mismatch crash."""
        parent = self._write(
            "parent/.tf_wrapper",
            """
            audit_api_url: https://parent.example.com
            """,
        )
        child = self._write(
            "parent/child/.tf_wrapper",
            """
            audit_api_url:
              - https://child-a.example.com
              - https://child-b.example.com
            """,
        )

        config = parse_wrapper_configs([parent, child])

        self.assertEqual(
            ["https://child-a.example.com", "https://child-b.example.com"],
            config.audit_api_url,
        )


class TestSiblingIsolation(TestCase):
    """Regression tests proving child .tf_wrappers cannot leak into sibling subtrees."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="terrawrap_sibling_")
        os.makedirs(os.path.join(self.tmpdir, "github", "amplify-enterprise"))
        os.makedirs(os.path.join(self.tmpdir, "github", "amplify-education", "astrotools"))
        with open(os.path.join(self.tmpdir, "github", ".tf_wrapper"), "w", encoding="utf-8") as handle:
            handle.write("envvars:\n  GITHUB_TOKEN:\n    source: unset\n")
        with open(
            os.path.join(self.tmpdir, "github", "amplify-enterprise", ".tf_wrapper"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(
                "envvars:\n  GITHUB_TOKEN:\n    source: ssm\n"
                "    path: /account/app_auth/github/terraform_token\n"
            )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_sibling_subtree_is_not_visited(self):
        """find_wrapper_config_files for amplify-education/astrotools must skip amplify-enterprise."""
        sibling = os.path.join(self.tmpdir, "github", "amplify-education", "astrotools")

        files = find_wrapper_config_files(sibling)

        github_wrapper = os.path.join(self.tmpdir, "github", ".tf_wrapper")
        enterprise_wrapper = os.path.join(self.tmpdir, "github", "amplify-enterprise", ".tf_wrapper")
        self.assertIn(github_wrapper, files)
        self.assertNotIn(enterprise_wrapper, files)


class TestCommandEnvVarSource(TestCase):
    """Verify the `command` envvar source parses, resolves, and fails loudly."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="terrawrap_command_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, rel_path: str, body: str) -> str:
        abs_path = os.path.join(self.tmpdir, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(body).lstrip())
        return abs_path

    def test_command_resolves_to_stdout(self):
        """A `command` envvar resolves to the command's stdout."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              MY_TOKEN:
                source: command
                command: ["echo", "resolved-value"]
            """,
        )

        config = parse_wrapper_configs([wrapper])
        envvar = config.envvars["MY_TOKEN"]
        self.assertIsInstance(envvar, CommandEnvVarConfig)
        self.assertEqual(["echo", "resolved-value"], envvar.command)
        self.assertEqual(DEFAULT_COMMAND_TIMEOUT, envvar.timeout)

        self.assertEqual({"MY_TOKEN": "resolved-value"}, resolve_envvars(config.envvars))

    def test_surrounding_whitespace_is_stripped(self):
        """Trailing newlines from a command must not leak into the envvar value."""
        resolved = resolve_envvars({"PADDED": CommandEnvVarConfig(["printf", "  padded  "])})

        self.assertEqual({"PADDED": "padded"}, resolved)

    def test_explicit_timeout_is_parsed(self):
        """An explicit `timeout` overrides the default."""
        wrapper = self._write(
            "config/.tf_wrapper",
            """
            envvars:
              MY_TOKEN:
                source: command
                command: ["echo", "hi"]
                timeout: 5
            """,
        )

        config = parse_wrapper_configs([wrapper])

        self.assertEqual(5, config.envvars["MY_TOKEN"].timeout)

    def test_string_command_is_rejected(self):
        """A bare string would be mis-parsed without a shell, so reject it outright."""
        with self.assertRaises(TypeError):
            env_var_deserializer({"source": "command", "command": "echo hi"}, CommandEnvVarConfig)

    def test_empty_command_is_rejected(self):
        with self.assertRaises(ValueError):
            env_var_deserializer({"source": "command", "command": []}, CommandEnvVarConfig)

    def test_missing_command_key_is_rejected(self):
        with self.assertRaises(KeyError):
            env_var_deserializer({"source": "command"}, CommandEnvVarConfig)

    def test_non_integer_timeout_is_rejected(self):
        with self.assertRaises(TypeError):
            env_var_deserializer(
                {"source": "command", "command": ["echo"], "timeout": "30"}, CommandEnvVarConfig
            )

    def test_zero_timeout_is_rejected(self):
        with self.assertRaises(ValueError):
            env_var_deserializer(
                {"source": "command", "command": ["echo"], "timeout": 0}, CommandEnvVarConfig
            )

    def test_failing_command_raises_with_stderr(self):
        """A non-zero exit must fail loudly, not resolve to an empty value."""
        command = ["sh", "-c", "echo 'boom' >&2; exit 3"]

        with self.assertRaises(EnvVarResolutionError) as context:
            resolve_envvars({"MY_TOKEN": CommandEnvVarConfig(command)})

        self.assertIn("MY_TOKEN", str(context.exception))
        self.assertIn("exited 3", str(context.exception))
        self.assertIn("boom", str(context.exception))

    def test_timed_out_command_raises(self):
        with self.assertRaises(EnvVarResolutionError) as context:
            resolve_envvars({"MY_TOKEN": CommandEnvVarConfig(["sleep", "10"], timeout=1)})

        self.assertIn("timed out after 1s", str(context.exception))

    def test_missing_binary_raises(self):
        with self.assertRaises(EnvVarResolutionError) as context:
            resolve_envvars({"MY_TOKEN": CommandEnvVarConfig(["terrawrap-no-such-binary-b3f1a2"])})

        self.assertIn("could not be run", str(context.exception))
