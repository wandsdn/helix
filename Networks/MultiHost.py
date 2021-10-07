#!/usr/bin/python

""" Topo module that has 4 host nodes and 4 switches. All links have a 2ms
latency and 1000Mbps badnwdith (expect for S2-S3 which is 100Mpbs).

Topo Diagram:
    Networks/Diagram/MultiHost.png
"""

# FIX IMPORT ISSUES CAUSED BY MININET
import sys, os
sys.path.append(os.path.abspath("."))
# -----------------------------------

from TopoBase import TopoBase
from mininet.link import TCLink


class NetTopo(TopoBase):
    """ Class that creates a Multi Host topology. """


    def __init__(self, inNamespace=True):
        super(NetTopo, self).__init__("MultiHost", inNamespace)


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

        # Create links between network objs
        self.addLink(h1, s1, cls=TCLink, bw=1000, delay='2ms')
        self.addLink(s1, s2, cls=TCLink, bw=1000, delay='2ms')
        self.addLink(s1, s4, cls=TCLink, bw=1000, delay='2ms')

        self.addLink(s2, h2, cls=TCLink, bw=1000, delay='2ms')
        self.addLink(s2, s3, cls=TCLink, bw=100, delay='2ms')
        self.addLink(s2, s4, cls=TCLink, bw=1000, delay='2ms')

        self.addLink(s3, h3, cls=TCLink, bw=1000, delay='2ms')
        self.addLink(s3, s4, cls=TCLink, bw=1000, delay='2ms')

        self.addLink(s4, h4, cls=TCLink, bw=1000, delay='2ms')


topos = {
    "topo": NetTopo
}
