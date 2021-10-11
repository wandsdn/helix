#!/usr/bin/python

""" Module that contains shared methods used by the emulation framework """

import subprocess
import os
import re
import csv
import json
import yaml
import time
import string

# Import the local controller base to use static method to compute GID
from TopoDiscoveryController import TopoDiscoveryController

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.log import info, warn, lg
from Networks.TopoBase import CustomCtrlSw


# ---------- STRING FORMATTERS ----------

class PartialStrFormat(string.Formatter):
    """ Class that defines a partial formatter that does not throw an error if
    a string contains placeholders with no provided value. For placeholders
    with no provided value, the formatter will output the placeholder name
    surrounded by curly braces (initial placeholder syntax). Note: To get the
    name of the placeholder, the formatter get field method returns a tuple
    value where the first field is None and the second is assumed to be the
    field name.

    The class needs to be instantiated before using the formatter!
    """
    def get_field(self, field_name, args, kwards):
        # Return special null tuple if no value provided for placeholder
        # (supress exception)
        try:
            val=super(PartialStrFormat, self).get_field(field_name, args,
                                                kwards)
        except (KeyError, AttributeError):
            val=(None,field_name),field_name
        return val

    def format_field(self, value, spec):
        # If a special null tuple found, output the initial placeholder
        # name
        if (isinstance(value, tuple) and len(value) == 2 and
                            value[0] == None and not value[1] == None):
            return "{%s}" % value[1]
        return super(PartialStrFormat, self).format_field(value, spec)

# Instantiate the formatter
fmt=PartialStrFormat()

# ---------- CONTROLLER CONFIG/INFO INTERACTION ----------


def load_ctrls(file):
    """ Load and return a controller info YAML file `file` as a dictionary.
    The controller info dictionary will use the format:
    '{<ctrl_name>: {"start_command": [<args>, ...]}}' were <ctrl_name>
    represents the name of the controller and "start_command" a list of args
    that can be used to run the controller. Any non string elements of the
    start command array are converted to strings.

    NOTE:
        The start command is no longer used by the emulation framework. The
        framework does, however, use the list of args to find the module of a
        controller (the second element of the start-command array).

    Args:
        file (str): Path to YAML file that needs to be loaded

    Returns:
        dict: Controller information dictionary loaded from file
    """
    ctrls = {}
    with open(file, "r") as stream:
        ctrls = yaml.safe_load(stream)

    for key,val in ctrls.iteritems():
        attr = []
        for v in val["start_command"]:
            attr.append(str(v))
        val["start_command"] = attr

    return ctrls

def get_ctrl_names(ctrls):
    """ From a controllers information dictionary, return a string of supported
    controller names. Method will concatenate all top-level keys of `ctrls`.

    Args:
        ctrls (dict): Controllers information dictionary

    Returns:
        str: Concatenated list of strings in format '<name>/<name>/...'
    """
    str = ""
    for key,val in ctrls.iteritems():
        if str == "":
            str = key
        else:
            str = "%s/%s" % (str,key)
    return str

def get_ctrl_module(ctrls, name):
    """ Return the module of the controller `name` from a controllers info
    dictionary start-command list. The module should always be specified as
    the second element of the start command array.

    Args:
        ctrls (dict): Controllers information dictionary
        name (str): Name of the controller to get module for

    Returns:
        str: Controller module or None if `name` is invalid
    """
    for key,val in ctrls.iteritems():
        if key == name:
            return val["start_command"][1]
    return None


# ---------- TOPOLOGY LOADING, SUBPROCESS INTERACTION AND CLEAN-UP ----------


def path_to_import_notation(module):
    """ Convert and return a module file path to a import dot-notation path.
    Method will replace all slashes from a path with dots and remove any ending
    .py file extension. If the method is called with a dot-notation path the
    method will not modify the provided path.

    Args:
        module (str0: Path of the module we want to convert.

    Returns:
        str: import dot-notation module path.
    """
    if "/" in module:
        module = module.replace("/", ".")
    if module.endswith(".py"):
        module = module[:-3]

    return module

def running_instance_check():
    """ Check if an instances of Mininet and RYU is already running. If a
    running instance was detected, the method will kill the process by sending
    a SIGTERM signal. To ensure clean start-up every time the script is
    executed, the script will run the Mininet clean command to remove any
    existing garbage links created by mininet. The clean command is executed
    after the running process checks.
    """
    # Running mininet instance check
    mininet_instances_pid = ""
    try:
         mininet_instances_pid = subprocess.check_output(["pgrep", "--full", "mininet"])
    except subprocess.CalledProcessError as e:
        if not e.returncode == 1:
            lg.critical("%s\n" % e)
            exit()

    # Check if there are any running instances of mininet
    if not mininet_instances_pid == "":
        info("A mininet instance is already running, trying to kill instance\n")

        # We have found the PID of the children processes we need to get
        # the PID of the parent thread, mininet wrapper to kill that
        PID_CHILD = mininet_instances_pid.splitlines()[0]
        PID_PARENT = subprocess.check_output(["ps", "-o", "ppid=", "-p", PID_CHILD]).strip()

        # Make sure we have a parent PID
        if (PID_PARENT == ""):
            lg.critical("Could not get PID of mininet parent to stop instance\n")
            lg.critical("Please manually close any mininet instance\n")
            exit()

        info("Killing mininet parent with PID %s\n" % PID_PARENT)
        subprocess.check_output(["kill", "-SIGTERM", PID_PARENT])
        info("Cleaning up mininet resources\n")
        subprocess.check_output(["mn", "-c"])

    # Running Ryu instance check
    ryu_instances_pid = ""
    try:
         ryu_instances_pid = subprocess.check_output(["pgrep", "--full", "ryu-manager"])
    except subprocess.CalledProcessError as e:
        if not e.returncode == 1:
            lg.critical("%s\n" % e)
            exit()

    # Check if there are any running ryu-instances
    if not ryu_instances_pid == "":
        info("A ryu-instance is already running, trying to kill instance\n")

        for pid in ryu_instances_pid.splitlines():
            subprocess.check_output(["kill", "-SIGTERM", pid])
            info("Killed process with PID %s\n" % pid)

    # Running root controller instance check
    root_instances_pid = ""
    try:
         root_instances_pid = subprocess.check_output(["pgrep", "--full", "python RootCtrl.py"])
    except subprocess.CalledProcessError as e:
        if not e.returncode == 1:
            lg.critical("%s\n" % e)
            exit()

    # Check if there are any running root ctrl instances
    if not root_instances_pid == "":
        info("A root instance is already running, trying to kill instances\n")

        for pid in root_instances_pid.splitlines():
            subprocess.check_output(["kill", "-SIGTERM", pid])
            info("Killed process with PID %s\n" % pid)

    # Mininet clean command
    mininet_clean_out = ""
    try:
        mininet_clean_out = subprocess.check_output(["mn", "--clean"], stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        if not e.returncode == 1:
            lg.critical("%s\n" % e)
            exit()

    if "Cleanup complete" not in mininet_clean_out:
        lg.critical("---- Failed mininet cleanup command ----\n")
        lg.critical("Command Output:\n")
        lg.critical("%s\n" % mininet_clean_out)
        exit()

def signal_subprocess(host, command, kill=False):
    """ Send a signal to a process process running on a mininet
    `host`. Method will search for the PID of the process by full name.
    If `kill` is set to False we will send a SIGINT, if true a SIGTERM
    is sent instead. If multiple processes match the specified name then the
    signal will be sent to all of them.

    Args:
        host (mininet.node): Host where the process is executing
        command (str): Full name of command to kill.
    """
    for pid in host.cmd("pgrep --full '%s'" % command).splitlines():
        if kill == True:
            host.cmd("kill -SIGTERM %s" % pid)
        else:
            host.cmd("kill -SIGINT %s" % pid)

def signal_local_subprocess(command, kill=False):
    """ Simial to ``signal_subprocess`, however, generates and sends a signal
    to a local process not running on a mininet node/host.

    Args:
        command (str): Full name of the command to kill
        kill (bool): Defaults to False. If true send a SIGTERM to the process
            otherwise send a SIGINT (CTRL+C).
    """
    try:
        for pid in subprocess.check_output([
                    "pgrep", "--full", command]).splitlines():
            if kill == True:
                subprocess.call(["kill", "-SIGTERM", pid])
            else:
                subprocess.call(["kill", "-SIGINT", pid])
    except subprocess.CalledProcessError as ex:
        pass


# ---------- EMULATION EXPERIMENT HELPERS ----------


def prepare_check_dict(check_dict):
    """ Go through a check dictionary `check_dict` and replace the src-dest
    host pairs of paths with the actuall GID values. the GID is computed by
    calling the appropriate Topology Discovery controller (Base Module).

    Args:
        check_dict (dict): Check dictionary that will be modified
    """
    for sw,details in check_dict.iteritems():
        for op,matches in details.iteritems():
            new_match = []
            for hkey,match in matches:
                h1 = hkey.split("-")[0]
                h2 = hkey.split("-")[1]
                gid = TopoDiscoveryController.get_gid(h1, h2)
                vlan_gid = 4096 + gid
                new_match.append(match.format(GID=gid, VLAN_GID=vlan_gid))

            details[op] = new_match


# ---------- CONTROLLER INSTANCE CONFIGURATION AND START UP ----------


def add_ctrl_options(options, ctrl_ip):
    """ Adds netem options to a control channel link based on the controllers
    IP address `ctrl_ip`. The netem options are applied to the loopback device.
    Method will create a traffic queue for the loopback interface and apply
    the netem options `options`. Two filters are created to apply the ctrl
    options only to traffic to and from the `ctrl_ip`.

    NOTE: ``remove_ctrl_options`` needs to be called before calling this method
    to ensure that no other ctrl channel attributes are present on the loopback
    interface. This comand applies the link attributes to both ends of the link.
    If applying latency (or other attributes), for example 10ms, the overall RTT
    latency is double the specified valie, i.e. 20ms as its enforced on both
    ends of the control channel link.

    TODO: Work out a way to apply queues to each seperate interface IP rather
    than matching the ctrl addresses to the single queue we create.

    Args:
        options (str): Netem attributes to add to the controll channel link.
            i.e. latency, jitter, packet loss. For possible netem attribute see
            ```https://wiki.linuxfoundation.org/networking/netem```.
        ctrl_ip (str): Controll channel IP address and prefix to apply `options`
            to. The IP address must be in the format 'A.B.C.D/<prefix length'.
    """
    # Check if the netem options have not been intiaited on the loopback device
    cmd = "tc qdisc show dev lo"
    output = subprocess.check_output(cmd.split(" ")).rstrip()
    if output == "qdisc noqueue 0: root refcnt 2":
        info("Creating queue with netem options %s\n" % options)
        # Create queue on loopback (traf class/prio band) with netem option
        cmd = "tc qdisc add dev lo root handle 1: prio"
        subprocess.check_output(cmd.split(" "))
        cmd = "tc qdisc add dev lo parent 1:3 handle 10: netem %s" % options
        subprocess.check_output(cmd.split(" "))

    # Add filter to apply ctrl channel for on ctrl channel based
    info("Creating filter for IP %s\n" % ctrl_ip)
    cmd = ("tc filter add dev lo protocol ip parent 1:0 prio 3 u32 match ip"
                " dst %s flowid 1:3" % ctrl_ip)
    subprocess.check_output(cmd.split(" "))
    cmd = ("tc filter add dev lo protocol ip parent 1:0 prio 3 u32 match ip"
                " src %s flowid 1:3" % ctrl_ip)
    subprocess.check_output(cmd.split(" "))

def remove_ctrl_options():
    """ Remove any applied control channel options. Method will check
    and remove any filter applied to the controll loopback interface.
    It will also remove any queing classes from the loopback interface
    if they exist. """
    # Remove any filters applied to the loopback interface
    cmd = "tc filter show dev lo"
    output = subprocess.check_output(cmd.split(" ")).rstrip()
    if not output == "":
        cmd = "tc filter del dev lo pref 3"
        subprocess.check_output(cmd.split(" "))

    # Remove any quieng classes applied to the loopback interface
    cmd = "tc qdisc show dev lo"
    output = subprocess.check_output(cmd.split(" ")).rstrip()
    if not output == "qdisc noqueue 0: root refcnt 2":
        cmd = "tc qdisc del root dev lo"
        subprocess.check_output(cmd.split(" "))

class ControllerManager:
    """ Controller manager that starts a multi-controler SDN system based on
    a switch to controller maping file and allows interation with instances.

    Configuration file start command placeholders:
        {log_level} - numeric log level to use
        {conf_file} - path to emulator base generated config file
        {log_file} - Path to log file
        {cip} - IP address assigned to controller
        {dom_id} - Domain/Area ID of the controller
        {inst_id} - ID of the instance
    """

    """ Dictionary of started controllers and information with format:
    {<dom_id>: {"proc": <proc>, "cmd": <cmd>, "extra_instances": {
        <inst_id>: {"proc": <iproc>, "cmd": <icmd>}, ...
    }, ...}

    <dom_id> = ID of the domain instances are managing (ID of the controllers)
    <proc> = Running process object of the controller instance (first instance)
    <cmd> = Command used to start the controller instance

    <inst_id> = ID of extra instances. The primary instance is configured under
        in the root of the CID dictionary and is always set to instance 0. All
        extra instances need to use different instance IDs.
    <iproc> = Running process object of the extra controller instance
    <icmd> = Command used to start the extra controller instance
    """
    __controllers = {}

    # Local controller start command (LOADED FROM CONFIG FILE)
    __local_ctrl_start = ""
    # Root controller start command (LOADED FROM CONFIG FILE)
    __root_ctrl_start = ""

    # Dictionary of local config attributes. Add key value pairs to each block
    # to write to the local controller instance configuration file. Note, the
    # top level dictionary key is in format (<order>, <name>) were the <order>
    # is used to enforce how the config blocks are added to the file. Blocks
    # are loaded from the config file
    __local_ctrl_config_attr = {}

    def __init__(self, ports_data=None, map=None, ctrl_channel_opts=None,
                    log_level="critical",
                    config_file=None):
        """ Initiate a new controller manager. If provided, load the ports
        file and switch-to-controller map (used to start multiple controllers).
        If a `map` was not provided, the manager will assume it's running in
        single ctrl mode (`:cls:attr:is_multi_ctrl` will be set to False).

        Args:
            ports_data (str): Default to None. Optional ports file data
                content which enforces capacity limites on links in the topo.
            map (str): Defaults to None. Optional path to switch-to-controller
                map file that is used to start multiple controllers.
            ctrl_channel_opts (str): Defaults to None. Optional attributes to
                add to the control channel.
            log_level (str): Default log level to apply to the controllers.
                Defaults to "critical" (level 30). String level will be
                converted to integers. If the level is invalid, the default
                level is used (critical).
            config_file (str): Path to controller configuration file that
                specifies the start command of the controllers.
        """
        self.controllers = {}
        self.ctrl_channel_opts = ctrl_channel_opts

        # Load the controller config file
        with open(config_file, "r") as fin:
            config_info = yaml.safe_load(fin)
        self.__local_ctrl_start = config_info["start_cmd"]["local"]
        self.__root_ctrl_start = config_info["start_cmd"]["root"]

        for block in config_info["local_config"]["blocks"]:
            self.__local_ctrl_config_attr[(block[0], block[1])] = {}
        if "extra" in config_info["local_config"]:
            for blk,blk_d in config_info["local_config"]["extra"].iteritems():
                for attr,val in blk_d.iteritems():
                    self.set_ctrl_config(blk, attr, val)

        # Set the log level
        self.log_level = 50
        if log_level == "debug":
            self.log_level = 10
        elif log_level == "info":
            self.log_level = 20
        elif log_level == "warning":
            self.log_level = 30
        elif log_level == "error":
            self.log_level = 40
        elif log_level == "critical":
            self.log_level = 50

        # If valid, process the provided ports file data which will be split
        # per controller when generating configuration file for each instance.
        # XXX: The first line of the ports_data needs to be the data labels.
        self.ports_data = []
        if ports_data is not None and "\n" in ports_data:
            csv_reader = csv.DictReader(ports_data.splitlines())
            for line in csv_reader:
                src = int(line["dpid"])
                port = int(line["port"])
                speed = int(line["speed"])
                self.ports_data.append((src, port, speed))

        if map is None:
            self.is_multi_ctrl = False
            self.set_ctrl_config("multi_ctrl", "start_com", False)
        else:
            # Switch controller map provided, load it and flag multi-ctrl
            self.sw_ctrl_map = self.load_sw_ctrl_map(map)
            self.is_multi_ctrl = True

    def load_sw_ctrl_map(self, fpath):
        """ Load and return a switch to controller mapping from a JSON file
        `fpath`. If the maping file is invalid, the method will raise a
        exception with the error details for logging purposes.

        NOTE: The method ignores any root controller attributes.

        TODO: Add root controller parsing and do something with the info. Work
        out how to handle multiple instances using current format!

        Args:
            fpath (str): Path to JSON file we need to parse

        Returns:
            dict: Switch to controller mapping with controller info in format:
                {<ctrl_name>: {
                    "dom_id": <dom_id>, "cip": "127.0.0.<cid>",
                    "instances": [<id>, ...],
                    "conf_file": "/tmp/emul_<cid>.conf",
                    "ports_file": "/tmp/emul_<cid>.ports.csv",
                    "sw": [<sw>, ...]
                }
        """
        local_info = {}
        sw_assigned = []
        host_assigned = []

        # Open file and deserialize to an object
        with open(fpath) as fin:
            obj = json.load(fin)

        # Validate file and load local controller information
        if "root" not in obj:
            raise Exception("Load sw-ctrl-map: No 'root' top level key")
        if "ctrl" not in obj:
            raise Exception("Load sw-ctrl-map: No 'ctrl' top level key")

        cip_base = 10
        for ctrl in sorted(obj["ctrl"].keys()):
            ctrl_d = obj["ctrl"][ctrl]
            if ctrl in local_info:
                # Duplicate local controoler CID found, raise error
                raise Exception("Load sw-ctrl-map: Duplicate local ctrl %s" % ctrl)

            cip_base += 1
            local_info[ctrl] = {
                "dom_id": int(ctrl[1:]),
                "cip": "127.0.0.%s" % cip_base,
                "extra_instances": {},
                "conf_file": "/tmp/emul_%s.conf" % ctrl,
                "ports_file": "/tmp/emul_%s.ports.csv" % ctrl,
                "sw": [],
                "hosts": [],
            }

            # If ctrl has instances generate and assign IPs to each instance
            if "extra_instances" in ctrl_d:
                for inst_num in ctrl_d["extra_instances"]:
                    cip_base += 1
                    cip = "127.0.0.%s" % cip_base
                    local_info[ctrl]["extra_instances"][inst_num] = {
                        "cip": cip,
                        "conf_file": "/tmp/emul_%s.%s.conf" % (ctrl, inst_num)
                    }

            # Go through switches assigned to controller
            for sw in ctrl_d["sw"]:
                if sw in sw_assigned:
                    # Switch already assigned to different controller, raise error
                    raise Exception("Load sw-ctrl-map: SW %s assigned to two ctrls"
                                        % sw)

                # Add switch to controller assignemd (and already proc list)
                sw_assigned.append(sw)
                local_info[ctrl]["sw"].append(sw)

            # Go through hosts assigned to controller
            for host in ctrl_d["host"]:
                if host in host_assigned:
                    # Host already assigned to different controller, raise error
                    raise Exception("Load sw-ctrl-map: Host %s assigned to two ctrls"
                                        % host)

                # Add host to controller assignment (and already added list)
                host_assigned.append(host)
                local_info[ctrl]["hosts"].append(host)

        return local_info

    def __start_multi_ctrl(self, net):
        """ Go through the loaded switch-to-controller map, start specified
        controllers and bind the controllers to the topology and switches they
        need to manage. This method will automatically start a single root
        controller instance. For every local controller instance, the required
        config files are also generated by calling `__create_lc_config`.

        Args:
            net (obj): Mininet network object to add ctrls to
        """
        # Process the sw-ctrl map and start all required controllers
        for ctrl,ctrl_info in self.sw_ctrl_map.iteritems():

            # Create controllers for the network and generate configurations
            ctrl_obj = net.addController(ctrl, controller=RemoteController,
                                            ip=ctrl_info["cip"], port=6653)

            extra_instances = []
            for inst,inst_d in ctrl_info["extra_instances"].iteritems():
                inst_ctrl = "%s.%s" % (ctrl, inst)
                inst_obj = net.addController(inst_ctrl,
                    controller=RemoteController, ip=inst_d["cip"],
                    port=6653)
                extra_instances.append(inst_ctrl)

            self.__create_lc_config(ctrl_info)

            # Assign switches to controller and any local controller instances
            # Assign the managed switches to the controller instances and start
            # the controller subprocesses
            for sw in ctrl_info["sw"]:
                sw_obj = net.get(sw)
                sw_obj.add_ctrl(ctrl)
                for inst_ctrl in extra_instances:
                    sw_obj.add_ctrl(inst_ctrl)

            self.start_local_ctrl(ctrl, ctrl_info)

        # Start the root controller
        self.start_root_ctrl()

    def start(self, topo):
        """ Initiate a new mininet network object, start all controllers and
        bind the switches. The method uses the switch-to-controller mapping
        `:cls:attr:(sw_ctrl_map)` to initiate the controllers and generate
        configuration files. If a mapping was not provided, the method will
        start a single controller instance using the local controller start
        command.

        Args:
            topo (obj): Topology module to use for the emulation
        """
        # XXX: Remove ctrl channel options added by mininet (call only once as
        # removes all active configs on the loopback device)
        if self.ctrl_channel_opts is not None:
            remove_ctrl_options()

        if self.is_multi_ctrl is True:
            # Initiate the mininet network and start multiple controllers
            net = Mininet(
                topo=topo,
                controller=None,
                switch=CustomCtrlSw,
                autoSetMacs=True)

            self.__start_multi_ctrl(net)
        else:
            # Initiate the mininet network and start the controller process
            net = Mininet(
                topo=topo,
                controller=RemoteController("c1", ip="127.0.0.2"),
                switch=OVSSwitch,
                autoSetMacs=True)

            ctrl_info = {
                "dom_id": 0,
                "cip": "127.0.0.2",
                "extra_instances": {},
                "conf_file": "/tmp/emul_main.conf",
                "ports_file": "/tmp/emul_main.ports.csv",
                "sw": []
            }

            # Create the controller configuration and start it
            self.__create_lc_config(ctrl_info)
            self.start_local_ctrl("main", ctrl_info)

        # Start the network, run the on_start command and return net
        net.start()
        if getattr(topo, "on_start", None):
            topo.on_start(net)
        return net

    def stop(self):
        """ Stop all running controller instances and remove any configured
        control channel options """
        if self.ctrl_channel_opts is not None:
            remove_ctrl_options()
            self.ctrl_channel_opts = None

        info("Stopping running controllers ...\n")
        for ctrl,ctrl_info in self.controllers.iteritems():
            info("\tTerminate controller %s\n" % ctrl)
            if ctrl_info["proc"] is not None:
                ctrl_info["proc"].terminate()
                ctrl_info["proc"].wait()
                ctrl_info["proc"] = None
            for inst,inst_d in ctrl_info["extra_instances"].iteritems():
                info("\tTerminate extra instance %s.%s\n" % (ctrl, inst))
                if inst_d["proc"] is not None:
                    inst_d["proc"].terminate()
                    inst_d["proc"].wait()
                    inst_d["proc"] = None

        self.controllers = {}
        info("Done\n")


    # -------------------- LOCAL CONTROLLER CONFIGURATION --------------------


    def set_ctrl_cmd_module(self, module):
        """ Change the local controller start command
        `:cls:attr:(__local_ctrl_start)` python module to `module`. Note that
        this method will not change any other attributes of the start command.

        Args:
            module (str): Local controller module to use
        """
        self.__local_ctrl_start = "ryu-manager %s " % module
        self.__local_ctrl_start += "--default-log-level {log_level} "
        self.__local_ctrl_start += "--config-file {conf_file} "
        self.__local_ctrl_start += "--log-file {log_file}"
        info("Changed local ctrl start command to:\n")
        info("\t%s\n" % self.__local_ctrl_start)

    def set_ctrl_config(self, block, attr, val):
        """ Add a new local controller configuration attribute to be set on all
        local controllers (added to their config file). `block` specifies the
        name of the configuration block to add the attribute value pair.

        Args:
            block (str): Configuration block the attribute-value is for
            attr (str): Name of the attribute we are configuring
            val (obj): Value of the attribute we are configuring
        """
        for conf_tlb in sorted(self.__local_ctrl_config_attr.keys()):
            _,block_name = conf_tlb
            if block_name == block:
                # We found the config block, add attr-val to dictionary
                self.__local_ctrl_config_attr[conf_tlb][attr] = val
                return

    def __add_conf_file_attr(self, conf, attr, val):
        """ Add a configuration attribute name value to a configuration file as
        a new line. If the value is not a boolean or number, the value is placed
        between double qoutes when added to the configuration string.

        Args:
            conf (str): Configuration string to add new attr-value pair to
            attr (str): Name of the attribute to add to the conf string
            val (obj): Value of the attribute

        Returns:
            str: Configuration string with the attr-value pair added
        """
        if isinstance(val, (bool, int, float)):
            conf = "%s\n%s = %s" % (conf, attr, val)
        else:
            conf = "%s\n%s = \"%s\"" % (conf, attr, val)
        return conf

    def __gen_lc_config(self, dynamic={}):
        """ Generate a local controller configuration string (to write to the
        config file) based on the default local controller configuration
        attributes `:cls:attr:(__local_ctrl_config_attr)` and any dynamic
        attributes which can very for every instance `dynamic`.

        Args:
            dynamic (dict): Dictionary of dynamic attributes that may very
                from instance to instance. Format of dynamic attributes is
                {<block_name>: {<attr>: <value>}} were '<block_name>' is the
                configuration block the attribute-value needs to be added to.

        Returns:
            str: Local controller config string to be written to the conf file
        """
        config = ""

        # Go through the top level blocks of the configuration
        for conf_tlb in sorted(self.__local_ctrl_config_attr.keys()):
            _,block_name = conf_tlb
            if config == "":
                config = "[%s]" % block_name
            else:
                config = "%s\n\n[%s]" % (config, block_name)

            # Add the attributes for the current config block
            attributes = self.__local_ctrl_config_attr[conf_tlb]
            for attr,val in attributes.iteritems():
                config = self.__add_conf_file_attr(config, attr, val)

            # Add any dynamic attributes to the config block
            if block_name in dynamic:
                for attr,val in dynamic[block_name].iteritems():
                    config = self.__add_conf_file_attr(config, attr, val)

        # Add a new line to the end of the config string and return
        config += "\n"
        return config

    def __create_lc_config(self, ctrl_info):
        """ Create the required configuration files for the controller
        instances that manage a domain using the domain information dictionary
        `ctrl_info`. The method generates the needed config by calling
        ``__gen_lc_config`` to create a Ryu config file string. The config is
        written to the path specified by "conf_file" in the info dict. This
        method will automatically create configuration files for all controller
        instances that manage the specified domain.

        Args:
            ctrl_info (dict): Domain information dictionary
        """
        extra_attr = {
            "DEFAULT": {"ofp_listen_host": ctrl_info["cip"]},
            "application": {"static_port_desc": ctrl_info["ports_file"]},
            "multi_ctrl": {"domain_id": ctrl_info["dom_id"], "inst_id": 0}
        }

        # If we are not starting multiple controllers remove the multi-ctrl
        # extra attributes section
        if self.is_multi_ctrl is False:
            del extra_attr["multi_ctrl"]
            ctrl_sw_dpid = []
        else:
            # Go through ctrl switches and gen list of SW DPIDs it manages
            ctrl_sw_dpid = []
            for sw in ctrl_info["sw"]:
                sw_dpid = int(re.search("\d+", sw).group())
                ctrl_sw_dpid.append(sw_dpid)

        # Create the controller ryu config file
        with open(ctrl_info["conf_file"], "w") as fout:
            fout.write(self.__gen_lc_config(extra_attr))

        # Create the controllers port file. If multi-controller, split the
        # data based on the switch DPID's it owns.
        with open(ctrl_info["ports_file"], "w") as fout:
            fout.write("dpid,port,speed\n")
            for dpid,port,speed in self.ports_data:
                if dpid in ctrl_sw_dpid or self.is_multi_ctrl == False:
                    fout.write("%s,%s,%s\n" % (dpid, port, speed))

        # Create config files for all extra instances
        for inst,inst_d in ctrl_info["extra_instances"].iteritems():
            extra_attr["DEFAULT"]["ofp_listen_host"] = inst_d["cip"]
            extra_attr["multi_ctrl"]["inst_id"] = int(inst)

            with open(inst_d["conf_file"], "w") as fout:
                fout.write(self.__gen_lc_config(extra_attr))


    # -------------------- CONTROLLER SUBPROCESS COMMANDS --------------------


    def start_local_ctrl(self, ctrl, ctrl_info):
        """ Start a new local controller subporcess and add it to the dict of
        running controllers `:cls:attr:(controllers)` to allow clean-up and
        interaction with the processes.  This method will start all controllers
        instances defined by `ctrl_info`.

        Args:
            ctrl (obj): Name of the controller group we are starting
            ctrl_info (dict): Information dictionary of controller instances
        """
        # Add ctrl channel options if specified
        if self.ctrl_channel_opts is not None:
            add_ctrl_options(self.ctrl_channel_opts, ctrl_info["cip"]+"/32")

        # Start the local controller instance and save it's details
        cmd = fmt.format(self.__local_ctrl_start,
                                    conf_file=ctrl_info["conf_file"],
                                    log_level=self.log_level,
                                    log_file="/tmp/%s.%s.log" % (ctrl, 0),
                                    cip=ctrl_info["cip"],
                                    dom_id=ctrl_info["dom_id"],
                                    inst_id=0)
        cmd = cmd.split(" ")

        self.controllers[ctrl] = {
            "proc": None,
            "cmd": cmd,
            "extra_instances": {}
        }
        self.__start_ctrl_process(cmd, self.controllers[ctrl])

        # Go through and start all controller extra instances
        for inst,inst_d in ctrl_info["extra_instances"].iteritems():
            if self.ctrl_channel_opts is not None:
                add_ctrl_options(self.ctrl_channel_opts, inst_d["cip"]+"/32")

            cmd = fmt.format(self.__local_ctrl_start,
                                    conf_file=inst_d["conf_file"],
                                    log_level=self.log_level,
                                    log_file="/tmp/%s.%s.log" % (ctrl, inst),
                                    cip=inst_d["cip"],
                                    dom_id=ctrl_info["dom_id"],
                                    inst_id=inst)
            cmd = cmd.split(" ")

            target = self.controllers[ctrl]["extra_instances"]
            target[inst] = {"proc": None, "cmd": cmd}
            self.__start_ctrl_process(cmd, target[inst])

    def start_root_ctrl(self):
        """ Start a new root controller subporcess and add it to the dict of
        running controllers `:cls:attr:(controllers)` to allow clean-up and
        interaction. By default, root is considered to have the controller name
        'root'.
        """
        cmd = fmt.format(self.__root_ctrl_start,
                                log_level=self.log_level,
                                log_file="/tmp/root.0.log")
        cmd = cmd.split(" ")
        self.controllers["root"] = {
            "proc": None,
            "cmd": cmd,
            "extra_instances": {}
        }
        self.__start_ctrl_process(cmd, self.controllers["root"])

    def __start_ctrl_process(self, cmd, info):
        """ Start a new controller process using the command `cmd`. Save the
        process object in the info dictionary `info` using the key `proc`. The
        new process will be configured to write all standard and error output
        to /dev/null (we expect that the app will log to a file as well) to
        prevent cluttering the emulation output.

        Args:
            cmd (list of str): List of arguments to use to start the controller
            info (dict): Target dictionary to save started controller info
        """
        FNULL = open(os.devnull, 'w')
        ctrl = subprocess.Popen(cmd, stdout=FNULL, stderr=FNULL, close_fds=True)
        info["proc"] = ctrl

    def stop_ctrl(self, ctrl, inst_id=None):
        """ Stop a running controller instance and return the time when the
        controller was stopped. The controller process is retrieved from the
        dictionary of running controllers `:cls:attr:(controllers)`. If
        `inst_id` is None (default), the method assumes that we want to stop
        the top-level controller in the instance dictionary. If a `inst_id`
        is provided, `inst_id` will reference a instance from the
        'extra_instances' controller field.

        Args:
            ctrl (obj): Name of the controller we want to stop
            inst_id (obj): ID of the instance. Defaults to None.

        Returns:
            float: Epoch time when controller proccess has terminated
        """
        warn("Stopping controller %s instance %s\n" % (ctrl, inst_id))
        ctrl_info = self.controllers[ctrl]
        if inst_id is not None:
            ctrl_info = ctrl_info["extra_instances"][inst_id]

        ctrl_info["proc"].kill()
        ctrl_info["proc"].wait()
        ctrl_info["proc"] = None
        return time.time()

    def restart_ctrl(self, ctrl, inst_id=None):
        """ Restartart a controller process by using the command saved in the
        started controller dictionary `:cls:attr:(controllers)`. The new
        started subporcess will be saved to the running controller dict. If
        `inst_id` is None (default), the method assumes we are re-starting
        the top-level controller from the running controller dictionary.

        Args:
            ctrl (obj): Name of the controller we want to stop.
            inst_id (obj): ID of the instance. Defaults to None.

        Returns:
            float: Epoch time when controller was re-started
        """
        warn("Restarting controller %s instance %s\n" % (ctrl, inst_id))
        ctrl_info = self.controllers[ctrl]
        if inst_id is not None:
            ctrl_info = ctrl_info["extra_instances"][inst_id]

        self.__start_ctrl_process(ctrl_info["cmd"], ctrl_info)
        return time.time()

    def exists(self, ctrl, inst_id=None):
        """ Check if a controller instance identified by the name `ctrl` and
        `inst_id` exists. If `inst_id` is null, the method will simply check
        for the controller `ctrl` (assumes we are refering to instance 0).

        Args:
            ctrl (obj): Name of the controller to check if exists
            inst_id (obj): ID of the instance to check if exists. Defaults to
                None, only check `ctrl`.

        Returns:
            bool: True if controller instance is valid, false otherwise
        """
        if ctrl not in self.controllers:
            return False

        # If the instance was provided check if ID is invalid
        if inst_id is not None:
            if inst_id not in self.controllers[ctrl]["extra_instances"]:
                return False

        # Otherwise, both ctrl and instance must exist
        return True

    def get_cip_ctrl(self, cip):
        """ Identinfy and return the label and instance ID for a controller
        instance that is ussing the control channel IP `cip`.

        Args:
            cip (str): IP of the controller to retrieve label for

        Returns:
            str: Label of the instance in format '<cid>.<inst_id>' or None
        """
        for ctrl,ctrl_info in self.sw_ctrl_map.iteritems():
            if ctrl_info["cip"] == cip:
                return ctrl

            for inst,inst_d in ctrl_info["extra_instances"].iteritems():
                if inst_d["cip"] == cip:
                    return "%s.%s" % (ctrl, inst)

        # Cound not find CIP so return None
        return None

    def get_sw_ctrl(self, sw):
        """ Similar to ``get_cip_ctrl``, however, fints the label of a
        controller that manages the switch `sw`.

        Args:
            sw (str): Switch to find controller that manages it

        Returns:
            str: Label of controller that manages switch `sw` or None
        """
        for ctrl,ctrl_info in self.sw_ctrl_map.iteritems():
            if sw in ctrl_info["sw"]:
                return ctrl

        # Could not find sw so return None
        return None

    def get_host_ctrl(self, host):
        """ Similar to ``get_sw_ctrl``, however, finds the label of a
        controller that manages a host `host`.

        Args:
            host (str): Host to find controller that manages it

        Returns:
            str: Label of controller that manages host `host` or None
        """
        for ctrl,ctrl_info in self.sw_ctrl_map.iteritems():
            if host in ctrl_info["hosts"]:
                return ctrl

        # Could not find host so return None
        return None

    def get_inst_log(self, ctrl, inst_id=None, pattern="XXXEMUL"):
        """ Return the contents of a instances temporary log file at path
        '/tmp/<ctrl>.<inst_id>.log'. If no instance ID is provided get the log
        file contents for the primary instance. `pattern` allows matching only
        specific lines of the log file to retrieve.

        Args:
            ctrl (obj): Name of the controller to get contents of log file
            inst_id (obj): ID of the instance to retrieve log file for.
                Defaults to None, get log file of primary instance.
            pattern (str): Grep pattern to use to retrieve specific lines of
                the log file. If None, return complete log file contents.
                Defaults to 'XXXEMUL' (special emulator output pattern).

        Returns:
            list of str: Log file contents of instance that match `pattern`.
                Each array entry represents a line of the log file
        """
        # If the instance ID is none assume we want the primary instance
        if inst_id is None:
            inst_id = 0
        log_file="/tmp/%s.%s.log" % (ctrl, inst_id)

        # If the log file dosen't exist return an empty result
        if not os.path.isfile(log_file):
            return []

        # Grep the log file for the specified pattern
        if pattern is not None:
            cmd = ["grep", pattern, log_file]
        else:
            cmd = ["cat", log_file]

        # Get the log file contents and return result as a array of lines
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        proc_out, proc_err = proc.communicate()
        if proc_out is None:
            return None
        return proc_out.splitlines()

    def get_init_inst(self):
        """ Return a list of all initiated controller instances.

        Returns:
            list of tuple: The format of the items is '(<ctrl>, <inst_id>)'
                were '<ctrl>' represents controller ID and '<inst_id>' the ID
                of the instance were '<inst_id>' is None for the primary
                instance.
        """
        instances = []
        for ctrl,ctrl_d in self.controllers.iteritems():
            instances.append((ctrl, None))
            for ex in ctrl_d["extra_instances"].keys():
                instances.append((ctrl, ex))
        return instances
