#!/usr/bin/python

""" Base topology module that defines the common code shared by all topos

NOTE:
    Due to the way mn works, all scripts that inherit and import this base
    topo module need to append their current working dir to sys.path.

Usage:
    sudo mn --custom <Module>.py --topo topo --switch ovs --mac --controller
    remote,ip=127.0.0.1"
"""

import subprocess
from mininet.topo import Topo
from mininet.log import info, lg

from mininet.node import OVSSwitch


class CustomCtrlSw(OVSSwitch):
    """ Custom switch class that allows configuring controllers a swithc needs
    to establish a connection to. This module adds supports for multi-ctrl
    SDN networks.
    """
    def __init__(self, name, failMode="secure", datapath="kernel", inband=False,
                    protocols=None, reconnectms=1000, stp=False, batch=False,
                    **params):
        super(CustomCtrlSw, self).__init__(name, failMode, datapath, inband,
                                protocols, reconnectms, stp, batch, **params)

        # List of controller instances the switch will connect to
        self.ctrls = []


    def start(self, controllers):
        """ Start the switch connecting it to the list of specified controllers
        `:cls:attr:(ctrls)` names.

        Args:
            controllers (list): List of controller instances that are bound to
                the topology.
        """
        # Based on the name of controllers the switch connects to, find all
        # controller instances to pass to the start function
        ctrls = []
        for c in self.ctrls:
            for cobj in controllers:
                if cobj.name == c:
                    # Found the controller instance, move to next name
                    ctrls.append(cobj)
                    break

        # XXX: Sanity check, make sure we found instances for all controllers
        if not len(ctrls) == len(self.ctrls):
            lg.critical("Error: Switch %s could not find all controllers!\n" %
                    self.name)

        info("Switch %s will connect to controllers: %s\n" % (self.name,
                self.ctrls))
        return OVSSwitch.start(self, ctrls)


    def add_ctrl(self, ctrl):
        """ Add a controller name `ctrl` to the list of controllers the switch
        needs to connect to.

        Args:
            ctrl (str): Name of the controller to connect to the switch
        """
        if ctrl not in self.ctrls:
            # Only add unique names to the connection list
            self.ctrls.append(ctrl)


class TopoBase(Topo):
    """ Base topology module. All topologies have to inherit this class.

    Attributes:
        name (str): Name that identifies the topology
        inNamespace (bool): Start the hosts in a namespace.
    """


    def __init__(self, name, inNamespace=True):
        """ Initiate the topology. Save the custom attributes.

        Args:
            name (str): Name of the topology
            inNamespace (bool) Start the hosts in a namespace. Defaults to true (yes).
        """
        self.name = name
        self.inNamespace = inNamespace
        super(TopoBase, self).__init__()


    def hosts_attr(self, net):
        """ Retrieve the hosts attributes list.

        Args:
            net (mininet.net.Mininet): Running network instance

        Returns:
            list of triple: List of host attributes triple in format (name, interface,
                advertise host name).
        """
        hosts_attr = []
        for h in self.hosts():
            host = net.get(h)
            intf = host.intfNames()[0]
            hosts_attr.append((h, intf, h))

        return hosts_attr


    def on_start(self, net):
        """ Method that should be called once the topo has started to configure
        attributes of the hosts (i.e. default route).

        Args:
            net (mininet.net.Mininet): Running network instance

        Note:
            If the topology is not running in a namespace this method exists
            without configuring anything
        """
        info("Running on start of topology\n")
        if self.inNamespace == False:
            info("Topology is not running in a namespace, done\n")
            return

        info("Configuring topology device attributes\n")
        for h in self.hosts():
            host = net.get(h)
            ip = host.IP().split(".")
            ip = ".".join(host.IP().split(".")[0:3])
            intf = host.intfNames()[0]

            cmd = "ip route add default via %s.254 dev %s" % (ip, intf)
            info("Setting default route on host %s\n\t%s\n" % (h, cmd))
            host.cmd(cmd)

        info("Finished\n")


    def dump_tables(self, dump_groups=False):
        """ Dump all flows and groups (if `dump_groups` is True) to STDOUT.

        Args:
            dump_groups (bool): Should we also output the group table. Defaults to False.
        """
        lg.critical("--- DUMP FLOWS ---\n")
        for sw in self.switches():
            lg.critical("%s: \n" % sw)
            lg.critical(subprocess.check_output(["ovs-ofctl", "dump-flows", "-O", "OpenFlow13", sw]))
        lg.critical("-----------------\n")

        if dump_groups:
            lg.critical("--- DUMP GROUPS ---\n")
            for sw in self.switches():
                lg.critical("%s: " % sw)
                lg.critical(subprocess.check_output(["ovs-ofctl", "dump-groups", "-O",
                                                "OpenFlow13", sw]))
            lg.critical("-----------------\n")
