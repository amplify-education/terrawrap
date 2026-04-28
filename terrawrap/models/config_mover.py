# pylint:disable=C0114,C0301
import json
import os
import sys
from functools import lru_cache
from os.path import relpath
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Iterable, Any

import boto3
import git
import yaml
from botocore.exceptions import ClientError
import hcl2

from terrawrap.utils.config import find_variable_files, parse_variable_files
from terrawrap.utils.path import calc_repo_path
from terrawrap.utils.terminal_colors import TerminalColors as Colors


class ConfigMover:
    """
    Class for moving terraform configuration between directories.
    This is done by moving .tfstate file in appropriate S3 bucket.
    """

    tf_state_file_extension = ".tfstate"

    def __init__(
        self,
        source_directory: Path,
        target_directory: Path,
    ):
        self.source_directory = source_directory
        self.target_directory = target_directory
        self.source_directory_abs = self.source_directory.absolute()
        self.target_directory_abs = self.target_directory.absolute()
        # we're using current path instead of the above in case they don't exist
        self._repo = git.Repo(os.getcwd(), search_parent_directories=True)
        self._s3 = boto3.client("s3")
        self._files_to_move: Optional[List[Path]] = None

    @property
    def s3_client(self):
        """S3 client"""
        return self._s3

    @property
    def repo(self) -> git.Repo:
        """Git repository"""
        return self._repo

    @lru_cache
    def _build_state_file_s3_key(self, terraform_path: Union[str, Path]) -> str:
        """
        Given path (absolute or relative) of terraform directory,
        return name of this directory's state file, example:
        Documents/terraform-config/config/aws/app/ ->
        terraform-config/config/aws/app.tfstate
        """
        return f"{calc_repo_path(terraform_path)}{self.tf_state_file_extension}"

    @lru_cache
    def _find_auto_variable(
        self, path: Path, variable_name: str, strict: bool = True
    ) -> Any:
        variables = parse_variable_files(self._find_variable_files(path))
        if strict:
            return variables[
                variable_name
            ]  # just in case variable_name is actually present, but is None
        return variables.get(variable_name)

    @lru_cache
    def _find_variable_files(self, path: Path) -> List[str]:
        """Find and cache .auto.tfvars files available at the scope of given path"""
        return find_variable_files(str(path))

    def _adjust_modules_sources(self, tf_files: Iterable[Path]):
        """
        For each module block in tf_files, adjusts path to its source depending on the location of target directory,
        for example, given that the target directory is one level deeper than the source directory:
        source = "../../../../../../modules/aws/s3_bucket/v3" ->
        source = "../../../../../../../modules/aws/s3_bucket/v3"
        This method works with modules paths virtually - it doesn't check their existence nor looks up them whatsoever.
        """

        for path in tf_files:
            content = path.read_text()
            config = hcl2.loads(content)
            modules = config.get("module", [])

            for module in modules:
                # get modules source relative path, e.g. '../../../modules/aws/s3_bucket/v3'
                module_source = list(module.values())[0]["source"]
                # convert above to absolute path
                module_source_absolute = (path.parent / module_source).resolve()
                # find modules source path relative to the new directory
                new_module_source = relpath(
                    module_source_absolute, self.target_directory_abs
                )
                content = content.replace(
                    f'"{module_source}"', f'"{new_module_source}"'
                )

            path.write_text(content)

    def _move_state_file_object(self):
        """Moves state file object inside S3 bucket"""
        state_bucket = self._find_auto_variable(
            self.source_directory_abs, "terraform_state_bucket"
        )
        source_key = self._build_state_file_s3_key(self.source_directory_abs)
        target_key = self._build_state_file_s3_key(self.target_directory_abs)

        try:
            response = self.s3_client.head_object(Bucket=state_bucket, Key=target_key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "404":
                raise exc
        else:
            last_modified_date = response["LastModified"]
            raise RuntimeError(
                Colors.RED(
                    f"Target state file {target_key} already exists inside {state_bucket} bucket.\n"
                    "This means one of the following:\n"
                    " - the target directory has been applied in another branch;\n"
                    f" - the state file is a leftover and probably can be safely deleted"
                    f" (file was last modified on {last_modified_date.isoformat()})."
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

    def _verify_source_directory(self) -> List[Path]:
        """Verify that the source directory is a valid terraform directory, returns paths of files to be moved"""
        if not self.source_directory_abs.exists():
            raise RuntimeError(
                Colors.RED(
                    f"Source directory {self.source_directory_abs} does not exist."
                )
            )

        files_to_move = []
        has_terraform_files = False

        git_files = set(self.repo.git.ls_files().splitlines())
        rel_source_path = Path(
            *Path(calc_repo_path(self.source_directory_abs)).parts[1:]
        )

        for path in self.source_directory_abs.iterdir():
            if path.is_file() and str(rel_source_path / path.name) in git_files:

                if path.name.endswith(".tf"):
                    has_terraform_files = True

                files_to_move.append(path)

        if not has_terraform_files:
            raise RuntimeError(
                Colors.RED(
                    f"No terraform configuration files (*.tf) found in {calc_repo_path(self.source_directory_abs)}\n"
                    "If you wish to move a subdirectory, run this tool for its path."
                )
            )

        self._files_to_move = sorted(files_to_move)
        return self._files_to_move

    def _verify_target_directory(self):
        """Verify that the target directory is empty"""
        self.target_directory_abs.mkdir(parents=True, exist_ok=True)
        if any(self.target_directory_abs.iterdir()):
            raise RuntimeError(
                Colors.RED(
                    f"Target directory {self.target_directory_abs} is not empty."
                )
            )

    def _verify_environment(self):
        error_message = Colors.RED(
            "Source and target directories must be in the same AWS account / environment"
        )

        source_state_bucket = self._find_auto_variable(
            self.source_directory_abs, "terraform_state_bucket"
        )
        target_state_bucket = self._find_auto_variable(
            self.target_directory_abs, "terraform_state_bucket"
        )

        if source_state_bucket != target_state_bucket:
            raise RuntimeError(error_message)

        source_environment = self._find_auto_variable(
            self.source_directory_abs, "environment", strict=False
        )
        target_environment = self._find_auto_variable(
            self.target_directory_abs, "environment", strict=False
        )

        if source_environment is None and target_environment is None:
            return

        if source_environment != target_environment:
            raise RuntimeError(error_message)

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
                file = Path(file)
                print("\t", Colors.YELLOW(f"{calc_repo_path(file.parent)}/{file.name}"))
            print(
                Colors.YELLOW(
                    "If your configuration depends on any of the variables defined in the above files, "
                    "make sure these variables are also defined in the target directory.\n"
                )
            )

    def _reset_local_changes(self):
        """
        Undo local changes made by this mover: unstage any pending rename, remove files
        created at target, and restore source files from HEAD. Scoped to files_to_move
        only — never touches unrelated paths. Requires `_verify_source_directory` to have
        run first (populates `_files_to_move`).
        """
        if not self._files_to_move:
            return

        repo_root = Path(self.repo.working_tree_dir)
        source_rel_paths: List[str] = []
        target_rel_paths: List[str] = []
        target_abs_paths: List[Path] = []
        for source_file in self._files_to_move:
            try:
                source_rel_paths.append(str(source_file.relative_to(repo_root)))
            except ValueError:
                continue
            target_file = self.target_directory_abs / source_file.name
            try:
                target_rel_paths.append(str(target_file.relative_to(repo_root)))
                target_abs_paths.append(target_file)
            except ValueError:
                continue

        all_rel_paths = source_rel_paths + target_rel_paths
        if all_rel_paths:
            try:
                self.repo.git.reset("HEAD", "--", *all_rel_paths)
            except git.GitCommandError:
                pass

        for target_file in target_abs_paths:
            if target_file.exists() and target_file.is_file():
                try:
                    target_file.unlink()
                except OSError:
                    pass

        if source_rel_paths:
            try:
                self.repo.git.checkout("HEAD", "--", *source_rel_paths)
            except git.GitCommandError:
                pass

        if (
            self.target_directory_abs.exists()
            and self.target_directory_abs != self.source_directory_abs
        ):
            try:
                if not any(self.target_directory_abs.iterdir()):
                    self.target_directory_abs.rmdir()
            except OSError:
                pass

    def run(self, skip_confirmation: bool = False):
        """Run"""

        if self.source_directory_abs == self.target_directory_abs:
            raise RuntimeError(Colors.RED("Source and target paths are the same."))

        files_to_move = self._verify_source_directory()
        self._verify_target_directory()
        self._verify_environment()

        state_bucket = self._find_auto_variable(
            self.source_directory_abs, "terraform_state_bucket"
        )
        source_state_file = self._build_state_file_s3_key(self.source_directory_abs)
        target_state_file = self._build_state_file_s3_key(self.target_directory_abs)

        print(
            "\nRemote state:\n"
            f"\tBucket:\t\t{Colors.BOLD(state_bucket)}\n"
            f"\tSource key: \t{Colors.BOLD(source_state_file)}\n"
            f"\tTarget key: \t{Colors.BOLD(target_state_file)}\n"
        )

        print(
            "Following files will be moved:\n"
            f"\t{Colors.BOLD(calc_repo_path(self.source_directory_abs))}"
        )
        for tf_file in files_to_move[:-1]:
            print(f"\t├────{Colors.BOLD(tf_file.name)}")
        print(f"\t└────{Colors.BOLD(files_to_move[-1].name)}")
        print(
            f"to the new directory: \n\t{Colors.BOLD(calc_repo_path(self.target_directory_abs))}\n"
        )

        self._diff_autovars()
        # fmt: off
        if (
            not skip_confirmation
            and input(Colors.BOLD(
                "This tool will move remote state file and local directory contents; proceed? (y/N) "
                )).lower() != "y"
        ):
            raise RuntimeError("Aborted.\n")
        # fmt: on

        self._adjust_modules_sources(
            file for file in files_to_move if file.name.endswith(".tf")
        )
        self._move_files(files_to_move)
        self._move_state_file_object()

        print(
            f"{Colors.GREEN('Remote state file moved successfuly.')}\n"
            f"{Colors.GREEN('Local directory contents moved successfuly.')}"
        )
        print(
            f"Adjust configuration in the target directory if needed.\n"
            f"Run {Colors.UNDERLINE('tf ' + str(self.target_directory) + ' init')}\n"
            f"and then {Colors.UNDERLINE('tf ' + str(self.target_directory) + ' plan')}\n"
            f"to make sure that there are no undesired infrastructure changes.\n"
            f"Remember to {Colors.UNDERLINE('commit local changes and create a PR')}.\n"
        )


class BatchConfigMover:
    """
    Orchestrates moving multiple terraform directories in a single batch. Validates the
    entire manifest up-front, executes moves attempt-all, auto-resets local state for
    failed items, and prompts at end-of-batch to optionally roll back successful items.
    """

    def __init__(self, manifest_path: str):
        self.manifest_path = manifest_path
        self.entries: List[Dict[str, str]] = self._load_manifest(manifest_path)
        self.movers: List[ConfigMover] = [
            ConfigMover(Path(entry["source"]), Path(entry["target"]))
            for entry in self.entries
        ]
        self.succeeded: List[int] = []
        self.failed: List[Tuple[int, Exception]] = []
        self.state_bucket: Optional[str] = None

    @staticmethod
    def _load_manifest(manifest_path: str) -> List[Dict[str, str]]:
        """Load and parse the manifest file. Supports JSON (.json) and YAML (.yaml/.yml).
        Pass '-' to read YAML from stdin."""
        if manifest_path == "-":
            content = sys.stdin.read()
            data = yaml.safe_load(content)
        else:
            path = Path(manifest_path)
            if not path.is_file():
                raise RuntimeError(
                    Colors.RED(f"Manifest file not found: {manifest_path}")
                )
            content = path.read_text()
            suffix = path.suffix.lower()
            if suffix == ".json":
                data = json.loads(content)
            elif suffix in (".yaml", ".yml"):
                data = yaml.safe_load(content)
            else:
                raise RuntimeError(
                    Colors.RED(
                        f"Unsupported manifest extension '{suffix}'. Use .json, .yaml, or .yml."
                    )
                )

        if not isinstance(data, list):
            raise RuntimeError(
                Colors.RED("Manifest must be a list of {source, target} entries.")
            )
        if not data:
            raise RuntimeError(Colors.RED("Manifest is empty."))

        for i, entry in enumerate(data):
            if not isinstance(entry, dict):
                raise RuntimeError(Colors.RED(f"Manifest entry {i} must be an object."))
            if set(entry.keys()) != {"source", "target"}:
                raise RuntimeError(
                    Colors.RED(
                        f"Manifest entry {i} must have exactly 'source' and 'target' keys (got: {sorted(entry.keys())})."
                    )
                )
            if not isinstance(entry["source"], str) or not isinstance(
                entry["target"], str
            ):
                raise RuntimeError(
                    Colors.RED(f"Manifest entry {i} source/target must be strings.")
                )

        return data

    def _validate_structural(self):
        """Pure validation: no duplicates, no chains, no self-moves."""
        sources = [m.source_directory_abs for m in self.movers]
        targets = [m.target_directory_abs for m in self.movers]

        for i, mover in enumerate(self.movers):
            if mover.source_directory_abs == mover.target_directory_abs:
                raise RuntimeError(
                    Colors.RED(
                        f"Entry {i}: source and target paths are the same ({mover.source_directory})."
                    )
                )

        dup_sources = {s for s in sources if sources.count(s) > 1}
        if dup_sources:
            raise RuntimeError(
                Colors.RED(
                    f"Duplicate source paths in manifest: {sorted(str(p) for p in dup_sources)}"
                )
            )

        dup_targets = {t for t in targets if targets.count(t) > 1}
        if dup_targets:
            raise RuntimeError(
                Colors.RED(
                    f"Duplicate target paths in manifest: {sorted(str(p) for p in dup_targets)}"
                )
            )

        source_set = set(sources)
        chain_targets = [t for t in targets if t in source_set]
        if chain_targets:
            raise RuntimeError(
                Colors.RED(
                    "Chained moves are not supported in a single batch "
                    f"(target is also another item's source): {sorted(str(p) for p in chain_targets)}.\n"
                    "Run separate batches instead."
                )
            )

    def _validate_per_item(self):
        """Reuse existing ConfigMover validators on each item."""
        for i, mover in enumerate(self.movers):
            try:
                mover._verify_source_directory()
                mover._verify_target_directory()
                mover._verify_environment()
            except RuntimeError as exc:
                raise RuntimeError(
                    Colors.RED(f"Entry {i} ({mover.source_directory}): ") + str(exc)
                ) from exc

    def _validate_cross_item(self):
        """All items must share a state bucket; no S3 target collisions."""
        buckets = []
        for i, mover in enumerate(self.movers):
            bucket = mover._find_auto_variable(
                mover.source_directory_abs, "terraform_state_bucket"
            )
            buckets.append((i, mover, bucket))

        distinct_buckets = {b for _, _, b in buckets}
        if len(distinct_buckets) > 1:
            details = ", ".join(f"entry {i}: {b}" for i, _, b in buckets)
            raise RuntimeError(
                Colors.RED(
                    f"All batch items must share the same terraform_state_bucket. Got: {details}"
                )
            )
        self.state_bucket = buckets[0][2]

        collisions = []
        for i, mover, _ in buckets:
            target_key = mover._build_state_file_s3_key(mover.target_directory_abs)
            try:
                mover.s3_client.head_object(Bucket=self.state_bucket, Key=target_key)
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "404":
                    raise
                continue
            collisions.append((i, target_key))

        if collisions:
            lines = "\n".join(f"  entry {i}: {key}" for i, key in collisions)
            raise RuntimeError(
                Colors.RED(
                    f"Target state file(s) already exist in {self.state_bucket}:\n{lines}"
                )
            )

    def _validate_clean_worktree(self):
        """Refuse the batch if any source file has uncommitted changes or is untracked."""
        dirty: List[str] = []
        repo = self.movers[0].repo
        repo_root = Path(repo.working_tree_dir)

        for mover in self.movers:
            for source_file in mover._files_to_move or []:
                try:
                    rel = str(source_file.relative_to(repo_root))
                except ValueError:
                    continue
                status = repo.git.status("--porcelain", "--", rel).strip()
                if status:
                    dirty.append(status)

        if dirty:
            lines = "\n".join(f"  {line}" for line in dirty)
            raise RuntimeError(
                Colors.RED(
                    "Batch refused: source files have uncommitted changes:\n"
                    + lines
                    + "\nCommit or stash your changes before running a batch move."
                )
            )

    def _print_plan(self):
        print(
            Colors.BOLD(
                f"\nBatch of {len(self.movers)} moves (bucket: {self.state_bucket})\n"
            )
        )
        for i, mover in enumerate(self.movers):
            source_key = mover._build_state_file_s3_key(mover.source_directory_abs)
            target_key = mover._build_state_file_s3_key(mover.target_directory_abs)
            print(
                f"  [{i}] {Colors.BOLD(calc_repo_path(mover.source_directory_abs))}"
                f" -> {Colors.BOLD(calc_repo_path(mover.target_directory_abs))}"
            )
            print(f"      state: {source_key} -> {target_key}")
        print()
        for mover in self.movers:
            mover._diff_autovars()

    def _execute(self):
        """Attempt all items. Per-item failure triggers a local reset for that item."""
        for i, mover in enumerate(self.movers):
            try:
                mover._adjust_modules_sources(
                    f for f in (mover._files_to_move or []) if f.name.endswith(".tf")
                )
                mover._move_files(mover._files_to_move or [])
                mover._move_state_file_object()
                self.succeeded.append(i)
                print(
                    Colors.GREEN(
                        f"  [{i}] OK: {mover.source_directory} -> {mover.target_directory}"
                    )
                )
            except Exception as exc:  # pylint: disable=broad-except
                self.failed.append((i, exc))
                print(
                    Colors.RED(
                        f"  [{i}] FAILED: {mover.source_directory} -> {mover.target_directory}\n"
                        f"      {exc}"
                    )
                )
                try:
                    mover._reset_local_changes()
                except Exception as reset_exc:  # pylint: disable=broad-except
                    print(Colors.RED(f"      (local reset also failed: {reset_exc})"))

    def _rollback_successful(self) -> List[str]:
        """Delete S3 target keys and reset local changes for successful items.
        Returns a list of manual-recovery lines for any operations that couldn't be rolled back."""
        recovery: List[str] = []
        for i in self.succeeded:
            mover = self.movers[i]
            target_key = mover._build_state_file_s3_key(mover.target_directory_abs)
            try:
                mover.s3_client.delete_object(Bucket=self.state_bucket, Key=target_key)
            except Exception as exc:  # pylint: disable=broad-except
                recovery.append(
                    f"  S3: delete s3://{self.state_bucket}/{target_key} (error: {exc})"
                )
            try:
                mover._reset_local_changes()
            except Exception as exc:  # pylint: disable=broad-except
                recovery.append(
                    f"  Local: restore {calc_repo_path(mover.source_directory_abs)} (error: {exc})"
                )
        return recovery

    def _prompt_end_of_batch(self, skip_confirmation: bool):
        """Three-way prompt on partial failure: roll back / keep / details."""
        if not self.succeeded or not self.failed:
            return
        if skip_confirmation:
            return

        while True:
            choice = (
                input(
                    Colors.BOLD(
                        f"\n{len(self.succeeded)} succeeded, {len(self.failed)} failed. "
                        "Roll back successful items? ([r]oll back / [k]eep / [s]how details): "
                    )
                )
                .strip()
                .lower()
            )
            if choice == "r":
                recovery = self._rollback_successful()
                if recovery:
                    print(
                        Colors.RED(
                            "\nRollback partially failed. Manual recovery needed:"
                        )
                    )
                    for line in recovery:
                        print(line)
                else:
                    print(Colors.GREEN("Rollback complete."))
                return
            if choice == "k":
                return
            if choice == "s":
                print("\nFailure details:")
                for i, exc in self.failed:
                    mover = self.movers[i]
                    print(
                        f"  [{i}] {mover.source_directory} -> {mover.target_directory}"
                    )
                    print(f"      {exc}")
                print("\nSuccessful items:")
                for i in self.succeeded:
                    mover = self.movers[i]
                    print(
                        f"  [{i}] {mover.source_directory} -> {mover.target_directory}"
                    )
                continue
            print("  Please enter r, k, or s.")

    def run(self, skip_confirmation: bool = False, dry_run: bool = False) -> int:
        """Run the batch. Returns process exit code (0 = all succeeded, 1 = any failed)."""
        self._validate_structural()
        self._validate_per_item()
        self._validate_cross_item()
        self._validate_clean_worktree()

        self._print_plan()

        if dry_run:
            print(Colors.YELLOW("--dry-run specified; no changes made."))
            return 0

        if (
            not skip_confirmation
            and input(
                Colors.BOLD(f"Proceed with {len(self.movers)} moves? (y/N) ")
            ).lower()
            != "y"
        ):
            raise RuntimeError("Aborted.\n")

        self._execute()
        self._prompt_end_of_batch(skip_confirmation)

        return 0 if not self.failed else 1
