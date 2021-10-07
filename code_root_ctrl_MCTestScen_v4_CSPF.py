#!/usr/bin/python
import logging
import unittest

from code_root_ctrl_MCTestScen_v4 import RootCtrlTest


class RootCtrlTestCSPF(RootCtrlTest):
    """ Multi-Controller Test Scenario V4 test that uses the CSPFRecomp
    TE-optimisation method with a candidate (path) revsort attribute of
    True (heavy hitters considered first)

    Test Scenarios:
        Docs/MCTestScenarios/scen-v4-CSPFRecomp-CandidateRevosrt.png
    """
    revsort = True

    def __init__(self, *args, **kwargs):
        super(RootCtrlTestCSPF, self).__init__(*args, **kwargs)

    def test_case_01(self, show_print=True):
        """ Scenario 1: h1 -> h8 50M, h2 -> h8 60M

        Outcome:
            c1 should swap h2-h8 to s2-s6 which causes the path to
                change egress in C2 and use s7-s9.
        """
        if show_print:
            print("\nTesting scenario 1 (h1->h8 110M | h2-h8 120M) CSPF")

        # Configure the initial state of the test by running through previous scenarios
        self.test_case_00(show_print=False)

        # Scenario ingress and egress changes which the local controllers
        # send to the root controller.
        c1_change = {"cid": "c1", "hkey": ("h2", "h8"), "new_paths": [
                {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."},
                {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}]
        }
        c2_change = {"cid": "c2", "hkey": ("h2", "h8"), "new_paths": [
                {"action": "add", "in": ("s06", 4), "out": ("s07", 3)},
                {"action": "add", "in": ("s04", 3), "out": ("s05", 4)}]
        }
        c3_change = {"cid": "c3", "hkey": ("h2", "h8"), "new_paths": [
                {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"},
                {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}]
        }

        # Initial expected path instructions for state at start of scenario (default state)
        exp_paths = {}
        exp_inst = {"c1": {}}

        # Inform root of egress change on C1
        self.ctrl._path_info_changed(c1_change)
        exp_inst["c1"][("h2", "h8")] = c1_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)

        # Inform the root of ingress and egress change at C2
        self.ctrl._path_info_changed(c2_change)
        exp_paths[("h2", "h8")] = {}
        exp_paths[("h2", "h8")]["prim"] = ["h2", "c1", "s02", "s06", "c2", "s07", "s08", "c3", "h8"]
        exp_paths[("h2", "h8")]["sec"] = ["h2", "c1", "s02", "s04", "c2", "s05", "s09", "c3", "h8"]
        exp_inst["c2"] = {}
        exp_inst["c2"][("h2", "h8")] = c2_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)

        # Inform the root of ingress change at C3
        self.ctrl._path_info_changed(c3_change)
        exp_paths[("h2", "h8")] = {}
        exp_paths[("h2", "h8")]["prim"] = ["h2", "c1", "s02", "s06", "c2", "s07", "s09", "c3", "h8"]
        exp_paths[("h2", "h8")]["sec"] = ["h2", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"]
        exp_inst["c3"] = {}
        exp_inst["c3"][("h2", "h8")] = c3_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)


    def test_case_02(self, show_print=True):
        """ Scenario 2: h1 -> h8 200M, h2 -> h8 60M

        Outcome:
            c2 should swap h2-h8 to s5-s8
        """
        if show_print:
            print("\nTesting scenario 2 (h1->h8 60M | h2-h8 200M) CSPF")

        # Configure the initial state of the test by running through previous scenarios
        self.test_case_01(show_print=False)

        # Local controller ingress and egress notifications sent to root controller
        c2_change = {"cid": "c2", "hkey": ("h2", "h8"), "new_paths": [
                {"action": "add", "in": ("s06", 4), "out": ("s05", 4)},
                {"action": "add", "in": ("s04", 3), "out": ("s07", 3)}]
        }
        c3_change = {"cid": "c3", "hkey": ("h2", "h8"), "new_paths": [
                {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"},
                {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"}]
        }

        # Expected path and instructions
        exp_paths = {
            ("h2", "h8"): {
                "prim": ["h2", "c1", "s02", "s06", "c2", "s05", "s09", "c3", "h8"],
                "sec": ["h2", "c1", "s02", "s04", "c2", "s07", "s08", "c3", "h8"]}
        }

        exp_inst = {
            "c1": {
                ("h2", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}],
            }, "c2": {
                ("h2", "h8"): [
                    {"action": "add", "in": ("s06", 4), "out": ("s05", 4)},
                    {"action": "add", "in": ("s04", 3), "out": ("s07", 3)}],
            }, "c3": {
                ("h2", "h8"): [
                    {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}],
            }
        }


        # Notify the root controller of the egress change at c2
        self.ctrl._path_info_changed(c2_change)
        self._check_computed_paths(exp_paths, exp_inst)

        # Notify the root controller of the ingress change at c3
        self.ctrl._path_info_changed(c3_change)
        exp_paths[("h2", "h8")]["prim"] = ["h2", "c1", "s02", "s06", "c2", "s05", "s08", "c3", "h8"]
        exp_paths[("h2", "h8")]["sec"] = ["h2", "c1", "s02", "s04", "c2", "s07", "s09", "c3", "h8"]
        exp_inst["c3"][("h2", "h8")] = c3_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)

    def test_case_03(self, show_print=True):
        """ Scenario 3: h1 -> h8 210M, h2 -> h8 200M

        Outcome:
            c1 will move h1-h8 to s2-s6 which causes a egress change in c2
                to s7-s9.
            c2 will detect s7-s9 as congested and fail to resolve
            root will modify h1-h8 to use s2-s13 on c1
        """
        if show_print:
            print("\nTesting scenario 3 (h1->h8 210M | h2-h8 200M) CSPF")

        # Configure the initial state of the experiment
        self.test_case_02(show_print=False)

        # Scenario ingress and egress changes which the local controllers
        # send to the root controller.
        c1_change = {"cid": "c1", "hkey": ("h1", "h8"), "new_paths": [
                {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."},
                {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}]
        }
        c2_change = {"cid": "c2", "hkey": ("h1", "h8"), "new_paths": [
                {"action": "add", "in": ("s06", 4), "out": ("s07", 3)},
                {"action": "add", "in": ("s04", 3), "out": ("s05", 4)}]
        }
        c3_change = {"cid": "c3", "hkey": ("h1", "h8"), "new_paths": [
                {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"},
                {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}]
        }

        # Expected path and instruction for scenario (con 0 - swap 0) pre c2,c3 change
        exp_paths = {
            ("h2", "h8"): {
                "prim": ["h2", "c1", "s02", "s06", "c2", "s05", "s08", "c3", "h8"],
                "sec": ["h2", "c1", "s02", "s04", "c2", "s07", "s09", "c3", "h8"]},
            ("h1", "h8"): {
                "prim": ["h1", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"],
                "sec": ["h1", "c1", "s02", "s06", "c2", "s07", "s09", "c3", "h8"]}
        }

        exp_inst = {
            "c1": {
                ("h2", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}],
                ("h1", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}],
            }, "c2": {
                ("h2", "h8"): [
                    {"action": "add", "in": ("s06", 4), "out": ("s05", 4)},
                    {"action": "add", "in": ("s04", 3), "out": ("s07", 3)}],
                ("h1", "h8"): [
                    {"action": "add", "in": ("s04", 3), "out": ("s05", 4)},
                    {"action": "add", "in": ("s06", 4), "out": ("s07", 3)}],
            }, "c3": {
                ("h2", "h8"): [
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"}],
                ("h1", "h8"): [
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"}],
            }
        }

        # Inform the root controller of the egress change on C1
        # C1 optimisation [(0) CON]
        self.ctrl._path_info_changed(c1_change)
        self._check_computed_paths(exp_paths, exp_inst)


        # Inform the root controller of the ingress and egress change for
        # h1-h8 in c2
        self.ctrl._path_info_changed(c2_change)
        exp_paths[("h1", "h8")]["prim"] = ["h1", "c1", "s02", "s06", "c2", "s07", "s08", "c3", "h8"]
        exp_paths[("h1", "h8")]["sec"] = ["h1", "c1", "s02", "s04", "c2", "s05", "s09", "c3", "h8"]
        exp_inst["c2"][("h1", "h8")] = c2_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)

        # Inform the root controller of the ingress change for h1-h8 in c3
        self.ctrl._path_info_changed(c3_change)
        exp_paths[("h1", "h8")]["prim"] = ["h1", "c1", "s02", "s06", "c2", "s07", "s09", "c3", "h8"]
        exp_paths[("h1", "h8")]["sec"] = ["h1", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"]
        exp_inst["c3"][("h1", "h8")] = c3_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)


        # XXX: In the above, c2 may actually swap h1-h8 to s7-s9 while c1
        # resolves congestion (i.e. 210+100 = 300M of traffic) over cap of
        # s5-s8 so c2 locally resolves congestion. The end result in terms of
        # ingress / egress changes is the same (order of ingress/egress may
        # varry). For now ignore the congestion fix and perform that as a
        # ingress change detection!

        # Initiate the root controller optimisation [(1) CON]
        exp_paths[("h1", "h8")]["prim"] = ["h1", "c1", "s02", "s13", "c5", "s15", "s09", "c3", "h8"]
        exp_paths[("h1", "h8")]["sec"] = ["h1", "c1", "s02", "s06", "c2", "s07", "s09", "c3", "h8"]
        exp_inst["c1"][("h1", "h8")] = [
            {"action": "add", "in": -1, "out": ("s02", 7), "out_addr": "0."},
            {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."}
        ]
        exp_inst["c2"][("h1", "h8")] = [
            {"action": "add", "in": ("s06", 4), "out": ("s07", 3)}
        ]
        exp_inst["c5"] = {("h1", "h8"): [
            {"action": "add", "in": ("s13", 3), "out": ("s15", 3)},
        ]}
        exp_inst["c3"][("h1", "h8")] = [
            {"action": "add", "in": ("s09", 3), "out": -1, "out_eth": "a::"},
            {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"}
        ]

        # Prime the root controller with traffic and send a congested message
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c1", "sw": "s02", "port": 4, "traff_bps": 0})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c1", "sw": "s02", "port": 5, "traff_bps": 410000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 300000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s07", "port": 3, "traff_bps": 200000000})
        self.ctrl._action_inter_domain_link_congested(
            {"cid": "c2", "sw": "s07", "port": 3, "traff_bps": 210000000,
               "te_thresh": 0.90, "paths": [
                    (("h1", "h8"), 210000000),
                ]
            }
        )

        self._check_computed_paths(exp_paths, exp_inst)

    def test_case_04(self, show_print=True):
        """ Scenario 4: h1 -> h8 200M, h2 -> h8 400M

        Outcome:
            root moves h2-h8 to c4 at c1
        """
        if show_print:
            print("\nTesting scenario 4 (h1->h8 200M | h2-h8 400M) CSPF")

        # Configure the initial state of the experiment
        self.test_case_03(show_print=False)

        # Expected paths and instructions from TE optimisation (includes state from previous scenario)
        exp_paths = {
            ("h1", "h8"): {
                "prim": ["h1", "c1", "s02", "s13", "c5", "s15", "s09", "c3", "h8"],
                "sec": ["h1", "c1", "s02", "s06", "c2", "s07", "s09", "c3", "h8"]},
            ("h2", "h8"): {
                "prim": ["h2", "c1", "s02", "s10", "c4", "s12", "s14", "c5", "s15", "s09", "c3", "h8"],
                "sec": ["h2", "c1", "s02", "s06", "c2", "s05", "s08", "c3", "h8"]}
        }

        exp_inst = {
            "c1": {
                ("h1", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 7), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."}],
                ("h2", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 6), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."}]
            }, "c2": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s06", 4), "out": ("s07", 3)}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s06", 4), "out": ("s05", 4)}]
            }, "c3": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s09", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s09", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}],
            }, "c4": {
                ("h2", "h8"): [
                    {"action": "add", "in": ("s10", 3), "out": ("s12", 3)}]
            }, "c5": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s13", 3), "out": ("s15", 3)}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s14", 3), "out": ("s15", 3)}]
            }
        }

        # Initiate experiment
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c1", "sw": "s02", "port": 4, "traff_bps": 0})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c1", "sw": "s02", "port": 5, "traff_bps": 400000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c1", "sw": "s02", "port": 7, "traff_bps": 200000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 300000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s07", "port": 3, "traff_bps": 0})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c5", "sw": "s15", "port": 3, "traff_bps": 200000000})
        self.ctrl._action_inter_domain_link_congested(
            {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 400000000,
               "te_thresh": 0.90, "paths": [(("h2", "h8"), 400000000)]}
        )

        self._check_computed_paths(exp_paths, exp_inst)
