"""Holds config utilities"""
import os
import sys
from typing import Dict, List, Optional, Tuple
import networkx

import hcl2
import jsons
import yaml
from jsons import DeserializationError
from ssm_cache import SSMParameterGroup

from terrawrap.exceptions import NotTerraformConfigDirectory, NoDependency
from terrawrap.models.wrapper_config import (
    WrapperConfig,
    AbstractEnvVarConfig,
    SSMEnvVarConfig,
    TextEnvVarConfig,
    BackendsConfig,
    UnsetEnvVarConfig,
)
from terrawrap.utils.collection_utils import update
from terrawrap.utils.path import get_absolute_path, calc_repo_path

DEFAULT_REGION = 'us-west-2'
SSM_ENVVAR_CACHE = SSMParameterGroup(max_age=600)
TF_WRAP_FILE = ".tf_wrapper"


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
            if file.endswith(TF_WRAP_FILE):
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
        with open(wrapper_config_path, encoding='utf-8') as wrapper_config_file:
            wrapper_config = yaml.safe_load(wrapper_config_file)
            if wrapper_config and isinstance(wrapper_config, dict):
                generated_wrapper_config = update(generated_wrapper_config, wrapper_config)

    try:
        wrapper_config_obj: WrapperConfig = jsons.load(generated_wrapper_config, WrapperConfig, strict=True)
        return wrapper_config_obj
    except DeserializationError as exception:
        print(f"Cannot parse wrapper config from files: {wrapper_config_files}")
        raise exception


def is_config_directory(directory: str) -> bool:
    """
    Checks if a wrapper file directory is a config_directory
    :param directory: A wrapper files directory
    :return: A boolean True if the config section of the wrapper file is not False or doesn't exist.
    """
    config = False
    for file in os.listdir(directory):
        if file.endswith(".tf"):
            config = True
    return config


def create_wrapper_config_obj(config_dir, wrapper_file=None):
    """
    Given a config dir containing a tf_wrapper.
    Parses the tf_wrapper for dependencies and makes a a wrapper config object.
    :param config_dir: A tf directory containing a tf_wrapper.
    :param wrapper_file: A wrapper file passed in if known
    :return: wrapper_config_obj: a wrapper config object
    """
    if not wrapper_file:
        for file in os.listdir(config_dir):
            if file.endswith(TF_WRAP_FILE):
                wrapper_file = os.path.join(config_dir, file)

    wrapper_files = [wrapper_file] if wrapper_file else []
    wrapper_config_obj: WrapperConfig = parse_wrapper_configs(wrapper_files)
    if wrapper_config_obj.depends_on:
        depends_on = []
        for dependency in wrapper_config_obj.depends_on:
            abs_dependency = get_absolute_path(dependency)
            if not os.path.isdir(abs_dependency):
                abs_dependency = get_absolute_path(dependency, config_dir)
            depends_on.append(abs_dependency)
        wrapper_config_obj.depends_on = depends_on
    if not is_config_directory(config_dir):
        wrapper_config_obj.config = False
    return wrapper_config_obj


def walk_and_graph_directory(starting_dir: str, config_dict) -> Tuple[networkx.DiGraph, List[str]]:
    """
    Given a starting directory, walks it and returns all dependency info.
    :param starting_dir: The starting directory
    :param config_dict: A dictionary containing wrapper config objects for each seen directory
    :return: directory_graph: A graph composed of all dependency information for a directory
    """
    graph_list = []
    post_graph_runs = []
    for root, _, files in os.walk(starting_dir):
        has_tf_wrapper = False
        for file in files:
            if file.endswith(TF_WRAP_FILE):
                has_tf_wrapper = True
                wrapper_file = os.path.join(root, file)
                wrapper_config_obj = create_wrapper_config_obj(root, wrapper_file)
                if not wrapper_config_obj.config:
                    continue
                if not wrapper_config_obj.apply_automatically:
                    continue
                if wrapper_config_obj.depends_on is None:
                    post_graph_runs.append(root)
                    continue
                single_config_dependency_graph = networkx.DiGraph()
                visited: List[str] = []
                graph_wrapper_dependencies(root, config_dict, single_config_dependency_graph, visited)
                graph_list.append(single_config_dependency_graph)
        if not has_tf_wrapper and is_config_directory(root):
            post_graph_runs.append(root)
    directory_graph = networkx.compose_all(graph_list)

    return directory_graph, post_graph_runs


def walk_without_graph_directory(starting_dir: str) -> List[str]:
    """
    Given a starting directory, walks it and returns a list of all tf configs to apply.
    :param starting_dir: The starting directory
    :return: post_graph: A graph composed of all dependency information for a directory
    """
    post_graph_runs = []
    for root, _, files in os.walk(starting_dir):
        has_tf_wrapper = False
        for file in files:
            if file.endswith(TF_WRAP_FILE):
                has_tf_wrapper = True
                wrapper_file = os.path.join(root, file)
                wrapper_config_obj = create_wrapper_config_obj(root, wrapper_file)
                if wrapper_config_obj.depends_on is not None:
                    raise NoDependency("Discovered dependency information")
                if not wrapper_config_obj.config:
                    continue
                if not wrapper_config_obj.apply_automatically:
                    continue
                post_graph_runs.append(root)
        if not has_tf_wrapper and is_config_directory(root):
            post_graph_runs.append(root)

    return post_graph_runs


# pylint: disable=R0912
def graph_wrapper_dependencies(config_dir: str, config_dict, graph: networkx.DiGraph, visited: List[str]):
    """
    Given a directory, recursively finds all other directories it depends on and builds a graph.
    :param config_dir: The config directory to obtain a dependency graph for
    :param config_dict: A dictionary containing wrapper config objects for each seen directory
    :param graph: The graph to add dependency info to. Empty at first, reused in recursion.
    :param visited: A list of visited nodes. Empty at first, reused in recursion
    """
    if config_dir in visited:
        return
    visited.append(config_dir)

    if config_dict.get(config_dir):  # add to dictionary so we only read the file once
        wrapper_config_obj = config_dict[config_dir].get("wrapper_config")
    else:
        wrapper_config_obj = create_wrapper_config_obj(config_dir)
        config_dict[config_dir] = {
            "wrapper_config": wrapper_config_obj
        }

    if wrapper_config_obj.config:
        graph.add_node(config_dir)

    tf_dependencies = wrapper_config_obj.depends_on

    if tf_dependencies is None:
        print("Cannot list a dependency without tf_wrapper dependency configuration:", config_dir)
        sys.exit(1)

    for dependency in tf_dependencies:
        graph.add_node(dependency)
        if config_dir in graph:
            graph.add_edge(dependency, config_dir)

    wrappers = find_wrapper_config_files(config_dir)
    wrappers.reverse()  # we want the closest wrapper file that gives inherited dependencies
    for wrapper in wrappers:
        wrapper_dir = os.path.dirname(wrapper)
        if config_dict.get(wrapper_dir):  # add to dictionary so we only read the file once
            new_wrapper_config_obj = config_dict[wrapper_dir].get("wrapper_config")
        else:
            new_wrapper_config_obj = create_wrapper_config_obj(wrapper_dir)
            config_dict[wrapper_dir] = {
                "wrapper_config": new_wrapper_config_obj
            }

        if wrapper_dir == config_dir:
            continue
        if new_wrapper_config_obj.depends_on is not None:
            inherited_dependencies = new_wrapper_config_obj.depends_on
            added = False
            for dependency in inherited_dependencies:
                if dependency == config_dir:
                    continue
                added = True
                graph.add_node(dependency)
                if config_dir in graph:
                    graph.add_edge(dependency, config_dir)
            if added:
                break  # we only need the closest, the recursion will handle anything higher

    for predecessor in list(graph.predecessors(config_dir)):
        graph_wrapper_dependencies(predecessor, config_dict, graph, visited)


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
            resolved_envvars[envvar_name] = str(envvar_config.value)
        if isinstance(envvar_config, UnsetEnvVarConfig):
            resolved_envvars[envvar_name] = None
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
    repo_path = calc_repo_path(path=path)

    # for backwards compatibility, include the default s3 backend options we used to automatically include
    if existing_backend_config.s3 is not None:
        region = variables.get('region', '')
        account_short_name = variables.get('account_short_name')
        terraform_bucket = f"{region}--mclass--terraform--{account_short_name}"

        options = {
            'dynamodb_table': variables.get('terraform_lock_table', 'terraform-locking'),
            'encrypt': 'true',
            'key': f'{repo_path}.tfstate',
            'region': region,
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
            wrapper_options['prefix'] = repo_path
        if existing_backend_config.s3 is not None and wrapper_config.backends.s3 is not None:
            wrapper_options = vars(wrapper_config.backends.s3)
        options.update({key: value for key, value in wrapper_options.items() if value is not None})

    backend_config.extend([f'-backend-config={key}={value}' for key, value in options.items()])
    return backend_config


def parse_variable_files(variable_files: List[str]) -> Dict[str, str]:
    """
    Convenience function for parsing variable files and returning the variables as a dictionary
    :param variable_files: List of file paths to variable files. Variable files overwrite files before them.
    :return: A dictionary representing the contents of those variable files.
    """
    variables: Dict = {}

    for variable_file in variable_files:
        with open(variable_file, encoding='utf-8') as var_file:
            variables.update(hcl2.load(var_file).items())

    return variables


def parse_backend_config_for_dir(dir_path: str) -> Optional[BackendsConfig]:
    """
    Parse tf files in a directory and try to get the state backend config from the "terraform" resource
    :param dir_path: Directory that has tf files
    :return: Backend config if a "terraform" resource exists, otherwise None
    """
    has_tf_files = False
    for file_path in os.listdir(dir_path):
        if '.terraform' in file_path or not file_path.endswith('.tf'):
            continue

        has_tf_files = True

        result = _parse_backend_config_for_file(
            file_path=os.path.join(dir_path, file_path),
        )
        if result:
            return result

    if not has_tf_files:
        raise NotTerraformConfigDirectory()

    return None


def _parse_backend_config_for_file(file_path: str) -> Optional[BackendsConfig]:
    with open(file_path, encoding='utf-8') as tf_file:
        try:
            configs: Dict[str, List] = hcl2.load(tf_file)

            terraform_config_blocks: List[Dict] = configs.get('terraform', [])
            for terraform_config in terraform_config_blocks:
                if 'backend' in terraform_config:
                    return jsons.load(terraform_config['backend'][0], BackendsConfig, strict=True)
            return None
        except Exception:
            print(f'Error while parsing file {file_path}')
            raise
