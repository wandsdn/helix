#!/usr/bin/env python

# -----------------------------------------------------------------
#
# TE optimisation method unit-test that checks that the FirstSol,
# BestSolUsage, BestSolPLen and CSPFRecomp works correctly. Test
# implements the  scenarios defined by the 'TE Opti Method Test'.
# For more info, refer to the folder `Docs/TEOptiMethodTest`.
#
# Run using the command:
#   python -m unittest code_te_opti_method_test
#
# -----------------------------------------------------------------

import copy
import unittest
import logging

from TE import TEOptimisation
from ShortestPath.dijkstra_te import Graph
from ShortestPath.protection_path_computation import group_table_to_path

# Imports used to spoof send and switch for rule extraction
import topo_discovery.api as topo_disc_api
from ryu.ofproto.ofproto_protocol import ProtocolDesc
from ryu.ofproto import ofproto_v1_3
from ryu.topology.switches import Switch

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


def PTB(u, c=1000000000):
    """ Convert usage a usage percentage `u` to bytes based on capacity `c` expressed in bits """
    bits = float(c)*float(u)
    byte = bits/8
    return byte


class DummyCtrlCom:
    """ Dummy controller communication class that stores info about congesed inter-dom links
    that we can't and any ingress or egress changes. """
    def __init__ (self, logger):
        self.inter_dom_paths = {}
        self.logger = logger

    def set_inter_dom_path_instructions(self, inst):
        self.inter_dom_paths = inst

    def notify_inter_domain_congestion(self, sw, port, rate, path_keys):
        pass

    def notify_egress_change(self, hkey, new_egress):
        raise Exception("DO NOT CALL METHOD")

    def notify_ingress_change(self, hkey, old_ingress, new_ingress, old_egress, new_egress):
        raise Exception("DO NOT CALL METHOD")

class DummyCtrl(ProactiveController):
    TESTING_MODE = True

    def __init__(self, topo, hosts, paths, logger, *args, **kwargs):
        super(DummyCtrl, self).__init__(*args, **kwargs)
        self.paths = copy.deepcopy(paths)
        self.graph = Graph(topo)
        self.logger = logger
        self.ctrl_com = DummyCtrlCom(self.logger)
        self.hosts = hosts

    def is_master(self):
        """ We are always the master controller """
        return True

    def get_poll_rate(self):
        """ Always return the poll interval as 1 """
        return 1

    def _init_ing_change_wait(self, hkey):
        """ Do not initiate the ingress change wait timer """
        pass

    def _install_protection(self):
        raise Exception("DO NOT CALL METHOD")

    def compute_path_segments(self, inter_dom_inst, inter_dom_links):
        raise Exception("DO NOT CALL METHOD")

    def ingress_change(self, hkey, sw, pn):
        raise Exception("DO NOT CALL METHOD")

    def te_optimisation(self, flow_demand_path, topo_traffic_path, over_util_path, inter_dom_links):
        raise Exception("DO NOT CALL METHOD DIRRECTLY")

    def is_inter_domain_link(self, sw, port):
        res = super(DummyCtrl, self).is_inter_domain_link(sw, port)
        self.logger.info("IS INTER DOM %s %s : %s" % (sw, port, res))
        return res


class TEOptimisationTest(unittest.TestCase):
    """ TE optimisation method unit test methods

    Arguments:
        DEFAULT_PATH (dict): Dictionary of default primary paths for two host pairs
        DEFAULT_PATH_INFO (dict): Dictionary of default path information for the two host pairs
        ctrl (DummyCtrl): Dummy controller object to test the TE module with
    """

    DEFAULT_PATH = {
        ("src1", "dst"): [("s1", "s2", 3), ("s2", "dst", 1)],
        ("src2", "dst"): [("s1", "s2", 3), ("s2", "dst", 1)]
    }

    DEFAULT_PATH_INFO = {
            ("src1", "dst"): {
                "gid": 1,
                "eth": None, "address": None,
                "ingress": "s1", "in_port": 1,
                "egress": "s2", "out_port": 1,
                "special_flows": {},
                "groups": {"s1": [3, 4, 5, 6], "s2": [1], "s3": [2], "s4": [2], "s5": [2], "s6": [2]},
                "stats": {"bytes": PTB(0.50)}
            }, ("src2", "dst"): {
                "gid": 2,
                "eth": None, "address": None,
                "ingress": "s1", "in_port": 2,
                "egress": "s2", "out_port": 1,
                "special_flows": {},
                "groups": {"s1": [3, 4, 5, 6], "s2": [1], "s3": [2], "s4": [2], "s5": [2], "s6": [2]},
                "stats": {"bytes": PTB(0.40)}
            }
    }

    def setUp(self):
        """ Define the default topology and initiate the controller """

        topo = {
            "src1": {-1: {"dest": "s1", "destPort": 1, "speed": 1000000000}},
            "src2": {-1: {"dest": "s1", "destPort": 2, "speed": 1000000000}},
            "dst": {-1: {"dest": "s2", "destPort": 1, "speed": 1000000000}},
            "s1": { 1: {"dest": "src1", "destPort": -1, "speed": 1000000000},
                    2: {"dest": "src2", "destPort": -1, "speed": 1000000000},
                    3: {"dest": "s2", "destPort": 2, "speed": 1000000000,
                        "poll_stats": {"tx_bytes": PTB(0.90)}},
                    4: {"dest": "s3", "destPort": 1, "speed": 1000000000,
                        "poll_stats": {"tx_bytes": PTB(0.20)}},
                    5: {"dest": "s4", "destPort": 1, "speed": 1000000000,
                        "poll_stats": {"tx_bytes": PTB(0.10)}},
                    6: {"dest": "s6", "destPort": 1, "speed": 1000000000,
                        "poll_stats": {"tx_bytes": PTB(0.15)}}},
            "s2": { 1: {"dest": "dst", "destPort": -1, "speed": 1000000000,
                        "poll_stats": {"tx_bytes": PTB(0.90)}},
                    2: {"dest": "s1", "destPort": 3, "speed": 1000000000},
                    3: {"dest": "s3", "destPort": 2, "speed": 1000000000},
                    4: {"dest": "s5", "destPort": 2, "speed": 1000000000},
                    5: {"dest": "s6", "destPort": 2, "speed": 1000000000}},
            "s3": { 1: {"dest": "s1", "destPort": 4, "speed": 1000000000},
                    2: {"dest": "s2", "destPort": 3, "speed": 1000000000,
                        "poll_stats": {"tx_bytes": PTB(0.20)}}},
            "s4": { 1: {"dest": "s1", "destPort": 5, "speed": 1000000000},
                    2: {"dest": "s5", "destPort": 1, "speed": 1000000000,
                        "poll_stats": {"tx_bytes": PTB(0.10)}}},
            "s5": { 1: {"dest": "s4", "destPort": 2, "speed": 1000000000},
                    2: {"dest": "s2", "destPort": 4, "speed": 1000000000,
                        "poll_stats": {"tx_bytes": PTB(0.10)}}},
            "s6": { 1: {"dest": "s1", "destPort": 6, "speed": 1000000000},
                    2: {"dest": "s2", "destPort": 5, "speed": 1000000000,
                        "poll_stats": {"tx_bytes": PTB(0.15)}}},
            "dst": {-1: {"dest": "s2", "destPort": 1, "speed": 1000000000}}}

        # Supress any logging by setting to a level above critical
        logging.basicConfig(level=1000)
        self.ctrl = DummyCtrl(topo, ["src1", "src2", "dst"], self.DEFAULT_PATH_INFO,
                                logging)

    def test_case_00(self):
        """ Default test case scenario that ensures check method works as expected """
        print("\nTesting default controller state")
        self._check_path()

    # -------------------- First solution --------------------

    def test_case_01(self):
        print("\nTesting FirstSol | candidate_sort_rev: false")
        self.TE = TEOptimisation(self.ctrl, 0.80, 0, opti_method = "FirstSol",
                            candidate_sort_rev=False, pot_path_sort_rev=False)
        self.TE.over_utilised = {("s1", 3): 0.90}
        self.TE._optimise_TE()

        self._check_path(
            expected_path = {
                ("src2", "dst"): [("s1", "s3", 4), ("s3", "s2", 2), ("s2", "dst", 1)]
            },
            expected_path_info = {
                ("src2", "dst"): {"groups": {"s1": [4, 5, 6, 3], "s2": [1], "s3": [2], "s4": [2],
                                                "s5": [2], "s6": [2]}}
            }
        )

    def test_case_02(self):
        print("\nTesting FirstSol | candidate_sort_rev: true")
        self.TE = TEOptimisation(self.ctrl, 0.80, 0, opti_method = "FirstSol",
                            candidate_sort_rev=True, pot_path_sort_rev=False)
        self.TE.over_utilised = {("s1", 3): 0.90}
        self.TE._optimise_TE()

        self._check_path(
            expected_path = {
                ("src1", "dst"): [("s1", "s3", 4), ("s3", "s2", 2), ("s2", "dst", 1)]
            },
            expected_path_info = {
                ("src1", "dst"): {"groups": {"s1": [4, 5, 6, 3], "s2": [1], "s3": [2], "s4": [2],
                                                "s5": [2], "s6": [2]}}
            }
        )

    # -------------------- Best solution usage --------------------

    def test_case_03(self):
        print("\nTesting BestSolUsage | candidate_sort_rev: false | pot_path_sort_rev: false")
        self.TE = TEOptimisation(self.ctrl, 0.80, 0, opti_method = "BestSolUsage",
                            candidate_sort_rev=False, pot_path_sort_rev=False)
        self.TE.over_utilised = {("s1", 3): 0.90}
        self.TE._optimise_TE()

        self._check_path(
            expected_path = {
                ("src2", "dst"): [("s1", "s4", 5), ("s4", "s5", 2), ("s5", "s2", 2), ("s2", "dst", 1)]
            },
            expected_path_info = {
                ("src2", "dst"): {"groups": {"s1": [5, 4, 6, 3], "s2": [1], "s3": [2], "s4": [2],
                                                "s5": [2], "s6": [2]}}
            }
        )

    def test_case_04(self):
        print("\nTesting BestSolUsage | candidate_sort_rev: false | pot_path_sort_rev: true")
        self.TE = TEOptimisation(self.ctrl, 0.80, 0, opti_method = "BestSolUsage",
                            candidate_sort_rev=False, pot_path_sort_rev=True)
        self.TE.over_utilised = {("s1", 3): 0.90}
        self.TE._optimise_TE()

        self._check_path(
            expected_path = {
                ("src2", "dst"): [("s1", "s3", 4), ("s3", "s2", 2), ("s2", "dst", 1)]
            },
            expected_path_info = {
                ("src2", "dst"): {"groups": {"s1": [4, 5, 6, 3], "s2": [1], "s3": [2], "s4": [2],
                                                "s5": [2], "s6": [2]}}
            }
        )


    def test_case_05(self):
        print("\nTesting BestSolUsage | candidate_sort_rev: true | pot_path_sort_rev: false")
        self.TE = TEOptimisation(self.ctrl, 0.80, 0, opti_method = "BestSolUsage",
                            candidate_sort_rev=True, pot_path_sort_rev=False)
        self.TE.over_utilised = {("s1", 3): 0.90}
        self.TE._optimise_TE()

        self._check_path(
            expected_path = {
                ("src1", "dst"): [("s1", "s4", 5), ("s4", "s5", 2), ("s5", "s2", 2), ("s2", "dst", 1)]
            },
            expected_path_info = {
                ("src1", "dst"): {"groups": {"s1": [5, 4, 6, 3], "s2": [1], "s3": [2], "s4": [2],
                                                "s5": [2], "s6": [2]}}
            }
        )

    def test_case_06(self):
        print("\nTesting BestSolUsage | candidate_sort_rev: true | pot_path_sort_rev: true")
        self.TE = TEOptimisation(self.ctrl, 0.80, 0, opti_method = "BestSolUsage",
                            candidate_sort_rev=True, pot_path_sort_rev=True)
        self.TE.over_utilised = {("s1", 3): 0.90}
        self.TE._optimise_TE()

        self._check_path(
            expected_path = {
                ("src1", "dst"): [("s1", "s3", 4), ("s3", "s2", 2), ("s2", "dst", 1)]
            },
            expected_path_info = {
                ("src1", "dst"): {"groups": {"s1": [4, 5, 6, 3], "s2": [1], "s3": [2], "s4": [2],
                                                "s5": [2], "s6": [2]}}
            }
        )

    # -------------------- Best solution path length --------------------

    def test_case_07(self):
        print("\nTesting BestSolPLen | candidate_sort_rev: false | pot_path_sort_rev: false")
        self.TE = TEOptimisation(self.ctrl, 0.80, 0, opti_method = "BestSolPLen",
                            candidate_sort_rev=False, pot_path_sort_rev=False)
        self.TE.over_utilised = {("s1", 3): 0.90}
        self.TE._optimise_TE()

        self._check_path(
            expected_path = {
                ("src2", "dst"): [("s1", "s6", 6), ("s6", "s2", 2), ("s2", "dst", 1)]
            },
            expected_path_info = {
                ("src2", "dst"): {"groups": {"s1": [6, 4, 5, 3], "s2": [1], "s3": [2], "s4": [2],
                                                "s5": [2], "s6": [2]}}
            }
        )

    def test_case_08(self):
        print("\nTesting BestSolPLen | candidate_sort_rev: false | pot_path_sort_rev: true")
        self.TE = TEOptimisation(self.ctrl, 0.80, 0, opti_method = "BestSolPLen",
                            candidate_sort_rev=False, pot_path_sort_rev=True)
        self.TE.over_utilised = {("s1", 3): 0.90}
        self.TE._optimise_TE()

        self._check_path(
            expected_path = {
                ("src2", "dst"): [("s1", "s3", 4), ("s3", "s2", 2), ("s2", "dst", 1)]
            },
            expected_path_info = {
                ("src2", "dst"): {"groups": {"s1": [4, 5, 6, 3], "s2": [1], "s3": [2], "s4": [2],
                                                "s5": [2], "s6": [2]}}
            }
        )


    def test_case_09(self):
        print("\nTesting BestSolPLen | candidate_sort_rev: true | pot_path_sort_rev: false")
        self.TE = TEOptimisation(self.ctrl, 0.80, 0, opti_method = "BestSolPLen",
                            candidate_sort_rev=True, pot_path_sort_rev=False)
        self.TE.over_utilised = {("s1", 3): 0.90}
        self.TE._optimise_TE()

        self._check_path(
            expected_path = {
                ("src1", "dst"): [("s1", "s6", 6), ("s6", "s2", 2), ("s2", "dst", 1)]
            },
            expected_path_info = {
                ("src1", "dst"): {"groups": {"s1": [6, 4, 5, 3], "s2": [1], "s3": [2], "s4": [2],
                                                "s5": [2], "s6": [2]}}
            }
        )

    def test_case_10(self):
        print("\nTesting BestSolPLen | candidate_sort_rev: true | pot_path_sort_rev: true")
        self.TE = TEOptimisation(self.ctrl, 0.80, 0, opti_method = "BestSolPLen",
                            candidate_sort_rev=True, pot_path_sort_rev=True)
        self.TE.over_utilised = {("s1", 3): 0.90}
        self.TE._optimise_TE()

        self._check_path(
            expected_path = {
                ("src1", "dst"): [("s1", "s3", 4), ("s3", "s2", 2), ("s2", "dst", 1)]
            },
            expected_path_info = {
                ("src1", "dst"): {"groups": {"s1": [4, 5, 6, 3], "s2": [1], "s3": [2], "s4": [2],
                                                "s5": [2], "s6": [2]}}
            }
        )

    # -------------------- CSPFRecomp solution --------------------

    def test_case_11(self):
        print("\nTesting CSPFRecomp | candidate_sort_rev: false")
        self.TE = TEOptimisation(self.ctrl, 0.80, 0, opti_method = "CSPFRecomp",
                            candidate_sort_rev=False, pot_path_sort_rev=False)
        self.TE.over_utilised = {("s1", 3): 0.90}
        self.TE._optimise_TE()

        self._check_path(
            expected_path = {
                ("src2", "dst"): [("s1", "s3", 4), ("s3", "s2", 2), ("s2", "dst", 1)]
            },
            expected_path_info = {
                #("src2", "dst"): {"groups": {"s1": [4, 6], "s2": [1], "s3": [2, 1], "s6": [2, 1]}}
                ("src2", "dst"): {"groups": {"s1": [4, 3], "s2": [1], "s3": [2]}}
            }
        )

    def test_case_12(self):
        print("\nTesting CSPFRecomp | candidate_sort_rev: true")
        self.TE = TEOptimisation(self.ctrl, 0.80, 0, opti_method = "CSPFRecomp",
                            candidate_sort_rev=True, pot_path_sort_rev=False)
        self.TE.over_utilised = {("s1", 3): 0.90}
        self.TE._optimise_TE()

        self._check_path(
            expected_path = {
                ("src1", "dst"): [("s1", "s3", 4), ("s3", "s2", 2), ("s2", "dst", 1)]
            },
            expected_path_info = {
                #("src1", "dst"): {"groups": {"s1": [4, 6], "s2": [1], "s3": [2, 1], "s6": [2, 1]}}
                ("src1", "dst"): {"groups": {"s1": [4, 3], "s2": [1], "s3": [2]}}
            }
        )


    # ---------- HELPER METHODS ----------


    def _check_path(self, expected_path={}, expected_path_info={}):
        """ Assert that the path information dictionary and paths generatd by the groups table
        are the same as `expected_path_info` and `expected_path`. Only the 'groups' field of
        the path info dictionary is checked and other fields are ignored. If `defaul_path_info`
        and `default_path` contain source-destination keys not found in `expected_path_info`
        and `expected_path` respecitvely, the method checks the value from these dictionaries.

        Args:
            expected_path (dict): Expected path which differs from `default_path`. Format:
                {(<src>, <dst>): [(<sw1>, <sw2>, <out_port>), ...]}
            expected_path_info (dict): Expected path info which differs from `default_path_info`.
                Format: {(<src>, <dst>): {"groups": {<sw>: [<pn>, ...]}}}
            default_path (dict): Default path. Format same as `expected_path`.
            default_path_info (dict): Default path info. Format same as `expected_path_info`.
        """
        # Compare the expected groups with the controller path information
        for hkey,expect_d in expected_path_info.iteritems():
            self.assertIn(hkey, self.ctrl.paths, msg="Hkey %s-%s not in controller path info!" % hkey)
            expect = expect_d["groups"]
            target = self.ctrl.paths[hkey]["groups"]
            self.assertEqual(target, expect, msg="Groups %s != %s for path %s-%s" % (target, expect,
                                                                                    hkey[0], hkey[1]))

        # Compare the default groups with the controller path information
        for hkey,expect_d in self.DEFAULT_PATH_INFO.iteritems():
            # Only check info of paths not in expected argument
            if hkey not in expected_path_info:
                self.assertIn(hkey, self.ctrl.paths, msg="Hkey %s-%s not in controller path info!" % hkey)
                expect = expect_d["groups"]
                target = self.ctrl.paths[hkey]["groups"]
                self.assertEqual(target, expect, msg="Groups %s != %s for path of %s-%s" % (target, expect,
                                                                                        hkey[0], hkey[1]))

        # Check the expected paths against the controller paths (group table)
        for hkey,expect in expected_path.iteritems():
            self.assertIn(hkey, self.ctrl.paths, msg="Hkey %s-%s not in controller path info!" % hkey)
            target_pinfo = self.ctrl.paths[hkey]
            target = group_table_to_path(target_pinfo, self.ctrl.get_topo(), target_pinfo["ingress"])
            self.assertEqual(target, expect, "Path %s != %s for path %s-%s" % (target, expect, hkey[0],
                                                                                hkey[1]))

        # Check the default paths against the controller paths (group table)
        for hkey,expect in self.DEFAULT_PATH.iteritems():
            # Only check paths which are not in the expected argument
            if hkey not in expected_path:
                self.assertIn(hkey, self.ctrl.paths, msg="Hkey %s-%s not in controller path info!" % hkey)
                target_pinfo = self.ctrl.paths[hkey]
                target = group_table_to_path(target_pinfo, self.ctrl.get_topo(), target_pinfo["ingress"])
                self.assertEqual(target, expect, "Path %s != %s for path %s-%s" % (target, expect, hkey[0],
                                                                                    hkey[1]))


# ----- Main method runner of unittest ----- #

if __name__ == "__main__":
    unittest.main()
