#!/usr/bin/python

""" Topo mod that defines a topo which will encounter a lopp when links
2-3, 3-4, 6-4 and 7-4 fail. The loop will occur in the ring 3-5-7-6.

Topo Diagram:
    Networks/Diagram/LoopTest.png
"""

# FIX IMPORT ISSUES CAUSED BY MININET
import sys, os
sys.path.append(os.path.abspath("."))
# -----------------------------------

from TopoBase import TopoBase


class NetTopo(TopoBase):
    """ Class that creates a Loop Test topology """


    def __init__(self, inNamespace=True):
        super(NetTopo, self).__init__("LoopTestNet", inNamespace)


    def build(self):
        # Create our hosts
        h1 = self.addHost("h1", inNamespace=self.inNamespace)
        h2 = self.addHost("h2", inNamespace=self.inNamespace)

        # Create a OF switch
        s1 = self.addSwitch("s1")
        s2 = self.addSwitch("s2")
        s3 = self.addSwitch("s3")
        s4 = self.addSwitch("s4")
        s5 = self.addSwitch("s5")
        s6 = self.addSwitch("s6")
        s7 = self.addSwitch("s7")

        self.addLink(h1, s1)
        self.addLink(s1, s2)

        self.addLink(s2, s3)
        self.addLink(s2, s5)

        self.addLink(s3, s5)
        self.addLink(s3, s6)
        self.addLink(s3, s4)

        self.addLink(s4, h2)
        self.addLink(s4, s6)
        self.addLink(s4, s7)

        self.addLink(s5, s7)
        self.addLink(s7, s6)


topos = {
    "topo": NetTopo
}
