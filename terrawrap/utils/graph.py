""" Holds graph utilities"""

import os
from typing import List, Tuple, Any
import networkx


def has_cycle(graph: networkx.DiGraph) -> bool:
    """
    Checks that a graph does not contain a cycle.
    :param graph: The graph to check
    :return: A boolean true if there is a cycle.
    """
    sources = find_source_nodes(graph)
    if not sources:
        return True

    try:
        for source in sources:
            cycle = networkx.find_cycle(graph, source)
            if cycle:
                print(cycle)
                return True
    except networkx.NetworkXNoCycle:
        return False

    return False


def find_source_nodes(graph: networkx.DiGraph) -> List[str]:
    """
    For a given graph return a list of source nodes (Nodes with no predecessors)
    :param graph: The graph to look for source nodes in.
    :return: source_nodes -  a list of nodes (str) in the graph with no predecessors
    """
    source_nodes = []
    for node in graph:
        preds = list(graph.predecessors(node))
        if preds:
            continue
        source_nodes.append(node)

    return source_nodes


def successors(depth: int, node: str, graph: networkx.DiGraph) -> Tuple[int, str, List[str]]:
    """
    For a given node in a given graph, return the node with it's successors.
    :param depth: The current depth of the successors
    :param node: The node to obtain successors for
    :param graph: The graph to query for successors
    :return: successors -  a tuple containing a node and a list of its successors
    """
    node_successors = (depth, node, list(graph.successors(node)))
    return node_successors


def generate_dependencies(nodes: List[str], graph: networkx.DiGraph) -> List[Any]:
    """
    Creates a list of dependencies for a graph which
    contains lists of tuples with a node its depth and its successors
    :param nodes: A list of nodes
    :param graph: A graph containing dependency information
    :return: A list of all dependency information in the graph
    """
    dependencies = []
    depth = 1
    for node in nodes:
        path = []
        node_successors = successors(depth, node, graph)
        path.append(node_successors)
        if node_successors[1]:
            generate_helper(node_successors[2], graph, depth + 1, path)
        dependencies.append(path)
    return dependencies


def generate_helper(nodes: List[str], graph: networkx.DiGraph, depth: int, path: List[Any]) -> List[str]:
    """
    The recursive helper function for generate_dependencies
    :param nodes: A list of nodes
    :param graph: The graph to search
    :param depth: The current depth
    :param path: The current path the dependencies are on
    :return: THe updated path the dependencies are in.
    """
    for node in nodes:
        node_successors = successors(depth, node, graph)
        path.append(node_successors)
        if node_successors[1]:
            generate_helper(node_successors[2], graph, depth + 1, path)
    return path


def visualize(dependencies: List[List[str]]):
    """
    For a given graph, generate a human readable output
    :param dependencies: A list of paths for a graph
    """
    for path in dependencies:
        depth = 0
        for node in path:
            tab_spacing = int(node[0]) - 1 + depth
            if depth > 0:
                print()
            relative_node = node[1].replace(os.getcwd(), "")
            print(("\t" * tab_spacing) + ">", relative_node)
        depth += 1
