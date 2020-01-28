"""Module containing the Pipeline class"""
import concurrent.futures
from typing import Iterable, Optional, List, DefaultDict


from terrawrap.utils.graph import find_source_nodes
from terrawrap.models.graph_entry import GraphEntry


class ApplyGraph:
    """Class for representing a pipeline."""

    def __init__(self, command: str, graph, post_graph, prefix):
        """
        :param command: The Terraform command that this pipeline should execute.
        :param pipeline_path: Path to the Terrawrap pipeline file. Can be absolute or relative from where
        the script is executed.
        """
        self.command = command
        self.reverse_pipeline = command == 'destroy'
        self.graph = graph
        self.graph_dict = {}
        self.post_graph = post_graph
        self.prefix = prefix
        self.not_applied = set()
        self.failures = []


    def apply_graph(self, num_parallel: int = 4, debug: bool = False, print_only_changes: bool = False):
        """
        Function for executing the pipeline. Will execute each sequence separately, with the entries inside
        each sequence being executed in parallel, up to the limit given in num_parallel.
        :param num_parallel: The number of pipeline entries to run in parallel.
        :param debug: True if Terraform debugging should be turned on.
        :param print_only_changes: True if only directories which contained changes should be printed.
        """
        sources = find_source_nodes(self.graph)
        futures_to_paths = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_parallel) as executor:
            for source in sources:
                entry = self._get_entry(source)
                if not self._has_prefix(entry):
                    print(entry.path, "is not a prefix")
                    future = executor.submit(entry.no_op)
                    futures_to_paths[future] = entry.path
                    continue

                print("Executing %s %s ..." % (entry.path, self.command))
                future = executor.submit(entry.execute, self.command, debug=debug)
                futures_to_paths[future] = entry.path

            for future in concurrent.futures.as_completed(futures_to_paths):
                path = futures_to_paths[future]
                if self.graph_dict.get(path).state != "no-op":
                    exit_code, stdout, changes_detected = future.result()

                    if print_only_changes and not changes_detected:
                        stdout = ["No changes detected.\n"]

                    print("\nFinished executing %s %s ..." % (path, self.command))
                    print("Output:\n\n%s\n" % "".join(stdout).strip())

                    if exit_code != 0:
                        self.failures.append(path)

                successors = list(self.graph.successors(path))
                if successors:
                    self.recursive_applier(executor, successors, num_parallel, debug, print_only_changes)

        for node in self.graph:
            item = self.graph_dict.get(node)
            if not item:
                self.not_applied.add(node)
                print("This path was not run %s", node)
            else:
                if item.state == "no-op":
                    self.not_applied.add(item)
        #print("printing not applied list")

        for apply in self.not_applied:
            if self.graph_dict.get(apply):
                applier = self.graph_dict.get(apply).path
            else:
                applier = apply.path
            print(applier, "in not applied")

        if self.failures:
            raise RuntimeError(
                "The follow pipeline entries failed with command '%s':\n%s" % (self.command, "\n".join(self.failures))
            )

    def recursive_applier(self, executor, successors, num_parallel: int, debug: bool, print_only_changes: bool):
        futures_to_paths = {}

        for node in successors:
            entry = self._get_entry(node)
            if entry.state is not "Pending":
                print(entry.path, "is state", entry.state)
                continue
            if not self.can_be_applied(entry):
                continue

            if not self._has_prefix(entry):
                future = executor.submit(entry.no_op)
                futures_to_paths[future] = entry.path
                continue

            future = executor.submit(entry.execute, self.command, debug=debug)
            futures_to_paths[future] = entry.path

        for future in concurrent.futures.as_completed(futures_to_paths):

            path = futures_to_paths[future]
            if self.graph_dict.get(path).state != "no-op":
                exit_code, stdout, changes_detected = future.result()

                if print_only_changes and not changes_detected:
                    stdout = ["No changes detected.\n"]

                print("\nFinished executing %s %s ..." % (path, self.command))
                print("Output:\n\n%s\n" % "".join(stdout).strip())
                if exit_code != 0:
                    self.failures.append(path)

            next_successors = list(self.graph.successors(path))
            if next_successors:
                self.recursive_applier(executor, next_successors, num_parallel, debug, print_only_changes)

    def can_be_applied(self, entry):
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
            print(entry, "is not in dict")
            return False

        return True

    def apply_post_graph(self, num_parallel: int = 4, debug: bool = False, print_only_changes: bool = False):
        futures_to_paths = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_parallel) as executor:
            for node in self.post_graph:
                entry = self._get_entry(node)
                if not self._has_prefix(entry):
                    future = executor.submit(entry.no_op)
                    futures_to_paths[future] = entry.path
                    continue

                future = executor.submit(entry.execute, self.command, debug=debug)
                futures_to_paths[future] = entry.path

            for future in concurrent.futures.as_completed(futures_to_paths):

                path = futures_to_paths[future]
                if self.graph_dict.get(path).state != "no-op":

                    exit_code, stdout, changes_detected = future.result()

                    if print_only_changes and not changes_detected:
                        stdout = ["No changes detected.\n"]

                    print("\nFinished executing %s %s ..." % (path, self.command))
                    print("Output:\n\n%s\n" % "".join(stdout).strip())

                    if exit_code != 0:
                        self.failures.append(path)


        for node in self.post_graph:
            item = self.graph_dict.get(node)
            if not item:
                self.not_applied.add(node)
            else:
                if item.state == "no-op":
                    self.not_applied.add(item)

    def _get_entry(self, node):
        if self.graph_dict.get(node):
            entry = self.graph_dict.get(node)
        else:
            entry = GraphEntry(node, [])
            self.graph_dict[node] = entry
        return entry

    def _has_prefix(self, entry):
        if not entry.path.startswith(self.prefix):
            return False
        return True
