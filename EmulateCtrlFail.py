#!/usr/bin/python

""" Emulation framework entry script that inities and runs ctrl failure test.
The framework will start a topology with multiple controllers and instances,
stops specific controller instances and records / reports time it takes for the
other instances in the are to detect the failure and switch over to a new
master controller.

Usage:
    sudo ./EmulateCtrlFail.py --topo <topology> --sw_ctrl_map <map> \
        --scenario <scen> --ctrl_options [ctrl_opt] \
        --config_file [config_file]

    <topology> - topology module to use for emulation
    <map> - Switch to controller mapping file that describes domains in topo
    <scen> - Failure scneario to apply to the controllers
    [ctrl_opt] - Optional netem attributes to apply to the controll channel
    [log_level] - Optional emulator logging level (debug, info, warning,
        error, critical). Defaults to critical
    [ctrl_log_level] - Optional controller logging level (debug, info, warning,
        error, critical). Defaults to critical.
    [config_file] - Optional configuration file to use for emulator. Specifies
        start command and other config attributes. Defaults to
        "EmulatorConfigs/config.CtrlFail.yaml".
"""

import os
import time
import subprocess
import threading
import importlib
import traceback
from argparse import ArgumentParser

# Parse configuration files
import json
import yaml

# Mininet imports
from mininet.log import setLogLevel, info, lg

# Shared method imports
from emulator_base import path_to_import_notation
from emulator_base import signal_subprocess
from emulator_base import ControllerManager
from emulator_base import running_instance_check

# Import the local controller base to use static method to compute GID
from TopoDiscoveryController import TopoDiscoveryController


# Running topology module information
topo = None
# Running mininet network instances
net = None
# Controller manager instance
controllers = None
# OFP monitor instances
mon = None

# Capture OFP packet command
#
# XXX: The command uses tsarh to capture all openflow v1.3 traffic on the
# loopback interface that is either a group-mod, role requeset or role reply
# message. The command will print a CSV style line for each capture packet
# with fields: <timestamp>,<src_ip>,<dst_ip>,<ofp_type>,<ofp_groupmod_id>,
# <ofp_role>. If any fields are not present in the current patcket (i.e.
# role for group mod messages), an emtpy column is written.
#
OFP_PACK_CAP_CMD_TOKEN = ["tshark", "-nli", "lo", "-Y",
"openflow_v4 and (openflow_v4.type == 0x0F or openflow_v4.type == 0x18)",
"-T", "fields", "-e", "frame.time_epoch", "-e", "ip.src_host", "-e",
"ip.dst_host", "-e", "openflow_v4.type", "-e", "openflow_v4.groupmod.group_id",
"-e", "openflow_v4.groupmod.command", "-e", "openflow_v4.role_request.role",
"-E", "separator=,"]


class OFP_Monitor():
    """ Class that monitors OpenFlow packets to observe path instalation and
    controller role changes. The monitor process occurs on a seperate thread
    that uses signals to indicate when the application has started to monitor
    OFP packets and also when the mintor has terminated. The minotir will parse
    output from a subprocess and generate a time-line object
    """

    def __init__(self):
        self.__monitor_thread = None
        self.__initiated = threading.Event()
        self.__pkt_proc = None
        self.__stop = False
        self.__finished = threading.Event()

        # Inactive wait attributes
        self.__inactive = threading.Event()
        self.__inactive_ofp_type = None
        self.__inactive_timer = None
        self.__inactive_wait_time = -1

        # Timeline of monitor
        self.timeline = []

    def start(self):
        """ Initiate a new monitor thread and start monitoring OFP """
        # Clear the stop flag and signals
        self.__stop = False
        self.__initiated.clear()
        self.__finished.clear()
        self.__inactive.clear()

        # Creat the monitor thread and start it
        self.__monitor_thread = threading.Thread(target=self.__worker)
        self.__monitor_thread.start()

    def stop(self):
        """ Stop the monitor thread by killing the capture process """
        if self.__stop == True or self.__pkt_proc is None:
            self.__finished.set()
            return

        # Cancel any active timers, stop tshark packet capture and flag stop
        if self.__inactive_timer is not None:
            self.__inactive_timer.cancel()
            self.__inactive_timer = None
        if self.__inactive_wait_time > -1:
            self.__inactive_wait_time = -1
            self.__inactive_ofp_type = None

        self.__stop = True
        self.__pkt_proc.kill()

    def __worker(self):
        """ Thread worker that starts the openflow minitor and processes ouptup
        from the thread. The worker iterates while the minitor subprocess is
        running.
        """
        self.__pkt_proc = subprocess.Popen(OFP_PACK_CAP_CMD_TOKEN,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        # While the monitor is still running
        while not self.__stop:
            # Read a line from standard out
            line = self.__pkt_proc.stdout.readline()
            if line is None:
                break

            # Strip the line and if empty do not process
            line = line.strip()
            if line == "":
                continue

            if "Capturing on" in line:
                # Line indicates start of catpure, generate signal
                self.__initiated.set()
            elif "," in line:
                # Output is a packet info line. Tokenize and process
                tok = line.split(",")
                ofp_type = int(tok[3])

                # Check if we need to handle a inactive timer request
                if self.__inactive_wait_time > -1:
                    if (self.__inactive_ofp_type is None or
                            self.__inactive_ofp_type == ofp_type):
                        # We have observed the OFP type to start the inactive
                        # timer, have already observed the type or no type
                        # required for inactive timer.
                        self.__inactive_ofp_type = None
                        self.__reset_inactive_timer()

                if ofp_type == 15:
                    ofp_group_mod_action = int(tok[5])

                    if ofp_group_mod_action == 0:
                        ofp_group_mod_action = "add"
                    elif ofp_group_mod_action == 1:
                        ofp_group_mod_action = "modify"
                    elif ofp_group_mod_action == 2:
                        ofp_group_mod_action = "delete"
                    else:
                        ofp_group_mod_action = "unkown"

                    # Add the group mod to the timeline
                    self.timeline.append({
                        "frame_ts": float(tok[0]),
                        "src_ip": tok[1],
                        "dst_ip": tok[2],
                        "type": "group_mod",
                        "gid": int(tok[4]),
                        "action": ofp_group_mod_action
                    })
                elif ofp_type == 24:
                    # Add the role change to the timeline
                    ofp_role = int(tok[6], 16)

                    if ofp_role == 0:
                        ofp_role = "no_change"
                    elif ofp_role == 1:
                        role = "equal"
                    elif ofp_role == 2:
                        role = "master"
                    elif ofp_role == 3:
                        role = "slave"
                    else:
                        role = "unkown"

                    self.timeline.append({
                        "frame_ts": float(tok[0]),
                        "src_ip": tok[1],
                        "dst_ip": tok[2],
                        "type": "role_change",
                        "role": role
                    })

        # Wait for packet process to terminate and signal monitor has stopped
        self.__pkt_proc.wait()
        self.__pkt_proc = None
        self.__finished.set()

    def __reset_inactive_timer(self):
        """ Reset or start the inactive timer to indicate that an OFP event
        was observed (monitor not inactive). If the timer is not reset, the
        timer `cls:attr:(__inactive_timer)` will trigger after the specified
        inactivity time `:cls:attr:(__inactive_wait_time)`.
        """
        if self.__inactive_timer is not None:
            self.__inactive_timer.cancel()

        self.__inactive_timer = threading.Timer(self.__inactive_wait_time,
                self.__mon_timeline_inactive)
        self.__inactive_timer.start()

    def __mon_timeline_inactive(self):
        """ Callback triggered on inactive timer execution. Set the event to
        show monitor was inactive for specified time.
        """
        self.__inactive_timer = None
        self.__inactive_wait_time = -1
        self.__inactive_ofp_type = None
        self.__inactive.set()

    def wait_start(self, timeout=60):
        """ Wait up to `timeout` seconds for the OFP monitor to start capturing
        packets. If the `:cls:attr:(__initiated)` event is not set before the
        timeout elapses, the method prints a error message and returns.

        Args:
            timeout (int): Wait up to n seconds for initiated event
        """
        if not self.__initiated.wait(timeout):
            lg.critical("Monitor failed to start ...\n")

    def wait_inactive(self, inactive, ofp_type=None, timeout=360):
        """ Wait for the OFP monitor to become inactive (no longer records
        events) for `inactive` seconds. If `ofp_type` is not None, the wait
        mechanism will use a two stage system were the monitor first waits for
        a OFP event of type `ofp_type` before waiting for inactivity. If the
        monitor does not become inactive within `timeout` seconds, the methods
        prints an error and stops. `timeout` should be set to a large value to
        account for a busy control channel and correctly group results.


        Args:
            inactive (int): Wait for the monitor to be inactive for n seconds
            ofp_type (int): Two stage wait mechanisn were the monitor starts
                the inactive wait process after observing a OFP event of this
                type. Defaults to None, do not wait for OFP event (just wait
                for inactivity).
            timeout (int): Wait up to n seconds for inactivity.

        Returns:
            bool: True if inactive wait triggered, false if timeout (error)
        """
        # Sanity check, if negative time don't start the timer
        if inactive < 0:
            lg.critical("Monitor wait inactive received -ve time!\n")
            return False

        # Update inactive wait attributes and start timer if we don't have to
        # wait for a OFP event to occur.
        self.__inactive_wait_time = inactive
        self.__inactive_ofp_type = ofp_type
        if self.__inactive_ofp_type is None:
            lg.info("Monitor inactive, no OFP type wait!\n")
            self.__reset_inactive_timer()

        # Wait up to time-out seconds for monitor inactivity
        timed_out = True
        for i in range(timeout):
            if self.__inactive.wait(1):
                timed_out = False
                break

        # If timeout before inactivity occured print error and return false
        if timed_out:
            lg.critical("Monitor inactive wait timed-out\n")
            return False

        # Everything is good
        return True

    def wait_stop(self, timeout=10):
        """ Wait up to `timeout` seconds for the OFP monitor to finish the
        capture packet process. If the `:cls:attr:(__finished)` event is not
        set before the timeout elapses, the method prints a wraning and simply
        returns.

        Args:
            timeout (int): Wait up to n seconds for initiated event
        """
        if not self.__finished.wait(timeout):
            lg.critical("Mintor has failed to stop ...\n")

    def get_first(self, ofp_type):
        """ Find and return the first occurance of the OFP action type from a
        list of type strings `ofp_type` in the timeline `:cls:attr:(timeline)`.

        Args:
            ofp_type (list of str): List of OFP actions trings to find in the
                timeline. If single string provided, automatic convert to list.
                For wildcard matching provide an empty list.

        Returns:
            dict: First occurance of action or None if types not in timeline.
        """
        # Convert single type string to a list
        if isinstance(ofp_type, str):
            ofp_type = [ofp_type]

        for obj in self.timeline:
            if not ofp_type or obj["type"] in ofp_type:
                return obj
        return None

    def get_all(self, ofp_type):
        """ Find and return all occurances of the OFP action type from a list
        of type strings `ofp_type` in the timeline `:cls:attr:(timeline)`.

        Args:
            ofp_type (list of str): List of OFP actions trings to find in the
                timeline. If single string provided, automatic convert to list.
                For wildcard matching provide an empty list.

        Returns:
            list of dict: List of occurances of the specified action types.
        """
        # Convert single type string to a list
        if isinstance(ofp_type, str):
            ofp_type = [ofp_type]

        res = []
        for obj in self.timeline:
            if not ofp_type or obj["type"] in ofp_type:
                res.append(obj)
        return res

    def timeline_size(self):
        """ Return the size of the monitor timeline `:cls:attr:(timeline)`.

        Returns:
            int: Number of items in the monitors timeline
        """
        return len(self.timeline)

    def clear_timeline(self):
        """ Clear all elements in the monitors timeline """
        self.timeline = []

    def contains(self, ofp_type):
        """ Check if the monitor timeline contains events of OFP action type
        `ofp_type`.

        Args:
            ofp_type (str): OFP action string to check for in timline

        Returns:
            bool: True if action exists in timeline and False otherwise.
        """
        for obj in self.timeline:
            if obj["type"] == ofp_type:
                return True
        return False

def load_scenario(file):
    """ Load a control-plane failure scenario from a YAML file `file`
    and return it.

    Args:
        file (str): Path to TE scenario YAML file.

    Returns:
        dict: TE scenario information dictionary
    """
    with open(file, "r") as stream:
        return yaml.safe_load(stream)

def validate_scenario(scen):
    """ Validate a failure scenario `scen`. Ensure that the scenario specifies
    the existing controller names and instances and that the actions
    of the scenario are correct. The method validates the controller name and
    inst_id by using the controller manager `:cls:attr:(controllers)`
    ```exists``` method. Scenario actions are validated by calling the method
    ``__validate_scenario_action`` which generates an exception if the action
    contains invalid controller instances or fields.

    Args:
        scen (dict): TE scenario information dictionary

    Raises:
        Exception: Scenario file is invalid
    """
    scen = scen["scenario"]

    # Go through the scenario timeline and ensure all fields are specified
    for s in scen:
        # XXX: We can just remove this validation check, why should we always
        # put delay 0 in the file?
        if "delay" not in s:
            raise Exception("Invalid scenario: Item %s missing 'delay'")
        if "actions" not in s:
            raise Exception("Invalid scenario: Item %s missing 'action' field")
        if "expected" not in s:
            raise Exception("Invalid scenario: Item missing 'expected' field")

        actions = s["actions"]
        # Go through and validate controller and inst IDs
        for action in actions:
            __validate_scenario_action(action)

        # TODO: Validate the expected elements

def __validate_scenario_action(action):
    """ Check if the action of a scenario is valid and the controller instance
    exists.

    Args:
        action (dict): Action dictionary entry to validate.

    Raises:
        Exception: On invalid action config
    """
    # Make sure all required fields are present
    if "ctrl" not in action or "inst_id" not in action or "op" not in action:
        raise Exception("Invalid scenario: Action missing fields")

    # Check if the controller instance is valid
    inst_id = None
    if int(action["inst_id"]) != 0:
        inst_id = action["inst_id"]
    if not controllers.exists(action["ctrl"], inst_id):
        raise Exception("Invalid scenario: Ctrl %s inst_id %d dosen't exist"
                            % (action["ctrl"], inst_id))

    # Check the operation
    if action["op"] not in ["fail", "start"]:
        raise Exception("Invalid Scenario: Unknown operation %s" % action["op"])

    # Check wait is valid int (if specified)
    if "wait" in action:
        try:
            wait = float(action["wait"])
            if wait < 0:
                raise Exception("Invalid scenario: Wait time must be >= 0")
        except ValueError:
            raise Exception("Invalid scenario: Wait time %s not a number" %
                                action["wait"])

def cleanup():
    """ Cleanup any used resources by terminating any running network,
    controller or host process that may be running. This method should be
    called on an error or when the emulation has finished
    """
    global net
    global controllers
    global mon

    # Stop the OFP monitor
    if mon is not None:
        mon.stop()
        mon.wait_stop()
        mon = None

    # Tell the controller manager to stop any running instances
    if controllers is not None:
        controllers.stop()
        controllers = None

    # Stop the host LLDP packet generators
    if net is not None:
        for h in topo.hosts_attr(net):
            host = net.get(h[0])
            signal_subprocess(host, "LLDP/lldp_host.py", kill=True)

        net.stop()
        net = None

def gen_inst_name(ctrl, inst_id=None):
    """ Generate a string representation of a instance name.
    Args:
        ctrl (obj): ID of the controller to generate name of
        inst_id (obj): ID of the instance to generate name of

    Returns:
        str: Name of the instance in format '<ctrl>.<inst_id>' or '<ctrl>' if
            `inst_id` is not not specified.
    """
    if inst_id is None:
        return ctrl
    return "%s.%s" % (ctrl, inst_id)

def run():
    """ TODO: Write method implementation and documentation"""
    global mon

    # Validate the failure scenario
    validate_scenario(SCENARIO)

    # Tell the hosts to start generating LLDP packets
    time.sleep(1)
    for h in topo.hosts_attr(net):
        host = net.get(h[0])
        host.cmd("LLDP/lldp_host.py %s %s 0 &" % (h[1], h[2]))

    # Initiate monitor and wait for topology to stabilise.
    mon = OFP_Monitor()
    mon.start()
    mon.wait_start()
    mon.wait_inactive(10, ofp_type=15)
    mon.stop()
    mon.wait_stop()

    # Dictionary that holds scenarios that failed validation (events that were
    # not exepected were observed in the timeline)
    failed_validation = {}

    # Go through the scenario timeline and perform required operations
    info("Running scenario timeline\n")
    for scen_i,scen in enumerate(SCENARIO["scenario"]):
        scen_start_time = time.time()
        delay = float(scen["delay"])
        if delay > 0:
            info("Delaying operations for %s seconds\n" % delay)
            time.sleep(delay)

        # Clear the monitor timeline and start monitoring OFP requests
        info("Starting OFP monitor\n")
        mon.clear_timeline()
        mon.start()
        mon.wait_start()

        # Dict to store processed results and event type (validation)
        proc_res = {}
        event_types = {
            "local_leader_elect": False,    # Did a leader election occur
            "local_path_recomp": False,     # Did a local path recomp occur
            "root_path_recomp": False,      # Did a root path recomp occur
        }

        # Execute the actions of the scenario item
        for action in scen["actions"]:
            ctrl = action["ctrl"]
            inst_id = int(action["inst_id"])
            op = action["op"]
            if inst_id == 0:
                inst_id = None

            wait = 0
            if "wait" in action:
                wait = float(action["wait"])

            if wait > 0:
                info("Applying wait of %s before action\n" % wait)
                time.sleep(wait)

            if op == "fail":
                op_time = controllers.stop_ctrl(ctrl, inst_id)
                info("Stopped controller %s inst_id %s at time %s\n" % (ctrl,
                         inst_id, op_time))

                # Add the event details to the ordered timeline
                ctrl_name = gen_inst_name(ctrl, inst_id)
                if ctrl_name not in proc_res:
                    proc_res[ctrl_name] = []
                proc_res[ctrl_name].append((op_time, "action", "fail",
                                                ctrl_name))
            elif op == "start":
                op_time = controllers.restart_ctrl(ctrl, inst_id)
                info("Started controller %s inst_id %s\n" % (ctrl, inst_id))

                # Add the event details to the ordered timeline
                ctrl_name = gen_inst_name(ctrl, inst_id)
                if ctrl_name not in proc_res:
                    proc_res[ctrl_name] = []
                proc_res[ctrl_name].append((op_time, "action", "start",
                                                ctrl_name))

            print("%d,%s,%s,%s,%f" % (scen_i, ctrl, inst_id, op, op_time))

        # Wait for the monitor to become inactivity
        wait_ofpt = 24
        if (scen["expected"]["local_path_recomp"] or
                    scen["expected"]["root_path_recomp"]):
            wait_ofpt = 15

        wait_time = 5
        if "monitor_wait" in scen:
            wait_time = float(scen["monitor_wait"])
            info("Applying custom mon wait time of %s sec\n" % wait_time)

        wait_res = mon.wait_inactive(wait_time, ofp_type=wait_ofpt)

        # Stop the monitor
        info("Stoping OFP monitor\n")
        mon.stop()
        mon.wait_stop()

        # Monitor wait inactive timed out (something bad happened so print
        # error and stop experiment)
        if not wait_res:
            lg.critical("STOP INACTIVE\n")
            break

        # Collect OFP monitor events
        for t in mon.get_all([]):
            ctrl = controllers.get_cip_ctrl(t["src_ip"])

            if t["type"] == "group_mod":
                gid = int(t["gid"])
                pkey = TopoDiscoveryController.get_reverse_gid(gid)
                action = t["action"]
                diff = t["frame_ts"] - op_time

                # Check if path is inter-domain or intra-domain
                ctrl_src = controllers.get_host_ctrl(pkey[0])
                ctrl_dst = controllers.get_host_ctrl(pkey[1])
                inter_dom = False
                if ctrl_src != ctrl_dst:
                    inter_dom = True

                # Flag event types that occured for validation
                if inter_dom:
                    event_types["root_path_recomp"] = True
                else:
                    event_types["local_path_recomp"] = True

                # Clean pkey and add info to processed timeline
                pkey = "%s-%s" % pkey
                if ctrl not in proc_res:
                    proc_res[ctrl] = []
                proc_res[ctrl].append((t["frame_ts"], "event_ofp",
                            "group_mod", inter_dom, pkey, action))
            elif t["type"] == "role_change":
                role = t["role"]
                diff = t["frame_ts"] - op_time

                # Flag event types that occured for validation
                event_types["local_leader_elect"] = True

                # Add info to processed timeline
                if ctrl not in proc_res:
                    proc_res[ctrl] = []
                proc_res[ctrl].append((t["frame_ts"], "event_ofp",
                            "role_change", role))

        # Collect controller local events (from log files)
        for ctrl,inst_id in controllers.get_init_inst():
            log = controllers.get_inst_log(ctrl, inst_id)
            for line in log:
                tmp = line.split("XXXEMUL,")[1]
                tok = tmp.split(",")
                ts = float(tok[0])
                if ts < scen_start_time:
                    continue

                el = [ts, "event_local"]
                el.extend(tok[1:])

                # Add the event details to the ordered timeline
                ctrl_name = gen_inst_name(ctrl, inst_id)
                if ctrl_name not in proc_res:
                    proc_res[ctrl_name] = []
                proc_res[ctrl_name].append(tuple(el))

        # Process collected events and output results to console in CSV format
        print("-----")
        for ctrl,ctrl_d in sorted(proc_res.items(), key=lambda (x,y): y[0]):
            prev_time = 0

            # Sort the events of the instance in ascending order
            for ev in sorted(ctrl_d, key=lambda x:x[0]):
                # Compute the diff between the previous event (if exists)
                diff = 0
                if prev_time > 0:
                    diff = ev[0] - prev_time
                prev_time = ev[0]

                # Build the info string to output to the console
                str_info = None
                for tok in ev[1:]:
                    if str_info is None:
                        str_info = str(tok)
                    else:
                        str_info += (",%s" % tok)

                # Print the result item to console
                print("%d,%s,%f,%f,%s" % (scen_i, ctrl, ev[0], diff, str_info))
        print("-----")

        # Validate the scenario
        failure = False
        for key,flag in event_types.iteritems():
            if not scen["expected"][key] == flag:
                failure = True
                break
        if failure:
            failed_validation[scen_i] = {"observed": event_types,
                                            "expected": scen["expected"]}

    # Output the info for scenarios that failed validation
    if len(failed_validation) > 0:
        print("\n!!!! VALIDATION ERROR !!!!")
        for scen,scen_info in failed_validation.iteritems():
            print("Scenario %d" % scen)
            pprint_validation_dict(scen_info["observed"], "\tObserved ->")
            pprint_validation_dict(scen_info["expected"], "\tExpected ->")

    # Clean-up and exit
    cleanup()

def pprint_validation_dict(dict, label):
    print("%s Local Leader Elect: %s, Local Path: %s, Root Path: %s" % (label,
                dict["local_leader_elect"], dict["local_path_recomp"],
                dict["root_path_recomp"]))


if __name__ == "__main__":
    # Load the controller config and retrieve the script arguments
    parser = ArgumentParser("Mininet Control-Plane Failure Resilience Framework")
    parser.add_argument("--topo", required=True, type=str,
        help="Python topology module to use for emulation")
    parser.add_argument("--scenario", required=True, type=str,
        help="Failure scenario YAML file")
    parser.add_argument("--sw_ctrl_map", required=True, type=str,
        help="Switch-controller JSON map file")
    parser.add_argument("--ctrl_options", type=str, default=None,
        help="netem options to apply to control channel (i.e. delay 10ms)")
    parser.add_argument("--log_level", type=str, default="critical",
        help="Emulator log level (debug, info, warning, error, critical)")
    parser.add_argument("--ctrl_log_level", type=str, default="critical",
        help="Controller log level (debug, info, warning, error, critical)")
    parser.add_argument("--config_file", type=str,
        default="EmulatorConfigs/config.CtrlFail.yaml",
        help="Framework config file (specify start cmd and config attr)")
    args = parser.parse_args()

    # Dump the experiment configuration info
    lg.critical("Running experiment\n")
    lg.critical("Config  : %s\n" % args.config_file)
    lg.critical("Topo    : %s\n" % args.topo)
    lg.critical("Scen    : %s\n" % args.scenario)
    lg.critical("Map     : %s\n" % args.sw_ctrl_map)
    if args.ctrl_options is not None:
        lg.critical("Ctrl Opt: %s\n" % args.ctrl_options)
    lg.critical("~" * 40)
    lg.critical("\n")

    # Load the topology module, failure scenario and validate/proc attributes
    topoMod = path_to_import_notation(args.topo)
    topo = importlib.import_module(topoMod)
    topo = topo.NetTopo()

    SCENARIO = load_scenario(args.scenario)

    ctrl_channel_options = None
    if args.ctrl_options:
        ctrl_channel_options = args.ctrl_options.lower()

    # Check if there any running instances and configure log level
    running_instance_check()
    setLogLevel(args.log_level)
    try:
        # Initiate a new controller manager and run emulation experiment
        controllers = ControllerManager(map=args.sw_ctrl_map,
                        ctrl_channel_opts=ctrl_channel_options,
                        log_level=args.ctrl_log_level,
                        config_file=args.config_file)
        net = controllers.start(topo)
        run()
    except:
        # Show the erro, cleanup and exit the app
        lg.critical("ERROR!,Exception occured during emulation\n")
        lg.critical("%s\n" % traceback.format_exc())
        cleanup()
