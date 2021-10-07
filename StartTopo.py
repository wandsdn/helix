#!/usr/bin/python

""" Script which starts a mininet topology, applies any post configs and
displays the mininet CLI

Usage:
    sudo ./StartTopo.py --topo topology --inNamespace inNamespace
        topology - Topology module (or path to file) to start

    Optional Attributes:
        inNamespace - Run the hosts in a namespace (True) or outside a
            namespace (False). In a namespace is needed to allow ping to
            work as we need to configure a gateway on each host and outside
            is needed when testing with pktgen as we need to share /proc/
            between hosts to start the instances. Defaults to True
"""

import importlib
from argparse import ArgumentTypeError
from argparse import ArgumentParser
from mininet.cli import CLI
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.log import setLogLevel

def path_to_import_notation(module):
    """ Convert a module file path to a dot notation import style reference. Method
    will esentially replace all slashes with dots and remove any .py file
    extensions from the end of the module path.

    Args:
        module (str): path or dot notation reference to file

    Returns:
        str: dot notation reference to module (to be used with import)
    """
    if "/" in module:
        module = module.replace("/", ".")
    if module.endswith(".py"):
        module = module[:-3]

    return module


def str2bool(str):
    """ Argparse method that allows arguments of type boolean, converting
    a string to a bool value.

    Accepted True Strings (case-insenstive):
        yes, true, t, y, 1

    Accepted False Strings (case-insesntive):
        no, false, t, n, 0

    Returns:
        boolean: Argument value

    Raises:
        ArgumentTypeError: If the argument is not a bool (str value is unknown)
    """
    if str.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif str.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise ArgumentTypeError('Boolean value expected.')


if __name__ == "__main__":
    # Parse the recived arguments
    parser = ArgumentParser("Start mininet topology")
    parser.add_argument("--topo", required=True, type=str,
        help="Topology module or path to start")
    parser.add_argument("--inNamespace", type=str2bool, default=True,
        help="Start hosts in namespace (true) or outside namespace (false)")
    parser.add_argument("--logLevel", type=str, default="info",
        help="Set the log level (debug, info, warning, error, critical")
    args = parser.parse_args()

    topoMod = path_to_import_notation(args.topo)
    inNamespace = args.inNamespace

    # Set the log level
    setLogLevel(args.logLevel)

    # Load the topology module, ininit mininet and start the topo
    topo = importlib.import_module(topoMod)
    topo = topo.NetTopo(inNamespace=inNamespace)

    net = Mininet(
        topo=topo,
        controller=RemoteController,
        switch=OVSSwitch,
        autoSetMacs=True)

    # Check if topology has a pre network start method
    pre_net_start = getattr(topo, "pre_net_start", None)
    if callable(pre_net_start):
        topo.pre_net_start(net)

    # Start the network
    net.start()

    # Check if the object has a on start method
    on_start = getattr(topo, "on_start", None)
    if callable(on_start):
        topo.on_start(net)

    # Initiate the hosts to send LLDP packets indefinetly for host discovery
    for h in topo.hosts_attr(net):
        host = net.get(h[0])
        cmd = "LLDP/lldp_host.py %s %s 0 &" % (h[1], h[2])
        host.cmd(cmd)
        print("Started LLDP host discovery on host %s" % h[0])
        print("\t%s" % cmd)

    # Show the CLI and once exited tear-down any resources
    CLI(net)
    net.stop()
