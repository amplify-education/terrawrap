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
    def __init__(self, paths: List[str]):
        if not paths:
            raise ValueError("SSMEnvVarConfig requires at least one path")
        super().__init__(EnvVarSource.SSM)
        self.paths = paths

    @property
    def path(self) -> str:
        """Deprecated — returns paths[0] for backward compatibility.

        Use ``.paths`` to access the full list of SSM paths.
        """
        return self.paths[0]


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
        bucket: Optional[str] = None,
        region: Optional[str] = None,
        dynamodb_table: Optional[str] = None,
        role_arn: Optional[str] = None,
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
    def __init__(self, bucket: Optional[str] = None):
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


def _parse_ssm_paths(raw_path) -> List[str]:
    """Normalize the SSM ``path`` field to a non-empty list of strings."""
    if isinstance(raw_path, str):
        return [raw_path]
    if isinstance(raw_path, list):
        if not raw_path:
            raise ValueError("SSM envvar 'path' list must not be empty")
        if all(isinstance(p, str) for p in raw_path):
            return list(raw_path)
    raise TypeError(
        f"SSM envvar 'path' must be a string or list of strings, got {raw_path!r}"
    )


def _parse_paths_list(raw) -> List[str]:
    """Validate a YAML ``paths`` value as a non-empty list of strings."""
    if not isinstance(raw, list):
        raise TypeError(f"SSM envvar 'paths' must be a list of strings, got {raw!r}")
    if not raw:
        raise ValueError("SSM envvar 'paths' list must not be empty")
    if not all(isinstance(p, str) for p in raw):
        raise TypeError(f"SSM envvar 'paths' must be a list of strings, got {raw!r}")
    return list(raw)


def _ssm_paths_from_dict(obj_dict: Dict) -> List[str]:
    """Resolve the SSM path list from the ``path``/``paths`` YAML keys.

    When both keys are present, all entries from ``path`` are prepended to
    ``paths`` so nothing is silently truncated.
    """
    has_path = "path" in obj_dict
    has_paths = "paths" in obj_dict
    if not has_path and not has_paths:
        raise KeyError("SSM envvar requires 'path' or 'paths'")
    if not has_paths:
        return _parse_ssm_paths(obj_dict["path"])
    paths = _parse_paths_list(obj_dict["paths"])
    if has_path:
        paths = _parse_ssm_paths(obj_dict["path"]) + paths
    return paths


# pylint: disable=unused-argument
def env_var_deserializer(obj_dict, cls, **kwargs):
    """convert a dict to a subclass of AbstractEnvVarConfig"""
    source = obj_dict["source"]
    if source == EnvVarSource.SSM.value:
        return SSMEnvVarConfig(_ssm_paths_from_dict(obj_dict))
    if source == EnvVarSource.TEXT.value:
        return TextEnvVarConfig(obj_dict["value"])
    if source == EnvVarSource.UNSET.value:
        return UnsetEnvVarConfig()
    raise RuntimeError("Invalid Source")


jsons.set_deserializer(env_var_deserializer, AbstractEnvVarConfig)


# pylint: disable=too-many-arguments,too-many-positional-arguments
class WrapperConfig:
    def __init__(
        self,
        configure_backend: bool = True,
        pipeline_check: bool = True,
        backend_check: bool = True,
        plan_check: bool = True,
        envvars: Optional[Dict[str, AbstractEnvVarConfig]] = None,
        backends: Optional[BackendsConfig] = None,
        depends_on: Optional[List[str]] = None,
        config: bool = True,
        audit_api_url: Optional[str] = None,
        apply_automatically: bool = True,
        plugins: Optional[Dict[str, str]] = None,
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
