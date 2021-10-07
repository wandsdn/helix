#!/usr/bin/python

""" Topo module that defines the topo presented in the 'Fast-Failover and
Switchover for Link Failures and Congestion in SDN' paper (IEEE ICC 2016).

Topo Diagram:
    Networks/Diagram/MultiHostCompPaper.png
"""

# FIX IMPORT ISSUES CAUSED BY MININET
import sys, os
sys.path.append(os.path.abspath("."))
# -----------------------------------

from TopoBase import TopoBase
from mininet.link import TCLink


class NetTopo(TopoBase):
    """ Class that creates a TestNet topology."""


    def __init__(self, inNamespace=True):
        super(NetTopo, self).__init__("MultiHostCompPaper", inNamespace)


    def build(self):
        """ Build the test net topology """
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
        self.addLink(h4, s3, cls=TCLink, bw=1000)

        self.addLink(s1, s5, cls=TCLink, bw=1000)
        self.addLink(s1, s2, cls=TCLink, bw=1000)
        self.addLink(s5, s6, cls=TCLink, bw=1000)
        self.addLink(s5, s4, cls=TCLink, bw=1000)
        self.addLink(s6, s3, cls=TCLink, bw=1000)
        self.addLink(s2, s4, cls=TCLink, bw=1000)
        self.addLink(s2, s3, cls=TCLink, bw=600)


topos = {
    "topo": NetTopo
}
