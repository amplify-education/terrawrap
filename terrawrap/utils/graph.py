""" """
import os

def find_source_nodes(graph):
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
        else:
            source_nodes.append(node)

    return source_nodes


def successors(count, node, graph):
    """
    For a given node in a given graph, return the node with it's successors.
    :param node: The node to obtain successors for
    :param graph: The graph to query for successors
    :return: successors -  a tuple containing a node and a list of its successors
    """
    node_successors = (count, node, list(graph.successors(node)))
    return node_successors


def generate_dependencies(nodes, graph):
    dependencies = []
    count = 1
    for node in nodes:
        path = []
        node_successors = successors(count, node, graph)
        path.append(node_successors)
        if node_successors[1]:
            recursive_dependency_helper(node_successors[2], graph, count+1, path)
        dependencies.append(path)
    return dependencies


def recursive_dependency_helper(nodes, graph, count, path):
    for node in nodes:
        node_successors = successors(count, node, graph)
        path.append(node_successors)
        if node_successors[1]:
            recursive_dependency_helper(node_successors[2], graph, count+1, path)
    return path


def visualize(dependencies, count):
    """
    For a given graph, generate a human readable output
    :param dependencies: A list of paths for a graph
    """
    for path in dependencies:
        for node in path:
            tab_spacing = int(node[0]) -1 + count
            if count > 0:
                print()
            relative_node = node[1].replace(os.getcwd(), "")
            print(("\t"*tab_spacing)+">", relative_node)
        count += 1
