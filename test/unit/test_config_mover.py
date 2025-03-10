# pylint:disable=C0114,C0116

import contextlib
import io
import shutil
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, MagicMock

import os

import git
import pytest
from botocore.exceptions import ClientError

from terrawrap.models.config_mover import ConfigMover


class TestConfigMover(TestCase):
    """Tests for ConfigMover"""

    _base_mock_path = (
        Path(os.path.normpath(os.path.dirname(__file__)))
        / "config-mover-mocks"
        / "terraform-config"
    )
    _default_source = _base_mock_path / "aws" / "default_source"
    _default_target = _base_mock_path / "aws" / "default_target"

    @classmethod
    def config_mover(
        cls, source: Path = _default_source, target: Path = _default_target
    ) -> ConfigMover:
        return ConfigMover(source, target)

    def setUp(self):
        self._default_source.mkdir(parents=True, exist_ok=True)
        self._default_target.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self._base_mock_path, ignore_errors=True)
        ConfigMover._find_variable_files.cache_clear()

    @patch("terrawrap.models.config_mover.find_variable_files")
    def test__find_variable_files(self, find_variable_files_mock: MagicMock):
        actual = find_variable_files_mock.return_value = MagicMock()

        expected = ConfigMover._find_variable_files(self._default_source)

        find_variable_files_mock.assert_called_once_with(str(self._default_source))
        assert actual == expected

    def test__to_repo_root_path(self):
        paths = {
            Path("/root/terraform-config/config/dir1/"): Path("config/dir1"),
            "/root/terraform-config/config/dir2": Path("config/dir2"),
            "/terraform-config/config/dir3": Path("config/dir3"),
            "terraform-config/config/dir4": Path("config/dir4"),
        }

        for path, expected in paths.items():
            actual = ConfigMover._to_repo_root_path(path)
            assert actual == expected

    def test__build_state_file_s3_key(self):
        paths = {
            Path(
                "/root/terraform-config/config/dir1/"
            ): "terraform-config/config/dir1.tfstate",
            "/root/terraform-config/config/dir1/": "terraform-config/config/dir1.tfstate",
            "/terraform-config/config/dir2": "terraform-config/config/dir2.tfstate",
            "terraform-config/config/dir3": "terraform-config/config/dir3.tfstate",
        }

        for path, expected in paths.items():
            actual = ConfigMover._build_state_file_s3_key(path)
            assert actual == expected

    def test_read_repo(self):
        cwd = os.getcwd()

        os.chdir(self._base_mock_path)
        expected_repo = git.Repo.init(self._base_mock_path)
        config_mover = self.config_mover()
        assert config_mover.repo == expected_repo

        # test that the repo can be found from subdirectories
        os.chdir(self._default_source)
        expected_repo = git.Repo.init(self._base_mock_path)
        config_mover = self.config_mover()
        assert config_mover.repo == expected_repo

        os.chdir(cwd)

    def test__find_state_bucket(self):
        expected_bucket = "amplify-devops-uw2-terraform"

        auto_tfvars = self._base_mock_path / "mock.auto.tfvars"
        auto_tfvars.touch()
        auto_tfvars.write_text(f'terraform_state_bucket = "{expected_bucket}"')

        config_mover = self.config_mover()
        actual_bucket = config_mover._find_state_bucket()
        assert expected_bucket == actual_bucket

    @patch("terrawrap.models.config_mover.ConfigMover.s3_client")
    @patch("terrawrap.models.config_mover.ConfigMover._find_state_bucket")
    def test__move_state_file_object(
        self, _find_state_bucket_mock: MagicMock, s3_mock: MagicMock
    ):
        expected_source = "terraform-config/aws/default_source.tfstate"
        expected_bucket = _find_state_bucket_mock.return_value = "state-bucket"
        expected_target_key = "terraform-config/aws/default_target.tfstate"

        config_mover = self.config_mover()

        # target state file exists case
        s3_mock.head_object.side_effect = MagicMock()
        with pytest.raises(RuntimeError):
            config_mover._move_state_file_object()

        # happy path
        s3_mock.reset_mock()
        s3_mock.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "")
        config_mover._move_state_file_object()
        s3_mock.head_object.assert_called_once_with(
            Bucket=expected_bucket,
            Key=expected_target_key,
        )
        s3_mock.copy.assert_called_once_with(
            CopySource={
                "Bucket": expected_bucket,
                "Key": expected_source,
            },
            Bucket=expected_bucket,
            Key=expected_target_key,
        )

        # non-existent state file case
        s3_mock.copy.side_effect = ClientError({"Error": {"Code": "404"}}, "")
        with pytest.raises(RuntimeError):
            config_mover._move_state_file_object()

        # unexpected cases
        s3_mock.copy.side_effect = ClientError({"Error": {"Code": "403"}}, "")
        with pytest.raises(ClientError):
            config_mover._move_state_file_object()

    # def test__move_files_same_depth(self):
    #     # case where source and target are on the same depth in dir tree
    #     tf_file_name = "backend.tf"
    #
    #     source_file = self._default_source / tf_file_name
    #     source_file.touch()
    #     expected_target_file = self._default_target / tf_file_name
    #     config_mover = self.config_mover()
    #     config_mover.repo.index.add(source_file)
    #     config_mover._move_files()
    #     assert expected_target_file.exists()
    #
    # def test__move_files_exclude_subdirs(self):
    #     # case where source directory contains .tf files and subdirectories
    #     tf_file_name = "backend.tf"
    #
    #     source_file = self._default_source / tf_file_name
    #     source_file.touch()
    #     subdirectory = self._default_source / "subdir"
    #     subdirectory.mkdir()
    #     expected_target_file = self._default_target / tf_file_name
    #     unexpected_target_directory = self._default_target / subdirectory.name
    #     config_mover = self.config_mover()
    #     config_mover.repo.index.add(source_file)
    #     config_mover._move_files()
    #     assert expected_target_file.exists()
    #     assert not unexpected_target_directory.exists()
    #
    # def test__move_files_different_depth(self):
    #     # case where target is on different depth
    #     tf_file_name = "backend.tf"
    #
    #     source_file = self._default_source / tf_file_name
    #     source_file.touch()
    #     expected_target = self._default_target / "app"
    #     expected_target_file = expected_target / tf_file_name
    #
    #     config_mover = self.config_mover(target=expected_target)
    #     config_mover.repo.index.add(source_file)
    #     config_mover._move_files()
    #
    #     assert expected_target_file.exists()
    #
    # def test__move_files_different_depth_2(self):
    #     # case where target is on different depth
    #     tf_file_name = "backend.tf"
    #
    #     source_file = self._default_source / tf_file_name
    #     source_file.touch()
    #     expected_target = self._default_target / ".."
    #     expected_target_file = expected_target / tf_file_name
    #
    #     config_mover = self.config_mover(target=expected_target)
    #     config_mover.repo.index.add(source_file)
    #     config_mover._move_files()
    #
    #     assert expected_target_file.exists()

    def test__verify_source_directory(self):
        directory = self._default_source / uuid.uuid4().hex

        config_mover = self.config_mover(source=directory)

        with pytest.raises(RuntimeError):
            config_mover._verify_source_directory()

        directory.mkdir()
        config_mover._verify_source_directory()

    def test__verify_target_directory(self):
        directory = self._default_target / uuid.uuid4().hex

        config_mover = self.config_mover(target=directory)

        # target dir does not exist - ok
        config_mover._verify_target_directory()

        # target dir is not empty - not ok
        (directory / "test").mkdir()
        with pytest.raises(RuntimeError):
            config_mover._verify_target_directory()

    def test__diff_autovars(self):
        base_auto_tfvars = self._base_mock_path / "base.auto.tfvars"
        source_auto_tfvars = self._default_source / "source.auto.tfvars"

        directory = self._default_source / "directory"

        base_auto_tfvars.touch()
        source_auto_tfvars.touch()

        config_mover = self.config_mover(source=directory)

        # assert that the warning message about missing auto.tfvars files was printed out
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            config_mover._diff_autovars()
        assert source_auto_tfvars.name in out.getvalue()
