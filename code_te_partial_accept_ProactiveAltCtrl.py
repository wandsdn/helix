#!/usr/bin/env python

# -----------------------------------------------------------------
#
# Same as ```code_te_partial_accept.py```, but assumes loose path splice are
# computed by the controller (ProactiveAlt instead of Priactive controller
# tested). More info, refer to Docs/TECodeUnitTest-CheckPartialSol.md.
#
# Run using the command:
#   python -m unittest code_te_partial_accept_ProactiveAltCtrl.py
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
from ProactiveControllerAlt import ProactiveControllerAlt

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

class DummyCtrl(ProactiveControllerAlt):
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
        ("src", "dst"): [("s1", "s2", 2), ("s2", "s5", 2), ("s5", "dst", 4)],
        ("dst", "src"): [("s5", "s2", 1), ("s2", "s1", 1), ("s1", "src", 1)]
    }

    DEFAULT_PATH_INFO = {
            ("src", "dst"): {
                "gid": 1,
                "eth": None, "address": None,
                "ingress": "s1", "in_port": 1,
                "egress": "s5", "out_port": 4,
                "special_flows": {},
                "groups": {"s1": [2, 3, 4], "s2": [2], "s3": [2], "s4": [2], "s5": [4]},
                "stats": {"bytes": 10000000}
            }, ("dst", "src"): {
                "gid": 2,
                "eth": None, "address": None,
                "ingress": "s5", "in_port": 4,
                "egress": "s1", "out_port": 1,
                "special_flows": {},
                "groups": {"s1": [1], "s2": [1], "s3": [1], "s4": [1], "s5": [1, 2, 3]},
                "stats": {"bytes": 0}
            }
    }

    DEFAULT_TOPO = {
        "src": {-1: {"dest": "s1", "destPort": 1, "speed": 1000000000}},
        "dst": {-1: {"dest": "s5", "destPort": 4, "speed": 1000000000}},
        "s1": { 1: {"dest": "src", "destPort": -1, "speed": 1000000000},
                2: {"dest": "s2", "destPort": 1, "speed": 80000000,
                    "poll_stats": {"tx_bytes": PTB(1.0)}},
                3: {"dest": "s3", "destPort": 1, "speed": 1000000000},
                4: {"dest": "s4", "destPort": 1, "speed": 1000000000}},
        "s2": { 1: {"dest": "s1", "destPort": 2, "speed": 1000000000},
                2: {"dest": "s5", "destPort": 1, "speed": 1000000000,
                    "poll_stats": {"tx_bytes": PTB(0.08)}}},
        "s3": { 1: {"dest": "s1", "destPort": 3, "speed": 1000000000},
                2: {"dest": "s5", "destPort": 2, "speed": 160000000}},
        "s4": { 1: {"dest": "s1", "destPort": 4, "speed": 1000000000},
                2: {"dest": "s5", "destPort": 3, "speed": 80000000}},
        "s5": { 1: {"dest": "s2", "destPort": 2, "speed": 1000000000},
                2: {"dest": "s3", "destPort": 2, "speed": 1000000000},
                3: {"dest": "s4", "destPort": 2, "speed": 1000000000},
                4: {"dest": "dst", "destPort": -1, "speed": 1000000000,
                    "poll_stats": {"tx_bytes": PTB(0.08)}}},
        "dst": {-1: {"dest": "s5", "destPort": 4, "speed": 1000000000}}}

    # XXX TODO: The expected groups for the CSPF algorithm are different as
    # we are faking paths. The controller path splice computation will never
    # use the S1-S4-S5 route, so when we recompute using CSPF we get different
    # groups. This is still okay as we are only intrested in the primary path
    # anyway.

    # Dictionary of expected results for TE optimisation tests.
    EXPECTED = {
        "NoChange": {
            "P": {("src", "dst"): [
                ("s1", "s2", 2), ("s2", "s5", 2), ("s5", "dst", 4)]
            },
            "GP": {("src", "dst"): {"groups": {
                "s1": [2, 3, 4], "s2": [2], "s3": [2], "s4": [2], "s5": [4]}}
            },
        },
        "Pa": {
            "P": {("src", "dst"): [
                ("s1", "s3", 3), ("s3", "s5", 2), ("s5", "dst", 4)]
            },
            "GP": {("src", "dst"): {"groups": {
                "s1": [3, 4, 2], "s2": [2], "s3": [2], "s4": [2], "s5": [4]}}
            },
        },
        "Pb": {
            "P": {("src", "dst"): [
                ("s1", "s4", 4), ("s4", "s5", 2), ("s5", "dst", 4)]
            },
            "GP": {("src", "dst"): {"groups": {
                "s1": [4, 3, 2], "s2": [2], "s3": [2], "s4": [2], "s5": [4]}}
            },
        },
    }


    def setUp(self):
        """ Initiate the controller and logginbg module """

        # Add default poll stats if not specified in the default top
        for src,src_i in self.DEFAULT_TOPO.iteritems():
            for _,dst_i in src_i.iteritems():
                if src in ["src", "dst"]:
                    continue

                if "poll_stats" not in dst_i:
                    dst_i["poll_stats"] = {"tx_bytes": 0}

        # Supress any logging by setting to a level above critical
        logging.basicConfig(level=40)
        self.ctrl = DummyCtrl(self.DEFAULT_TOPO, ["src", "dst"],
                                self.DEFAULT_PATH_INFO, logging)


    def reset_ctrl_groups(self, a=160000000, b=80000000):
        self.ctrl.paths = copy.deepcopy(self.DEFAULT_PATH_INFO)
        self.ctrl.graph = Graph(self.DEFAULT_TOPO)
        self.ctrl.graph.topo["s3"][2]["speed"] = a
        self.ctrl.graph.topo["s4"][2]["speed"] = b


    def test_case_00(self):
        """ Sanity check, ensure controller was correct initiated """
        print("\nTesting default controller state")
        self._check_path()


    def test_case_01(self):
        print("\nLink A = 160mbps, B = 80mbps")

        # Partial accept is false, all TE methods should use Pa
        for m in ["FirstSol", "BestSolUsage", "BestSolPLen"]:
            for csr in [False, True]:
                for psr in [False, True]:
                    for p in [False]:
                        # Make sure the topology is in the default state
                        self.reset_ctrl_groups(b=81000000)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["Pa"]["P"],
                            expected_path_info=self.EXPECTED["Pa"]["GP"]
                        )

        # FirstSol will always use Pa because partial accept does not
        # apply. Validate this is the case.
        for m in ["FirstSol"]:
            for csr in [False, True]:
                for psr in [False, True]:
                    for p in [True]:
                        # Make sure the topology is in the default state
                        self.reset_ctrl_groups(b=81000000)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["Pa"]["P"],
                            expected_path_info=self.EXPECTED["Pa"]["GP"]
                        )

        # If partial accept true, other methods will use Pa only if
        # candidate revsort is set to false.
        for m in ["BestSolUsage", "BestSolPLen"]:
            for csr in [False, True]:
                for psr in [False]:
                    for p in [True]:
                        # Make sure the topology is in the default state
                        self.reset_ctrl_groups(b=81000000)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["Pa"]["P"],
                            expected_path_info=self.EXPECTED["Pa"]["GP"]
                        )

        # Otherwise, BestSolUsage and BestSolPLen will use Pb
        for m in ["BestSolUsage", "BestSolPLen"]:
            for csr in [False, True]:
                for psr in [True]:
                    for p in [True]:
                        # Make sure the topology is in the default state
                        self.reset_ctrl_groups(b=81000000)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["Pb"]["P"],
                            expected_path_info=self.EXPECTED["Pb"]["GP"]
                        )

        # CSPF will have different groups from expected as we faked the
        # test group table to run the scenario. Recomputing paths will
        # return them to default. See note above ``:cls:EXPECTED``.
        expected_gp_CSPF = {("src", "dst"): {"groups": {"s1": [3, 2, 4],
                                        "s2": [2], "s3": [2], "s5": [4]}}}

        # XXX: CSPF has no candidate rev-sort. When partial accept is true
        # we have two potential routes, via S3 and S4. Dijkstra's algorithm
        # will select the first (lowest node), so CSPF will always use Pa.
        for m in ["CSPFRecomp"]:
            for csr in [False, True]:
                for psr in [False, True]:
                    for p in [False, True]:
                        self.reset_ctrl_groups(b=81000000)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["Pa"]["P"],
                            expected_path_info=expected_gp_CSPF
                        )

    def test_case_02(self):
        print("\nLink A = 160mbps, B = 79mbps | no partial, all use Pa")

        # No partial accept, all methods will use Pa
        for m in ["FirstSol", "BestSolUsage", "BestSolPLen"]:
            for csr in [False, True]:
                for psr in [False, True]:
                    for p in [False, True]:
                        # Make sure the topology is in the default state
                        self.reset_ctrl_groups(a=160000000, b=79999999)
                        self._run_te_opti(m, csr, psr, p)
                        self._check_path(
                            expected_path=self.EXPECTED["Pa"]["P"],
                            expected_path_info=self.EXPECTED["Pa"]["GP"]
                        )

        expected_gp_CSPF = {("src", "dst"): {"groups": {"s1": [3, 2, 4],
                                        "s2": [2], "s3": [2], "s5": [4]}}}

        for m in ["CSPFRecomp"]:
            for csr in [False, True]:
                for psr in [False, True]:
                    for p in [False, True]:
                        self.reset_ctrl_groups(a=160000000, b=79999999)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["Pa"]["P"],
                            expected_path_info=expected_gp_CSPF
                        )

    def test_case_03(self):
        print("\nLink A = 100mbps, B = 140mbps | paccept sucesfull")

        # All TE methods will fail if partial accept is false
        for m in ["FirstSol", "BestSolUsage", "BestSolPLen", "CSPFRecomp"]:
            for csr in [False, True]:
                for psr in [False, True]:
                    for p in [False]:
                        self.reset_ctrl_groups(a=100000000, b=140000000)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["NoChange"]["P"],
                            expected_path_info=self.EXPECTED["NoChange"]["GP"]
                        )

        # FirstSol has no partial accept so fails even if flag is true
        for m in ["FirstSol"]:
            for csr in [False, True]:
                for psr in [False, True]:
                    for p in [True]:
                        self.reset_ctrl_groups(a=100000000, b=140000000)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["NoChange"]["P"],
                            expected_path_info=self.EXPECTED["NoChange"]["GP"]
                        )


        # If partial accept true, other methods will use Pa only if
        # candidate revsort is set to false.
        for m in ["BestSolUsage", "BestSolPLen"]:
            for csr in [False, True]:
                for psr in [False]:
                    for p in [True]:
                        self.reset_ctrl_groups(a=100000000, b=140000000)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["Pb"]["P"],
                            expected_path_info=self.EXPECTED["Pb"]["GP"]
                        )

        # Otherwise, BestSolUsage and BestSolPLen will use Pb
        for m in ["BestSolUsage", "BestSolPLen"]:
            for csr in [False, True]:
                for psr in [True]:
                    for p in [True]:
                        self.reset_ctrl_groups(a=100000000, b=140000000)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["Pa"]["P"],
                            expected_path_info=self.EXPECTED["Pa"]["GP"]
                        )

        # CSPF will have different groups from expected as we faked the
        # test group table to run the scenario. Recomputing paths will
        # return them to default. See note above ``:cls:EXPECTED``.
        expected_gp_CSPF = {("src", "dst"): {"groups": {"s1": [3, 2, 4],
                                        "s2": [2], "s3": [2], "s5": [4]}}}

        # XXX: CSPF has no candidate rev-sort. When partial accept is true
        # we have two potential routes, via S3 and S4. Dijkstra's algorithm
        # will select the first (lowest node), so CSPF will always use Pa.
        for m in ["CSPFRecomp"]:
            for csr in [False, True]:
                for psr in [False, True]:
                    for p in [True]:
                        self.reset_ctrl_groups(a=100000000, b=140000000)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["Pa"]["P"],
                            expected_path_info=expected_gp_CSPF
                        )

    def test_case_04(self):
        print("\nLink A = 79,999,999bps, B = 79,999,999bps | All fail")

        for m in ["FirstSol", "BestSolUsage", "BestSolPLen", "CSPFRecomp"]:
            for csr in [False, True]:
                for psr in [False, True]:
                    for p in [False, True]:
                        self.reset_ctrl_groups(a=79999999, b=79999999)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["NoChange"]["P"],
                            expected_path_info=self.EXPECTED["NoChange"]["GP"]
                        )

    def test_case_05(self):
        print("\nLink A = 80mbps, B = 80mbps | All fail (paccept invalid solution)")

        # All merthods regardless of partial accept fail because partial accept
        # solution is invalid (did not improve overall congestion)
        for m in ["FirstSol", "BestSolUsage", "BestSolPLen", "CSPFRecomp"]:
            for csr in [False, True]:
                for psr in [False, True]:
                    for p in [False, True]:
                        # Make sure the topology is in the default state
                        self.reset_ctrl_groups(a=80000000, b=80000000)
                        self._run_te_opti(m, csr, psr, p)

                        self._check_path(
                            expected_path=self.EXPECTED["NoChange"]["P"],
                            expected_path_info=self.EXPECTED["NoChange"]["GP"]
                        )


    # ---------- HELPER METHODS ----------


    def _run_te_opti(self, m, csr, psr, p):
        """ Helper method that intitiates a new TE module instance based on
        provided attributes, sets the congested link and runs the TE
        optimisation routine ``_optimise_TE()``. method also outputs debug
        info to the screen which outlines the arguments used to configure
        the TE module for this test.
        """
        print(" * Testing %-12s | candidate_sort_rev: %-5s |"
                " pot_path_sort_rev: %-5s |"
                " partial_accept: %-5s" %
                (m, csr, psr, p))
        self.TE = TEOptimisation(self.ctrl, 0.50, 0,
                opti_method=m,
                partial_accept=p,
                candidate_sort_rev=csr,
                pot_path_sort_rev=psr)

        self.TE.over_utilised = {("s1", 2): 1.0}
        self.TE._optimise_TE()


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
