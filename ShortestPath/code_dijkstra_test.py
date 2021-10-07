#!/usr/bin/env python

# -----------------------------------------------------------------
#
# Unit-test which checks that the dijkstra module works corerctly
#
# Run using the command:
#   'python -m unittest code_dijkstra_test.py'
#
# -----------------------------------------------------------------

import sys
import os
import unittest
from copy import copy

# Import our project code to test
from dijkstra import Graph

class CodeTestDijkstra(unittest.TestCase):
    """ Unit test python class.

    Arguments:
        topo (dict): Topology without failures to use for the test in
            the format: {src: {src_port: (dst, dst_port, cost)}}
        fail (list of list of tuple): Failure scenarios to test path computation.
            Each new entry in the main list is a new scenario.
        expected (list of list of str): Expected path for each
            failure scenario defined by `:cls:attr:(fail)`.
    """
    def setUp(self):
        # Initiate the default topology (without failures)
        # as per the diagrams
        self.topo = {
            "p1": {
                -1: ("s1", 1, 100)},
            "s1": {
                1: ("p1", -1, 100),
                2: ("s2", 1, 100),
                3: ("s4", 1, 100)},
            "s2": {
                1: ("s1", 2, 100),
                2: ("s3", 1, 100),
                3: ("s4", 2, 100),
                4: ("s5", 1, 100)},
            "s3": {
                1: ("s2", 2, 100),
                2: ("d1", -1, 100),
                3: ("s5", 2, 100)},
            "s4": {
                1: ("s1", 3, 100),
                2: ("s2", 3, 100),
                3: ("s5", 3, 100)},
            "s5": {
                1: ("s2", 4, 100),
                2: ("s3", 3, 100),
                3: ("s4", 3, 100)},
            "d1": {
                -1: ("s3", 2, 100)},
        }

        self.fail = [
            [],
            [("s1","s2",2,1)],
            [("s2","s3",2,1)],
            [("s1","s2",2,1), ("s4","s5",3,3)],
            [("s1","s2",2,1), ("s2","s3",2,1), ("s4","s5",3,3)],
            [("s2","s3",2,1), ("s2","s5",4,1)],
            [("s1","s2",2,1), ("s2","s3",2,1), ("s4","s5",3,3), ("s5","s3",2,3)],   # NO PATH
            [("s1","s2",2,1), ("s2","s3",2,1), ("s4","s5",3,3), ("s4","s2",2,3)],   # NO PATH
        ]

        # Expected shortest path from p1 to d1 for failure scenarios
        self.expected = [
            ["p1","s1","s2","s3","d1"],
            ["p1","s1","s4","s2","s3","d1"],
            ["p1","s1","s2","s5","s3","d1"],
            ["p1","s1","s4","s2","s3","d1"],
            ["p1","s1","s4","s2","s5","s3","d1"],
            ["p1","s1","s4","s5","s3","d1"],
            [],
            []
        ]


    def tearDown(self):
        pass


    def runTest(self):
        pass


    def paths_same(self, check, expected):
        """ Check if two paths are the same. A path is considered to be the
        same if they have the same length and the same elements.

        Args:
            check (list of str): First path to check
            expected (list of str): Path to check against

        Returns:
            bool: True if the paths are the same, False otherwise.
        """
        if not len(check) == len(expected):
            return False

        for i in range(len(check)):
            if not check[i] == expected[i]:
                return False

        return True


    def topo_same(self, check, expected):
        """ Check if two topology objects are the same. Topology object have the
        same format as ``Topology`` from the dijkstra.py module.

        Args:
            check (dict): Topology to check
            expected (dict): Topology to check against

        Returns:
            bool: True if the two topologies are the same. False otherwise.
        """
        # Check the lenghts of dict switches
        if not len(check) == len(expected):
            return False

        # Iterate through switch and make sure they are the same
        for s_id,s_val in check.iteritems():
            # Check if the switch ID exists in the expected
            if s_id not in expected:
                return False

            # If the port numbers do not match return false
            if not len(check[s_id]) == len(expected[s_id]):
                return False

            # Iterate through all ports of the switch and
            # make sure they are equal
            for p_id,p_val in check[s_id].iteritems():
                if p_id not in expected[s_id]:
                    return False
                if not p_val == expected[s_id][p_id]:
                    return False

        return True


    def test_shortest_path(self):
        """ Test the shortest path computation of the module. Method will test the
        shortest path for `:cls:attr:(topo)` topology with failure scenarios `:cls:attr:(fail)`.
        For each `:cls:attr:(fail)` we will expect the same path as `:cls:attr:(expected)`.
        """
        # Iterate through all failure scenarios
        for i in range(len(self.fail)):
            failure = self.fail[i]
            e = self.expected[i]

            # Initiate the topology and remove the failed links
            g = Graph(self.topo)

            for link in failure:
                g.remove_port(link[0], link[1], link[2], link[3])
                g.remove_port(link[1], link[0], link[3], link[2])

            # Get the shortest path from p1 do d1 and check the lengths
            res = g.shortest_path("p1", "d1")
            t = i + 1
            print("Checking scenario %d of %d" % (t, len(self.fail)))
            self.assertTrue(self.paths_same(res, e),
                        "Test %d failed, paths are different\n%s\n%s" % (t, res, e))


    def test_switch_remove(self):
        """ Test the switch removal method of the module. Method will remove some
        of the switches in the topology and make sure the shortest path is
        correct for the specific scenario.
        """
        # Initiate the topology and validate it
        print("\nSwitch remove test")
        print("\tInitiating default topology")
        g = Graph(self.topo)
        self.assertTrue(self.topo_same(g.topo, self.topo),
                    "Topology initiation failed\n%s\n\n%s" % (g.topo, self.topo))

        # Make sure the link remove behaves as expected
        print("\tRemoving switch S2")
        g.remove_switch("s2")
        expected_topo = {
            "p1": {
                -1: ("s1", 1, 100)},
            "s1": {
                1: ("p1", -1, 100),
                3: ("s4", 1, 100)},
            "s3": {
                2: ("d1", -1, 100),
                3: ("s5", 2, 100)},
            "s4": {
                1: ("s1", 3, 100),
                3: ("s5", 3, 100)},
            "s5": {
                2: ("s3", 3, 100),
                3: ("s4", 3, 100)},
            "d1": {
                -1: ("s3", 2, 100)},
        }
        self.assertTrue(self.topo_same(g.topo, expected_topo),
                    "Topology after switch removal is different from expected\n%s\n\n%s" % (g.topo, expected_topo))

        # Compute the shortest path and validate its correct
        e = ["p1", "s1", "s4", "s5", "s3", "d1"]
        res = g.shortest_path("p1", "d1")
        self.assertTrue(self.paths_same(res, e), "Test failed, paths are different\n%s\n%s" %
                        (res, e))

        # Remove switch S4 and make sure no path exists
        print("\tRemoving switch S4")
        g.remove_switch("s4")
        expected_topo = {
            "p1": {
                -1: ("s1", 1, 100)},
            "s1": {
                1: ("p1", -1, 100)},
            "s3": {
                2: ("d1", -1, 100),
                3: ("s5", 2, 100)},
            "s5": {
                2: ("s3", 3, 100)},
            "d1": {
                -1: ("s3", 2, 100)},
        }
        self.assertTrue(self.topo_same(g.topo, expected_topo),
                    "Topology after switch removal is different from expected\n%s\n\n%s" % (g.topo, expected_topo))

        # Compute the shortest path and validate its correct
        e = []
        res = g.shortest_path("p1", "d1")
        self.assertTrue(self.paths_same(res, e), "Test failed, paths are different\n%s\n%s" %
                        (res, e))

        # Starting form the first topology delete link S4
        print("\tRecreating topology")
        g = Graph(self.topo)
        self.assertTrue(self.topo_same(g.topo, self.topo),
                    "Topology initiation failed\n%s\n\n%s" % (g.topo, self.topo))

        print("\tRemoving switch S4 (recreated topo)")
        g.remove_switch("s4")
        expected_topo = {
            "p1": {
                -1: ("s1", 1, 100)},
            "s1": {
                1: ("p1", -1, 100),
                2: ("s2", 1, 100)},
            "s2": {
                1: ("s1", 2, 100),
                2: ("s3", 1, 100),
                4: ("s5", 1, 100)},
            "s3": {
                1: ("s2", 2, 100),
                2: ("d1", -1, 100),
                3: ("s5", 2, 100)},
            "s5": {
                1: ("s2", 4, 100),
                2: ("s3", 3, 100)},
            "d1": {
                -1: ("s3", 2, 100)},
        }

        self.assertTrue(self.topo_same(g.topo, expected_topo),
                    "Topology after switch removal is different from expected\n%s\n\n%s" % (g.topo, expected_topo))

        # Compute the shortest path and validate its correct
        e = ["p1", "s1", "s2", "s3", "d1"]
        res = g.shortest_path("p1", "d1")
        self.assertTrue(self.paths_same(res, e), "Test failed, paths are different\n%s\n%s" %
                        (res, e))

        # Remove switch S5
        print("\tRemoving switch S5")
        g.remove_switch("s5")
        expected_topo = {
            "p1": {
                -1: ("s1", 1, 100)},
            "s1": {
                1: ("p1", -1, 100),
                2: ("s2", 1, 100)},
            "s2": {
                1: ("s1", 2, 100),
                2: ("s3", 1, 100)},
            "s3": {
                1: ("s2", 2, 100),
                2: ("d1", -1, 100)},
            "d1": {
                -1: ("s3", 2, 100)},
        }

        self.assertTrue(self.topo_same(g.topo, expected_topo),
                    "Topology after switch removal is different from expected\n%s\n\n%s" % (g.topo, expected_topo))

        # Compute the shortest path and validate its correct
        e = ["p1", "s1", "s2", "s3", "d1"]
        res = g.shortest_path("p1", "d1")
        self.assertTrue(self.paths_same(res, e), "Test failed, paths are different\n%s\n%s" %
                        (res, e))


if __name__ == "__main__":
    unittest.main()
