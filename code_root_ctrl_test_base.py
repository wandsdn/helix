#!/usr/bin/python
import logging
import unittest

from RootCtrl import RootCtrl


class DummyRootCtrl(RootCtrl):
    """ Dummy root controller that inherits from the main root controller module. Overide
    some methods to disable the communication channel functionality and some logging features
    """
    def __init__(self, revsort, logger=None):
        # If the logger is not defined init one that suppresses all errors
        if logger is None:
            logging.basicConfig(format="[%(levelname)1.1s] %(funcName)-20.20s : %(message)s")
            logger = logging.getLogger("RootCtrl")
            logger.setLevel(1000)

        super(DummyRootCtrl, self).__init__(logger, te_candidate_sort_rev=revsort)

    def start(self):
        """ On start call do not do anything """
        pass

    def stop(self):
        """ On stop do not do anything """
        pass

    def _safe_send(self, routing_key, data):
        self.logger.info("Send data (RK: %s) -> %s" % (routing_key, data))

    def _safe_cmd(self, action):
        self.logger.info("Safe CMD")

    def _write_controller_state(self):
        """ On write controller state do not do anything """
        pass

    def _init_keep_alive_timer(self, cid, count=0):
        """ On initiate of keep alive controller timer just clear the controller dictionary entry """
        self._ctrls[cid] = {"timer": None, "count": 0}

    def init_local_controller(self, cid):
        """ Helper method that initiates a new local controller instance """
        if cid not in self._ctrls:
            self._init_keep_alive_timer(cid)
            self._topo[cid] = {"hosts": [], "switches": [], "neighbours": {}, "te_thresh": 0}

class BaseRootCtrlTest(unittest.TestCase):
    # Do not sort candidates in reverse (lowest candidates checked first)
    revsort = False

    # Scenario controller information (hosts and switches)
    LOCAL_CONTROLLERS = {
        "c1": {"hosts": ["h1", "h2"], "switches": ["s1", "s02", "s03"]},
        "c2": {"hosts": [], "switches": ["s04", "s05", "s06", "s07"]},
        "c3": {"hosts": ["h8"], "switches": ["s08", "s09"]},
        "c4": {"hosts": [], "switches": ["s10", "s11", "s12"]},
        "c5": {"hosts": [], "switches": ["s13", "s14", "s15"]}
    }

    # Scenario list of inter-domain dictionary entries where the we have two keys. The syntax is <a>
    # to <b> or vice-versa where the value is tripple of syntax (<cid>, <switch>, <port>).
    INTER_DOM_LINKS = [
        {"a": ("c1", "s02", 4), "b": ("c2", "s04", 3)},
        {"a": ("c1", "s02", 5), "b": ("c2", "s06", 4)},
        {"a": ("c1", "s02", 6), "b": ("c4", "s10", 3)},
        {"a": ("c2", "s05", 4), "b": ("c3", "s08", 3)},
        {"a": ("c2", "s07", 3), "b": ("c3", "s09", 2)},
        {"a": ("c3", "s09", 3), "b": ("c5", "s15", 3)},
        {"a": ("c4", "s12", 3), "b": ("c5", "s14", 3)}
    ]

    # Dictionary of default inter-domain paths computed by the root controller. Used to check that
    # the controller state is correct.
    DEFAULT_PATHS = {
        ("h1", "h8"): {
            "prim": ["h1", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"],
            "sec": ["h1", "c1", "s02", "s06", "c2", "s07", "s09", "c3", "h8"]},
        ("h2", "h8"): {
            "prim": ["h2", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"],
            "sec": ["h2", "c1", "s02", "s06", "c2", "s07", "s09", "c3", "h8"]},
        ("h8", "h1"): {
            "prim": ["h8", "c3", "s08", "s05", "c2", "s04", "s02", "c1", "h1"],
            "sec": ["h8", "c3", "s09", "s07", "c2", "s06", "s02", "c1", "h1"]},
        ("h8", "h2"): {
            "prim": ["h8", "c3", "s08", "s05", "c2", "s04", "s02", "c1", "h2"],
            "sec": ["h8", "c3", "s09", "s07", "c2", "s06", "s02", "c1", "h2"]}
    }

    # Dictionary of inter-domain instructions computed by the root controller for the default paths.
    # These instructions are sent to the local controllers.
    DEFAULT_INSTRUCTIONS = {
        "c1": {
            ("h1", "h8"): [
                {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."},
                {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."}],
            ("h2", "h8"): [
                {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."},
                {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."}],
            ("h8", "h1"): [
                {"action": "add", "in": ("s02", 4), "out": -1, "out_eth": "a::"},
                {"action": "add", "in": ("s02", 5), "out": -1, "out_eth": "a::"}],
            ("h8", "h2"): [
                {"action": "add", "in": ("s02", 4), "out": -1, "out_eth": "a::"},
                {"action": "add", "in": ("s02", 5), "out": -1, "out_eth": "a::"}]
        }, "c2": {
            ("h1", "h8"): [
                {"action": "add", "in": ("s04", 3), "out": ("s05", 4)},
                {"action": "add", "in": ("s06", 4), "out": ("s07", 3)}],
            ("h2", "h8"): [
                {"action": "add", "in": ("s04", 3), "out": ("s05", 4)},
                {"action": "add", "in": ("s06", 4), "out": ("s07", 3)}],
            ("h8", "h1"): [
                {"action": "add", "in": ("s05", 4), "out": ("s04", 3)},
                {"action": "add", "in": ("s07", 3), "out": ("s06", 4)}],
            ("h8", "h2"): [
                {"action": "add", "in": ("s05", 4), "out": ("s04", 3)},
                {"action": "add", "in": ("s07", 3), "out": ("s06", 4)}],
        }, "c3": {
            ("h1", "h8"): [
                {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"},
                {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"}],
            ("h2", "h8"): [
                {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"},
                {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"}],
            ("h8", "h1"): [
                {"action": "add", "in": -1, "out": ("s08", 3), "out_addr": "0."},
                {"action": "add", "in": -1, "out": ("s09", 2), "out_addr": "0."}],
            ("h8", "h2"): [
                {"action": "add", "in": -1, "out": ("s08", 3), "out_addr": "0."},
                {"action": "add", "in": -1, "out": ("s09", 2), "out_addr": "0."}],
        }
    }

    def _set_link_capacity(self, a, b, cap):
        """ Helper method that sets the capacity of a inter-domain link, identified by a triple
        with format (<cid>, <sw>, <port>). If `a` and `b` dosen't exist in `:cls:attr:(INTER_DOM_LINKS)`
        a new link entry is added.

        Args:
            a (triple): A component of the inter-domain link
            b (triple): B component of the inter-domain link
            cap (int): Capacity of port in bytes
        """
        found = False
        for idp in self.INTER_DOM_LINKS:
            if idp["a"] == a and idp["b"] == b:
                idp["capacity"] = cap
                found = True
                break

        if not found:
            self.INTER_DOM_LINKS.append({"a": a, "b": b, "capacity": cap})

    def _get_hosts_triple_list(self, hosts):
        """ Return a list of host triples used by the root controller. The triplers syntax is
        (<host>, <ethernet address>, <ip address>).

        Args:
            hosts (list): List of hosts

        Returns:
            list: List of host triples
        """
        ret = []
        for h in hosts:
            ret.append((h, "a::", "0."))
        return ret

    def _check_computed_paths(self, paths={}, inst={}):
        """ Check that the paths computed by the root controller are correct. Method checks ```old_paths```
        and ```old_send``` against `paths` and `inst` respectively. XXX For paths, method will
        only check the list of nodes and not the list of ports. It's assumes that this is correct if
        the path and instructions are correct.

        Args:
            paths (dict): Expected path dictionary (both primary and secondary for both)
            inst (dict): Expected path instructions
        """
        # Build the expected paths dictionary by combining the default with the modified
        exp_paths = {}
        for hkey,path in self.DEFAULT_PATHS.iteritems():
            if hkey not in paths:
                exp_paths[hkey] = path
        for hkey,path in paths.iteritems():
            # Check if we have a path that should no longer exist
            if path is None:
                continue
            exp_paths[hkey] = path

        # Build the expected path instruction dictionary by combining the default with the modified
        exp_inst = {}
        for cid,data in self.DEFAULT_INSTRUCTIONS.iteritems():
            if cid not in inst:
                exp_inst[cid] = data
            else:
                if inst[cid] is None:
                    continue

                # Prime the expected dictionary if not already primed
                if cid not in exp_inst:
                    exp_inst[cid] = {}

                for hkey,path in data.iteritems():
                    if hkey not in inst[cid]:
                        exp_inst[cid][hkey] = path

        for cid,data in inst.iteritems():
            # If we have a removed CID do not add it
            if data is None:
                continue

            # Prime the expected dictionary if not already primed
            if cid not in exp_inst:
                exp_inst[cid] = {}

            for hkey,path in data.iteritems():
                # If the hkey is removed skip it
                if path is None:
                    continue

                exp_inst[cid][hkey] = path

        # Check the computed paths
        for key,paths in exp_paths.iteritems():
            ctrl_paths = self.ctrl._old_paths
            ctrl_prim = ctrl_paths[key][0][0]
            ctrl_sec = ctrl_paths[key][1][0]
            exp_prim = paths["prim"]
            exp_sec = paths["sec"]

            self.assertIn(key, ctrl_paths, msg="Path %s not in old_paths" % str(key))
            self.assertEqual(exp_prim, ctrl_prim,
                    msg="Primary path for %s not correct (%s != %s)" % (key, exp_prim, ctrl_prim))
            self.assertEqual(exp_sec, ctrl_sec,
                    msg="Secondary path for %s not correct (%s != %s)" % (key, exp_sec, ctrl_sec))

        for key,paths in self.ctrl._old_paths.iteritems():
            self.assertIn(key, exp_paths, msg="Extra path (%s) in old_paths" % str(key))

        # Check the send dictionary
        for cid,info in exp_inst.iteritems():
            ctrl_send = self.ctrl._old_send

            self.assertIn(cid, ctrl_send, msg="CID %s not in sent inter-domain instructions" % cid)
            for hkey,data in info.iteritems():
                self.assertIn(hkey, ctrl_send[cid],
                    msg="CID %s path key %s not in inter-domain instructions" % (cid, hkey))
                self.assertEqual(data, ctrl_send[cid][hkey],
                    msg="CID %s path %s not correct (%s != %s)" % (cid, hkey, data, ctrl_send[cid][hkey]))

        for cid,info in self.ctrl._old_send.iteritems():
            self.assertIn(cid, exp_inst, msg="Extra CID %s in sent inter-domain instructions" % cid)

            for hkey,data in info.iteritems():
                self.assertIn(hkey, exp_inst[cid],
                    msg="CID %s extra path key %s in inter-domain instructions" % (cid, hkey))

    def setUp(self):
        """ Initiate a dummy root controller instance and prime the topology and local controller info """
        self.ctrl = DummyRootCtrl(self.revsort)
        self._expected_topo_neighbours = {}

        # Add the local controllers
        for cid,data in self.LOCAL_CONTROLLERS.iteritems():
            self.ctrl.init_local_controller(cid)
            obj = {"cid": cid, "hosts": self._get_hosts_triple_list(data["hosts"]),
                    "switches": data["switches"], "unknown_links": {}, "te_thresh": 0.90}
            self.ctrl._action_topo(obj)

        # Add the inter-domain links
        for idl in self.INTER_DOM_LINKS:
            a_cid,a_sw,a_pn = idl["a"]
            b_cid,b_sw,b_pn = idl["b"]

            cap = 1000000000
            if "capacity" not in idl:
                idl["capacity"] = cap
            else:
                cap = idl["capacity"]

            a_obj = {"cid": a_cid, "sw": a_sw, "port": a_pn, "speed": cap, "dest_sw": b_sw}
            b_obj = {"cid": b_cid, "sw": b_sw, "port": b_pn, "speed": cap, "dest_sw": a_sw}
            self.ctrl._action_unknown_sw(a_obj)
            self.ctrl._action_unknown_sw(b_obj)

            # Build the exepected topology neighbours dictionary
            if a_cid not in self._expected_topo_neighbours:
                self._expected_topo_neighbours[a_cid] = {}
            if b_cid not in self._expected_topo_neighbours:
                self._expected_topo_neighbours[b_cid] = {}
            self._expected_topo_neighbours[a_cid][(b_cid, a_sw, a_pn)] = {"switch": b_sw, "port": b_pn}
            self._expected_topo_neighbours[b_cid][(a_cid, b_sw, b_pn)] = {"switch": a_sw, "port": a_pn}

    def test_case_00(self):
        """ Default test case that checks the initial topology is correct """
        print("\nTesting topology initiation of controller")
        topo = self.ctrl._topo

        # Check the controller topology information
        for cid,data in self.LOCAL_CONTROLLERS.iteritems():
            self.assertIn(cid, topo, msg="CID not in controller topology")
            self.assertEqual(0.90, topo[cid]["te_thresh"],
                    msg="CID %s topo te-threshold incorrect (0.90 != %.2f)" % (cid, topo[cid]["te_thresh"]))
            self.assertEqual(self._get_hosts_triple_list(data["hosts"]), topo[cid]["hosts"],
                    msg="CID %s topo hosts incorrect (%s != %s)" % (cid, topo[cid]["hosts"], data["hosts"]))
            self.assertEqual(data["switches"], topo[cid]["switches"],
                    msg="CID %s topo sw incorrect (%s != %s)" % (cid, topo[cid]["switches"], data["switches"]))

            for nkey,ndata in self._expected_topo_neighbours[cid].iteritems():
                self.assertIn(nkey, topo[cid]["neighbours"],
                    msg="CID %s topo neighbour key %s not in topo" % (cid, nkey))
                self.assertEqual(ndata["switch"], topo[cid]["neighbours"][nkey]["switch"],
                    msg="CID %s topo neighbour with key %s, sw incorrect" % (cid, nkey))
                self.assertEqual(ndata["port"], topo[cid]["neighbours"][nkey]["port"],
                    msg="CID %s topo neighbour with key %s, port incorrect" % (cid, nkey))

            for nkey,ndata in topo[cid]["neighbours"].iteritems():
                self.assertIn(nkey, self._expected_topo_neighbours[cid],
                    msg="CID %s topo neighour has extra key %s" % (cid, nkey))


# --------------------------------------------------------------------

def p_to_bit(u, c=1000000000):
    """ Convert a usage percentage `u` to bits based on the link capacity
    `c` expresed in bps. """
    bits = float(c)*float(u)
    return bits
