#!/usr/bin/python

# -----------------------------------------------------------------
#
# Same black-box test as ```TESwapEfficiencyTest.py```, but uses the
# CSPFRecomp TE optimiation method with a candidate reverse sort flag set
# to false. For more info about the test and the expected result, refer
# to the Docs/TESwapEfficiencyTest.md read me "CSPFRecomp TE Optimisation
# Method Expected REsults" section.
#
# -----------------------------------------------------------------


from TESwapEfficiencyTest import BlackBoxTETest


class BlackBoxTETestCSPF(BlackBoxTETest):
    # Override default controller config to use CSPF recomputation
    # as the TE optimisaiton method
    CONFIG_FILE = """[DEFAULT]
ofp_listen_host = "127.0.0.1"

[application]
optimise_protection = False
static_port_desc = 'port_desc_unittest.csv'

[stats]
collect = True
interval = 1
collect_port = True
out_port = False

[te]
utilisation_threshold = 0.90
te_consolidate_time = 1
opti_method = CSPFRecomp
candidate_sort_rev = False

[multi_ctrl]
start_com = False
"""

    def test_case_03(self):
        # XXX: For CSPF, no path change occurs (other methods leave S2-S3
        # as a congested port and require two swaps).
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
                ("h2", "h4"): [("s1", "3"), ("s2", "2"), ("s3", "3")]
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
