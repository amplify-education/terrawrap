"""Holds config utilities"""
import os
import re
import subprocess
from typing import Dict, List, Optional

import hcl2
import jsons
import yaml
from ssm_cache import SSMParameterGroup

from terrawrap.models.wrapper_config import (
    WrapperConfig,
    AbstractEnvVarConfig,
    SSMEnvVarConfig,
    TextEnvVarConfig,
    BackendsConfig
)
from terrawrap.utils.collection_utils import update

GIT_REPO_REGEX = r"URL.*/([\w-]*)(?:\.git)?"
DEFAULT_REGION = 'us-west-2'
SSM_ENVVAR_CACHE = SSMParameterGroup(max_age=600)


def find_variable_files(path: str) -> List[str]:
    """
    Convenience function for finding all Terraform variable files by walking a given path.
    :param path: The path to the Terraform configuration directory.
    :return: A list of Terraform variable files that can be found by walking down that path, in order of
    discovery from the root of the path.
    """
    variable_files = []

    elements = path.split(os.path.sep)

    cur_path = os.path.sep

    for element in elements:
        cur_path = os.path.join(cur_path, element)
        for file in os.listdir(cur_path):
            if file.endswith(".auto.tfvars"):
                variable_files.append(os.path.join(cur_path, file))

    return variable_files


def find_wrapper_config_files(path: str) -> List[str]:
    """
    Convenience function for finding all wrapper config files by walking a given path.
    :param path: The path to the Terraform configuration directory.
    :return: A list of wrapper config files that can be found by walking down that path, in order of
    discovery from the root of the path.
    """
    wrapper_config_files = []

    elements = path.split(os.path.sep)

    cur_path = os.path.sep

    for element in elements:
        cur_path = os.path.join(cur_path, element)
        for file in os.listdir(cur_path):
            if file.endswith(".tf_wrapper") or file.endswith(".tf_wrapper.yml"):
                wrapper_config_files.append(os.path.join(cur_path, file))

    return wrapper_config_files


def parse_wrapper_configs(wrapper_config_files: List[str]) -> WrapperConfig:
    """
    Function for parsing the Terraform wrapper config file.
    :param wrapper_config_files: A list of file paths to wrapper config files. Config files later in the list
    override those earlier in the list, and are merged with the default config and earlier files.
    :return: A WrapperConfig object representing the accumulated values of all the wrapper config files
    """
    generated_wrapper_config: Dict = {}

    for wrapper_config_path in wrapper_config_files:
        with open(wrapper_config_path) as wrapper_config_file:
            wrapper_config = yaml.safe_load(wrapper_config_file)
            if wrapper_config and isinstance(wrapper_config, dict):
                generated_wrapper_config = update(generated_wrapper_config, wrapper_config)

    wrapper_config_obj: WrapperConfig = jsons.load(generated_wrapper_config, WrapperConfig, strict=True)
    return wrapper_config_obj


def resolve_envvars(envvar_configs: Dict[str, AbstractEnvVarConfig]) -> Dict[str, str]:
    """
    Resolves the 'envvars' section from the wrapper config to actual environment variables that can be easily
    supplied to a command.
    :param envvar_configs: The 'envvars' dictionary from the wrapper config.
    :return: A dictionary representing the environment variables that were resolved, with the key being the
    name of the environment variable and the value being the value of the environment variable.
    """
    resolved_envvars = {}
    for envvar_name, envvar_config in envvar_configs.items():
        if isinstance(envvar_config, SSMEnvVarConfig):
            resolved_envvars[envvar_name] = SSM_ENVVAR_CACHE.parameter(envvar_config.path).value
        if isinstance(envvar_config, TextEnvVarConfig):
            resolved_envvars[envvar_name] = envvar_config.value
    return resolved_envvars


def calc_backend_config(
        path: str,
        variables: Dict[str, str],
        wrapper_config: WrapperConfig,
        existing_backend_config: BackendsConfig
) -> List[str]:
    """
    Convenience function for calculating the backend config of the given Terraform directory.
    :param path: The path to the directory containing the Terraform config.
    :param variables: The variables derived from the auto.tfvars files.
    :param wrapper_config:
    :param existing_backend_config: Backend config object from parsing the terraform resource in the configs
    :return: A dictionary representing the backend configuration for the Terraform directory.
    """

    backend_config = ['-reconfigure']
    options: Dict[str, str] = {}

    byte_output = subprocess.check_output(["git", "remote", "show", "origin", "-n"], cwd=path)
    output = byte_output.decode("utf-8", errors="replace")
    match = re.search(GIT_REPO_REGEX, output)
    if match:
        repo_name = match.group(1)
    else:
        raise RuntimeError("Could not determine git repo name, are we in a git repo?")

    # for backwards compatibility, include the default s3 backend options we used to automatically include
    if existing_backend_config.s3 is not None:
        terraform_bucket = "{region}--mclass--terraform--{account_short_name}".format(
            region=variables.get('region'),
            account_short_name=variables.get('account_short_name')
        )

        options = {
            'dynamodb_table': variables.get('terraform_lock_table', 'terraform-locking'),
            'encrypt': 'true',
            'key': '%s/%s.tfstate' % (repo_name, path[path.index("/config") + 1:]),
            'region': variables.get('region', ''),
            'bucket': variables.get('terraform_state_bucket', terraform_bucket),
            'skip_region_validation': 'true',
            'skip_credentials_validation': 'true'
        }

    # copy any backend options from the backend config
    if wrapper_config.backends:
        wrapper_options: Dict[str, Optional[str]] = {}
        if existing_backend_config.gcs is not None and wrapper_config.backends.gcs is not None:
            # convert the object into a dict so we can append each field to the backend config dynamically
            wrapper_options = vars(wrapper_config.backends.gcs)
            wrapper_options['prefix'] = '%s/%s' % (repo_name, path[path.index("/config") + 1:])
        if existing_backend_config.s3 is not None and wrapper_config.backends.s3 is not None:
            wrapper_options = vars(wrapper_config.backends.s3)
        options.update({key: value for key, value in wrapper_options.items() if value is not None})

    backend_config.extend(['-backend-config=%s=%s' % (key, value) for key, value in options.items()])
    return backend_config


def parse_variable_files(variable_files: List[str]) -> Dict[str, str]:
    """
    Convenience function for parsing variable files and returning the variables as a dictionary
    :param variable_files: List of file paths to variable files. Variable files overwrite files before them.
    :return: A dictionary representing the contents of those variable files.
    """
    variables: Dict = {}

    for variable_file in variable_files:
        with open(variable_file) as var_file:
            flat_vars = {key: values[0] for key, values in hcl2.load(var_file).items()}
            variables.update(flat_vars)

    return variables


def parse_backend_config_for_dir(dir_path: str) -> Optional[BackendsConfig]:
    """
    Parse tf files in a directory and try to get the state backend config from the "terraform" resource
    :param dir_path: Directory that has tf files
    :return: Backend config if a "terraform" resource exists, otherwise None
    """
    for file_path in os.listdir(dir_path):
        if '.terraform' in file_path or not file_path.endswith('tf'):
            continue

        result = _parse_backend_config_for_file(
            file_path=os.path.join(dir_path, file_path),
        )
        if result:
            return result

    return None


def _parse_backend_config_for_file(file_path: str) -> Optional[BackendsConfig]:
    with open(file_path) as tf_file:
        try:
            configs: Dict[str, List] = hcl2.load(tf_file)

            terraform_config_blocks: List[Dict] = configs.get('terraform', [])
            for terraform_config in terraform_config_blocks:
                if 'backend' in terraform_config:
                    return jsons.load(terraform_config['backend'][0], BackendsConfig, strict=True)
            return None
        except Exception:
            print('Error while parsing file %s' % file_path)
            raise
