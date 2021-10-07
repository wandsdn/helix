# Modify sys-path for imports as one directory up
import sys, os
sys.path.append(os.path.abspath(".."))
# -----------------------------------------------

import unittest
import importlib
import subprocess
import time

from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch

from tools.FindPortsUsed import find_changed_tuple


class TETestBase(unittest.TestCase):
    """ Base TE testing module. Contains helper methods which allow easier execution of tests. All
    TE tests should inherit this class.

    Note:
        This class contains a set-up and tear-down method that automatically initiates the
        required topology and stops it on completion of a test.

        Topology link attributes can be modified by using ```self.topo.linkInfo``` and
        ```self.topo.setLinkInfo```.

    Usage:
        Define required topology module for testing in `cls:attr:(TOPO_MOD)`
        Define scenario dictionary in `cls:attr:(SCENARIO)`
        Run scenario by calling ``run_scenario``

    Args:
        topo (Network.NetTopo): Mininet topology class used for tests
        net (mininet.net.Mininet): Mininet network instance
        controller (subprocess.Popen): Ryu controller sub process object
        sw (list of str): List of switches in the topology, generated dynamically on
            run scenario call.
        host_ip (dict): Hopst name to IP mapping
    """

    # CONTROLLER CONFIG FILE TO USE FOR TEST
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
opti_method = FirstSol
candidate_sort_rev = False

[multi_ctrl]
start_com = False
"""

    # CONTROLLER START COMMAND
    CNTRL_START_CMD = ["ryu-manager", "../ProactiveController.py",
        "--default-log-level", "100", "--config-file", "controller_unittest.conf"]

    """ Dict that contains the secnario information in the format:
        {
            "send" : [ {src_host: str, dest_host: str, rate: str, delay: int} ],
            "recieve": [ str of hosts used to recieve packets ],
            "default_path": {
                (host_src, host_dest): [(sw, port), ...]
            },
            "expected_path": {
                (host_src, host_dest): [(sw, port), ...]
            },
            stream_time: int
        }

        The 'expected_path' and 'default_path' contain a list of path tuples that encode the
        switch and port used by traffic for the host pair path.
    """
    SCENARIO = {}

    # Arguments used for the unit-test
    controller = None
    topo = None
    net = None


    # --------------------- UNIT-TEST INIT AND STOP METHODS -------------------------- #


    def setUp(self):
        """ Prepare the tests by killing any running ryu and mininet instance and loading
        the required elements for the test.
        """
        print("\nChecking for running instances of mn and ryu")
        setLogLevel("critical")

        # XXX: THIS CHECK BREAKS RUNNING TESTS ONE AFTER EACH OTHER SO WE DISABLE IT FOR
        # NOW

        #mininet_instances_pid = ""
        #try:
        #     mininet_instances_pid = subprocess.check_output(["pgrep", "--full", "mininet"])
        #except subprocess.CalledProcessError as e:
        #    if not e.returncode == 1:
        #        print(e)
        #        exit()
        # Check if there are any running instances of mininet
        #if not mininet_instances_pid == "":
        #    print("A mininet instance is already running, trying to kill instance")

            # We have found the PID of the children processes we need to get
            # the PID of the parent thread, mininet wrapper to kill that
        #    PID_CHILD = mininet_instances_pid.splitlines()[0]
        #    PID_PARENT = subprocess.check_output(["ps", "-o", "ppid=", "-p", PID_CHILD]).strip()

            # Make sure we have a parent PID
        #    if (PID_PARENT == ""):
        #        print("Could not get PID of mininet parent to stop instance")
        #        print("Please manually close any mininet instance")
        #        exit()

        #    print("Killing mininet parent with PID %s" % PID_PARENT)
        #    subprocess.check_output(["kill", "-SIGTERM", PID_PARENT])
        #    print("Cleaning up mininet resources")
        #    subprocess.check_output(["mn", "-c"])

        # Check if there are any running ryu-instances that we need to kill before proceding
        ryu_instances_pid = ""
        try:
             ryu_instances_pid = subprocess.check_output(["pgrep", "--full", "ryu-manager"])
        except subprocess.CalledProcessError as e:
            if not e.returncode == 1:
                print(e)
                exit()

        if not ryu_instances_pid == "":
            print("A ryu-instance is already running, trying to kill instance")

            for pid in ryu_instances_pid.splitlines():
                subprocess.check_output(["kill", "-SIGTERM", pid])
                print("Killed process with PID %s" % pid)

        # Load the topology and write the config files
        self.topo = importlib.import_module(self.TOPO_MOD)
        self.topo = self.topo.NetTopo()
        print("Loaded topology for unit-test")

        # Write controller configuration files
        print("Writing controller config file")
        with open("controller_unittest.conf", "w") as f:
            f.write(self.CONFIG_FILE)


    def tearDown(self):
        """ When a test finishes clean up and kill running topology and controller instances """
        print("Stopping controller and ryu instances")

        # Stop the controller if running
        if self.controller is not None:
            self.controller.terminate()
            self.controller.wait()
            self.controller = None

        # Stop the network and any running instances
        if self.net is not None:
            # TODO: MAYBE WE SHOULD KILL IPERF STREAMS
            for h in self.topo.hosts_attr(self.net):
                host = self.net.get(h[0])
                self.signal_subprocess(host, "LLDP/lldp_host.py", kill=True)

            # Stopped mininet
            self.net.stop()
            self.net = None

        print("Removing unit test configuration files")
        os.remove("controller_unittest.conf")
        os.remove("port_desc_unittest.csv")


    # ----------------------- HELPER METHODS ---------------------------


    def signal_subprocess(self, host, command, kill=False):
        """ Send a signal to a process process running on a mininet `host`. Method will
        search for the PID of the process by full name. If `kill` is set to False we will
        send a SIGINT, if true a SIGTERM is sent instead. If multiple processes match the
        specified name then the signal will be sent to all of them.

        Args:
            host (mininet.node): Host where the process is executing
            command (str): Full name of command to kill.
        """
        for pid in host.cmd("pgrep --full '%s'" % command).splitlines():
            if kill == True:
                host.cmd("kill -SIGTERM %s" % pid)
            else:
                host.cmd("kill -SIGINT %s" % pid)


    def _start_topo(self):
        """ Start the loaded mininet topology and controller """
        print("\tStarting controller and topology")
        self.controller = subprocess.Popen(self.CNTRL_START_CMD)
        self.net = Mininet(
            topo=self.topo,
            controller=RemoteController("c1", ip="127.0.0.1"),
            switch=OVSSwitch,
            autoSetMacs=True)

        self.net.start()
        if getattr(self.topo, "on_start", None):
            self.topo.on_start(self.net)

        time.sleep(1)
        print("\tStarting LLDP host discovery")
        for h in self.topo.hosts_attr(self.net):
            host = self.net.get(h[0])
            host.cmd("../LLDP/lldp_host.py %s %s &" % (h[1], h[2]))

        # Wait 2 seconds for topo to stabilise
        time.sleep(2)


    def _gen_iperf_send_script(self, host, dest_addr, bandwidth, time, delay_time=0):
        """ Generate an iperf UDP send script that sends traffic to a specific host.
        The method creates a new file of the format `host`.sh. This script will indicate
        when it has finished by writing 'DONE' to the file `host`.done. This file is
        created and cleared automatically on start of the script to prevent errors.

        Args:
            host (str): Name of the host, used for file names (format: "<host_name>.sh")
            dest_addr (str): Address we are sending iperf traffic to
            bandwidth (str): Bandwidth of iperf UDP traffic we are sending
            time (int): Ammount of time in seconds we are sending traffic for
            delay_time (int): Delay to start iperf in seconds. Defaults to 0, no delay.
        """
        with open("%s.sh" % host, "w") as f:
            f.write("echo -ne > %s.done;\n" % host)
            f.write("sleep %s;\n" % delay_time)
            f.write("iperf -c %s -u -b %s -t %s;\n" % (dest_addr, bandwidth, time))
            f.write("echo 'DONE' > %s.done\n" % host)


    def _check_path(self, send, rec, path):
        """ Check that a particular path from host `send` to host `rec` is the same
        as the expected path `path`. Method will assert that the retrieved path is
        the same as the exepected path.

        Args:
            send (str): Host to generate iperf traffic on path (source of path)
            rec (str): Host that recives iperf traffic to (destination of path)
            expected_path (list of tuple): Expected path for source destination pair
        """
        # Start the receive host
        host_rec = self.net.get(rec)
        host_rec.cmd("iperf -s -u &")

        # Generate and start the send host
        host_send = self.net.get(send)
        dest_addr = self.host_ip[rec]
        self._gen_iperf_send_script(send, dest_addr, "1m", 4)

        host_send.cmd("bash %s.sh &" % send)
        time.sleep(1)
        used_path = find_changed_tuple(self.sw, 1)

        # Wait for the iperf stream to finish
        while True:
            with open("%s.done" % send, "r") as f:
                if f.readline().rstrip() == "DONE":
                    break
            time.sleep(1)

        # Remove the gen script and stop the recive host
        self.signal_subprocess(host_rec, "iperf -s", kill=True)
        os.remove("%s.done" % send)
        os.remove("%s.sh" % send)

        # Assert that the path is correct
        self.assertEqual(len(path), len(used_path), "Path length different for %s-%s: got %s" %
                                                                        (send, rec, used_path))
        for sw in used_path:
            self.assertIn(sw, path, "Node %s dosen't exist in path %s-%s: %s" %
                                                                        (sw, send, rec, path))

    def run_scenario(self):
        """ Run the scenario defined in `cls:attr(SCENARIO)` checking paths """

        # Generate the switch and host IP attributes
        self.sw = self.topo.switches()
        self.host_ip = {}
        for host in self.topo.hosts():
            self.host_ip[host] = self.topo.nodeInfo(host)["ip"].split("/")[0]

        # Start the topology
        self._start_topo()
        print("\tTopology has started, checking default path is correct")

        # Check the default path for the topo is as expected
        for host_pair,path in self.SCENARIO["default_path"].iteritems():
            self._check_path(host_pair[0], host_pair[1], path)

        # Run the actuall scenario unit-test streams
        print("\tRunning unit-test case")
        for rec in self.SCENARIO["receive"]:
            host = self.net.get(rec)
            host.cmd("iperf -s -u &")

        stream_time = self.SCENARIO["stream_time"]
        for s in self.SCENARIO["send"]:
            send = s["src_host"]
            dest_addr = self.host_ip[s["dest_host"]]
            rate = s["rate"]
            delay = s["delay"]
            self._gen_iperf_send_script(send, dest_addr, rate, stream_time, delay_time=delay)

            host = self.net.get(send)
            host.cmd("bash %s.sh &" % send)

        # Wait for the iperf streams to finish and clean-up
        stream_done = []
        for i in range(len(self.SCENARIO["send"])):
            stream_done.append(False)

        time.sleep(1)

        while True:
            bool_all_done = True
            for i in range(len(self.SCENARIO["send"])):
                if stream_done[i] == False:
                    bool_all_done = False
                    host_name = self.SCENARIO["send"][i]["src_host"]
                    with open("%s.done" % host_name, "r") as f:
                        if f.readline().rstrip() == "DONE":
                            stream_done[i] = True

            if bool_all_done:
                break

            time.sleep(1)

        # Stop the recieve streams and remove send files
        for rec in self.SCENARIO["receive"]:
            host = self.net.get(rec)
            self.signal_subprocess(host, "iperf -s", kill=True)

        for s in self.SCENARIO["send"]:
            send = s["src_host"]
            os.remove("%s.done" % send)
            os.remove("%s.sh" % send)

        # Assert the path is correct (i.e. our controller swapped paths as expected)
        for host_pair,path in self.SCENARIO["expected_path"].iteritems():
            self._check_path(host_pair[0], host_pair[1], path)
