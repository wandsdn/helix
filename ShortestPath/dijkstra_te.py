#!/usr/bin/python

import sys
import copy
from collections import deque, namedtuple

DEFAULT_COST = 100

class Graph():
    """ Graph class that holds topo info and allows computing shortest path
    using dijkstras algorithm.

    Topology:
        `:cls:attr:(topo)` contains port info that encodes links in topology. A link
        is made up of two port ends where src and dest info matches. It has the syntax:
            {src id: {
                    src port: {
                        dest: dest id,
                        destPort: dest port,
                        cost: cost,
                        speed: speed in bits,
                        total_stats: {
                            rx_packets: rx_packets,
                            rx_bytes: rx_bytes in bytes,
                            rx_errors: rx_errors,
                            rx_rate: rx_rate,
                            tx_packets: tx_packets,
                            tx_bytes: tx_bytes in bytes,
                            tx_errors: tx_errors,
                            tx_rate: tx_rate,
                        },
                        poll_stats: {
                            ... Same fields as total
                        }}}}

        'src id' and 'dest id' are either names or numeric DPID of switches.
        The 'total_stats' and 'poll_stats" dictionary entries are used to store
        port TE metrics. These dicts are and componenets added to the link entry
        only when TE info is set on the link (not present by default).

        Stat dict fields prefixed by 'rx_' stand for recived and 'tx_' tranmissited.

        A topo dict is used to gen a set of switches (vertex) and a list of ``Links``
        (verticies) tuples for dijkstra computation.

    Note (Topology):
        Hosts always have out port -1 to allow diferetiation from switches in topo.

    Links:
        Links from `:cls:attr:(links)` are encoded as a list of tuples in format
        (src id, dest id, cost). Links are computed only when `:cls:attr:topo_stale`
        flag is True, when calling ``shortest_path()``.

    Attributes:
        topo (dict): Topology of network graph
        topo_stale (bool): Flag that indicates if the topo needs to be recomputed
            before perorming a shortest path operation. This flag should be set when
            `:cls:atr:(topo)` is modified.
        sw (set of str): Switches in the topology (vertex)
        links (list of tuple): Links in the topology (verticies) ``Links``
        fixed_speed (dict): Dictionary of fixed speed ports. Format of dict:
            { sw: { port: speed in bits } }
    """

    def __init__(self, topo=None):
        """ Initiate a new graph instance. ``change_topo()`` is called with args
        `topo` to initiate our graph with link information (if specified)

        Args:
            topo (dict): Topology in format ``Topology``. Defaults to None.
        """
        self.sw = set()
        self.links = []
        self.fixed_speed = {}
        self.change_topo(topo)


    def _process_topo(self):
        """ Process `:cls:attr:(topo)` into a set of switches and a list of link
        tuples (in format ``Link``) if `:cls:attr:(topo_state)` is True.
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
            # XXX: Fixes issue #73. Do not process NULL ports
            if sw_id is None:
                continue

            for src_port,dst in sw_val.iteritems():
                # XXX: Fixes issue #73. Do not process NULL ports
                if dst["dest"] is None:
                    continue

                self.links.append((sw_id, dst["dest"], dst["cost"]))
                self.sw.add(dst["dest"])

            self.sw.add(sw_id)

        # Mark the topology as being processed (not stale)
        self.topo_stale = False


    def change_topo(self, topo=None):
        """ Change the graph topo information. If `topo` is None then this method
        will clear any existing topo info. Method always sests `:cls:attr(topo_stale)`
        to True (topology is stale so needs recomputation).

        Note:
            If the 'speed' or 'cost' dictionary entries are ommited in `topo` links
            these will be set to default values of 0 and `:mod:attr:(DEFAULT_COST)`.

            If the port details appear in `:cls:attr:(fixed_speed)`, the 'speed' of
            the port is set to this value (regardless if it's ignored or not)

        Args:
            topo (dict): New topology in format ``Topology``. Defaults to None.
        """
        if isinstance(topo, dict):
            self.topo = copy.deepcopy(topo)

            # Set any ommited link fields to default values
            for src,src_val in self.topo.iteritems():
                for port,port_val in src_val.iteritems():
                    if "speed" not in self.topo[src][port]:
                        self.topo[src][port]["speed"] = 0

                    # If port has a fixed speed set the ports speed to the fixed value
                    if src in self.fixed_speed and port in self.fixed_speed[src]:
                        self.topo[src][port]["speed"] = self.fixed_speed[src][port]

                    if "cost" not in self.topo[src][port]:
                        self.topo[src][port]["cost"] = DEFAULT_COST
        else:
            self.topo = {}

        self.topo_stale = True


    def add_link(self, src, dst, src_port, dst_port, cost=DEFAULT_COST):
        """ Add a new link to the topology. If `:cls:attr:(topo)` attribute was
        modified then `:cls:attr:(topo_stale)` is set to True.

        Args:
            src (obj): ID of link source node
            dst (obj): ID of link destination node
            src_port (obj): Port used by link on source node
            dst_port (obj): Port used by link on destination node
            cost (int): Cost of the link. Defaults to `:mod:attr:(DEFAULT_COST)`

        Returns:
            bool: True if a link was added or modified, False otherwise.
        """
        # Initiate the port and check if the link already exists
        self._init_port(src, src_port)
        if ((self.topo[src][src_port]["dest"] == dst) and
            (self.topo[src][src_port]["destPort"] == dst_port) and
            (self.topo[src][src_port]["cost"] == cost)):
            return False

        # Modify the link details and mark the topo as stale
        self.topo[src][src_port]["dest"] = dst
        self.topo[src][src_port]["destPort"] = dst_port
        self.topo[src][src_port]["cost"] = cost
        self.topo_stale = True
        return True


    def _init_port(self, src, src_port):
        """ Initiate a new port dictionary entry if one dosen't exist for `src` and `src_port`.

        Args:
            src (obj): Source ID of the switch
            src_port (obj): Source switch port number
        """
        if src not in self.topo:
            self.topo[src] = {}

        if src_port not in self.topo[src]:
            # If the port has a fixed speed set it to that value
            speed = 0
            if src in self.fixed_speed and src_port in self.fixed_speed[src]:
                speed = self.fixed_speed[src][src_port]

            self.topo[src][src_port] = {
                "dest": None, "destPort": None, "cost": DEFAULT_COST, "speed": speed
            }


    def update_port_info(self, src, src_port, speed=None, rx_packets=None, rx_bytes=None,
                        rx_errors=None, tx_packets=None, tx_bytes=None, tx_errors=None,
                        tx_rate=None, rx_rate=None, addr=None, eth_addr=None, is_total=True):
        """ Update port info and stats counts in topology. Method will initiate a new blank
        port if `src` and `src_port` do not exist in `:cls:attr:(topo)`. Any optional fields
        with null values are ommited (not set).

        Attr:
            src (obj): Source ID of the link
            src_port (obj): Source port of link
            speed (int): Optional Speed of port in bits. Defaults to None
            tx_* (int): Optional port transmit stats. Defaults to None
            rx_* (int): Optional port recive stats. Defaults to None
            addr (str): Optional address of the host i.e. destination. Defaults to None
            eth_addr (str): Optional ethernet address of a host. Defaults to None
            is_total (bool): Flag that indicates if the tx and rx counts are for
                the total stats field (true) or the for the current poll fields (False).
                Defaults to True (apply tx and rx counts to totals).
        """
        # Make sure the port is initiated and exists in the topo
        self._init_port(src, src_port)

        # Update the port info attributes specified
        d = self.topo[src][src_port]
        if speed is not None:
            # Set the ports speed if the port dosen't have a fixed speed specifie
            if not src in self.fixed_speed or not src_port in self.fixed_speed[src]:
                d["speed"] = speed

        if addr is not None:
            d["address"] = addr
        if eth_addr is not None:
            d["eth_address"] = eth_addr

        # If we have no stats update just exit early
        if (rx_packets is None and rx_bytes is None and rx_rate is None and
                tx_packets is None and tx_bytes is None and tx_rate is None):
            return

        # Initiate and select what stats we are setting
        if is_total == True:
            if "total_stats" not in d:
                d["total_stats"] = {}
            d = d["total_stats"]
        else:
            if "poll_stats" not in d:
                d["poll_stats"] = {}
            d = d["poll_stats"]

        if rx_packets is not None:
            d["rx_packets"] = rx_packets
        if rx_bytes is not None:
            d["rx_bytes"] = rx_bytes
        if rx_errors is not None:
            d["rx_errors"] = rx_errors
        if rx_rate is not None:
            d["rx_rate"] = rx_rate
        if tx_packets is not None:
            d["tx_packets"] = tx_packets
        if tx_bytes is not None:
            d["tx_bytes"] = tx_bytes
        if tx_errors is not None:
            d["tx_errors"] = tx_errors
        if tx_rate is not None:
            d["tx_rate"] = tx_rate


    def get_port_info(self, src, src_port):
        """ Return port info by retriving link details from `:cls:attr:(topo)`.

        Args:
            src (obj): ID of the source switch to get the port info of
            src_port (obj): Port of the source switch to get the info of

        Returns:
            dict: Link info dict or None if link dosen't exist.
        """
        if (src not in self.topo or src_port not in self.topo[src]):
            return None
        return self.topo[src][src_port]


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

        # Validate the destination details of the link
        if ((not dst == self.topo[src][src_port]["dest"]) or
                (not dst_port == self.topo[src][src_port]["destPort"])):
            return False

        # Remove the link and set the topology as stale
        self.topo_stale = True
        del self.topo[src][src_port]
        return True


    def remove_host_link(self, src, src_port):
        """ Remove a host link from the topology where switch `src` connects
        to a host via port `src_port`. Both ends of the link will be deleted
        (switch to host and host to switch).

        Args:
            src (int): Source ID of the switch connecting to the host
            src_port (int): Port number of the switch connecting to the host

        Returns:
            str: Host name if link exists or None if link can't be found.
        """
        # Try to find the link port and make sure its for a host
        if src not in self.topo:
            return None
        if src_port not in self.topo[src]:
            return None
        if not self.topo[src][src_port]["destPort"] == -1:
            return None

        # Delete the switch end of the link and make topo stale
        self.topo_stale = True
        host = self.topo[src][src_port]["dest"]
        del self.topo[src][src_port]

        # Remove the host port part of the link if it exists
        if host in self.topo and -1 in self.topo[host]:
            del self.topo[host][-1]

        # Delete the node if it has no more ports
        if len(self.topo[host]) == 0:
            del self.topo[host]

        return host


    def remove_switch(self, id):
        """ Remove a switch from the topology. This method will search through
        `:cls:attr:(topo)` and remove all links that connect to or from the specified
        switch.

        Args:
            id (obj): ID of switch (vertex) to remove

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
                # If the switch is part of the link add it for removal
                if val["dest"] == id:
                    delete.append((s_id,port))
                    changed = True
                    self.topo_stale = True

        for d in delete:
            del self.topo[d[0]][d[1]]

        # Return weather or not a change was performed
        return changed


    def remove_host(self, host):
        """ Remove a host from the topology. This method will search through
        `:cls:attr:(topo)` and remove all links that connect a host to a specific
        switch.

        Args:
            host (obj): Name of the host to remove

        Returns:
            bool: True if the host was found and removed, False otherwise
        """
        # If the host dosen't exist in the topo can't delete anything
        if host not in self.topo or -1 not in self.topo[host]:
            return False

        # Go through the hosts ports and remove both ends of the link
        for h_port,h_data in self.topo[host].items():
            self.remove_host_link(h_data["dest"], h_data["destPort"])

        self.topo_stale = True
        return True


    def get_switches(self):
        """ Retrieve a list of all switches from `:cls:attr:(topo)`. A node is a switch
        if it's destination port, or source, is not -1.

        Returns:
            list of int: List of switch DPIDs currently present in the topology
        """
        switches = set()
        for sw_id,sw_val in self.topo.iteritems():
            for src_port,dst in sw_val.iteritems():
                # If the destination is unkown or we have a host (do not add to sw list)
                if dst["dest"] is None or dst["destPort"] == -1:
                    continue
                switches.add(dst["dest"])


            if sw_id is not None and -1 not in sw_val:
                switches.add(sw_id)

        # Convert the set of switches to a list and return it
        return list(switches)


    def change_cost(self, src, dst, src_port, dst_port, cost=DEFAULT_COST):
        """ Change hte cost of a link in our topology. Method searches through
        `:cls:attr:(topo)` to find the ports of a link. If they exist the cost
        of both ports (bidirectiona) will be set to `cost` and `:cls:attr:(topo_stale)`
        set to True.

        Note:
            This method will modify the cost of the link in both dirrections.
            i.e. updating cost of S1(1) to S3(2) will also update cost of
            S3(2) to S1(1) if it exists.

        Args:
            src (obj): Source ID of link
            dst (obj): Destination ID of link
            src_port (obj): Source port of link
            dst_port (obj): Destination port of link
            cost (int): Cost of link, defaults to `:mod:attr:(DEFAULT_COST)`
        """
        if (src not in self.topo or src_port not in self.topo[src] or
                not dst == self.topo[src][src_port]["dest"] or
                not dst_port == self.topo[src][src_port]["destPort"]):
            return

        self.topo[src][src_port]["cost"] = cost
        self.topo_stale = True

        # Check if the reverse exists and if it does update the cost
        if (dst not in self.topo or dst_port not in self.topo[dst] or
                not src == self.topo[dst][dst_port]["dest"] or
                not src_port == self.topo[dst][dst_port]["destPort"]):
            return

        self.topo[dst][dst_port]["cost"] = cost


    def find_ports(self, src_id, dst_id):
        """ Find a port pair that connects two switches in `:cls:attr:(topo)`.
        Method finds the ports used by a link between `src_id` and `dst_id`

        Args:
            src_id (obj): Source ID of link to find port of
            dst_id (obj): Destination ID of link to find port of

        Returns:
            tuple: Port pair of the link in the format (src_port, dst_port) or
                None if we couldn't find a link between `src_id` and `dst_id`.
        """
        if (src_id not in self.topo):
            return None

        for key,val in self.topo[src_id].iteritems():
            if (val["dest"] == dst_id):
                return (key,val["destPort"])
        return None


    def flows_for_path(self, path):
        """ Generate an array of flow rule port map tuples for a path. This
        method translates a network path into a list of tuples which need
        to be installed into the network switches to implement the path.

        Note:
            The destination will not be included in the returned list and if
            the source is a host it will be ommited as well (port is -1). If
            the source is a switch it will be added to the list with a 'in_port'
            of -1.

        Args:
            path (list of obj): List of switches for path

        Returns:
            list of tuples: Flow rule instruction to install path in the format
            (switch id, in_port, out_port) or empty list if path invalid
        """
        res = []

        # Iterate through the path array of tuples
        for i in range(len(path)-1):
            if i == 0:
                ports = self.find_ports(path[i], path[i+1])
                if ports[0] == -1:
                    continue

                res.append((path[i], -1, ports[0]))
                continue

            ports1 = self.find_ports(path[i-1], path[i])
            ports2 = self.find_ports(path[i], path[i+1])

            # If no ports could be found, invalid path
            if ports1 is None:
                raise Exception("Invalid path ... can't find correct ports for %s %s" % (
                    path[i-1], path[i]))
                return []
            if ports2 is None:
                raise Exception("Invalid path ... can't find correct ports for %s %s" % (
                    path[i], path[i+1]))
                return []

            # Add the flow rule tuples to the result (sw id, in_port, out_port)
            res.append((path[i], ports1[1], ports2[0]))
        return res


    def shortest_path(self, src, dest, logger=None):
        """ Compute the shortest path from `src` to `dest` using dijkstras algorithm.
        Both `src` and `dest` have to be valid nodes otherwise a empty list is returned.
        If `:cls:attr:(topo_stale)` is True ``_process_topo()`` method will be called.

        Note:
            The algorithm uses cost/distance as the main metric in finding the shortest
            path and node name ordering as a tie breaker if two potential nodes have the
            same cost. i.e. node_a < node_b.

        Args:
            src (obj): Start of the path (switch or host)
            dest (obj): Destination of the path (switch or host)
            logger (Logger): Output debug and error info if provided (defaults
                to None).

        Returns:
            list of obj: Nodes in the path or empty list if path can't be computed
        """
        if self.topo_stale == True:
            self._process_topo()

        # Check if the src and dest exist (i.e. we can compute a path)
        if src not in self.sw:
            if logger is not None:
                logger.critical("SRC %s not in sw list (comp path)" % src)
            return []
        if dest not in self.sw:
            if logger is not None:
                logger.critical("DEST %s not in sw list (comp path)" % dest)
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
                    # Check if the new node distance is better or its ID is
                    # lower, if so update the previous node
                    if alt < dist[v] or (alt == dist[v] and u < prev[v]):
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
        "p1": {-1: {"dest": 1, "destPort": 1}},
        1: {1: {"dest": "p1", "destPort": -1},
            2: {"dest": 2, "destPort": 1},
            3: {"dest": 4, "destPort": 1}},
        2: {1: {"dest": 1, "destPort": 2},
            2: {"dest": 3, "destPort": 1},
            3: {"dest": 4, "destPort": 2},
            4: {"dest": 5, "destPort": 1}},
        3: {1: {"dest": 2, "destPort": 2},
            3: {"dest": 5, "destPort": 2},
            2: {"dest": "d1", "destPort": -1}},
        4: {1: {"dest": 1, "destPort": 3},
            2: {"dest": 2, "destPort": 3},
            3: {"dest": 5, "destPort": 3}},
        5: {1: {"dest": 2, "destPort": 4},
            2: {"dest": 3, "destPort": 3},
            3: {"dest": 4, "destPort": 3}},
        "d1": {-1: {"dest": 3, "destPort": 2}}
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
