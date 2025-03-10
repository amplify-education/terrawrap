# pylint:disable=C0114,C0301
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Union, Iterable

import boto3
import git
from botocore.exceptions import ClientError

from terrawrap.utils.config import find_variable_files, parse_variable_files
from terrawrap.utils.terminal_colors import TerminalColors as Colors


class ConfigMover:
    """
    Class for moving terraform configuration between directories.
    This is done by moving .tfstate file in appropriate S3 bucket.
    """

    tf_config_repo_root = "terraform-config"
    tf_state_file_extension = ".tfstate"

    @staticmethod
    @lru_cache()
    def _find_variable_files(path: Path) -> List[str]:
        """Find and cache .auto.tfvars files available at the scope of given path"""
        return find_variable_files(str(path))

    @classmethod
    def _to_repo_root_path(cls, path: Union[str, Path]) -> Path:
        """
        Convert to path relative to terraform-config repository root
        /Users/home/terraform-config/config/aws/amplify-learning-dev ->
        terraform-config/config/aws/amplify-learning-dev
        """
        # [1:] removes leading slash
        return Path(str(path).partition(cls.tf_config_repo_root)[2][1:])

    @classmethod
    def _build_state_file_s3_key(cls, terraform_path: Union[str, Path]) -> str:
        """
        Given path (absolute or relative) of terraform directory,
        return name of this directory's state file, example:
        Documents/terraform-config/config/aws/amplify-learning-dev/devci/astrotools/test/ ->
        terraform-config/config/aws/amplify-learning-dev/devci/astrotools/test.tfstate
        """
        return f"{cls.tf_config_repo_root}/{cls._to_repo_root_path(terraform_path)}{cls.tf_state_file_extension}"

    def __init__(self, source_directory: Path, target_directory: Path):
        self.source_directory = source_directory
        self.target_directory = target_directory
        self.source_directory_abs = self.source_directory.absolute()
        self.target_directory_abs = self.target_directory.absolute()
        # we're using current path instead of the above in case they don't exist
        self._repo = git.Repo(os.getcwd(), search_parent_directories=True)
        self._s3 = boto3.client("s3")

    @property
    def s3_client(self):
        """S3 client"""
        return self._s3

    @property
    def repo(self):
        """Git repository"""
        return self._repo

    @lru_cache
    def _find_state_bucket(self) -> str:
        """Search for state bucket name across .auto.tfvars files and return it"""
        return parse_variable_files(
            self._find_variable_files(self.source_directory_abs.parent)
        )["terraform_state_bucket"]

    def _move_state_file_object(self):
        """Moves state file object inside S3 bucket"""
        state_bucket = self._find_state_bucket()
        source_key = self._build_state_file_s3_key(self.source_directory_abs)
        target_key = self._build_state_file_s3_key(self.target_directory_abs)

        try:
            self.s3_client.head_object(Bucket=state_bucket, Key=target_key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "404":
                raise exc
        else:
            raise RuntimeError(
                Colors.RED(
                    f"Target state file {target_key} already exists inside {state_bucket} bucket.\n"
                    "This means that the target directory has been applied in another branch "
                    "or that the statefile is a leftover."
                )
            )

        try:
            self.s3_client.copy(
                CopySource={
                    "Bucket": state_bucket,
                    "Key": source_key,
                },
                Bucket=state_bucket,
                Key=target_key,
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "404":
                raise RuntimeError(
                    Colors.RED(
                        f"No state file has been found for {self.source_directory} "
                        f"directory inside {state_bucket} bucket.\n"
                        "Make sure that the directory is a valid terraform directory and has been applied."
                    )
                ) from exc
            raise exc from exc

    def _move_files(self, files: Iterable[Path]):
        """Moves terraform configuration files with git mv, skips subdirectories."""
        self.target_directory_abs.mkdir(parents=True, exist_ok=True)
        sources = [str(f) for f in files]
        self.repo.index.move([*sources, str(self.target_directory_abs)])

    def _verify_source_directory(self):
        """Verify that the source directory exists"""
        if not self.source_directory_abs.exists():
            raise RuntimeError(
                Colors.RED(
                    f"Source directory {self._to_repo_root_path(self.source_directory_abs)} does not exist."
                )
            )

    def _verify_target_directory(self):
        """Verify that the target directory is empty"""
        self.target_directory_abs.mkdir(parents=True, exist_ok=True)
        if any(self.target_directory_abs.iterdir()):
            raise RuntimeError(
                Colors.RED(
                    f"Target directory {self._to_repo_root_path(self.target_directory_abs)} is not empty."
                )
            )

    def _diff_autovars(self):
        """Find .auto.fvars files that are available in scope of the source directory, but not in scope of the target"""
        source_var_files = self._find_variable_files(self.source_directory_abs.parent)
        target_var_files = self._find_variable_files(self.target_directory_abs.parent)

        missing_target_var_files = set(source_var_files) - set(target_var_files)
        if missing_target_var_files:
            print(
                Colors.YELLOW(
                    "Following .auto.tfvars files are not available in the scope of target directory:"
                )
            )
            for file in missing_target_var_files:
                print("\t", Colors.YELLOW(str(self._to_repo_root_path(file))))
            print(
                Colors.YELLOW(
                    "If your configuration depends on any of the variables defined in the above files, "
                    "make sure these variables are also defined in the target directory.\n"
                )
            )

    def run(self):
        """Run"""

        self._verify_source_directory()
        self._verify_target_directory()

        state_bucket = self._find_state_bucket()
        source_state_file = self._build_state_file_s3_key(self.source_directory_abs)
        target_state_file = self._build_state_file_s3_key(self.target_directory_abs)
        print("")  # for vertical spacing
        print(
            "Remote state:\n"
            f"\tBucket:\t\t{Colors.BOLD(state_bucket)}\n"
            f"\tSource key: \t{Colors.BOLD(source_state_file)}\n"
            f"\tTarget key: \t{Colors.BOLD(target_state_file)}\n"
        )

        source_dir_items = list(path for path in self.source_directory_abs.iterdir())

        files_to_move = sorted(
            list(item for item in source_dir_items if item.is_file())
        )

        if len(files_to_move) == 0:
            raise RuntimeError(
                Colors.RED(
                    f"No terraform configuration files found in {self._to_repo_root_path(self.source_directory_abs)}\n"
                    "If you wish to move a subdirectory, run this tool for its path."
                )
            )

        print(
            "Following files will be moved:\n"
            f"\t{Colors.BOLD(self._to_repo_root_path(self.source_directory_abs))}"
        )
        for tf_file in files_to_move[:-1]:
            print(f"\t├────{Colors.BOLD(tf_file.name)}")
        print(f"\t└────{Colors.BOLD(files_to_move[-1].name)}")
        print(
            f"to the new directory: \n\t{Colors.BOLD(self._to_repo_root_path(self.target_directory_abs))}\n"
        )

        self._diff_autovars()

        if (
            input(
                Colors.BOLD(
                    "This tool will move remote state file and local directory contents; proceed? (y/N) "
                )
            )
            != "y"
        ):
            raise RuntimeError("Aborted")
        print("")

        self._move_files(files_to_move)
        self._move_state_file_object()

        print(
            f"{Colors.GREEN('Remote state file moved successfuly.')}\n"
            f"{Colors.GREEN('Local directory contents moved successfuly.')}"
        )
        print(
            f"Run {Colors.UNDERLINE('tf ' + str(self.target_directory) + ' plan')} "
            f"to make sure that there are no undesired infrastructure changes.\n"
            f"Remember to {Colors.UNDERLINE('commit local changes and create a PR')}.\n"
        )
