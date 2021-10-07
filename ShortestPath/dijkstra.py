#!/usr/bin/python

import sys
import copy
from collections import deque, namedtuple

class Graph():
    """ Graph class that holds topology information and allows computation of
    shortest path using dijkstras algorithm.

    Topology:
        The topology (`topo` module attribute) is encoded as a dictionary that
        has the following syntax:
            {
            src id: {
                    port: (dest id, dest port, cost)
                }
            }
        The src and dest id are vertix names from the `:cls:attr:(sw)`.
        A topology dict is used to generate a set of switches and a list of
        ``Link`` tuples. The dict tells us what destination a port on a switch
        can reach.

    Note (Topology):
        The 'cost' of the link is optional and may be ommited in the tuple. If
        the tuple has a length of 2 the ``Link`` generated will default to a
        cost of 100. Otherwise the cost of the tuple is used if the size is 3.

        The hosts need to have out port values of -1 to allow us to differeiante
        them from switches.

    Link:
        Links from `:cls:attr:(links)` are encoded as a list of tuples that
        take the format: (src id, dst id, cost). The links are computed if the
        `:cls:attr:topo_stale` flag is True, when performing a shortest path
        computation.

    Attributes:
        topo (dict): Topology of network graph
        topo_stale (bool): Flag that indicates if the topo needs to be
            recomputed before perorming a shortest path operation. This flag
            should be set when `:cls:atr:(topo)` is modified.
        sw (set of str): Switches in the topology (vertex)
        links (list of tuple): Links in the topology (verticies)
    """

    def __init__(self, topo=None):
        """ Initiate a new graph object instance. If `topo` is not None then
        `:cls:attr:(topo)` will be set as a copy of `topo`. Otherwise
        `:cls:attr:(topo)` is set to an empty dict.

        Args:
            topo (dict, optional): topology of graph in format
                ``Topology``. Defaults to None
        """
        # If the topology is a dictionary make a copy of it and set
        # the topo as stale
        if isinstance(topo, dict):
            self.topo = copy.deepcopy(topo)
            self.topo_stale = True
        # Otherwise initiate a empty dictionary as the topology
        else:
            self.topo = {}
            self.topo_stale = False

        self.link_count = 0
        self.sw = set()
        self.links = []


    def _process_topo(self):
        """ Process the current topology, if `:cls:attr:(topo_stale)` is true,
        into a set of switches (vertexes) and a list of link tuples (verticies).

        This method should only be called when `:cls:attr:(topo_stale)` is
        True. Refer to ``Link`` for the syntax of the generate link tuples.

        Note:
            If `:cls:attr:(topo)` tuple has a length of 2 elements (i.e. no cost)
            the cost of the new ``Link`` defaults to 100. Otherwise the cost is
            set to the cost element of the tuple if its of size 3.
        """
        # If the topology is not stale do not re-process the topology
        if self.topo_stale == False:
            return

        # Clear the set of switches and links array
        self.sw = set()
        self.links = []

        # Generate the link array as a list of tuples made up
        # of (src switch id, des switch id, cost)
        for sw_id,sw_val in self.topo.iteritems():
            for src_port,dst in sw_val.iteritems():
                cost = (dst[2] if len(dst) == 3 else 100)
                self.links.append((sw_id, dst[0], cost))
                self.sw.add(dst[0])

            self.sw.add(sw_id)

        # Mark the topology as being processed (not stale)
        self.topo_stale = False


    def change_topo(self, topo=None):
        """ Change the topology of a dictionary of the graph with a new topology
        object. If `topo` is None then this method will set `:cls:attr:(topo)`
        to an empty dictionary (i.e. clear topology). Method always sets
        `:cls:attr:(topo_stale)`to False.

        Args:
            topo (dict, optional): New topology in format ``Topology``.
                Defaults to None.
        """
        if isinstance(topo, dict):
            self.topo = copy.deepcopy(topo)
        else:
            self.topo = {}

        self.topo_stale = True


    def add_link(self, src, dst, src_port, dst_port, cost=100):
        """ Add a new link to the topology. If the link dosen't currently exist in
        the topology `:cls:attr:(link_count)` is incremented. If `:cls:attr:(topo)`
        attribute was modified then `:cls:attr:(topo_stale)` is set to True.

        Args:
            src (str): ID of link source node
            dst (str): ID of link destination node
            src_port (int): Port used by link on source node
            dst_port (int): Port used by link on destination node
            cost (int, optional): Cost of the link. Defaults to 100

        Returns:
            bool: True if a link was added or modified, False otherwise.
        """
        # If we are adding a new source make a dictionary for the destinations
        if src not in self.topo:
            self.topo[src] = {}

        # If the new entry is not a modification do not re-add it
        if (
            (src_port in self.topo[src]) and
            (self.topo[src][src_port] == (dst, dst_port, cost))
        ):
            return False

        if (src_port not in self.topo[src]):
            self.link_count += 1

        # Modify the topology, mark it as stale and increment the link count if
        # a new link was added
        self.topo[src][src_port] = (dst, dst_port, cost)
        self.topo_stale = True
        return True


    def remove_port(self, src, dst, src_port, dst_port):
        """ Remove a port from the topology. If the specified port exists, it will be
        deleted from `:cls:attr:(topo)` and `:cls:attr:(topo_stale)` set to True.

        Args:
            src (obj): Source ID of link to remove
            dst (obj): Destination ID of link to remove
            src_port (int): Source port of link to remove
            dst_port (int): Destination port of link to remove

        Returns:
            bool: True if a port was removed, False otherwise
        """
        if src not in self.topo:
            return False
        if src_port not in self.topo[src]:
            return False

        # Validate that the other end details are the same. If they differ
        # do not delete the port
        if (
            (not dst == self.topo[src][src_port][0]) or
            (not dst_port == self.topo[src][src_port][1])
        ):
            return False

        # Decrement the count, set as stale and remove the port
        self.link_count -= 1
        self.topo_stale = True
        del self.topo[src][src_port]
        return True


    def remove_switch(self, id):
        """ Remove a switch from the topology. This method will search through
        `:cls:attr:(topo)` and remove all links that connect to or from the specified
        switch. The method will automatically decrement `:cls:attr:(link_count)` when
        links are removed.

        Args:
            id (str): ID of switch (vertex) to remove

        Returns:
            bool: True if the switch was found and removed, False otherwise
        """
        changed = False
        # Check if the ID is a major src switch (if so delete it)
        if id in self.topo:
            del self.topo[id]
            cahnged = True
            self.topo_stale = True

        # Iterate through all switches and ports
        delete = []
        for s_id,s_ports in self.topo.iteritems():
            for port,val in s_ports.iteritems():
                # If the switch is part of this link delete it
                if val[0] == id:
                    delete.append((s_id,port))
                    changed = True
                    self.topo_stale = True

        for d in delete:
            del self.topo[d[0]][d[1]]
            self.link_count -= 1

        # Return weather or not a change was performed
        return changed


    def change_cost(self, src, dst, src_port, dst_port, cost=100):
        """ Change the cost of a link in our topology. Method will search through
        `:cls:attr:(topo)` to find a link. If the link dosen't exist in
        `:cls:attr:(topo)` method will terminate early, otherwise the cost is
        updated and `:cls:attr:(topo_stale)` set to True.

        Note:
            This method will modify the cost of the link in both dirrections.
            i.e. updating cost of S1(1) to S3(2) will also update cost of
            S3(2) to S1(1) if it exists.

        Args:
            src (str): Source ID of link
            dst (str): Destination ID of link
            src_port (str): Source port of link
            dst_port (str): Destination port of link
        """
        if (src not in self.topo or src_port not in self.topo[src] or
                not dst == self.topo[src][src_port][0] or
                not dst_port == self.topo[src][src_port][1]):
            return

        self.topo[src][src_port] = (dst, dst_port, cost)
        self.topo_stale = True

        # Check if the reverse exists and if it does add the cost
        if (dst not in self.topo or dst_port not in self.topo[dst] or
                not src == self.topo[dst][dst_port][0] or
                not src_port == self.topo[dst][dst_port][1]):
            return

        self.topo[dst][dst_port] = (src, src_port, cost)
        self.topo_stale = True


    def num_links(self):
        """ Get the number of links in the topology.

        Returns:
            int: number of links in the topology of the graph
        """
        return self.link_count


    def _find_ports(self, src_id, dst_id):
        """ Find a port pair that connects two switches in `:cls:attr:(topo)`.
        Method finds the ports used by a link between `src_id` and `dst_id`

        Args:
            src_id (str): Source ID of link to find port of
            dst_id (str): Destination ID of link to find port of

        Returns:
            tuple: Port pair of the link in the format (src_port, dst_port) or
            None if we couldn't find a link between `src_id` and `dst_id`.
        """
        if (src_id not in self.topo):
            return None

        for key,val in self.topo[src_id].iteritems():
            if (val[0] == dst_id):
                return (key,val[1])
        return None


    def flows_for_path(self, path):
        """ Generate an array of flow rule port map tuples for a path. This
        method translates a network path into a list of tuples which need
        to be installed into the network switches to implement the path.

        Note:
            The `dst` will not be included in ``Returns`` list. If `src` has a
            undefined out port/is a host (i.e. -1) it will not be included in
            the ``Returns`` list. Otherwise we will add it to the list with a
            'in_port' value of -1 to indicate that it dosen't have a 'in-port'
            for the `path`.

            This method will assume that all hosts to switch connections will
            define port -1 as their out port.

        Args:
            path (list of str): path of switches

        Returns:
            list of tuples: Flow rule instruction to install path in the format
            (switch id, in_port, out_port) or None if path is invalid.
        """
        res = []

        # Iterate through the path array of tuples
        for i in range(len(path)-1):
            if i == 0:
                ports = self._find_ports(path[i], path[i+1])
                if ports[0] == -1:
                    continue

                res.append((path[i], -1, ports[0]))
                continue

            ports1 = self._find_ports(path[i-1], path[i])
            ports2 = self._find_ports(path[i], path[i+1])

            # If no ports could be found, invalid path
            if ports1 is None:
                print("Invalid path ... can't find correct ports for %s %s" % (
                    path[i-1], path[i]))
                return []
            if ports2 is None:
                print("Invalid path ... can't find correct ports for %s %s" % (
                    path[i], path[i+1]))
                return []

            # Add the flow rule tuples to the result (sw id, in_port, out_port)
            res.append((path[i], ports1[1], ports2[0]))
        return res


    def shortest_path(self, src, dest):
        """ Compute the shortest path from `src` to `dest` using dijkstras algorithm.
        Both `src` and `dest` have to be valid nodes, otherwise an exception is raised.

        If `:cls:attr:(topo_stale)` is True ``_process_topo()`` method will be called.

        Args:
            src (str): Switch ID for start of path
            dest (str): Switch ID for end of path

        Returns:
            list of str: Nodes in the path. Empty list if path can't be found
        """
        if self.topo_stale == True:
            self._process_topo()

        # Check if the src and dest exist (i.e. we can compute a path)
        if src not in self.sw:
            return []
        if dest not in self.sw:
            return []

        try:
            # Create a set of switches to process
            q = self.sw.copy()

            # Initiate the cost array to infinity
            dist = {s: sys.maxint for s in self.sw}
            # Initiate the previous node in optimal path to none
            prev = {s: None for s in self.sw}
            # Set the cost of the start node to 0
            dist[src] = 0

            # Create a set of neighbours
            neighbours = {s: set() for s in self.sw}
            for start, end, cost in self.links:
                neighbours[start].add((end, cost))

            # While Q is not empty
            while q:
                # get the node with the least distance
                u = min(q, key=lambda s: dist[s])
                q.remove(u)

                # If the cost is inf or we have reached our destination
                if dist[u] == sys.maxint or u == dest:
                    break

                # For all of the neighbours fo the link
                for v, cost in neighbours[u]:
                    alt = dist[u] + cost
                    # If a shortest path was found
                    if alt < dist[v]:
                        dist[v] = alt
                        prev[v] = u

            # Get the shortest path as from start to end
            s = deque()
            u = dest
            while prev[u]:
                s.appendleft(u)
                u = prev[u]
            s.appendleft(u)
        except Exception:
            return []

        # Return the path or a empty list if the src or dst is not in the result
        res = list(s)
        if src not in res or dest not in res:
            return []
        return res


if __name__ == "__main__":
    g = Graph({
        "p1": {-1: (1, 1)},      # Fake add the source host in our topo
        1: {1: ("p1", -1), 2: (2, 1), 3: (4, 1)},
        2: {1: (1, 2), 2: (3, 1), 3: (4, 2), 4: (5, 1)},
        3: {1: (2, 2), 3: (5, 2), 2: ("d1", -1)},
        4: {1: (1, 3), 2: (2, 3), 3: (5, 3)},
        5: {1: (2, 4), 2: (3, 3), 3: (4, 3)},
        "d1": {-1: (3, 2)}        # Fake add the destination host in our topo
    })

    # Compute two test paths from the two hosts
    path = g.shortest_path("p1","d1")
    print("Shortest Path: %s" % path)
    ports = g.flows_for_path(path)
    for sw in ports:
        print("\tSwitch ID: %s SRC PORT: %s (DST PORT %s)" % (sw[0], sw[1], sw[2]))

    path = g.shortest_path("d1","p1")
    print("Shortest Path: %s" % path)
    ports = g.flows_for_path(path)
    for sw in ports:
        print("\tSwitch ID: %s SRC PORT: %s (DST PORT %s)" % (sw[0], sw[1], sw[2]))
