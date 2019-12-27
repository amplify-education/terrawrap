"""Holds config utilities"""
import os
import re
import subprocess
from typing import Dict, List, Optional
import networkx

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
from terrawrap.utils.path import get_absolute_path
from terrawrap.utils.graph import find_source_nodes

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


def parse_dependencies(directory) -> List:
    """
    Function for parsing the Terraform wrapper config file for dependencies.
    :param wrapper_config_file: A file path to a wrapper config file.
    :return: dependencies - A list of dependencies for the given wrapper config file.
    """
    has_tfwrapper = False
    dependencies = []
    for file_name in os.listdir(directory):
        if file_name.endswith('.tf_wrapper'):
            file_name = os.path.join(directory, file_name)
            wrapper_config_file = file_name
            with open(wrapper_config_file) as wrapper_config_file:
                wrapper_config = yaml.safe_load(wrapper_config_file)
            try:
                if wrapper_config.get("depends_on"):
                    wrapper_dependencies = wrapper_config['depends_on']
                    for path in wrapper_dependencies:
                        path = get_absolute_path(path)
                        dependencies.append(path)
                    return dependencies
            except TypeError:
                return dependencies
    if not has_tfwrapper:
        return dependencies

def get_child_nodes(graph):
    child_nodes = []
    for node in graph:
        successors = list(graph.successors(node))
        if successors:
            continue
        else:
            child_nodes.append(node)
    return child_nodes

def add_to_graph(graph, node, child_nodes):
    graph.add_node(node)
    for child in child_nodes:
        graph.add_edge(child,node)


# def get_dependencies(config_dir):
#     wrapper_files = find_wrapper_config_files(config_dir)
#     outer_graph = networkx.DiGraph()
#     for wrapper_file in wrapper_files:
#         with open(wrapper_file) as wrapper_file:
#             wrapper_config = yaml.safe_load(wrapper_file)
#             config = wrapper_config.get(config_dir) == False
#             depends_on = wrapper_config.get('depends_on')
#             wrapper_dir = os.path.dirname(wrapper_file)
#         try:
#             if config == False and depends_on == None:
#                 continue
#             elif config and depends_on == None:
#                 if os.listdir(wrapper_dir) not in outer_graph.nodes:
#                     add_to_graph(outer_graph,wrapper_dir)
#                 continue
#             elif config == False:
#                 if wrapper_dir in outer_graph:
#                     continue
#                 else:
#                     minigraph = networkx.DiGraph()
#                     smart_parse_depenedencies(wrapper_dir,wrapper_config['dependencies'], outer_graph, minigraph)
#                     sources = find_source_nodes(minigraph)
#                     for source in sources:
#                         add_to_graph(outer_graph, source)


def is_config(directory):
    wrapper_file = os.path.join(directory, ".tf_wrapper")
    with open(wrapper_file) as wrapper_file:
        wrapper_config = yaml.safe_load(wrapper_file)
        try:
            # print("checking config")
            # print(directory)
            # print(wrapper_config.get("config"))
            return wrapper_config.get("config") is None
        except AttributeError:
            return True

def has_depends_on(directory):
    wrapper_file = os.path.join(directory, ".tf_wrapper")
    with open(wrapper_file) as wrapper_file:
        wrapper_config = yaml.safe_load(wrapper_file)
        try:
            # print("checking config")
            # print(directory)
            # print(wrapper_config.get("config"))
            return wrapper_config.get("depends_on") is not None
        except AttributeError:
            return False

def smart_parse_depenedencies(dir,dependencies,  outer_graph, graph):
        if dir not in graph:
            graph.add_node(dir)
        for dependency in dependencies:
            if dependency in outer_graph:
                continue
            if dependency not in graph:
                graph.add_node(dependency)
            if not (graph.has_edge(dependency,dir)):
                graph.add_edge(dependency, dir)
            inner_dependencies = parse_dependencies(dependency)
            if inner_dependencies:
                smart_parse_depenedencies(dependency, inner_dependencies, graph)
def non_recure_dep(dir, outergraph):
    wrapper_files = find_wrapper_config_files(dir)
    for wrapper_file in wrapper_files:
        wrapper_dir = os.path.dirname(wrapper_file)
        child_nodes = get_child_nodes(outergraph)
        try:
            dependencies = parse_dependencies(wrapper_dir)

        except AttributeError:
            dependencies = None
        if dependencies:
            for dependency in dependencies:
                minigraph = networkx.DiGraph()
                # minigraph.add_node(wrapper_dir)
                # minigraph.add_node(dependency)
                # minigraph.add_edge(dependency, wrapper_dir)
                if dependency not in outergraph and not dependency == dir:
                    find_inherited_dependencies(dependency, minigraph)
                    for source in find_source_nodes(minigraph):
                        if source not in outergraph:
                            add_to_graph(outergraph, source, child_nodes)
                    networkx.compose(outergraph, minigraph)
        child_nodes = get_child_nodes(outergraph)

    if is_config(dir):
        if dir not in outergraph:
            add_to_graph(outergraph, dir, child_nodes)

def is_cyclic(graph):
    sources = find_source_nodes(graph)
    if not sources:
        return True

def apply_graph(starting_dir):
    graph_list = []
    for root,dirs,files in os.walk(starting_dir):
        for name in dirs:
            for file in os.listdir(os.path.join(root, name)):
                if file.endswith(".tf_wrapper"):
                    if not is_config(os.path.join(root, name)):
                        continue
                    print("ive found one")
                    print(os.path.join(root, name))
                    sub_graph = networkx.DiGraph()
                    visited = []
                    i_hate_my_life(os.path.join(root, name), sub_graph, visited)
                    print("subgraph")
                    # for node in sub_graph:
                    #     print(node)
                    graph_list.append(sub_graph)
    print("apply_graph")
    print(graph_list)
    apply = networkx.compose_all(graph_list)
    return apply

def find_inherited_dependencies(dir, outergraph):
    wrapper_files = find_wrapper_config_files(dir)
    for wrapper_file in wrapper_files:
        wrapper_dir = os.path.dirname(wrapper_file)
     #   print(wrapper_file)
        child_nodes = get_child_nodes(outergraph)
        try:
            #print("dependencies for %s" % wrapper_dir)
            dependencies = parse_dependencies(wrapper_dir)

        except AttributeError:
            dependencies = None
        if dependencies:
            for dependency in dependencies:
                minigraph = networkx.DiGraph()
                if dependency not in outergraph and not dependency == dir:
                    minigraph = networkx.DiGraph()
                    # minigraph.add_node(wrapper_dir)
                    # minigraph.add_node(dependency)
                    # minigraph.add_edge(dependency, wrapper_dir)
                    find_inherited_dependencies(dependency, minigraph)
                    print(minigraph.nodes)
                    for source in find_source_nodes(minigraph):
                        #print("source")
                        #print(source)
                        if source not in outergraph:
                          #  print("adding node %s", source)
                            add_to_graph(outergraph, source, child_nodes)
                    networkx.compose(outergraph, minigraph)
        child_nodes = get_child_nodes(outergraph)
       # print(child_nodes)

        if is_config(dir):
           # print(dir)
            if dir not in outergraph:
              #  print("adding node %s", wrapper_dir)
                add_to_graph(outergraph, dir, child_nodes)


# def new_way(dir):
#     wrapper_files = find_wrapper_config_files(dir)
#     dep_list = []
#     for wrapper_file in wrapper_files:
#         wrapper_dir = os.path.dirname(wrapper_file)
#         try:
#             #print("dependencies for %s" % wrapper_dir)
#             dependencies = parse_dependencies(wrapper_dir)
#
#         except AttributeError:
#             dependencies = []
#         if dependencies:
#             for dependency in dependencies:
#                 minigraph = networkx.DiGraph()
#                 if dependency not in outergraph and not dependency == dir:
#         if is_config(wrapper_dir):
#             dep_list.append(wrapper_dir)
# def recursive_wrapper_file_dependencies(dir, dependencies, graph):
#     """
#
#     :param wrapperfile:
#     :param dependencies:
#     :param graph:
#     :return:
#     """
#     if dir not in graph:
#         graph.add_node(dir)
#     for dependency in dependencies:
#         if dependency not in graph:
#             graph.add_node(dependency)
#         if not (graph.has_edge(dependency,dir)):
#             graph.add_edge(dependency, dir)
#         inner_dependencies = parse_dependencies(dependency)
#         if inner_dependencies:
#             recursive_wrapper_file_dependencies(dependency, inner_dependencies, graph)

def i_hate_my_life(dir, graph, visited):
    print("calling on dir", dir)
    if dir in visited:
        return
    visited.append(dir)
    if dir not in graph and is_config(dir):
        graph.add_node(dir)
    #    print("this is config", dir)
    try:
        tf_dependencies = parse_dependencies(dir)
    except AttributeError:
        tf_dependencies = []
    for dep in tf_dependencies:
        if dep not in graph and is_config(dep):
        #    print("this is config tf dep", dep)
            graph.add_node(dep)
        if dir in graph and not graph.has_edge(dep,dir):
            graph.add_edge(dep, dir)
       #     print(" Adding edge from dep", dep, " to ", dir)
    wrappers = find_wrapper_config_files(dir)
    wrappers.reverse()
    for wrapper in wrappers:
        wrapper_dir = os.path.dirname(wrapper)
        if wrapper_dir == dir:
            continue
        if has_depends_on(wrapper_dir):
        #    print(wrapper_dir, " should not = ", dir)
            closest_inheritance = wrapper_dir
            inherit_deps = parse_dependencies(closest_inheritance)
            for dep in inherit_deps:
                if dep == dir:
                    continue
                if dep not in graph and is_config(dep):
             #       print("this is config inherit dep", dep)
                    graph.add_node(dep)
                if dir in graph and not graph.has_edge(dep,dir):
                    graph.add_edge(dep, dir)
              #      print(" Adding edge from", dep, " to ", dir)
            break
    for pred in list(graph.predecessors(dir)):
        i_hate_my_life(pred, graph, visited)

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

    output = subprocess.check_output(["git", "remote", "show", "origin", "-n"], cwd=path).decode("utf-8")
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
