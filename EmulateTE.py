#!/usr/bin/python

""" Emulation framework entry script that initiates and runs a TE swap-over
performance test on a topology with a sepecific controller.

Usage:
    sudo ./EmulateTE.py --topo <topology> --controller <ctrl_name> --scenario \
        <scen> --sw_ctrl_map [map] --ctrl_options [ctrl_opts]

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
from emulator_base import prepare_check_dict
from emulator_base import ControllerManager
from emulator_base import running_instance_check


# Dictionary that contains information about avaible controllers.
# XXX NOTE: The 'start_command' attribute is used to find the module for the
# required controller. We assume that the module is located as the second item
# in the list (index 1). All other attributes of the command are ignored!
CONTROLLERS = {}

# Template for the iperf stream script used to generate traffic for the experiment
IPERF_GEN_SCRIPT_TMPL = """#!/bin/bash

sleep %s;
iperf -c %s -u -b %s -t %s;
echo 'DONE' > %s.done
"""

# Template used to generate gnuplot script to make graphs for viewing results
GNUPLOT_SCRIPT_TMPL = """set datafile separator ','
set autoscale
unset log
set xtic 5
set ytic 5
set title 'Congestion Minimisation Performance'
set xlabel 'Time (seconds)'
set ylabel 'Packet Loss (%%)'
set term png
set output '%s'
set bmargin %s
set key box below

set grid ytics lc rgb '#bbbbbb' lw 1 lt 0
set grid xtics lc rgb '#bbbbbb' lw 1 lt 0

plot \\
"""

GNUPLOT_SERIES_TMPL = """    '%s' using %s title '%s' with linespoints"""

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
controllers = None
# Running network instance
net = None

def load_scenario(file):
    """ Load the TE emulation scenario from a YAML file `file` and return it.

    Args:
        file (str): Path to TE scenario YAML file.

    Returns:
        dict: TE scenario information dictionary
    """
    with open(file, "r") as stream:
        return yaml.safe_load(stream)

def validate_scenario(scen, ctrl, topo):
    """ Validate a TE scenario `scen` from the controller `ctrl`. Ensure that
    the scenario specifies valid sender and recivers as defined by the topology
    `topo`.

    Note:
        This method will modify the scenario by over-writing the top-level
        dictionary of controllers (key 'scenario') with the controller we
        are using for emulation `ctrl`.

    Args:
        scen (dict): TE scenario information dictionary
        ctrl (str): Name of controller to validate scenario info for
        topo (obj): Topology module to use for validation

    Raises:
        Exception: Scenario file is invalid
    """
    # Make sure the controller exists in the scenario file
    if ctrl not in scen["scenario"]:
        raise Exception("Invalid scenario. Controller %s not found!" % ctrl)

    # Remove redundant controller scenario info
    scen["scenario"] = scen["scenario"][ctrl]
    scen = scen["scenario"]

    # Check if the stream time exists in the config
    if "stream_time" not in scen:
        raise Exception("Invalid scenario: Scenario has no stream time field")
    else:
        if int(scen["stream_time"]) <= 0:
            raise Exception("Invalid scenario: Stream time not positive int")

    # Check that the attributes are correct
    for s in scen["send"]:
        if ("src_host" not in s or "dest_addr" not in s or "rate" not in s
                    or "delay" not in s):
            raise Exception("Invalid scenario: Send info has missing fields")
        if s["delay"] < 0:
            raise Exception("Invalid scenario: Send delay not positive float")
        stream_time = scen["stream_time"]
        if stream_time < s["delay"]:
            raise Exception("Invalid scenario: Send delay > stream time")
        if not s["src_host"] in topo.hosts():
            raise Exception("Invalid scenario: Send host dosen't exist")

    for r in scen["receive"]:
        if "host" not in r:
            raise Exception("Invalid scenari:. Receive info has missing fields")
        if not r["host"] in topo.hosts():
            raise Exception("Invalid scenario. Receive host dosen't exist")

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
        # Stop the LLDP packet generators
        for h in topo.hosts_attr(net):
            host = net.get(h[0])
            signal_subprocess(host, "LLDP/lldp_host.py", kill=True)

        # Stop the iperf traffic generators and receivers
        for i in range(len(SCENARIO["scenario"]["send"])):
            s = SCENARIO["scenario"]["send"][i]
            host = net.get(s["src_host"])
            info("Stopped iperf stream script on host %s\n" % s["src_host"])
            signal_subprocess(host, "bash st%s.sh" % i, kill=True)

        for i in range(len(SCENARIO["scenario"]["receive"])):
            r = SCENARIO["scenario"]["receive"][i]
            host = net.get(r["host"])
            info("Stopped iperf server on host %s\n" % r["host"])
            signal_subprocess(host, "iperf -s", kill=True)

        # Stop the network
        net.stop()
        net = None

def run(controller_name):
    """ Start and run the emulation experiment to record TE swap-over
    performance by looking at sustained congestion/loss rates when links are
    constrained and sufficient traffic is placed on them to generate congestion
    loss. This emulation test uses iperf sender and receivers to generate
    traffic on the topology. All sustained congestion intervals are printed to
    standard output on single lines with format '<ID>,<start_time>,<end_time>'
    were <ID> represents the iperf stream ID, <start_time> the start time (in
    seconds) when congestion was first observed and <end_time> the end time (in
    seconds) when congestion loss stopped (loss % reached 0). In addition to the
    numeric results, graphs of congestion loss % vs time are saved in files
    named 'graph_<server_id>.png' were <server_id> represents the index number
    of the iperf server (receiver) from the scenario file.

    If an error occurs, a single line is printed to standard output in format
    'ERROR!,<msg>'. Extra information such as stack traces, task lists and
    flow/group table dumps are outputed using the mininet logger (written to
    error out) with a critical logging level.

    Note:
        Similar to 'EmulateLinkFailure.py', the tests waits for the switches to
        be in a specific state before starting the experiment. The expected
        state is defined in a the 'WaitState' directory by a JSON file with the
        name '<controller name>.<topology name>.json'.

    Args:
        controller_name (str): Name of controller to use
    """
    # Create the stream iperf scripts to run and clear the done indicator
    # files of the scripts
    for i in range(len(SCENARIO["scenario"]["send"])):
        s = SCENARIO["scenario"]["send"][i]
        t = s["delay"] + 1
        end_t = SCENARIO["scenario"]["stream_time"] - s["delay"]
        fname = "st%s" % i
        with open("%s.sh" % fname, "w") as f:
            f.write(IPERF_GEN_SCRIPT_TMPL % (t, s["dest_addr"], s["rate"], end_t, fname))

        open("%s.done" % fname, "w").close()

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
        ls.critical("%s\n" % subprocess.check_output(["ps", "-aux"]))

        # Dump the flow rules (and groups if not reactive controller)
        topo.dump_tables(dump_groups=False if controller_name == "reactive" else True)

        # Cleanup and exit
        cleanup()
        return

    info("Topology has stabilised, running iperf test\n")

    for i in range(len(SCENARIO["scenario"]["receive"])):
        r = SCENARIO["scenario"]["receive"][i]
        info("RECV %s %s\n" % (i, r["host"]))
        host = net.get(r["host"])
        host.cmd("iperf -s -u -i 1 > TE_OUT_%s.txt &" % i)

    for i in range(len(SCENARIO["scenario"]["send"])):
        s = SCENARIO["scenario"]["send"][i]
        info("SEND %s %s\n" % (i, s["src_host"]))
        fname = "st%s.sh" % i
        host = net.get(s["src_host"])
        host.cmd("bash %s &" % fname)

    # Wait for the iperf stream senders to finish sending data
    stream_done = []
    for i in range(len(SCENARIO["scenario"]["send"])):
        stream_done.append(False)

    timed_out = True
    for wait in range(1, 120):
        bool_all_done = True
        for i in range(len(SCENARIO["scenario"]["send"])):
            if stream_done[i] == False:
                bool_all_done = False
                with open("st%s.done" % i, "r") as f:
                    if f.readline().rstrip() == "DONE":
                        stream_done[i] = True

        if bool_all_done:
            timed_out = False
            break

        time.sleep(1)

    if timed_out:
        critical("Iperf Stream did not terminate in time\n")

    info("Finished iperf, cleaning up and computing results\n")

    # Cleanup, process results and remove temp and generated files
    cleanup()
    for i in range(len(SCENARIO["scenario"]["receive"])):
        try:
            proc_iperf_data(i)
            os.remove("TE_OUT_%s.txt" % i)
        except Exception as ex:
            lg.critical("Error processing iperf data of receiver %s: %s\n"
                            % (i, ex))
            continue

    for i in range(len(SCENARIO["scenario"]["send"])):
        os.remove("st%s.sh" % i)
        os.remove("st%s.done" % i)

def proc_iperf_out(line):
    """ Process a iperf server line interval output. Method returns a
    packed tuple of the fields in a a iperf -s line when the inveral is
    set to 1. If the line is not a interval entry, Null is returned.

    Args:
        line (str): Line to extract fields from
    Returns:
        packed tuple: time_left, time_right, size,rate, delay, loss or None if
            `line` is not a valid interval line.
    """
    time_left = None
    time_right = None
    size = None
    rate = None
    delay = None
    loss = None

    line_unproc = line.lower()
    if "sec" in line_unproc:
        line_unproc = line_unproc.split(" sec")

        time = line_unproc[0]
        line_unproc = line_unproc[1].strip()

        time_left = float(time.split("-")[0].strip())
        time_right = float(time.split("-")[1].strip())
    else:
        return None

    if "bytes" in line_unproc:
        line_unproc = line_unproc.split("bytes")

        size = line_unproc[0]+"Bytes"
        line_unproc = line_unproc[1].strip()
    else:
        return None

    if "bits/sec" in line_unproc:
        line_unproc = line_unproc.split("bits/sec")

        rate = line_unproc[0] + "bits/sec"
        line_unproc = line_unproc[1].strip()
    else:
        return None

    if "ms" in line_unproc:
        line_unproc = line_unproc.split("ms")
        delay = line_unproc[0] + "ms"
        line_unproc = line_unproc[1].strip()
    else:
        return None

    if "%" in line_unproc:
        line_unproc = line_unproc.split("(")
        loss = line_unproc[1].split(")")[0]
    else:
        return None

    if (time_right - time_left) > 1:
        # Skip the total line
        return None

    return (time_left, time_right, size, rate, delay, loss)

def proc_iperf_data(server_index):
    """ Process through the iperf server output to generate the TE recovery
    time graph. Method will iterate through 'TE_OUT.txt' created by the iperf
    server and create a gnuplot file which is then used to make the graph
    for this execution in file 'graph.png'.
    """
    stream_id = []
    stream_data = {}

    # Split the iperf server file by streams
    with open("TE_OUT_%s.txt" % server_index) as f:
        for line in f.readlines():
            line = line.strip()
            if line.startswith("["):
                if "]" not in line:
                    continue

                ID = line.split("]")
                data = ID[1].strip()
                ID = ID[0][1:].strip()
                if ID.isdigit() == False:
                    continue

                if ID not in stream_id:
                    stream_id.append(ID)
                if ID not in stream_data:
                    stream_data[ID] = []

                stream_data[ID].append(data)

    # Consolidate the streams into one line of data and work out start and end of congestion
    stream_congestion = {}
    for ID in stream_id:
        stream_congestion[ID] = {"start": None, "end": None}

    proc_data = {}
    index = 0
    for ID in stream_id:
        ST_START_DELAY = SCENARIO["scenario"]["send"][index]["delay"]
        index += 1
        for line in stream_data[ID]:
            res = proc_iperf_out(line)
            if res is not None:
                tmp = "%s" % ",".join(map(str, res[2:]))
                tup = (res[0]+ST_START_DELAY, res[1]+ST_START_DELAY)
                if tup not in proc_data:
                    proc_data[tup] = {}

                proc_data[tup][ID] = tmp

                # Try to find the start and the end of the congestion
                if stream_congestion[ID]["start"] is None and float(res[5][:-1]) > 1:
                    stream_congestion[ID]["start"] = res[0]+ST_START_DELAY
                elif (stream_congestion[ID]["start"] is not None and
                                stream_congestion[ID]["end"] is None and
                                float(res[5][:-1]) < 1):
                    stream_congestion[ID]["end"] = res[0]+ST_START_DELAY

    # Output data that needs to be plotted by gnuplot
    with open("out_%s.dat" % server_index, "w") as f:
        for key in sorted(proc_data.keys()):
            dat = proc_data[key]
            f.write("%s,%s," % (key[0], key[1]))
            skipped = False
            for ID in stream_id:
                if skipped:
                    f.write(",")
                else:
                    skipped = True

                if ID in dat:
                    f.write(dat[ID])
                else:
                    f.write("0,0,0,0")

            f.write("\n")

    # Generate the gnuplot script used to make the graphs
    num_series = len(SCENARIO["scenario"]["send"])
    margin = 5
    if num_series > 3:
        margin += 1

    with open("out_%s.p" % server_index, "w") as f:
        out_file = "graph_%s.png" % server_index
        data_fname = "out_%s.dat" % server_index
        f.write(GNUPLOT_SCRIPT_TMPL % (out_file, margin))

        for i in range(num_series):
            series = "1:%s" % (6+4*i)
            series_name = "Stream %s" % (i+1)
            f.write(GNUPLOT_SERIES_TMPL % (data_fname, series, series_name))

            if not i == (num_series - 1):
                f.write(", \\\n")
            else:
                f.write("\n")

    # Create graph of data and print detected congestion start and end times for each stream
    cmd = "gnuplot out_%s.p" % server_index
    subprocess.call(cmd.split(" "))
    for ID in stream_id:
        print("%s,%s,%s" % (ID, stream_congestion[ID]["start"],
                stream_congestion[ID]["end"]))


if __name__ == "__main__":
    # Load the controller config and retrieve the script arguments
    CONTROLLERS = load_ctrls("controllers_te.yaml")
    parser = ArgumentParser("Mininet Emulator: Iperf TE benchmark")
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
    topo = topo.NetTopo()

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
