#!/usr/bin/env python

# -----------------------------------------------------------------
#
# Integration tests that checks that the controller TE optimisation
# mechanism behaves as expected. The tests implement the "TE Swap
# Efficiency Test" outlined in `Docs/TESwapEfficiencyTest.md`.
#
# Run using the command:
#   python -m unittest code_te_swap_efficiency_test.py
#
# -----------------------------------------------------------------

import sys
import os
import unittest
import logging

from dummy_ctrl import DummyCtrl

class TEScenarioTest(unittest.TestCase):
    """ Integrationt test class.

    Arguments:
        DEFAULT_PATHS (dict): Dictionary of expected path information to be generated
            by the controller.
        topo (dict): Topology description of the network
        hosts (list of str): List of hosts in the topology
        ctrl (DummyCtrl): Dummy controller object to test
    """

    DEFAULT_PATHS = {
            ("h1", "h2"): {
                "ingress": "s1", "in_port": 1,
                "egress": "s1", "out_port": 2,
                "groups": {}
            }, ("h1", "h3"): {
                "ingress": "s1", "in_port": 1,
                "egress": "s3", "out_port": 3,
                "groups": {"s1": [3, 4], "s2": [3, 4], "s3": [3], "s4": [2], "s5": [2]}
            }, ("h1", "h4"): {
                "ingress": "s1", "in_port": 1,
                "egress": "s3", "out_port": 4,
                "groups": {"s1": [3, 4], "s2": [3, 4], "s3": [4], "s4": [2], "s5": [2]}

            }, ("h2", "h1"): {
                "ingress": "s1", "in_port": 2,
                "egress": "s1", "out_port": 1,
                "groups": {}
            }, ("h2", "h3"): {
                "ingress": "s1", "in_port": 2,
                "egress": "s3", "out_port": 3,
                "groups": {"s1": [3, 4], "s2": [3, 4], "s3": [3], "s4": [2], "s5": [2]}
            }, ("h2", "h4"): {
                "ingress": "s1", "in_port": 2,
                "egress": "s3", "out_port": 4,
                "groups": {"s1": [3, 4], "s2": [3, 4], "s3": [4], "s4": [2], "s5": [2]}

            }, ("h3", "h1"): {
                "ingress": "s3", "in_port": 3,
                "egress": "s1", "out_port": 1,
                "groups": {"s3": [1, 2], "s2": [1, 2], "s1": [1], "s5": [1], "s4": [1]}
            }, ("h3", "h2"): {
                "ingress": "s3", "in_port": 3,
                "egress": "s1", "out_port": 2,
                "groups": {"s3": [1, 2], "s2": [1, 2], "s1": [2], "s5": [1], "s4": [1]}
            }, ("h3", "h4"): {
                "ingress": "s3", "in_port": 3,
                "egress": "s3", "out_port": 4,
                "groups": {}

            }, ("h4", "h1"): {
                "ingress": "s3", "in_port": 4,
                "egress": "s1", "out_port": 1,
                "groups": {"s3": [1, 2], "s2": [1, 2], "s1": [1], "s5": [1], "s4": [1]}
            }, ("h4", "h2"): {
                "ingress": "s3", "in_port": 4,
                "egress": "s1", "out_port": 2,
                "groups": {"s3": [1, 2], "s2": [1, 2], "s1": [2], "s5": [1], "s4": [1]}
            }, ("h4", "h3"): {
                "ingress": "s3", "in_port": 4,
                "egress": "s3", "out_port": 3,
                "groups": {}
            }
        }

    def setUp(self):
        """ Build the topology, initiate the controller and compute required paths """
        self.topo = {
            "h1": {-1: {"dest": "s1", "destPort": 1, "speed": 1000000000}},
            "h2": {-1: {"dest": "s1", "destPort": 2, "speed": 1000000000}},
            "s1": { 1: {"dest": "h1", "destPort": -1, "speed": 1000000000},
                    2: {"dest": "h2", "destPort": -1, "speed": 1000000000},
                    3: {"dest": "s2", "destPort": 1, "speed": 1000000000},
                    4: {"dest": "s4", "destPort": 1, "speed": 1000000000}},
            "s4": { 1: {"dest": "s1", "destPort": 4, "speed": 1000000000},
                    2: {"dest": "s2", "destPort": 2, "speed": 1000000000}},
            "s2": { 1: {"dest": "s1", "destPort": 3, "speed": 1000000000},
                    2: {"dest": "s4", "destPort": 2, "speed": 1000000000},
                    3: {"dest": "s3", "destPort": 1, "speed": 1000000000},
                    4: {"dest": "s5", "destPort": 1, "speed": 1000000000}},
            "s5": { 1: {"dest": "s2", "destPort": 4, "speed": 1000000000},
                    2: {"dest": "s3", "destPort": 2, "speed": 1000000000}},
            "s3": { 1: {"dest": "s2", "destPort": 3, "speed": 1000000000},
                    2: {"dest": "s5", "destPort": 2, "speed": 1000000000},
                    3: {"dest": "h3", "destPort": -1, "speed": 1000000000},
                    4: {"dest": "h4", "destPort": -1, "speed": 1000000000}},
            "h3": {-1: {"dest": "s3", "destPort": 3, "speed": 1000000000}},
            "h4": {-1: {"dest": "s3", "destPort": 4, "speed": 1000000000}}}
        self.hosts = ["h1", "h2", "h3", "h4"]

        # Supress any logging by setting to a level above critical
        logging.basicConfig(level=100)
        self.ctrl = DummyCtrl(topo=self.topo, hosts=self.hosts, logger=logging)
        self.ctrl._install_protection()
        self.ctrl.clear_traffic()

    def test_case_00(self):
        print("\nTesting default controller state")
        self._check_info_dict(self.ctrl.paths)
        self._check_congested_link([])

    def test_case_01(self):
        print("\nTesting scenario 1 (h1-h3 150M | h2-h4 120M)")

        # Constraint the link between s1-s2 to 200Mbps and load traffic
        print("\tConstraining topology links and loading traffic")
        scenario_traffic = {("h1", "h3"): 150000000, ("h2", "h4"): 120000000}
        self.ctrl.graph.update_port_info("s1", 3, speed=200000000)
        self.ctrl.graph.update_port_info("s2", 1, speed=200000000)
        self.ctrl.load_traffic(scenario_traffic)

        # Check for congested links and run optimisation
        print("\tChecking for congested links")
        expected_congested = [("s1", 3)]
        self._check_congested_link(expected_congested)

        print("\tOptimising network")
        self.ctrl.TE._optimise_TE()

        expected = {
            ("h1", "h3"): {
                "ingress": "s1", "in_port": 1,
                "egress": "s3", "out_port": 3,
                "groups": {
                    "s1": [3, 4], "s2": [3, 4], "s3": [3], "s4": [2], "s5": [2]
                }
            }, ("h2", "h4"): {
                "ingress": "s1", "in_port": 2,
                "egress": "s3", "out_port": 4,
                "groups": {
                    "s1": [4, 3], "s2": [3, 4], "s3": [4], "s4": [2], "s5": [2]
                }
            }
        }

        print("\tChecking path modifications")
        self._check_info_dict(self.ctrl.paths, expected)

        print("\tChecking final state of controller")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        self._check_congested_link([])

    def test_case_02(self):
        print("\nTesting scenario 2 (h1-h3 150M | h2-h4 120M)")

        # Constrain links and load traffic
        print("\tConstraining topology links and loading traffic")
        scenario_traffic = {("h1", "h3"): 150000000, ("h2", "h4"): 120000000}
        self.ctrl.graph.update_port_info("s1", 3, speed=200000000)
        self.ctrl.graph.update_port_info("s2", 1, speed=200000000)
        self.ctrl.graph.update_port_info("s2", 3, speed=200000000)
        self.ctrl.graph.update_port_info("s3", 1, speed=200000000)
        self.ctrl.load_traffic(scenario_traffic)

        # Check for congested links and run optimisation
        print("\tChecking for congested links")
        expected_congested = [("s1", 3), ("s2", 3)]
        self._check_congested_link(expected_congested)

        print("\tOptimising network")
        self.ctrl.TE._optimise_TE()

        expected = {
            ("h1", "h3"): {
                "ingress": "s1", "in_port": 1,
                "egress": "s3", "out_port": 3,
                "groups": {
                    "s1": [3, 4], "s2": [3, 4], "s3": [3], "s4": [2], "s5": [2]
                }
            }, ("h2", "h4"): {
                "ingress": "s1", "in_port": 2,
                "egress": "s3", "out_port": 4,
                "groups": {
                    "s1": [4, 3], "s2": [4, 3], "s3": [4], "s4": [2], "s5": [2]
                }
            }
        }

        print("\tChecking path modifications")
        self._check_info_dict(self.ctrl.paths, expected)

        print("\tChecking final state of controller")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        self._check_congested_link([])

    def test_case_03(self):
        print("\nTesting scenario 3 (h1-h3 150M | h2-h4 120M)")

        # Constrain links and load traffic
        print("\tConstraining topology links and loading traffic")
        scenario_traffic = {("h1", "h3"): 150000000, ("h2", "h4"): 120000000}
        self.ctrl.graph.update_port_info("s1", 3, speed=200000000)
        self.ctrl.graph.update_port_info("s2", 1, speed=200000000)
        self.ctrl.graph.update_port_info("s2", 3, speed=200000000)
        self.ctrl.graph.update_port_info("s3", 1, speed=200000000)
        self.ctrl.graph.update_port_info("s5", 2, speed=100000000)
        self.ctrl.graph.update_port_info("s3", 2, speed=100000000)
        self.ctrl.load_traffic(scenario_traffic)

        # Check for congested links and run optimisation
        print("\tChecking for congested links")
        expected_congested = [("s1", 3), ("s2", 3)]
        self._check_congested_link(expected_congested)

        print("\tOptimising network")
        self.ctrl.TE._optimise_TE()

        expected = {
            ("h1", "h3"): {
                "ingress": "s1", "in_port": 1,
                "egress": "s3", "out_port": 3,
                "groups": {
                    "s1": [3, 4], "s2": [3, 4], "s3": [3], "s4": [2], "s5": [2]
                }
            }, ("h2", "h4"): {
                "ingress": "s1", "in_port": 2,
                "egress": "s3", "out_port": 4,
                "groups": {
                    "s1": [4, 3], "s2": [3, 4], "s3": [4], "s4": [2], "s5": [2]
                }
            }
        }

        print("\tChecking path modifications")
        self._check_info_dict(self.ctrl.paths, expected)

        print("\tChecking final state of controller")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        self._check_congested_link([("s2", 3)])

    # XXX TODO: While going through the steps of this test it seems that the controller
    # TE swapover misbehaves, why dosen't it detect that swapping traffic at S1-S4 for
    # both host pairs over-constrains the next effective link, S2-S3. This is strange.
    # what is going on!!!!
    def test_case_04(self):
        print("\nTesting scenario 4 (h1-h3 150M | h2-h4 120M)")

        # Constrain links and load traffic
        print("\tConstraining topology links and loading traffic")
        scenario_traffic = {("h1", "h3"): 150000000, ("h2", "h4"): 120000000}
        self.ctrl.graph.update_port_info("s1", 3, speed=100000000)
        self.ctrl.graph.update_port_info("s2", 1, speed=100000000)
        self.ctrl.graph.update_port_info("s2", 3, speed=200000000)
        self.ctrl.graph.update_port_info("s3", 1, speed=200000000)
        self.ctrl.load_traffic(scenario_traffic)

        # Check for congested links and run optimisation (step 1)
        print("\tChecking for congested links (step 1)")
        expected_congested = [("s1", 3)]
        self._check_congested_link(expected_congested)

        print("\tOptimising network (step 1)")
        self.ctrl.TE._optimise_TE()

        expected = {
            ("h1", "h3"): {
                "ingress": "s1", "in_port": 1,
                "egress": "s3", "out_port": 3,
                "groups": {
                    "s1": [4, 3], "s2": [3, 4], "s3": [3], "s4": [2], "s5": [2]
                }
            }, ("h2", "h4"): {
                "ingress": "s1", "in_port": 2,
                "egress": "s3", "out_port": 4,
                "groups": {
                    "s1": [4, 3], "s2": [3, 4], "s3": [4], "s4": [2], "s5": [2]
                }
            }
        }

        print("\tChecking path modifications (step 1)")
        self._check_info_dict(self.ctrl.paths, expected)

        # Check for congested links and run optimisation (step 2)
        print("\tChecking for congested links (step 2)")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        expected_congested = [("s2", 3)]
        self._check_congested_link(expected_congested)

        print("\tOptimising network (step 2)")
        self.ctrl.TE._optimise_TE()

        expected = {
            ("h1", "h3"): {
                "ingress": "s1", "in_port": 1,
                "egress": "s3", "out_port": 3,
                "groups": {
                    "s1": [4, 3], "s2": [3, 4], "s3": [3], "s4": [2], "s5": [2]
                }
            }, ("h2", "h4"): {
                "ingress": "s1", "in_port": 2,
                "egress": "s3", "out_port": 4,
                "groups": {
                    "s1": [4, 3], "s2": [4, 3], "s3": [4], "s4": [2], "s5": [2]
                }
            }
        }

        print("\tChecking path modifications (step 2)")
        self._check_info_dict(self.ctrl.paths, expected)

        print("\tChecking final state of controller")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        self._check_congested_link([])

    def test_case_05(self):
        print("\nTesting scenario 5 (h1-h3 150M | h2-h4 120M)")

        # Constrain links and load traffic
        print("\tConstraining topology links and loading traffic")
        scenario_traffic = {("h1", "h3"): 150000000, ("h2", "h4"): 120000000}
        self.ctrl.graph.update_port_info("s1", 3, speed=200000000)
        self.ctrl.graph.update_port_info("s2", 1, speed=200000000)
        self.ctrl.graph.update_port_info("s2", 3, speed=100000000)
        self.ctrl.graph.update_port_info("s3", 1, speed=100000000)
        self.ctrl.load_traffic(scenario_traffic)

        # Check for congested links and run optimisation
        print("\tChecking for congested links")
        expected_congested = [("s1", 3), ("s2", 3)]
        self._check_congested_link(expected_congested)

        print("\tOptimising network")
        self.ctrl.TE._optimise_TE()

        expected = {
            ("h1", "h3"): {
                "ingress": "s1", "in_port": 1,
                "egress": "s3", "out_port": 3,
                "groups": {
                    "s1": [3, 4], "s2": [4, 3], "s3": [3], "s4": [2], "s5": [2]
                }
            }, ("h2", "h4"): {
                "ingress": "s1", "in_port": 2,
                "egress": "s3", "out_port": 4,
                "groups": {
                    "s1": [4, 3], "s2": [4, 3], "s3": [4], "s4": [2], "s5": [2]
                }
            }
        }

        print("\tChecking path modifications")
        self._check_info_dict(self.ctrl.paths, expected)

        print("\tChecking final state of controller")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        self._check_congested_link([])

    def test_case_06(self):
        print("\nTesting scenario 6 (h1-h3 150M | h2-h4 120M)")

        # Constrain links and load traffic
        print("\tConstraining topology links and loading traffic")
        scenario_traffic = {("h1", "h3"): 150000000, ("h2", "h4"): 120000000}
        self.ctrl.graph.update_port_info("s1", 3, speed=100000000)
        self.ctrl.graph.update_port_info("s2", 1, speed=100000000)
        self.ctrl.graph.update_port_info("s2", 3, speed=100000000)
        self.ctrl.graph.update_port_info("s3", 1, speed=100000000)
        self.ctrl.load_traffic(scenario_traffic)

        # Check for congested links and run optimisation
        print("\tChecking for congested links")
        expected_congested = [("s1", 3), ("s2", 3)]
        self._check_congested_link(expected_congested)

        print("\tOptimising network")
        self.ctrl.TE._optimise_TE()

        expected = {
            ("h1", "h3"): {
                "ingress": "s1", "in_port": 1,
                "egress": "s3", "out_port": 3,
                "groups": {
                    "s1": [4, 3], "s2": [4, 3], "s3": [3], "s4": [2], "s5": [2]
                }
            }, ("h2", "h4"): {
                "ingress": "s1", "in_port": 2,
                "egress": "s3", "out_port": 4,
                "groups": {
                    "s1": [4, 3], "s2": [4, 3], "s3": [4], "s4": [2], "s5": [2]
                }
            }
        }

        print("\tChecking path modifications")
        self._check_info_dict(self.ctrl.paths, expected)

        print("\tChecking final state of controller")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        self._check_congested_link([])

    def test_case_07(self):
        print("\nTesting scenario 7 (h1-h3 150M)")

        # Constrain links and load traffic
        print("\tConstraining topology links and loading traffic")
        scenario_traffic = {("h1", "h3"): 150000000}
        self.ctrl.graph.update_port_info("s1", 3, speed=100000000)
        self.ctrl.graph.update_port_info("s2", 1, speed=100000000)
        self.ctrl.graph.update_port_info("s2", 3, speed=100000000)
        self.ctrl.graph.update_port_info("s3", 1, speed=100000000)
        self.ctrl.load_traffic(scenario_traffic)

        # Check for congested links and run optimisation
        print("\tChecking for congested links")
        expected_congested = [("s1", 3), ("s2", 3)]
        self._check_congested_link(expected_congested)

        print("\tOptimising network")
        self.ctrl.TE._optimise_TE()

        expected = {
            ("h1", "h3"): {
                "ingress": "s1", "in_port": 1,
                "egress": "s3", "out_port": 3,
                "groups": {
                    "s1": [4, 3], "s2": [4, 3], "s3": [3], "s4": [2], "s5": [2]
                }
            }, ("h2", "h4"): {
                "ingress": "s1", "in_port": 2,
                "egress": "s3", "out_port": 4,
                "groups": {
                    "s1": [3, 4], "s2": [3, 4], "s3": [4], "s4": [2], "s5": [2]
                }
            }
        }

        print("\tChecking path modifications")
        self._check_info_dict(self.ctrl.paths, expected)

        print("\tChecking final state of controller")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        self._check_congested_link([])

    def test_case_08(self):
        print("\nTesting scenario 8 (h1-h3 150M | h4-h2 120M)")

        # Constrain links and load traffic
        print("\tConstraining topology links and loading traffic")
        scenario_traffic = {("h1", "h3"): 150000000, ("h4", "h2"): 120000000}
        self.ctrl.graph.update_port_info("s1", 3, speed=200000000)
        self.ctrl.graph.update_port_info("s2", 1, speed=200000000)
        self.ctrl.graph.update_port_info("s2", 3, speed=200000000)
        self.ctrl.graph.update_port_info("s3", 1, speed=200000000)
        self.ctrl.load_traffic(scenario_traffic)

        # Check for congested links and run optimisation
        print("\tChecking for congested links")
        expected_congested = []
        self._check_congested_link(expected_congested)

        print("\tOptimising network")
        self.ctrl.TE._optimise_TE()

        print("\tChecking paths were not modified")
        self._check_info_dict(self.ctrl.paths)

        print("\tChecking final state of controller")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        self._check_congested_link([])

    def test_case_09(self):
        print("\nTesting scenario 9 (h1-h3 150M | h4-h2 120M)")

        # Constrain links and load traffic
        print("\tConstraining topology links and loading traffic")
        scenario_traffic = {("h1", "h3"): 150000000, ("h4", "h2"): 120000000}
        self.ctrl.graph.update_port_info("s1", 3, speed=100000000)
        self.ctrl.graph.update_port_info("s2", 1, speed=100000000)
        self.ctrl.graph.update_port_info("s2", 3, speed=100000000)
        self.ctrl.graph.update_port_info("s3", 1, speed=100000000)
        self.ctrl.load_traffic(scenario_traffic)

        # Check for congested links and run optimisation
        print("\tChecking for congested links")
        expected_congested = [("s1", 3), ("s2", 3), ("s3", 1), ("s2", 1)]
        self._check_congested_link(expected_congested)

        print("\tOptimising network")
        self.ctrl.TE._optimise_TE()

        expected = {
            ("h1", "h3"): {
                "ingress": "s1", "in_port": 1,
                "egress": "s3", "out_port": 3,
                "groups": {
                    "s1": [4, 3], "s2": [4, 3], "s3": [3], "s4": [2], "s5": [2]
                }
            }, ("h4", "h2"): {
                "ingress": "s3", "in_port": 4,
                "egress": "s1", "out_port": 2,
                "groups": {"s3": [2, 1], "s2": [2, 1], "s1": [2], "s5": [1], "s4": [1]}
            }
        }

        print("\tChecking path modifications")
        self._check_info_dict(self.ctrl.paths, expected)

        print("\tChecking final state of controller")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        self._check_congested_link([])

    def test_case_10(self):
        print("\nTesting scenario 10 (h1-h2 1G | h3-h4 1G)")

        # Constrain links and load traffic
        print("\tConstraining topology links and loading traffic")
        scenario_traffic = {("h1", "h2"): 1000000000, ("h3", "h4"): 1000000000}
        self.ctrl.load_traffic(scenario_traffic)

        # Check for congested links and run optimisation
        print("\tChecking for congested links")
        expected_congested = [("s1", 2), ("s3", 4)]
        self._check_congested_link(expected_congested)

        print("\tOptimising network")
        self.ctrl.TE._optimise_TE()

        print("\tChecking paths were not modified")
        self._check_info_dict(self.ctrl.paths)

        print("\tChecking final state of controller")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        self._check_congested_link([], expected_congested)

    def test_case_11(self):
        print("\nTesting scenario 11 (h1-h3 150M | h2-h4 150M)")

        # Constrain links and load traffic
        print("\tConstraining topology links and loading traffic")
        scenario_traffic = {("h1", "h3"): 150000000, ("h2", "h4"): 150000000}
        self.ctrl.graph.update_port_info("h1", -1, speed=100000000)
        self.ctrl.graph.update_port_info("s1", 1, speed=100000000)
        self.ctrl.graph.update_port_info("h2", -1, speed=100000000)
        self.ctrl.graph.update_port_info("s1", 2, speed=100000000)
        self.ctrl.graph.update_port_info("h3", -1, speed=100000000)
        self.ctrl.graph.update_port_info("s3", 3, speed=100000000)
        self.ctrl.graph.update_port_info("h4", -1, speed=100000000)
        self.ctrl.graph.update_port_info("s3", 4, speed=100000000)
        self.ctrl.load_traffic(scenario_traffic)

        # Check for congested links and run optimisation
        print("\tChecking for congested links")
        expected_congested = [("s3", 3), ("s3", 4)]
        self._check_congested_link(expected_congested)

        print("\tOptimising network")
        self.ctrl.TE._optimise_TE()

        print("\tChecking paths were not modified")
        self._check_info_dict(self.ctrl.paths)

        print("\tChecking final state of controller")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        self._check_congested_link([], expected_congested)

    def test_case_12(self):
        print("\nTesting scenario 12 (h1-h4 150M | h2-h3 150M)")

        # Constrain links and load traffic
        print("\tConstraining topology links and loading traffic")
        scenario_traffic = {("h1", "h4"): 150000000, ("h2", "h3"): 150000000}
        self.ctrl.graph.update_port_info("h1", -1, speed=100000000)
        self.ctrl.graph.update_port_info("s1", 1, speed=100000000)
        self.ctrl.graph.update_port_info("h2", -1, speed=100000000)
        self.ctrl.graph.update_port_info("s1", 2, speed=100000000)
        self.ctrl.graph.update_port_info("h3", -1, speed=100000000)
        self.ctrl.graph.update_port_info("s3", 3, speed=100000000)
        self.ctrl.graph.update_port_info("h4", -1, speed=100000000)
        self.ctrl.graph.update_port_info("s3", 4, speed=100000000)
        self.ctrl.load_traffic(scenario_traffic)

        # Check for congested links and run optimisation
        print("\tChecking for congested links")
        expected_congested = [("s3", 3), ("s3", 4)]
        self._check_congested_link(expected_congested)

        print("\tOptimising network")
        self.ctrl.TE._optimise_TE()

        print("\tChecking paths were not modified")
        self._check_info_dict(self.ctrl.paths)

        print("\tChecking final state of controller")
        self.ctrl.clear_traffic()
        self.ctrl.load_traffic(scenario_traffic)
        self._check_congested_link([], expected_congested)


    # ---------- HELPER METHODS ----------


    def _check_info_dict(self, check, expected={}):
        """ Asert if the information dictionary `check` contains the same state as `expected`.
        Only the value of the fields in `expected` are compared. If the entries in `check`
        contain extra fields, these will be ignored.

        NOTE:
            If `expected` dosen't contain a path host key, the default value is compared against
            `expected`. Defaults are defined in `mod:attr:(DEFAULTS_PATHS)`.
        """
        # Compare expected
        for hkey,expect_d in expected.iteritems():
            self.assertIn(hkey, check, msg="Host key %s-%s not in path info" % hkey)
            for field,val in expect_d.iteritems():
                target = self.ctrl.paths[hkey]
                self.assertIn(field, target, msg="Field %s not in path info of %s-%s" %
                                                                (field, hkey[0], hkey[1]))
                self.assertEqual(target[field], val, msg="Field (%s) %s != %s for path info of %s-%s" %
                                                        (field, target[field], val, hkey[0], hkey[1]))

        # Compare default field values
        for hkey,expect_d in self.DEFAULT_PATHS.iteritems():
            if hkey in expected:
                continue

            self.assertIn(hkey, check, msg="(DEFAULT) Host key %s-%s not in path info" % hkey)
            for field,val in expect_d.iteritems():
                target = self.ctrl.paths[hkey]
                self.assertIn(field, target, msg="(DEFAULT) Field %s not in path info of %s-%s" %
                                                                (field, hkey[0], hkey[1]))
                self.assertEqual(target[field], val, msg="(DEFAULT) Field (%s) %s != %s for path info of %s-%s" %
                                                        (field, target[field], val, hkey[0], hkey[1]))

    def _check_congested_link(self, congested, over_util_keys=None):
        """ Assert that the controller is correctly detecting all links defined in `congested` as
        congested. All other links also need to not be congested.

        NOTE: `over_util_keys` specifies what keys we expect to be present in the TE module
        over utilised dictionary at the end of the link congestion check. By default this value
        is set to the list of congested ports `congested`.
        """
        # Check that the congested links are being detected as congested
        for lk in congested:
            sw, pn = lk
            pinfo = self.ctrl.graph.get_port_info(sw, pn)
            self.assertIsNotNone(pinfo)
            self.assertIn("poll_stats", pinfo)
            self.assertIn("tx_bytes", pinfo["poll_stats"])

            conv = 8.0 / self.ctrl.get_poll_rate()
            tx = pinfo["poll_stats"]["tx_bytes"]
            tx_rate = round(float(tx*conv)/float(pinfo["speed"]), 2)
            self.assertTrue(self.ctrl.TE.check_link_congested(sw, pn, tx_rate),
                                msg="SW %s port %s is not congested (expected congestion)" % lk)

        # Check that the other links are not congested
        for sw,sw_d in self.ctrl.graph.topo.iteritems():
            for pn,pn_d in sw_d.iteritems():
                if (sw, pn) in congested:
                    continue

                pinfo = self.ctrl.graph.get_port_info(sw, pn)
                self.assertIn("poll_stats", pinfo)
                self.assertIn("tx_bytes", pinfo["poll_stats"])

                conv = 8.0 / self.ctrl.get_poll_rate()
                tx = pinfo["poll_stats"]["tx_bytes"]
                tx_rate = round(float(tx*conv)/float(pinfo["speed"]), 2)
                self.assertFalse(self.ctrl.TE.check_link_congested(sw, pn, tx_rate),
                            msg="SW %s port %s is congested (expected not congestion)" % (sw, pn))

        # Make sure the congested dict of the TE module is correct
        if over_util_keys is None:
            over_util_keys = sorted(congested)
        keys = sorted(self.ctrl.TE.over_utilised.keys())
        self.assertEqual(over_util_keys, keys, msg="TE over-util keys %s != %s" % (keys, over_util_keys))


# ----- Main method runner of unittest ----- #

if __name__ == "__main__":
    unittest.main()
