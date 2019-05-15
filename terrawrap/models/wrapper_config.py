"""Data classes to represent the wrapper config file"""
# TODO: convert these classes to dataclasses once we drop support for Python3.6

from enum import Enum
from typing import Dict

import jsons


# pylint: disable=missing-docstring
class EnvVarSource(Enum):
    SSM = 'ssm'


# pylint: disable=missing-docstring
class AbstractEnvVarConfig:
    def __init__(self, source: EnvVarSource):
        self.source = source


# pylint: disable=missing-docstring
class SSMEnvVarConfig(AbstractEnvVarConfig):
    def __init__(self, path: str):
        super().__init__(EnvVarSource.SSM)
        self.path = path


# pylint: disable=missing-docstring
class S3BackendConfig:
    def __init__(self, bucket: str, region: str, dynamodb_table: str = None, role_arn: str = None):
        self.region = region
        self.bucket = bucket
        self.dynamodb_table = dynamodb_table
        self.role_arn = role_arn


# pylint: disable=missing-docstring
class BackendsConfig:
    # pylint: disable=invalid-name
    def __init__(self, s3: S3BackendConfig = None):
        self.s3 = s3


# pylint: disable=unused-argument
def env_var_deserializer(obj_dict, cls, **kwargs):
    """convert a dict to a subclass of AbstractEnvVarConfig"""
    if obj_dict['source'] == EnvVarSource.SSM.value:
        return SSMEnvVarConfig(obj_dict['path'])

    raise RuntimeError('Invalid Source')


jsons.set_deserializer(env_var_deserializer, AbstractEnvVarConfig)


# pylint: disable=missing-docstring
class WrapperConfig:
    def __init__(
            self,
            configure_backend: bool = True,
            pipeline_check: bool = True,
            envvars: Dict[str, AbstractEnvVarConfig] = None,
            backends: BackendsConfig = None
    ):
        self.configure_backend = configure_backend
        self.pipeline_check = pipeline_check
        self.envvars = envvars or {}
        self.backends = backends
