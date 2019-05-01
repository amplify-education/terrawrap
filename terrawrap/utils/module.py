"""Utility functions for working with Terraform modules"""
from collections import defaultdict
from typing import Dict, Set, Tuple
import concurrent.futures

import os
import hcl


def get_module_usage_map(root_directory: str) -> Dict[str, Set[str]]:
    """
    Recursively scan a directory with terraform config files and return what modules are being used
    :param root_directory: Directory to scan
    :return: Map of module path to list of directories that depend on each module
    """
    module_map = defaultdict(set)
    future_list = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        # pylint: disable=unused-variable
        for current_dir, dirs, files in os.walk(root_directory, followlinks=True):
            if '.terraform' in current_dir:
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
                module_map[module_source_path].add(os.path.normpath(directory))

    return dict(module_map)


def _get_modules_for_file(directory: str, file_name: str) -> Tuple[str, Set[str]]:
    """
    Get the modules used in a terraform file
    :param directory: Directory where the file is in
    :param file_name: Name of file
    :return:
    """
    modules = set()
    with open(directory + '/' + file_name, 'r') as file:
        tf_info = hcl.load(file)
        for module_config in tf_info.get('module', {}).values():
            modules.add(os.path.normpath(module_config['source']))

    return directory, modules
