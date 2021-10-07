#!/usr/bin/python

""" Topo module that defines a k-ary FatTree topo. A Fat Tree topo is very
commonly found in data centers (DC) networks as it can scale to large sizes
and is well suited for dealing with congestion. It's made up of:

    core sw ---> aggregation sw ---> edge sw ---> Pods (hosts/leafs)

    Pods           - consisnts of (k/2)^2 hosts, 2 layers of k/2 SW
    Edge SW        - connects to k/2 hosts, k/2 aggregation SW
    Aggregation SW - connects to k/2 edges, k/2 core SW
    Cored SW       - (k/2)^2 SW each connecting to k pods of hosts

Note:
    Pods are made up of ``pods of hosts`` numbered of switches. This
    topo will have only two hosts, h1 and h2 where h1 is connected to
    the first sw in por 1 and h2 to the last sw in last pod.

SW Naming Convetion:
    sw<num> where num is a unique number of the sw. Switches in the
    core are numbered first, followed by each pod, sequentially starting
    from aggregate and edge then going to the next pod.

Usage:
    sudo mn --custom FatTreeNet.py --topo topo,k=<k_order> --switch ovs --mac
    --controller remote,ip=127.0.0.1

    Creates a fat-tree topology of k_order

Topo Diagram:
    Networks/Diagram/FatTreeNet.png
"""

# FIX IMPORT ISSUES CAUSED BY MININET
import sys, os
sys.path.append(os.path.abspath("."))
# -----------------------------------

from TopoBase import TopoBase


class NetTopo(TopoBase):
    """ Class that created a k-arry FatTree topo with two hosts.

    Attributes:
        k (int): K attribute of FatTree topology (size)
        CID (int): Current ID of switches (used to generate names)
    """


    def __init__(self, k=4, inNamespace=True):
        """ Initiate the topology and validate the arguments """
        self.k = k
        self.CID = 1

        if (not k >= 0) or (not k % 2 == 0):
            raise Exception("K has to be a non-negative multiple of two integer!")

        super(NetTopo, self).__init__("FatTree", inNamespace)


    def _genSWName(self):
        """ Generate the name of a fat tree switch. Method will sequentially
        generate the switches based on `:cls:attr:(CID)`.

        Returns:
            str: Name of switch in format sw<num> where num is the CID number.
        """
        name = "sw%d" % self.CID
        self.CID += 1
        return name


    def build(self):
        """ Construct the k-ary fat tree topology """
        # Create our hosts
        h1 = self.addHost("h1", inNamespace=self.inNamespace)
        h2 = self.addHost("h2", inNamespace=self.inNamespace)

        # Calculate the topology cherecteristics
        numPods = self.k
        numEdge = self.k/2
        numAggr = numEdge
        numCore = pow((self.k/2), 2)

        # Temporary array of initiated switches
        swCore = []
        swAggr = []
        swEdge = []

        # Initiate the core switches
        for core in range(numCore):
            swCore.append(self.addSwitch(self._genSWName()))

        # Initiate the aggregation switches
        for pod in range(numPods):
            for aggr in range(numAggr):
                aggrSW = self.addSwitch(self._genSWName())
                swAggr.append(aggrSW)

                # Connect the aggregation to the core switches
                for core in range(numEdge*aggr, numEdge*(aggr+1)):
                    self.addLink(aggrSW, swCore[core])

            # Initiate the edge switches
            for edge in range(numEdge):
                edgeSW = self.addSwitch(self._genSWName())
                swEdge.append(edgeSW)

                # Connect the edge switch to the aggregation switches
                for aggr in range(numAggr):
                    self.addLink(edgeSW, swAggr[aggr+(pod*numAggr)])

        # Connect the two hosts to the first and final pod
        self.addLink(h1, swEdge[0])
        self.addLink(h2, swEdge[len(swEdge)-1])


topos = {
    "topo": NetTopo
}
