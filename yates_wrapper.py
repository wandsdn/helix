#!/usr/bin/python

from argparse import ArgumentParser

import ShortestPath.protection_path_computation as paths
from ShortestPath.dijkstra_te import Graph
from TE import TEOptimisation

import re
import os
from enum import Enum
import json
import logging


# Location of temporary path file (used to preserve path info outside yates)
TEMP_PATH_FILE = "/tmp/paths.tmp"

# Should we compute lose path splices
LOOSE_SPLICE = False


class Action(Enum):
    """ Enumaration class used to restrict and select the supported actions of
    the wrapper.
    """
    topo = 'topo'
    te = 'te'

    def __str__ (self):
        return self.value


class CustomArgParser (ArgumentParser):
    def __init__ (self, name, logger):
        super(CustomArgParser, self).__init__(name)
        self.logger = logger

    """ Custom argument parser that doses not output anything when argument
    parsing errors occur.
    """
    def error(self, message):
        self.logger.info(message)
        exit(2)


class DummyCtrlCom:
    def __init__(self):
        self.inter_dom_paths = {}


class TE_Wrapper():
    """ Class that defines a wrapper for the TE optimisation class. This class is used
    to work out modifications to resolve congestion.

    Attrs:
        modified (bool): Flag that indicates if our TE optimisation has modified the paths
        logger (logging): Logger used to output debug information
        paths (dict): Currently installed paths in the topology. Loaded from temp path file
        graph (ShortestPathDisktra_te.Graph): Current topology of the network
        TE (TE.TEOptimisation): TE module instance used to resolve congestion
    """
    def __init__(self, topo, flow_demand_file, topo_traffic_file, over_util_file,
                                                te_thresh, logger, path_file=TEMP_PATH_FILE):
        self.modified = False
        self.logger = logger
        self.ctrl_com = DummyCtrlCom()

        # Unserialize the paths from the JSON file and load to the paths object
        with open(path_file, "r") as f:
            self.paths = {}
            for data in json.load(f):
                src = data["keysrc"]
                dst = data["keydst"]
                del data["keysrc"]
                del data["keydst"]
                self.paths[(src, dst)] = data

                # Fix and validate the groups
                gp_fix = {}
                if "groups" not in data:
                    raise Exception(data)
                for gp_sw,gp_d in data["groups"].iteritems():
                    if gp_sw not in gp_fix:
                        gp_fix[gp_sw] = []

                    for gp_pt in gp_d:
                        # Make sure we have no tuples
                        if isinstance(gp_pt, list):
                            raise Exception("Invalid state load, group table with tuple %s-%s" % key)
                        gp_fix[gp_sw].append(gp_pt)

                self.paths[(src, dst)]["groups"] = gp_fix

                # Fix and validate the special flow rules
                special_flow_fix = {}
                for sp_sw,sp_d in data["special_flows"].iteritems():
                    if sp_sw not in special_flow_fix:
                        special_flow_fix[sp_sw] = []

                    for sp_pt in sp_d:
                        if not isinstance(sp_pt, list) or not len(sp_pt) == 2:
                            raise Exception("Invalid state load, special flow not two element tuple %s%s" % key)
                        special_flow_fix[sp_sw].append((sp_pt[0], sp_pt[1]))

                self.paths[(src, dst)]["special_flows"] = special_flow_fix

                # TODO: Maybe this needs to be change
                # Add a dummy GID for TE optimisation
                self.paths[(src, dst)]["gid"] = -1

        # Initiate the topo and load the demands
        self.graph = Graph(topo)
        self.load_flow_demand(flow_demand_file)
        self.load_topo_traffic(topo_traffic_file)

        # Initiate the TE optimisation class and resolve the congestion
        self.TE = TEOptimisation(self, te_thresh, 1.0)

        self.load_over_util_links(over_util_file)
        self.logger.info(self.TE.over_utilised)

        self.TE._optimise_TE()

        # Serialize the modified paths back to the paths file
        save_temp_path_file(self.paths)


    def get_poll_rate(self):
        """ Get the poll rate for the statistics. Assume poll interval of 1s """
        return 1.0


    def get_paths(self):
        """ Get the installed paths of the topo """
        return self.paths


    def get_topo(self):
        """ Get the topology object """
        return self.graph


    def is_inter_domain_link(self, sw, port):
        """ Check if a link is an inter-domain link (always return false) """
        return False


    def load_flow_demand(self, file_path):
        """ Load all flow demands from a JSON file to the path stats.

        Args:
            file_path (str): Path to JSON file to load
        """
        with open(file_path, "r") as fin:
            for obj in json.load(fin):
                src = obj["src"]
                dst = obj["dest"]
                bits = obj["val"]
                if src == dst:
                    continue

                self.paths[(src, dst)]["stats"] = {"bytes": (bits / 8)}


    def load_topo_traffic(self, file_path):
        """ Load the traffic on the topology links from the JSON file

        Args:
            file_path (str): Path to JSON file
        """
        with open(file_path, "r") as fin:
            for obj in json.load(fin):
                src = obj["src"]
                src_port = int(obj["src_port"])
                bytes = int(obj["val"]) / 8

                # Update the tx bytes on the port for the poll interval
                self.graph.update_port_info(src, src_port, tx_bytes=bytes,
                                            is_total=False)


    def load_over_util_links(self, file_path):
        """ Load the over utilised links JSON file.

        Args:
            file_path (str): Path to JSON file to load
        """
        with open(file_path, "r") as fin:
            for obj in json.load(fin):
                sw = str(obj["src"])
                port = int(obj["src_port"])
                usage = float(obj["usage"])
                self.TE.over_utilised[(sw, port)] = usage


    def invert_group_ports(self, hkey, node, groupID):
        """ Invert the ports of a group entry. Method will modify the paths object
        such that a group is inverted and flag that a modification has occured (if ports
        were swapped).

        Args:
            hkey (tuple): SRC and DEST host tuple.
            sw (obj): Switch we are inverting the group ports for
            groupID (int): GID of path (in this case GID is not used)
        """
        sw,new_pt = node
        old_pt = self.paths[hkey]["groups"][sw][0]
        gp = self.paths[hkey]["groups"][sw][1:]
        if new_pt not in gp:
            raise Exception("Can't invert group for path %s as new port %s not in group entry %s" %
                (hkey, node, gp))

        # Remove the new port and re-build the group entry
        gp.remove(new_pt)
        gp.insert(0, new_pt)
        gp.append(old_pt)
        self.paths[hkey]["groups"][sw] = gp

        # Swap the group bucket entry and update the path groups to reflect our modification
        if len(gp) > 0:
            self.logger.info("Inverted GP of %s at %s from %s to %s (GP: %s)" % (hkey, sw, old_pt, new_pt, gp))
            self.modified = True

            # Modify the paths (caused by swapping groups)
            # XXX: We need to use the method as we can also have splices which cause our
            # primary path to change. The path is used by Yates to figure out where traffic
            # goes (dosen't use the GP table that we altered).
            ingress = self.paths[hkey]["ingress"]
            egress = self.paths[hkey]["egress"]
            groups = self.paths[hkey]["groups"]

            new_prim_path = []
            new_prim_path.append(hkey[0])
            for tp in paths.group_table_to_path(self.paths[hkey], self.get_topo(), ingress):
                new_prim_path.append(tp[0])
            new_prim_path.append(hkey[1])

            self.paths[hkey]["primary"] = new_prim_path


def compute_paths(topo, hosts):
    """ Compute all required paths for every host pair from `hosts` on topology `topo`.
    The method also serializes and saves all information required later to the temporary
    path file to prevent needing to store more path info in yates. Info is serilized and
    saved to `:mod:TEMP_PATH_FILE`.

    Args:
        topo (dict): Topology dictionary
        hosts (list of str): Hosts we are computing paths for

    Returns:
        dict: Array of paths that we have computed
    """
    res = {}
    res_ser = {}

    for host_1 in hosts:
        for host_2 in hosts:
            if host_1 == host_2:
                # Can't compute path to ourselves
                continue

            ser_key = (host_1, host_2)

            # Compute GID, initiate a new graph object and the work out the paths
            graph = Graph(topo)
            path_primary, path_secondary, ports_primary, ports_secondary = paths.find_path(
                    host_1, host_2, graph)

            # Find the required path splices for our two paths
            if LOOSE_SPLICE == False:
                splice = paths.gen_splice(path_primary, path_secondary, graph)
                splice.update(paths.gen_splice(path_secondary, path_primary, graph))
            else:
                splice = paths.gen_splice_loose(path_primary, path_secondary, graph)
                splice.update(paths.gen_splice_loose(path_secondary, path_primary, graph))

            # Add the host path information to the result dictionary
            if host_1 not in res:
                res[host_1] = {}
            if host_2 not in res[host_1]:
                res[host_1][host_2] = {}
            if ser_key not in res_ser:
                res_ser[ser_key] = {}

            res_ser[ser_key]["primary"] = path_primary
            res_ser[ser_key]["secondary"] = path_secondary
            res_ser[ser_key]["splice"] = []
            res_ser[ser_key]["ingress"] = path_primary[1]
            res_ser[ser_key]["egress"] = path_primary[len(path_primary)-2]

            res[host_1][host_2]["primary"] = path_primary
            res[host_1][host_2]["secondary"] = path_secondary
            res[host_1][host_2]["splice"] = []

            # Add the slice paths to the splice list
            for sw,sp in splice.iteritems():
                res_ser[ser_key]["splice"].append(sp)
                res[host_1][host_2]["splice"].append(sp)

            # Compute the group table needed for the new path
            group_table = {}
            for port in ports_primary:
                # Initiate the switch in the dictionary if it dosen't exist
                if port[0] not in group_table:
                    group_table[port[0]] = []

                # If the port is not part of the bucket add it
                if port[2] not in group_table[port[0]]:
                    group_table[port[0]].append(port[2])

            for port in ports_secondary:
                if port[0] not in group_table:
                    group_table[port[0]] = []

                if port[2] not in group_table[port[0]]:
                    group_table[port[0]].append(port[2])

            special_flows = {}
            for sw,sp in splice.iteritems():
                # Get the ports for the splice path and go through them
                ports = graph.flows_for_path(sp)
                for port in ports:
                    # Check if the current switch is at the start or end of the path splice
                    if port[0] == sp[0] or port[0] == sp[len(sp)-1]:
                        if port[0] not in group_table:
                            group_table[port[0]] = []
                        if port[2] not in group_table[port[0]]:
                            group_table[port[0]].append(port[2])
                    else:
                        # If its in the midle of the path we need to install a flow
                        # rule with in out port mappings.
                        # XXX: This occurs when a path splie has more than 2 switches
                        # and we are installing on a path other than the start and end
                        # of the splice.
                        if port[0] not in special_flows:
                            special_flows[port[0]] = []
                        if (port[1], port[2]) not in special_flows[port[0]]:
                            special_flows[port[0]].append((port[1], port[2]))

            res_ser[ser_key]["groups"] = group_table
            res_ser[ser_key]["special_flows"] = special_flows

    # Save the path dictionary to the temp path file and return the computes paths object
    save_temp_path_file(res_ser)
    return res


def save_temp_path_file(path_dict):
    """ Method takes a path dictionary object in a format similar to what the SDN controller
    generates, and serializes it to the path dictionary file. The object will be cleaned
    before writing to the temp file.

    Args:
        path_dict (dict): Object that contains the path information.
    """
    # Only allow the following dictionary keys to be serialized for each path entry
    OUT_DICT_KEYS = ["ingress", "egress", "groups", "primary", "special_flows", "secondary", "splice"]

    # Clean up the paths dictionary before outputing
    ser_dict = []
    for key,data in path_dict.iteritems():
        obj = {"keysrc": key[0], "keydst": key[1]}

        for d_key, d_data in data.iteritems():
            if d_key in OUT_DICT_KEYS:
                obj[d_key] = d_data

        ser_dict.append(obj)

    # Output the path dict to a temporary file for later use
    with open(TEMP_PATH_FILE, "w") as f:
        f.write(json.dumps(ser_dict))

    #logging.debug("Wrote temp path file content")
    #logging.debug("------\n%s\n-----" %  json.dumps(ser_dict, indent=1, sort_keys=True))


def load_topo (file_path):
    """ Load the topology information from a topology JSON file.

    Args:
        file_path (str): Path to JSON file to load topo info from.

    Returns:
        (dict, list): Tuple of topology dictionary info and list of hosts.
    """
    topo = {}
    hosts = []

    with open(file_path, "r") as fin:
        try:
            data = json.load(fin)

            for h in data["hosts"]:
                hosts.append(str(h))

            # Fix the topo object
            for obj in data["topo"]:
                src = str(obj["src"])
                src_p = int(obj["srcPort"])
                dst = str(obj["dest"])
                dst_p = obj["destPort"]
                cost = int(obj["cost"])

                if src not in topo:
                    topo[src] = {}
                if src_p not in topo[src]:
                    topo[src][src_p] = {}

                topo[src][src_p] = {
                    "dest": dst,
                    "destPort": dst_p,
                    "cost": cost,
                    "speed": int(obj["speed"]),
                    "poll_stats": {
                        "tx_bytes": 0.0
                    }
                }
        except:
            return None,None
    return topo,hosts

if __name__ == "__main__":
    # Get the incremental number of the log file
    #LOG_NUM = 0
    #for fname in os.listdir("/scratch/SimTest4/LOG/"):
    #    if ".log" in fname:
    #        tmp_num = int(fname.split(".")[0])
    #        if tmp_num > LOG_NUM:
    #            LOG_NUM = tmp_num

    # Configure the logger leve and tell it to log to a file
    #LOG_NUM += 1
    #logging.basicConfig(level=logging.DEBUG, filename="/scratch/SimTest4/LOG/%d.log" % LOG_NUM)
    logging.basicConfig(level=1000)

    # Initiate the argument parser
    parser = CustomArgParser("Yates SDN Controller Wrapper", logging)
    parser.add_argument("--action", required=True, type=Action, choices=list(Action),
        help="topo = Compute paths | te = Check Congestion")
    parser.add_argument("--topo", required=True, type=str, default=None,
        help="Path to topology JSON file")
    parser.add_argument("--flow_demand", required=False, type=str, default=None,
        help="(TE Action Only) path to src-dst demand JSON file")
    parser.add_argument("--topo_traffic", required=False, type=str, default=None,
        help="(TE Action Only) path to link traffic JSON file")
    parser.add_argument("--over_util", required=False, type=str, default=None,
        help="(TE Action Only) path to over utilised link JSON file")
    parser.add_argument("--te_thresh", required=False, type=float, default=None,
        help="(TE Action Only) TE threshold value for optimisation")
    args = parser.parse_args()

    # Load the topology object and validate
    if not os.path.isfile(args.topo):
        logging.info("Topo path file (%s) dosen't exist" % args.topo)
        exit(1)
    topo,hosts = load_topo(args.topo)
    if topo is None or hosts is None:
        logging.info("Error while parsing topo file %s" % args.topo)
        exit(1)

    # Compute the paths from a topology object action
    if args.action == Action.topo:
        logging.info("Action is compute topology (topo)")

        # Log the data we will return to YATES
        data = compute_paths(topo, hosts)
        logging.debug("Returned data to YATES")
        logging.debug("------\n%s\n-----" %  json.dumps(data, indent=1, sort_keys=True))

        # Output data to yates
        print(json.dumps(data))
    elif args.action == Action.te:
        logging.info("Action is optimise TE (te)")
        if (args.flow_demand is None or args.topo_traffic is None or
                args.over_util is None or args.te_thresh is None):
            logging.info("Not all required TE arguments where provided")
            exit(1)
        if not os.path.isfile(args.flow_demand):
            logging.info("Flow demand file (%s) dosen't exist" % args.flow_demand)
            exit(1)
        if not os.path.isfile(args.topo_traffic):
            logging.info("Topology traffic file (%s) dosen't exist" % args.topo_traffic)
            exit(1)
        if not os.path.isfile(args.over_util):
            logging.info("Over utilised ports file (%s) dosen't exist" % args.over_util)
            exit(1)

        TE = TE_Wrapper(topo, args.flow_demand, args.topo_traffic, args.over_util,
                        args.te_thresh, logging)
        if TE.modified:
            tmp = {}
            for key,data in TE.get_paths().iteritems():
                if key[0] not in tmp:
                    tmp[key[0]] = {}
                if key[1] not in tmp[key[0]]:
                    tmp[key[0]][key[1]] = {}

                tmp[key[0]][key[1]]["primary"] = data["primary"]
                tmp[key[0]][key[1]]["secondary"] = data["secondary"]
                tmp[key[0]][key[1]]["splice"] = data["splice"]

            #logging.debug("Returned data to YATES")
            #logging.debug("-----\n%s\n-----" % json.dumps(tmp, indent=1, sort_keys=True))
            print(json.dumps(tmp))
        else:
            logging.info("No TE changes occured, empty JSON object returned to yates")
            print("{}")
