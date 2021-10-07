#!/usr/bin/python

import sys
from networkx.readwrite import gml

from argparse import ArgumentParser

INDENT = "        "

HOST_TMPL = "{INDENT}{VNAME} = self.addHost('{NAME}', inNamespace=self.inNamespace)\n"
SW_TMPL = "{INDENT}{VNAME} = self.addSwitch('{NAME}')\n"

LINK_TMPL = "{INDENT}self.addLink({TO}, {FROM}, cls=TCLink, bw={BW})\n"
LINK_TMPL_NGW = "{INDENT}self.addLink({TO}, {FROM})\n"

args = None


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
        ArgumentTypeError: If the argument is not a bool (str value is unkown)
    """
    if str.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif str.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise ArgumentTypeError('Boolean value expected.')


def name_to_var(prefix, name):
    """ Convert the name (ID) of a node to a label variable

    Args:
        prefix (str): Prefix to apply to variable name.
        name (str): Name of the node.

    Returns:
        str: Variable name in format '`prefix``name`'.
    """
    return "%s%s" % (prefix, name)


def gen_link_str(src, dest, bw=1000, indent=INDENT):
    """ Generate a link string to add to the mininet module.

    Note:
        Link attrs such as `bw` are only set to the link if, `:mod:attr(args.set_link_attr)`
        is True. If it is `:mod:attr(LINK_TMPL)` will be used to generate the link speed,
        otherwise `:mod:attr(LINK_TMPL_NGW)` is used.

    Args:
        src (str): Source of the link
        dest (str): Destination of the link
        bw (int): Bandwidth of link in Mbps. Defaults to 1000 (1Gbps).
        indent (str): Indentation to apply to link line. Defaults to `:mod:attr(INDENT)`.

    Returns:
        String representation of the link to output to mininet module.
    """
    if args.set_link_attr:
        str = LINK_TMPL.format(INDENT=indent, TO=src, FROM=dest, BW=bw)
    else:
        str = LINK_TMPL_NGW.format(INDENT=indent, TO=src, FROM=dest)
    return str


if __name__ == "__main__":
    # Process the argumets
    parser = ArgumentParser()
    parser.add_argument("--input", required=True, type=str, help="GML file to convert")
    parser.add_argument("--output", required=True, type=str, help="Destination file")
    parser.add_argument("--name", required=True, type=str, help="Topology name")
    parser.add_argument("--hosts_per_sw", required=False, type=int, default=1,
            help="Number of hosts per each switch")
    parser.add_argument("--set_link_attr", required=False, type=str2bool, default=False,
            help="Should the output contain link attributes (e.g. speed)")
    parser.add_argument("--speed_scale", required=False, type=float, default=1.0,
            help="Divide all BW by this ammount to scale (MN limits bw to 1000Mbps)")
    args = parser.parse_args()

    # Convert the GML file to a list of nodes and edges
    g = gml.read_gml(path=args.input, label='id')
    nodes = g.nodes.items()
    edges = g.edges.items()

    # Generate a mapping of node IDs to labels and load the python template
    node_labels = {}
    for node,info in nodes:
        node_labels[node] = info["label"] if "label" in info else node

    tmpl = ""
    with open("mn_template.txt") as f:
        tmpl=f.read()


    # Generate the GMP file attribute string
    # Find the max pad ammount of the attribute key
    max_key_size = 0
    for key,val in g.graph.iteritems():
        if len(key) > max_key_size:
            max_key_size = len(key)

    line_tmpl = "{:%s} : {}\n" % max_key_size
    gml_file_attr = ""
    for key,val in g.graph.iteritems():
        gml_file_attr += line_tmpl.format(key, val)


    # Generate the hosts
    host_str = ""
    hosts = []
    ID = 0
    for node,info in nodes:
        sw_name = name_to_var("s", node)
        sw_lbl = info["label"] if "label" in info else sw_name
        if args.hosts_per_sw > 1:
            # Create multiple hosts per switch
            for i in range(args.hosts_per_sw):
                host_name = name_to_var("h", ID)
                host_lbl = ("%s_%s" % (name_to_var("h_", sw_lbl), i))

                hosts.append((host_name, sw_name))
                host_str += "%s# HOST %s to SW %s (Num: %s)\n" % (INDENT, host_lbl, sw_lbl, i)
                host_str += HOST_TMPL.format(INDENT=INDENT, VNAME=host_name, NAME=host_name)
                ID += 1
        else:
            host_name = name_to_var("h", node)
            host_lbl = name_to_var("h_", sw_lbl)

            hosts.append((host_name, sw_name))
            host_str += "%s# HOST %s to SW %s\n" % (INDENT, host_lbl, sw_lbl)
            host_str += HOST_TMPL.format(INDENT=INDENT, VNAME=host_name, NAME=host_name)


    # Generate the switch string
    sw_str = ""
    for node,info in nodes:
        sw_name = name_to_var("s", node)
        sw_lbl = info["label"] if "label" in info else sw_name

        sw_str += "%s# %s\n" % (INDENT, sw_lbl)
        sw_str += "%s# INFO" % INDENT
        if "Latitude" in info:
            sw_str += " | Lat: %s" % info["Latitude"]
        if "Longitude" in info:
            sw_str += " | Lon: %s" % info["Longitude"]
        if "Country" in info:
            sw_str += " | Country: %s" % info["Country"]
        if "Internal" in info:
            sw_str += " | Internal: %s" % ("yes" if info["Internal"] == 1 else "no")
        sw_str += "\n"
        sw_str += SW_TMPL.format(INDENT=INDENT, VNAME=sw_name, NAME=sw_name)


    # Generate the links that connect to the hosts
    link_str = "%s# Host Links\n" % INDENT
    for h in hosts:
        bw = int(1000 / args.speed_scale)
        link_str += gen_link_str(h[0], h[1], bw=bw)


    # Generate the links
    link_str += "\n"
    for edge,info in edges:
        edge_to = name_to_var("s", edge[0])
        edge_from = name_to_var("s", edge[1])

        edge_to_lbl = node_labels[edge[0]]
        edge_from_lbl = node_labels[edge[1]]

        link_str += "%s# %s to %s\n" % (INDENT, edge_to_lbl, edge_from_lbl)
        if "LinkLabel" in info:
            link_str += "%s# Label: %s\n" % (INDENT, info["LinkLabel"])

        link_str += "%s# INFO" % INDENT
        if "LinkType" in info:
            link_str += " | Type: %s" % info["LinkType"]
        if "LinkNote" in info:
            link_str += " | Note: %s" % info["LinkNote"]
        if "LinkSpeed" in info and "LinkSpeedUnits" in info:
            link_str += " | Speed: %s %s" % (info["LinkSpeed"], info["LinkSpeedUnits"])
        link_str += "\n"

        # Links are 1Gbps by default if not specified
        BW = 1000 / args.speed_scale
        if "LinkSpeedRaw" in info:
            lspeed = int(info["LinkSpeedRaw"] / 1000000)
            lspeed = int(lspeed / args.speed_scale)
            BW = lspeed

        link_str += gen_link_str(edge_to, edge_from, bw=BW)


    # Generate the output module using the template we have loaded
    with open(args.output, "w")as f:
        f.write(tmpl.format(GML_FILE=args.input, TOPO_NAME=args.name, HOSTS=host_str,
                SWITCHES=sw_str, LINKS=link_str, GML_FILE_ATTRS=gml_file_attr))


    print("Finished converting file %s to MN module %s" % (args.input, args.output))
