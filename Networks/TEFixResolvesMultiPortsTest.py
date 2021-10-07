#!/usr/bin/python

""" Topo module mnade up of multiple hosts which is designed to test
behaivour and fix for considering if swapping a path will fix multiple
over-util ports (TE).

For more info refer to the 'Swap Fixes Multiple Over-Util Ports' document:
    Docs/SwapFixesMultipleOverUtilPorts.md

Topo Diagram:
    Networks/Diagram/TEFixResolvesMultiPortsTest.png
"""

# FIX IMPORT ISSUES CAUSED BY MININET
import sys, os
sys.path.append(os.path.abspath("."))
# -----------------------------------

from TopoBase import TopoBase
from mininet.link import TCLink


class NetTopo(TopoBase):
    """ Class that creates a TE Fix Resolves Multiple Ports Test topo. """


    def __init__(self, inNamespace=True):
        super(NetTopo, self).__init__("TEFfixResolvesMultiPortsTest", inNamespace)


    def build(self):
        # Create our hosts
        h1 = self.addHost("h1", inNamespace=self.inNamespace, ip="10.0.1.1/24")
        h2 = self.addHost("h2", inNamespace=self.inNamespace, ip="10.0.2.1/24")
        h3 = self.addHost("h3", inNamespace=self.inNamespace, ip="10.0.3.1/24")
        h4 = self.addHost("h4", inNamespace=self.inNamespace, ip="10.0.4.1/24")

        # Create OF switches
        s1 = self.addSwitch("s1")
        s2 = self.addSwitch("s2")
        s3 = self.addSwitch("s3")
        s4 = self.addSwitch("s4")
        s5 = self.addSwitch("s5")
        s6 = self.addSwitch("s6")

        # Create links between network objs
        self.addLink(h1, s1, cls=TCLink, bw=1000)
        self.addLink(h2, s1, cls=TCLink, bw=1000)
        self.addLink(h3, s1, cls=TCLink, bw=1000)

        self.addLink(s1, s2, cls=TCLink, bw=200)
        self.addLink(s2, s3, cls=TCLink, bw=200)

        self.addLink(s1, s4, cls=TCLink, bw=1000)
        self.addLink(s4, s5, cls=TCLink, bw=1000)
        self.addLink(s5, s6, cls=TCLink, bw=1000)
        self.addLink(s6, s3, cls=TCLink, bw=1000)

        self.addLink(s3, h4, cls=TCLink, bw=1000)


topos = {
    "topo": NetTopo
}
