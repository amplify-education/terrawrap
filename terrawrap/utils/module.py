"""Utility functions for working with Terraform modules"""
import concurrent.futures
import os
from typing import Set, Tuple

import hcl2
from networkx import DiGraph


def get_module_usage_graph(root_directory: str) -> DiGraph:
    """
    Recursively scan a directory with terraform config files and return what modules are being used
    :param root_directory: Directory to scan
    :return: Graph of module path and lists of directories that depend on each module
    """
    graph = DiGraph()
    future_list = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        # pylint: disable=unused-variable
        for current_dir, dirs, files in os.walk(root_directory, followlinks=True):
            if '.terraform' in current_dir or '.git' in current_dir:
                continue

            for file in files:
                if not file.endswith('.tf'):
                    continue
                future = executor.submit(_get_modules_for_file, current_dir, file)
                future_list.append(future)

        for future in concurrent.futures.as_completed(future_list):
            directory, modules = future.result()
            for mod in modules:
                module_source_path = os.path.normpath(directory + '/' + mod)
                target_path = os.path.normpath(directory)

                if module_source_path not in graph.nodes:
                    graph.add_node(module_source_path)

                if target_path not in graph.nodes:
                    graph.add_node(target_path)

                graph.add_edge(module_source_path, target_path)
    return graph


def _get_modules_for_file(directory: str, file_name: str) -> Tuple[str, Set[str]]:
    """
    Get the modules used in a terraform file
    :param directory: Directory where the file is in
    :param file_name: Name of file
    :return:
    """
    modules = set()
    with open(directory + '/' + file_name, 'r', encoding='utf-8') as file:
        try:
            tf_info = hcl2.load(file)
            for module in tf_info.get('module', []):
                for module_config in module.values():
                    modules.add(os.path.normpath(module_config['source']))
        except Exception:
            print(f'Error while parsing file {file.name}')
            raise

    return directory, modules
