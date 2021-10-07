#!/usr/bin/python

""" Emulation framework entry script that initiates and runs a data-plane
link failure test on a topology with a specific controller.

Usage:
    sudo ./Emulate.py --topo <topology> --controller <ctrl_name> --failure \
        <fail> --sw_ctrl_map [map] --ctrl_options [ctrl_opts]

    <topology> - Topology module to use for the emulation
    <ctrl_name> - Name of the controller to use. See 'controllers.yaml' for
        list of supported names. Note, start command of YAML file is ignored
    <fail> - Path to failure scearnio YAML file that defines experiment
    [map] - Switch-controller map. Using this attribute will initiate multiple
        controllers and instances (as per the map details).
    [ctrl_opts] - Netem attributes to apply to the controll channel to modify
        characterstics of switch-to-controller communication.
    [log_level] - Optional emulator logging level (debug, info, warning,
        error, critical). Defaults to critical.
    [ctrl_log_level] - Optional controller logging level (debug, info, warning,
        error, critical). Defaults to critical.
"""

import os
import time
import subprocess
import importlib
import traceback
from argparse import ArgumentParser

# Mininet imports
from mininet.log import setLogLevel, lg

# File parsing and state matching check
import json
import yaml
from tools.StateMatches import StateWaitTimeoutException, wait_match

# Shared method imports
from emulator_base import load_ctrls, get_ctrl_names, get_ctrl_module
from emulator_base import path_to_import_notation
from emulator_base import signal_subprocess
from emulator_base import prepare_check_dict
from emulator_base import ControllerManager
from emulator_base import running_instance_check


# Dictionary that contains information about available controllers.
# XXX NOTE: The 'start_command' attribute is used to find the module for the
# required controller. We assume that the module is located as the second
# item in the list (index 1). All other attributes of the command are ignored!
CONTROLLERS = {}

# Dictionary that contains information relating to the failure scenario that
# needs to be emulated (links that will fail).
FAILURE = {}
""" Format:
{"failure_name": <name>, "failed_links": [(<switch_pair>), ...],
    "logger_location": {
        <ctrl>: {
            "primary": {
                "switch": <prim_sw>,
                "interface": <prim_intf>,
                "port": <prim_port>
            },
            "secondary": { same format as primary ... }
        },
        ...
    }
}

<switch_pair> represents a '(<sw>, <sw>)' tupple describing the link that needs
to fail. <ctrl> represents the name of the controller while 'primary' and
'secondary' the location of the packet tracers which log packets to detect the
link failure time and recovery time (switch over).

For multi-link failure scenarios, <prim_sw>, <prim_intf> and <prim_port> is
defined as a list of switches, interfaces and ports for each failed link. When
failing the first link, the first elements of the lists are used. For the next
link the second and so on.
"""

# Running topology module information
topo = None
# Controller manager instance
controllers = None
# Running network instance
net = None


def load_failure(path):
    """ Load a failure scenario from a YAML file and validate it. A exception will
    be thrown if the file can't be loaded or is invalid

    Args:
        path (str): Path to failure YAML file
    """
    global FAILURE
    with open(path, "r") as stream:
        FAILURE = yaml.safe_load(stream)

def validate_failure(controller_name):
    """ Validate that the failure scenario we have loaded is valid. Method
    makes sure that `:mod:attr:(FAILURE)` specifies switches and interfaces that
    exist in `:mod:attr:(topo)` and also if we have a multi-link scenario we
    have the correct number of logger locations.

    Args:
        controller_name (str): Name of the controller to use

    Raises:
        Exception: Failure file is invalid
    """
    # Iterate through the failed links, split them into tuples and validate them
    failed_links = []
    for link in FAILURE["failed_links"]:
        split = link.split("-")
        failed_link = (split[0], split[1])

        # Validate the failed link exists in the topo
        if (net.get(failed_link[0]) is None or
                net.get(failed_link[1]) is None or
                (failed_link not in topo.iterLinks() and
                    (split[1], split[0]) not in topo.iterLinks())):
            raise Exception("Invalid failure scenario. Failed link %s dosen't exist" %
                    str(failed_link))

        failed_links.append(failed_link)
    FAILURE["failed_links"] = failed_links

    # Validate the controller exists in the logger location, otherwise raise an exception
    if controller_name not in FAILURE["logger_location"]:
        raise Exception("Invalid failure scenario. Controller %s logger location not found!"
                % controller_name)

    FAILURE["logger_location"] = FAILURE["logger_location"][controller_name]

    # Check the primary and secondary logger exists
    primary = FAILURE["logger_location"]["primary"]
    secondary = FAILURE["logger_location"]["secondary"]

    # Check if we have a multi link failure
    num_links_failed = len(FAILURE["failed_links"])
    if (num_links_failed > 1):
        # Make sure we have the correct number of logger info for each failed link
        if (
            isinstance(primary["switch"], list) == False or
            isinstance(primary["interface"], list) == False or
            isinstance(primary["port"], list) == False or
            isinstance(secondary["switch"], list) == False or
            isinstance(secondary["interface"], list) == False or
            isinstance(secondary["port"], list) == False
        ):
            raise Exception("Invalid failure scenario. Multi link failure needs list type"
                            " logger info!")

        if (
            (not num_links_failed == len(primary["switch"])) or
            (not num_links_failed == len(primary["interface"])) or
            (not num_links_failed == len(primary["port"])) or
            (not num_links_failed == len(secondary["switch"])) or
            (not num_links_failed == len(secondary["interface"])) or
            (not num_links_failed == len(secondary["port"]))
        ):
            raise Exception("Invalid failure scenario. Need to provide logger info for each"
                            " failed link!")

        # Validate each individual logger position
        for i in range(num_links_failed):
            validate_logger_location(primary["switch"][i], secondary["switch"][i],
                    primary["interface"][i], secondary["interface"][i])
    else:
        # Validate the single link failure
        validate_logger_location(primary["switch"], secondary["switch"],
                    primary["interface"], secondary["interface"])

        # Convert the single element attributes to lists
        FAILURE["logger_location"]["primary"]["switch"] = [primary["switch"]]
        FAILURE["logger_location"]["primary"]["interface"] = [primary["interface"]]
        FAILURE["logger_location"]["primary"]["port"] = [primary["port"]]
        FAILURE["logger_location"]["secondary"]["switch"] = [secondary["switch"]]
        FAILURE["logger_location"]["secondary"]["interface"] = [secondary["interface"]]
        FAILURE["logger_location"]["secondary"]["port"] = [secondary["port"]]

def validate_logger_location (first_sw, second_sw, first_intf, second_intf):
    """ Validate the logger locationd details. Method will check if the switches and
    interfaces where we will place the loggers exist in our network

    Args:
        first_sw (str): Name of switch where we will have the primary logger.
        second_sw (str): Name of switch where we will have the secondary logger.
        first_intf (str): Interface name of the primary logger.
        second_intf (str): Interface name of the secondary logger.

    Raises:
        Exception: Invalid logger location (see message for details).
    """
    prim_sw = net.get(first_sw)
    sec_sw = net.get(second_sw)

    if prim_sw is None:
        raise Exception("Invalid Scenario: Primary logger %s invalid"
                            % first_sw)
    if sec_sw is None:
        raise Exception("Invalid Scenario: Secondary logger %s invalid"
                            % second_sw)

    if first_intf not in prim_sw.intfNames():
        raise Exception("Invalid Scenario: Primary logger %s intf %s invalid"
                            % (first_sw, first_intf))
    if second_intf not in sec_sw.intfNames():
        raise Exception("Invalid Scenario: Secondary logger %s intf %s invalid"
                            % (second_sw, second_intf))

def cleanup():
    """ Clean used resources by terminating running network, controller or host
    process instances. Method should be called on an error or when the emulation
    has finished.
    """
    global net
    global controllers

    # Tell the controller manager to stop any running instances
    if controllers is not None:
        controllers.stop()
        controllers = None

    if net is not None:
        # Stop the host LLDP packet generators
        for h in topo.hosts_attr(net):
            host = net.get(h[0])
            signal_subprocess(host, "LLDP/lldp_host.py", kill=True)

        prober = net.get(topo.hosts()[0])
        signal_subprocess(prober, "bash pktgen.sh", kill=True)

        net.stop()
        net = None

def run(controller_name):
    """ Start and run the emulation experiment to record data-plane failure
    recovery. All failure recovery results are printed to standard out as a
    single line with format 'recovery time(ms), packet loss, l1 pktgen_seq,
    l1 pktgen_time, l2 pktgen_seq, l2 pktgen_time, failure number'. L1 referes
    to the first logger which detects when the failure occurs, while L2 referes
    to the second logger which detects the swap-over time (fix time). The
    failure number is only displayed if the scenario is a multi-link failure.
    Failure number represents the link (from the scenario) that was failed.

    If an error occurs, a single line is printed to standard output in format
    'ERROR!,<msg>'. Extra information such as stack traces, task lists and
    flow/group table dumps are outputed using the mininet logger (written to
    error out) with a critical logging level.

    Note:
        To ensure consistency, the tests wait for the switches to be in a
        specific state before starting the emulation experiment. The expected
        state is defined in the 'WaitState' directory by a JSON file with the
        name '<controller name>.<topology name>.json'.

        The primary logger will tell the emulator that it has finished flusing
        it's packet trace file contents by writting 'DONE' to the file
        'logger.done'.

        If the emulator detects a negative recovery time, the temporary packet
        trace collected for the emulation are moved to the 'BAD_TRACE/' folder.
        A negative recovery time is caused by packet re-ordering.

    Args:
        controller_name (str): Name of controller to use
    """
    # Validate the failure scenario against the topology
    validate_failure(controller_name)

    # Initiate the prober for the scenario
    # NOTE XXX: The prober is the first host in the hosts list of the topo
    prober = net.get(topo.hosts()[0])
    prober.cmd("modprobe pktgen")
    prober.cmd("bash pktgen.sh &> /dev/null &")

    # Tell the hosts to start generating LLDP packets
    time.sleep(1)
    for h in topo.hosts_attr(net):
        host = net.get(h[0])
        host.cmd("LLDP/lldp_host.py %s %s &" % (h[1], h[2]))

    # Wait for the switches to start-up with the correct state
    try:
        check_dict = {}
        with open("WaitState/%s.%s.json" % (controller_name, topo.name), "r") as data_file:
            check_dict = json.load(data_file)
        prepare_check_dict(check_dict)
        wait_match(check_dict, timeout=30)
    except StateWaitTimeoutException:
        # If we time out write an error message, dump the flows and clean-up
        print("ERROR!,Network state took too long to stabilise, exiting ...")
        lg.critical("%s\n" % subprocess.check_output(["ps", "-aux"]))

        # Dump the flow rules (and groups if not reactive controller)
        topo.dump_tables(dump_groups=False if controller_name == "reactive" else True)

        # Cleanup and exit
        cleanup()
        return

    # Start the primary and secondary loggers
    for fail_num in range(len(FAILURE["failed_links"])):
        # Start the loggers to stabalise
        prim_sw = FAILURE["logger_location"]["primary"]["switch"][fail_num]
        sec_sw = FAILURE["logger_location"]["secondary"]["switch"][fail_num]
        prim_intf = FAILURE["logger_location"]["primary"]["interface"][fail_num]
        sec_intf = FAILURE["logger_location"]["secondary"]["interface"][fail_num]

        prim_sw = net.get(prim_sw)
        sec_sw = net.get(sec_sw)
        prim_sw.cmd("LibtraceLogger/logger int:%s pcap:prim.pcap &" % prim_intf)
        sec_sw.cmd("LibtraceLogger/logger int:%s pcap:sec.pcap 10 &"  % sec_intf)

        # Clear the logger done file (or create it) and wait 2 seconds for things
        # to stabalise
        open("logger.done", "w").close()
        time.sleep(2)

        # Take the link down using the mininet API
        net.configLinkStatus(FAILURE["failed_links"][fail_num][0],
                FAILURE["failed_links"][fail_num][1], "down")
        time.sleep(1)

        # Stop the primary logger and wait up to 10 secs for prim logger to
        # indicate it has finished
        signal_subprocess(prim_sw, "Libtrace/logger int:%s*" % prim_intf)

        for wait in range(1, 10):
            with open("logger.done", "r") as f:
                if f.readline().rstrip() == "DONE":
                    break
            time.sleep(1)

        # Calculate the recovery time and output it to the console
        rec_time = subprocess.check_output(["LibtraceLogger/processPKTGEN",
                                "prim.pcap", "sec.pcap"])

        if (len(FAILURE["failed_links"]) > 1):
            print("%s,%d" % (rec_time, (fail_num+1)))
        else:
            print(rec_time)

        # Check if we have received a negative result
        rec_time_split = rec_time.rstrip().split(",")
        keep_trace = False
        if len(rec_time_split) == 6:
            if float(rec_time_split[0]) < 0 or float(rec_time_split[1]) < 0:
                keep_trace = True
                break

    # Cleanup
    cleanup()
    os.remove("logger.done")

    if (keep_trace == False):
        os.remove("prim.pcap")
        os.remove("sec.pcap")
    else:
        # Keep the trace files by moving to the BAD TRACE folder and suffixing
        # the controller name and topology to the trace file name
        file_suffix = "%s.%s.pcap" % (controller_name, topo.name)
        os.rename("prim.pcap", "BAD_TRACE/prim.%s" % file_suffix)
        os.rename("sec.pcap", "BAD_TRACE/sec.%s" % file_suffix)


if __name__ == "__main__":
    # Load the controller config and retrieve the script arguments
    CONTROLLERS = load_ctrls("controllers.yaml")
    parser = ArgumentParser("Mininet emulator: data-plane recovery time")
    parser.add_argument("--topo", required=True, type=str,
        help="Topology module to use for emulation")
    parser.add_argument("--controller", required=True, type=str,
        help="Controller to use for emulation (%s)"
                    % get_ctrl_names(CONTROLLERS))
    parser.add_argument("--failure", required=True, type=str,
        help="Failure scenario YAML file")
    parser.add_argument("--sw_ctrl_map", type=str, default=None,
        help="Switch-controller JSON map file (use multiple controllers)")
    parser.add_argument("--ctrl_options", type=str, default=None,
        help="netem options to apply to control channel (i.e. delay 10ms)")
    parser.add_argument("--log_level", type=str, default="critical",
        help="Emulator log level (debug, info, warning, error, critical)")
    parser.add_argument("--ctrl_log_level", type=str, default="critical",
        help="Controller log level (debug, info, warning, error, critical)")
    args = parser.parse_args()

    # Load the topology module, failure scenario and validate attributes/run
    topoMod = path_to_import_notation(args.topo)
    topo = importlib.import_module(topoMod)
    topo = topo.NetTopo()

    controller_name = args.controller.lower()
    if controller_name not in CONTROLLERS:
        lg.critical("Invalid controller name received!\n")
        exit()

    load_failure(args.failure)
    if "usable_on_topo" in FAILURE:
        if topo.name not in FAILURE["usable_on_topo"]:
            exit()

    if args.ctrl_options:
        ctrl_channel_options = args.ctrl_options.lower()
    else:
        ctrl_channel_options = None

    sw_ctrl_map = None
    if args.sw_ctrl_map is not None and os.path.isfile(args.sw_ctrl_map):
        sw_ctrl_map = args.sw_ctrl_map

    # Check if there any running instances of mininet, or the controller
    running_instance_check()
    setLogLevel(args.log_level)
    try:
        # Initiate controller manager, start emulation and run experiment
        controllers = ControllerManager(map=sw_ctrl_map,
                        ctrl_channel_opts=ctrl_channel_options,
                        log_level=args.ctrl_log_level)
        controllers.set_ctrl_config("application", "optimise_protection", False)
        controllers.set_ctrl_config("stats", "collect", False)
        controllers.set_ctrl_cmd_module(get_ctrl_module(CONTROLLERS,
                                            controller_name))
        net = controllers.start(topo)
        run(controller_name)
    except:
        # Show the error and exit execution
        print("ERROR!,Exception occured while running emulation")
        lg.critical("%s\n" % traceback.format_exc())
        cleanup()
