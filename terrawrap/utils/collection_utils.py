"""Utilities for working with collections"""
from typing import Dict

# Leaf list fields that should use child-wins replacement instead of additive
# union when merging .tf_wrapper files. Both spellings of the SSM envvar
# fallback list (`path` and `paths`) qualify — extending either would
# silently bleed parent paths into a child's resolution order.
_REPLACE_LIST_KEYS = frozenset({"path", "paths"})


def update(dict1: Dict, dict2: Dict) -> Dict:
    """
    Recursively updates the first provided dictionary with the keys and values from the second dictionary.
    Child dictionaries are merged; lists are appended except for keys in _REPLACE_LIST_KEYS.
    :param dict1: The dictionary to merge into.
    :param dict2: The dictionary to merge.
    :return: A merged dictionary.
    """
    for key, value in dict2.items():
        if isinstance(value, dict):
            dict1[key] = update(dict1.get(key, {}), value)
        elif isinstance(value, list):
            if key in _REPLACE_LIST_KEYS:
                dict1[key] = list(value)
            else:
                original_value = dict1.get(key, [])
                if not isinstance(original_value, list):
                    original_value = []
                original_value.extend(value)
                dict1[key] = original_value
        else:
            dict1[key] = value
    return dict1
