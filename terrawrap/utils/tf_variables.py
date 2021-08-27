"""Utilities for working with Terraform variables"""
import concurrent.futures
import os
from collections import defaultdict, namedtuple
from typing import Dict, Set, Tuple, Union

import hcl2
from lark import Token
from networkx import DiGraph

Variable = namedtuple('Variable', ['name', 'value'])


def get_auto_vars(root_directory: str) -> Dict[str, Set[Variable]]:
    """
    Recursively scan a directory and find all variables that are being exposed via tfvars files
    :param root_directory: directory where to start search
    :return:
    """
    auto_vars: Dict[str, Set[Variable]] = defaultdict(set)
    # pylint: disable=unused-variable
    for current_dir, dirs, files in os.walk(root_directory, followlinks=True):
        if '.terraform' in current_dir:
            continue

        vars_files = [file_name for file_name in files if file_name.endswith('.tfvars')]
        for file_name in vars_files:
            with open(current_dir + '/' + file_name, 'r', encoding='utf-8') as file:
                variables = hcl2.load(file)
                for key, value in variables.items():
                    auto_vars[os.path.join(current_dir, file_name)].add(Variable(key, _make_hashable(value)))

    return dict(auto_vars)


def _make_hashable(input_value):
    if isinstance(input_value, list):
        return tuple(_make_hashable(item) for item in input_value)
    if isinstance(input_value, dict):
        return tuple((_make_hashable(key), _make_hashable(value)) for key, value in input_value.items())
    if isinstance(input_value, Token):
        return str(input_value)
    return input_value


def get_nondefault_variables_for_file(file_path: str) -> Set[str]:
    """
    Find all variables missing default values that are declared in a terraform file
    :param file_path: a terraform file
    :return: Set of variable names declared in the file
    """
    variables = set()
    with open(file_path, 'r', encoding='utf-8') as file:
        tf_info = hcl2.load(file)
        for variable in tf_info.get('variable', []):
            for variable_name, var_config in variable.items():
                if not var_config.get('default'):
                    variables.add(variable_name)

    return variables


def get_source_for_variable(usage_directory: str, var_name: str, vars_map: Dict[str, Set[Variable]]) \
        -> Union[None, str]:
    """
    Find which auto tfvars file terraform will use to get a variable value from
    :param usage_directory: A directory with terraform config that's using a variable
    :param var_name: Name of a variable that needs to get a value via auto tfvars
    :param vars_map: Dict of tfvars files and the vars they provided returned by `get_auto_vars`
    :return: file path of tfvars file with the value for the variable
    """
    # find which var files have the var we want and are in a directory above the one we are in
    possible_sources = [
        file
        for file, var_info in vars_map.items()
        if any(var[0] == var_name for var in var_info) and usage_directory.startswith(os.path.dirname(file))
    ]

    if not possible_sources:
        return None

    # sort the list by how deeply nested it is
    possible_sources = sorted(possible_sources, key=lambda s: len(s.split('/')))

    # the most deeply nested one is the one closest to where we are using the variable
    # which is the one that would get used
    return possible_sources[-1]


def get_auto_var_usage_graph(root_directory: str) -> DiGraph:
    """
    Recursively scan a directory to build a graph of auto tfvars files and the directories
    that depend on them
    :param root_directory: directory where to start the search
    :return:
    """
    graph = DiGraph()
    auto_vars = get_auto_vars(root_directory)

    future_list = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        # pylint: disable=unused-variable
        for current_dir, dirs, files in os.walk(root_directory, followlinks=True):
            if '.terraform' in current_dir or '.git' in current_dir:
                continue

            for file in files:
                if not file.endswith('.tf'):
                    continue

                future = executor.submit(_collect_variable_usages, current_dir, file, auto_vars)
                future_list.append(future)

        for future in concurrent.futures.as_completed(future_list):
            directory, var_sources = future.result()
            for var_source in var_sources:

                if var_source not in graph.nodes:
                    graph.add_node(var_source)

                if directory not in graph.nodes:
                    graph.add_node(directory)

                graph.add_edge(var_source, directory)

    return graph


def _collect_variable_usages(current_dir: str, file: str, auto_vars: Dict[str, Set[Variable]]) \
        -> Tuple[str, Set[str]]:
    var_sources = set()
    for variable in get_nondefault_variables_for_file(os.path.join(current_dir, file)):
        var_source = get_source_for_variable(current_dir, variable, auto_vars)
        if var_source:
            var_sources.add(var_source)
    return current_dir, var_sources
