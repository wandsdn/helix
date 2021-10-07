#!/usr/bin/python
import logging
import unittest

from code_root_ctrl_test_base import BaseRootCtrlTest, p_to_bit


class RootCtrlTest(BaseRootCtrlTest):
    """ Multi-Controller Test Scenario V2 test

    Test Scenarios:
        Docs/MCTestScenarios/scen-v2.png
    """
    def __init__(self, *args, **kwargs):
        super(RootCtrlTest, self).__init__(*args, **kwargs)
        self._set_link_capacity(("c2", "s05", 4), ("c3", "s08", 3), 200000000)
        self._set_link_capacity(("c2", "s07", 3), ("c3", "s09", 2), 200000000)

    def test_case_00(self, show_print=True):
        """ Compute and validate inter-domain paths """
        if show_print:
            print("\nTesting inter-domain path computation")
        self.ctrl._compute_inter_domain_paths()
        self._check_computed_paths()

    def test_case_01(self, show_print=True):
        """ Scenario 1: h1 -> h8 110M, h2 -> h8 120M

        Outcome:
            C2 should swap h1-h8 to s7-s9
        """
        if show_print:
            print("\nTesting scenario 1 (h1->h8 110M | h2-h8 120M)")

        # Configure the initial state of the experiment
        self.test_case_00(show_print=False)

        c2_egg_change = {"cid": "c2", "hkey": ("h1", "h8"), "new_paths": [
                {"action": "add", "in": ("s04", 3), "out": ("s07", 3)},
                {"action": "add", "in": ("s06", 4), "out": ("s05", 4)}]
        }
        c3_ing_change = {"cid": "c3", "hkey": ("h1", "h8"), "new_paths": [
                {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"},
                {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}]
        }

        exp_paths = {("h1", "h8"): {}}
        exp_inst = {"c2": {}}

        # Perform egress change C2 and check results are correct
        self.ctrl._path_info_changed(c2_egg_change)
        exp_paths[("h1", "h8")]["prim"] = ["h1", "c1", "s02", "s04", "c2", "s07", "s08", "c3", "h8"]
        exp_paths[("h1", "h8")]["sec"] = ["h1", "c1", "s02", "s06", "c2", "s05", "s09", "c3", "h8"]
        exp_inst["c2"][("h1", "h8")] = c2_egg_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)

        # Perform the ingress change at c3 and check results
        self.ctrl._path_info_changed(c3_ing_change)
        exp_paths[("h1", "h8")]["prim"] = ["h1", "c1", "s02", "s04", "c2", "s07", "s09", "c3", "h8"]
        exp_paths[("h1", "h8")]["sec"] = ["h1", "c1", "s02", "s06", "c2", "s05", "s08", "c3", "h8"]
        exp_inst["c3"] = {}
        exp_inst["c3"][("h1", "h8")] = c3_ing_change["new_paths"]
        self._check_computed_paths(exp_paths, exp_inst)

    def test_case_02(self, show_print=True):
        """ Scenario 2: h1 -> h8 110M, h2 -> h8 400M

        Outcome:
            h2-h8 moved to c4 at c1
        """
        if show_print:
            print("\nTesting scenario 2 (h1->h8 110M | h2-h8 400M)")

        # Configure the initial state of the experiment
        self.test_case_01(show_print=False)

        # Prime the topology with TE information (including congestion)
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c1", "sw": "s02", "port": 4, "traff_bps": 510000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 200000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s07", "port": 3, "traff_bps": 110000000})
        self.ctrl._action_inter_domain_link_congested(
            {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 400000000,
               "te_thresh": 0.90, "paths": [(("h2", "h8"), 400000000)]}
        )

        exp_paths = {
            ("h1", "h8"): {
                "prim": ["h1", "c1", "s02", "s04", "c2", "s07", "s09", "c3", "h8"],
                "sec": ["h1", "c1", "s02", "s06", "c2", "s05", "s08", "c3", "h8"]},
            ("h2", "h8"): {
                "prim": ["h2", "c1", "s02", "s10", "c4", "s12", "s14", "c5", "s15", "s09", "c3", "h8"],
                "sec": ["h2", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"]}
        }

        exp_inst = {
            "c1": {
                ("h1", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 5), "out_addr": "0."}],
                ("h2", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 6), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}],
            }, "c2": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s04", 3), "out": ("s07", 3)},
                    {"action": "add", "in": ("s06", 4), "out": ("s05", 4)}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s04", 3), "out": ("s05", 4)}],
            }, "c3": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s09", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}],
            }, "c4": {
                ("h2", "h8"): [
                    {"action": "add", "in": ("s10", 3), "out": ("s12", 3)}],
            }, "c5": {
                ("h2", "h8"): [
                    {"action": "add", "in": ("s14", 3), "out": ("s15", 3)}],
            }
        }

        self._check_computed_paths(exp_paths, exp_inst)

    def test_case_03(self, show_print=True):
        """ Scenario 3: h1 -> h8 400M, h2 -> h8 400M

        Outcome:
            h1-h8 moved to c4 at c1
        """
        if show_print:
            print("\nTesting scenario 3 (h1->h8 400M | h2-h8 400M)")

        # Configure the initial state of the experiment
        self.test_case_02(show_print=False)

        # Initiate experiment
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c1", "sw": "s02", "port": 4, "traff_bps": 400000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c1", "sw": "s02", "port": 6, "traff_bps": 400000000})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 0})
        self.ctrl._action_inter_domain_link_traffic(
            {"cid": "c2", "sw": "s07", "port": 3, "traff_bps": 200000000})
        self.ctrl._action_inter_domain_link_congested(
            {"cid": "c2", "sw": "s07", "port": 3, "traff_bps": 400000000,
            "te_thresh": 0.90, "paths": [(("h1", "h8"), 400000000)]}
        )

        exp_paths = {
            ("h1", "h8"): {
                "prim": ["h1", "c1", "s02", "s10", "c4", "s12", "s14", "c5", "s15", "s09", "c3", "h8"],
                "sec": ["h1", "c1", "s02", "s04", "c2", "s07", "s09", "c3", "h8"]},
            ("h2", "h8"): {
                "prim": ["h2", "c1", "s02", "s10", "c4", "s12", "s14", "c5", "s15", "s09", "c3", "h8"],
                "sec": ["h2", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"]}
        }

        exp_inst = {
            "c1": {
                ("h1", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 6), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}],
                ("h2", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 6), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}],
                ("h8", "h1"): [
                    {"action": "add", "in": ("s02", 4), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s02", 5), "out": -1, "out_eth": "a::"}],
                ("h8", "h2"): [
                    {"action": "add", "in": ("s02", 4), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s02", 5), "out": -1, "out_eth": "a::"}]
            }, "c2": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s04", 3), "out": ("s07", 3)}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s04", 3), "out": ("s05", 4)}],
                ("h8", "h1"): [
                    {"action": "add", "in": ("s05", 4), "out": ("s04", 3)},
                    {"action": "add", "in": ("s07", 3), "out": ("s06", 4)}],
                ("h8", "h2"): [
                    {"action": "add", "in": ("s05", 4), "out": ("s04", 3)},
                    {"action": "add", "in": ("s07", 3), "out": ("s06", 4)}],
            }, "c3": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s09", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s09", 2), "out": -1, "out_eth": "a::"}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s09", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}],
                ("h8", "h1"): [
                    {"action": "add", "in": -1, "out": ("s08", 3), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s09", 2), "out_addr": "0."}],
                ("h8", "h2"): [
                    {"action": "add", "in": -1, "out": ("s08", 3), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s09", 2), "out_addr": "0."}],
            }, "c4": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s10", 3), "out": ("s12", 3)}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s10", 3), "out": ("s12", 3)}],
            }, "c5": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s14", 3), "out": ("s15", 3)}],
                ("h2", "h8"): [
                    {"action": "add", "in": ("s14", 3), "out": ("s15", 3)}],
            }
        }

        self._check_computed_paths(exp_paths, exp_inst)

    def test_case_04(self, show_print=True):
        """ Scenario 4: h1 -> h8 400M, h2 -> h8 400M

        NOTE: This is a clean slate scenario that does not build off of
        scenario 1-3 state. This scenario starts at scenario 0 and checks
        the behaivour of the candidate filtering.

        Outcome:
            No path changes should occur for the 3 checks while the last
            should trigger a TE optimisation as a host-pair is over-using
            the port and the adjusted usage is above the te-threshold.
        """
        if show_print:
            print("\nTesting scenario 4 (candidate usage checks)")

        # Configure the initial state of the experiment (no TE optimisation)
        self.test_case_00(show_print=False)

        # XXX: No NEED TO SPECIFY FAKE TRAFFIC ON LINKS AS WE ARE TESTING
        # WITH FAKE MESSAGES TO SEE BEHAIVOUR
        #
        # Initiate experiment and make sure no changes occur
        #self.ctrl._action_inter_domain_link_traffic(
        #    {"cid": "c1", "sw": "s02", "port": 4, "traff_bps": 110000000})
        #self.ctrl._action_inter_domain_link_traffic(
        #    {"cid": "c1", "sw": "s02", "port": 6, "traff_bps": 80000000})
        #self.ctrl._action_inter_domain_link_traffic(
        #    {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 0})
        #self.ctrl._action_inter_domain_link_traffic(
        #    {"cid": "c2", "sw": "s07", "port": 3, "traff_bps": 110000000})

        # Check that all host pairs have been removed
        if show_print:
            print("\tTesting - No pair uses port")
        self.ctrl._action_inter_domain_link_congested(
            {"cid": "c2", "sw": "s07", "port": 3, "traff_bps": 600000000,
               "te_thresh": 0.90, "paths": [
                    (("h1", "h8"), 200000000),
                    (("h2", "h8"), 200000000),
                    (("h8", "h1"), 200000000)
                ]
            }
        )
        self._check_computed_paths()

        # Check that TE-Thresh is correctly adjusted
        if show_print:
            print("\tTesting - Congestion under threshold (remove lowest usage pair)")
        self.ctrl._action_inter_domain_link_congested(
            {"cid": "c1", "sw": "s02", "port": 4, "traff_bps": 1000000000,
                "te_thresh": 0.90, "paths": [
                    (("h1", "h8"), 600000000),
                    (("h8", "h1"), 400000000)
                ]
            }
        )
        self._check_computed_paths()

        # Check that TE-thresh is adjusted before optimisation
        if show_print:
            print("\tTesting - Congestion under threshold (remove highest usage pair)")
        self.ctrl._action_inter_domain_link_congested(
            {"cid": "c1", "sw": "s02", "port": 4, "traff_bps": 1300000000,
               "te_thresh": 0.90, "paths": [
                    (("h1", "h8"), 600000000),
                    (("h8", "h1"), 700000000)
                ]
            }
        )
        self._check_computed_paths()

        # Ensure that we still optimise after adjustment
        exp_paths = {
            ("h1", "h8"): {
                "prim": ["h1", "c1", "s02", "s10", "c4", "s12", "s14", "c5", "s15", "s09", "c3", "h8"],
                "sec": ["h1", "c1", "s02", "s04", "c2", "s05", "s08", "c3", "h8"]},
        }

        exp_inst = {
            "c1": {
                ("h1", "h8"): [
                    {"action": "add", "in": -1, "out": ("s02", 6), "out_addr": "0."},
                    {"action": "add", "in": -1, "out": ("s02", 4), "out_addr": "0."}],
            }, "c2": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s04", 3), "out": ("s05", 4)}],
            }, "c3": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s09", 3), "out": -1, "out_eth": "a::"},
                    {"action": "add", "in": ("s08", 3), "out": -1, "out_eth": "a::"}]
            }, "c4": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s10", 3), "out": ("s12", 3)}],
            }, "c5": {
                ("h1", "h8"): [
                    {"action": "add", "in": ("s14", 3), "out": ("s15", 3)}],
            }
        }

        if show_print:
            print("\tTesting - Optimise after filter if usage > te-thresh")
        self.ctrl._action_inter_domain_link_congested(
            {"cid": "c2", "sw": "s05", "port": 4, "traff_bps": 1080000000,
               "te_thresh": 0.90, "paths": [
                    (("h8", "h2"), 480000000),
                    (("h1", "h8"), 200000000),
                    (("h8", "h1"), 400000000)
                ]
            }
        )

        self._check_computed_paths(exp_paths, exp_inst)


if __name__ == "__main__":
    dummy = DummyRootCtrl()
    dummy.start()
    dummy.stop()
