#!/usr/bin/python

""" Topo module that defines a simple topology made up of 5 switches and
two hosts.

Topo Diagram:
    Networks/Diagram/TestNet.png
"""

# FIX IMPORT ISSUES CAUSED BY MININET
import sys, os
sys.path.append(os.path.abspath("."))
# -----------------------------------

from TopoBase import TopoBase


class NetTopo(TopoBase):
    """ Class that creates a TestNet topology."""


    def __init__(self, inNamespace=True):
        super(NetTopo, self).__init__("TestNet", inNamespace)


    def build(self):
        """ Build the test net topology """
        # Create our hosts
        h1 = self.addHost("h1", inNamespace=self.inNamespace)
        h2 = self.addHost("h2", inNamespace=self.inNamespace)

        # Create a OF switch
        s1 = self.addSwitch("s1")
        s2 = self.addSwitch("s2")
        s3 = self.addSwitch("s3")
        s4 = self.addSwitch("s4")
        s5 = self.addSwitch("s5")

        # XXX: OVS switch dosen't work in namespace so switches
        # have to be exposed (inNamespace=True)
        self.addLink(h1, s1)
        self.addLink(s1, s2)
        self.addLink(s1, s4)

        self.addLink(s2, s3)
        self.addLink(s2, s4)
        self.addLink(s2, s5)

        self.addLink(s3, h2)
        self.addLink(s3, s5)

        self.addLink(s4, s5)


topos = {
    "topo": NetTopo
}
