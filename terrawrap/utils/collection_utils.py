"""Utilities for working with collections"""
from typing import List, Iterable, Mapping, TypeVar, Dict

Type = TypeVar('Type')


def flatten_collection(lists: Iterable[Iterable[Type]]) -> List[Type]:
    """
    Flatten a collection of collections into a list
    :param lists:
    :return:
    """
    return [
        item
        for sublist in lists
        for item in sublist
    ]


def pick_dict_values_by_substring(search_terms: Iterable[str], dictionary: Mapping[str, Type]) \
        -> Iterable[Type]:
    """
    Get list of dictionary values with keys that are substrings of a list of search terms
    :param search_terms: search terms
    :param dictionary:
    :return:
    """
    return [
        value for key, value in dictionary.items()
        if any(search_term.startswith(key) for search_term in search_terms)
    ]


def update(dict1: Dict, dict2: Dict) -> Dict:
    """
    Recursively updates the first provided dictionary with the keys and values from the second dictionary.
    Child dictionary and lists are merged, not replaced.
    :param dict1: The dictionary to merge into.
    :param dict2: The dictionary to merge.
    :return: A merged dictionary.
    """
    for key, value in dict2.items():
        if isinstance(value, Dict):
            dict1[key] = update(dict1.get(key, {}), value)
        elif isinstance(value, List):
            original_value = dict1.get(key, [])
            original_value.extend(value)
            dict1[key] = original_value
        else:
            dict1[key] = value
    return dict1
