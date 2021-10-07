#!/usr/bin/python

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3

# Topology discovery
from topo_discovery import event
from topo_discovery.lldp_discovery import SwitchesDiscovery
from topo_discovery.api import get_switch
from topo_discovery.api import pause_topo_discovery, resume_topo_discovery

# Topology ingress change detection
import six
from ryu.lib.packet import vlan
from ryu.lib.packet import packet, ethernet

# OFPErrorMsg output handler
from ryu import utils
from ryu.ofproto import ofproto_parser

from ryu import cfg
from threading import Timer
import re
import csv
import signal
import os
import logging
import time

from ShortestPath.dijkstra_te import Graph
import OFP_Helper

# TE optimisation and inter controller communication
from TE import TEOptimisation
from InterControllerCommunication import ControllerCommunication


# Private global mapping variable of GIDs to host pairs
__GID_MAP__ = {}


class TopoDiscoveryController(app_manager.RyuApp):
    """ Base controller that handles topo discovery callbacks, stats collection, role changes
    and other helpfull methods to allow controller switch interaction.

    Attributes:
        OFP_VERSIONS (array of ofproto.OFP_VERSION): Supported OF versions.
        CONTROLLER_NAME (str): Name of the controller, inherting class should change!
        graph (ShortestPath.dijkstra): Topology information graph object
        hosts (list of obj): List of connected hosts
        TE (obj): TE optimisation module instance
        ctrl_com (obj): Controller communication module instance
        __stats_timer (threading.Timer): Timer instance that triggers stats polling
        __rebuild_state_timeout (int): Rebuild state timout count
        __rebuild_state_sw (dict): Rebuild state switches recovered state info
        __ctrl_role (str): Current controller role (unknown, slave, master)
        unknown_links (dict): List of unknown links in format
            {(<src sw>, <src pn>, <dst pn>): <cid or [timeout value]>}
        __unknown_links_timer (threading.Timer): Timer instance that handles CID resolution for
            unknown links.
        __ing_change_detect_wait (dict): List of paths ingress change detection is temporary
            disabled to prevent swapping due to in-flight packets. {(h1, h2): <Timer Object>}.
    """
    CONTROLLER_NAME = ""
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    # XXX NOTE: SETTING FLAG TO TRUE WILL ENABLE TESTING MODE WHERE NO RYU OR MULTI-CONTROLLER
    # FUNCTIONALITY IS LOADED. THIS MODE SHOULD ONLY BE USED WHEN TESTING THE BARE BONE FUNCTIONS
    # OF THE IMPLEMENTATION. DO NOT SET THIS FLAG TO TRUE UNLESS YOU ARE TESTING THE CLASS
    TESTING_MODE = False


    def __init__(self, *args, **kwargs):
        """ Initiate arguments, topology discovery, controller communication and TE
        optimisation isntance. Process the config file and other attributes """

        # Check for TESTING MODE
        if self.TESTING_MODE:
            # Initiate dummy conf parser and logger
            self.CONF = cfg.CONF
            if "logger" in kwargs:
                self.logger = kwargs["logger"]
            else:
                logging.basicConfig(level=logging.CRITICAL)
                self.logger = logging
            self.logger.warning("CONTROLER RUNNING IN TESTING MODE!")

            # Initiate default attributes
            if "topo" in kwargs:
                self.graph = Graph(kwargs["topo"])
            else:
                self.graph = Graph()

            if "hosts" in kwargs:
                self.hosts = kwargs["hosts"]
            else:
                self.hosts = []

            self.__stats_timer = None
            self.__rebuild_state_timeout = 0
            self.__rebuild_state_sw = {}
            self.__ctrl_role = "unknown"
            self.unknown_links = {}
            self.__unknown_links_timer = None
            self.__ing_change_detect_wait = {}
            self.__cleanup_handlers = []

            # Initiate the inter controller communication module without starting
            # the thread.
            self.ctrl_com = ControllerCommunication(self.logger, self)
            return

        super(TopoDiscoveryController, self).__init__(*args, **kwargs)

        # If a log file was provided log information only to the file
        #if self.CONF.log_file:
        #    root_logger = logging.getLogger()
        #    for handler in root_logger.handlers:
        #        if not isinstance(handler, logging.handlers.WatchedFileHandler):
        #            root_logger.removeHandler(handler)

        # Stop execution if the the base controller is loaded or name is not modified
        if self.CONTROLLER_NAME == "":
            self.logger.critical("Loaded base controller or did not overwrite controller name!")
            exit(0)


        # Register application-stats arguments
        self.CONF.register_opts([
            cfg.BoolOpt("collect", default=True,
                help="Query and collect stats from the switches and network"),
            cfg.BoolOpt("collect_port", default=True,
                help="Collect, process and output to the console OpenFlow port stats"),
            cfg.FloatOpt("interval", default=10.0, min=0.5, max=600.0,
                help="Query and collect stats from the switches and network (1 to 600)"),
            cfg.BoolOpt("out_port", default=False,
                help="Output port stats on stats out signal recived")
        ], group="stats")

        self.CONF.register_opts([
            cfg.BoolOpt("start_com", default=True,
                help="Initiate the multi-controller communication module (defaults True)"),
            cfg.IntOpt("domain_id", default=0,
                help="ID of the domain that contains the controller (defaults to 0)"),
            cfg.IntOpt("inst_id", default=None,
                help="ID of controller instances (defaults to -1, gen random id)")
        ], group="multi_ctrl")

        self.CONF.register_opts([
            cfg.StrOpt("static_port_desc", default="",
                help="File that contains the static port descriptions")
        ], group="application")

        self.CONF.register_opts([
            cfg.FloatOpt("utilisation_threshold", default=0.90, min = 0.0, max = 1.0,
                help="Threshold used to decide if a port is congested (defaults to 0.90)"),
            cfg.FloatOpt("consolidate_time", default=1.0, min=0.1,
                help="TE optimisation consolidation timeout (defaults 1.0)"),
            cfg.StrOpt("opti_method", default="FirstSol",
                help="TE Opti Method: FirstSol (default), BestSolUsage, BestSolPLen, CSPFRecomp"),
            cfg.BoolOpt("candidate_sort_rev", default=True,
                help="Consider src-dest pairs (candidates) in decending order"),
            cfg.BoolOpt("pot_path_sort_rev", default=False,
                help="Reverse potential path set. Only applies to some opti methods!")
        ], group="te")

        # Instantiate topo discovery module instance
        app_mngr = app_manager.AppManager.get_instance()

        # If multi-controller communications have been disabled make sure
        # topo discovery is not paused by default. Promoet to master is not
        # called
        if not self.CONF.multi_ctrl.start_com:
            self.logger.warning("Multi-controller communications turned off!")
            self.logger.warning("\tCtrlCom module init but not started")
            self.logger.warning("\tTopology discovery is started by default")
            self.logger.warning("\tMultiple instances disabled (no election)")
            app_mngr.instantiate(SwitchesDiscovery, pause_detection=False)
        else:
            app_mngr.instantiate(SwitchesDiscovery)

        # Initiate default attributes
        self.graph = Graph()
        self.hosts = []
        self.__stats_timer = None
        self.__rebuild_state_timeout = 0
        self.__rebuild_state_sw = {}
        self.__ctrl_role = "unknown"
        self.unknown_links = {}
        self.__unknown_links_timer = None
        self.__ing_change_detect_wait = {}
        self.__cleanup_handlers = []

        # Inter-controller communication module initiation
        self.ctrl_com = ControllerCommunication(self.logger, self,
                                    dom_id=self.CONF.multi_ctrl.domain_id)
        if self.CONF.multi_ctrl.start_com:
            if self.CONF.multi_ctrl.inst_id is None:
                self.ctrl_com.start()
            else:
                self.ctrl_com.start(self.CONF.multi_ctrl.inst_id)
        else:
            # Do not start CtrlCom module and force ctrl role to master
            self.logger.warning("\tController will start in master role")
            self.__ctrl_role = "master"


        # If inter-controller communications disabled and TE enabled, trigger
        # the stats timmer. Normally `promote_master()` will start the timmer
        # when the instance becomes master. Because inter-ctrl coms are
        # disabled, no leader elections => method never triggers!
        if not self.CONF.multi_ctrl.start_com and self.CONF.stats.collect == True:
            self.logger.info("\tStarting stats collection (ctrl-com off)!")
            self.__trigger_stats_timer()


        # Output the multi-controller config attributes
        self.logger.info("-" * 50)
        self.logger.info("Multi-Controller Config:")
        self.logger.info("\tdomain_id: %s" % self.CONF.multi_ctrl.domain_id)
        if self.CONF.multi_ctrl.inst_id is not None:
            self.logger.info("\tinst_id: %s" % self.CONF.multi_ctrl.inst_id)
        self.logger.info("\tstart_com: %s" % self.CONF.multi_ctrl.start_com)

        # TE optimisation module initiation
        self.logger.info("TE Config:")
        self.logger.info("\tutilisation_threshold: %s" % self.CONF.te.utilisation_threshold)
        self.logger.info("\tconsolidate_time: %s" % self.CONF.te.consolidate_time)
        self.logger.info("\topti_method: %s" % self.CONF.te.opti_method)
        self.logger.info("\tcandidate_sort_rev: %s" % self.CONF.te.candidate_sort_rev)
        self.logger.info("\tpot_path_sort_rev: %s" % self.CONF.te.pot_path_sort_rev)
        self.TE = TEOptimisation(self, self.CONF.te.utilisation_threshold,
                                self.CONF.te.consolidate_time,
                                opti_method = self.CONF.te.opti_method,
                                candidate_sort_rev = self.CONF.te.candidate_sort_rev,
                                pot_path_sort_rev = self.CONF.te.pot_path_sort_rev)

        # If we are collecting stats bind the output signal handler
        self.logger.info("Stats Config:")
        self.logger.info("\tcollect_stats: %s" % self.CONF.stats.collect)
        if self.CONF.stats.collect == True:
            self.logger.info("\tcollect_port_stats: %s" % self.CONF.stats.collect_port)
            self.logger.info("\tout_port: %s" % self.CONF.stats.out_port)
            self.logger.info("\tstats_interval: %s" % self.CONF.stats.interval)
            self.logger.info("\tSignal for stats: kill -USR1 %s" % os.getpid())
            signal.signal(signal.SIGUSR1, self.__stats_signal)

        # Output the config end indicator
        self.logger.info("-" * 50)

        # Process the static port description file
        if not self.CONF.application.static_port_desc == "":
            dat = {}

            # Try to load the file relative to the working dir, if that fails
            # try to load it relative to the config file parent directory
            if not os.path.isfile(self.CONF.application.static_port_desc):
                tmp_path = os.path.dirname(self.CONF.config_file[0])
                self.CONF.application.static_port_desc = os.path.join(tmp_path,
                    self.CONF.application.static_port_desc)

            self.logger.info("static_port_desc: %s" % self.CONF.application.static_port_desc)

            try:
                with open(self.CONF.application.static_port_desc) as f:
                    csv_reader = csv.DictReader(f)
                    for line in csv_reader:
                        src = int(line["dpid"])
                        port = int(line["port"])
                        speed = int(line["speed"])
                        if src not in dat:
                            dat[src] = {}
                        dat[src][port] = speed
                self.graph.fixed_speed = dat
                self.logger.info("PORT DESC DICT: %s" % self.graph.fixed_speed)
            except Exception as e:
                self.logger.error("Error occured while reading static port description")
                self.logger.error(e)


    def register_cleanup(self, method):
        """ Register a new cleanup method to execute on controller stop """
        self.__cleanup_handlers.append(method)


    def get_topo(self):
        """ Return the gurrent network topology

        Returns:
            (obj): Topology of the network
        """
        return self.graph


    def get_paths(self):
        """ Get the currently installed paths

        Returns:
            (dict): Currently installed paths dictionary
        """
        return self.paths


    def get_poll_rate(self):
        """ Get the current stats poll interval in seconds

        Returns:
            (int): Poll rate in seconds
        """
        return self.CONF.stats.interval


    def __stop_stats_timer(self):
        """ Stop any in progress stats poll interval """
        if self.__stats_timer is not None:
            self.__stats_timer.cancel()
        self.__stats_timer = None


    def __trigger_stats_timer(self):
        """ Start (or reset) the stats poll interval """
        self.__stop_stats_timer()
        self.__stats_timer = Timer(self.get_poll_rate(), self.__get_stats)
        self.__stats_timer.start()


    def __get_stats(self):
        """ Request port and flow stats for all connected switches. """
        self.__stats_timer = None
        self.logger.info("Sending stats request to connected switches")

        for sw in get_switch(self):
            dp = sw.dp
            ofp = dp.ofproto
            parser = dp.ofproto_parser
            match = parser.OFPMatch()

            # Request the port and datapath stats
            req = parser.OFPFlowStatsRequest(dp, 0, ofp.OFPTT_ALL, ofp.OFPP_ANY,
                                            ofp.OFPG_ANY, 0, 0, match)
            dp.send_msg(req)

            # Check if we have to collect port stats
            if self.CONF.stats.collect_port == True:
                req = parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY)
                dp.send_msg(req)

            self.logger.debug("Request stats from switch with DPID %s" % dp.id)

        # Reset the stats request timer to re-trigger
        self.__trigger_stats_timer()


    def __stats_signal(self, signum, stack):
        """ Stats signal handler that outputs collected statistics """
        # Create format string used to output values and output headers
        fstr = "{:^16} {:>3} {:>6} {:>6} {:>6} {:>6} {:>6} {:>6} {:>6} {:>6} {:>6}"
        self.logger.info(fstr.format("Path(src, dst)", "gid", "pkt", "bt", "t_pkt",
                                        "t_bt", "time", "pkt/s", "bt/s",
                                         "tpkt/s", "tbt/s"))
        self.logger.info(fstr.format("----------------", "---", "------", "------", "------",
                                        "------", "------", "------", "------",
                                        "------", "------"))

        # Iterate through the paths and output the stats counts
        for key,val in self.paths.iteritems():
            gid = "na" if "gid" not in val else val["gid"]

            stats = {} if "stats" not in val else val["stats"]
            total_time = "na" if "total_time" not in stats else stats["total_time"]
            pkts = "na" if "pkts" not in stats else stats["pkts"]
            bytes = "na" if "bytes" not in stats else stats["bytes"]
            total_pkts = "na" if "total_pkts" not in stats else stats["total_pkts"]
            total_bytes = "na" if "total_bytes" not in stats else stats["total_bytes"]
            pkts_persec = "na" if "pkts_persec" not in stats else stats["pkts_persec"]
            bytes_persec = "na" if "bytes_persec" not in stats else stats["bytes_persec"]
            total_pkts_persec = ("na" if "total_pkts_persec" not in stats else
                                    stats["total_pkts_persec"])
            total_bytes_persec = ("na" if "total_bytes_persec" not in stats else
                                    stats["total_bytes_persec"])

            self.logger.info(fstr.format(
                    key, gid, __hum_read(pkts), __hum_read(bytes), __hum_read(total_pkts),
                    __hum_read(total_bytes), __hum_read(total_time), __hum_read(pkts_persec),
                    __hum_read(bytes_persec), __hum_read(total_pkts_persec),
                    __hum_read(total_bytes_persec)))

        self.logger.info("")
        if self.CONF.stats.out_port == False:
            return

        # Iterate through all switches in topo and output port stats of each
        for dpid,dpid_val in self.graph.topo.iteritems():
            # Ignore showing stats for the host switches (as none exist)
            if -1 in dpid_val:
                continue

            self.logger.info("DPID: %s" % dpid)
            for pn,pn_val in dpid_val.iteritems():
                self.logger.info("\t+ PORT: %s, SPEED: %sb" % (pn, __hum_read(pn_val["speed"])))

                # If there are no poll stats don't output
                if "poll_stats" in pn_val:
                    pstV = pn_val["poll_stats"]
                    self.logger.info("\t|    tx_packets: %s, tx_bytes: %sB, tx_errors: %s" % (
                            __hum_read(pstV["tx_packets"]), __hum_read(pstV["tx_bytes"]),
                            __hum_read(pstV["tx_errors"])))
                    self.logger.info("\t|    tx_rate: %s" % (pstV["tx_rate"]))

                # If there are no total stats don't output
                if "total_stats" in pn_val:
                    pstV = pn_val["total_stats"]
                    self.logger.info("\t|    TOTAL tx_packets: %s, tx_bytes: %sB, tx_errors: %s"
                            % (__hum_read(pstV["tx_packets"]), __hum_read(pstV["tx_bytes"]),
                        __hum_read(pstV["tx_errors"])))

        # Output a new line to make things cleaner
        self.logger.info("")


    def __stop_unknown_links_timer(self):
        """ Stop the unknown links timer """
        if self.__unknown_links_timer is not None:
            self.__unknown_links_timer.cancel()
        self.__unknown_links_timer = None


    def __trigger_unknown_links_timer(self):
        """ Start the unknown links timmer for CID resolution """
        self.__stop_unknown_links_timer()
        self.__unknown_links_timer = Timer(1, self.__unknown_links_loop)
        self.__unknown_links_timer.start()


    def __unknown_links_loop(self):
        """ unknown links resolution callback. For every unresolved link, where the standown
        period is exceeded (10 timer ticks), the CID is request from the root controller.
        If no more unresolved unknown links exist, timer is stopped, otherwise its restarted
        automatically.
        """
        # Clear the timer and process the unknown links
        self.__unknown_links_timer = None
        in_progress = False

        for key in self.unknown_links:
            if isinstance(self.unknown_links[key], list):
                in_progress = True
                if self.unknown_links[key][0] < 10:
                    # If we are in a standown period just increment counter
                    self.unknown_links[key][0] += 1
                else:
                    # Resolve the unknown links CID
                    self.unknown_links[key] = [0]

                    (src_sw, src_pn, dst_sw) = key
                    src_port = self.graph.get_port_info(src_sw, src_pn)
                    speed = 0
                    if src_port is not None:
                        speed = src_port["speed"]
                    else:
                        self.logger.error("Inter-domain link %s %s has no speed!" % (src_sw, src_pn))
                        continue

                    self.ctrl_com.notify_outside_link(src_sw, src_pn, dst_sw, speed)

        # If we still have unknown links that need to be resolved reset the timer
        if in_progress:
            self.__trigger_unknown_links_timer()


    def _init_ing_change_wait(self, hkey):
        """ Initiate a lockut timer for ingress change detection to prevent triggering back and
        forth swapping due to in-flight packets that are being dequed.

        Args:
            hkey (tuple): Path pair key
        """
        timer = Timer(2, self.__exp_ing_change_wait, args=hkey)
        if self._is_ing_change_wait(hkey):
            # Stop in progress ingress change instance and restart
            self.__ing_change_detect_wait[hkey].cancel()

        self.__ing_change_detect_wait[hkey] = timer
        timer.start()


    def __exp_ing_change_wait(self, h1, h2):
        """ Callback executed by the ingress change wait timer. Remove the path from wait list.

        Args:
            h1 (str): First host in pair key
            h2 (str): Second host in pair key
        """
        hkey = (h1, h2)
        del self.__ing_change_detect_wait[hkey]
        self.logger.info("Ingress Change Wait Expired for %s-%s" % hkey)


    def __clear_ing_change_wait(self):
        """ Stop all in progress ingress change detection wait timer """
        for hkey, timer in self.__ing_change_detect_wait.items():
            timer.stop()
            del self.__ing_change_detect_wait[hkey]
        self.__ing_change_detect_wait = {}


    def _is_ing_change_wait(self, hkey):
        """ Check if the path pair is in the ingress change wait phase.

        Args:
            hkey (tuple): Host pair key of path

        Returns:
            bool: True if the path is in the wait pahse, False otherwise.
        """
        return hkey in self.__ing_change_detect_wait


    def __save_port_speed(self, dp, p):
        """ Process a port info object and extract the speed of the port """
        # Check if this is not a local port
        # XXX: OFP has a limit of local ports of OFPP_MAX, if we have
        # a port over this, we have a OFP specific port
        if p.port_no > dp.ofproto.OFPP_MAX:
            return

        # Convert the ryu speed to bits from kbits and save it
        p_speed = p.curr_speed * 1000

        # XXX FIXME: This is a dirty hack to deal with mininet links always being 10G and
        # not being able to specify TC limit of 10G (link can handle more 50G). If the link
        # is 10G then set it toa speed of 1G
        if p_speed >= 10000000000:
            p_speed = 1000000000

        self.graph.update_port_info(dp.id, p.port_no, speed=p_speed)


    def stop(self):
        """ Callback triggered on controller stop. Stop the inter ctrl com and timers """
        super(TopoDiscoveryController, self).stop()
        self.__stop_stats_timer()
        self.__stop_unknown_links_timer()
        self.__clear_ing_change_wait()

        self.ctrl_com.stop()

        self.logger.info("\n\nRunning cleanup handlers ...\n\n")
        for func in self.__cleanup_handlers:
            func()


    # ------------------------- RYU API METHODS --------------------------


    @set_ev_cls(event.EventSwitchEnter)
    @set_ev_cls(event.EventSwitchReconnected)
    def switch_enter_handler(self, ev):
        """ Handler called on switch enter/reconnect. Assign switch current
        controller role `:cls:attr:(__ctrl_role)`. If current role is master, on
        role reply, controller will automatically initiate state rebuild from
        switch.
        """
        dp = ev.switch.dp
        self.logger.info("SW %s has entered topo at %f" % (dp.id, time.time()))
        self.logger.critical("XXXEMUL,%f,sw_enter,%s" % (time.time(), dp.id))

        # Request port description of switch to get port capacity
        self._req_port_desc(dp)

        # Send current controller role to switch and apply barrier
        if not self.__ctrl_role == "unknown":
            self.__send_ctrl_role(dp, self.__ctrl_role)
            self._send_barrier(dp)


    @set_ev_cls(event.EventLinkAdd)
    def event_link_add_handler(self, ev):
        """ Handler called when a new link is added. Add the link to the topology and trigger
        ``topo_change`` if graph modified.
        """
        src_sw = ev.link.src.dpid
        dst_sw = ev.link.dst.dpid
        src_pn = ev.link.src.port_no
        dst_pn = ev.link.dst.port_no
        self.logger.info("Link added %s(%s) to %s(%s)" % (src_sw, src_pn, dst_sw, dst_pn))

        modified = False
        if self.graph.add_link(src_sw, dst_sw, src_pn, dst_pn) == True:
            modified = True
        if self.graph.add_link(dst_sw, src_sw, dst_pn, src_pn) == True:
            modified = True

        if modified == True:
            self.topo_changed()


    @set_ev_cls(event.EventLinkDelete)
    def event_link_delete_handler(self, ev):
        """ Handler called when a link is removed. Remove the link from the topology and
        trigger ``topo_change`` if graph modified. If the controller uses protection and
        optimise_protection is false, ``topo_change`` is not triggered.
        """
        src_sw = ev.link.src.dpid
        dst_sw = ev.link.dst.dpid
        src_pn = ev.link.src.port_no
        dst_pn = ev.link.dst.port_no

        self.logger.info("Link del %s(%s) to %s(%s)" % (src_sw, src_pn, dst_sw, dst_pn))

        # Remove the link that was deleted from the model
        modified = False
        if self.graph.remove_port(src_sw, dst_sw, src_pn, dst_pn):
            modified = True
        if self.graph.remove_port(dst_sw, src_sw, dst_pn, dst_pn):
            modified = True

        # Check if protection optimisation is disabled
        if self.CONTROLLER_NAME == "PROACTIVE" and self.CONF.application.optimise_protection == False:
            # XXX: We could consider unregistering the handler at this
            # point as all further requests to the link delete will result
            # in it stopping early. This may not be esential though.
            return

        # If a topo modification occured start topo timer to optimise path
        if modified == True:
            self.topo_changed()


    @set_ev_cls(event.EventHostAdd)
    def event_host_add_handler(self, ev):
        """ Handler called on new host add. Add host to the topology and store details. """
        host = ev.host
        host_name = host.name
        dst_sw = host.port.dpid
        dst_pn = host.port.port_no
        src_addr = host.ipv4[0]
        src_eth = host.mac
        self.logger.info("Host link added %s to %s(%s)" % (host_name, dst_sw, dst_pn))

        modified = False
        if self.graph.add_link(host_name, dst_sw, -1, dst_pn) == True:
            modified = True
        if self.graph.add_link(dst_sw, host_name, dst_pn, -1) == True:
            modified = True

        self.logger.debug("Host Address is IP: %s, ETH: %s" % (src_addr, src_eth))
        self.graph.update_port_info(host_name, -1, addr=src_addr, eth_addr=src_eth)

        # Append host name to list (if not exist) and trigger topo change if topo modified
        if host_name not in self.hosts:
            self.hosts.append(host_name)

        if modified == True:
            self.topo_changed()


    @set_ev_cls(event.EventInterDomLinkAdd)
    def event_inter_dom_link_add_handler(self, ev):
        """ Handler called on new inter domain link add. Notify the root controller of the link and
        initiate CID resolution for link.
        """
        src_sw = ev.link.src.dpid
        dst_sw = ev.link.dst.dpid
        src_pn = ev.link.src.port_no
        dst_pn = ev.link.dst.port_no

        self.logger.info("Inter domain link added %s(%s) to %s(%s)" % (src_sw, src_pn, dst_sw, dst_pn))

        # If the link already added, ignore the reequest
        key = (src_sw, src_pn, dst_sw)
        if key in self.unknown_links:
            return

        # Add the details of the unkown links and stop operation if not master
        self.unknown_links[key] = [0]
        if not self.is_master():
            self.logger.info("Controller is not master, supress unknown link")
            return

        # Initiate unkown links timer, get port speed and notify root controller
        if self.__unknown_links_timer is None:
            self.__trigger_unknown_links_timer()

        src_port = self.graph.get_port_info(src_sw, src_pn)
        speed = 0
        if src_port is not None:
            speed = src_port["speed"]
        else:
            return

        self.ctrl_com.notify_outside_link(src_sw, src_pn, dst_sw, speed)


    @set_ev_cls(event.EventInterDomLinkDelete)
    def event_inter_dom_link_delete_handler(self, ev):
        """ Handler called on inter domain link remove. Notify the root controller of the removed link """
        src_sw = ev.link.src.dpid
        dst_sw = ev.link.dst.dpid
        src_pn = ev.link.src.port_no
        dst_pn = ev.link.dst.port_no

        self.logger.info("Inter domain link deleted %s(%s) to %s(%s)" % (src_sw, src_pn, dst_sw, dst_pn))
        key = (src_sw, src_pn, dst_sw)
        if key not in self.unknown_links:
            return

        self.ctrl_com.notify_inter_domain_port_down(key)


    @set_ev_cls(event.EventHostDelete)
    def event_host_delete_handler(self, ev):
        """ Handler called on host delete. Remove host from topology and delete details. """
        host = ev.host
        host_name = host.name
        dst_sw = host.port.dpid
        dst_pn = host.port.port_no
        src_addr = host.ipv4[0]
        src_eth = host.mac
        self.logger.info("Host link Deleted %s to %s(%s)" % (host_name, dst_sw, dst_pn))

        del_host = self.graph.remove_host_link(dst_sw, dst_pn)
        if del_host is not None:
            if del_host in self.hosts:
                self.hosts.remove(del_host)
            self.topo_changed()


    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """ Handler called on packet in received by controller. Method implements ingress change
        detection for inter-domain paths.

        Args:
            ev (ofp_event.EventOFPPacketIn): Packet in event from the controller.
        """
        msg = ev.msg
        pkt = packet.Packet(msg.data)
        i = iter(pkt)
        eth_pkt = six.next(i)
        if not type(eth_pkt) == ethernet.ethernet:
            return

        # Is this an ingress change for a inter-domain link?
        next_pkt = six.next(i)
        if type(next_pkt) == vlan.vlan:
            vid = next_pkt.vid
            sw = msg.datapath.id
            pn = msg.match["in_port"]
            self.logger.info("INGRESS_CHANGE_DETECT_PKT")
            self._ingress_change(vid, sw, pn)
            return


    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, ev):
        """ Handler called on port status change. On status add get and save the ports speed """
        dp = ev.msg.datapath
        ofp = dp.ofproto

        # Check if port state changed to up
        if (ev.msg.reason == ofp.OFPPR_ADD or (ev.msg.reason == ofp.OFPPR_MODIFY and
                                                ev.msg.desc.state == ofp.OFPPS_LIVE)):
            self.__save_port_speed(ev.msg.datapath, ev.msg.desc)


    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        """ Handler called on flow stats reply from a switch. Calls ``_process_flow_stats``. """
        dp = ev.msg.datapath
        body = ev.msg.body
        self.logger.debug("FlowStats received from SW DPID:%s" % dp.id)
        self._process_flow_stats(dp, body)


    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        """ Handler called on port stats reply from switch. Get port stats
        and extract relevant metrics from counters. Reserved ports (number
        > OFPP_MAX) are ignored.
        """
        self.logger.debug("PortStats received from SW DPID:%s" %
                            ev.msg.datapath.id)

        for p in ev.msg.body:
            # Check if this is not a local port
            # XXX: OFP has a limit of local ports of OFPP_MAX, if we have
            # a port over this, we have a OFP specific port
            if p.port_no > ev.msg.datapath.ofproto.OFPP_MAX:
                continue

            # If port is not in topology just jump to the next one
            pInfo = self.graph.get_port_info(ev.msg.datapath.id, p.port_no)
            if pInfo is None:
                continue

            old = pInfo["total_stats"] if "total_stats" in pInfo else None

            # If we have no previous count info do not compute poll metric
            if (old is not None and
                    old["rx_packets"] is not None and
                    old["rx_bytes"] is not None and
                    old["rx_errors"] is not None and
                    old["tx_packets"] is not None and
                    old["tx_bytes"] is not None and
                    old["tx_errors"] is not None
            ):
                # Compute the stat counts and rates for the current poll
                rx_packets = p.rx_packets - old["rx_packets"]
                rx_bytes = p.rx_bytes - old["rx_bytes"]
                rx_errors = p.rx_errors - old["rx_errors"]
                tx_packets = p.tx_packets - old["tx_packets"]
                tx_bytes = p.tx_bytes - old["tx_bytes"]
                tx_errors = p.tx_errors - old["tx_errors"]

                rx_rate = None
                tx_rate = None

                if not pInfo["speed"] == 0:
                    # XXX: The (tx/rx)_bytes is in bytes while the max speed
                    # is in bits so convert (8x numerator). Compute the
                    # average per second value (account for the poll rate)
                    conv = 8.0 / self.get_poll_rate()
                    rx_rate = round(float(rx_bytes*conv)/float(pInfo["speed"]), 2)
                    tx_rate = round(float(tx_bytes*conv)/float(pInfo["speed"]), 2)

                    # Is this a inter-domain link we requested a root
                    # ctrl optimisation?
                    skip_check = False
                    key = (ev.msg.datapath.id, p.port_no)
                    if key in self.TE.inter_domain_over_util:
                        val = self.TE.inter_domain_over_util[key]
                        self.logger.info("Inter-domain link opti request still"
                                            " outstanding (count %s)" % val)
                        if val <= 0:
                            # Wait counter elapsed, allow checking if link
                            # congested
                            del self.TE.inter_domain_over_util[key]
                        else:
                            # Decrement the counter, link optimisation still
                            # in progress
                            val -= 1
                            self.TE.inter_domain_over_util[key] = val
                            skip_check = True

                    if skip_check:
                        self.logger.info("Suppressed con check for idl")
                    else:
                        # Check if the link is congested
                        self.TE.check_link_congested(
                                ev.msg.datapath.id, p.port_no, tx_rate
                        )

                    # Notify the root controller of idl traffic
                    if self.is_inter_domain_link(ev.msg.datapath.id, p.port_no):
                        self.ctrl_com.notify_inter_domain_link_traffic(
                            ev.msg.datapath.id, p.port_no, (tx_bytes * conv)
                        )

                # Update the port counts for the poll interval
                self.graph.update_port_info(ev.msg.datapath.id, p.port_no,
                            rx_packets=rx_packets, rx_bytes=rx_bytes,
                            rx_errors=rx_errors, tx_packets=tx_packets,
                            tx_bytes=tx_bytes, tx_errors=tx_errors,
                            rx_rate=rx_rate, tx_rate=tx_rate,
                            is_total=False)


            # Update the port total counters
            self.graph.update_port_info(ev.msg.datapath.id, p.port_no,
                        rx_packets=p.rx_packets, rx_bytes=p.rx_bytes,
                        rx_errors=p.rx_errors, tx_packets=p.tx_packets,
                        tx_bytes=p.tx_bytes, tx_errors=p.tx_errors,
                        is_total=True)


    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        """ Handler called on port description received from switch. Extract and save port
        speed (given in kbits) to topology. Non local ports (number > OFPP_MAX) are ingnored.
        """
        self.logger.debug("PortDesc received from SW DPID:%s" % ev.msg.datapath.id)

        for p in ev.msg.body:
            self.__save_port_speed(ev.msg.datapath, p)


    @set_ev_cls(ofp_event.EventOFPGroupDescStatsReply, MAIN_DISPATCHER)
    def group_desc_reply_handler(self, ev):
        """ Handler called on group description reply received from switch. Calls
        ``_process_group_desc`` to recover state from group entries.
        """
        self._process_group_desc(ev.msg.datapath, ev.msg.body)


    @set_ev_cls(ofp_event.EventOFPErrorMsg, MAIN_DISPATCHER)
    def error_msg_handler(self, ev):
        """ Handler called on OFP error message received from switch. Code is copied from the ryu
        module `controller/ofp_handeler.py` line 269. Code outputs any errors message received.
        Original code logged debug messages, which outputs a lot of garbage. To avoid using level
        DEBUG, message changes log severity to info.
        """
        msg = ev.msg
        ofp = msg.datapath.ofproto
        self.logger.info(
            "EventOFPErrorMsg received.\n"
            "version=%s, msg_type=%s, msg_len=%s, xid=%s\n"
            " `-- msg_type: %s",
            hex(msg.version), hex(msg.msg_type), hex(msg.msg_len),
            hex(msg.xid),
            ofp.ofp_msg_type_to_str(msg.msg_type))
        if msg.type == ofp.OFPET_EXPERIMENTER:
            self.logger.info(
                "OFPErrorExperimenterMsg(type=%s, exp_type=%s,"
                " experimenter=%s, data=b'%s')",
                hex(msg.type), hex(msg.exp_type),
                hex(msg.experimenter), utils.binary_str(msg.data))
        else:
            self.logger.info(
                "OFPErrorMsg(type=%s, code=%s, data=b'%s')\n"
                " |-- type: %s\n"
                " |-- code: %s",
                hex(msg.type), hex(msg.code), utils.binary_str(msg.data),
                ofp.ofp_error_type_to_str(msg.type),
                ofp.ofp_error_code_to_str(msg.type, msg.code))
        if msg.type == ofp.OFPET_HELLO_FAILED:
            self.logger.info(
                " `-- data: %s", msg.data.decode('ascii'))
        elif len(msg.data) >= ofp.OFP_HEADER_SIZE:
            (version, msg_type, msg_len, xid) = ofproto_parser.header(msg.data)
            self.logger.info(
                " `-- data: version=%s, msg_type=%s, msg_len=%s, xid=%s\n"
                "     `-- msg_type: %s",
                hex(version), hex(msg_type), hex(msg_len), hex(xid),
                ofp.ofp_msg_type_to_str(msg_type))
        else:
            self.logger.warning(
                "The data field sent from the switch is too short: "
                "len(msg.data) < OFP_HEADER_SIZE\n"
                "The OpenFlow Spec says that the data field should contain "
                "at least 64 bytes of the failed request.\n"
                "Please check the settings or implementation of your switch.")


    @set_ev_cls(ofp_event.EventOFPRoleReply, MAIN_DISPATCHER)
    def role_reply_handler(self, ev):
        """ Handler called on a role change reply from a switch. If the switch
        role is master, initiate state rebuild for the switch by calling
        ``_request_sw_state``.
        """
        dp = ev.msg.datapath
        ofp = dp.ofproto

        role = ""
        if ev.msg.role == ofp.OFPCR_ROLE_MASTER:
            role = "master"

            # If swith role was set to master, request its current state
            self._request_sw_state(dp)
        if ev.msg.role == ofp.OFPCR_ROLE_EQUAL:
            role = "equal"
        elif ev.msg.role == ofp.OFPCR_ROLE_MASTER:
            role = "master"
        elif ev.msg.role == ofp.OFPCR_ROLE_SLAVE:
            role = "slave"

        self.logger.info('OFPRoleReply received: role=%s gen_id=%d dpid=%s',
                          role, ev.msg.generation_id, dp.id)


    # -------------------------- HELPER METHODS --------------------------


    def _get_gid(self, host_1, host_2):
        """ Compute a unique GID for a host pair. Method calls the static ``get_gid``
        with an approrpriate number of host value.

        Args:
            host_1 (str): First host name
            host_2 (str): Second host name

        Returns:
            int: GID for host pair
        """
        n = 64
        return TopoDiscoveryController.get_gid(host_1, host_2, n)


    def _get_reverse_gid(self, gid):
        """ Compute the host pair for a GID. Method calls the static ``get_reverse_gid``.

        Args:
            gid (int): GID to recover switch pair of

        Returns:
            (str, str): Host pair if GID is valid or None.
        """
        n = 64
        return TopoDiscoveryController.get_reverse_gid(gid, n)


    def _rebuild_state_in_progress(self):
        """ Check if a state rebuild operation is in progress.

        Retruns:
            bool: True if operation in progress, False otherwise
        """
        if self.__rebuild_state_timeout != 0:
            return True
        return False


    def _rebuild_state_tick(self):
        """ Decrement the state rebuild timeout timer. Once the value reaches 0
        the rebuild state operation is automatically stopped and rules for any
        non resposive switches will be cleared to prevent errors.
        """
        self.__rebuild_state_timeout -= 1
        self.logger.info("Rebuild state tick %d" % self.__rebuild_state_timeout)
        if self.__rebuild_state_timeout == 0:
            self.logger.info("Rebuild state timed out")


    def _proc_sw_state(self, dpid, type):
        """ Indicate that the state `type` for a switch with id `dpid` has been processed.
        Method modifies the stats flags from ``:cls:attr:(__rebuild_state_sw)`` to
        indicate processed state. When all switch state was restored switch is removed
        from dictionary. When the dictionary is empty, the rebuild state operation
        is terminated.

        Args:
            dpid (int): ID of the switch
            type (str): Recovered state type (flow, gp ...).
        """
        if dpid in self.__rebuild_state_sw:
            if type in self.__rebuild_state_sw[dpid]:
                self.__rebuild_state_sw[dpid][type] = True

                # Check if we can delete sw (all true)
                all_true = True
                for k,v in self.__rebuild_state_sw[dpid].iteritems():
                    if v == False:
                        all_true = False
                        break

                if all_true:
                    del self.__rebuild_state_sw[dpid]

            # Check if entire state was processed
            if len(self.__rebuild_state_sw) == 0:
                self.__rebuild_state_timeout = 0


    def _add_flow(self, dp, match, actions, priority=0, table_id=0, extra_inst=[]):
        """ Install a flow rule onto a switch `dp` that uses the match `match` and
        performs the set of actions `actions` with priority `priority`.

        Args:
            dp (controller.datapath): Datapath of switch
            match (OFPMatch): Match instruction of flow rule
            actions (list of OFPAction): Actions to perform on `match` of packets
            priority (int, optional): Flow rule priority. Defaults to 0.
            table_id (int, optional): ID of the table to install the rule. Defaults to 0.
            extra_inst (list): Extra instructions to add to the rule after an aply action
                generated from `actions`.
        """
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        inst = OFP_Helper.apply(dp, actions)
        inst.extend(extra_inst)
        req = parser.OFPFlowMod(datapath=dp, command=ofp.OFPFC_ADD,
            table_id=table_id, priority=priority, match=match, instructions=inst)
        dp.send_msg(req)


    def _del_flow(self, dp, match, out_port=None, out_group=None, tableID=None):
        """ Remove a flow rule on switch `dp` from table `tableID` that contains a match
        `match`, outputs on `out_port` or outputs to group `out_group`. To remove all
        flow rules set `match` to None and leave args as default.

        Note:
            Leaving `out_port`, `out_group`, `tableID` to None (default) will overwrite
            the attributes to OFPP_ANY, OFPG_ANY and OFPTT_ALL respectively. This will
            match any rules from all tables.

        Args:
            dp (controller.datapath): Datapath of switch
            match (OFPMatch): Match instruction of rule to remove
            out_port (int): Output port criteria of rule to remove. Defaults to None.
            out_group (int): Output group criteria of rule to remove. Defaults to None.
            tableID (int): Table number to remove rules. Defaults to None.
        """
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        # Set the default attributes value
        if out_port is None:
            out_port = ofp.OFPP_ANY
        if out_group is None:
            out_group = ofp.OFPG_ANY
        if tableID is None:
            tableID = ofp.OFPTT_ALL

        req = parser.OFPFlowMod(datapath=dp, command=ofp.OFPFC_DELETE,
                                table_id=tableID, match=match, out_port=out_port,
                                out_group=out_group)
        dp.send_msg(req)


    def _add_group(self, dp, groupID, actions, modify=False):
        """ Install a fast failover (OFPGT_FF) group with ID `groupID` on switch `dp`
        that contains action buckets `actions`.

        Args:
            dp (controller.datapath): Datapath of switch
            groupID (int): ID of group
            actions (list of tuples): Bucket of group (<watch port>, [OFPActions])
            modify (bool): Is operation add (true) or a modify (false). Defaults add.
        """
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        buckets = []
        for gp in actions:
            buckets.append(parser.OFPBucket(watch_port=gp[0], actions=gp[1]))

        command = ofp.OFPGC_ADD
        if modify:
            command = ofp.OFPGC_MODIFY

        self.logger.debug("GROUP EDIT: sw=%s modify=%s" % (dp.id, modify))
        req = parser.OFPGroupMod(datapath=dp, command=command,
                    type_=ofp.OFPGT_FF, group_id=groupID, buckets=buckets)

        dp.send_msg(req)


    def _del_group(self, dp, groupID):
        """ Remove a group from switch `dp` with id `groupID`. To delete all groups set
        `groupID` to ofproto.OFPG_ALL.

        Args:
            dp (controller.datapath): Datapath of switch
            groupID (int): ID of group to remove.
        """
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        req = parser.OFPGroupMod(datapath=dp, command=ofp.OFPGC_DELETE, group_id=groupID)
        dp.send_msg(req)


    def _add_meter(self, dp, mid, pps):
        """ Add a meter to switch `dp` with ID `mid` that limits traffic to `pps`
        packets per second.

        Args:
            dp(controller.datapath): Datapath of switch
            mid (int): ID of meter
            pps (int): Packet per second limit of meter
        """
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        req = parser.OFPMeterMod(datapath=dp, command=ofp.OFPFC_ADD, meter_id=mid,
                flags=ofp.OFPMF_PKTPS, bands=[parser.OFPMeterBandDrop(rate=pps)])
        dp.send_msg(req)


    def _del_meter(self, dp, mid):
        """ Remove a meter with ID `mid` installed on switch `dp`. To remove all meters set
        `mid` to OFPM_ALL.

        Args:
            dp (controller.datapath): Datapath of switch
            mid (int): ID of the meter to remove
        """
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        req = parser.OFPMeterMod(datapath=dp, command=ofp.OFPMC_DELETE, flags=0, meter_id=mid)
        dp.send_msg(req)


    def _send_barrier(self, dp):
        """ Send a barrier to switch `dp` to enforce command processing order.

        Args:
            dp (controller.datapath): Datapath of switch
        """
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        req = parser.OFPBarrierRequest(dp)
        dp.send_msg(req)


    def _clear_rules(self):
        """ Clear the flow, group and meter tables fror all connected switches. Calls
        ``_clear_rule`` with the switch dp.
        """
        for dp in get_switch(self, dpid=None):
            dp = dp.dp
            self._clear_rules(dp)


    def _clear_rules(self, dp):
        """ Clear the flow, grup and meter tables for a switch with dp `dp` and re-install
        the LLDP discovery rule on that switch. Triggers ``topo_change`` automatically.

        Args:
            dp (controller.datapath): Datapath of switch to clear rules
        """
        ofp = dp.ofproto
        self.logger.info("Removing flows, group and meters of switch %s" % dp.id)

        self._del_flow(dp, None)
        self._del_group(dp, ofp.OFPG_ALL)
        self._del_meter(dp, ofp.OFPM_ALL)

        # XXX: The default LLDP install rule happens on EventOFPStateChange, which
        # should occur after EventOFPSwitchFeatures. Occasionally the clear is recived
        # by the switch after the default LLDP rule is installed. We send a basrrier to
        # force the clear to be executed and then we re-install the LLDP rule (issue #47),
        # resolving the issue.
        self._send_barrier(dp)
        self._install_LLDP_discovery(dp)
        self.topo_changed()


    def _install_LLDP_discovery(self, dp):
        """ Install the special topology dection LLDP discovery rule on switch `dp`.
        The rule matches LLDP packets and sends them to the controller via packet in.

        Args:
            dp (controller.datapath): Datapath of switch
        """
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        # Retrieve the match and actions from the OFP helper methods
        match = OFP_Helper.lldp_discovery_match(dp)
        actions = OFP_Helper.lldp_discovery_action(dp)

        # Generate the rule and send it to the switch
        inst = OFP_Helper.apply(dp, actions)
        req = parser.OFPFlowMod(datapath=dp, match=match, idle_timeout=0, hard_timeout=0,
                    instructions=inst, priority=0xFFFF)
        dp.send_msg(req)


    def _install_arp_fix_rule(self, dp):
        """ Install the special ARP fix rule on switch `dp` to force the switch to respond
        to ARP packets, without needing to flood or send them across the network. This is
        a hack that tricks a switch into thinking it has connectivity to the other hosts.

        Args:
            dp (controller.datapath): Datapath of switch
        """
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        # Retrieve the match and actions from the OFP helper methods
        match = OFP_Helper.match(dp, arp=True)
        actions = OFP_Helper.arp_fix_action(dp)

        # Generate the rule and send it to the switch
        inst = OFP_Helper.apply(dp, actions)
        req = parser.OFPFlowMod(datapath=dp, match=match, idle_timeout=0, hard_timeout=0,
                    instructions=inst, priority=0)
        dp.send_msg(req)


    def _req_port_desc(self, dp):
        """ Request port descriptions for the switch `dp`.

        Args:
            dp (controller.datapath): Datapath of switch to request port descriptions
        """
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        req = parser.OFPPortDescStatsRequest(dp, 0)
        dp.send_msg(req)


    def _request_sw_state(self, dp):
        """ Rebuild the current state of a switch by requesting the flow and
        group tables of the device. Method will reset the state rebuild
        timeout (wait up to n-seconds to retrieve state of switch)
        `:cls:attr:(__rebuild_state_timeout)` and adds the detauls of the
        switch to the rebuild dictionary `:cls:attr:(__rebuild_state_sw)`.

        TODO: WORK OUT A WAY TO TRIGGER RECOMPUTE ON RECOVER STATE OF SWITCH
        IF PATH RECOMPUTE IS NOT ALREADY IN PROGRESS ...

        Args:
            dp (controller.datapath): Datapath of switch
        """
        self.logger.info("Requesting state of DPID: %s" % dp.id)

        # If a request for the state of the switch is already in progress
        # do not request again.
        if dp.id in self.__rebuild_state_sw:
            self.logger.info("Already waiting for sate of sw %" % dp.id)
            return

        self.__rebuild_state_sw[dp.id] = {"flow": False, "gp": False}
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        match = parser.OFPMatch()

        # Initiate or reset the state rebuild time-out
        self.__rebuild_state_timeout = 2

        # Request the Flow stats, no other way to get OFP rules :-(
        # XXX TODO: Is this actually true
        req = parser.OFPFlowStatsRequest(dp, 0, ofp.OFPTT_ALL, ofp.OFPP_ANY,
                                        ofp.OFPG_ANY, 0, 0, match)
        dp.send_msg(req)

        # Request group descriptions and meter descriptions
        req = parser.OFPGroupDescStatsRequest(dp, 0)
        dp.send_msg(req)

        # Is this one actually necessary ???
        #req = parser.OFPOFPMeterConfigStatsRequest(dp, 0, ofp.OFPM_ALL)
        #dp.send_msg(req)


    def __send_ctrl_role(self, dp, role=None, generation_id=0):
        """ Change the controller role to `role` for switch `dp`. The generation ID should
        be incremented for every role change request to enforce role change order.

        Args:
            dp (controller.datapath): Datapath of switch
            role (str): Role of controller (master, slave, equal). Defaults to None (request
                current role).
            generation_id (int): ID of the request message
        """
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        # Convert the role to a OFP attribute
        if role == "master":
            role = ofp.OFPCR_ROLE_MASTER
        elif role == "slave":
            role = ofp.OFPCR_ROLE_SLAVE
        elif role == "equal":
            role = ofp.OFPCR_ROLE_EQUAL
        else:
            role = ofp.OFPCR_ROLE_NOCHANGE

        req = parser.OFPRoleRequest(dp, role, generation_id)
        dp.send_msg(req)


    def promote_master(self):
        """ For every switch promote the controller to master """
        if self.__ctrl_role == "master":
            return

        self.logger.info("Promoting controller to master role")
        self.__ctrl_role = "master"

        for sw in get_switch(self):
            dp = sw.dp
            self.__send_ctrl_role(dp, "master")
            self._send_barrier(dp)

        # Initiate the state rebuild timeout and resume topo discovery
        self.__rebuild_state_timeout = 2
        resume_topo_discovery(self)

        # If configured to do so re-start collecting stats
        if self.CONF.stats.collect == True:
            self.logger.info("Restart stats timmer")
            self.__trigger_stats_timer()

        # Trigger any outstanding unkown links resolution
        found_unknown = False
        for key in self.unknown_links:
            if isinstance(self.unknown_links[key], list):
                found_unknown = True
                self.unknown_links[key] = [100]
        if found_unknown:
            self.__unknown_links_loop()


    def demote_slave(self):
        """ For every switch demote the controller to slave """
        if self.__ctrl_role == "slave":
            return

        self.logger.info("Demoting controller to slave role")
        self.__ctrl_role = "slave"

        # Stop stats collection, pause topo discovery and update role
        self.__stop_stats_timer()
        pause_topo_discovery(self)

        for sw in get_switch(self):
            dp = sw.dp
            self.__send_ctrl_role(dp, "slave")
            self._send_barrier(dp)


    def is_master(self):
        """ Check if the controller role is mater.

        Returns:
            bool: True if controller is master, False otherwise
        """
        if self.__ctrl_role == "master":
            return True
        else:
            return False


    def is_inter_domain_link(self, sw, port):
        """ Check if the link represented by switch `sw` and output port `port` connects
        to another domain, i.e. exists in `:cls:attr:(unknown_links)`. and has a CID.

        Args:
            sw (int): ID of the switch
            port (int): Port of the link on `sw`.

        Returns:
            bool: True if this is an inter-domain link, False otherwise.
        """
        for key,cid in self.unknown_links.iteritems():
            if (isinstance(cid, list) == False and key[0] == sw and key[1] == port):
                return True
        return False


    # -------------------------- STATIC METHODS ---------------------------


    @staticmethod
    def get_gid(host_1, host_2, n=64):
        """ Compute a unique ID for two host pairs by extracting the number part of the
        name and using the formula ((h1 - 1) * (n - 1)) + dh2 where h1 and h2 are the
        two host numbers, n is the total number of hosts in topo and dh2 = (h2 - 1) iff
        h2 > h1 else dh2 = h2.

        TODO FIXME:
            Our dependency on the number of hosts n may not be a good idea as this will mean
            that if a new host connets at a later date all the computed GIDs will be
            invalid and need to be re-computed. We can remove n from the equation
            completly and simply opt for a h1*h2 scheme which may cause some gaps but there
            should be no confilcs assuming unique host name numbers. The problem then is that
            for example, 1*2 is = 2*1 in which case they should be different.

        Args:
            host_1 (str): First host name
            host_2 (str): Second host name
            n (int): Number of hosts

        Returns:
            int: GID of hosts computed using formula.
        """
        # Extract the numbers list and validate we have at-lest a single digit
        h1_nums = [int(a) for a in re.findall("\d+", host_1)]
        h2_nums = [int(a) for a in re.findall("\d+", host_2)]
        if len(h1_nums) == 0 or len(h2_nums) == 0:
            return -1

        # Get the digits and compute the GID
        h1 = h1_nums[0]
        h2 = h2_nums[0]

        # Compute the GID
        gid = ((h1 - 1) * (n - 1))
        dh2 = h2
        if h2 > h1:
            dh2 = h2 - 1
        gid += dh2

        return gid


    @staticmethod
    def get_reverse_gid(gid, n=64):
        """ Retrieved a tuple of hosts from a GID. The method uses `__GID_MAP__` to store
        all host mappings for all possible GID values (up to `n` x `n`). The dictionary
        is only computed once.

        TODO FIXME: See ``get_gid``, same problem can occur here.

        Args:
            gid (int): GID to return host pair for
            n (int): max number of hosts (from the gid equation). Defaults 64.

        Returns:
            tuple (str, str): Host pair for the GID or None if can't be found.
        """
        global __GID_MAP__
        # If the map is empty compute the map up to n x n hosts.
        if len(__GID_MAP__) == 0:
            for i in range(n):
                for q in range(n):
                    if i == q:
                        continue
                    h1 = "h%d" % (i+1)
                    h2 = "h%d" % (q+1)
                    comp_gid = TopoDiscoveryController.get_gid(h1, h2, n)
                    __GID_MAP__[comp_gid] = (h1, h2)

        # If the GID entry exists return the tuple otherwise return null
        if gid not in __GID_MAP__:
            return None
        else:
            return __GID_MAP__[gid]


    # -------------------------- ABSTRACT METHODS --------------------------


    def topo_changed(self):
        """ Triggered by a modification to `:attr:cls:(graph)` (topology change). Should
        initiate a path re-computation.
        """
        raise NotImplementedError


    def _process_flow_stats(self, dp, body):
        """ Iterate and process flow stats `body` received from switch `dp` to extract
        relevant information.

        Args:
            dp (controller.datapath): Datapath of switch
            body (List of OFPFlowStats): List of stats reply data
        """
        raise NotImplementedError


    def _ingress_change(self, vid, sw, pn):
        """ Detected an ingress change for path with ID `vid` on switch `sw` to port `pn`.

        Args:
            vid (int): GID or VLAN id of path
            sw (int): Switch where ingress change was detected
            pn (int): New ingress port (where packets moved to).
        """
        raise NotImplementedError


    def _process_flow_desc(self, dp, body):
        """ Iterate and process flow descriptions `body` received from switch `dp` to
        rebuild the state of the controller. OF V1.3 dosen't have a flow description
        command so flow state is retrieved from stats requests. This method should be
        implemented in the child class!

        Args:
            dp (controller.datapath): Datapath of switch
            body (List of OFPFlowStats): List of flow stats reply
        """
        raise NotImplementedError


    def _process_group_desc(self, dp, body):
        """ Iterate and process group descriptions `body` received from switch `dp` to
        rebuild the state of the controller.

        Args:
            dp (controller.datapath): Datapath of switch
            body (List of OFPGroupDescStats): List of group description state
        """
        raise NotImplementedError


def __hum_read(val):
    """ Convert a large number to a human readable string. The result will use SI prefixes
    to make the value more legible. Currently supports from 1000 (kilo) to 1000^8 (yotta)
    with a granularity of 1000.

    Args:
        val (int, float): Value to convert

    Returns:
        str: Human readable string with a metric prefix added to the end or `val`
            converted to a string if type is not int or float.
    """
    # If the value is not a number just return the string representation
    if not isinstance(val, (int, float)):
        return "%s" % val


    # Array of metric prefixes (each value is 1000 times the other)
    metricPrefix = [
        "k", "M", "G", "T", "P", "E", "Z", "Y"
    ]

    index = -1
    check_val = 1000

    # Find the largest metric prefix divisor
    while val >= check_val:
        index += 1
        check_val *= 1000

    if index == -1:
        # No metric can be applied just return the string of the value
        return "%s" % val
    else:
        # Adjust the check_val to the correct divisor
        check_val /= 1000

        # Compute the metriced value and convert to a string (show only 1 dp)
        adjVal = float(val) / float(check_val)
        valStr = str(adjVal)
        valStr = "%s.%s" % (valStr.split(".")[0], valStr.split(".")[1][0])

        # Return the human readable value
        return "%s%s" % (valStr, metricPrefix[index])
