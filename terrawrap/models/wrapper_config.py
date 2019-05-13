# TODO: convert these classes to dataclasses once we drop support for Python3.6

from enum import Enum
from typing import Dict


class EnvVarSource(Enum):
    SSM = 'ssm'


class EnvVarConfig:
    def __init__(self, source: EnvVarSource, path: str = None):
        self.source = source
        self.path = path


class WrapperConfig:
    def __init__(self, configure_backend: bool = True, pipeline_check: bool = True,
                 envvars: Dict[str, EnvVarConfig] = None, resolved_envvars:Dict[str, str] = None):
        self.configure_backend = configure_backend
        self.pipeline_check = pipeline_check
        self.envvars = envvars
        self.resolved_envvars = resolved_envvars or {}
