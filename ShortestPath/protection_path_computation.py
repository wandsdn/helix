#!/usr/bin/python

# --------------------------------------------------------------
#
# This script provides methods that allow computation of protection
# scheme group table entries and path splices from a topology Graph
# object.
#
# Please note that the method compute_path should be implemeneted
# in the controller to install the required group rules and flow
# rules into the switches. The implementation in this module are
# for demonstration and testing purposes only.
#
# Usage:
#   ./splicing_path_compute_test.py
#
# ---------------------------------------------------------------


def link_in_path(src, dst, path, unidirect=True):
    """ Check if link (`src`, `dst`) exists in `path`. If `unidrect` is True,
    method also checks if (`dst`, `src`) exists as well (assume links are not
    multidirect).

    TODO:
        This method may be movable into the disjktra module, however
        it may also be very specific to the current implementation
        of the dynamic proactive controller. Consider if we will move it.

    Args:
        src (str): ID of switch at start of link
        dst (str): ID of switch at end of link
        path (list of str): Path to search for link

    Returns:
        bool: True if link exists in `path`, or false otherwise.
    """
    for i in range(len(path) - 1):
        if path[i] == src:
            if path[i+1] == dst:
                return True

        if unidirect and path[i] == dst:
            if path[i+1] == src:
                return True
    return False


def gen_splice(path_primary, path_secondary, g):
    """ Generate a path splice from `path_primary` to `path_secondary`.
    A path splice is defined as the shortest and most optimal path from a
    unique node in `path_primary` to any unique node in `path_secondary`.
    A unique node is a node that is only present in `path_primary` but not
    in `path_secondary`.

    Note:
        An optimal path is a path that has the shortest length. If there are
        multiple paths with the same short length, we will use paths that
        place us closer to the destination in the `path_secondary`.

    Args:
        path_primary (list of str): Primary path to find splices from
        path_secondary (list of str): Secondary path to find splices to
        g (ShortPath.dijkstra.Graph): Topology object to use when finding
            path splice

    Retruns:
        dict: Path splice ports for each unique switch in `path_primary`
        in the format: {id: [path]}.
    """
    # Generate the array of switches that we need to find path splices from
    search = []
    for node in path_primary:
        # XXX: IGNORE ANY TEMPORARY NODES ADDED FOR INTER- AREA PATHS
        if isinstance(node, str) and node.startswith("*"):
            continue
        if node not in path_secondary:
            search.append(node)

    splice = {}
    # Find the shortet path splicing node, currently based on size of path
    for sw in search:
        shortest = []
        shortest_proximity = 10000

        for sw_sec in path_secondary:
            # XXX: IGNORE ANY TEMPORARY NODES ADDED FOR INTER- AREA PATHS
            if isinstance(sw_sec, str) and sw_sec.startswith("*"):
                continue

            # Do not compute a path splice to oursevels or a path splice
            # to a node that is found in the primary path (i.e. secondary and
            # primary path overlap).
            if (sw == sw_sec or sw_sec in path_primary):
                continue

            # Try to find the path between the nodes and check if
            # shortest path
            path = g.shortest_path(sw, sw_sec)

            # Find the proximity of the splice to the destination
            prox = 10000
            for i in range(len(path_secondary)):
                if path_secondary[i] == path[len(path)-1]:
                    prox = len(path_secondary)-i-1
                    break

            # Check if the new path is more better than the old one
            if (
                (len(shortest) == 0) or
                (len(shortest) > len(path)) or
                (len(shortest) == len(path) and prox < shortest_proximity)
            ):
                shortest = path
                shortest_proximity = prox

        if len(shortest) > 0:
            splice[sw] = shortest

    return splice


def gen_splice_loose(path_primary, path_secondary, g):
    """ Generate a set of path splices between `path_primary` to
    `path_secondary`. A path splice is defined as the shortest path between
    unique nodes in the primary path to unique nodes in the secondary path,
    such that the exit of the splice is closest to the destination.

    Note: The lose path splice method extends the set of potential splice
    source and destination nodes with adjacent nodes to unique segments in
    the primary path. If the splice uses a link already used in the primary
    path, this splice is not considered (using such a splice will cause the
    switch to no longer forward based on the group table). If the exit node
    of the splice if further away from the destination, the path splice is
    invalid and not considered.

    TODO FIXME: Ignore temporary nodes added for inter-area paths ...

    Args:
        path_primary (list of str): Primary path, start nodes of splices
        path_secondary (list of str): Secondary path, end nodes of splices
        g (Graph): Topology object to use when computing path splices

    Returns:
        dict: Path splices where key represents the node the splice is for
        and the value is a list of nodes (path), {"node": [path]}.
    """
    # Generate a list of unique nodes in the primary path and nodes which
    # are adjacent to unique segments (loose path splice only)
    adj_search = []
    search = []
    found_start = False
    for i in range(len(path_primary)):
        node = path_primary[i]
        if node not in path_secondary:
            # Found unique node in primary path
            search.append(node)

            if found_start == False:
                # Found the start of a unique segment, add the adjacent
                # node to the set and flag that we are in a unique segment
                found_start = True
                if i > 0:
                    adj_search.append(path_primary[i-1])
        else:
            if found_start == True:
                # This is an adjacent node, subsequent node was part of
                # unique sequence and current node not unique. Add to set
                found_start = False
                adj_search.append(path_primary[i])

    # Convert to set (disregard duplicates)
    search_set = set(search)
    search_set.update(adj_search)
    splice = {}

    # Iterate through the nodes we need to compute splices from (source)
    for sw in search_set:
        shortest = []
        shortest_proximity = 10000
        #print("SEARCH SW %s" % sw)

        # Go through nodes in the secondary path to find splice destinations
        for sw_sec in path_secondary:
            # Do not compute a path splice to ourselves or to a non unique
            # node in the primary path. Allow computing to adjacent nodes.
            if sw == sw_sec or (sw_sec in path_primary and
                                        sw_sec not in adj_search):
                #print("\tDISREGARD DEST: %s" % sw_sec)
                continue

            #print("\tNODE_OK %s %s" % (sw, sw_sec))

            # Try compute the shortest path between the nodes
            path = g.shortest_path(sw, sw_sec)

            # Check if any links are part of the primary or secondary path
            invalid_link = False
            for i in range(len(path)-1):
                node_a = path[i]
                node_b = path[i+1]
                if (link_in_path(node_a, node_b, path_primary) or
                        link_in_path(node_a, node_b, path_secondary)):
                    invalid_link = True
                    break

            if invalid_link:
                continue

            #print("\tVALID SPLICE %s" % path)

            spl_exit_ind = path_secondary.index(path[-1])
            spl_exit_prox = len(path_secondary) - spl_exit_ind - 1
            #print("\t\tPROX %s" % (spl_exit_prox))

            # If start is in secondary path (i.e. adjacent nod), check if
            # splice backtracks, goes back on the secondary path
            if sw in path_secondary:
                #print("\t\tSplice start in secondary path, check backtrack")
                spl_start_ind = path_secondary.index(path[0])
                if spl_exit_ind < spl_start_ind:
                    #print("\t\tSplice backtracks, disregard ...")
                    continue

            # Check if the new path is more better than the old one
            if (
                (len(shortest) == 0) or
                (len(shortest) > len(path)) or
                (len(shortest) == len(path) and spl_exit_prox < shortest_proximity)
            ):
                shortest = path

        if len(shortest) > 0:
            splice[sw] = shortest

    #print("\n")
    return splice


def increase_used_edge_cost(graph, ports):
    """ Increase the cost of links in path `ports`. Method should be used
    when computing minimally overlapping paths.

    Args:
        graph (ShortestPath.dikstra.Graph): Topology
        ports (list of triple): Nodes of path to increase links
    """
    for i in range(len(ports)-1):
        src = ports[i][0]
        dst = ports[i+1][0]
        src_port = ports[i][2]
        dst_port = ports[i+1][1]
        graph.change_cost(src, dst, src_port, dst_port, 100000)


def find_path(src, dest, graph, graph_sec=None, logger=None):
    """ Compute a primary and secondary path between `src` to `dest` in
    topology `graph`. Method computes two shortest minimally overlapping paths.
    A minimally overlapping secondary path is computed by setting the weights
    of links used in the primary path to large values and recomputing the path.
    Modifying the weights forces the secondary path to try and avoid using the
    same links from the secondary path. After computing the second path, the
    weights used in the second path are set to large values as well.

    Note:
        Method will modify the link weights of `graph`. If `graph_sec` is not
        null, the weights of `graph_sec` are increased while `graph` is not
        modified (due to the methods implementation). Link weights are
        increased by calling ``increase_used_edge_cost``.

    Args:
        src (str): Source node of paths
        dest (str): Destination node of paths
        graph (Graph): Topology graph to use when computing paths
        graph_sec (Graph): Optional topology graph to use for computing the
            secondary path. Defaults to null (use `graph` to compute both
            primary and secondary path).


    Returns:
        list of str, list of str, list of triple, list of trile: List of nodes
            in the primary path, list of nodes in the secondary, list of port
            triples in format (node, in port, out port) in the primary and
            secondary path.
    """
    # Compute the primary path
    path_primary = graph.shortest_path(src, dest, logger)
    ports_primary = graph.flows_for_path(path_primary)

    # If the secondary graph not specified use the primary graph to compute the
    # secondary path and increment
    if graph_sec is None:
        graph_sec = graph

    # Increment the edges used and compute the secondary path
    increase_used_edge_cost(graph_sec, ports_primary)

    path_secondary = graph_sec.shortest_path(src, dest)
    ports_secondary = graph_sec.flows_for_path(path_secondary)

    # Increment edges used by the secondary path and return result
    increase_used_edge_cost(graph_sec, ports_secondary)
    return path_primary, path_secondary, ports_primary, ports_secondary


def group_table_to_path(path_info, graph, ingress, old=None, swap=None, egress=None):
    """ Go through the groups of `path_info` to work out the primary path traffic uses
    to reach a destination. The path starts at the `ingress` switch and ends once a
    source switch no longer exists in the group table. Note, a switch that leads to
    nothing is considered invalid and will cause the method to exist early. If both
    `swap` and `old` are not null, the method re-computes the current path from
    `swap` prepending `old` to the computed path.

    XXX FIXME: `egress` seems to not be used

    Args:
        path_info (dict): Path information dictionary
        graph (Graph): Topology of the network
        ingress (obj): Ingress of the path
        old (list of triples): Old path to re-use. Defaults null (compute entire path)
        swap (triple): Triple of node, current port and candidate port. Defaults to null
            (do not swap and just compute the primary path)

    Returns:
        list of triples: (From Switch, To Switch, Port) or None if path is invalid or
            has a loop in it.
    """
    gp = path_info["groups"]
    if len(gp) == 0:
        # XXX: When we have two hosts on the same switch, gp is empty so
        # this method returns null for the path.
        return None

    sw_from = ingress
    sw_to = None
    sw_visited = []
    port = None
    path = []

    # If this is a inter domain link (tuple) clean the from switch before
    # using it
    if isinstance(ingress, tuple):
        sw_from = ingress[0]
    if isinstance(egress, tuple):
        egress = egress[0]

    # If the old path and swap node were provided use the path up to the swap node.
    found_swap = False
    if old is not None and swap is not None:
        for p in old:
            sw_visited.append([0])
            if p[0] == swap[0]:
                sw_from = p[0]
                found_swap = True
                break
            path.append(p)

    if not found_swap:
        path = []

    # Find the remainder of the path up to the egress
    while sw_from is not None:
        # Check if we have to swap the nodes or use the first
        if swap is not None and swap[0] == sw_from:
            if not swap[1] == gp[sw_from][0] or not swap[2] in gp[sw_from]:
                raise Exception("GP to path error at sw %s, current port %s or swap port %s not in gp %s"
                    % (sw_from, swap[1], swap[2], gp[sw_from]))
            port = swap[2]
        else:
            # If the group is empty or switch dosen't exist in group table try the special flows
            if sw_from not in gp or len(gp[sw_from]) == 0:
                if sw_from in path_info["special_flows"]:
                    pt = None
                    for flow in path_info["special_flows"][sw_from]:
                        if flow[0] == port:
                            pt = flow[1]
                            break
                    # If the special flows don't match return None, invalid path
                    if pt is None:
                        raise Exception("Found abrupt end %s | %s | %s | %s" % (path_info, sw_from, port, path))
                        return None
                else:
                    # If there is no valid special flow entry just return that the path seems to be invalid
                    raise Exception("CAN'T FIND CONNECTION %s | %s | %s | %s" % (path_info, sw_from, port, path))
                    return None
            else:
                port = gp[sw_from][0]

        # Get the port info to find the destination
        sw_to = graph.get_port_info(sw_from, port)
        if sw_to is None:
            # TODO FIXME: What is this used for, why partial paths ????
            # XXX: Fix for YATES-interface, if a path has no to (i.e. inter-domain without
            # a destination) just exit processing and return the path up to this point.
            # This should not break anything else, it simply allows returning partial paths
            # which is required for the interface processing!
            return None
            break

        # Add the next hop in the path
        port_to = sw_to["destPort"]
        sw_to = sw_to["dest"]
        path.append((sw_from, sw_to, port))

        # Check if we have already visisted the next switch and advance to next switch
        if sw_to in sw_visited:
            return None
        sw_from = sw_to
        if (sw_from not in gp and sw_from not in path_info["special_flows"]):
            sw_from = None

        # XXX: Port will become destination port for next iteration
        port = port_to

        # Append the next switch to the switches visited
        sw_visited.append(sw_from)

    return path


# --------------------------------------------------------------------
# Test methods start here. The following methods are used for demonstration
# purposes and to test the functionality of this script.
# --------------------------------------------------------------------

def compute_paths(hosts, topo_dict):
    """ Compute paths between the provided `hosts` using the fast-failover
    group. Each host will receive a unique VLAN tag ID. The VLAN tag is the
    index of the host in the array. The bridge dirrectly connected to the
    host, will pop and push VLAN tags.

    Note:
        This method should be implemented in the controller to install the
        group and flow rules into the switches. This provided implementation
        is just for testing purposes.

    Args:
        hosts (list of str): Hosts to compute paths between
    """
    for i in range(len(hosts)):
        host_1 = hosts[i]
        for host_2 in hosts:
            # Do not compute a path to the same host
            if host_1 == host_2:
                continue

            print("Hosts", host_1, host_2)
            graph = Graph(topo_dict)
            path_primary, path_secondary, ports_primary, ports_secondary = find_path(
                host_1, host_2, graph)

            print("PATH PRIMARY", path_primary)
            print("PATH SECOND", path_secondary)
            print("PORTS PRIMARY", ports_primary)
            print("PORTS SECOND", ports_secondary)

            # Find the path splices
            splice = gen_splice(path_primary, path_secondary, graph)
            splice.update(gen_splice(path_secondary, path_primary, graph))

            # Generate the group rules bucket port for each switch
            group_table = {}
            for port in ports_primary:
                # if the switch is not in the dict initiate it
                if port[0] not in group_table:
                    group_table[port[0]] = []

                # If we alredy have the port as a bucket, we are done
                if port[2] not in group_table[port[0]]:
                    group_table[port[0]].append(port[2])

            for port in ports_secondary:
                if port[0] not in group_table:
                    group_table[port[0]] = []

                if port[2] not in group_table[port[0]]:
                    group_table[port[0]].append(port[2])

            # Iterate through the path splices
            for sw,sp in splice.iteritems():
                ports = graph.flows_for_path(sp)
                # Go through the ports of the path splicing
                for port in ports:
                    if port[0] not in group_table:
                        group_table[port[0]] = []

                    if port[2] not in group_table[port[0]]:
                        group_table[port[0]].append(port[2])

            print("SPLICES:%s" % splice)
            print("GROUP_TABLE: %s" % group_table)

            # Work out VLAN tagging scheme
            print("\nVLAN %s" % (i+1))
            print("\tTag at sw %s" % path_primary[1])


            last_sw = path_primary[len(path_primary)-2]
            last_sw_out_port =  graph._find_ports(last_sw, host_2)[0]
            print("\tPop at sw %s and output port %s" % (last_sw,last_sw_out_port))
            print("\n")


if __name__ == "__main__":
    # Modify the import searchpath to load the modules from outside the
    # tools folder
    import sys
    import os
    sys.path.append(os.path.abspath(".."))

    # Import the graph object
    from ShortestPath.dijkstra import Graph

    net_topo = {
        "p1": {-1: (1, 1)},      # Fake add the source host in our topo
        1: {1: ("p1", -1), 2: (2, 1), 3: (4, 1)},
        2: {1: (1, 2), 2: (3, 1), 3: (4, 2), 4: (5, 1)},
        3: {1: (2, 2), 3: (5, 2), 2: ("d1", -1)},
        4: {1: (1, 3), 2: (2, 3), 3: (5, 3)},
        5: {1: (2, 4), 2: (3, 3), 3: (4, 3)},
        "d1": {-1: (3, 2)}        # Fake add the destination host in our topo
    }

    compute_paths(["p1", "d1"], net_topo)
