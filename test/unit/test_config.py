"""Test terraform config utilities"""
import os
from unittest import TestCase

from unittest.mock import patch, MagicMock

from terrawrap.models.wrapper_config import WrapperConfig, BackendsConfig, S3BackendConfig
from terrawrap.utils.config import (
    calc_backend_config,
    parse_wrapper_configs,
    find_wrapper_config_files,
    resolve_envvars,
)

ROLE_ARN = 'arn:aws:iam::1234567890:role/test_role'
BUCKET = 'us-west-2--mclass--terraform--test'
REGION = 'us-west-2'
LOCK_TABLE = 'terraform-locking'


class TestConfig(TestCase):
    """Test terraform config utilities"""

    def setUp(self):
        self.prev_dir = os.getcwd()
        os.chdir(os.path.normpath(os.path.dirname(__file__) + '/../helpers'))

    def test_calc_backend_config(self):
        """Test that correct backend config is generated"""
        actual_config = calc_backend_config(
            'mock_directory/config/app1', {
                'region': REGION,
                'account_short_name': 'test',
            },
            WrapperConfig(),
            BackendsConfig(s3=S3BackendConfig(bucket=BUCKET, region=REGION))
        )

        expected_config = [
            '-reconfigure',
            ('-backend-config=dynamodb_table=%s' % LOCK_TABLE),
            '-backend-config=encrypt=true',
            '-backend-config=key=terrawrap/config/app1.tfstate',
            ('-backend-config=region=%s' % REGION),
            ('-backend-config=bucket=%s' % BUCKET),
            '-backend-config=skip_region_validation=true',
            '-backend-config=skip_credentials_validation=true'
        ]

        self.assertEqual(expected_config, actual_config)

    def test_calc_backend_config_wrapper_config(self):
        """Test that correct backend config is generated from the tf wrapper config"""
        wrapper_config = WrapperConfig(
            backends=BackendsConfig(
                s3=S3BackendConfig(
                    bucket=BUCKET,
                    region=REGION
                )
            )
        )

        actual_config = calc_backend_config(
            'mock_directory/config/app1',
            {},
            wrapper_config,
            BackendsConfig(s3=S3BackendConfig(bucket=BUCKET, region=REGION))
        )

        expected_config = [
            '-reconfigure',
            '-backend-config=dynamodb_table=%s' % LOCK_TABLE,
            '-backend-config=encrypt=true',
            '-backend-config=key=terrawrap/config/app1.tfstate',
            '-backend-config=region=%s' % REGION,
            '-backend-config=bucket=%s' % BUCKET,
            '-backend-config=skip_region_validation=true',
            '-backend-config=skip_credentials_validation=true'
        ]

        self.assertEqual(expected_config, actual_config)

    def test_calc_backend_config_with_role_arn(self):
        """Test that the correct role is used in backend config"""
        wrapper_config = WrapperConfig(
            backends=BackendsConfig(
                s3=S3BackendConfig(
                    bucket=BUCKET,
                    region=REGION,
                    role_arn=ROLE_ARN
                )
            )
        )

        actual_config = calc_backend_config(
            'mock_directory/config/app1',
            {},
            wrapper_config,
            BackendsConfig(s3=S3BackendConfig(bucket=BUCKET, region=REGION))
        )

        expected_config = [
            '-reconfigure',
            '-backend-config=dynamodb_table=%s' % LOCK_TABLE,
            '-backend-config=encrypt=true',
            '-backend-config=key=terrawrap/config/app1.tfstate',
            '-backend-config=region=%s' % REGION,
            '-backend-config=bucket=%s' % BUCKET,
            '-backend-config=skip_region_validation=true',
            '-backend-config=skip_credentials_validation=true',
            '-backend-config=role_arn=%s' % ROLE_ARN
        ]

        self.assertEqual(expected_config, actual_config)

    def test_find_wrapper_configs(self):
        """Test find wrapper configs along a confir dir's path"""
        actual_config_files = find_wrapper_config_files(
            os.path.join(os.getcwd(), 'mock_directory/config/app4')
        )
        expected_config_files = [
            os.path.join(os.getcwd(), 'mock_directory/config/.tf_wrapper'),
            os.path.join(os.getcwd(), 'mock_directory/config/app4/.tf_wrapper'),
        ]

        self.assertEqual(expected_config_files, actual_config_files)

    def test_parse_wrapper_config(self):
        """Test parse wrapper configs and merge correctly"""
        wrapper_config = parse_wrapper_configs(
            wrapper_config_files=[
                os.path.join(os.getcwd(), 'mock_directory/config/.tf_wrapper'),
                os.path.join(os.getcwd(), 'mock_directory/config/app4/.tf_wrapper'),
            ]
        )

        self.assertEqual("OVERWRITTEN_VALUE", wrapper_config.envvars["OVERWRITTEN_KEY"].value)
        self.assertEqual("HARDCODED_VALUE", wrapper_config.envvars["HARDCODED_KEY"].value)
        self.assertEqual("FAKE_SSM_PATH", wrapper_config.envvars["SSM_KEY"].path)

    @patch("terrawrap.utils.config.SSM_ENVVAR_CACHE")
    def test_resolve_envvars_from_wrapper_config(self, mock_ssm_cache):
        """Test envvars can be resolved correctly"""
        mock_ssm_cache.parameter.return_value = MagicMock(value="SSM_VALUE")
        wrapper_config = parse_wrapper_configs(
            wrapper_config_files=[
                os.path.join(os.getcwd(), 'mock_directory/config/.tf_wrapper'),
                os.path.join(os.getcwd(), 'mock_directory/config/app4/.tf_wrapper'),
            ]
        )

        actual_envvars = resolve_envvars(wrapper_config.envvars)

        self.assertEqual("OVERWRITTEN_VALUE", actual_envvars["OVERWRITTEN_KEY"])
        self.assertEqual("HARDCODED_VALUE", actual_envvars["HARDCODED_KEY"])
        self.assertEqual("SSM_VALUE", actual_envvars["SSM_KEY"])
        mock_ssm_cache.parameter.assert_called_once_with("FAKE_SSM_PATH")
