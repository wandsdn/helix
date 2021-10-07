#!/usr/bin/python

""" Topo module that defines a topology made up of two hosts and a single
switch.

Topo Diagram:
    Networks/Diagram/Simple.png
"""

# FIX IMPORT ISSUES CAUSED BY MININET
import sys, os
sys.path.append(os.path.abspath("."))
# -----------------------------------

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

topos = {
    "topo": NetTopo
}
