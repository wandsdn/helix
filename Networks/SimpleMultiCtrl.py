#!/usr/bin/python

""" Topo module that defines a topology made up of two hosts a single switch
and 3 controllers with IPs 127.0.0.{1-3}. This module uses the same topology
defined in ```Simple.py```.

Topo Diagram:
    Networks/Diagram/Simple.png
"""

# FIX IMPORT ISSUES CAUSED BY MININET
import sys, os
sys.path.append(os.path.abspath("."))
# -----------------------------------

from mininet.node import RemoteController

from TopoBase import TopoBase


class NetTopo(TopoBase):
    """ Class that creates a Simple topology."""


    def __init__(self, inNamespace=True):
        super(NetTopo, self).__init__("TestNet", inNamespace)


    def build(self):
        """ Build the test net topology """
        # Create our hosts
        h1 = self.addHost("h1", inNamespace=self.inNamespace)
        h2 = self.addHost("h2", inNamespace=self.inNamespace)

        # Create a OF switch
        s1 = self.addSwitch("s1")

        # XXX: OVS switch dosen't work in namespace so switches
        # have to be exposed (inNamespace=True)
        self.addLink(h1, s1)
        self.addLink(s1, h2)

    def pre_net_start(self, net):
        """ Add controllers before the topology starts """
        c1 = net.addController("c1", controller=RemoteController, ip="127.0.0.1", port=6633)
        c2 = net.addController("c2", controller=RemoteController, ip="127.0.0.2", port=6633)
        c3 = net.addController("c3", controller=RemoteController, ip="127.0.0.3", port=6633)


topos = {
    "topo": NetTopo
}
