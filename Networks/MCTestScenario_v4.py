#!/usr/bin/python

""" Topology that deploys multiple domains and controllers, used to
test TE optimisation. This file is used for the scenarios outlined in
the Multi Domain Controller Scenario Document.

Controller Config File: MDC_Scenario_Config/c*_v4.conf
Port Description File : MDC_Scenario_Config/c*_v4.csv

Topo Diagram:
    Networks/Diagram/MultiDomainController_v4.png
"""

# FIX IMPORT ISSUES CAUSED BY MININET
import sys, os
sys.path.append(os.path.abspath("."))
# -----------------------------------

from mininet.node import RemoteController, OVSSwitch
from TopoBase import TopoBase, CustomCtrlSw
from mininet.link import TCLink


class NetTopo(TopoBase):
    """ Class that creates a Simple topology."""


    def __init__(self, inNamespace=True):
        super(NetTopo, self).__init__("TestNet", inNamespace)


    def build(self):
        """ Build the test net topology """
        # Create our hosts
        h1 = self.addHost("h1", inNamespace=self.inNamespace)
        h2 = self.addHost("h2", inNamespace=self.inNamespace)
        h8 = self.addHost("h8", inNamespace=self.inNamespace)

        # Create a OF switch
        s1 = self.addSwitch("s1", cls=CustomCtrlSw)
        s2 = self.addSwitch("s2", cls=CustomCtrlSw)
        s3 = self.addSwitch("s3", cls=CustomCtrlSw)
        s4 = self.addSwitch("s4", cls=CustomCtrlSw)
        s5 = self.addSwitch("s5", cls=CustomCtrlSw)
        s6 = self.addSwitch("s6", cls=CustomCtrlSw)
        s7 = self.addSwitch("s7", cls=CustomCtrlSw)
        s8 = self.addSwitch("s8", cls=CustomCtrlSw)
        s9 = self.addSwitch("s9", cls=CustomCtrlSw)
        s10 = self.addSwitch("s10", cls=CustomCtrlSw)
        s11 = self.addSwitch("s11", cls=CustomCtrlSw)
        s12 = self.addSwitch("s12", cls=CustomCtrlSw)
        s13 = self.addSwitch("s13", cls=CustomCtrlSw)
        s14 = self.addSwitch("s14", cls=CustomCtrlSw)
        s15 = self.addSwitch("s15", cls=CustomCtrlSw)

        # Connect the switches to the hosts
        self.addLink(h1, s1)
        self.addLink(h2, s2)
        self.addLink(h8, s8)


        # Connect the controllers together
        self.addLink(s1, s2, cls=TCLink, bw=1000)
        self.addLink(s1, s3, cls=TCLink, bw=1000)
        self.addLink(s2, s3, cls=TCLink, bw=1000)

        self.addLink(s4, s5, cls=TCLink, bw=1000)
        self.addLink(s4, s6, cls=TCLink, bw=1000)
        self.addLink(s5, s6, cls=TCLink, bw=1000)
        self.addLink(s5, s7, cls=TCLink, bw=1000)
        self.addLink(s6, s7, cls=TCLink, bw=1000)

        self.addLink(s8, s9, cls=TCLink, bw=1000)

        self.addLink(s10, s11, cls=TCLink, bw=1000)
        self.addLink(s10, s12, cls=TCLink, bw=1000)
        self.addLink(s11, s12, cls=TCLink, bw=1000)

        self.addLink(s13, s14, cls=TCLink, bw=1000)
        self.addLink(s13, s15, cls=TCLink, bw=1000)
        self.addLink(s14, s15, cls=TCLink, bw=1000)

        # Interdomain links
        self.addLink(s2, s4, cls=TCLink, bw=100)
        self.addLink(s2, s6, cls=TCLink, bw=500)
        self.addLink(s5, s8, cls=TCLink, bw=300)
        self.addLink(s7, s9, cls=TCLink, bw=200)


        self.addLink(s2, s13, cls=TCLink, bw=300)
        self.addLink(s2, s10, cls=TCLink, bw=500)
        self.addLink(s12, s14, cls=TCLink, bw=1000)
        self.addLink(s15, s9, cls=TCLink, bw=1000)


    def pre_net_start(self, net):
        """ Add controllers before the topology starts """
        c1 = net.addController("c1", controller=RemoteController, ip="127.0.0.11", port=6633)
        c2 = net.addController("c2", controller=RemoteController, ip="127.0.0.12", port=6633)
        c3 = net.addController("c3", controller=RemoteController, ip="127.0.0.13", port=6633)
        c4 = net.addController("c4", controller=RemoteController, ip="127.0.0.14", port=6633)
        c5 = net.addController("c5", controller=RemoteController, ip="127.0.0.15", port=6633)

        # Bind the switches to specific controllers
        s1 = net.get("s1")
        s2 = net.get("s2")
        s3 = net.get("s3")
        s4 = net.get("s4")
        s5 = net.get("s5")
        s6 = net.get("s6")
        s7 = net.get("s7")
        s8 = net.get("s8")
        s9 = net.get("s9")
        s10 = net.get("s10")
        s11 = net.get("s11")
        s12 = net.get("s12")
        s13 = net.get("s13")
        s14 = net.get("s14")
        s15 = net.get("s15")

        s1.add_ctrl("c1")
        s2.add_ctrl("c1")
        s3.add_ctrl("c1")
        s4.add_ctrl("c2")
        s5.add_ctrl("c2")
        s6.add_ctrl("c2")
        s7.add_ctrl("c2")
        s8.add_ctrl("c3")
        s9.add_ctrl("c3")
        s10.add_ctrl("c4")
        s11.add_ctrl("c4")
        s12.add_ctrl("c4")
        s13.add_ctrl("c5")
        s14.add_ctrl("c5")
        s15.add_ctrl("c5")

topos = {
    "topo": NetTopo
}
