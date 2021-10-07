#!/usr/bin/python

""" Topo module that creates the topo created in GNS3 to compare SDN
performance with standard decentrilised MPLS TE performance.

Topo Diagram:
    Networks/Diagram/MPLSCompTopo.png
"""

# FIX IMPORT ISSUES CAUSED BY MININET
import sys, os
sys.path.append(os.path.abspath("."))
# -----------------------------------

from TopoBase import TopoBase
from mininet.link import TCLink


class NetTopo(TopoBase):
    """ Class that creates a MPLS Comparison Topo topology """


    def __init__(self, inNamespace=True):
        super(NetTopo, self).__init__("MPLSCompTopo", inNamespace)


    def build(self):
        # Create our hosts
        h1 = self.addHost("h1", inNamespace=self.inNamespace, ip="10.0.1.1/24")
        h2 = self.addHost("h2", inNamespace=self.inNamespace, ip="10.0.2.1/24")
        h3 = self.addHost("h3", inNamespace=self.inNamespace, ip="10.0.3.1/24")

        # Create OF switches
        s1 = self.addSwitch("s1")
        s2 = self.addSwitch("s2")
        s3 = self.addSwitch("s3")
        s4 = self.addSwitch("s4")
        s5 = self.addSwitch("s5")
        s6 = self.addSwitch("s6")
        s7 = self.addSwitch("s7")
        s8 = self.addSwitch("s8")
        s9 = self.addSwitch("s9")

        # Create links between network objs
        self.addLink(h1, s1, cls=TCLink, bw=1000)
        self.addLink(s1, s2, cls=TCLink, bw=1000)

        self.addLink(s2, s3, cls=TCLink, bw=1000)
        self.addLink(s2, s8, cls=TCLink, bw=1000)
        self.addLink(s8, s9, cls=TCLink, bw=1000)
        self.addLink(s9, h2, cls=TCLink, bw=1000)

        self.addLink(s3, s4, cls=TCLink, bw=1000)
        self.addLink(s3, s8, cls=TCLink, bw=1000)
        self.addLink(s4, s5, cls=TCLink, bw=1000)

        self.addLink(s5, s6, cls=TCLink, bw=1000)
        self.addLink(s6, s8, cls=TCLink, bw=100)
        self.addLink(s6, s7, cls=TCLink, bw=1000)
        self.addLink(s7, h3, cls=TCLink, bw=1000)


topos = {
    "topo": NetTopo
}
