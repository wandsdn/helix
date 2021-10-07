#!/usr/bin/env python

# -----------------------------------------------------------------
#
# Unit-test which checks that the dijkstra module works corerctly
#
# Run using the command:
#   'python -m unittest code_dijkstra_te_test'
#
# -----------------------------------------------------------------

import sys
import os
import unittest
from copy import copy

# Import our project code to test
from dijkstra_te import Graph


class CodeTestDijkstraTe(unittest.TestCase):
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
            "p1": {-1: {"dest": "s1", "destPort": 1}},
            "s1": {1: {"dest": "p1", "destPort": -1},
                2: {"dest": "s2", "destPort": 1},
                3: {"dest": "s4", "destPort": 1}},
            "s2": {1: {"dest": "s1", "destPort": 2},
                2: {"dest": "s3", "destPort": 1},
                3: {"dest": "s4", "destPort": 2},
                4: {"dest": "s5", "destPort": 1}},
            "s3": {1: {"dest": "s2", "destPort": 2},
                3: {"dest": "s5", "destPort": 2},
                2: {"dest": "d1", "destPort": -1}},
            "s4": {1: {"dest": "s1", "destPort": 3},
                2: {"dest": "s2", "destPort": 3},
                3: {"dest": "s5", "destPort": 3}},
            "s5": {1: {"dest": "s2", "destPort": 4},
                2: {"dest": "s3", "destPort": 3},
                3: {"dest": "s4", "destPort": 3}},
            "d1": {-1: {"dest": "s3", "destPort": 2}}
        }

        # Failure scenarios to apply to topo (links)
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

        # Initiate the standard graph from the topology
        self.g = Graph(self.topo)


    def tearDown(self):
        pass


    def runTest(self):
        pass


    def test_first_topo_init(self):
        """ Test the topology initiation and change method """
        print("\nTopology initiation and change test")

        # Test an empty initiation
        print("\tChecking empty initiation")
        temp = Graph()
        self.assertTrue(_topo_same(temp.topo, {}),
                    "Topology on empty initiation failed\n%s\n\n%s" % (temp.topo, {}))

        # Test a update with a non empty dictionary
        print("\tChecking update with non empty dictionary")
        temp.change_topo(self.topo)
        self.assertTrue(_topo_same(temp.topo, self.topo),
                    "Topology change with non empty failed\n%s\n\n%s" % (temp.topo, self.topo))

        # Test a non empty initiation
        print("\tChecking non empty initiation")
        self.assertTrue(_topo_same(self.g.topo, self.topo),
                    "Topology initiation with non empty failed\n%s\n\n%s" % (self.g.topo, self.topo))

        # Test a update with a empty dictionary
        print("\tChecking update with empty dictionary")
        self.g.change_topo({})
        self.assertTrue(_topo_same(self.g.topo, {}),
                    "Topology change with empty failed\n%s\n\n%s" % (self.g.topo, {}))


    def test_shortest_path(self):
        """ Test the shortest path computation of the module. Method will test the
        shortest path for `:cls:attr:(topo)` topology with failure scenarios `:cls:attr:(fail)`.
        For each `:cls:attr:(fail)` we will expect the same path as `:cls:attr:(expected)`.
        """
        print("\nShortest path test")

        # Iterate through all failure scenarios
        for i in range(len(self.fail)):
            failure = self.fail[i]
            e = self.expected[i]

            # Reset the topology
            self.g.change_topo(self.topo)

            for link in failure:
                self.g.remove_port(link[0], link[1], link[2], link[3])
                self.g.remove_port(link[1], link[0], link[3], link[2])

            # Get the shortest path from p1 do d1 and check the lengths
            res = self.g.shortest_path("p1", "d1")
            t = i + 1
            print("\tChecking scenario %d of %d" % (t, len(self.fail)))
            self.assertTrue(_paths_same(res, e),
                    "Test %d failed, paths are different!" % (t))


    def test_host_link_remove(self):
        """ Test the host link remove method of the module """
        print("\nHost link remove test")

        # Make sure the link remove behaves as expected
        print("\tRemoving host link (s1, 1) (host p1)")
        rem_res = self.g.remove_host_link("s1", 1)
        self.assertEqual(rem_res, "p1", "Host link remove failed %s != p1" % rem_res)
        expected_topo = {
            "s1": {2: {"dest": "s2", "destPort": 1},
                3: {"dest": "s4", "destPort": 1}},
            "s2": {1: {"dest": "s1", "destPort": 2},
                2: {"dest": "s3", "destPort": 1},
                3: {"dest": "s4", "destPort": 2},
                4: {"dest": "s5", "destPort": 1}},
            "s3": {1: {"dest": "s2", "destPort": 2},
                3: {"dest": "s5", "destPort": 2},
                2: {"dest": "d1", "destPort": -1}},
            "s4": {1: {"dest": "s1", "destPort": 3},
                2: {"dest": "s2", "destPort": 3},
                3: {"dest": "s5", "destPort": 3}},
            "s5": {1: {"dest": "s2", "destPort": 4},
                2: {"dest": "s3", "destPort": 3},
                3: {"dest": "s4", "destPort": 3}},
            "d1": {-1: {"dest": "s3", "destPort": 2}}
        }

        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                "Topology after host link removal is different from expected\n%s\n\n%s" %
                (self.g.topo, expected_topo))


        # Remove an inexistent host and ensure return is correct
        print("\tRemoving inexistent host link (s1, 1)")
        rem_res = self.g.remove_host_link("s1", 1)
        self.assertEqual(rem_res, None, "Inexistent host link remove failed %s != None" % rem_res)
        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                "Topology after inexistent host link removal changed\n%s\n\n%s" %
                (self.g.topo, expected_topo))


        # Remove host with host end details (should not modify anything)
        print("\tRemoving host link (d1, -1) (incorrect end)")
        rem_res = self.g.remove_host_link("d1", -1)
        self.assertEqual(rem_res, None, "Incorrect end host remove failed %s != None" % rem_res)
        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                "Topology after incorrect end host link removal changed\n%s\n\n%s" %
                (self.g.topo, expected_topo))


        # Remove a non host link (should not change anything)
        print("\tRemoving normal link as host link (s2, 3)")
        rem_res = self.g.remove_host_link("s2", 3)
        self.assertEqual(rem_res, None, "Normal link as host link remove failed %s != None" % rem_res)
        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                "Topology after normal link as host link removal changed\n%s\n\n%s" %
                (self.g.topo, expected_topo))


        # Remove another host
        print("\tRemoving host link (s3, 2) (host d1)")
        rem_res = self.g.remove_host_link("s3", 2)
        self.assertEqual(rem_res, "d1", "Host link remove failed %s != d1" % rem_res)
        expected_topo = {
            "s1": {2: {"dest": "s2", "destPort": 1},
                3: {"dest": "s4", "destPort": 1}},
            "s2": {1: {"dest": "s1", "destPort": 2},
                2: {"dest": "s3", "destPort": 1},
                3: {"dest": "s4", "destPort": 2},
                4: {"dest": "s5", "destPort": 1}},
            "s3": {1: {"dest": "s2", "destPort": 2},
                3: {"dest": "s5", "destPort": 2}},
            "s4": {1: {"dest": "s1", "destPort": 3},
                2: {"dest": "s2", "destPort": 3},
                3: {"dest": "s5", "destPort": 3}},
            "s5": {1: {"dest": "s2", "destPort": 4},
                2: {"dest": "s3", "destPort": 3},
                3: {"dest": "s4", "destPort": 3}}
        }

        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                "Topology after host link removal is different from expected\n%s\n\n%s" %
                (self.g.topo, expected_topo))


    def test_switch_remove(self):
        """ Test the switch removal method of the module. Method will remove some
        of the switches in the topology and make sure the shortest path is
        correct for the specific scenario.
        """
        print("\nSwitch remove test")

        # Make sure the link remove behaves as expected
        print("\tRemoving switch S2")
        self.g.remove_switch("s2")
        expected_topo = {
            "p1": {
                -1: {"dest": "s1", "destPort": 1}},
            "s1": {
                1: {"dest": "p1", "destPort": -1},
                3: {"dest": "s4", "destPort": 1}},
            "s3": {
                2: {"dest": "d1", "destPort": -1},
                3: {"dest": "s5", "destPort": 2}},
            "s4": {
                1: {"dest": "s1", "destPort": 3},
                3: {"dest": "s5", "destPort": 3}},
            "s5": {
                2: {"dest": "s3", "destPort": 3},
                3: {"dest": "s4", "destPort": 3}},
            "d1": {
                -1: {"dest": "s3", "destPort": 2}},
        }
        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                "Topology after switch removal is different from expected\n%s\n\n%s" %
                (self.g.topo, expected_topo))

        # Compute the shortest path and validate its correct
        e = ["p1", "s1", "s4", "s5", "s3", "d1"]
        res = self.g.shortest_path("p1", "d1")
        self.assertTrue(_paths_same(res, e), "Test failed, paths are different\n%s\n%s" %
                        (res, e))

        # Remove switch S4 and make sure no path exists
        print("\tRemoving switch S4")
        self.g.remove_switch("s4")
        expected_topo = {
            "p1": {
                -1: {"dest": "s1", "destPort": 1}},
            "s1": {
                1: {"dest": "p1", "destPort": -1}},
            "s3": {
                2: {"dest": "d1", "destPort": -1},
                3: {"dest": "s5", "destPort": 2}},
            "s5": {
                2: {"dest": "s3", "destPort": 3}},
            "d1": {
                -1: {"dest": "s3", "destPort": 2}},
        }
        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                    "Topology after switch removal is different from expected\n%s\n\n%s" %
                    (self.g.topo, expected_topo))

        # Compute the shortest path and validate its correct
        e = []
        res = self.g.shortest_path("p1", "d1")
        self.assertTrue(_paths_same(res, e), "Test failed, paths are different\n%s\n%s" %
                        (res, e))

        # Starting form the first topology delete link S4
        print("\tReseting topology")
        self.g.change_topo(self.topo)

        print("\tRemoving switch S4 (recreated topo)")
        self.g.remove_switch("s4")
        expected_topo = {
            "p1": {
                -1: {"dest": "s1", "destPort": 1}},
            "s1": {
                1: {"dest": "p1", "destPort": -1},
                2: {"dest": "s2", "destPort": 1}},
            "s2": {
                1: {"dest": "s1", "destPort": 2},
                2: {"dest": "s3", "destPort": 1},
                4: {"dest": "s5", "destPort": 1}},
            "s3": {
                1: {"dest": "s2", "destPort": 2},
                2: {"dest": "d1", "destPort": -1},
                3: {"dest": "s5", "destPort": 2}},
            "s5": {
                1: {"dest": "s2", "destPort": 4},
                2: {"dest": "s3", "destPort": 3}},
            "d1": {
                -1: {"dest": "s3", "destPort": 2}},
        }

        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                    "Topology after switch removal is different from expected\n%s\n\n%s" %
                    (self.g.topo, expected_topo))

        # Compute the shortest path and validate its correct
        e = ["p1", "s1", "s2", "s3", "d1"]
        res = self.g.shortest_path("p1", "d1")
        self.assertTrue(_paths_same(res, e), "Test failed, paths are different\n%s\n%s" %
                        (res, e))

        # Remove switch S5
        print("\tRemoving switch S5")
        self.g.remove_switch("s5")
        expected_topo = {
            "p1": {
                -1: {"dest": "s1", "destPort": 1}},
            "s1": {
                1: {"dest": "p1", "destPort": -1},
                2: {"dest": "s2", "destPort": 1}},
            "s2": {
                1: {"dest": "s1", "destPort": 2},
                2: {"dest": "s3", "destPort": 1}},
            "s3": {
                1: {"dest": "s2", "destPort": 2},
                2: {"dest": "d1", "destPort": -1}},
            "d1": {
                -1: {"dest": "s3", "destPort": 2}},
        }

        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                "Topology after switch removal is different from expected\n%s\n\n%s" %
                (self.g.topo, expected_topo))

        # Compute the shortest path and validate its correct
        e = ["p1", "s1", "s2", "s3", "d1"]
        res = self.g.shortest_path("p1", "d1")
        self.assertTrue(_paths_same(res, e), "Test failed, paths are different\n%s\n%s" %
                (res, e))


    def test_host_remove(self):
        """ Test the host remove method of the module """
        print("\nHost remove test")

        # Remove a host from the topo
        print("\tRemoving host p1")
        rem_res = self.g.remove_host("p1")
        self.assertEqual(rem_res, True, "Host remove failed %s != False" % rem_res)
        expected_topo = {
            "s1": {2: {"dest": "s2", "destPort": 1},
                3: {"dest": "s4", "destPort": 1}},
            "s2": {1: {"dest": "s1", "destPort": 2},
                2: {"dest": "s3", "destPort": 1},
                3: {"dest": "s4", "destPort": 2},
                4: {"dest": "s5", "destPort": 1}},
            "s3": {1: {"dest": "s2", "destPort": 2},
                3: {"dest": "s5", "destPort": 2},
                2: {"dest": "d1", "destPort": -1}},
            "s4": {1: {"dest": "s1", "destPort": 3},
                2: {"dest": "s2", "destPort": 3},
                3: {"dest": "s5", "destPort": 3}},
            "s5": {1: {"dest": "s2", "destPort": 4},
                2: {"dest": "s3", "destPort": 3},
                3: {"dest": "s4", "destPort": 3}},
            "d1": {-1: {"dest": "s3", "destPort": 2}}
        }

        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                "Topology after host removal is different from expected\n%s\n\n%s" %
                (self.g.topo, expected_topo))


        # Remove an inexistent host
        print("\tRemoving inexistent host (k1)")
        rem_res = self.g.remove_host("k1")
        self.assertEqual(rem_res, False, "Inexistent host remove failed %s != False" % rem_res)
        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                "Topology after inexistent host removal changed\n%s\n\n%s" %
                (self.g.topo, expected_topo))


        # Remove a switch as a host (should not change anything)
        print("\tRemoving swith as host (s2)")
        rem_res = self.g.remove_host("s2")
        self.assertEqual(rem_res, False, "Switch as host remove failed %s != False" % rem_res)
        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                "Topology after switch as host removal changed\n%s\n\n%s" %
                (self.g.topo, expected_topo))


        # Remove another host
        print("\tRemoving host d1")
        rem_res = self.g.remove_host("d1")
        self.assertEqual(rem_res, True, "Host remove failed %s != True" % rem_res)
        expected_topo = {
            "s1": {2: {"dest": "s2", "destPort": 1},
                3: {"dest": "s4", "destPort": 1}},
            "s2": {1: {"dest": "s1", "destPort": 2},
                2: {"dest": "s3", "destPort": 1},
                3: {"dest": "s4", "destPort": 2},
                4: {"dest": "s5", "destPort": 1}},
            "s3": {1: {"dest": "s2", "destPort": 2},
                3: {"dest": "s5", "destPort": 2}},
            "s4": {1: {"dest": "s1", "destPort": 3},
                2: {"dest": "s2", "destPort": 3},
                3: {"dest": "s5", "destPort": 3}},
            "s5": {1: {"dest": "s2", "destPort": 4},
                2: {"dest": "s3", "destPort": 3},
                3: {"dest": "s4", "destPort": 3}}
        }

        self.assertTrue(_topo_same(self.g.topo, expected_topo),
                "Topology after host removal is different from expected\n%s\n\n%s" %
                (self.g.topo, expected_topo))


    def test_cost_update(self):
        """ Test that the default cost is applied on initiation and addition of a link
        and that the change cost method sucesfully modifies the cost of the topo link
        in both directions.
        """
        t = {
            "s1": {
                1: {"dest": "s2", "destPort": 1}},
            "s2": {
                1: {"dest": "s1", "destPort": 1}},
        }

        print("\nChecking cost init and update")

        # Make sure the cost is set to default if not specified in initiation topo obj
        g = Graph(t)
        g.add_link("s2", "s3", 2, 1)
        g.add_link("s3", "s2", 1, 2)
        for src_id,src_val in g.topo.iteritems():
            for port_id,port_val in src_val.iteritems():
                self.assertEqual(port_val["cost"], 100,
                    "Topo init from obj cost set on omission is incorrect")

        # Make sure that if cost specified on init its not overwritten
        t["s1"][1]["cost"] = 50
        t["s2"][1]["cost"] = 50
        g = Graph(t)
        for src_id,src_val in g.topo.iteritems():
            for port_id,port_val in src_val.iteritems():
                self.assertEqual(port_val["cost"], 50,
                    "Topo init should not overide cost if specified")

        # Verify that changing cost changes in both directions
        g.change_cost("s1", "s2", 1, 1, cost=2500)
        self.assertEqual(g.topo["s1"][1]["cost"], 2500, "Forward link cost not updated")
        self.assertEqual(g.topo["s2"][1]["cost"], 2500, "Reverse link cost not updated")

        # Verify that not specifying cost on change cost call sets to default
        g.change_cost("s1", "s2", 1, 1)
        self.assertEqual(g.topo["s1"][1]["cost"], 100,
                "Forward link cost omission not setting cost to default")
        self.assertEqual(g.topo["s2"][1]["cost"], 100,
                "Reverse link cost ommision not setting cost to default")


    def test_speed_update(self):
        """ Test that the default speed is applied on initiation and addition of a link
        and that the change speed method sucesfully modifies the speed of the port.
        """
        t = {
            "s1": {
                1: {"dest": "s2", "destPort": 1}},
            "s2": {
                1: {"dest": "s1", "destPort": 1}},
        }

        print("\nChecking speed init and update")

        # Make sure the speed is set to default if not specified in initiation topo obj
        g = Graph(t)
        g.add_link("s2", "s3", 2, 1)
        g.add_link("s3", "s2", 1, 2)
        for src_id,src_val in g.topo.iteritems():
            for port_id,port_val in src_val.iteritems():
                self.assertEqual(port_val["speed"], 0,
                    "Topo init from obj speed on omission is incorrect")

        # Make sure that if speed specified on init its not overwritten
        t["s1"][1]["speed"] = 50
        t["s2"][1]["speed"] = 50
        g = Graph(t)
        for src_id,src_val in g.topo.iteritems():
            for port_id,port_val in src_val.iteritems():
                self.assertEqual(port_val["speed"], 50,
                    "Topo init should not overide speed if specified")

        # Check that the update speed works correctly
        g.update_port_info("s1", 1, speed=1000000)
        g.update_port_info("s2", 1, speed=900000)
        self.assertEqual(g.topo["s1"][1]["speed"], 1000000, "Speed was not updated")
        self.assertEqual(g.topo["s2"][1]["speed"], 900000, "Speed was not updated")

        # Check that the get port info works correctly
        p_info = g.get_port_info("s1", 1)
        self.assertEqual(p_info["speed"], 1000000, "Get port info didn't retrieve correct info")
        p_info = g.get_port_info("s2", 1)
        self.assertEqual(p_info["speed"], 900000, "Get port info didn't retrieve correct info")


    def test_port_update(self):
        """ Test that the default stat counts are added to the topo object on initiation
        with omission of dict objects and that updating the port info works as expected.
        """
        t = {
            "s1": {
                1: {"dest": "s2", "destPort": 1}},
            "s2": {
                1: {"dest": "s1", "destPort": 1}},
        }

        print("\nChecking stat counts init and update")

        # Make sure the stats are not added to the link on creation
        g = Graph(t)
        g.add_link("s2", "s3", 2, 1)
        g.add_link("s3", "s2", 1, 2)
        for src_id,src_val in g.topo.iteritems():
            for port_id,port_val in src_val.iteritems():
                self.assertTrue("poll_stats" not in port_val,
                    "Topo init from obj poll stats should not be added by default")
                self.assertTrue("total_stats" not in port_val,
                    "Topo init from obj total stats should not be added by default")

        # Make sure the update gets applied to the correct count
        g.update_port_info("s1", 1, tx_packets=1000)
        g.update_port_info("s1", 1, rx_packets=900, is_total=False)
        self.assertEqual(g.topo["s1"][1]["total_stats"]["tx_packets"], 1000,
                "Update was not applied to correct position")
        self.assertTrue("rx_packets" not in g.topo["s1"][1]["total_stats"],
                "Update should not have set total stats rx_packets")
        self.assertEqual(g.topo["s1"][1]["poll_stats"]["rx_packets"], 900,
                "Update was not applied to correct position")
        self.assertTrue("tx_packets" not in g.topo["s1"][1]["poll_stats"],
                "Update should not have set poll stats tx_packets")

        # Check that the get port info works correctly
        p_info = g.get_port_info("s1", 1)
        self.assertEqual(p_info["total_stats"]["tx_packets"], 1000,
                "Get port info didn't retrieve correct info")
        self.assertEqual(p_info["poll_stats"]["rx_packets"], 900,
                "Get port info didn't retrieve correct info")


    def test_fixed_speed(self):
        """ Test that applying a fixed speed to a port prevents it from being updatable
        and that calling change topo with a speed for a fixed speed port will not default
        to the ports fixed speed. Omitting the speed for change topo with a fixed speed
        topo port should also set the ports speed to the fixed value.
        """
        t = {
            "s1": {
                1: {"dest": "s2", "destPort": 1}},
            "s2": {
                1: {"dest": "s1", "destPort": 1}}
        }

        fixed_speed = {
            "s1": {1: 200000000},   # S1 to S2 200Mbits fixed speed
            "s2": {2: 500000000}    # S2 to S3 500Mbits fixed speed
        }

        print("\nChecking fixed speed behaivour")

        # Make sure the fixed speed ports are initiated to the fixed speed value
        g = Graph()
        g.fixed_speed = fixed_speed
        g.change_topo(t)
        for src_id,src_val in g.topo.iteritems():
            for port_id,port_val in src_val.iteritems():
                if src_id in fixed_speed and port_id in fixed_speed[src_id]:
                    self.assertEqual(port_val["speed"], fixed_speed[src_id][port_id],
                        "Topo init from obj speed on omission is incorrect")
                else:
                    self.assertEqual(port_val["speed"], 0,
                        "Topo init from obj speed on omission is incorrect")

        # Add another link (fixed speed s2 to s3) and make sure fixed speed is init
        # correctly
        g.add_link("s2", "s3", 2, 1)
        g.add_link("s3", "s2", 1, 2)
        for src_id,src_val in g.topo.iteritems():
            for port_id,port_val in src_val.iteritems():
                if src_id in fixed_speed and port_id in fixed_speed[src_id]:
                    self.assertEqual(port_val["speed"], fixed_speed[src_id][port_id],
                        "Topo add link fixed speed port is incorrect")
                else:
                    self.assertEqual(port_val["speed"], 0,
                        "Topo add link port speed is incorrect")

        # Check that the fixed speed ports can't be modified
        for src_id,src_val in g.topo.iteritems():
            for port_id,port_val in src_val.iteritems():
                g.update_port_info(src_id, port_id, speed=1000000000)

        for src_id,src_val in g.topo.iteritems():
            for port_id,port_val in src_val.iteritems():
                if src_id in fixed_speed and port_id in fixed_speed[src_id]:
                    self.assertEqual(port_val["speed"], fixed_speed[src_id][port_id],
                        "Topo update speed fixed port should not change!")
                else:
                    self.assertEqual(port_val["speed"], 1000000000,
                        "Topo update speed non fixed port should change!")

        # Ensure that fixed speed ports default to their fixed value when changing topo with speed
        # specified
        for src_id,src_val in t.iteritems():
            for port_id,port_val in src_val.iteritems():
                t[src_id][port_id]["speed"] = 5000000000
        g.change_topo(t)

        for src_id,src_val in g.topo.iteritems():
            for port_id,port_val in src_val.iteritems():
                if src_id in fixed_speed and port_id in fixed_speed[src_id]:
                    self.assertEqual(port_val["speed"], fixed_speed[src_id][port_id],
                        "Topo change fixed speed port should default to fixed value!")
                else:
                    self.assertEqual(port_val["speed"], 5000000000,
                        "Topo change port should use specified speed value!")


# ----- EXTRA HELPER METHODS ------ #


def _paths_same(check, expected):
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


def _topo_same(check, expected):
    """ Check if two topology objects are the same. Topology object have the
    same format as ``Topology`` from the dijkstra_te.py module.

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
            if (not p_val["dest"] == expected[s_id][p_id]["dest"] or
                    not p_val["destPort"] == expected[s_id][p_id]["destPort"]):
                return False

    return True


# ----- Main method runner of unittest ----- #


if __name__ == "__main__":
    unittest.main()
