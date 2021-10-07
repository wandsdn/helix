#!/usr/bin/python
import logging
import unittest

from code_root_ctrl_MCTestScen_v3 import RootCtrlTest


class RootCtrlTestCSPF(RootCtrlTest):
    """ Multi-Controller Test Scenario V3 test that uses the CSPFRecomp
    TE-optimisation method with a candidate (path) revsort attribute of
    True (heavy hitters considered first)

    Test Scenarios:
        Docs/MCTestScenarios/scen-v3-CSPFRecomp-CandidateRevsort.png
    """
    revsort = True

    def __init__(self, *args, **kwargs):
        super(RootCtrlTestCSPF, self).__init__(*args, **kwargs)

    def test_case_01(self, show_print=True):
        """ Scenario 1: h1 -> h8 50M, h2 -> h8 60M

        Outcome:
            c1 Should swap h2-h8 to s2-s6 which changes the path to s7-s9
        """
        if show_print:
            print("\nTesting scenario 1 (h1->h8 50M | h2-h8 60M) CSPF")

        # Configure the initial state of the test by running through previous scenarios
        self.test_case_00(show_print=False)

        # Ingress and egress change modifications received from local controllers for local
        # TE optimisation
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

        # Perform egress change on C1
        self.ctrl._path_info_changed(c1_change)
        exp_inst["c1"][("h2", "h8")] = c1_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)

        # Perform the ingress and egress change at C2
        self.ctrl._path_info_changed(c2_change)
        exp_paths[("h2", "h8")] = {}
        exp_paths[("h2", "h8")]["prim"] = ["h2", "c1", "s02", "s06", "c2", "s07", "s08", "c3", "h8"]
        exp_paths[("h2", "h8")]["sec"] = ["h2", "c1", "s02", "s04", "c2", "s05", "s09", "c3", "h8"]
        exp_inst["c2"] = {}
        exp_inst["c2"][("h2", "h8")] = c2_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)

        # Perform the ingress change at C3
        self.ctrl._path_info_changed(c3_change)
        exp_paths[("h2", "h8")] = {}
        exp_paths[("h2", "h8")]["prim"] = ["h2", "c1", "s02", "s06", "c2", "s07", "s09", "c3", "h8"]
        exp_paths[("h2", "h8")]["sec"] = ["h2", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"]
        exp_inst["c3"] = {}
        exp_inst["c3"][("h2", "h8")] = c3_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)


    def test_case_02(self, show_print=True):
        """ Scenario 2: h1 -> h8 50M, h2 -> h8 110M

        Outcome:
            No change occurs so don't do anything ...
        """
        if show_print:
            print("\nTesting scenario 2 (h1->h8 50M | h2-h8 110M) CSPF")

        # Configure the initial state of the test by running through previous scenarios
        self.test_case_01(show_print=False)

    def test_case_03(self, show_print=True):
        """ Scenario 3: h1 -> h8 110M, h2 -> h8 220M

        Outcome:
            h1-h8 (local TE) will use s2,s6,s7,s9
            h1-h2 moved to c4 on c1 (root TE opti)
        """
        if show_print:
            print("\nTesting scenario 3 (h1->h8 120M | h2-h8 210M) CSPF")

        # Configure the initial state of the experiment
        self.test_case_02(show_print=False)

        # Expected paths and instructions from TE optimisation (includes state from previous scenario)
        exp_paths = {
            ("h1", "h8"): {
                "prim": ["h1", "c1", "s02", "s06", "c2", "s07", "s09", "c3", "h8"],
                "sec": ["h1", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"]},
            ("h2", "h8"): {
                "prim": ["h2", "c1", "s02", "s10", "c4", "s12", "s14", "c5", "s15", "s09", "c3", "h8"],
                "sec": ["h2", "c1", "s02", "s06", "c2", "s07", "s09", "c3", "h8"]}
        }

        exp_inst = {
            "c1": {
                ("h1", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}],
                ("h2", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 6), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."}]
            }, "c2": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s06", 4), "out": ("s07", 3)},
                    {"action": "add", "in": ("s04", 3), "out": ("s05", 4)}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s06", 4), "out": ("s07", 3)}]
            }, "c3": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s09", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"}],
            }, "c4": {
                ("h2", "h8"): [
                    {"action": "add", "in": ("s10", 3), "out": ("s12", 3)}]
            }, "c5": {
                ("h2", "h8"): [
                    {"action": "add", "in": ("s14", 3), "out": ("s15", 3)}]
            }
        }

        # Notify the root controller of the local ingress/egress changes for
        # h1-h8
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
        self.ctrl._path_info_changed(c1_change)
        self.ctrl._path_info_changed(c2_change)
        self.ctrl._path_info_changed(c3_change)

        # Initiate experiment
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c1", "sw": "s02", "port": 4, "traff_bps": 0})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c1", "sw": "s02", "port": 5, "traff_bps": 320000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 0})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s07", "port": 3, "traff_bps": 300000000})
        self.ctrl._action_inter_domain_link_congested(
            {"cid": "c2", "sw": "s07", "port": 3, "traff_bps": 330000000,
               "te_thresh": 0.90, "paths": [
                    (("h1", "h8"), 110000000),
                    (("h2", "h8"), 220000000)
                ]
            }
        )

        self._check_computed_paths(exp_paths, exp_inst)


if __name__ == "__main__":
    dummy = DummyRootCtrl()
    dummy.start()
    dummy.stop()
