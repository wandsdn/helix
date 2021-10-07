#!/usr/bin/python

""" Emulation framework entry script that initiates and runs a Pktgen TE
swap-over performance test on a topology with a sepecific controller.

Usage:
    sudo ./EmulateTEPktgen.py --topo <topology> --controller <ctrl_name> \
        --scenario <scen> --sw_ctrl_map [map] --ctrl_options [ctrl_opts]

    <topology> - Topology module to use for the emulation
    <ctrl_name> - Name of the controller to use. See 'controllers_te.yaml' for
        list of supported names. Note, start command of YMAL file is ignored
    <scen> - Path to scenario YAML file that defines experiment behaivour
    [map] - Swith-controller map. Using this attribute will initiate multiple
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
import shutil
import importlib
import traceback
from argparse import ArgumentParser

# Mininet imports
from mininet.log import setLogLevel, info, lg

# Config file loading and switch state check
import json
import yaml
from tools.StateMatches import StateWaitTimeoutException, wait_match

# Shared method imports
from emulator_base import load_ctrls, get_ctrl_names, get_ctrl_module
from emulator_base import path_to_import_notation
from emulator_base import signal_subprocess
from emulator_base import signal_local_subprocess
from emulator_base import prepare_check_dict
from emulator_base import ControllerManager
from emulator_base import running_instance_check

# Imports from Iperf emulator (shared methods)
from EmulateTE import load_scenario
from EmulateTE import validate_scenario


# Dictionary that contains information about avaible controllers.
# XXX NOTE: The 'start_command' attribute is used to find the module for the
# required controller. We assume that the module is located as the second item
# in the list (index 1). All other attributes of the command are ignored!
CONTROLLERS = {}

# Template for the Pktgen script used to generate traffic
PKTGEN_SCRIPT_TMPL = """#!/bin/bash

# Number of CPUS
CPUS=`grep -c ^processor /proc/cpuinfo`

function pgset() {{
    local result

    echo $1 > $PGDEV

    result=`cat $PGDEV | fgrep "Result: OK:"`
    if [ "$result" = "" ]; then
        cat $PGDEV | fgrep Result:
    fi
}}

# Load the pktgen module
modprobe pktgen

# Clear all configured devices
for ((processor=0;processor<$CPUS;processor++)) do
    PGDEV=/proc/net/pktgen/kpktgend_$processor
    pgset "rem_device_all"
done

{conf_block}

# Start the stream
PGDEV=/proc/net/pktgen/pgctrl pgset "start"
"""

# Template for a Pktgen stream that intiates sending traffic to
# a particular destination with a specific rate.
PKTGEN_STREAM_TMPL = """PGDEV=/proc/net/pktgen/kpktgend_0
pgset 'add_device {eth_device}@0'
PGDEV=/proc/net/pktgen/{eth_device}@0

pgset 'count 0'
pgset 'flag QUEUE_MAP_CPU'
pgset 'clone_skb 0'
pgset 'frags 0'
pgset 'pkt_size 1024'
pgset 'rate {packet_rate}'
pgset 'dst {dest_ip}'
"""

# Dictionary that defines the TE optimisation test scenario that needs to be
# emulated (i.e. host send rates and times)
SCENARIO = {}
""" Format:
{"scenario_name": <name>, "usable_on_topo": [<topo_name>, ...], "scenario": {
    <ctrl>: {
        "send": [
            {
                "src_host": <src_host>, "dest_addr": <dest_addr>,
                "rate": <rate>, "delay": <delay>
            },
            ...
        ],
        "receive": [{"host": <dest_host>}, ...]
    }, ...}
}

<ctrl> represents the name of the controller the scenario applies to while the
'send' attribute defines the ammount of traffic (<rate>) a host (<src_host>) is
sending to a destination receiver (<dest_addr>). The 'receive' list defines all
the hosts that will act as iperf servers (receives).
"""

# Running topology module information
topo = None
# Controller manager instance
controller = None
# Running network instance
net = None


def cleanup():
    """ Clean used resources by terminating running network, controller and host
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
        # Stop the LLDP packet generators
        for h in topo.hosts_attr(net):
            host = net.get(h[0])
            signal_subprocess(host, "LLDP/lldp_host.py", kill=True)

        # Stop the TE packet performance loggers (receivers)
        info("Stopping recivers and senders\n")
        for i in range(len(SCENARIO["scenario"]["receive"])):
            r = SCENARIO["scenario"]["receive"][i]
            info("Stopping reciver %s\n" % r["host"])
            host = net.get(r["host"])
            signal_subprocess(host, "TEPerformanceLogger/logger")

        # Stop the pktgen script, cleanup and stop the network
        signal_local_subprocess("bash pktgen_run.sh", kill=True)
        clean_out = subprocess.check_output("bash pktrem.sh", shell=True)
        net.stop()
        net = None

def run(controller_name):
    """ Start and run the emulation experiment to record TE swap-over
    performance by looking at sustained congestion/loss rates when links are
    constrained and sufficient traffic is placed on them to generate congestion
    loss. This emulation test uses Pktgen to generate a stream of packets and
    libtrace loggers to capture and process data. The behaivour of the
    experiment is similar to 'EmulateTE.py' which uses Iperf. All results will
    be printed to standard output with loss % displayed as multi-column info.

    If an error occurs, a single line is printed to standard output in format
    'ERROR!,<msg>'. Extra information such as stack traces, task lists and
    flow/group table dumps are outputed using the mininet logger (written to
    error out) with a critical logging level.

    Note:
        Similar to 'EmulateTE.py' the test waits for the switches to be in a
        specific state before starting the experiment. The expected state is
        defined in the 'WaitState' directory by a JSON file with name
        '<controller name>.<topology name>.json'.

    Args:
        controller_name (str): Name of controller to use
    """
    # Tell the hosts to start generating LLDP packets
    time.sleep(1)
    for h in topo.hosts_attr(net):
        host = net.get(h[0])
        host.cmd("LLDP/lldp_host.py %s %s &" % (h[1], h[2]))

    # Wait for the switches to start-up with the correct state
    try:
        check_dict = {}
        wait_state_fname = "WaitState/%s.%s.json" % (controller_name, topo.name)
        with open(wait_state_fname, "r") as data_file:
            check_dict = json.load(data_file)
        prepare_check_dict(check_dict)
        wait_match(check_dict, timeout=30)
    except StateWaitTimeoutException:
        # If we time out write an error message, dump the flows and clean-up
        print("ERROR!,Network state took too long to stabilise, exiting ...")
        ls.critical("%s\n" % subprocess.check_output(["ps", "-aux"]))

        # Dump the flow rules (and groups if not reactive controller)
        dump_groups = False
        if controller_name is not "reactive":
            dump_groups = True
        topo.dump_tables(dump_groups=dump_groups)

        # Cleanup and exit
        cleanup()
        return

    info("Topology has stabilised, running pktgen test\n")

    for i in range(len(SCENARIO["scenario"]["receive"])):
        r = SCENARIO["scenario"]["receive"][i]
        info("Starting reciver %s\n" % r["host"])
        host = net.get(r["host"])
        host.cmd("TEPerformanceLogger/logger int:%s-eth0 pcap:%s.pcap &"
                    % (r["host"], i))

    # Construct a timeline for test based on sender and stream info
    timed_out = True
    active_streams = []
    for wait in range(120):
        all_done = True
        restart_streams = False
        for i in range(len(SCENARIO["scenario"]["send"])):
            s = SCENARIO["scenario"]["send"][i]
            start_at = s["delay"] + 1
            end_at = s["delay"] + 1 + SCENARIO["scenario"]["stream_time"]
            if start_at == wait:
                # Start the stream sending
                info("Adding stream %s at time %s\n" % (s["src_host"], wait))
                active_streams.append(i)
                all_done = False

                # Restart the streams
                restart_streams = True
            elif end_at > wait:
                # This stream has not finished so keep running
                all_done = False
            elif end_at == wait:
                info("Ending sender %s at time %s\n" % (s["src_host"], wait))
                active_streams.remove(i)
                restart_streams = True

        # If we ened to re-start pktgen
        if restart_streams:
            signal_local_subprocess("bash pktgen_run.sh", kill=True)

            with open("pktgen_run.sh", "w") as f:
                cmd_str = ""
                for i in active_streams:
                    s = SCENARIO["scenario"]["send"][i]
                    eth_device = "%s-eth0" % s["src_host"]
                    packet_rate = s["rate"]
                    dest_ip = s["dest_addr"]
                    cmd_str += "\n%s\n" % (PKTGEN_STREAM_TMPL.format(
                                            eth_device=eth_device,
                                            packet_rate=packet_rate,
                                            dest_ip=dest_ip))
                f.write(PKTGEN_SCRIPT_TMPL.format(conf_block=cmd_str))

            # Start the newly created script
            info("Re-starting pktgen scripts at time %s\n" % wait)
            subprocess.call("bash pktgen_run.sh &", shell=True)
            info("\tDone\n")

        if all_done:
            timed_out = False
            break

        time.sleep(1)

    if timed_out:
        critlca("Pktgen stream did not terminate in time\n")

    info("Finished, cleaning up and computing results")

    # Cleanup, process results and remove temp files
    cleanup()
    os.remove("logger.done")
    for i in range(len(SCENARIO["scenario"]["receive"])):
        try:
            proc_pktgen_data(i)
            #os.remove("%s.pcap" % i)
        except Exception as ex:
            lg.critical("Error occured processing data of reciver %s: %s\n"
                            % (i, ex))
            continue

    os.remove("pktgen_run.sh")

def proc_pktgen_data(server_index):
    """ Process the pktgen data of a specific sender and generate a result file.

    Args:
        server_index (int): Index of the sender
    """
    print(subprocess.check_output(
        ["TEPerformanceLogger/processPKTGEN", "pcap:%s.pcap" % server_index]
    ))


if __name__ == "__main__":
    # Load the controller config and retrieve the script arguments
    CONTROLLERS = load_ctrls("controllers_te.yaml")
    parser = ArgumentParser("Mininet Emulator: Pktgen TE benchmark")
    parser.add_argument("--topo", required=True, type=str,
        help="Topology module to use for emulation")
    parser.add_argument("--controller", required=True, type=str,
        help="Controller to use for emulation (%s)"
                    % get_ctrl_names(CONTROLLERS))
    parser.add_argument("--scenario", required=True, type=str,
        help="TE scenario YAML file")
    parser.add_argument("--sw_ctrl_map", type=str, default=None,
        help="Switch-controller JSON map file (use multiple controllers)")
    parser.add_argument("--ctrl_options", type=str, default=None,
        help="netem options to apply to control channel (i.e. delay 10ms)")
    parser.add_argument("--log_level", type=str, default="critical",
        help="Emulator log level (debug, info, warning, error, critical)")
    parser.add_argument("--ctrl_log_level", type=str, default="critical",
        help="Controller log level (debug, info, warning, error, critical)")
    args = parser.parse_args()

    # Load the topology module, TE scenario and validate attributes/run
    topoMod = path_to_import_notation(args.topo)
    topo = importlib.import_module(topoMod)
    topo = topo.NetTopo(inNamespace=False)

    controller_name = args.controller.lower()
    if controller_name not in CONTROLLERS:
        lg.critical("Invalid controller name received!\n")
        exit()

    SCENARIO = load_scenario(args.scenario)
    if "usable_on_topo" in SCENARIO:
        if topo.name not in SCENARIO["usable_on_topo"]:
            exit()
    validate_scenario(SCENARIO, controller_name, topo)

    ctrl_channel_options = None
    if args.ctrl_options:
        ctrl_channel_options = args.ctrl_options.lower()

    sw_ctrl_map = None
    if args.sw_ctrl_map is not None and os.path.isfile(args.sw_ctrl_map):
        sw_ctrl_map = args.sw_ctrl_map

    # Check if there any running instances of mininet, or the controller
    running_instance_check()
    setLogLevel(args.log_level)
    try:
        # Apply ports data to controllers if scenario specifies field
        ports_data = None
        if "port_desc" in SCENARIO:
            info("Port desc found in scenario, applying to controllers\n")
            ports_data = SCENARIO["port_desc"]

        # Initiate controller manager, configure controllers and run experiment
        controllers = ControllerManager(ports_data=ports_data,
                        map=sw_ctrl_map,
                        ctrl_channel_opts=ctrl_channel_options,
                        log_level=args.ctrl_log_level)

        # If TE config defined in scenario, ovewrite default attribute values
        interval = 1
        threshold = 0.90
        consolidate_time = 1
        if "te_conf" in SCENARIO:
            if "interval" in SCENARIO["te_conf"]:
                interval = SCENARIO["te_conf"]["interval"]
            if "threshold" in SCENARIO["te_conf"]:
                threshold = SCENARIO["te_conf"]["threshold"]
            if "consolidate_time" in SCENARIO["te_conf"]:
                consolidate_time = SCENARIO["te_conf"]["consolidate_time"]

        # Set controller configuration attributes
        controllers.set_ctrl_config("application", "optimise_protection", False)
        controllers.set_ctrl_config("stats", "collect", True)
        controllers.set_ctrl_config("stats", "collect_port", True)
        controllers.set_ctrl_config("stats", "interval", interval)
        controllers.set_ctrl_config("te", "utilisation_threshold", threshold)
        controllers.set_ctrl_config("te", "consolidate_time", consolidate_time)
        controllers.set_ctrl_cmd_module(get_ctrl_module(CONTROLLERS,
                                            controller_name))
        net = controllers.start(topo)
        run(controller_name)
    except:
        # Show the erro, cleanup and exit the app
        print("ERROR!,Exception occured while running emulation")
        lg.critical("%s\n" % traceback.format_exc())
        cleanup()
