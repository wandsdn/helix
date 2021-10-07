#!/usr/bin/python

""" Topo module that defines a simple mininet topo made up of two hosts and 6
swtiches. Topo is an extended version of ```TestNet.py```.

Usage:
    sudo mn --custom ExtendedTestNet.py --topo topo --switch ovs --mac --controller
    remote,ip=127.0.0.1

Topo Diagram:
    Networks/Diagram/ExtendedTestNet.png
"""

# FIX IMPORT ISSUES CAUSED BY MININET
import sys, os
sys.path.append(os.path.abspath("."))
# -----------------------------------

from TopoBase import TopoBase


class NetTopo(TopoBase):
    """ Class that creates an Extended Test Net topology."""


    def __init__(self, inNamespace=True):
        super(NetTopo, self).__init__("ExtendedTestNet", inNamespace)


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

        self.addLink(h1, s1)
        self.addLink(s1, s2)
        self.addLink(s1, s4)
        self.addLink(s1, s6)

        self.addLink(s2, s3)
        self.addLink(s2, s4)
        self.addLink(s2, s5)

        self.addLink(s3, h2)
        self.addLink(s3, s5)
        self.addLink(s3, s6)

        self.addLink(s4, s5)
        self.addLink(s4, s6)

        self.addLink(s5, s6)


topos = {
    "topo": NetTopo
}
