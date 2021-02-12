"""Utilities for working with collections"""
from typing import TypeVar, Dict

Type = TypeVar('Type')


def update(dict1: Dict, dict2: Dict) -> Dict:
    """
    Recursively updates the first provided dictionary with the keys and values from the second dictionary.
    Child dictionary and lists are merged, not replaced.
    :param dict1: The dictionary to merge into.
    :param dict2: The dictionary to merge.
    :return: A merged dictionary.
    """
    for key, value in dict2.items():
        if isinstance(value, dict):
            dict1[key] = update(dict1.get(key, {}), value)
        elif isinstance(value, list):
            original_value = dict1.get(key, [])
            original_value.extend(value)
            dict1[key] = original_value
        else:
            dict1[key] = value
    return dict1
