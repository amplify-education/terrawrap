"""Data classes to represent the wrapper config file"""
# TODO: convert these classes to dataclasses once we drop support for Python3.6
# pylint: disable=missing-docstring

from enum import Enum
from typing import Dict, Optional, List

import jsons


class EnvVarSource(Enum):
    SSM = "ssm"
    TEXT = "text"
    UNSET = "unset"


class AbstractEnvVarConfig:
    def __init__(self, source: EnvVarSource):
        self.source = source


class SSMEnvVarConfig(AbstractEnvVarConfig):
    def __init__(self, path: str):
        super().__init__(EnvVarSource.SSM)
        self.path = path


class TextEnvVarConfig(AbstractEnvVarConfig):
    def __init__(self, value: str):
        super().__init__(EnvVarSource.TEXT)
        self.value = value


class UnsetEnvVarConfig(AbstractEnvVarConfig):
    def __init__(self):
        super().__init__(EnvVarSource.UNSET)


class S3BackendConfig:
    def __init__(
        self,
        bucket: str = None,
        region: str = None,
        dynamodb_table: str = None,
        role_arn: str = None,
        # None by default to not override the native terraform backend option by the wrapper options
        # https://developer.hashicorp.com/terraform/language/upgrade-guides#s3-native-state-locking
        use_lockfile: Optional[bool] = None,
    ):
        self.region = region
        self.bucket = bucket
        self.dynamodb_table = dynamodb_table
        self.role_arn = role_arn
        self.use_lockfile = use_lockfile


class GCSBackendConfig:
    def __init__(self, bucket: str = None):
        self.bucket = bucket


class BackendsConfig:
    # pylint: disable=invalid-name
    def __init__(
        self,
        s3: Optional[S3BackendConfig] = None,
        gcs: Optional[GCSBackendConfig] = None,
    ):
        self.s3 = s3
        self.gcs = gcs


# pylint: disable=unused-argument
def env_var_deserializer(obj_dict, cls, **kwargs):
    """convert a dict to a subclass of AbstractEnvVarConfig"""
    if obj_dict["source"] == EnvVarSource.SSM.value:
        return SSMEnvVarConfig(obj_dict["path"])
    if obj_dict["source"] == EnvVarSource.TEXT.value:
        return TextEnvVarConfig(obj_dict["value"])
    if obj_dict["source"] == EnvVarSource.UNSET.value:
        return UnsetEnvVarConfig()

    raise RuntimeError("Invalid Source")


jsons.set_deserializer(env_var_deserializer, AbstractEnvVarConfig)


# pylint: disable=too-many-arguments
class WrapperConfig:
    def __init__(
        self,
        configure_backend: bool = True,
        pipeline_check: bool = True,
        backend_check: bool = True,
        plan_check: bool = True,
        envvars: Dict[str, AbstractEnvVarConfig] = None,
        backends: BackendsConfig = None,
        depends_on: List[str] = None,
        config: bool = True,
        audit_api_url: str = None,
        apply_automatically: bool = True,
        plugins: Dict[str, str] = None,
    ):
        self.configure_backend = configure_backend
        self.pipeline_check = pipeline_check
        self.backend_check = backend_check
        self.plan_check = plan_check
        self.envvars = envvars or {}
        self.backends = backends
        self.depends_on = depends_on
        self.config = config
        self.audit_api_url = audit_api_url
        self.apply_automatically = apply_automatically
        self.plugins = plugins or {}
