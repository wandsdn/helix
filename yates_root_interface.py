#!/usr/bin/python
import re
import os
from enum import Enum
import json
import logging

from argparse import ArgumentParser
from RootCtrl import RootCtrl


# Location of temporary path file (used to preserve path info outside yates)
TEMP_PATH_FILE = "/tmp/paths.root.tmp"
TEMP_PATH_INST_FILE = "/tmp/inst.root.tmp"


class Action(Enum):
    """ Enumaration class used to restrict and select the supported actions of
    the interface.
    """
    topo = "topo"
    te = "te"
    ing_egg_change = "ing_egg_change"

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


class DummyRootCtrl(RootCtrl):
    """ Dummy root controller used by the interface. Disable all communication channel actions """

    def __init__(self, logger=None, te_candidate_sort_rev=True, te_paccept=False):
        # If the logger is not defined init one that suppresses all errors
        if logger is None:
            logging.basicConfig(format="[%(levelname)1.1s] %(funcName)-20.20s : %(message)s")
            logger = logging.getLogger("RootCtrl")
            logger.setLevel(100)

        self.__send_inst = {}
        super(DummyRootCtrl, self).__init__(logger, te_candidate_sort_rev, te_paccept)

    def start(self):
        pass

    def stop(self):
        pass

    def _safe_send(self, routing_key, data):
        """ Dummy safe send method that saves all instructions in a temporary dictionary """
        if routing_key not in self.__send_inst:
            self.__send_inst[routing_key] = []
        self.__send_inst[routing_key].append(data)

    def _safe_cmd(self, action):
        pass

    def _write_controller_state(self):
        """ Save the controller state to temporary files. The method will save `:cls:attr:(_old_paths)`
        and `:cls:attr:(_old_send)` to `:mod:attr:(TEMP_PATH_FILE)` and `:mod:attr:(TEMP_PATH_INST_FILE)`
        respectively.
        """
        self.logger.debug("Writing computed paths to temporary file")
        ser = []
        for hkey,paths in self._old_paths.iteritems():
            ser.append({
                "keysrc": hkey[0], "keydst": hkey[1],
                "paths": paths
            })
        with open(TEMP_PATH_FILE, "w") as f:
            f.write(json.dumps(ser))

        self.logger.debug("Writing computed inter-domain instructions to file")
        ser = {}
        for cid,cid_d in self._old_send.iteritems():
            if cid not in ser:
                ser[cid] = []
            for hkey,insts in cid_d.iteritems():
                ser[cid].append({
                    "keysrc": hkey[0], "keydst": hkey[1],
                    "instructions": insts
                })
        with open(TEMP_PATH_INST_FILE, "w") as f:
            f.write(json.dumps(ser))

    def _init_keep_alive_timer(self, cid, count=0):
        """ On initiate of a controller keep alive just clear the controller dictionary """
        self._ctrls[cid] = {"timer": None, "count": 0}

    def init_local_controller(self, cid):
        """ Helper method that initiates a new local controller instance """
        if cid not in self._ctrls:
            self._init_keep_alive_timer(cid)
            self._topo[cid] = {"hosts": [], "switches": [], "neighbours": {}, "te_thresh": 0}

    def load_topology(self, fpath_map, fpath_topo):
        """ Build the root controller topology from a switch-to-controller map `fpath_map` and
        a topology file `fpath_topo` (to get link speeds).

        Args:
            fpath_map (str): Switch to controller map file path
            fpath_topo (str): Topology file path
        """
        # Load the map file and topology file
        sw_ctrl_map = self._load_sw_ctrl_map(fpath_map)
        if sw_ctrl_map is None:
            self.logger.info("Error while parsing SW ctrl map file %s" % fpath_map)
            return False

        link_speeds = {}
        with open(fpath_topo, "r") as fin:
            tmp_topo = json.load(fin)
            if "topo" in tmp_topo:
                tmp_topo = tmp_topo["topo"]
                for link in tmp_topo:
                    key = (link["src"], link["srcPort"])
                    link_speeds[key] = link

        # Go through and build the root controller topology
        for cid,cid_d in sw_ctrl_map.iteritems():
            self.init_local_controller(cid)
            hosts = []
            for h in cid_d["host"]:
                hosts.append((h, "a::", "0."))

            cid_obj = {"cid": cid, "hosts": hosts, "switches": cid_d["sw"],
                        "unknown_links": {}, "te_thresh": 0.90}
            self._action_topo(cid_obj)

        for cid,cid_d in sw_ctrl_map.iteritems():
            for ncid,idls in cid_d["dom"].iteritems():
                for idl in idls:
                    src_sw = idl["sw"]
                    src_pn = int(idl["port"])
                    dst_sw = idl["sw_to"]
                    dst_pn = int(idl["port_to"])

                    # Check if we have link speed
                    cap = 1000000000
                    speed_key = (src_sw, src_pn)
                    if speed_key in link_speeds:
                        if (link_speeds[speed_key]["dest"] == dst_sw and
                                link_speeds[speed_key]["destPort"] == dst_pn and
                                "speed" in link_speeds[speed_key]):
                            cap = link_speeds[speed_key]["speed"]

                    obj = {"cid": cid, "sw": src_sw, "port": src_pn, "dest_sw": dst_sw, "speed": cap}
                    self._action_unknown_sw(obj)

        return True

    def _load_sw_ctrl_map(self, fpath):
        """ Unserialize a switch-to-controller map JSON file.

        Args:
            fpath (str): Path to the JSON file

        Returns:
            dict: Switch to controller object or None if file is corrupt
        """
        topo = {}
        with open(fpath, "r") as fin:
            try:
                data = json.load(fin)
                topo = data["ctrl"]
            except:
                return None
        return topo

    def clear_old_state(self):
        """ Clear the old state of the controller """
        self.logger.info("Clearing old state of the controller")
        self._old_paths = {}
        self._old_send = {}

    def load_old_state(self):
        """ Load the old controller state from the temporary files """
        self._load_old_paths()
        self._load_old_send()

    def _load_old_paths(self):
        """ Unserialize the old computed path dictionary for the temporary JSON file """
        old_paths = {}
        if not os.path.exists(TEMP_PATH_FILE) or not os.path.isfile(TEMP_PATH_FILE):
            # If there is no file we have no old state
            self.logger.info("Old path temporary file dosen't exist, can't load %s" % TEMP_PATH_FILE)
            return

        with open(TEMP_PATH_FILE, "r") as fin:
            for obj in json.load(fin):
                src = obj["keysrc"]
                dst = obj["keydst"]
                key = (src, dst)
                paths = obj["paths"]

                if key not in old_paths:
                    old_paths[key] = []

                for path in paths:
                    p = path[0]
                    ports = []
                    for port in path[1]:
                        ports.append((port[0], port[1], port[2]))
                    old_paths[key].append((p, ports))

        self.logger.info("Loaded old paths from temporary file %s" % TEMP_PATH_FILE)
        self._old_paths = old_paths

    def _load_old_send(self):
        """ Unserialize the old send dictionary from the temporary JSON file """
        old_send = {}
        if not os.path.exists(TEMP_PATH_INST_FILE) or not os.path.isfile(TEMP_PATH_INST_FILE):
            # If there is no file we have no old state
            self.logger.info("Old send temporary file dosen't exist, can't load %s" % TEMP_PATH_INST_FILE)
            return

        with open(TEMP_PATH_INST_FILE, "r") as fin:
            for cid,cid_d in json.load(fin).iteritems():
                if cid not in old_send:
                    old_send[cid] = {}

                for obj in cid_d:
                    src = obj["keysrc"]
                    dst = obj["keydst"]
                    key = (src, dst)
                    insts = obj["instructions"]

                    tmp_insts = []
                    for inst in insts:
                        if isinstance(inst["in"], list):
                            inst["in"] = tuple(inst["in"])
                        if isinstance(inst["out"], list):
                            inst["out"] = tuple(inst["out"])
                        tmp_insts.append(inst)
                    old_send[cid][key] = tmp_insts

        self.logger.info("Loaded old send information from temporary file %s" % TEMP_PATH_INST_FILE)
        self._old_send = old_send

    def load_topo_traffic (self, fpath):
        """ Load topology traffic of inter-domain links from the JSON file `fpath`.

        Args:
            fpath (str): Path of JSON file to load

        Returns:
            bool: True if sucesfully loaded, False otherwise
        """
        with open(fpath, "r") as fin:
            try:
                for obj in json.load(fin):
                    src = obj["src"]
                    src_port = int(obj["src_port"])
                    traff_bps = int(obj["val"])

                    # Find the port capacity from the topology
                    port_info = self._graph.get_port_info(src, src_port)
                    if port_info is None:
                        raise Exception("Invalid Port")
                    port_speed = port_info["speed"]

                    # Update the inter-domain port information
                    cid = self._find_sw_cid(src)
                    self._action_inter_domain_link_traffic({
                        "cid": cid, "sw": src, "port": src_port,
                        "traff_bps": traff_bps
                    })
            except Exception as e:
                return False
        return True

    def compute_paths(self):
        """ Compute inter-domain paths by calling the relevant controller method and returning a
        dictionary of inter-domain instructions as the result. Note that this method will clear
        `:cls:mod:(__send_inst)` to return controller instrctions related only to the current operation.

        Returns:
            dict: Inter-domain instructions generated from operation
        """
        self.__send_inst = {}
        ctrl._compute_inter_domain_paths()

        # Go through the safe send information and clean up info
        res = {}
        for rk,data in self.__send_inst.iteritems():
            cid = rk.split(".")[1]
            if cid in self._ctrls:
                if cid not in res:
                    res[cid] = {}

                for msg in data:
                    if "paths" not in msg:
                        continue
                    for hkey,paths in msg["paths"].iteritems():
                        res[cid][hkey] = paths
        return res

    def te_optimisation(self, opti_request):
        """ Perform a TE optimisation for `opti_request`, returing the relevant path modifications as
        inter-domain instructions. Note that this method will clear `:cls:mod:(__send_inst)` to return
        controller instructions only for the current operation.

        Returns:
            dict: Inter-domain instructions generated from opration
        """
        self.__send_inst = {}
        for cid,cid_d in opti_request.iteritems():
            for req in cid_d:
                req["cid"] = cid
                self._action_inter_domain_link_congested(req)

        # Go through the safe send information and clean up info
        res = {}
        for rk,data in self.__send_inst.iteritems():
            cid = rk.split(".")[1]
            if cid in self._ctrls:
                if cid not in res:
                    res[cid] = {}

                for msg in data:
                    if "paths" not in msg:
                        continue
                    for hkey,paths in msg["paths"].iteritems():
                        res[cid][hkey] = paths
        return res

def load_opti_request (fpath):
    """ Load and return a TE optimisation from a JSON file.

    Args:
        fpath (str): Path to the JSON file

    Returns:
        dict: Optimistaion request dictionary or None if invalid
    """
    req = {}
    with open(fpath, "r") as fin:
        try:
            for cid,cid_d in json.load(fin).iteritems():
                if cid not in req:
                    req[cid] = []

                for obj in cid_d:
                    sw = obj["sw"]
                    port = obj["port"]

                    paths = []
                    for tmp in obj["path_keys"]:
                        tmp_src = tmp["keysrc"]
                        tmp_dst = tmp["keydst"]
                        tmp_key = (tmp_src, tmp_dst)
                        tmp_traff_bps = tmp["traff_bps"]
                        paths.append((tmp_key, tmp_traff_bps))

                    req[cid].append({
                        "sw": sw,
                        "port": port,
                        "traff_bps": obj["traff_bps"],
                        "paths": paths,
                        "te_thresh": obj["te_thresh"]
                    })
        except Exception as e:
            logging.critical(e)
            return None
    return req

def load_ing_egg_change (fpath):
    """ Load and return a ingress/egress change notification from a JSON file

    Args:
        fpath (str): Path to the JSON file

    Returns:
        dict: Ingress/egress change request or None if invalid
    """
    req = {}
    with open(fpath, "r") as fin:
        try:
            for cid,cid_d in json.load(fin).iteritems():
                if cid not in req:
                    req[cid] = {}

                for obj in cid_d:
                    src = obj["keysrc"]
                    dst = obj["keydst"]
                    hkey = (src, dst)

                    insts = []
                    for inst in obj["instructions"]:
                        if isinstance(inst["in"], list):
                            inst["in"] = tuple(inst["in"])
                        if isinstance(inst["out"], list):
                            inst["out"] = tuple(inst["out"])
                        insts.append(inst)
                    req[cid][hkey] = insts
        except Exception as e:
            logging.critical(e)
            return None
    return req

if __name__ == "__main__":
    logging.basicConfig(level=1000)

    # Initiate the argument parser
    parser = CustomArgParser("Yates SDN Root Controller Interface", logging)
    parser.add_argument("--action", required=True, type=Action, choices=list(Action),
        help="topo = Compute paths | te = Check Congestion | ing_egg_change = Ingress / Egress change")
    parser.add_argument("--sw_ctrl_map", required=True, type=str, default=None,
        help="Switch to controller mapping file that provided inter-domain topology")
    parser.add_argument("--topo", required=True, type=str, default=None,
        help="Network topology (used to extract inter-dom link speeds)")
    parser.add_argument("--te_opti_req", required=False, type=str, default=None,
        help="(TE Action Only) path to optimisation request file")
    parser.add_argument("--te_candidate_sort_rev", required=False, type=str, default="true",
        help="(TE Action Only) TE sort candidates in decending (true, default) or ascending order (false)")
    parser.add_argument("--te_paccept", required=False, type=str, default="false",
        help="(TE Action Only) TE accept partial solutions (true) or not (false, default)")
    parser.add_argument("--topo_traffic", required=False, type=str, default=None,
        help="(TE Action Only) path to topology link traffic JSON file")
    parser.add_argument("--path_inst", required=False, type=str, default=None,
        help="(Ingress/Egress Change  Action Only) path to the modified instruction JSON file")
    args = parser.parse_args()

    # Convert the boolean strings to boolean values
    args.te_candidate_sort_rev = False if (args.te_candidate_sort_rev.lower() == "false") else True
    args.te_paccept = True if (args.te_paccept.lower() == "true") else False

    # Validate required arguments, initiate controller and build topology
    if not os.path.isfile(args.sw_ctrl_map):
        logging.info("SW Ctrl Map file (%s) dosen't exist" % args.sw_ctrl_map)
        exit(1)

    ctrl = DummyRootCtrl(logging, te_candidate_sort_rev=args.te_candidate_sort_rev,
                                                te_paccept=args.te_paccept)
    if not ctrl.load_topology(args.sw_ctrl_map, args.topo):
        logging.info("Error while loading root controller topology %s" % args.sw_ctrl_map)
        exit(0)

    ctrl.load_old_state()

    # Process the required operation
    result = {}
    if args.action == Action.topo:
        # Compute all inter-domain paths
        logging.info("Action is compute topology (topo)")
        ctrl.clear_old_state()
        result = ctrl.compute_paths()

    elif args.action == Action.te:
        # Perform TE optimisation
        logging.info("Action is optimise TE (te)")
        if not os.path.isfile(args.te_opti_req):
            logging.info("TE optimisation request file (%s) dosen't exist" % args.te_opti_req)
            exit(1)
        if not os.path.isfile(args.topo_traffic):
            logging.info("Topology traffic file (%s) dosen't exist" % args.topo_traffic)
            exit(1)

        opti_request = load_opti_request(args.te_opti_req)
        if opti_request is None:
            logging.info("Optimisation request file is corrupt!")
            exit(1)

        if not ctrl.load_topo_traffic(args.topo_traffic):
            logging.info("Topology traffic file is corrupt!")
            exit(1)

        result = ctrl.te_optimisation(opti_request)

    elif args.action == Action.ing_egg_change:
        logging.info("Action is ingress / egress change")
        # Handle a ingress / egress change by updating the local path information
        if (args.path_inst is None):
            logging.info("Not all required TE arguments were provided")
            exit(1)
        if not os.path.isfile(args.path_inst):
            loging.info("Path instruction file (%s) doen't exist" % args.path_inst)
            exit(1)

        info_change = load_ing_egg_change(args.path_inst)
        if info_change is None:
            logging.info("Path instruction file is corrupt!")
            exit(1)

        for cid,cid_d in info_change.iteritems():
            for hkey,paths in cid_d.iteritems():
                obj = {"cid": cid, "hkey": hkey, "new_paths": paths}
                logging.info("Ingress change: %s" % obj)
                ctrl._path_info_changed(obj)


    # -------------------------------------------------

    # Sanitize, serailize and return the result to the caller (output to std-out)
    res_ser = {}
    for cid,cid_d in result.iteritems():
        res_ser[cid] = []
        for hkey,insts in cid_d.iteritems():
            res_ser[cid].append({
                "keysrc": hkey[0], "keydst": hkey[1],
                "instructions": insts
            })

    print(json.dumps(res_ser))
    logging.info("Returned data to YATES")
    logging.info("------\n%s\n-----" %  json.dumps(res_ser, indent=1, sort_keys=True))
