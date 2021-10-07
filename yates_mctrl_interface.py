#!/usr/bin/python

from ShortestPath.dijkstra_te import Graph
import ShortestPath.protection_path_computation as ppc
import topo_discovery.api as topo_disc_api

from TE import TEOptimisation

# Imports used to spoof send and switch for rule extraction
from ryu.ofproto.ofproto_protocol import ProtocolDesc
from ryu.ofproto import ofproto_v1_3
from ryu.topology.switches import Switch

from argparse import ArgumentParser
import re
import os
from enum import Enum
import json
import logging


# ---------- OVERRIDE API CALLS USED BY CODE ----------

def send_dummy(req):
    """ Fake send method used to attack to fake DPID object """
    pass

def get_switch(self, dpid=None):
    """ Fake get switch method that returns a fake switch object that dosen't
    have a connection to a device. """
    dummy_prot = ProtocolDesc(ofproto_v1_3.OFP_VERSION)
    dummy_prot.id = dpid
    dummy_prot.send_msg = send_dummy
    dummy_obj = Switch(dummy_prot)
    return[dummy_obj]

# XXX: Overwrite the get switch of the topology discovery API and finally import parent
topo_disc_api.get_switch = get_switch
from ProactiveController import ProactiveController

# --------------------------------------------------


# Location of temporary path file (used to preserve path info outside yates)
TEMP_PATH_FILE = "/tmp/paths.%s.tmp"

# CID used by the local controller
CID = ""


class Action(Enum):
    """ Enumaration class used to restrict and select the supported actions of
    the interface.
    """
    topo = 'topo'
    te = 'te'
    inter_dom = "inter-dom"
    ing_change = "ing-change"

    def __str__ (self):
        return self.value

class CustomArgParser (ArgumentParser):
    """ Custom argument parser that suppereses any error output messages when invalid
    arguments are provided. """
    def __init__ (self, name, logger):
        super(CustomArgParser, self).__init__(name)
        self.logger = logger

    def error(self, message):
        self.logger.info(message)
        exit(2)

class DummyCtrlCom:
    """ Dummy controller communication class that stores info about congesed inter-dom links
    that we can't and any ingress or egress changes. """
    def __init__ (self, logger):
        self.congested_info = {}
        self.inter_dom_paths = {}
        self.logger = logger
        self.idp_change = []

    def set_inter_dom_path_instructions(self, inst):
        self.inter_dom_paths = inst

    def notify_inter_domain_congestion(self, sw, port, traff_bps, path_keys):
        self.congested_info[(sw, port)] = {
            "traff_bps": traff_bps,
            "path_keys": path_keys
        }

    def notify_egress_change(self, hkey, new_egress):
        paths = None
        if hkey in self.inter_dom_paths:
            paths = self.inter_dom_paths[hkey]
            prim = paths[0]
            sec = None

            # Iterate through the installed paths and try to find the new egress
            for p in paths:
                if p["out"] == new_egress:
                    sec = p
                    break

            # If we found the correct out swap the primary paths with the secondary path
            # for which the egress belongs
            if sec is not None:
                old_egress = prim["out"]
                prim["out"] = new_egress
                sec["out"] = old_egress

                # Add the key to the modified IDP list if not already added
                if hkey not in self.idp_change:
                    self.idp_change.append(hkey)
            else:
                self.logger.critical("Could not find new egress in old root controller paths")
                self.logger.critical("%s %s" % (hkey, new_egress))
                return

        else:
            self.logger.critical("Could not find hkey in old root controller paths to change egress")
            return

    # XXX TODO: Should we just use the default method and overwride the safe send instead????
    def notify_ingress_change(self, hkey, old_ingress, new_ingress, old_egress, new_egress):
        paths = []
        if hkey in self.inter_dom_paths:
            paths = self.inter_dom_paths[hkey]
            prim = paths[0]
            sec = None

            # Look for the secondary path in the inter-dom installed paths list
            for p in paths:
                if p["in"] == new_ingress:
                    sec = p
                    break

            # If we found the correct paths swap the primary and secondary path ingress
            if sec is not None:
                prim["in"] = new_ingress
                sec["in"] = old_ingress
                self.logger.info("Found the old root controller paths, modifying ingress")

                # Only update egress if we are a transit inter-domain path segment and
                # if the new egress differs from the old one (try to preserve ports).
                if isinstance(old_egress, tuple) and not old_egress == new_egress:
                    prim["out"] = new_egress
                    sec["out"] = old_egress
                    self.logger.info("Modified egress of old root controller path")

                # Add the key to the modified IDP list if not already added
                if hkey not in self.idp_change:
                    self.idp_change.append(hkey)
            else:
                self.logger.error("Could not find new ingress in old root controller paths")
                self.logger.critical("%s %s" % (hkey, new_ingress))
        else:
            self.logger.error("Could not find hkey in old root controller paths to change ingress")


class DummyTEOpti(TEOptimisation):
    def __init__(self, controller, thresh, opti_method, candidate_sort_rev,
                        pot_path_sort_rev, te_paccept):
        super(DummyTEOpti, self).__init__(controller, thresh, 0,
                            opti_method, candidate_sort_rev, pot_path_sort_rev,
                            te_paccept)

    def _trigger_optimise_timer(self):
        pass

class DummyCtrl(ProactiveController):
    TESTING_MODE = True

    def __init__(self, te_thresh=0.90, te_opti_method="FirstSol",
                                        te_candidate_sort_rev=True,
                                        te_pot_path_sort_rev=False,
                                        te_paccept=False,
                                        *args, **kwargs):
        super(DummyCtrl, self).__init__(*args, **kwargs)
        self.computed_paths = {}
        self.TE = DummyTEOpti(self, te_thresh, te_opti_method,
                    te_candidate_sort_rev, te_pot_path_sort_rev, te_paccept)
        self.te_thresh = te_thresh
        self.poll_interval = 1

        self.ctrl_com = DummyCtrlCom(self.logger)
        self.te_mod_paths = []

    def get_poll_rate(self):
        """ Get the current stats poll interval """
        return self.poll_interval

    def get_computed_paths(self):
        """ Get the dictionary of computed paths """
        return self.computed_paths

    def is_master(self):
        """ We are always the master controller """
        return True

    def set_inter_dom_path_instructions(self, inst):
        """ Set the inter-domain path instructions in the fake controller communication module """
        self.ctrl_com.set_inter_dom_path_instructions(inst)

    def _init_ing_change_wait(self, hkey):
        """ Do not initiate the ingress change wait timer """
        pass

    def _install_protection(self):
        """ Override default install protection method to compute all host-pair paths and not
        start the timer.
        """
        for host_1 in self.hosts:
            for host_2 in self.hosts:
                if host_1 == host_2:
                    continue

                graph = Graph(self.graph.topo)
                self._compute_paths(graph, host_1, host_2, None, None)

    def compute_path_dict(self, graph, src, dest, inp=None, outp=None, path_key=None, graph_sec=None):
        """ Save the computed enriched information to a dictionary and return
        the result. The computd paths are removed before adding entry to path info dict
        """
        res = super(DummyCtrl, self).compute_path_dict(graph, src, dest, inp, outp, path_key, graph_sec)
        key = path_key
        if key is None:
            key = (src, dest)

        # If there is no path info remove any onld info and return an empty result without
        # saving path information
        if res == {}:
            if key in self.computed_paths:
                del self.computed_paths[key]
            return {}

        if key not in self.computed_paths:
            self.computed_paths[key] = {}
        self.computed_paths[key]["primary"] = res["path_primary"]
        self.computed_paths[key]["secondary"] = res["path_secondary"]
        self.computed_paths[key]["splices"] = res["path_splices"]
        return res

    def save_path_info(self):
        """ Serialize the internal path information dictionary `:cls:attr:(paths)` to the temporary
        path info file `:mod:attr(TEMP_PATH_FILE)`.
        """
        # Only allow the following dictionary keys to be serialized for each path entry
        OUT_DICT_KEYS = ["ingress", "egress", "groups", "primary", "secondary", "splice",
                            "ingress_change_detect", "gid", "special_flows"]

        # Clean up the paths dictionary before outputing
        ser_dict = []
        for key,data in self.paths.iteritems():
            obj = {"keysrc": key[0], "keydst": key[1]}

            for d_key, d_data in data.iteritems():
                if d_key in OUT_DICT_KEYS:
                    obj[d_key] = d_data

            ser_dict.append(obj)

        # Output the path dict to a temporary file for later use
        with open(TEMP_PATH_FILE, "w") as f:
            f.write(json.dumps(ser_dict))

        self.logger.debug("Wrote temp path file content")
        self.logger.debug("------\n%s\n-----" %  json.dumps(ser_dict, indent=1, sort_keys=True))

    def load_path_info (self):
        """ Retrieve the saved internal path information dictionary to `:cls:attr:(paths)` from the
        temporary file `:mod:attr:(TEMP_PATH_FILE)`.
        """
        with open(TEMP_PATH_FILE, "r") as fin:
            for data in json.load(fin):
                src = data["keysrc"]
                dst = data["keydst"]
                del data["keysrc"]
                del data["keydst"]

                key = (src, dst)
                self.paths[key] = data

                # Fix serialization of tuples as lists
                if isinstance(self.paths[key]["ingress"], list):
                    if len(self.paths[key]["ingress"]) != 2:
                        raise Exception("Ingress tuple has more thatn two elements")
                    self.paths[key]["ingress"] = (self.paths[key]["ingress"][0], self.paths[key]["ingress"][1])

                if isinstance(self.paths[key]["egress"], list):
                    if len(self.paths[key]["egress"]) != 2:
                        raise Exception("Egress tuple has more thatn two elements")
                    self.paths[key]["egress"] = (self.paths[key]["egress"][0], self.paths[key]["egress"][1])

                if "ingress_change_detect" in self.paths[key]:
                    ing_change_fix = []
                    for ing_change in self.paths[key]["ingress_change_detect"]:
                        if len(ing_change) != 2:
                            raise Exception("Ingress change detect tuple has more than two elements")
                        ing_change_fix.append((ing_change[0], ing_change[1]))
                    self.paths[key]["ingress_change_detect"] = ing_change_fix

                # Fix and validate the groups
                gp_fix = {}
                for gp_sw,gp_d in data["groups"].iteritems():
                    if gp_sw not in gp_fix:
                        gp_fix[gp_sw] = []

                    for gp_pt in gp_d:
                        # Make sure we have no tuples
                        if isinstance(gp_pt, list):
                            raise Exception("Invalid state load, group table with tuple %s-%s" % key)
                        gp_fix[gp_sw].append(gp_pt)

                self.paths[key]["groups"] = gp_fix

                # Fix and validate the special flow rules
                special_flow_fix = {}
                for sp_sw,sp_d in data["special_flows"].iteritems():
                    if sp_sw not in special_flow_fix:
                        special_flow_fix[sp_sw] = []

                    for sp_pt in sp_d:
                        if not isinstance(sp_pt, list) or not len(sp_pt) == 2:
                            raise Exception("Invalid state load, special flow not two element tuple %s%s" % key)
                        special_flow_fix[sp_sw].append((sp_pt[0], sp_pt[1]))

                self.paths[key]["special_flows"] = special_flow_fix

                # Add dummy default attributes
                self.paths[key]["in_port"] = -1
                self.paths[key]["address"] = "0.0.0.0"
                self.paths[key]["eth"] = "00:00:00:00:00:00"
                self.paths[key]["stats"] = {"bytes": 0}

    def add_dummy_destination(self, hkey, info, graph):
        """ Override the add dummy destination method to preserve the other end of the inter-domain
        link that we need to a compute a path to. The fake name of the other end uses a syntax of
        'TARGET-<sw>' where <sw> repersents the other end of the link. We need to still override
        the node to ensure that the computed path uses the specified port (i.e. ignore any other
        connecting links to the required node).
        """
        host_1, host_2 = hkey
        ret_target = []
        if host_2 in self.hosts and host_1 not in self.hosts:
            # If this is a destination segment the target is the destination
            for i in range(len(info)):
                ret_target.append(host_2)
        else:
            rewrote_out = {}

            # Otherwise add fake name to the end of the graph
            for i in range(len(info)):
                # Get the destination node name and generate the fake name using it
                out_sw = info[i]["out"][0]
                out_port = info[i]["out"][1]
                dest = graph.topo[out_sw][out_port]["dest"]
                destPort = graph.topo[out_sw][out_port]["destPort"]
                fake_name = (dest, destPort)

                if info[i]["out"] in rewrote_out:
                    ret_target.append(rewrote_out[info[i]["out"]])
                    continue

                rewrote_out[info[i]["out"]] = fake_name
                graph.topo[out_sw][out_port]["dest"] = fake_name
                graph.topo_stale = True
                ret_target.append(fake_name)
        return ret_target

    def compute_path_segments(self, inter_dom_inst, inter_dom_links):
        """ Compute path segments from a list of inter-domain path instructions """
        for hkey,info in inter_dom_inst.iteritems():
            self.compute_path_segment(hkey, info)

        # TODO FIXME: What if we have a path that we are modifying that results
        # in the same effective path, should we re-install it ??????
        # Go through and add the changed paths to the returned result
        res = {}
        for hkey,info in inter_dom_inst.iteritems():
            if hkey in self.computed_paths:
                path = self.computed_paths[hkey]
                host_1, host_2 = hkey

                if host_1 not in res:
                    res[host_1] = {}
                if host_2 not in res[host_1]:
                    res[host_1][host_2] = {}

                # Fix up the paths
                self.__fix_res_path_node_names(path["primary"])
                self.__fix_res_path_node_names(path["secondary"])

                for n,s in path["splices"].iteritems():
                    self.__fix_res_path_node_names(s)

                res[host_1][host_2] = {
                    "primary": path["primary"],
                    "secondary": path["secondary"],
                    "splices": path["splices"]
                }

        return res

    def __fix_res_path_node_names(self, p):
        if isinstance(p[0], tuple):
            p[0] = p[0][0]
        if isinstance(p[-1], tuple):
            p[-1] = p[-1][0]

    def ingress_change(self, hkey, sw, pn):
        """ Perform a ingress change for the host pair `hkey` to the new switch `sw` `pn`. """
        # Validate the request, get the GID and call the change method
        if hkey not in self.paths:
            logging.info("Can't find pair key %s for ingress change" % hkey)
            return {"path": [], "idp_change": []}
        if self.paths[hkey]["ingress"] == (sw, pn):
            logging.info("Ingress change %s %s is already ingress of path %s" % (sw, pn, hkey))
            return {"path": [], "idp_change": []}

        if ("ingress_change_detect" not in self.paths[hkey] or
                (sw, pn) not in self.paths[hkey]["ingress_change_detect"]):
            logging.critical("New ingress %s %s is not in ingress change of path %s" % (sw, pn, hkey))
            logging.critical(self.paths[hkey])
            raise Exception("STOP EXECUTION (CRITICAL ERROR)")
#            self.paths[hkey]["ingress_change_detect"] = [(sw, pn)]
#            return {"path": [], "idp_change": {}}

        gid = self._get_gid(hkey[0], hkey[1])
        try:
            self._ingress_change(gid, sw, pn)
        except Exception as e:
            logging.critical("Ingress change failure")
            logging.critical("%s %s %s %s" % (gid, sw, pn, hkey))
            logging.critical(self.paths[hkey])
            raise e

        # Retrieve and return the ingress change result
        res = {"path": [], "idp_change": []}
        for hkey in self.ctrl_com.idp_change:
            obj = {"keysrc": hkey[0], "keydst": hkey[1], "instructions": []}

            # Get the new path and convert it to a simple node list
            pinfo = self.paths[hkey]
            path = ppc.group_table_to_path(pinfo, self.graph, pinfo["ingress"])
            path_simple = []
            for p in path:
                if p[0] not in path_simple:
                    path_simple.append(p[0])
                if p[1] not in path_simple:
                    path_simple.append(p[1])
            res["path"] = path_simple

            # Add the modified inter domnain path rules to the result
            for inst in self.ctrl_com.inter_dom_paths[hkey]:
                obj["instructions"].append({"action": "add", "in": inst["in"], "out": inst["out"]})
            res["idp_change"].append(obj)
        return res

    def load_flow_demand(self, file_path):
        """ Load flow demands from a JSON file to the path stats.

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
        """ Load the traffic on the topology from a JSON file

        Args:
            file_path (str): Path to JSON file to load
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

    def install_path_dict(self, path_key, path_dict, combine_gp={},
                                                combine_special_flows={}):
        """ Call the parent method but also save the key of the new path.
        This method is called by the TE optimisation CSPF recomputation
        method to install the new computed CSPF paths.
        """
        super(DummyCtrl, self).install_path_dict(path_key, path_dict,
                                combine_gp, combine_special_flows)
        self.te_mod_paths.append(path_key)

    def invert_group_ports(self, hkey, sw, groupID):
        """ Call the parent method but also save the key of the modified paths """
        super(DummyCtrl, self).invert_group_ports(hkey, sw, groupID)
        self.te_mod_paths.append(hkey)

    def is_inter_domain_link(self, sw, port):
        res = super(DummyCtrl, self).is_inter_domain_link(sw, port)
        self.logger.info("IS INTER DOM %s %s : %s" % (sw, port, res))
        return res

    def te_optimisation(self, flow_demand_path, topo_traffic_path, over_util_path, inter_dom_links):
        self.load_flow_demand(flow_demand_path)
        self.load_topo_traffic(topo_traffic_path)
        self.load_over_util_links(over_util_path)

        # Add the inter-domain links
        for idl in inter_dom_links:
            self.unknown_links[(idl[0], idl[1])] = idl[2]

        self.TE._optimise_TE()
        self.logger.info(self.TE.inter_domain_over_util)

        result = {"res": {}, "failed_inter_dom_links": [], "idp_change": []}
        for hkey in self.te_mod_paths:
            path = ppc.group_table_to_path(self.paths[hkey], self.graph, self.paths[hkey]["ingress"])
            path_simple = []
            for p in path:
                if p[0] not in path_simple:
                    path_simple.append(p[0])
                if p[1] not in path_simple:
                    path_simple.append(p[1])
            src,dst = hkey
            if src not in result["res"]:
                result["res"][src] = {}
            if dst not in result["res"][src]:
                result["res"][src][dst] = {}

            # If we are the start or end segment, we need to add the src and dst node to the
            # path otherwise the returned path won't make sense to YATES.
            if src in self.hosts and src not in path_simple:
                path_simple.insert(0, src)
            if dst in self.hosts and dst not in path_simple:
                path_simple.append(dst)

            result["res"][src][dst]["primary"] = path_simple
            result["res"][src][dst]["secondary"] = []
            result["res"][src][dst]["splice"] = []

        for idl_key, idl_data in self.ctrl_com.congested_info.iteritems():
            obj = {"sw": idl_key[0], "port": idl_key[1], "path_keys": []}

            for idl_path_key,idl_path_usage in idl_data["path_keys"]:
                obj["path_keys"].append({
                    "keysrc": idl_path_key[0],
                    "keydst": idl_path_key[1],
                    "traff_bps": idl_path_usage
                })

            obj["traff_bps"] = idl_data["traff_bps"]
            obj["te_thresh"] = self.te_thresh
            result["failed_inter_dom_links"].append(obj)

        for hkey in self.ctrl_com.idp_change:
            obj = {"keysrc": hkey[0], "keydst": hkey[1], "instructions": []}

            for inst in self.ctrl_com.inter_dom_paths[hkey]:
                obj["instructions"].append({"action": "add", "in": inst["in"], "out": inst["out"]})

            result["idp_change"].append(obj)
        return result


# ---------- HELPER METHODS -----------


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
                dst_p = int(obj["destPort"])
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

def load_inter_dom_links (file_path, topo):
    """ Load the inter-domain information from a JSON file and strip the topology
    of the links, simulating controller behaivour.

    Args:
        file_path (str): Path to JSON file that contains inter-dom links
        topo (dict): Loaded topology object to strip of inter-dom links

    Returns:
        (dict): Inter-domain links in format {(src_sw, src_pn, dst_sw): ncid}
    """
    inter_dom_links = {}

    with open(file_path, "r") as fin:
        try:
            for l in json.load(fin):
                (src_sw, src_pn, dst_sw, ncid) = l
                key = (src_sw, src_pn, dst_sw)
                inter_dom_links[key] = ncid
        except:
            return None
    return inter_dom_links


if __name__ == "__main__":
    # Initiate the argument parser and logging module
    parser = CustomArgParser("Yates SDN Controller Interface", logging)
    parser.add_argument("--cid", required=True, type=str, default=None,
        help="CID of the local controller.")
    parser.add_argument("--action", required=True, type=Action, choices=list(Action),
        help="topo = Compute paths | te = Check congestion | inter_dom = Compute ID paths | ing_change = Ingress change")
    parser.add_argument("--topo", required=True, type=str, default=None,
        help="Path to topology JSON file")
    parser.add_argument("--inter_dom_links", required=True, type=str, default=None,
        help="Path to inter-domain links JSON file")
    parser.add_argument("--inter_dom_inst", required=False, type=str, default=None,
        help="Path to inter-domain instructions file")
    parser.add_argument("--flow_demand", required=False, type=str, default=None,
        help="(TE Action Only) path to src-dst demand JSON file")
    parser.add_argument("--topo_traffic", required=False, type=str, default=None,
        help="(TE Action Only) path to topology link traffic JSON file")
    parser.add_argument("--over_util", required=False, type=str, default=None,
        help="(TE Action Only) path to over utilised link JSON file")
    parser.add_argument("--te_thresh", required=False, type=float, default=None,
        help="(TE Action Only) TE Threshold value for optimisation")
    parser.add_argument("--te_opti_method", required=False, type=str, default="FirstSol",
        help="(TE Action Only) TE opti method: FirstSol (default), BestSolUsage, BestSolPLen, CSPFRecomp")
    parser.add_argument("--te_candidate_sort_rev", required=False, type=str, default="true",
        help="(TE Action Only) TE sort src-dest candidate in decending (true, default) or ascending order (false)")
    parser.add_argument("--te_pot_path_sort_rev", required=False, type=str, default="false",
        help="(TE Action Only) TE sort pot path set in decending (true) or ascending order (false, default)")
    parser.add_argument("--te_paccept", required=False, type=str, default="false",
        help="(TE Action Only) TE accept partial solutions (true) or not (false, default)")
    parser.add_argument("--ing_change_sw", required=False, type=str, default=None,
        help="(Ingress Change Only) New ingress switch")
    parser.add_argument("--ing_change_pn", required=False, type=int, default=None,
        help="(Ingress Change Only) New ingress switch port number")
    parser.add_argument("--ing_change_key_src", required=False, type=str, default=None,
        help="(Ingress Change Only) Ingress changed for path with key pair (source)")
    parser.add_argument("--ing_change_key_dst", required=False, type=str, default=None,
        help="(Ingress Change Only) Ingress changed for path with key pair (destination)")
    args = parser.parse_args()

    logging_format = "|" + args.cid + "|%(levelname)s| %(message)s"
    logging.basicConfig(format=logging_format, level=1000)

    # Convert the boolean strings to boolean values
    args.te_candidate_sort_rev = False if (args.te_candidate_sort_rev.lower() == "false") else True
    args.te_pot_path_sort_rev = True if (args.te_pot_path_sort_rev.lower() == "true") else False
    args.te_paccept = True if (args.te_paccept.lower() == "true") else False

    # Validate required arguments and prime required information
    if not os.path.isfile(args.topo):
        logging.info("Topo path file (%s) dosen't exist" % args.topo)
        exit(1)
    topo, hosts = load_topo(args.topo)
    if topo is None or hosts is None:
        logging.info("Error while parsing topo file %s" % args.topo)
        exit(1)

    if not os.path.isfile(args.inter_dom_links):
        logging.info("Inter-domain links file (%s) dosen't exist" % args.inter_dom_links)
        exit(1)
    inter_dom_links = load_inter_dom_links(args.inter_dom_links, topo)
    if inter_dom_links is None:
        logging.info("Error parsing inter-domain links file %s" % args.inter_dom_links)

    if args.cid is None:
        logging.info("Local controller needs CID provided to it")
        exit(1)

    CID = args.cid
    TEMP_PATH_FILE = TEMP_PATH_FILE % CID
    RET_RES = {}
    inter_dom_inst = {}

    # Initiate the controller object with the te-threshold if specified
    ctrl = None
    if args.te_thresh is None:
        ctrl = DummyCtrl(topo=topo, hosts=hosts, logger=logging,
                te_opti_method=args.te_opti_method,
                te_candidate_sort_rev=args.te_candidate_sort_rev,
                te_pot_path_sort_rev=args.te_pot_path_sort_rev,
                te_paccept=args.te_paccept
        )
    else:
        ctrl = DummyCtrl(topo=topo, hosts=hosts, logger=logging,
                te_thresh=args.te_thresh,
                te_opti_method=args.te_opti_method,
                te_candidate_sort_rev=args.te_candidate_sort_rev,
                te_pot_path_sort_rev=args.te_pot_path_sort_rev,
                te_paccept=args.te_paccept
        )

    # If the action is anything other than intra domain path computation load
    # inter-domain path instructions
    if args.action != Action.topo:
        if ((args.inter_dom_inst is None) or (not os.path.isfile(args.inter_dom_inst))):
            logging.info("No inter-domain path instruction file provided or file invalid")
            exit(1)

        # Unserialize inter-domain instructions from the provided file
        with open(args.inter_dom_inst, "r") as fin:
            for obj in json.load(fin):
                src = obj["keysrc"]
                dst = obj["keydst"]
                hkey = (src, dst)
                for inst in obj["instructions"]:
                    if isinstance(inst["in"], list):
                        inst["in"] = tuple(inst["in"])
                    if isinstance(inst["out"], list):
                        inst["out"] = tuple(inst["out"])
                    inst["out_addr"] = "0.0.0.0"
                    inst["out_eth"] = "00:00:00:00:00:00"
                inter_dom_inst[hkey] = obj["instructions"]

    # ----------- PERFORM THE REQUIRED ACTION ----------

    # Handle intra-dommain path computation operation
    try:
        if args.action == Action.topo:
            logging.info("Action is compute topology (topo)")
            ctrl._install_protection()

            for hkey,data in ctrl.get_computed_paths().iteritems():
                host_1, host_2 = hkey
                if host_1 not in RET_RES:
                    RET_RES[host_1] = {}
                if host_2 not in RET_RES[host_1]:
                    RET_RES[host_1][host_2] = {}
                RET_RES[host_1][host_2] = data

        # Handle ingress change action
        elif args.action == Action.ing_change:
            logging.info("Action is ingress change detection notification")

            if (args.ing_change_key_src is None or args.ing_change_key_dst is None or
                    args.ing_change_sw is None or args.ing_change_pn is None):
                logging.critical("Required ingress change argumets were not provided")
                print(json.dumps({"path": [], "idp_change": {}}))
                exit(0)

            # Load the old paths and perform the ingress change operation
            ctrl.load_path_info()
            ctrl.set_inter_dom_path_instructions(inter_dom_inst)
            hkey = (args.ing_change_key_src, args.ing_change_key_dst)
            RET_RES = ctrl.ingress_change(hkey, args.ing_change_sw, args.ing_change_pn)

        elif args.action == Action.inter_dom:
            logging.info("Action is compute inter-domain path (inter_dom)")

            # Restore the old computed path dictionary and process instructions
            ctrl.load_path_info()
            RET_RES = ctrl.compute_path_segments(inter_dom_inst, inter_dom_links)

        elif args.action == Action.te:
            logging.info("Action is optimise TE (te)")
            if (args.flow_demand is None or args.topo_traffic is None or
                    args.over_util is None or args.te_thresh is None):
                logging.info("Not all required TE arguments were provided")
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

            ctrl.load_path_info()
            ctrl.set_inter_dom_path_instructions(inter_dom_inst)
            RET_RES = ctrl.te_optimisation(args.flow_demand, args.topo_traffic,
                                           args.over_util, inter_dom_links)

        # Save any path dicitionary information modifications
        ctrl.save_path_info()
    except Exception as e:
        logging.critical("EXCEPTION: %s" % e)
        logging.critical(e, exc_info=True)
        #logging.critical(ctrl.paths.keys())

        # Serialize default empty result to ignore error and not crash YATES
        if args.action == Action.topo:
            RET_RES = {}
        elif args.action == Action.ing_change:
            RET_RES = {"path": [], "idp_change": []}
        elif args.action == Action.inter_dom:
            RET_RES = {}
        elif args.action == Action.te:
            RET_RES = {"res": {}, "failed_inter_dom_links": [], "idp_change": []}

    logging.info("Returned data to YATES")
    logging.info("------\n%s\n-----" %  json.dumps(RET_RES, indent=1, sort_keys=True))
    print(json.dumps(RET_RES))
