"""Module containing the ApplyGraph class"""
import concurrent.futures
from typing import List, Dict, Set

import networkx

from terrawrap.utils.graph import find_source_nodes
from terrawrap.models.graph_entry import GraphEntry, NoOpGraphEntry, Entry


class ApplyGraph:
    """Class for representing an Apply Graph."""

    def __init__(self, command: str, graph: networkx.DiGraph, post_graph: List[str], prefix: str):
        """
        :param command: The Terraform command that this pipeline should execute.
        :param graph: The graph to be executed.
        :param post_graph: The list of items to be executed after the graph has been run.
        :param prefix: The prefix an item must match to be applied.
        """
        self.command = command
        self.graph = graph
        self.graph_dict: Dict[str, Entry] = {}
        self.post_graph = post_graph
        self.prefix = prefix
        self.not_applied: Set[str] = set()
        self.applied: Set[str] = set()
        self.failures: List[str] = []

    # pylint: disable=too-many-locals
    def execute_graph(self, num_parallel: int = 4, debug: bool = False, print_only_changes: bool = False):
        """
        Function for executing the graph. Will execute in parallel, up to the limit given in num_parallel.
        :param num_parallel: The number of pipeline entries to run in parallel.
        :param debug: True if Terraform debugging should be turned on.
        :param print_only_changes: True if only directories which contained changes should be printed.
        """
        sources = find_source_nodes(self.graph)
        futures_to_paths = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_parallel) as executor:
            for source in sources:
                entry = self._get_or_create_entry(source)

                future = executor.submit(entry.execute, self.command, debug=debug)
                futures_to_paths[future] = entry.path

            for future in concurrent.futures.as_completed(futures_to_paths):
                path = futures_to_paths[future]
                exit_code, stdout, changes_detected = future.result()

                if stdout and print_only_changes and not changes_detected:
                    stdout = ["No changes detected.\n"]

                print("Output for %s:\n\n%s\n" % (path, "".join(stdout).strip()))

                if exit_code != 0:
                    self.failures.append(path)

                successors = list(self.graph.successors(path))
                if successors:
                    self.recursive_executor(executor, successors, num_parallel, debug, print_only_changes)

        for node in self.graph:
            item = self.graph_dict.get(node)
            if not item:
                self.not_applied.add(node)
            elif item.state == "no-op":
                self.not_applied.add(item.path)
            else:
                self.applied.add(node)

    def recursive_executor(
            self,
            executor: concurrent.futures.Executor,
            successors: List[str],
            num_parallel: int,
            debug: bool,
            print_only_changes: bool):
        """
        Helper function for executing graph entries recursively
        :param executor: The Executor to use. See concurrent.futures.Executor.
        :param successors: A list of successors to be executed from the previous call
        :param num_parallel: The number of pipeline entries to run in parallel.
        :param debug: True if Terraform debugging should be turned on.
        :param print_only_changes: True if only directories which contained changes should be printed.
        """
        futures_to_paths = {}

        for node in successors:
            entry = self._get_or_create_entry(node)
            if entry.state != "Pending":
                continue
            if not self._can_be_applied(entry):
                continue

            future = executor.submit(entry.execute, self.command, debug=debug)
            futures_to_paths[future] = entry.path

        for future in concurrent.futures.as_completed(futures_to_paths):
            path = futures_to_paths[future]
            exit_code, stdout, changes_detected = future.result()

            if stdout and print_only_changes and not changes_detected:
                stdout = ["No changes detected.\n"]

            print("Output for %s:\n\n%s\n" % (path, "".join(stdout).strip()))
            if exit_code != 0:
                self.failures.append(path)

            next_successors = list(self.graph.successors(path))
            if next_successors:
                self.recursive_executor(
                    executor, next_successors, num_parallel, debug, print_only_changes
                )

    def execute_post_graph(
            self,
            num_parallel: int = 4,
            debug: bool = False,
            print_only_changes: bool = False):
        """
        Function for executing entries not in the graph in parallel.
        :param num_parallel: The number of pipeline entries to run in parallel.
        :param debug: True if Terraform debugging should be turned on.
        :param print_only_changes: True if only directories which contained changes should be printed.
        """
        futures_to_paths = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_parallel) as executor:
            for node in self.post_graph:
                entry = self._get_or_create_entry(node)

                future = executor.submit(entry.execute, self.command, debug=debug)
                futures_to_paths[future] = entry.path

            for future in concurrent.futures.as_completed(futures_to_paths):

                path = futures_to_paths[future]
                if self.graph_dict[path].state != "no-op":

                    exit_code, stdout, changes_detected = future.result()

                    if print_only_changes and not changes_detected:
                        stdout = ["No changes detected.\n"]

                    print("Output for %s:\n\n%s\n" % (path, "".join(stdout).strip()))

                    if exit_code != 0:
                        self.failures.append(path)

        for node in self.post_graph:
            item = self.graph_dict.get(node)
            if not item:
                self.not_applied.add(node)
            elif item.state == "no-op":
                self.not_applied.add(item.path)
            else:
                self.applied.add(node)

    def _can_be_applied(self, entry: GraphEntry):
        """
        Checks if an entry can be applied.
        :param entry: The entry to be tested.
        :return: A boolean False if the entry cannot be applied otherwise True.
        """
        if entry:
            path = entry.path
            predecessors = list(self.graph.predecessors(path))

            for predecessor in predecessors:
                pred_entry = self.graph_dict.get(predecessor)

                if pred_entry:
                    if pred_entry.state not in ("Success", "no-op"):
                        return False
                else:
                    return False

        else:
            return False

        return True

    def _get_or_create_entry(self, node: str):
        """
        Gets an entry from the graph dictionary or create it if it does not exist
        :param node: The node used to fetch the graph entry
        :return: The graph entry
        """
        if self.graph_dict.get(node):
            entry = self.graph_dict.get(node)
        else:
            if node.startswith(self.prefix):
                entry = GraphEntry(node, [])
            else:
                entry = NoOpGraphEntry(node, [])
            self.graph_dict[node] = entry
        return entry
