"""Module containing the Pipeline class"""
import concurrent.futures
import csv
from collections import defaultdict
from pathlib import Path
import networkx
from typing import Iterable, Optional, List, DefaultDict


from terrawrap.models.pipeline_entry import PipelineEntry
from terrawrap.utils.graph import find_source_nodes
from terrawrap.models.graph_entry import GraphEntry


class ApplyGraph:
    """Class for representing a pipeline."""

    def __init__(self, command: str, graph):
        """
        :param command: The Terraform command that this pipeline should execute.
        :param pipeline_path: Path to the Terrawrap pipeline file. Can be absolute or relative from where
        the script is executed.
        """
        self.command = command
        self.graph = graph
        self.reverse_pipeline = command == 'destroy'
        self.graph_dict = {}

    def apply_graph(self):
        sources = find_source_nodes(self.graph)
        futures_to_paths = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            for source in sources:
                if self.graph_dict.get(source):
                    entry = self.graph_dict.get(source)
                else:
                    entry = GraphEntry(source, [])
                    self.graph_dict[source] = entry

                future = executor.submit(entry.test_execute)
                futures_to_paths[future] = entry.path
            for future in concurrent.futures.as_completed(futures_to_paths):
                #exit_code, stdout, changes_detected = future.result()
                path = futures_to_paths[future]
                print("executed in first", path)
                successors = list(self.graph.successors(path))
                if successors: #and no failure
                    print("these are the", successors)
                  #  self.recursive_applier(executor, successors, futures_to_paths)

                #if print_only_changes and not changes_detected:
                    #stdout = ["No changes detected.\n"]

                #print("\nFinished executing %s %s ..." % (path, command))
                #print("Output:\n\n%s\n" % "".join(stdout).strip())

                # if exit_code != 0:
                #     failures.append(path)

    def recursive_applier(self, executor, successors, futures_to_paths):
        for node in successors:
            print("this is my current node", node)
            if self.graph_dict.get(node):
                entry = self.graph_dict.get(node)
            else:
                entry = GraphEntry(node, [])
                self.graph_dict[node] = entry
            if entry.state == "Success":
                print("this already success", entry.path)
                continue
            #print("Executing %s ..." % entry.path)
            future = executor.submit(entry.test_execute)
            futures_to_paths[future] = entry.path

        for future in concurrent.futures.as_completed(futures_to_paths):
            path = futures_to_paths[future]
            print("executed in second", path)
            next_successors = list(self.graph.successors(path))
            if next_successors: #and no failure
                print(next_successors)
                self.recursive_applier(executor, next_successors, futures_to_paths)
            print("finished executing")

    # def apply(self, graph, nodes, executor, config_dict, debug: bool = False, print_only_changes: bool = False):
    #
    #     for node in nodes
    #         try:
    #             self._execute_entries(
    #                 command=self.command,
    #                 entries=nodes,
    #                 debug=debug,
    #                 executor=executor,
    #                 print_only_changes=print_only_changes,
    #             )
    #         except RuntimeError: #this is the if failed
    #             print("this one failed")
    #
    #         for node in nodes:
    #             successors = list(graph.successors(node))
    #             if successors:
    #                 self.apply(graph,successors,executor, debug, print_only_changes)
    #


    def execute(self, graph, node, num_parallel: int = 4, debug: bool = False, print_only_changes: bool = False):
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
    #
    # def apply_tester(self, executor):

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
