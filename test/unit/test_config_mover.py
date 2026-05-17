# pylint:disable=C0114,C0116

import contextlib
import io
import json
import shutil
import sys
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, MagicMock

import os

import git
import hcl2
import pytest
import yaml
from botocore.exceptions import ClientError

from terrawrap.models.config_mover import BatchConfigMover, ConfigMover


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
        shutil.rmtree(self._repo_root_path, ignore_errors=True)
        os.chdir(self.prev_dir)

    @patch("terrawrap.models.config_mover.find_variable_files")
    def test__find_variable_files(self, find_variable_files_mock: MagicMock):
        config_mover = self.config_mover()
        actual = find_variable_files_mock.return_value = MagicMock()

        expected = config_mover._find_variable_files(self._default_source)

        find_variable_files_mock.assert_called_once_with(str(self._default_source))
        assert actual == expected

    @patch("terrawrap.utils.path.subprocess.check_output")
    def test__build_state_file_s3_key(self, check_output_mock: MagicMock):
        paths = [
            Path("terraform-config") / "config" / "apps" / "app2",
            Path("tfc") / "config" / "apps" / "app2",
        ]

        expected_s3_key = "terraform-config/config/apps/app2.tfstate"
        check_output_mock.return_value = (
            b"https://github.com/amplify-education/terraform-config.git"
        )
        for path in paths:
            actual = self.config_mover()._build_state_file_s3_key(path)
            assert actual == expected_s3_key

        expected_s3_key = "tfc/config/apps/app2.tfstate"
        check_output_mock.return_value = b"https://github.com/amplify-education/tfc.git"
        for path in paths:
            actual = self.config_mover()._build_state_file_s3_key(path)
            assert actual == expected_s3_key

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

    @patch("terrawrap.utils.path.subprocess.check_output")
    def test__verify_source_directory(self, check_output_mock: MagicMock):
        directory = self._default_source / uuid.uuid4().hex
        subdirectory = directory / "subdirectory"

        check_output_mock.return_value = (
            b"https://github.com/amplify-education/terraform-config.git"
        )

        git.Repo.init(self._repo_root_path)
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
        file_5 = directory / ".terraform.lock.hcl"
        file_6 = subdirectory / "backend.tf"

        file_1.touch()
        file_2.touch()
        file_5.touch()
        file_6.touch()
        config_mover.repo.index.add([file_1, file_2, file_6])
        with pytest.raises(RuntimeError) as exc:
            config_mover._verify_source_directory()
        assert "No terraform configuration files (*.tf) found in" in str(exc.value)

        file_3.touch()
        file_4.touch()
        config_mover.repo.index.add([file_3, file_4])
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


_MAIN_TF = 'module "m" {\n' '  source = "./sub"\n' '  foo = "bar"\n' "}\n"


class TestBatchConfigMover(TestCase):
    """Integration tests for BatchConfigMover. Exercises run() end-to-end against a real
    temp git repo + real filesystem, with only the S3 client mocked."""

    _base_path = (Path(__file__) / "../../helpers").resolve() / "mock_config_mover"
    _repo_root_path = _base_path / "terraform-config"
    _config_path = _repo_root_path / "config"
    _aws_path = _config_path / "aws"

    def setUp(self):
        self._aws_path.mkdir(parents=True, exist_ok=True)

        # shared bucket declaration at aws/ level; inherited by sources and targets
        (self._aws_path / "base.auto.tfvars").write_text(
            'terraform_state_bucket = "test-bucket"\n'
        )

        self.sources = {}
        self.targets = {}
        for name in ("a", "b", "c"):
            src = self._aws_path / f"src_{name}"
            tgt = self._aws_path / f"tgt_{name}"
            src.mkdir(parents=True, exist_ok=True)
            (src / "main.tf").write_text(_MAIN_TF)
            self.sources[name] = src
            self.targets[name] = tgt

        self.repo = git.Repo.init(self._repo_root_path)
        self.repo.create_remote(
            "origin", "https://github.com/amplify-education/terraform-config.git"
        )
        self.repo.git.add("--all")
        self.repo.index.commit("initial")

        self.prev_dir = Path(os.getcwd()).absolute()
        os.chdir(self._repo_root_path)

    def tearDown(self):
        os.chdir(self.prev_dir)
        shutil.rmtree(self._repo_root_path, ignore_errors=True)

    def _manifest_path(self, entries, fmt="yaml", filename="manifest"):
        path = self._base_path / f"{filename}.{fmt}"
        if fmt == "json":
            path.write_text(json.dumps(entries))
        else:
            path.write_text(yaml.safe_dump(entries))
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return str(path)

    def _s3_mock(self, copy_side_effect=None):
        """Build an S3 mock that 404s on head_object and records copy/delete calls."""
        mock = MagicMock()
        mock.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )
        if copy_side_effect is not None:
            mock.copy.side_effect = copy_side_effect
        return mock

    # ---- happy path & dry run --------------------------------------------------------

    @patch(
        "terrawrap.models.config_mover.ConfigMover.s3_client", new_callable=MagicMock
    )
    def test_happy_path_all_items_succeed(self, s3_mock: MagicMock):
        s3_mock.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )

        manifest = self._manifest_path(
            [
                {"source": str(self.sources["a"]), "target": str(self.targets["a"])},
                {"source": str(self.sources["b"]), "target": str(self.targets["b"])},
            ]
        )
        batch = BatchConfigMover(manifest)
        exit_code = batch.run(skip_confirmation=True)

        assert exit_code == 0
        assert not self.sources["a"].exists() or not any(self.sources["a"].iterdir())
        assert (self.targets["a"] / "main.tf").exists()
        assert (self.targets["b"] / "main.tf").exists()
        assert s3_mock.copy.call_count == 2
        assert len(batch.succeeded) == 2
        assert batch.failed == []

    @patch(
        "terrawrap.models.config_mover.ConfigMover.s3_client", new_callable=MagicMock
    )
    def test_dry_run_makes_no_changes(self, s3_mock: MagicMock):
        s3_mock.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )

        manifest = self._manifest_path(
            [
                {"source": str(self.sources["a"]), "target": str(self.targets["a"])},
                {"source": str(self.sources["b"]), "target": str(self.targets["b"])},
            ]
        )
        batch = BatchConfigMover(manifest)
        exit_code = batch.run(skip_confirmation=True, dry_run=True)

        assert exit_code == 0
        assert (self.sources["a"] / "main.tf").exists()
        assert (self.sources["b"] / "main.tf").exists()
        assert not self.targets["a"].exists() or not any(self.targets["a"].iterdir())
        s3_mock.copy.assert_not_called()

    # ---- up-front validation rejections ----------------------------------------------

    @patch(
        "terrawrap.models.config_mover.ConfigMover.s3_client", new_callable=MagicMock
    )
    def test_duplicate_targets_aborts_before_mutation(self, s3_mock: MagicMock):
        manifest = self._manifest_path(
            [
                {"source": str(self.sources["a"]), "target": str(self.targets["a"])},
                {"source": str(self.sources["b"]), "target": str(self.targets["a"])},
            ]
        )
        batch = BatchConfigMover(manifest)
        with pytest.raises(RuntimeError, match="Duplicate target"):
            batch.run(skip_confirmation=True)
        assert (self.sources["a"] / "main.tf").exists()
        assert (self.sources["b"] / "main.tf").exists()
        s3_mock.copy.assert_not_called()

    @patch(
        "terrawrap.models.config_mover.ConfigMover.s3_client", new_callable=MagicMock
    )
    def test_duplicate_sources_aborts_before_mutation(self, s3_mock: MagicMock):
        manifest = self._manifest_path(
            [
                {"source": str(self.sources["a"]), "target": str(self.targets["a"])},
                {"source": str(self.sources["a"]), "target": str(self.targets["b"])},
            ]
        )
        batch = BatchConfigMover(manifest)
        with pytest.raises(RuntimeError, match="Duplicate source"):
            batch.run(skip_confirmation=True)
        s3_mock.copy.assert_not_called()

    @patch(
        "terrawrap.models.config_mover.ConfigMover.s3_client", new_callable=MagicMock
    )
    def test_target_is_another_items_source_aborts(self, s3_mock: MagicMock):
        manifest = self._manifest_path(
            [
                {"source": str(self.sources["a"]), "target": str(self.sources["b"])},
                {"source": str(self.sources["b"]), "target": str(self.targets["c"])},
            ]
        )
        batch = BatchConfigMover(manifest)
        with pytest.raises(RuntimeError, match="Chained moves"):
            batch.run(skip_confirmation=True)
        s3_mock.copy.assert_not_called()

    @patch(
        "terrawrap.models.config_mover.ConfigMover.s3_client", new_callable=MagicMock
    )
    def test_mixed_state_buckets_aborts(self, s3_mock: MagicMock):
        # Build an alt subtree with its own bucket override so per-item env check passes
        # but cross-item bucket check fails.
        alt_root = self._aws_path / "alt"
        alt_root.mkdir(parents=True, exist_ok=True)
        (alt_root / "alt.auto.tfvars").write_text(
            'terraform_state_bucket = "other-bucket"\n'
        )
        alt_src = alt_root / "src_alt"
        alt_src.mkdir()
        (alt_src / "main.tf").write_text(_MAIN_TF)
        alt_tgt = alt_root / "tgt_alt"
        self.repo.git.add("--all")
        self.repo.index.commit("alt bucket subtree")

        manifest = self._manifest_path(
            [
                {"source": str(self.sources["a"]), "target": str(self.targets["a"])},
                {"source": str(alt_src), "target": str(alt_tgt)},
            ]
        )
        batch = BatchConfigMover(manifest)
        s3_mock.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )
        with pytest.raises(RuntimeError, match="same terraform_state_bucket"):
            batch.run(skip_confirmation=True)
        s3_mock.copy.assert_not_called()

    @patch(
        "terrawrap.models.config_mover.ConfigMover.s3_client", new_callable=MagicMock
    )
    def test_s3_target_collision_aborts_before_mutation(self, s3_mock: MagicMock):
        # head_object returns success for item 1's target key only, 404 for others
        def head_side_effect(
            Bucket, Key
        ):  # pylint: disable=invalid-name,unused-argument
            if "tgt_b" in Key:
                return {"LastModified": MagicMock()}
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

        s3_mock.head_object.side_effect = head_side_effect

        manifest = self._manifest_path(
            [
                {"source": str(self.sources["a"]), "target": str(self.targets["a"])},
                {"source": str(self.sources["b"]), "target": str(self.targets["b"])},
            ]
        )
        batch = BatchConfigMover(manifest)
        with pytest.raises(RuntimeError, match="already exist"):
            batch.run(skip_confirmation=True)
        assert (self.sources["a"] / "main.tf").exists()
        assert (self.sources["b"] / "main.tf").exists()
        s3_mock.copy.assert_not_called()

    @patch(
        "terrawrap.models.config_mover.ConfigMover.s3_client", new_callable=MagicMock
    )
    def test_dirty_source_file_aborts_entire_batch(self, s3_mock: MagicMock):
        s3_mock.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )

        # make src_a's main.tf dirty
        (self.sources["a"] / "main.tf").write_text(_MAIN_TF + "\n# dirty\n")

        manifest = self._manifest_path(
            [
                {"source": str(self.sources["a"]), "target": str(self.targets["a"])},
                {"source": str(self.sources["b"]), "target": str(self.targets["b"])},
            ]
        )
        batch = BatchConfigMover(manifest)
        with pytest.raises(RuntimeError, match="uncommitted changes"):
            batch.run(skip_confirmation=True)
        s3_mock.copy.assert_not_called()
        assert (self.sources["a"] / "main.tf").exists()
        assert (self.sources["b"] / "main.tf").exists()

    # ---- execution-stage failures ----------------------------------------------------

    @patch(
        "terrawrap.models.config_mover.ConfigMover.s3_client", new_callable=MagicMock
    )
    def test_execution_failure_resets_failed_item_only(self, s3_mock: MagicMock):
        s3_mock.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )

        # S3 copy succeeds for item 0 (a), fails for item 1 (b)
        def copy_side_effect(
            CopySource, Bucket, Key
        ):  # pylint: disable=invalid-name,unused-argument
            if "tgt_b" in Key:
                raise ClientError({"Error": {"Code": "500"}}, "CopyObject")
            return None

        s3_mock.copy.side_effect = copy_side_effect

        manifest = self._manifest_path(
            [
                {"source": str(self.sources["a"]), "target": str(self.targets["a"])},
                {"source": str(self.sources["b"]), "target": str(self.targets["b"])},
            ]
        )
        batch = BatchConfigMover(manifest)
        exit_code = batch.run(skip_confirmation=True)

        assert exit_code == 1
        assert batch.succeeded == [0]
        assert [i for i, _ in batch.failed] == [1]

        # item a: moved successfully
        assert (self.targets["a"] / "main.tf").exists()
        # item b: reset — source files back, target empty
        assert (self.sources["b"] / "main.tf").exists()
        assert not self.targets["b"].exists() or not any(self.targets["b"].iterdir())
        # working tree clean for item b (original state restored)
        status_b = self.repo.git.status(
            "--porcelain", "--", str(self.sources["b"])
        ).strip()
        assert status_b == ""

    @patch("builtins.input")
    @patch(
        "terrawrap.models.config_mover.ConfigMover.s3_client", new_callable=MagicMock
    )
    def test_failure_then_rollback_accepted(
        self, s3_mock: MagicMock, input_mock: MagicMock
    ):
        s3_mock.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )

        def copy_side_effect(
            CopySource, Bucket, Key
        ):  # pylint: disable=invalid-name,unused-argument
            if "tgt_b" in Key:
                raise ClientError({"Error": {"Code": "500"}}, "CopyObject")
            return None

        s3_mock.copy.side_effect = copy_side_effect
        input_mock.side_effect = ["y", "r"]

        manifest = self._manifest_path(
            [
                {"source": str(self.sources["a"]), "target": str(self.targets["a"])},
                {"source": str(self.sources["b"]), "target": str(self.targets["b"])},
            ]
        )
        batch = BatchConfigMover(manifest)
        exit_code = batch.run(skip_confirmation=False)

        assert exit_code == 1
        s3_mock.delete_object.assert_called_once()
        delete_kwargs = s3_mock.delete_object.call_args.kwargs
        assert "tgt_a" in delete_kwargs["Key"]
        # item a's local state rolled back
        assert (self.sources["a"] / "main.tf").exists()
        assert not self.targets["a"].exists() or not any(self.targets["a"].iterdir())
        assert self.repo.git.status("--porcelain").strip() == ""

    @patch("builtins.input")
    @patch(
        "terrawrap.models.config_mover.ConfigMover.s3_client", new_callable=MagicMock
    )
    def test_failure_then_keep_accepted(
        self, s3_mock: MagicMock, input_mock: MagicMock
    ):
        s3_mock.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )

        def copy_side_effect(
            CopySource, Bucket, Key
        ):  # pylint: disable=invalid-name,unused-argument
            if "tgt_b" in Key:
                raise ClientError({"Error": {"Code": "500"}}, "CopyObject")
            return None

        s3_mock.copy.side_effect = copy_side_effect
        input_mock.side_effect = ["y", "k"]

        manifest = self._manifest_path(
            [
                {"source": str(self.sources["a"]), "target": str(self.targets["a"])},
                {"source": str(self.sources["b"]), "target": str(self.targets["b"])},
            ]
        )
        batch = BatchConfigMover(manifest)
        exit_code = batch.run(skip_confirmation=False)

        assert exit_code == 1
        s3_mock.delete_object.assert_not_called()
        assert (self.targets["a"] / "main.tf").exists()

    @patch("builtins.input")
    @patch(
        "terrawrap.models.config_mover.ConfigMover.s3_client", new_callable=MagicMock
    )
    def test_rollback_failure_prints_manual_recovery(
        self, s3_mock: MagicMock, input_mock: MagicMock
    ):
        s3_mock.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )

        def copy_side_effect(
            CopySource, Bucket, Key
        ):  # pylint: disable=invalid-name,unused-argument
            if "tgt_b" in Key:
                raise ClientError({"Error": {"Code": "500"}}, "CopyObject")
            return None

        s3_mock.copy.side_effect = copy_side_effect
        s3_mock.delete_object.side_effect = ClientError(
            {"Error": {"Code": "500"}}, "DeleteObject"
        )
        input_mock.side_effect = ["y", "r"]

        manifest = self._manifest_path(
            [
                {"source": str(self.sources["a"]), "target": str(self.targets["a"])},
                {"source": str(self.sources["b"]), "target": str(self.targets["b"])},
            ]
        )
        batch = BatchConfigMover(manifest)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exit_code = batch.run(skip_confirmation=False)

        assert exit_code == 1
        assert "Manual recovery" in out.getvalue()
        # only one rollback attempted, not retried
        assert s3_mock.delete_object.call_count == 1

    # ---- manifest parsing ------------------------------------------------------------

    def test_manifest_parses_yaml(self):
        manifest = self._manifest_path(
            [
                {"source": "/a", "target": "/b"},
                {"source": "/c", "target": "/d"},
            ],
            fmt="yaml",
        )
        entries = BatchConfigMover._load_manifest(manifest)
        assert entries == [
            {"source": "/a", "target": "/b"},
            {"source": "/c", "target": "/d"},
        ]

    def test_manifest_parses_json(self):
        manifest = self._manifest_path(
            [{"source": "/a", "target": "/b"}],
            fmt="json",
        )
        entries = BatchConfigMover._load_manifest(manifest)
        assert entries == [{"source": "/a", "target": "/b"}]

    def test_manifest_parses_stdin(self):
        payload = yaml.safe_dump([{"source": "/a", "target": "/b"}])
        with patch.object(sys, "stdin", io.StringIO(payload)):
            entries = BatchConfigMover._load_manifest("-")
        assert entries == [{"source": "/a", "target": "/b"}]

    def test_manifest_rejects_non_list(self):
        path = self._base_path / "bad.yaml"
        path.write_text("source: /a\ntarget: /b\n")
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        with pytest.raises(RuntimeError, match="must be a list"):
            BatchConfigMover._load_manifest(str(path))

    def test_manifest_rejects_missing_keys(self):
        manifest = self._manifest_path([{"source": "/a"}], fmt="yaml", filename="bad2")
        with pytest.raises(RuntimeError, match="source.*target"):
            BatchConfigMover._load_manifest(manifest)

    def test_manifest_rejects_empty(self):
        path = self._base_path / "empty.yaml"
        path.write_text("[]\n")
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        with pytest.raises(RuntimeError, match="empty"):
            BatchConfigMover._load_manifest(str(path))

    def test_manifest_rejects_unsupported_extension(self):
        path = self._base_path / "bad.txt"
        path.write_text("foo")
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        with pytest.raises(RuntimeError, match="Unsupported manifest extension"):
            BatchConfigMover._load_manifest(str(path))
