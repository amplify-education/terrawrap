"""Module containing the Pipeline class"""
import concurrent.futures
import csv
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional, List, DefaultDict

from terrawrap.models.pipeline_entry import PipelineEntry


class Pipeline:
    """Class for representing a pipeline."""

    def __init__(self, command: str, pipeline_path: str):
        """
        :param command: The Terraform command that this pipeline should execute.
        :param pipeline_path: Path to the Terrawrap pipeline file. Can be absolute or relative from where
        the script is executed.
        """
        self.command = command

        self.reverse_pipeline = command == 'destroy'

        if not pipeline_path.endswith(".csv"):
            raise RuntimeError("Config file '%s' doesn't appear to be a CSV file: Should end in .csv")

        with open(pipeline_path) as pipeline_file:
            reader = csv.DictReader(pipeline_file)
            # Lambda function is needed here because the argument to defaultdict needs to be a function that
            # returns an object.
            entries: DefaultDict[int, DefaultDict[str, List[PipelineEntry]]] = \
                defaultdict(lambda: defaultdict(list))

            for row in reader:
                entry = PipelineEntry(
                    path=row['directory'],
                    variables=row['variables'].split(' ') if row['variables'] else []
                )
                seq = int(row['seq'])
                path = Path(row['directory'])
                if not path.is_symlink():
                    entries[seq]['parallel'].append(entry)
                else:
                    entries[seq]['sequential'].append(entry)

        self.entries = entries

    def execute(self, num_parallel: int = 4, debug: bool = False, print_only_changes: bool = False):
        """
        Function for executing the pipeline. Will execute each sequence separately, with the entries inside
        each sequence being executed in parallel, up to the limit given in num_parallel.
        :param num_parallel: The number of pipeline entries to run in parallel.
        :param debug: True if Terraform debugging should be turned on.
        :param print_only_changes: True if only directories which contained changes should be printed.
        """
        for sequence in sorted(self.entries.keys(), reverse=self.reverse_pipeline):
            print("Executing sequence %s" % sequence)
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_parallel) as executor:
                self._execute_entries(
                    command=self.command,
                    entries=self.entries[sequence]['parallel'],
                    debug=debug,
                    executor=executor,
                    print_only_changes=print_only_changes,
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                for entry in self.entries[sequence]['sequential']:
                    # It's very important that these sequential entries run init and then plan, and not all
                    # the inits and then all the plans, because the symlink directories might share the same
                    # real directories, and then running init multiple times in that directory will break
                    # future applies. So run init and then the command immediately.
                    self._execute_entries(
                        command=self.command,
                        entries=[entry],
                        debug=debug,
                        executor=executor,
                        print_only_changes=print_only_changes,
                    )

        print("Pipeline executed successfully.")

    def _execute_entries(
            self,
            entries: Iterable[PipelineEntry],
            executor: concurrent.futures.Executor,
            command: Optional[str] = None,
            debug: bool = False,
            print_only_changes: bool = False,
    ):
        """
        Convenience function for executing the given entries with the given command.
        :param entries: An iterable of Pipeline Entries to execute.
        :param executor: The Executor to use. See concurrent.futures.Executor.
        :param command: The Terraform command to execute. If not provided, defaults to the command for the
        pipeline.
        :param debug: True if Terraform debugging should be printed.
        :param print_only_changes: True if only directories which contained changes should be printed.
        """
        command = command or self.command
        futures_to_paths = {}
        failures = []

        for entry in entries:
            print("Executing %s %s ..." % (entry.path, command))
            future = executor.submit(entry.execute, command, debug=debug)
            futures_to_paths[future] = entry.path

        for future in concurrent.futures.as_completed(futures_to_paths):
            exit_code, stdout, changes_detected = future.result()
            path = futures_to_paths[future]

            if print_only_changes and not changes_detected:
                stdout = ["No changes detected.\n"]

            print("\nFinished executing %s %s ..." % (path, command))
            print("Output:\n\n%s\n" % "".join(stdout).strip())

            if exit_code != 0:
                failures.append(path)

        if failures:
            raise RuntimeError(
                "The follow pipeline entries failed with command '%s':\n%s" % (command, "\n".join(failures))
            )
