#!/usr/bin/python
import logging
import unittest

from code_root_ctrl_test_base import BaseRootCtrlTest


class RootCtrlTest(BaseRootCtrlTest):
    """ Multi-Controller Test Scenario V4 test

    Test Scenarios:
        Docs/MCTestScenarios/scen-v4.png
    """
    def __init__(self, *args, **kwargs):
        super(RootCtrlTest, self).__init__(*args, **kwargs)
        self._set_link_capacity(("c1", "s02", 4), ("c2", "s04", 3), 100000000)
        self._set_link_capacity(("c1", "s02", 5), ("c2", "s06", 4), 500000000)
        self._set_link_capacity(("c1", "s02", 6), ("c4", "s10", 3), 500000000)
        self._set_link_capacity(("c1", "s02", 7), ("c5", "s13", 3), 300000000)
        self._set_link_capacity(("c2", "s05", 4), ("c3", "s08", 3), 300000000)
        self._set_link_capacity(("c2", "s07", 3), ("c3", "s09", 2), 200000000)

    def test_case_00(self, show_print=True):
        """ Compute and validate inter-domain paths """
        if show_print:
            print("\nTesting inter-domain path computation")
        self.ctrl._compute_inter_domain_paths()
        self._check_computed_paths()

    def test_case_01(self, show_print=True):
        """ Scenario 1: h1 -> h8 50M, h2 -> h8 60M

        Outcome:
            c1 Should swap h1-h8 to s2-s6 which causes the path s7-s9
        """
        if show_print:
            print("\nTesting scenario 1 (h1->h8 110M | h2-h8 120M)")

        # Configure the initial state of the test by running through previous scenarios
        self.test_case_00(show_print=False)

        # Ingress and egress change modifications received from local controllers for local
        # TE optimisation
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

        # Initial expected path instructions for state at start of scenario (default state)
        exp_paths = {}
        exp_inst = {"c1": {}}

        # Perform egress change on C1
        self.ctrl._path_info_changed(c1_change)
        exp_inst["c1"][("h1", "h8")] = c1_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)

        # Perform the ingress and egress change at C2
        self.ctrl._path_info_changed(c2_change)
        exp_paths[("h1", "h8")] = {}
        exp_paths[("h1", "h8")]["prim"] = ["h1", "c1", "s02", "s06", "c2", "s07", "s08", "c3", "h8"]
        exp_paths[("h1", "h8")]["sec"] = ["h1", "c1", "s02", "s04", "c2", "s05", "s09", "c3", "h8"]
        exp_inst["c2"] = {}
        exp_inst["c2"][("h1", "h8")] = c2_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)

        # Perform the ingress change at C3
        self.ctrl._path_info_changed(c3_change)
        exp_paths[("h1", "h8")] = {}
        exp_paths[("h1", "h8")]["prim"] = ["h1", "c1", "s02", "s06", "c2", "s07", "s09", "c3", "h8"]
        exp_paths[("h1", "h8")]["sec"] = ["h1", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"]
        exp_inst["c3"] = {}
        exp_inst["c3"][("h1", "h8")] = c3_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)


    def test_case_02(self, show_print=True):
        """ Scenario 2: h1 -> h8 200M, h2 -> h8 60M

        Outcome:
            c2 should swap h1-h8 to s5-s8
        """
        if show_print:
            print("\nTesting scenario 2 (h1->h8 200M | h2-h8 60M)")

        # Configure the initial state of the test by running through previous scenarios
        self.test_case_01(show_print=False)

        # Local controller ingress and egress notifications sent to root controller
        c2_change = {"cid": "c2", "hkey": ("h1", "h8"), "new_paths": [
                {"action": "add", "in": ("s06", 4), "out": ("s05", 4)},
                {"action": "add", "in": ("s04", 3), "out": ("s07", 3)}]
        }
        c3_change = {"cid": "c3", "hkey": ("h1", "h8"), "new_paths": [
                {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"},
                {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"}]
        }

        # Expected path and instructions
        exp_paths = {
            ("h1", "h8"): {
                "prim": ["h1", "c1", "s02", "s06", "c2", "s05", "s09", "c3", "h8"],
                "sec": ["h1", "c1", "s02", "s04", "c2", "s07", "s08", "c3", "h8"]}
        }

        exp_inst = {
            "c1": {
                ("h1", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}],
            }, "c2": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s06", 4), "out": ("s05", 4)},
                    {"action": "add", "in": ("s04", 3), "out": ("s07", 3)}],
            }, "c3": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}],
            }
        }


        # Perform the ingress and egress change at C2
        self.ctrl._path_info_changed(c2_change)
        self._check_computed_paths(exp_paths, exp_inst)

        # Perform the ingress change at C3
        self.ctrl._path_info_changed(c3_change)
        exp_paths[("h1", "h8")]["prim"] = ["h1", "c1", "s02", "s06", "c2", "s05", "s08", "c3", "h8"]
        exp_paths[("h1", "h8")]["sec"] = ["h1", "c1", "s02", "s04", "c2", "s07", "s09", "c3", "h8"]
        exp_inst["c3"][("h1", "h8")] = c3_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)

    def test_case_03(self, show_print=True):
        """ Scenario 3: h1 -> h8 210M, h2 -> h8 200M

        Outcome:
            h2-h8 moved to c5 at c1
        """
        if show_print:
            print("\nTesting scenario 3 (h1->h8 210M | h2-h8 200M)")

        # Configure the initial state of the experiment
        self.test_case_02(show_print=False)

        # Expected paths and instructions from TE optimisation (includes state from previous scenario)
        exp_paths = {
            ("h1", "h8"): {
                "prim": ["h1", "c1", "s02", "s06", "c2", "s05", "s08", "c3", "h8"],
                "sec": ["h1", "c1", "s02", "s04", "c2", "s07", "s09", "c3", "h8"]},
            ("h2", "h8"): {
                "prim": ["h2", "c1", "s02", "s13", "c5", "s15", "s09", "c3", "h8"],
                "sec": ["h2", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"]}
        }

        exp_inst = {
            "c1": {
                ("h1", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}],
                ("h2", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 7), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}]
            }, "c2": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s06", 4), "out": ("s05", 4)},
                    {"action": "add", "in": ("s04", 3), "out": ("s07", 3)}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s04", 3), "out": ("s05", 4)}]
            }, "c3": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s09", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}],
            }, "c5": {
                ("h2", "h8"): [
                    {"action": "add", "in": ("s13", 3), "out": ("s15", 3)}]
            }
        }


        # XXX: Because S2-S4 is constrained to 100M, C2 will only see 100M of
        # the 200M H2-H8 host traffic. If the con message uses this correct
        # value, TE opti will fail as 100M can move to S7-S9. Normally, C1
        # will resolve the congestion on S2-S4, and C2 will resolve the
        # congestion on S5-S8, by swapping traffic to S7-S9. Then, C2 will
        # detect congestion on S7-S9 and request a root optimisisation.
        # This scenario is skips the first step and jumps straight to a
        # root test.

        # Initiate experiment
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c1", "sw": "s02", "port": 4, "traff_bps": 100000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c1", "sw": "s02", "port": 5, "traff_bps": 210000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 300000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s07", "port": 3, "traff_bps": 0})
        self.ctrl._action_inter_domain_link_congested(
            {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 310000000,
               "te_thresh": 0.90, "paths": [
                    (("h1", "h8"), 210000000),
                    (("h2", "h8"), 200000000)
                ]
            }
        )

        self._check_computed_paths(exp_paths, exp_inst)

    def test_case_04(self, show_print=True):
        """ Scenario 4: h1 -> h8 400M, h2 -> h8 200M

        Outcome:
            h1-h8 moved to c4 at c1
        """
        if show_print:
            print("\nTesting scenario 4 (h1->h8 400M | h2-h8 200M)")

        # Configure the initial state of the experiment
        self.test_case_03(show_print=False)

        # Expected paths and instructions from TE optimisation (includes state from previous scenario)
        exp_paths = {
            ("h1", "h8"): {
                "prim": ["h1", "c1", "s02", "s10", "c4", "s12", "s14", "c5", "s15", "s09", "c3", "h8"],
                "sec": ["h1", "c1", "s02", "s06", "c2", "s05", "s08", "c3", "h8"]},
            ("h2", "h8"): {
                "prim": ["h2", "c1", "s02", "s13", "c5", "s15", "s09", "c3", "h8"],
                "sec": ["h2", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"]}
        }

        exp_inst = {
            "c1": {
                ("h1", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 6), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."}],
                ("h2", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 7), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}]
            }, "c2": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s06", 4), "out": ("s05", 4)}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s04", 3), "out": ("s05", 4)}]
            }, "c3": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s09", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s09", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}],
            }, "c4": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s10", 3), "out": ("s12", 3)}]
            }, "c5": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s14", 3), "out": ("s15", 3)}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s13", 3), "out": ("s15", 3)}]
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
            {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 400000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s07", "port": 3, "traff_bps": 0})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c5", "sw": "s15", "port": 3, "traff_bps": 200000000})
        self.ctrl._action_inter_domain_link_congested(
            {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 400000000,
               "te_thresh": 0.90, "paths": [(("h1", "h8"), 400000000)]}
        )

        self._check_computed_paths(exp_paths, exp_inst)
