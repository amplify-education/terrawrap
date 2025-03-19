"""Test terraform config utilities"""
import os
from unittest import TestCase

from unittest.mock import patch, MagicMock

import networkx

from terrawrap.models.wrapper_config import (
    WrapperConfig,
    BackendsConfig,
    S3BackendConfig,
)
from terrawrap.utils.config import (
    calc_backend_config,
    parse_wrapper_configs,
    find_wrapper_config_files,
    resolve_envvars,
    graph_wrapper_dependencies,
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
        starting_dir = os.path.join(
            os.getcwd(), "mock_graph_directory/config/account_level/regional_level_2"
        )
        actual_graph, actual_post_graph = walk_and_graph_directory(
            starting_dir, self.config_dict
        )

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

        app_team_4 = os.path.join(os.getcwd(), "mock_directory/config/team/app4")

        expected_post_graph = [app1, app2, app_team_4]

        expected_post_graph.sort()
        actual_post_graph.sort()

        self.assertEqual(actual_post_graph, expected_post_graph)

    def wont_apply_automatically_in_parrallel(self):
        """Test will not automatically apply if set with no dependency info"""
        starting_dir = os.path.join(
            os.getcwd(), "mock_graph_directory/config/account_level/regional_level_3"
        )
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
            "-backend-config=use_lockfile=false",
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
            "-backend-config=use_lockfile=false",
        ]

        self.assertEqual(expected_config, actual_config)

    def test_calc_backend_config_with_role_arn(self):
        """Test that the correct role is used in backend config"""
        wrapper_config = WrapperConfig(
            backends=BackendsConfig(
                s3=S3BackendConfig(bucket=BUCKET, region=REGION, role_arn=ROLE_ARN)
            )
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
            "-backend-config=use_lockfile=false",
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

        self.assertEqual(
            "OVERWRITTEN_VALUE", wrapper_config.envvars["OVERWRITTEN_KEY"].value
        )
        self.assertEqual(
            "HARDCODED_VALUE", wrapper_config.envvars["HARDCODED_KEY"].value
        )
        self.assertEqual("FAKE_SSM_PATH", wrapper_config.envvars["SSM_KEY"].path)

    @patch("terrawrap.utils.config.SSM_ENVVAR_CACHE")
    def test_resolve_envvars_from_wrapper_config(self, mock_ssm_cache):
        """Test envvars can be resolved correctly"""
        mock_ssm_cache.parameter.return_value = MagicMock(value="SSM_VALUE")
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
        mock_ssm_cache.parameter.assert_called_once_with("FAKE_SSM_PATH")
