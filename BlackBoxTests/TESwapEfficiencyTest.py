#!/usr/bin/python

# -----------------------------------------------------------------
#
# Black-box test that checks behaivour of controller with a simulated
# network when performing traffic engineering. The test implements the
# scenarios outlined in the "TE Swap Efficiency Test" read me
# Docs/TESwapEfficiencyTest.md. This test uses the FirstSol TE optimisation
# method with candidate reverse sort flag of False (candidates sorted in
# ascending order) and TE threshold of 90%.
#
# Test uses the topology module: Netowkrs/TETestTopo.py
#
# Run tests using command:
#   python -m TESwapEfficiencyTest
# -----------------------------------------------------------------


from TETestBase import TETestBase


class BlackBoxTETest(TETestBase):
    # Define the topology we want to execute the tests on
    TOPO_MOD = "Networks.TETestTopo"

    # Define the time to execute each iperf stream for the tests
    iperf_stream_time = 5

    def test_case_01(self):
        print("Testing scenario 1 (h1-h3 150M | h2-h4 120M)")
        self.SCENARIO = {
            "send": [
                {"src_host": "h1", "dest_host": "h3", "rate": "150M", "delay": 0},
                {"src_host": "h2", "dest_host": "h4", "rate": "120M", "delay": 0},
            ],
            "receive": [
                "h3", "h4"
            ],
            "default_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")]
            },
            "expected_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "4"), ("s4", "2"), ("s2", "2"), ("s3", "3")]
            },
            "stream_time": self.iperf_stream_time
        }

        # Change the topology attributes before starting and generate the host ip dict
        print("\tConstraining topology links")
        link_info = self.topo.linkInfo("s1", "s2")
        link_info["bw"] = 200
        self.topo.setlinkInfo("s1", "s2", link_info)

        # Write the port desc file contents used for the test case
        with open("port_desc_unittest.csv", "w") as f:
            f.write("dpid,port,speed\n")
            f.write("1,3,200000000\n")
            f.write("2,1,200000000\n")

        # Execute the unit-test scenario
        self.run_scenario()

    def test_case_02(self):
        print("Testing scenario 2 (h1-h3 150M | h2-h4 120M)")
        self.SCENARIO = {
            "send": [
                {"src_host": "h1", "dest_host": "h3", "rate": "150M", "delay": 0},
                {"src_host": "h2", "dest_host": "h4", "rate": "120M", "delay": 0}
            ],
            "receive": [
                "h3", "h4"
            ],
            "default_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")]
            },
            "expected_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "4"), ("s4", "2"), ("s2", "4"), ("s5", "2"), ("s3", "3")]
            },
            "stream_time": self.iperf_stream_time
        }

        # Change the topology attributes before starting and generate the host ip dict
        print("\tConstraining topology links")
        link_info = self.topo.linkInfo("s1", "s2")
        link_info["bw"] = 200
        self.topo.setlinkInfo("s1", "s2", link_info)
        link_info = self.topo.linkInfo("s2", "s3")
        link_info["bw"] = 200
        self.topo.setlinkInfo("s2", "s3", link_info)

        # Write the port desc file contents used for the test case
        with open("port_desc_unittest.csv", "w") as f:
            f.write("dpid,port,speed\n")
            f.write("1,3,200000000\n")
            f.write("2,1,200000000\n")
            f.write("2,2,200000000\n")
            f.write("3,1,200000000\n")

        # Execute the unit-test scenario
        self.run_scenario()

    def test_case_03(self):
        print("scenario 3 (h1-h3 150M | h2-h4 120M)")
        self.SCENARIO = {
            "send": [
                {"src_host": "h1", "dest_host": "h3", "rate": "150M", "delay": 0},
                {"src_host": "h2", "dest_host": "h4", "rate": "120M", "delay": 0}
            ],
            "receive": [
                "h3", "h4"
            ],
            "default_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")]
            },
            "expected_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "4"), ("s4", "2"), ("s2", "2"), ("s3", "3")]
            },
            "stream_time": self.iperf_stream_time
        }

        # Change the topology attributes before starting and generate the host ip dict
        print("\tConstraining topology links")
        link_info = self.topo.linkInfo("s1", "s2")
        link_info["bw"] = 200
        self.topo.setlinkInfo("s1", "s2", link_info)
        link_info = self.topo.linkInfo("s2", "s3")
        link_info["bw"] = 200
        self.topo.setlinkInfo("s2", "s3", link_info)
        link_info = self.topo.linkInfo("s5", "s3")
        link_info["bw"] = 100
        self.topo.setlinkInfo("s5", "s3", link_info)

        # Write the port desc file contents used for the test case
        with open("port_desc_unittest.csv", "w") as f:
            f.write("dpid,port,speed\n")
            f.write("1,3,200000000\n")
            f.write("2,1,200000000\n")
            f.write("2,2,200000000\n")
            f.write("3,1,200000000\n")
            f.write("5,2,100000000\n")
            f.write("3,4,100000000\n")

        # Execute the unit-test scenario
        self.run_scenario()

    def test_case_04(self):
        print("Testing scenario 4 (h1-h3 150M | h2-h4 120M)")
        self.SCENARIO = {
            "send": [
                {"src_host": "h1", "dest_host": "h3", "rate": "150M", "delay": 0},
                {"src_host": "h2", "dest_host": "h4", "rate": "120M", "delay": 0}
            ],
            "receive": [
                "h3", "h4"
            ],
            "default_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")]
            },
            "expected_path": {
                ("h1", "h3"): [("s1", "4"), ("s4", "2"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "4"), ("s4", "2"), ("s2", "4"), ("s5", "2"), ("s3", "3")]
            },
            "stream_time": self.iperf_stream_time
        }

        # Change the topology attributes before starting and generate the host ip dict
        print("\tConstraining topology links")
        link_info = self.topo.linkInfo("s1", "s2")
        link_info["bw"] = 100
        self.topo.setlinkInfo("s1", "s2", link_info)
        link_info = self.topo.linkInfo("s2", "s3")
        link_info["bw"] = 200
        self.topo.setlinkInfo("s2", "s3", link_info)

        # Write the port desc file contents used for the test case
        with open("port_desc_unittest.csv", "w") as f:
            f.write("dpid,port,speed\n")
            f.write("1,3,100000000\n")
            f.write("2,1,100000000\n")
            f.write("2,2,200000000\n")
            f.write("3,1,200000000\n")

        # Execute the unit-test scenario
        self.run_scenario()

    def test_case_05(self):
        print("Testing scenario 5 (h1-h3 150M | h2-h4 120M)")
        self.SCENARIO = {
            "send": [
                {"src_host": "h1", "dest_host": "h3", "rate": "150M", "delay": 0},
                {"src_host": "h2", "dest_host": "h4", "rate": "120M", "delay": 0}
            ],
            "receive": [
                "h3", "h4"
            ],
            "default_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")]
            },
            "expected_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "4"), ("s5", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "4"), ("s4", "2"), ("s2", "4"), ("s5", "2"), ("s3", "3")]
            },
            "stream_time": self.iperf_stream_time
        }

        # Change the topology attributes before starting and generate the host ip dict
        print("\tConstraining topology links")
        link_info = self.topo.linkInfo("s1", "s2")
        link_info["bw"] = 200
        self.topo.setlinkInfo("s1", "s2", link_info)
        link_info = self.topo.linkInfo("s2", "s3")
        link_info["bw"] = 100
        self.topo.setlinkInfo("s2", "s3", link_info)

        # Write the port desc file contents used for the test case
        with open("port_desc_unittest.csv", "w") as f:
            f.write("dpid,port,speed\n")
            f.write("1,3,200000000\n")
            f.write("2,1,200000000\n")
            f.write("2,2,100000000\n")
            f.write("3,1,100000000\n")

        # Execute the unit-test scenario
        self.run_scenario()

    def test_case_06(self):
        print("Testing scenario 6 (h1-h3 150M | h2-h4 120M)")
        self.SCENARIO = {
            "send": [
                {"src_host": "h1", "dest_host": "h3", "rate": "150M", "delay": 0},
                {"src_host": "h2", "dest_host": "h4", "rate": "120M", "delay": 0}
            ],
            "receive": [
                "h3", "h4"
            ],
            "default_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")]
            },
            "expected_path": {
                ("h1", "h3"): [("s1", "4"), ("s4", "2"), ("s2", "4"), ("s5", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "4"), ("s4", "2"), ("s2", "4"), ("s5", "2"), ("s3", "3")]
            },
            "stream_time": self.iperf_stream_time
        }

        # Change the topology attributes before starting and generate the host ip dict
        print("\tConstraining topology links")
        link_info = self.topo.linkInfo("s1", "s2")
        link_info["bw"] = 100
        self.topo.setlinkInfo("s1", "s2", link_info)
        link_info = self.topo.linkInfo("s2", "s3")
        link_info["bw"] = 100
        self.topo.setlinkInfo("s2", "s3", link_info)

        # Write the port desc file contents used for the test case
        with open("port_desc_unittest.csv", "w") as f:
            f.write("dpid,port,speed\n")
            f.write("1,3,100000000\n")
            f.write("2,1,100000000\n")
            f.write("2,2,100000000\n")
            f.write("3,1,100000000\n")

        # Execute the unit-test scenario
        self.run_scenario()

    def test_case_07(self):
        print("Testing scenario 7 (h1-h3 150M)")
        self.SCENARIO = {
            "send": [
                {"src_host": "h1", "dest_host": "h3", "rate": "150M", "delay": 0}
            ],
            "receive": [
                "h3", "h4"
            ],
            "default_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")]
            },
            "expected_path": {
                ("h1", "h3"): [("s1", "4"), ("s4", "2"), ("s2", "4"), ("s5", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")]
            },
            "stream_time": self.iperf_stream_time
        }

        # Change the topology attributes before starting and generate the host ip dict
        print("\tConstraining topology links")
        link_info = self.topo.linkInfo("s1", "s2")
        link_info["bw"] = 100
        self.topo.setlinkInfo("s1", "s2", link_info)
        link_info = self.topo.linkInfo("s2", "s3")
        link_info["bw"] = 100
        self.topo.setlinkInfo("s2", "s3", link_info)

        # Write the port desc file contents used for the test case
        with open("port_desc_unittest.csv", "w") as f:
            f.write("dpid,port,speed\n")
            f.write("1,3,100000000\n")
            f.write("2,1,100000000\n")
            f.write("2,2,100000000\n")
            f.write("3,1,100000000\n")

        # Execute the unit-test scenario
        self.run_scenario()

    def test_case_08(self):
        print("Testing scenario 8 (h1-h3 150M | h4-h2 120M)")
        self.SCENARIO = {
            "send": [
                {"src_host": "h1", "dest_host": "h3", "rate": "150M", "delay": 0},
                {"src_host": "h4", "dest_host": "h2", "rate": "120M", "delay": 0}
            ],
            "receive": [
                "h3", "h2"
            ],
            "default_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h4", "h2"): [("s3", "1"), ("s2", "1"), ("s1", "2")]
            },
            "expected_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h4", "h2"): [("s3", "1"), ("s2", "1"), ("s1", "2")]
            },
            "stream_time": self.iperf_stream_time
        }

        # Change the topology attributes before starting and generate the host ip dict
        print("\tConstraining topology links")
        link_info = self.topo.linkInfo("s1", "s2")
        link_info["bw"] = 200
        self.topo.setlinkInfo("s1", "s2", link_info)
        link_info = self.topo.linkInfo("s2", "s3")
        link_info["bw"] = 200
        self.topo.setlinkInfo("s2", "s3", link_info)

        # Write the port desc file contents used for the test case
        with open("port_desc_unittest.csv", "w") as f:
            f.write("dpid,port,speed\n")
            f.write("1,3,200000000\n")
            f.write("2,1,200000000\n")
            f.write("2,2,200000000\n")
            f.write("3,1,200000000\n")

        # Execute the unit-test scenario
        self.run_scenario()

    def test_case_09(self):
        print("Testing scenario 9 (h1-h3 150M | h4-h2 120M)")
        self.SCENARIO = {
            "send": [
                {"src_host": "h1", "dest_host": "h3", "rate": "150M", "delay": 0},
                {"src_host": "h4", "dest_host": "h2", "rate": "120M", "delay": 0}
            ],
            "receive": [
                "h3", "h2"
            ],
            "default_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h4", "h2"): [("s3", "1"), ("s2", "1"), ("s1", "2")]
            },
            "expected_path": {
                ("h1", "h3"): [("s1", "4"), ("s4", "2"), ("s2", "4"), ("s5", "2"), ("s3", "2")],
                ("h4", "h2"): [("s3", "4"), ("s5", "1"), ("s2", "3"), ("s4", "1"), ("s1", "2")]
            },
            "stream_time": self.iperf_stream_time
        }

        # Change the topology attributes before starting and generate the host ip dict
        print("\tConstraining topology links")
        link_info = self.topo.linkInfo("s1", "s2")
        link_info["bw"] = 100
        self.topo.setlinkInfo("s1", "s2", link_info)
        link_info = self.topo.linkInfo("s2", "s3")
        link_info["bw"] = 100
        self.topo.setlinkInfo("s2", "s3", link_info)

        # Write the port desc file contents used for the test case
        with open("port_desc_unittest.csv", "w") as f:
            f.write("dpid,port,speed\n")
            f.write("1,3,100000000\n")
            f.write("2,1,100000000\n")
            f.write("2,2,100000000\n")
            f.write("3,1,100000000\n")

        # Execute the unit-test scenario
        self.run_scenario()

    def test_case_10(self):
        print("Testing scenario 10 (h1-h2 1G | h3-h4 1G)")
        self.SCENARIO = {
            "send": [
                {"src_host": "h1", "dest_host": "h2", "rate": "1000M", "delay": 0},
                {"src_host": "h3", "dest_host": "h4", "rate": "1000M", "delay": 0}
            ],
            "receive": [
                "h2", "h4"
            ],
            "default_path": {
                ("h1", "h2"): [("s1", "2")],
                ("h3", "h4"): [("s3", "3")]
            },
            "expected_path": {
                ("h1", "h2"): [("s1", "2")],
                ("h3", "h4"): [("s3", "3")]
            },
            "stream_time": self.iperf_stream_time
        }

        # Change the topology attributes before starting and generate the host ip dict
        print("\tConstraining topology links")
        link_info = self.topo.linkInfo("s1", "s2")
        link_info["bw"] = 100
        self.topo.setlinkInfo("s1", "s2", link_info)
        link_info = self.topo.linkInfo("s2", "s3")
        link_info["bw"] = 100
        self.topo.setlinkInfo("s2", "s3", link_info)

        # Write the port desc file contents used for the test case
        with open("port_desc_unittest.csv", "w") as f:
            f.write("dpid,port,speed\n")
            f.write("1,3,100000000\n")
            f.write("2,1,100000000\n")
            f.write("2,2,100000000\n")
            f.write("3,1,100000000\n")

        # Execute the unit-test scenario
        self.run_scenario()

    def test_case_11(self):
        print("Testing scenario 11 (h1-h3 150M | h2-h4 150M)")
        self.SCENARIO = {
            "send": [
                {"src_host": "h1", "dest_host": "h3", "rate": "150M", "delay": 0},
                {"src_host": "h2", "dest_host": "h4", "rate": "150M", "delay": 0}
            ],
            "receive": [
                "h3", "h4"
            ],
            "default_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")]
            },
            "expected_path": {
                ("h1", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")],
                ("h2", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")]
            },
            "stream_time": self.iperf_stream_time
        }

        # Change the topology attributes before starting and generate the host ip dict
        print("\tConstraining topology links")
        link_info = self.topo.linkInfo("h1", "s1")
        link_info["bw"] = 100
        self.topo.setlinkInfo("h1", "s1", link_info)
        link_info = self.topo.linkInfo("h2", "s1")
        link_info["bw"] = 100
        self.topo.setlinkInfo("h2", "s1", link_info)
        link_info = self.topo.linkInfo("h3", "s3")
        link_info["bw"] = 100
        self.topo.setlinkInfo("h3", "s3", link_info)
        link_info = self.topo.linkInfo("h4", "s3")
        link_info["bw"] = 100
        self.topo.setlinkInfo("h4", "s3", link_info)

        # Write the port desc file contents used for the test case
        with open("port_desc_unittest.csv", "w") as f:
            f.write("dpid,port,speed\n")
            f.write("1,1,100000000\n")
            f.write("1,2,100000000\n")
            f.write("3,2,100000000\n")
            f.write("3,3,100000000\n")

        # Execute the unit-test scenario
        self.run_scenario()

    def test_case_12(self):
        print("Testing scenario 12 (h1-h4 150M | h2-h3 150M)")
        self.SCENARIO = {
            "send": [
                {"src_host": "h1", "dest_host": "h4", "rate": "150M", "delay": 0},
                {"src_host": "h2", "dest_host": "h3", "rate": "150M", "delay": 0}
            ],
            "receive": [
                "h3", "h4"
            ],
            "default_path": {
                ("h1", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")],
                ("h2", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")]
            },
            "expected_path": {
                ("h1", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")],
                ("h2", "h3"): [("s1", "3"), ("s2", "2"), ("s3", "2")]
            },
            "stream_time": self.iperf_stream_time
        }

        # Change the topology attributes before starting and generate the host ip dict
        print("\tConstraining topology links")
        link_info = self.topo.linkInfo("h1", "s1")
        link_info["bw"] = 100
        self.topo.setlinkInfo("h1", "s1", link_info)
        link_info = self.topo.linkInfo("h2", "s1")
        link_info["bw"] = 100
        self.topo.setlinkInfo("h2", "s1", link_info)
        link_info = self.topo.linkInfo("h3", "s3")
        link_info["bw"] = 100
        self.topo.setlinkInfo("h3", "s3", link_info)
        link_info = self.topo.linkInfo("h4", "s3")
        link_info["bw"] = 100
        self.topo.setlinkInfo("h4", "s3", link_info)

        # Write the port desc file contents used for the test case
        with open("port_desc_unittest.csv", "w") as f:
            f.write("dpid,port,speed\n")
            f.write("1,1,100000000\n")
            f.write("1,2,100000000\n")
            f.write("3,2,100000000\n")
            f.write("3,3,100000000\n")

        # Execute the unit-test scenario
        self.run_scenario()
