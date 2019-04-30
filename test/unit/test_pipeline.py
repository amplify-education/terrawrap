"""Tests for pipelines"""
from unittest import TestCase

import os

from mock import patch, call

from terrawrap.models.pipeline import Pipeline


class TestPipeline(TestCase):
    """Tests for pipelines"""
    def setUp(self):
        self.prev_dir = os.getcwd()
        os.chdir(os.path.normpath(os.path.dirname(__file__) + '/../helpers/mock_directory'))

    def tearDown(self):
        os.chdir(self.prev_dir)

    @patch('terrawrap.models.pipeline.PipelineEntry')
    def test_execute(self, pipeline_entry_class):
        """Test that executing a pipeline will call init and then the command"""
        pipeline_entry_class.return_value.execute.return_value = (0, ['Success'])

        pipeline = Pipeline('plan', 'pipelines/test.csv')

        pipeline.execute()

        self.assertEqual(
            pipeline_entry_class.return_value.execute.mock_calls,
            [call('init', debug=False), call('plan', debug=False)]
        )
