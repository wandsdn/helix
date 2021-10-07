#!/usr/bin/python

""" Topo mod that defines a a topo with 2 hosts and 6 switches. This is an
extended version of 'ExtendedTestNet' topo.

Topo Diagram:
    Networks/Diagram/TestPathSpliceFixNet.py
"""

# FIX IMPORT ISSUES CAUSED BY MININET
import sys, os
sys.path.append(os.path.abspath("."))
# -----------------------------------

from TopoBase import TopoBase


class NetTopo(TopoBase):
    """ Class that creates a Test Path Splice Fix topology. """


    def __init__(self, inNamespace=True):
        super(NetTopo, self).__init__("TestPathSpliceFixNet", inNamespace)


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
        s8 = self.addSwitch("s8")

        self.addLink(h1, s1)
        self.addLink(s1, s2)
        self.addLink(s1, s4)
        self.addLink(s1, s8)

        self.addLink(s2, s3)
        self.addLink(s2, s4)
        self.addLink(s2, s5)

        self.addLink(s3, h2)
        self.addLink(s3, s5)
        self.addLink(s3, s8)

        self.addLink(s4, s5)
        self.addLink(s4, s6)

        self.addLink(s5, s7)
        self.addLink(s6, s7)
        self.addLink(s6, s8)
        self.addLink(s7, s8)

        """ OpenFlow port configuration
            Name(Port) - Name(Port)
              1(2)     -    2(1)
              1(3)     -    4(1)
              1(4)     -    6(1)
            ***********************
              2(1)     -    1(2)
              2(2)     -    3(1)
              2(3)     -    4(2)
              2(4)     -    5(1)
            ***********************
              3(1)     -    2(2)
              3(3)     -    5(2)
              3(4)     -    6(2)
            ***********************
              4(1)     -    1(3)
              4(2)     -    2(3)
              4(3)     -    5(3)
              4(4)     -    6(3)
            ***********************
              5(1)     -    2(4)
              5(2)     -    3(3)
              5(3)     -    4(3)
              5(4)     -    6(4)
            ***********************
              6(1)     -    1(4)
              6(2)     -    3(4)
              6(3)     -    4(4)
              6(4)     -    5(4)
        """


topos = {
    "topo": NetTopo
}
