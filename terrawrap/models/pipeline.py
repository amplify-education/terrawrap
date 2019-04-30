"""Module containing the Pipeline class"""
import csv
import concurrent.futures

from collections import defaultdict

from terrawrap.models.pipeline_entry import PipelineEntry


class Pipeline:
    """Class for representing a pipeline."""

    def __init__(self, command, config_path):
        """
        :param command: The Terraform command that this pipeline should execute.
        :param config_path: Path to the Terraform configuration file. Can be absolute or relative from where
        the script is executed.
        """
        self.command = command

        self.reverse_pipeline = command == 'destroy'

        if not config_path.endswith(".csv"):
            raise RuntimeError("Config file '%s' doesn't appear to be a CSV file: Should end in .csv")

        with open(config_path) as config_file:
            reader = csv.DictReader(config_file)
            entries = defaultdict(list)

            for row in reader:
                entry = PipelineEntry(
                    path=row['directory'],
                    variables=row['variables'].split(' ') if row['variables'] else []
                )
                entries[int(row['seq'])] += [entry]

        self.entries = entries

    def execute(self, num_parallel=4, debug=False):
        """
        Function for executing the pipeline. Will execute each sequence separately, with the entries inside
        each sequence being executed in parallel, up to the limit given in num_parallel.
        :param num_parallel: The number of pipeline entries to run in parallel.
        :param debug: True if Terraform debugging should be turned on.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_parallel) as executor:
            for sequence in sorted(self.entries.keys(), reverse=self.reverse_pipeline):
                print("Executing sequence %s" % sequence)

                self._execute_entries(
                    command="init",
                    entries=self.entries[sequence],
                    debug=debug,
                    executor=executor
                )

                self._execute_entries(
                    command=self.command,
                    entries=self.entries[sequence],
                    debug=debug,
                    executor=executor
                )

        print("Pipeline executed successfully.")

    def _execute_entries(self, entries, executor, command=None, debug=False):
        """
        Convenience function for executing the given entries with the given command.
        :param entries: An iterable of Pipeline Entries to execute.
        :param executor: The Executor to use. See concurrent.futures.Executor.
        :param command: The Terraform command to execute. If not provided, defaults to the command for the
        pipeline.
        :param debug: True if Terraform debugging should be printed.
        """
        command = command or self.command
        futures_to_paths = {}
        failures = []

        for entry in entries:
            print("Executing %s %s ..." % (entry.path, command))
            future = executor.submit(entry.execute, command, debug=debug)
            futures_to_paths[future] = entry.path

        for future in concurrent.futures.as_completed(futures_to_paths):
            exit_code, stdout = future.result()
            path = futures_to_paths[future]

            print("\nFinished executing %s %s ..." % (path, command))
            print("Output:\n\n%s\n" % "".join(stdout).strip())

            if exit_code != 0:
                failures.append(path)

        if failures:
            raise RuntimeError(
                "The follow pipeline entries failed with command '%s':\n%s" % (command, "\n".join(failures))
            )
