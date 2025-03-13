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
import hcl2
import pytest
from botocore.exceptions import ClientError

from terrawrap.models.config_mover import ConfigMover


class TestConfigMover(TestCase):
    """Tests for ConfigMover"""

    _base_path = (Path(__file__) / "../../helpers").resolve() / "mock_config_mover"
    _mocks_path = _base_path / "mocks"
    _repo_root_path = _base_path / "terraform-config"
    _config_path = _repo_root_path / "config"
    _default_source = _config_path / "aws" / "default_source"
    _default_target = _config_path / "aws" / "default_target"

    @staticmethod
    def _read_hcl2_modules(hcl2_content: str):
        config = hcl2.loads(hcl2_content)
        result = {}
        modules = config.get("module", [])
        for module in modules:
            result[list(module.keys())[0]] = list(module.values())[0]
        return result

    @classmethod
    def config_mover(
        cls,
        source: Path = _default_source,
        target: Path = _default_target,
    ) -> ConfigMover:
        return ConfigMover(source, target)

    def setUp(self):
        self._default_source.mkdir(parents=True, exist_ok=True)
        self._default_target.mkdir(parents=True, exist_ok=True)
        self.prev_dir = Path(os.getcwd()).absolute()
        os.chdir(self._repo_root_path)

    def tearDown(self):
        shutil.rmtree(self._config_path, ignore_errors=True)
        os.chdir(self.prev_dir)

    @patch("terrawrap.models.config_mover.find_variable_files")
    def test__find_variable_files(self, find_variable_files_mock: MagicMock):
        config_mover = self.config_mover()
        actual = find_variable_files_mock.return_value = MagicMock()

        expected = config_mover._find_variable_files(self._default_source)

        find_variable_files_mock.assert_called_once_with(str(self._default_source))
        assert actual == expected

    def test__build_state_file_s3_key(self):
        paths = {
            self._default_source
            / "app1": "terrawrap/config/aws/default_source/app1.tfstate",
            self._default_source
            / "apps"
            / "app2": "terrawrap/config/aws/default_source/apps/app2.tfstate",
        }

        for path, expected in paths.items():
            path.mkdir(parents=True)
            actual = self.config_mover()._build_state_file_s3_key(path)
            assert actual == expected

    def test_read_repo(self):
        cwd = os.getcwd()

        os.chdir(self._config_path)
        expected_repo = git.Repo.init(self._config_path)
        config_mover = self.config_mover()
        assert config_mover.repo == expected_repo

        # test that the repo can be found from subdirectories
        os.chdir(self._default_source)
        expected_repo = git.Repo.init(self._config_path)
        config_mover = self.config_mover()
        assert config_mover.repo == expected_repo

        os.chdir(cwd)

    @patch("terrawrap.models.config_mover.ConfigMover.s3_client")
    @patch("terrawrap.models.config_mover.ConfigMover._find_auto_variable")
    @patch("terrawrap.utils.path.re")
    def test__move_state_file_object(
        self,
        re_mock: MagicMock,
        _find_auto_variable_mock: MagicMock,
        s3_mock: MagicMock,
    ):
        re_search_mock = re_mock.search.return_value = MagicMock()
        re_search_mock.group.return_value = "terraform-config"
        expected_source_key = "terraform-config/config/aws/default_source.tfstate"
        expected_bucket = _find_auto_variable_mock.return_value = "state-bucket"
        expected_target_key = "terraform-config/config/aws/default_target.tfstate"

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
                "Key": expected_source_key,
            },
            Bucket=expected_bucket,
            Key=expected_target_key,
        )
        s3_mock.delete_object.assert_called_once_with(
            Bucket=expected_bucket,
            Key=expected_source_key,
        )

        # non-existent state file case
        s3_mock.copy.side_effect = ClientError({"Error": {"Code": "404"}}, "")
        with pytest.raises(RuntimeError):
            config_mover._move_state_file_object()

        # unexpected cases
        s3_mock.copy.side_effect = ClientError({"Error": {"Code": "403"}}, "")
        with pytest.raises(ClientError):
            config_mover._move_state_file_object()

    def test__move_files_same_depth(self):
        # case where source and target are on the same depth in dir tree
        tf_file_name = "backend.tf"

        source_file = self._default_source / tf_file_name
        source_file.touch()
        expected_target_file = self._default_target / tf_file_name
        config_mover = self.config_mover()
        config_mover.repo.index.add(source_file)
        config_mover._move_files([source_file])
        assert expected_target_file.exists()

    def test__move_files_exclude_subdirs(self):
        # case where source directory contains .tf files and subdirectories
        tf_file_name = "backend.tf"

        source_file = self._default_source / tf_file_name
        source_file.touch()
        subdirectory = self._default_source / "subdir"
        subdirectory.mkdir()
        expected_target_file = self._default_target / tf_file_name
        unexpected_target_directory = self._default_target / subdirectory.name
        config_mover = self.config_mover()
        config_mover.repo.index.add(source_file)
        config_mover._move_files([source_file])
        assert expected_target_file.exists()
        assert not unexpected_target_directory.exists()

    def test__move_files_different_depth(self):
        # case where target is on different depth
        tf_file_name = "backend.tf"

        source_file = self._default_source / tf_file_name
        source_file.touch()
        expected_target = self._default_target / "app"
        expected_target_file = expected_target / tf_file_name

        config_mover = self.config_mover(target=expected_target)
        config_mover.repo.index.add(source_file)
        config_mover._move_files([source_file])

        assert expected_target_file.exists()

    def test__move_files_different_depth_2(self):
        # case where target is on different depth
        tf_file_name = "backend.tf"

        source_file = self._default_source / tf_file_name
        source_file.touch()
        expected_target = self._default_target / ".."
        expected_target_file = expected_target / tf_file_name

        config_mover = self.config_mover(target=expected_target)
        config_mover.repo.index.add(source_file)
        config_mover._move_files([source_file])

        assert expected_target_file.exists()

    def test__verify_source_directory(self):
        directory = self._default_source / uuid.uuid4().hex
        subdirectory = directory / "subdirectory"

        config_mover = self.config_mover(source=directory)

        with pytest.raises(RuntimeError) as exc:
            config_mover._verify_source_directory()
        assert "does not exist" in str(exc.value)

        subdirectory.mkdir(parents=True)
        with pytest.raises(RuntimeError) as exc:
            config_mover._verify_source_directory()
        assert "No terraform configuration files (*.tf) found in" in str(exc.value)

        file_1 = directory / "buildspec.yml"
        file_2 = directory / "app.auto.tfvars"
        file_3 = directory / "variables.tf"
        file_4 = directory / "backend.tf"
        file_5 = subdirectory / "backend.tf"

        file_1.touch()
        file_2.touch()
        file_5.touch()

        with pytest.raises(RuntimeError) as exc:
            config_mover._verify_source_directory()
        assert "No terraform configuration files (*.tf) found in" in str(exc.value)

        file_3.touch()
        file_4.touch()

        result = config_mover._verify_source_directory()
        assert result == [file_2, file_4, file_1, file_3]

    def test__verify_target_directory(self):
        directory = self._default_target / uuid.uuid4().hex

        config_mover = self.config_mover(target=directory)

        # target dir does not exist - ok
        config_mover._verify_target_directory()

        # target dir is not empty - not ok
        (directory / "test").mkdir()
        with pytest.raises(RuntimeError):
            config_mover._verify_target_directory()

    def test__verify_environment(self):
        def _set(file, _bucket, _env=None):
            text = f'terraform_state_bucket = "{_bucket}"'
            if _env is not None:
                text += f'\nenvironment = "{_env}"'
            file.write_text(text)

        expected_error_message = "Source and target directories must be in the same AWS account / environment"

        source_vars = self._default_source / "source.auto.tfvars"
        source_vars.touch()
        target_vars = self._default_target / "target.auto.tfvars"
        target_vars.touch()

        _set(source_vars, "state_bucket_1")
        _set(target_vars, "state_bucket_1")
        self.config_mover()._verify_environment()

        _set(source_vars, "state_bucket_1", "env_1")
        _set(target_vars, "state_bucket_1", "env_1")
        self.config_mover()._verify_environment()

        _set(source_vars, "state_bucket_1")
        _set(target_vars, "state_bucket_2")
        with pytest.raises(RuntimeError) as exc:
            self.config_mover()._verify_environment()
        assert expected_error_message in str(exc.value)

        _set(source_vars, "state_bucket_1", "env_1")
        _set(target_vars, "state_bucket_1")
        with pytest.raises(RuntimeError) as exc:
            self.config_mover()._verify_environment()
        assert expected_error_message in str(exc.value)

        _set(source_vars, "state_bucket_1", "env_1")
        _set(target_vars, "state_bucket_2", "env_1")
        with pytest.raises(RuntimeError) as exc:
            self.config_mover()._verify_environment()
        assert expected_error_message in str(exc.value)

        _set(source_vars, "state_bucket_1", "env_1")
        _set(target_vars, "state_bucket_1", "env_2")
        with pytest.raises(RuntimeError) as exc:
            self.config_mover()._verify_environment()
        assert expected_error_message in str(exc.value)

    def test__adjust_modules_sources(self):
        test_cases = [
            {
                "target_directory": self._default_source,
                "expected_outcome": {
                    "config1.tf": {},
                    "config2.tf": {
                        "module_instance_1": "../../../../../modules/aws/docker_application/v4",
                        "module_instance_2": "modules/custom_pipeline_module",
                    },
                    "config3.tf": {
                        "module_instance_1": "../../../modules/aws/s3_bucket/v3",
                        "module_instance_2": "../modules/custom_website_module",
                    },
                },
            },
            {
                "target_directory": self._default_target,
                "expected_outcome": {
                    "config1.tf": {},
                    "config2.tf": {
                        "module_instance_1": "../../../../../modules/aws/docker_application/v4",
                        "module_instance_2": "../default_source/modules/custom_pipeline_module",
                    },
                    "config3.tf": {
                        "module_instance_1": "../../../modules/aws/s3_bucket/v3",
                        "module_instance_2": "../modules/custom_website_module",
                    },
                },
            },
            {
                "target_directory": self._default_target / "directory1" / "directory2",
                "expected_outcome": {
                    "config1.tf": {},
                    "config2.tf": {
                        "module_instance_1": "../../../../../../../modules/aws/docker_application/v4",
                        "module_instance_2": "../../../default_source/modules/custom_pipeline_module",
                    },
                    "config3.tf": {
                        "module_instance_1": "../../../../../modules/aws/s3_bucket/v3",
                        "module_instance_2": "../../../modules/custom_website_module",
                    },
                },
            },
            {
                "target_directory": self._default_target.parent,
                "expected_outcome": {
                    "config1.tf": {},
                    "config2.tf": {
                        "module_instance_1": "../../../../modules/aws/docker_application/v4",
                        "module_instance_2": "default_source/modules/custom_pipeline_module",
                    },
                    "config3.tf": {
                        "module_instance_1": "../../modules/aws/s3_bucket/v3",
                        "module_instance_2": "modules/custom_website_module",
                    },
                },
            },
        ]

        mock_files = ["config1.tf", "config2.tf", "config3.tf"]

        for test_case in test_cases:

            for mock_file in mock_files:
                test_file = self._default_source / mock_file
                test_file.unlink(missing_ok=True)
                shutil.copy(self._mocks_path / mock_file, test_file)

            config_mover = self.config_mover(target=test_case["target_directory"])

            for file in mock_files:
                path = self._default_source / file

                # process tf file
                config_mover._adjust_modules_sources([path])

                # read tf file content
                actual_modules = self._read_hcl2_modules(path.read_text())

                for module_name, module_block in actual_modules.items():
                    expected_source = test_case["expected_outcome"][file][module_name]
                    assert expected_source == module_block["source"]

    def test__diff_autovars(self):
        base_auto_tfvars = self._config_path / "base.auto.tfvars"
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
