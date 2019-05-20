"""Test terraform config utilities"""
import os
from unittest import TestCase

from mock import patch, MagicMock

from terrawrap.models.wrapper_config import WrapperConfig, BackendsConfig, S3BackendConfig, SSMEnvVarConfig
from terrawrap.utils.config import calc_backend_config, resolve_envvars

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
        actual_config = calc_backend_config('mock_directory/config/app1', {
            'region': REGION,
            'account_short_name': 'test',
        }, WrapperConfig())

        expected_config = [
            '-reconfigure',
            ('-backend-config=dynamodb_table=%s' % LOCK_TABLE),
            '-backend-config=encrypt=true',
            '-backend-config=key=terrawrap/config/app1.tfstate',
            ('-backend-config=region=%s' % REGION),
            ('-backend-config=bucket=%s' % BUCKET),
            '-backend-config=skip_get_ec2_platforms=true',
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

        actual_config = calc_backend_config('mock_directory/config/app1', {}, wrapper_config)

        expected_config = [
            '-reconfigure',
            '-backend-config=dynamodb_table=%s' % LOCK_TABLE,
            '-backend-config=encrypt=true',
            '-backend-config=key=terrawrap/config/app1.tfstate',
            '-backend-config=region=%s' % REGION,
            '-backend-config=bucket=%s' % BUCKET,
            '-backend-config=skip_get_ec2_platforms=true',
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

        actual_config = calc_backend_config('mock_directory/config/app1', {}, wrapper_config)

        expected_config = [
            '-reconfigure',
            '-backend-config=dynamodb_table=%s' % LOCK_TABLE,
            '-backend-config=encrypt=true',
            '-backend-config=key=terrawrap/config/app1.tfstate',
            '-backend-config=region=%s' % REGION,
            '-backend-config=bucket=%s' % BUCKET,
            '-backend-config=skip_get_ec2_platforms=true',
            '-backend-config=skip_region_validation=true',
            '-backend-config=skip_credentials_validation=true',
            '-backend-config=role_arn=%s' % ROLE_ARN
        ]

        self.assertEqual(expected_config, actual_config)

    @patch('terrawrap.utils.config.get_ssm_cache')
    def test_resolve_envvars(self, get_ssm_cache_mock):
        """Test that env vars are correctly retrieved based on the config"""

        def get_ssm_cache_side_effect(region):
            ssm_cache = MagicMock()
            cache_result = MagicMock()
            ssm_cache.parameter.return_value = cache_result
            if region == 'us-moon-1':
                cache_result.value = 'other region value'
            else:
                cache_result.value = 'value'

            return ssm_cache

        get_ssm_cache_mock.side_effect = get_ssm_cache_side_effect

        env_vars = resolve_envvars({
            'var1': SSMEnvVarConfig('/foo/bar'),
            'var2': SSMEnvVarConfig('/foo/bar', 'us-moon-1')
        })

        self.assertEqual(env_vars, {
            'var1': 'value',
            'var2': 'other region value'
        })
