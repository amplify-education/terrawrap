"""Test collection utilities"""

from unittest import TestCase

from terrawrap.utils.collection_utils import update


class TestUpdate(TestCase):
    """Test the update merge utility."""

    def test_scalar_replaced_by_child_list(self):
        """Defensive branch: parent has a scalar for a key the child declares as a list (non-replace key)."""
        result = update({"tags": "old_scalar"}, {"tags": ["new", "values"]})
        self.assertEqual(result, {"tags": ["new", "values"]})
