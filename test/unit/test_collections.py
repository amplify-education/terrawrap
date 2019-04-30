"""Test collections utils"""
from unittest import TestCase

from terrawrap.utils.collection_utils import flatten_collection, pick_dict_values_by_substring


class TestCollections(TestCase):
    """Test collections utils"""
    def test_flatten_collection(self):
        """Test flattening a list of lists to a list"""
        actual = flatten_collection([[1, 2, 3], [4, 5]])
        self.assertEqual(actual, [1, 2, 3, 4, 5])

    def test_pick_dict_values_by_substring(self):
        """test finding all values whose keys are substrings of a list of terms"""
        actual = pick_dict_values_by_substring(['foo_some_text', 'bar'], {
            'foo': 1,
            'bar': 2,
            'baz': 3
        })

        self.assertEqual(set(actual), {1, 2})
